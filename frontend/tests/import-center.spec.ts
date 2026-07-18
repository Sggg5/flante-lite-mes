import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'

import ImportCenterView from '../src/views/ImportCenterView.vue'
import { useAuthStore } from '../src/stores/auth'
import {
  WIZARD_STEPS, batchCanBeConfirmed, hasImportPermission,
  mappingColumnsAreUnique, previewRowClass,
} from '../src/views/import-workflow'
import type { ImportBatch, PreviewRow } from '../src/api/imports'

vi.mock('../src/api/imports', async (importOriginal) => {
  const original = await importOriginal<typeof import('../src/api/imports')>()
  return {
    ...original,
    listImports: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 }),
    listImportIssues: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    listImportAuditLogs: vi.fn().mockResolvedValue({ items: [] }),
    listWeeklyPlanStaging: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    searchProductCandidates: vi.fn().mockResolvedValue({ items: [] }),
  }
})

function batch(overrides: Partial<ImportBatch> = {}): ImportBatch {
  return {
    id: 1, batch_no: 'IMP-DEMO-001', import_type: 'INVENTORY', original_filename: 'synthetic.xlsx',
    file_sha256: 'a'.repeat(64), file_size: 100, workbook_sheet_count: 1, selected_sheet_name: '数据',
    status: 'READY', total_rows: 1, valid_rows: 1, warning_rows: 0, error_rows: 0, imported_rows: 0,
    field_mapping: { product_code: 1 }, import_options: {}, error_summary: {}, created_by_name: '测试用户',
    created_at: '2026-07-18T00:00:00Z', confirmed_at: null, cancel_reason: null, ...overrides,
  }
}

describe('Excel import center', () => {
  it('defines the complete wizard including weekly plan matching', () => {
    expect(WIZARD_STEPS).toEqual(['选择导入类型', '上传文件', '选择工作表', '字段匹配', '数据预览', '校验结果', '确认导入', '周计划待匹配', '导入结果'])
  })

  it('rejects conflicting field mappings', () => {
    expect(mappingColumnsAreUnique({ product_code: 1, product_name: 2 })).toBe(true)
    expect(mappingColumnsAreUnique({ product_code: 1, product_name: 1 })).toBe(false)
  })

  it('marks preview error and warning rows with distinct classes', () => {
    const error = { severity: 'ERROR' } as PreviewRow
    const warning = { severity: 'WARNING' } as PreviewRow
    expect(previewRowClass(error)).toBe('preview-error')
    expect(previewRowClass(warning)).toBe('preview-warning')
  })

  it('only permits confirmation for ready batches without errors', () => {
    expect(batchCanBeConfirmed(batch())).toBe(true)
    expect(batchCanBeConfirmed(batch({ error_rows: 1 }))).toBe(false)
    expect(batchCanBeConfirmed(batch({ status: 'ANALYZED' }))).toBe(false)
  })

  it('applies backend-aligned import permission checks', () => {
    expect(hasImportPermission(['import.view'], 'import.view')).toBe(true)
    expect(hasImportPermission(['import.view'], 'import.confirm')).toBe(false)
  })

  it('renders the batch list and hides upload for a read-only user', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const auth = useAuthStore()
    auth.user = { id: 2, username: 'viewer', display_name: '只读用户', roles: ['VIEWER'], permissions: ['import.view'] }
    const wrapper = mount(ImportCenterView, { global: { plugins: [pinia, ElementPlus] } })
    await Promise.resolve()
    expect(wrapper.text()).toContain('Excel 数据导入中心')
    expect(wrapper.find('[data-testid="batch-list"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="new-import"]').exists()).toBe(false)
  })
})

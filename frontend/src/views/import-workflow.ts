import type { ImportBatch, PreviewRow } from '../api/imports'

export const WIZARD_STEPS = ['选择导入类型', '上传文件', '选择工作表', '字段匹配', '数据预览', '校验结果', '确认导入', '周计划待匹配', '导入结果']

export function mappingColumnsAreUnique(mapping: Record<string, number>) {
  const columns = Object.values(mapping)
  return columns.every((column) => column > 0) && new Set(columns).size === columns.length
}

export function previewRowClass(row: PreviewRow) {
  return `preview-${row.severity.toLowerCase()}`
}

export function batchCanBeConfirmed(batch: ImportBatch | null) {
  return Boolean(batch && batch.status === 'READY' && batch.error_rows === 0)
}

export function hasImportPermission(permissions: string[], permission: string) {
  return permissions.includes(permission)
}

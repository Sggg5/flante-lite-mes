import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import http from '../src/api/http'
import { approveRun, bulkReviewSuggestions, calculateRun, cancelProductionDemand, convertSuggestions, getReplenishmentRun, getSuggestion, listRunIssues, listRuns, listSuggestions, resolveRunIssue, reviewSuggestion, updateScheduledOverride, type ReplenishmentIssue, REPLENISHMENT_REQUEST_TIMEOUT_MS } from '../src/api/replenishment'
import { useAuthStore } from '../src/stores/auth'
import ProductionDemandView from '../src/views/ProductionDemandView.vue'
import ReplenishmentView from '../src/views/ReplenishmentView.vue'
import { canConvertSuggestion, issueActionMode, REPLENISHMENT_WIZARD_STEPS, weightsAreValid } from '../src/views/replenishment-workflow'

vi.mock('../src/api/replenishment', async (importOriginal) => {
  const original = await importOriginal<typeof import('../src/api/replenishment')>()
  return {
    ...original,
    listRuns: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    listSuggestions: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    listRunIssues: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    getSuggestion: vi.fn(),
    listProductionDemands: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    getReplenishmentRun: vi.fn(),
  }
})

describe('phase 3 replenishment UI', () => {
  it('defines all twelve guarded wizard steps', () => {
    expect(REPLENISHMENT_WIZARD_STEPS).toHaveLength(12)
    expect(REPLENISHMENT_WIZARD_STEPS).toContain('校验数据日期')
    expect(REPLENISHMENT_WIZARD_STEPS).toContain('显示完整性问题')
  })

  it('keeps all five required source batches before the optional weekly plan', () => {
    expect(REPLENISHMENT_WIZARD_STEPS.slice(1, 7)).toEqual([
      '选择销售批次', '选择库存批次', '选择水管在制', '选择管件在制', '选择常规产品', '选择周计划',
    ])
  })

  it('uses the ten minute timeout for replenishment calculation', async () => {
    expect(REPLENISHMENT_REQUEST_TIMEOUT_MS).toBe(600_000)
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: { id: 9, status: 'READY_FOR_REVIEW' } })
    await calculateRun(9)
    expect(post).toHaveBeenCalledWith('/v1/replenishment/runs/9/calculate', {
      override_blocking_checks: false, override_reason: undefined,
    }, { timeout: 600_000 })
    post.mockRestore()
  })

  it('only converts approved positive suggestions', () => {
    expect(canConvertSuggestion('ACCEPTED', '1')).toBe(true)
    expect(canConvertSuggestion('ADJUSTED', '0')).toBe(false)
    expect(canConvertSuggestion('PENDING', '10')).toBe(false)
  })

  it('validates six non-negative weights summing to one', () => {
    expect(weightsAreValid('0.05,0.05,0.10,0.15,0.25,0.40')).toBe(true)
    expect(weightsAreValid('1,1,1,1,1,1')).toBe(false)
    expect(weightsAreValid('0.5,-0.1,0.1,0.1,0.2,0.2')).toBe(false)
  })

  it('sends explicit manual confirmation quantity and reason', async () => {
    const patch = vi.spyOn(http, 'patch').mockResolvedValue({ data: {} })
    await reviewSuggestion(7, 'APPROVE', '450', '现场库存调整')
    expect(patch).toHaveBeenCalledWith('/v1/replenishment/suggestions/7', { action: 'APPROVE', confirmed_qty: '450', reason: '现场库存调整' })
    patch.mockRestore()
  })

  it('sends batch acceptance with selected suggestion ids', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: {} })
    await bulkReviewSuggestions([1, 2], 'APPROVE', '批量接受')
    expect(post).toHaveBeenCalledWith('/v1/replenishment/suggestions/bulk-review', { suggestion_ids: [1, 2], action: 'APPROVE', reason: '批量接受' })
    post.mockRestore()
  })

  it('sends issue resolution with an auditable reason', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: {} })
    await resolveRunIssue(3, 8, 'RESOLVE', '已核对源数据')
    expect(post).toHaveBeenCalledWith('/v1/replenishment/runs/3/issues/8', { action: 'RESOLVE', reason: '已核对源数据' })
    post.mockRestore()
  })

  it('uses the dedicated scheduled override endpoint and excludes it from generic resolution', async () => {
    expect(issueActionMode('SCHEDULED_ACTUAL_UNKNOWN', 'BLOCKING')).toBe('SCHEDULED_OVERRIDE')
    expect(issueActionMode('INVENTORY_SNAPSHOT_MISSING', 'BLOCKING')).toBe('NONE')
    expect(issueActionMode('NEGATIVE_WIP_CLAMPED', 'WARNING')).toBe('ACKNOWLEDGE')
    const put = vi.spyOn(http, 'put').mockResolvedValue({ data: { id: 7 } })
    await updateScheduledOverride(7, '150', '现场确认未知实际量')
    expect(put).toHaveBeenCalledWith('/v1/replenishment/suggestions/7/scheduled-override', {
      scheduled_override_qty: '150', reason: '现场确认未知实际量',
    })
    put.mockRestore()
  })

  it('uses a distinct run approval action before conversion', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: {} })
    await approveRun(3, '审核完成')
    expect(post).toHaveBeenCalledWith('/v1/replenishment/runs/3/approve', { reason: '审核完成', allow_no_replenishment: false })
    post.mockRestore()
  })

  it('uses the long timeout and id list for demand conversion', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: {} })
    await convertSuggestions(3, [8, 9], '转需求')
    expect(post).toHaveBeenCalledWith('/v1/replenishment/runs/3/convert', { suggestion_ids: [8, 9], reason: '转需求' }, { timeout: 600_000 })
    post.mockRestore()
  })

  it('cancels an unallocated demand with a reason', async () => {
    const post = vi.spyOn(http, 'post').mockResolvedValue({ data: {} })
    await cancelProductionDemand(11, '业务取消')
    expect(post).toHaveBeenCalledWith('/v1/production-demands/11/cancel', { reason: '业务取消' })
    post.mockRestore()
  })

  it('renders replenishment center and hides mutations for viewer', async () => {
    const pinia = createPinia(); setActivePinia(pinia)
    useAuthStore().user = { id: 2, username: 'viewer', display_name: '只读', roles: ['VIEWER'], permissions: ['replenishment.view'] }
    const wrapper = mount(ReplenishmentView, { global: { plugins: [pinia, ElementPlus] } })
    await Promise.resolve()
    expect(wrapper.text()).toContain('补库计算与建议中心')
    expect(wrapper.text()).not.toContain('新建补库计算')
  })

  it('renders a dedicated unknown-actual override action without generic resolve or ignore', async () => {
    const run = { id: 3, run_no: 'RR-VIRTUAL', calculation_date: '2026-07-15', status: 'READY_FOR_REVIEW' }
    const suggestion = {
      id: 7, run_id: 3, product_id: 9, product_code: 'VIRTUAL-00009', product_name: '虚拟产品',
      specification: 'VIRTUAL-SPEC', monthly_shipments: {}, scheduled_known_qty: '100',
      scheduled_override_qty: '0', scheduled_not_started_qty: '100', system_suggested_qty: '500',
      confirmed_qty: null, review_status: 'PENDING',
    }
    const issue: ReplenishmentIssue = { id: 8, run_id: 3, suggestion_id: 7, issue_code: 'SCHEDULED_ACTUAL_UNKNOWN', severity: 'BLOCKING', message: '实际量未知', status: 'OPEN', product_id: 9, details: null }
    vi.mocked(listRuns).mockResolvedValueOnce({ items: [run] as never[], total: 1 })
    vi.mocked(getReplenishmentRun).mockResolvedValue({ ...run, order_inputs: [], audit_logs: [] } as never)
    vi.mocked(listSuggestions).mockResolvedValue({ items: [suggestion] as never[], total: 1 })
    vi.mocked(listRunIssues).mockResolvedValue({ items: [issue], total: 1 })
    vi.mocked(getSuggestion).mockResolvedValue({ ...suggestion, issues: [issue] } as never)
    const pinia = createPinia(); setActivePinia(pinia)
    useAuthStore().user = { id: 2, username: 'planner', display_name: '计划员', roles: ['PLANNER'], permissions: ['replenishment.view', 'replenishment.review'] }
    const wrapper = mount(ReplenishmentView, { attachTo: document.body, global: { plugins: [pinia, ElementPlus] } })
    await flushPromises()
    const firstRow = wrapper.find('.el-table__body-wrapper tbody tr')
    expect(firstRow.exists()).toBe(true)
    await firstRow.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('填写已排覆盖')
    expect(wrapper.text()).not.toContain('解决忽略')
    const button = wrapper.findAll('button').find(item => item.text().includes('填写已排覆盖'))
    await button?.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('周计划实际量未知')
    expect(document.body.textContent).toContain('已知已排未开工')
    wrapper.unmount()
  })

  it('renders minimal demand pool without scheduling controls', async () => {
    const pinia = createPinia(); setActivePinia(pinia)
    useAuthStore().user = { id: 2, username: 'viewer', display_name: '只读', roles: ['VIEWER'], permissions: ['demand.view'] }
    const wrapper = mount(ProductionDemandView, { global: { plugins: [pinia, ElementPlus] } })
    await Promise.resolve()
    expect(wrapper.text()).toContain('生产需求池')
    expect(wrapper.text()).toContain('不创建排产任务')
  })
})


import axios from 'axios'

import http from './http'

export const REPLENISHMENT_REQUEST_TIMEOUT_MS = 600_000

export interface ReplenishmentRun {
  id: number; run_no: string; calculation_date: string; status: string; default_algorithm: string
  shipment_batch_id: number; inventory_batch_id: number; pipe_wip_batch_id: number
  fitting_wip_batch_id: number; regular_product_batch_id: number; weekly_plan_batch_id: number | null
  total_products: number; suggestion_count: number; positive_suggestion_count: number
  pending_review_count: number; blocking_issue_count: number; warning_issue_count: number
  warning_count: number; approved_count: number; converted_count: number; created_by: number
  source_date_summary: Record<string, string | null>; created_at: string
}

export interface ReplenishmentSuggestion {
  id: number; run_id: number; product_id: number; product_code: string; product_name: string | null
  specification: string | null; category: string | null; unit: string | null
  algorithm: string; monthly_shipments: Record<string, string>
  calculated_target_qty: string; target_stock_qty: string; on_hand_qty: string
  expected_inbound_qty: string; expected_outbound_qty: string; available_qty: string
  pipe_wip_raw_qty: string; pipe_wip_effective_qty: string
  fitting_wip_raw_qty: string; fitting_wip_effective_qty: string; scheduled_not_started_qty: string
  scheduled_known_qty: string; scheduled_override_qty: string
  system_suggested_qty: string; confirmed_qty: string | null; review_status: string
}

export interface ProductionDemand {
  id: number; demand_no: string; product_code: string; product_name: string | null
  specification: string | null; unit: string | null; source_run_no: string; source_suggestion_id: number
  confirmed_qty: string; active_allocated_qty: string; qualified_completed_qty: string
  remaining_to_schedule_qty: string; remaining_to_complete_qty: string; priority: number
  required_date: string | null; status: string; created_at: string
}

export interface SourceBatch { id: number; batch_no: string; import_type: string; source_date: string | null; imported_rows: number; confirmed_at: string; total_staging_rows?: number; matched_rows?: number; ignored_rows?: number; incomplete_rows?: number; matching_complete?: boolean }
export interface ReplenishmentIssue { id: number; run_id: number | null; suggestion_id: number | null; issue_code: string; severity: string; message: string; status: string; product_id: number | null; details: Record<string, unknown> | null }
export interface ProductOption { id: number; product_code: string; product_name: string | null; specification: string | null }

export async function listReplenishmentSourceBatches(importType?: string) {
  const params: Record<string, unknown> = {}
  if (importType) params.import_type = importType
  return (await http.get<{ items: SourceBatch[] }>('/v1/replenishment/source-batches', { params })).data
}

export async function getReplenishmentRun(runId: number) {
  return (await http.get<ReplenishmentRun & { order_inputs: Record<string, unknown>[]; audit_logs: Record<string, unknown>[] }>(`/v1/replenishment/runs/${runId}`)).data
}

export function describeReplenishmentError(error: unknown): string {
  if (axios.isAxiosError(error) && error.code === 'ECONNABORTED') {
    return '计算请求超时，后端可能仍在执行，请刷新运行状态确认，不要重复提交'
  }
  if (axios.isAxiosError(error)) return error.response?.data?.message ?? '补库处理失败，请查看问题清单'
  return '补库处理失败，请稍后重试'
}

export async function listRuns(params: Record<string, unknown> = {}) {
  return (await http.get<{ items: ReplenishmentRun[]; total: number }>('/v1/replenishment/runs', { params })).data
}

export async function createRun(payload: Record<string, unknown>) {
  return (await http.post<ReplenishmentRun>('/v1/replenishment/runs', payload)).data
}

export async function calculateRun(runId: number, override = false, reason?: string) {
  return (await http.post<ReplenishmentRun>(`/v1/replenishment/runs/${runId}/calculate`, {
    override_blocking_checks: override, override_reason: reason,
  }, { timeout: REPLENISHMENT_REQUEST_TIMEOUT_MS })).data
}

export async function listSuggestions(runId: number, params: Record<string, unknown> = {}) {
  return (await http.get<{ items: ReplenishmentSuggestion[]; total: number }>('/v1/replenishment/suggestions', { params: { run_id: runId, ...params } })).data
}

export async function getSuggestion(suggestionId: number) {
  return (await http.get<ReplenishmentSuggestion & { issues: ReplenishmentIssue[] }>(`/v1/replenishment/suggestions/${suggestionId}`)).data
}

export async function listRunIssues(runId: number, params: Record<string, unknown> = {}) {
  return (await http.get<{ items: ReplenishmentIssue[]; total: number }>(`/v1/replenishment/runs/${runId}/issues`, { params })).data
}

export async function resolveRunIssue(runId: number, issueId: number, action: 'RESOLVE' | 'IGNORE', reason: string) {
  return (await http.post(`/v1/replenishment/runs/${runId}/issues/${issueId}`, { action, reason })).data
}

export async function updateScheduledOverride(suggestionId: number, qty: string, reason: string) {
  return (await http.put<ReplenishmentSuggestion>(
    `/v1/replenishment/suggestions/${suggestionId}/scheduled-override`,
    { scheduled_override_qty: qty, reason },
  )).data
}

export async function searchReplenishmentProducts(keyword: string) {
  return (await http.get<{ items: ProductOption[] }>('/v1/replenishment/products', { params: { keyword } })).data
}

export async function reviewSuggestion(suggestionId: number, action: string, confirmedQty: string | undefined, reason: string) {
  return (await http.patch<ReplenishmentSuggestion>(`/v1/replenishment/suggestions/${suggestionId}`, { action, confirmed_qty: confirmedQty, reason })).data
}

export async function bulkReviewSuggestions(suggestionIds: number[], action: string, reason: string) {
  return (await http.post('/v1/replenishment/suggestions/bulk-review', { suggestion_ids: suggestionIds, action, reason })).data
}

export async function convertSuggestions(runId: number, suggestionIds: number[], reason: string) {
  return (await http.post(`/v1/replenishment/runs/${runId}/convert`, { suggestion_ids: suggestionIds, reason }, { timeout: REPLENISHMENT_REQUEST_TIMEOUT_MS })).data
}

export async function approveRun(runId: number, reason: string, allowNoReplenishment = false) {
  return (await http.post<ReplenishmentRun>(`/v1/replenishment/runs/${runId}/approve`, { reason, allow_no_replenishment: allowNoReplenishment })).data
}

export async function listProductionDemands(params: Record<string, unknown> = {}) {
  return (await http.get<{ items: ProductionDemand[]; total: number }>('/v1/production-demands', { params })).data
}

export async function cancelProductionDemand(demandId: number, reason: string) {
  return (await http.post<ProductionDemand>(`/v1/production-demands/${demandId}/cancel`, { reason })).data
}

import http from './http'

export type ImportStatus =
  | 'UPLOADED' | 'ANALYZED' | 'VALIDATION_FAILED' | 'READY'
  | 'IMPORTING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'ROLLED_BACK'

export interface ImportBatch {
  id: number
  batch_no: string
  import_type: string
  original_filename: string
  file_sha256: string
  file_size: number
  workbook_sheet_count: number
  selected_sheet_name: string | null
  status: ImportStatus
  total_rows: number
  valid_rows: number
  warning_rows: number
  error_rows: number
  imported_rows: number
  field_mapping: Record<string, number>
  import_options: Record<string, unknown>
  error_summary: Record<string, number>
  created_by_name: string | null
  created_at: string
  confirmed_at: string | null
  cancel_reason: string | null
  sheet_names?: string[]
}

export interface ImportIssue {
  id?: number
  excel_row_number: number
  severity: 'ERROR' | 'WARNING' | 'INFO'
  field_name: string | null
  raw_value: string | null
  issue_code: string
  message: string
}

export interface PreviewRow {
  excel_row_number: number
  data: Record<string, unknown>
  issues: ImportIssue[]
  severity: 'ERROR' | 'WARNING' | 'VALID'
}

export interface ImportAuditLog {
  id: number
  action: string
  user_id: number | null
  before_data: Record<string, unknown> | null
  after_data: Record<string, unknown> | null
  reason: string | null
  request_id: string
  occurred_at: string
}

export const IMPORT_TYPE_LABELS: Record<string, string> = {
  SHIPMENT: '销售出货明细', INVENTORY: '实时库存', PIPE_WIP: '水管在制品',
  FITTING_WIP: '管件在制品', REGULAR_PRODUCT: '常规排产产品清单', WEEKLY_PLAN: '现有周生产计划',
}

export async function listImports(params: Record<string, unknown> = {}) {
  return (await http.get<{ items: ImportBatch[]; total: number; page: number; page_size: number }>('/v1/imports', { params })).data
}

export async function uploadImport(importType: string, file: File, sourceDate?: string) {
  const form = new FormData()
  form.append('import_type', importType)
  form.append('file', file)
  if (sourceDate) form.append('source_date', sourceDate)
  return (await http.post<ImportBatch>('/v1/imports/upload', form)).data
}

export async function getImport(batchId: number) {
  return (await http.get<ImportBatch>(`/v1/imports/${batchId}`)).data
}

export async function getImportSheets(batchId: number) {
  return (await http.get<{ sheet_names: string[]; sheets: Array<Record<string, unknown>> }>(`/v1/imports/${batchId}/sheets`)).data
}

export async function analyzeImport(batchId: number, sheetName: string) {
  return (await http.post<ImportBatch & { analysis: Record<string, unknown> }>(`/v1/imports/${batchId}/analyze`, { sheet_name: sheetName })).data
}

export async function updateImportMapping(batchId: number, fieldMapping: Record<string, number>) {
  return (await http.put<ImportBatch>(`/v1/imports/${batchId}/mapping`, { field_mapping: fieldMapping, conversion_rules: {} })).data
}

export async function getImportPreview(batchId: number, issueFilter?: string) {
  return (await http.get<{ items: PreviewRow[] }>(`/v1/imports/${batchId}/preview`, { params: { issue_filter: issueFilter || undefined, limit: 100 } })).data
}

export async function validateImport(batchId: number) {
  return (await http.post<ImportBatch>(`/v1/imports/${batchId}/validate`)).data
}

export async function confirmImport(batchId: number) {
  return (await http.post<ImportBatch>(`/v1/imports/${batchId}/confirm`)).data
}

export async function rollbackImport(batchId: number, reason: string) {
  return (await http.post<ImportBatch>(`/v1/imports/${batchId}/rollback`, { reason })).data
}

export async function listImportIssues(batchId: number, severity?: string) {
  return (await http.get<{ items: ImportIssue[]; total: number }>(`/v1/imports/${batchId}/issues`, { params: { severity } })).data
}

export async function listImportAuditLogs(batchId: number) {
  return (await http.get<{ items: ImportAuditLog[] }>(`/v1/imports/${batchId}/audit-logs`)).data
}

export async function downloadImportIssues(batchId: number, batchNo: string) {
  const response = await http.get<Blob>(`/v1/imports/${batchId}/issues/export`, { responseType: 'blob' })
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = `${batchNo}-issues.csv`
  link.click()
  URL.revokeObjectURL(url)
}

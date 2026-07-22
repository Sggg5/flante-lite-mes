
export function getLocalDateString(): string {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export const REPLENISHMENT_WIZARD_STEPS = [
  '选择计算日期', '选择销售批次', '选择库存批次', '选择水管在制',
  '选择管件在制', '选择常规产品', '选择周计划', '选择默认算法',
  '配置权重和取整', '校验数据日期', '显示完整性问题', '确认开始计算',
]

export function canConvertSuggestion(status: string, confirmedQty: string | null): boolean {
  return ['ACCEPTED', 'ADJUSTED'].includes(status) && Number(confirmedQty ?? 0) > 0
}

export function weightsAreValid(values: string): boolean {
  const weights = values.split(',').map(value => Number(value.trim()))
  return weights.length === 6 && weights.every(value => Number.isFinite(value) && value >= 0)
    && Math.abs(weights.reduce((total, value) => total + value, 0) - 1) <= 0.000001
}

export type IssueActionMode = 'SCHEDULED_OVERRIDE' | 'ACKNOWLEDGE' | 'RELEASE' | 'NONE'

export function issueActionMode(issueCode: string, severity: string): IssueActionMode {
  if (issueCode === 'SCHEDULED_ACTUAL_UNKNOWN') return 'SCHEDULED_OVERRIDE'
  if (['SNAPSHOT_DATE_MISMATCH', 'SHIPMENT_WINDOW_INCOMPLETE'].includes(issueCode)) return 'RELEASE'
  if (['INVENTORY_SNAPSHOT_MISSING', 'ORDER_INPUT_REQUIRED', 'SCHEDULED_ROWS_UNMATCHED', 'SNAPSHOT_DATE_IN_FUTURE'].includes(issueCode)) return 'NONE'
  return ['WARNING', 'INFO'].includes(severity) ? 'ACKNOWLEDGE' : 'NONE'
}

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

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { approveRun, bulkReviewSuggestions, calculateRun, convertSuggestions, createRun, describeReplenishmentError, getReplenishmentRun, getSuggestion, listReplenishmentSourceBatches, listRunIssues, listRuns, listSuggestions, resolveRunIssue, searchReplenishmentProducts, reviewSuggestion, updateScheduledOverride, type ProductOption, type ReplenishmentIssue, type ReplenishmentRun, type ReplenishmentSuggestion, type SourceBatch } from '../api/replenishment'
import { useAuthStore } from '../stores/auth'
import { REPLENISHMENT_WIZARD_STEPS, canConvertSuggestion, getLocalDateString, issueActionMode } from './replenishment-workflow'

const auth = useAuthStore()
const loading = ref(false)
const processing = ref(false)
const runs = ref<ReplenishmentRun[]>([])
const suggestions = ref<ReplenishmentSuggestion[]>([])
const issues = ref<ReplenishmentIssue[]>([])
const selectedRun = ref<ReplenishmentRun | null>(null)
const selectedSuggestions = ref<ReplenishmentSuggestion[]>([])
const wizardVisible = ref(false)
const wizardStep = ref(0)
const sourceOptions = reactive<Record<string, SourceBatch[]>>({})
const form = reactive({ calculation_date: getLocalDateString(), shipment_batch_id: undefined as number | undefined, inventory_batch_id: undefined as number | undefined, pipe_wip_batch_id: undefined as number | undefined, fitting_wip_batch_id: undefined as number | undefined, regular_product_batch_id: undefined as number | undefined, weekly_plan_batch_id: undefined as number | undefined })
const defaultAlgorithm = ref('SIX_MONTH_MAX')
const defaultWeights = ref('0.05,0.05,0.10,0.15,0.25,0.40')
const defaultFixedTargetQty = ref('')
const roundingMode = ref('NONE')
const defaultMinBatchQty = ref('')
const orderInputs = ref<Array<{ product_id?: number; quantity: string; reason: string }>>([])
const productOptions = ref<ProductOption[]>([])
const filters = reactive({ status: '', keyword: '', review_status: '', algorithm: '' })
const positiveOnly = ref(true)
const issueSeverity = ref('')
const issueStatus = ref('')
const detailVisible = ref(false)
const suggestionDetail = ref<(ReplenishmentSuggestion & { issues?: ReplenishmentIssue[] }) | null>(null)
const scheduledOverrideVisible = ref(false)
const scheduledOverrideSuggestion = ref<(ReplenishmentSuggestion & { issues?: ReplenishmentIssue[] }) | null>(null)
const scheduledOverrideForm = reactive({ qty: '0', reason: '' })
const runPage = ref(1)
const runPageSize = ref(20)
const runTotal = ref(0)
const suggestionPage = ref(1)
const suggestionPageSize = ref(50)
const suggestionTotal = ref(0)
const issuePage = ref(1)
const issuePageSize = ref(50)
const issueTotal = ref(0)

const canCalculate = computed(() => auth.hasPermission('replenishment.run.create') && auth.hasPermission('replenishment.run.calculate'))
const canReview = computed(() => auth.hasPermission('replenishment.review'))
const canConvert = computed(() => auth.hasPermission('replenishment.convert'))
const canApprove = computed(() => auth.hasPermission('replenishment.approve'))
const convertible = computed(() => selectedSuggestions.value.filter(item => canConvertSuggestion(item.review_status, item.confirmed_qty)))

async function refreshRuns() {
  loading.value = true
  try {
    const resp = await listRuns({ status: filters.status || undefined, page: runPage.value, page_size: runPageSize.value })
    runs.value = resp.items; runTotal.value = resp.total
  }
  finally { loading.value = false }
}

async function loadSource(type: string) {
  sourceOptions[type] = (await listReplenishmentSourceBatches(type)).items
}

async function startWizard() {
  wizardStep.value = 0
  wizardVisible.value = true
  form.calculation_date = getLocalDateString()
  form.weekly_plan_batch_id = undefined
  orderInputs.value = []
  runPage.value = 1; suggestionPage.value = 1; issuePage.value = 1
  selectedSuggestions.value = []
  await Promise.all(['SHIPMENT', 'INVENTORY', 'PIPE_WIP', 'FITTING_WIP', 'REGULAR_PRODUCT', 'WEEKLY_PLAN'].map(loadSource))
}

async function finishCalculation() {
  processing.value = true
  try {
    const run = await createRun({
      ...form, default_algorithm: defaultAlgorithm.value, rounding_mode: roundingMode.value,
      default_weight_config: defaultAlgorithm.value === 'SIX_MONTH_WEIGHTED' ? defaultWeights.value.split(',').map(value => value.trim()) : undefined,
      default_fixed_target_qty: defaultAlgorithm.value === 'FIXED_TARGET' ? defaultFixedTargetQty.value : undefined,
      default_min_batch_qty: roundingMode.value === 'CEIL_TO_MIN_BATCH' ? defaultMinBatchQty.value : undefined,
      order_inputs: orderInputs.value.filter(item => item.product_id).map(item => ({ ...item, product_id: item.product_id })),
    })
    selectedRun.value = await calculateRun(run.id)
    await selectRun(selectedRun.value)
    wizardVisible.value = false
    ElMessage.success('补库计算完成，请处理问题并审核建议')
  } catch (error) { ElMessage.error(describeReplenishmentError(error)) }
  finally { processing.value = false }
}

async function nextStep() {
  if (wizardStep.value < 11) { wizardStep.value += 1; return }
  await finishCalculation()
}

async function selectRun(run: ReplenishmentRun) {
  selectedRun.value = run
  suggestionPage.value = 1; issuePage.value = 1
  selectedSuggestions.value = []
  issueSeverity.value = ''; issueStatus.value = ''
  await refreshCurrentRunData()
}

async function refreshCurrentRunData() {
  if (!selectedRun.value) return
  const runId = selectedRun.value.id
  // Refresh selectedRun stats from detail API
  try {
    selectedRun.value = await getReplenishmentRun(runId)
  } catch {
    selectedRun.value = null
    ElMessage.error('当前运行已不存在或已被取消')
    return
  }
  const sugResp = await listSuggestions(runId, {
    keyword: filters.keyword || undefined, review_status: filters.review_status || undefined,
    positive_only: positiveOnly.value, page: suggestionPage.value, page_size: suggestionPageSize.value,
  })
  suggestions.value = sugResp.items; suggestionTotal.value = sugResp.total
  const issResp = await listRunIssues(runId, {
    page: issuePage.value, page_size: issuePageSize.value,
    severity: issueSeverity.value || undefined, status: issueStatus.value || undefined,
  })
  issues.value = issResp.items; issueTotal.value = issResp.total
}

async function openRun(run: ReplenishmentRun) {
  await selectRun(run)
}

async function searchProducts(keyword: string) { productOptions.value = keyword ? (await searchReplenishmentProducts(keyword)).items : [] }
function addOrderInput() { orderInputs.value.push({ quantity: '0', reason: '订单生产输入' }) }
async function handleIssue(issue: ReplenishmentIssue, action: 'RESOLVE' | 'IGNORE') {
  if (!selectedRun.value) return
  const { value } = await ElMessageBox.prompt('请输入问题处理依据', action === 'RESOLVE' ? '解决问题' : '忽略问题')
  await resolveRunIssue(selectedRun.value.id, issue.id, action, value)
  await refreshCurrentRunData()
}

async function openScheduledOverride(issue: ReplenishmentIssue) {
  if (!issue.suggestion_id) return ElMessage.error('该问题没有关联补库建议，无法填写已排覆盖')
    scheduledOverrideSuggestion.value = await getSuggestion(issue.suggestion_id)
  scheduledOverrideForm.qty = scheduledOverrideSuggestion.value.scheduled_override_qty ?? '0'
  scheduledOverrideForm.reason = ''
  scheduledOverrideVisible.value = true
}

async function submitScheduledOverride() {
  if (!scheduledOverrideSuggestion.value || !selectedRun.value) return
  processing.value = true
  try {
    const updated = await updateScheduledOverride(
      scheduledOverrideSuggestion.value.id,
      scheduledOverrideForm.qty,
      scheduledOverrideForm.reason,
    )
    scheduledOverrideVisible.value = false
    await refreshCurrentRunData()
    if (suggestionDetail.value?.id === updated.id) suggestionDetail.value = await getSuggestion(updated.id)
    ElMessage.success('已重新计算系统建议量，审核状态已重置')
  } catch (error) { ElMessage.error(describeReplenishmentError(error)) }
  finally { processing.value = false }
}

function selectionChanged(rows: ReplenishmentSuggestion[]) { selectedSuggestions.value = rows }
async function openSuggestionDetail(row: ReplenishmentSuggestion) {
  suggestionDetail.value = await getSuggestion(row.id)
  detailVisible.value = true
}

async function approveOne(row: ReplenishmentSuggestion) {
  const result = await ElMessageBox.prompt('确认数量；如修改系统建议量，请在下一步填写原因', '审核补库建议', { inputValue: row.confirmed_qty ?? row.system_suggested_qty })
  const reason = await ElMessageBox.prompt('请输入审核原因', '审核原因', { inputValue: '确认系统补库建议' })
  await reviewSuggestion(row.id, 'APPROVE', result.value, reason.value)
  await refreshCurrentRunData()
}

async function bulkApprove() {
  if (!selectedSuggestions.value.length) return ElMessage.warning('请先选择建议')
  const { value } = await ElMessageBox.prompt('请输入批量审核原因', '批量审核', { inputValue: '批量确认系统建议量' })
  await bulkReviewSuggestions(selectedSuggestions.value.map(item => item.id), 'APPROVE', value)
  await refreshCurrentRunData()
}

async function convertSelected() {
  if (!convertible.value.length || !selectedRun.value) return ElMessage.warning('请选择确认量大于 0 的已批准建议')
  processing.value = true
  try {
    await convertSuggestions(selectedRun.value.id, convertible.value.map(item => item.id), '人工确认转入生产需求池')
    ElMessage.success('已转入生产需求池；重复提交不会重复创建')
    await refreshCurrentRunData()
    await refreshRuns()
  } catch (error) { ElMessage.error(describeReplenishmentError(error)) }
  finally { processing.value = false }
}
async function approveCurrentRun() {
  if (!selectedRun.value) return
  const { value } = await ElMessageBox.prompt('请输入运行批准原因', '批准补库运行', { inputValue: '所有建议与问题已复核' })
  try { selectedRun.value = await approveRun(selectedRun.value.id, value); ElMessage.success('补库运行已批准'); await refreshRuns() }
  catch (error) { ElMessage.error(describeReplenishmentError(error)) }
}

onMounted(refreshRuns)

async function handleRunPageChange(page: number) {
  runPage.value = page
  await refreshRuns()
}

async function handleSuggestionPageChange(page: number) {
  suggestionPage.value = page
  selectedSuggestions.value = []
  if (selectedRun.value) {
    const resp = await listSuggestions(selectedRun.value.id, {
      keyword: filters.keyword || undefined, review_status: filters.review_status || undefined,
      positive_only: positiveOnly.value, algorithm: filters.algorithm || undefined,
      page: suggestionPage.value, page_size: suggestionPageSize.value,
    })
    suggestions.value = resp.items; suggestionTotal.value = resp.total
  }
}

async function handleIssuePageChange(page: number) {
  issuePage.value = page
  selectedSuggestions.value = []
  if (selectedRun.value) {
    const resp = await listRunIssues(selectedRun.value.id, {
      page: issuePage.value, page_size: issuePageSize.value,
      severity: issueSeverity.value || undefined, status: issueStatus.value || undefined,
    })
    issues.value = resp.items; issueTotal.value = resp.total
  }
}

function handleSuggestionSizeChange(size: number) {
  suggestionPageSize.value = size
  suggestionPage.value = 1
  handleSuggestionPageChange(1)
}


async function handleIssueSizeChange(size: number) {
  issuePageSize.value = size
  issuePage.value = 1
  await handleIssuePageChange(1)
}

function onIssueSeverityChange() {
  issuePage.value = 1
  refreshCurrentRunData()
}

function onIssueStatusChange() {
  issuePage.value = 1
  refreshCurrentRunData()
}

function onFilterChange() {
  suggestionPage.value = 1
  refreshCurrentRunData()
}

</script>

<template>
  <section class="business-page">
    <div class="page-actions">
      <div><span class="section-kicker">REPLENISHMENT CONTROL</span><h2>补库计算与建议中心</h2><p>固定输入快照，保留六个月销售、库存、在制、已排量和人工审核证据。</p></div>
      <el-button v-if="canCalculate" type="primary" @click="startWizard">新建补库计算</el-button>
    </div>
    <el-card shadow="never">
      <el-form inline><el-form-item label="状态"><el-select v-model="filters.status" clearable style="width:180px"><el-option v-for="value in ['DRAFT','READY_FOR_REVIEW','PARTIALLY_REVIEWED','APPROVED','PARTIALLY_CONVERTED','CONVERTED','FAILED']" :key="value" :value="value" /></el-select></el-form-item><el-button @click="refreshRuns">刷新</el-button></el-form>
      <el-table v-loading="loading" :data="runs" @row-click="selectRun">
        <el-table-column prop="run_no" label="运行编号" min-width="190" /><el-table-column prop="calculation_date" label="计算日期" width="120" /><el-table-column label="快照日期" width="120"><template #default="{ row }">{{ row.source_date_summary?.inventory ?? '-' }}</template></el-table-column><el-table-column prop="default_algorithm" label="默认算法" width="160" /><el-table-column prop="status" label="状态" width="170" /><el-table-column prop="total_products" label="产品" width="80" /><el-table-column prop="positive_suggestion_count" label="正数建议" width="90" /><el-table-column prop="pending_review_count" label="待审核" width="90" /><el-table-column prop="converted_count" label="已转换" width="90" /><el-table-column prop="warning_count" label="警告" width="75" /><el-table-column prop="blocking_issue_count" label="阻断" width="75" /><el-table-column prop="created_by" label="创建人" width="85" /><el-table-column prop="created_at" label="创建时间" width="170" />
      </el-table>
      <el-pagination v-if="runTotal > 0" v-model:current-page="runPage" :page-size="runPageSize" :total="runTotal" layout="total, prev, pager, next" size="small" @current-change="handleRunPageChange" />
      
    </el-card>

    <el-card v-if="selectedRun" shadow="never" class="suggestions-card">
      <template #header><div class="card-title"><strong>{{ selectedRun.run_no }} · 建议明细</strong><div><el-button v-if="canReview" @click="bulkApprove">批量接受</el-button><el-button v-if="canApprove" type="success" @click="approveCurrentRun">批准运行</el-button><el-button v-if="canConvert" type="primary" :loading="processing" @click="convertSelected">转生产需求</el-button></div></div></template>
      <el-form inline><el-select v-model="issueSeverity" clearable placeholder="严重程度" style="width:150px" @change="onIssueSeverityChange"><el-option value="" label="全部" /><el-option value="BLOCKING" label="阻断" /><el-option value="WARNING" label="警告" /><el-option value="INFO" label="提示" /></el-select><el-select v-model="issueStatus" clearable placeholder="问题状态" style="width:150px" @change="onIssueStatusChange"><el-option value="" label="全部" /><el-option value="OPEN" label="待处理" /><el-option value="RESOLVED" label="已解决" /><el-option value="IGNORED" label="已放行" /></el-select></el-form>
      <el-alert v-if="issues.some(item => item.status === 'OPEN')" :title="`当前有 ${issues.filter(item => item.status === 'OPEN').length} 个待处理问题`" type="warning" :closable="false" show-icon />
      <el-table v-if="issues.length" :data="issues" size="small" class="issue-table"><el-table-column prop="severity" label="级别" width="100"/><el-table-column prop="issue_code" label="问题代码" width="230"/><el-table-column prop="message" label="说明" min-width="300"/><el-table-column prop="status" label="状态" width="100"/><el-table-column v-if="auth.hasPermission('replenishment.review')" label="处理" width="170"><template #default="{row}"><el-button v-if="row.status === 'OPEN' && issueActionMode(row.issue_code, row.severity) === 'SCHEDULED_OVERRIDE'" link type="primary" @click="openScheduledOverride(row)">填写已排覆盖</el-button><el-button v-else-if="row.status === 'OPEN' && issueActionMode(row.issue_code, row.severity) === 'ACKNOWLEDGE'" link @click="handleIssue(row,'RESOLVE')">确认知悉</el-button><el-button v-else-if="row.status === 'OPEN' && issueActionMode(row.issue_code, row.severity) === 'RELEASE' && (row.issue_code !== 'SHIPMENT_WINDOW_INCOMPLETE' || auth.user?.roles.includes('ADMIN'))" link type="warning" @click="handleIssue(row,'IGNORE')">填写依据并放行</el-button><span v-else-if="row.status === 'OPEN'">{{ row.issue_code === 'SHIPMENT_WINDOW_INCOMPLETE' ? '仅管理员可放行' : '请按提示修正来源' }}</span></template></el-table-column></el-table>
      <div v-if="issueTotal > 0" style="display:flex;justify-content:space-between;align-items:center;padding:8px 0">
        <span style="color:#909399;font-size:13px">共 {{ issueTotal }} 条</span>
        <el-pagination v-model:current-page="issuePage" :page-size="issuePageSize" :page-sizes="[50,100,200]" :total="issueTotal" layout="total, sizes, prev, pager, next" size="small" @size-change="handleIssueSizeChange" @current-change="handleIssuePageChange" />
      </div>
      <el-form inline><el-input v-model="filters.keyword" placeholder="产品编码/名称/规格" clearable style="width:230px" /><el-select v-model="filters.review_status" clearable placeholder="审核状态" style="width:150px"><el-option v-for="value in ['PENDING','ACCEPTED','ADJUSTED','REJECTED','NOT_REQUIRED','CONVERTED']" :key="value" :value="value" /></el-select><el-switch v-model="positiveOnly" active-text="只看正数建议" inactive-text="查看全部"/><el-button @click="refreshCurrentRunData()">查询</el-button></el-form>
      <el-table :data="suggestions" row-key="id" @row-click="openSuggestionDetail" @selection-change="selectionChanged"><el-table-column type="selection" width="46" /><el-table-column prop="product_code" label="产品编码" fixed width="150" /><el-table-column prop="product_name" label="名称" fixed width="150" /><el-table-column prop="specification" label="规格" width="140" /><el-table-column label="六个月销量" min-width="260"><template #default="{ row }"><span class="month-values">{{ Object.values(row.monthly_shipments).join(' / ') }}</span></template></el-table-column><el-table-column prop="target_stock_qty" label="目标库存" width="110" /><el-table-column prop="on_hand_qty" label="现存" width="90" /><el-table-column prop="expected_inbound_qty" label="预计入库" width="95" /><el-table-column prop="expected_outbound_qty" label="预计出库" width="95" /><el-table-column prop="available_qty" label="可用库存" width="110" /><el-table-column prop="pipe_wip_effective_qty" label="水管在制" width="100" /><el-table-column prop="fitting_wip_effective_qty" label="管件在制" width="100" /><el-table-column prop="scheduled_not_started_qty" label="已排未开" width="100" /><el-table-column prop="system_suggested_qty" label="系统建议" width="110" /><el-table-column prop="confirmed_qty" label="确认量" width="100" /><el-table-column prop="review_status" label="审核状态" width="110" /><el-table-column v-if="canReview" label="操作" fixed="right" width="90"><template #default="{ row }"><el-button link type="primary" @click.stop="approveOne(row)">审核</el-button></template></el-table-column></el-table>
      <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0">
        <span style="color:#909399;font-size:13px">当前页已选择 {{ selectedSuggestions.length }} 条</span>
        <el-pagination v-if="suggestionTotal > 0" v-model:current-page="suggestionPage" :page-size="suggestionPageSize" :page-sizes="[50,100,200]" :total="suggestionTotal" layout="total, sizes, prev, pager, next, jumper" @size-change="handleSuggestionSizeChange" @current-change="handleSuggestionPageChange" />
      </div>
    </el-card>

    <el-drawer v-model="detailVisible" title="补库建议计算明细" size="620px">
      <el-descriptions v-if="suggestionDetail" :column="2" border>
        <el-descriptions-item label="产品">{{ suggestionDetail.product_code }} · {{ suggestionDetail.product_name }}</el-descriptions-item>
        <el-descriptions-item label="算法">{{ suggestionDetail.algorithm }}</el-descriptions-item>
        <el-descriptions-item label="六个月销售" :span="2">{{ Object.entries(suggestionDetail.monthly_shipments).map(([month, qty]) => `${month}: ${qty}`).join(' / ') }}</el-descriptions-item>
        <el-descriptions-item label="算法原始值">{{ suggestionDetail.calculated_target_qty }}</el-descriptions-item>
        <el-descriptions-item label="取整后目标">{{ suggestionDetail.target_stock_qty }}</el-descriptions-item>
        <el-descriptions-item label="现存 / 入库 / 出库">{{ suggestionDetail.on_hand_qty }} / {{ suggestionDetail.expected_inbound_qty }} / {{ suggestionDetail.expected_outbound_qty }}</el-descriptions-item>
        <el-descriptions-item label="可用量">{{ suggestionDetail.available_qty }}</el-descriptions-item>
        <el-descriptions-item label="水管在制 原值 / 有效">{{ suggestionDetail.pipe_wip_raw_qty }} / {{ suggestionDetail.pipe_wip_effective_qty }}</el-descriptions-item>
        <el-descriptions-item label="管件在制 原值 / 有效">{{ suggestionDetail.fitting_wip_raw_qty }} / {{ suggestionDetail.fitting_wip_effective_qty }}</el-descriptions-item>
        <el-descriptions-item label="已排未开工">{{ suggestionDetail.scheduled_not_started_qty }}</el-descriptions-item>
        <el-descriptions-item label="系统建议">{{ suggestionDetail.system_suggested_qty }}</el-descriptions-item>
        <el-descriptions-item label="人工确认">{{ suggestionDetail.confirmed_qty }}</el-descriptions-item>
        <el-descriptions-item label="审核状态">{{ suggestionDetail.review_status }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-for="issue in suggestionDetail?.issues ?? []" :key="issue.id" :title="`${issue.issue_code}: ${issue.message}`" :type="issue.severity === 'BLOCKING' ? 'error' : 'warning'" :closable="false" show-icon class="detail-issue" />
    </el-drawer>

    <el-dialog v-model="scheduledOverrideVisible" title="填写周计划已排数量覆盖" width="560px" :close-on-click-modal="!processing">
      <el-alert title="周计划实际量未知。请根据现场确认填写额外的已排未开工数量；提交后系统建议量会重新计算，原审核结果与确认量会清除。" type="warning" :closable="false" show-icon />
      <el-descriptions v-if="scheduledOverrideSuggestion" :column="1" border class="override-detail">
        <el-descriptions-item label="产品">{{ scheduledOverrideSuggestion.product_code }} · {{ scheduledOverrideSuggestion.product_name }}</el-descriptions-item>
        <el-descriptions-item label="已知已排未开工">{{ scheduledOverrideSuggestion.scheduled_known_qty }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-width="140px">
        <el-form-item label="覆盖数量"><el-input v-model="scheduledOverrideForm.qty" inputmode="decimal" /></el-form-item>
        <el-form-item label="确认原因"><el-input v-model="scheduledOverrideForm.reason" type="textarea" :rows="3" placeholder="至少填写2个字符" /></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="processing" @click="scheduledOverrideVisible=false">取消</el-button><el-button type="primary" :loading="processing" :disabled="scheduledOverrideForm.reason.trim().length < 2" @click="submitScheduledOverride">确认并重新计算</el-button></template>
    </el-dialog>

    <el-dialog v-model="wizardVisible" title="新建补库计算" width="900px" :close-on-click-modal="!processing">
      <el-steps :active="wizardStep" finish-status="success" simple><el-step v-for="step in REPLENISHMENT_WIZARD_STEPS" :key="step" :title="step" /></el-steps>
      <div class="wizard-body">
        <el-date-picker v-if="wizardStep === 0" v-model="form.calculation_date" value-format="YYYY-MM-DD" type="date" placeholder="计算日期" />
        <el-select v-if="wizardStep === 1" v-model="form.shipment_batch_id" filterable placeholder="请选择销售批次" style="width:100%"><el-option v-for="item in sourceOptions.SHIPMENT" :key="item.id" :label="`${item.batch_no} · ${item.source_date ?? '无数据日期'}`" :value="item.id" /></el-select>
        <el-select v-if="wizardStep === 2" v-model="form.inventory_batch_id" filterable placeholder="请选择库存批次" style="width:100%"><el-option v-for="item in sourceOptions.INVENTORY" :key="item.id" :label="`${item.batch_no} · ${item.source_date ?? '无数据日期'}`" :value="item.id" /></el-select>
        <el-select v-if="wizardStep === 3" v-model="form.pipe_wip_batch_id" filterable placeholder="请选择水管在制批次" style="width:100%"><el-option v-for="item in sourceOptions.PIPE_WIP" :key="item.id" :label="`${item.batch_no} · ${item.source_date ?? '无数据日期'}`" :value="item.id" /></el-select>
        <el-select v-if="wizardStep === 4" v-model="form.fitting_wip_batch_id" filterable placeholder="请选择管件在制批次" style="width:100%"><el-option v-for="item in sourceOptions.FITTING_WIP" :key="item.id" :label="`${item.batch_no} · ${item.source_date ?? '无数据日期'}`" :value="item.id" /></el-select>
        <el-select v-if="wizardStep === 5" v-model="form.regular_product_batch_id" filterable placeholder="请选择常规产品批次" style="width:100%"><el-option v-for="item in sourceOptions.REGULAR_PRODUCT" :key="item.id" :label="`${item.batch_no} · ${item.source_date ?? '无数据日期'}`" :value="item.id" /></el-select>
        <el-select v-if="wizardStep === 6" v-model="form.weekly_plan_batch_id" clearable filterable placeholder="可选：请选择已匹配周计划批次" style="width:100%"><el-option v-for="item in sourceOptions.WEEKLY_PLAN" :key="item.id" :value="item.id" :disabled="item.matching_complete === false"><span style="display:flex;justify-content:space-between;width:100%"><span>{{ item.batch_no }} · {{ item.source_date ?? '无数据日期' }}</span><span :style="{color:item.matching_complete?'#67c23a':'#e6a23c'}">{{ item.matching_complete ? '✓ 匹配完成' : '✗ 待匹配('+(item.incomplete_rows??0)+')' }}</span></span></el-option></el-select>
        <el-select v-if="wizardStep === 7" v-model="defaultAlgorithm" style="width:100%" placeholder="默认算法"><el-option v-for="value in ['SIX_MONTH_MAX','SIX_MONTH_AVG','THREE_MONTH_AVG','SIX_MONTH_WEIGHTED','FIXED_TARGET','ORDER_BASED']" :key="value" :value="value" /></el-select>
        <div v-if="wizardStep === 8" class="order-inputs"><el-input v-if="defaultAlgorithm === 'SIX_MONTH_WEIGHTED'" v-model="defaultWeights" placeholder="六个权重，逗号分隔且合计为1"/><el-input v-if="defaultAlgorithm === 'FIXED_TARGET'" v-model="defaultFixedTargetQty" placeholder="默认固定目标库存"/><el-select v-model="roundingMode" style="width:100%"><el-option value="NONE"/><el-option value="CEIL_TO_INTEGER"/><el-option value="CEIL_TO_MIN_BATCH"/></el-select><el-input v-if="roundingMode === 'CEIL_TO_MIN_BATCH'" v-model="defaultMinBatchQty" placeholder="默认最小批量"/><el-button @click="addOrderInput">添加订单产品</el-button><p v-if="orderInputs.length === 0" style="color:#909399;font-size:12px;margin:0">订单型产品输入（仅 ORDER_BASED 产品需要）</p><div v-for="(item,index) in orderInputs" :key="index" class="order-row"><el-select v-model="item.product_id" filterable remote :remote-method="searchProducts" placeholder="搜索产品编码/名称" style="width:330px"><el-option v-for="product in productOptions" :key="product.id" :value="product.id" :label="`${product.product_code} · ${product.product_name ?? ''}`"/></el-select><el-input v-model="item.quantity" placeholder="订单数量"/><el-input v-model="item.reason" placeholder="输入原因"/><el-button type="danger" link @click="orderInputs.splice(index,1)">删除</el-button></div></div>
        <el-alert v-if="wizardStep === 9" title="系统将检查三类快照日期一致、不得晚于计算日，并检查销售是否完整覆盖前六个自然月。" type="warning" show-icon :closable="false" />
        <el-alert v-if="wizardStep === 10" title="未匹配周计划、未知实际量、缺失库存和销售窗口不足会形成阻断问题；计算后必须逐项处理。" type="warning" show-icon :closable="false" />
        <el-alert v-if="wizardStep === 11" title="计算可能需要数分钟。处理中请勿关闭页面或重复提交。" type="success" show-icon :closable="false" />
      </div>
      <template #footer><el-button @click="wizardVisible=false">关闭</el-button><el-button v-if="wizardStep > 0" @click="wizardStep--">上一步</el-button><el-button type="primary" :loading="processing" @click="nextStep">{{ wizardStep === 11 ? '确认开始计算' : '下一步' }}</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.business-page{display:grid;gap:18px}.page-actions,.card-title{display:flex;align-items:center;justify-content:space-between;gap:24px}.page-actions h2{margin:5px 0;font-size:26px}.page-actions p{margin:0;color:#6b7971}.section-kicker{color:#75914f;font-size:10px;font-weight:800;letter-spacing:.18em}.suggestions-card{margin-top:2px}.wizard-body{min-height:180px;display:grid;place-items:center;padding:38px 20px}.month-values{font-variant-numeric:tabular-nums;color:#52655b}.el-steps{overflow:auto}.issue-table{margin:14px 0}.order-inputs{display:grid;gap:12px;width:100%}.order-row{display:grid;grid-template-columns:2fr 1fr 2fr auto;gap:8px}.override-detail{margin:16px 0}
</style>

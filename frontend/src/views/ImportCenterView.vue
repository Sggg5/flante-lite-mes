<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'

import {
  IMPORT_TYPE_LABELS, analyzeImport, confirmImport, downloadImportIssues, getImportPreview, getImportSheets,
  listImportAuditLogs, listImportIssues, listImports, rollbackImport, updateImportMapping,
  uploadImport, validateImport, type ImportAuditLog, type ImportBatch, type ImportIssue, type PreviewRow,
} from '../api/imports'
import { useAuthStore } from '../stores/auth'
import { WIZARD_STEPS, previewRowClass } from './import-workflow'

const auth = useAuthStore()
const loading = ref(false)
const batches = ref<ImportBatch[]>([])
const total = ref(0)
const filters = reactive({ import_type: '', status: '', page: 1, page_size: 20 })
const wizardVisible = ref(false)
const wizardStep = ref(0)
const uploadType = ref('INVENTORY')
const sourceDate = ref('')
const selectedFile = ref<File | null>(null)
const currentBatch = ref<ImportBatch | null>(null)
const sheetNames = ref<string[]>([])
const selectedSheet = ref('')
const mapping = ref<Record<string, number>>({})
const previewRows = ref<PreviewRow[]>([])
const previewFilter = ref('')
const detailVisible = ref(false)
const detailBatch = ref<ImportBatch | null>(null)
const detailIssues = ref<ImportIssue[]>([])
const detailAuditLogs = ref<ImportAuditLog[]>([])

const canUpload = computed(() => auth.hasPermission('import.upload'))
const canValidate = computed(() => auth.hasPermission('import.validate'))
const canConfirm = computed(() => auth.hasPermission('import.confirm'))
const canRollback = computed(() => auth.hasPermission('import.rollback'))
const previewColumns = computed(() => {
  const keys = new Set<string>()
  previewRows.value.forEach((row) => Object.keys(row.data).filter((key) => key !== 'raw_data').forEach((key) => keys.add(key)))
  return [...keys]
})

function statusType(status: string) {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED' || status === 'VALIDATION_FAILED') return 'danger'
  if (status === 'READY' || status === 'ANALYZED') return 'warning'
  return 'info'
}

function tableRowClassName({ row }: { row: PreviewRow }) {
  return previewRowClass(row)
}

async function refresh() {
  loading.value = true
  try {
    const result = await listImports({ ...filters, import_type: filters.import_type || undefined, status: filters.status || undefined })
    batches.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function startWizard() {
  wizardStep.value = 0
  uploadType.value = 'INVENTORY'
  sourceDate.value = ''
  selectedFile.value = null
  currentBatch.value = null
  sheetNames.value = []
  selectedSheet.value = ''
  mapping.value = {}
  previewRows.value = []
  wizardVisible.value = true
}

function chooseFile(file: UploadFile) {
  selectedFile.value = file.raw ?? null
}

async function nextWizardStep() {
  if (wizardStep.value === 0) {
    wizardStep.value = 1
    return
  }
  if (wizardStep.value === 1) {
    if (!selectedFile.value) return ElMessage.warning('请选择 .xlsx 文件')
    currentBatch.value = await uploadImport(uploadType.value, selectedFile.value, sourceDate.value || undefined)
    const sheets = await getImportSheets(currentBatch.value.id)
    sheetNames.value = sheets.sheet_names
    selectedSheet.value = sheetNames.value[0] ?? ''
    wizardStep.value = 2
    return
  }
  if (wizardStep.value === 2) {
    if (!currentBatch.value || !selectedSheet.value) return ElMessage.warning('请选择工作表')
    currentBatch.value = await analyzeImport(currentBatch.value.id, selectedSheet.value)
    mapping.value = { ...currentBatch.value.field_mapping }
    wizardStep.value = 3
    return
  }
  if (wizardStep.value === 3) {
    if (!currentBatch.value) return
    currentBatch.value = await updateImportMapping(currentBatch.value.id, mapping.value)
    previewRows.value = (await getImportPreview(currentBatch.value.id)).items
    wizardStep.value = 4
    return
  }
  if (wizardStep.value === 4) {
    wizardStep.value = 5
    return
  }
  if (wizardStep.value === 5) {
    if (!currentBatch.value) return
    currentBatch.value = await validateImport(currentBatch.value.id)
    wizardStep.value = 6
    return
  }
  if (wizardStep.value === 6) {
    if (!currentBatch.value || currentBatch.value.error_rows > 0) return ElMessage.error('存在错误行，不能确认导入')
    currentBatch.value = await confirmImport(currentBatch.value.id)
    wizardStep.value = 7
    await refresh()
  }
}

async function applyPreviewFilter() {
  if (!currentBatch.value) return
  previewRows.value = (await getImportPreview(currentBatch.value.id, previewFilter.value)).items
}

async function openDetail(batch: ImportBatch) {
  detailBatch.value = batch
  const [issues, auditLogs] = await Promise.all([listImportIssues(batch.id), listImportAuditLogs(batch.id)])
  detailIssues.value = issues.items
  detailAuditLogs.value = auditLogs.items
  detailVisible.value = true
}

async function rollbackBatch() {
  if (!detailBatch.value) return
  const result = await ElMessageBox.prompt('请输入撤销原因', '撤销导入批次', { inputValidator: (value) => value.length >= 2 || '至少输入2个字符' })
  detailBatch.value = await rollbackImport(detailBatch.value.id, result.value)
  ElMessage.success('导入批次已撤销')
  await refresh()
}

async function exportIssues() {
  if (detailBatch.value) await downloadImportIssues(detailBatch.value.id, detailBatch.value.batch_no)
}

onMounted(refresh)
</script>

<template>
  <section class="import-center" data-testid="import-center">
    <header class="import-heading">
      <div><div class="eyebrow">PHASE 2 · DATA INTAKE</div><h2>Excel 数据导入中心</h2><p>上传、分析、校验并追踪每一次标准化导入。</p></div>
      <el-button v-if="canUpload" type="primary" data-testid="new-import" @click="startWizard">新建导入</el-button>
    </header>

    <el-card shadow="never" class="filter-card">
      <el-form inline>
        <el-form-item label="导入类型"><el-select v-model="filters.import_type" clearable style="width: 190px"><el-option v-for="(label, value) in IMPORT_TYPE_LABELS" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="状态"><el-select v-model="filters.status" clearable style="width: 160px"><el-option v-for="value in ['UPLOADED','ANALYZED','VALIDATION_FAILED','READY','COMPLETED','FAILED','ROLLED_BACK']" :key="value" :label="value" :value="value" /></el-select></el-form-item>
        <el-button @click="refresh">筛选</el-button><el-button @click="refresh">刷新</el-button>
      </el-form>
    </el-card>

    <el-card shadow="never" class="batch-card" data-testid="batch-list">
      <el-table v-loading="loading" :data="batches" stripe>
        <el-table-column prop="batch_no" label="批次号" width="210" fixed />
        <el-table-column label="导入类型" width="160"><template #default="scope">{{ IMPORT_TYPE_LABELS[scope.row.import_type] }}</template></el-table-column>
        <el-table-column prop="original_filename" label="文件名" min-width="190" show-overflow-tooltip />
        <el-table-column prop="selected_sheet_name" label="工作表" width="130" />
        <el-table-column label="状态" width="150"><template #default="scope"><el-tag :type="statusType(scope.row.status)">{{ scope.row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="total_rows" label="总行" width="75" /><el-table-column prop="valid_rows" label="有效" width="75" />
        <el-table-column prop="warning_rows" label="警告" width="75" /><el-table-column prop="error_rows" label="错误" width="75" />
        <el-table-column prop="created_by_name" label="导入人" width="110" /><el-table-column prop="created_at" label="导入时间" width="190" />
        <el-table-column label="操作" width="100" fixed="right"><template #default="scope"><el-button link type="primary" @click="openDetail(scope.row)">详情</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="filters.page" :page-size="filters.page_size" :total="total" layout="total, prev, pager, next" @current-change="refresh" />
    </el-card>

    <el-dialog v-model="wizardVisible" width="92%" top="4vh" destroy-on-close data-testid="import-wizard" title="Excel 导入向导">
      <el-steps :active="wizardStep" finish-status="success" align-center><el-step v-for="step in WIZARD_STEPS" :key="step" :title="step" /></el-steps>
      <div class="wizard-panel">
        <div v-if="wizardStep === 0"><h3>选择导入类型</h3><el-radio-group v-model="uploadType"><el-radio-button v-for="(label, value) in IMPORT_TYPE_LABELS" :key="value" :value="value">{{ label }}</el-radio-button></el-radio-group></div>
        <div v-else-if="wizardStep === 1"><h3>上传文件</h3><el-date-picker v-model="sourceDate" value-format="YYYY-MM-DD" placeholder="数据日期（可选）" /><el-upload :auto-upload="false" accept=".xlsx" :limit="1" :on-change="chooseFile"><el-button>选择 .xlsx 文件</el-button></el-upload></div>
        <div v-else-if="wizardStep === 2"><h3>选择工作表</h3><el-select v-model="selectedSheet" style="width: 320px"><el-option v-for="sheet in sheetNames" :key="sheet" :label="sheet" :value="sheet" /></el-select></div>
        <div v-else-if="wizardStep === 3" data-testid="field-mapping"><h3>字段匹配</h3><p>列号从 1 开始；每个 Excel 列只能映射一次。</p><el-row :gutter="16"><el-col v-for="(_, field) in mapping" :key="field" :span="8"><el-form-item :label="field"><el-input-number v-model="mapping[field]" :min="1" /></el-form-item></el-col></el-row></div>
        <div v-else-if="wizardStep === 4" data-testid="preview-table"><div class="preview-tools"><h3>数据预览（最多100行）</h3><el-radio-group v-model="previewFilter" @change="applyPreviewFilter"><el-radio-button value="">全部</el-radio-button><el-radio-button value="ERROR">只看错误</el-radio-button><el-radio-button value="WARNING">只看警告</el-radio-button></el-radio-group></div><el-table :data="previewRows" max-height="430" :row-class-name="tableRowClassName"><el-table-column prop="excel_row_number" label="Excel行号" width="100" fixed /><el-table-column v-for="column in previewColumns" :key="column" :prop="`data.${column}`" :label="column" min-width="150" :fixed="['product_code','product_name','specification'].includes(column) ? 'left' : false" /></el-table></div>
        <div v-else-if="wizardStep === 5"><h3>执行全量校验</h3><el-alert title="校验不会写入正式业务表" type="info" show-icon /></div>
        <div v-else-if="wizardStep === 6" data-testid="confirm-import"><h3>确认导入</h3><el-descriptions v-if="currentBatch" border :column="4"><el-descriptions-item label="有效行">{{ currentBatch.valid_rows }}</el-descriptions-item><el-descriptions-item label="警告行">{{ currentBatch.warning_rows }}</el-descriptions-item><el-descriptions-item label="错误行">{{ currentBatch.error_rows }}</el-descriptions-item><el-descriptions-item label="状态">{{ currentBatch.status }}</el-descriptions-item></el-descriptions><el-alert v-if="currentBatch?.warning_rows" title="警告行默认允许导入，请确认后继续" type="warning" show-icon /></div>
        <el-result v-else icon="success" title="导入完成" :sub-title="`已导入 ${currentBatch?.imported_rows ?? 0} 行`" />
      </div>
      <template #footer><el-button @click="wizardVisible = false">关闭</el-button><el-button v-if="wizardStep < 7" type="primary" :disabled="(wizardStep === 5 && !canValidate) || (wizardStep === 6 && !canConfirm)" @click="nextWizardStep">{{ wizardStep === 6 ? '确认导入' : '下一步' }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" size="58%" title="导入批次详情" data-testid="batch-detail">
      <template v-if="detailBatch"><el-descriptions border :column="2"><el-descriptions-item label="批次号">{{ detailBatch.batch_no }}</el-descriptions-item><el-descriptions-item label="状态">{{ detailBatch.status }}</el-descriptions-item><el-descriptions-item label="文件">{{ detailBatch.original_filename }}</el-descriptions-item><el-descriptions-item label="SHA-256"><code>{{ detailBatch.file_sha256 }}</code></el-descriptions-item><el-descriptions-item label="工作表">{{ detailBatch.selected_sheet_name }}</el-descriptions-item><el-descriptions-item label="统计">有效 {{ detailBatch.valid_rows }} / 警告 {{ detailBatch.warning_rows }} / 错误 {{ detailBatch.error_rows }}</el-descriptions-item></el-descriptions><h3>字段映射</h3><pre>{{ JSON.stringify(detailBatch.field_mapping, null, 2) }}</pre><div class="detail-actions"><el-button link type="primary" @click="exportIssues">下载错误明细</el-button><el-button v-if="canRollback && detailBatch.status === 'COMPLETED'" type="danger" plain @click="rollbackBatch">撤销批次</el-button></div><h3>错误与警告</h3><el-table :data="detailIssues"><el-table-column prop="excel_row_number" label="行号" width="80" /><el-table-column prop="severity" label="等级" width="90" /><el-table-column prop="field_name" label="字段" width="140" /><el-table-column prop="message" label="说明" /></el-table><h3>操作日志</h3><el-table :data="detailAuditLogs"><el-table-column prop="occurred_at" label="时间" width="185" /><el-table-column prop="action" label="动作" width="180" /><el-table-column prop="user_id" label="操作人ID" width="100" /><el-table-column prop="reason" label="原因" /><el-table-column prop="request_id" label="请求编号" min-width="220" /></el-table></template>
    </el-drawer>
  </section>
</template>

<style scoped>
.import-heading { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:20px; }
.import-heading h2 { margin:8px 0 6px; font-size:28px; }.import-heading p { margin:0; color:#6b7971; }
.filter-card { margin-bottom:16px; }.filter-card :deep(.el-card__body) { padding-bottom:4px; }
.batch-card :deep(.el-pagination) { margin-top:18px; justify-content:flex-end; }
.wizard-panel { min-height:450px; padding:34px 10px 10px; }.wizard-panel h3 { margin-top:0; }
.preview-tools,.detail-actions { display:flex; justify-content:space-between; align-items:center; }
:deep(.preview-error td) { background:#fff1f0 !important; }:deep(.preview-warning td) { background:#fff7e6 !important; }
pre { padding:14px; overflow:auto; background:#f5f7f5; border:1px solid #dce3dc; } code { word-break:break-all; }
</style>

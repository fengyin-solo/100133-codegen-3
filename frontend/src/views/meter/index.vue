<template>
  <section class="page" data-module="meter">
    <header class="page-head">
      <div>
        <h2>仪表校准管理</h2>
        <p class="page-desc">统一判定口径：临近阈值自动待校准、停用报废不参与判定、同一编号校准记录以最近一次为准。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记仪表</button>
        <button class="btn" type="button" @click="recalculate">按新口径重标</button>
        <button class="btn" type="button" @click="exportRows">导出仪表校准清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>仪表编号</span>
        <input v-model="filters.keyword" placeholder="按仪表编号检索" />
      </label>
      <label class="filter-item">
        <span>仪表状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-abnormal': row.abnormal }">
          <td v-for="column in columns" :key="column" class="cell-detail" @click="openDetail(row)">
            <span v-if="column === '仪表状态'" class="status-tag" :data-status="String(row[column] ?? '')">{{ row[column] }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无仪表校准数据，可先登记仪表</td>
        </tr>
      </tbody>
    </table>

    <section v-if="detail" class="detail-panel">
      <header class="detail-head">
        <h3>仪表详情：{{ detail.仪表编号 }}（与台账同一判定口径）</h3>
        <button class="link" type="button" @click="closeDetail">收起</button>
      </header>
      <dl class="detail-grid">
        <template v-for="field in detailFields" :key="field">
          <dt>{{ field }}</dt>
          <dd>{{ detail[field] ?? '—' }}</dd>
        </template>
      </dl>
      <h4 class="detail-sub">校准记录<small>{{ calibrationNote }}</small></h4>
      <table class="data-table">
        <thead>
          <tr><th>校准日期</th><th>下次校准日</th><th>量程核验</th><th>登记人</th><th>判定采用</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in calibrations" :key="String(item.id)" :class="{ 'row-adopted': item.是否采用 }">
            <td>{{ item.校准日期 }}</td>
            <td>{{ item.下次校准日 }}</td>
            <td>{{ item.量程核验 }}</td>
            <td>{{ item.登记人 }}</td>
            <td>{{ item.是否采用 ? '✓ 当前采用' : '—' }}</td>
          </tr>
          <tr v-if="!calibrations.length">
            <td colspan="5" class="empty-state">暂无校准记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <div v-if="dialog" class="dialog-mask" @click.self="closeDialog">
      <form class="dialog" @submit.prevent="submitDialog">
        <h3>{{ dialog.mode === 'create' ? '登记仪表' : `校准登记：${dialog.row?.仪表编号 ?? ''}` }}</h3>
        <label v-for="field in dialogFields" :key="field.key" class="dialog-field">
          <span>{{ field.label }}</span>
          <select v-if="field.options" v-model="dialog.form[field.key]">
            <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
          </select>
          <input v-else v-model="dialog.form[field.key]" :type="field.type ?? 'text'" :placeholder="field.placeholder ?? ''" />
        </label>
        <p v-if="dialog.error" class="error-text">{{ dialog.error }}</p>
        <div class="dialog-actions">
          <button class="btn primary" type="submit">保存</button>
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条仪表校准记录</span>
      <span v-if="notice" class="ok-text">{{ notice }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

type DialogField = {
  key: string
  label: string
  type?: string
  placeholder?: string
  options?: string[]
}

type DialogState = {
  mode: 'create' | 'calibrate'
  row: Row | null
  form: Record<string, string>
  error: string
}

const ENDPOINT = '/api/meter'
const columns = ["仪表编号", "仪表名称", "安装位置", "测量参数", "仪表量程", "最近校准日", "下次校准日", "量程核验", "剩余天数", "预警阈值", "仪表状态", "判定结论"]
const actions = ["校准登记", "漂移预警", "停用仪表", "报废仪表", "启用仪表"]
const statuses = ["正常", "漂移预警", "待校准", "已停用", "已报废"]
const detailFields = ["仪表编号", "仪表名称", "安装位置", "测量参数", "仪表量程", "量程核验", "最近校准日", "下次校准日", "剩余天数", "预警阈值", "仪表状态", "判定结论"]
const createFields: DialogField[] = [
  { key: '仪表编号', label: '仪表编号', placeholder: '如 METE-0010' },
  { key: '仪表名称', label: '仪表名称' },
  { key: '安装位置', label: '安装位置', placeholder: '如 出水口在线间 / 化验室' },
  { key: '测量参数', label: '测量参数' },
  { key: '仪表量程', label: '仪表量程' },
  { key: '最近校准日', label: '最近校准日（首次校准可选）', type: 'date' },
  { key: '下次校准日', label: '下次校准日（首次校准可选）', type: 'date' },
  { key: '量程核验', label: '量程核验', options: ['符合', '不符'] },
]
const calibrateFields: DialogField[] = [
  { key: '校准日期', label: '校准日期', type: 'date' },
  { key: '下次校准日', label: '下次校准日', type: 'date' },
  { key: '量程核验', label: '量程核验', options: ['符合', '不符'] },
  { key: '登记人', label: '登记人' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<{ label: string; value: number }[]>([])
const errorMessage = ref('')
const notice = ref('')
const filters = ref({ keyword: '', status: '' })
const detail = ref<Row | null>(null)
const calibrations = ref<Row[]>([])
const calibrationNote = ref('')
const dialog = ref<DialogState | null>(null)

const dialogFields = computed(() => (dialog.value?.mode === 'calibrate' ? calibrateFields : createFields))

function todayText() {
  return new Date().toISOString().slice(0, 10)
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  dialog.value = { mode: 'create', row: null, error: '', form: { 量程核验: '符合' } }
}

function openCalibrate(row: Row) {
  dialog.value = { mode: 'calibrate', row, error: '', form: { 校准日期: todayText(), 量程核验: '符合' } }
}

function closeDialog() {
  dialog.value = null
}

async function parseResult(response: Response): Promise<{ ok: boolean; message: string }> {
  const payload = (await response.json().catch(() => ({}))) as { ok?: boolean; message?: string; detail?: string }
  if (!response.ok) {
    return { ok: false, message: payload.detail ?? `接口返回 ${response.status}` }
  }
  return { ok: Boolean(payload.ok), message: payload.message ?? '' }
}

async function submitDialog() {
  const current = dialog.value
  if (!current) return
  current.error = ''
  try {
    const isCreate = current.mode === 'create'
    const url = isCreate ? ENDPOINT : `${ENDPOINT}/${current.row?.id}/actions`
    const values = isCreate ? current.form : { action: '校准登记', ...current.form }
    const response = await request(url, { method: 'POST', body: JSON.stringify({ values }) })
    const result = await parseResult(response)
    if (!result.ok) {
      current.error = result.message || '保存被拦下，请检查填写内容'
      return
    }
    dialog.value = null
    notice.value = result.message
    await reload()
  } catch (error) {
    current.error = error instanceof Error ? error.message : '保存失败'
  }
}

async function runAction(action: string, row: Row) {
  if (action === '校准登记') {
    openCalibrate(row)
    return
  }
  if ((action === '停用仪表' || action === '报废仪表')
    && !window.confirm(`确认对 ${row.仪表编号} 执行「${action}」？停用与报废后不再参与到期判定。`)) {
    return
  }
  errorMessage.value = ''
  notice.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const result = await parseResult(response)
    if (!result.ok) {
      errorMessage.value = result.message || '动作被拦下'
      return
    }
    notice.value = result.message
    await reload()
    if (detail.value && detail.value.id === row.id) {
      await openDetail(row)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '仪表校准操作失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const [detailResp, calibrationResp] = await Promise.all([
      request(`${ENDPOINT}/${row.id}`),
      request(`${ENDPOINT}/${row.id}/calibrations`),
    ])
    if (!detailResp.ok) {
      throw new Error('仪表详情读取失败')
    }
    detail.value = (await detailResp.json()) as Row
    if (calibrationResp.ok) {
      const payload = (await calibrationResp.json()) as { items?: Row[]; 判定口径?: string }
      calibrations.value = payload.items ?? []
      calibrationNote.value = payload.判定口径 ?? ''
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '仪表详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
  calibrations.value = []
}

async function recalculate() {
  errorMessage.value = ''
  notice.value = ''
  try {
    const response = await request(`${ENDPOINT}/recalculate`, { method: 'POST', body: JSON.stringify({ values: {} }) })
    const result = await parseResult(response)
    if (!result.ok) {
      errorMessage.value = result.message || '重标失败'
      return
    }
    notice.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重标失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const payload = (await response.json()) as Record<string, number>
    stats.value = [
      { label: '正常仪表', value: payload['正常'] ?? 0 },
      { label: '待校仪表', value: payload['待校准'] ?? 0 },
      { label: '漂移预警', value: payload['漂移预警'] ?? 0 },
      { label: '停用/报废', value: (payload['已停用'] ?? 0) + (payload['已报废'] ?? 0) },
      { label: '异常仪表', value: payload['异常'] ?? 0 },
    ]
  } catch {
    stats.value = []
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('仪表列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '仪表校准列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.cell-detail { cursor: pointer; }
.row-abnormal td { background: #fff5f5; }
.status-tag { padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #eef2f7; white-space: nowrap; }
.status-tag[data-status='正常'] { background: #dcfce7; color: #166534; }
.status-tag[data-status='待校准'] { background: #fef3c7; color: #92400e; }
.status-tag[data-status='漂移预警'] { background: #fee2e2; color: #991b1b; }
.status-tag[data-status='已停用'], .status-tag[data-status='已报废'] { background: #e5e7eb; color: #4b5563; }
.detail-panel { margin-top: 12px; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; }
.detail-head { display: flex; justify-content: space-between; align-items: center; }
.detail-head h3 { margin: 0; font-size: 15px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, max-content 1fr); gap: 6px 16px; margin: 10px 0; }
.detail-grid dt { color: var(--muted); font-size: 12px; }
.detail-grid dd { margin: 0; font-size: 13px; }
.detail-sub { font-size: 14px; margin: 12px 0 6px; }
.detail-sub small { color: var(--muted); font-weight: normal; margin-left: 8px; }
.row-adopted td { background: #f0f7ff; }
.dialog-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.35); display: flex; align-items: center; justify-content: center; z-index: 10; }
.dialog { background: #fff; border-radius: 8px; padding: 16px 20px; width: 420px; display: flex; flex-direction: column; gap: 10px; }
.dialog h3 { margin: 0; font-size: 15px; }
.dialog-field span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 2px; }
.dialog-field input, .dialog-field select { width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.dialog-actions { display: flex; gap: 8px; justify-content: flex-end; }
.ok-text { color: #15803d; }
.filter-item select { padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px; }
</style>

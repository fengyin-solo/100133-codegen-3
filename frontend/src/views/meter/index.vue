<template>
  <section class="page" data-module="meter">
    <header class="page-head">
      <div>
        <h2>仪表校准管理</h2>
        <p class="page-desc">
          校准结论由系统按安装位置阈值统一判定：距下次校准日不足阈值的仪表自动标为「待校准」，
          停用与报废仪表不参与判定；校准记录同一编号以最近一次为准。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记仪表</button>
        <button class="btn" type="button" @click="openCalibration()">校准登记</button>
        <button class="btn" type="button" @click="openThresholds()">阈值配置</button>
        <button class="btn" type="button" @click="reevaluate">按新口径重标</button>
        <button class="btn" type="button" @click="exportRows">导出清单</button>
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
        <span>校准结论</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="dueHint" class="due-hint">
      有 <strong>{{ dueHint.count }}</strong> 台仪表距下次校准日不足阈值，已自动标记为「待校准」：{{ dueHint.nos }}
    </p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>剩余天数</th>
          <th>判定原因</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-due': row.仪表状态 === '待校准' }">
          <td v-for="column in columns" :key="column">
            <a v-if="column === '仪表编号'" class="link" @click="openDetail(row)">{{ row[column] ?? '—' }}</a>
            <span v-else :class="{ 'badge-due': column === '仪表状态' && row[column] === '待校准' }">{{ row[column] ?? '—' }}</span>
          </td>
          <td>{{ formatRemaining(row) }}</td>
          <td class="reason-cell">{{ row.判定原因 ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button class="link" type="button" @click="openCalibration(row)">校准登记</button>
            <button
              v-if="row.生命周期状态 === '在用'"
              class="link" type="button"
              @click="runAction('停用', row)"
            >停用</button>
            <button v-else class="link" type="button" @click="runAction('启用', row)">启用</button>
            <button
              v-if="row.生命周期状态 !== '报废'"
              class="link danger" type="button"
              @click="runAction('报废', row)"
            >报废</button>
            <button
              v-if="row.生命周期状态 === '在用' && !row.漂移标记"
              class="link" type="button"
              @click="toggleDrift(row, true)"
            >漂移预警</button>
            <button v-else-if="row.漂移标记" class="link" type="button" @click="toggleDrift(row, false)">解除漂移</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无仪表数据，可先登记仪表</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 台仪表</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <!-- 登记仪表 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记仪表</h3>
        <p class="modal-tip">校准日期不在此填写，登记后请通过「校准登记」写入，避免人工随意改动。</p>
        <label v-for="f in meterFormFields" :key="f.key" class="form-item">
          <span>{{ f.label }}<em v-if="f.required">*</em></span>
          <input v-model="createForm[f.key]" :placeholder="f.placeholder" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="submit">保存</button>
        </div>
      </form>
    </div>

    <!-- 校准登记 -->
    <div v-if="showCalibration" class="modal-mask" @click.self="showCalibration = false">
      <form class="modal" @submit.prevent="submitCalibration">
        <h3>校准登记</h3>
        <p class="modal-tip">
          最近校准日晚于下次校准日、或校准时量程与台账不符且仪表仍在使用时，系统会拦下并说明原因。
          同一仪表编号以最近一次校准为准。
        </p>
        <label class="form-item">
          <span>仪表编号<em>*</em></span>
          <input v-model="calForm.仪表编号" list="meter-no-list" placeholder="如 METE-0001" />
          <datalist id="meter-no-list">
            <option v-for="row in rows" :key="String(row.id)" :value="String(row.仪表编号)"></option>
          </datalist>
        </label>
        <label class="form-item">
          <span>校准日期<em>*</em></span>
          <input v-model="calForm.校准日期" type="date" />
        </label>
        <label class="form-item">
          <span>下次校准日<em>*</em></span>
          <input v-model="calForm.下次校准日" type="date" />
        </label>
        <label class="form-item">
          <span>校准时量程</span>
          <input v-model="calForm.校准时量程" placeholder="如 0-500 mg/L，须与台账量程一致" />
        </label>
        <label class="form-item">
          <span>校准人员</span>
          <input v-model="calForm.校准人员" />
        </label>
        <div class="modal-actions">
          <button class="btn" type="button" @click="showCalibration = false">取消</button>
          <button class="btn primary" type="submit">保存校准记录</button>
        </div>
      </form>
    </div>

    <!-- 仪表明细 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal modal-wide">
        <h3>仪表明细 · {{ detail.仪表编号 }}</h3>
        <div class="detail-grid">
          <span v-for="f in detailFields" :key="f">
            <em>{{ f }}</em>{{ detail[f] ?? '—' }}
          </span>
          <span>
            <em>到期阈值</em>{{ detail.到期阈值天数 }} 天
          </span>
          <span>
            <em>判定原因</em>{{ detail.判定原因 }}
          </span>
        </div>
        <h4>校准记录（{{ detail.校准记录?.length ?? 0 }} 条，最近一次在最前）</h4>
        <table class="data-table inner">
          <thead>
            <tr>
              <th>校准日期</th>
              <th>下次校准日</th>
              <th>校准时量程</th>
              <th>校准人员</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(rec, idx) in detail.校准记录" :key="rec.id" :class="{ 'latest-record': idx === 0 }">
              <td>{{ rec.校准日期 }}</td>
              <td>{{ rec.下次校准日 }}</td>
              <td>{{ rec.校准时量程 }}</td>
              <td>{{ rec.校准人员 }}</td>
            </tr>
            <tr v-if="!(detail.校准记录?.length)">
              <td colspan="4" class="empty-state">暂无校准记录</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 阈值配置 -->
    <div v-if="showThresholds" class="modal-mask" @click.self="showThresholds = false">
      <div class="modal">
        <h3>到期阈值配置（按安装位置）</h3>
        <p class="modal-tip">默认阈值 {{ thresholds.默认阈值天数 }} 天；位置未单独配置时走默认值。调整后存量仪表立即重标。</p>
        <table class="data-table inner">
          <thead>
            <tr><th>安装位置</th><th>阈值（天）</th></tr>
          </thead>
          <tbody>
            <tr v-for="(days, loc) in thresholds.安装位置阈值" :key="String(loc)">
              <td>{{ loc }}</td>
              <td>{{ days }}</td>
            </tr>
          </tbody>
        </table>
        <div class="form-item inline">
          <input v-model="thresholdForm.安装位置" placeholder="安装位置，如 进水仪表间" />
          <input v-model.number="thresholdForm.阈值天数" type="number" min="1" placeholder="阈值天数" />
          <button class="btn primary" type="button" @click="saveThreshold">保存并立即重标</button>
        </div>
        <div class="modal-actions">
          <button class="btn" type="button" @click="showThresholds = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type CalibrationRecord = {
  id: number
  仪表编号: string
  校准日期: string
  下次校准日: string
  校准时量程: string | null
  校准人员: string | null
}
type DetailRow = Row & { 校准记录?: CalibrationRecord[] | null }

const ENDPOINT = '/api/meter'
const columns = ['仪表编号', '仪表名称', '安装位置', '测量参数', '仪表量程', '最近校准日', '下次校准日', '仪表状态']
const statuses = ['正常', '漂移预警', '待校准', '停用中', '已报废']
const detailFields = ['仪表名称', '安装位置', '测量参数', '仪表量程', '生命周期状态', '最近校准日', '下次校准日', '仪表状态', '距下次校准天数']
const meterFormFields = [
  { key: '仪表编号', label: '仪表编号', required: true, placeholder: '如 METE-0008' },
  { key: '仪表名称', label: '仪表名称', required: true, placeholder: '如 进水COD在线分析仪' },
  { key: '安装位置', label: '安装位置', required: true, placeholder: '如 进水仪表间（决定阈值）' },
  { key: '测量参数', label: '测量参数', required: false, placeholder: '如 COD' },
  { key: '仪表量程', label: '仪表量程', required: false, placeholder: '如 0-500 mg/L' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const messageOk = ref(false)
const filters = ref<Record<string, string>>({ keyword: '', status: '' })

const showCreate = ref(false)
const showCalibration = ref(false)
const showThresholds = ref(false)
const detail = ref<DetailRow | null>(null)

const createForm = reactive<Record<string, string>>({})
const calForm = reactive<Record<string, string>>({ 仪表编号: '', 校准日期: '', 下次校准日: '', 校准时量程: '', 校准人员: '' })
const thresholdForm = reactive({ 安装位置: '', 阈值天数: 30 })
const thresholds = ref<{ 默认阈值天数: number; 安装位置阈值: Record<string, number> }>({ 默认阈值天数: 30, 安装位置阈值: {} })

const stats = computed(() => {
  const count = (s: string) => rows.value.filter((r) => r.仪表状态 === s).length
  return [
    { label: '正常仪表', value: count('正常') + count('漂移预警') },
    { label: '待校准', value: count('待校准') },
    { label: '停用/报废', value: count('停用中') + count('已报废') },
  ]
})

const dueHint = computed(() => {
  const due = rows.value.filter((r) => r.仪表状态 === '待校准')
  if (!due.length) return null
  return { count: due.length, nos: due.map((r) => String(r.仪表编号)).join('、') }
})

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function formatRemaining(row: Row) {
  const v = row.距下次校准天数
  if (v === null || v === undefined || v === '') return '—'
  return Number(v) < 0 ? `已逾期 ${-Number(v)} 天` : `${v} 天`
}

async function reload() {
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('仪表列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    flash(error instanceof Error ? error.message : '仪表列表读取失败', false)
  }
}

async function postJson(path: string, body: unknown) {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return response.json() as Promise<{ ok: boolean; message: string; entry?: unknown }>
}

function openCreate() {
  Object.keys(createForm).forEach((k) => delete createForm[k])
  showCreate.value = true
}

async function submitCreate() {
  const result = await postJson(ENDPOINT, { values: { ...createForm } })
  flash(result.message, result.ok)
  if (result.ok) {
    showCreate.value = false
    await reload()
  }
}

function openCalibration(row?: Row) {
  Object.assign(calForm, { 仪表编号: row ? String(row.仪表编号 ?? '') : '', 校准日期: '', 下次校准日: '', 校准时量程: '', 校准人员: '' })
  showCalibration.value = true
}

async function submitCalibration() {
  const result = await postJson(`${ENDPOINT}/calibrations`, { values: { ...calForm } })
  flash(result.message, result.ok)
  if (result.ok) {
    showCalibration.value = false
    await reload()
  }
}

async function runAction(action: string, row: Row) {
  const result = await postJson(`${ENDPOINT}/${row.id}/actions`, { action })
  flash(result.message, result.ok)
  await reload()
}

async function toggleDrift(row: Row, flagged: boolean) {
  const response = await request(`${ENDPOINT}/${row.id}/drift`, {
    method: 'POST',
    body: JSON.stringify({ values: { flagged } }),
  })
  const result = await response.json()
  flash(result.message, result.ok)
  await reload()
}

async function openDetail(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('仪表明细读取失败')
    detail.value = (await response.json()) as DetailRow
  } catch (error) {
    flash(error instanceof Error ? error.message : '仪表明细读取失败', false)
  }
}

async function loadThresholds() {
  try {
    const response = await request(`${ENDPOINT}/thresholds`)
    if (response.ok) thresholds.value = await response.json()
  } catch {
    // 阈值读取失败不阻塞列表页
  }
}

async function openThresholds() {
  await loadThresholds()
  showThresholds.value = true
}

async function saveThreshold() {
  if (!thresholdForm.安装位置.trim() || !thresholdForm.阈值天数) {
    flash('请填写安装位置与阈值天数', false)
    return
  }
  try {
    const response = await request(`${ENDPOINT}/thresholds`, {
      method: 'PUT',
      body: JSON.stringify({ values: { 安装位置: thresholdForm.安装位置, 阈值天数: thresholdForm.阈值天数 } }),
    })
    const result = await response.json()
    flash(result.message, result.ok)
    if (result.ok) {
      thresholdForm.安装位置 = ''
      await loadThresholds()
      await reload()
    }
  } catch (error) {
    flash(error instanceof Error ? error.message : '阈值保存失败', false)
  }
}

async function reevaluate() {
  const result = await postJson(`${ENDPOINT}/reevaluate`, {})
  flash(result.message, result.ok)
  await reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

onMounted(() => {
  void reload()
  void loadThresholds()
})
</script>

<style scoped>
.due-hint {
  margin: 8px 0;
  padding: 8px 12px;
  border: 1px solid #e0a800;
  background: #fff8e1;
  color: #8a6100;
  border-radius: 6px;
  font-size: 13px;
}
.row-due {
  background: #fff5f5;
}
.badge-due {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  background: #e05a3f;
  color: #fff;
  font-size: 12px;
}
.reason-cell {
  font-size: 12px;
  color: #666;
  max-width: 280px;
}
.ok-text {
  color: #1f8a4d;
}
.link.danger {
  color: #c0392b;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: #fff;
  border-radius: 8px;
  padding: 20px 24px;
  width: 420px;
  max-height: 86vh;
  overflow: auto;
}
.modal-wide {
  width: 720px;
}
.modal h3 {
  margin: 0 0 8px;
}
.modal h4 {
  margin: 16px 0 8px;
}
.modal-tip {
  font-size: 12px;
  color: #777;
  margin: 0 0 12px;
}
.form-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
  font-size: 13px;
}
.form-item em {
  color: #c0392b;
  font-style: normal;
}
.form-item.inline {
  flex-direction: row;
  gap: 8px;
  align-items: center;
}
.form-item.inline input {
  flex: 1;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px 16px;
  font-size: 13px;
  margin-bottom: 8px;
}
.detail-grid span {
  display: flex;
  flex-direction: column;
}
.detail-grid em {
  font-style: normal;
  color: #999;
  font-size: 12px;
}
.data-table.inner {
  font-size: 12px;
}
.latest-record {
  background: #f0f7ff;
  font-weight: 600;
}
</style>

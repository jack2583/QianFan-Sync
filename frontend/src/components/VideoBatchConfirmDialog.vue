<template>
  <el-dialog
    :model-value="visible"
    width="860px"
    top="6vh"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <template #header>
      <div class="vbc-dialog-header">
        <span class="vbc-dialog-title">批量发布确认</span>
        <el-tooltip content="引导" placement="top">
          <button class="vbc-guide-btn" type="button" @click="startGuide">
            <el-icon><QuestionFilled /></el-icon>
          </button>
        </el-tooltip>
      </div>
    </template>
    <div v-if="rows.length === 0" class="empty">队列为空</div>
    <template v-else>
      <!-- ── 顶部统计条：结果一目了然，可点击筛选 ── -->
      <div class="stat-bar" data-tour="vbc-stats">
        <div class="stat-chips">
          <button
            :class="['stat-chip', 'is-all', { 'is-active': filter === 'all' }]"
            @click="filter = 'all'"
          >全部 {{ rows.length }}</button>
          <button
            :class="['stat-chip', 'is-ok', { 'is-active': filter === 'ok' }]"
            @click="filter = 'ok'"
          >
            <el-icon><CircleCheckFilled /></el-icon>可发布 {{ okCount }}
          </button>
          <button
            v-if="failedCount > 0"
            :class="['stat-chip', 'is-fail', { 'is-active': filter === 'failed' }]"
            @click="filter = 'failed'"
          >
            <el-icon><CircleCloseFilled /></el-icon>待处理 {{ failedCount }}
          </button>
        </div>
        <div class="stat-right">
          预计产生 <b>{{ estimatedAllTasks }}</b> 个发布任务
        </div>
      </div>

      <!-- ── 视频卡片列表 ── -->
      <div class="video-list">
        <div
          v-for="(row, i) in filteredRows"
          :key="row.index"
          :data-tour="i === 0 ? 'vbc-video-card' : undefined"
          :class="['video-card', {
            'is-selected': selectedIndexes.includes(row.index),
            'is-failed': row.errors.length > 0,
          }]"
          :role="row.errors.length ? undefined : 'checkbox'"
          :aria-checked="row.errors.length ? undefined : selectedIndexes.includes(row.index)"
          @click="row.errors.length === 0 && toggleRow(row.index)"
        >
          <!-- 勾选区 -->
          <div class="card-check">
            <el-checkbox
              :model-value="selectedIndexes.includes(row.index)"
              :disabled="row.errors.length > 0"
              @click.stop
              @change="(val) => toggleRow(row.index, val)"
            />
          </div>

          <!-- 视频信息 -->
          <div class="video-cell">
            <div class="video-thumb">
              <img v-if="row.coverUrl" :src="row.coverUrl" alt="" />
              <el-icon v-else :size="18"><VideoCameraFilled /></el-icon>
            </div>
            <div class="video-info">
              <div class="video-name" :title="row.name">{{ row.name }}</div>
              <div class="video-title" :title="row.title">{{ row.title || '（无标题）' }}</div>
            </div>
          </div>

          <!-- 元信息 -->
          <div class="card-meta">
            <span class="meta-item">{{ row.accountCount }} 个账号</span>
            <span class="meta-item">{{ row.hasSchedule ? '定时发布' : '立即发布' }}</span>
          </div>

          <!-- 状态 -->
          <div class="card-status">
            <el-tag v-if="row.errors.length === 0" type="success" size="small" effect="light" round>
              <el-icon class="tag-icon"><CircleCheckFilled /></el-icon>可发布
            </el-tag>
            <el-tag v-else type="danger" size="small" effect="light" round>
              <el-icon class="tag-icon"><CircleCloseFilled /></el-icon>{{ row.errors.length }} 个问题
            </el-tag>
          </div>

          <!-- ── 问题详情：直接内联展示，不用展开行 ── -->
          <div v-if="row.errors.length > 0" class="card-errors" @click.stop>
            <div v-for="(e, i) in row.errors" :key="i" class="err-block">
              <div class="err-head">
                <span class="err-type">{{ errType(e) }}</span>
                <span v-if="errHint(e)" class="err-hint">{{ errHint(e) }}</span>
              </div>
              <div v-if="errAccounts(e).length" class="err-accounts">
                <span class="err-accounts-label">影响账号（{{ errAccounts(e).length }}）</span>
                <el-tag
                  v-for="a in errAccounts(e)"
                  :key="a"
                  type="danger"
                  effect="plain"
                  size="small"
                  class="err-account-tag"
                >{{ a }}</el-tag>
              </div>
            </div>
          </div>
        </div>

        <div v-if="filteredRows.length === 0" class="empty">该分类下没有视频</div>
      </div>

      <!-- ── 操作间隔：始终显示，默认 30 分钟，避免连续操作触发平台风控 ── -->
      <div class="interval-row" data-tour="vbc-interval">
        <el-icon class="interval-icon"><Timer /></el-icon>
        <span class="interval-label">发布间隔</span>
        <el-input-number
          v-model="intervalMinutes"
          :min="0"
          :max="120"
          :step="1"
          controls-position="right"
          style="width: 110px"
        />
        <span class="interval-unit">分钟</span>
        <el-tooltip placement="top">
          <template #content>
            每操作完一个视频等待指定分钟数再操作下一个，避免连续操作触发平台风控。<br />
            默认 30 分钟。此间隔控制浏览器自动化操作节奏，与下方自动定时的平台定时时刻互不影响。<br />
            填 0 表示立即操作下一个（不推荐，易触发风控）。仅对本次批量生效。
          </template>
          <el-icon class="interval-help"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>

      <!-- ── 自动定时 ── -->
      <div class="autosched-box" data-tour="vbc-autoschedule">
        <div class="autosched-head">
          <el-switch v-model="autoEnabled" />
          <span class="autosched-title">自动定时</span>
          <el-tooltip placement="top">
            <template #content>
              按起始时间与间隔，自动算出每个「视频 × 平台」的定时发布时间并填入各平台。<br />
              上方的「发布间隔」仍照常生效（控制操作节奏、避免连续操作触发风控），与平台定时时刻互不影响。
            </template>
            <el-icon class="autosched-help"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>

        <template v-if="autoEnabled">
          <div class="autosched-params">
            <div class="aparam">
              <span class="aparam-label">起始发布时间</span>
              <el-date-picker
                v-model="startAt"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm:ss"
                format="YYYY-MM-DD HH:mm:ss"
                placeholder="选择时间"
                :disabled-date="scheduleDisabledDate"
                :disabled-hours="scheduleDisabledHours"
                :clearable="false"
                style="width: 210px"
              />
            </div>
            <div class="aparam">
              <span class="aparam-label">不同视频间隔</span>
              <el-input-number v-model="videoInterval" :min="1" :max="1440" :step="1" controls-position="right" style="width: 110px" />
              <span class="aparam-unit">分钟</span>
            </div>
            <div class="aparam">
              <span class="aparam-label">同视频不同平台间隔</span>
              <el-input-number v-model="platformInterval" :min="1" :max="240" :step="1" controls-position="right" style="width: 110px" />
              <span class="aparam-unit">分钟</span>
            </div>
          </div>

          <!-- 校验错误：禁止提交并逐条提示 -->
          <div v-if="autoPlan && autoPlan.errors.length > 0" class="autosched-errors">
            <div class="aserr-head">排程不通过，请调整参数后重试（共 {{ autoPlan.errors.length }} 处）：</div>
            <div v-for="(e, i) in autoPlan.errors.slice(0, 8)" :key="i" class="aserr-line">
              视频{{ e.videoOrder + 1 }} · {{ e.platformName }}({{ e.accountName }}) {{ e.timeStr }} — {{ e.reason }}
            </div>
            <div v-if="autoPlan.errors.length > 8" class="aserr-more">……还有 {{ autoPlan.errors.length - 8 }} 处</div>
          </div>

          <!-- 排程预览（前 8 条） -->
          <div v-else-if="autoPlan && autoPlan.preview.length > 0" class="autosched-preview">
            <div class="asprev-head">排程预览（前 {{ autoPlan.preview.length }} 条，共 {{ autoPlan.assignments.length }} 个任务）</div>
            <div v-for="(line, i) in autoPlan.preview" :key="i" class="asprev-line">{{ line }}</div>
            <div v-if="autoPlan.assignments.length > autoPlan.preview.length" class="asprev-more">……其余 {{ autoPlan.assignments.length - autoPlan.preview.length }} 条</div>
          </div>
        </template>
      </div>
    </template>

    <template #footer>
      <div class="footer-row">
        <div class="footer-summary">
          <template v-if="rows.length > 0">
            已选 <b>{{ selectedIndexes.length }}</b> / {{ rows.length }} 个视频
            <template v-if="failedCount > 0">
              · <span class="summary-fail">{{ failedCount }} 个视频需先修复上方问题</span>
            </template>
            <span class="hint">（提交后可关闭页面，任务在后端继续执行）</span>
          </template>
        </div>
        <div class="footer-btns">
          <el-button @click="$emit('update:visible', false)" :disabled="submitting">取消</el-button>
          <el-button
            type="primary"
            data-tour="vbc-submit"
            :disabled="selectedIndexes.length === 0 || scheduleInvalid"
            :loading="submitting"
            @click="onConfirm"
          >
            发布 {{ selectedIndexes.length }} 个视频
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>

  <!-- 发布流程引导（teleport 到 body；流程中弹窗不自动播放，仅标题栏「?」按需查看） -->
  <GuideTour
    ref="vbcTourRef"
    :steps="videoConfirmGuideSteps"
  />
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { VideoCameraFilled, CircleCheckFilled, CircleCloseFilled, Timer, QuestionFilled } from '@element-plus/icons-vue'
import GuideTour from '@/components/GuideTour.vue'
import { videoConfirmGuideSteps } from '@/config/guides'
import {
  computeAutoSchedule,
  defaultStartAt,
} from '@/utils/autoSchedule'

const props = defineProps({
  visible: { type: Boolean, default: false },
  // [{index, name, coverUrl, title, accountCount, hasSchedule, errors: []}]
  // errors 项为 { type, hint, accounts }（兼容旧版纯文本字符串）
  rows: { type: Array, default: () => [] },
  submitting: { type: Boolean, default: false },
})

const emit = defineEmits(['update:visible', 'confirm'])

const selectedIndexes = ref([])
// 筛选：all / ok / failed
const filter = ref('all')
// 本次批量发布的视频间隔（分钟）。0 = 立即开始下一个；>0 = 等满分钟再发下一个。
// 仅本次批量生效，不影响 settings.batchTaskInterval 全局值。
// 默认 30 分钟：避免平台风控（用户反馈：默认 0 太隐蔽，容易忘记设置）。
const intervalMinutes = ref(30)

// ── 自动定时 ──
const autoEnabled = ref(false)
const startAt = ref(defaultStartAt())
const videoInterval = ref(60)
const platformInterval = ref(15)

// rows 由父组件构造，每项含 accounts: [{id, platformKey, platformName, accountName}]
const autoPlan = computed(() => {
  if (!autoEnabled.value) return null
  return computeAutoSchedule({
    rows: props.rows,
    selectedIndexes: selectedIndexes.value,
    startAt: startAt.value,
    videoInterval: videoInterval.value,
    platformInterval: platformInterval.value,
  })
})
const scheduleInvalid = computed(() => !!autoPlan.value && autoPlan.value.errors.length > 0)

// 起始时间选择器：禁止选今天之前 / 超过 14 天；当天禁止选 06:00 前与 22:00 后的小时
function scheduleDisabledDate(date) {
  if (!date) return false
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const max = new Date(startOfToday)
  max.setDate(max.getDate() + 14)
  return date < startOfToday || date > max
}
function scheduleDisabledHours() {
  return Array.from({ length: 24 }, (_, h) => h).filter((h) => h < 6 || h > 22)
}

const okCount = computed(() => props.rows.filter((r) => r.errors.length === 0).length)
const failedCount = computed(() => props.rows.length - okCount.value)

// ========== 弹窗新手引导（流程中弹窗：仅标题栏「?」按需查看，不自动播放） ==========
const vbcTourRef = ref(null)
const startGuide = () => vbcTourRef.value?.start()
const estimatedAllTasks = computed(() =>
  props.rows.reduce((sum, r) => sum + (r.accountCount || 0), 0)
)

const filteredRows = computed(() => {
  if (filter.value === 'ok') return props.rows.filter((r) => r.errors.length === 0)
  if (filter.value === 'failed') return props.rows.filter((r) => r.errors.length > 0)
  return props.rows
})

// 每次打开：勾选全部可发布视频、默认展示全部（问题已内联，无需定位）
watch(
  () => props.visible,
  (vis) => {
    if (vis) {
      filter.value = 'all'
      selectedIndexes.value = props.rows
        .filter((r) => r.errors.length === 0)
        .map((r) => r.index)
    } else {
      // 保险：弹窗关闭时结束可能还开着的引导
      vbcTourRef.value?.stop()
    }
  },
  { immediate: true }
)

const estimatedTasks = computed(() =>
  props.rows
    .filter((r) => selectedIndexes.value.includes(r.index))
    .reduce((sum, r) => sum + (r.accountCount || 0), 0)
)
// 保留在 summary 里显示已选任务量
void estimatedTasks

function toggleRow(index, checked) {
  const has = selectedIndexes.value.includes(index)
  if (checked === undefined) {
    // 整卡点击 = 切换
    if (has) selectedIndexes.value = selectedIndexes.value.filter((i) => i !== index)
    else selectedIndexes.value = [...selectedIndexes.value, index]
    return
  }
  if (checked && !has) selectedIndexes.value = [...selectedIndexes.value, index]
  if (!checked && has) selectedIndexes.value = selectedIndexes.value.filter((i) => i !== index)
}

// 兼容新旧两种错误格式
function errType(e) { return typeof e === 'string' ? '问题' : e.type }
function errHint(e) { return typeof e === 'string' ? e : (e.hint || '') }
function errAccounts(e) { return typeof e === 'string' ? [] : (e.accounts || []) }

function onConfirm() {
  if (selectedIndexes.value.length === 0) return
  // 自动定时排程校验不通过 → 禁止提交
  if (autoEnabled.value && scheduleInvalid.value) return
  // 父组件读取数值并传给后端（仅本次批量生效）。
  // el-input-number 已限制 min=0，组件无需重复校验。
  emit('confirm', {
    selectedIndexes: [...selectedIndexes.value],
    // 发布间隔（操作间隔）始终生效，默认 30 分钟，避免连续操作触发平台风控。
    // 自动定时只决定平台网页的定时时刻，不替代操作间隔。
    intervalMinutes: Number(intervalMinutes.value) || 0,
    autoSchedule: autoEnabled.value && autoPlan.value
      ? {
        enabled: true,
        start_at: startAt.value,
        video_interval_minutes: Number(videoInterval.value) || 0,
        platform_interval_minutes: Number(platformInterval.value) || 0,
      }
      : null,
  })
}
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

// 自定义 header（#header 插槽内容编译自本组件，scoped 直接命中）：
// 标题 + 「?」引导按钮，padding-right 给右上角关闭按钮留位
.vbc-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 32px;
}

.vbc-dialog-title {
  font-size: 18px;
  font-weight: 600;
  color: $text-primary;
}

.vbc-guide-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px dashed rgba($overlay-rgb, 0.28);
  border-radius: 50%;
  background: transparent;
  color: $text-muted;
  font-size: 13px;
  cursor: pointer;
  padding: 0;
  transition: all $transition-fast;

  &:hover {
    color: $brand-start;
    border-color: rgba($brand-start, 0.5);
    background: rgba($brand-start, 0.08);
  }
}

.empty {
  text-align: center;
  color: $text-muted;
  padding: 40px 0;
}

// ── 顶部统计条 ──
.stat-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;

  .stat-chips {
    display: flex;
    gap: 8px;
  }

  .stat-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 5px 14px;
    border-radius: 999px;
    border: 1px solid $border;
    background: $bg-surface;
    font-size: 13px;
    color: $text-secondary;
    cursor: pointer;
    transition: all 0.15s;

    &:hover { border-color: $brand-start; }

    &.is-active {
      border-color: $brand-start;
      background: rgba($brand-start, 0.08);
      color: $brand-start;
      font-weight: 600;
    }

    &.is-ok .el-icon { color: $success-color; }
    &.is-fail .el-icon { color: $danger-color; }
  }

  .stat-right {
    font-size: 13px;
    color: $text-secondary;

    b { color: $brand-start; }
  }
}

// ── 视频卡片列表 ──
.video-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 46vh;
  overflow-y: auto;
  padding: 2px 4px 2px 2px;
}

.video-card {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  grid-template-areas:
    'check video meta status'
    'errors errors errors errors';
  align-items: center;
  gap: 6px 12px;
  padding: 10px 14px;
  background: $bg-surface;
  border: 1px solid $border;
  border-radius: 10px;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;

  &:not(.is-failed) {
    cursor: pointer;

    &:hover { border-color: $brand-start; }
  }

  &.is-selected {
    border-color: $brand-start;
    background: rgba($brand-start, 0.04);
    box-shadow: 0 0 0 1px $brand-start inset;
  }

  &.is-failed {
    border-left: 3px solid $danger-color;
    background: rgba($danger-color, 0.03);
    cursor: default;
  }

  .card-check {
    grid-area: check;
    display: flex;
    align-items: center;
  }

  .card-meta {
    grid-area: meta;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;

    .meta-item {
      font-size: 12px;
      color: $text-muted;
      white-space: nowrap;
    }
  }

  .card-status {
    grid-area: status;
    display: flex;
    align-items: center;

    .tag-icon {
      margin-right: 3px;
    }
  }
}

.video-cell {
  grid-area: video;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;

  .video-thumb {
    width: 64px;
    height: 36px;
    border-radius: 6px;
    overflow: hidden;
    flex-shrink: 0;
    background: rgba($overlay-rgb, 0.06);
    display: flex;
    align-items: center;
    justify-content: center;
    color: $text-muted;

    img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
  }

  .video-info {
    min-width: 0;

    .video-name {
      font-size: 13px;
      font-weight: 500;
      color: $text-primary;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 340px;
    }

    .video-title {
      font-size: 12px;
      color: $text-muted;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 340px;
      margin-top: 2px;
    }
  }
}

// ── 内联错误详情 ──
.card-errors {
  grid-area: errors;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 4px;
  padding: 10px 12px;
  background: rgba($danger-color, 0.05);
  border-radius: 8px;

  .err-block {
    display: flex;
    flex-direction: column;
    gap: 6px;

    & + .err-block {
      padding-top: 8px;
      border-top: 1px dashed rgba($danger-color, 0.2);
    }
  }

  .err-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    flex-wrap: wrap;

    .err-type {
      flex-shrink: 0;
      font-size: 13px;
      font-weight: 600;
      color: $danger-color;
    }

    .err-hint {
      font-size: 12px;
      color: $text-secondary;
      line-height: 1.6;
    }
  }

  .err-accounts {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;

    .err-accounts-label {
      font-size: 12px;
      color: $text-muted;
      flex-shrink: 0;
    }

    .err-account-tag {
      max-width: 240px;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  }
}

// ── 发布间隔 ──
.interval-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding: 10px 14px;
  background: rgba($warning-color, 0.06);
  border: 1px solid rgba($warning-color, 0.25);
  border-radius: 8px;

  .interval-icon { color: $warning-color; }
  .interval-label { font-size: 13px; font-weight: 500; color: $text-primary; }
  .interval-unit { font-size: 13px; color: $text-secondary; }

  .interval-help {
    color: $text-muted;
    cursor: help;

    &:hover { color: $text-secondary; }
  }
}

// ── 自动定时 ──
.autosched-box {
  margin-top: 14px;
  padding: 10px 14px;
  background: rgba($brand-start, 0.05);
  border: 1px solid rgba($brand-start, 0.22);
  border-radius: 8px;

  .autosched-head {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .autosched-title { font-size: 13px; font-weight: 500; color: $text-primary; }

  .autosched-help {
    color: $text-muted;
    cursor: help;
    &:hover { color: $text-secondary; }
  }
}

.autosched-params {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 20px;
  margin-top: 12px;

  .aparam {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .aparam-label { font-size: 13px; color: $text-secondary; }
  .aparam-unit { font-size: 13px; color: $text-secondary; }
}

.autosched-preview,
.autosched-errors {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.8;
  max-height: 180px;
  overflow-y: auto;
}

.autosched-preview {
  background: $bg-surface;
  border: 1px solid $border;

  .asprev-head { font-weight: 600; color: $text-primary; margin-bottom: 4px; }
  .asprev-line { color: $text-secondary; font-variant-numeric: tabular-nums; }
  .asprev-more { color: $text-muted; margin-top: 2px; }
}

.autosched-errors {
  background: rgba($danger-color, 0.06);
  border: 1px solid rgba($danger-color, 0.25);

  .aserr-head { font-weight: 600; color: $danger-color; margin-bottom: 4px; }
  .aserr-line { color: $text-secondary; font-variant-numeric: tabular-nums; }
  .aserr-more { color: $text-muted; margin-top: 2px; }
}

// ── 底部 ──
.footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;

  .footer-summary {
    flex: 1;
    font-size: 13px;
    color: $text-secondary;
    min-width: 0;

    b { color: $brand-start; }

    .summary-fail { color: $danger-color; }

    .hint {
      color: $text-muted;
      font-size: 12px;
      margin-left: 4px;
    }
  }

  .footer-btns {
    display: flex;
    gap: 10px;
    flex-shrink: 0;
  }
}
</style>

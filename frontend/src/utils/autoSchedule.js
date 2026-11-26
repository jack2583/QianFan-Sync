/**
 * 批量发布「自动定时」排程计算与校验（纯函数）
 *
 * 规则（见需求文档第四节）：
 *  T(i,j) = T0 + i×视频间隔 + j×平台间隔；若早于上一条任务时刻则顺延到该时刻（R3~R5）
 *  时间窗 06:00:00 ~ 22:00:00，越界禁止提交（R6~R9）
 *  各平台 scheduleTime 自身约束校验（R10~R12）
 *
 * 本模块只负责「算出每个『视频 × 平台』的定时时刻」，不涉及任何发布执行。
 * 调用方（VideoBatchConfirmDialog / PublishCenter）用返回的 assignments 把
 * timeStr 写入每个视频快照的 accountOverrides[accountId].scheduleTime。
 */

// 发布时间窗
export const SCHEDULE_WINDOW_START_HOUR = 6
export const SCHEDULE_WINDOW_END_HOUR = 22
// 发布页定时选择器全局上限（与 PublishCenter.scheduleDisabledDate 一致）
export const GLOBAL_MAX_DAYS = 14

/**
 * 各平台定时约束表（依据 platforms.js 中 scheduleTime 字段的 placeholder / disabledDate）
 *  - maxDays:     仅支持今天起 N 天内（按日期 00:00 计算）
 *  - maxMonths:   仅支持今天起 N 个月内
 *  - minLeadMin:  需晚于当前至少 N 分钟
 *  - stepMinutes: 分钟必须为 N 的倍数
 */
export const PLATFORM_RULES = {
  baijiahao: { maxDays: 7 },
  toutiao: { maxDays: 7 },
  dayu: { maxDays: 7, stepMinutes: 5 },
  zhihu: { maxMonths: 1 },
  weixin_gzh: { maxDays: 7, minLeadMin: 60 },
}

/** 'YYYY-MM-DD HH:mm:ss' → Date（本地时间）。兼容 Safari（把 '-' 换成 '/'） */
export function parseTime(str) {
  if (!str) return null
  const d = new Date(String(str).replace(/-/g, '/'))
  return isNaN(d.getTime()) ? null : d
}

/** Date → 'YYYY-MM-DD HH:mm:ss'（本地时间） */
export function formatTime(d) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
    + `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 起始时间默认值：当前时间向后取整到下一个整点；超出窗口则跳到下一个 06:00 */
export function defaultStartAt(now = new Date()) {
  const base = new Date(now)
  base.setSeconds(0, 0)
  base.setMinutes(0)
  const next = new Date(base.getTime() + 60 * 60 * 1000)
  if (next.getHours() >= SCHEDULE_WINDOW_START_HOUR && next.getHours() <= SCHEDULE_WINDOW_END_HOUR) {
    return formatTime(next)
  }
  // 落在窗口外 → 下一个 06:00（必须晚于 now）
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate(), SCHEDULE_WINDOW_START_HOUR, 0, 0)
  if (d.getTime() <= now.getTime()) d.setDate(d.getDate() + 1)
  return formatTime(d)
}

function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/**
 * 计算整批排程
 *
 * @param {object}   o
 * @param {Array}    o.rows            确认弹窗的行数据，每项需含 { index, accounts: [{id, platformKey, platformName, accountName}] }
 * @param {Array}    o.selectedIndexes 选中的行 index（未排序也可，内部升序）
 * @param {string}   o.startAt         'YYYY-MM-DD HH:mm:ss'
 * @param {number}   o.videoInterval   视频间隔（分钟）
 * @param {number}   o.platformInterval 平台间隔（分钟）
 * @param {Date}     o.now             基准当前时间（便于测试注入）
 * @returns {{assignments: Array, preview: Array<string>, errors: Array}}
 */
export function computeAutoSchedule({ rows, selectedIndexes, startAt, videoInterval, platformInterval, now = new Date() }) {
  const base = parseTime(startAt)
  const assignments = []
  const errors = []
  if (!base) {
    errors.push({ reason: '起始时间格式无效' })
    return { assignments, preview: [], errors }
  }

  const V = Math.max(0, Number(videoInterval) || 0)
  const P = Math.max(0, Number(platformInterval) || 0)
  const rowMap = new Map((rows || []).map((r) => [r.index, r]))
  const sorted = [...new Set(selectedIndexes || [])].sort((a, b) => a - b)
  const today0 = startOfDay(now)
  const globalMax = today0 + GLOBAL_MAX_DAYS * 86400000

  let lastTs = -Infinity
  sorted.forEach((rowIndex, i) => {
    const row = rowMap.get(rowIndex)
    if (!row) return
    const accounts = row.accounts || []
    accounts.forEach((acc, j) => {
      // R3/R4：基础时刻，早于上一条任务则顺延
      let ts = base.getTime() + (i * V + j * P) * 60000
      if (ts < lastTs) ts = lastTs
      lastTs = ts

      const d = new Date(ts)
      const timeStr = formatTime(d)
      assignments.push({
        videoOrder: i,
        rowIndex,
        accountId: acc.id,
        platformKey: acc.platformKey || '',
        platformName: acc.platformName || '',
        accountName: acc.accountName || '',
        timeStr,
        ts,
      })

      const err = (reason) => errors.push({
        videoOrder: i,
        rowIndex,
        platformName: acc.platformName || '',
        accountName: acc.accountName || '',
        timeStr,
        reason,
      })

      // R6~R9：发布时间窗 06:00:00 ~ 22:00:00
      const h = d.getHours()
      if (h < SCHEDULE_WINDOW_START_HOUR || h > SCHEDULE_WINDOW_END_HOUR
        || (h === SCHEDULE_WINDOW_END_HOUR && (d.getMinutes() > 0 || d.getSeconds() > 0))) {
        err(`超出发布时间窗（06:00~22:00）`)
        return
      }

      // 通用：必须晚于当前时间，且不超过全局 14 天
      if (ts <= now.getTime()) {
        err('定时时刻必须晚于当前时间')
        return
      }
      if (ts > globalMax) {
        err(`超出可选范围（${GLOBAL_MAX_DAYS} 天内）`)
        return
      }

      // R10~R12：平台自身约束
      const rule = PLATFORM_RULES[acc.platformKey]
      if (!rule) return
      if (rule.maxDays) {
        const max = today0 + rule.maxDays * 86400000
        if (ts < today0 || ts > max) {
          err(`${acc.platformName} 仅支持 ${rule.maxDays} 天内定时`)
          return
        }
      }
      if (rule.maxMonths) {
        const max = new Date(today0)
        max.setMonth(max.getMonth() + rule.maxMonths)
        if (ts > max.getTime()) {
          err(`${acc.platformName} 仅支持 ${rule.maxMonths} 个月内定时`)
          return
        }
      }
      if (rule.minLeadMin && ts - now.getTime() < rule.minLeadMin * 60000) {
        err(`${acc.platformName} 需晚于当前至少 ${rule.minLeadMin / 60} 小时`)
        return
      }
      if (rule.stepMinutes && d.getMinutes() % rule.stepMinutes !== 0) {
        err(`${acc.platformName} 定时分钟需为 ${rule.stepMinutes} 的倍数`)
      }
    })
  })

  const preview = assignments.slice(0, 8).map((a) =>
    `视频${a.videoOrder + 1} · ${a.platformName}(${a.accountName})   ${a.timeStr}`
  )
  return { assignments, preview, errors }
}

/**
 * 把排程结果写入视频快照的 accountOverrides[accountId].scheduleTime。
 * 返回写入后的新 videos 数组（不修改入参）。
 *
 * @param {Array} videos         batchPublishVideos 的 videos 快照数组（已按选中顺序排列）
 * @param {Array} assignments    computeAutoSchedule 的 assignments
 */
export function applyAutoScheduleToVideos(videos, assignments) {
  const byRow = new Map()
  for (const a of assignments) {
    if (!byRow.has(a.rowIndex)) byRow.set(a.rowIndex, {})
    byRow.get(a.rowIndex)[a.accountId] = a.timeStr
  }
  return (videos || []).map((v, rowIndex) => {
    const map = byRow.get(rowIndex)
    if (!map) return v
    const accountOverrides = { ...(v.accountOverrides || {}) }
    for (const [accountId, timeStr] of Object.entries(map)) {
      accountOverrides[accountId] = { ...(accountOverrides[accountId] || {}), scheduleTime: timeStr }
    }
    return { ...v, accountOverrides }
  })
}

import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import type { Citation } from './types'

dayjs.extend(utc)
dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

export function fmtTime(value?: string | null, format = 'YYYY-MM-DD HH:mm'): string {
  if (!value) return '-'
  return dayjs.utc(value).local().format(format)
}

export function fromNow(value?: string | null): string {
  if (!value) return '-'
  return dayjs.utc(value).local().fromNow()
}

export function locatorText(locator: Record<string, any> | undefined | null): string {
  if (!locator) return '正文'
  const parts: string[] = []
  if (locator.page_no) parts.push(`第 ${locator.page_no} 页`)
  if (locator.sheet_name) parts.push(`工作表「${locator.sheet_name}」`)
  if (locator.row_start) {
    const end = locator.row_end && locator.row_end !== locator.row_start ? `-${locator.row_end}` : ''
    parts.push(`第 ${locator.row_start}${end} 行`)
  }
  if (locator.heading_path) parts.push(String(locator.heading_path))
  return parts.length ? parts.join(' · ') : '正文'
}

export function sourceTitle(source: Citation): string {
  return source.doc_title || '知识库片段'
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export const STATUS_META: Record<string, { label: string; color: string; percent: number }> = {
  pending: { label: '排队中', color: 'default', percent: 5 },
  parsing: { label: '解析中', color: 'processing', percent: 25 },
  embedding: { label: '向量化', color: 'processing', percent: 65 },
  persisting: { label: '写入中', color: 'processing', percent: 90 },
  retrying: { label: '重试中', color: 'warning', percent: 40 },
  ready: { label: '已完成', color: 'success', percent: 100 },
  failed: { label: '失败', color: 'error', percent: 100 },
}

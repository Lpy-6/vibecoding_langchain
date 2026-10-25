import { describe, expect, it } from 'vitest'
import { STATUS_META, fmtTime, formatBytes, fromNow, locatorText } from './utils'

describe('locatorText', () => {
  it('falls back to 正文 for empty locators', () => {
    expect(locatorText(null)).toBe('正文')
    expect(locatorText({})).toBe('正文')
  })

  it('renders page and heading path', () => {
    expect(locatorText({ page_no: 3, heading_path: '售后 › 保修' })).toBe('第 3 页 · 售后 › 保修')
  })

  it('renders worksheet and row range', () => {
    expect(
      locatorText({ sheet_name: '价格表', row_start: 2, row_end: 6 }),
    ).toBe('工作表「价格表」 · 第 2-6 行')
  })

  it('collapses a single row without a range suffix', () => {
    expect(locatorText({ row_start: 5, row_end: 5 })).toBe('第 5 行')
  })
})

describe('formatBytes', () => {
  it('formats B / KB / MB', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
  })
})

describe('time helpers', () => {
  it('returns dash for missing values', () => {
    expect(fmtTime(null)).toBe('-')
    expect(fromNow(undefined)).toBe('-')
  })

  it('formats an ISO UTC string', () => {
    expect(fmtTime('2026-10-24T00:00:00')).toMatch(/2026-10-24/)
  })

  it('renders a relative time string', () => {
    expect(fromNow(new Date().toISOString())).toBeTruthy()
  })
})

describe('STATUS_META', () => {
  it('covers ingestion states and reaches 100% on terminal states', () => {
    expect(STATUS_META.ready.percent).toBe(100)
    expect(STATUS_META.failed.percent).toBe(100)
    expect(STATUS_META.uploading).toBeUndefined()
    expect(STATUS_META.embedding.color).toBe('processing')
  })
})

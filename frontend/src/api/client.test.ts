import { describe, expect, it } from 'vitest'
import { errorMessage } from './client'

describe('errorMessage', () => {
  it('prefers a string detail from FastAPI', () => {
    expect(errorMessage({ response: { data: { detail: '用户名已存在' } } })).toBe('用户名已存在')
  })

  it('extracts the first validation message', () => {
    const error = { response: { data: { detail: [{ msg: '密码至少 6 位' }] } } }
    expect(errorMessage(error)).toBe('密码至少 6 位')
  })

  it('falls back to Error.message', () => {
    expect(errorMessage(new Error('network down'))).toBe('network down')
  })

  it('uses the provided fallback for unknown errors', () => {
    expect(errorMessage({}, '加载失败')).toBe('加载失败')
    expect(errorMessage(null, '加载失败')).toBe('加载失败')
  })
})

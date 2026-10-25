import axios, { AxiosError } from 'axios'
import type { SSEHandlers } from '../types'

const BASE = '/api/v1'

let accessToken: string | null = null
let refreshing: Promise<any> | null = null

export function setAccessToken(token: string | null) {
  accessToken = token
}

export function getAccessToken() {
  return accessToken
}

export const api = axios.create({
  baseURL: BASE,
  withCredentials: true,
  timeout: 60000,
})

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

const rawClient = axios.create({ baseURL: BASE, withCredentials: true, timeout: 30000 })

// 这些认证端点不依赖访问令牌，收到 401 时不做自动续期重试
//（/auth/password 依赖令牌，必须允许续期后重试）
const NO_REFRESH_URLS = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout']

let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn
}

export async function refreshSession(): Promise<any> {
  if (!refreshing) {
    refreshing = rawClient
      .post('/auth/refresh')
      .then((res) => {
        accessToken = res.data.access_token
        return res.data
      })
      .catch((err) => {
        accessToken = null
        throw err
      })
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original: any = error.config
    const status = error.response?.status
    const url = String(original?.url || '')
    const refreshable =
      status === 401 && original && !original.__retried && !NO_REFRESH_URLS.some((u) => url.includes(u))
    if (refreshable) {
      original.__retried = true
      try {
        const data = await refreshSession()
        if (data?.access_token) {
          original.headers = original.headers || {}
          original.headers.Authorization = `Bearer ${data.access_token}`
          return api(original)
        }
      } catch {
        // 访问令牌与刷新令牌都已失效：清空登录态，路由守卫会跳转登录页，
        // 避免页面停留在“看似已登录”但所有请求都 401 的僵尸状态
        onUnauthorized?.()
      }
    }
    return Promise.reject(error)
  },
)

export function errorMessage(err: unknown, fallback = '操作失败'): string {
  const anyErr = err as any
  const detail = anyErr?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  if (anyErr?.message) return anyErr.message
  return fallback
}

export interface StreamChatPayload {
  question: string
  conversation_id?: string | null
  kb_ids: string[]
  use_cache?: boolean
}

async function parseSSE(
  response: Response,
  handlers: SSEHandlers,
  signal: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error('浏览器不支持流式响应')
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    if (signal.aborted) {
      await reader.cancel()
      return
    }
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx = buffer.indexOf('\n\n')
    while (idx >= 0) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      idx = buffer.indexOf('\n\n')
      const lines = block.split('\n')
      let event = 'message'
      const dataLines: string[] = []
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      let data: any = null
      try {
        data = JSON.parse(dataLines.join('\n'))
      } catch {
        continue
      }
      switch (event) {
        case 'meta':
          handlers.onMeta?.(data)
          break
        case 'stage':
          handlers.onStage?.(data)
          break
        case 'cache':
          handlers.onCache?.(data)
          break
        case 'rewrite':
          handlers.onRewrite?.(data)
          break
        case 'sources':
          handlers.onSources?.(data)
          break
        case 'token':
          handlers.onToken?.(data)
          break
        case 'usage':
          handlers.onUsage?.(data)
          break
        case 'done':
          handlers.onDone?.(data)
          break
        case 'error':
          handlers.onError?.(data)
          break
      }
    }
  }
}

export function streamChat(payload: StreamChatPayload, handlers: SSEHandlers): () => void {
  const controller = new AbortController()
  const run = async (retried = false) => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`
    const response = await fetch(`${BASE}/chat/stream`, {
      method: 'POST',
      headers,
      credentials: 'include',
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    if (response.status === 401 && !retried) {
      await refreshSession()
      return run(true)
    }
    if (!response.ok) {
      let message = `请求失败 (${response.status})`
      try {
        const data = await response.json()
        if (data?.detail) message = typeof data.detail === 'string' ? data.detail : message
      } catch {
        /* ignore */
      }
      handlers.onError?.({ message })
      return
    }
    await parseSSE(response, handlers, controller.signal)
    handlers.onClose?.()
  }
  run().catch((err: any) => {
    if (err?.name === 'AbortError') return
    handlers.onError?.({ message: err?.message || '连接中断，请重试' })
  })
  return () => controller.abort()
}

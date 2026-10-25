import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App as AntdApp, Button, Input, Modal, Select, Tag, Tooltip } from 'antd'
import {
  DatabaseOutlined,
  DownloadOutlined,
  SendOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { api, errorMessage, streamChat } from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { ChatMessage, Citation, Conversation, KnowledgeBase } from '../types'
import ConversationSidebar from '../components/chat/ConversationSidebar'
import MessageItem from '../components/chat/MessageItem'
import SourceDrawer from '../components/chat/SourceDrawer'

const SUGGESTIONS = [
  { q: '这款手机的保修期是多久？', hint: '售后政策 · 保修' },
  { q: '退换货需要满足什么条件？', hint: '售后政策 · 七天无理由' },
  { q: '请介绍热销手机的参数和价格', hint: '商品资料 · 参数对比' },
  { q: '支持哪些支付方式和发票类型？', hint: '购买指南 · 支付开票' },
]

export default function ChatPage() {
  const { message, modal } = AntdApp.useApp()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [title, setTitle] = useState('新会话')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([])
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [stage, setStage] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerCitations, setDrawerCitations] = useState<Citation[]>([])
  const [drawerRank, setDrawerRank] = useState<number | undefined>()
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const abortRef = useRef<null | (() => void)>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const loadConversations = useCallback(async (q = '') => {
    try {
      const res = await api.get('/conversations', { params: { q: q || undefined, page_size: 50 } })
      setConversations(res.data.items)
    } catch (err) {
      if ((err as any)?.response?.status !== 401) message.error(errorMessage(err, '会话列表加载失败'))
    }
  }, [message])

  useEffect(() => {
    void (async () => {
      try {
        const [kbRes, convRes] = await Promise.all([
          api.get('/kbs'),
          api.get('/conversations', { params: { page_size: 50 } }),
        ])
        setKbs(kbRes.data)
        setSelectedKbIds(kbRes.data.map((kb: KnowledgeBase) => kb.id))
        setConversations(convRes.data.items)
      } catch (err) {
        message.error(errorMessage(err, '初始化失败'))
      }
    })()
  }, [message])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: streaming ? 'auto' : 'smooth', block: 'end' })
  }, [messages, streaming])

  useEffect(() => {
    return () => abortRef.current?.()
  }, [])

  if (!user) return null

  const newChat = () => {
    abortRef.current?.()
    abortRef.current = null
    setActiveId(null)
    setTitle('新会话')
    setMessages([])
    setInput('')
    setStreaming(false)
    setStage('')
  }

  const openConversation = async (conv: Conversation) => {
    if (streaming) return
    try {
      const res = await api.get(`/conversations/${conv.id}/messages`)
      const detail = res.data
      setActiveId(conv.id)
      setTitle(detail.conversation.title)
      setMessages(detail.items)
      const convKbs: string[] = detail.conversation.kb_ids || []
      const valid = convKbs.filter((id) => kbs.some((kb) => kb.id === id))
      setSelectedKbIds(valid.length ? valid : kbs.map((kb) => kb.id))
    } catch (err) {
      message.error(errorMessage(err, '会话加载失败'))
    }
  }

  const send = (raw?: string) => {
    const question = (raw ?? input).trim()
    if (!question || streaming) return
    if (!kbs.length) {
      message.warning('当前没有可用的知识库，请联系管理员上传资料')
      return
    }
    const now = new Date().toISOString()
    const userTempId = `local-user-${Date.now()}`
    const assistantTempId = `local-assistant-${Date.now()}`
    const historyConversation = activeId

    setMessages((prev) => [
      ...prev,
      {
        id: userTempId,
        role: 'user',
        content: question,
        status: 'complete',
        created_at: now,
        citations: [],
      },
      {
        id: assistantTempId,
        role: 'assistant',
        content: '',
        status: 'streaming',
        created_at: now,
        citations: [],
      },
    ])
    setInput('')
    setStreaming(true)
    setStage('正在理解问题并检索知识库…')

    const stop = streamChat(
      {
        question,
        conversation_id: historyConversation,
        kb_ids: selectedKbIds,
        use_cache: true,
      },
      {
        onMeta: (data) => {
          setActiveId((prev) => prev ?? data.conversation_id)
          setTitle(data.conversation_title || question.slice(0, 30))
          setConversations((prev) => {
            if (prev.some((c) => c.id === data.conversation_id)) return prev
            return [
              {
                id: data.conversation_id,
                title: data.conversation_title || question.slice(0, 30),
                kb_ids: selectedKbIds,
                message_count: 2,
                last_message_at: now,
                created_at: now,
              },
              ...prev,
            ]
          })
        },
        onStage: (data) => setStage(data.stage || ''),
        onCache: () => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantTempId ? { ...m, cache_hit: true } : m)),
          )
          setStage('命中语义缓存，正在返回结果…')
        },
        onRewrite: (data) => {
          if (data?.rewritten_query) setStage(`已改写检索问题：${data.rewritten_query}`)
        },
        onSources: (data) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantTempId ? { ...m, citations: data.sources || [] } : m)),
          )
        },
        onToken: (data) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantTempId ? { ...m, content: m.content + (data.delta || '') } : m,
            ),
          )
        },
        onDone: (data) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantTempId
                ? {
                    ...m,
                    id: data.message_id,
                    status: 'complete',
                    latency_ms: data.latency_ms,
                    cache_hit: data.cache_hit,
                    citations: m.citations.map((c) => ({
                      ...c,
                      used: (data.used_citations || []).includes(c.rank),
                    })),
                  }
                : m,
            ),
          )
          setActiveId((prev) => prev ?? data.conversation_id)
          setStreaming(false)
          setStage('')
          abortRef.current = null
          void loadConversations(search)
        },
        onError: (data) => {
          message.error(data.message || '生成失败')
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantTempId ? { ...m, status: 'failed' } : m)),
          )
          setStreaming(false)
          setStage('')
          abortRef.current = null
        },
        onClose: () => {
          setStreaming(false)
          setStage('')
          abortRef.current = null
          setMessages((prev) =>
            prev.map((m) => (m.status === 'streaming' ? { ...m, status: 'failed' } : m)),
          )
        },
      },
    )
    abortRef.current = stop
  }

  const stopStreaming = () => {
    abortRef.current?.()
    abortRef.current = null
    setStreaming(false)
    setStage('')
    setMessages((prev) =>
      prev.map((m) => (m.status === 'streaming' ? { ...m, status: 'failed' } : m)),
    )
  }

  const onFeedback = async (msg: ChatMessage, rating: number) => {
    if (msg.id.startsWith('local-') || msg.status !== 'complete') return
    try {
      if (msg.feedback === rating) {
        await api.delete(`/messages/${msg.id}/feedback`)
        setMessages((prev) => prev.map((m) => (m.id === msg.id ? { ...m, feedback: null } : m)))
      } else {
        await api.post(`/messages/${msg.id}/feedback`, { rating })
        setMessages((prev) => prev.map((m) => (m.id === msg.id ? { ...m, feedback: rating } : m)))
        message.success('感谢反馈')
      }
    } catch (err) {
      message.error(errorMessage(err, '反馈提交失败'))
    }
  }

  const openSources = (citations: Citation[], rank?: number) => {
    setDrawerCitations(citations)
    setDrawerRank(rank)
    setDrawerOpen(true)
  }

  const confirmDelete = (conv: Conversation) => {
    modal.confirm({
      title: '删除会话',
      content: `确定删除「${conv.title}」吗？删除后不可恢复。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await api.delete(`/conversations/${conv.id}`)
        if (activeId === conv.id) newChat()
        await loadConversations(search)
        message.success('已删除')
      },
    })
  }

  const submitRename = async () => {
    if (!renameTarget) return
    const value = renameValue.trim()
    if (!value) return
    try {
      await api.patch(`/conversations/${renameTarget.id}`, { title: value })
      if (activeId === renameTarget.id) setTitle(value)
      setRenameTarget(null)
      await loadConversations(search)
    } catch (err) {
      message.error(errorMessage(err, '重命名失败'))
    }
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const exportMarkdown = () => {
    if (!messages.length) return
    const lines = [`# ${title}`, '']
    for (const m of messages) {
      if (m.role === 'user') lines.push(`## 提问`, '', m.content, '')
      else {
        lines.push(`## 回答`, '', m.content, '')
        if (m.citations?.length) {
          lines.push('### 引用来源', '')
          for (const c of m.citations.filter((x) => x.used !== false)) {
            lines.push(`- [${c.rank}] ${c.doc_title}`)
          }
          lines.push('')
        }
      }
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title || 'conversation'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="chat-shell">
      <ConversationSidebar
        conversations={conversations}
        activeId={activeId}
        search={search}
        user={user}
        onSearch={(value) => {
          setSearch(value)
          void loadConversations(value)
        }}
        onSelect={openConversation}
        onNew={newChat}
        onRename={(conv) => {
          setRenameTarget(conv)
          setRenameValue(conv.title)
        }}
        onDelete={confirmDelete}
        onProfile={() => navigate('/profile')}
        onAdmin={() => navigate('/admin')}
        onLogout={handleLogout}
      />

      <main className="chat-main">
        <header className="chat-header">
          <div style={{ minWidth: 0 }}>
            <div className="title">{title}</div>
            <div style={{ fontSize: 11, color: '#94a3b8' }}>多轮对话 · 引用可追溯 · 历史自动保存</div>
          </div>
          <div className="header-spacer" />
          <Select
            className="kb-select"
            mode="multiple"
            allowClear
            maxTagCount={2}
            placeholder="选择知识库（默认全部）"
            value={selectedKbIds}
            onChange={setSelectedKbIds}
            disabled={streaming}
            optionFilterProp="label"
            options={kbs.map((kb) => ({
              value: kb.id,
              label: `${kb.name}（${kb.chunk_count} 片段）`,
            }))}
            suffixIcon={<DatabaseOutlined />}
          />
          <Tooltip title="导出当前会话为 Markdown">
            <Button icon={<DownloadOutlined />} onClick={exportMarkdown} disabled={!messages.length} />
          </Tooltip>
          <span className="header-badge">
            <span className="dot" /> 已连接
          </span>
        </header>

        <div className="messages-scroll">
          <div className="messages-inner">
            {!messages.length && (
              <div className="empty-state">
                <div className="hero-icon"><ThunderboltOutlined /></div>
                <h2>有什么商品问题，交给我</h2>
                <p>
                  我会从商品知识库中检索资料，给出有依据的回答，并标注引用来源。
                  {!kbs.length && '（当前暂无知识库，请联系管理员）'}
                </p>
                <div className="suggest-grid">
                  {SUGGESTIONS.map((item) => (
                    <div key={item.q} className="suggest-card" onClick={() => send(item.q)}>
                      <div className="q">{item.q}</div>
                      <div className="hint">{item.hint}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, idx) => (
              <MessageItem
                key={m.id}
                message={m}
                streaming={streaming && idx === messages.length - 1}
                onFeedback={onFeedback}
                onOpenSources={openSources}
              />
            ))}
            <div ref={endRef} />
          </div>
        </div>

        <div className="composer-wrap">
          {streaming && (
            <div style={{ maxWidth: 900, margin: '0 auto 8px', fontSize: 12, color: '#6366f1' }}>
              <Tag color="purple" style={{ marginInlineEnd: 8 }}>处理中</Tag>
              {stage || '正在生成回答…'}
            </div>
          )}
          <div className="composer">
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入你的商品问题，例如：这款手机的保修期是多久？"
              autoSize={{ minRows: 1, maxRows: 6 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              disabled={streaming}
            />
            {streaming ? (
              <Button danger className="send-btn" icon={<StopOutlined />} onClick={stopStreaming}>
                停止
              </Button>
            ) : (
              <Button
                type="primary"
                className="send-btn"
                icon={<SendOutlined />}
                onClick={() => send()}
                disabled={!input.trim()}
              >
                发送
              </Button>
            )}
          </div>
          <div className="composer-foot">
            Enter 发送 · Shift + Enter 换行 · 回答由 <b>LangChain RAG</b> 生成，请以知识库原文为准
          </div>
        </div>
      </main>

      <SourceDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        sources={drawerCitations}
        activeRank={drawerRank}
      />

      <Modal
        title="重命名会话"
        open={!!renameTarget}
        onOk={submitRename}
        onCancel={() => setRenameTarget(null)}
        okText="保存"
        cancelText="取消"
      >
        <Input
          value={renameValue}
          onChange={(e) => setRenameValue(e.target.value)}
          maxLength={60}
          onPressEnter={submitRename}
          placeholder="输入会话名称"
        />
      </Modal>
    </div>
  )
}

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button, Tag, Tooltip } from 'antd'
import {
  CopyOutlined,
  DislikeFilled,
  DislikeOutlined,
  LikeFilled,
  LikeOutlined,
  RobotOutlined,
  UserOutlined,
} from '@ant-design/icons'
import type { ChatMessage, Citation } from '../../types'
import { fmtTime, locatorText, sourceTitle } from '../../utils'

interface Props {
  message: ChatMessage
  streaming?: boolean
  onFeedback: (message: ChatMessage, rating: number) => void
  onOpenSources: (citations: Citation[], rank?: number) => void
}

export default function MessageItem({ message, streaming, onFeedback, onOpenSources }: Props) {
  const isUser = message.role === 'user'
  const isTemp = message.id.startsWith('local-')
  const showTyping = !isUser && streaming && !message.content
  const usedCitations = message.citations || []

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
    } catch {
      /* ignore */
    }
  }

  return (
    <div className={`msg ${isUser ? 'user' : 'assistant'}`}>
      <div className="msg-avatar">{isUser ? <UserOutlined /> : <RobotOutlined />}</div>
      <div className="msg-body">
        <div className="msg-name">{isUser ? '你' : '知识库助手'}</div>
        <div className="bubble">
          {showTyping ? (
            <span className="typing-dots"><i /><i /><i /></span>
          ) : isUser ? (
            message.content
          ) : (
            <div className="markdown-body">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
                }}
              >
                {message.content || ' '}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {!isUser && usedCitations.length > 0 && (
          <div className="citation-row">
            {usedCitations.map((c) => (
              <Tooltip key={`${c.rank}-${c.chunk_id || c.snippet.slice(0, 8)}`} title={`${sourceTitle(c)} · ${locatorText(c.locator)}`}>
                <span
                  className={`citation-chip ${c.used ? 'used' : ''}`}
                  onClick={() => onOpenSources(usedCitations, c.rank)}
                >
                  <span className="idx">[{c.rank}]</span>
                  <span className="doc">{c.doc_title || '知识库片段'}</span>
                </span>
              </Tooltip>
            ))}
          </div>
        )}

        {!isUser && (message.status !== 'streaming' || message.content) && (
          <div className="msg-meta">
            <span>{fmtTime(message.created_at, 'HH:mm')}</span>
            {message.latency_ms ? (<><span className="sep" /><span>{(message.latency_ms / 1000).toFixed(1)}s</span></>) : null}
            {message.cache_hit ? (<><span className="sep" /><Tag color="cyan" style={{ marginInlineEnd: 0, fontSize: 10, lineHeight: '16px' }}>语义缓存</Tag></>) : null}
            {message.model ? (<><span className="sep" /><span>{message.model}</span></>) : null}
            {message.status === 'failed' ? (<><span className="sep" /><Tag color="red" style={{ marginInlineEnd: 0, fontSize: 10 }}>未完成</Tag></>) : null}
            <div className="msg-actions">
              <Tooltip title="复制回答">
                <Button type="text" size="small" icon={<CopyOutlined />} onClick={copy} />
              </Tooltip>
              {!isTemp && (
                <>
                  <Tooltip title="有帮助">
                    <Button
                      type="text"
                      size="small"
                      icon={message.feedback === 1 ? <LikeFilled style={{ color: '#4f46e5' }} /> : <LikeOutlined />}
                      onClick={() => onFeedback(message, 1)}
                    />
                  </Tooltip>
                  <Tooltip title="需要改进">
                    <Button
                      type="text"
                      size="small"
                      icon={message.feedback === -1 ? <DislikeFilled style={{ color: '#ef4444' }} /> : <DislikeOutlined />}
                      onClick={() => onFeedback(message, -1)}
                    />
                  </Tooltip>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

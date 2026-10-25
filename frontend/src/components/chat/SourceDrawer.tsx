import { useEffect } from 'react'
import { Drawer, Empty, Tag } from 'antd'
import type { Citation } from '../../types'
import { locatorText } from '../../utils'

interface Props {
  open: boolean
  onClose: () => void
  sources: Citation[]
  activeRank?: number
}

export default function SourceDrawer({ open, onClose, sources, activeRank }: Props) {
  useEffect(() => {
    if (open && activeRank) {
      const timer = setTimeout(() => {
        document.getElementById(`source-${activeRank}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }, 200)
      return () => clearTimeout(timer)
    }
  }, [open, activeRank])

  return (
    <Drawer
      title="引用来源"
      open={open}
      onClose={onClose}
      width={500}
      styles={{ body: { background: '#f8fafc' } }}
    >
      {!sources.length ? (
        <Empty description="本次回答没有引用来源" />
      ) : (
        <>
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
            共 {sources.length} 条检索片段，高亮为回答中实际引用的来源。点击回答中的 [编号] 可定位。
          </div>
          {sources.map((s) => (
            <div
              key={`${s.rank}-${s.chunk_id || s.snippet.slice(0, 8)}`}
              id={`source-${s.rank}`}
              className={`source-item ${activeRank === s.rank ? 'active' : ''}`}
              style={{ background: '#fff' }}
            >
              <div className="head">
                <span className="rank">[{s.rank}]</span>
                <span className="title">{s.doc_title || '知识库片段'}</span>
                {s.used ? <Tag color="purple" style={{ marginInlineEnd: 0 }}>已引用</Tag> : null}
              </div>
              <div className="loc">{locatorText(s.locator)}</div>
              <div className="snippet" style={{ marginTop: 8 }}>{s.snippet}</div>
              <div className="scores">
                {s.dense_score != null && <span>向量 {s.dense_score.toFixed(3)}</span>}
                {s.sparse_score != null && <span>关键词 {s.sparse_score.toFixed(3)}</span>}
                {s.rerank_score != null && <span>重排 {s.rerank_score.toFixed(3)}</span>}
              </div>
            </div>
          ))}
        </>
      )}
    </Drawer>
  )
}

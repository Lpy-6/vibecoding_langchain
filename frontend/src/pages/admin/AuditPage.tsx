import { useEffect, useState } from 'react'
import { App as AntdApp, Card, Input, Table, Tag, Tooltip } from 'antd'
import { api, errorMessage } from '../../api/client'
import { fmtTime } from '../../utils'

const ACTION_COLORS: Record<string, string> = {
  auth: 'blue',
  kb: 'purple',
  document: 'cyan',
  user: 'orange',
}

export default function AuditPage() {
  const { message } = AntdApp.useApp()
  const [items, setItems] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async (targetPage = page) => {
    setLoading(true)
    try {
      const res = await api.get('/admin/audit-logs', {
        params: {
          page: targetPage,
          page_size: 20,
          action: action || undefined,
          actor: actor || undefined,
        },
      })
      setItems(res.data.items)
      setTotal(res.data.total)
    } catch (err) {
      message.error(errorMessage(err, '审计日志加载失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(page)
  }, [page])

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <h2 className="page-title">审计日志</h2>
          <p className="page-sub">记录登录、知识库变更、文档操作与用户管理行为。</p>
        </div>
        <Input.Search
          placeholder="操作类型，如 document"
          allowClear
          value={action}
          onChange={(e) => setAction(e.target.value)}
          onSearch={() => {
            setPage(1)
            void load(1)
          }}
          style={{ width: 200 }}
        />
        <Input.Search
          placeholder="操作人用户名"
          allowClear
          value={actor}
          onChange={(e) => setActor(e.target.value)}
          onSearch={() => {
            setPage(1)
            void load(1)
          }}
          style={{ width: 180 }}
        />
      </div>

      <Card className="stat-card">
        <Table
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={{ current: page, pageSize: 20, total, onChange: setPage }}
          columns={[
            {
              title: '操作',
              dataIndex: 'action',
              width: 200,
              render: (v: string) => {
                const prefix = v.split('.')[0]
                return <Tag color={ACTION_COLORS[prefix] || 'default'}>{v}</Tag>
              },
            },
            { title: '操作人', dataIndex: 'actor_name', width: 120, render: (v: string) => v || '匿名' },
            {
              title: '资源',
              width: 220,
              render: (_, row) => (
                <span style={{ fontSize: 12, color: '#64748b' }}>
                  {row.resource_type || '-'} {row.resource_id ? `· ${row.resource_id.slice(0, 8)}` : ''}
                </span>
              ),
            },
            {
              title: '详情',
              dataIndex: 'detail',
              ellipsis: true,
              render: (v: any) => {
                const text = JSON.stringify(v || {})
                return (
                  <Tooltip title={<pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', maxWidth: 500 }}>{JSON.stringify(v, null, 2)}</pre>}>
                    <span style={{ fontSize: 12, color: '#475569' }}>{text}</span>
                  </Tooltip>
                )
              },
            },
            { title: 'IP', dataIndex: 'ip', width: 130, render: (v: string) => v || '-' },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 160,
              render: (v: string) => fmtTime(v, 'YYYY-MM-DD HH:mm:ss'),
            },
          ]}
        />
      </Card>
    </div>
  )
}

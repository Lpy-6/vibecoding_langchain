import { useEffect, useState } from 'react'
import { App as AntdApp, Button, Card, Col, Descriptions, Row, Statistic, Table, Tag } from 'antd'
import { ClearOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api, errorMessage } from '../../api/client'
import { fmtTime } from '../../utils'

export default function StatsPage() {
  const { message, modal } = AntdApp.useApp()
  const [overview, setOverview] = useState<any>(null)
  const [system, setSystem] = useState<any>(null)
  const [qa, setQa] = useState<any[]>([])
  const [qaTotal, setQaTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [o, s, q] = await Promise.all([
        api.get('/admin/stats/overview'),
        api.get('/admin/system'),
        api.get('/admin/stats/qa', { params: { page, page_size: 10 } }),
      ])
      setOverview(o.data)
      setSystem(s.data)
      setQa(q.data.items)
      setQaTotal(q.data.total)
    } catch (err) {
      message.error(errorMessage(err, '统计加载失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [page])

  const daily: { date: string; count: number }[] = overview?.daily_questions || []
  const maxDaily = Math.max(1, ...daily.map((d) => d.count))

  const clearCache = () => {
    modal.confirm({
      title: '清空语义缓存',
      content: '清空后相同问题会重新检索生成，不影响知识库内容。',
      okText: '清空',
      cancelText: '取消',
      onOk: async () => {
        const res = await api.delete('/admin/cache')
        message.success(`已清理 ${res.data.removed} 条缓存`)
        await load()
      },
    })
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <h2 className="page-title">数据看板</h2>
          <p className="page-sub">问答量、知识库规模、缓存命中与生成延迟。</p>
        </div>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
        <Button icon={<ClearOutlined />} danger onClick={clearCache}>清空语义缓存</Button>
      </div>

      <Row gutter={[14, 14]}>
        <Col xs={12} md={6}><Card className="stat-card"><Statistic title="用户总数 / 启用" value={overview?.users.total || 0} suffix={`/ ${overview?.users.active || 0}`} /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card"><Statistic title="知识库" value={overview?.kbs.total || 0} suffix="个" /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card"><Statistic title="已就绪文档" value={overview?.documents.ready || 0} suffix={`/ ${overview?.documents.total || 0}`} /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card"><Statistic title="向量片段" value={overview?.chunks || 0} /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card"><Statistic title="累计回答" value={overview?.answers || 0} suffix="条" /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card"><Statistic title="平均生成延迟" value={overview?.avg_latency_ms || 0} suffix="ms" /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card"><Statistic title="语义缓存" value={overview?.cache.entries || 0} suffix={`条 / 命中 ${overview?.cache.hits || 0}`} /></Card></Col>
        <Col xs={12} md={6}><Card className="stat-card"><Statistic title="反馈 好评/差评" value={overview?.feedback.up || 0} suffix={`/ ${overview?.feedback.down || 0}`} /></Card></Col>
      </Row>

      <Row gutter={[14, 14]} style={{ marginTop: 14 }}>
        <Col xs={24} lg={14}>
          <Card title="近 7 天提问量" className="stat-card">
            <div className="mini-chart">
              {daily.map((d) => (
                <div className="bar-wrap" key={d.date}>
                  <div style={{ fontSize: 11, color: '#64748b' }}>{d.count}</div>
                  <div className="bar" style={{ height: `${Math.max(4, (d.count / maxDaily) * 100)}%` }} />
                  <div className="bar-label">{dayjs(d.date).format('MM-DD')}</div>
                </div>
              ))}
            </div>
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card title="运行配置" className="stat-card">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="生成模式">
                <Tag color={system?.llm_mode === 'dashscope' ? 'green' : 'orange'}>
                  {system?.llm_mode === 'dashscope' ? '百炼在线模型' : '离线 Mock 模式'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="对话模型">{system?.chat_model}</Descriptions.Item>
              <Descriptions.Item label="向量模型">{system?.embedding_provider}（{system?.embedding_dim} 维）</Descriptions.Item>
              <Descriptions.Item label="重排模型">{system?.rerank_model}</Descriptions.Item>
              <Descriptions.Item label="提示词版本">{system?.prompt_version}</Descriptions.Item>
              <Descriptions.Item label="内存索引">
                {Object.keys(system?.vector_index || {}).length
                  ? Object.entries(system.vector_index).map(([k, v]: any) => (
                      <Tag key={k}>{v.chunks} 块 · v{v.version}</Tag>
                    ))
                  : '尚未构建'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Card title="最近问答记录" className="stat-card" style={{ marginTop: 14 }}>
        <Table
          rowKey="message_id"
          size="small"
          dataSource={qa}
          pagination={{ current: page, pageSize: 10, total: qaTotal, onChange: setPage }}
          columns={[
            { title: '用户', dataIndex: 'username', width: 110 },
            { title: '会话', dataIndex: 'conversation_title', width: 180, ellipsis: true },
            { title: '回答摘要', dataIndex: 'answer', ellipsis: true },
            {
              title: '缓存',
              dataIndex: 'cache_hit',
              width: 80,
              render: (v: boolean) => (v ? <Tag color="cyan">命中</Tag> : <Tag>未命中</Tag>),
            },
            {
              title: '延迟',
              dataIndex: 'latency_ms',
              width: 90,
              render: (v: number) => (v ? `${(v / 1000).toFixed(1)}s` : '-'),
            },
            {
              title: '反馈',
              dataIndex: 'feedback',
              width: 70,
              render: (v: number | null) =>
                v === 1 ? <Tag color="green">赞</Tag> : v === -1 ? <Tag color="red">踩</Tag> : '-',
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 140,
              render: (v: string) => fmtTime(v, 'MM-DD HH:mm'),
            },
          ]}
        />
      </Card>
    </div>
  )
}

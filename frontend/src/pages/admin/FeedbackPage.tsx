import { useEffect, useState } from 'react'
import { App as AntdApp, Card, Segmented, Table, Tag } from 'antd'
import { api, errorMessage } from '../../api/client'
import { fmtTime } from '../../utils'

export default function FeedbackPage() {
  const { message } = AntdApp.useApp()
  const [items, setItems] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [rating, setRating] = useState<string>('all')
  const [loading, setLoading] = useState(false)

  const load = async (targetPage = page) => {
    setLoading(true)
    try {
      const res = await api.get('/admin/feedback', {
        params: {
          page: targetPage,
          page_size: 20,
          rating: rating === 'all' ? undefined : Number(rating),
        },
      })
      setItems(res.data.items)
      setTotal(res.data.total)
    } catch (err) {
      message.error(errorMessage(err, '反馈加载失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(page)
  }, [page, rating])

  return (
    <div>
      <h2 className="page-title">用户反馈</h2>
      <p className="page-sub">用户对回答的点赞/点踩与原因，用于持续优化检索与提示词。</p>

      <Card className="stat-card">
        <div style={{ marginBottom: 14 }}>
          <Segmented
            value={rating}
            options={[
              { label: '全部', value: 'all' },
              { label: '好评', value: '1' },
              { label: '差评', value: '-1' },
            ]}
            onChange={(v) => {
              setPage(1)
              setRating(v as string)
            }}
          />
        </div>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={{ current: page, pageSize: 20, total, onChange: setPage }}
          columns={[
            {
              title: '评价',
              dataIndex: 'rating',
              width: 80,
              render: (v: number) => (v === 1 ? <Tag color="green">有帮助</Tag> : <Tag color="red">需改进</Tag>),
            },
            { title: '用户', dataIndex: 'username', width: 120 },
            {
              title: '原因/备注',
              width: 200,
              render: (_, row) => (
                <div style={{ fontSize: 12 }}>
                  {row.reason_code ? <Tag>{row.reason_code}</Tag> : null}
                  {row.comment || '-'}
                </div>
              ),
            },
            {
              title: '关联回答',
              dataIndex: 'answer',
              ellipsis: true,
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 150,
              render: (v: string) => fmtTime(v),
            },
          ]}
        />
      </Card>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App as AntdApp, Button, Form, Input, Modal, Switch, Table, Tag } from 'antd'
import { DeleteOutlined, EditOutlined, FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'
import { api, errorMessage } from '../../api/client'
import type { KnowledgeBase } from '../../types'
import { fmtTime } from '../../utils'

export default function KbListPage() {
  const { message, modal } = AntdApp.useApp()
  const navigate = useNavigate()
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<KnowledgeBase | null>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.get('/admin/kbs')
      setItems(res.data)
    } catch (err) {
      message.error(errorMessage(err, '加载失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ is_public: true })
    setOpen(true)
  }

  const openEdit = (kb: KnowledgeBase) => {
    setEditing(kb)
    form.setFieldsValue({ name: kb.name, description: kb.description, is_public: kb.is_public })
    setOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    try {
      if (editing) {
        await api.patch(`/admin/kbs/${editing.id}`, values)
        message.success('知识库已更新')
        setOpen(false)
        await load()
      } else {
        const res = await api.post('/admin/kbs', values)
        message.success('知识库已创建，接下来上传文档吧')
        setOpen(false)
        navigate(`/admin/kbs/${res.data.id}`)
      }
    } catch (err) {
      message.error(errorMessage(err, '保存失败'))
    }
  }

  const remove = (kb: KnowledgeBase) => {
    modal.confirm({
      title: '删除知识库',
      content: `确定删除「${kb.name}」吗？其下 ${kb.doc_count} 个文档、${kb.chunk_count} 个片段和权限配置都会被删除，且不可恢复。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await api.delete(`/admin/kbs/${kb.id}`)
        message.success('已删除')
        await load()
      },
    })
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h2 className="page-title">知识库管理</h2>
          <p className="page-sub">
            先创建知识库，然后进入「文档管理」上传本地文件或导入网页。点击「文档管理」或知识库名称即可进入。
          </p>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建知识库
        </Button>
      </div>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={false}
        columns={[
          {
            title: '知识库',
            dataIndex: 'name',
            render: (_, kb) => (
              <div>
                <a onClick={() => navigate(`/admin/kbs/${kb.id}`)} style={{ fontWeight: 600 }}>
                  {kb.name}
                </a>
                <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{kb.description || '暂无描述'}</div>
              </div>
            ),
          },
          {
            title: '可见性',
            dataIndex: 'is_public',
            width: 110,
            render: (v: boolean) => (v ? <Tag color="green">公开</Tag> : <Tag color="orange">私有</Tag>),
          },
          { title: '文档', dataIndex: 'doc_count', width: 80 },
          { title: '片段', dataIndex: 'chunk_count', width: 80 },
          { title: '版本', dataIndex: 'version', width: 80 },
          {
            title: '更新时间',
            dataIndex: 'updated_at',
            width: 170,
            render: (v: string) => fmtTime(v),
          },
          {
            title: '操作',
            width: 210,
            render: (_, kb) => (
              <>
                <Button type="link" size="small" icon={<FolderOpenOutlined />} onClick={() => navigate(`/admin/kbs/${kb.id}`)}>
                  文档管理
                </Button>
                <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(kb)}>
                  编辑
                </Button>
                <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => remove(kb)}>
                  删除
                </Button>
              </>
            ),
          },
        ]}
      />

      <Modal
        title={editing ? '编辑知识库' : '新建知识库'}
        open={open}
        onOk={submit}
        onCancel={() => setOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={64} placeholder="例如：手机数码商品库" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={500} placeholder="说明该知识库包含哪些商品资料" />
          </Form.Item>
          <Form.Item name="is_public" label="所有登录用户可见" valuePropName="checked">
            <Switch />
          </Form.Item>
          {!editing && (
            <div style={{ fontSize: 12, color: '#64748b', background: '#f8fafc', padding: '8px 10px', borderRadius: 8 }}>
              保存后将进入文档管理页，届时可上传 PDF / Word / Excel / TXT / Markdown / 图片，或导入网页。
            </div>
          )}
        </Form>
      </Modal>
    </div>
  )
}

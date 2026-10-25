import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  App as AntdApp,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Segmented,
  Switch,
  Table,
  Tag,
  Tooltip,
  Upload,
} from 'antd'
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  InboxOutlined,
  LinkOutlined,
  ReloadOutlined,
  SafetyOutlined,
} from '@ant-design/icons'
import { api, errorMessage } from '../../api/client'
import type { ChunkItem, DocumentItem, KnowledgeBase } from '../../types'
import { fmtTime, formatBytes, locatorText, STATUS_META } from '../../utils'

const IN_PROGRESS = ['pending', 'parsing', 'embedding', 'persisting', 'retrying']

export default function KbDetailPage() {
  const { kbId = '' } = useParams<{ kbId: string }>()
  const { message, modal } = AntdApp.useApp()
  const navigate = useNavigate()

  const [kb, setKb] = useState<KnowledgeBase | null>(null)
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [urlOpen, setUrlOpen] = useState(false)
  const [permOpen, setPermOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [permUsers, setPermUsers] = useState<any[]>([])
  const [permSelected, setPermSelected] = useState<string[]>([])
  const [chunkDrawer, setChunkDrawer] = useState(false)
  const [activeDoc, setActiveDoc] = useState<DocumentItem | null>(null)
  const [chunks, setChunks] = useState<ChunkItem[]>([])
  const [chunkType, setChunkType] = useState<'child' | 'parent'>('child')
  const [chunkPage, setChunkPage] = useState(1)
  const [chunkTotal, setChunkTotal] = useState(0)
  const [urlForm] = Form.useForm()
  const [editForm] = Form.useForm()

  const loadKb = useCallback(async () => {
    try {
      const res = await api.get(`/kbs/${kbId}`)
      setKb(res.data)
    } catch (err) {
      message.error(errorMessage(err, '知识库加载失败'))
    }
  }, [kbId, message])

  const loadDocs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get(`/admin/kbs/${kbId}/documents`, { params: { page: 1, page_size: 100 } })
      setDocs(res.data.items)
    } catch (err) {
      message.error(errorMessage(err, '文档加载失败'))
    } finally {
      setLoading(false)
    }
  }, [kbId, message])

  useEffect(() => {
    void loadKb()
    void loadDocs()
  }, [loadKb, loadDocs])

  const hasInProgress = docs.some((d) => IN_PROGRESS.includes(d.status))
  useEffect(() => {
    if (!hasInProgress) return
    const timer = setInterval(() => {
      void loadDocs()
      void loadKb()
    }, 2000)
    return () => clearInterval(timer)
  }, [hasInProgress, loadDocs, loadKb])

  const uploadFile = async (options: any) => {
    const { file, onSuccess, onError } = options
    if (file.size > 50 * 1024 * 1024) {
      message.error(`${file.name} 超过 50MB`)
      onError?.(new Error('too large'))
      return
    }
    const fd = new FormData()
    fd.append('files', file)
    try {
      const res = await api.post(`/admin/kbs/${kbId}/documents`, fd)
      const data = res.data
      if (data.duplicates?.length) {
        message.warning(`${file.name}：内容重复，已跳过`)
      } else {
        message.success(`${file.name} 已提交解析`)
      }
      onSuccess?.(data)
      await loadDocs()
      await loadKb()
    } catch (err) {
      message.error(`${file.name}：${errorMessage(err, '上传失败')}`)
      onError?.(err as Error)
    }
  }

  const submitUrl = async () => {
    const values = await urlForm.validateFields()
    try {
      await api.post(`/admin/kbs/${kbId}/documents/url`, values)
      message.success('网页已提交解析')
      setUrlOpen(false)
      urlForm.resetFields()
      await loadDocs()
    } catch (err) {
      message.error(errorMessage(err, '导入失败'))
    }
  }

  const openChunks = async (doc: DocumentItem) => {
    setActiveDoc(doc)
    setChunkDrawer(true)
    setChunkType('child')
    setChunkPage(1)
    await loadChunks(doc.id, 'child', 1)
  }

  const loadChunks = async (docId: string, type: 'child' | 'parent', page: number) => {
    try {
      const res = await api.get(`/admin/documents/${docId}/chunks`, {
        params: { chunk_type: type, page, page_size: 10 },
      })
      setChunks(res.data.items)
      setChunkTotal(res.data.total)
    } catch (err) {
      message.error(errorMessage(err, '分块加载失败'))
    }
  }

  const reindex = async (doc: DocumentItem) => {
    try {
      await api.post(`/admin/documents/${doc.id}/reindex`)
      message.success('已提交重索引任务')
      await loadDocs()
    } catch (err) {
      message.error(errorMessage(err, '重索引失败'))
    }
  }

  const removeDoc = (doc: DocumentItem) => {
    modal.confirm({
      title: '删除文档',
      content: `确定删除「${doc.title}」及其全部向量片段吗？`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        await api.delete(`/admin/documents/${doc.id}`)
        message.success('已删除')
        await loadDocs()
        await loadKb()
      },
    })
  }

  const openPermissions = async () => {
    try {
      const res = await api.get(`/admin/kbs/${kbId}/permissions`)
      setPermUsers(res.data.users)
      setPermSelected(res.data.users.filter((u: any) => u.granted).map((u: any) => u.id))
      setPermOpen(true)
    } catch (err) {
      message.error(errorMessage(err, '权限加载失败'))
    }
  }

  const savePermissions = async () => {
    try {
      await api.put(`/admin/kbs/${kbId}/permissions`, { user_ids: permSelected })
      message.success('权限已保存')
      setPermOpen(false)
    } catch (err) {
      message.error(errorMessage(err, '保存失败'))
    }
  }

  const submitEdit = async () => {
    const values = await editForm.validateFields()
    try {
      await api.patch(`/admin/kbs/${kbId}`, values)
      message.success('已更新')
      setEditOpen(false)
      await loadKb()
    } catch (err) {
      message.error(errorMessage(err, '保存失败'))
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Button shape="circle" icon={<ArrowLeftOutlined />} onClick={() => navigate('/admin/kbs')} />
        <div style={{ flex: 1 }}>
          <div className="page-title" style={{ marginBottom: 2 }}>
            {kb?.name || '知识库'}
            {kb ? (
              <Tag color={kb.is_public ? 'green' : 'orange'} style={{ marginLeft: 10, verticalAlign: 'middle' }}>
                {kb.is_public ? '公开' : '私有'}
              </Tag>
            ) : null}
          </div>
          <div className="page-sub" style={{ margin: 0 }}>{kb?.description || '管理文档、解析进度与访问权限'}</div>
        </div>
        <Button icon={<EditOutlined />} onClick={() => {
          if (!kb) return
          editForm.setFieldsValue({ name: kb.name, description: kb.description, is_public: kb.is_public })
          setEditOpen(true)
        }}>
          编辑
        </Button>
        <Button icon={<SafetyOutlined />} onClick={openPermissions}>访问权限</Button>
        <Button type="primary" icon={<LinkOutlined />} onClick={() => setUrlOpen(true)}>
          导入网页
        </Button>
      </div>

      <Descriptions
        size="small"
        column={5}
        style={{ background: '#fff', padding: '14px 18px', borderRadius: 12, marginBottom: 16, border: '1px solid #e5e7eb' }}
      >
        <Descriptions.Item label="文档数">{kb?.doc_count ?? 0}</Descriptions.Item>
        <Descriptions.Item label="向量片段">{kb?.chunk_count ?? 0}</Descriptions.Item>
        <Descriptions.Item label="内容版本">v{kb?.version ?? 1}</Descriptions.Item>
        <Descriptions.Item label="更新时间">{kb ? fmtTime(kb.updated_at) : '-'}</Descriptions.Item>
        <Descriptions.Item label="解析状态">
          {hasInProgress ? <Tag color="processing">有任务进行中</Tag> : <Tag color="success">空闲</Tag>}
        </Descriptions.Item>
      </Descriptions>

      <Upload.Dragger
        multiple
        customRequest={uploadFile}
        showUploadList={false}
        accept=".pdf,.docx,.txt,.md,.markdown,.xlsx,.xlsm,.csv,.png,.jpg,.jpeg,.webp,.bmp,.tiff"
        style={{ marginBottom: 18, borderRadius: 12 }}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
        <p className="ant-upload-hint" style={{ fontSize: 12 }}>
          支持 PDF / Word / TXT / Markdown / Excel / CSV / 图片；单文件 ≤ 50MB。扫描版 PDF 与图片需配置百炼 Key 启用 OCR。
        </p>
      </Upload.Dragger>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={docs}
        pagination={false}
        columns={[
          {
            title: '文档',
            dataIndex: 'title',
            render: (_, doc) => (
              <div>
                <div style={{ fontWeight: 600 }}>{doc.title}</div>
                <div style={{ fontSize: 12, color: '#94a3b8' }}>
                  {doc.source_type === 'url' ? doc.source_url : doc.original_filename}
                </div>
                {doc.error_message ? (
                  <Tooltip title={doc.error_message}>
                    <div style={{ fontSize: 12, color: '#ef4444', maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {doc.error_message}
                    </div>
                  </Tooltip>
                ) : null}
              </div>
            ),
          },
          {
            title: '类型',
            dataIndex: 'source_type',
            width: 90,
            render: (v: string) => (
              <Tag>{v === 'url' ? '网页' : v === 'image' ? '图片' : '文件'}</Tag>
            ),
          },
          { title: '大小', dataIndex: 'size_bytes', width: 90, render: (v: number) => formatBytes(v) },
          {
            title: '状态',
            dataIndex: 'status',
            width: 170,
            render: (v: string) => {
              const meta = STATUS_META[v] || { label: v, color: 'default', percent: 0 }
              if (v === 'ready' || v === 'failed') {
                return <Tag color={meta.color}>{meta.label}</Tag>
              }
              return <Progress percent={meta.percent} size="small" status="active" />
            },
          },
          { title: '片段', dataIndex: 'chunk_count', width: 70 },
          {
            title: '页/OCR',
            width: 90,
            render: (_, doc) => `${doc.page_count}${doc.ocr_pages ? ` / ${doc.ocr_pages}` : ''}`,
          },
          { title: '创建时间', dataIndex: 'created_at', width: 150, render: (v: string) => fmtTime(v, 'MM-DD HH:mm') },
          {
            title: '操作',
            width: 200,
            render: (_, doc) => (
              <>
                <Button type="link" size="small" icon={<FileTextOutlined />} onClick={() => openChunks(doc)}>
                  分块
                </Button>
                <Button type="link" size="small" icon={<ReloadOutlined />} onClick={() => reindex(doc)}>
                  重索引
                </Button>
                <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => removeDoc(doc)}>
                  删除
                </Button>
              </>
            ),
          },
        ]}
        locale={{ emptyText: <Empty description="还没有文档，先上传商品资料吧" /> }}
      />

      <Modal title="导入网页" open={urlOpen} onOk={submitUrl} onCancel={() => setUrlOpen(false)} okText="开始抓取" cancelText="取消">
        <Form form={urlForm} layout="vertical">
          <Form.Item
            name="url"
            label="网页地址"
            rules={[{ required: true, message: '请输入 URL' }, { pattern: /^https?:\/\//, message: '仅支持 http/https' }]}
          >
            <Input placeholder="https://example.com/product/123" />
          </Form.Item>
          <Form.Item name="title" label="文档标题（可选）">
            <Input placeholder="默认使用网页标题" maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="访问权限（私有知识库仅授权用户可见）"
        open={permOpen}
        onOk={savePermissions}
        onCancel={() => setPermOpen(false)}
        okText="保存"
        cancelText="取消"
        width={520}
      >
        {kb?.is_public ? (
          <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', padding: 10, borderRadius: 8, marginBottom: 14, fontSize: 12, color: '#166534' }}>
            当前知识库为「公开」，所有登录用户都可问答。以下授权仅在切换为「私有」后生效。
          </div>
        ) : null}
        <Checkbox.Group
          value={permSelected}
          onChange={(v) => setPermSelected(v as string[])}
          style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
        >
          {permUsers.map((u) => (
            <Checkbox key={u.id} value={u.id} disabled={!u.is_active}>
              {u.display_name || u.username}（{u.username}）
              {!u.is_active ? ' · 已禁用' : ''}
            </Checkbox>
          ))}
        </Checkbox.Group>
      </Modal>

      <Modal title="编辑知识库" open={editOpen} onOk={submitEdit} onCancel={() => setEditOpen(false)} okText="保存" cancelText="取消">
        <Form form={editForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
          <Form.Item name="is_public" label="所有登录用户可见" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={activeDoc ? `分块预览 · ${activeDoc.title}` : '分块预览'}
        open={chunkDrawer}
        onClose={() => setChunkDrawer(false)}
        width={720}
      >
        <div style={{ marginBottom: 14 }}>
          <Segmented
            value={chunkType}
            options={[
              { label: '子块（检索单元）', value: 'child' },
              { label: '父块（生成上下文）', value: 'parent' },
            ]}
            onChange={(v) => {
              const type = v as 'child' | 'parent'
              setChunkType(type)
              setChunkPage(1)
              if (activeDoc) void loadChunks(activeDoc.id, type, 1)
            }}
          />
        </div>
        <Table
          rowKey="id"
          size="small"
          dataSource={chunks}
          pagination={{
            current: chunkPage,
            pageSize: 10,
            total: chunkTotal,
            onChange: (page) => {
              setChunkPage(page)
              if (activeDoc) void loadChunks(activeDoc.id, chunkType, page)
            },
          }}
          columns={[
            { title: '#', dataIndex: 'ordinal', width: 60 },
            {
              title: '内容',
              dataIndex: 'content',
              render: (v: string) => (
                <Tooltip title={v} overlayStyle={{ maxWidth: 520 }}>
                  <div style={{ maxWidth: 420, maxHeight: 72, overflow: 'hidden', whiteSpace: 'pre-wrap', fontSize: 12, lineHeight: 1.6 }}>
                    {v}
                  </div>
                </Tooltip>
              ),
            },
            { title: 'Tokens', dataIndex: 'token_count', width: 70 },
            {
              title: '位置',
              width: 150,
              render: (_, c) => (
                <span style={{ fontSize: 12, color: '#64748b' }}>
                  {locatorText({ page_no: c.page_no, sheet_name: c.sheet_name, row_start: c.row_start, row_end: c.row_end, heading_path: c.heading_path })}
                </span>
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  )
}

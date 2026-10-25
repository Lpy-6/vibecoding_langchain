import { useCallback, useEffect, useState } from 'react'
import { App as AntdApp, Button, Form, Input, Modal, Select, Switch, Table, Tag } from 'antd'
import { KeyOutlined } from '@ant-design/icons'
import { api, errorMessage } from '../../api/client'
import type { User } from '../../types'
import { fmtTime } from '../../utils'

export default function UsersPage() {
  const { message } = AntdApp.useApp()
  const [items, setItems] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [resetUser, setResetUser] = useState<User | null>(null)
  const [resetForm] = Form.useForm()

  const load = useCallback(async (keyword = q, targetPage = page) => {
    setLoading(true)
    try {
      const res = await api.get('/admin/users', {
        params: { q: keyword || undefined, page: targetPage, page_size: 20 },
      })
      setItems(res.data.items)
      setTotal(res.data.total)
    } catch (err) {
      message.error(errorMessage(err, '用户加载失败'))
    } finally {
      setLoading(false)
    }
  }, [message, page, q])

  useEffect(() => {
    void load()
  }, [page])

  const patchUser = async (user: User, values: Record<string, any>) => {
    try {
      await api.patch(`/admin/users/${user.id}`, values)
      message.success('已更新')
      await load()
    } catch (err) {
      message.error(errorMessage(err, '更新失败'))
    }
  }

  const submitReset = async () => {
    const values = await resetForm.validateFields()
    if (!resetUser) return
    try {
      await api.post(`/admin/users/${resetUser.id}/reset-password`, { new_password: values.new_password })
      message.success('密码已重置，该用户需重新登录')
      setResetUser(null)
      resetForm.resetFields()
    } catch (err) {
      message.error(errorMessage(err, '重置失败'))
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 16 }}>
        <div style={{ flex: 1 }}>
          <h2 className="page-title">用户管理</h2>
          <p className="page-sub">管理账号状态与角色。管理员可访问管理后台，普通用户仅能问答。</p>
        </div>
        <Input.Search
          placeholder="搜索用户名或昵称"
          allowClear
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onSearch={(value) => {
            setPage(1)
            void load(value, 1)
          }}
          style={{ width: 260 }}
        />
      </div>

      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage, showTotal: (t) => `共 ${t} 人` }}
        columns={[
          {
            title: '用户',
            render: (_, u) => (
              <div>
                <div style={{ fontWeight: 600 }}>{u.display_name || u.username}</div>
                <div style={{ fontSize: 12, color: '#94a3b8' }}>@{u.username}</div>
              </div>
            ),
          },
          {
            title: '角色',
            dataIndex: 'role',
            width: 130,
            render: (role: string, u) => (
              <Select
                size="small"
                value={role}
                style={{ width: 100 }}
                onChange={(value) => patchUser(u, { role: value })}
                options={[
                  { value: 'user', label: '普通用户' },
                  { value: 'admin', label: '管理员' },
                ]}
              />
            ),
          },
          {
            title: '状态',
            dataIndex: 'is_active',
            width: 100,
            render: (active: boolean, u) => (
              <Switch
                checked={active}
                checkedChildren="启用"
                unCheckedChildren="禁用"
                onChange={(checked) => patchUser(u, { is_active: checked })}
              />
            ),
          },
          {
            title: '最近登录',
            dataIndex: 'last_login_at',
            width: 170,
            render: (v: string | null) => (v ? fmtTime(v, 'MM-DD HH:mm') : <Tag>从未登录</Tag>),
          },
          {
            title: '注册时间',
            dataIndex: 'created_at',
            width: 170,
            render: (v: string) => fmtTime(v),
          },
          {
            title: '操作',
            width: 140,
            render: (_, u) => (
              <Button
                type="link"
                size="small"
                icon={<KeyOutlined />}
                onClick={() => {
                  setResetUser(u)
                  resetForm.resetFields()
                }}
              >
                重置密码
              </Button>
            ),
          },
        ]}
      />

      <Modal
        title={`重置密码 · ${resetUser?.display_name || resetUser?.username || ''}`}
        open={!!resetUser}
        onOk={submitReset}
        onCancel={() => setResetUser(null)}
        okText="重置"
        cancelText="取消"
      >
        <Form form={resetForm} layout="vertical">
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, max: 64, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password placeholder="至少 6 位" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

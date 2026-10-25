import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { App as AntdApp, Button, Card, Descriptions, Form, Input, Tag } from 'antd'
import { ArrowLeftOutlined, LockOutlined } from '@ant-design/icons'
import { api, errorMessage } from '../api/client'
import { useAuthStore } from '../stores/auth'

export default function ProfilePage() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()

  const submit = async (values: any) => {
    setLoading(true)
    try {
      await api.post('/auth/password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      message.success('密码已修改，请重新登录')
      form.resetFields()
      await logout()
      navigate('/login', { replace: true })
    } catch (err) {
      message.error(errorMessage(err, '修改失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '28px 20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
        <Button shape="circle" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')} />
        <div>
          <div className="page-title">个人中心</div>
          <div className="page-sub" style={{ margin: 0 }}>管理账号信息与登录密码</div>
        </div>
      </div>
      <Card style={{ marginBottom: 18, borderRadius: 14 }}>
        <Descriptions column={2} title="账号信息">
          <Descriptions.Item label="用户名">{user?.username}</Descriptions.Item>
          <Descriptions.Item label="昵称">{user?.display_name}</Descriptions.Item>
          <Descriptions.Item label="角色">
            <Tag color={user?.role === 'admin' ? 'purple' : 'blue'}>
              {user?.role === 'admin' ? '管理员' : '普通用户'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={user?.is_active ? 'green' : 'red'}>{user?.is_active ? '正常' : '禁用'}</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card style={{ borderRadius: 14 }} title="修改密码">
        <Form form={form} layout="vertical" onFinish={submit} style={{ maxWidth: 420 }} requiredMark={false}>
          <Form.Item name="old_password" label="原密码" rules={[{ required: true, message: '请输入原密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="请输入原密码" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, max: 64, message: '密码至少 6 位' },
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="至少 6 位" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                  return Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="再次输入新密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={loading}>
            保存并重新登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}

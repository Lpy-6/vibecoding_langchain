import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { App as AntdApp, Button, Form, Input, Tabs } from 'antd'
import { LockOutlined, UserOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useAuthStore } from '../stores/auth'
import { errorMessage } from '../api/client'

export default function LoginPage() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const login = useAuthStore((s) => s.login)
  const register = useAuthStore((s) => s.register)
  const [tab, setTab] = useState('login')
  const [loading, setLoading] = useState(false)

  if (user) return <Navigate to="/" replace />

  const onLogin = async (values: any) => {
    setLoading(true)
    try {
      await login(values.username, values.password)
      message.success('登录成功')
      navigate('/', { replace: true })
    } catch (err) {
      message.error(errorMessage(err, '登录失败'))
    } finally {
      setLoading(false)
    }
  }

  const onRegister = async (values: any) => {
    setLoading(true)
    try {
      await register(values.username, values.password, values.display_name || values.username)
      message.success('注册成功，已自动登录')
      navigate('/', { replace: true })
    } catch (err) {
      message.error(errorMessage(err, '注册失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-hero">
        <div className="auth-logo">
          <div className="logo-mark">智</div>
          商品知识库智能问答
        </div>
        <h1>让每一条商品资料，都能被准确回答</h1>
        <p>
          基于 LangChain 构建的企业级 RAG 知识库系统。混合检索、重排序、语义缓存与流式生成，
          回答有据可查，来源清晰可见。
        </p>
        <div className="auth-features">
          <div className="auth-feature"><span className="dot">1</span> 向量 + 关键词混合检索，引用可追溯</div>
          <div className="auth-feature"><span className="dot">2</span> 多用户、多会话，历史记录永久保存</div>
          <div className="auth-feature"><span className="dot">3</span> 异步文档解析，支持 PDF / Word / 表格 / 网页 / OCR</div>
        </div>
      </div>
      <div className="auth-panel">
        <div className="auth-card">
          <h2>{tab === 'login' ? '欢迎回来' : '创建账号'}</h2>
          <div className="sub">{tab === 'login' ? '登录后即可开始知识库问答' : '注册普通用户账号，开始提问'}</div>
          <Tabs
            activeKey={tab}
            onChange={setTab}
            items={[
              {
                key: 'login',
                label: '登录',
                children: (
                  <Form layout="vertical" onFinish={onLogin} requiredMark={false} size="large">
                    <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
                      <Input prefix={<UserOutlined />} placeholder="请输入用户名" autoFocus />
                    </Form.Item>
                    <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
                      <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" block loading={loading} style={{ height: 46, fontWeight: 600 }}>
                      登录
                    </Button>
                  </Form>
                ),
              },
              {
                key: 'register',
                label: '注册',
                children: (
                  <Form layout="vertical" onFinish={onRegister} requiredMark={false} size="large">
                    <Form.Item
                      name="username"
                      label="用户名"
                      rules={[
                        { required: true, message: '请输入用户名' },
                        { min: 3, max: 32, message: '用户名 3-32 个字符' },
                      ]}
                    >
                      <Input prefix={<UserOutlined />} placeholder="3-32 位字母、数字、下划线或中文" />
                    </Form.Item>
                    <Form.Item name="display_name" label="昵称">
                      <Input placeholder="可选，默认与用户名相同" />
                    </Form.Item>
                    <Form.Item
                      name="password"
                      label="密码"
                      rules={[
                        { required: true, message: '请输入密码' },
                        { min: 6, max: 64, message: '密码至少 6 位' },
                      ]}
                    >
                      <Input.Password prefix={<LockOutlined />} placeholder="至少 6 位" />
                    </Form.Item>
                    <Form.Item
                      name="confirm"
                      label="确认密码"
                      dependencies={['password']}
                      rules={[
                        { required: true, message: '请再次输入密码' },
                        ({ getFieldValue }) => ({
                          validator(_, value) {
                            if (!value || getFieldValue('password') === value) return Promise.resolve()
                            return Promise.reject(new Error('两次输入的密码不一致'))
                          },
                        }),
                      ]}
                    >
                      <Input.Password prefix={<SafetyCertificateOutlined />} placeholder="再次输入密码" />
                    </Form.Item>
                    <Button type="primary" htmlType="submit" block loading={loading} style={{ height: 46, fontWeight: 600 }}>
                      注册并登录
                    </Button>
                  </Form>
                ),
              },
            ]}
          />
        </div>
      </div>
    </div>
  )
}

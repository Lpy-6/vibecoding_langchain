import { useMemo } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Avatar, Button, Menu, Tag } from 'antd'
import {
  AuditOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  MessageOutlined,
  TeamOutlined,
  HomeOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '../../stores/auth'

export default function AdminLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const user = useAuthStore((s) => s.user)

  const selectedKey = useMemo(() => {
    if (location.pathname.startsWith('/admin/kbs')) return 'kbs'
    if (location.pathname.startsWith('/admin/users')) return 'users'
    if (location.pathname.startsWith('/admin/stats')) return 'stats'
    if (location.pathname.startsWith('/admin/feedback')) return 'feedback'
    if (location.pathname.startsWith('/admin/audit')) return 'audit'
    return 'kbs'
  }, [location.pathname])

  return (
    <div className="admin-shell">
      <aside className="admin-sider">
        <div className="admin-brand">
          <div className="mark">智</div>
          <div>
            <div>知识库管理后台</div>
            <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>Admin Console</div>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={[
            { key: 'kbs', icon: <DatabaseOutlined />, label: '知识库与文档' },
            { key: 'users', icon: <TeamOutlined />, label: '用户管理' },
            { key: 'stats', icon: <BarChartOutlined />, label: '数据看板' },
            { key: 'feedback', icon: <MessageOutlined />, label: '用户反馈' },
            { key: 'audit', icon: <AuditOutlined />, label: '审计日志' },
          ]}
          onClick={({ key }) => navigate(`/admin/${key}`)}
        />
        <div style={{ flex: 1 }} />
        <div style={{ padding: '14px 8px', borderTop: '1px solid rgba(148,163,184,.15)', display: 'flex', gap: 10, alignItems: 'center' }}>
          <Avatar style={{ background: '#4f46e5' }}>{user?.display_name?.[0] || 'A'}</Avatar>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: '#e2e8f0', fontSize: 13, fontWeight: 600 }}>{user?.display_name || user?.username}</div>
            <div style={{ color: '#94a3b8', fontSize: 11 }}>管理员</div>
          </div>
        </div>
      </aside>

      <div className="admin-main">
        <div className="admin-topbar">
          <Button type="text" icon={<HomeOutlined />} onClick={() => navigate('/')}>
            返回问答
          </Button>
          <Tag color="purple">RAG 知识库</Tag>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 12, color: '#64748b' }}>管理员：{user?.username}</span>
        </div>
        <div className="admin-content">
          <Outlet />
        </div>
      </div>
    </div>
  )
}

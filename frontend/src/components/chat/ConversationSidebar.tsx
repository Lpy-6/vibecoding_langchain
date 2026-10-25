import { Avatar, Button, Dropdown, Input, Tooltip } from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  LogoutOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons'
import type { Conversation, User } from '../../types'
import { fromNow } from '../../utils'

interface Props {
  conversations: Conversation[]
  activeId: string | null
  search: string
  user: User
  onSearch: (value: string) => void
  onSelect: (conv: Conversation) => void
  onNew: () => void
  onRename: (conv: Conversation) => void
  onDelete: (conv: Conversation) => void
  onProfile: () => void
  onAdmin: () => void
  onLogout: () => void
}

export default function ConversationSidebar({
  conversations,
  activeId,
  search,
  user,
  onSearch,
  onSelect,
  onNew,
  onRename,
  onDelete,
  onProfile,
  onAdmin,
  onLogout,
}: Props) {
  return (
    <aside className="chat-sidebar">
      <div className="sidebar-brand">
        <div className="mark">智</div>
        <div>
          <div style={{ lineHeight: 1.2 }}>商品知识库</div>
          <div style={{ fontSize: 11, color: '#94a3b8', fontWeight: 400 }}>RAG 智能问答</div>
        </div>
      </div>

      <Button type="primary" icon={<PlusOutlined />} className="new-chat-btn" onClick={onNew} block>
        新建会话
      </Button>

      <Input
        allowClear
        prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
        placeholder="搜索历史会话"
        value={search}
        onChange={(e) => onSearch(e.target.value)}
      />

      <div className="conv-list">
        <div className="conv-list-title">历史会话</div>
        {!conversations.length && (
          <div style={{ fontSize: 12, color: '#94a3b8', padding: '8px 10px' }}>暂无会话，点击上方开始提问</div>
        )}
        {conversations.map((conv) => (
          <div
            key={conv.id}
            className={`conv-item ${activeId === conv.id ? 'active' : ''}`}
            onClick={() => onSelect(conv)}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="title">{conv.title || '新会话'}</div>
              <div className="time">{fromNow(conv.last_message_at)} · {conv.message_count} 条消息</div>
            </div>
            <div className="actions" onClick={(e) => e.stopPropagation()}>
              <Dropdown
                trigger={['click']}
                menu={{
                  items: [
                    { key: 'rename', icon: <EditOutlined />, label: '重命名' },
                    { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true },
                  ],
                  onClick: ({ key }) => (key === 'rename' ? onRename(conv) : onDelete(conv)),
                }}
              >
                <Button type="text" size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </div>
          </div>
        ))}
      </div>

      <div className="sidebar-user">
        <Avatar style={{ background: '#eef2ff', color: '#4f46e5' }} icon={<UserOutlined />} />
        <div className="meta">
          <div className="name">{user.display_name || user.username}</div>
          <div className="role">{user.role === 'admin' ? '管理员' : '普通用户'}</div>
        </div>
        <Dropdown
          trigger={['click']}
          placement="topRight"
          menu={{
            items: [
              { key: 'profile', icon: <SettingOutlined />, label: '个人中心 / 修改密码' },
              ...(user.role === 'admin'
                ? [{ key: 'admin', icon: <SettingOutlined />, label: '知识库管理后台' }]
                : []),
              { type: 'divider' as const },
              { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
            ],
            onClick: ({ key }) => {
              if (key === 'profile') onProfile()
              if (key === 'admin') onAdmin()
              if (key === 'logout') onLogout()
            },
          }}
        >
          <Tooltip title="账号设置">
            <Button type="text" icon={<MoreOutlined />} />
          </Tooltip>
        </Dropdown>
      </div>
    </aside>
  )
}

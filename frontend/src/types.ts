export interface User {
  id: string
  username: string
  email?: string | null
  display_name: string
  role: 'admin' | 'user'
  is_active: boolean
  created_at: string
  last_login_at?: string | null
}

export interface KnowledgeBase {
  id: string
  name: string
  description: string
  is_public: boolean
  version: number
  doc_count: number
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface DocumentItem {
  id: string
  kb_id: string
  title: string
  source_type: string
  original_filename?: string | null
  mime_type?: string | null
  size_bytes: number
  source_url?: string | null
  status: string
  error_message?: string | null
  page_count: number
  chunk_count: number
  ocr_pages: number
  created_at: string
  updated_at: string
}

export interface IngestTask {
  id: string
  document_id: string
  kb_id: string
  task_type: string
  status: string
  stage: string
  progress: number
  attempts: number
  max_attempts: number
  error?: string | null
  created_at: string
}

export interface ChunkItem {
  id: number
  chunk_type: 'parent' | 'child'
  ordinal: number
  content: string
  token_count: number
  page_no?: number | null
  sheet_name?: string | null
  row_start?: number | null
  row_end?: number | null
  heading_path?: string | null
  parent_id?: number | null
}

export interface Citation {
  id?: number
  rank: number
  chunk_id?: number | null
  document_id?: string | null
  kb_id?: string | null
  snippet: string
  doc_title: string
  locator: Record<string, any>
  dense_score?: number | null
  sparse_score?: number | null
  rerank_score?: number | null
  used?: boolean
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  status: string
  model?: string | null
  latency_ms?: number | null
  created_at: string
  citations: Citation[]
  feedback?: number | null
  cache_hit?: boolean
  retrieval_meta?: Record<string, any>
}

export interface Conversation {
  id: string
  title: string
  kb_ids: string[]
  message_count: number
  last_message_at: string
  created_at: string
}

export interface ConversationDetail {
  conversation: Conversation
  items: ChatMessage[]
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface SSEHandlers {
  onMeta?: (data: any) => void
  onStage?: (data: { stage: string }) => void
  onCache?: (data: any) => void
  onRewrite?: (data: any) => void
  onSources?: (data: { sources: Citation[]; rewritten_query?: string; keywords?: string[] }) => void
  onToken?: (data: { delta: string }) => void
  onUsage?: (data: any) => void
  onDone?: (data: any) => void
  onError?: (data: { message: string }) => void
  onClose?: () => void
}

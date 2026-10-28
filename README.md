# 电商商品知识库 RAG 智能问答系统

基于 **LangChain** 构建的面向电商商品场景的企业级知识库问答系统。支持知识库管理、多用户多会话、流式问答与**可追溯引用**，并实现混合检索、重排序、查询改写、语义缓存、异步文档解析、限流、监控与离线评测。

> 本项目针对“无 Docker、单机 Windows”环境做了本地化适配：业务数据使用 SQLite，向量检索使用进程内 numpy 索引，中文关键词检索使用 jieba + BM25，异步任务使用线程池。所有企业级能力（权限、异步摄入、缓存、限流、监控、评测）均保留，生产化替换路径见文末。

---

## 1. 功能清单

### 普通用户
- 注册、登录、修改密码、退出登录
- 多知识库选择，流式问答（SSE）
- 回答中的 `[1][2]` 引用编号 + 来源卡片 + 来源抽屉（文档名、页码/工作表/行、片段、检索分数）
- 多会话管理：新建、重命名、删除、搜索、历史恢复
- 点赞/点踩反馈、复制回答、导出 Markdown
- 会话与消息持久化，跨登录找回

### 管理员（`admin / 123456`）
- 知识库 CRUD、公开/私有可见性、按用户授权
- 文档管理：批量上传、URL 导入、实时解析进度、失败重试、重索引、分块预览、删除
- 支持 PDF / Word / TXT / Markdown / Excel / CSV / 图片 OCR / 网页
- 用户管理：启用/禁用、角色调整、重置密码
- 数据看板：问答量、Token/延迟、缓存、反馈、近 7 天趋势
- 用户反馈列表、审计日志、语义缓存清理
- 所有管理接口后端强制 RBAC，普通用户直接请求返回 `403`

---

## 2. 技术栈

| 层次 | 选型 |
|---|---|
| 后端 | Python 3.12、FastAPI、SQLAlchemy 2.0 async、Pydantic v2、Uvicorn |
| RAG 框架 | **LangChain 1.x**：`ChatOpenAI`、`ChatPromptTemplate`、LCEL、`StrOutputParser`、`RecursiveCharacterTextSplitter` |
| 模型 | 阿里云百炼：`qwen-plus`、`text-embedding-v4`（1024 维）、`gte-rerank-v2`、`qwen-vl-ocr` |
| 存储 | SQLite（WAL）+ 本地文件存储 |
| 检索 | 稠密向量（numpy 余弦）+ jieba/BM25 稀疏检索 + RRF + 重排序 |
| 前端 | React 18、TypeScript、Vite 6、Ant Design 5、Zustand、React Markdown |
| 认证 | JWT Access Token（内存）+ HttpOnly Refresh Cookie（轮换 + 重放检测）+ Argon2 |
| 可观测 | Prometheus `/metrics`、结构化日志、`X-Request-ID`、`/healthz`、`/readyz` |

### 为什么没有 Docker / PostgreSQL？

运行环境无法使用 Docker，Windows 下安装 pgvector + 中文分词的 PostgreSQL 成本过高，因此采用可零安装运行的本地栈：

- SQLite 代替 PostgreSQL：保留完整关系模型与索引；WAL + busy_timeout 支持 API 与后台线程并发读写
- numpy 内存索引代替 pgvector HNSW：万级分块下查询为毫秒级，按知识库版本懒加载并自动失效
- jieba + BM25 代替 zhparser 全文索引：中文分词、同义词扩展、IDF 加权
- 线程池 + 数据库任务表代替 Celery/Redis：支持进度、重试、幂等
- 进程内滑动窗口限流 + 指标代替 Redis 限流

生产化时可保持 API/表结构不变，将 `app/ingest/vector_index.py` 替换为 pgvector/Qdrant 实现，将任务执行器替换为 Celery 即可。

---

## 3. 快速开始

### 3.1 环境要求
- **Python 3.12**（务必使用 3.12；3.15 生态兼容性不足）
- Node.js 20+（当前已验证 Node 24）
- 无需 Docker、无需 PostgreSQL/Redis

### 3.2 安装依赖

```bash
# 仓库根目录
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
cd ..

cd frontend
npm install
cd ..
```

### 3.3 配置

```bash
# Windows CMD/PowerShell
copy .env.example .env
```

编辑 `.env`：

```ini
# 留空 = 离线 Mock 模式；填入百炼 Key 并重启 = 真实模型
DASHSCOPE_API_KEY=
CHAT_MODEL=qwen-plus
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIM=1024
RERANK_MODEL=gte-rerank-v2
OCR_MODEL=qwen-vl-ocr
```

### 3.4 初始化演示数据

```bash
backend/.venv/Scripts/python.exe scripts/seed_demo.py
```

会创建：
- 管理员 `admin / 123456`
- 演示用户 `demo / demo123`
- 「商品知识库」及 6 个不同格式的演示文档（Markdown、Word、Excel、PDF、网页），共 33 个子块

### 3.5 启动

```bash
# 终端 1
start_backend.bat
# 或：backend/.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端 2
start_frontend.bat
# 或：cd frontend && npm run dev
```

打开 **http://127.0.0.1:5173**。

| 地址 | 说明 |
|---|---|
| http://127.0.0.1:5173 | 前端 |
| http://127.0.0.1:8000/docs | Swagger API |
| http://127.0.0.1:8000/readyz | 就绪检查 |
| http://127.0.0.1:8000/metrics | Prometheus 指标 |

---

## 4. 接入真实模型（百炼）

1. 在阿里云百炼控制台创建 API Key。
2. 写入 `.env` 的 `DASHSCOPE_API_KEY`。
3. **重启后端**（向量提供方在进程启动时确定）。
4. 重要：演示数据是用离线哈希向量生成的，切换后需要重新向量化：
   ```bash
   backend/.venv/Scripts/python.exe scripts/reindex_all.py
   ```
5. 重启后端，打开管理端「数据看板」，确认：
   - 生成模式：百炼在线模型
   - 向量模型：`text-embedding-v4`
   - 提示词版本、重排模型正确

> 切换模型后如果不重索引，旧向量不会被检索（系统按 `embedding_model` 过滤，避免混合不同向量空间）。
> 离线模式仅用于无 Key 演示，检索偏词面匹配；真实百炼 Embedding + Rerank 才能发挥语义检索效果。

---

## 5. 目录结构

```
rag_project/
├─ backend/
│  ├─ app/
│  │  ├─ api/           # auth / kbs / documents / chat / admin / health
│  │  ├─ core/          # 配置、JWT、Argon2、权限依赖、限流、指标
│  │  ├─ db/            # 模型与会话（async + sync 双引擎）
│  │  ├─ ingest/        # 解析器、父子分块、摄入流水线、线程池任务、向量索引
│  │  ├─ llm/           # 百炼 Embedding / Rerank / OCR 原生 API 客户端
│  │  ├─ rag/           # 归一化、改写、混合检索、RRF、重排、提示词、LCEL 链、引用
│  │  ├─ services/      # 权限、缓存、审计、统计、存储
│  │  ├─ schemas.py     # Pydantic 请求/响应
│  │  ├─ seed.py        # 幂等初始化 admin/demo/默认知识库
│  │  └─ main.py        # FastAPI 入口、中间件、静态托管
│  ├─ tests/            # pytest 单元测试
│  └─ pyproject.toml
├─ frontend/src/
│  ├─ api/client.ts     # Axios + Refresh 单飞 + SSE 解析
│  ├─ components/       # 消息、引用抽屉、会话侧栏、ErrorBoundary
│  ├─ pages/            # 登录、问答、个人中心、管理端 6 个页面
│  └─ stores/auth.ts
├─ scripts/
│  ├─ seed_demo.py      # 演示数据（多格式）
│  ├─ reindex_all.py    # 切换模型后全量重索引
│  └─ smoke_e2e.py      # 端到端冒烟测试
├─ eval/
│  ├─ golden/qa.jsonl   # 20 条评测集
│  ├─ run_eval.py       # 检索命中/引用/延迟评测
│  ├─ run_ragas.py      # 可选 RAGAS 评测
│  └─ results.csv       # 最近一次评测明细
├─ .env.example
├─ start_backend.bat / start_frontend.bat / seed_demo.bat
└─ README.md
```

---

## 6. RAG 问答链路

```
用户问题
  │
  ├─ 1. 归一化（NFKC、去控制符、限长）
  ├─ 2. 知识库可见性校验（公开 / 授权 / 管理员）
  ├─ 3. 语义缓存（精确命中 → 向量相似度 ≥ 0.95）
  ├─ 4. 多轮改写（仅指代/短追问触发；输出独立问题 + 关键词）
  ├─ 5. 混合检索
  │     ├─ 稠密：numpy 归一化矩阵余弦，Top 40
  │     └─ 稀疏：jieba search 分词 + 同义词扩展 + BM25，Top 40
  ├─ 6. RRF 融合（稠密 1.0 / 稀疏 0.8，k=60）
  ├─ 7. Rerank（gte-rerank-v2 Top 8；失败自动降级为 IDF 词法重排）
  ├─ 8. 父块回填（子块命中 → 父块作为生成上下文，按父块去重）
  ├─ 9. 上下文预算（约 6000 字符，按分数裁剪到段落边界）
  ├─ 10. LCEL 链流式生成（qwen-plus；无 Key 时抽取式 Mock）
  ├─ 11. 引用校验（正则提取 [n]，丢弃越界编号，标记 used）
  └─ 12. 持久化消息、引用快照、会话标题、语义缓存
```

### 引用如何做到“可追溯”
- 每个知识块在入库时保留 `page_no / sheet_name / row_start / row_end / heading_path` 定位信息
- 回答完成后解析 `[n]`，只保留合法编号；前端展示所有检索来源，高亮实际使用项
- `message_citations` 保存片段快照与文档标题，即使原文档删除，历史回答仍可查看来源
- 来源抽屉展示向量分、关键词分、重排分，便于答辩演示检索过程

### 父子分块
- 父块约 1200 字（生成上下文），子块约 300 字（检索单元，overlap 50）
- 子块嵌入时前置「文档标题 › 标题路径」，提升标题类问题的召回
- 表格按行组织，避免跨行截断；Excel 每 20 行一块并重复表头

---

## 7. LangChain 使用位置

| 能力 | 文件 | 用法 |
|---|---|---|
| 对话模型 | `backend/app/rag/chain.py` | `ChatOpenAI(base_url=百炼兼容模式)` |
| 提示词 | `backend/app/rag/prompts.py` | `ChatPromptTemplate.from_messages` |
| LCEL 流式链 | `backend/app/rag/chain.py` | `prompt \| llm \| StrOutputParser()` + `astream` |
| 文本切分 | `backend/app/ingest/chunker.py` | `RecursiveCharacterTextSplitter`（中文分隔符） |
| 查询改写 | `backend/app/rag/rewrite.py` | `ChatOpenAI.ainvoke` + JSON 解析 |
| 检索 | `backend/app/rag/retriever.py` | 为支持“向量 + BM25 + RRF + 父块”单条 SQL/内存融合，使用自定义检索并返回统一来源结构 |

---

## 8. 企业级设计要点

1. **混合检索 + RRF + 重排 + 查询改写**：提升召回与准确率
2. **语义缓存**：相似问题直接返回；缓存 key 包含知识库版本、模型、提示词版本与检索配置，内容变更自动失效
3. **异步摄入**：线程池 + 任务表，阶段进度（解析/切分/向量化/写入）、最多 3 次重试、内容哈希去重、失败可重试
4. **流式 SSE**：先发 `meta` → `sources` → `token*` → `usage` → `done`，Nginx 关闭缓冲，前端可停止生成
5. **认证安全**：Argon2、Access JWT 短时有效、Refresh Cookie 轮换 + 复用检测、改密后 `token_version` 全局失效
6. **权限模型**：公开库 / 私有库 + 显式授权；所有文档、会话、消息接口做所有权校验
7. **输入安全**：上传扩展名/大小校验、URL 导入 SSRF 防护（DNS 解析 + 私网/回环拦截 + 重定向校验）、检索内容视为数据防提示注入
8. **稳定性**：限流、健康检查、请求 ID、统一异常、任务失败可观测
9. **可观测**：HTTP / RAG 阶段延迟直方图、缓存命中、反馈、文档任务指标
10. **评测闭环**：20 条黄金问题 + 检索命中/引用率/延迟 + 可选 RAGAS

---

## 9. 测试与评测

### 单元/集成测试

测试方法论已迁移为项目 Skill：`.zcode/skills/generate-tests/`（Given-When-Then 用例设计与规则）。

```bash
# 后端：98 项，覆盖率 75%
cd backend
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m pytest --cov=app --cov-report=term-missing -q

# 前端：13 项（Vitest）
cd ../frontend
npm run typecheck
npm test
```

覆盖：认证/JWT/Refresh 轮换、RBAC 与私有库授权、会话隔离、SSE 事件顺序、引用落库、语义缓存、反馈、文档上传→异步解析→检索→删除、去重与重索引、管理端统计/用户/审计、MD/Word/Excel/CSV/PDF/HTML 解析、OCR HTML 清洗、SSRF、限流、缓存 key 版本化、前端定位/格式化/错误提示。

> 测试全程使用临时 SQLite 与 `LLM_MODE=mock`，不读取 `data/` 演示库、不调用真实模型、不产生费用。首次运行前需安装开发依赖（`pytest-cov`、`vitest`）。

### 端到端冒烟测试

先启动后端，然后：

```bash
backend/.venv/Scripts/python.exe scripts/smoke_e2e.py
```

覆盖：管理员/普通用户权限、私有库授权与撤销、文档上传→异步解析→检索→删除、问答引用、语义缓存、反馈、会话持久化、统计、审计、Prometheus。

最近一次结果：**全部通过**。

### 检索/回答评测

```bash
backend/.venv/Scripts/python.exe eval/run_eval.py
# 仅重算已有结果（不重新请求）：--rescore
```

**真实百炼模式（qwen-plus + text-embedding-v4 + gte-rerank-v2，20 条问题）：**

| 指标 | 结果 |
|---|---|
| 检索命中率（关键词出现在引用片段） | **1.000** |
| 回答命中率（关键词出现在回答，归一化比较） | **1.000** |
| 引用率（有有效 `[n]` 且有来源） | **1.000** |
| 平均首字延迟（含检索/重排/模型首包） | **1.32 s** |
| P95 首字延迟 | **1.76 s** |
| 平均总延迟 | **3.04 s** |
| P95 总延迟 | **6.62 s** |

**离线 Mock 模式（历史数据，无 Key 演示用）：**

| 指标 | 结果 |
|---|---|
| 检索 / 回答 / 引用命中率 | 1.000 / 1.000 / 1.000 |
| 平均延迟 | 47 ms |

明细见 `eval/results.csv`（真实模式）与 `eval/results_mock.csv`（离线模式）。

### 压力测试（100 并发）

使用 Locust 模拟 100 人同时使用（隔离 `data_stress/` 环境 + `LLM_MODE=mock`，不触碰演示库、不产生模型费用）：

```bat
stress\run_stress.bat pilot   REM 5 并发 1 分钟试跑
stress\run_stress.bat full    REM S1/S2 各 10 分钟 + S3 阶梯加压
```

核心结论（详见 [stress/STRESS-REPORT.md](stress/STRESS-REPORT.md)）：

| 场景 | 结果 |
|---|---|
| S1 稳态 100 并发纯问答 10min | 24,376 次问答 / 40.65 req/s，**0 失败**，完整回答 P50 85ms / P95 1.9s |
| S2 混合负载 100 并发 10min | 48,037 请求 / 80.2 RPS，**0 失败**，聚合 P95 2.4s |
| S3 阶梯 10→30→60→100 | 60 并发内 P95 <200ms；100 并发 P95 1.1s（软拐点），仍 0 错误 |

语义缓存命中率 99.96%（热点问题近零成本）、SQLite 锁错误 0、内存稳定无泄漏。

> 评测集为 20 条商品 FAQ / 售后 / 促销问题，采用“关键词命中 + 引用存在”作为轻量指标，不代表完整语义质量；论文中建议补充 RAGAS 的 Faithfulness / Context Recall / Answer Relevancy，并对比“纯向量 / 混合检索 / 混合+重排 / +查询改写”四组配置。

### RAGAS 评测（可选）

```bash
uv pip install --python backend/.venv/Scripts/python.exe -r eval/requirements-ragas.txt
set DASHSCOPE_API_KEY=sk-xxx
backend/.venv/Scripts/python.exe eval/run_ragas.py
```

### 真实接口验证记录

- 百炼 `text-embedding-v4`：1024 维、归一化正常，单批耗时约 0.5 s
- `gte-rerank-v2`：返回相关度排序正常，约 0.3 s
- `qwen-plus`：OpenAI 兼容模式流式对话正常
- `qwen-vl-ocr`：图片 OCR 正常；系统会清洗 OCR 返回的 HTML 包裹
- 6 个演示文档已用真实向量重建索引（33 个子块）

---

## 10. 主要 API

完整文档见 `http://127.0.0.1:8000/docs`。

| 模块 | 接口 |
|---|---|
| 认证 | `POST /auth/register` `login` `refresh` `logout` `password`、`GET /auth/me` |
| 问答 | `POST /chat/stream`（SSE）、`GET /conversations`、`GET /conversations/{id}/messages`、`PATCH/DELETE /conversations/{id}` |
| 引用/反馈 | `GET /messages/{id}/citations`、`POST/DELETE /messages/{id}/feedback` |
| 知识库 | `GET /kbs`、管理端 `/admin/kbs` CRUD、`PUT /admin/kbs/{id}/permissions` |
| 文档 | `POST /admin/kbs/{id}/documents`、`POST .../documents/url`、`DELETE /admin/documents/{id}`、`POST .../reindex`、`GET .../chunks` |
| 任务 | `GET /admin/tasks/{id}`、`GET /admin/tasks/{id}/events`（SSE 进度） |
| 管理 | `/admin/users`、`/admin/stats/overview`、`/admin/stats/qa`、`/admin/feedback`、`/admin/audit-logs`、`/admin/cache`、`/admin/system` |
| 运维 | `/healthz`、`/readyz`、`/metrics` |

SSE 事件：`meta`、`stage`、`cache`、`rewrite`、`sources`、`token`、`usage`、`done`、`error`。

---

## 11. 数据模型

| 表 | 作用 |
|---|---|
| `users` / `refresh_tokens` | 账号、角色、状态、令牌轮换 |
| `knowledge_bases` / `kb_permissions` | 知识库与私有授权 |
| `documents` | 文档元数据、解析状态、内容哈希、定位 |
| `chunks` | 父子块、向量 BLOB、页码/工作表/行、标题路径、向量模型 |
| `conversations` / `messages` | 多用户多会话、消息序号、状态、延迟、Token |
| `message_citations` | 引用快照（即使原文删除也可回看） |
| `feedback` / `audit_logs` | 反馈闭环与审计 |
| `semantic_cache` | 语义缓存（含知识库版本） |
| `ingest_tasks` | 解析任务进度与重试 |

---

## 12. 常见问题

**Q：启动报 `greenlet` 缺失？**  
使用 `uv pip install -e ".[dev]"` 安装，`sqlalchemy[asyncio]` 会自动带上 greenlet；也可手动 `uv pip install greenlet`。

**Q：页面一直显示“登录”/刷新后退出？**  
确认后端 `JWT_SECRET` 稳定，且未清空 `data/app.db`；清库后需要重新登录。Refresh Cookie 路径为 `/api/v1/auth`，请通过前端代理访问，不要跨端口直接调后端。

**Q：切换百炼 Key 后回答“未找到相关信息”？**  
旧文档仍是哈希向量，被 `embedding_model` 过滤。执行 `scripts/reindex_all.py` 后重启后端。

**Q：扫描 PDF / 图片没有内容？**  
需要配置 `DASHSCOPE_API_KEY`，系统会调用 `qwen-vl-ocr`；离线模式无法 OCR。

**Q：时间显示相差 8 小时？**  
后端统一存 UTC，前端 `fmtTime` 转为本地时区；若浏览器时区为 UTC 则显示 UTC。

**Q：如何重置演示数据？**  
停止后端，删除 `data/app.db*` 与 `data/uploads/*`，重新执行 `scripts/seed_demo.py`。

**Q：端口被占用？**  
后端默认 8000，前端 5173；可在 `start_backend.bat` 与 `frontend/vite.config.ts` 修改。

---

## 13. 安全与生产化建议

- 首次部署后立即修改 `admin` 默认密码，并更换 `JWT_SECRET`
- 生产环境启用 HTTPS，并将 Refresh Cookie 的 `secure` 改为 `True`
- SQLite 适合单机答辩/小规模团队；高并发/多实例建议替换为 PostgreSQL + pgvector，Redis + Celery
- 增加登录验证码、邮箱验证、SSO、细粒度文档权限、内容审核等
- 对上传文件做病毒扫描；对 URL 导入做更严格的出网代理
- 建议把 `eval/` 接入 CI，持续跟踪检索命中与引用率

---

## 14. 论文可展开的技术点

1. RAG 系统架构与各模块职责（前端、API、检索、生成、存储）
2. 混合检索与 RRF 的公式与实验对比
3. 父子分块对长文档问答的收益
4. 查询改写触发条件与多轮对话消歧
5. 语义缓存的版本化失效机制与命中率
6. 引用溯源的数据结构（定位信息 + 快照）
7. 异步摄入与失败重试的可靠性设计
8. 权限模型与 JWT/Refresh 轮换安全分析
9. 离线评测与 RAGAS 指标（Faithfulness / Context Recall / Answer Relevancy）
10. 与纯向量 RAG 的延迟、成本、准确率对比

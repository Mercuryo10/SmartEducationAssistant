# API 接口设计

> 配套文档：`00-项目总览.md`（接口前缀/端口基线）· `02-系统架构设计.md`（数据流）。
> 约定：统一前缀 `/api/v1`；请求/响应均 JSON（上传除外）；错误统一结构 `{"code": ..., "message": ..., "detail": ...}`（见 §8）。
> 路由文件位置：`app/api/`，一个模块对应一组接口。

## 1. 全局约定

| 项 | 约定 |
|----|------|
| 基础路径 | `http://localhost:8000/api/v1` |
| 鉴权 | 简化：`Authorization: Bearer <token>`（可选启用）。未带 token 时默认 `demo` 用户（`APP_ENV=dev` 下） |
| 时间格式 | ISO 8601 字符串（UTC，如 `2026-08-17T06:00:00Z`） |
| 分页 | `page`（默认 1）/ `page_size`（默认 20），响应含 `total` |
| 流式 | 聊天接口用 **SSE**：`Content-Type: text/event-stream` |
| 上传限制 | 图片 `image/jpeg, image/png, image/webp`，音频 `audio/wav, audio/mp3`，单文件 ≤ 10MB |

## 2. 接口一览

| # | 方法 | 路径 | 说明 | 流式 |
|---|------|------|------|------|
| 1 | POST | `/api/v1/auth/register` | 注册 | — |
| 2 | POST | `/api/v1/auth/login` | 登录（返回 token） | — |
| 3 | GET | `/api/v1/auth/me` | 当前用户信息 | — |
| 4 | POST | `/api/v1/chat` | 多模态智能答疑（multipart） | ✅ SSE |
| 5 | GET | `/api/v1/conversations` | 会话列表 | — |
| 6 | GET | `/api/v1/conversations/{conversation_id}/messages` | 会话消息历史 | — |
| 7 | POST | `/api/v1/homework/grade` | 作业批改（multipart 上传图片） | — |
| 8 | GET | `/api/v1/homework/submissions/{submission_id}` | 查询批改结果 | — |
| 9 | POST | `/api/v1/mistakes` | 录入错题 | — |
| 10 | GET | `/api/v1/mistakes` | 错题列表（可按知识点过滤） | — |
| 11 | POST | `/api/v1/mistakes/{mistake_id}/analyze` | 错题讲解（AI 生成） | — |
| 12 | GET | `/api/v1/knowledge-points` | 知识点列表 | — |
| 13 | POST | `/api/v1/exercises/generate` | 生成练习题 | — |
| 14 | POST | `/api/v1/push/create` | 创建推送任务 | — |
| 15 | POST | `/api/v1/push/plan` | 按遗忘曲线生成复习计划 | — |
| 16 | GET | `/api/v1/push/logs` | 推送日志列表 | — |
| 17 | GET | `/api/v1/health` | 健康检查 | — |

## 3. 鉴权接口

### 3.1 注册 `POST /auth/register`

```json
// Request
{ "username": "alice", "password": "123456", "nickname": "爱丽丝" }
// Response 200
{ "id": 1, "username": "alice", "nickname": "爱丽丝", "role": "student" }
```

### 3.2 登录 `POST /auth/login`

```json
// Request
{ "username": "demo", "password": "demo123" }
// Response 200
{ "token": "eyJhbGciOi...", "user": { "id": 1, "username": "demo", "nickname": "演示用户", "role": "student" } }
```

> 实现提示：token 可用 `itsdangerous` 或 `pyjwt` 签发，有效期 1 天；演示环境可 `APP_ENV=dev` 下跳过强校验。

## 4. 智能答疑（核心，SSE 流式）

### 4.1 发起对话 `POST /chat`（multipart/form-data）

**字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | ✅ | 用户问题 |
| `conversation_id` | string/int | 否 | 续接已有会话；缺省新建 |
| `file` | file | 否 | 图片（走 OCR）或音频（走语音转写） |

**示例（curl）**：

```bash
curl -N http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer <token>" \
  -F "message=请讲一下 Transformer 中的注意力机制" \
  -F "conversation_id=3" \
  -F "file=@question.jpg"
```

**响应（SSE 事件流）**：

```
event: meta
data: {"conversation_id": 3, "message_id": 12, "task": "qa"}

event: token
data: {"text": "注意力机制是 Transformer 的核心..."}

event: token
data: {"text": "它通过 Q、K、V 三个矩阵计算..."}

event: done
data: {"message_id": 12, "source_refs": [{"doc_id": 1, "source": "大模型导论·注意力机制", "snippet": "..."}]}

event: error
data: {"code": "LLM_ERROR", "message": "上游模型调用失败", "detail": "..."}
```

**SSE 事件类型约定**：

| event | 载荷 | 说明 |
|-------|------|------|
| `meta` | `{conversation_id, message_id, task}` | 会话与消息标识 |
| `token` | `{text}` | 流式文本增量 |
| `done` | `{message_id, source_refs}` | 结束，携带溯源 |
| `error` | `{code, message, detail}` | 出错（其后关闭流） |

> 实现提示：后端用 `StreamingResponse(media_type="text/event-stream")` + `async` 生成器；流结束或异常都要正确关闭。

### 4.2 会话历史 `GET /conversations/{conversation_id}/messages`

```json
// Response 200
{
  "conversation_id": 3,
  "messages": [
    { "id": 11, "role": "user", "content": "请讲一下 Transformer 中的注意力机制", "created_at": "..." },
    { "id": 12, "role": "assistant", "content": "注意力机制是 Transformer 的核心...", "source_refs": [...], "created_at": "..." }
  ]
}
```

## 5. 作业批改

### 5.1 提交批改 `POST /homework/grade`（multipart/form-data）

**字段**：`file`（图片，必填）、`answer_key`（参考答案文本，选填）、`question_type_hint`（选填，如 `choice+fill+solve`）。

```json
// Response 200（同步返回批改结果）
{
  "submission_id": 5,
  "status": "done",
  "summary": { "total": 3, "correct": 2, "objective_score": 80 },
  "items": [
    {
      "question_no": 1, "question_type": "objective", "question_text": "Transformer 自注意力由哪三个矩阵计算得到？",
      "student_answer": "K、V、Q 三个矩阵", "reference_answer": "Q（查询）、K（键）、V（值）三个矩阵",
      "is_correct": true, "score": 100, "comment": ""
    },
    {
      "question_no": 2, "question_type": "objective", "question_text": "...",
      "student_answer": "B", "reference_answer": "B", "is_correct": true, "score": 100, "comment": ""
    },
    {
      "question_no": 3, "question_type": "subjective", "question_text": "...",
      "student_answer": "...", "reference_answer": "...",
      "score": 86, "comment": "思路正确，过程略简化，注意写全步骤", "is_ai_scored": true
    }
  ]
}
```

> 说明：图片可多张（`files` 数组）；多张时按提交顺序拼接文本后批改。

### 5.2 查询结果 `GET /homework/submissions/{submission_id}`

返回与上一致的批改结构（从 `grading_results` 读取）。

## 6. 错题分析

### 6.1 录入错题 `POST /mistakes`

```json
// Request
{
  "question_text": "简述 RAG 为什么能缓解大模型幻觉？",
  "wrong_answer": "RAG 只是把检索结果拼进 prompt",
  "correct_answer": "RAG 通过检索相关证据片段约束生成，降低对参数化记忆的依赖",
  "knowledge_point_name": "检索增强生成（RAG）"   // 选填；缺省由 AI 自动关联
}
// Response 201
{ "id": 9, "knowledge_point_id": 3, "knowledge_point_name": "检索增强生成（RAG）", "created_at": "..." }
```

### 6.2 错题列表 `GET /mistakes?user_id=&knowledge_point_id=&page=&page_size=`

```json
// Response 200
{
  "total": 12, "page": 1, "page_size": 20,
  "items": [
    { "id": 9, "question_text": "...", "error_type": "概念混淆",
      "knowledge_point_id": 3, "knowledge_point_name": "检索增强生成（RAG）", "created_at": "..." }
  ]
}
```

### 6.3 错题讲解 `POST /mistakes/{mistake_id}/analyze`

```json
// Response 200
{
  "mistake_id": 9,
  "knowledge_point": "检索增强生成（RAG）",
  "analysis": "该题错误模式为概念混淆：把 RAG 简单理解为文本拼接，忽略了检索对生成的约束作用...",
  "explanation": "RAG 的基本流程：检索（Retrieval）→ 增强（Augmentation）→ 生成（Generation）...",
  "common_mistakes": ["把 RAG 理解为纯文本拼接", "忽略检索质量对回答的影响"],
  "variant_exercise": "请说明 RAG 的检索阶段与生成阶段各自的作用（提示：本题为同类变式）"
}
```

## 7. 练习生成 / 学习推送

### 7.1 生成练习题 `POST /exercises/generate`

```json
// Request
{
  "knowledge_point_id": 3,
  "difficulty": "medium",          // easy / medium / hard
  "question_type": "solve",        // choice / fill / solve
  "count": 3
}
// Response 200
{
  "items": [
    {
      "question_text": "下列关于注意力机制的表述，正确的是（  ）",
      "answer": "C（自注意力通过 Q/K/V 三个矩阵计算加权表示）",
      "explanation": "自注意力通过 Q 与 K 计算注意力权重，再与 V 加权求和，得到序列中各位置的表示",
      "difficulty": "medium",
      "knowledge_point_id": 3
    }
  ]
}
```

### 7.2 创建推送任务 `POST /push/create`

```json
// Request（二选一：直接指定时间，或用遗忘曲线计划）
{
  "user_id": 1,
  "content": "该复习【注意力机制】了",
  "scheduled_at": "2026-08-18T09:00:00Z",
  "channel": "mock"
}
// Response 201
{ "id": 7, "status": "pending", "scheduled_at": "2026-08-18T09:00:00Z" }
```

### 7.3 遗忘曲线复习计划 `POST /push/plan`

```json
// Request
{ "user_id": 1, "knowledge_point_id": 3, "start_date": "2026-08-17" }
// Response 200（间隔 1/2/4/7 天）
{ "items": [
  { "scheduled_at": "2026-08-18T09:00:00Z", "content": "复习：注意力机制（第1次）" },
  { "scheduled_at": "2026-08-19T09:00:00Z", "content": "复习：注意力机制（第2次）" },
  { "scheduled_at": "2026-08-21T09:00:00Z", "content": "复习：注意力机制（第3次）" },
  { "scheduled_at": "2026-08-24T09:00:00Z", "content": "复习：注意力机制（第4次）" }
]}
```

### 7.4 推送日志 `GET /push/logs?page=&page_size=`

```json
// Response 200
{ "total": 8, "items": [ { "id": 1, "task_id": 7, "status": "success", "detail": "mock 触达", "created_at": "..." } ] }
```

## 8. 错误响应统一结构

| HTTP | 场景 |
|------|------|
| 400 | 参数校验失败（`{code: "VALIDATION_ERROR"}`） |
| 401 | 未登录/凭证无效（`{code: "UNAUTHORIZED"}`） |
| 404 | 资源不存在（`{code: "NOT_FOUND"}`） |
| 500 | 内部错误（`{code: "INTERNAL_ERROR"}`） |

```json
{ "code": "LLM_ERROR", "message": "上游模型调用失败", "detail": "Timeout after 30s" }
```

## 9. 健康检查 `GET /health`

```json
// Response 200
{ "status": "ok", "app": "EduMentor", "version": "0.1.0", "db": "ok", "llm": "ok" }
```

> `llm` 字段通过一次低成本探测（调用当前 `LLM_PROVIDER` 的单 token 请求）判断；`db` 判断 MySQL 可连接；`vector`/`cache` 字段（生产模式）判断 Milvus/Redis 可达（可选，开发期可省略）。

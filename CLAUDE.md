# CLAUDE.md — AI 编码主指令

> 本文件是 **AI coding 代理**的首选入口。开始任何编码工作前，先通读本文件与 `docs/` 索引，再按 `docs/09-开发计划与验收.md` 的阶段推进。

## 项目一句话

**EduMentor**：基于多 Agent 协作架构的智能教育助手（校招项目）。大模型 + LangGraph 多 Agent 编排 + 教育工具服务层，实现**智能答疑 / 作业批改 / 错题分析 / 练习生成 / 学习推送**五大能力，支持文本/图片/语音多模态输入。**双模式部署**：笔记本（Windows）轻量开发，实验室 Ubuntu（RTX 4090）生产运行。

## 技术栈（不许自行更换）

| 项 | 开发期（笔记本） | 生产期（Ubuntu+4090） |
|----|------------------|----------------------|
| Python | 3.11 | 3.11 |
| Web | FastAPI + Uvicorn（8000，`/api/v1`） | 同左 |
| **LLM** | **DeepSeek 云 API** `deepseek-v4-flash` | **本地 Qwen**（Ollama，`qwen2.5:14b`） |
| **Embedding** | **千问 API** `text-embedding-v4`（1024 维） | **本地 `bge-m3`**（Ollama，1024 维） |
| Agent | LangChain + LangGraph（最新稳定版，Supervisor） | 同左 |
| OCR | PaddleOCR（CPU，PP-OCRv4） | 同左（4090 可 GPU） |
| 语音 | faster-whisper `small`（int8，CPU） | faster-whisper（GPU） |
| **业务库** | **MySQL 8.0**（本机） | **MySQL 8.0**（已部署实例，直接连接） |
| **向量库** | **FAISS**（`faiss-cpu`） | **Milvus 2.x**（已部署实例，直接连接） |
| **缓存** | **内存 TTL**（cachetools） | **Redis 7.x**（已部署实例，直接连接） |
| 定时 | APScheduler（AsyncIOScheduler） | 同左 |
| 前端 | FastAPI 托管静态单页 + SSE 流式 | 同左 |

**核心抽象（必须遵守）**：

- 向量库：实现 `VectorStore` 接口（`add/search/delete_by_doc/rebuild/count`），`app/storage/vector_store.py` 提供 `get_vector_store()` 工厂，按 `VECTOR_BACKEND`（`faiss|milvus`）返回实现。业务层**只依赖接口**。
- 缓存：实现 `Cache` 接口（`get/set/delete/clear`），`app/storage/cache.py` 提供 `get_cache()` 工厂，按 `CACHE_BACKEND`（`memory|redis`）返回实现。业务层**只依赖接口**。
- LLM/Embedding：`app/services/llm.py` 的 `get_chat_llm()` / `get_embedding_client()` 按 `LLM_PROVIDER`（`deepseek|local`）/ `EMBEDDING_PROVIDER`（`qwen|local`）返回对应客户端。业务层**只调用工厂**。
- 严禁在业务代码里 `import faiss` / `import redis` / `import pymilvus` 直接使用后端；一律经接口。

## 文档索引（构建蓝图，先读再写代码）

| 文档 | 内容 | 何时读 |
|------|------|--------|
| `docs/00-项目总览.md` | **技术规格基线**：环境变量、端口、目录结构、常量、双模式说明 | 每次开工前 |
| `docs/01-需求规格说明书.md` | 5 个 Agent 的 User Story 与验收标准 | 实现某 Agent 前 |
| `docs/02-系统架构设计.md` | 三层架构、术语对照表、双部署拓扑、依赖边界 | 实现前 |
| `docs/03-数据库设计.md` | MySQL 建表 DDL、VectorStore/Cache 双后端、仓储接口 | 写 storage 时 |
| `docs/04-API接口设计.md` | 全部接口（含 SSE 事件格式）与示例 | 写 api 时 |
| `docs/05-Agent编排设计.md` | LangGraph 状态/图/各 Agent 节点与 prompt | 写 agents 时 |
| `docs/06-工具服务层设计.md` | 工具签名/Schema/实现要点、LLM 提供商工厂 | 写 tools 时 |
| `docs/07-部署与运行指南.md` | 环境搭建、MySQL 建库、中间件连接（compose 可选）、Ollama、**迁移清单** | 跑起来/迁移时 |
| `docs/08-开发规范与编码约定.md` | **硬性编码规范**（分层/注解/日志/异常/接口抽象） | 全程遵守 |
| `docs/09-开发计划与验收.md` | **分阶段构建顺序 + 每阶段验收 + Ubuntu 迁移验收** | 规划工作时 |
| `docs/10-评测方案.md` | AI 数据生成管线 + 各 Agent 量化评测指标与脚本 | 阶段九 |

## 核心编码约定（硬性）

- 分层依赖单向：`api → agents → tools/services → storage`，禁止反向 import。
- 目录/文件：小写蛇形；类：PascalCase；常量：全大写。公开函数必须 docstring + 类型注解，**docstring 用中文**。
- 配置一律走 `app/core/config.py` 的 `settings`（读取 `.env`），禁止硬编码；**API Key 不得写入代码/提交仓库**。
- **存储/缓存/LLM 一律走接口与工厂**（见上），禁止业务代码直连后端。
- 关键链路（OCR/检索/LLM）必须记耗时日志；异常统一转 `{"code","message","detail"}`。
- 阻塞调用（OCR/ASR/FAISS/Milvus/Redis）不得阻塞事件循环（用 `def` 或线程池）。
- 单文件 < 400 行；表结构、接口路径、工具名以 `docs/03`、`docs/04`、`docs/06` 为准，**禁止另起炉灶改名**。

## 增量构建纪律（最重要）

1. 严格按照 `docs/09-开发计划与验收.md` 的 7+1 阶段推进（8 个阶段含 Ubuntu 迁移验收）。
2. **每完成一个阶段必须能独立启动并用 curl/页面验证**，通过验收清单再进入下一阶段。
3. 严禁一次性铺开全部代码。一次改动聚焦一个 Agent / 一个接口。
4. 每完成一个模块，过一遍 `docs/08` §11 自查清单。
5. 依赖版本冲突、API 变化时：以 `pip show <包>` 实际版本查官方文档修正，**不要臆测**。

## 常见坑（编码时特别注意）

- **LangChain/LangGraph 是新版**（与 `项目介绍.md` 中 0.1.17/0.0.45 不同）：统一用 `langchain_openai`、`langgraph.graph.StateGraph`、`START/END`。见 `docs/05` §1。
- **LLM 接入**：DeepSeek / Ollama / DashScope 三者都是 OpenAI 兼容端点，统一用 `ChatOpenAI` / `OpenAIEmbeddings` 配 `base_url` + `model` 即可。DeepSeek 需 `DEEPSEEK_API_KEY`；本地 Ollama 用占位 key（如 `ollama`）。
- **MySQL**：用 `mysql+pymysql://` 连接串 + `charset=utf8mb4`；建表用 InnoDB/utf8mb4；JSON 字段用 `JSON` 类型。开发机需先建库（见 `docs/07` §3）。
- **Milvus / Redis（生产）**：集合/键设计见 `docs/03`；本地没有可不开，开发默认 FAISS + 内存缓存。
- **PaddleOCR / faster-whisper**：必须**惰性加载单例**（首次调用才初始化），否则启动慢且占内存；首次调用会下载模型，属正常。
- **SSE 流式**：`StreamingResponse(media_type="text/event-stream")`，事件类型 `meta/token/done/error`，流结束必须正常关闭。

## 运行方式（开发期，详见 docs/07）

```bash
conda create -n edumentor python=3.11 -y && conda activate edumentor
pip install -r requirements.txt
mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS edumentor CHARACTER SET utf8mb4;"
cp .env.example .env        # 填入 DEEPSEEK_API_KEY 与 QWEN_API_KEY
python scripts/init_db.py
python scripts/build_kb.py
uvicorn app.main:app --reload --port 8000
# 页面 http://localhost:8000 · Swagger http://localhost:8000/docs
```

## 生产迁移提示（详见 docs/07 §9）

- 移植到 Ubuntu 后：**中间件（MySQL/Redis/Milvus）若已部署，直接改 `.env` 连接即可**；Ollama 部署本地 Qwen 与 `bge-m3`。
- 若目标机未预装中间件：可用根目录 `docker-compose.prod.yml`（**可选/备用**）一键起 MySQL/Redis/Milvus 全套。
- `.env` 切换：`LLM_PROVIDER=local`、`EMBEDDING_PROVIDER=local`、`VECTOR_BACKEND=milvus`、`CACHE_BACKEND=redis`、`APP_ENV=prod`。
- 代码零改动（接口抽象），只需重建知识库索引（`python scripts/build_kb.py`）。

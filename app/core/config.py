"""全局配置：读取 .env，双模式（dev/prod）切换的关键。

取值以 `docs/00-项目总览.md` §7 环境变量基线为准。
业务代码一律 `from app.core.config import settings`，禁止硬编码。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全部配置项，字段名与 .env 键一致（小写映射为大写）。"""

    # --- 应用 ---
    app_name: str = "EduMentor"
    app_version: str = "0.1.0"
    app_env: str = "dev"                 # dev / prod
    app_port: int = 8000
    upload_dir: str = "data/uploads"

    # --- LLM 提供商：deepseek(云) | local(Ollama) ---
    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "qwen2.5:14b"

    # --- Embedding 提供商：qwen(云) | local(Ollama) ---
    embedding_provider: str = "qwen"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_embedding_model: str = "text-embedding-v4"
    local_embedding_base_url: str = "http://localhost:11434/v1"
    local_embedding_model: str = "bge-m3"

    # --- 业务库：MySQL（pymysql 驱动） ---
    database_url: str = "mysql+pymysql://edumentor:edumentor123@127.0.0.1:3306/edumentor?charset=utf8mb4"

    # --- 向量库后端：faiss(开发) | milvus(生产) ---
    vector_backend: str = "faiss"
    vector_index_dir: str = "data/vector_index"
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530

    # --- 缓存后端：memory(开发) | redis(生产) ---
    cache_backend: str = "memory"
    cache_url: str = "redis://127.0.0.1:6379/0"

    # --- 鉴权 JWT（docs/04 §3；生产必须改 JWT_SECRET） ---
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_seconds: int = 86400  # token 有效期 1 天

    # --- 检索/切分常量（docs/00 §8） ---
    vector_dim: int = 1024               # text-embedding-v4 / bge-m3 维度
    retrieve_top_k: int = 5              # 检索 top_k
    chunk_size: int = 500                # 文档切分
    chunk_overlap: int = 50

    # --- 学习推送调度（docs/05 §5.5 / 阶段六） ---
    push_scan_interval: int = 30         # 调度器扫描到期任务间隔（秒）
    push_review_intervals: str = "1,2,4,7"  # 遗忘曲线复习间隔（天，逗号分隔）
    push_review_hour: int = 9            # 复习任务每日触发小时（UTC 09:00）

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()

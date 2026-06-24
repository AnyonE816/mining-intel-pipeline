"""
全局配置 — 使用 Pydantic Settings 管理所有环境变量和常量

所有可配置项集中在此, 通过环境变量或 .env 文件覆盖.
使用方法: from config import settings
"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── 路径 ──────────────────────────────────────────
    PROJECT_ROOT: Path = Path(__file__).parent
    DATA_DIR: Path = PROJECT_ROOT / "data"
    RAW_DIR: Path = DATA_DIR / "raw"
    PROCESSED_DIR: Path = DATA_DIR / "processed"
    CHROMA_DIR: Path = DATA_DIR / "chroma_db"

    # ── LLM 配置 ──────────────────────────────────────
    LLM_PROVIDER: str = "qwen"           # qwen | deepseek | openai
    LLM_MODEL: str = "qwen3-max"          # qwen3-max | qwen-max | qwen-plus | qwen-turbo
    LLM_TEMPERATURE: float = 0.1
    DASHSCOPE_API_KEY: str = ""          # 阿里云 DashScope (Qwen/Tongyi)
    # 以下为 DeepSeek/OpenAI 备选配置
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = ""

    # ── Embedding 配置 ────────────────────────────────
    EMBEDDING_PROVIDER: str = "dashscope"  # dashscope | local | openai
    EMBEDDING_MODEL: str = "text-embedding-v4"  # DashScope: text-embedding-v4(1024维,推荐)/v3/v2

    # ── 采集配置 ──────────────────────────────────────
    SCRAPE_DELAY: float = 1.5             # 请求间隔(秒)
    SCRAPE_MAX_CONCURRENT: int = 3        # 最大并发
    SCRAPE_DAYS_BACK: int = 30            # 采集多少天前的数据
    SCRAPE_MIN_PER_SOURCE: int = 200      # 每个源最少条数
    MOCK_MODE: bool = False               # 爬虫被墙时使用模拟数据

    # ── Chunk 配置 ────────────────────────────────────
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50

    # ── 去重配置 ──────────────────────────────────────
    DEDUP_TITLE_SIMILARITY_THRESHOLD: float = 0.85

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 全局单例
settings = Settings()

# 确保目录存在
for d in [settings.RAW_DIR, settings.PROCESSED_DIR, settings.CHROMA_DIR]:
    d.mkdir(parents=True, exist_ok=True)

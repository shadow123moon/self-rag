from pathlib import Path
from typing import List

from langchain_deepseek import ChatDeepSeek
from langchain_openai import OpenAI, OpenAIEmbeddings
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
BASE_DIR = Path(__file__).resolve().parent
class Settings(BaseSettings):
    chunk_size :int = 1000
    chunk_overlap :int= 100
    BM25_MIN_SCORE:int=5
    BM25_STRONG_SCORE: float = 20.0
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
    )

    separators: List[str] = [
        "\n\n",
        "\n",
        ". ",
        "? ",
        "! ",
        "。",
        "？",
        "！",
        "; ",
        "；",
        ", ",
        "，",
        " ",
        "",
    ]

    max_split_char_number :int = 1000
    # ===== 数据库 URL =====
    DATABASE_URL: str = Field(..., description="数据库连接字符串，如 mysql+pymysql://user:pass@host:3306/dbname")

    # ===== OpenAI / LLM =====
    OPENAI_API_KEY: str = Field(..., description="OpenAI API密钥")
    OPENAI_BASE_URL: str = "https://api.deepseek.com/v1"   # 默认官方地址
    OPENAI_MODEL: str = "deepseek-v4-flash"                    # 对话模型
    EMBEDDING_MODEL: str = "BAAI/bge-m3"      # 向量化模型

    EMBEDDING_URL: str = "https://api.siliconflow.cn/v1"
    EMBEDDING_KEY: str = Field(..., description="嵌入模型密钥")
    # ===== 文件上传 =====
    UPLOAD_DIR: str = "./storage/uploads"                # 上传文件保存目录
    #======重排序模型配置
    RERANK_URL:str="https://api.siliconflow.cn/v1/rerank"
    RERANK_KEY: str = Field(..., description="RERANK_KEY")
    RERANK_MODEL:str=Field(..., description="重排序模型")
    # ===== 向量库 (Chroma) =====
    CHROMA_PERSIST_DIR: str = "./chroma_data"            # Chroma 持久化路径
    CHROMA_COLLECTION_NAME: str = "documents"
    RAG_MAX_DISTANCE: float = 0.95                       # Chroma 距离分数，越小越相关，超过这个值就不作为引用

    # ===== 其他 =====
    MAX_UPLOAD_SIZE_MB: int = 20                         # 上传大小限制
    APP_NAME: str = "My RAG App"
    DEBUG: bool = False
    RERANK_ENABLED: bool = True

# 创建全局配置实例，之后直接从 config import settings 使用
settings = Settings()


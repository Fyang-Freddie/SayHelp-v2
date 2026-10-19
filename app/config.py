from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    test_database_url: str | None = None

    chat_base_url: str = ""
    chat_model: str = ""
    chat_api_key: str = ""
    model_provider_context_window: int = 1000000

    jev_model: str = ""
    jev_base_url: str = ""
    jev_api_key: str = ""

    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str = ""
    milvus_minio_user: str = ""
    milvus_minio_password: str = ""

    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    embedding_use_fp16: bool = False

    # 检索编排（Task 6）：rerank 分数 ≥ rerank_min 视为有效证据；
    # evidence_confidence ≥ evidence_confidence_threshold 才通过闸（待标注集校准）。
    rerank_min: float = 0.3
    evidence_confidence_threshold: float = 0.5

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    @model_validator(mode="after")
    def _reject_insecure_jwt_secret(self):
        if self.jwt_secret == "dev-secret-change-me":
            raise ValueError(
                "JWT_SECRET 未配置或仍为开发默认值；请生成随机密钥写入 .env（参考 .env.example）"
            )
        return self


settings = Settings()

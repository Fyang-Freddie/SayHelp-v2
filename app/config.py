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

    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://dgo:dgo@localhost:5432/dgo"

    llm_base_url: str = "http://localhost:8001/v1"
    llm_model: str = "gemma"
    llm_api_key: str = ""

    camunda_gateway_address: str = "localhost:26500"

    datahub_api_url: str = "http://localhost:8080"
    datahub_api_token: str = ""

    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

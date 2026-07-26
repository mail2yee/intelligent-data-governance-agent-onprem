from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://dgo:dgo@localhost:5432/dgo"

    llm_base_url: str = "http://localhost:8001/v1"
    llm_model: str = "gemma"
    llm_api_key: str = ""

    camunda_gateway_address: str = "localhost:26500"
    # No BPMN process is deployed yet (confirmed with the user) - this is a
    # placeholder. Deploy a real process and update it here, no code change needed.
    camunda_process_id: str = "data-gov-approval"
    # Leave unset to use an unauthenticated (insecure) gRPC channel - confirmed
    # with the user this is likely fine for their trusted internal network.
    # Set all three to use an OAuth2 client-credentials-authenticated channel
    # instead (Camunda Identity/Keycloak) - see camunda_client.py docstring,
    # this path is unconfirmed/untested against a live server.
    camunda_oauth_client_id: str = ""
    camunda_oauth_client_secret: str = ""
    camunda_oauth_token_url: str = ""
    camunda_oauth_audience: str = "zeebe-api"

    datahub_api_url: str = "http://localhost:8080"
    datahub_api_token: str = ""

    # WrenAI semantic layer project directory (see ../../wren/project and
    # integrations/wrenai_client.py). Resolved relative to the process's
    # working directory, which differs between local dev (run from
    # backend/, so the repo-root wren/ is one level up) and Docker (WORKDIR
    # /app, where the Dockerfile copies it to /app/wren_project) - the
    # docker-compose.yml environment overrides this for the container case.
    wren_project_path: str = "../wren/project"

    cors_origins: str = "http://localhost:5173"

    # Used to pad a ticket's approver list up to a minimum of 3 when the
    # requested products' own owners don't already provide that many
    # (see main.py create_ticket). This was a hardcoded PoC placeholder
    # rule ported as-is - worth reconsidering the whole "pad to 3" policy
    # once real approval requirements are known, not just where the emails
    # come from.
    default_fallback_approvers: str = "compliance_director@example.com,info_sec_auditor@example.com"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def default_fallback_approvers_list(self) -> list[str]:
        return [o.strip() for o in self.default_fallback_approvers.split(",") if o.strip()]


settings = Settings()

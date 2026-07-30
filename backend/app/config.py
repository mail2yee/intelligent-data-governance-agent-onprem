from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://dgo:dgo@localhost:5432/dgo"

    llm_base_url: str = "http://localhost:8001/v1"
    llm_model: str = "gemma"
    llm_api_key: str = ""
    # Optional second model, used only for chat.py's SQL-generation call
    # (resolve_via_semantic_layer) - a tool-calling/structured-output-tuned
    # model tends to be far more reliable at that than a general chat
    # model (confirmed testing locally: qwen2.5 struggled with strict SQL
    # syntax for this step). Empty means "use llm_model for everything",
    # same as before this setting existed.
    llm_sql_model: str = ""

    # On-prem Camunda 7 (self-managed) REST API - see
    # integrations/camunda_client.py. Confirmed 2026-07-29 the company's
    # actual instance is Camunda **7.22** (REST, no gRPC/Zeebe/pyzeebe -
    # a full rewrite from an earlier, incorrect Camunda 8 assumption).
    # Default matches a local `camunda/camunda-bpm-platform:7.22.0`
    # container run directly (not via this repo's docker-compose, which
    # remaps the port and overrides this to the container-network address
    # - see docker-compose.yml).
    camunda_base_url: str = "http://localhost:8080/engine-rest"
    # The BPMN process *definition key* (Camunda 7's term - the
    # `id="..."` attribute on `<bpmn:process>`), not a Zeebe
    # bpmn_process_id. `camunda/data-gov-approval.bpmn` in this repo
    # declares exactly this key, and this app deploys that file itself
    # (see backend/entrypoint.sh) - the company's real instance would
    # need its own process deployed with a matching key, or this value
    # changed to match theirs. No code change needed either way.
    camunda_process_definition_key: str = "data-gov-approval"
    # Leave both blank for an unauthenticated connection (confirmed OK
    # against the local test instance - Camunda 7's REST API has no
    # authentication by default). The company's real instance likely
    # requires HTTP Basic Auth (the standard Camunda 7 approach, via a
    # servlet filter) - unconfirmed against it specifically.
    camunda_basic_auth_username: str = ""
    camunda_basic_auth_password: str = ""

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

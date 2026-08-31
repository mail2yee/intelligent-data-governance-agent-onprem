from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+asyncmy://dgo:dgo@localhost:3307/dgo"

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

    # Shared-secret gate on every /api/* route (see main.py's
    # require_api_key) - checked against the client's X-API-Key header.
    # Empty (the default) means auth is disabled, matching this repo's
    # existing convention for optional integrations - convenient for local
    # dev, but **a real value must be set before any real deployment**,
    # same caveat as docker-compose.yml's POSTGRES_PASSWORD default.
    # Added 2026-07-30 in response to a security review that flagged this
    # API having zero authentication at all. Deliberately scoped: this is
    # a coarse, single shared secret (blocks anonymous/external traffic),
    # not per-user identity - it does NOT fix submit_approval()'s separate
    # gap (nothing verifies the caller actually *is* the owner_email they
    # claim to be in the request body). That needs real per-user auth
    # (company SSO/OIDC) to close properly; this is an interim measure.
    api_key: str = ""

    # WrenAI semantic layer project directory (see ../../wren/project and
    # integrations/wrenai_client.py). Resolved relative to the process's
    # working directory, which differs between local dev (run from
    # backend/, so the repo-root wren/ is one level up) and Docker (WORKDIR
    # /app, where the Dockerfile copies it to /app/wren_project) - the
    # docker-compose.yml environment overrides this for the container case.
    wren_project_path: str = "../wren/project"

    # Second WrenAI project (see integrations/business_data.py's
    # PRODUCT_DATA_SOURCES registry and integrations/wrenai_client.py's
    # resolve_business_query) - the fake business database used to prove
    # real NL-to-SQL against actual business data, gated by ticket
    # approval, rather than just catalog metadata matching. Same
    # local-dev-vs-Docker path resolution caveat as wren_project_path
    # above.
    wren_business_project_path: str = "../wren/business_capacity_plan"

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

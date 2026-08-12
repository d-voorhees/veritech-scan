from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration.

    All values are overridable via environment variables so product identity
    and behavior are configured, not hardcoded, per the product requirements.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_domain: str = "localhost"
    app_url: str = "http://localhost:3000"
    marketing_site_url: str = "https://veritechdiligence.com"
    product_name: str = "Veritech Scan"
    parent_brand: str = "Veritech Diligence"
    report_name: str = "Technical Acquisition Brief"

    database_url: str = "postgresql+psycopg://veritech_scan:change-me@postgres:5432/veritech_scan"
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: str = "dev-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 1440

    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "change-me"

    scan_max_total_minutes: int = 10
    scan_default_request_delay_seconds: float = 1.5
    scan_max_pages: int = 50
    scan_worker_concurrency: int = 1
    scan_page_timeout_seconds: int = 15
    scan_create_rate_limit_per_hour: int = 10

    google_pagespeed_api_key: str = ""
    sentry_dsn: str = ""

    artifact_storage_backend: str = "local"
    artifact_storage_local_path: str = "/data/artifacts"

    log_format: str = "console"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

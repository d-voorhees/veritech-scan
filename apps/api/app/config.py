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

    database_url: str = ""

    # Fly.io deployment settings. fly_database_url mirrors the DATABASE_URL
    # style secret Fly Postgres/Managed Postgres attaches under a
    # Fly-specific name; fly_api_token/fly_app_name/fly_primary_region drive
    # the Fly Machines API client (app/services/fly_machines.py) that
    # creates the on-demand scan-runner Machine. FLY_API_TOKEN is
    # server-side only and must never be sent to the browser.
    fly_app_name: str = ""
    fly_api_token: str = ""
    fly_primary_region: str = "iad"
    fly_database_url: str = ""

    jwt_secret: str = "dev-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 1440

    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "change-me"

    scan_max_total_minutes: int = 10
    scan_default_request_delay_seconds: float = 1.5
    scan_max_pages: int = 50
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

    @property
    def resolved_database_url(self) -> str:
        """DATABASE_URL wins if set (local dev, tests); otherwise fall back
        to FLY_DATABASE_URL (as attached by Fly Postgres in production),
        then a native-Postgres-friendly local default.
        """
        return (
            self.database_url
            or self.fly_database_url
            or "postgresql+psycopg://veritech_scan:change-me@127.0.0.1:5432/veritech_scan"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

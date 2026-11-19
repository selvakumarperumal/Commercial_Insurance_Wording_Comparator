"""API settings, read once from environment variables (the field name in upper case, e.g. REDIS_URL)."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Every setting of the API, with defaults for local development."""

    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql+psycopg://ciwc_user:ciwc_password@localhost:5432/ciwc_db"

    jwt_secret: str = ""
    jwt_expire_minutes: int = 60

    upload_dir: Path = Path("uploads")
    max_pdf_mb: int = 50

    job_stream: str = "ciwc:jobs"
    job_ttl_s: int = 7 * 24 * 3600
    max_active_jobs_per_user: int = 2

    @property
    def max_pdf_bytes(self) -> int:
        """Upload size limit per PDF in bytes."""
        return self.max_pdf_mb * 1024 * 1024


settings = Settings()

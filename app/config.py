from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Service
    service_name: str = "cp-compiler"
    service_version: str = "2.2.0"
    service_host: str = "0.0.0.0"
    service_port: int = 8000

    # Security
    internal_token: str = Field(
        description="Bearer token for service-to-service authentication"
    )

    # Temp directories
    compiler_temp_dir: str = Field(
        default="/compiler-temp",
        description="Container-side temp directory for code compilation and execution",
    )

    # Logging
    log_level: str = "INFO"

    # Default resource limits (ICPC/IOI standards)
    default_time_limit_ms: int = 1000       # 1 second
    default_memory_limit_mb: int = 256      # 256 MB
    max_time_limit_ms: int = 30000          # 30 seconds max
    max_memory_limit_mb: int = 1024         # 1 GB max
    output_limit_mb: int = 16              # 16 MB (ICPC standard)

    # CORS
    cors_origins: str = ""

    # Trusted Host header (comma-separated)
    trusted_hosts: str = "localhost,127.0.0.1"

    # Trusted proxy IPs for X-Forwarded-For
    trusted_proxies: list[str] = []

    # Concurrency control — prevents CPU thrashing during contest spikes.
    # 0 = auto (derived from CPU count).
    global_concurrency_slots: int = Field(
        default=0,
        description="Global nsjail parallel execution limit. 0 = auto (CPU x 6).",
    )
    per_language_concurrency_slots: int = Field(
        default=0,
        description="Per-language nsjail parallel execution limit. 0 = auto (CPU x 4).",
    )

    # Backpressure — max concurrent /judge requests.
    # When exceeded, 503 is returned so the caller can retry on another replica.
    max_inflight_judge_requests: int = Field(
        default=0,
        description="Max concurrent /judge requests. 0 = auto (global_slots + 4).",
    )

    # Compilation cache — avoids redundant recompilation of identical source code.
    compile_cache_max_entries: int = Field(
        default=256,
        description="Max compiled artifacts kept in LRU cache. 0 = disabled.",
    )
    compile_cache_ttl_seconds: int = Field(
        default=600,
        description="Cache entry TTL in seconds.",
    )


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Service
    service_name: str = "cp-compiler"
    service_version: str = "2.4.0"
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
    stderr_limit_kb: int = 256             # Per-stream stderr cap (DoS protection)
    compile_output_limit_kb: int = 64      # Max compile output returned in response

    # Max HTTP request body size — prevents OOM via huge JudgeRequest bodies.
    max_request_body_bytes: int = 100 * 1024 * 1024  # 100 MB

    # Custom checker code is attacker-controllable if untrusted callers can
    # submit checker source. Disable in deployments where the calling layer
    # does not gate checker submission to trusted contest setters.
    allow_custom_checker: bool = True

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

    # File-based test delivery — test data read from disk instead of HTTP body.
    test_data_dir: str = Field(
        default="/test-data",
        description="Root directory for file-based test case data.",
    )
    max_test_file_size_mb: int = Field(
        default=256,
        description="Max size of a single test file (input or expected output) in MB.",
    )

    # Disk usage monitoring — returns 503 when temp dir is nearly full.
    temp_disk_usage_threshold: float = Field(
        default=0.80,
        description="Fraction of /compiler-temp used before returning 503.",
    )

    # Zombie process reaper interval (seconds).
    zombie_reaper_interval: int = Field(
        default=30,
        description="Interval in seconds for reaping zombie nsjail processes.",
    )

    # Interactive problem support.
    max_interactive_turns: int = Field(
        default=10000,
        description="Max stdin/stdout turns for interactive problems.",
    )
    interactive_idle_timeout_ms: int = Field(
        default=5000,
        description="Idle timeout per turn for interactive problems (ms).",
    )


settings = Settings()

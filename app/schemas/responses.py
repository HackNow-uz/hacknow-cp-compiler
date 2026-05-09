"""Response schemas for the CP Compiler API."""

from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class ExecutionStatus(str, Enum):
    """Execution result status codes (ICPC / IOI / Codeforces / Polygon)."""

    OK = "OK"       # Accepted
    WA = "WA"       # Wrong Answer
    PE = "PE"       # Presentation Error (tokens match, format differs)
    TLE = "TLE"     # Time Limit Exceeded
    MLE = "MLE"     # Memory Limit Exceeded
    RTE = "RTE"     # Runtime Error
    CE = "CE"       # Compilation Error
    OLE = "OLE"     # Output Limit Exceeded
    SE = "SE"       # Security Violation
    IE = "IE"       # Internal Error (judge system failure)
    SK = "SK"       # Skipped (subtask dependency failed)


class LanguageInfo(BaseModel):
    """Language information returned by GET /languages."""

    id: str
    name: str
    version: str
    time_limit_ms: int = Field(description="Default time limit for this language")
    memory_limit_mb: int = Field(description="Default memory limit for this language")
    time_multiplier: float = Field(default=1.0)
    memory_multiplier: float = Field(default=1.0)


class RunResponse(BaseModel):
    """Response for single code execution (POST /run)."""

    status: ExecutionStatus
    stdout: str = ""
    stderr: str = ""
    compile_output: str = ""
    exit_code: int = 0
    time_ms: int = Field(default=0, description="CPU execution time in milliseconds")
    memory_kb: int = Field(default=0, description="Peak memory usage in kilobytes")
    compile_time_ms: int = Field(default=0, description="Compilation time in milliseconds")


class TestResult(BaseModel):
    """Single test case result within a judge response."""

    test_id: str
    status: ExecutionStatus
    time_ms: int = 0
    memory_kb: int = 0
    score: int = 0
    stdout: str = ""
    stderr: str = ""
    subtask: Optional[str] = Field(
        default=None,
        description="Subtask this test belongs to (IOI-style)",
    )
    checker_message: str = Field(
        default="",
        description="Checker-emitted feedback (PE/WA reason)",
    )


class SubtaskResult(BaseModel):
    """IOI-style subtask aggregation result."""

    id: str
    name: Optional[str] = None
    score: int = 0
    max_score: int = 0
    status: ExecutionStatus
    test_count: int = 0
    passed_count: int = 0
    skipped: bool = Field(
        default=False,
        description="True if a dependency subtask scored 0 and this group was skipped",
    )


class JudgeResponse(BaseModel):
    """Response for multi-test judging (POST /judge)."""

    submission_id: str
    problem_id: str
    language_id: str
    status: ExecutionStatus
    score: int = 0
    max_score: int = 0
    compile_output: str = ""
    compile_time_ms: int = 0
    tests: List[TestResult] = []
    subtasks: List[SubtaskResult] = Field(
        default_factory=list,
        description="Per-subtask aggregated results (IOI-style). Empty for flat judging.",
    )
    error: Optional[str] = None


class CompileCacheStats(BaseModel):
    """Compilation cache statistics."""

    size: int = 0
    max: int = 0
    hits: int = 0
    misses: int = 0
    hit_rate: float = 0.0


class ConcurrencyStats(BaseModel):
    """Current concurrency configuration."""

    global_slots: int = 0
    per_language_slots: int = 0


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str
    uptime_seconds: int
    compile_cache: Optional[CompileCacheStats] = None
    concurrency: Optional[ConcurrencyStats] = None
    temp_dir_mb: Optional[int] = None

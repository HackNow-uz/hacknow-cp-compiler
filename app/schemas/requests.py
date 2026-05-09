"""Request schemas for the CP Compiler API."""

from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Literal


class RunRequest(BaseModel):
    """Single code execution request for testing/debugging."""

    language_id: str = Field(
        ...,
        max_length=32,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Language identifier. See GET /api/v1/languages.",
    )
    source_code: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="Source code to execute",
    )
    input: str = Field(
        default="",
        max_length=10_000_000,
        description="Stdin input for the program",
    )
    time_limit_ms: int = Field(
        default=1000, ge=100, le=30000,
        description="Time limit in milliseconds",
    )
    memory_limit_mb: int = Field(
        default=256, ge=16, le=1024,
        description="Memory limit in megabytes",
    )


class TestCase(BaseModel):
    """Single test case for judging."""

    id: str = Field(..., max_length=64, pattern=r"^[A-Za-z0-9_\-.]+$",
                    description="Test case identifier")
    input: str = Field(..., max_length=10_000_000, description="Stdin input data")
    expected_output: str = Field(..., max_length=10_000_000,
                                  description="Expected stdout output")
    score: int = Field(default=10, ge=0, le=10000, description="Points for this test")
    time_limit_ms: Optional[int] = Field(
        default=None, ge=100, le=30000,
        description="Per-test time limit override",
    )
    memory_limit_mb: Optional[int] = Field(
        default=None, ge=16, le=1024,
        description="Per-test memory limit override",
    )
    subtask: Optional[str] = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z0-9_\-.]+$",
        description="Subtask identifier for IOI-style grouping",
    )


class Subtask(BaseModel):
    """
    IOI-style subtask: a group of tests with an aggregation rule.

    score_mode:
      - "min"  : lowest test score in the group (IOI default — all must pass)
      - "sum"  : sum of individual test scores (Codeforces partial)
      - "all_or_nothing" : full points if all pass, 0 otherwise
    """

    id: str = Field(..., description="Subtask identifier (matches TestCase.subtask)")
    name: Optional[str] = Field(default=None, description="Human-readable name")
    max_score: int = Field(..., ge=0, description="Maximum points for this subtask")
    score_mode: Literal["min", "sum", "all_or_nothing"] = Field(
        default="min",
        description="Aggregation rule across the subtask's tests",
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="Subtask IDs that must score >0 before this subtask runs. "
                    "Tests in this subtask are SKIPPED if any dependency scored 0.",
    )


class CheckerConfig(BaseModel):
    """Checker configuration for custom output validation (Polygon/testlib style)."""

    type: str = Field(
        default="standard",
        description="Checker type: standard, tokens, float, custom",
    )
    code: Optional[str] = Field(
        default=None,
        max_length=100_000,
        description="C++ source for custom checker (type=custom only)",
    )
    language_id: str = Field(
        default="cpp",
        description="Language of checker code",
    )
    epsilon: float = Field(
        default=1e-6,
        description="Tolerance for float checker type",
    )


class JudgeRequest(BaseModel):
    """
    Multi-test judging request.

    Supports ICPC (fail-fast), Codeforces (partial), and IOI (subtask) scoring.
    """

    submission_id: str = Field(..., max_length=128, pattern=r"^[A-Za-z0-9_\-.]+$",
                                description="Unique submission identifier")
    problem_id: str = Field(..., max_length=128, pattern=r"^[A-Za-z0-9_\-.]+$",
                             description="Problem identifier")
    language_id: str = Field(..., max_length=32, pattern=r"^[a-z][a-z0-9_]*$",
                              description="Language identifier")
    source_code: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="Source code to judge",
    )
    tests: List[TestCase] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Test cases to run against",
    )
    time_limit_ms: int = Field(
        default=1000, ge=100, le=30000,
        description="Default time limit per test (ms)",
    )
    memory_limit_mb: int = Field(
        default=256, ge=16, le=1024,
        description="Default memory limit per test (MB)",
    )
    checker: Optional[CheckerConfig] = Field(
        default=None,
        description="Output checker config. None = standard exact match.",
    )
    stop_on_first_failure: bool = Field(
        default=True,
        description=(
            "ICPC fail-fast (default). Set False for IOI/partial scoring "
            "so all tests run. Automatically False when subtasks are provided."
        ),
    )
    subtasks: Optional[List[Subtask]] = Field(
        default=None,
        description="IOI-style subtask groups with per-subtask aggregation and dependencies.",
    )

    @model_validator(mode="after")
    def _validate_subtasks(self):
        if self.subtasks:
            valid_ids = {st.id for st in self.subtasks}
            for st in self.subtasks:
                for dep in st.depends_on:
                    if dep not in valid_ids:
                        raise ValueError(
                            f"Subtask '{st.id}' depends on unknown subtask '{dep}'"
                        )
            for t in self.tests:
                if t.subtask is None:
                    raise ValueError(
                        f"Test '{t.id}' missing subtask_id, but subtasks were provided"
                    )
                if t.subtask not in valid_ids:
                    raise ValueError(
                        f"Test '{t.id}' references unknown subtask='{t.subtask}'"
                    )
            self.stop_on_first_failure = False
        return self

    @model_validator(mode="after")
    def _validate_total_size(self):
        # Cap aggregate test data to prevent memory exhaustion via 100x10MB requests.
        total = sum(len(t.input) + len(t.expected_output) for t in self.tests)
        if total > 200 * 1024 * 1024:  # 200 MB aggregate cap
            raise ValueError(
                f"Total test data size {total} exceeds 200MB limit"
            )
        return self

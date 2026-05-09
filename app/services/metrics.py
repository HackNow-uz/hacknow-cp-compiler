"""
Prometheus metrics for judge and executor activity.

prometheus_client is optional — if not installed, all metric operations
become no-ops, so the service works without it in dev/test environments.

Metrics:
  cp_judge_verdicts_total{language, verdict}  - verdict counter per language
  cp_judge_compile_time_ms{language}          - compilation time histogram
  cp_judge_test_time_ms{language}             - per-test execution histogram
  cp_judge_duration_seconds{language}         - end-to-end /judge duration
  cp_judge_score_ratio{language}              - score/max_score (0..1)
  cp_judge_inflight{language}                 - currently in-flight requests

Endpoint:
  GET /api/v1/metrics -> Prometheus text format
"""

from typing import Iterable

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROM_OK = True
except ImportError:  # pragma: no cover
    _PROM_OK = False

    class _Stub:
        def labels(self, *_, **__):
            return self
        def inc(self, *_, **__):
            return None
        def dec(self, *_, **__):
            return None
        def observe(self, *_, **__):
            return None
        def set(self, *_, **__):
            return None

    Counter = Gauge = Histogram = lambda *_, **__: _Stub()  # type: ignore
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

    def generate_latest(*_, **__) -> bytes:
        return b"# prometheus_client not installed\n"


# Histogram buckets — 1ms to 30s, tuned for CP workloads.
_TIME_BUCKETS_MS: Iterable[float] = (
    1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 10000, 30000,
)
_DURATION_BUCKETS_S: Iterable[float] = (
    0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60,
)
_SCORE_BUCKETS = (0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)

judge_verdicts_total = Counter(
    "cp_judge_verdicts_total",
    "Total /judge verdicts emitted",
    ["language", "verdict"],
)
judge_compile_time_ms = Histogram(
    "cp_judge_compile_time_ms",
    "Compile time in milliseconds",
    ["language"],
    buckets=_TIME_BUCKETS_MS,
)
judge_test_time_ms = Histogram(
    "cp_judge_test_time_ms",
    "Per-test execution time in milliseconds",
    ["language"],
    buckets=_TIME_BUCKETS_MS,
)
judge_duration_seconds = Histogram(
    "cp_judge_duration_seconds",
    "End-to-end /judge request duration",
    ["language"],
    buckets=_DURATION_BUCKETS_S,
)
judge_score_ratio = Histogram(
    "cp_judge_score_ratio",
    "Submission score / max_score (0..1)",
    ["language"],
    buckets=_SCORE_BUCKETS,
)
judge_inflight = Gauge(
    "cp_judge_inflight",
    "Currently in-flight /judge requests",
    ["language"],
)


def export() -> bytes:
    """Return Prometheus text exposition format buffer."""
    return generate_latest()

"""
Multi-test judging with compile-once optimization.

Scoring modes: ICPC (fail-fast), Codeforces (partial), IOI (subtask with
min/sum/all_or_nothing aggregation and depends_on ordering).
Every test runs in an isolated nsjail sandbox with independent CPU time
and memory measurement.
"""
import asyncio
import logging
import shutil
import time
from collections import deque

from app.config import settings
from app.languages import get_language
from app.sandbox import nsjail_runner, ExecutionResult
from app.schemas.requests import (
    CheckerConfig, JudgeRequest, Subtask, TestCase,
)
from app.schemas.responses import (
    ExecutionStatus, JudgeResponse, SubtaskResult, TestResult,
)
from app.services.comparator import (
    compare_float, compare_standard, compare_tokens,
)
from app.services.metrics import (
    judge_compile_time_ms, judge_duration_seconds, judge_test_time_ms,
    judge_verdicts_total, judge_score_ratio, judge_inflight,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
#  Public entry-point
# ─────────────────────────────────────────────────────────────────────────
async def judge_submission(data: JudgeRequest) -> JudgeResponse:
    """
    Judge a submission against multiple test cases.

    Flow:
      1. Compile the source ONCE (short-circuit on CE).
      2. If a custom checker is specified, compile it once as well.
      3. Run each test in a fresh nsjail sandbox.
      4. If subtasks are present, perform per-subtask aggregation
         while respecting ``depends_on`` ordering.
    """
    judge_start = time.time()
    judge_inflight.labels(language=data.language_id).inc()

    language = get_language(data.language_id)
    if not language:
        judge_inflight.labels(language=data.language_id).dec()
        return JudgeResponse(
            submission_id=data.submission_id,
            problem_id=data.problem_id,
            language_id=data.language_id,
            status=ExecutionStatus.IE,
            error=f"Unsupported language: {data.language_id}",
        )

    log_extra = {
        "submission_id": data.submission_id,
        "problem_id": data.problem_id,
        "language_id": data.language_id,
        "tests": len(data.tests),
        "subtasks": len(data.subtasks) if data.subtasks else 0,
        "checker": data.checker.type if data.checker else "standard",
    }
    logger.info("judge.start", extra=log_extra)

    compiled_dir = None
    checker_dir = None
    try:
        # ── 1. Compile submission once ──────────────────────────────────
        compiled_dir, compile_output, compile_time_ms = await nsjail_runner.compile_once(
            language=language,
            source_code=data.source_code,
        )
        judge_compile_time_ms.labels(language=data.language_id).observe(compile_time_ms)

        if compiled_dir is None:
            logger.info("judge.compile_error", extra={**log_extra, "compile_time_ms": compile_time_ms})
            judge_verdicts_total.labels(
                language=data.language_id, verdict=ExecutionStatus.CE.value
            ).inc()
            return JudgeResponse(
                submission_id=data.submission_id,
                problem_id=data.problem_id,
                language_id=data.language_id,
                status=ExecutionStatus.CE,
                score=0,
                max_score=_max_score(data),
                compile_output=compile_output,
                compile_time_ms=compile_time_ms,
                error=compile_output,
            )

        # ── 2. Compile custom checker if needed ─────────────────────────
        if data.checker and data.checker.type == "custom" and data.checker.code:
            checker_lang = get_language(data.checker.language_id or "cpp")
            if checker_lang:
                checker_dir, checker_compile_out, _ = await nsjail_runner.compile_once(
                    language=checker_lang,
                    source_code=data.checker.code,
                )
                if checker_dir is None:
                    logger.error("judge.checker_compile_error", extra={
                        **log_extra, "checker_output": checker_compile_out[:500],
                    })
                    return JudgeResponse(
                        submission_id=data.submission_id,
                        problem_id=data.problem_id,
                        language_id=data.language_id,
                        status=ExecutionStatus.IE,
                        compile_output=compile_output,
                        compile_time_ms=compile_time_ms,
                        error=f"Checker compilation error: {checker_compile_out[:500]}",
                    )

        # ── 3. Run tests ────────────────────────────────────────────────
        test_results = await _run_all_tests(
            data, language, compiled_dir, checker_dir,
        )

        # ── 4. Compute final verdict + score ─────────────────────────────
        if data.subtasks:
            overall_status, total_score, max_score, subtask_results = _aggregate_subtasks(
                data.subtasks, test_results,
            )
            response_subtasks = subtask_results
        else:
            overall_status, total_score, max_score = _aggregate_flat(
                data.tests, test_results,
            )
            response_subtasks = []

        # Metrics
        judge_verdicts_total.labels(
            language=data.language_id, verdict=overall_status.value
        ).inc()
        if max_score > 0:
            judge_score_ratio.labels(language=data.language_id).observe(
                total_score / max_score
            )
        judge_duration_seconds.labels(language=data.language_id).observe(
            time.time() - judge_start
        )

        logger.info("judge.complete", extra={
            **log_extra,
            "verdict": overall_status.value,
            "score": total_score,
            "max_score": max_score,
            "duration_ms": int((time.time() - judge_start) * 1000),
        })

        return JudgeResponse(
            submission_id=data.submission_id,
            problem_id=data.problem_id,
            language_id=data.language_id,
            status=overall_status,
            score=total_score,
            max_score=max_score,
            compile_output=compile_output,
            compile_time_ms=compile_time_ms,
            tests=test_results,
            subtasks=response_subtasks,
            error=test_results[-1].stderr if (
                overall_status == ExecutionStatus.RTE and test_results
            ) else None,
        )

    except Exception as e:
        logger.exception("judge.exception: %s", e, extra=log_extra)
        return JudgeResponse(
            submission_id=data.submission_id,
            problem_id=data.problem_id,
            language_id=data.language_id,
            status=ExecutionStatus.IE,
            error=str(e),
        )

    finally:
        judge_inflight.labels(language=data.language_id).dec()
        if compiled_dir:
            shutil.rmtree(compiled_dir, ignore_errors=True)
            nsjail_runner.release_compiled(data.language_id, data.source_code)
        if checker_dir:
            shutil.rmtree(checker_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────
#  Private helpers
# ─────────────────────────────────────────────────────────────────────────
def _max_score(data: JudgeRequest) -> int:
    """Return the total maximum score (from subtasks if present, otherwise from tests)."""
    if data.subtasks:
        return sum(st.max_score for st in data.subtasks)
    return sum(t.score for t in data.tests)


async def _run_single_test(
    test: TestCase,
    data: JudgeRequest,
    language,
    compiled_dir: str,
    checker_dir: str | None,
) -> TestResult:
    """Execute a single test case inside an nsjail sandbox and return a TestResult."""
    time_limit = test.time_limit_ms or data.time_limit_ms
    memory_limit = test.memory_limit_mb or data.memory_limit_mb

    result = await nsjail_runner.run_test(
        language=language,
        compiled_dir=compiled_dir,
        input_data=test.input,
        time_limit_ms=time_limit,
        memory_limit_mb=memory_limit,
    )

    status, checker_message = await _determine_test_status(
        result, time_limit, memory_limit,
        test.input, test.expected_output,
        data.checker, checker_dir,
    )

    score = test.score if status == ExecutionStatus.OK else 0

    judge_test_time_ms.labels(language=language.id).observe(result.time_ms)

    return TestResult(
        test_id=test.id,
        status=status,
        time_ms=result.time_ms,
        memory_kb=result.memory_kb,
        score=score,
        stdout=_truncate(result.stdout, 500),
        stderr=_truncate(result.stderr, 500),
        subtask=test.subtask,
        checker_message=checker_message,
    )


async def _run_all_tests(
    data: JudgeRequest,
    language,
    compiled_dir: str,
    checker_dir: str | None,
) -> list[TestResult]:
    """
    Run every test in its own nsjail sandbox.

    Fail-fast (ICPC): sequential, stops on first non-OK.
    Concurrent (IOI/partial): parallel via asyncio.gather with semaphores.
    """
    fail_fast = data.stop_on_first_failure and not data.subtasks

    if fail_fast:
        test_results: list[TestResult] = []
        for test in data.tests:
            tr = await _run_single_test(test, data, language, compiled_dir, checker_dir)
            test_results.append(tr)
            if tr.status != ExecutionStatus.OK:
                break
        return test_results

    coros = [
        _run_single_test(test, data, language, compiled_dir, checker_dir)
        for test in data.tests
    ]
    test_results = await asyncio.gather(*coros)
    return list(test_results)


def _aggregate_flat(
    tests: list[TestCase],
    results: list[TestResult],
) -> tuple[ExecutionStatus, int, int]:
    """ICPC / Codeforces flat scoring: sum scores and report the first non-OK verdict."""
    max_score = sum(t.score for t in tests)
    total_score = sum(r.score for r in results)
    overall = ExecutionStatus.OK
    for r in results:
        if r.status != ExecutionStatus.OK:
            overall = r.status
            break
    return overall, total_score, max_score


def _aggregate_subtasks(
    subtasks: list[Subtask],
    results: list[TestResult],
) -> tuple[ExecutionStatus, int, int, list[SubtaskResult]]:
    """
    IOI-style subtask aggregation with topological ordering and
    min/sum/all_or_nothing score modes.
    """
    # Group results by subtask
    by_subtask: dict[str, list[TestResult]] = {}
    for r in results:
        if r.subtask:
            by_subtask.setdefault(r.subtask, []).append(r)

    sorted_ids = _toposort_subtasks(subtasks)

    score_map: dict[str, int] = {}
    sub_results: list[SubtaskResult] = []
    overall_first_failure: ExecutionStatus | None = None

    by_id = {st.id: st for st in subtasks}
    for st_id in sorted_ids:
        st = by_id[st_id]
        st_results = by_subtask.get(st.id, [])
        passed = sum(1 for r in st_results if r.status == ExecutionStatus.OK)

        # Dependency check
        skipped = any(score_map.get(dep, 0) <= 0 for dep in st.depends_on)
        if skipped:
            sub_results.append(SubtaskResult(
                id=st.id, name=st.name, score=0, max_score=st.max_score,
                status=ExecutionStatus.SK, test_count=len(st_results),
                passed_count=passed, skipped=True,
            ))
            score_map[st.id] = 0
            for r in st_results:
                r.status = ExecutionStatus.SK
                r.score = 0
            continue

        # Aggregate score based on score_mode
        if not st_results:
            score = 0
            status = ExecutionStatus.WA
        elif st.score_mode == "all_or_nothing":
            if all(r.status == ExecutionStatus.OK for r in st_results):
                score = st.max_score
                status = ExecutionStatus.OK
            else:
                score = 0
                status = next(
                    (r.status for r in st_results if r.status != ExecutionStatus.OK),
                    ExecutionStatus.WA,
                )
        elif st.score_mode == "sum":
            score = min(sum(r.score for r in st_results), st.max_score)
            status = ExecutionStatus.OK if passed == len(st_results) else next(
                (r.status for r in st_results if r.status != ExecutionStatus.OK),
                ExecutionStatus.WA,
            )
        else:  # "min"
            ratios: list[float] = []
            for r in st_results:
                ratios.append(1.0 if r.status == ExecutionStatus.OK else 0.0)
            score = int(st.max_score * min(ratios) if ratios else 0)
            status = ExecutionStatus.OK if score == st.max_score else next(
                (r.status for r in st_results if r.status != ExecutionStatus.OK),
                ExecutionStatus.WA,
            )

        score_map[st.id] = score
        sub_results.append(SubtaskResult(
            id=st.id, name=st.name, score=score, max_score=st.max_score,
            status=status, test_count=len(st_results),
            passed_count=passed, skipped=False,
        ))

        if overall_first_failure is None and status != ExecutionStatus.OK:
            overall_first_failure = status

    total = sum(score_map.values())
    max_total = sum(st.max_score for st in subtasks)
    overall = overall_first_failure or ExecutionStatus.OK
    return overall, total, max_total, sub_results


def _toposort_subtasks(subtasks: list[Subtask]) -> list[str]:
    """Kahn's topological sort; falls back to original order if a cycle is detected."""
    in_degree: dict[str, int] = {st.id: 0 for st in subtasks}
    deps: dict[str, list[str]] = {st.id: list(st.depends_on) for st in subtasks}
    children: dict[str, list[str]] = {st.id: [] for st in subtasks}
    for st in subtasks:
        for d in st.depends_on:
            if d in in_degree:
                in_degree[st.id] += 1
                children[d].append(st.id)

    queue = deque(st.id for st in subtasks if in_degree[st.id] == 0)
    order: list[str] = []
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for ch in children.get(cur, []):
            in_degree[ch] -= 1
            if in_degree[ch] == 0:
                queue.append(ch)

    if len(order) != len(subtasks):
        logger.warning("Cycle detected in subtask dependencies -- using original order")
        return [st.id for st in subtasks]
    return order


def _truncate(s: str, n: int) -> str:
    return s[:n] if s else ""


# ─────────────────────────────────────────────────────────────────────────
#  Per-test verdict logic
# ─────────────────────────────────────────────────────────────────────────
async def _determine_test_status(
    result: ExecutionResult,
    time_limit_ms: int,
    memory_limit_mb: int,
    test_input: str,
    expected_output: str,
    checker_config: CheckerConfig | None,
    checker_dir: str | None,
) -> tuple[ExecutionStatus, str]:
    """
    Determine the verdict for a single test case.
    Verdict priority: CE > TLE > MLE > OLE > RTE > WA > PE > OK.
    """
    if result.output_limit_exceeded:
        return ExecutionStatus.OLE, "Output limit exceeded"

    if result.exit_code == 0:
        if result.time_ms > time_limit_ms:
            return ExecutionStatus.TLE, ""
        if result.memory_kb > memory_limit_mb * 1024:
            return ExecutionStatus.MLE, ""

        verdict, msg = await _check_output(
            result.stdout, expected_output, test_input,
            checker_config, checker_dir,
        )
        return verdict, msg

    # Non-zero exit
    if result.timed_out or result.time_ms > time_limit_ms:
        return ExecutionStatus.TLE, ""
    if result.memory_exceeded or result.memory_kb > memory_limit_mb * 1024:
        return ExecutionStatus.MLE, ""
    return ExecutionStatus.RTE, ""


async def _check_output(
    actual: str,
    expected: str,
    test_input: str,
    checker_config: CheckerConfig | None,
    checker_dir: str | None,
) -> tuple[ExecutionStatus, str]:
    """Determine the verdict based on the configured checker type."""
    checker_type = checker_config.type if checker_config else "standard"

    if checker_type == "tokens":
        return (ExecutionStatus.OK, "") if compare_tokens(actual, expected) else (
            ExecutionStatus.WA, "Token mismatch"
        )

    if checker_type == "float":
        epsilon = checker_config.epsilon if checker_config else 1e-6
        return (ExecutionStatus.OK, "") if compare_float(actual, expected, epsilon) else (
            ExecutionStatus.WA, f"Float mismatch (eps={epsilon})"
        )

    if checker_type == "custom" and checker_dir:
        return await _run_custom_checker(
            checker_dir, test_input, expected, actual,
        )

    # standard -- Codeforces wcmp-style comparison
    cmp = compare_standard(actual, expected)
    if cmp == "OK":
        return ExecutionStatus.OK, ""
    if cmp == "PE":
        return ExecutionStatus.PE, "Tokens match but formatting differs"
    return ExecutionStatus.WA, "Output mismatch"


async def _run_custom_checker(
    checker_dir: str,
    test_input: str,
    expected_output: str,
    actual_output: str,
) -> tuple[ExecutionStatus, str]:
    """
    Run a custom checker (Polygon / testlib.h-style).

    Exit codes: 0=OK, 1=WA, 2=PE, 3=Partial (treated as WA).
    """
    checker_lang = get_language("cpp")
    if not checker_lang:
        return ExecutionStatus.WA, "Checker language unavailable"

    def _section(data: str) -> bytes:
        encoded = data.encode("utf-8", "replace")
        return f"{len(encoded)}\n".encode() + encoded + b"\n"

    stdin_bytes = (
        _section(test_input)
        + _section(expected_output)
        + _section(actual_output)
    )

    try:
        result = await nsjail_runner.run_test(
            language=checker_lang,
            compiled_dir=checker_dir,
            input_data=stdin_bytes.decode("utf-8", "replace"),
            time_limit_ms=5000,
            memory_limit_mb=256,
        )

        msg = (result.stderr or "").strip()[:200]

        if result.exit_code == 0:
            return ExecutionStatus.OK, msg
        if result.exit_code == 1:
            return ExecutionStatus.WA, msg or "Checker rejected"
        if result.exit_code == 2:
            return ExecutionStatus.PE, msg or "Presentation error"
        if result.exit_code == 3:
            return ExecutionStatus.WA, msg or "Partial answer"

        logger.warning("Checker returned unknown exit code: %d", result.exit_code)
        return ExecutionStatus.WA, msg or f"Checker exit={result.exit_code}"

    except Exception as e:
        logger.exception("Custom checker error: %s", e)
        return ExecutionStatus.IE, f"Checker error: {e}"

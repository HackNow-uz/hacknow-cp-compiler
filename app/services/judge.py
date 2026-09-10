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
from app.sandbox.runner import SecurityError, check_disk_pressure, read_test_data
from app.schemas.requests import (
    CheckerConfig, InteractiveConfig, JudgeRequest, Subtask, TestCase,
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

    # Disk pressure check — return 503-like IE before wasting resources
    if check_disk_pressure():
        judge_inflight.labels(language=data.language_id).dec()
        logger.warning("judge.disk_pressure: temp dir usage above threshold")
        return JudgeResponse(
            submission_id=data.submission_id,
            problem_id=data.problem_id,
            language_id=data.language_id,
            status=ExecutionStatus.IE,
            error="Service temporarily unavailable: disk pressure",
        )

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

    # NOTE: every name referenced by the `finally` block below MUST be bound
    # here, BEFORE `try:`. The compile-error path returns from inside the try
    # before step 2b, so initialising these there left `interactor_dir` unbound
    # and the `finally` raised UnboundLocalError — which replaces the return
    # value and turns every CE into an HTTP 500.
    compiled_dir = None
    checker_dir = None
    checker_language = None
    interactor_dir = None
    interactor_language = None
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
            if not settings.allow_custom_checker:
                return JudgeResponse(
                    submission_id=data.submission_id,
                    problem_id=data.problem_id,
                    language_id=data.language_id,
                    status=ExecutionStatus.IE,
                    error="Custom checkers are disabled by service policy",
                )
            checker_language = get_language(data.checker.language_id or "cpp")
            if checker_language:
                checker_dir, checker_compile_out, _ = await nsjail_runner.compile_once(
                    language=checker_language,
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

        # ── 2b. Compile interactor if needed ───────────────────────────
        if data.interactive:
            interactor_language = get_language(data.interactive.interactor_language_id or "cpp")
            if not interactor_language:
                return JudgeResponse(
                    submission_id=data.submission_id,
                    problem_id=data.problem_id,
                    language_id=data.language_id,
                    status=ExecutionStatus.IE,
                    error=f"Unsupported interactor language: {data.interactive.interactor_language_id}",
                )
            interactor_dir, int_compile_out, _ = await nsjail_runner.compile_once(
                language=interactor_language,
                source_code=data.interactive.interactor_code,
            )
            if interactor_dir is None:
                logger.error("judge.interactor_compile_error", extra={
                    **log_extra, "interactor_output": int_compile_out[:500],
                })
                return JudgeResponse(
                    submission_id=data.submission_id,
                    problem_id=data.problem_id,
                    language_id=data.language_id,
                    status=ExecutionStatus.IE,
                    compile_output=compile_output,
                    compile_time_ms=compile_time_ms,
                    error=f"Interactor compilation error: {int_compile_out[:500]}",
                )

        # ── 3. Run tests ────────────────────────────────────────────────
        test_results = await _run_all_tests(
            data, language, compiled_dir, checker_dir,
            interactor_dir=interactor_dir,
            interactor_language=interactor_language,
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
            # `language.id`, not `data.language_id`: "cpp17"/"py" are aliases for
            # "cpp"/"py3", and compile_once() caches under the canonical id — so
            # releasing under the alias silently decremented nothing.
            nsjail_runner.release_compiled(language.id, data.source_code)
        # compile_once() takes one cache ref per successful compile — the
        # checker and the interactor need releasing too, otherwise their
        # ref_count never returns to 0 and the cache dir is never reclaimed.
        if checker_dir:
            shutil.rmtree(checker_dir, ignore_errors=True)
            if checker_language:
                nsjail_runner.release_compiled(checker_language.id, data.checker.code)
        if interactor_dir:
            shutil.rmtree(interactor_dir, ignore_errors=True)
            if interactor_language:
                nsjail_runner.release_compiled(
                    interactor_language.id, data.interactive.interactor_code,
                )


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
    interactor_dir: str | None = None,
    interactor_language=None,
) -> TestResult:
    """Execute a single test case inside an nsjail sandbox and return a TestResult.

    Supports inline and file-based test data, and interactive mode.
    Graceful isolation: catches per-test exceptions and returns IE instead of crashing.
    """
    time_limit = test.time_limit_ms or data.time_limit_ms
    memory_limit = test.memory_limit_mb or data.memory_limit_mb

    try:
        # Resolve expected output (always needed for verdict checking)
        expected_output = read_test_data(test.expected_output, test.expected_output_path)

        # For file-based input: stream directly from disk to avoid double read.
        # Only read into memory when needed (interactive mode or inline input).
        use_file_streaming = (test.input is None and test.input_path is not None)

        if interactor_dir and interactor_language:
            # Interactive mode needs input in memory for the interactor header
            test_input = read_test_data(test.input, test.input_path)
            sub_result, int_result = await nsjail_runner.run_interactive(
                language=language,
                compiled_dir=compiled_dir,
                interactor_dir=interactor_dir,
                interactor_language=interactor_language,
                test_input=test_input,
                time_limit_ms=time_limit,
                memory_limit_mb=memory_limit,
            )
            status, checker_message = _determine_interactive_status(
                sub_result, int_result, time_limit, memory_limit,
            )
            exec_result = sub_result
        else:
            # Standard mode — stream from file if possible
            if use_file_streaming:
                result = await nsjail_runner.run_test(
                    language=language,
                    compiled_dir=compiled_dir,
                    input_data="",
                    time_limit_ms=time_limit,
                    memory_limit_mb=memory_limit,
                    input_file_path=test.input_path,
                )
                # For verdict checking, read input only if custom checker needs it
                if data.checker and data.checker.type == "custom":
                    test_input = read_test_data(test.input, test.input_path)
                else:
                    test_input = ""
            else:
                test_input = test.input or ""
                result = await nsjail_runner.run_test(
                    language=language,
                    compiled_dir=compiled_dir,
                    input_data=test_input,
                    time_limit_ms=time_limit,
                    memory_limit_mb=memory_limit,
                )

            status, checker_message = await _determine_test_status(
                result, time_limit, memory_limit,
                test_input, expected_output,
                data.checker, checker_dir,
            )
            exec_result = result

        score = test.score if status == ExecutionStatus.OK else 0

        judge_test_time_ms.labels(language=language.id).observe(exec_result.time_ms)

        return TestResult(
            test_id=test.id,
            status=status,
            time_ms=exec_result.time_ms,
            memory_kb=exec_result.memory_kb,
            score=score,
            stdout=_truncate(exec_result.stdout, 500),
            stderr=_truncate(exec_result.stderr, 500),
            subtask=test.subtask,
            checker_message=checker_message,
        )

    except (SecurityError, FileNotFoundError, ValueError) as exc:
        # Bad or refused test-data path: a problem-configuration fault, never
        # the submission's. Report IE and keep the resolved path out of the
        # response — the full detail goes to the log for the operator.
        logger.error(
            "Test %s: test-data rejected: %s", test.id, exc, exc_info=True,
        )
        return TestResult(
            test_id=test.id,
            status=ExecutionStatus.IE,
            score=0,
            subtask=test.subtask,
            checker_message="Internal error: test data unavailable",
        )

    except Exception as exc:
        # Graceful isolation — one test crashing doesn't kill the whole judge
        logger.error("Test %s failed with exception: %s", test.id, exc, exc_info=True)
        return TestResult(
            test_id=test.id,
            status=ExecutionStatus.IE,
            score=0,
            subtask=test.subtask,
            checker_message=f"Internal error: {str(exc)[:100]}",
        )


def _determine_interactive_status(
    sub_result: ExecutionResult,
    int_result: ExecutionResult,
    time_limit_ms: int,
    memory_limit_mb: int,
) -> tuple[ExecutionStatus, str]:
    """Determine verdict for interactive problems.

    Interactor exit codes: 0=OK, 1=WA, 2=PE, 3=Partial (→WA).
    Submission resource limits are checked first.
    """
    # Check submission resource limits first
    if sub_result.output_limit_exceeded:
        return ExecutionStatus.OLE, "Output limit exceeded"
    if sub_result.timed_out or sub_result.time_ms > time_limit_ms:
        return ExecutionStatus.TLE, ""
    if sub_result.memory_exceeded or sub_result.memory_kb > memory_limit_mb * 1024:
        return ExecutionStatus.MLE, ""
    if sub_result.exit_code != 0 and not int_result.timed_out:
        return ExecutionStatus.RTE, ""

    # Interactor verdict
    msg = "".join(c for c in (int_result.stderr or "").strip() if c.isprintable())[:64]
    if int_result.exit_code == 0:
        return ExecutionStatus.OK, msg
    if int_result.exit_code == 1:
        return ExecutionStatus.WA, msg or "Interactor rejected"
    if int_result.exit_code == 2:
        return ExecutionStatus.PE, msg or "Protocol error"
    return ExecutionStatus.WA, msg or f"Interactor exit={int_result.exit_code}"


async def _run_all_tests(
    data: JudgeRequest,
    language,
    compiled_dir: str,
    checker_dir: str | None,
    interactor_dir: str | None = None,
    interactor_language=None,
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
            tr = await _run_single_test(
                test, data, language, compiled_dir, checker_dir,
                interactor_dir=interactor_dir,
                interactor_language=interactor_language,
            )
            test_results.append(tr)
            if tr.status != ExecutionStatus.OK:
                break
        return test_results

    coros = [
        _run_single_test(
            test, data, language, compiled_dir, checker_dir,
            interactor_dir=interactor_dir,
            interactor_language=interactor_language,
        )
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

        # SECURITY: a malicious checker can encode the expected output in
        # stderr to exfiltrate problem data. Limit to 64 chars and only allow
        # printable ASCII (no control chars, no full output reflection).
        raw = (result.stderr or "").strip()
        msg = "".join(c for c in raw if c.isprintable())[:64]

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

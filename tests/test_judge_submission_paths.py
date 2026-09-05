"""End-to-end paths through judge_submission().

Regression cover for the 2026-05-16 defect (v2.4.0): `interactor_dir` was
initialised inside the try block, *after* the compile-error and checker-error
early returns, while the `finally` block referenced it unconditionally. Every
submission that failed to compile therefore raised

    UnboundLocalError: cannot access local variable 'interactor_dir'

from inside `finally`, which replaces the return value — so /api/v1/judge
answered HTTP 500 and students saw "Internal Error" instead of their compiler
diagnostics. CE verdicts fell to zero in production for ~3.7 months.

These tests stub the sandbox so they run anywhere (no nsjail needed) and
exercise judge_submission() itself, which the pre-existing suite never did:
it only covered the pure aggregation helpers.
"""
import pytest

from app.schemas.requests import CheckerConfig, InteractiveConfig, JudgeRequest, TestCase
from app.schemas.responses import ExecutionStatus
from app.services import judge as judge_mod


def _request(**overrides) -> JudgeRequest:
    payload = dict(
        submission_id="s1",
        problem_id="p1",
        language_id="cpp",
        source_code="int main(){}",
        tests=[TestCase(id="t1", input="1", expected_output="1", score=10)],
    )
    payload.update(overrides)
    return JudgeRequest(**payload)


@pytest.fixture
def sandbox(monkeypatch):
    """Stub nsjail_runner; each test sets .compile_results / .released."""

    class _Stub:
        def __init__(self):
            self.compile_results = []   # queued (dir, output, ms) tuples
            self.released = []          # (language_id, source_code) pairs
            self.calls = []

        async def compile_once(self, language, source_code):
            self.calls.append((language.id, source_code))
            if self.compile_results:
                return self.compile_results.pop(0)
            return ("/tmp/fake-compiled", "", 5)

        def release_compiled(self, language_id, source_code):
            self.released.append((language_id, source_code))

    stub = _Stub()
    monkeypatch.setattr(judge_mod, "nsjail_runner", stub)
    monkeypatch.setattr(judge_mod, "check_disk_pressure", lambda: False)
    # Cleanup must not touch the real filesystem for the fake dirs above.
    monkeypatch.setattr(judge_mod.shutil, "rmtree", lambda *a, **k: None)
    return stub


class TestCompileErrorPath:
    """The path that produced the 500 in production."""

    @pytest.mark.asyncio
    async def test_compile_error_returns_ce_not_exception(self, sandbox):
        sandbox.compile_results = [(None, "main.cpp:1: error: expected ';'", 42)]

        # Before the fix this raised UnboundLocalError out of `finally`.
        result = await judge_mod.judge_submission(_request())

        assert result.status == ExecutionStatus.CE
        assert result.score == 0
        assert "expected ';'" in result.compile_output
        assert result.compile_time_ms == 42

    @pytest.mark.asyncio
    async def test_compile_error_does_not_release_an_unheld_cache_ref(self, sandbox):
        """compile_once takes no cache ref when it fails, so nothing to release."""
        sandbox.compile_results = [(None, "syntax error", 7)]

        await judge_mod.judge_submission(_request())

        assert sandbox.released == []

    @pytest.mark.asyncio
    async def test_compile_error_reports_max_score_from_tests(self, sandbox):
        sandbox.compile_results = [(None, "err", 1)]
        req = _request(tests=[
            TestCase(id="t1", input="", expected_output="", score=30),
            TestCase(id="t2", input="", expected_output="", score=70),
        ])

        result = await judge_mod.judge_submission(req)

        assert result.status == ExecutionStatus.CE
        assert result.max_score == 100


class TestCheckerErrorPaths:
    """Same class of early return — also reached `finally` before the fix."""

    @pytest.mark.asyncio
    async def test_checker_compile_error_returns_ie_not_exception(self, sandbox):
        sandbox.compile_results = [
            ("/tmp/submission", "", 10),   # submission compiles
            (None, "checker.cpp: error", 8),  # checker does not
        ]
        req = _request(checker=CheckerConfig(type="custom", code="int main(){}"))

        result = await judge_mod.judge_submission(req)

        assert result.status == ExecutionStatus.IE
        assert "Checker compilation error" in result.error

    @pytest.mark.asyncio
    async def test_custom_checker_disabled_returns_ie_not_exception(
        self, sandbox, monkeypatch
    ):
        monkeypatch.setattr(judge_mod.settings, "allow_custom_checker", False)
        req = _request(checker=CheckerConfig(type="custom", code="int main(){}"))

        result = await judge_mod.judge_submission(req)

        assert result.status == ExecutionStatus.IE
        assert "disabled" in result.error


class TestCompileCacheRefRelease:
    """Every successful compile_once takes one cache ref that must come back."""

    @pytest.mark.asyncio
    async def test_submission_ref_released(self, sandbox, monkeypatch):
        monkeypatch.setattr(judge_mod, "_run_all_tests", _ok_tests)

        await judge_mod.judge_submission(_request())

        assert ("cpp", "int main(){}") in sandbox.released

    @pytest.mark.asyncio
    async def test_alias_language_releases_under_canonical_id(
        self, sandbox, monkeypatch
    ):
        """"cpp17" is an alias for "cpp"; compile_once caches under the
        canonical id, so the release must use it too or it decrements nothing."""
        monkeypatch.setattr(judge_mod, "_run_all_tests", _ok_tests)

        await judge_mod.judge_submission(_request(language_id="cpp17"))

        assert sandbox.released == [("cpp", "int main(){}")]

    @pytest.mark.asyncio
    async def test_checker_ref_released(self, sandbox, monkeypatch):
        monkeypatch.setattr(judge_mod, "_run_all_tests", _ok_tests)
        checker_src = "int main(){return 0;}"
        req = _request(checker=CheckerConfig(type="custom", code=checker_src))

        await judge_mod.judge_submission(req)

        assert ("cpp", checker_src) in sandbox.released

    @pytest.mark.asyncio
    async def test_interactor_ref_released(self, sandbox, monkeypatch):
        monkeypatch.setattr(judge_mod, "_run_all_tests", _ok_tests)
        interactor_src = "int main(){return 0;}"
        req = _request(interactive=InteractiveConfig(interactor_code=interactor_src))

        await judge_mod.judge_submission(req)

        assert ("cpp", interactor_src) in sandbox.released


async def _ok_tests(data, language, compiled_dir, checker_dir, **kwargs):
    from app.schemas.responses import TestResult
    return [
        TestResult(test_id=t.id, status=ExecutionStatus.OK, score=t.score)
        for t in data.tests
    ]

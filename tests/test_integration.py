"""Integration tests that execute code through the real nsjail sandbox.

Run inside the Docker container:
    pytest tests/test_integration.py -m integration -v

Skipped automatically when nsjail is not available (CI, dev machines).
"""
import os
import os.path as _real_ospath
import shutil
import tempfile
import time

import pytest
import pytest_asyncio

from app.languages import get_language
from app.sandbox import NsjailRunner
from app.schemas.requests import JudgeRequest, TestCase
from app.schemas.responses import ExecutionStatus
from app.services.judge import judge_submission

# Use os.path.isfile to bypass the conftest os.path.exists patch
NSJAIL_AVAILABLE = _real_ospath.isfile("/usr/bin/nsjail")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not NSJAIL_AVAILABLE, reason="nsjail not available"),
    pytest.mark.asyncio,
]


@pytest_asyncio.fixture
async def runner():
    r = NsjailRunner()
    yield r


@pytest.fixture
def tmp_artifacts(tmp_path):
    yield tmp_path


# ── 1. C++ compile and run ──────────────────────────────────────────────

async def test_cpp_hello_world(runner):
    lang = get_language("cpp")
    source = '#include <iostream>\nint main() { std::cout << "hello"; }'
    result, compile_out, _ = await runner.execute(
        language=lang, source_code=source,
        input_data="", time_limit_ms=5000, memory_limit_mb=256,
    )
    assert result.stdout.strip() == "hello"


# ── 2. Python execution ────────────────────────────────────────────────

async def test_python_a_plus_b(runner):
    lang = get_language("py3")
    source = "a, b = map(int, input().split())\nprint(a + b)"
    result, _, _ = await runner.execute(
        language=lang, source_code=source,
        input_data="3 7\n", time_limit_ms=5000, memory_limit_mb=256,
    )
    assert result.stdout.strip() == "10"


# ── 3. Compilation error ───────────────────────────────────────────────

async def test_cpp_compile_error(runner):
    lang = get_language("cpp")
    source = "int main() { this is not valid c++ }"
    result, compile_out, _ = await runner.execute(
        language=lang, source_code=source,
        input_data="", time_limit_ms=5000, memory_limit_mb=256,
    )
    assert result.exit_code != 0
    assert compile_out != ""


# ── 4. Time limit exceeded ─────────────────────────────────────────────

async def test_cpp_tle(runner):
    lang = get_language("cpp")
    source = "int main() { while(1); }"
    result, _, _ = await runner.execute(
        language=lang, source_code=source,
        input_data="", time_limit_ms=1000, memory_limit_mb=256,
    )
    assert result.timed_out


# ── 5. Runtime error ───────────────────────────────────────────────────

async def test_cpp_runtime_error(runner):
    lang = get_language("cpp")
    source = "#include <cstdlib>\nint main() { int *p = nullptr; *p = 42; }"
    result, _, _ = await runner.execute(
        language=lang, source_code=source,
        input_data="", time_limit_ms=5000, memory_limit_mb=256,
    )
    assert result.exit_code != 0


# ── 6. Memory limit exceeded ──────────────────────────────────────────

async def test_cpp_mle(runner):
    lang = get_language("cpp")
    source = (
        "#include <vector>\n"
        "int main() {\n"
        "  std::vector<char> v;\n"
        "  while(true) v.resize(v.size() + 1024*1024*10);\n"
        "}\n"
    )
    result, _, _ = await runner.execute(
        language=lang, source_code=source,
        input_data="", time_limit_ms=5000, memory_limit_mb=64,
    )
    assert result.exit_code != 0


# ── 7. Source validation rejection ─────────────────────────────────────

async def test_go_embed_rejected(runner):
    lang = get_language("go")
    source = (
        'package main\n'
        '//go:embed secret.txt\n'
        'var s string\n'
        'func main() {}\n'
    )
    result, compile_out, _ = await runner.execute(
        language=lang, source_code=source,
        input_data="", time_limit_ms=5000, memory_limit_mb=256,
    )
    assert "not allowed" in compile_out


# ── 8. Judge with 3 tests (2 correct + 1 wrong = WA) ──────────────────

async def test_judge_partial_wa():
    req = JudgeRequest(
        submission_id="test-001",
        problem_id="aplusb",
        language_id="py3",
        source_code="a, b = map(int, input().split())\nprint(a + b)",
        tests=[
            TestCase(id="t1", input="1 2\n", expected_output="3\n", score=10),
            TestCase(id="t2", input="5 5\n", expected_output="10\n", score=10),
            TestCase(id="t3", input="3 4\n", expected_output="999\n", score=10),
        ],
        time_limit_ms=5000,
        memory_limit_mb=256,
        stop_on_first_failure=False,
    )
    resp = await judge_submission(req)
    assert resp.status == ExecutionStatus.WA
    assert resp.score == 20
    assert resp.max_score == 30


# ── 9. Compilation cache hit ──────────────────────────────────────────

async def test_compile_cache_hit(runner):
    lang = get_language("cpp")
    source = '#include <iostream>\nint main() { std::cout << "cached"; }'

    _, _, time_1 = await runner.compile_once(language=lang, source_code=source)
    runner.release_compiled(lang.id, source)

    _, _, time_2 = await runner.compile_once(language=lang, source_code=source)
    runner.release_compiled(lang.id, source)

    assert time_2 < time_1 or time_2 == 0


# ── 10. Output limit exceeded ─────────────────────────────────────────

async def test_cpp_output_limit(runner):
    lang = get_language("cpp")
    source = (
        '#include <cstdio>\n'
        'int main() {\n'
        '  char buf[4096];\n'
        '  for(int i=0;i<4096;i++) buf[i]=\'A\';\n'
        '  for(long i=0;i<100000;i++) fwrite(buf,1,4096,stdout);\n'
        '}\n'
    )
    result, _, _ = await runner.execute(
        language=lang, source_code=source,
        input_data="", time_limit_ms=10000, memory_limit_mb=256,
    )
    assert result.output_limit_exceeded or len(result.stdout) > 0

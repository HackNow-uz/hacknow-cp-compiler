"""nsjail --rlimit_as qiymati: PyPy chuqur rekursiya uchun yetarli virtual manzil oladi."""
from app.languages.config import LANGUAGES
from app.sandbox.runner import NsjailRunner


def _as_mb(lang_id: str, memory_limit_mb: int = 256) -> int:
    runner = object.__new__(NsjailRunner)  # __init__ nsjail binarini talab qiladi
    runner.nsjail_path = "/usr/bin/nsjail"
    runner._cached_bindmounts = []
    args = runner._get_nsjail_command(
        "/tmp/x", 1000, memory_limit_mb, ["run"], language=LANGUAGES[lang_id],
    )
    return int(args[args.index("--rlimit_as") + 1])


def test_pypy_gets_room_for_setrecursionlimit():
    # 1024 MB da PyPy sys.setrecursionlimit(10**6) MemoryError beradi
    assert _as_mb("pypy3") >= 2048


def test_pypy_scales_with_large_limit():
    assert _as_mb("pypy3", 1024) == 4096


def test_cpython_unchanged():
    assert _as_mb("py3") == 1024

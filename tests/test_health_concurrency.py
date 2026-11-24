"""Band slotlarni hisoblash: /health/detail monitoring uchun."""
import asyncio

import pytest

pytest.importorskip("fastapi")


def _fn():
    import pathlib
    import re
    # health.py import paytida nsjail/sozlamalarni talab qilmasligi uchun faqat funksiyaning o'zi olinadi.
    src = pathlib.Path(__file__).resolve().parents[1].joinpath("app/api/health.py").read_text()
    body = re.search(r"def semaphore_in_use\(.*?\n\n\n", src, re.S).group(0)
    ns: dict = {}
    exec(body, ns)  # noqa: S102 — o'z repomizdagi kod
    return ns["semaphore_in_use"]


def test_counts_acquired_slots():
    f = _fn()

    async def run():
        sem = asyncio.Semaphore(4)
        assert f(sem, 4) == 0
        await sem.acquire()
        await sem.acquire()
        assert f(sem, 4) == 2
        sem.release()
        assert f(sem, 4) == 1

    asyncio.run(run())


def test_unknown_instead_of_wrong_number():
    f = _fn()

    class NoValue:
        pass

    class Weird:
        _value = "3"

    assert f(NoValue(), 4) is None
    assert f(Weird(), 4) is None
    assert f(asyncio.Semaphore(4), 0) is None


def test_result_is_clamped():
    f = _fn()

    class Over:
        _value = 9      # jami sondan ko'p bo'sh — manfiy band soni chiqmasin

    class Under:
        _value = -3     # hech qachon jami sondan ko'p band emas

    assert f(Over(), 4) == 0
    assert f(Under(), 4) == 4


def test_schema_has_optional_live_fields():
    from app.schemas.responses import ConcurrencyStats
    s = ConcurrencyStats(global_slots=8, per_language_slots=4)
    assert (s.global_in_use, s.judge_inflight, s.judge_max_inflight) == (None, None, None)
    assert ConcurrencyStats(global_slots=8, per_language_slots=4, global_in_use=3, judge_inflight=2, judge_max_inflight=12).global_in_use == 3

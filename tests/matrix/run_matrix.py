"""Drive the verdict matrix against a running compiler instance.

Runs inside the compiler container (stdlib only — no requests/httpx needed):
    python3 run_matrix.py --token "$TOKEN" [--lang cpp] [--verdict ce]

Prints a per-cell PASS/FAIL table and exits non-zero if any cell fails, so it
can be a CI stage. Every cell asserts the verdict AND that no HTTP 5xx escaped
(a 500 is always a defect, whatever the verdict should have been).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from programs import ALIASES, ALL_LANGUAGES, PROGRAMS, VERDICTS

EXPECTED = {
    "ok": "OK", "wa": "WA", "ce": "CE",
    "rte": "RTE", "tle": "TLE", "mle": "MLE", "ole": "OLE",
}
# Verdicts that legitimately have more than one acceptable outcome.
TOLERATED = {
    # A memory-starved runtime often dies via its own allocator instead of the
    # cgroup killer; both are correct rejections of an over-allocating program.
    "mle": {"MLE", "RTE"},
    # Flooding stdout can trip the output cap or the time cap first.
    "ole": {"OLE", "TLE"},
    # Interpreters with no separate compile step surface syntax errors at
    # runtime; the judge is entitled to report either.
    "ce": {"CE", "RTE"},
}


def judge(base, token, lang, source, tlim, mlim, timeout):
    payload = {
        "submission_id": "matrix-%s" % lang,
        "problem_id": "matrix",
        "language_id": lang,
        "source_code": source,
        "tests": [{"id": "t1", "input": "2 3", "expected_output": "5", "score": 10}],
        "time_limit_ms": tlim,
        "memory_limit_mb": mlim,
    }
    req = urllib.request.Request(
        base + "/api/v1/judge",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"raw": e.read().decode()[:400]}
    except Exception as e:
        return 0, {"raw": "%s: %s" % (type(e).__name__, e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--token", required=True)
    ap.add_argument("--lang", action="append")
    ap.add_argument("--verdict", action="append")
    ap.add_argument("--time-limit", type=int, default=1000)
    ap.add_argument("--memory-limit", type=int, default=256)
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args()

    langs = a.lang or list(ALL_LANGUAGES)
    verds = a.verdict or list(VERDICTS)

    print("%-9s %-5s %-6s %-6s %8s  %s" % ("LANG", "CELL", "WANT", "GOT", "ms", "RESULT"))
    print("-" * 78)
    fails, cells = [], 0
    for lang in langs:
        for v in verds:
            src = PROGRAMS[lang][v]
            want = EXPECTED[v]
            allowed = TOLERATED.get(v, {want})
            t0 = time.time()
            code, body = judge(a.base, a.token, lang, src,
                               a.time_limit, a.memory_limit, a.timeout)
            ms = int((time.time() - t0) * 1000)
            got = body.get("status", "HTTP%s" % code)
            cells += 1
            if code >= 500 or code == 0:
                verdict = "FAIL 5xx/err"
                fails.append((lang, v, got, body.get("raw", "")[:160]))
            elif got in allowed:
                verdict = "pass" if got == want else "pass (%s)" % got
            else:
                verdict = "FAIL"
                fails.append((lang, v, got, (body.get("error") or body.get("raw") or "")[:160]))
            print("%-9s %-5s %-6s %-6s %8d  %s" % (lang, v, want, got, ms, verdict))

    print("-" * 78)
    print("%d cells, %d failed" % (cells, len(fails)))
    if fails:
        print("\nFAILURES")
        for lang, v, got, detail in fails:
            print("  %-9s %-5s got=%-6s %s" % (lang, v, got, detail.replace("\n", " ")))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

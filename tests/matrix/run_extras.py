"""Phase 1 extras: the judge paths the verdict matrix does not reach.

Covers the three areas that had zero coverage:
  * interactive problems  (feature shipped in v2.4.0, 0 production use, 0 tests)
  * file-based test delivery via input_path / expected_output_path
  * path-traversal rejection on those same fields

Runs inside the compiler container, stdlib only:
    python3 run_extras.py --token "$TOKEN"

Exits non-zero if any probe fails, so it can be a CI stage.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

# ── interactive: classic "guess the number" ───────────────────────────────
# Protocol implemented by the service: the interactor receives `test_input`
# plus a newline on its stdin, then interactor stdout <-> submission stdin
# are relayed bidirectionally. Interactor exit code is the verdict:
# 0=OK, 1=WA, 2=PE, anything else -> WA.

INTERACTOR_OK = r'''
#include <iostream>
int main(){
    long long secret, hi;
    if(!(std::cin >> secret >> hi)) return 2;      // header line
    long long guess; int queries = 0;
    while (std::cin >> guess) {
        if (++queries > 25) { std::cerr << "too many queries"; return 1; }
        if (guess == secret) { std::cout << "=" << std::endl; return 0; }
        std::cout << (guess < secret ? "<" : ">") << std::endl;
    }
    std::cerr << "stream closed without solving"; return 1;
}
'''

# Submission that binary-searches — should be accepted.
SUBMISSION_SOLVES = r'''
#include <iostream>
#include <string>
int main(){
    long long lo = 1, hi = 100;
    while (lo <= hi) {
        long long mid = lo + (hi - lo) / 2;
        std::cout << mid << std::endl;
        std::string r;
        if(!(std::cin >> r)) return 0;
        if (r == "=") return 0;
        if (r == "<") lo = mid + 1; else hi = mid - 1;
    }
    return 0;
}
'''

# Submission that guesses linearly from the top — blows the 25-query budget.
SUBMISSION_EXCEEDS = r'''
#include <iostream>
#include <string>
int main(){
    for (long long g = 100; g >= 1; --g) {
        std::cout << g << std::endl;
        std::string r;
        if(!(std::cin >> r)) return 0;
        if (r == "=") return 0;
    }
    return 0;
}
'''

# Submission that never answers — the interactor's idle timeout must fire
# instead of the request hanging forever.
SUBMISSION_SILENT = r'''
#include <unistd.h>
int main(){ sleep(30); return 0; }
'''


def post(base, token, payload, timeout=180):
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
        body = e.read().decode()[:400]
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}
    except Exception as e:
        return 0, {"raw": "%s: %s" % (type(e).__name__, e)}


def base_request(**over):
    p = {
        "submission_id": "extras",
        "problem_id": "extras",
        "language_id": "cpp",
        "source_code": SUBMISSION_SOLVES,
        "tests": [{"id": "t1", "input": "7 100", "expected_output": "", "score": 10}],
        "time_limit_ms": 2000,
        "memory_limit_mb": 256,
    }
    p.update(over)
    return p


def interactive(code):
    return {"interactor_code": code, "interactor_language_id": "cpp"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--token", required=True)
    a = ap.parse_args()

    probes = []

    # ── interactive ───────────────────────────────────────────────────────
    probes.append((
        "interactive: binary search solves",
        base_request(submission_id="int-ok", source_code=SUBMISSION_SOLVES,
                     interactive=interactive(INTERACTOR_OK)),
        {"OK"},
    ))
    probes.append((
        "interactive: query budget exceeded",
        base_request(submission_id="int-wa", source_code=SUBMISSION_EXCEEDS,
                     interactive=interactive(INTERACTOR_OK)),
        {"WA"},
    ))
    probes.append((
        "interactive: submission never replies",
        base_request(submission_id="int-idle", source_code=SUBMISSION_SILENT,
                     interactive=interactive(INTERACTOR_OK)),
        {"WA", "TLE", "RTE"},
    ))
    probes.append((
        "interactive: submission fails to compile -> CE",
        base_request(submission_id="int-ce", source_code="int main(){ int x = ; }",
                     interactive=interactive(INTERACTOR_OK)),
        {"CE"},
    ))
    probes.append((
        "interactive: interactor fails to compile -> IE",
        base_request(submission_id="int-badint", source_code=SUBMISSION_SOLVES,
                     interactive=interactive("this is not c++")),
        {"IE"},
    ))
    probes.append((
        "interactive: unsupported interactor language -> IE",
        base_request(submission_id="int-badlang", source_code=SUBMISSION_SOLVES,
                     interactive={"interactor_code": INTERACTOR_OK,
                                  "interactor_language_id": "brainfuck"}),
        {"IE"},
    ))

    # ── file-based delivery ───────────────────────────────────────────────
    SUM = '#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b;}'
    probes.append((
        "file-based: input_path + expected_output_path",
        base_request(submission_id="fb-ok", source_code=SUM,
                     tests=[{"id": "t1", "score": 10,
                             "input_path": "/test-data/probe_in.txt",
                             "expected_output_path": "/test-data/probe_out.txt"}]),
        {"OK"},
    ))
    probes.append((
        "file-based: mixed inline input + file expected",
        base_request(submission_id="fb-mixed", source_code=SUM,
                     tests=[{"id": "t1", "score": 10, "input": "2 3",
                             "expected_output_path": "/test-data/probe_out.txt"}]),
        {"OK"},
    ))
    probes.append((
        "file-based: missing file -> IE, not 500",
        base_request(submission_id="fb-missing", source_code=SUM,
                     tests=[{"id": "t1", "score": 10,
                             "input_path": "/test-data/does_not_exist.txt",
                             "expected_output": "5"}]),
        {"IE"},
    ))

    # ── traversal: every one of these must be refused ─────────────────────
    for label, path in [
        ("relative ..", "/test-data/../etc/passwd"),
        ("absolute outside root", "/etc/passwd"),
        ("deep traversal", "/test-data/../../etc/shadow"),
        ("prefix sibling dir", "/test-data-evil/secret.txt"),
        ("symlink to /etc/passwd", "/test-data/evil_symlink"),
        ("proc environ (token leak)", "/proc/self/environ"),
    ]:
        probes.append((
            "traversal refused: %s" % label,
            base_request(submission_id="trav", source_code=SUM,
                         tests=[{"id": "t1", "score": 10,
                                 "input_path": path, "expected_output": "5"}]),
            {"IE"},
        ))

    print("%-52s %-6s %-6s %s" % ("PROBE", "WANT", "GOT", "RESULT"))
    print("-" * 92)
    fails = []
    for label, payload, allowed in probes:
        code, body = post(a.base, a.token, payload)
        got = body.get("status", "HTTP%s" % code)
        detail = (body.get("error") or body.get("raw") or "")
        if code >= 500 or code == 0:
            res, ok = "FAIL 5xx/err", False
        elif got in allowed:
            res, ok = "pass", True
        else:
            res, ok = "FAIL", False
        if not ok:
            fails.append((label, got, detail[:150].replace("\n", " ")))
        print("%-52s %-6s %-6s %s" % (label[:52], "/".join(sorted(allowed))[:6], got, res))

    print("-" * 92)
    print("%d probes, %d failed" % (len(probes), len(fails)))
    if fails:
        print("\nFAILURES")
        for label, got, detail in fails:
            print("  %-52s got=%-6s %s" % (label[:52], got, detail))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

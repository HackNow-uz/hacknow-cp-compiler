import math
from typing import Literal

CompareResult = Literal["OK", "PE", "WA"]


def compare_standard(actual: str, expected: str) -> CompareResult:
    """
    Standard checker -- equivalent to Codeforces 'wcmp'.

    Splits both outputs by whitespace into token sequences.
    Different tokens -> "WA". Same tokens -> check formatting -> "OK" or "PE".
    """
    actual_tokens = actual.split()
    expected_tokens = expected.split()

    if actual_tokens != expected_tokens:
        return "WA"

    # Tokens match. Check if formatting is also identical.
    if actual == expected:
        return "OK"
    if _normalize_strict(actual) == _normalize_strict(expected):
        return "OK"
    return "PE"


def compare_tokens(actual: str, expected: str) -> bool:
    """Whitespace-agnostic token comparison. Ignores extra spaces and newlines."""
    return actual.split() == expected.split()


def compare_float(
    actual: str,
    expected: str,
    epsilon: float = 1e-6,
) -> bool:
    """
    Floating-point comparison with both absolute and relative tolerance.

    Equivalent to Codeforces 'rcmp': |a-e| <= eps OR |a-e|/|e| <= eps.
    Token count must match. Non-numeric tokens are compared as strings.
    """
    try:
        a = actual.split()
        e = expected.split()
        if len(a) != len(e):
            return False

        for act, exp in zip(a, e):
            try:
                a_val = float(act)
                e_val = float(exp)
            except ValueError:
                if act != exp:
                    return False
                continue

            if math.isnan(a_val) and math.isnan(e_val):
                continue
            if math.isinf(a_val) or math.isinf(e_val):
                if a_val == e_val:
                    continue
                return False

            diff = abs(a_val - e_val)
            if diff <= epsilon:
                continue
            if abs(e_val) > 0 and diff / abs(e_val) <= epsilon:
                continue
            return False
        return True
    except Exception:
        return False


def _normalize_strict(output: str) -> str:
    """Codeforces-style whitespace normalization:
      - strip trailing whitespace from each line
      - remove trailing empty lines
      - preserve internal whitespace (to distinguish PE from OK)
    """
    if not output:
        return ""
    lines = [line.rstrip() for line in output.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)

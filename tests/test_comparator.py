import pytest
from app.services.comparator import compare_standard, compare_tokens, compare_float


class TestCompareStandard:
    def test_identical(self):
        assert compare_standard("42\n", "42\n") == "OK"

    def test_trailing_whitespace_is_ok(self):
        assert compare_standard("42  \n", "42\n") == "OK"

    def test_trailing_newline_is_ok(self):
        assert compare_standard("42\n\n", "42\n") == "OK"

    def test_pe_extra_spaces_between_tokens(self):
        assert compare_standard("1  2", "1 2") == "PE"

    def test_wa_different_tokens(self):
        assert compare_standard("1 2", "1 3") == "WA"

    def test_empty_both(self):
        assert compare_standard("", "") == "OK"

    def test_wa_empty_vs_nonempty(self):
        assert compare_standard("", "1") == "WA"

    def test_multiline_ok(self):
        assert compare_standard("a\nb\n", "a\nb\n") == "OK"

    def test_multiline_trailing_ws_is_ok(self):
        assert compare_standard("a  \nb\n", "a\nb") == "OK"

    def test_multiline_pe_inner_spacing(self):
        assert compare_standard("a  b\n", "a b\n") == "PE"


class TestCompareTokens:
    @pytest.mark.parametrize("actual,expected", [
        ("1 2 3", "1  2  3"),
        ("hello\nworld", "hello world"),
        ("  a  ", "a"),
    ])
    def test_match(self, actual, expected):
        assert compare_tokens(actual, expected) is True

    def test_mismatch(self):
        assert compare_tokens("1 2", "1 3") is False

    def test_empty(self):
        assert compare_tokens("", "") is True


class TestCompareFloat:
    def test_exact(self):
        assert compare_float("3.14", "3.14") is True

    def test_within_epsilon(self):
        assert compare_float("1.0000001", "1.0000002", epsilon=1e-6) is True

    def test_outside_epsilon(self):
        assert compare_float("1.0", "2.0", epsilon=1e-6) is False

    def test_relative_tolerance(self):
        assert compare_float("1000000.5", "1000001.0", epsilon=1e-6) is True

    def test_nan_both(self):
        assert compare_float("nan", "nan") is True

    def test_nan_one_side(self):
        assert compare_float("nan", "1.0") is False

    def test_inf_match(self):
        assert compare_float("inf", "inf") is True

    def test_inf_mismatch(self):
        assert compare_float("inf", "-inf") is False

    def test_inf_vs_number(self):
        assert compare_float("inf", "1.0") is False

    def test_mixed_tokens(self):
        assert compare_float("hello 3.14", "hello 3.14") is True

    def test_mixed_tokens_string_mismatch(self):
        assert compare_float("hello 3.14", "world 3.14") is False

    def test_token_count_mismatch(self):
        assert compare_float("1 2", "1 2 3") is False

    def test_empty_both(self):
        assert compare_float("", "") is True

    def test_empty_vs_nonempty(self):
        assert compare_float("", "1.0") is False

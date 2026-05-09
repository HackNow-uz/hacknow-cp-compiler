import pytest
from app.sandbox import NsjailRunner

runner = NsjailRunner.__new__(NsjailRunner)


class TestGoValidation:
    def test_embed_blocked(self):
        assert runner._validate_source("go", '//go:embed hello.txt\nvar f string') is not None

    def test_normal_go_allowed(self):
        assert runner._validate_source("go", 'package main\nfunc main(){}') is None


class TestCValidation:
    @pytest.mark.parametrize("lang", ["c", "cpp", "cpp11", "cpp14", "cpp17", "cpp20", "cpp23"])
    def test_absolute_include_blocked(self, lang):
        assert runner._validate_source(lang, '#include "/etc/passwd"') is not None

    @pytest.mark.parametrize("lang", ["c", "cpp"])
    def test_traversal_include_blocked(self, lang):
        assert runner._validate_source(lang, '#include "../../etc/passwd"') is not None

    def test_normal_include_allowed(self):
        assert runner._validate_source("cpp", '#include <iostream>\n#include "header.h"') is None


class TestRustValidation:
    def test_absolute_include_bytes_blocked(self):
        assert runner._validate_source("rust", 'include_bytes!("/etc/passwd")') is not None

    def test_absolute_include_str_blocked(self):
        assert runner._validate_source("rust", 'include_str!("/etc/shadow")') is not None

    def test_traversal_include_blocked(self):
        src = 'include_str!("../../etc/passwd")'
        assert runner._validate_source("rust", src) is not None

    def test_traversal_include_bytes_blocked(self):
        src = 'include_bytes!("../secret.txt")'
        assert runner._validate_source("rust", src) is not None

    def test_bare_include_not_blocked(self):
        src = 'include!("../lib.rs")'
        assert runner._validate_source("rust", src) is None

    def test_env_macro_blocked(self):
        assert runner._validate_source("rust", 'let t = env!("INTERNAL_TOKEN");') is not None

    def test_option_env_blocked(self):
        assert runner._validate_source("rust", 'let t = option_env!("SECRET");') is not None

    def test_safe_rust_allowed(self):
        src = 'fn main() { println!("hello"); }'
        assert runner._validate_source("rust", src) is None


class TestUnrelatedLanguages:
    @pytest.mark.parametrize("lang", ["py3", "java", "js", "ruby"])
    def test_no_validation_errors(self, lang):
        assert runner._validate_source(lang, '#include "/etc/passwd"\n//go:embed x') is None

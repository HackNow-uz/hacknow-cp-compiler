import pytest
from app.sandbox import NsjailRunner

runner = NsjailRunner.__new__(NsjailRunner)


class TestParseTimeOutput:
    def test_full_resource_block(self):
        stderr = (
            "some user output\n"
            "RESOURCE_USAGE\n"
            "USER_TIME:0.42\n"
            "SYS_TIME:0.08\n"
            "MEM:12345\n"
            "EXIT:0\n"
        )
        user_stderr, cpu_sec, mem_kb = runner._parse_time_output(stderr)
        assert user_stderr == "some user output"
        assert abs(cpu_sec - 0.50) < 1e-9
        assert mem_kb == 12345

    def test_empty_input(self):
        user_stderr, cpu_sec, mem_kb = runner._parse_time_output("")
        assert user_stderr == ""
        assert cpu_sec == 0.0
        assert mem_kb == 0

    def test_no_resource_block(self):
        user_stderr, cpu_sec, mem_kb = runner._parse_time_output("just stderr\n")
        assert user_stderr == "just stderr"
        assert cpu_sec == 0.0

    def test_nsjail_log_lines_filtered(self):
        stderr = "[W][2024] warning\n[I][2024] info\nreal output\nRESOURCE_USAGE\nUSER_TIME:1.0\nSYS_TIME:0.0\nMEM:100\nEXIT:0\n"
        user_stderr, cpu_sec, mem_kb = runner._parse_time_output(stderr)
        assert "[W]" not in user_stderr
        assert "[I]" not in user_stderr
        assert "real output" in user_stderr
        assert cpu_sec == 1.0
        assert mem_kb == 100

    def test_malformed_values_handled(self):
        stderr = "RESOURCE_USAGE\nUSER_TIME:abc\nSYS_TIME:\nMEM:xyz\nEXIT:0\n"
        user_stderr, cpu_sec, mem_kb = runner._parse_time_output(stderr)
        assert cpu_sec == 0.0
        assert mem_kb == 0

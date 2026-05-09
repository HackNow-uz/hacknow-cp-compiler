import pytest
from pydantic import ValidationError
from app.schemas.requests import JudgeRequest, RunRequest, TestCase, Subtask


class TestRunRequest:
    def test_valid_minimal(self):
        r = RunRequest(language_id="cpp", source_code="int main(){}")
        assert r.time_limit_ms == 1000
        assert r.memory_limit_mb == 256

    def test_source_code_min_length(self):
        with pytest.raises(ValidationError):
            RunRequest(language_id="cpp", source_code="")

    @pytest.mark.parametrize("field,value", [
        ("time_limit_ms", 50),
        ("time_limit_ms", 50000),
        ("memory_limit_mb", 8),
        ("memory_limit_mb", 2048),
    ])
    def test_out_of_bounds(self, field, value):
        with pytest.raises(ValidationError):
            RunRequest(language_id="cpp", source_code="x", **{field: value})


class TestJudgeRequestSubtaskValidation:
    def _make_tests(self, subtask_id="s1"):
        return [TestCase(id="t1", input="1", expected_output="2", subtask=subtask_id)]

    def test_valid_subtasks(self):
        req = JudgeRequest(
            submission_id="sub1",
            problem_id="p1",
            language_id="cpp",
            source_code="int main(){}",
            tests=self._make_tests("s1"),
            subtasks=[Subtask(id="s1", max_score=100)],
        )
        assert req.stop_on_first_failure is False

    def test_missing_subtask_on_test(self):
        with pytest.raises(ValidationError, match="missing subtask_id"):
            JudgeRequest(
                submission_id="sub1",
                problem_id="p1",
                language_id="cpp",
                source_code="int main(){}",
                tests=[TestCase(id="t1", input="1", expected_output="2")],
                subtasks=[Subtask(id="s1", max_score=100)],
            )

    def test_unknown_subtask_reference(self):
        with pytest.raises(ValidationError, match="unknown subtask"):
            JudgeRequest(
                submission_id="sub1",
                problem_id="p1",
                language_id="cpp",
                source_code="int main(){}",
                tests=self._make_tests("s_nonexistent"),
                subtasks=[Subtask(id="s1", max_score=100)],
            )

    def test_no_subtasks_keeps_stop_on_first_failure(self):
        req = JudgeRequest(
            submission_id="sub1",
            problem_id="p1",
            language_id="cpp",
            source_code="int main(){}",
            tests=[TestCase(id="t1", input="1", expected_output="2")],
        )
        assert req.stop_on_first_failure is True

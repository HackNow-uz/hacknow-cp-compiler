import pytest
from app.schemas.requests import Subtask, TestCase
from app.schemas.responses import ExecutionStatus, TestResult
from app.services.judge import _aggregate_flat, _aggregate_subtasks, _toposort_subtasks


def _tc(tid, score=10, subtask=None):
    return TestCase(id=tid, input="", expected_output="", score=score, subtask=subtask)


def _tr(tid, status=ExecutionStatus.OK, score=10, subtask=None):
    return TestResult(test_id=tid, status=status, score=score, subtask=subtask)


class TestAggregateFlat:
    def test_all_ok(self):
        tests = [_tc("t1", 10), _tc("t2", 20)]
        results = [_tr("t1", score=10), _tr("t2", score=20)]
        status, total, max_s = _aggregate_flat(tests, results)
        assert status == ExecutionStatus.OK
        assert total == 30
        assert max_s == 30

    def test_first_failure_reported(self):
        tests = [_tc("t1"), _tc("t2")]
        results = [
            _tr("t1", ExecutionStatus.OK, 10),
            _tr("t2", ExecutionStatus.WA, 0),
        ]
        status, total, _ = _aggregate_flat(tests, results)
        assert status == ExecutionStatus.WA
        assert total == 10

    def test_empty_results(self):
        tests = [_tc("t1")]
        status, total, max_s = _aggregate_flat(tests, [])
        assert status == ExecutionStatus.OK
        assert total == 0


class TestAggregateSubtasks:
    def test_min_mode_all_pass(self):
        subtasks = [Subtask(id="s1", max_score=100, score_mode="min")]
        results = [_tr("t1", subtask="s1"), _tr("t2", subtask="s1")]
        status, total, max_s, subs = _aggregate_subtasks(subtasks, results)
        assert status == ExecutionStatus.OK
        assert total == 100

    def test_min_mode_one_fails(self):
        subtasks = [Subtask(id="s1", max_score=100, score_mode="min")]
        results = [
            _tr("t1", subtask="s1"),
            _tr("t2", ExecutionStatus.WA, 0, subtask="s1"),
        ]
        _, total, _, subs = _aggregate_subtasks(subtasks, results)
        assert total == 0
        assert subs[0].score == 0

    def test_sum_mode(self):
        subtasks = [Subtask(id="s1", max_score=100, score_mode="sum")]
        results = [
            _tr("t1", score=30, subtask="s1"),
            _tr("t2", score=40, subtask="s1"),
        ]
        _, total, _, subs = _aggregate_subtasks(subtasks, results)
        assert subs[0].score == 70

    def test_sum_mode_capped(self):
        subtasks = [Subtask(id="s1", max_score=50, score_mode="sum")]
        results = [
            _tr("t1", score=30, subtask="s1"),
            _tr("t2", score=40, subtask="s1"),
        ]
        _, total, _, subs = _aggregate_subtasks(subtasks, results)
        assert subs[0].score == 50

    def test_all_or_nothing_pass(self):
        subtasks = [Subtask(id="s1", max_score=100, score_mode="all_or_nothing")]
        results = [_tr("t1", subtask="s1"), _tr("t2", subtask="s1")]
        _, total, _, subs = _aggregate_subtasks(subtasks, results)
        assert total == 100

    def test_all_or_nothing_fail(self):
        subtasks = [Subtask(id="s1", max_score=100, score_mode="all_or_nothing")]
        results = [
            _tr("t1", subtask="s1"),
            _tr("t2", ExecutionStatus.TLE, 0, subtask="s1"),
        ]
        _, total, _, subs = _aggregate_subtasks(subtasks, results)
        assert total == 0

    def test_dependency_skip(self):
        subtasks = [
            Subtask(id="s1", max_score=50, score_mode="min"),
            Subtask(id="s2", max_score=50, score_mode="min", depends_on=["s1"]),
        ]
        results = [
            _tr("t1", ExecutionStatus.WA, 0, subtask="s1"),
            _tr("t2", subtask="s2"),
        ]
        _, total, _, subs = _aggregate_subtasks(subtasks, results)
        assert subs[1].skipped is True
        assert subs[1].score == 0


class TestToposortSubtasks:
    def test_no_deps(self):
        subtasks = [Subtask(id="a", max_score=10), Subtask(id="b", max_score=10)]
        order = _toposort_subtasks(subtasks)
        assert set(order) == {"a", "b"}

    def test_linear_chain(self):
        subtasks = [
            Subtask(id="a", max_score=10),
            Subtask(id="b", max_score=10, depends_on=["a"]),
            Subtask(id="c", max_score=10, depends_on=["b"]),
        ]
        order = _toposort_subtasks(subtasks)
        assert order.index("a") < order.index("b") < order.index("c")

    def test_cycle_falls_back_to_original_order(self):
        subtasks = [
            Subtask(id="a", max_score=10, depends_on=["b"]),
            Subtask(id="b", max_score=10, depends_on=["a"]),
        ]
        order = _toposort_subtasks(subtasks)
        assert order == ["a", "b"]

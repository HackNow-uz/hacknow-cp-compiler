"""Compile-cache reference counting.

This is where three defects lived, all of the same shape: a reference taken
by ``get()``/``put()`` and never given back, so ``ref_count`` never returned
to 0 and the cache directory was never reclaimed from a 512 MB tmpfs.

  * the checker's and the interactor's refs were never released at all;
  * ``release_compiled()`` was called with the alias (``cpp17``/``py``) while
    the cache stores under the canonical id (``cpp``/``py3``), so ``release()``
    decremented nothing;
  * ``compile_once()`` abandoned a ref when the cache dir had vanished or the
    hardlink step failed.

The invariant these tests pin down: **a directory is only ever removed while
its ref_count is 0**, and every ref that is taken can be given back.
"""
import os
import time

import pytest

from app.sandbox.cache import _CompileCache


def _dir(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    (d / "solution").write_text("binary")
    return str(d)


class TestRefCountLifecycle:
    def test_put_takes_one_ref(self, tmp_path):
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        entry = c.put("cpp", "src", _dir(tmp_path, "a"), "", 10)
        assert entry.ref_count == 1

    def test_get_takes_another_ref(self, tmp_path):
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        c.put("cpp", "src", _dir(tmp_path, "a"), "", 10)
        got = c.get("cpp", "src")
        assert got is not None
        assert got.ref_count == 2

    def test_release_gives_a_ref_back(self, tmp_path):
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        c.put("cpp", "src", _dir(tmp_path, "a"), "", 10)
        c.get("cpp", "src")
        c.release("cpp", "src")
        assert c._entries["cpp:%s" % _hash("src")].ref_count == 1

    def test_release_never_goes_negative(self, tmp_path):
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        c.put("cpp", "src", _dir(tmp_path, "a"), "", 10)
        for _ in range(10):
            c.release("cpp", "src")
        assert c._entries["cpp:%s" % _hash("src")].ref_count == 0

    def test_release_of_unknown_key_is_a_noop(self):
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        c.release("cpp", "never-cached")  # must not raise

    def test_alias_and_canonical_id_are_different_keys(self, tmp_path):
        """The bug: cached under `cpp`, released under `cpp17` -> nothing freed.

        The cache is keyed on the id it is given, so the *caller* must
        normalise. This test documents that the cache will not do it for you.
        """
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        c.put("cpp", "src", _dir(tmp_path, "a"), "", 10)
        c.release("cpp17", "src")           # the historical mistake
        assert c._entries["cpp:%s" % _hash("src")].ref_count == 1, (
            "releasing under an alias must not be mistaken for a real release"
        )
        c.release("cpp", "src")             # the correct call
        assert c._entries["cpp:%s" % _hash("src")].ref_count == 0


class TestReclamation:
    def test_expired_entry_with_no_refs_is_removed_from_disk(self, tmp_path):
        c = _CompileCache(max_entries=8, ttl_seconds=0)
        d = _dir(tmp_path, "a")
        c.put("cpp", "src", d, "", 10)
        c.release("cpp", "src")             # ref_count -> 0
        time.sleep(0.01)
        assert c.get("cpp", "src") is None  # expired
        assert not os.path.exists(d)

    def test_expired_entry_still_referenced_is_kept_on_disk(self, tmp_path):
        """A live judge still holds this dir — expiry must not delete under it."""
        c = _CompileCache(max_entries=8, ttl_seconds=0)
        d = _dir(tmp_path, "a")
        c.put("cpp", "src", d, "", 10)      # ref_count = 1, never released
        time.sleep(0.01)
        assert c.get("cpp", "src") is None  # expired and dropped from the map
        assert os.path.exists(d), "removed a directory that was still referenced"

    def test_eviction_removes_only_unreferenced_dirs(self, tmp_path):
        c = _CompileCache(max_entries=1, ttl_seconds=600)
        d1 = _dir(tmp_path, "a")
        d2 = _dir(tmp_path, "b")
        c.put("cpp", "src1", d1, "", 10)
        c.release("cpp", "src1")            # unreferenced -> evictable
        c.put("cpp", "src2", d2, "", 10)    # forces eviction of src1
        assert not os.path.exists(d1)
        assert os.path.exists(d2)

    def test_eviction_keeps_a_referenced_dir(self, tmp_path):
        c = _CompileCache(max_entries=1, ttl_seconds=600)
        d1 = _dir(tmp_path, "a")
        d2 = _dir(tmp_path, "b")
        c.put("cpp", "src1", d1, "", 10)    # ref_count = 1, in use
        c.put("cpp", "src2", d2, "", 10)    # evicts src1 from the map
        assert os.path.exists(d1), "evicted a directory that was still in use"

    def test_replacing_a_key_frees_the_old_unreferenced_dir(self, tmp_path):
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        d1 = _dir(tmp_path, "a")
        d2 = _dir(tmp_path, "b")
        c.put("cpp", "src", d1, "", 10)
        c.release("cpp", "src")
        c.put("cpp", "src", d2, "", 10)
        assert not os.path.exists(d1)
        assert os.path.exists(d2)


class TestDisabledCache:
    def test_max_entries_zero_stores_nothing(self, tmp_path):
        c = _CompileCache(max_entries=0, ttl_seconds=600)
        entry = c.put("cpp", "src", _dir(tmp_path, "a"), "", 10)
        assert entry.ref_count == 1
        assert c.get("cpp", "src") is None
        assert c._entries == {}

    def test_release_is_a_noop_when_disabled(self, tmp_path):
        c = _CompileCache(max_entries=0, ttl_seconds=600)
        c.put("cpp", "src", _dir(tmp_path, "a"), "", 10)
        c.release("cpp", "src")  # must not raise


class TestStats:
    def test_hit_and_miss_counters(self, tmp_path):
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        c.get("cpp", "absent")               # miss
        c.put("cpp", "src", _dir(tmp_path, "a"), "", 10)
        c.get("cpp", "src")                  # hit
        s = c.stats
        assert s["hits"] == 1
        assert s["misses"] == 1
        assert s["size"] == 1
        assert s["hit_rate"] == 0.5

    def test_hit_rate_is_zero_with_no_traffic(self):
        assert _CompileCache(max_entries=8, ttl_seconds=600).stats["hit_rate"] == 0.0

    def test_distinct_sources_do_not_share_an_entry(self, tmp_path):
        c = _CompileCache(max_entries=8, ttl_seconds=600)
        c.put("cpp", "src1", _dir(tmp_path, "a"), "", 10)
        assert c.get("cpp", "src2") is None
        assert c.stats["size"] == 1


def _hash(source: str) -> str:
    import hashlib
    return hashlib.sha256(source.encode()).hexdigest()

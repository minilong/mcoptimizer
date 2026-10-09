"""Cache tests."""

import time

from mcoptimizer.cache import Cache


def test_roundtrip(tmp_path):
    c = Cache(tmp_path)
    c.put("query-meals", {"storeCode": "S1"}, {"items": [1, 2, 3]})
    assert c.get("query-meals", {"storeCode": "S1"}) == {"items": [1, 2, 3]}


def test_args_canonicalization(tmp_path):
    c = Cache(tmp_path)
    c.put("query-meals", {"b": 2, "a": 1}, "data")
    assert c.get("query-meals", {"a": 1, "b": 2}) == "data"


def test_miss(tmp_path):
    c = Cache(tmp_path)
    assert c.get("query-meals", {"storeCode": "X"}) is None


def test_ttl_expiry(tmp_path, monkeypatch):
    c = Cache(tmp_path)
    c.put("query-meals", {}, "data")  # ttl = 3600
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 7200)
    assert c.get("query-meals", {}) is None
    assert c.get_stale("query-meals", {}) == "data"


def test_disabled(tmp_path):
    c = Cache(tmp_path, enabled=False)
    c.put("query-meals", {}, "data")
    assert c.get("query-meals", {}) is None

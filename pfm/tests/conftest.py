"""
Shared test fixtures.

- FastAPI test client with async httpx
- Mock auth delegate auto-wired
- DI overrides applied
"""

import fnmatch

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.mock import MockAuthDelegate
from app.core.analytics import AnalyticsService, ConsoleAnalyticsDelegate
from app.db.redis import redis_client
from app.dependencies import _get_auth_delegate
from app.main import create_app


class FakeRedisPipeline:
    def __init__(self, redis):
        self._redis = redis
        self._operations = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._operations.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zadd(self, key, mapping):
        self._operations.append(("zadd", key, mapping))
        return self

    def zcard(self, key):
        self._operations.append(("zcard", key))
        return self

    def expire(self, key, ttl):
        self._operations.append(("expire", key, ttl))
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def execute(self):
        results = []
        for operation in self._operations:
            name = operation[0]
            if name == "zremrangebyscore":
                _, key, min_score, max_score = operation
                results.append(self._redis.zremrangebyscore(key, min_score, max_score))
            elif name == "zadd":
                _, key, mapping = operation
                results.append(self._redis.zadd(key, mapping))
            elif name == "zcard":
                _, key = operation
                results.append(self._redis.zcard(key))
            elif name == "expire":
                _, key, ttl = operation
                results.append(self._redis.expire(key, ttl))
        self._operations.clear()
        return results


class FakeRedis:
    def __init__(self):
        self._data = {}
        self._lists = {}
        self._sorted_sets = {}
        self._ttl = {}

    def pipeline(self):
        return FakeRedisPipeline(self)

    async def ping(self):
        return True

    async def close(self):
        return None

    async def get(self, key):
        return self._data.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self._data:
            return False
        self._data[key] = value
        if ex is not None:
            self._ttl[key] = ex
        return True

    async def delete(self, key):
        self._data.pop(key, None)
        self._lists.pop(key, None)
        self._sorted_sets.pop(key, None)

    async def scan_iter(self, match=None):
        keys = list(self._data.keys()) + list(self._lists.keys()) + list(self._sorted_sets.keys())
        for key in keys:
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    async def llen(self, key):
        return len(self._lists.get(key, []))

    def zremrangebyscore(self, key, min_score, max_score):
        bucket = self._sorted_sets.setdefault(key, [])
        original_len = len(bucket)
        self._sorted_sets[key] = [
            (member, score)
            for member, score in bucket
            if not (min_score <= score <= max_score)
        ]
        return original_len - len(self._sorted_sets[key])

    def zadd(self, key, mapping):
        bucket = self._sorted_sets.setdefault(key, [])
        for member, score in mapping.items():
            bucket.append((member, score))
        return len(mapping)

    def zcard(self, key):
        return len(self._sorted_sets.get(key, []))

    def expire(self, key, ttl):
        self._ttl[key] = ttl
        return True


@pytest.fixture
def fake_redis():
    redis = FakeRedis()
    original = redis_client._redis
    redis_client._redis = redis
    yield redis
    redis_client._redis = original


@pytest.fixture
def app(fake_redis):
    application = create_app()
    application.state.shutting_down = False
    application.state.analytics = AnalyticsService(delegates=[ConsoleAnalyticsDelegate()])
    # Override auth to use mock delegate in tests
    mock_delegate = MockAuthDelegate()
    application.dependency_overrides[_get_auth_delegate] = lambda: mock_delegate
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

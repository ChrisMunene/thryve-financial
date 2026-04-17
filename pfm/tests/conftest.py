"""
Shared test fixtures.

- FastAPI test client with async httpx
- Mock auth service auto-wired
- DI overrides applied
"""

import fnmatch
import hashlib

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.mock import MockAuthService
from app.core.analytics.analytics import AnalyticsService, ConsoleAnalyticsDelegate
from app.db.redis import RedisService
from app.db.session import get_engine
from app.dependencies import get_auth_service
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
        self._scripts = {}

    def pipeline(self):
        return FakeRedisPipeline(self)

    async def ping(self):
        return True

    async def aclose(self):
        return None

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

    async def script_load(self, script):
        digest = hashlib.sha1(script.encode("utf-8")).hexdigest()
        self._scripts[digest] = script
        return digest

    async def evalsha(self, script_hash, numkeys, *args):
        if script_hash not in self._scripts:
            raise RuntimeError("NOSCRIPT No matching script. Please use EVAL.")

        if numkeys != 1:
            raise ValueError("FakeRedis only supports one key for evalsha")

        if len(args) < 5:
            raise ValueError("FakeRedis received insufficient evalsha arguments")

        bucket = args[0]
        now = int(args[1])
        space_required = int(args[2])
        item_name = str(args[3])
        rates_count = int(args[4])
        rate_args = args[5:]

        if len(rate_args) != rates_count * 2:
            raise ValueError("FakeRedis received mismatched rate arguments")

        entries = self._sorted_sets.setdefault(bucket, [])

        for index in range(rates_count):
            interval = int(rate_args[index * 2])
            limit = int(rate_args[index * 2 + 1])
            count = sum(1 for _, score in entries if now - interval <= score <= now)
            if limit - count < space_required:
                return index

        for weight_index in range(1, space_required + 1):
            entries.append((f"{item_name}{weight_index}", now))

        return -1

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
    return FakeRedis()


@pytest.fixture
def fake_redis_service(fake_redis):
    return RedisService.with_client(fake_redis)


@pytest.fixture
def app(fake_redis_service):
    application = create_app()
    application.state.shutting_down = False
    application.state.analytics = AnalyticsService(delegates=[ConsoleAnalyticsDelegate()])
    application.state.redis = fake_redis_service
    # Override auth to use a mock service in tests.
    mock_auth_service = MockAuthService()
    application.dependency_overrides[get_auth_service] = lambda: mock_auth_service
    return application


@pytest.fixture(autouse=True)
async def cleanup_database_engine():
    yield
    await get_engine().dispose()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

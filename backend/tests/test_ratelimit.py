"""The in-process sliding-window limiter (docs/ARCHITECTURE.md §5.2)."""

from app.core.ratelimit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_then_blocks() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    for _ in range(3):
        assert limiter.hit("k", limit=3) is None
    retry_after = limiter.hit("k", limit=3)
    assert retry_after is not None and 0 < retry_after <= 60


def test_window_slides() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    assert limiter.hit("k", limit=1) is None
    assert limiter.hit("k", limit=1) == 60.0
    clock.now += 30
    assert limiter.hit("k", limit=1) == 30.0
    clock.now += 31
    assert limiter.hit("k", limit=1) is None


def test_blocked_attempts_do_not_extend_the_block() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    assert limiter.hit("k", limit=1) is None
    clock.now += 59
    assert limiter.hit("k", limit=1) is not None  # blocked, not counted
    clock.now += 2
    assert limiter.hit("k", limit=1) is None


def test_keys_are_independent() -> None:
    limiter = RateLimiter(clock=FakeClock())
    assert limiter.hit("a", limit=1) is None
    assert limiter.hit("b", limit=1) is None
    assert limiter.hit("a", limit=1) is not None


def test_reset_clears_everything() -> None:
    limiter = RateLimiter(clock=FakeClock())
    assert limiter.hit("a", limit=1) is None
    limiter.reset()
    assert limiter.hit("a", limit=1) is None


def test_stale_buckets_are_swept() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock)
    for i in range(10_001):
        limiter.hit(f"k{i}", limit=5)
    clock.now += 120
    limiter.hit("fresh", limit=5)  # crosses the threshold and sweeps the stale keys
    assert len(limiter._hits) == 1

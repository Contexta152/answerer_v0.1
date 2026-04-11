import os
import time
from collections import defaultdict, deque
from fastapi import HTTPException

RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

# tenant_id -> deque of timestamps (seconds)
_windows: dict[str, deque] = defaultdict(deque)


def check_rate_limit(tenant_id: str) -> None:
    now = time.monotonic()
    window = _windows[tenant_id]
    cutoff = now - 60.0
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limit_exceeded", "message": "Rate limit exceeded"},
        )
    window.append(now)

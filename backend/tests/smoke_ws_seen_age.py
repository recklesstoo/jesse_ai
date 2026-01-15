from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    os.environ.setdefault("PYTHONPATH", str(repo_root))

    from backend.state import _get_bot_state, compute_feed_status, state_lock
    import asyncio

    bot_id = "smoke-bot-seen"

    async def run() -> None:
        async with state_lock:
            st = _get_bot_state(bot_id)
            st.clear()
            st["connected"] = True
            st["data_source"] = "LIVE_WS"
            # last_seen is 10s old => should be STALE.
            old = datetime.now(timezone.utc) - timedelta(seconds=10)
            st["last_seen_utc"] = old.isoformat().replace("+00:00", "Z")

        computed = compute_feed_status(bot_id)
        assert computed["ws_open"] is True
        assert computed["connection_status"] == "STALE"
        assert float(computed["last_seen_age_seconds"]) >= 9.0

        async with state_lock:
            st = _get_bot_state(bot_id)
            st["connected"] = False

        computed2 = compute_feed_status(bot_id)
        assert computed2["ws_open"] is False
        assert computed2["connection_status"] == "DISCONNECTED"

    asyncio.run(run())
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


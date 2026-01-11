import uuid

import backend.app as app_module


def _bar(idx: int):
    return {
        "ts": f"2026-01-01T00:{idx:02d}:00Z",
        "symbol": "MNQ",
        "timeframe": "1 Minute",
        "o": 100 + idx * 0.1,
        "h": 101 + idx * 0.1,
        "l": 99 + idx * 0.1,
        "c": 100.5 + idx * 0.1,
        "v": 1000 + idx,
    }


def test_auto_calibration_updates_state():
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        app_module.update_bot_state(bot_id, mode="LIVE", instrument="MNQ")
        store = app_module.bars_store[bot_id]
        for i in range(500):
            store.append(_bar(i))
        app_module.update_ai_signal(bot_id)
        state = app_module.auto_cal_state.get(bot_id, {})
        assert state.get("last_calibrated") == 500
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
        app_module.bars_store.pop(bot_id, None)
        app_module.ai_signal_store.pop(bot_id, None)
        app_module.ai_signal_history.pop(bot_id, None)
        app_module.auto_cal_state.pop(bot_id, None)
        app_module.wyckoff_config_store.pop(bot_id, None)
        app_module.auto_trade_config_store.pop(bot_id, None)

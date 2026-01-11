import uuid

import backend.app as app_module


def test_instrument_default_configs():
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        app_module.update_bot_state(bot_id, instrument="MNQ")
        cfg_mnq = app_module.get_auto_trade_config(bot_id)
        wyck_mnq = app_module.get_wyckoff_config(bot_id)

        app_module.update_bot_state(bot_id, instrument="ES")
        cfg_es = app_module.get_auto_trade_config(bot_id)
        wyck_es = app_module.get_wyckoff_config(bot_id)

        app_module.update_bot_state(bot_id, instrument="GC")
        cfg_gc = app_module.get_auto_trade_config(bot_id)
        wyck_gc = app_module.get_wyckoff_config(bot_id)

        assert cfg_mnq["min_confidence"] == 0.72
        assert cfg_es["min_confidence"] == 0.65
        assert cfg_gc["min_confidence"] == 0.78

        assert wyck_mnq["break_pct"] == 0.0025
        assert wyck_es["break_pct"] == 0.0015
        assert wyck_gc["break_pct"] == 0.002
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
        app_module.bars_store.pop(bot_id, None)
        app_module.ai_signal_store.pop(bot_id, None)

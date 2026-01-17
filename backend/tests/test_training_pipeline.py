from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.database import SessionLocal
from backend.database import Base, engine
from backend.models import DataBar, ModelRun
from backend.training.pipeline import TrainConfig, train_from_db


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_training_pipeline_writes_model_run_and_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WYCKOFF_MODELS_DIR", str(tmp_path))
    Base.metadata.create_all(bind=engine)

    bot_id = "test-bot"
    symbol = "ZZZ"
    timeframe = "1m"

    db = SessionLocal()
    try:
        # Clean any previous leftovers.
        db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe).delete(synchronize_session=False)
        db.query(ModelRun).filter(ModelRun.bot_id == bot_id, ModelRun.symbol == symbol, ModelRun.timeframe == timeframe).delete(synchronize_session=False)
        db.commit()

        # Insert deterministic bars: 10,050 rows (guardrail requires >=10k).
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        rows = []
        price = 100.0
        for i in range(10_050):
            ts = start + timedelta(minutes=i)
            # Deterministic oscillation so labels contain both classes.
            price += 0.2 if (i % 4) < 2 else -0.2
            rows.append(
                DataBar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts_utc=ts,
                    open=price - 0.05,
                    high=price + 0.10,
                    low=price - 0.10,
                    close=price,
                    volume=100 + (i % 10),
                    source="IMPORT",
                    is_simulated=False,
                )
            )
        db.bulk_save_objects(rows)
        db.commit()

        cfg = TrainConfig(lookback_days=3650, horizon_bars=10, min_real_bars=10_000, random_state=42)
        st = train_from_db(db=db, bot_id=bot_id, symbol=symbol, timeframe=timeframe, config=cfg)
        assert st.status == "DONE", st.message
        assert st.artifact_path

        artifact_dir = Path(st.artifact_path)
        assert (artifact_dir / "model.pkl").exists()
        assert (artifact_dir / "feature_schema.json").exists()
        assert (artifact_dir / "metrics.json").exists()
        assert (artifact_dir / "train_config.json").exists()

        run = db.query(ModelRun).filter(ModelRun.id == st.run_id).first()
        assert run is not None
        assert run.status == "DONE"
        assert run.artifact_path == st.artifact_path
    finally:
        # Cleanup DB rows (artifacts stay in tmp_path).
        try:
            db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe).delete(synchronize_session=False)
            db.query(ModelRun).filter(ModelRun.bot_id == bot_id, ModelRun.symbol == symbol, ModelRun.timeframe == timeframe).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

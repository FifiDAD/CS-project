"""Smoke tests for train_eta_model.py — ensure the trainer runs end-to-end."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def isolated_models_dir(tmp_path, monkeypatch):
    """Run the trainer with a temp models/ dir to avoid clobbering production artifacts.

    Done by importing train_eta_model and rebinding the module-level paths.
    """
    import train_eta_model as t
    # Store generated model files in the test temp directory.
    monkeypatch.setattr(t, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(t, "ARTIFACT_PATH", tmp_path / "models" / "eta_xgb.joblib")
    monkeypatch.setattr(t, "META_PATH", tmp_path / "models" / "eta_meta.json")
    monkeypatch.setattr(t, "IMPORTANCE_PNG", tmp_path / "models" / "eta_feature_importance.png")
    return tmp_path / "models"


def test_trainer_seed_run_produces_artifacts(isolated_models_dir, monkeypatch):
    """Running the trainer with --seed must write the joblib + meta + importance png."""
    import train_eta_model as t

    # Drive main() programmatically with --no-cv to keep the smoke test fast.
    monkeypatch.setattr(sys, "argv", ["train_eta_model.py", "--seed", "--no-cv"])
    t.main()

    assert (isolated_models_dir / "eta_xgb.joblib").exists()
    assert (isolated_models_dir / "eta_meta.json").exists()

    meta = json.loads((isolated_models_dir / "eta_meta.json").read_text())
    assert "n_train" in meta
    assert meta["n_train"] > 0
    assert meta["mae_minutes"] >= 0
    assert "feature_names" in meta
    assert "per_chokepoint_mae" in meta


def test_trainer_refuses_below_threshold(tmp_path, monkeypatch):
    """Trainer must exit nonzero when there's not enough data and --seed not supplied."""
    import train_eta_model as t

    # Use an empty database path so the trainer cannot meet the data threshold.
    monkeypatch.setattr(t, "DEFAULT_DB", tmp_path / "missing.db")
    monkeypatch.setattr(t, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(t, "ARTIFACT_PATH", tmp_path / "models" / "eta_xgb.joblib")
    monkeypatch.setattr(t, "META_PATH", tmp_path / "models" / "eta_meta.json")
    monkeypatch.setattr(t, "IMPORTANCE_PNG", tmp_path / "models" / "eta_feature_importance.png")
    monkeypatch.setattr(sys, "argv", ["train_eta_model.py"])

    with pytest.raises(SystemExit) as exc:
        t.main()
    assert exc.value.code == 1

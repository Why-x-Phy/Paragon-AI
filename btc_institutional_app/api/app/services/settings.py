from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateThresholds:
    min_sample: int
    min_profit_factor: float
    max_drawdown_pct: float
    min_winrate: float


@dataclass(frozen=True)
class AppSettings:
    execution_enabled: bool
    write_token: str
    gate: GateThresholds


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def read_secret_value(key: str, default: str = "") -> str:
    raw = os.getenv(key)
    if raw is not None and raw != "":
        return raw

    secret_file = os.getenv(f"{key}_FILE", "").strip()
    if not secret_file:
        return default

    try:
        value = Path(secret_file).read_text(encoding="utf-8").strip()
        return value if value != "" else default
    except OSError:
        return default


def load_settings() -> AppSettings:
    return AppSettings(
        execution_enabled=_as_bool(os.getenv("EXECUTION_ENABLED", "false"), default=False),
        write_token=read_secret_value("API_WRITE_TOKEN", ""),
        gate=GateThresholds(
            min_sample=int(os.getenv("GATE_MIN_SAMPLE", "30")),
            min_profit_factor=float(os.getenv("GATE_MIN_PROFIT_FACTOR", "1.2")),
            max_drawdown_pct=float(os.getenv("GATE_MAX_DRAWDOWN_PCT", "6.0")),
            min_winrate=float(os.getenv("GATE_MIN_WINRATE", "0.45")),
        ),
    )


SETTINGS = load_settings()

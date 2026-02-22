from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./btc_app.db")


def build_engine() -> Engine:
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    return create_engine(DATABASE_URL, future=True, connect_args=connect_args)


engine = build_engine()


@contextmanager
def session_scope():
    with engine.begin() as conn:
        yield conn


def init_db() -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT NOT NULL,
            timeframe_set TEXT NOT NULL,
            regime TEXT NOT NULL,
            regime_confidence NUMERIC(5,4) NOT NULL,
            data_degraded BOOLEAN NOT NULL DEFAULT FALSE,
            feature_version TEXT NOT NULL,
            model_version TEXT NOT NULL
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS raw_snapshots (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            source TEXT NOT NULL,
            symbol TEXT NOT NULL,
            payload TEXT NOT NULL,
            data_degraded BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS features (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            case_id INTEGER NOT NULL,
            feature_key TEXT NOT NULL,
            feature_value TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            case_id INTEGER NOT NULL,
            scenario_name TEXT NOT NULL,
            bias TEXT NOT NULL,
            probability NUMERIC(6,5) NOT NULL,
            trigger_text TEXT NOT NULL,
            invalidation_text TEXT NOT NULL,
            targets TEXT NOT NULL,
            risk_notes TEXT NOT NULL,
            reason_codes TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            case_id INTEGER NOT NULL,
            total_score INTEGER NOT NULL,
            bull_prob NUMERIC(6,5) NOT NULL,
            bear_prob NUMERIC(6,5) NOT NULL,
            subscores TEXT NOT NULL,
            penalties TEXT NOT NULL,
            reason_codes TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            case_id INTEGER NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            acknowledged BOOLEAN NOT NULL DEFAULT FALSE
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS outcomes (
            id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            case_id INTEGER NOT NULL,
            chosen_scenario TEXT NOT NULL,
            horizon TEXT NOT NULL,
            pnl_pct NUMERIC(8,4) NOT NULL,
            mfe_pct NUMERIC(8,4) NOT NULL,
            mae_pct NUMERIC(8,4) NOT NULL,
            outcome_label TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]

    sqlite_statements = [
        stmt.replace("INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        for stmt in statements
    ]

    selected = sqlite_statements if DATABASE_URL.startswith("sqlite") else statements
    with session_scope() as conn:
        for stmt in selected:
            conn.execute(text(stmt))

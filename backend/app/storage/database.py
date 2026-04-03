"""SQLite-backed storage service for runs, strategies, and parameter presets."""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


class StorageService:
    """Persistent storage backed by a single SQLite database file."""

    def __init__(self, db_path: str = "storage/app.db") -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create all required tables if they do not already exist."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    config TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    metrics TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_artifacts (
                    run_id TEXT PRIMARY KEY,
                    trace TEXT,
                    fills TEXT,
                    pnl_history TEXT,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS strategies (
                    strategy_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'custom',
                    description TEXT NOT NULL DEFAULT '',
                    source_code TEXT NOT NULL DEFAULT '',
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    parameters TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS parameter_presets (
                    preset_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    params TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def save_run(self, run) -> str:
        """Persist a BacktestRun and return its run_id."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                    (run_id, config, status, started_at, completed_at, metrics, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    json.dumps(run.config.model_dump() if hasattr(run.config, "model_dump") else run.config),
                    run.status,
                    run.started_at,
                    run.completed_at,
                    json.dumps(run.metrics) if run.metrics else None,
                    run.error,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            return run.run_id
        finally:
            conn.close()

    def get_run(self, run_id: str) -> Optional[dict]:
        """Retrieve a single run by its ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_run_dict(row)
        finally:
            conn.close()

    def list_runs(self) -> list[dict]:
        """Return all runs ordered by creation time descending."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC"
            ).fetchall()
            return [self._row_to_run_dict(r) for r in rows]
        finally:
            conn.close()

    def delete_run(self, run_id: str) -> None:
        """Delete a run and its artifacts."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM run_artifacts WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            conn.commit()
        finally:
            conn.close()

    def save_run_artifacts(self, run_id: str, artifacts: dict) -> None:
        """Save trace, fills, and pnl_history as JSON blobs for a run."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO run_artifacts (run_id, trace, fills, pnl_history)
                VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    json.dumps(artifacts.get("trace")),
                    json.dumps(artifacts.get("fills")),
                    json.dumps(artifacts.get("pnl_history")),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_run_artifacts(self, run_id: str) -> Optional[dict]:
        """Retrieve artifacts for a run."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM run_artifacts WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return {
                "run_id": row["run_id"],
                "trace": json.loads(row["trace"]) if row["trace"] else [],
                "fills": json.loads(row["fills"]) if row["fills"] else [],
                "pnl_history": json.loads(row["pnl_history"]) if row["pnl_history"] else [],
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def save_strategy(self, strategy_def: dict) -> str:
        """Persist a strategy definition and return its strategy_id."""
        strategy_id = strategy_def.get("strategy_id", str(uuid.uuid4()))
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO strategies
                    (strategy_id, name, category, description, source_code,
                     is_builtin, parameters, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_id,
                    strategy_def.get("name", "Untitled"),
                    strategy_def.get("category", "custom"),
                    strategy_def.get("description", ""),
                    strategy_def.get("source_code", ""),
                    1 if strategy_def.get("is_builtin", False) else 0,
                    json.dumps(strategy_def.get("parameters", [])),
                    strategy_def.get("created_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
            conn.commit()
            return strategy_id
        finally:
            conn.close()

    def get_strategy(self, strategy_id: str) -> Optional[dict]:
        """Retrieve a single strategy by ID."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM strategies WHERE strategy_id = ?", (strategy_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_strategy_dict(row)
        finally:
            conn.close()

    def list_strategies(self) -> list[dict]:
        """Return all persisted strategies."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM strategies ORDER BY created_at DESC"
            ).fetchall()
            return [self._row_to_strategy_dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Parameter presets
    # ------------------------------------------------------------------

    def save_preset(self, strategy_id: str, name: str, params: dict) -> str:
        """Save a named parameter preset for a strategy."""
        preset_id = str(uuid.uuid4())
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO parameter_presets
                    (preset_id, strategy_id, name, params, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    preset_id,
                    strategy_id,
                    name,
                    json.dumps(params),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            return preset_id
        finally:
            conn.close()

    def get_presets(self, strategy_id: str) -> list[dict]:
        """Return all parameter presets for a given strategy."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM parameter_presets WHERE strategy_id = ? ORDER BY created_at DESC",
                (strategy_id,),
            ).fetchall()
            return [
                {
                    "preset_id": r["preset_id"],
                    "strategy_id": r["strategy_id"],
                    "name": r["name"],
                    "params": json.loads(r["params"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _row_to_run_dict(row) -> dict:
        return {
            "run_id": row["run_id"],
            "config": json.loads(row["config"]),
            "status": row["status"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "metrics": json.loads(row["metrics"]) if row["metrics"] else None,
            "error": row["error"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _row_to_strategy_dict(row) -> dict:
        return {
            "strategy_id": row["strategy_id"],
            "name": row["name"],
            "category": row["category"],
            "description": row["description"],
            "source_code": row["source_code"],
            "is_builtin": bool(row["is_builtin"]),
            "parameters": json.loads(row["parameters"]),
            "created_at": row["created_at"],
        }

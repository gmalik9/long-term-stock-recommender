"""SQLite audit log for every MCP tool invocation (read or write)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
from typing import Any

_LOCK = threading.Lock()


def _db_path() -> str:
    p = os.environ.get("STOCK_REC_AUDIT_DB")
    if p:
        d = os.path.dirname(p) or "."
        os.makedirs(d, exist_ok=True)
        return p
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "trades.sqlite")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), timeout=20, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init() -> None:
    with _LOCK, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts TEXT NOT NULL,
          caller TEXT NOT NULL,
          tool TEXT NOT NULL,
          args_json TEXT NOT NULL,
          result_status TEXT NOT NULL,
          result_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
        """)


def record(caller: str, tool: str, args: dict | None,
           status: str, result: Any) -> None:
    init()
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT INTO audit (ts, caller, tool, args_json, result_status, result_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                dt.datetime.now(dt.timezone.utc).isoformat(),
                caller, tool,
                json.dumps(args or {}, default=str),
                status,
                json.dumps(result, default=str)[:8000],  # cap blob size
            ),
        )


def recent(limit: int = 200) -> list[dict]:
    init()
    with _LOCK, _conn() as c:
        rows = c.execute(
            "SELECT id, ts, caller, tool, args_json, result_status, result_json "
            "FROM audit ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    cols = ["id", "ts", "caller", "tool", "args_json", "result_status", "result_json"]
    return [dict(zip(cols, r)) for r in rows]

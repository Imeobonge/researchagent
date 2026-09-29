from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests

from core.config import secret


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "research.db"


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    if _supabase_enabled():
        return
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS researches (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                created_at TEXT NOT NULL,
                date_mode TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT,
                requested_sources INTEGER NOT NULL,
                analyzed_sources INTEGER NOT NULL,
                sections_json TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                report_markdown TEXT NOT NULL,
                synthesis_mode TEXT NOT NULL,
                elapsed_seconds REAL NOT NULL
            )
            """
        )


def save_research(payload: dict[str, Any]) -> str:
    research_id = str(uuid.uuid4())
    if _supabase_enabled():
        _supabase_request("POST", json=_cloud_row(research_id, payload))
        return research_id
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO researches (
                id, topic, created_at, date_mode, start_date, end_date,
                requested_sources, analyzed_sources, sections_json,
                sources_json, report_markdown, synthesis_mode, elapsed_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                research_id,
                payload["topic"],
                datetime.now(timezone.utc).isoformat(),
                payload["date_mode"],
                payload.get("start_date"),
                payload.get("end_date"),
                payload["requested_sources"],
                payload["analyzed_sources"],
                json.dumps(payload["sections"]),
                json.dumps(payload["sources"]),
                payload["report_markdown"],
                payload["synthesis_mode"],
                payload["elapsed_seconds"],
            ),
        )
    return research_id


def list_researches(search: str = "") -> list[dict[str, Any]]:
    if _supabase_enabled():
        rows = _supabase_request(
            "GET", params={"select": "*", "order": "created_at.desc"}
        )
        decoded = [_decode_cloud(row) for row in rows]
        token = search.strip().lower()
        if token:
            decoded = [
                row for row in decoded
                if token in row["topic"].lower() or token in row["report_markdown"].lower()
            ]
        return decoded
    query = "SELECT * FROM researches"
    params: tuple[Any, ...] = ()
    if search.strip():
        query += " WHERE topic LIKE ? OR report_markdown LIKE ?"
        token = f"%{search.strip()}%"
        params = (token, token)
    query += " ORDER BY created_at DESC"
    with connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_decode(dict(row)) for row in rows]


def get_research(research_id: str) -> dict[str, Any] | None:
    if _supabase_enabled():
        rows = _supabase_request(
            "GET", params={"select": "*", "id": f"eq.{research_id}", "limit": "1"}
        )
        return _decode_cloud(rows[0]) if rows else None
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM researches WHERE id = ?", (research_id,)
        ).fetchone()
    return _decode(dict(row)) if row else None


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    row["sections"] = json.loads(row.pop("sections_json"))
    row["sources"] = json.loads(row.pop("sources_json"))
    return row


def storage_backend() -> str:
    return "Supabase" if _supabase_enabled() else "SQLite"


def _supabase_enabled() -> bool:
    return bool(secret("SUPABASE_URL") and secret("SUPABASE_SECRET_KEY"))


def _supabase_request(method: str, *, params: dict | None = None, json: dict | None = None) -> Any:
    key = secret("SUPABASE_SECRET_KEY")
    headers = {
        "apikey": key,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    response = requests.request(
        method,
        f'{secret("SUPABASE_URL").rstrip("/")}/rest/v1/researches',
        headers=headers,
        params=params,
        json=json,
        timeout=20,
    )
    response.raise_for_status()
    if not response.content:
        return []
    return response.json()


def _cloud_row(research_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": research_id,
        "topic": payload["topic"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "date_mode": payload["date_mode"],
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "requested_sources": payload["requested_sources"],
        "analyzed_sources": payload["analyzed_sources"],
        "sections": payload["sections"],
        "sources": payload["sources"],
        "report_markdown": payload["report_markdown"],
        "synthesis_mode": payload["synthesis_mode"],
        "elapsed_seconds": payload["elapsed_seconds"],
    }


def _decode_cloud(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    decoded["sections"] = decoded.get("sections") or []
    decoded["sources"] = decoded.get("sources") or []
    return decoded

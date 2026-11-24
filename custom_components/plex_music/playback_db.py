"""SQLite-backed recovery of Plex Music playback queues.

Only catalogue metadata and playback positions are stored, never Plex credentials
or public stream tokens. Access happens in the Home Assistant executor.
"""
from __future__ import annotations

import json
import sqlite3
import time


def initialise(path: str) -> None:
    with sqlite3.connect(path, timeout=10) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS playback (
            entry_id TEXT NOT NULL,
            device_key TEXT NOT NULL,
            queue_json TEXT NOT NULL,
            position INTEGER NOT NULL,
            offset_ms INTEGER NOT NULL,
            paused INTEGER NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (entry_id, device_key)
        )""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(playback)")}
        if "queue_id" not in columns:
            db.execute("ALTER TABLE playback ADD COLUMN queue_id TEXT")
        db.execute("""CREATE TABLE IF NOT EXISTS listening_history (
            entry_id TEXT NOT NULL,
            track_key TEXT NOT NULL,
            played_at REAL NOT NULL,
            PRIMARY KEY (entry_id, track_key)
        )""")


def read_entry(path: str, entry_id: str) -> list[dict]:
    with sqlite3.connect(path, timeout=10) as db:
        rows = db.execute(
            "SELECT device_key, queue_json, position, offset_ms, paused, queue_id "
            "FROM playback WHERE entry_id = ?", (entry_id,)
        ).fetchall()
    results = []
    for key, queue_json, position, offset, paused, queue_id in rows:
        try:
            tracks = json.loads(queue_json)
            if isinstance(tracks, list) and tracks:
                results.append({
                    "device_key": key, "queue_id": queue_id, "tracks": tracks, "index": position,
                    "offset": offset, "paused": bool(paused),
                })
        except (TypeError, ValueError):
            continue
    return results


def write_entry(path: str, entry_id: str, states: list[dict]) -> None:
    with sqlite3.connect(path, timeout=10) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM playback WHERE entry_id = ?", (entry_id,))
        db.executemany(
            "INSERT INTO playback "
            "(entry_id, device_key, queue_json, position, offset_ms, paused, updated_at, queue_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (entry_id, row["device_key"], json.dumps(row["tracks"]),
                 row["index"], row["offset"], int(row["paused"]), time.time(), row.get("queue_id"))
                for row in states
            ],
        )


def read_history(path: str, entry_id: str, limit: int = 100) -> list[str]:
    """Most recently started distinct Plex tracks, newest first."""
    with sqlite3.connect(path, timeout=10) as db:
        return [row[0] for row in db.execute(
            "SELECT track_key FROM listening_history WHERE entry_id = ? "
            "ORDER BY played_at DESC LIMIT ?", (entry_id, limit)
        )]


def record_played(path: str, entry_id: str, track_key: str) -> None:
    """Keep a bounded, cross-device history of tracks actually started."""
    with sqlite3.connect(path, timeout=10) as db:
        db.execute(
            "INSERT INTO listening_history(entry_id, track_key, played_at) "
            "VALUES (?, ?, ?) ON CONFLICT(entry_id, track_key) "
            "DO UPDATE SET played_at = excluded.played_at",
            (entry_id, track_key, time.time()),
        )
        db.execute(
            "DELETE FROM listening_history WHERE entry_id = ? AND track_key NOT IN "
            "(SELECT track_key FROM listening_history WHERE entry_id = ? "
            "ORDER BY played_at DESC LIMIT 100)", (entry_id, entry_id)
        )

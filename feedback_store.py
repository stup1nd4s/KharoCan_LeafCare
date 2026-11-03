"""SQLite persistence for reviewed LeafCare images and YOLO annotations."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DATABASE_PATH = Path(
    os.getenv(
        "LEAFCARE_DATABASE_PATH",
        str(Path(__file__).resolve().parent / "data" / "feedback.sqlite3"),
    )
)


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reviewed_samples (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL CHECK (source IN ('camera', 'gallery')),
                decision TEXT NOT NULL CHECK (
                    decision IN ('correct', 'edited', 'no_lesions')
                ),
                image_jpeg BLOB NOT NULL,
                detections_json TEXT NOT NULL,
                annotations_json TEXT NOT NULL,
                exported_at TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS reviewed_samples_created_at "
            "ON reviewed_samples(created_at)"
        )


def save_reviewed_sample(
    *,
    source: str,
    decision: str,
    image_jpeg: bytes,
    detections: list[dict[str, Any]],
    annotations: list[dict[str, float]],
) -> str:
    initialize_database()
    sample_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO reviewed_samples (
                id, created_at, source, decision, image_jpeg,
                detections_json, annotations_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sample_id,
                created_at,
                source,
                decision,
                sqlite3.Binary(image_jpeg),
                json.dumps(detections, separators=(",", ":"), allow_nan=False),
                json.dumps(annotations, separators=(",", ":"), allow_nan=False),
            ),
        )
    return sample_id


def get_review_stats() -> dict[str, int]:
    initialize_database()
    with _connect() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM reviewed_samples"
        ).fetchone()[0]
        decisions = connection.execute(
            "SELECT decision, COUNT(*) AS count "
            "FROM reviewed_samples GROUP BY decision"
        ).fetchall()
    result = {"total": int(total), "correct": 0, "edited": 0, "no_lesions": 0}
    result.update({row["decision"]: int(row["count"]) for row in decisions})
    return result


def get_reviewed_samples() -> list[dict[str, Any]]:
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, source, decision, image_jpeg,
                   detections_json, annotations_json
            FROM reviewed_samples
            ORDER BY created_at, id
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "source": row["source"],
            "decision": row["decision"],
            "image_jpeg": bytes(row["image_jpeg"]),
            "detections": json.loads(row["detections_json"]),
            "annotations": json.loads(row["annotations_json"]),
        }
        for row in rows
    ]

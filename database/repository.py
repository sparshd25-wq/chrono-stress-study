"""SQLite persistence layer for study records."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import sqlite3
from typing import Any, Iterator

import numpy as np
import pandas as pd

from config import DAILY_ASSESSMENT_TARGET, DATABASE_PATH, STUDY_DURATION_DAYS


def utc_now() -> str:
    """Return a timezone-aware ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with foreign keys and row access enabled."""
    conn = sqlite3.connect(DATABASE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialise_database() -> None:
    """Create all tables and indexes if they do not yet exist."""
    schema = """
    CREATE TABLE IF NOT EXISTS participants (
        participant_id TEXT PRIMARY KEY,
        access_code_hash TEXT NOT NULL,
        age INTEGER NOT NULL,
        gender TEXT NOT NULL,
        occupation TEXT NOT NULL,
        academic_status TEXT NOT NULL,
        medication TEXT NOT NULL,
        sleep_disorders TEXT NOT NULL,
        mental_health_diagnosis TEXT,
        coffee_per_day INTEGER NOT NULL,
        smoking TEXT NOT NULL,
        alcohol TEXT NOT NULL,
        average_sleep_hours REAL NOT NULL,
        enrolled_at TEXT NOT NULL,
        study_days INTEGER NOT NULL DEFAULT 21
    );

    CREATE TABLE IF NOT EXISTS consents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        participant_id TEXT NOT NULL,
        consent_version TEXT NOT NULL,
        privacy_accepted INTEGER NOT NULL,
        participation_accepted INTEGER NOT NULL,
        consented_at TEXT NOT NULL,
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    );

    CREATE TABLE IF NOT EXISTS wearable_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        participant_id TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        provider TEXT NOT NULL,
        heart_rate REAL,
        hrv REAL,
        resting_hr REAL,
        sleep_hours REAL,
        stress_score REAL,
        recovery_score REAL,
        steps INTEGER,
        battery INTEGER,
        source TEXT NOT NULL DEFAULT 'mock',
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    );

    CREATE TABLE IF NOT EXISTS assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        participant_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        location TEXT NOT NULL,
        activity TEXT NOT NULL,
        sleep_hours REAL NOT NULL,
        caffeine_recent INTEGER NOT NULL,
        medication_today INTEGER NOT NULL,
        workload TEXT NOT NULL,
        stress REAL NOT NULL,
        mental_fatigue REAL NOT NULL,
        emotional_arousal REAL NOT NULL,
        perceived_control REAL NOT NULL,
        anxiety REAL NOT NULL,
        stressful_event INTEGER NOT NULL,
        event_type TEXT,
        event_duration TEXT,
        event_upset REAL,
        event_expected INTEGER,
        event_control REAL,
        reflection TEXT,
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    );

    CREATE TABLE IF NOT EXISTS task_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assessment_id INTEGER NOT NULL,
        participant_id TEXT NOT NULL,
        task_type TEXT NOT NULL,
        target_seconds REAL,
        response_seconds REAL NOT NULL,
        signed_error REAL NOT NULL,
        absolute_error REAL NOT NULL,
        recorded_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (assessment_id) REFERENCES assessments(id),
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    );

    CREATE TABLE IF NOT EXISTS cognitive_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assessment_id INTEGER NOT NULL,
        participant_id TEXT NOT NULL,
        task_type TEXT NOT NULL,
        accuracy REAL NOT NULL,
        mean_reaction_ms REAL NOT NULL,
        errors INTEGER NOT NULL,
        misses INTEGER NOT NULL,
        false_alarms INTEGER NOT NULL,
        trials_json TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        FOREIGN KEY (assessment_id) REFERENCES assessments(id),
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    );

    CREATE INDEX IF NOT EXISTS idx_assessments_participant_time
        ON assessments(participant_id, submitted_at);
    CREATE INDEX IF NOT EXISTS idx_wearable_participant_time
        ON wearable_data(participant_id, recorded_at);
    CREATE INDEX IF NOT EXISTS idx_tasks_participant_time
        ON task_results(participant_id, recorded_at);
    """
    with connection() as conn:
        conn.executescript(schema)


def participant_exists(participant_id: str) -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM participants WHERE participant_id = ?", (participant_id,)
        ).fetchone()
    return row is not None


def create_participant(record: dict[str, Any]) -> None:
    fields = (
        "participant_id", "access_code_hash", "age", "gender", "occupation",
        "academic_status", "medication", "sleep_disorders",
        "mental_health_diagnosis", "coffee_per_day", "smoking", "alcohol",
        "average_sleep_hours", "enrolled_at", "study_days",
    )
    values = [record.get(field) for field in fields]
    placeholders = ", ".join("?" for _ in fields)
    with connection() as conn:
        conn.execute(
            f"INSERT INTO participants ({', '.join(fields)}) VALUES ({placeholders})",
            values,
        )


def get_participant(participant_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM participants WHERE participant_id = ?", (participant_id,)
        ).fetchone()
    return dict(row) if row else None


def save_consent(participant_id: str) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO consents
               (participant_id, consent_version, privacy_accepted,
                participation_accepted, consented_at)
               VALUES (?, '1.0', 1, 1, ?)""",
            (participant_id, utc_now()),
        )


def has_consent(participant_id: str) -> bool:
    with connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM consents WHERE participant_id = ? LIMIT 1",
            (participant_id,),
        ).fetchone()
    return row is not None


def save_assessment(
    participant_id: str,
    started_at: str,
    answers: dict[str, Any],
    time_tasks: list[dict[str, Any]],
    cognitive: dict[str, Any],
) -> int:
    """Atomically save an assessment and all behavioural results."""
    assessment_fields = (
        "location", "activity", "sleep_hours", "caffeine_recent",
        "medication_today", "workload", "stress", "mental_fatigue",
        "emotional_arousal", "perceived_control", "anxiety",
        "stressful_event", "event_type", "event_duration", "event_upset",
        "event_expected", "event_control", "reflection",
    )
    with connection() as conn:
        cursor = conn.execute(
            f"""INSERT INTO assessments
                (participant_id, started_at, submitted_at, {', '.join(assessment_fields)})
                VALUES (?, ?, ?, {', '.join('?' for _ in assessment_fields)})""",
            [participant_id, started_at, utc_now()]
            + [answers.get(field) for field in assessment_fields],
        )
        assessment_id = int(cursor.lastrowid)

        for task in time_tasks:
            conn.execute(
                """INSERT INTO task_results
                   (assessment_id, participant_id, task_type, target_seconds,
                    response_seconds, signed_error, absolute_error, recorded_at,
                    metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment_id,
                    participant_id,
                    task["task_type"],
                    task.get("target_seconds"),
                    task["response_seconds"],
                    task["signed_error"],
                    task["absolute_error"],
                    utc_now(),
                    json.dumps(task.get("metadata", {})),
                ),
            )

        conn.execute(
            """INSERT INTO cognitive_results
               (assessment_id, participant_id, task_type, accuracy,
                mean_reaction_ms, errors, misses, false_alarms, trials_json,
                recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                assessment_id,
                participant_id,
                cognitive["task_type"],
                cognitive["accuracy"],
                cognitive["mean_reaction_ms"],
                cognitive["errors"],
                cognitive["misses"],
                cognitive["false_alarms"],
                json.dumps(cognitive["trials"]),
                utc_now(),
            ),
        )
    return assessment_id


def dataframe(query: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


def participant_frames(participant_id: str) -> dict[str, pd.DataFrame]:
    """Return export-ready participant tables."""
    return {
        "participant": dataframe(
            "SELECT * FROM participants WHERE participant_id = ?", (participant_id,)
        ),
        "consent": dataframe(
            "SELECT * FROM consents WHERE participant_id = ?", (participant_id,)
        ),
        "assessments": dataframe(
            "SELECT * FROM assessments WHERE participant_id = ? ORDER BY submitted_at",
            (participant_id,),
        ),
        "wearable": dataframe(
            "SELECT * FROM wearable_data WHERE participant_id = ? ORDER BY recorded_at",
            (participant_id,),
        ),
        "time_tasks": dataframe(
            "SELECT * FROM task_results WHERE participant_id = ? ORDER BY recorded_at",
            (participant_id,),
        ),
        "cognitive": dataframe(
            "SELECT * FROM cognitive_results WHERE participant_id = ? ORDER BY recorded_at",
            (participant_id,),
        ),
    }


def seed_mock_wearable(participant_id: str, days: int = STUDY_DURATION_DAYS) -> None:
    """Create deterministic demonstration wearable observations once."""
    with connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM wearable_data WHERE participant_id = ?",
            (participant_id,),
        ).fetchone()[0]
        if count:
            return

        seed = sum(ord(char) for char in participant_id)
        rng = np.random.default_rng(seed)
        today = date.today()
        rows = []
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            stress = float(np.clip(rng.normal(48, 14), 12, 92))
            sleep = float(np.clip(8.2 - stress / 35 + rng.normal(0, 0.45), 4.5, 9.2))
            hrv = float(np.clip(72 - stress * 0.45 + rng.normal(0, 5), 20, 85))
            resting_hr = float(np.clip(58 + stress * 0.15 + rng.normal(0, 2), 52, 85))
            rows.append(
                (
                    participant_id,
                    datetime.combine(day, datetime.min.time(), timezone.utc)
                    .replace(hour=8)
                    .isoformat(),
                    "Oura demo",
                    round(resting_hr + rng.normal(12, 3), 1),
                    round(hrv, 1),
                    round(resting_hr, 1),
                    round(sleep, 2),
                    round(stress, 1),
                    round(100 - stress * 0.65 + rng.normal(0, 4), 1),
                    int(np.clip(rng.normal(7600, 2100), 1800, 15000)),
                    int(rng.integers(42, 96)),
                    "mock",
                )
            )
        conn.executemany(
            """INSERT INTO wearable_data
               (participant_id, recorded_at, provider, heart_rate, hrv,
                resting_hr, sleep_hours, stress_score, recovery_score,
                steps, battery, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )


def study_summary(participant_id: str) -> dict[str, Any]:
    participant = get_participant(participant_id)
    if participant is None:
        return {}
    assessments = dataframe(
        "SELECT submitted_at, stress FROM assessments WHERE participant_id = ?",
        (participant_id,),
    )
    wearable = dataframe(
        """SELECT * FROM wearable_data WHERE participant_id = ?
           ORDER BY recorded_at DESC LIMIT 1""",
        (participant_id,),
    )
    enrolled = datetime.fromisoformat(participant["enrolled_at"]).date()
    study_day = min((date.today() - enrolled).days + 1, participant["study_days"])
    total_expected = participant["study_days"] * DAILY_ASSESSMENT_TARGET
    completion = min(100.0, len(assessments) / total_expected * 100)
    today_count = 0
    if not assessments.empty:
        submitted = pd.to_datetime(assessments["submitted_at"], utc=True)
        today_count = int((submitted.dt.date == date.today()).sum())
    latest = wearable.iloc[0].to_dict() if not wearable.empty else {}
    return {
        "study_day": study_day,
        "study_days": participant["study_days"],
        "assessment_count": len(assessments),
        "today_count": today_count,
        "completion": completion,
        "missing": max(total_expected - len(assessments), 0),
        "wearable": latest,
    }


"""Persistence layer for study records.

Production deployments use Supabase PostgreSQL when a database URL is provided
through Streamlit Secrets or environment variables. Local development keeps the
existing SQLite fallback so the rest of the application can use the same
repository API without UI, task, or assessment-flow changes.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import os
import sqlite3
from typing import Any, Iterator

import numpy as np
import pandas as pd

from config import (
    DAILY_ASSESSMENT_TARGET,
    DATABASE_PATH,
    STUDY_DURATION_DAYS,
)


POSTGRES_URL_KEYS = (
    "SUPABASE_DB_URL",
    "SUPABASE_DATABASE_URL",
    "DATABASE_URL",
    "POSTGRES_URL",
)
TABLES = (
    "participants",
    "consents",
    "wearable_data",
    "assessments",
    "task_results",
    "cognitive_results",
    "assessment_metadata",
)


def utc_now() -> str:
    """Return a timezone-aware ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _secret_value(key: str) -> str | None:
    """Read database credentials from Streamlit Secrets or the environment."""
    value: str | None = None
    try:
        import streamlit as st

        value = st.secrets.get(key)
    except Exception:
        value = None
    return str(value) if value else os.getenv(key)


def _postgres_url() -> str | None:
    for key in POSTGRES_URL_KEYS:
        value = _secret_value(key)
        if value:
            return value
    try:
        import streamlit as st

        for section_name in ("supabase", "postgres"):
            section = st.secrets.get(section_name, {})
            if hasattr(section, "get"):
                for key in ("db_url", "database_url", "postgres_url", "connection_string", "uri"):
                    value = section.get(key)
                    if value:
                        return str(value)
    except Exception:
        pass
    return None


def database_type() -> str:
    """Return the active database backend name."""
    return "postgres" if _postgres_url() else "sqlite"


def _is_postgres() -> bool:
    return database_type() == "postgres"


def _sql(query: str) -> str:
    """Convert SQLite-style placeholders to PostgreSQL placeholders."""
    return query.replace("?", "%s") if _is_postgres() else query


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except Exception:
        return row[index]


def _execute(conn: Any, query: str, params: Any = ()) -> Any:
    return conn.execute(_sql(query), params)


def _executemany(conn: Any, query: str, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    if _is_postgres():
        with conn.cursor() as cursor:
            cursor.executemany(_sql(query), rows)
    else:
        conn.executemany(query, rows)


def _scalar(conn: Any, query: str, params: Any = (), key: str = "value") -> Any:
    row = _execute(conn, query, params).fetchone()
    return _row_value(row, key)


@contextmanager
def connection() -> Iterator[Any]:
    """Open a database connection with transactions enabled."""
    if _is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "Supabase/PostgreSQL credentials are configured, but psycopg is "
                "not installed. Add psycopg[binary] to requirements.txt."
            ) from exc
        conn = psycopg.connect(_postgres_url(), row_factory=dict_row)
    else:
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

    CREATE TABLE IF NOT EXISTS assessment_metadata (
        assessment_id INTEGER PRIMARY KEY,
        participant_id TEXT NOT NULL,
        assessment_date TEXT NOT NULL,
        assessment_start_time TEXT NOT NULL,
        assessment_end_time TEXT NOT NULL,
        assessment_duration_seconds REAL NOT NULL,
        device_type TEXT NOT NULL,
        browser TEXT NOT NULL,
        session_id TEXT NOT NULL,
        assessment_version TEXT NOT NULL,
        total_assessment_duration REAL NOT NULL,
        mean_time_per_task REAL NOT NULL,
        completed_without_interruptions INTEGER NOT NULL,
        completion_status TEXT NOT NULL,
        FOREIGN KEY (assessment_id) REFERENCES assessments(id),
        FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
    );

    CREATE INDEX IF NOT EXISTS idx_assessments_participant_time
        ON assessments(participant_id, submitted_at);
    CREATE INDEX IF NOT EXISTS idx_wearable_participant_time
        ON wearable_data(participant_id, recorded_at);
    CREATE INDEX IF NOT EXISTS idx_tasks_participant_time
        ON task_results(participant_id, recorded_at);
    CREATE INDEX IF NOT EXISTS idx_metadata_participant_time
        ON assessment_metadata(participant_id, assessment_end_time);
    """
    with connection() as conn:
        if _is_postgres():
            postgres_schema = schema.replace(
                "INTEGER PRIMARY KEY AUTOINCREMENT",
                "INTEGER PRIMARY KEY GENERATED BY DEFAULT AS IDENTITY",
            )
            for statement in postgres_schema.split(";"):
                if statement.strip():
                    conn.execute(statement)
        else:
            conn.executescript(schema)
        _ensure_longitudinal_columns(conn)
    if _is_postgres():
        _migrate_sqlite_to_postgres()
    _log_database_status()


def _ensure_longitudinal_columns(conn: Any) -> None:
    """Add participant-specific longitudinal keys to existing databases."""
    required_columns = {
        "assessments": {
            "assessment_uid": "TEXT",
            "day_number": "INTEGER",
            "prompt_number": "INTEGER",
        },
        "task_results": {
            "assessment_uid": "TEXT",
            "day_number": "INTEGER",
            "prompt_number": "INTEGER",
        },
        "cognitive_results": {
            "assessment_uid": "TEXT",
            "day_number": "INTEGER",
            "prompt_number": "INTEGER",
        },
        "assessment_metadata": {
            "assessment_uid": "TEXT",
            "day_number": "INTEGER",
            "prompt_number": "INTEGER",
        },
    }
    for table, columns in required_columns.items():
        if _is_postgres():
            existing = {
                row["column_name"]
                for row in conn.execute(
                    """SELECT column_name
                       FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = %s""",
                    (table,),
                ).fetchall()
            }
        else:
            existing = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
        for column, column_type in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_uid
           ON assessments(assessment_uid)
           WHERE assessment_uid IS NOT NULL"""
    )


def _log_database_status() -> None:
    """Print a startup health check without exposing participant data."""
    with connection() as conn:
        participant_count = _scalar(
            conn, "SELECT COUNT(*) AS value FROM participants", key="value"
        )
        assessment_count = _scalar(
            conn, "SELECT COUNT(*) AS value FROM assessments", key="value"
        )
    print(f"ChronoStress database type: {database_type()}")
    print(f"ChronoStress participant count: {participant_count}")
    print(f"ChronoStress assessment count: {assessment_count}")


def _sqlite_source_frames() -> dict[str, pd.DataFrame]:
    """Read any existing local SQLite data for one-time Supabase migration."""
    if not DATABASE_PATH.exists():
        return {}
    source = sqlite3.connect(DATABASE_PATH)
    try:
        frames: dict[str, pd.DataFrame] = {}
        for table in TABLES:
            try:
                frames[table] = pd.read_sql_query(f"SELECT * FROM {table}", source)
            except Exception:
                frames[table] = pd.DataFrame()
        return frames
    finally:
        source.close()


def _safe_db_value(value: Any) -> Any:
    """Convert pandas/numpy missing values to database NULL during migration."""
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _migrate_sqlite_to_postgres() -> None:
    """Copy existing local SQLite records to Supabase without changing schema.

    Streamlit Community Cloud storage is ephemeral, but a developer may have
    local SQLite pilot records before configuring Supabase. This migration is
    idempotent: existing primary keys or participant IDs are left untouched.
    """
    frames = _sqlite_source_frames()
    if not frames:
        return

    with connection() as conn:
        for table in TABLES:
            frame = frames.get(table, pd.DataFrame())
            if frame.empty:
                continue
            columns = list(frame.columns)
            placeholders = ", ".join(["%s"] * len(columns))
            column_sql = ", ".join(columns)
            query = (
                f"INSERT INTO {table} ({column_sql}) "
                f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            )
            rows = [
                tuple(_safe_db_value(value) for value in row)
                for row in frame.itertuples(index=False, name=None)
            ]
            with conn.cursor() as cursor:
                cursor.executemany(query, rows)

        for table in (
            "consents",
            "wearable_data",
            "assessments",
            "task_results",
            "cognitive_results",
        ):
            conn.execute(
                f"""SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 1), 1),
                    true
                )"""
            )


def _longitudinal_context(
    conn: Any, participant_id: str, submitted_at: str
) -> dict[str, Any]:
    participant = _execute(
        conn,
        "SELECT enrolled_at FROM participants WHERE participant_id = ?", (participant_id,)
    ).fetchone()
    if participant is None:
        raise ValueError("Assessment cannot be saved without a valid participant_id.")

    submitted_date = datetime.fromisoformat(submitted_at).date()
    enrolled_date = datetime.fromisoformat(_row_value(participant, "enrolled_at")).date()
    day_number = (submitted_date - enrolled_date).days + 1
    existing_rows = _execute(
        conn,
        "SELECT submitted_at FROM assessments WHERE participant_id = ?",
        (participant_id,),
    ).fetchall()
    prompt_number = (
        sum(
            1
            for row in existing_rows
            if datetime.fromisoformat(_row_value(row, "submitted_at")).date()
            == submitted_date
        )
        + 1
    )
    assessment_uid = f"{participant_id}_D{day_number:02d}_P{prompt_number:02d}"
    duplicate = _execute(
        conn,
        "SELECT 1 FROM assessments WHERE assessment_uid = ?", (assessment_uid,)
    ).fetchone()
    if duplicate:
        raise ValueError(f"Duplicate assessment_id detected: {assessment_uid}")
    return {
        "assessment_uid": assessment_uid,
        "day_number": day_number,
        "prompt_number": prompt_number,
    }


def participant_exists(participant_id: str) -> bool:
    with connection() as conn:
        row = _execute(
            conn,
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
        _execute(
            conn,
            f"INSERT INTO participants ({', '.join(fields)}) VALUES ({placeholders})",
            values,
        )


def get_participant(participant_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = _execute(
            conn,
            "SELECT * FROM participants WHERE participant_id = ?", (participant_id,)
        ).fetchone()
    return dict(row) if row else None


def save_consent(participant_id: str) -> None:
    with connection() as conn:
        _execute(
            conn,
            """INSERT INTO consents
               (participant_id, consent_version, privacy_accepted,
                participation_accepted, consented_at)
               VALUES (?, '1.0', 1, 1, ?)""",
            (participant_id, utc_now()),
        )


def has_consent(participant_id: str) -> bool:
    with connection() as conn:
        row = _execute(
            conn,
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
    assessment_metadata: dict[str, Any] | None = None,
) -> int:
    """Atomically save an assessment and all behavioural results."""
    if not participant_id:
        raise ValueError("Assessment cannot be saved without a participant_id.")
    assessment_fields = (
        "location", "activity", "sleep_hours", "caffeine_recent",
        "medication_today", "workload", "stress", "mental_fatigue",
        "emotional_arousal", "perceived_control", "anxiety",
        "stressful_event", "event_type", "event_duration", "event_upset",
        "event_expected", "event_control", "reflection",
    )
    with connection() as conn:
        submitted_at = utc_now()
        context = _longitudinal_context(conn, participant_id, submitted_at)
        assessment_insert = f"""INSERT INTO assessments
                (participant_id, assessment_uid, day_number, prompt_number,
                 started_at, submitted_at, {', '.join(assessment_fields)})
                VALUES (?, ?, ?, ?, ?, ?, {', '.join('?' for _ in assessment_fields)})"""
        if _is_postgres():
            assessment_insert += " RETURNING id"
        cursor = _execute(
            conn,
            assessment_insert,
            [
                participant_id,
                context["assessment_uid"],
                context["day_number"],
                context["prompt_number"],
                started_at,
                submitted_at,
            ]
            + [answers.get(field) for field in assessment_fields],
        )
        assessment_id = (
            int(_row_value(cursor.fetchone(), "id"))
            if _is_postgres()
            else int(cursor.lastrowid)
        )

        for task in time_tasks:
            _execute(
                conn,
                """INSERT INTO task_results
                   (assessment_id, assessment_uid, participant_id, day_number,
                    prompt_number, task_type, target_seconds,
                    response_seconds, signed_error, absolute_error, recorded_at,
                    metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment_id,
                    context["assessment_uid"],
                    participant_id,
                    context["day_number"],
                    context["prompt_number"],
                    task["task_type"],
                    task.get("target_seconds"),
                    task["response_seconds"],
                    task["signed_error"],
                    task["absolute_error"],
                    submitted_at,
                    json.dumps(task.get("metadata", {})),
                ),
            )

        _execute(
            conn,
            """INSERT INTO cognitive_results
               (assessment_id, assessment_uid, participant_id, day_number,
                prompt_number, task_type, accuracy,
                mean_reaction_ms, errors, misses, false_alarms, trials_json,
                recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                assessment_id,
                context["assessment_uid"],
                participant_id,
                context["day_number"],
                context["prompt_number"],
                cognitive["task_type"],
                cognitive["accuracy"],
                cognitive["mean_reaction_ms"],
                cognitive["errors"],
                cognitive["misses"],
                cognitive["false_alarms"],
                json.dumps(cognitive["trials"]),
                submitted_at,
            ),
        )

        if assessment_metadata:
            metadata_fields = (
                "assessment_uid", "day_number", "prompt_number", "assessment_date",
                "assessment_start_time", "assessment_end_time",
                "assessment_duration_seconds", "device_type", "browser",
                "session_id", "assessment_version", "total_assessment_duration",
                "mean_time_per_task", "completed_without_interruptions",
                "completion_status",
            )
            metadata_payload = {
                **assessment_metadata,
                "assessment_uid": context["assessment_uid"],
                "day_number": context["day_number"],
                "prompt_number": context["prompt_number"],
            }
            metadata_insert = f"""INSERT INTO assessment_metadata
                    (assessment_id, participant_id, {', '.join(metadata_fields)})
                    VALUES (?, ?, {', '.join('?' for _ in metadata_fields)})"""
            if _is_postgres():
                metadata_insert += (
                    " ON CONFLICT (assessment_id) DO UPDATE SET "
                    + ", ".join(
                        f"{field} = EXCLUDED.{field}"
                        for field in ("participant_id",) + metadata_fields
                    )
                )
            else:
                metadata_insert = metadata_insert.replace(
                    "INSERT INTO", "INSERT OR REPLACE INTO", 1
                )
            _execute(
                conn,
                metadata_insert,
                [assessment_id, participant_id]
                + [metadata_payload.get(field) for field in metadata_fields],
            )
    return assessment_id


def dataframe(query: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with connection() as conn:
        return pd.read_sql_query(_sql(query), conn, params=params)


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
        "metadata": dataframe(
            """SELECT * FROM assessment_metadata
               WHERE participant_id = ? ORDER BY assessment_end_time""",
            (participant_id,),
        ),
    }


def all_study_frames() -> dict[str, pd.DataFrame]:
    """Return all tables needed for researcher-wide exports and analytics."""
    return {
        "participant": dataframe("SELECT * FROM participants ORDER BY enrolled_at"),
        "consent": dataframe("SELECT * FROM consents ORDER BY consented_at"),
        "assessments": dataframe("SELECT * FROM assessments ORDER BY submitted_at"),
        "wearable": dataframe("SELECT * FROM wearable_data ORDER BY recorded_at"),
        "time_tasks": dataframe("SELECT * FROM task_results ORDER BY recorded_at"),
        "cognitive": dataframe("SELECT * FROM cognitive_results ORDER BY recorded_at"),
        "metadata": dataframe("SELECT * FROM assessment_metadata ORDER BY assessment_end_time"),
    }


def seed_mock_wearable(participant_id: str, days: int = STUDY_DURATION_DAYS) -> None:
    """Create deterministic demonstration wearable observations once."""
    with connection() as conn:
        count = _scalar(
            conn,
            "SELECT COUNT(*) AS value FROM wearable_data WHERE participant_id = ?",
            (participant_id,),
        )
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
        _executemany(
            conn,
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

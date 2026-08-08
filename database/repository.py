"""SQLite / Turso (libSQL) persistence layer for study records.

Streamlit Community Cloud gives each app an *ephemeral* local disk: the
filesystem is reset whenever the app sleeps from inactivity, restarts, or
is redeployed. A plain ``sqlite3.connect(DATABASE_PATH)`` file therefore
cannot be trusted to keep participant data -- which is exactly what wiped
every participant, assessment, and event after the last sleep/wake cycle.

To fix that without touching the schema, the queries, or anything calling
into this module, ``connection()`` below transparently uses a Turso
(libSQL) *embedded replica* instead of a bare local file whenever
``TURSO_DATABASE_URL`` / ``TURSO_AUTH_TOKEN`` are configured (via
``st.secrets`` or environment variables): reads are served from a fast
local replica file exactly like SQLite always was, and every write is
synced to the remote, durable Turso primary as part of its commit. A
freshly started process resyncs from that primary on its very first
connection, so a container that just woke up (with an empty local disk)
comes back with every existing participant intact.

Without those credentials configured (e.g. local development), this
module falls back to the original local SQLite file, completely
unchanged -- nothing about local development changes. On Streamlit
Community Cloud specifically, falling back silently would mean quietly
losing data, so ``initialise_database()`` refuses to start instead --
see ``_running_on_streamlit_cloud()`` below.

This uses Turso's ``libsql`` package (``pip install libsql``), the
actively maintained successor to the now-deprecated
``libsql_experimental`` package: same connect()/execute()/sync() API,
still installed as the ``libsql`` module, but with prebuilt wheels for
current Python versions -- including the one Streamlit Community Cloud
now builds against, which is why the old package started failing to
install.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import os
import sqlite3
import threading
from typing import Any, Iterator

import numpy as np
import pandas as pd

from config import (
    DAILY_ASSESSMENT_TARGET,
    DATA_DIR,
    DATABASE_PATH,
    EXPORTS_DIR,
    LOGS_DIR,
    STUDY_DURATION_DAYS,
)

try:
    import libsql
except ImportError:  # pragma: no cover - optional dependency
    libsql = None


def _read_secret(name: str) -> str | None:
    """Read a config value from Streamlit secrets, falling back to the
    environment. Never raises: an app with no secrets.toml at all (the
    normal case for local development) is treated the same as the key
    simply being absent, so it falls back to plain SQLite below."""
    try:
        import streamlit as st

        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(name)


def _turso_credentials() -> tuple[str | None, str | None]:
    return _read_secret("TURSO_DATABASE_URL"), _read_secret("TURSO_AUTH_TOKEN")

_sync_lock = threading.Lock()
_synced_once = False
_schema_ready = False


def _turso_status() -> tuple[str | None, str | None, bool]:
    """Resolve Turso credentials fresh on every call instead of caching
    them once at module-import time. Import time runs before Streamlit
    has necessarily attached ``st.secrets`` to this process on every code
    path, and a stale ``False`` snapshot taken then would otherwise pin
    the whole process to local SQLite for its entire lifetime with no
    error -- which is exactly the "CSV works, Turso has zero tables"
    failure mode this replaces."""
    url, token = _turso_credentials()
    return url, token, bool(url and token and libsql is not None)


def _running_on_streamlit_cloud() -> bool:
    """Best-effort detection of Streamlit Community Cloud, which clones
    every app to ``/mount/src/<repo>`` before running it. Set the
    ``CHRONOSTRESS_REQUIRE_TURSO`` secret/environment variable to
    ``true``/``false`` to override this in either direction (e.g. to get
    the same no-silent-fallback guarantee on another host, or to relax it
    while debugging on Community Cloud itself)."""
    override = _read_secret("CHRONOSTRESS_REQUIRE_TURSO")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes"}
    return str(BASE_DIR).startswith("/mount/src")


class _Row:
    """Mapping-style row -- supports ``row["col"]``, ``row[0]``, and
    ``dict(row)`` -- matching ``sqlite3.Row`` behaviour for result tuples
    returned by libsql, which has no row_factory of its own."""

    __slots__ = ("_columns", "_values")

    def __init__(self, columns: list[str], values: tuple[Any, ...]) -> None:
        self._columns = columns
        self._values = values

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return self._values[self._columns.index(key)]
        return self._values[key]

    def keys(self) -> list[str]:
        return list(self._columns)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Row({dict(zip(self._columns, self._values))})"


class _LibsqlCursor:
    """Wraps a libsql cursor so fetched rows support the same dict-style
    access as sqlite3.Row-backed cursors do."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def _columns(self) -> list[str] | None:
        if self._cursor.description is None:
            return None
        return [col[0] for col in self._cursor.description]

    def fetchone(self) -> Any:
        row = self._cursor.fetchone()
        if row is None:
            return None
        columns = self._columns()
        return _Row(columns, row) if columns else row

    def fetchall(self) -> list[Any]:
        rows = self._cursor.fetchall()
        columns = self._columns()
        if not columns:
            return rows
        return [_Row(columns, row) for row in rows]

    def fetchmany(self, size: int | None = None) -> list[Any]:
        rows = self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()
        columns = self._columns()
        if not columns:
            return rows
        return [_Row(columns, row) for row in rows]

    @property
    def lastrowid(self) -> Any:
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> Any:
        return getattr(self._cursor, "rowcount", -1)


class _LibsqlConnection:
    """Adapts a libsql Connection (a local embedded replica of
    the remote Turso database) to the subset of the sqlite3.Connection
    interface this repository relies on: dict-style row access via
    execute()/fetchone()/fetchall(), executemany, executescript, and a
    cursor() passthrough for pandas.

    Only commits that actually wrote data trigger a sync to the remote
    primary (checked via ``in_transaction``, which is only true after a
    real INSERT/UPDATE/DELETE) -- so the frequent read-only connections
    opened throughout the app (e.g. the participant lookup that runs on
    every rerun, including during the timed Stroop trials) never pay for
    a network round trip, and assessment timing is unaffected.
    """

    def __init__(self, raw_connection: Any) -> None:
        self._conn = raw_connection

    def execute(self, sql: str, parameters: Any = ()) -> _LibsqlCursor:
        return _LibsqlCursor(self._conn.execute(sql, parameters))

    def executemany(self, sql: str, seq_of_parameters: Any) -> _LibsqlCursor:
        return _LibsqlCursor(self._conn.executemany(sql, seq_of_parameters))

    def executescript(self, script: str) -> Any:
        return self._conn.executescript(script)

    def cursor(self) -> Any:
        # Unwrapped, raw cursor: this is what pandas.read_sql_query needs.
        return self._conn.cursor()

    def commit(self) -> None:
        wrote = self._conn.in_transaction
        self._conn.commit()
        if wrote:
            self._conn.sync()

    def rollback(self) -> None:
        self._conn.rollback()

    def sync(self) -> None:
        self._conn.sync()

    def close(self) -> None:
        self._conn.close()


def utc_now() -> str:
    """Return a timezone-aware ISO timestamp."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection() -> Iterator[Any]:
    """Open a database connection with foreign keys and row access enabled.

    Uses a synced Turso (libSQL) embedded replica when credentials are
    configured, otherwise the original local SQLite file. See the module
    docstring for why this matters on Streamlit Community Cloud.
    """
    global _synced_once
    turso_url, turso_token, use_libsql = _turso_status()
    if use_libsql:
        raw_conn = libsql.connect(
            str(DATABASE_PATH), sync_url=turso_url, auth_token=turso_token
        )
        if not _synced_once:
            with _sync_lock:
                if not _synced_once:
                    raw_conn.sync()
                    _synced_once = True
        conn: Any = _LibsqlConnection(raw_conn)
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


def turso_diagnostics() -> dict[str, Any]:
    """Non-secret status snapshot for an admin-only diagnostic view --
    never returns the database URL or auth token themselves, only
    whether they were detected and whether the connection actually works.

    Wire this into an admin page, e.g.::

        st.json(turso_diagnostics())
    """
    turso_url, turso_token, use_libsql = _turso_status()
    info: dict[str, Any] = {
        "turso_credentials_detected": bool(turso_url and turso_token),
        "libsql_driver_loaded": libsql is not None,
        "using_turso": use_libsql,
        "mode": "Turso (libSQL embedded replica)" if use_libsql else "Local SQLite",
        "detected_as_streamlit_cloud": _running_on_streamlit_cloud(),
    }
    if use_libsql:
        try:
            with connection() as conn:
                info["participant_count"] = conn.execute(
                    "SELECT COUNT(*) FROM participants"
                ).fetchone()[0]
                info["assessment_count"] = conn.execute(
                    "SELECT COUNT(*) FROM assessments"
                ).fetchone()[0]
            info["connection_ok"] = True
        except Exception as exc:  # pragma: no cover - diagnostic path only
            info["connection_ok"] = False
            info["error"] = str(exc)
    return info


def initialise_database() -> None:
    """Create all tables and indexes if they do not yet exist."""
    global _schema_ready
    turso_url, turso_token, use_libsql = _turso_status()
    turso_configured = bool(turso_url and turso_token)
    if not use_libsql and (turso_configured or _running_on_streamlit_cloud()):
        missing = []
        if not turso_configured:
            missing.append("TURSO_DATABASE_URL / TURSO_AUTH_TOKEN secrets")
        if libsql is None:
            missing.append("the libsql package (check requirements.txt / the build log)")
        raise RuntimeError(
            "ChronoStress has Turso configured (or is running on Streamlit "
            "Community Cloud) but does not have a working Turso connection "
            "(missing: " + "; ".join(missing) + "). Refusing to fall back "
            "to local SQLite here, since that storage is wiped on every "
            "sleep/restart and participant data would be silently lost. "
            "Double-check TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in the "
            "app's Secrets, or set CHRONOSTRESS_REQUIRE_TURSO=false if "
            "ephemeral storage is genuinely intended here."
        )
    print(
        f"[ChronoStress] database mode: "
        f"{'Turso (libSQL embedded replica)' if use_libsql else 'local SQLite'}"
        f" | turso_credentials_detected={turso_configured}"
        f" | libsql_driver_loaded={libsql is not None}"
    )
    for directory in (DATA_DIR, EXPORTS_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    if _schema_ready:
        # Every statement below is guarded with IF NOT EXISTS, so re-running
        # this on every single Streamlit rerun (this function is called
        # unconditionally at the top of main()) was always redundant. Now
        # that a rerun can also mean a network sync (see connection()),
        # skipping the repeat work after the first successful run matters
        # more than it used to -- this changes no behaviour, since the
        # schema itself is only ever created once either way.
        return

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
        conn.executescript(schema)
        _ensure_longitudinal_columns(conn)
        if use_libsql:
            # DDL (CREATE TABLE/INDEX, ALTER TABLE) doesn't set
            # in_transaction, so the ordinary commit-triggered sync in
            # _LibsqlConnection.commit() wouldn't push it. Do it explicitly
            # here, once, so a brand-new Turso database ends up with the
            # schema on the remote primary too, not just this local replica.
            conn.sync()
    _sync_master_exports()
    _schema_ready = True


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


def _sync_master_exports() -> None:
    """Refresh study-level master CSV files from the current SQLite state."""
    from utils.exports import sync_master_csvs

    sync_master_csvs(all_study_frames())


def _longitudinal_context(
    conn: Any, participant_id: str, submitted_at: str
) -> dict[str, Any]:
    participant = conn.execute(
        "SELECT enrolled_at FROM participants WHERE participant_id = ?", (participant_id,)
    ).fetchone()
    if participant is None:
        raise ValueError("Assessment cannot be saved without a valid participant_id.")

    submitted_date = datetime.fromisoformat(submitted_at).date()
    enrolled_date = datetime.fromisoformat(participant["enrolled_at"]).date()
    day_number = (submitted_date - enrolled_date).days + 1
    prompt_number = int(
        conn.execute(
            """SELECT COUNT(*) FROM assessments
               WHERE participant_id = ? AND date(submitted_at) = date(?)""",
            (participant_id, submitted_at),
        ).fetchone()[0]
    ) + 1
    assessment_uid = f"{participant_id}_D{day_number:02d}_P{prompt_number:02d}"
    duplicate = conn.execute(
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
        cursor = conn.execute(
            f"""INSERT INTO assessments
                (participant_id, assessment_uid, day_number, prompt_number,
                 started_at, submitted_at, {', '.join(assessment_fields)})
                VALUES (?, ?, ?, ?, ?, ?, {', '.join('?' for _ in assessment_fields)})""",
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
        assessment_id = int(cursor.lastrowid)

        for task in time_tasks:
            conn.execute(
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

        conn.execute(
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
            conn.execute(
                f"""INSERT OR REPLACE INTO assessment_metadata
                    (assessment_id, participant_id, {', '.join(metadata_fields)})
                    VALUES (?, ?, {', '.join('?' for _ in metadata_fields)})""",
                [assessment_id, participant_id]
                + [metadata_payload.get(field) for field in metadata_fields],
            )
    _sync_master_exports()
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

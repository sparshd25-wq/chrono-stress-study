"""Longitudinal research exports for the ChronoStress study.

The master CSVs are intentionally flat and analysis-ready: one row per
participant, one row per assessment session, one row per Stroop trial, and one
long-format raw-event log. This shape supports within-day, across-day, and
across-participant repeated-measures analyses without post-hoc restructuring.
"""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import ASSESSMENT_VERSION, DATA_DIR


PARTICIPANTS_COLUMNS = {
    "participant_id": "Unique study participant identifier.",
    "age": "Participant age if available.",
    "gender": "Participant gender if available.",
    "enrollment_date": "Date on which the participant enrolled.",
    "completed_days": "Number of distinct study days with at least one completed assessment.",
    "status": "Study participation status inferred from completion.",
    "device_type": "Most recent device class inferred from the browser user-agent.",
    "app_version": "ChronoStress assessment/app version.",
}

DAILY_ASSESSMENT_COLUMNS = {
    "participant_id": "Unique study participant identifier.",
    "assessment_id": "Longitudinal assessment key: participantID_Dday_Pprompt.",
    "day_number": "Study day number from 1 to 21.",
    "prompt_number": "Prompt number within the study day.",
    "assessment_datetime": "UTC timestamp for assessment completion.",
    "assessment_date": "UTC calendar date for assessment completion.",
    "assessment_time": "UTC clock time for assessment completion.",
    "assessment_duration_seconds": "Total assessment duration in seconds.",
    "device_type": "Device class inferred from browser user-agent.",
    "browser": "Browser inferred from user-agent.",
    "session_id": "UUID assigned when the assessment session started.",
    "app_version": "ChronoStress assessment/app version.",
    "true_interval": "Task 1 target interval in seconds.",
    "reproduced_interval": "Task 1 participant reproduced interval in seconds.",
    "task1_signed_error": "Task 1 reproduced interval minus true interval.",
    "task1_absolute_error": "Absolute Task 1 timing error.",
    "task1_completion_time": "Task 1 completion timestamp.",
    "target_interval": "Task 2 target interval in seconds.",
    "participant_interval": "Task 2 participant response interval in seconds.",
    "task2_signed_error": "Task 2 participant interval minus target interval.",
    "task2_absolute_error": "Absolute Task 2 timing error.",
    "task2_completion_time": "Task 2 completion timestamp.",
    "reference_pulse_rate": "Task 3 reference pulse frequency in pulses per second.",
    "participant_selected_rate": "Task 3 selected pulse frequency in pulses per second.",
    "pulse_matching_error": "Selected pulse rate minus reference pulse rate.",
    "absolute_matching_error": "Absolute pulse matching error.",
    "pulse_time_taken": "Seconds taken to select the matching pulse.",
    "slider_final_value": "Final value returned by the pulse matching control.",
    "overall_accuracy": "Overall Stroop accuracy percentage.",
    "overall_mean_RT": "Mean correct Stroop reaction time in milliseconds.",
    "overall_median_RT": "Median correct Stroop reaction time in milliseconds.",
    "overall_SD_RT": "Standard deviation of correct Stroop reaction times.",
    "congruent_accuracy": "Accuracy percentage on congruent Stroop trials.",
    "incongruent_accuracy": "Accuracy percentage on incongruent Stroop trials.",
    "congruent_mean_RT": "Mean correct RT for congruent Stroop trials.",
    "incongruent_mean_RT": "Mean correct RT for incongruent Stroop trials.",
    "stroop_interference_effect": "Incongruent mean RT minus congruent mean RT.",
    "number_of_errors": "Number of incorrect non-timeout Stroop responses.",
    "number_of_timeouts": "Number of Stroop trials with no response before timeout.",
    "stress_score": "Self-reported current stress rating from 1 to 7.",
    "stress_label": "Verbal label for the stress rating.",
}

STROOP_TRIAL_COLUMNS = {
    "participant_id": "Unique study participant identifier.",
    "assessment_id": "Longitudinal assessment key shared with daily_assessments.csv.",
    "day_number": "Study day number from 1 to 21.",
    "prompt_number": "Prompt number within the study day.",
    "trial_number": "Stroop trial number within the assessment.",
    "condition": "Congruent or incongruent trial classification.",
    "word": "Text shown to the participant.",
    "ink_colour": "Ink colour of the displayed word.",
    "correct_response": "Correct colour response for the trial.",
    "participant_response": "Participant response colour, if any.",
    "accuracy": "True if response matched the ink colour.",
    "reaction_time_ms": "Reaction time in milliseconds.",
    "timeout": "True if no response occurred before the response window.",
    "timestamp": "UTC timestamp when the trial response or timeout was recorded.",
}

RAW_EVENT_COLUMNS = {
    "participant_id": "Unique study participant identifier.",
    "assessment_id": "Longitudinal assessment key when the event belongs to an assessment.",
    "day_number": "Study day number from 1 to 21 when available.",
    "prompt_number": "Prompt number within the study day when available.",
    "timestamp": "UTC timestamp for the event.",
    "event_name": "Recorded event or variable name.",
    "event_value": "Recorded value for debugging and reproducibility.",
}

MASTER_FILES = {
    "Participants": "participants.csv",
    "Daily Assessments": "daily_assessments.csv",
    "Stroop Trials": "stroop_trials.csv",
    "Raw Events": "raw_events.csv",
}

MASTER_KEYS = {
    "Participants": ["participant_id"],
    "Daily Assessments": ["assessment_id"],
    "Stroop Trials": ["assessment_id", "trial_number"],
    "Raw Events": list(RAW_EVENT_COLUMNS),
}


def _json_dict(value: object) -> dict:
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _json_list(value: object) -> list[dict]:
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _stress_label(score: object) -> str:
    labels = {
        1: "Very Low",
        2: "Low",
        3: "Slightly Low",
        4: "Moderate",
        5: "Slightly High",
        6: "High",
        7: "Very High",
    }
    try:
        return labels.get(int(float(score)), "")
    except (TypeError, ValueError):
        return ""


def _expanded_task_frame(tasks: pd.DataFrame) -> pd.DataFrame:
    if tasks.empty:
        return tasks.copy()
    rows = []
    for record in tasks.to_dict("records"):
        rows.append({**record, **_json_dict(record.get("metadata_json"))})
    return pd.DataFrame(rows)


def _base_assessments(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    participants = frames.get("participant", pd.DataFrame()).copy()
    assessments = frames.get("assessments", pd.DataFrame()).copy()
    metadata = frames.get("metadata", pd.DataFrame()).copy()

    if assessments.empty:
        return pd.DataFrame()

    base = assessments.rename(
        columns={"id": "sqlite_assessment_id", "submitted_at": "assessment_datetime"}
    )
    base["assessment_datetime"] = pd.to_datetime(
        base["assessment_datetime"], errors="coerce", utc=True
    )
    if "enrolled_at" in participants.columns:
        enrollment = participants[["participant_id", "enrolled_at"]].copy()
        enrollment["enrolled_at"] = pd.to_datetime(
            enrollment["enrolled_at"], errors="coerce", utc=True
        )
        base = base.merge(enrollment, on="participant_id", how="left")
    else:
        base["enrolled_at"] = pd.NaT

    base["assessment_date"] = base["assessment_datetime"].dt.date.astype(str)
    base["assessment_time"] = base["assessment_datetime"].dt.strftime("%H:%M:%S")
    base = base.sort_values(["participant_id", "assessment_datetime", "sqlite_assessment_id"])
    if "day_number" not in base or base["day_number"].isna().all():
        base["day_number"] = (
            base["assessment_datetime"].dt.date - base["enrolled_at"].dt.date
        ).apply(lambda value: value.days + 1 if pd.notna(value) else np.nan)
    if "prompt_number" not in base or base["prompt_number"].isna().all():
        base["prompt_number"] = (
            base.groupby(["participant_id", "assessment_date"]).cumcount() + 1
        )
    generated_ids = base.apply(
        lambda row: (
            f"{row['participant_id']}_D{int(row['day_number']):02d}_"
            f"P{int(row['prompt_number']):02d}"
        )
        if pd.notna(row["day_number"]) and pd.notna(row["prompt_number"])
        else f"{row['participant_id']}_A{int(row['sqlite_assessment_id']):04d}",
        axis=1,
    )
    if "assessment_uid" in base:
        base["assessment_id"] = base["assessment_uid"].fillna(generated_ids)
    else:
        base["assessment_id"] = generated_ids

    if not metadata.empty:
        metadata = metadata.rename(columns={"assessment_id": "sqlite_assessment_id"})
        base = base.merge(
            metadata.drop(columns=["participant_id"], errors="ignore"),
            on="sqlite_assessment_id",
            how="left",
            suffixes=("", "_metadata"),
        )

    base["app_version"] = base.get("assessment_version", ASSESSMENT_VERSION)
    if "device_type" not in base:
        base["device_type"] = "unknown"
    base["stress_score"] = base["stress"]
    base["stress_label"] = base.get("stress_label", base["stress"].apply(_stress_label))
    return base


def _stroop_trial_frame(
    cognitive: pd.DataFrame, base: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict] = []
    if cognitive.empty or base.empty:
        return pd.DataFrame(columns=list(STROOP_TRIAL_COLUMNS))

    lookup = base.set_index("sqlite_assessment_id")[
        ["assessment_id", "day_number", "prompt_number"]
    ].to_dict("index")

    for record in cognitive.to_dict("records"):
        context = lookup.get(record.get("assessment_id"), {})
        trials = _json_list(record.get("trials_json"))
        for index, trial in enumerate(trials, start=1):
            rows.append(
                {
                    "participant_id": record.get("participant_id"),
                    "assessment_id": context.get("assessment_id"),
                    "day_number": context.get("day_number"),
                    "prompt_number": context.get("prompt_number"),
                    "trial_number": trial.get("trial_number", index),
                    "condition": trial.get(
                        "congruent_or_incongruent",
                        "congruent" if trial.get("congruent") else "incongruent",
                    ),
                    "word": trial.get("word"),
                    "ink_colour": trial.get("ink_colour", trial.get("ink")),
                    "correct_response": trial.get("correct_response", trial.get("ink")),
                    "participant_response": trial.get(
                        "participant_response", trial.get("response")
                    ),
                    "accuracy": bool(trial.get("correct", False)),
                    "reaction_time_ms": trial.get(
                        "reaction_time_ms", trial.get("reaction_ms")
                    ),
                    "timeout": bool(trial.get("timeout", trial.get("miss", False))),
                    "timestamp": trial.get("timestamp", record.get("recorded_at")),
                }
            )
    return pd.DataFrame(rows, columns=list(STROOP_TRIAL_COLUMNS))


def _stroop_summary(stroop_trials: pd.DataFrame) -> pd.DataFrame:
    if stroop_trials.empty:
        return pd.DataFrame()

    rows = []
    trials = stroop_trials.copy()
    trials["accuracy"] = trials["accuracy"].astype(bool)
    trials["timeout"] = trials["timeout"].astype(bool)
    trials["reaction_time_ms"] = pd.to_numeric(
        trials["reaction_time_ms"], errors="coerce"
    )
    for assessment_id, group in trials.groupby("assessment_id", dropna=False):
        correct = group[group["accuracy"]]
        congruent = group[group["condition"] == "congruent"]
        incongruent = group[group["condition"] == "incongruent"]
        congruent_correct = congruent[congruent["accuracy"]]
        incongruent_correct = incongruent[incongruent["accuracy"]]
        congruent_mean = congruent_correct["reaction_time_ms"].mean()
        incongruent_mean = incongruent_correct["reaction_time_ms"].mean()
        rows.append(
            {
                "assessment_id": assessment_id,
                "overall_accuracy": group["accuracy"].mean() * 100,
                "overall_mean_RT": correct["reaction_time_ms"].mean(),
                "overall_median_RT": correct["reaction_time_ms"].median(),
                "overall_SD_RT": correct["reaction_time_ms"].std(),
                "congruent_accuracy": congruent["accuracy"].mean() * 100,
                "incongruent_accuracy": incongruent["accuracy"].mean() * 100,
                "congruent_mean_RT": congruent_mean,
                "incongruent_mean_RT": incongruent_mean,
                "stroop_interference_effect": incongruent_mean - congruent_mean,
                "number_of_errors": int((~group["accuracy"] & ~group["timeout"]).sum()),
                "number_of_timeouts": int(group["timeout"].sum()),
            }
        )
    return pd.DataFrame(rows)


def _task_values(tasks: pd.DataFrame, base: pd.DataFrame, task_type: str) -> pd.DataFrame:
    if tasks.empty or base.empty:
        return pd.DataFrame()
    rows = tasks[tasks["task_type"] == task_type].copy()
    if rows.empty:
        return pd.DataFrame()
    lookup = base[["sqlite_assessment_id", "assessment_id"]]
    rows = rows.merge(
        lookup, left_on="assessment_id", right_on="sqlite_assessment_id", how="left"
    )
    if "assessment_id_y" in rows:
        rows["assessment_id"] = rows["assessment_id_y"]
        rows = rows.drop(columns=["assessment_id_x", "assessment_id_y"], errors="ignore")
    return rows


def participants_dataset(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build participants.csv: one row per participant."""
    participants = frames.get("participant", pd.DataFrame()).copy()
    base = _base_assessments(frames)
    if participants.empty:
        return pd.DataFrame(columns=list(PARTICIPANTS_COLUMNS))

    participants["enrollment_date"] = pd.to_datetime(
        participants["enrolled_at"], errors="coerce", utc=True
    ).dt.date.astype(str)
    if base.empty:
        completed_days = pd.Series(dtype="int64")
        latest_device = pd.Series(dtype="object")
    else:
        completed_days = base.groupby("participant_id")["day_number"].nunique()
        latest_device = (
            base.sort_values("assessment_datetime")
            .groupby("participant_id")["device_type"]
            .last()
        )

    participants["completed_days"] = (
        participants["participant_id"].map(completed_days).fillna(0).astype(int)
    )
    participants["status"] = participants["completed_days"].map(
        lambda days: "completed" if days >= 21 else "active"
    )
    participants["device_type"] = (
        participants["participant_id"].map(latest_device).fillna("unknown")
    )
    participants["app_version"] = ASSESSMENT_VERSION
    for column in PARTICIPANTS_COLUMNS:
        if column not in participants:
            participants[column] = pd.NA
    return participants[list(PARTICIPANTS_COLUMNS)]


def daily_assessments_dataset(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build daily_assessments.csv: one row per Participant x Day x Prompt."""
    base = _base_assessments(frames)
    tasks = _expanded_task_frame(frames.get("time_tasks", pd.DataFrame()))
    cognitive = frames.get("cognitive", pd.DataFrame()).copy()
    if base.empty:
        return pd.DataFrame(columns=list(DAILY_ASSESSMENT_COLUMNS))

    daily = base.copy()
    task1 = _task_values(tasks, base, "time_reproduction")
    task2 = _task_values(tasks, base, "prospective_timing")
    pulse = _task_values(tasks, base, "pulse_matching")

    task_specs = [
        (
            task1,
            {
                "target_seconds": "true_interval",
                "response_seconds": "reproduced_interval",
                "signed_error": "task1_signed_error",
                "absolute_error": "task1_absolute_error",
                "completion_time": "task1_completion_time",
            },
        ),
        (
            task2,
            {
                "target_seconds": "target_interval",
                "response_seconds": "participant_interval",
                "signed_error": "task2_signed_error",
                "absolute_error": "task2_absolute_error",
                "completion_time": "task2_completion_time",
            },
        ),
        (
            pulse,
            {
                "target_pulse_rate": "reference_pulse_rate",
                "matched_pulse_rate": "participant_selected_rate",
                "matching_error": "pulse_matching_error",
                "absolute_matching_error": "absolute_matching_error",
                "time_taken_to_match": "pulse_time_taken",
                "slider_final_value": "slider_final_value",
            },
        ),
    ]
    for task_frame, columns in task_specs:
        if task_frame.empty:
            continue
        selected_columns = ["assessment_id"] + [
            column for column in columns if column in task_frame.columns
        ]
        selected = task_frame[selected_columns].rename(columns=columns)
        daily = daily.merge(selected, on="assessment_id", how="left")

    stroop_trials = _stroop_trial_frame(cognitive, base)
    stroop = _stroop_summary(stroop_trials)
    if not stroop.empty:
        daily = daily.merge(stroop, on="assessment_id", how="left")

    for column in DAILY_ASSESSMENT_COLUMNS:
        if column not in daily:
            daily[column] = pd.NA
    return daily[list(DAILY_ASSESSMENT_COLUMNS)]


def stroop_trials_dataset(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build stroop_trials.csv: one row for every Stroop trial."""
    return _stroop_trial_frame(frames.get("cognitive", pd.DataFrame()), _base_assessments(frames))


def raw_events_dataset(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build raw_events.csv: long-format event log for reproducibility checks."""
    base = _base_assessments(frames)
    daily = daily_assessments_dataset(frames)
    stroop = stroop_trials_dataset(frames)
    raw_rows: list[dict] = []

    context = (
        base.set_index("sqlite_assessment_id")[
            ["assessment_id", "day_number", "prompt_number", "assessment_datetime"]
        ].to_dict("index")
        if not base.empty
        else {}
    )
    for event_name, frame in (
        ("participant", participants_dataset(frames)),
        ("daily_assessment", daily),
        ("stroop_trial", stroop),
    ):
        for record in frame.to_dict("records"):
            timestamp = (
                record.get("timestamp")
                or record.get("assessment_datetime")
                or record.get("enrollment_date")
            )
            for field, value in record.items():
                raw_rows.append(
                    {
                        "participant_id": record.get("participant_id"),
                        "assessment_id": record.get("assessment_id"),
                        "day_number": record.get("day_number"),
                        "prompt_number": record.get("prompt_number"),
                        "timestamp": timestamp,
                        "event_name": f"{event_name}.{field}",
                        "event_value": value,
                    }
                )

    for table_name, frame in frames.items():
        if frame.empty:
            continue
        for record in frame.to_dict("records"):
            sqlite_id = record.get("assessment_id", record.get("id"))
            row_context = context.get(sqlite_id, {})
            timestamp = (
                record.get("recorded_at")
                or record.get("submitted_at")
                or record.get("assessment_end_time")
                or record.get("enrolled_at")
                or record.get("consented_at")
            )
            for field, value in record.items():
                raw_rows.append(
                    {
                        "participant_id": record.get("participant_id"),
                        "assessment_id": row_context.get("assessment_id"),
                        "day_number": row_context.get("day_number"),
                        "prompt_number": row_context.get("prompt_number"),
                        "timestamp": timestamp,
                        "event_name": f"{table_name}.{field}",
                        "event_value": value,
                    }
                )
    return pd.DataFrame(raw_rows, columns=list(RAW_EVENT_COLUMNS))


def data_dictionary() -> pd.DataFrame:
    """Document every exported column for the study data dictionary."""
    rows = []
    for dataset, columns in (
        ("participants.csv", PARTICIPANTS_COLUMNS),
        ("daily_assessments.csv", DAILY_ASSESSMENT_COLUMNS),
        ("stroop_trials.csv", STROOP_TRIAL_COLUMNS),
        ("raw_events.csv", RAW_EVENT_COLUMNS),
    ):
        for column, description in columns.items():
            rows.append(
                {
                    "dataset": dataset,
                    "column": column,
                    "description": description,
                }
            )
    return pd.DataFrame(rows)


def research_datasets(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Return all master datasets used by export and analytics pages."""
    return {
        "Participants": participants_dataset(frames),
        "Daily Assessments": daily_assessments_dataset(frames),
        "Stroop Trials": stroop_trials_dataset(frames),
        "Raw Events": raw_events_dataset(frames),
        "Data Dictionary": data_dictionary(),
    }


def validate_unique_assessment_ids(daily: pd.DataFrame) -> None:
    """Prevent duplicate longitudinal assessment IDs from entering exports."""
    if daily.empty:
        return
    duplicated = daily["assessment_id"][daily["assessment_id"].duplicated()].unique()
    if len(duplicated):
        raise ValueError(
            "Duplicate assessment_id values detected: " + ", ".join(map(str, duplicated))
        )


def sync_master_csvs(frames: dict[str, pd.DataFrame], data_dir: Path = DATA_DIR) -> None:
    """Merge current SQLite records into the four growing master CSV files."""
    data_dir.mkdir(parents=True, exist_ok=True)
    datasets = research_datasets(frames)
    validate_unique_assessment_ids(datasets["Daily Assessments"])
    for dataset_name, filename in MASTER_FILES.items():
        path = data_dir / filename
        current = datasets[dataset_name]
        if path.exists():
            existing = pd.read_csv(path)
            combined = pd.concat([existing, current], ignore_index=True)
            keys = [key for key in MASTER_KEYS[dataset_name] if key in combined.columns]
            combined = combined.drop_duplicates(subset=keys, keep="last")
        else:
            combined = current
        combined.to_csv(path, index=False)


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """Return a UTF-8 CSV payload for Streamlit download buttons."""
    return frame.to_csv(index=False).encode("utf-8")


def excel_workbook(frames: dict[str, pd.DataFrame]) -> bytes:
    """Create ChronoStress_Data.xlsx with the four requested study sheets."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name in ("Participants", "Daily Assessments", "Stroop Trials", "Raw Events"):
            frames[name].to_excel(writer, sheet_name=name, index=False)
    return output.getvalue()

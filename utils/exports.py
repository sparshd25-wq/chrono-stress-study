"""Generate analysis-ready research exports for ChronoStress.

The exported tables deliberately use flat, documented columns so they can be
opened directly in Python, R, SPSS, Excel, or statistical packages used for an
M.Tech thesis workflow.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pandas as pd


SUMMARY_COLUMNS = {
    "participant_id": "Unique study participant identifier.",
    "assessment_id": "Unique SQLite assessment row identifier.",
    "date": "Calendar date on which the assessment was submitted.",
    "assessment_start_time": "UTC timestamp for assessment start.",
    "assessment_end_time": "UTC timestamp for assessment completion.",
    "assessment_duration": "Total assessment duration in seconds.",
    "device_type": "Device class inferred from browser user-agent.",
    "browser": "Browser inferred from user-agent.",
    "session_id": "Unique UUID assigned to the assessment session.",
    "assessment_version": "Version label of the ChronoStress assessment battery.",
    "stress_rating": "Self-reported stress rating from 1 to 7.",
    "stress_label": "Verbal label for the 1 to 7 stress rating.",
    "task1_error": "Signed error for time reproduction in seconds.",
    "task1_absolute_error": "Absolute error for time reproduction in seconds.",
    "task2_error": "Signed error for prospective timing in seconds.",
    "task2_absolute_error": "Absolute error for prospective timing in seconds.",
    "pulse_matching_error": "Signed pulse-frequency matching error.",
    "pulse_absolute_matching_error": "Absolute pulse-frequency matching error.",
    "stroop_accuracy": "Overall Stroop accuracy percentage.",
    "stroop_RT": "Mean correct Stroop reaction time in milliseconds.",
    "stroop_interference": "Incongruent mean RT minus congruent mean RT.",
    "assessment_duration_seconds": "Total assessment duration in seconds.",
    "mean_time_per_task": "Total duration divided by the four behavioural tasks.",
    "completed_without_interruptions": "1 if assessment was completed in one recorded session.",
    "completion_status": "Completion state for the saved assessment.",
}

STROOP_COLUMNS = {
    "participant_id": "Unique study participant identifier.",
    "assessment_id": "Unique SQLite assessment row identifier.",
    "trial": "Stroop trial number within the assessment.",
    "condition": "Congruent or incongruent trial classification.",
    "word": "Text shown to the participant.",
    "ink": "Ink colour of the displayed word.",
    "correct_response": "Correct colour response for the trial.",
    "participant_response": "Participant response colour, if any.",
    "accuracy": "True if response matched the ink colour.",
    "reaction_time": "Reaction time in milliseconds.",
    "timeout": "True if no response occurred before the response window.",
    "timestamp": "UTC timestamp when the trial response or timeout was recorded.",
}

RAW_COLUMNS = {
    "participant_id": "Unique study participant identifier.",
    "assessment_id": "Assessment row identifier, if the event belongs to an assessment.",
    "event_type": "Type of raw event, e.g. assessment, task, stroop_trial.",
    "timestamp": "UTC timestamp for the event.",
    "field": "Recorded variable name.",
    "value": "Recorded variable value.",
}


def _today_suffix() -> str:
    return date.today().isoformat()


def dated_filename(stem: str, suffix: str) -> str:
    """Return a download filename with the current date embedded."""
    return f"{stem}_{_today_suffix()}.{suffix}"


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
        metadata = _json_dict(record.get("metadata_json"))
        rows.append({**record, **metadata})
    return pd.DataFrame(rows)


def _stroop_trial_frame(cognitive: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    if cognitive.empty:
        return pd.DataFrame(columns=list(STROOP_COLUMNS))

    for record in cognitive.to_dict("records"):
        trials = _json_list(record.get("trials_json"))
        for index, trial in enumerate(trials, start=1):
            rows.append(
                {
                    "participant_id": record.get("participant_id"),
                    "assessment_id": record.get("assessment_id"),
                    "trial": trial.get("trial_number", index),
                    "condition": trial.get(
                        "congruent_or_incongruent",
                        "congruent" if trial.get("congruent") else "incongruent",
                    ),
                    "word": trial.get("word"),
                    "ink": trial.get("ink_colour", trial.get("ink")),
                    "correct_response": trial.get("correct_response", trial.get("ink")),
                    "participant_response": trial.get(
                        "participant_response", trial.get("response")
                    ),
                    "accuracy": bool(trial.get("correct", False)),
                    "reaction_time": trial.get("reaction_time_ms", trial.get("reaction_ms")),
                    "timeout": bool(trial.get("timeout", trial.get("miss", False))),
                    "timestamp": trial.get("timestamp", record.get("recorded_at")),
                }
            )
    return pd.DataFrame(rows, columns=list(STROOP_COLUMNS))


def _stroop_summary(stroop_trials: pd.DataFrame) -> pd.DataFrame:
    if stroop_trials.empty:
        return pd.DataFrame()

    rows = []
    for assessment_id, group in stroop_trials.groupby("assessment_id", dropna=False):
        correct = group[group["accuracy"] == True]  # noqa: E712
        congruent = group[group["condition"] == "congruent"]
        incongruent = group[group["condition"] == "incongruent"]
        congruent_correct = congruent[congruent["accuracy"] == True]  # noqa: E712
        incongruent_correct = incongruent[incongruent["accuracy"] == True]  # noqa: E712

        congruent_mean = pd.to_numeric(
            congruent_correct["reaction_time"], errors="coerce"
        ).mean()
        incongruent_mean = pd.to_numeric(
            incongruent_correct["reaction_time"], errors="coerce"
        ).mean()
        reaction_times = pd.to_numeric(correct["reaction_time"], errors="coerce")
        rows.append(
            {
                "assessment_id": assessment_id,
                "overall_accuracy": group["accuracy"].mean() * 100,
                "overall_mean_RT": reaction_times.mean(),
                "overall_median_RT": reaction_times.median(),
                "overall_SD_RT": reaction_times.std(),
                "congruent_accuracy": congruent["accuracy"].mean() * 100,
                "incongruent_accuracy": incongruent["accuracy"].mean() * 100,
                "congruent_mean_RT": congruent_mean,
                "incongruent_mean_RT": incongruent_mean,
                "stroop_interference_effect": incongruent_mean - congruent_mean,
                "number_of_errors": int((~group["accuracy"] & ~group["timeout"]).sum()),
                "number_of_missed_trials": int(group["timeout"].sum()),
            }
        )
    return pd.DataFrame(rows)


def _task_lookup(tasks: pd.DataFrame, task_type: str) -> pd.DataFrame:
    if tasks.empty:
        return pd.DataFrame()
    return tasks[tasks["task_type"] == task_type].copy()


def participant_summary(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build one analysis row per completed assessment."""
    assessments = frames.get("assessments", pd.DataFrame()).copy()
    metadata = frames.get("metadata", pd.DataFrame()).copy()
    tasks = _expanded_task_frame(frames.get("time_tasks", pd.DataFrame()))
    stroop_trials = _stroop_trial_frame(frames.get("cognitive", pd.DataFrame()))
    stroop = _stroop_summary(stroop_trials)

    if assessments.empty:
        return pd.DataFrame(columns=list(SUMMARY_COLUMNS))

    summary = assessments.rename(
        columns={"id": "assessment_id", "submitted_at": "assessment_end_time"}
    )
    summary["date"] = pd.to_datetime(
        summary["assessment_end_time"], errors="coerce", utc=True
    ).dt.date.astype(str)
    summary["stress_rating"] = summary["stress"]
    summary["stress_label"] = summary["stress"].apply(_stress_label)

    if not metadata.empty:
        summary = summary.merge(
            metadata.drop(columns=["participant_id"], errors="ignore"),
            on="assessment_id",
            how="left",
            suffixes=("", "_metadata"),
        )

    task_specs = {
        "time_reproduction": (
            "task1_error",
            "task1_absolute_error",
            "signed_error",
            "absolute_error",
        ),
        "prospective_timing": (
            "task2_error",
            "task2_absolute_error",
            "signed_error",
            "absolute_error",
        ),
        "pulse_matching": (
            "pulse_matching_error",
            "pulse_absolute_matching_error",
            "matching_error",
            "absolute_matching_error",
        ),
    }
    for task_type, (error_col, abs_col, source_error, source_abs) in task_specs.items():
        task_rows = _task_lookup(tasks, task_type)
        if task_rows.empty:
            summary[error_col] = np.nan
            summary[abs_col] = np.nan
            continue
        selected = task_rows[["assessment_id", source_error, source_abs]].rename(
            columns={source_error: error_col, source_abs: abs_col}
        )
        summary = summary.merge(selected, on="assessment_id", how="left")

    if not stroop.empty:
        summary = summary.merge(stroop, on="assessment_id", how="left")

    summary["stroop_accuracy"] = summary.get("overall_accuracy", np.nan)
    summary["stroop_RT"] = summary.get("overall_mean_RT", np.nan)
    summary["stroop_interference"] = summary.get("stroop_interference_effect", np.nan)
    summary["assessment_duration"] = summary.get(
        "assessment_duration_seconds", summary.get("total_assessment_duration", np.nan)
    )

    for column in SUMMARY_COLUMNS:
        if column not in summary:
            summary[column] = np.nan
    return summary[list(SUMMARY_COLUMNS)]


def stroop_trials(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build one row per Stroop trial for trial-level modelling."""
    return _stroop_trial_frame(frames.get("cognitive", pd.DataFrame()))


def complete_raw_data(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a long-format raw event table with no omitted recorded fields."""
    raw_rows: list[dict] = []

    for table_name, frame in frames.items():
        if frame.empty:
            continue
        for record in frame.to_dict("records"):
            participant_id = record.get("participant_id")
            assessment_id = record.get("assessment_id", record.get("id"))
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
                        "participant_id": participant_id,
                        "assessment_id": assessment_id,
                        "event_type": table_name,
                        "timestamp": timestamp,
                        "field": field,
                        "value": value,
                    }
                )

    for trial in stroop_trials(frames).to_dict("records"):
        for field, value in trial.items():
            raw_rows.append(
                {
                    "participant_id": trial.get("participant_id"),
                    "assessment_id": trial.get("assessment_id"),
                    "event_type": "stroop_trial",
                    "timestamp": trial.get("timestamp"),
                    "field": field,
                    "value": value,
                }
            )

    return pd.DataFrame(raw_rows, columns=list(RAW_COLUMNS))


def data_dictionary() -> pd.DataFrame:
    """Document every exported column for another researcher."""
    rows = []
    for dataset, columns in (
        ("Participant Summary", SUMMARY_COLUMNS),
        ("Stroop Trials", STROOP_COLUMNS),
        ("Raw Data", RAW_COLUMNS),
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
    """Return all analysis-ready research datasets."""
    return {
        "Participant Summary": participant_summary(frames),
        "Stroop Trials": stroop_trials(frames),
        "Raw Data": complete_raw_data(frames),
        "Data Dictionary": data_dictionary(),
    }


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def csv_archive(frames: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, frame in frames.items():
            archive.writestr(f"{name}.csv", frame.to_csv(index=False))
    return output.getvalue()


def excel_workbook(frames: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, frame in frames.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
    return output.getvalue()


def json_export(frames: dict[str, pd.DataFrame]) -> bytes:
    payload = {
        name: json.loads(frame.to_json(orient="records", date_format="iso"))
        for name, frame in frames.items()
    }
    return json.dumps(payload, indent=2).encode("utf-8")

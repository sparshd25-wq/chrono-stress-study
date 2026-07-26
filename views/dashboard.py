"""Participant dashboard, longitudinal analytics, and data export."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from components.ui import banner, section_heading, wearable_status
from config import DAILY_ASSESSMENT_TARGET
from database.repository import all_study_frames, participant_frames, study_summary
from utils.analytics import (
    add_derived_assessment_metrics,
    correlation_chart,
    multi_trend,
    trend_chart,
)
from utils.exports import (
    csv_bytes,
    excel_workbook,
    research_datasets,
)


INDIA_TZ = ZoneInfo("Asia/Kolkata")


def format_india_datetime(value: object) -> str:
    """Format UTC or naive timestamps for local India study displays."""
    if isinstance(value, str) and value.endswith(" IST"):
        return value
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return ""
    return parsed.tz_convert(INDIA_TZ).strftime("%Y-%m-%d %H:%M:%S IST")


def _india_timestamp_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce", utc=True).dt.tz_convert(INDIA_TZ)


def _force_export_timestamps_to_ist(datasets: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Force the final downloaded export tables to show Indian local time."""
    converted = {name: frame.copy() for name, frame in datasets.items()}

    daily = converted.get("Daily Assessments")
    if daily is not None and not daily.empty and "assessment_datetime" in daily:
        already_ist = daily["assessment_datetime"].astype(str).str.endswith(" IST")
        local_times = _india_timestamp_series(daily["assessment_datetime"].where(~already_ist))
        valid = local_times.notna()
        daily.loc[valid, "assessment_datetime"] = local_times.loc[valid].dt.strftime(
            "%Y-%m-%d %H:%M:%S IST"
        )
        if "assessment_date" in daily:
            daily.loc[valid, "assessment_date"] = local_times.loc[valid].dt.strftime(
                "%d-%m-%Y"
            )
        if "assessment_time" in daily:
            daily.loc[valid, "assessment_time"] = local_times.loc[valid].dt.strftime(
                "%H:%M:%S"
            )

    for name in ("Stroop Trials", "Raw Events"):
        frame = converted.get(name)
        if frame is None or frame.empty or "timestamp" not in frame:
            continue
        already_ist = frame["timestamp"].astype(str).str.endswith(" IST")
        local_times = _india_timestamp_series(frame["timestamp"].where(~already_ist))
        valid = local_times.notna()
        frame.loc[valid, "timestamp"] = local_times.loc[valid].dt.strftime(
            "%Y-%m-%d %H:%M:%S IST"
        )

    return converted


def _latest_value(latest: dict, key: str, suffix: str = "", fallback: str = "--") -> str:
    value = latest.get(key)
    return f"{value:g}{suffix}" if pd.notna(value) and value is not None else fallback


def render_dashboard(participant_id: str) -> None:
    summary = study_summary(participant_id)
    frames = participant_frames(participant_id)
    latest = summary.get("wearable", {})
    banner(
        f"Study day {summary['study_day']} of {summary['study_days']}",
        "Your daily measures help build a picture of stress and time perception across everyday life.",
    )
    if st.session_state.pop("assessment_saved", False):
        st.success("Assessment saved. Thank you for completing today's check-in.")

    top_left, top_right = st.columns([3, 2])
    with top_left:
        section_heading("Today's protocol", "Assessment progress")
        completed = summary["today_count"]
        st.progress(min(completed / DAILY_ASSESSMENT_TARGET, 1.0))
        st.write(f"**{completed} of {DAILY_ASSESSMENT_TARGET}** scheduled assessments completed today")
        if completed < DAILY_ASSESSMENT_TARGET:
            if st.button("Continue daily assessment", type="primary", use_container_width=True):
                st.session_state.active_page = "Daily Assessment"
                st.rerun()
            st.caption("Next assessment available now  •  Estimated time 5-7 minutes")
        else:
            st.success("Today's assessment schedule is complete.")
    with top_right:
        section_heading("Wearable", "Connection status")
        with st.container(border=True):
            wearable_status(latest.get("provider", "Oura demo"))
            last_sync = format_india_datetime(latest.get("recorded_at"))
            st.caption(f"Last sync: {last_sync or 'Not available'}")
            st.progress(int(latest.get("battery", 0)) / 100)
            st.caption(f"Device battery {int(latest.get('battery', 0))}%")

    st.markdown("#### Latest physiology")
    metrics = st.columns(5)
    metrics[0].metric("Stress", _latest_value(latest, "stress_score", "/100"))
    metrics[1].metric("Recovery", _latest_value(latest, "recovery_score", "/100"))
    metrics[2].metric("Sleep", _latest_value(latest, "sleep_hours", " h"))
    metrics[3].metric("HRV", _latest_value(latest, "hrv", " ms"))
    metrics[4].metric("Resting HR", _latest_value(latest, "resting_hr", " bpm"))

    chart_left, chart_right = st.columns([3, 2])
    wearable = frames["wearable"]
    with chart_left:
        st.markdown("#### Physiology trend")
        if not wearable.empty:
            st.plotly_chart(multi_trend(wearable.tail(14)), use_container_width=True, config={"displayModeBar": False})
    with chart_right:
        st.markdown("#### Study completion")
        st.metric("Overall completion", f"{summary['completion']:.0f}%")
        st.progress(summary["completion"] / 100)
        st.caption(f"{summary['assessment_count']} assessments stored • {summary['missing']} scheduled responses remaining")
        st.markdown("#### Upcoming")
        st.write("**Evening EMA**")
        st.caption("Today, 7:30 PM • Notification schedule demonstration")

    st.markdown("#### Latest assessments")
    assessments = frames["assessments"]
    if assessments.empty:
        st.info("Your completed assessments will appear here.")
    else:
        display = assessments.tail(5)[["submitted_at", "activity", "stress", "mental_fatigue", "workload"]].copy()
        display["submitted_at"] = display["submitted_at"].apply(format_india_datetime)
        display.columns = ["Submitted", "Activity", "Stress", "Mental fatigue", "Workload"]
        st.dataframe(display, hide_index=True, use_container_width=True)


def _require_admin() -> bool:
    if st.session_state.get("user_role") != "admin":
        st.error("You do not have permission to access this page.")
        return False
    return True


def render_admin_dashboard() -> None:
    if not _require_admin():
        return
    frames = all_study_frames()
    datasets = research_datasets(frames)
    participants = datasets["Participants"]
    daily = datasets["Daily Assessments"]
    section_heading("Research dashboard", "Study overview")
    metrics = st.columns(4)
    metrics[0].metric("Participants", len(participants))
    metrics[1].metric("Completed assessments", len(daily))
    metrics[2].metric("Stroop trials", len(datasets["Stroop Trials"]))
    metrics[3].metric("Raw events", len(datasets["Raw Events"]))
    if not daily.empty:
        st.markdown("#### Recent Assessments")
        st.dataframe(daily.tail(10), hide_index=True, use_container_width=True)


def render_analytics() -> None:
    if not _require_admin():
        return
    frames = all_study_frames()
    datasets = research_datasets(frames)
    summary = datasets["Daily Assessments"]
    stroop = datasets["Stroop Trials"]
    section_heading(
        "Research overview",
        "Pilot analytics",
        "Analysis-ready tables for monitoring incoming ChronoStress data.",
    )

    if summary.empty:
        st.info("Completed assessments will appear here once participants submit data.")
        return

    numeric_columns = [
        "stress_score",
        "task1_absolute_error",
        "task2_absolute_error",
        "absolute_matching_error",
        "overall_accuracy",
        "overall_mean_RT",
        "stroop_interference_effect",
        "assessment_duration_seconds",
    ]
    for column in numeric_columns:
        summary[column] = pd.to_numeric(summary[column], errors="coerce")
    if not stroop.empty:
        stroop["reaction_time_ms"] = pd.to_numeric(
            stroop["reaction_time_ms"], errors="coerce"
        )

    congruent_rt = (
        stroop.loc[
            (stroop["condition"] == "congruent") & (stroop["accuracy"] == True),
            "reaction_time_ms",
        ].mean()
        if not stroop.empty
        else pd.NA
    )
    incongruent_rt = (
        stroop.loc[
            (stroop["condition"] == "incongruent") & (stroop["accuracy"] == True),
            "reaction_time_ms",
        ].mean()
        if not stroop.empty
        else pd.NA
    )

    metrics = pd.DataFrame(
        [
            {"Metric": "Participant count", "Value": 1},
            {"Metric": "Average stress", "Value": summary["stress_score"].mean()},
            {"Metric": "Average Task 1 error", "Value": summary["task1_absolute_error"].mean()},
            {"Metric": "Average Task 2 error", "Value": summary["task2_absolute_error"].mean()},
            {
                "Metric": "Average pulse matching error",
                "Value": summary["absolute_matching_error"].mean(),
            },
            {"Metric": "Average Stroop accuracy", "Value": summary["overall_accuracy"].mean()},
            {"Metric": "Average Stroop RT", "Value": summary["overall_mean_RT"].mean()},
            {"Metric": "Average incongruent RT", "Value": incongruent_rt},
            {"Metric": "Average congruent RT", "Value": congruent_rt},
            {
                "Metric": "Average Stroop interference",
                "Value": summary["stroop_interference_effect"].mean(),
            },
            {
                "Metric": "Average assessment duration",
                "Value": summary["assessment_duration_seconds"].mean(),
            },
        ]
    )
    metrics["Value"] = metrics["Value"].map(
        lambda value: "--" if pd.isna(value) else f"{float(value):.2f}"
    )
    st.dataframe(metrics, hide_index=True, use_container_width=True)

    st.markdown("#### Daily Assessments")
    st.dataframe(summary, hide_index=True, use_container_width=True)

    if not stroop.empty:
        st.markdown("#### Stroop Trials")
        st.dataframe(stroop, hide_index=True, use_container_width=True)


def _legacy_render_export(participant_id: str) -> None:
    return
    section_heading("Data portability", "Export participant record")
    st.write(
        "Export all records linked to this participant ID. Files include profile, consent, EMA, "
        "wearable observations, timing tasks, and cognitive results."
    )
    frames = participant_frames(participant_id)
    row_count = sum(len(frame) for frame in frames.values())
    st.metric("Rows available", row_count)
    st.caption(f"Generated locally from SQLite • Participant {participant_id} • {datetime.now().strftime('%d %b %Y %H:%M')}")
    csv_col, excel_col, json_col = st.columns(3)
    csv_col.download_button(
        "Download CSV bundle", csv_archive(frames),
        file_name=f"{participant_id}_study_data_csv.zip", mime="application/zip",
        use_container_width=True,
    )
    excel_col.download_button(
        "Download Excel", excel_workbook(frames),
        file_name=f"{participant_id}_study_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    json_col.download_button(
        "Download JSON", json_export(frames),
        file_name=f"{participant_id}_study_data.json", mime="application/json",
        use_container_width=True,
    )
    st.warning("For a live study, researcher-wide exports should sit behind separate role-based authentication and an approved data-management policy.")


def render_export() -> None:
    if not _require_admin():
        return
    section_heading("Data portability", "Longitudinal master datasets")
    st.write(
        "Download the admin-only longitudinal repeated-measures dataset for the full study."
    )
    datasets = _force_export_timestamps_to_ist(
        research_datasets(all_study_frames(), readable_exports=True)
    )
    participants = datasets["Participants"]
    daily = datasets["Daily Assessments"]
    stroop = datasets["Stroop Trials"]
    raw = datasets["Raw Events"]
    row_count = len(participants) + len(daily) + len(stroop) + len(raw)
    st.metric("Rows available", row_count)
    st.caption("Master CSV files are also maintained in the local data folder.")

    first_row, second_row = st.columns(2)
    third_row, fourth_row = st.columns(2)
    first_row.download_button(
        "Download participants.csv",
        csv_bytes(participants),
        file_name="participants.csv",
        mime="text/csv",
        use_container_width=True,
    )
    second_row.download_button(
        "Download daily_assessments.csv",
        csv_bytes(daily),
        file_name="daily_assessments.csv",
        mime="text/csv",
        use_container_width=True,
    )
    third_row.download_button(
        "Download stroop_trials.csv",
        csv_bytes(stroop),
        file_name="stroop_trials.csv",
        mime="text/csv",
        use_container_width=True,
    )
    fourth_row.download_button(
        "Download raw_events.csv",
        csv_bytes(raw),
        file_name="raw_events.csv",
        mime="text/csv",
        use_container_width=True,
    )
    workbook_bytes, workbook_warnings = excel_workbook(datasets, return_warnings=True)
    for warning in workbook_warnings:
        st.warning(warning)
    st.download_button(
        "Download ChronoStress_Data.xlsx",
        workbook_bytes,
        file_name="ChronoStress_Data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    st.markdown("#### Export Column Dictionary")
    st.dataframe(datasets["Data Dictionary"], hide_index=True, use_container_width=True)
    st.warning("For a live study, researcher-wide exports should sit behind separate role-based authentication and an approved data-management policy.")


def render_participant_management() -> None:
    if not _require_admin():
        return
    section_heading("Participants", "Participant Management")
    expected_prompts = 21 * 3
    datasets = research_datasets(all_study_frames())
    participants = datasets["Participants"]
    daily = datasets["Daily Assessments"]
    if participants.empty:
        st.info("No participants are enrolled yet.")
        return

    completed = (
        daily.groupby("participant_id")["assessment_id"].nunique()
        if not daily.empty
        else pd.Series(dtype="int64")
    )
    management = participants.copy()
    management["Completed Prompts"] = (
        management["participant_id"].map(completed).fillna(0).astype(int)
    )
    management["Expected Prompts"] = expected_prompts
    management["Completion %"] = (
        management["Completed Prompts"] / expected_prompts * 100
    ).round(1)

    def adherence_status(percentage: float) -> str:
        if percentage < 25:
            return "🔴 Needs Follow-up"
        if percentage < 75:
            return "🟡 In Progress"
        if percentage < 100:
            return "🟢 Nearly Complete"
        return "✅ Completed"

    management["Status"] = management["Completion %"].apply(adherence_status)
    management["Progress"] = management["Completion %"]
    management = management.sort_values(
        ["Completion %", "participant_id"], ascending=[True, True]
    ).reset_index(drop=True)
    st.dataframe(
        management,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Progress": st.column_config.ProgressColumn(
                "Progress",
                min_value=0,
                max_value=100,
                format="%.1f%%",
            ),
            "Completion %": st.column_config.NumberColumn(
                "Completion %",
                format="%.1f%%",
            ),
        },
    )


def render_study_progress() -> None:
    if not _require_admin():
        return
    section_heading("Progress", "Study Progress")
    datasets = research_datasets(all_study_frames())
    daily = datasets["Daily Assessments"]
    if daily.empty:
        st.info("No completed assessments yet.")
        return
    progress = (
        daily.groupby("participant_id")
        .agg(
            completed_assessments=("assessment_id", "count"),
            completed_days=("day_number", "nunique"),
            latest_day=("day_number", "max"),
            latest_prompt=("prompt_number", "max"),
            last_completed_time=("assessment_datetime", "max"),
        )
        .reset_index()
    )
    st.dataframe(progress, hide_index=True, use_container_width=True)


def render_raw_events() -> None:
    if not _require_admin():
        return
    section_heading("Raw Events", "Debug and reproducibility log")
    raw = research_datasets(all_study_frames())["Raw Events"]
    if raw.empty:
        st.info("No raw events are available yet.")
        return
    st.dataframe(raw, hide_index=True, use_container_width=True)


def render_protocol() -> None:
    section_heading("Study information", "Protocol and support")
    st.markdown("#### Daily protocol")
    st.write("Wear the connected device continuously, complete prompts near their scheduled time, and avoid counting during timing tasks.")
    st.markdown("#### Safety")
    st.write("Never complete an assessment while driving, crossing a road, exercising intensely, or in another unsafe setting.")
    st.markdown("#### Technical support")
    st.write("In a live deployment, the approved study email, withdrawal contact, ethics reference, and adverse-event pathway belong here.")
    st.info("This research application does not provide diagnosis, monitoring, or treatment advice.")

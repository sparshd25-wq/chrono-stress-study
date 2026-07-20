"""Participant dashboard, longitudinal analytics, and data export."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from components.ui import banner, section_heading, wearable_status
from config import DAILY_ASSESSMENT_TARGET
from database.repository import participant_frames, study_summary
from utils.analytics import (
    add_derived_assessment_metrics,
    assessment_summary,
    correlation_chart,
    explode_stroop_trials,
    flatten_task_metadata,
    multi_trend,
    trend_chart,
)
from utils.exports import csv_archive, excel_workbook, json_export


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
            st.caption(f"Last sync: {str(latest.get('recorded_at', 'Not available'))[:16].replace('T', ' ')} UTC")
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
        display["submitted_at"] = pd.to_datetime(display["submitted_at"]).dt.strftime("%d %b, %H:%M")
        display.columns = ["Submitted", "Activity", "Stress", "Mental fatigue", "Workload"]
        st.dataframe(display, hide_index=True, use_container_width=True)


def render_analytics(participant_id: str) -> None:
    frames = participant_frames(participant_id)
    assessments = add_derived_assessment_metrics(frames["assessments"])
    wearable = frames["wearable"].copy()
    tasks = frames["time_tasks"].copy()
    section_heading("Longitudinal view", "Participant analytics", "Within-person patterns become more informative as daily observations accumulate.")

    if not wearable.empty:
        wearable["recorded_at"] = pd.to_datetime(wearable["recorded_at"], utc=True)
        week = wearable.tail(7)
        metric_columns = st.columns(4)
        metric_columns[0].metric("7-day stress", f"{week['stress_score'].mean():.1f}")
        metric_columns[1].metric("7-day HRV", f"{week['hrv'].mean():.1f} ms")
        metric_columns[2].metric("7-day sleep", f"{week['sleep_hours'].mean():.1f} h")
        metric_columns[3].metric("Wearable days", f"{len(wearable)}")

    tabs = st.tabs(["Stress & recovery", "Time perception", "Associations", "Task performance"])
    with tabs[0]:
        if wearable.empty:
            st.info("Wearable observations are not available yet.")
        else:
            left, right = st.columns(2)
            left.plotly_chart(trend_chart(wearable, "recorded_at", "stress_score", "Stress"), use_container_width=True, config={"displayModeBar": False})
            right.plotly_chart(trend_chart(wearable, "recorded_at", "hrv", "HRV"), use_container_width=True, config={"displayModeBar": False})
            left.plotly_chart(trend_chart(wearable, "recorded_at", "sleep_hours", "Sleep"), use_container_width=True, config={"displayModeBar": False})
            right.plotly_chart(trend_chart(wearable, "recorded_at", "recovery_score", "Recovery"), use_container_width=True, config={"displayModeBar": False})
    with tabs[1]:
        if tasks.empty:
            st.info("Complete a daily assessment to begin the time-distortion series.")
        else:
            tasks["recorded_at"] = pd.to_datetime(tasks["recorded_at"], utc=True)
            task_choice = st.selectbox("Task", sorted(tasks["task_type"].unique()))
            subset = tasks[tasks["task_type"] == task_choice]
            st.plotly_chart(trend_chart(subset, "recorded_at", "signed_error", "Signed error"), use_container_width=True, config={"displayModeBar": False})
            st.dataframe(subset[["recorded_at", "target_seconds", "response_seconds", "signed_error", "absolute_error"]], hide_index=True, use_container_width=True)
    with tabs[2]:
        if tasks.empty or wearable.empty:
            st.info("At least one behavioural assessment and wearable observation are needed for association plots.")
        else:
            reproduction = tasks[tasks["task_type"] == "time_reproduction"].copy()
            reproduction["day"] = pd.to_datetime(reproduction["recorded_at"], utc=True).dt.date
            physiology = wearable.copy()
            physiology["day"] = physiology["recorded_at"].dt.date
            merged = reproduction.merge(physiology, on="day", how="inner")
            if merged.empty:
                st.info("No same-day wearable and task observations are available yet.")
            else:
                selectors = {
                    "Stress score": "stress_score",
                    "HRV": "hrv",
                    "Sleep duration": "sleep_hours",
                }
                label = st.selectbox("Physiological predictor", selectors)
                st.plotly_chart(correlation_chart(merged, selectors[label], "signed_error", label), use_container_width=True, config={"displayModeBar": False})
                if len(merged) < 3:
                    st.caption("Trend modelling appears after three matched daily observations.")
    with tabs[3]:
        cognitive = frames["cognitive"]
        if cognitive.empty:
            st.info("Colour-word task performance will appear after your first assessment.")
        else:
            left, right = st.columns(2)
            left.plotly_chart(trend_chart(cognitive, "recorded_at", "accuracy", "Accuracy"), use_container_width=True, config={"displayModeBar": False})
            right.plotly_chart(trend_chart(cognitive, "recorded_at", "mean_reaction_ms", "Reaction time"), use_container_width=True, config={"displayModeBar": False})


def render_export(participant_id: str) -> None:
    section_heading("Data portability", "Export participant record")
    st.write(
        "Export all records linked to this participant ID. Files include profile, consent, EMA, "
        "wearable observations, timing tasks, and cognitive results."
    )
    frames = participant_frames(participant_id)
    # The raw tables keep task metadata and Stroop trials as one JSON string
    # per row — fine for the database, unusable in a spreadsheet. These three
    # add flattened/wide versions on top, without dropping the raw tables, so
    # both full-fidelity and analysis-ready shapes are in every export.
    export_frames = {
        **frames,
        "time_tasks_flat": flatten_task_metadata(frames["time_tasks"]),
        "stroop_trials": explode_stroop_trials(frames["cognitive"]),
        "assessment_summary": assessment_summary(frames),
    }
    row_count = sum(len(frame) for frame in export_frames.values())
    st.metric("Rows available", row_count)
    st.caption(f"Generated locally from SQLite • Participant {participant_id} • {datetime.now().strftime('%d %b %Y %H:%M')}")
    st.caption(
        "`assessment_summary` is one row per assessment with every task's result "
        "joined on — the shape most pilot analyses will actually run against. "
        "`time_tasks_flat` and `stroop_trials` unpack the per-task and per-trial "
        "detail. Raw normalized tables are included too, for full fidelity."
    )
    csv_col, excel_col, json_col = st.columns(3)
    csv_col.download_button(
        "Download CSV bundle", csv_archive(export_frames),
        file_name=f"{participant_id}_study_data_csv.zip", mime="application/zip",
        use_container_width=True,
    )
    excel_col.download_button(
        "Download Excel", excel_workbook(export_frames),
        file_name=f"{participant_id}_study_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    json_col.download_button(
        "Download JSON", json_export(export_frames),
        file_name=f"{participant_id}_study_data.json", mime="application/json",
        use_container_width=True,
    )
    st.warning("For a live study, researcher-wide exports should sit behind separate role-based authentication and an approved data-management policy.")


def render_protocol() -> None:
    section_heading("Study information", "Protocol and support")
    st.markdown("#### Daily protocol")
    st.write("Wear the connected device continuously, complete prompts near their scheduled time, and avoid counting during timing tasks.")
    st.markdown("#### Safety")
    st.write("Never complete an assessment while driving, crossing a road, exercising intensely, or in another unsafe setting.")
    st.markdown("#### Technical support")
    st.write("In a live deployment, the approved study email, withdrawal contact, ethics reference, and adverse-event pathway belong here.")
    st.info("This research application does not provide diagnosis, monitoring, or treatment advice.")

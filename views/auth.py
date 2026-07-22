"""Welcome, consent, registration, and participant access views."""

from __future__ import annotations

from datetime import datetime, timezone
import re

import streamlit as st

from components.ui import banner, section_heading
from config import STUDY_DURATION_DAYS
from database.repository import (
    create_participant,
    get_participant,
    participant_exists,
    save_consent,
)
from services.auth import hash_access_code, verify_access_code
from services.wearables import DemoWearableProvider


def _clear_participant_scoped_state() -> None:
    """Remove in-progress assessment data before binding another participant."""
    preserved = {
        "authenticated",
        "participant_id",
        "authenticated_participant_id",
        "participant_record",
        "auth_view",
        "active_page",
    }
    for key in list(st.session_state):
        if key not in preserved:
            del st.session_state[key]


def _sign_in(participant: dict) -> None:
    participant_id = participant["participant_id"]
    _clear_participant_scoped_state()
    st.session_state.participant_id = participant_id
    st.session_state.authenticated_participant_id = participant_id
    st.session_state.participant_record = participant
    st.session_state.authenticated = True
    st.session_state.active_page = "Dashboard"
    st.session_state.assessment_active = False
    st.session_state.assessment_step = 1


def render_welcome() -> None:
    banner(
        "ChronoStress Study",
        "A longitudinal research study of physiological stress and everyday time perception.",
    )
    st.markdown("### Your daily research companion")
    st.write(
        "Across the study, you will complete short daily check-ins and cognitive tasks while "
        "a supported wearable records physiology. Your participation helps researchers understand "
        "how longer-term stress relates to the way time is experienced in daily life."
    )
    columns = st.columns(3)
    columns[0].metric("Study period", f"{STUDY_DURATION_DAYS} days")
    columns[1].metric("Daily prompts", "Up to 3")
    columns[2].metric("Assessment", "5-7 min")
    st.info("This is a cognitive science research platform, not a diagnostic or mental health service.")
    left, right = st.columns(2)
    if left.button("I am a new participant", type="primary", use_container_width=True):
        st.session_state.auth_view = "consent"
        st.rerun()
    if right.button("Participant sign in", use_container_width=True):
        st.session_state.auth_view = "login"
        st.rerun()


def render_consent() -> None:
    section_heading("Participant information", "Informed consent")
    st.write(
        "Please read this summary before deciding whether to join. In a live study, the approved "
        "participant information sheet and university ethics reference would be inserted here."
    )
    with st.container(border=True):
        st.markdown("**What participation involves**")
        st.write(
            "For 14-30 days, you will wear a compatible device and complete repeated questionnaires, "
            "time-perception tasks, and a brief colour-word task."
        )
        st.markdown("**Data collected**")
        st.write(
            "Responses, reaction times, task errors, and wearable measures such as heart rate, HRV, "
            "resting heart rate, sleep, activity, and recovery may be stored with your participant ID."
        )
        st.markdown("**Privacy and withdrawal**")
        st.write(
            "The app uses a study ID rather than your name. Participation is voluntary. You may stop "
            "at any time and contact the research team about withdrawal under the approved protocol."
        )
        st.markdown("**Possible inconvenience**")
        st.write("Some prompts may interrupt routine activities. Do not complete tasks while driving or when unsafe.")
    participation = st.checkbox("I have read the information above and voluntarily agree to participate.")
    privacy = st.checkbox("I understand what data will be collected and how it will be used for research.")
    age_confirmation = st.checkbox("I confirm that I am eligible under the study's approved age criteria.")
    left, right = st.columns(2)
    if left.button("Back", use_container_width=True):
        st.session_state.auth_view = "welcome"
        st.rerun()
    if right.button(
        "Continue to registration",
        type="primary",
        disabled=not (participation and privacy and age_confirmation),
        use_container_width=True,
    ):
        st.session_state.pending_consent = True
        st.session_state.auth_view = "register"
        st.rerun()


def render_registration() -> None:
    section_heading("Study enrolment", "Participant registration", "Use the ID supplied by the research team, or create one for this demonstration.")
    with st.form("registration_form"):
        identity_left, identity_right = st.columns(2)
        participant_id = identity_left.text_input("Participant ID", placeholder="e.g. CST-1042").strip().upper()
        access_code = identity_right.text_input("Private access code", type="password", help="Use at least 6 characters.")
        age = identity_left.number_input("Age", 18, 100, 21)
        gender = identity_right.selectbox("Gender", ("Woman", "Man", "Non-binary", "Prefer to self-describe", "Prefer not to say"))
        occupation = identity_left.text_input("Occupation", placeholder="Student, researcher, engineer...")
        academic_status = identity_right.selectbox("Academic status", ("Not currently studying", "Undergraduate", "Postgraduate", "Doctoral", "Other"))
        st.markdown("#### Health and routine")
        health_left, health_right = st.columns(2)
        medication = health_left.text_input("Regular medication", placeholder="None, or describe")
        sleep_disorders = health_right.selectbox("Diagnosed sleep disorder", ("No", "Yes", "Prefer not to say"))
        diagnosis = health_left.text_input("Mental health diagnosis (optional)")
        coffee = health_right.number_input("Caffeinated drinks per day", 0, 20, 2)
        smoking = health_left.selectbox("Smoking", ("Never", "Former", "Occasional", "Daily", "Prefer not to say"))
        alcohol = health_right.selectbox("Alcohol use", ("None", "Monthly or less", "Weekly", "Most days", "Prefer not to say"))
        average_sleep = st.slider("Average sleep duration", 3.0, 12.0, 7.0, .25, format="%.2f hours")
        submitted = st.form_submit_button("Create participant account", type="primary", use_container_width=True)
    if submitted:
        errors = []
        if not re.fullmatch(r"[A-Z0-9-]{4,20}", participant_id):
            errors.append("Participant ID must use 4-20 letters, numbers, or hyphens.")
        if len(access_code) < 6:
            errors.append("Access code must contain at least 6 characters.")
        if not occupation.strip():
            errors.append("Please enter an occupation or academic role.")
        if participant_exists(participant_id):
            errors.append("That participant ID already exists. Sign in instead.")
        if errors:
            for error in errors:
                st.error(error)
            return
        create_participant(
            {
                "participant_id": participant_id,
                "access_code_hash": hash_access_code(access_code),
                "age": age,
                "gender": gender,
                "occupation": occupation.strip(),
                "academic_status": academic_status,
                "medication": medication.strip() or "None reported",
                "sleep_disorders": sleep_disorders,
                "mental_health_diagnosis": diagnosis.strip() or None,
                "coffee_per_day": coffee,
                "smoking": smoking,
                "alcohol": alcohol,
                "average_sleep_hours": average_sleep,
                "enrolled_at": datetime.now(timezone.utc).isoformat(),
                "study_days": STUDY_DURATION_DAYS,
            }
        )
        participant = get_participant(participant_id)
        save_consent(participant_id)
        DemoWearableProvider().sync(participant_id)
        _sign_in(participant)
        st.rerun()
    if st.button("Back to consent"):
        st.session_state.auth_view = "consent"
        st.rerun()


def render_login() -> None:
    section_heading("Participant access", "Welcome back")
    st.write("Use your participant ID and private access code to continue the study.")
    with st.form("login_form"):
        participant_id = st.text_input("Participant ID").strip().upper()
        access_code = st.text_input("Access code", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submitted:
        participant = get_participant(participant_id)
        if participant is None:
            if not re.fullmatch(r"[A-Z0-9-]{4,20}", participant_id) or len(access_code) < 6:
                st.error("Invalid Participant ID or Access Code.")
                return
            create_participant(
                {
                    "participant_id": participant_id,
                    "access_code_hash": hash_access_code(access_code),
                    "age": 18,
                    "gender": "Prefer not to say",
                    "occupation": "Not collected",
                    "academic_status": "Other",
                    "medication": "Not collected",
                    "sleep_disorders": "Prefer not to say",
                    "mental_health_diagnosis": None,
                    "coffee_per_day": 0,
                    "smoking": "Prefer not to say",
                    "alcohol": "Prefer not to say",
                    "average_sleep_hours": 7.0,
                    "enrolled_at": datetime.now(timezone.utc).isoformat(),
                    "study_days": STUDY_DURATION_DAYS,
                }
            )
            participant = get_participant(participant_id)
        elif not verify_access_code(access_code, participant["access_code_hash"]):
            st.error("Invalid Participant ID or Access Code.")
            return

        if participant:
            DemoWearableProvider().sync(participant_id)
            _sign_in(participant)
            st.rerun()
        st.error("Invalid Participant ID or Access Code.")
    if st.button("Back", use_container_width=True):
        st.session_state.auth_view = "welcome"
        st.rerun()


def render_authentication() -> None:
    view = st.session_state.get("auth_view", "welcome")
    views = {
        "welcome": render_welcome,
        "consent": render_consent,
        "register": render_registration,
        "login": render_login,
    }
    views.get(view, render_welcome)()

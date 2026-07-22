"""ChronoStress longitudinal cognitive science research platform."""

from __future__ import annotations

import streamlit as st

from components.ui import load_css
from database.repository import get_participant, initialise_database
from views.assessment import cancel_assessment, render_assessment
from views.auth import render_authentication
from views.dashboard import (
    render_admin_dashboard,
    render_analytics,
    render_dashboard,
    render_export,
    render_participant_management,
    render_protocol,
    render_raw_events,
    render_study_progress,
)


def initialise_session() -> None:
    defaults = {
        "authenticated": False,
        "participant_id": None,
        "authenticated_participant_id": None,
        "user_role": None,
        "auth_view": "welcome",
        "active_page": "Dashboard",
        "assessment_active": False,
        "assessment_step": 1,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def sign_out() -> None:
    for key in list(st.session_state):
        del st.session_state[key]
    st.rerun()


def authenticated_identity() -> tuple[str | None, str | None]:
    """Return the validated role and participant ID for this session."""
    if not st.session_state.get("authenticated"):
        return None, None
    role = st.session_state.get("user_role")
    if role == "admin":
        return "admin", None
    participant_id = st.session_state.get("authenticated_participant_id")
    if role != "participant" or not participant_id:
        return None, None
    participant = get_participant(participant_id)
    if participant is None:
        for key in list(st.session_state):
            del st.session_state[key]
        return None, None
    st.session_state.participant_id = participant["participant_id"]
    st.session_state.participant_record = participant
    return "participant", participant["participant_id"]


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("## ChronoStress")
        st.caption("LONGITUDINAL STUDY PORTAL")
        st.divider()
        role = st.session_state.get("user_role")
        if role == "participant" and st.session_state.assessment_active:
            st.info(f"Assessment in progress - Step {st.session_state.assessment_step} of 7")
            if st.button("Leave assessment", use_container_width=True):
                cancel_assessment()
                st.rerun()
            return "Daily Assessment"

        if role == "admin":
            pages = (
                "Dashboard",
                "Analytics",
                "Data Export",
                "Participant Management",
                "Study Progress",
                "Raw Events",
                "Study Protocol",
            )
        else:
            pages = ("Dashboard", "Daily Assessment", "Study Protocol")
        current = st.session_state.active_page
        index = pages.index(current) if current in pages else 0
        page = st.radio("Navigation", pages, index=index, label_visibility="collapsed")
        st.session_state.active_page = page
        st.divider()
        if role == "admin":
            st.caption(f"SIGNED IN AS ADMIN\n\n{st.session_state.get('admin_username')}")
        else:
            st.caption(f"SIGNED IN AS\n\n{st.session_state.authenticated_participant_id}")
        if st.button("Sign out", use_container_width=True):
            sign_out()
        return page


def main() -> None:
    st.set_page_config(
        page_title="ChronoStress Study",
        page_icon=":material/schedule:",
        layout="wide",
        initial_sidebar_state="auto",
    )
    initialise_database()
    initialise_session()
    load_css()

    role, participant_id = authenticated_identity()
    if role is None:
        st.session_state.authenticated = False
        render_authentication()
        return

    page = render_sidebar()
    if role == "participant" and page in {
        "Analytics",
        "Data Export",
        "Participant Management",
        "Study Progress",
        "Raw Events",
    }:
        st.error("You do not have permission to access this page.")
        return
    if page == "Dashboard" and role == "admin":
        render_admin_dashboard()
    elif page == "Dashboard":
        render_dashboard(participant_id)
    elif page == "Daily Assessment" and role == "participant":
        render_assessment(participant_id)
    elif page == "Analytics" and role == "admin":
        render_analytics()
    elif page == "Data Export" and role == "admin":
        render_export()
    elif page == "Participant Management" and role == "admin":
        render_participant_management()
    elif page == "Study Progress" and role == "admin":
        render_study_progress()
    elif page == "Raw Events" and role == "admin":
        render_raw_events()
    else:
        render_protocol()


if __name__ == "__main__":
    main()

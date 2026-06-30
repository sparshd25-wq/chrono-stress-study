"""ChronoStress longitudinal cognitive science research platform."""

from __future__ import annotations

import streamlit as st

from components.ui import load_css
from database.repository import initialise_database
from views.assessment import cancel_assessment, render_assessment
from views.auth import render_authentication
from views.dashboard import render_analytics, render_dashboard, render_export, render_protocol


def initialise_session() -> None:
    defaults = {
        "authenticated": False,
        "participant_id": None,
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


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("## ChronoStress")
        st.caption("LONGITUDINAL STUDY PORTAL")
        st.divider()
        if st.session_state.assessment_active:
            st.info(f"Assessment in progress • Step {st.session_state.assessment_step} of 8")
            if st.button("Leave assessment", use_container_width=True):
                cancel_assessment()
                st.rerun()
            return "Daily Assessment"

        pages = ("Dashboard", "Daily Assessment", "Analytics", "Data Export", "Study Protocol")
        current = st.session_state.active_page
        index = pages.index(current) if current in pages else 0
        page = st.radio("Navigation", pages, index=index, label_visibility="collapsed")
        st.session_state.active_page = page
        st.divider()
        st.caption(f"SIGNED IN AS\n\n{st.session_state.participant_id}")
        if st.button("Sign out", use_container_width=True):
            sign_out()
        return page


def main() -> None:
    st.set_page_config(
        page_title="ChronoStress Study",
        page_icon=":material/schedule:",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    initialise_database()
    initialise_session()
    load_css()

    if not st.session_state.authenticated:
        render_authentication()
        return

    participant_id = st.session_state.participant_id
    page = render_sidebar()
    if page == "Dashboard":
        render_dashboard(participant_id)
    elif page == "Daily Assessment":
        render_assessment(participant_id)
    elif page == "Analytics":
        render_analytics(participant_id)
    elif page == "Data Export":
        render_export(participant_id)
    else:
        render_protocol()


if __name__ == "__main__":
    main()

"""Shared Streamlit presentation helpers."""

from __future__ import annotations

import streamlit as st


def load_css() -> None:
    """Load the study design system."""
    st.markdown(
        """
        <style>
        :root {
            color-scheme: light;
            --ink: #152238;
            --muted: #64748b;
            --blue: #1769aa;
            --teal: #0f8b8d;
            --line: #d9e2ec;
            --surface: #ffffff;
            --soft: #f3f7fa;
        }

        .stApp {
            background: #f7fafc;
            color: var(--ink);
        }

        [data-testid="stAppViewContainer"] {
            background: #f7fafc;
            color: var(--ink);
        }

        [data-testid="stWidgetLabel"] p,
        [data-testid="stCheckbox"] label p,
        [data-testid="stRadio"] label p,
        [data-testid="stMetricLabel"] p,
        [data-testid="stMetricValue"] {
            color: var(--ink) !important;
        }

        .block-container {
            max-width: 1120px;
            padding-top: 5.5rem;
            padding-bottom: 4rem;
        }

        h1, h2, h3 {
            color: var(--ink);
            letter-spacing: 0;
        }

        [data-testid="stSidebar"] {
            background: #102a43;
        }

        [data-testid="stSidebar"] * {
            color: #f4f8fb;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            padding: 0.45rem 0.6rem;
            border-radius: 6px;
        }

        /* Keep sidebar nav labels white — overrides the global ink-color
           rule above, which would otherwise make radio option text
           dark-on-dark inside the dark navy sidebar. */
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
        [data-testid="stSidebar"] [data-testid="stRadio"] label p {
            color: #f4f8fb !important;
        }

        [data-testid="stMetric"] {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1rem 1.1rem;
            min-height: 118px;
            box-shadow: 0 2px 10px rgba(21, 34, 56, 0.04);
        }

        div.stButton > button,
        div.stDownloadButton > button {
            border-radius: 6px;
            min-height: 42px;
            font-weight: 650;
        }

        div.stButton > button[kind="primary"] {
            background: #1769aa;
            border-color: #1769aa;
            color: #ffffff;
        }

        div.stButton > button[kind="primary"] p {
            color: #ffffff !important;
        }

        div.stButton > button[kind="secondary"] {
            background: #ffffff;
            border-color: var(--line);
            color: var(--ink);
        }

        div.stButton > button[kind="secondary"] p {
            color: var(--ink) !important;
        }

        .study-banner {
            background: linear-gradient(115deg, #0f4c75, #0f8b8d);
            color: white;
            border-radius: 8px;
            padding: 1.5rem 1.75rem;
            margin-bottom: 1.25rem;
        }

        .study-banner h1,
        .study-banner h2,
        .study-banner p {
            color: white;
            margin: 0;
        }

        .study-banner p {
            margin-top: 0.45rem;
            opacity: 0.9;
        }

        .eyebrow {
            color: #0f8b8d;
            font-size: 0.78rem;
            font-weight: 750;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .research-card {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1.2rem 1.3rem;
            margin-bottom: 0.8rem;
        }

        .status-dot {
            display: inline-block;
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background: #20a37a;
            margin-right: 0.4rem;
        }

        .task-stage {
            min-height: 250px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            background: #ffffff;
            border: 1px solid var(--line);
            border-radius: 8px;
            margin: 1rem 0;
        }

        .fixation {
            font-size: 4rem;
            color: #152238;
        }

        .stimulus-circle {
            width: 128px;
            height: 128px;
            border-radius: 50%;
            background: #1976d2;
            box-shadow: 0 0 0 10px rgba(25, 118, 210, 0.08);
        }

        .stroop-word {
            font-size: 3.4rem;
            font-weight: 800;
            letter-spacing: 0;
        }

        .fine-print {
            color: var(--muted);
            font-size: 0.82rem;
            line-height: 1.55;
        }

        @media (max-width: 700px) {
            .block-container {
                padding: 5rem 0.8rem 3rem;
            }

            .study-banner {
                padding: 1.15rem;
            }

            .stroop-word {
                font-size: 2.35rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def banner(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="study-banner"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def section_heading(
    kicker: str,
    title: str,
    description: str = "",
) -> None:
    st.markdown(
        f'<div class="eyebrow">{kicker}</div>',
        unsafe_allow_html=True,
    )
    st.subheader(title)

    if description:
        st.caption(description)


def assessment_header(
    step: int,
    total: int,
    title: str,
    minutes: str = "2-4 min",
) -> None:
    left, right = st.columns([4, 1])
    left.caption(f"DAILY ASSESSMENT | STEP {step} OF {total}")
    right.caption(f"About {minutes}")
    st.progress(step / total)
    st.header(title)


def wearable_status(provider: str = "Oura demo") -> None:
    st.markdown(
        (
            '<span class="status-dot"></span>'
            f"<strong>{provider}</strong> synced for demonstration"
        ),
        unsafe_allow_html=True,
    )

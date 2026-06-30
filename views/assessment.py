"""Resumable daily EMA and behavioural assessment workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import random
import time
from typing import Any

import numpy as np
import streamlit as st
import streamlit_hotkeys as hotkeys

from components.ui import assessment_header
from config import (
    ACTIVITY_OPTIONS,
    EVENT_DURATIONS,
    EVENT_TYPES,
    LOCATION_OPTIONS,
    WORKLOAD_OPTIONS,
)
from database.repository import save_assessment


TOTAL_STEPS = 8
STROOP_COLORS = {
    "Red": "#d64545",
    "Blue": "#1976d2",
}
STROOP_KEY_MAP = {"ArrowLeft": "Blue", "ArrowRight": "Red"}
STROOP_TRIAL_COUNT = 12
STROOP_TRIAL_DURATION_SECONDS = 1.5  # each trial auto-advances after this long, response or not


def start_assessment() -> None:
    """Create a fresh in-session assessment record."""
    for key in list(st.session_state):
        if key.startswith("task_") or key.startswith("stroop_"):
            del st.session_state[key]
    st.session_state.assessment_active = True
    st.session_state.assessment_step = 1
    st.session_state.assessment_started_at = datetime.now(timezone.utc).isoformat()
    st.session_state.assessment_answers = {}
    st.session_state.time_task_results = []
    st.session_state.cognitive_result = None


def cancel_assessment() -> None:
    st.session_state.assessment_active = False
    st.session_state.assessment_step = 1
    st.session_state.active_page = "Dashboard"


def next_step() -> None:
    st.session_state.assessment_step += 1
    st.rerun()


def previous_step() -> None:
    st.session_state.assessment_step = max(1, st.session_state.assessment_step - 1)
    st.rerun()


def navigation_back() -> None:
    if st.button("Back", use_container_width=True):
        previous_step()


def render_context() -> None:
    assessment_header(1, TOTAL_STEPS, "Current context")
    st.write("Tell us about the setting around this assessment.")
    answers = st.session_state.assessment_answers
    with st.form("context_form"):
        left, right = st.columns(2)
        location = left.selectbox("Current location", LOCATION_OPTIONS)
        activity = right.selectbox("Current activity", ACTIVITY_OPTIONS)
        sleep_hours = left.number_input(
            "Hours slept last night", 0.0, 16.0, float(answers.get("sleep_hours", 7.0)), .25
        )
        caffeine_recent = right.radio(
            "Caffeine in the last two hours?", ("No", "Yes"), horizontal=True
        )
        medication_today = left.radio(
            "Medication taken today?", ("No", "Yes"), horizontal=True
        )
        workload = right.select_slider("Current workload", options=WORKLOAD_OPTIONS, value="Moderate")
        submitted = st.form_submit_button("Continue", type="primary", use_container_width=True)
    if submitted:
        answers.update(
            location=location,
            activity=activity,
            sleep_hours=sleep_hours,
            caffeine_recent=int(caffeine_recent == "Yes"),
            medication_today=int(medication_today == "Yes"),
            workload=workload,
        )
        next_step()


def _vas(label: str, help_text: str, default: int) -> int:
    return st.slider(label, 0, 100, default, help=help_text)


def render_scales() -> None:
    assessment_header(2, TOTAL_STEPS, "Current experience")
    st.write("Move each marker to the point that best reflects how you feel right now.")
    answers = st.session_state.assessment_answers
    with st.form("scales_form"):
        stress = _vas("How stressed do you feel?", "0 = not at all, 100 = extremely", int(answers.get("stress", 50)))
        fatigue = _vas("How mentally exhausted are you?", "0 = not at all, 100 = extremely", int(answers.get("mental_fatigue", 50)))
        arousal = _vas("How emotionally activated or overwhelmed are you?", "0 = calm, 100 = extremely activated", int(answers.get("emotional_arousal", 50)))
        control = _vas("How much control do you currently feel?", "0 = no control, 100 = complete control", int(answers.get("perceived_control", 50)))
        anxiety = _vas("How anxious do you currently feel?", "0 = not at all, 100 = extremely", int(answers.get("anxiety", 40)))
        left, right = st.columns(2)
        back = left.form_submit_button("Back", use_container_width=True)
        submitted = right.form_submit_button("Continue", type="primary", use_container_width=True)
    if back:
        previous_step()
    if submitted:
        answers.update(
            stress=stress,
            mental_fatigue=fatigue,
            emotional_arousal=arousal,
            perceived_control=control,
            anxiety=anxiety,
        )
        next_step()


def render_event() -> None:
    assessment_header(3, TOTAL_STEPS, "Since the previous assessment")
    answers = st.session_state.assessment_answers
    happened = st.radio(
        "Has anything stressful happened since your previous assessment?",
        ("No", "Yes"), horizontal=True, key="event_happened",
    )
    with st.form("event_form"):
        if happened == "Yes":
            left, right = st.columns(2)
            event_type = left.selectbox("Type of event", EVENT_TYPES)
            event_duration = right.selectbox("How long did it last?", EVENT_DURATIONS)
            event_upset = st.slider("How emotionally upsetting was it?", 0, 100, 50)
            event_expected = st.radio("Did you expect the event?", ("No", "Yes"), horizontal=True)
            event_control = st.slider("How much control did you have?", 0, 100, 50)
        else:
            event_type = event_duration = event_upset = event_expected = event_control = None
        left, right = st.columns(2)
        back = left.form_submit_button("Back", use_container_width=True)
        submitted = right.form_submit_button("Continue", type="primary", use_container_width=True)
    if back:
        previous_step()
    if submitted:
        answers.update(
            stressful_event=int(happened == "Yes"),
            event_type=event_type,
            event_duration=event_duration,
            event_upset=event_upset,
            event_expected=int(event_expected == "Yes") if event_expected else None,
            event_control=event_control,
        )
        next_step()


def _timed_stage(content: str) -> None:
    st.markdown(f'<div class="task-stage">{content}</div>', unsafe_allow_html=True)


def render_reproduction() -> None:
    assessment_header(4, TOTAL_STEPS, "Time reproduction", "Under 1 min")
    phase = st.session_state.get("task_reproduction_phase", "ready")

    if phase == "ready":
        st.write("Watch the circle carefully. After it disappears, reproduce how long it was visible.")
        _timed_stage("<div><strong>Keep your attention on the centre.</strong></div>")
        if st.button("Begin task", type="primary", use_container_width=True):
            st.session_state.task_reproduction_target = random.uniform(5.0, 10.0)
            st.session_state.task_reproduction_phase = "fixation"
            st.session_state.task_phase_started = time.monotonic()
            st.rerun()
        navigation_back()
        return

    elapsed = time.monotonic() - st.session_state.task_phase_started
    if phase == "fixation":
        _timed_stage('<div class="fixation">+</div>')
        if elapsed >= 1.25:
            st.session_state.task_reproduction_phase = "stimulus"
            st.session_state.task_phase_started = time.monotonic()
        time.sleep(.08)
        st.rerun()

    if phase == "stimulus":
        _timed_stage('<div class="stimulus-circle"></div>')
        if elapsed >= st.session_state.task_reproduction_target:
            st.session_state.task_reproduction_phase = "respond"
            st.rerun()
        time.sleep(.08)
        st.rerun()

    if phase == "respond":
        _timed_stage("<div><strong>Reproduce the interval</strong><br><small>The clock will remain hidden.</small></div>")
        st.caption("Select Start, wait for the remembered duration, then select Stop.")
        if st.button("Start reproduction", type="primary", use_container_width=True):
            st.session_state.task_reproduction_started = time.monotonic()
            st.session_state.task_reproduction_phase = "recording"
            st.rerun()
        return

    if phase == "recording":
        _timed_stage("<div><strong>Timing in progress</strong><br><small>Stop when the remembered interval has passed.</small></div>")
        if st.button("Stop reproduction", type="primary", use_container_width=True):
            response = time.monotonic() - st.session_state.task_reproduction_started
            target = st.session_state.task_reproduction_target
            signed = response - target
            st.session_state.time_task_results.append(
                {
                    "task_type": "time_reproduction",
                    "target_seconds": target,
                    "response_seconds": response,
                    "signed_error": signed,
                    "absolute_error": abs(signed),
                }
            )
            st.session_state.task_reproduction_phase = "done"
            st.rerun()
        return

    _timed_stage("<div><strong>Response recorded</strong><br><small>Your result remains blinded until submission.</small></div>")
    if st.button("Continue", type="primary", use_container_width=True):
        next_step()


def render_prospective() -> None:
    assessment_header(5, TOTAL_STEPS, "Prospective timing", "About 1 min")
    phase = st.session_state.get("task_prospective_phase", "ready")
    if phase == "ready":
        st.write("Without counting, press Finish when you believe 30 seconds have elapsed.")
        _timed_stage("<div><strong>The display will not show elapsed time.</strong></div>")
        if st.button("Start 30-second task", type="primary", use_container_width=True):
            st.session_state.task_prospective_started = time.monotonic()
            st.session_state.task_prospective_phase = "recording"
            st.rerun()
        navigation_back()
        return
    if phase == "recording":
        _timed_stage("<div><strong>Timing in progress</strong><br><small>Respond when you think 30 seconds have passed.</small></div>")
        if st.button("Finish", type="primary", use_container_width=True):
            response = time.monotonic() - st.session_state.task_prospective_started
            signed = response - 30.0
            st.session_state.time_task_results.append(
                {
                    "task_type": "prospective_timing",
                    "target_seconds": 30.0,
                    "response_seconds": response,
                    "signed_error": signed,
                    "absolute_error": abs(signed),
                }
            )
            st.session_state.task_prospective_phase = "done"
            st.rerun()
        return
    _timed_stage("<div><strong>Response recorded</strong></div>")
    if st.button("Continue", type="primary", use_container_width=True):
        next_step()


def render_estimation() -> None:
    assessment_header(6, TOTAL_STEPS, "Time estimation", "Under 1 min")
    phase = st.session_state.get("task_estimation_phase", "ready")
    if phase == "ready":
        st.write("Watch the visual pulse. You will estimate how long it was displayed.")
        _timed_stage("<div><strong>Focus on the visual display.</strong></div>")
        if st.button("Begin display", type="primary", use_container_width=True):
            st.session_state.task_estimation_target = random.uniform(5.0, 10.0)
            st.session_state.task_estimation_started = time.monotonic()
            st.session_state.task_estimation_phase = "display"
            st.rerun()
        navigation_back()
        return
    if phase == "display":
        target = st.session_state.task_estimation_target
        elapsed = time.monotonic() - st.session_state.task_estimation_started
        _timed_stage('<div class="stimulus-circle" style="animation:pulse 1s ease-in-out infinite alternate"></div>')
        st.markdown("<style>@keyframes pulse { from {transform:scale(.72); opacity:.65} to {transform:scale(1); opacity:1} }</style>", unsafe_allow_html=True)
        if elapsed >= target:
            st.session_state.task_estimation_phase = "respond"
            st.rerun()
        time.sleep(.08)
        st.rerun()
    if phase == "respond":
        _timed_stage("<div><strong>How long was the animation displayed?</strong></div>")
        with st.form("estimation_response"):
            estimate = st.number_input("Estimated seconds", 0.1, 60.0, 7.0, .1)
            submitted = st.form_submit_button("Record estimate", type="primary", use_container_width=True)
        if submitted:
            target = st.session_state.task_estimation_target
            signed = estimate - target
            st.session_state.time_task_results.append(
                {
                    "task_type": "time_estimation",
                    "target_seconds": target,
                    "response_seconds": estimate,
                    "signed_error": signed,
                    "absolute_error": abs(signed),
                }
            )
            st.session_state.task_estimation_phase = "done"
            st.rerun()
        return
    _timed_stage("<div><strong>Estimate recorded</strong></div>")
    if st.button("Continue", type="primary", use_container_width=True):
        next_step()


def _make_stroop_trials() -> list[dict[str, str | bool]]:
    """Build a balanced set of congruent and incongruent two-colour trials."""
    trials: list[dict[str, str | bool]] = []
    repetitions = STROOP_TRIAL_COUNT // 4
    for ink in STROOP_COLORS:
        other_colour = next(colour for colour in STROOP_COLORS if colour != ink)
        for _ in range(repetitions):
            trials.append({"word": ink, "ink": ink, "congruent": True})
            trials.append({"word": other_colour, "ink": ink, "congruent": False})
    random.shuffle(trials)
    return trials


def render_stroop() -> None:
    assessment_header(7, TOTAL_STEPS, "Colour-word task", "About 1 min")
    if "stroop_trials" not in st.session_state:
        st.write(
            "Respond to the ink colour, not the written word. Keep one finger on each "
            "arrow key and respond as quickly and accurately as possible."
        )
        st.markdown(
            """
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0">
                <div class="research-card" style="text-align:center;margin:0">
                    <strong>Left Arrow</strong><br><span style="color:#1976d2">BLUE ink</span>
                </div>
                <div class="research-card" style="text-align:center;margin:0">
                    <strong>Right Arrow</strong><br><span style="color:#d64545">RED ink</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        _timed_stage(
            '<div><span class="stroop-word" style="color:#1976d2">RED</span>'
            '<br><small>Correct response: Left Arrow, because the ink is blue.</small></div>'
        )
        if st.button(
            f"Begin {STROOP_TRIAL_COUNT} trials",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.stroop_trials = _make_stroop_trials()
            st.session_state.stroop_index = 0
            st.session_state.stroop_responses = []
            st.session_state.stroop_shown_at = None
            st.rerun()
        navigation_back()
        return

    index = st.session_state.stroop_index
    trials = st.session_state.stroop_trials
    if index < len(trials):
        trial = trials[index]
        st.progress(index / len(trials))
        st.caption("Left Arrow = BLUE  |  Right Arrow = RED")
        _timed_stage(
            f'<div class="stroop-word" style="color:{STROOP_COLORS[trial["ink"]]}">{trial["word"].upper()}</div>'
        )
        if st.session_state.stroop_shown_at is None:
            st.session_state.stroop_shown_at = time.monotonic()

        listener_key = f"stroop_trial_{index}"
        hotkeys.activate(
            [
                hotkeys.hk("stroop_left", "ArrowLeft", prevent_default=True),
                hotkeys.hk("stroop_right", "ArrowRight", prevent_default=True),
            ],
            key=listener_key,
        )
        pressed_key = None
        if hotkeys.pressed("stroop_left", key=listener_key):
            pressed_key = "ArrowLeft"
        elif hotkeys.pressed("stroop_right", key=listener_key):
            pressed_key = "ArrowRight"

        elapsed_trial = time.monotonic() - st.session_state.stroop_shown_at

        if pressed_key:
            reaction_ms = elapsed_trial * 1000
            selected_colour = STROOP_KEY_MAP[pressed_key]
            st.session_state.stroop_responses.append(
                {
                    **trial,
                    "response": selected_colour,
                    "response_key": pressed_key,
                    "correct": selected_colour == trial["ink"],
                    "reaction_ms": round(reaction_ms, 2),
                    "timed_out": False,
                }
            )
            st.session_state.stroop_index += 1
            st.session_state.stroop_shown_at = None
            st.rerun()
            return

        if elapsed_trial >= STROOP_TRIAL_DURATION_SECONDS:
            # No key press within the trial window — record it as a genuine
            # miss (distinct from an incorrect key press) and auto-advance.
            st.session_state.stroop_responses.append(
                {
                    **trial,
                    "response": None,
                    "response_key": None,
                    "correct": False,
                    "reaction_ms": None,
                    "timed_out": True,
                }
            )
            st.session_state.stroop_index += 1
            st.session_state.stroop_shown_at = None
            st.rerun()
            return

        # Keep polling every cycle, same pattern as the timing tasks above.
        # This re-arms the hotkey listener on a fresh rerun each time, so the
        # trial keeps refreshing whether or not the participant has responded
        # yet, rather than sitting frozen until some other widget triggers a
        # rerun. A short interval keeps the auto-advance timing in the line
        # above accurate at a sub-second trial duration.
        time.sleep(.03)
        st.rerun()
        return

    responses = st.session_state.stroop_responses
    accuracy = float(np.mean([item["correct"] for item in responses]) * 100)
    reaction_times = [
        item["reaction_ms"] for item in responses
        if item["correct"] and item["reaction_ms"] is not None
    ]
    mean_reaction = float(np.mean(reaction_times)) if reaction_times else 0.0
    misses = sum(1 for item in responses if item.get("timed_out"))
    errors = sum(1 for item in responses if not item["correct"] and not item.get("timed_out"))
    st.session_state.cognitive_result = {
        "task_type": "stroop",
        "accuracy": accuracy,
        "mean_reaction_ms": mean_reaction,
        "errors": errors,
        "misses": misses,
        "false_alarms": 0,
        "trials": responses,
    }
    _timed_stage(f"<div><strong>Task complete</strong><br><small>{accuracy:.0f}% accuracy</small></div>")
    if st.button("Continue", type="primary", use_container_width=True):
        next_step()


def render_review(participant_id: str) -> None:
    assessment_header(8, TOTAL_STEPS, "Review and submit", "Under 1 min")
    answers = st.session_state.assessment_answers
    st.success("All required task responses are complete.")
    left, middle, right = st.columns(3)
    left.metric("Context", answers.get("activity", "Recorded"))
    middle.metric("Current stress", f"{answers.get('stress', 0)}/100")
    right.metric("Tasks completed", "4 of 4")
    reflection = st.text_area(
        "Optional reflection",
        placeholder="Anything that may have affected your responses today?",
        max_chars=500,
    )
    st.caption("Submitting will timestamp and securely store this assessment in the study database.")
    left_button, right_button = st.columns(2)
    if left_button.button("Back", use_container_width=True):
        previous_step()
    if right_button.button("Submit assessment", type="primary", use_container_width=True):
        answers["reflection"] = reflection.strip()
        with st.spinner("Saving assessment..."):
            assessment_id = save_assessment(
                participant_id,
                st.session_state.assessment_started_at,
                answers,
                st.session_state.time_task_results,
                st.session_state.cognitive_result,
            )
        st.session_state.last_assessment_id = assessment_id
        st.session_state.assessment_active = False
        st.session_state.active_page = "Dashboard"
        st.session_state.assessment_saved = True
        st.rerun()


def render_assessment(participant_id: str) -> None:
    """Render the currently active assessment section."""
    if not st.session_state.get("assessment_active"):
        st.header("Daily assessment")
        st.write(
            "This assessment combines a brief EMA check-in, three time-perception tasks, "
            "and a colour-word task. Complete it somewhere safe and quiet."
        )
        st.info("Estimated completion time: 5-7 minutes. Avoid counting seconds during timing tasks.")
        if st.button("Begin daily assessment", type="primary", use_container_width=True):
            start_assessment()
            st.rerun()
        return

    step = st.session_state.assessment_step
    renderers: dict[int, Any] = {
        1: render_context,
        2: render_scales,
        3: render_event,
        4: render_reproduction,
        5: render_prospective,
        6: render_estimation,
        7: render_stroop,
    }
    if step == 8:
        render_review(participant_id)
    else:
        renderers[step]()

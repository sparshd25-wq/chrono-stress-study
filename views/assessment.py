
"""Resumable daily EMA and behavioural assessment workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import random
import time
from typing import Any

import numpy as np
import streamlit as st
import streamlit_hotkeys as hotkeys
from streamlit.components import v2 as components_v2

from components.ui import assessment_header
from config import (
    ACTIVITY_OPTIONS,
    LOCATION_OPTIONS,
)
from database.repository import save_assessment


TOTAL_STEPS = 7
STROOP_COLORS = {
    "Red": "#d64545",
    "Blue": "#1976d2",
}
STROOP_KEY_MAP = {"ArrowLeft": "Blue", "ArrowRight": "Red"}
STROOP_TRIAL_COUNT = 12
STROOP_RESPONSE_WINDOW = 1.4
STROOP_ITI = 0.3
COUNTING_OPTIONS = ("Not at all", "Occasionally", "Frequently", "Continuously")
STRESS_OPTIONS = (
    (1, "Very Low"),
    (2, "Low"),
    (3, "Slightly Low"),
    (4, "Moderate"),
    (5, "Slightly High"),
    (6, "High"),
    (7, "Very High"),
)


HOLD_REPRODUCTION_COMPONENT = components_v2.component(
    "hold_to_reproduce",
    html='<button type="button" class="hold-button"><span>HOLD TO REPRODUCE</span></button>',
    css="""
        :host { display: flex; justify-content: center; padding: 14px 0 22px; }
        .hold-button {
            align-items: center;
            background: #1976d2;
            border: 0;
            border-radius: 50%;
            box-shadow: 0 0 0 12px rgba(25, 118, 210, .09),
                        0 10px 28px rgba(25, 118, 210, .22);
            color: white;
            cursor: pointer;
            display: flex;
            font: 700 16px/1.25 Inter, Arial, sans-serif;
            height: 210px;
            justify-content: center;
            letter-spacing: .04em;
            overflow: hidden;
            padding: 34px;
            position: relative;
            text-align: center;
            touch-action: none;
            user-select: none;
            width: 210px;
            -webkit-tap-highlight-color: transparent;
        }
        .hold-button::before {
            background: rgba(255, 255, 255, .18);
            border-radius: 50%;
            content: "";
            inset: 50%;
            position: absolute;
            transition: inset .22s ease;
        }
        .hold-button span { position: relative; z-index: 1; }
        .hold-button.holding {
            animation: held-pulse 1.1s ease-in-out infinite alternate;
            box-shadow: 0 0 0 16px rgba(25, 118, 210, .12),
                        0 0 34px rgba(25, 118, 210, .46);
        }
        .hold-button.holding::before { inset: 7%; }
        @keyframes held-pulse {
            from { transform: scale(.97); }
            to { transform: scale(1.03); }
        }
    """,
    js="""
        export default function(component) {
            const { parentElement, setTriggerValue } = component;
            const button = parentElement.querySelector('.hold-button');
            let startedAt = null;

            const begin = (event) => {
                event.preventDefault();
                if (startedAt !== null) return;
                startedAt = performance.now();
                button.classList.add('holding');
                if (event.pointerId !== undefined) {
                    button.setPointerCapture(event.pointerId);
                }
            };
            const finish = (event) => {
                event.preventDefault();
                if (startedAt === null) return;
                const durationMs = performance.now() - startedAt;
                startedAt = null;
                button.classList.remove('holding');
                setTriggerValue('duration_ms', Math.round(durationMs));
            };
            const cancel = () => {
                startedAt = null;
                button.classList.remove('holding');
            };

            button.addEventListener('pointerdown', begin);
            button.addEventListener('pointerup', finish);
            button.addEventListener('pointercancel', cancel);
            button.addEventListener('contextmenu', (event) => event.preventDefault());
            button.addEventListener('keydown', (event) => {
                if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) begin(event);
            });
            button.addEventListener('keyup', (event) => {
                if (event.key === ' ' || event.key === 'Enter') finish(event);
            });

            return () => {
                button.replaceWith(button.cloneNode(true));
            };
        }
    """,
)


PULSE_RATE_MATCH_COMPONENT = components_v2.component(
    "pulse_rate_hold_dial",
    html="""
        <div class="pulse-hold-match">
            <div class="preview-wrap" aria-hidden="true">
                <div class="preview-pulse"></div>
            </div>

            <div class="dial-row">
                <span>SLOWER</span>
                <button type="button" class="hold-dial" aria-label="Hold to match pulse rhythm">
                    <span class="dial-core"></span>
                </button>
                <span>FASTER</span>
            </div>
        </div>
    """,
    css="""
        :host {
            display:block;
        }
        .pulse-hold-match {
            align-items:center;
            color:#152238;
            display:flex;
            flex-direction:column;
            gap:24px;
            justify-content:center;
            padding:18px 8px 28px;
        }
        .preview-wrap {
            align-items:center;
            display:flex;
            height:170px;
            justify-content:center;
            width:100%;
        }
        .preview-pulse {
            animation: preview-pulse var(--pulse-duration, 1.35s) ease-in-out infinite;
            background:#1976d2;
            border-radius:50%;
            box-shadow:0 0 0 12px rgba(25,118,210,.08),
                       0 16px 32px rgba(25,118,210,.18);
            height:118px;
            opacity:.76;
            transform:scale(.72);
            width:118px;
        }
        .dial-row {
            align-items:center;
            display:grid;
            gap:18px;
            grid-template-columns:minmax(76px, 1fr) auto minmax(76px, 1fr);
            max-width:520px;
            width:100%;
        }
        .dial-row span {
            color:#587084;
            font:700 13px/1 Inter, Arial, sans-serif;
            letter-spacing:.12em;
            text-align:center;
        }
        .hold-dial {
            --fill:0deg;
            align-items:center;
            background:conic-gradient(#1976d2 var(--fill), #d8e5ef 0deg);
            border:0;
            border-radius:50%;
            box-shadow:0 12px 30px rgba(21,34,56,.16);
            cursor:pointer;
            display:flex;
            height:148px;
            justify-content:center;
            padding:12px;
            touch-action:none;
            user-select:none;
            width:148px;
            -webkit-tap-highlight-color:transparent;
        }
        .hold-dial:focus-visible {
            outline:3px solid rgba(25,118,210,.35);
            outline-offset:4px;
        }
        .hold-dial.holding {
            box-shadow:0 0 0 10px rgba(25,118,210,.08),
                       0 18px 36px rgba(21,34,56,.20);
        }
        .dial-core {
            background:#ffffff;
            border-radius:50%;
            box-shadow:inset 0 0 0 1px rgba(88,112,132,.16);
            display:block;
            height:100%;
            width:100%;
        }
        @keyframes preview-pulse {
            0%, 100% { transform:scale(.72); opacity:.66; }
            50% { transform:scale(1); opacity:1; }
        }
        @media (max-width: 560px) {
            .dial-row {
                gap:10px;
                grid-template-columns:minmax(58px, 1fr) auto minmax(58px, 1fr);
            }
            .dial-row span {
                font-size:11px;
                letter-spacing:.08em;
            }
            .hold-dial {
                height:126px;
                width:126px;
            }
        }
    """,
    js="""
        export default function(component) {
            const { parentElement, setTriggerValue } = component;
            const dial = parentElement.querySelector('.hold-dial');
            const preview = parentElement.querySelector('.preview-pulse');
            const minRate = 0.5;
            const maxRate = 2.5;
            const maxHoldMs = 4200;
            let startedAt = null;
            let animationFrame = null;
            let currentRate = minRate;

            const rateFromProgress = (progress) => {
                const eased = 1 - Math.pow(1 - progress, 2);
                return minRate + (maxRate - minRate) * eased;
            };

            const render = () => {
                const elapsed = performance.now() - startedAt;
                const progress = Math.min(1, elapsed / maxHoldMs);
                currentRate = rateFromProgress(progress);
                dial.style.setProperty('--fill', `${progress * 360}deg`);
                preview.style.setProperty('--pulse-duration', `${(1 / currentRate).toFixed(3)}s`);
                animationFrame = requestAnimationFrame(render);
            };

            const begin = (event) => {
                event.preventDefault();
                if (startedAt !== null) return;
                startedAt = performance.now();
                dial.classList.add('holding');
                if (event.pointerId !== undefined) {
                    dial.setPointerCapture(event.pointerId);
                }
                render();
            };

            const finish = (event) => {
                event.preventDefault();
                if (startedAt === null) return;
                cancelAnimationFrame(animationFrame);
                animationFrame = null;
                startedAt = null;
                dial.classList.remove('holding');
                setTriggerValue('matched_rate', Number(currentRate.toFixed(4)));
            };

            const cancel = () => {
                if (animationFrame !== null) {
                    cancelAnimationFrame(animationFrame);
                }
                animationFrame = null;
                startedAt = null;
                dial.classList.remove('holding');
            };

            preview.style.setProperty('--pulse-duration', `${(1 / minRate).toFixed(3)}s`);
            dial.addEventListener('pointerdown', begin);
            dial.addEventListener('pointerup', finish);
            dial.addEventListener('pointercancel', cancel);
            dial.addEventListener('pointerleave', (event) => {
                if (startedAt !== null && event.buttons === 0) cancel();
            });
            dial.addEventListener('contextmenu', (event) => event.preventDefault());
            dial.addEventListener('keydown', (event) => {
                if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) begin(event);
            });
            dial.addEventListener('keyup', (event) => {
                if (event.key === ' ' || event.key === 'Enter') finish(event);
            });

            return () => {
                cancel();
                dial.replaceWith(dial.cloneNode(true));
            };
        }
    """,
)

def start_assessment() -> None:
    """Create a fresh in-session assessment record."""
    for key in list(st.session_state):
        if key.startswith("task_") or key.startswith("stroop_"):
            del st.session_state[key]
    st.session_state.pop("stroop_started", None)
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


def render_counting_questions() -> None:
    """Collect strategy reports only after every behavioural task is complete."""
    assessment_header(5, TOTAL_STEPS, "Counting strategies", "Under 1 min")
    st.write("Please report any counting strategies you used during the completed tasks.")
    with st.form("post_task_counting_report"):
        reproduction_counting = st.radio(
            "Did you intentionally count during the interval reproduction task?",
            COUNTING_OPTIONS,
        )
        prospective_counting = st.radio(
            "Did you intentionally count during the 30-second task?",
            COUNTING_OPTIONS,
        )
        pulse_counting = st.radio(
            "Did you intentionally count during the visual pulse task?",
            COUNTING_OPTIONS,
        )
        submitted = st.form_submit_button(
            "Continue", type="primary", use_container_width=True
        )
    if submitted:
        _append_time_task(
            st.session_state.task_reproduction_result,
            {"intentional_counting": reproduction_counting},
        )
        _append_time_task(
            st.session_state.task_prospective_result,
            {"intentional_counting": prospective_counting},
        )
        _append_time_task(
            st.session_state.task_estimation_result,
            {"intentional_counting": pulse_counting},
        )
        st.session_state.task_counting_complete = True
        st.rerun()


def render_context() -> None:
    if not st.session_state.get("task_counting_complete", False):
        render_counting_questions()
        return

    assessment_header(5, TOTAL_STEPS, "Current context")
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
        submitted = st.form_submit_button("Continue", type="primary", use_container_width=True)
    if submitted:
        answers.update(
            location=location,
            activity=activity,
            sleep_hours=sleep_hours,
            caffeine_recent=int(caffeine_recent == "Yes"),
            medication_today=int(medication_today == "Yes"),
        )
        next_step()


def render_scales() -> None:
    assessment_header(6, TOTAL_STEPS, "Current stress")
    answers = st.session_state.assessment_answers
    stress_values = [value for value, _label in STRESS_OPTIONS]
    stress_labels = dict(STRESS_OPTIONS)
    saved_stress = int(answers.get("stress", 4))
    with st.form("scales_form"):
        stress = st.radio(
            "How stressed do you feel right now?",
            stress_values,
            index=stress_values.index(saved_stress) if saved_stress in stress_values else 3,
            format_func=lambda value: stress_labels[value],
        )
        left, right = st.columns(2)
        back = left.form_submit_button("Back", use_container_width=True)
        submitted = right.form_submit_button("Continue", type="primary", use_container_width=True)
    if back:
        previous_step()
    if submitted:
        answers["stress"] = stress
        next_step()


def _timed_stage(content: str) -> None:
    st.markdown(f'<div class="task-stage">{content}</div>', unsafe_allow_html=True)


def _append_time_task(result: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Commit a completed timing result with its post-task monitoring response."""
    result.setdefault("metadata", {}).update(metadata)
    # Back-navigation can revisit a completed task; update its report without
    # duplicating the behavioural result in the eventual database transaction.
    if result not in st.session_state.time_task_results:
        st.session_state.time_task_results.append(result)


def _assessment_answers_for_storage(answers: dict[str, Any]) -> dict[str, Any]:
    """Fill legacy database fields that are no longer shown to participants."""
    return {
        **answers,
        "workload": "Not collected",
        "mental_fatigue": 0,
        "emotional_arousal": 0,
        "perceived_control": 0,
        "anxiety": 0,
        "stressful_event": 0,
        "event_type": None,
        "event_duration": None,
        "event_upset": None,
        "event_expected": None,
        "event_control": None,
    }


def _time_tasks_for_storage(time_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map new pulse-rate matching fields onto the unchanged task table."""
    storage_tasks: list[dict[str, Any]] = []
    for task in time_tasks:
        if task["task_type"] != "pulse_matching":
            storage_tasks.append(task)
            continue

        matching_error = float(task["matching_error"])
        storage_task = {
            **task,
            "target_seconds": None,
            "response_seconds": float(task["matched_pulse_rate"]),
            "signed_error": matching_error,
            "absolute_error": abs(matching_error),
            "metadata": {
                **task.get("metadata", {}),
                "target_pulse_rate": task["target_pulse_rate"],
                "matched_pulse_rate": task["matched_pulse_rate"],
                "matching_error": matching_error,
            },
        }
        storage_tasks.append(storage_task)
    return storage_tasks


def _make_irregular_pulse_plan(duration: float) -> list[dict[str, float]]:
    """Pre-generate smooth pulses with independently jittered pulse/rest times."""
    plan: list[dict[str, float]] = []
    start = 0.0
    while start < duration + 1.0:
        pulse_duration = random.uniform(0.48, 0.78)
        grow_duration = pulse_duration * random.uniform(0.42, 0.58)
        plan.append(
            {
                "start": start,
                "grow": grow_duration,
                "shrink": pulse_duration - grow_duration,
            }
        )
        # Independent onset gaps remove the regular beat while preserving the pulse.
        start += pulse_duration + random.uniform(0.18, 0.46)
    return plan


def _pulse_rate_style(elapsed: float, pulse_rate: float) -> str:
    """Return a smooth pulse state for a fixed pulse rate."""
    progress = (elapsed * pulse_rate) % 1.0
    eased = 0.5 - 0.5 * np.cos(2 * np.pi * progress)
    scale = 0.72 + 0.28 * eased
    opacity = 0.65 + 0.35 * eased
    return f"transform:scale({scale:.4f});opacity:{opacity:.4f}"


def _irregular_pulse_style(elapsed: float, plan: list[dict[str, float]]) -> str:
    """Return an eased pulse state for the current point in the random plan."""
    scale = 0.72
    for pulse in plan:
        local_time = elapsed - pulse["start"]
        pulse_duration = pulse["grow"] + pulse["shrink"]
        if 0.0 <= local_time <= pulse_duration:
            if local_time <= pulse["grow"]:
                progress = local_time / pulse["grow"]
            else:
                progress = 1.0 - (local_time - pulse["grow"]) / pulse["shrink"]
            eased = 0.5 - 0.5 * np.cos(np.pi * progress)
            scale = 0.72 + 0.28 * eased
            break
    opacity = 0.65 + (scale - 0.72) * (0.35 / 0.28)
    return f"transform:scale({scale:.4f});opacity:{opacity:.4f}"


def render_reproduction() -> None:
    assessment_header(1, TOTAL_STEPS, "Time reproduction", "Under 1 min")
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
        _timed_stage(
            "<div><strong>Reproduce the interval</strong><br>"
            "<small>Press and hold, then release after the remembered duration.</small></div>"
        )
        # Pointer-down/up timing provides classical reproduction without exposing
        # a clock, while restrained tactile-style feedback supports mobile use.
        hold_result = HOLD_REPRODUCTION_COMPONENT(
            key="reproduction_hold",
            height=260,
            on_duration_ms_change=lambda: None,
        )
        duration_ms = getattr(hold_result, "duration_ms", None)
        if duration_ms is not None:
            response = float(duration_ms) / 1000.0
            target = st.session_state.task_reproduction_target
            signed = response - target
            st.session_state.task_reproduction_result = {
                "task_type": "time_reproduction",
                "target_seconds": target,
                "response_seconds": response,
                "signed_error": signed,
                "absolute_error": abs(signed),
            }
            _append_time_task(st.session_state.task_reproduction_result, {})
            st.session_state.task_reproduction_phase = "done"
            st.rerun()
        return

    _timed_stage("<div><strong>Response recorded</strong><br><small>Your result remains blinded until submission.</small></div>")
    if st.button("Continue", type="primary", use_container_width=True):
        st.session_state.stroop_started = False
        next_step()


def render_prospective() -> None:
    assessment_header(2, TOTAL_STEPS, "Prospective timing", "About 1 min")
    phase = st.session_state.get("task_prospective_phase", "ready")
    if phase == "ready":
        st.write("This is not a test and there is no correct answer.")
        st.write(
            "Please avoid intentionally counting seconds. Simply allow time to pass "
            "naturally and press Finish when you believe 30 seconds have elapsed."
        )
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
            st.session_state.task_prospective_result = {
                "task_type": "prospective_timing",
                "target_seconds": 30.0,
                "response_seconds": response,
                "signed_error": signed,
                "absolute_error": abs(signed),
            }
            st.session_state.task_prospective_phase = "done"
            st.rerun()
        return
    _timed_stage("<div><strong>Response recorded</strong></div>")
    if st.button("Continue", type="primary", use_container_width=True):
        _append_time_task(st.session_state.task_prospective_result, {})
        next_step()


def render_estimation() -> None:
    assessment_header(3, TOTAL_STEPS, "Pulse rhythm matching", "Under 1 min")
    phase = st.session_state.get("task_estimation_phase", "ready")
    if phase == "ready":
        st.write("Watch the visual pulse. Afterwards, recreate the pulse rhythm you observed.")
        _timed_stage("<div><strong>Focus on the visual display.</strong></div>")
        if st.button("Begin display", type="primary", use_container_width=True):
            st.session_state.task_estimation_display_duration = random.uniform(5.0, 10.0)
            st.session_state.task_estimation_target_pulse_rate = random.uniform(0.7, 1.9)
            st.session_state.task_estimation_started = time.monotonic()
            st.session_state.task_estimation_phase = "display"
            st.rerun()
        navigation_back()
        return
    if phase == "display":
        display_duration = st.session_state.task_estimation_display_duration
        elapsed = time.monotonic() - st.session_state.task_estimation_started
        pulse_style = _pulse_rate_style(
            elapsed, st.session_state.task_estimation_target_pulse_rate
        )
        _timed_stage(
            f'<div class="stimulus-circle" style="{pulse_style};'
            'transition:transform .1s linear,opacity .1s linear"></div>'
        )
        if elapsed >= display_duration:
            st.session_state.task_estimation_phase = "respond"
            st.rerun()
        time.sleep(.08)
        st.rerun()
    if phase == "respond":
        st.markdown("### Pulse rhythm matching")
        st.write(
            "Recreate the pulse rhythm you just observed.\n\n"
            "Press and hold the circular control until the pulse below feels like "
            "the same rhythm you experienced previously.\n\n"
            "Release when it feels like a match."
        )
        match_result = PULSE_RATE_MATCH_COMPONENT(
            key="pulse_rate_match",
            height=360,
            on_matched_rate_change=lambda: None,
        )
        matched_rate = getattr(match_result, "matched_rate", None)
        if matched_rate is not None:
            target_rate = st.session_state.task_estimation_target_pulse_rate
            participant_rate = float(matched_rate)
            st.session_state.task_estimation_result = {
                "task_type": "pulse_matching",
                "target_pulse_rate": target_rate,
                "matched_pulse_rate": participant_rate,
                "matching_error": participant_rate - target_rate,
            }
            _append_time_task(st.session_state.task_estimation_result, {})
            st.session_state.task_estimation_phase = "done"
            st.rerun()
        return
    _timed_stage("<div><strong>Response recorded</strong></div>")
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
    assessment_header(4, TOTAL_STEPS, "Colour-word task", "About 1 min")
    # A single placeholder for the swapping region below. Writing into the same
    # st.empty() slot every rerun forces Streamlit to fully replace its prior
    # content, which is what stops the intro screen's buttons from lingering
    # under rapid polling reruns once trials have started.
    stage = st.empty()

    if not st.session_state.get("stroop_started", False) and "stroop_trials" not in st.session_state:
        with stage.container():
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
                st.session_state.stroop_started = True
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
        with stage.container():
            st.progress(index / len(trials))
            st.caption("Left Arrow = BLUE  |  Right Arrow = RED")
            _timed_stage(
                f'<div class="stroop-word" style="color:{STROOP_COLORS[trial["ink"]]}">{trial["word"].upper()}</div>'
            )
        if st.session_state.stroop_shown_at is None:
            st.session_state.stroop_shown_at = time.monotonic()

        # Check for a real keypress FIRST. Previously the timeout branch fell
        # straight into an unconditional "time.sleep(0.1); st.rerun()", and
        # st.rerun() halts the script immediately — so the hotkey listener
        # below it never actually ran on any trial. Every trial silently
        # timed out and was logged as a miss regardless of what the
        # participant pressed, which is why accuracy was always wrong.
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

        if pressed_key:
            reaction_ms = (time.monotonic() - st.session_state.stroop_shown_at) * 1000
            selected_colour = STROOP_KEY_MAP[pressed_key]
            st.session_state.stroop_responses.append(
                {
                    **trial,
                    "response": selected_colour,
                    "response_key": pressed_key,
                    "correct": selected_colour == trial["ink"],
                    "reaction_ms": round(reaction_ms, 2),
                    "miss": False,
                }
            )
            st.session_state.stroop_index += 1
            st.session_state.stroop_shown_at = None
            st.rerun()
            return

        elapsed = time.monotonic() - st.session_state.stroop_shown_at

        # automatic timeout after 1.4 seconds
        if elapsed >= STROOP_RESPONSE_WINDOW:
            st.session_state.stroop_responses.append(
                {
                    **trial,
                    "response": None,
                    "response_key": None,
                    "correct": False,
                    "reaction_ms": None,
                    "miss": True,
                }
            )
            time.sleep(STROOP_ITI)
            st.session_state.stroop_index += 1
            st.session_state.stroop_shown_at = None
            st.rerun()
            return

        # force periodic reruns while waiting for a response
        time.sleep(0.1)
        st.rerun()
        return

    with stage.container():
        responses = st.session_state.stroop_responses
        accuracy = float(np.mean([item["correct"] for item in responses]) * 100)
        reaction_times = [item["reaction_ms"] for item in responses if item["correct"]]
        mean_reaction = float(np.mean(reaction_times)) if reaction_times else 0.0
        misses = sum(1 for item in responses if item.get("miss"))
        errors = sum(1 for item in responses if not item["correct"] and not item.get("miss"))
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
    assessment_header(7, TOTAL_STEPS, "Review and submit", "Under 1 min")
    answers = st.session_state.assessment_answers
    st.success("All required task responses are complete.")
    left, middle, right = st.columns(3)
    left.metric("Context", answers.get("activity", "Recorded"))
    middle.metric("Current stress", f"{answers.get('stress', 'Recorded')}/7")
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
                _assessment_answers_for_storage(answers),
                _time_tasks_for_storage(st.session_state.time_task_results),
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
        1: render_reproduction,
        2: render_prospective,
        3: render_estimation,
        4: render_stroop,
        5: render_context,
        6: render_scales,
    }
    if step == 7:
        render_review(participant_id)
    else:
        renderers[step]()

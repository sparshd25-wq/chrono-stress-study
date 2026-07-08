"""Resumable daily EMA and behavioural assessment workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import random
import time
from typing import Any
import wave

import numpy as np
import streamlit as st
import streamlit_hotkeys as hotkeys
from streamlit.components import v2 as components_v2

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
COUNTING_OPTIONS = ("Not at all", "Occasionally", "Frequently", "Continuously")
TONE_SAMPLE_RATE = 16_000
STANDARD_TONE_DURATION_SECONDS = 0.25
TARGET_TONE_DURATION_SECONDS = 0.35
STANDARD_TONE_AMPLITUDE = 0.42
TARGET_TONE_AMPLITUDE = 0.56


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


SUBJECTIVE_DURATION_COMPONENT = components_v2.component(
    "subjective_duration_slider",
    html="""
        <div class="duration-match">
            <div class="duration-labels">
                <span>Passed Very Quickly</span>
                <span>Passed Very Slowly</span>
            </div>
            <input class="duration-slider" type="range" min="0" max="100" step="1"
                   value="50" aria-label="How long the interval felt">
        </div>
    """,
    css="""
        .duration-match { padding: 20px 8px 12px; }
        .duration-labels {
            color: #334e68;
            display: flex;
            font: 600 14px/1.35 Inter, Arial, sans-serif;
            justify-content: space-between;
            margin-bottom: 18px;
        }
        .duration-labels span:last-child { text-align: right; }
        .duration-slider {
            accent-color: #1976d2;
            cursor: pointer;
            height: 40px;
            margin: 0;
            touch-action: pan-x;
            width: 100%;
        }
    """,
    js="""
        export default function(component) {
            const { parentElement, setStateValue } = component;
            const slider = parentElement.querySelector('.duration-slider');
            slider.addEventListener('change', () => {
                setStateValue('position', Number(slider.value));
            });
        }
    """,
)


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
    assessment_header(6, TOTAL_STEPS, "Current experience")
    st.write("Move each marker to the point that best reflects how you feel right now.")
    answers = st.session_state.assessment_answers
    with st.form("scales_form"):
        fatigue = _vas("How mentally exhausted are you?", "0 = not at all, 100 = extremely", int(answers.get("mental_fatigue", 50)))
        arousal = _vas("How emotionally activated or overwhelmed are you?", "0 = calm, 100 = extremely activated", int(answers.get("emotional_arousal", 50)))
        control = _vas("How much control do you currently feel?", "0 = no control, 100 = complete control", int(answers.get("perceived_control", 50)))
        st.markdown("#### Stress scales")
        stress = _vas("How stressed do you feel?", "0 = not at all, 100 = extremely", int(answers.get("stress", 50)))
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
    assessment_header(7, TOTAL_STEPS, "Since the previous assessment")
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


def _append_time_task(result: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Commit a completed timing result with its post-task monitoring response."""
    result.setdefault("metadata", {}).update(metadata)
    # Back-navigation can revisit a completed task; update its report without
    # duplicating the behavioural result in the eventual database transaction.
    if result not in st.session_state.time_task_results:
        st.session_state.time_task_results.append(result)


def _build_oddball_trial() -> tuple[bytes, int]:
    """Create a hidden 30-second oddball stream with unpredictable 2-5 s ITIs."""
    target_count = random.randint(2, 5)
    # Eight standards keep targets infrequent and make monitoring sufficient to
    # disrupt explicit counting without replacing prospective timing as the task.
    tone_count = target_count + 8
    first_tone = random.uniform(0.4, 1.0)

    raw_intervals = [random.uniform(2.0, 5.0) for _ in range(tone_count - 1)]
    available = random.uniform(27.0, 29.0) - first_tone
    minimum = 2.0 * len(raw_intervals)
    excess = sum(interval - 2.0 for interval in raw_intervals)
    scale = min(1.0, (available - minimum) / excess) if excess else 1.0
    intervals = [2.0 + (interval - 2.0) * scale for interval in raw_intervals]

    onset_times = [first_tone]
    for interval in intervals:
        onset_times.append(onset_times[-1] + interval)
    target_indices = set(random.sample(range(tone_count), target_count))

    # A WAV stream is generated locally so no recordings or external audio assets
    # are required. Normalized attack/decay envelopes improve laptop audibility
    # without clicks, and make targets clearly distinct without becoming harsh.
    samples = np.zeros(30 * TONE_SAMPLE_RATE, dtype=np.float32)
    for index, onset in enumerate(onset_times):
        is_target = index in target_indices
        frequency = 1200 if is_target else 800
        duration = (
            TARGET_TONE_DURATION_SECONDS if is_target
            else STANDARD_TONE_DURATION_SECONDS
        )
        amplitude = TARGET_TONE_AMPLITUDE if is_target else STANDARD_TONE_AMPLITUDE
        tone_length = int(duration * TONE_SAMPLE_RATE)
        tone_time = np.arange(tone_length) / TONE_SAMPLE_RATE
        fade_length = int(0.02 * TONE_SAMPLE_RATE)
        fade = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, fade_length))
        envelope = np.ones(tone_length, dtype=np.float32)
        envelope[:fade_length] = fade
        envelope[-fade_length:] = fade[::-1]
        tone = np.sin(2 * np.pi * frequency * tone_time) * envelope
        tone /= np.max(np.abs(tone))
        tone *= amplitude
        start = int(onset * TONE_SAMPLE_RATE)
        samples[start:start + tone_length] += tone

    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TONE_SAMPLE_RATE)
        wav_file.writeframes((samples * 32767).astype("<i2").tobytes())
    return output.getvalue(), target_count


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
        next_step()


def render_prospective() -> None:
    assessment_header(2, TOTAL_STEPS, "Prospective timing", "About 1 min")
    phase = st.session_state.get("task_prospective_phase", "ready")
    if phase == "ready":
        st.write("Without counting, press Finish when you believe 30 seconds have elapsed.")
        st.write(
            "While estimating the interval, also monitor the sounds and remember "
            "how many high-pitched tones you hear."
        )
        _timed_stage("<div><strong>The display will not show elapsed time.</strong></div>")
        if st.button("Start 30-second task", type="primary", use_container_width=True):
            audio, target_count = _build_oddball_trial()
            st.session_state.task_prospective_audio = audio
            st.session_state.task_prospective_target_count = target_count
            st.session_state.task_prospective_started = time.monotonic()
            st.session_state.task_prospective_phase = "recording"
            st.rerun()
        navigation_back()
        return
    if phase == "recording":
        # Hide playback controls so the audio stream cannot reveal elapsed time.
        st.markdown(
            "<style>div[data-testid='stAudio']{display:none}</style>",
            unsafe_allow_html=True,
        )
        st.audio(st.session_state.task_prospective_audio, format="audio/wav", autoplay=True)
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
    with st.form("prospective_auditory_report"):
        reported_count = st.number_input(
            "How many high-pitched tones did you hear?", 0, 20, 0, 1
        )
        submitted = st.form_submit_button("Continue", type="primary", use_container_width=True)
    if submitted:
        target_count = st.session_state.task_prospective_target_count
        _append_time_task(
            st.session_state.task_prospective_result,
            {
                "actual_target_count": target_count,
                "participant_reported_target_count": int(reported_count),
                "oddball_accuracy": int(reported_count == target_count),
            },
        )
        next_step()


def render_estimation() -> None:
    assessment_header(3, TOTAL_STEPS, "Subjective passage of time", "Under 1 min")
    phase = st.session_state.get("task_estimation_phase", "ready")
    if phase == "ready":
        st.write("Watch the visual pulse. Afterwards, indicate how long the interval felt.")
        _timed_stage("<div><strong>Focus on the visual display.</strong></div>")
        if st.button("Begin display", type="primary", use_container_width=True):
            st.session_state.task_estimation_target = random.uniform(5.0, 10.0)
            st.session_state.task_estimation_pulse_plan = _make_irregular_pulse_plan(
                st.session_state.task_estimation_target
            )
            st.session_state.task_estimation_started = time.monotonic()
            st.session_state.task_estimation_phase = "display"
            st.rerun()
        navigation_back()
        return
    if phase == "display":
        target = st.session_state.task_estimation_target
        elapsed = time.monotonic() - st.session_state.task_estimation_started
        # Sample a pre-generated irregular pulse plan: cosine easing keeps motion
        # smooth while jittered pulse/rest durations prevent rhythmic entrainment.
        pulse_style = _irregular_pulse_style(
            elapsed, st.session_state.task_estimation_pulse_plan
        )
        _timed_stage(
            f'<div class="stimulus-circle" style="{pulse_style};'
            'transition:transform .1s linear,opacity .1s linear"></div>'
        )
        if elapsed >= target:
            st.session_state.task_estimation_phase = "respond"
            st.rerun()
        time.sleep(.08)
        st.rerun()
    if phase == "respond":
        _timed_stage(
            "<div><strong>Move the slider to indicate how long the interval felt.</strong></div>"
        )
        # A non-numeric continuum captures experienced passage of time without
        # prompting conversion into seconds or another chronometric strategy.
        match_result = SUBJECTIVE_DURATION_COMPONENT(
            key="subjective_duration_match",
            default={"position": 50},
            height=110,
            on_position_change=lambda: None,
        )
        slider_position = float(getattr(match_result, "position", 50))
        if st.button("Record response", type="primary", use_container_width=True):
            target = st.session_state.task_estimation_target
            normalized_score = slider_position / 100.0
            centered_score = normalized_score - 0.5
            st.session_state.task_estimation_result = {
                "task_type": "subjective_passage_matching",
                "target_seconds": target,
                # Generic numeric fields remain populated for SQLite/export
                # compatibility; their unit is normalized rather than seconds.
                "response_seconds": normalized_score,
                "signed_error": centered_score,
                "absolute_error": abs(centered_score),
            }
            _append_time_task(
                st.session_state.task_estimation_result,
                {
                    "slider_position": slider_position,
                    "normalized_subjective_duration_score": normalized_score,
                    "response_measure": "normalized_subjective_duration",
                },
            )
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
                }
            )
            st.session_state.stroop_index += 1
            st.session_state.stroop_shown_at = None
            st.rerun()
        return

    responses = st.session_state.stroop_responses
    accuracy = float(np.mean([item["correct"] for item in responses]) * 100)
    reaction_times = [item["reaction_ms"] for item in responses if item["correct"]]
    mean_reaction = float(np.mean(reaction_times)) if reaction_times else 0.0
    errors = sum(not item["correct"] for item in responses)
    st.session_state.cognitive_result = {
        "task_type": "stroop",
        "accuracy": accuracy,
        "mean_reaction_ms": mean_reaction,
        "errors": errors,
        "misses": 0,
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
        1: render_reproduction,
        2: render_prospective,
        3: render_estimation,
        4: render_stroop,
        5: render_context,
        6: render_scales,
        7: render_event,
    }
    if step == 8:
        render_review(participant_id)
    else:
        renderers[step]()

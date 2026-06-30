"""Longitudinal metric computation and Plotly figures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


CHART_COLORS = ["#1769aa", "#0f8b8d", "#ef8354", "#6b5ca5"]


def style_figure(figure: go.Figure, height: int = 310) -> go.Figure:
    figure.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=35, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Arial, sans-serif", color="#334e68"),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=0),
    )
    figure.update_xaxes(showgrid=False, title=None)
    figure.update_yaxes(gridcolor="#e8eef3", title=None)
    return figure


def trend_chart(
    frame: pd.DataFrame,
    date_col: str,
    value_col: str,
    label: str,
) -> go.Figure:
    data = frame.copy()
    data[date_col] = pd.to_datetime(data[date_col])

    figure = px.line(
        data,
        x=date_col,
        y=value_col,
        markers=True,
        color_discrete_sequence=[CHART_COLORS[0]],
    )
    figure.update_traces(
        line=dict(width=3),
        marker=dict(size=6),
        name=label,
    )
    return style_figure(figure)


def multi_trend(frame: pd.DataFrame) -> go.Figure:
    data = frame.copy()
    data["recorded_at"] = pd.to_datetime(data["recorded_at"])
    data = data.rename(
        columns={
            "stress_score": "Stress",
            "hrv": "HRV",
            "sleep_hours": "Sleep",
        }
    )

    long = data.melt(
        id_vars="recorded_at",
        value_vars=["Stress", "HRV", "Sleep"],
        var_name="Metric",
        value_name="Value",
    )

    figure = px.line(
        long,
        x="recorded_at",
        y="Value",
        color="Metric",
        markers=True,
        color_discrete_sequence=CHART_COLORS,
    )
    return style_figure(figure, 340)


def correlation_chart(
    frame: pd.DataFrame,
    x: str,
    y: str,
    x_label: str,
) -> go.Figure:
    figure = px.scatter(
        frame,
        x=x,
        y=y,
        labels={
            x: x_label,
            y: "Time distortion (seconds)",
        },
        color_discrete_sequence=[CHART_COLORS[2]],
    )
    figure.update_traces(marker=dict(size=10, opacity=0.78))

    clean = frame[[x, y]].dropna()

    if len(clean) >= 3 and clean[x].nunique() > 1:
        slope, intercept = np.polyfit(clean[x], clean[y], 1)
        x_values = np.linspace(clean[x].min(), clean[x].max(), 100)

        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=slope * x_values + intercept,
                mode="lines",
                name="Linear trend",
                line=dict(
                    color=CHART_COLORS[0],
                    width=2,
                    dash="dash",
                ),
            )
        )

    return style_figure(figure)


def add_derived_assessment_metrics(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    if frame.empty:
        return frame

    result = frame.copy()
    result["submitted_at"] = pd.to_datetime(
        result["submitted_at"],
        utc=True,
    )
    result = result.sort_values("submitted_at")

    result["stress_moving_average"] = (
        result["stress"].rolling(3, min_periods=1).mean()
    )

    result["stress_7_day_average"] = (
        result.set_index("submitted_at")["stress"]
        .rolling("7D")
        .mean()
        .values
    )

    return result

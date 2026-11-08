"""Plotly figures for the economics tab. Pure functions so they can be tested without Shiny."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from .economics import PCM_PRICE_USD_PER_KG, EconInputs, EconResult, npv_grid

BLUE, ORANGE, GREY = "#2563eb", "#d97706", "#64748b"


def breakeven_figure(res: EconResult, inp: EconInputs, material_key: str) -> go.Figure:
    """NPV(PCM vs water) over PCM price x chiller cost. The zero contour is the break-even line."""
    prices = np.logspace(np.log10(0.02), np.log10(10.0), 70)
    chillers = np.linspace(250.0, 3000.0, 60)
    z = npv_grid(res, prices, chillers)
    lim = float(np.max(np.abs(z))) or 1.0
    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        x=prices, y=chillers, z=z, zmid=0.0, zmin=-lim, zmax=lim, colorscale="RdBu",
        colorbar={"title": "5-yr NPV ($)<br>blue = PCM wins"},
        hovertemplate="PCM $%{x:.3f}/kg<br>Chiller $%{y:,.0f}/ton<br>NPV $%{z:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Contour(
        x=prices, y=chillers, z=z, showscale=False, hoverinfo="skip",
        contours={"start": 0.0, "end": 0.0, "size": 1.0, "coloring": "none"},
        line={"color": "black", "width": 2},
    ))
    lo, _, hi = PCM_PRICE_USD_PER_KG[material_key]
    fig.add_vrect(x0=lo, x1=hi, line_width=0, fillcolor="black", opacity=0.07,
                  annotation_text="sourced price range", annotation_position="top left")
    fig.add_trace(go.Scatter(
        x=[inp.pcm_usd_per_kg], y=[inp.chiller_usd_per_ton], mode="markers",
        marker={"size": 12, "color": "white", "line": {"color": "black", "width": 2}},
        name="current inputs", hovertemplate="current inputs<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white", height=420, margin={"l": 50, "r": 10, "t": 20, "b": 50},
        xaxis={"type": "log", "title": "PCM material price ($/kg)"},
        yaxis={"title": "Installed chiller cost ($/ton), unsourced axis"},
        legend={"orientation": "h", "y": 1.1},
    )
    return fig


def sensitivity_figure(rows: list[dict]) -> go.Figure:
    """Tornado: change in NPV versus the base case when each input moves across its range."""
    base = rows[0]["base"]
    rows = sorted(rows, key=lambda r: abs(r["npv_high"] - r["npv_low"]))
    labels = [r["label"] for r in rows]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels, x=[r["npv_low"] - base for r in rows], orientation="h", name="low end of range",
        marker_color=BLUE,
        customdata=[[r["low"], r["npv_low"]] for r in rows],
        hovertemplate="input = %{customdata[0]}<br>NPV $%{customdata[1]:,.0f}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=labels, x=[r["npv_high"] - base for r in rows], orientation="h", name="high end of range",
        marker_color=ORANGE,
        customdata=[[r["high"], r["npv_high"]] for r in rows],
        hovertemplate="input = %{customdata[0]}<br>NPV $%{customdata[1]:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white", barmode="overlay", height=320,
        margin={"l": 10, "r": 10, "t": 20, "b": 40},
        xaxis={"title": f"Change in NPV vs base case (${base:,.0f})", "zeroline": True},
        legend={"orientation": "h", "y": 1.15},
    )
    return fig

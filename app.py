"""Flux Capacitor: Shiny research prototype for water vs PCM storage.

Run: shiny run --reload app.py
The initial prototype does NOT estimate electrical savings, prices, or CO2e.
"""
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_widget

from pcm.materials import MATERIALS, get_material
from pcm.thermal import Config, simulate, summarize
from pcm.workload import normalize_month

BASE = Path(__file__).parent
LABELS = {key: f"{m.category} — {m.name}" for key, m in MATERIALS.items()}

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.h4("System configuration"),
        ui.input_file("workload_file", "IT power profile (.csv)", accept=[".csv"]),
        ui.p("No file: synthetic demonstration profile, NOT an ESIF measurement.", class_="small text-muted"),
        ui.input_select("material", "PCM material", choices=LABELS, selected="rt35hc"),
        ui.input_checkbox("graphite", "Hypothetical nano-graphite enhancement", value=False),
        ui.input_numeric("panels", "Number of identical panels", value=100, min=1, max=10000),
        ui.input_slider("thickness", "Panel thickness (mm)", min=20, max=100, value=50, step=5),
        ui.input_action_button("run", "Run month simulation", class_="btn-primary w-100"),
        ui.hr(),
        ui.p("Fixed temperatures: 27 °C supply / 37 °C return. Panel face: 1 m².", class_="small"),
        ui.p("Controller: same daily top-8/bottom-8 IT-power-hour schedule for both materials. Not price optimization.", class_="small text-muted"),
        width=350,
    ),
    ui.div(
        ui.h2("Flux Capacitor"),
        ui.p("Liquid-cooled data center | water vs PCM storage | research prototype"),
        ui.div("THERMAL RESULTS ONLY — cost, grid electricity and emissions models not yet implemented.", class_="alert alert-warning"),
        ui.output_ui("summary_cards"),
        ui.layout_columns(
            ui.card(ui.card_header("Heat transferred to storage (kW thermal)"), output_widget("storage_plot")),
            ui.card(ui.card_header("PCM melt fraction (%)"), output_widget("melt_plot")),
            col_widths=[6, 6],
        ),
        ui.card(ui.card_header("Raw IT workload and resulting heat-rejection load (kW thermal)"), output_widget("load_plot")),
        ui.card(ui.card_header("Model assumptions & limitations"), ui.output_text_verbatim("assumptions")),
        ui.card(ui.card_header("First week of hourly results"), ui.output_data_frame("result_table")),
    ),
    title="Flux Capacitor | PCM Lab",
    fillable=True,
)


def _fig(title: str, lines: list[tuple]):
    fig = go.Figure()
    for t, y, name, color in lines:
        fig.add_trace(go.Scatter(x=t, y=y, name=name, mode="lines", line={"color": color, "width": 2}))
    fig.update_layout(title=None, xaxis_title="UTC time", yaxis_title=title,
                      margin={"l": 34, "r": 10, "t": 18, "b": 36},
                      legend={"orientation":"h", "y":1.12, "x":0},
                      template="plotly_white", height=350)
    return fig


def server(input, output, session):
    @reactive.calc
    @reactive.event(input.run)
    def model():
        try:
            upload = input.workload_file()
            if upload:
                raw = pd.read_csv(upload[0]["datapath"])
                label = f"Uploaded CSV ({upload[0]['name']})"
            else:
                raw = pd.read_csv(BASE / "data" / "sample_synthetic_2025_07.csv")
                label = "Synthetic demo (not measured)"
            load = normalize_month(raw)
            mat = get_material(input.material(), input.graphite())
            cfg = Config(panels=int(input.panels()), thickness_m=float(input.thickness())/1000)
            result = simulate(load, mat, cfg)
            return {"result": result, "summary": summarize(result), "material": mat, "label": label, "cfg": cfg}
        except Exception as exc:
            return {"error": f"Cannot run simulation: {exc}"}

    @render.ui
    def summary_cards():
        data = model()
        if not data:
            return ui.p("Choose a PCM and press Run month simulation.")
        if "error" in data:
            return ui.div(data["error"], class_="alert alert-danger")
        s, cfg = data["summary"], data["cfg"]
        return ui.div(
            ui.p(f"Data: {data['label']} | {len(data['result'])} hourly readings | Volume: {cfg.panels*cfg.area_per_panel_m2*cfg.thickness_m:.2f} m³", class_="text-muted"),
            ui.layout_columns(
                ui.value_box("PCM heat absorbed over month", f"{s['pcm_heat_absorbed_kwh']:,.0f} kWhₜₕ"),
                ui.value_box("Water heat absorbed over month", f"{s['water_heat_absorbed_kwh']:,.0f} kWhₜₕ"),
                ui.value_box("Maximum PCM melt fraction", f"{s['pcm_max_melt_percent']:.1f}%"),
                col_widths=[4,4,4],
            ),
        )

    @render_widget
    def storage_plot():
        d = model()
        if not d or "error" in d:
            return go.Figure()
        r = d["result"]
        return _fig("Thermal kW (+ charging / − regenerating)", [
            (r.timestamp, r.pcm_storage_kw, "PCM", "#d97706"),
            (r.timestamp, r.water_storage_kw, "Water", "#2563eb"),
        ])

    @render_widget
    def melt_plot():
        d = model()
        if not d or "error" in d:
            return go.Figure()
        r = d["result"]
        return _fig("Melted (%)", [(r.timestamp, r.pcm_melt_fraction*100, "PCM", "#d97706")])

    @render_widget
    def load_plot():
        d = model()
        if not d or "error" in d:
            return go.Figure()
        r = d["result"]
        return _fig("Heat rejection load, NOT electricity (kWₜₕ)", [
            (r.timestamp, r.it_power_kw, "IT power ≈ heat", "#64748b"),
            (r.timestamp, r.pcm_plant_thermal_kw, "With PCM", "#d97706"),
            (r.timestamp, r.water_plant_thermal_kw, "With water", "#2563eb"),
        ])

    @render.text
    def assumptions():
        d = model()
        if not d or "error" in d:
            return "Run a simulation to see material-specific assumptions."
        return (f"{d['material'].name}\n\n"
                f"{d['material'].limitations}\n\n"
                "Module boundaries: prescribed return 37°C during charge; prescribed supply 27°C during regeneration. "
                "Panel back face insulated, 1D conduction, idealized uniform interface coefficient. "
                "No heat-exchanger pressure drop, tank wall/encapsulation, hysteresis, corrosion, graphite cost, "
                "weather-linked cooling plant, or measured facility calibration. \n"
                "Comparison is heat shifted, not electricity/cost/emission savings. Both systems use identical geometry "
                "and the same fixed load-ranking dispatch heuristic.\n"
                f"Material source: {d['material'].source_url}")

    @render.data_frame
    def result_table():
        d = model()
        if not d or "error" in d:
            return render.DataGrid(pd.DataFrame())
        return render.DataGrid(d["result"].head(168).round(3), filters=True)

app = App(app_ui, server)

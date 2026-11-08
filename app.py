"""Flux Capacitor: Shiny research prototype for water vs PCM storage.

Run: shiny run --reload app.py
Thermal tab: heat shifted by water vs PCM. Economics tab: exploratory five-year
PCM-vs-water comparison. Every economic input carries a provenance label; several
are unsourced placeholders. See SOURCES.md.
"""
import asyncio
from time import perf_counter
from html import escape
import json
import numpy as np
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_widget

from pcm.econ_plots import breakeven_figure, sensitivity_figure
from pcm.economics import (
    ASSUMPTION, INPUT_META, PCM_PRICE_NOTE, PCM_PRICE_SOURCE, PCM_PRICE_USD_PER_KG, PLACEHOLDER,
    RANGE, SOURCED, EconInputs, evaluate, pcm_price_default, sensitivity,
)
from pcm.materials import MATERIALS, get_material
from pcm.peak_dispatch import optimize_peak_dispatch
from pcm.cycles import audit_cycles
from pcm.plant import PlantConfig, simulate_plant, plant_summary
from pcm.lifecycle import LifecycleInputs, evaluate_lifecycle
from pcm.thermal import Config, simulate, summarize
from pcm.workload import normalize_month

BASE = Path(__file__).parent
LABELS = {key: f"{m.category} — {m.name}" for key, m in MATERIALS.items()}
STATUS_COLOR = {SOURCED: "#15803d", RANGE: "#b45309", ASSUMPTION: "#475569", PLACEHOLDER: "#b91c1c"}


def _badge(status: str) -> str:
    return (f'<span style="background:{STATUS_COLOR[status]};color:#fff;border-radius:3px;'
            f'padding:1px 6px;font-size:0.75em;white-space:nowrap">{escape(status)}</span>')


def _hint(key: str):
    m = INPUT_META[key]
    short = m.source.split(". ")[0].rstrip(".") + "."
    return ui.HTML(f'<div class="small text-muted mb-3">{_badge(m.status)} {escape(short)}</div>')


def _usd(x: float) -> str:
    x = round(x)  # also turns -0.0 into 0
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def _link(url: str, text: str) -> str:
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">{escape(text)}</a>' if url else escape(text)


M = INPUT_META
econ_inputs_card = ui.card(
    ui.card_header("Assumptions (editable)"),
    ui.input_numeric("pcm_price", "PCM material price ($/kg)", value=pcm_price_default("rt35hc"), min=0, step=0.01),
    ui.output_ui("pcm_price_hint"),
    ui.input_numeric("e_price", f"{M['electricity_c_per_kwh'].label} (¢/kWh)", value=M["electricity_c_per_kwh"].default, min=0, step=0.5),
    _hint("electricity_c_per_kwh"),
    ui.input_numeric("d_charge", f"{M['demand_usd_per_kw_month'].label} ($/kW-month)", value=M["demand_usd_per_kw_month"].default, min=0, step=1),
    _hint("demand_usd_per_kw_month"),
    ui.input_numeric("kw_ton", f"{M['chiller_kw_per_ton'].label} (kW/ton)", value=M["chiller_kw_per_ton"].default, min=0.1, step=0.01),
    _hint("chiller_kw_per_ton"),
    ui.input_numeric("chiller_cost", f"{M['chiller_usd_per_ton'].label} ($/ton)", value=M["chiller_usd_per_ton"].default, min=0, step=50),
    _hint("chiller_usd_per_ton"),
    ui.input_numeric("extra_m2", f"{M['pcm_extra_usd_per_m2'].label} ($/m² of panel)", value=M["pcm_extra_usd_per_m2"].default, min=0, step=10),
    _hint("pcm_extra_usd_per_m2"),
    ui.input_numeric("disc_pct", "Discount rate (%/yr)", value=M["discount_rate"].default * 100, min=0, max=50, step=0.5),
    _hint("discount_rate"),
    ui.p("Horizon fixed at 5 years.", class_="small text-muted"),
)

METHOD_MD = """
**What is compared.** The PCM array against the water array from the Thermal tab (same panels,
volume and controller algorithm, but independently chosen feasible thresholds in optimized mode).
*Positive NPV = PCM beats water under these modeling assumptions*, not versus no storage.

**Value streams**

- *Chiller capacity*: `(peak plant load with water − peak plant load with PCM) ÷ 3.517 kW/ton × $/ton`.
  Negative if PCM raises the peak.
- *Demand charge*: `peak shaved (kWₜₕ) × (kW/ton ÷ 3.517) × $/kW-month × 12`.
- *Energy*: hourly cooling electricity × price. With a flat tariff this is **zero by construction**:
  storage moves heat to other hours, it does not remove it.

**Costs.** PCM material (`mass × $/kg`, mass = solid density × panel volume) plus an optional containment
premium, minus water fill. Panel hardware, heat exchangers and installation are assumed identical for
both and cancel.

**Roll-up.** `NPV = annual savings × Σ 1/(1+r)^t (t = 1…5) − (PCM cost − avoided chiller capex)`.
Break-even price and break-even chiller cost solve `NPV = 0` for one input with the others fixed.

**Read this before quoting anything.** The simulated month is scaled to a year; billed demand is assumed to
follow the cooling peak; chiller efficiency is constant; containment cost for corrosive salt hydrates is not
included (this favours PCM); and the default workload is synthetic.
"""

LOADER_STYLE = "\n#flux-sim-loader { position:fixed; inset:0; z-index:1050; display:flex; align-items:center; justify-content:center; background:rgba(248,250,252,.96); opacity:0; visibility:hidden; pointer-events:none; transition:opacity .2s ease,visibility .2s ease; }\n#flux-sim-loader.visible { opacity:1; visibility:visible; pointer-events:auto; }\n.flux-sketch-card { width:min(760px,90vw); padding:clamp(18px,4vw,40px); color:#163047; text-align:center; }\n.flux-sketch-card h3 { font-size:clamp(20px,3vw,29px); font-weight:650; letter-spacing:-.03em; margin:0 0 6px; }\n.flux-sketch-card p { color:#56697c; font-size:14px; margin:6px 0 14px; }\n.flux-sketch { display:block; width:100%; max-height:360px; margin:10px auto 16px; overflow:visible; }\n.flux-sketch path, .flux-sketch line, .flux-sketch rect { stroke-linecap:round; stroke-linejoin:round; fill:none; vector-effect:non-scaling-stroke; }\n.flux-sketch .trace { stroke:#34739d; stroke-width:2; stroke-dasharray:1600; stroke-dashoffset:1600; animation:flux-trace 4.8s ease-in-out infinite; }\n.flux-sketch .detail { stroke:#5ca9bd; stroke-width:1.5; }\n.flux-sketch .delay-1 { animation-delay:.30s; } .flux-sketch .delay-2 { animation-delay:.65s; } .flux-sketch .delay-3 { animation-delay:1.0s; } .flux-sketch .delay-4 { animation-delay:1.35s; }\n.flux-sketch .flux-coolant { stroke:#26a3b3; stroke-width:3; stroke-dasharray:9 14; animation:flux-flow 1.0s linear infinite; }\n.flux-status { display:flex; align-items:center; justify-content:center; gap:10px; font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:#496077; }\n.flux-status:before { content:\"\"; display:inline-block; width:8px; height:8px; border-radius:50%; background:#269eb5; animation:flux-pulse 1s ease-in-out infinite alternate; }\n@keyframes flux-trace { 0% { stroke-dashoffset:1600;opacity:.7; } 42%,78% { stroke-dashoffset:0;opacity:1; } 100% { stroke-dashoffset:-1600;opacity:.25; } }\n@keyframes flux-flow { to { stroke-dashoffset:-23; } }\n@keyframes flux-pulse { to { transform:scale(1.4);opacity:.3; } }\n@media (prefers-reduced-motion:reduce) { .flux-sketch .trace { animation:none;stroke-dashoffset:0; } .flux-sketch .flux-coolant,.flux-status:before { animation:none; } }"
LOADER_SCRIPT = "\n(function(){\n  var timer = null;\n  function overlay(){ return document.getElementById(\"flux-sim-loader\"); }\n  function setBusy(busy){\n    if(timer){ clearTimeout(timer); timer=null; }\n    var run=document.getElementById(\"run\");\n    if(run) { if(busy) setTimeout(function(){run.disabled=true;},0); else run.disabled=false; }\n    if(busy){\n      timer=setTimeout(function(){ var el=overlay(); if(el){ el.classList.add(\"visible\"); el.setAttribute(\"aria-hidden\",\"false\"); } },220);\n    } else {\n      var el=overlay(); if(el){ el.classList.remove(\"visible\"); el.setAttribute(\"aria-hidden\",\"true\"); }\n    }\n  }\n  document.addEventListener(\"click\",function(e){\n    if(e.target.closest && e.target.closest(\"#run\"))setBusy(true);\n  },true);\n  function register(){\n    if(window.Shiny && !window.__fluxHandlerRegistered) {\n      window.__fluxHandlerRegistered=true;\n      Shiny.addCustomMessageHandler(\"flux_sim_finished\",function(){ setBusy(false); });\n    }\n  }\n  document.addEventListener(\"shiny:connected\",register);\n  document.addEventListener(\"shiny:disconnected\",function(){setBusy(false);});\n  if(document.readyState===\"loading\")document.addEventListener(\"DOMContentLoaded\",register);else register();\n})();"
LOADER_HTML = "\n<div id=\"flux-sim-loader\" aria-live=\"polite\" aria-hidden=\"true\" role=\"status\">\n  <div class=\"flux-sketch-card\">\n    <h3>Tracing the cooling system</h3>\n    <p>Testing feasible thermal peak limits and repeatable storage states</p>\n    <svg class=\"flux-sketch\" viewBox=\"0 0 760 350\" aria-label=\"Animated line sketch of server racks and a data center cooling loop\">\n      <g class=\"trace\">\n        <path d=\"M60 295 L160 95 L600 95 L700 295 M60 295 L700 295 M160 95 L160 38 L600 38 L600 95 M160 38 L60 217 M600 38 L700 217\"/>\n      </g>\n      <g class=\"trace detail delay-1\">\n        <path d=\"M98 252 L205 118 L303 118 L262 252 Z M116 252 L209 137 L291 137 L252 252 M150 252 L222 154 M192 252 L240 174 M225 252 L256 196\"/>\n        <path d=\"M457 118 L555 118 L662 252 L498 252 Z M469 137 L551 137 L644 252 M485 154 L611 252 M502 174 L568 252\"/>\n      </g>\n      <g class=\"trace detail delay-2\">\n        <path d=\"M314 115 L446 115 L492 292 L268 292 Z M338 133 L423 133 L456 270 L304 270 Z M330 171 L431 171 M322 207 L438 207 M313 244 L447 244\"/>\n        <path d=\"M145 277 L620 277 M174 308 L590 308 M326 328 L434 328\"/>\n      </g>\n      <g class=\"trace delay-3\">\n        <path d=\"M196 70 L565 70 L589 47 M200 78 L193 118 M548 78 L568 118 M379 70 L379 111\"/>\n        <path d=\"M44 320 L244 320 L264 306 M716 320 L516 320 L496 306\"/>\n      </g>\n      <g class=\"trace detail delay-4\">\n        <path d=\"M42 275 L42 328 L119 328 M641 328 L718 328 L718 275\"/>\n        <path d=\"M61 303 L83 303 M677 303 L699 303 M63 312 L88 312 M673 312 L697 312\"/>\n      </g>\n      <path class=\"flux-coolant\" d=\"M189 58 H580 L622 112 M190 58 L141 110\" />\n    </svg>\n    <div class=\"flux-status\">Calculating feasible peaks · No progress percentage estimated</div>\n  </div>\n</div>"

app_ui = ui.page_sidebar(
    ui.sidebar(
        ui.h4("System configuration"),
        ui.input_file("workload_file", "IT power profile (.csv)", accept=[".csv"]),
        ui.p("No file: synthetic demonstration profile, NOT an ESIF measurement.", class_="small text-muted"),
        ui.input_select("material", "PCM material", choices=LABELS, selected="rt35hc"),
        ui.input_checkbox("graphite", "Hypothetical nano-graphite enhancement", value=False),
        ui.input_numeric("panels", "Number of identical panels", value=100, min=1, max=10000),
        ui.input_slider("thickness", "Panel thickness (mm)", min=20, max=100, value=50, step=5),
        ui.input_slider("capture_fraction", "IT heat captured in modeled liquid loop (%)", min=20, max=100, value=100, step=5),
        ui.p("Liquid capture fraction is an assumption; the remainder still contributes to total IT electricity, but is outside this modeled cooling loop.", class_="small text-muted"),
        ui.input_select("dispatch", "Cooling dispatch", choices={
            "optimized": "Optimize each storage system's thermal peak",
            "legacy": "Original daily top/bottom-eight-hours heuristic",
        }, selected="optimized"),
        ui.input_checkbox("cap_regen", "Legacy only: cap regeneration at no-storage peak", value=True),
        ui.p("Idealization: uses the month's peak IT load in advance, same rule for water and PCM. Off reproduces the milestone-1 heuristic.", class_="small text-muted"),
        ui.input_action_button("run", "Run month simulation", class_="btn-primary w-100"),
        ui.hr(),
        ui.p("Fixed temperatures: 27 °C supply / 37 °C return. Panel face: 1 m².", class_="small"),
        ui.p("Optimized mode searches independent, feasible hourly thermal-peak ceilings for PCM and water; idealized month-ahead knowledge. Legacy mode retains the eight-hour heuristic.", class_="small text-muted"),
        ui.p("Economics assumptions live on the Economics tab and update instantly; the simulation re-runs only when you press Run.", class_="small text-muted"),
        width=350,
    ),
    ui.head_content(ui.tags.style(LOADER_STYLE), ui.tags.script(LOADER_SCRIPT)),
    ui.HTML(LOADER_HTML),
    ui.div(
        ui.h2("Flux Capacitor"),
        ui.p("Liquid-cooled data center | water vs PCM storage | research prototype"),
        ui.navset_tab(
            ui.nav_panel(
                "Thermal",
                ui.div("THERMAL RESULTS — default profile is synthetic. See Plant & lifecycle for electricity, costs and emissions.", class_="alert alert-warning mt-2"),
                ui.output_ui("dispatch_note"),
                ui.output_ui("summary_cards"),
                ui.layout_columns(
                    ui.card(ui.card_header("Heat transferred to storage (kW thermal)"), output_widget("storage_plot")),
                    ui.card(ui.card_header("Storage state: PCM melt fraction and water sensible proxy (%)"), output_widget("melt_plot"),
                        ui.p("Water proxy is temperature between 27°C and 37°C, not a melt fraction or equal stored energy.", class_="small text-muted")),
                    col_widths=[6, 6],
                ),
                ui.card(ui.card_header("Modeled liquid-loop heat and rejection (kW thermal)"), output_widget("load_plot")),
                ui.card(ui.card_header("Model assumptions & limitations"), ui.output_text_verbatim("assumptions")),
                ui.card(ui.card_header("First week of hourly results"), ui.output_data_frame("result_table")),
            ),
            ui.nav_panel(
                "Plant & lifecycle",
                ui.div(
                    "ILLUSTRATIVE MODEL — synthetic weather when CSV has no outside_air_temp_c. "
                    "Dry-cooler availability, COP, fans, pumps, installed costs, carbon factors and annualization "
                    "are assumption-driven, not measured plant performance.",
                    class_="alert alert-warning mt-2",
                ),
                ui.layout_columns(
                    ui.card(
                        ui.card_header("Cooling plant & ambient scenario"),
                        ui.input_numeric("ambient_mean", "Synthetic mean ambient (°C)", value=27.0, min=-20, max=55, step=1),
                        ui.input_numeric("ambient_swing", "Synthetic daily temperature swing (°C)", value=6.0, min=0, max=25, step=1),
                        ui.input_numeric("plant_cop", "Nominal chiller COP at 25°C", value=4.5, min=1, max=12, step=0.25),
                        ui.p("If a CSV provides complete outside_air_temp_c, actual uploaded weather overrides the synthetic ambient scenario. Dry-cooler 4°C approach, 5°C transition, fan draw 0.025 kWe/kWth, circulation 8 kW, storage pumps 0.001 kW/panel are uncalibrated assumptions.", class_="small text-muted"),
                    ),
                    ui.card(
                        ui.card_header("Lifetime & environmental assumptions"),
                        ui.input_numeric("life_pcm_containment", "PCM containment ($/m²)", value=120, min=0, step=10),
                        ui.input_numeric("life_water_containment", "Water containment ($/m²)", value=65, min=0, step=10),
                        ui.input_numeric("life_grid_carbon", "Grid intensity (kg CO₂e/kWh)", value=0.4, min=0, max=2, step=0.05),
                        ui.input_numeric("life_pcm_embodied", "PCM embodied (kg CO₂e/kg material)", value=2.0, min=0, step=0.2),
                        ui.input_numeric("life_pcm_replace", "PCM replacement interval (years)", value=8, min=1, step=1),
                        ui.input_numeric("life_carbon_price", "Hypothetical shadow carbon price ($/tonne)", value=0, min=0, step=10),
                        ui.input_checkbox("life_capacity_credit", "Explore chiller capacity credit (only if both cycle audits pass)", value=False),
                        ui.p("Electricity, demand, PCM price and discount rate are editable on the Economics tab and also used here. Lifetime costs assume a five-year horizon and repeat the selected month 12 times/year.", class_="small text-muted"),
                    ),
                    col_widths=[6, 6],
                ),
                ui.output_ui("plant_notes"),
                ui.output_ui("plant_cards"),
                ui.card(ui.card_header("Modeled cooling electricity (kW electrical)"), output_widget("plant_power_plot")),
                ui.layout_columns(
                    ui.card(ui.card_header("Five-year incremental PCM-versus-water cash flow"), ui.output_data_frame("lifecycle_cash_table")),
                    ui.card(ui.card_header("Data & reproducibility exports"),
                            ui.p("Download the hourly modeled facility/thermal data and all effective assumptions. Simulation inputs are labeled as synthetic or uploaded.", class_="small text-muted"),
                            ui.download_button("download_hourly", "Export hourly CSV", class_="btn-outline-primary"),
                            ui.download_button("download_assumptions", "Export assumptions JSON", class_="btn-outline-secondary"),
                    ),
                    col_widths=[8, 4],
                ),
            ),
            ui.nav_panel(
                "Economics (legacy thermal proxy)",
                ui.div("LEGACY THERMAL-PROXY ECONOMICS. This historical tab does not use the new ambient-dependent plant electricity or cyclic safeguards. For the preferred updated view use Plant & lifecycle.", class_="alert alert-danger mt-2"),
                ui.output_ui("econ_notes"),
                ui.layout_columns(
                    econ_inputs_card,
                    ui.div(
                        ui.output_ui("econ_cards"),
                        ui.card(ui.card_header("Where the NPV comes from"), ui.output_ui("npv_breakdown")),
                    ),
                    col_widths=[4, 8],
                ),
                ui.card(
                    ui.card_header("Break-even map: where does PCM beat water?"),
                    ui.p("Each point is the 5-year NPV of PCM versus water for that PCM price and chiller cost, holding the "
                         "simulated thermal result and other inputs fixed. The black line is NPV = 0.", class_="small text-muted"),
                    output_widget("breakeven_plot"),
                ),
                ui.layout_columns(
                    ui.card(ui.card_header("Sensitivity (one input at a time)"), output_widget("sens_plot")),
                    ui.card(ui.card_header("Five-year cash flow (PCM relative to water)"), ui.output_data_frame("cash_table")),
                    col_widths=[6, 6],
                ),
                ui.card(ui.card_header("How the numbers are computed"), ui.markdown(METHOD_MD)),
                ui.card(ui.card_header("Input provenance"), ui.output_ui("provenance")),
            ),
        ),
    ),
    title="Flux Capacitor | PCM Lab",
    fillable=False,
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
    model_state = reactive.value(None)

    @reactive.calc
    def model():
        return model_state.get()

    @reactive.effect
    @reactive.event(input.run)
    async def _run_model():
        started = perf_counter()
        try:
            upload = input.workload_file()
            if upload:
                raw = pd.read_csv(upload[0]["datapath"])
                label = f"Uploaded CSV ({upload[0]['name']})"
            else:
                raw = pd.read_csv(BASE / "data" / "sample_synthetic_2025_07.csv")
                label = "Synthetic demo (not measured)"
            load = normalize_month(raw)
            thermal_load = load.copy()
            thermal_load["it_power_kw"] = load.it_power_kw * (float(input.capture_fraction()) / 100.0)
            mat = get_material(input.material(), input.graphite())
            cfg = Config(panels=int(input.panels()), thickness_m=float(input.thickness())/1000,
                         cap_regeneration=bool(input.cap_regen()))
            dispatch = input.dispatch()
            audit = None
            if dispatch == "optimized":
                _single_month, peak = await asyncio.to_thread(optimize_peak_dispatch, thermal_load, mat, cfg)
                # Periodic-state replay is required before showing capacity credit.
                result, audit = await asyncio.to_thread(audit_cycles, thermal_load, mat, cfg, peak)
            else:
                result = await asyncio.to_thread(simulate, thermal_load, mat, cfg)
                peak = None
            result["facility_it_electric_kw"] = load.it_power_kw.to_numpy(float)
            model_state.set({
                "result": result, "summary": summarize(result), "material": mat,
                "label": label, "cfg": cfg, "synthetic": not upload,
                "dispatch": dispatch, "peak": peak, "audit": audit, "load": load,
                "capture_fraction": float(input.capture_fraction())/100,
                "elapsed_s": perf_counter() - started,
            })
        except Exception as exc:
            model_state.set({"error": f"Cannot run simulation: {exc}"})
        finally:
            await session.send_custom_message("flux_sim_finished", {})

    @render.ui
    def dispatch_note():
        d = model()
        if not d or "error" in d:
            return ui.div()
        if d["dispatch"] == "optimized":
            pk = d["peak"]
            audit = d["audit"]
            assert pk is not None and audit is not None
            pstate = "PASS" if audit.pcm_verified else "NOT VERIFIED"
            wstate = "PASS" if audit.water_verified else "NOT VERIFIED"
            return ui.div(
                ui.strong("Month-ahead threshold search + repeat-month thermal-state audit"),
                ui.p(
                    f"Initial monthly target: PCM {pk.pcm_target_kw:,.2f} kWₜₕ; water "
                    f"{pk.water_target_kw:,.2f} kWₜₕ. Replayed month measured peaks: "
                    f"PCM {d['result'].pcm_plant_thermal_kw.max():,.2f}, "
                    f"water {d['result'].water_plant_thermal_kw.max():,.2f} kWₜₕ. "
                    f"Thermal-state cycle audit after {audit.passes} passes — "
                    f"PCM {pstate} ({audit.pcm_state_drift_kwh:.2f} kWhₜₕ drift), "
                    f"water {wstate} ({audit.water_state_drift_kwh:.2f} kWhₜₕ drift). "
                    f"Runtime {d['elapsed_s']:.1f} s.",
                    class_="mb-1",
                ),
                ui.p(
                    "PASS checks repeatability of an identical synthetic month only. "
                    "It cannot prove a real seasonal or equipment-level capacity benefit; "
                    "unverified systems receive no equipment capacity credit. "
                    "PCM/water compare on the same geometry and thermal constraints. "
                    + audit.note,
                    class_="small mb-0",
                ),
                class_="alert alert-info mt-2" if audit.pcm_verified and audit.water_verified else "alert alert-warning mt-2",
            )
        return ui.div(
            "Legacy fixed-hour controller (no cyclic validation); regeneration cap "
            + ("on" if d["cfg"].cap_regeneration else "off")
            + f". Runtime {d['elapsed_s']:.1f} s. No capacity credit.",
            class_="alert alert-secondary mt-2",
        )

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
        cfg = d["cfg"]
        water_fraction = np.clip((r.water_mean_c-cfg.supply_c)/(cfg.return_c-cfg.supply_c), 0, 1)*100
        return _fig("State proxy (%)", [
            (r.timestamp, r.pcm_melt_fraction*100, "PCM molten fraction", "#d97706"),
            (r.timestamp, water_fraction, "Water sensible range fraction", "#2563eb"),
        ])

    @render_widget
    def load_plot():
        d = model()
        if not d or "error" in d:
            return go.Figure()
        r = d["result"]
        return _fig("Heat rejection load, NOT electricity (kWₜₕ)", [
            (r.timestamp, r.it_power_kw, "Captured liquid-loop IT heat", "#64748b"),
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
                "Comparison is heat shifted; cost effects are on the Economics tab and rest on the assumptions listed there. " +
                ("Optimized independent load-ceiling dispatch with perfect monthly foresight.\n"
                 if d["dispatch"] == "optimized" else
                 "Both systems use the same fixed load-ranking heuristic.\n") +
                f"Material source: {d['material'].source_url}")

    @render.data_frame
    def result_table():
        d = model()
        if not d or "error" in d:
            return render.DataGrid(pd.DataFrame())
        return render.DataGrid(d["result"].head(168).round(3), filters=True)

    @reactive.calc
    def plant_and_lifecycle():
        d = model()
        if not d or "error" in d:
            return None
        vals = (input.ambient_mean(), input.ambient_swing(), input.plant_cop(),
                input.life_pcm_containment(), input.life_water_containment(),
                input.life_grid_carbon(), input.life_pcm_embodied(),
                input.life_pcm_replace(), input.life_carbon_price(),
                input.e_price(), input.d_charge(), input.disc_pct(), input.pcm_price())
        if any(v is None for v in vals):
            return {"error": "Fill in every input in Plant & lifecycle and Economics."}
        try:
            cfg = PlantConfig(
                supply_c=d["cfg"].supply_c,
                scenario_ambient_mean_c=float(input.ambient_mean()),
                scenario_ambient_swing_c=float(input.ambient_swing()),
                nominal_chiller_cop=float(input.plant_cop()),
            )
            has_weather = "outside_air_temp_c" in d["load"].columns
            ambient = d["load"]["outside_air_temp_c"].to_numpy(float) if has_weather else None
            plant = simulate_plant(d["result"], cfg, panels=d["cfg"].panels,
                                   facility_it_kw=d["result"].facility_it_electric_kw.to_numpy(float),
                                   ambient_c=ambient)
            life_input = LifecycleInputs(
                pcm_material_usd_kg=float(input.pcm_price()),
                energy_price_usd_kwh=float(input.e_price()) / 100,
                demand_charge_usd_kw_month=float(input.d_charge()),
                discount_rate=float(input.disc_pct()) / 100,
                pcm_containment_usd_m2=float(input.life_pcm_containment()),
                water_containment_usd_m2=float(input.life_water_containment()),
                grid_kgco2e_kwh=float(input.life_grid_carbon()),
                pcm_embodied_kgco2e_kg=float(input.life_pcm_embodied()),
                pcm_replace_years=int(input.life_pcm_replace()),
                shadow_price_usd_tco2e=float(input.life_carbon_price()),
                allow_capacity_credit=bool(input.life_capacity_credit()),
            )
            audit = d["audit"]
            lifecycle = evaluate_lifecycle(
                plant, d["material"], d["cfg"], life_input,
                pcm_cycle_verified=bool(audit and audit.pcm_verified),
                water_cycle_verified=bool(audit and audit.water_verified),
            )
            return {"plant": plant, "summary": plant_summary(plant),
                    "lifecycle": lifecycle, "inputs": life_input, "plant_cfg": cfg,
                    "measured_weather": has_weather}
        except (ValueError, OverflowError) as exc:
            return {"error": str(exc)}

    @render.ui
    def plant_notes():
        x = plant_and_lifecycle()
        if not x:
            return ui.p("Press Run month simulation to populate plant and lifecycle results.")
        if "error" in x:
            return ui.div(x["error"], class_="alert alert-danger")
        status = "uploaded complete weather" if x["measured_weather"] else "synthetic diurnal temperature scenario"
        notes = "; ".join(x["lifecycle"].warnings)
        return ui.div(
            ui.strong(f"Ambient input: {status}."),
            ui.p("All plant and lifecycle values are illustrative; no validated tariffs, weather-dependent "
                 "manufacturer performance curves, site COP or installed costs.", class_="mb-1"),
            ui.p(notes, class_="small mb-0"),
            class_="alert alert-secondary mt-2",
        )

    @render.ui
    def plant_cards():
        x = plant_and_lifecycle()
        if not x or "error" in x:
            return ui.div()
        s, r = x["summary"], x["lifecycle"]
        verdict = ("PCM lower modeled 5-year cost" if r.npv_usd > 0
                   else "Water lower modeled 5-year cost" if r.npv_usd < 0
                   else "Modeled cost tie")
        return ui.div(
            ui.p(f"Scenario verdict (not validated): {verdict}", class_="fw-semibold"),
            ui.layout_columns(
                ui.value_box("PCM cooling electricity / month",
                             f"{r.pcm_month_energy_kwh:,.0f} kWh",
                             ui.p(f"Water {r.water_month_energy_kwh:,.0f} kWh", class_="small")),
                ui.value_box("PCM facility peak",
                             f"{s['pcm']['facility_peak_kw']:,.1f} kWₑ",
                             ui.p(f"Water {s['water']['facility_peak_kw']:,.1f} kWₑ", class_="small")),
                ui.value_box("PCM minus water installed CAPEX",
                             _usd(r.pcm_capex_usd-r.water_capex_usd),
                             ui.p(f"Capacity credit {_usd(r.chiller_credit_usd)}", class_="small")),
                ui.value_box("5-year modeled incremental NPV",
                             _usd(r.npv_usd),
                             ui.p("Positive = PCM less costly; month × 12/yr", class_="small")),
                ui.value_box("5-year total modeled cooling CO₂e difference",
                             f"{(r.pcm_total_5y_kgco2e-r.water_total_5y_kgco2e):+,.0f} kg",
                             ui.p("PCM minus water, operational + media only", class_="small")),
                ui.value_box("Annual net operating advantage",
                             _usd(r.annual_operating_savings_usd),
                             ui.p("Water cost less PCM, includes assumed maintenance", class_="small")),
                col_widths=[4, 4, 4, 4, 4, 4],
            )
        )

    @render_widget
    def plant_power_plot():
        x = plant_and_lifecycle()
        if not x or "error" in x:
            return go.Figure()
        p = x["plant"]
        return _fig("Electrical kW (cooling equipment only; illustrative)", [
            (p.timestamp, p.none_cooling_electric_kw, "No storage", "#64748b"),
            (p.timestamp, p.water_cooling_electric_kw, "Water", "#2563eb"),
            (p.timestamp, p.pcm_cooling_electric_kw, "PCM", "#d97706"),
        ])

    @render.data_frame
    def lifecycle_cash_table():
        x = plant_and_lifecycle()
        if not x or "error" in x:
            return render.DataGrid(pd.DataFrame())
        return render.DataGrid(x["lifecycle"].cashflows.round(2))

    @render.download(filename="flux_capacitor_hourly.csv")
    def download_hourly():
        x = plant_and_lifecycle()
        d = model()
        if not x or "error" in x or not d or "error" in d:
            yield "Run a valid simulation before exporting."
            return
        joined = d["result"].merge(x["plant"], on="timestamp", validate="one_to_one",
                                   suffixes=("_thermal", "_plant"))
        yield joined.to_csv(index=False)

    @render.download(filename="flux_capacitor_assumptions.json")
    def download_assumptions():
        x = plant_and_lifecycle()
        d = model()
        if not x or "error" in x or not d or "error" in d:
            yield json.dumps({"error": "No valid simulation available."})
            return
        payload = {
            "workload_label": d["label"], "synthetic_workload": d["synthetic"],
            "measured_weather_uploaded": x["measured_weather"],
            "dispatch": d["dispatch"], "material": d["material"].key,
            "thermal_config": vars(d["cfg"]), "capture_fraction": d["capture_fraction"],
            "plant_config": vars(x["plant_cfg"]), "lifecycle_inputs": vars(x["inputs"]),
            "cycle_audit": vars(d["audit"]) if d["audit"] else None,
            "limitations": list(x["lifecycle"].warnings),
        }
        yield json.dumps(payload, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ economics
    @reactive.effect
    @reactive.event(input.material)
    def _sync_price_default():
        ui.update_numeric("pcm_price", value=pcm_price_default(input.material()))

    @render.ui
    def pcm_price_hint():
        key = input.material()
        lo, _, hi = PCM_PRICE_USD_PER_KG[key]
        return ui.HTML(f'<div class="small text-muted mb-3">{_badge(RANGE)} Sourced range ${lo:g}–${hi:g}/kg; default is '
                       f'the midpoint. {escape(PCM_PRICE_NOTE[key])}</div>')

    @reactive.calc
    def econ():
        d = model()
        if not d or "error" in d:
            return None
        vals = [input.pcm_price(), input.e_price(), input.d_charge(), input.kw_ton(),
                input.chiller_cost(), input.extra_m2(), input.disc_pct()]
        if any(v is None for v in vals):
            return {"error": "Fill in every assumption field."}
        inp = EconInputs(
            electricity_c_per_kwh=float(input.e_price()), demand_usd_per_kw_month=float(input.d_charge()),
            chiller_kw_per_ton=float(input.kw_ton()), chiller_usd_per_ton=float(input.chiller_cost()),
            discount_rate=float(input.disc_pct()) / 100.0, years=5,
            pcm_usd_per_kg=float(input.pcm_price()), pcm_extra_usd_per_m2=float(input.extra_m2()),
        )
        try:
            res = evaluate(d["result"], d["material"], d["cfg"], inp, synthetic=d["synthetic"])
            sens = sensitivity(d["result"], d["material"], d["cfg"], inp, synthetic=d["synthetic"])
        except ValueError as exc:
            return {"error": str(exc)}
        return {"res": res, "inp": inp, "sens": sens, "material": d["material"],
                "dispatch": d["dispatch"], "peak": d["peak"]}

    def _econ_ready():
        e = econ()
        return e if e and "error" not in e else None

    @render.ui
    def econ_notes():
        e = econ()
        if not e:
            return ui.p("Press Run month simulation to compute economics.")
        if "error" in e:
            return ui.div(e["error"], class_="alert alert-danger")
        critical_keys = ("EXCEEDS", "RAISES", "water's dispatch spike", "synthetic")
        critical = [w for w in e["res"].warnings if any(k in w for k in critical_keys)]
        alerts = "".join(f'<div class="alert alert-danger py-2 mb-2">{escape(w)}</div>' for w in critical)
        if e["dispatch"] == "optimized":
            alerts += (
                '<div class="alert alert-warning py-2 mb-2">'
                'Optimized mode uses full-month foresight and starts at 27°C. '
                'Ending storage energy can differ from the starting state; '
                'chiller capacity and demand-charge credits have NOT been '
                'validated for repeated months. Read the terminal-heat '
                'adjustment caveat in the README before quoting an NPV.'
                '</div>'
            )
        items = "".join(f"<li>{escape(w)}</li>" for w in e["res"].warnings)
        return ui.HTML(alerts + f'<details class="mb-3"><summary><b>All limitations that apply to these numbers ({len(e["res"].warnings)})</b></summary>'
                       f'<ul class="small mt-2">{items}</ul></details>')

    @render.ui
    def econ_cards():
        e = _econ_ready()
        if not e:
            return ui.p("")
        r = e["res"]
        if r.break_even_pcm_usd_per_kg <= 0:
            be_price = "none (needs ≤ $0/kg)"
        else:
            be_price = f"${r.break_even_pcm_usd_per_kg:,.2f}/kg"
        if r.break_even_chiller_usd_per_ton is None:
            be_chiller = "n/a (no capacity credit)"
        elif r.break_even_chiller_usd_per_ton <= 0:
            be_chiller = "PCM wins at any $/ton"
        else:
            be_chiller = f"${r.break_even_chiller_usd_per_ton:,.0f}/ton"
        if r.break_even_extra_usd_per_m2 <= 0:
            be_extra = "none (PCM loses even at $0/m²)"
        else:
            be_extra = f"${r.break_even_extra_usd_per_m2:,.0f}/m²"
        return ui.layout_columns(
            ui.value_box("5-year NPV, PCM vs water", _usd(r.npv), ui.p("positive = PCM wins", class_="small")),
            ui.value_box("Net upfront cost vs water", _usd(r.net_capex), ui.p("negative = PCM cheaper upfront", class_="small")),
            ui.value_box("Annual savings", _usd(r.annual_savings),
                         ui.p(f"demand {_usd(r.demand_savings_year)} + energy {_usd(r.energy_savings_year)}", class_="small")),
            ui.value_box("Cooling peak: PCM vs water", f"{r.delta_peak_kw:+.1f} kWₜₕ",
                         ui.p(f"{r.avoided_tons:+.1f} tons; positive = PCM lower", class_="small")),
            ui.value_box("Cooling peak: PCM vs no storage", f"{r.delta_peak_pcm_vs_none_kw:+.1f} kWₜₕ",
                         ui.p(f"PCM {r.peak_pcm_kw:,.0f} | water {r.peak_water_kw:,.0f} | none {r.peak_none_kw:,.0f} kWₜₕ. Negative = worse than no storage", class_="small")),
            ui.value_box("PCM mass / material cost", f"{r.pcm_mass_kg:,.0f} kg", ui.p(f"{_usd(r.pcm_material_cost)} at ${e['inp'].pcm_usd_per_kg:,.3f}/kg", class_="small")),
            ui.value_box("Break-even PCM price", be_price, ui.p("other inputs held fixed", class_="small")),
            ui.value_box("Break-even containment premium", be_extra,
                         ui.p("most extra panel cost per m² the benefit can absorb", class_="small")),
            ui.value_box("Break-even chiller cost", be_chiller, ui.p("placeholder input, see map", class_="small")),
            col_widths=[4, 4, 4, 4, 4, 4, 4, 4, 4],
        )

    @render.ui
    def npv_breakdown():
        e = _econ_ready()
        if not e:
            return ui.p("")
        r = e["res"]
        rows = [
            ("+ PV of demand-charge change", r.demand_savings_year * r.annuity_factor),
            ("+ PV of energy-cost change (flat tariff: zero by construction)", r.energy_savings_year * r.annuity_factor),
            ("+ Chiller capacity avoided (negative if PCM adds load)", r.avoided_chiller_capex),
            ("− PCM material", -r.pcm_material_cost),
            ("− PCM containment premium", -r.pcm_extra_cost),
            ("+ Water fill not needed", r.water_cost),
        ]
        body = "".join(f"<tr><td>{escape(k)}</td><td style='text-align:right'>{_usd(v)}</td></tr>" for k, v in rows)
        body += f"<tr style='border-top:2px solid #000'><td><b>= 5-year NPV, PCM vs water</b></td><td style='text-align:right'><b>{_usd(r.npv)}</b></td></tr>"
        return ui.HTML(f"<table class='table table-sm mb-0'>{body}</table>"
                       f"<div class='small text-muted mt-2'>PCM mass {r.pcm_mass_kg:,.0f} kg; annuity factor {r.annuity_factor:.3f} "
                       f"({int(e['inp'].years)} yr at {e['inp'].discount_rate*100:.1f}%).</div>")

    @render_widget
    def breakeven_plot():
        e = _econ_ready()
        if not e:
            return go.Figure()
        return breakeven_figure(e["res"], e["inp"], e["material"].key)

    @render_widget
    def sens_plot():
        e = _econ_ready()
        if not e:
            return go.Figure()
        return sensitivity_figure(e["sens"])

    @render.data_frame
    def cash_table():
        e = _econ_ready()
        if not e:
            return render.DataGrid(pd.DataFrame())
        c = e["res"].cashflow.rename(columns={
            "year": "Year", "capex_net": "Net upfront ($)", "savings": "Savings ($)",
            "discount_factor": "Discount factor", "discounted": "Discounted ($)",
            "cumulative_discounted": "Cumulative ($)"})
        return render.DataGrid(c.round(3))

    @render.ui
    def provenance():
        key = input.material()
        lo, mid, hi = PCM_PRICE_USD_PER_KG[key]
        rows = [(f"PCM material price ({MATERIALS[key].name})", f"{lo:g}–{hi:g} (default {mid:g})", "$/kg", RANGE,
                 PCM_PRICE_NOTE[key] + " OSTI 1813229; cost data collected autumn 2020.", PCM_PRICE_SOURCE)]
        rows += [(m.label, f"{m.default:g}", m.unit, m.status, m.source, m.url) for m in INPUT_META.values()]
        body = "".join(
            f"<tr><td>{escape(a)}</td><td>{escape(b)}</td><td>{escape(c)}</td><td>{_badge(d)}</td>"
            f"<td class='small'>{escape(s)} {_link(u, 'source') if u else ''}</td></tr>"
            for a, b, c, d, s, u in rows)
        return ui.HTML("<table class='table table-sm'><thead><tr><th>Input</th><th>Default</th><th>Unit</th>"
                       f"<th>Status</th><th>Basis</th></tr></thead><tbody>{body}</tbody></table>")


app = App(app_ui, server)

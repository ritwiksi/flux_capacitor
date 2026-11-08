"""Flux Capacitor: Shiny research prototype for water vs PCM storage.

Run: shiny run --reload app.py
Tab "Annual cost (Boston 2024)": hourly LP cost model from pcm/annual.py (wholesale electricity only, no CO2e).
Tab "Thermal lab": the initial prototype; it does NOT estimate electrical savings, prices, or CO2e.
"""
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_widget

from pcm.annual import PCM_PRICE_DEFAULT, PRESETS, Params, hottest_week, load_year, monthly_costs, run
from pcm.materials import MATERIALS, get_material
from pcm.thermal import Config, simulate, summarize
from pcm.workload import normalize_month

BASE = Path(__file__).parent
LABELS = {key: f"{m.category} — {m.name}" for key, m in MATERIALS.items()}

# ---------- Annual cost tab: data, presets and input -> Params mapping ----------
YEAR = load_year()
AC_MATERIALS = {}
for _key, _m in MATERIALS.items():
    AC_MATERIALS.setdefault(_m.category, {})[_key] = LABELS[_key]
PRESET_NOTES = {
    "PCM showcase: chiller plant, salt hydrate, thin panels":
        "Showcase: a chiller-dependent plant (no economiser) with salt-hydrate PCM in thin 20 mm panels, "
        "500 m² per MW of IT. These are the conditions where PCM can pay in Boston.",
    "Boston as built: free cooling on, paraffin defaults":
        "Boston as built: water-cooled chiller with waterside free cooling and the paraffin defaults. "
        "The tower handles most hours, so PCM has little chiller energy to shift.",
}
SOURCED = {"supply_c", "return_c", "h_w_m2k", "panel_area_m2"}          # taken from thermal.Config
INPUTS = {"it_mw", "material", "graphite", "thickness_m", "panels_per_mw", "economiser"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def preset_inputs(name: str) -> dict:
    """UI values for a preset; anything the preset omits comes from Params() defaults."""
    p = Params(**PRESETS[name])
    price = p.pcm_usd_per_kg if p.pcm_usd_per_kg is not None else PCM_PRICE_DEFAULT[MATERIALS[p.material].category]
    return dict(material=p.material, graphite=p.graphite, thickness_mm=p.thickness_m * 1000, it_mw=p.it_mw,
                panels_per_mw=p.panels_per_mw, pcm_usd_per_kg=price, demand=p.demand_usd_per_kw_month,
                chiller=p.chiller_usd_per_kw, economiser=p.economiser, approach_k=p.approach_k)


def params_from_inputs(v: dict) -> Params:
    return Params(it_mw=float(v["it_mw"]), material=v["material"], graphite=bool(v["graphite"]),
                  thickness_m=float(v["thickness_mm"]) / 1000, panels_per_mw=float(v["panels_per_mw"]),
                  economiser=bool(v["economiser"]), approach_k=float(v["approach_k"]),
                  demand_usd_per_kw_month=float(v["demand"]), chiller_usd_per_kw=float(v["chiller"]),
                  pcm_usd_per_kg=float(v["pcm_usd_per_kg"]))


AC0 = preset_inputs(next(iter(PRESETS)))

annual_sidebar = ui.sidebar(
    ui.input_select("ac_preset", "Scenario preset", choices=list(PRESETS)),
    ui.input_select("ac_material", "PCM material", choices=AC_MATERIALS, selected=AC0["material"]),
    ui.input_checkbox("ac_graphite", "Hypothetical nano-graphite enhancement (assumed 2x k, not validated)",
                      value=AC0["graphite"]),
    ui.input_slider("ac_thickness", "PCM thickness (mm)", min=20, max=100, value=AC0["thickness_mm"], step=5),
    ui.input_numeric("ac_it_mw", "Datacenter size (MW of IT)", value=AC0["it_mw"], min=0.5, max=20, step=0.5),
    ui.input_numeric("ac_panels", "Panels per MW (1 m² each)", value=AC0["panels_per_mw"], min=10, max=5000, step=10),
    ui.input_action_button("ac_run", "Run annual model", class_="btn-primary w-100"),
    ui.accordion(
        ui.accordion_panel(
            "Advanced (assumed values)",
            ui.input_numeric("ac_price", "PCM price ($/kg)", value=AC0["pcm_usd_per_kg"], min=0.5, max=30, step=0.5),
            ui.input_numeric("ac_demand", "Demand charge ($/kW-month)", value=AC0["demand"], min=0, max=40),
            ui.input_numeric("ac_chiller", "Chiller capex ($/kW_th)", value=AC0["chiller"], min=0, max=1000, step=10),
            ui.input_checkbox("ac_economiser", "Free cooling (waterside economiser)", value=AC0["economiser"]),
            ui.input_numeric("ac_approach", "Cooling tower approach (K)", value=AC0["approach_k"], min=2, max=8, step=0.5),
        ),
        open=False,
    ),
    ui.p("Model runs only when you press Run (hourly LP over 8,784 h).", class_="small text-muted"),
    width=350,
)
annual_body = ui.div(
    ui.h2("Annual cost: Boston 2024, baseline vs PCM"),
    ui.output_ui("ac_preset_note"),
    ui.output_ui("ac_kpis"),
    ui.layout_columns(
        ui.card(ui.card_header("Monthly energy + demand charges ($, chiller capex excluded)"), output_widget("ac_monthly_plot")),
        ui.card(ui.card_header("Hottest week (highest mean wet-bulb), hourly"), output_widget("ac_week_plot")),
        col_widths=[6, 6],
    ),
    ui.card(ui.card_header("Assumptions and data provenance"), ui.output_ui("ac_assumptions")),
)

thermal_sidebar = ui.sidebar(
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
)
thermal_body = ui.div(
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
)

app_ui = ui.page_navbar(
    ui.nav_panel("Annual cost (Boston 2024)", ui.layout_sidebar(annual_sidebar, annual_body)),
    ui.nav_panel("Thermal lab", ui.layout_sidebar(thermal_sidebar, thermal_body)),
    title="Flux Capacitor",
    window_title="Flux Capacitor | PCM Lab",
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
    # ---------- Annual cost tab ----------
    last_category = [MATERIALS[AC0["material"]].category]

    @reactive.effect
    @reactive.event(input.ac_preset, ignore_init=True)
    def _apply_preset():
        v = preset_inputs(input.ac_preset())
        ui.update_select("ac_material", selected=v["material"])
        ui.update_checkbox("ac_graphite", value=v["graphite"])
        ui.update_slider("ac_thickness", value=v["thickness_mm"])
        ui.update_numeric("ac_it_mw", value=v["it_mw"])
        ui.update_numeric("ac_panels", value=v["panels_per_mw"])
        ui.update_numeric("ac_price", value=v["pcm_usd_per_kg"])
        ui.update_numeric("ac_demand", value=v["demand"])
        ui.update_numeric("ac_chiller", value=v["chiller"])
        ui.update_checkbox("ac_economiser", value=v["economiser"])
        ui.update_numeric("ac_approach", value=v["approach_k"])

    @reactive.effect
    @reactive.event(input.ac_material)
    def _price_follows_category():
        cat = MATERIALS[input.ac_material()].category
        if cat != last_category[0]:
            last_category[0] = cat
            ui.update_numeric("ac_price", value=PCM_PRICE_DEFAULT[cat])

    @reactive.calc
    @reactive.event(input.ac_run, ignore_none=False)   # also runs once at startup so the tab is never empty
    def ac_model():
        try:
            p = params_from_inputs(dict(
                material=input.ac_material(), graphite=input.ac_graphite(), thickness_mm=input.ac_thickness(),
                it_mw=input.ac_it_mw(), panels_per_mw=input.ac_panels(), pcm_usd_per_kg=input.ac_price(),
                demand=input.ac_demand(), chiller=input.ac_chiller(), economiser=input.ac_economiser(),
                approach_k=input.ac_approach()))
            return {"r": run(YEAR, p), "p": p}
        except Exception as exc:
            return {"error": f"Cannot run annual model: {exc}"}

    @render.ui
    def ac_preset_note():
        name = input.ac_preset()
        return ui.p(PRESET_NOTES.get(name, name) + " Edit any input and press Run to explore.", class_="text-muted")

    @render.ui
    def ac_kpis():
        d = ac_model()
        if "error" in d:
            return ui.div(d["error"], class_="alert alert-danger")
        k, p = d["r"]["kpis"], d["p"]
        b, c = k["base"], k["pcm"]
        hours = len(d["r"]["hourly"])
        if p.economiser:
            note = (f"Free cooling (economiser) is ON: the tower alone covers {k['free_hours_full']:,} of {hours:,} h "
                    f"in Boston 2024 (partly {k['free_hours_partial']:,} h), so there is little chiller energy for PCM "
                    "to shift and savings are small.")
        else:
            note = ("Free cooling (economiser) is OFF: this models a chiller-dependent plant, where every hour of "
                    "heat goes through the chiller.")
        cool_saving = b["cooling_kwh"] - c["cooling_kwh"]
        cool_pct = 100 * cool_saving / b["cooling_kwh"] if b["cooling_kwh"] > 0 else 0.0
        pb = k["payback_yr"]
        payback = "no payback" if pb is None else "immediate (avoided chiller capex ≥ PCM capex)" if pb == 0 else f"{pb:.1f} yr"
        be = k["breakeven_usd_per_kg"]
        price = k["pcm_usd_per_kg"]
        if be is None:
            be_text, be_verdict = "n/a", "No PCM mass in this run."
        else:
            be_text = f"${be:,.2f}/kg"
            be_verdict = (f"vs ${price:,.2f}/kg assumed: "
                          + (f"PCM pays back within its {p.pcm_life_yr}-yr life at the assumed price." if be >= price
                             else "PCM does NOT pay back at the assumed price."))
        return ui.div(
            ui.div(note, class_="alert alert-info py-2"),
            ui.p(f"{k['material']} | {k['area_m2']:,.0f} m² of panels | E_max {k['e_max_kwh']:,.0f} kWhₜₕ | "
                 f"charge ≤ {k['p_charge_kw']:,.1f} kWₜₕ, regen ≤ {k['p_regen_kw']:,.1f} kWₜₕ "
                 f"(conduction limits)", class_="small text-muted"),
            ui.layout_columns(
                ui.value_box("Break-even PCM price (headline)", be_text, ui.p(be_verdict),
                             theme="primary", showcase=ui.span("$/kg", class_="fs-3 fw-bold")),
                ui.value_box("Annual cost saving", f"${k['saving_usd']:,.0f}",
                             ui.p(f"{k['saving_pct']:.2f}% of ${b['total_usd']:,.0f} baseline "
                                  "(energy + demand + annualised chiller)")),
                ui.value_box("Cooling energy saving", f"{cool_saving / 1000:,.1f} MWhₑ",
                             ui.p(f"{cool_pct:.2f}% of {b['cooling_kwh'] / 1000:,.0f} MWhₑ baseline cooling")),
                col_widths=[4, 4, 4],
            ),
            ui.layout_columns(
                ui.value_box("PUE: baseline → with PCM", f"{k['pue_base']:.4f} → {k['pue_pcm']:.4f}",
                             ui.p(f"Free-cooling hours: {k['free_hours_full']:,} full / {k['free_hours_partial']:,} partial")),
                ui.value_box("Peak grid demand reduction", f"{b['peak_grid_kw'] - c['peak_grid_kw']:,.1f} kWₑ",
                             ui.p(f"Chiller capacity avoided: {k['chiller_avoided_kw']:,.1f} kWₜₕ")),
                ui.value_box("PCM capex and payback", f"${k['pcm_capex_usd']:,.0f}",
                             ui.p(f"{k['mass_kg']:,.0f} kg at ${price:,.2f}/kg | payback: {payback}")),
                col_widths=[4, 4, 4],
            ),
        )

    @render_widget
    def ac_monthly_plot():
        d = ac_model()
        if "error" in d:
            return go.Figure()
        m = monthly_costs(d["r"]["hourly"], d["p"])
        x = [MONTHS[i - 1] for i in m.index]
        fig = _fig("$ per month", [])
        fig.add_trace(go.Bar(x=x, y=m.base_usd, name="Baseline (no PCM)", marker_color="#64748b"))
        fig.add_trace(go.Bar(x=x, y=m.pcm_usd, name="With PCM", marker_color="#d97706"))
        fig.update_layout(barmode="group", xaxis_title="Month (local standard time)")
        return fig

    @render_widget
    def ac_week_plot():
        d = ac_model()
        if "error" in d:
            return go.Figure()
        w = hottest_week(d["r"]["hourly"])
        fig = _fig("Chiller thermal load (kWₜₕ)", [
            (w.index, w.chiller_base_kw, "Chiller, baseline", "#64748b"),
            (w.index, w.chiller_pcm_kw, "Chiller, with PCM", "#d97706"),
        ])
        fig.add_trace(go.Scatter(x=w.index, y=w.pcm_kwh, name="PCM stored (kWhₜₕ)", mode="lines", yaxis="y2",
                                 line={"color": "#2563eb", "width": 1.5, "dash": "dot"}))
        fig.update_layout(yaxis2={"title": "PCM stored (kWhₜₕ)", "overlaying": "y", "side": "right", "rangemode": "tozero"},
                          margin={"l": 34, "r": 50, "t": 18, "b": 36})
        return fig

    @render.ui
    def ac_assumptions():
        d = ac_model()
        if "error" in d:
            return ui.p("Run the model to see the parameters used.")
        r = d["r"]
        rows = []
        for name, value in r["params"].items():
            if name == "pcm_usd_per_kg":
                value = f"{r['kpis']['pcm_usd_per_kg']} ({r['kpis']['category']})"
            tag = ("input" if name in INPUTS else "sourced: thermal model config" if name in SOURCED else "assumed")
            rows.append(ui.tags.tr(ui.tags.td(ui.tags.code(name)), ui.tags.td(str(value)), ui.tags.td(tag)))
        mat = get_material(d["p"].material, d["p"].graphite)
        return ui.div(
            ui.tags.table(ui.tags.thead(ui.tags.tr(ui.tags.th("Parameter"), ui.tags.th("Value"), ui.tags.th("Tag"))),
                          ui.tags.tbody(*rows), class_="table table-sm"),
            ui.p(ui.tags.b("Material: "), f"{mat.name}. {mat.limitations} Source: {mat.source_url}", class_="small"),
            ui.tags.ul(
                ui.tags.li(f"IT load: NLR/ESIF measured it_power_kw (Golden, CO HPC facility), 2024; shape scaled so "
                           f"its peak = {d['p'].it_mw:g} MW. {r['kpis']['it_filled_hours']} hours filled from the same "
                           "hour ±1 week (gaps and glitches)."),
                ui.tags.li("Weather: NSRDB GOES Conus v4, Boston grid cell (42.36, -71.07), 2024 dry-bulb and RH; "
                           "wet-bulb from Stull (2011)."),
                ui.tags.li("Electricity price: ISO-NE day-ahead final LMP, load zone .Z.NEMASSBOST. "
                           "Wholesale only, no retail adder."),
                class_="small",
            ),
        )

    # ---------- Thermal lab tab (unchanged) ----------
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

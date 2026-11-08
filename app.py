"""Flux Capacitor: annual cost of PCM cooling storage for a Boston datacenter, 2024.

Run: shiny run --reload app.py
Every number shown comes from pcm/annual.py run() (wholesale electricity only, no CO2e).
"""
import re
from pathlib import Path
import plotly.graph_objects as go
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_widget

from pcm.annual import PCM_PRICE_DEFAULT, PRESETS, Params, load_year, peak_week, run
from pcm.materials import MATERIALS, get_material

YEAR = load_year()
SHOWCASE, AS_BUILT = list(PRESETS)            # PRESETS order: PCM showcase first, then Boston as built
SCENARIOS = {SHOWCASE: "Chiller plant (PCM showcase)", AS_BUILT: "Boston with free cooling"}
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def short_label(key: str) -> str:
    """'Salt hydrate: Na₂SO₄·10H₂O' / 'Paraffin: RT35HC', built from materials.py."""
    m = MATERIALS[key]
    kind = "Salt hydrate" if "salt hydrate" in m.category else "Paraffin"
    found = re.search(r"\((.+)\)", m.name)
    short = (re.sub(r"(?<=[A-Za-z])\d+", lambda g: g.group().translate(_SUB), found.group(1)) if found
             else m.name.split()[-1])
    return f"{kind}: {short}"


MATERIAL_CHOICES = {k: short_label(k) for k in sorted(MATERIALS, key=lambda k: "salt hydrate" not in MATERIALS[k].category)}
PARAM_LABELS = {
    "it_mw": "Datacenter size (MW of IT, peak)", "material": "PCM material",
    "graphite": "Nano-graphite enhancement (hypothetical)", "thickness_m": "PCM thickness (m)",
    "panels_per_mw": "PCM panels per MW of IT", "panel_area_m2": "Panel face area (m²)",
    "supply_c": "Loop supply temperature (°C)", "return_c": "Loop return temperature (°C)",
    "h_w_m2k": "Fluid-side heat transfer coefficient (W/m²K)", "cop_ref": "Chiller COP at the reference wet-bulb",
    "cop_ref_twb_c": "Wet-bulb for the reference chiller COP (°C)", "cop_slope": "Chiller COP lost per K of wet-bulb",
    "cop_min": "Minimum chiller COP", "economiser": "Waterside economiser (free cooling)",
    "approach_k": "Cooling tower approach (K)", "cop_free": "Free-cooling COP (tower fans and pumps)",
    "demand_usd_per_kw_month": "Demand charge ($/kW-month)", "chiller_usd_per_kw": "Chiller capex ($/kW_th)",
    "chiller_life_yr": "Chiller life (years)", "pcm_usd_per_kg": "PCM price ($/kg)",
    "pcm_life_yr": "PCM life (years)", "discount": "Discount rate",
}
SOURCED = {"supply_c", "return_c", "h_w_m2k", "panel_area_m2"}          # taken from thermal.Config
INPUTS = {"it_mw", "material", "graphite", "thickness_m", "panels_per_mw", "economiser"}


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


def week_figure(w) -> go.Figure:
    """Peak week chart. x as plain local-standard-time strings: shinywidgets sends tz-aware timestamps as
    '...Z' text and a naive DatetimeIndex as int nanoseconds."""
    x = list(w.index.tz_convert("Etc/GMT+5").strftime("%Y-%m-%d %H:%M"))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=w.chiller_base_kw, name="Chiller, baseline", line={"color": "#5b6770", "width": 2}))
    fig.add_trace(go.Scatter(x=x, y=w.chiller_pcm_kw, name="Chiller, with PCM", line={"color": "#00836c", "width": 3}))
    fig.add_trace(go.Scatter(x=x, y=w.pcm_kwh, name="PCM stored (kWhₜₕ)", yaxis="y2",
                             line={"color": "#b45309", "width": 2, "dash": "dot"}))
    fig.update_layout(template="plotly_white", height=360, font={"family": "Inter, system-ui, sans-serif", "size": 13, "color": "#333"}, margin={"l": 50, "r": 50, "t": 10, "b": 40},
                      legend={"orientation": "h", "y": -0.25, "x": 0},
                      xaxis={"type": "date", "title": "Local standard time (EST)"},
                      yaxis={"title": "Chiller thermal load (kWₜₕ)"},
                      yaxis2={"title": "PCM stored (kWhₜₕ)", "overlaying": "y", "side": "right", "rangemode": "tozero"})
    return fig


def week_summary(w) -> str:
    t = w.index[0].tz_convert("Etc/GMT+5")
    return (f"Peak week starting {t:%b} {t.day}: chiller peak {w.chiller_base_kw.max():,.0f} kWₜₕ without PCM "
            f"vs {w.chiller_pcm_kw.max():,.0f} kWₜₕ with PCM; PCM stores up to {w.pcm_kwh.max():,.0f} kWhₜₕ.")


AC0 = preset_inputs(SHOWCASE)

FONTS = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700"
         "&family=Newsreader:opsz,wght@6..72,400..700&display=swap")


def icon(path: str, size: int = 16) -> ui.HTML:
    """Authored stroke icon (one weight): chevron, check, dash."""
    return ui.HTML(f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
                   f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{path}"/></svg>')


CHEVRON, CHECK, DASH = icon("M6 3l5 5-5 5"), icon("M3 8.5l3.2 3.2L13 4.5"), icon("M3.5 8h9")
WAVE = ui.HTML('<svg class="hero-wave" viewBox="0 0 1440 90" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
               '<path d="M0 52 C 240 12 480 8 760 40 C 1010 68 1230 70 1440 30 L1440 90 L0 90 Z" fill="#f6f9fc"/></svg>')


def step_head(n: int, title: str, sub: str):
    return ui.div(ui.div(ui.span(str(n), class_="step-badge", aria_hidden="true"), ui.h2(title), class_="step-title"),
                  ui.p(sub, class_="step-sub"), class_="step-head")


def field(widget):
    return ui.div(widget, class_="field")


hero = ui.tags.header(
    ui.div(ui.span("Flux Capacitor", class_="wordmark"), ui.span("Boston 2024", class_="pill-tag"), class_="topbar"),
    ui.div(
        ui.div(
            ui.h1("Does phase-change storage pay off in your datacenter?"),
            ui.p("Pick a PCM, a panel thickness and a size. See the annual cost, payback and break-even price "
                 "for a Boston facility in 2024.", class_="hero-sub"),
            ui.input_radio_buttons("ac_scenario", "Scenario", choices=SCENARIOS, selected=SHOWCASE, inline=True),
            ui.div(
                ui.tags.button(ui.span("Run annual model"), CHEVRON, type="button", class_="btn-pill btn-orange",
                               onclick="document.getElementById('ac_run').click()"),
                ui.tags.a(ui.span("How we model it"), CHEVRON, href="#assumptions", class_="link-chevron",
                          onclick="var b=document.querySelector('#assumptions .accordion-button.collapsed');"
                                  "if(b){b.click();}"),
                class_="hero-actions",
            ),
            class_="hero-copy",
        ),
        ui.div(ui.output_ui("ac_result"), class_="result-card", aria_live="polite"),
        class_="hero-grid",
    ),
    WAVE,
    class_="hero",
)

configure = ui.tags.section(
    step_head(1, "Configure your design", "Choose the material, panel thickness and datacenter size, then run the model."),
    ui.div(
        field(ui.input_select("ac_material", "PCM material", choices=MATERIAL_CHOICES, selected=AC0["material"])),
        field(ui.input_slider("ac_thickness", "PCM thickness (mm)", min=20, max=100, value=AC0["thickness_mm"], step=5)),
        field(ui.input_numeric("ac_it_mw", "Datacenter size (MW of IT)", value=AC0["it_mw"], min=0.5, max=20, step=0.5)),
        ui.div(ui.input_action_button("ac_run", ui.TagList(ui.span("Run annual model"), CHEVRON),
                                      class_="btn-pill btn-orange"), class_="field field-run"),
        class_="config-grid",
    ),
    ui.accordion(
        ui.accordion_panel(
            "Advanced (assumed values)",
            ui.div(
                field(ui.input_numeric("ac_panels", f"Panels per MW ({Params().panel_area_m2:g} m² each)", value=AC0["panels_per_mw"], min=10, max=5000, step=10)),
                field(ui.input_numeric("ac_price", "PCM price ($/kg)", value=AC0["pcm_usd_per_kg"], min=0.5, max=30, step=0.5)),
                field(ui.input_numeric("ac_demand", "Demand charge ($/kW-month)", value=AC0["demand"], min=0, max=40)),
                field(ui.input_numeric("ac_chiller", "Chiller capex ($/kW_th)", value=AC0["chiller"], min=0, max=1000, step=10)),
                field(ui.input_numeric("ac_approach", "Cooling tower approach (K)", value=AC0["approach_k"], min=2, max=8, step=0.5)),
                field(ui.input_checkbox("ac_graphite", "Hypothetical nano-graphite (assumed, not validated)",
                                        value=AC0["graphite"])),
                class_="config-grid",
            ),
        ),
        open=False,
        class_="advanced",
    ),
    class_="config-card",
)

proof = ui.tags.section(
    step_head(2, "See it work", "The peak week of the year: chiller load with and without PCM, and the heat the PCM is storing."),
    ui.div(ui.output_ui("ac_week"), class_="panel"),
    class_="proof",
)

app_ui = ui.page_fluid(
    ui.tags.head(
        ui.tags.link(rel="preconnect", href="https://fonts.googleapis.com"),
        ui.tags.link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin=""),
        ui.tags.link(rel="stylesheet", href=FONTS),
        ui.tags.link(rel="stylesheet", href="style.css"),
        ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1"),
    ),
    ui.tags.a("Skip to the model", href="#main", class_="skip-link"),
    hero,
    ui.tags.main(
        configure,
        proof,
        ui.div(ui.accordion(ui.accordion_panel("Assumptions and sources", ui.output_ui("ac_assumptions")), open=False),
               id="assumptions", class_="assumptions"),
        id="main",
    ),
    ui.tags.footer(
        ui.p("Data: measured NLR/ESIF IT load (Golden, CO) scaled to your size, NSRDB weather for Boston and ISO-NE "
             "day-ahead wholesale prices, all 2024; costs exclude retail adders and CO₂e, and every plant and price "
             "constant not marked sourced is assumed."),
        class_="site-footer",
    ),
    title="Flux Capacitor: PCM cooling storage, Boston 2024",
    lang="en",
)


def server(input, output, session):
    last_category = [MATERIALS[AC0["material"]].category]
    request = reactive.value(dict(AC0, scenario=SHOWCASE))   # what the model runs on; set by Run or a scenario switch

    @reactive.effect
    @reactive.event(input.ac_scenario, ignore_init=True)
    def _apply_scenario():
        v = preset_inputs(input.ac_scenario())
        ui.update_select("ac_material", selected=v["material"])
        ui.update_checkbox("ac_graphite", value=v["graphite"])
        ui.update_slider("ac_thickness", value=v["thickness_mm"])
        ui.update_numeric("ac_it_mw", value=v["it_mw"])
        ui.update_numeric("ac_panels", value=v["panels_per_mw"])
        ui.update_numeric("ac_price", value=v["pcm_usd_per_kg"])
        ui.update_numeric("ac_demand", value=v["demand"])
        ui.update_numeric("ac_chiller", value=v["chiller"])
        ui.update_numeric("ac_approach", value=v["approach_k"])
        request.set(dict(v, scenario=input.ac_scenario()))   # preset values directly: widgets are still stale here

    @reactive.effect
    @reactive.event(input.ac_material)
    def _price_follows_category():
        cat = MATERIALS[input.ac_material()].category
        if cat != last_category[0]:
            last_category[0] = cat
            ui.update_numeric("ac_price", value=PCM_PRICE_DEFAULT[cat])

    @reactive.effect
    @reactive.event(input.ac_run)
    def _run_pressed():
        s = input.ac_scenario()
        request.set(dict(
            material=input.ac_material(), graphite=input.ac_graphite(), thickness_mm=input.ac_thickness(),
            it_mw=input.ac_it_mw(), panels_per_mw=input.ac_panels(), pcm_usd_per_kg=input.ac_price(),
            demand=input.ac_demand(), chiller=input.ac_chiller(), approach_k=input.ac_approach(),
            economiser=preset_inputs(s)["economiser"], scenario=s))

    @reactive.calc
    def ac_model():
        v = request()
        try:
            p = params_from_inputs(v)
            return {"r": run(YEAR, p), "p": p, "scenario": v["scenario"]}
        except Exception as exc:
            return {"error": f"Cannot run annual model: {exc}"}

    @render.ui
    def ac_result():
        d = ac_model()
        if "error" in d:
            return ui.div(ui.p(d["error"], class_="rc-error", role="alert"), class_="rc-body")
        k, p = d["r"]["kpis"], d["p"]
        if p.economiser:
            context = (f"Free cooling covers {k['free_hours_full']:,} of {len(d['r']['hourly']):,} h, "
                       "so little chiller energy is left to shift.")
        else:
            context = "No free cooling: all heat goes through the chiller."
        be, price = k["breakeven_usd_per_kg"], k["pcm_usd_per_kg"]
        if be is None:
            be_text, verdict, state = "n/a", "No PCM mass in this run, so there is no break-even price.", "na"
        else:
            be_text = f"${be:,.2f}/kg"
            pays = be >= price
            verdict = (f"At the assumed ${price:,.2f}/kg, PCM "
                       + ("pays back" if pays else "does not pay back")
                       + f" within its {p.pcm_life_yr}-year life.")
            state = "pays" if pays else "no"
        pb = k["payback_yr"]
        payback = "no payback" if pb is None else "immediate" if pb == 0 else f"{pb:.1f} years"

        def stat(label, value, note):
            return ui.div(ui.div(label, class_="tile-label"), ui.div(value, class_="tile-value"),
                          ui.div(note, class_="tile-note"), class_="rc-tile")

        return ui.div(
            ui.h2("Break-even PCM price", class_="rc-label"),
            ui.p(be_text, class_="rc-value"),
            ui.p(CHECK if state == "pays" else DASH, ui.span(verdict), class_=f"rc-verdict is-{state}"),
            ui.div(
                stat("Annual cost saving", f"${k['saving_usd']:,.0f}",
                     f"{k['saving_pct']:.2f}% of ${k['base']['total_usd']:,.0f}"),
                stat("Payback", payback, f"PCM capex ${k['pcm_capex_usd']:,.0f}"),
                stat("Chiller capacity avoided", f"{k['chiller_avoided_kw']:,.1f} kWₜₕ", "peak chiller load"),
                class_="rc-stats",
            ),
            ui.p(ui.tags.b(SCENARIOS[d["scenario"]] + ". "), context, class_="rc-context"),
            class_="rc-body",
        )

    @reactive.calc
    def week():
        d = ac_model()
        return None if "error" in d else peak_week(d["r"]["hourly"])

    @render.ui
    def ac_week():
        w = week()
        if w is None:
            return ui.p("No chart: the model did not run.")
        text = week_summary(w)
        return ui.div(ui.div(output_widget("ac_week_plot"), role="figure", aria_label=text), ui.p(text, class_="week-summary"))

    @render_widget
    def ac_week_plot():
        w = week()
        return go.Figure() if w is None else week_figure(w)

    @render.ui
    def ac_assumptions():
        d = ac_model()
        if "error" in d:
            return ui.p("Run the model to see the parameters used.")
        r = d["r"]
        rows = []
        for name, value in r["params"].items():
            if name == "pcm_usd_per_kg":
                value = f"{r['kpis']['pcm_usd_per_kg']:g} ({r['kpis']['category']})"
            elif name == "cop_ref":
                value = f"{value:g} at {r['params']['cop_ref_twb_c']:g} °C wet-bulb"
            elif name == "material":
                value = MATERIAL_CHOICES[value]
            tag = "input" if name in INPUTS else "sourced" if name in SOURCED else "assumed"
            rows.append(ui.tags.tr(ui.tags.td(PARAM_LABELS.get(name, name)), ui.tags.td(str(value)), ui.tags.td(tag)))
        mat = get_material(d["p"].material, d["p"].graphite)
        return ui.div(
            ui.tags.table(ui.tags.thead(ui.tags.tr(ui.tags.th("Parameter"), ui.tags.th("Value"), ui.tags.th("Tag"))),
                          ui.tags.tbody(*rows), class_="table table-sm assump-table"),
            ui.p("Tags: input = set in the Configure card; sourced = from the thermal model configuration; "
                 "assumed = placeholder, not measured.", class_="note"),
            ui.p(ui.tags.b("Material: "), f"{mat.name}. {mat.limitations} Source: ",
                 ui.tags.a(mat.source_url, href=mat.source_url, target="_blank"), class_="text-break"),
            ui.tags.ul(
                ui.tags.li(f"IT load: NLR/ESIF measured it_power_kw (Golden, CO HPC facility), 2024; shape scaled so "
                           f"its peak = {d['p'].it_mw:g} MW. {r['kpis']['it_filled_hours']} hours filled from the same "
                           "hour ±1 week (gaps and glitches)."),
                ui.tags.li("Weather: NSRDB GOES Conus v4, Boston grid cell (42.36, -71.07), 2024 dry-bulb and RH; "
                           "wet-bulb from Stull (2011)."),
                ui.tags.li("Electricity price: ISO-NE day-ahead final LMP, load zone .Z.NEMASSBOST. "
                           "Wholesale only, no retail adder."),
                class_="note",
            ),
        )


app = App(app_ui, server, static_assets=Path(__file__).parent / "www")

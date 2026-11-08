# UI scope: Flux Capacitor

One Shiny app, two tabs. Tab 1 is Ritwik's existing thermal lab, unchanged. Tab 2 is new and is what we demo.

## Layout
`ui.page_navbar` with:
1. **Annual cost (Boston 2024)**: new, default tab.
2. **Thermal lab**: the current app body and sidebar, moved into a `nav_panel` with `ui.layout_sidebar`. No behaviour change.

## Tab "Annual cost": inputs (sidebar)
| Control | Type | Default | Range | Notes |
|---|---|---|---|---|
| PCM material | select, grouped by category | RT35HC | 4 materials from `materials.py` | Paraffin vs salt hydrate is the headline choice |
| PCM thickness | slider, mm | 50 | 20–100, step 5 | Changes both capacity and charge speed |
| Datacenter size | numeric, MW of IT | 1.0 | 0.5–20 | Scales the ESIF load shape |
| Panels per MW | numeric | 100 | 10–5000 | 1 m² each. Shown openly because it dominates results |
| Run | button | | | Model runs only on click (LP takes seconds) |
| **Advanced** (collapsed accordion) | | | | All assumed values, editable |
| PCM price | numeric, $/kg | 5 paraffin / 2 salt hydrate | 0.5–30 | Default switches with category |
| Demand charge | numeric, $/kW-month | 15 | 0–40 | Placeholder |
| Chiller capex | numeric, $/kW_th | 250 | 0–1000 | Annualised at 7 %, 20 yr |
| Free cooling (economiser) | checkbox | on | | Tower cools the loop when wet-bulb allows |
| Tower approach | numeric, K | 4 | 2–8 | Assumed |

## Outputs
### KPI cards (one row, then a second row)
1. **Annual cost saving**: $ and % (baseline total − PCM total). Total = energy + demand charges + annualised chiller.
2. **Cooling energy saving**: MWh_e and %.
3. **PUE**: baseline → with PCM. Plus **free-cooling hours** (full / partial) from the weather.
4. **Peak demand reduction**: kW_e on the grid (max monthly peak) and kW_th of chiller capacity avoided.
5. **PCM capex and payback**: $ capex, simple payback in years, or "no payback" if savings ≤ 0.
6. **Break-even PCM price**: the $/kg at which PCM pays back over its life. This is the headline for contractors.

### Charts (Plotly, existing `_fig` helper style)
1. **Monthly cost**: grouped bars, baseline vs PCM.
2. **Hottest week, hourly**: chiller thermal load baseline vs PCM, plus PCM state of charge on a second axis.
   Week = the 168 h with the highest mean wet-bulb in 2024 (computed, not hard-coded).

### Assumptions panel
A card listing every parameter used in the run, tagged **sourced** or **assumed**, plus data provenance:
ESIF (Golden, CO, measured, scaled), NSRDB Boston weather, ISO-NE wholesale prices, ESIF fill count.

## States
- Before first run: a one-line prompt plus the data provenance.
- Running: Shiny's busy indicator; inputs stay editable.
- Error: red alert with the exception text (same pattern as tab 1).
- Savings ≤ 0: show it plainly. A "PCM does not pay here" result is valid.

## Performance budget
One run (LP over 8784 h) must finish in about 5 s on a laptop. If it doesn't, fall back to the rule-based dispatch
and say so in the UI.

## Out of scope for the demo
BESS, other cities or years, CSV upload on tab 2, CO2, accounts, deployment, mobile layout.

## Build order (each step demoable)
1. `pcm/annual.py` + tests (no UI).
2. Navbar wrapper; tab 1 still works.
3. Tab 2 inputs + KPI cards.
4. Two charts + assumptions card.
5. README section and SOURCES.md entries for the new data.

## Decided
- **Cooling plant**: water-cooled chiller + cooling tower with waterside economiser. Free cooling per hour comes from
  NSRDB wet-bulb (from temperature and RH). Toggle in the UI so the no-economiser case can be shown too.

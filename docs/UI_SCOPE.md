# UI scope: Flux Capacitor

One Shiny app, **one page**, three features: **Configure**, **Result**, **Proof**. Everything shown comes from
`pcm.annual` (see CLAUDE.md for the interface). The only cost shown is **annual cost**.

## 1. Configure (sidebar)
| Control | Type | Default | Notes |
|---|---|---|---|
| Scenario | radio, 2 options | Chiller plant (PCM showcase) | **Chiller plant (PCM showcase)** = `PRESETS` showcase, economiser off. **Boston with free cooling** = `PRESETS` as-built, economiser on. The scenario owns the economiser setting |
| PCM material | select, short labels | from scenario | 4 materials from `materials.py`, e.g. "Salt hydrate: Na₂SO₄·10H₂O" |
| PCM thickness | mm | from scenario | Changes both capacity and charge speed |
| Datacenter size | MW of IT | 1.0 | Scales the ESIF load shape |
| Run | button | | Model runs only on click (LP takes ~0.5 s) |
| **Advanced (assumed values)** | collapsed accordion | | All assumed, all editable |
| Panels per MW | numeric | from scenario | 1 m² each; dominates results |
| PCM price | $/kg | 5 paraffin / 2 salt hydrate | Default switches with category |
| Demand charge | $/kW-month | 15 | Placeholder |
| Chiller capex | $/kW_th | 250 | Annualised at 7 %, 20 yr |
| Tower approach | K | 4 | Used only when free cooling is on |
| Nano-graphite | checkbox | off | **Hypothetical**: no measured properties |

## 2. Result (one hero section)
- **Headline: break-even PCM price** ($/kg, the price at which PCM pays back over its life), with a verdict against
  the assumed price: *pays* if break-even ≥ assumed price, otherwise *does not pay*. A "does not pay" result is shown
  plainly; it is a valid answer.
- **Three stats**: annual saving ($ and %), payback (years, or "never"), chiller capacity avoided (kW_th).
- **One context line**: for free cooling, the computed free-cooling hours (full / partial) from the weather.

## 3. Proof
- **Chart "PCM in action: peak week" (168 h around the annual chiller peak)** (Plotly): chiller thermal load baseline vs with PCM, plus PCM stored energy
  (kWh_th) on a second axis. Week = the 168 h with the highest mean wet-bulb in 2024 (computed, not hard-coded).
  x-axis in **local standard time** (data are stored in UTC).
- **"Assumptions and sources"** (collapsed accordion): every parameter of the run with a human-readable label and a
  tag **input**, **sourced** or **assumed**, plus data provenance: ESIF (Golden, CO, measured, scaled), NSRDB Boston
  weather, ISO-NE wholesale prices, ESIF filled-hour count.

## States
- Before first run: a one-line prompt plus the data provenance.
- Running: Shiny's busy indicator; inputs stay editable.
- Error: red alert with the exception text.

## Removed for the demo
- **Thermal lab tab**: one message per page. Its model (`pcm/thermal.py`), tests and SOURCES.md entries remain; the
  UI is recoverable from git history.
- **Monthly cost chart**: baseline and PCM bars were visually identical.
- **PUE card and cooling-energy card**: differences of ~0.1 %, not decision-relevant.
- **Separate peak-grid card**: folded into chiller capacity avoided.
- **Economiser checkbox**: the scenario radio owns it.

## Design rules (from the UI audit)
- No nested cards.
- Prose max ~70ch per line.
- Correct heading order (no skipped levels).
- Functional text ≥ 11 px.
- No horizontal overflow at 390 px width.

## Out of scope for the demo
BESS, other cities or years, CSV upload, CO2, accounts, deployment.

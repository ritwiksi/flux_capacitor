# CLAUDE.md — Flux Capacitor

Guidance for Claude Code and teammates working in this repository. Read **README.md** and **SOURCES.md** before editing the simulation. `SOURCES.md` is the source of truth for which parameters are supported by evidence versus provisional assumptions.

## Project in one paragraph

**Flux Capacitor** is a Shiny for Python research prototype comparing **water sensible-heat storage** against **phase-change material (PCM) storage**, using identical external module geometry beside server racks in a **warm-water liquid-cooling loop**. The input is a real, timestamped **IT electrical-power load profile (kW)**, ideally the publicly available Colorado NLR/ESIF dataset. The model estimates hourly heat transfer, storage temperatures and PCM melting fraction, then eventually cooling-plant electricity, full installed cost, and manufacturing + operational emissions. **It must be scientifically honest: negative or negligible PCM benefits are acceptable results.**

## Agreed scope — do not quietly change it

- **Exactly two comparison cases:** (1) water storage and (2) selected PCM storage. No third no-storage reference case unless explicitly requested.
- **No BESS**, no COMSOL; use Python and a defensible simplified model.
- **Physical location:** rack-adjacent storage modules integrated into the liquid-cooling loop; hot server return water can charge the modules, and sufficiently cool water regenerates them. Model/bypass the associated plumbing realistically when later expanding the model.
- **Temperatures:** 27 °C supply and 37 °C return are **scenario assumptions**, not measured ESIF supply/return conditions.
- **Starting geometry:** 100 panels × 1 m² heat-transfer face × 0.05 m (50 mm) thickness = **5 m³ gross storage volume**. The interface may vary thickness and panel count; optional auto-sizing is a later feature, not an excuse to silently select a favorable panel count.
- **PCM menu:** label materials as **Organic / paraffin-based** or **Inorganic / salt hydrate-based** and name the actual compound/product.
- **Graphite:** a binary nano-graphite enhanced/unenhanced switch. Current coefficients are illustrative only.
- **Workload:** use actual IT power in kW, not guessed megawatts derived from floor area. Default evaluation is **one complete calendar month**; choose the first complete month reproducibly, not a cherry-picked favorable month.
- **Comparison fairness:** identical geometric envelope and reasonable heat-exchanger/loop assumptions. Give water and PCM the same operating opportunities; if optimizing control later, optimize **both** systems fairly.
- **Desired eventual outputs:** thermal storage and melt fraction; cooling-plant electricity and peak demand; installed CAPEX, operating OPEX, five-year scenario economics; operational and embodied CO₂e. Do not present these future outputs as currently implemented.

## Current state of code (first thermal MVP)

| Path | Purpose |
| --- | --- |
| `app.py` | Shiny dashboard, input controls, Plotly charts and hourly output table |
| `pcm/workload.py` | Validate and aggregate timestamps / `it_power_kw` into the earliest complete UTC calendar month |
| `pcm/materials.py` | Four candidate materials, organic/inorganic classifications, provisional graphite toggle |
| `pcm/thermal.py` | 1D finite-volume PCM enthalpy/conduction, mixed sensible-water comparator, fixed daily dispatch heuristic |
| `scripts/prepare_esif.py` | Convert a locally downloaded NLR/ESIF CSV/ZIP into a month of hourly records |
| `data/sample_synthetic_2025_07.csv` | **Synthetic UI test data only**, not measured data |
| `tests/test_thermal.py` | Baseline tests for monthly loads, comparisons and hypothetical graphite |
| `SOURCES.md` | Exact sources, model assumptions, caveats and missing subsystems |

The existing **dispatch is not an optimizer**: each UTC day charges in its eight highest IT-load hours and regenerates in its eight lowest. Both storage options receive the same schedule. The heat-rejection-load traces are **thermal proxies**, not electrical consumption or proof of cost savings. The current thermal model omits PCM liquid natural convection, salt-hydrate supercooling/segregation, detailed exchanger losses and regeneration plant electricity.

## Setup and routine checks

From the repository root:

```bash
python -m venv .venv
# Activate .venv for your OS.
pip install -r requirements.txt
python -m pytest -q
shiny run --reload app.py
```

The UI accepts a CSV of UTC timestamps and IT electric power:

```csv
timestamp,it_power_kw
2025-07-01T00:00:00Z,950
2025-07-01T01:00:00Z,945
```

Download official **ESIF DC Power Metrics Timeseries Data (Zipped CSV)** via https://data.nlr.gov/submissions/300 and prepare it with:

```bash
python -m scripts.prepare_esif /path/to/esif.csv.zip data/esif_month.csv
```

Then upload `data/esif_month.csv` in Shiny. **Do not claim ESIF data has been imported or validated until that has been done.** The importer rejects incomplete months rather than fabricating missing data. Do not add the raw multi-GB dataset to Git.

## Modeling rules for contributors

1. **Never invent measurements or source citations.** Every material, cooling-plant, pricing and emissions parameter should have units, provenance (measured / manufacturer / literature / assumed), and any material uncertainty documented in `SOURCES.md`.
2. **Keep units explicit** in variables, outputs and equations: W vs kW vs kWh; thermal kW vs electrical kW; °C vs K; J/kg vs kJ/kg. Do not equate stored thermal kWh with saved electric kWh.
3. **Conserve energy:** charging merely defers heat rejection, and regeneration eventually adds that heat back to the plant. Include pumping, auxiliary loads, thermal loss, equipment limitations and weather/COP where justified.
4. **Respect phase-transition feasibility:** a PCM should not earn credit if the fluid temperatures cannot sufficiently melt **and resolidify** it; show incomplete cycles. Do not treat a manufacturer's total storage capacity across a temperature band as pure latent heat.
5. **Water is a serious baseline.** Its capacity and heat transfer must be modeled consistently, not weakened to make PCM win.
6. **Graphite is unvalidated in this code.** `get_material(..., graphite=True)` currently applies hypothetical 2× thermal conductivity and 0.98× latent heat. Do not describe those factors as experimentally verified for the selected products; replace with material-specific evidence when available.
7. **Do not optimize or select an input period based on favorable PCM savings.** Keep workload choice and tariff assumptions independent of results. Report failures, negative savings and uncertain estimates.
8. **Separate modules and tests** from reactive Shiny UI logic. Make simulations deterministic with no external downloads at runtime.
9. **Before claiming success**, run `python -m pytest -q`, smoke-test the Shiny interface, check physical bounds (melt fraction 0–1, positive mass/volume, finite temperatures) and describe which checks you actually performed.
10. **Work in feature branches / pull requests.** Avoid direct pushes to `main` and don't silently replace research parameters or make broad unrelated refactors.

## Next engineering milestones (in order)

1. **Validate the real input:** download ESIF, inspect its actual headers and coverage, verify timestamps, missing values, IT-power units, and choose a reproducible complete month. Distinguish measured IT electric demand from cooling electric power and heat rejected.
2. **Validate thermal behavior:** energy-balance checks, month-long repeated cycling, heat-transfer sensitivity, fluid limits, water comparability and credible literature reference cases. Improve model fidelity only where it changes decisions.
3. **Model the cooling plant:** source an equipment-performance curve or measured data; calculate temperature-dependent cooling electricity and pumping/regeneration energy, under the same site/weather assumptions.
4. **Implement proper dispatch:** replace load-ranking heuristic with constraint-aware dispatch that considers plant capacity, storage state, weather and tariffs, evaluating water and PCM fairly.
5. **Build documented economics/emissions:** installed module / exchanger / labor CAPEX; energy + actual demand-charge tariff; maintenance / replacement; embodied PCM/graphite/water/module emissions; operational electricity CO₂e; optional *hypothetical* U.S. carbon-price sensitivity; five-year scenarios clearly distinguished from measured results.
6. **Polish UX:** expose confidence levels, data provenance, material compatibility warnings, downloadable plots and CSV outputs, and an optional automatic sizing mode.

## Definition of a credible result

A graph may show **heat shifted** without implying electric savings. A monetary or emissions result is only credible once all required cooling-plant, dispatch, tariff, manufacturing and operational data are implemented and documented. If input evidence is inadequate, show “not estimated” rather than a precise-looking number. Explicitly label synthetic profiles, provisional inputs and illustrative extrapolations.

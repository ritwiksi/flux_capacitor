# CLAUDE.md: Flux Capacitor

Read this before touching the repo. It is the shared brief for every agent working here.

## What we are building
A Shiny for Python tool that lets a datacenter contractor choose a PCM technology, PCM thickness and datacenter
size, and see the effect on **annual cost** (saving, payback, break-even PCM price, chiller capacity avoided) for a
datacenter in **Boston, 2024**, compared with the same facility without PCM. Single page: Configure, Result, Proof. Audience: hackathon judges. **Deadline: a few hours.** Ship the
smallest thing that works and is honest.

Detailed UI spec: [docs/UI_SCOPE.md](docs/UI_SCOPE.md). Sources and provenance: [SOURCES.md](SOURCES.md).

## Decisions already made (do not reopen)
| Topic | Decision |
|---|---|
| Stack | Shiny for Python only. No React, no separate API. |
| Location / year | Boston, calendar year 2024 in local standard time (2024-01-01 05:00 UTC onward, 8784 h), timestamps stored in **UTC** |
| IT load | Measured NLR/ESIF `it_power_kw` (Golden, CO HPC facility), 2024, shape scaled so its peak = chosen MW |
| Weather | NSRDB GOES Conus v4, Boston grid cell (42.36, -71.07): dry-bulb, RH |
| Electricity price | ISO-NE day-ahead final LMP, load zone 4008 `.Z.NEMASSBOST`. **Wholesale only, no retail adder.** |
| Cooling | Conventional water cooling: water-cooled chiller + cooling tower **with waterside economiser (free cooling)**, driven by NSRDB wet-bulb |
| Scenarios | Baseline (no PCM) vs PCM. **No BESS, no other cities, no CO2** in v1. |
| Dispatch | Linear program over the full year (`scipy.optimize.linprog`, HiGHS). No new dependencies. ~0.5 s per run. |
| Framing | **PCM-first.** Scenario radio: "Chiller plant (PCM showcase)" is the default; "Boston with free cooling" is one click away. The scenario owns the economiser setting. |

## Repo map
```
app.py                 Shiny app, single page, annual cost only (Thermal lab tab removed for the demo; in git history)
pcm/materials.py       4 PCMs (2 paraffin, 2 salt hydrate) with sources + limitations. Reuse, don't fork.
pcm/thermal.py         Ritwik's 1D enthalpy PCM vs water model (monthly). No UI now; tests remain. Do not change its physics.
pcm/workload.py        Month importer (ESIF timestamp parse bug: see Known issues)
pcm/annual.py          NEW: annual cost model (PCM limits, COP, LP, KPIs)
scripts/prepare_boston_2024.py   NEW: builds data/boston_2024_hourly.csv from raw downloads
data/boston_2024_hourly.csv      NEW: utc, temp_c, rh_pct, price_usd_per_kwh, it_kw_esif, it_filled (8784 rows)
tests/                 pytest; every new module gets tests
```

## The annual model (pcm/annual.py)
- Hourly, 8784 h, Δt = 1 h, units **kW and kWh** (match the existing code), thermal vs electric always labelled.
- `Q_IT = P_IT` (all IT power becomes heat). PCM net heat in `s[t]` (kW_th, + = melting/absorbing).
- Heat to the cooling plant `q_c = Q_IT - s >= 0`; cooling electricity `k[t]·q_c` (k = free-cooling mix, below).
- PCM energy `E[t+1] = E[t] + s[t]`, `0 <= E <= E_max`, cyclic `E[end] = E[0]`.
- Power limits from conduction (geometry from `thermal.Config`, properties from `materials.py`):
  `UA = A / (1/h + (thickness/2)/k)`; charge `s <= UA·(T_return - T_melt)`; regen `-s <= UA·(T_melt - T_supply)`.
- `E_max = m·(L + cp·(T_return - T_supply))`, `m = ρ·A·thickness`, `A = panels_per_MW · MW · 1 m²`.
- Objective: `Σ price·P_grid + Σ_months c_d·D_m + c_cap·C`, with `D_m >= P_grid[t]` in month m, `C >= (1-f)·q_c[t]`,
  `P_grid = P_IT + k·q_c`. Baseline = same with `s = 0`.
- Wet-bulb from NSRDB T and RH: Stull (2011) formula.
- Free cooling fraction per hour (known from weather, so the LP stays linear):
  `f = clip((T_return - approach - T_wb) / (T_return - T_supply), 0, 1)`; f = 1 means the tower alone makes supply water.
  `k = f/COP_free + (1-f)/COP_chiller(T_wb)` kW_e per kW_th.

### Default parameters: all **assumed** unless stated; every one must be editable or listed in the UI
| Parameter | Default |
|---|---|
| Loop supply / return | 27 / 37 °C (Ritwik's config) |
| Panels per MW of IT | 100 (1 m² face each; Ritwik's default for ~1 MW) |
| Fluid-side h | 150 W/m²K (Ritwik's config) |
| Chiller COP | 6.0 at T_wb = 20 °C, −0.2 per K, floor 3.0 (EIA 2023: COP 6.3–7.2; slope inferred from CA Title 24 §110.2 curve) |
| Economiser | on; tower approach 4 K; free-cooling COP 25 (fans + pumps) |
| Demand charge c_d | **$27.5/kW-month, sourced**: Eversource G-3 2024, $14.64 distribution + $12.87 transmission |
| Chiller capex | $250/kW_th, 20 yr, 7 % → annualised with CRF |
| PCM cost | paraffin $5/kg, salt hydrate $2/kg (assumed formulated price; raw chemical is $0.03–0.19/kg salt hydrate, $1–20/kg paraffin, ORNL 2021) |
| PCM life / discount | 15 yr / 7 % |

## Rules
1. **Honesty over polish.** Every number shown is either sourced (cite it) or labelled *assumed*. Never present
   synthetic data as measured.
2. **Small diffs.** Reuse `materials.py` and `Config`; no new dependencies; no abstractions nobody asked for.
3. **Tests for new logic**, at minimum: energy balance closes; PCM with zero mass equals baseline;
   PCM total cost <= baseline (s = 0 is feasible); `E` stays within bounds.
4. Run `python -m pytest -q` before every commit. Work on branch `feat/cost-model`; open a PR to `main`.
5. **This repo is public.** Never commit credentials, API keys, emails, raw ESIF/NSRDB/ISO-NE downloads, or
   anything from outside the repo except the derived `data/boston_2024_hourly.csv`.

## Commands
```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # Windows path
.venv/Scripts/python -m pytest -q
.venv/Scripts/shiny run --reload app.py
```

## Raw data (outside the repo, on Siddharth's machine)
- `Desktop/Hack/data/raw/weather/boston_2024.csv` (NSRDB; needs `NLR_API_KEY`, `NLR_EMAIL` to refetch)
- `Desktop/Hack/data/raw/esif/esif_it_hourly_utc.csv` (from the ESIF PUE zip, data.nlr.gov/submissions/300)
- `Desktop/Hack/data/raw/isone/da_4008_2024MMDD.json` (needs `ISONE_USER`, `ISONE_PASS`; fetch script in Hack/scripts)

## Known issues / facts
- ESIF `ts` looks like `Mon Nov 09 2015 20:00:01 GMT-0700 (Mountain Standard Time)`; `pd.to_datetime` returns NaT,
  so `normalize_month` rejects real ESIF files. Fix: strip the `(...)` suffix and parse with
  `format="%a %b %d %Y %H:%M:%S GMT%z"`.
- ESIF 2024: 96.7 % hourly coverage, 14 gaps (longest 90 h) plus glitch readings < 10 % of median; 298 hours filled
  from the same hour ±1 week and flagged in `it_filled`. Mean 2.7 MW, peak 3.9 MW.
- With default geometry, paraffin's low conductivity (0.2 W/mK) limits PCM power to a few kW per 100 m², so savings
  can be tiny. That is a real result, not a bug; the UI must expose panels per MW and thickness.

## Findings that shape the demo (from a 192-run scan, 2024 data)
- **Boston as built** (free cooling on, RT35HC, 50 mm, 100 panels/MW): saving $40/yr on ~$548k (0.01 %). The tower
  makes 27 °C water alone for 8,531 of 8,784 h, so there is almost no chiller energy to shift.
- **PCM showcase** (chiller plant without economiser, Na2SO4·10H2O, 20 mm, 500 panels/MW, $27.5/kW-month, no graphite):
  saving $6,209/yr (1.0 % of ~$612k), chiller -57 kW, payback 3.1 yr, break-even $4.01/kg vs $2/kg assumed price.
- What makes PCM work: salt hydrates (higher k and latent heat), **thin** panels (faster charging), enough area,
  a chiller-dependent plant, a real demand charge. Graphite helps but is hypothetical; label it so.
- **Never tune or hide numbers to favour PCM.** Favouring PCM means presenting it first and showing the real
  conditions where it pays. Judges will ask.

## pcm/annual.py interface (the UI must use only this)
```python
from pcm.annual import Params, PRESETS, load_year, run, peak_week, hottest_week
df = load_year()                       # once at app start
r = run(df, Params(**kwargs))          # ~0.5 s
r["kpis"]   # dict: material, category, pcm_usd_per_kg, area_m2, mass_kg, e_max_kwh, p_charge_kw, p_regen_kw,
            #   pcm_capex_usd, base{...}, pcm{...} (each: energy_usd, demand_usd, chiller_kw, chiller_usd,
            #   cooling_kwh, peak_grid_kw, total_usd), saving_usd, saving_pct, opex_saving_usd,
            #   chiller_avoided_kw, chiller_avoided_usd, payback_yr (None = never), breakeven_usd_per_kg,
            #   pue_base, pue_pcm, free_hours_full, free_hours_partial, it_filled_hours
r["hourly"] # DataFrame (UTC index): q_it_kw, twb_c, free_frac, kwe_per_kwth, price, pcm_kw, pcm_kwh,
            #   chiller_base_kw, chiller_pcm_kw, grid_base_kw, grid_pcm_kw
r["params"] # dict of the Params used (for the assumptions card)
peak_week(r["hourly"])  # 168 h around the annual chiller peak (proof chart)
hottest_week(r["hourly"])   # hottest 168 h by wet-bulb (not used in the UI)
```
Params fields: it_mw, material, graphite, thickness_m, panels_per_mw, economiser, approach_k, demand_usd_per_kw_month,
chiller_usd_per_kw, pcm_usd_per_kg (None = category default), plus the plant constants in the table above.

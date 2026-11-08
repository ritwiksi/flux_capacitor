# CLAUDE.md: Flux Capacitor

Read this before touching the repo. It is the shared brief for every agent working here.

## What we are building
A Shiny for Python tool that lets a datacenter contractor choose a PCM technology, PCM thickness and datacenter
size, and see the effect on **annual cost, cooling energy and peak demand** for a datacenter in **Boston, 2024**,
compared with the same facility without PCM. Audience: hackathon judges. **Deadline: a few hours.** Ship the
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
| Dispatch | Linear program over the full year (`scipy.optimize.linprog`, HiGHS). No new dependencies. |

## Repo map
```
app.py                 Shiny app. Tab 1 "Thermal lab" = Ritwik's original; tab 2 "Annual cost" = new
pcm/materials.py       4 PCMs (2 paraffin, 2 salt hydrate) with sources + limitations. Reuse, don't fork.
pcm/thermal.py         Ritwik's 1D enthalpy PCM vs water model (monthly). Do not change its physics.
pcm/workload.py        Month importer (ESIF timestamp parse bug: see Known issues)
pcm/annual.py          NEW: annual cost model (PCM limits, COP, LP, KPIs)
scripts/prepare_boston_2024.py   NEW: builds data/boston_2024_hourly.csv from raw downloads
data/boston_2024_hourly.csv      NEW: utc, temp_c, rh_pct, price_usd_per_kwh, it_kw_esif, it_filled (8784 rows)
tests/                 pytest; every new module gets tests
```

## The annual model (pcm/annual.py)
- Hourly, 8784 h, Δt = 1 h, units **kW and kWh** (match the existing code), thermal vs electric always labelled.
- `Q_IT = P_IT` (all IT power becomes heat). PCM net heat in `s[t]` (kW_th, + = melting/absorbing).
- Chiller thermal load `q_c = Q_IT - s >= 0`; chiller electricity `q_c / COP(T_wb)`.
- PCM energy `E[t+1] = E[t] + s[t]`, `0 <= E <= E_max`, cyclic `E[end] = E[0]`.
- Power limits from conduction (geometry from `thermal.Config`, properties from `materials.py`):
  `UA = A / (1/h + (thickness/2)/k)`; charge `s <= UA·(T_return - T_melt)`; regen `-s <= UA·(T_melt - T_supply)`.
- `E_max = m·(L + cp·(T_return - T_supply))`, `m = ρ·A·thickness`, `A = panels_per_MW · MW · 1 m²`.
- Objective: `Σ price·P_grid + Σ_months c_d·D_m + c_cap·C`, with `D_m >= P_grid[t]` in month m, `C >= q_c[t]`,
  `P_grid = P_IT + q_c/COP`. Baseline = same with `s = 0`.
- Wet-bulb from NSRDB T and RH: Stull (2011) formula.
- Free cooling fraction per hour (known from weather, so the LP stays linear):
  `f = clip((T_return - approach - T_wb) / (T_return - T_supply), 0, 1)`; f = 1 means the tower alone makes supply water.
  Cooling electricity per kW_th = `f/COP_free + (1-f)/COP_chiller(T_wb)`. Chiller capacity constraint uses `(1-f)·q_c`.

### Default parameters: all **assumed** unless stated; every one must be editable or listed in the UI
| Parameter | Default |
|---|---|
| Loop supply / return | 27 / 37 °C (Ritwik's config) |
| Panels per MW of IT | 100 (1 m² face each; Ritwik's default for ~1 MW) |
| Fluid-side h | 150 W/m²K (Ritwik's config) |
| Chiller COP | 6.0 at T_wb = 20 °C, −0.15 per K, floor 3.0 |
| Economiser | on; tower approach 4 K; free-cooling COP 25 (fans + pumps) |
| Demand charge c_d | $15/kW-month (placeholder) |
| Chiller capex | $250/kW_th, 20 yr, 7 % → annualised with CRF |
| PCM cost | paraffin $5/kg, salt hydrate $2/kg (placeholders) |
| PCM life / discount | 15 yr / 7 % |

## Rules
1. **Honesty over polish.** Every number shown is either sourced (cite it) or labelled *assumed*. Never present
   synthetic data as measured. Keep Ritwik's warning banners for the thermal tab.
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
- ESIF 2024: 96.7 % hourly coverage, 14 gaps (longest 90 h), 5 glitch readings < 300 kW; mean 2.7 MW, peak 3.9 MW.
  Gaps filled from the same hour ±1 week and flagged.
- With default geometry, paraffin's low conductivity (0.2 W/mK) limits PCM power to a few kW per 100 m², so savings
  can be tiny. That is a real result, not a bug; the UI must expose panels per MW and thickness.

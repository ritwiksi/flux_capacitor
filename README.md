# Flux Capacitor

**Research prototype: thermal storage comparison for liquid-cooled data centers.**

A Shiny for Python app compares two identically sized, rack-adjacent thermal storage module arrays: **water (sensible heat)** and a selected **organic/inorganic PCM**. It estimates time-varying heat absorption, regeneration, and PCM melt fraction from a full calendar-month IT-power CSV. An **Economics tab** adds an *exploratory* five-year PCM-vs-water comparison (NPV, break-even PCM price, break-even containment premium). It does **not** yet report weather-dependent chiller electricity, tariff optimization, or CO2e, and several economic inputs are unsourced placeholders (see below).

## Run

```bash
python -m venv .venv
# activate your virtual environment
pip install -r requirements.txt
shiny run --reload app.py
```

The app defaults to a clearly labeled **synthetic UI demonstration profile** until you upload a real CSV. To use the published NLR ESIF data:

1. Download the **ESIF DC Power Metrics Timeseries Data (Zipped CSV)** from https://data.nlr.gov/submissions/300 .
2. Convert the downloaded zip to a complete hourly month:

   ```bash
   python -m scripts.prepare_esif /path/to/esif.influx.buildingData.PUE.combined.csv.zip data/esif_month.csv
   ```

3. Upload `data/esif_month.csv` through the UI.

The converter selects the **earliest fully observed UTC calendar month**, avoiding cherry-picking. If no complete month is available it raises an error rather than inventing missing load.

Alternatively upload any CSV with columns:

```csv
timestamp,it_power_kw
2025-07-01T00:00:00Z,950
2025-07-01T01:00:00Z,945
```

**A full calendar month of observations is required**, preferably hourly (higher-frequency timestamps are aggregated into hourly means). `ts` is also accepted instead of `timestamp`. Values are IT electrical power in kW, not percentages or cooling electrical kW.

## Defaults

- Supply / return: **27°C / 37°C** (assumed), 100 panels, each 1 m² face and 50 mm thickness → **5 m³ gross storage volume**.
- 1D PCM conduction + enthalpy/melting fraction; a mixed sensible-water comparator.
- **Default:** independently optimize each system's lowest *feasible hourly thermal peak* under the same 1D physics and 27/37°C boundary conditions. Targets are found by bisection; PCM and water may receive different schedules. This is a full-month perfect-foresight benchmark, **not** a weather-based cooling controller.
- **Legacy mode:** identical daily top-8/bottom-8 load-ranked hours, with the optional regeneration cap preserved.
- Organic paraffin and inorganic salt-hydrate materials; graphite toggle is **hypothetical** pending measurements.

## Economics tab (exploratory)

Compares the PCM array against the **water** array from the thermal run (same panels, volume and dispatch). Positive NPV means PCM beats water. Value comes from (1) avoided chiller capacity, (2) demand-charge reduction, (3) energy-cost change. With a flat tariff and constant chiller efficiency (3) is zero by construction, because storage shifts heat rather than removing it.

Every input carries a provenance badge: **sourced**, **range-sourced**, **assumption**, or **placeholder (no source found)**. The headline outputs are break-even values rather than a single savings figure:

- **Break-even PCM price** and **break-even containment premium ($/m²)**: how much extra panel cost the modeled benefit can absorb. Panel hardware, heat exchangers and installation are assumed identical for PCM and water; corrosive salt hydrates will cost more, so this *favours PCM*.
- **Peak vs no storage** is shown next to peak vs water. The new default controller picks a target cooling peak below the no-storage peak and charges only in hours above it; regeneration occurs only within the headroom beneath it. Each store is optimized independently, with the same geometry, load, and boundary temperatures. The original heuristic and cap can be replayed by switching dispatch modes. With the old uncapped mode, a new regeneration-driven cooling peak can still appear; the app warns about it.

**Critical limitation:** The monthly benchmark starts each store at 27°C, but does not enforce the same temperature/enthalpy at month end. The UI discloses remaining stored heat. It cannot establish repeatable yearly peak relief or justify reducing installed chiller size, especially when residual heat persists. Energy-cost comparisons use a simplified terminal heat adjustment, but that adjustment is not reflected in the peak/capacity estimate. Economic results remain sensitivity illustrations, *not bankable savings*. The default workload is synthetic. Do not quote its economics. Sources and limits: [SOURCES.md](SOURCES.md).

## Deploying to a shareable link

The app needs a Python host (it is a Shiny for Python app with `shinywidgets`), not static hosting. On [shinyapps.io](https://www.shinyapps.io):

```bash
pip install rsconnect-python
# shinyapps.io -> Account -> Tokens -> Show -> copy name, token, secret
rsconnect add --account NAME --name NAME --token TOKEN --secret SECRET
rsconnect deploy shiny . --name NAME --title flux-capacitor --entrypoint app:app
```

This deploy path has **not been tested** from this repository (it needs your account credentials). Check your plan's active-hour and idle-sleep limits before a demo, and open the link a few minutes beforehand so it is awake. `requirements.txt` also lists `pytest` and `scipy`, which the app does not need and which only lengthen the build.

## Validation and observed runtime

```bash
python -m pytest -q
python -m scripts.benchmark_peak
```

The benchmark measures one full synthetic month with 100 panels on your machine; it prints its observed runtime rather than guessing or advertising a fake progress percentage. The Shiny app also shows actual completed runtime. A client-side animated SVG sketch draws server racks and cooling piping while computing; it is a loading indicator, **not** a rendering of the simulated physics.

Detailed distinctions between source-derived inputs and research assumptions are in [SOURCES.md](SOURCES.md).

## Next milestone

Validate month-to-month cyclic recovery (the end-state must return to its starting energy before crediting a repeatable peak reduction), replace month-ahead foresight with an implementable predictive controller, then add a documented temperature-dependent heat-rejection plant and fully sourced tariff. Replace placeholder chiller, containment, pump and installation costs with vendor quotes. Only then treat the five-year economics as more than exploratory. Emissions are still not modelled.


## Extension: cyclic audit, plant and lifecycle (2026-11-08)

The **Plant & lifecycle** tab introduces a scenario-only energy/emissions and financial model. It is distinct from the historical **Economics (legacy thermal proxy)** tab. Both the default 2025 summer load and default ambient temperatures are **synthetic**.

- A repeat-month auditor replays the threshold controller up to four identical months, carrying each PCM cell's enthalpy and the water storage temperature across month boundaries. A cycle is verified only if its full thermal state converges, hourly plant peak stays within the requested ceiling, and the integrated storage energy balance closes. Failure is reported. A repeated synthetic month does not validate seasonal reliability.
- A liquid heat-capture slider governs how much measured IT electrical consumption is modeled as heat entering the 27/37 C liquid loop. All IT electricity is still included in the *facility* electricity-peak tariff calculation.
- The plant is a **hypothetical** dry cooler, compressor chiller and pump/fan model. Free cooling varies with ambient temperature, and chiller COP changes with ambient; the app accepts a complete hourly outside_air_temp_c CSV field or generates a transparently synthetic diurnal ambient curve. All curve coefficients are assumptions, not manufacturer calibration.
- Monthly billing uses facility-level hourly kWh at a flat price and the monthly peak facility kW at an illustrative demand tariff. Water and PCM have independent cooling loads and the same electricity tariff.
- Lifecycle compares total installed media, container, common installation, maintenance, scheduled replacements and illustrative five-year operating differences. Optional avoided-chiller capacity credit defaults OFF and cannot be applied unless **both** periodic audits verify. Media-only operational/embodied CO2e is an approximation, **not** a whole-system LCA.
- Download buttons export modeled hourly thermal and electrical data plus an assumptions/audit JSON.
- The user's initial synthetic 100-panel settings are retained. Real-world claims require measured load + weather, vendor curves, system pressure drop/flow modeling, verified installation bids and a full-year/cyclic operational validation. There is no embedded digital twin/COMSOL connection in this module.

### Next research improvements

Build a forecast-constrained controller without perfect monthly foresight, model a physically complete flow-limited warm-water loop, validate against plant data and seasonal weather, perform mesh/timestep convergence, verify salt-hydrate degradation/hysteresis, and replace scenario values with source-verified industrial tariffs and LCA factors. Before a live presentation, perform a manual browser test and deploy to an authorized Shiny host.

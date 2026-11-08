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
- Identical geometry and daily load-ranked dispatch heuristic for both.
- Organic paraffin and inorganic salt-hydrate materials; graphite toggle is **hypothetical** pending measurements.

## Economics tab (exploratory)

Compares the PCM array against the **water** array from the thermal run (same panels, volume and dispatch). Positive NPV means PCM beats water. Value comes from (1) avoided chiller capacity, (2) demand-charge reduction, (3) energy-cost change. With a flat tariff and constant chiller efficiency (3) is zero by construction, because storage shifts heat rather than removing it.

Every input carries a provenance badge: **sourced**, **range-sourced**, **assumption**, or **placeholder (no source found)**. The headline outputs are break-even values rather than a single savings figure:

- **Break-even PCM price** and **break-even containment premium ($/m²)**: how much extra panel cost the modeled benefit can absorb. Panel hardware, heat exchangers and installation are assumed identical for PCM and water; corrosive salt hydrates will cost more, so this *favours PCM*.
- **Peak vs no storage** is shown next to peak vs water. The milestone-1 top-8/bottom-8 heuristic let regeneration in low-load hours create new cooling peaks (observed at 1,000 panels on the synthetic profile, where PCM "beat" water only because water spiked more). The sidebar option *Cap regeneration* (on by default) limits release to the headroom under the month's no-storage peak, so neither system can end up worse than no storage. **Side effect: at large panel counts the capped regeneration refills that headroom up to the old peak, so peak shave there is zero by construction.** A threshold peak-shaving dispatch (target a lower peak, charge only above it) is the proper fix and is not built yet. When PCM or water exceeds the no-storage peak (cap off) the app raises a red warning.

The default workload is synthetic. Do not quote its economics. Sources and limits: [SOURCES.md](SOURCES.md).

## Deploying to a shareable link

The app needs a Python host (it is a Shiny for Python app with `shinywidgets`), not static hosting. On [shinyapps.io](https://www.shinyapps.io):

```bash
pip install rsconnect-python
# shinyapps.io -> Account -> Tokens -> Show -> copy name, token, secret
rsconnect add --account NAME --name NAME --token TOKEN --secret SECRET
rsconnect deploy shiny . --name NAME --title flux-capacitor --entrypoint app:app
```

This deploy path has **not been tested** from this repository (it needs your account credentials). Check your plan's active-hour and idle-sleep limits before a demo, and open the link a few minutes beforehand so it is awake. `requirements.txt` also lists `pytest` and `scipy`, which the app does not need and which only lengthen the build.

## Validation

```bash
python -m pytest -q
```

Detailed distinctions between source-derived inputs and research assumptions are in [SOURCES.md](SOURCES.md).

## Next milestone

Replace the top-8/bottom-8 heuristic with a threshold peak-shaving dispatch (choose a target peak below the no-storage peak, charge only in hours above it, regenerate within the headroom under it), add a documented temperature-dependent heat-rejection plant and a fully sourced tariff, and replace the placeholder chiller and containment costs with vendor quotes. Only then treat the five-year economics as more than exploratory. Emissions are still not modelled.

# Flux Capacitor

**Research prototype: thermal storage comparison for liquid-cooled data centers.**

A Shiny for Python app compares two identically sized, rack-adjacent thermal storage module arrays: **water (sensible heat)** and a selected **organic/inorganic PCM**. It estimates time-varying heat absorption, regeneration, and PCM melt fraction from a full calendar-month IT-power CSV. It does **not** yet report electrical savings, operating cost, payback, or CO2e.

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

## Validation

```bash
python -m pytest -q
```

Detailed distinctions between source-derived inputs and research assumptions are in [SOURCES.md](SOURCES.md).

## Next milestone

Add a documented temperature-dependent heat-rejection plant, thermal-cycling-constrained dispatch optimization, and a fully sourced monthly electricity tariff. Only then connect to annualized CAPEX/OPEX, emissions, and 5-year financial forecasts.

# Flux Capacitor

**Research prototype: thermal storage comparison for liquid-cooled data centers.**

A single-page Shiny for Python app that compares a baseline datacenter cooling plant with the same plant plus PCM, over every hour of 2024 in Boston, and reports the **annual cost** result. See [Annual cost model](#annual-cost-model-boston-2024).

- **Configure** (sidebar): scenario ("Chiller plant (PCM showcase)", the default, or "Boston with free cooling"), PCM material, thickness, datacenter size, Run. Assumed values (panels per MW, PCM price, demand charge, chiller capex, tower approach, hypothetical nano-graphite) sit in a collapsed "Advanced (assumed values)" section.
- **Result**: break-even PCM price with a pays / does-not-pay verdict against the assumed price, plus annual saving, payback and chiller capacity avoided.
- **Proof**: the peak week of 2024 (the 168 h around the annual chiller peak), hourly (chiller load with and without PCM, PCM stored energy), and an "Assumptions and sources" section tagging every parameter as input, sourced or assumed.

The UI spec is in [docs/UI_SCOPE.md](docs/UI_SCOPE.md).

## Thermal lab model (no UI in the demo)

The earlier **Thermal lab** tab was removed from the UI for the demo; its model (`pcm/thermal.py`), the month importer, the tests and the SOURCES.md entries remain, and the tab can be restored from git history. It compares two identically sized, rack-adjacent thermal storage module arrays: **water (sensible heat)** and a selected **organic/inorganic PCM**. It estimates time-varying heat absorption, regeneration, and PCM melt fraction from a full calendar-month IT-power CSV. It does **not** report electrical savings, operating cost, payback, or CO2e.

## Run

```bash
python -m venv .venv
# activate your virtual environment
pip install -r requirements.txt
shiny run --reload app.py
```

The app needs only the committed `data/boston_2024_hourly.csv`. The notes below apply to the thermal-lab model (`pcm/thermal.py`), which used a clearly labeled **synthetic demonstration profile** until a real month CSV was uploaded. To use the published NLR ESIF data:

1. Download the **ESIF DC Power Metrics Timeseries Data (Zipped CSV)** from https://data.nlr.gov/submissions/300 .
2. Convert the downloaded zip to a complete hourly month:

   ```bash
   python -m scripts.prepare_esif /path/to/esif.influx.buildingData.PUE.combined.csv.zip data/esif_month.csv
   ```

3. Feed `data/esif_month.csv` to the thermal model (the upload UI was part of the removed tab).

The converter selects the **earliest fully observed UTC calendar month**, avoiding cherry-picking. If no complete month is available it raises an error rather than inventing missing load.

Alternatively upload any CSV with columns:

```csv
timestamp,it_power_kw
2025-07-01T00:00:00Z,950
2025-07-01T01:00:00Z,945
```

**A full calendar month of observations is required**, preferably hourly (higher-frequency timestamps are aggregated into hourly means). `ts` is also accepted instead of `timestamp`. ESIF-style timestamps such as `Mon Nov 09 2015 20:00:01 GMT-0700 (Mountain Standard Time)` are parsed and converted to UTC. Values are IT electrical power in kW, not percentages or cooling electrical kW.

## Thermal lab defaults

- Supply / return: **27°C / 37°C** (assumed), 100 panels, each 1 m² face and 50 mm thickness → **5 m³ gross storage volume**.
- 1D PCM conduction + enthalpy/melting fraction; a mixed sensible-water comparator.
- Identical geometry and daily load-ranked dispatch heuristic for both.
- Organic paraffin and inorganic salt-hydrate materials; graphite toggle is **hypothetical** pending measurements.

## Annual cost model (Boston 2024)

`pcm/annual.py` compares a **baseline** facility (no PCM) with the **same facility plus PCM** for every hour of Boston's 2024 calendar year (8784 h, local standard time, stored in UTC). For the PCM case it solves one linear program over the whole year (`scipy.optimize.linprog`, HiGHS, about 0.5 s) that chooses when the PCM absorbs heat and when it regenerates, minimising wholesale energy cost + monthly demand charges + annualised chiller capacity. The baseline is the same cost with the PCM held at zero; since that is a feasible LP solution, the PCM case can never cost more than the baseline.

- **Cooling plant**: water-cooled chiller + cooling tower with a waterside economiser. Each hour's free-cooling fraction comes from the weather: wet-bulb is computed from NSRDB temperature and RH (Stull 2011); when the tower can make supply water on its own the chiller is off. The chiller COP falls with wet-bulb (assumed curve).
- **PCM**: properties from `pcm/materials.py`; storage capacity from mass, latent and sensible heat; charge and regeneration power limited by conduction through half the panel thickness. Equations and every default are in [CLAUDE.md](CLAUDE.md); all plant and price defaults are **assumed** and listed in [SOURCES.md](SOURCES.md).

### Data

`data/boston_2024_hourly.csv` (8784 rows: `utc, temp_c, rh_pct, price_usd_per_kwh, it_kw_esif, it_filled`) is built by `scripts/prepare_boston_2024.py` from three downloads that are **not committed**:

- **IT load**: measured NLR/ESIF `it_power_kw` for 2024 (Golden, CO HPC facility, not a Boston site). Its shape is scaled so its peak equals the chosen MW. 298 missing or glitch hours were filled from the same hour one week earlier or later and are flagged in `it_filled`.
- **Weather**: NSRDB GOES Conus v4, Boston grid cell (42.36, -71.07), hourly dry-bulb and RH.
- **Price**: ISO-NE day-ahead final LMP, load zone `.Z.NEMASSBOST`. **Wholesale energy only**: no retail adder or delivery charges, so absolute costs are low.

```bash
python -m scripts.prepare_boston_2024 --weather W.csv --esif E.csv --isone DIR
```

### Presets and findings

The UI opens on the "Chiller plant (PCM showcase)" scenario; "Boston with free cooling" (as built) is one click away. Results from a 192-run scan on the 2024 data (nothing tuned after the fact):

- **Boston as built** (free cooling on, RT35HC, 50 mm, 100 panels/MW): saving **$40/yr on ~$548k (0.01 %)**. The tower makes 27 °C water alone for 8,531 of 8,784 h, so there is almost no chiller energy to shift.
- **PCM showcase** (chiller plant without economiser, Na2SO4·10H2O, 20 mm, 500 panels/MW, $27.5/kW-month, no graphite): saving **$6,209/yr (1.0 %)**, chiller -57 kW, payback 3.1 yr, break-even $4.01/kg vs $2/kg assumed price.

What makes PCM work: salt hydrates (higher conductivity and latent heat), **thin** panels (faster charging), enough area, a chiller-dependent plant, and a real demand charge. Graphite helps but is **hypothetical**. With default geometry, paraffin's low conductivity (0.2 W/mK) limits PCM power to a few kW per 100 m²; that is a real result, not a bug.

## Validation

```bash
python -m pytest -q
shiny run --reload app.py   # single page
```

Detailed distinctions between source-derived inputs and research assumptions are in [SOURCES.md](SOURCES.md).

## Next milestone

The annual model now has a weather-driven heat-rejection plant, hourly wholesale prices and LP dispatch. Still missing: a fully sourced retail tariff (delivery and demand charges), measured PCM and graphite properties, cycling degradation and supercooling, BESS comparison, emissions, and multi-year financial forecasts.

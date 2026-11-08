# Sources and model provenance

The first milestone is a **research prototype**, not validated engineering design or a claim that PCM saves money.

## Workload
- NLR/ESIF *HPC Facility Power Usage Effectiveness (PUE) Data* (2025, updated 2026); DOI: 10.7799/3015212. https://data.nlr.gov/submissions/300 . Published `it_power_kw` represents IT electrical demand; other fields include `cooling_kw` and `pump_kw`. Their electrical readings are not equivalent to total heat rejection. The repository does not embed the large ESIF raw dataset.
- `data/sample_synthetic_2025_07.csv` is **fabricated solely for testing the interface**. It must never be presented as NLR measurements or used for financial claims.
- The CSV importer deterministically chooses the earliest month with all UTC hours present and rejects partial months. This is an operational completeness rule, not an assertion that the selected month is annual-representative. ESIF timestamps (`Mon Nov 09 2015 20:00:01 GMT-0700 (Mountain Standard Time)`) are parsed with their UTC offset.
- **ESIF 2024 hourly series** (annual model, `it_kw_esif` in `data/boston_2024_hourly.csv`): `it_power_kw` from the same dataset, averaged to UTC hours over Boston's 2024 local-standard-time year (2024-01-01 05:00 UTC onward, 8784 h). Coverage is 96.7 % with 14 gaps (longest 90 h); readings below 10 % of the median are treated as glitches. Every missing or glitch hour is copied from the same hour one week earlier (else one week later), repeated until covered: **298 hours filled, all flagged in `it_filled`**. Mean 2.7 MW, peak 3.9 MW. This is a Golden, CO HPC load shape, scaled so its peak equals the chosen MW; it is not a Boston facility measurement.

## Weather (annual model)
- NSRDB GOES Conus v4.0.0 (NLR): https://developer.nlr.gov/docs/solar/nsrdb/nsrdb-GOES-conus-v4-0-0-download/ . Boston grid cell (42.36, -71.07), hourly (interval 60), calendar year 2024, fetched in **local standard time** (UTC-5, no daylight saving) and converted to UTC. Fields used: `Temperature` (dry-bulb, °C) and `Relative Humidity` (%). Raw download not committed.
- Wet-bulb: Stull, R. (2011), *Wet-Bulb Temperature from Relative Humidity and Air Temperature*, Journal of Applied Meteorology and Climatology 50, 2267-2269, doi:10.1175/JAMC-D-11-0143.1. Empirical fit valid for roughly 5-99 % RH and -20 to 50 °C at sea-level pressure; reported errors within about -1 to +0.65 K.

## Electricity price (annual model)
- ISO-NE web services, hourly **day-ahead final LMP**, location 4008 `.Z.NEMASSBOST` (NEMA/Boston load zone): https://webservices.iso-ne.com/docs/v1.1/ . `LmpTotal` in $/MWh, converted to $/kWh. **Wholesale energy only**: no retail adder, capacity, transmission or delivery charges, so absolute annual costs understate a real bill. Raw downloads not committed (the service needs an ISO-NE account).

## PCM material properties
- Rubitherm RT35HC: https://www.rubitherm.com/media/products/datasheets/Techdata_-RT35HC_EN_09102020.PDF . Melting 34–36°C, 0.2 W/(m K), 2 kJ/(kg K), solid density 0.88 kg/L. Manufacturer's **240 kJ/kg is combined sensible + latent storage between 27–42°C**, not pure latent. The `180 kJ/kg` latent parameter in `materials.py` is a provisional modeling assumption and MUST NOT be treated as datasheet value.
- Rubitherm RT28HC: https://www.rubitherm.eu/media/products/datasheets/Techdata_-RT28HC_EN_09102020.PDF . Melting 27–29°C, conductivity 0.2 W/(m K), cp 2 kJ/(kg K), solid density 0.88 kg/L. Its **250 kJ/kg is total sensible + latent storage over 21–36°C**. `190 kJ/kg` in the app is an unverified assumption.
- NASA historical salt-hydrate table: https://ntrs.nasa.gov/api/citations/19720012306/downloads/19720012306.pdf . Lists CaCl2·6H2O melting ~29.4°C, latent 170 kJ/kg; Na2SO4·10H2O melting 32.4°C, latent 253 kJ/kg, density 1460 kg/m³. Several other properties in the code are placeholder assumptions. Real salt hydrates can phase-separate and supercool, neither represented here.
- Nano-graphite enhancement is a **hypothetical sensitivity case** (2x conductivity, 0.98x latent heat), not experimentally established for any named PCM here. Per-material characterization is required before economic conclusions.

## Thermal algorithm
- PCM: 1D finite-volume conduction through an idealized planar layer, explicit update of node enthalpy, uniformly spread 2°C phase transition. Zero heat flux at rear face. Fluid-side convection applied with series half-cell resistance. Stability timestep constrained by diffusion in the solid/sensible phase. No natural convection in liquid PCM, melting hysteresis or phase-separation physics.
- Water: well-mixed, constant-cp sensible storage with same gross volume and fluid-side heat-transfer coefficient. A full engineering model needs matching containment, pressure drop, exchanger area, tank mixing and thermal losses.
- Initial PCM/water temperature 27°C. Hot return fluid assumed 37°C during charge; regeneration assumes 27°C supply water. No weather-dependent fluid supply temperature; external cooling-equipment energy for regeneration is **not** evaluated.
- Controller: rank each day's IT hourly load, allow charge in eight highest load hours, regenerate in eight lowest. This is a **heuristic, not an optimization**. The same hours and geometry are applied to water and PCM, regardless of resulting heat-transfer capacity. Hourly storage kW are thermal energy / 1h; plant thermal load = IT power − storage kW. That equality does **not** compute chiller electricity or demand charges.
- 100 panels * 1 m² * 0.05 m = 5 m³ gross material volume; the real encapsulated volume would differ. The water reference capacity for 10°C sensible change is 58.06 kWh.

## Annual model assumptions
Every value below is **assumed** (engineering placeholder, not sourced or calibrated). All are fields of `pcm.annual.Params`.
- Loop supply / return 27 / 37 °C; fluid-side h 150 W/m²K; 100 panels per MW of IT, 1 m² face each (from the thermal lab `Config`).
- Chiller COP: 6.0 at wet-bulb 20 °C, falling 0.15 per K of wet-bulb, floor 3.0.
- Waterside economiser on; cooling-tower approach 4 K; free-cooling COP 25 (tower fans + pumps). Free-cooling fraction `f = clip((T_return - approach - T_wb) / (T_return - T_supply), 0, 1)`.
- Demand charge $15/kW-month on the monthly peak of grid power (placeholder, not a utility tariff).
- Chiller capex $250/kW_th, 20-year life, 7 % discount, annualised with the capital recovery factor.
- PCM price: paraffin $5/kg, salt hydrate $2/kg (placeholders, not quotes). PCM life 15 years, 7 % discount.
- PCM power limit from conduction only: `UA = A / (1/h + (thickness/2)/k)`; charge `<= UA·(T_return - T_melt)`, regeneration `<= UA·(T_melt - T_supply)`, `T_melt` = midpoint of the melt range. Half-thickness is a mean melt-front depth; no natural convection, hysteresis or partial-melt dynamics.
- Storage capacity `E_max = m·(L + cp·(T_return - T_supply))`, cyclic over the year; perfect foresight of load, weather and price in the LP.
- All IT power becomes heat (`Q_IT = P_IT`).

## Explicitly not implemented
Now implemented in the annual model (with the assumptions above, not calibrated): weather integration, hourly wholesale prices with a demand charge, LP dispatch, and PCM / chiller capex. Still missing: cooling-plant calibration against a real chiller and tower, retail tariffs (delivery, capacity, real demand-charge schedules), battery storage (BESS) comparison, embodied and operational CO2e, carbon-price scenarios, replacement/maintenance costs, multi-year DCF, experimentally measured graphite effectiveness, repeated-cycle material degradation, salt-hydrate supercooling and phase separation. These should be separate validated modules in later PRs.

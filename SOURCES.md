# Sources and model provenance

The first milestone is a **research prototype**, not validated engineering design or a claim that PCM saves money.

## Workload
- NLR/ESIF *HPC Facility Power Usage Effectiveness (PUE) Data* (2025, updated 2026); DOI: 10.7799/3015212. https://data.nlr.gov/submissions/300 . Published `it_power_kw` represents IT electrical demand; other fields include `cooling_kw` and `pump_kw`. Their electrical readings are not equivalent to total heat rejection. The repository does not embed the large ESIF raw dataset.
- `data/sample_synthetic_2025_07.csv` is **fabricated solely for testing the interface**. It must never be presented as NLR measurements or used for financial claims.
- The CSV importer deterministically chooses the earliest month with all UTC hours present and rejects partial months. This is an operational completeness rule, not an assertion that the selected month is annual-representative.

## PCM material properties
- Rubitherm RT35HC: https://www.rubitherm.com/media/products/datasheets/Techdata_-RT35HC_EN_09102020.PDF . Melting 34–36°C, 0.2 W/(m K), 2 kJ/(kg K), solid density 0.88 kg/L. Manufacturer's **240 kJ/kg is combined sensible + latent storage between 27–42°C**, not pure latent. The `180 kJ/kg` latent parameter in `materials.py` is a provisional modeling assumption and MUST NOT be treated as datasheet value.
- Rubitherm RT28HC: https://www.rubitherm.eu/media/products/datasheets/Techdata_-RT28HC_EN_09102020.PDF . Melting 27–29°C, conductivity 0.2 W/(m K), cp 2 kJ/(kg K), solid density 0.88 kg/L. Its **250 kJ/kg is total sensible + latent storage over 21–36°C**. `190 kJ/kg` in the app is an unverified assumption.
- NASA historical salt-hydrate table: https://ntrs.nasa.gov/api/citations/19720012306/downloads/19720012306.pdf . Lists CaCl2·6H2O melting ~29.4°C, latent 170 kJ/kg; Na2SO4·10H2O melting 32.4°C, latent 253 kJ/kg, density 1460 kg/m³. Several other properties in the code are placeholder assumptions. Real salt hydrates can phase-separate and supercool, neither represented here.
- Nano-graphite enhancement is a **hypothetical sensitivity case** (2x conductivity, 0.98x latent heat), not experimentally established for any named PCM here. Per-material characterization is required before economic conclusions.

## Thermal algorithm
- PCM: 1D finite-volume conduction through an idealized planar layer, explicit update of node enthalpy, uniformly spread 2°C phase transition. Zero heat flux at rear face. Fluid-side convection applied with series half-cell resistance. Stability timestep constrained by diffusion in the solid/sensible phase. No natural convection in liquid PCM, melting hysteresis or phase-separation physics.
- Water: well-mixed, constant-cp sensible storage with same gross volume and fluid-side heat-transfer coefficient. A full engineering model needs matching containment, pressure drop, exchanger area, tank mixing and thermal losses.
- Initial PCM/water temperature 27°C. Hot return fluid assumed 37°C during charge; regeneration assumes 27°C supply water. No weather-dependent fluid supply temperature; external cooling-equipment energy for regeneration is **not** evaluated.
- Controller: rank each day's IT hourly load, allow charge in eight highest load hours, regenerate in eight lowest. This is a **heuristic, not an optimization**. The same hours and geometry are applied to water and PCM, regardless of resulting heat-transfer capacity. With `cap_regeneration=True` (default since milestone 2) heat released in any hour is also limited to (month peak IT power − that hour's IT power), applied identically to water and PCM. This uses perfect foresight of the month's peak, an idealization, and guarantees neither system's plant load exceeds the no-storage peak. It does not target a lower peak: capped regeneration can refill the headroom up to the old peak, so shave at large panel counts is zero by construction. `cap_regeneration=False` reproduces milestone 1. Hourly storage kW are thermal energy / 1h; plant thermal load = IT power − storage kW. That equality does **not** compute chiller electricity or demand charges.
- 100 panels * 1 m² * 0.05 m = 5 m³ gross material volume; the real encapsulated volume would differ. The water reference capacity for 10°C sensible change is 58.06 kWh.

## Economics inputs (milestone 2, exploratory)

Values below were read through a summarizing page fetch, not by opening each PDF. **Confirm each against its source before quoting it.**

| Input | Default | Status | Basis |
|---|---|---|---|
| Electricity price | 14.00 ¢/kWh | sourced | EIA STEO Table 7c, U.S. commercial average, 2026 forecast (13.41 ¢ in 2025; 14.21 ¢ in 2027). https://www.eia.gov/outlooks/steo/tables/pdf/7ctab.pdf . National average, not a site tariff. |
| Chiller electric intensity | 0.544 kW/ton | sourced | DOE FEMP water-cooled centrifugal chillers 300-399 tons, full-load requirement (IPLV 0.520). https://www.energy.gov/femp/purchasing-energy-efficient-water-cooled-electric-chillers . Compressor only. |
| PCM material price | by material | range-sourced | OSTI 1813229 (cost data collected autumn 2020): CaCl2·6H2O 0.10-0.19 $/kg; Na2SO4·10H2O 0.03-0.09 $/kg; generic paraffin waxes 0.45-1.76 $/kg. https://www.osti.gov/servlets/purl/1813229 . Default is the midpoint. Branded Rubitherm RT28HC/RT35HC prices were **not found**; the paraffin range is a generic-wax proxy. Bulk material only, not installed. |
| Demand charge | 15 $/kW-month | range-sourced | No national average found. NREL (Aug 2017) gives state medians of utility maximum demand charges from $3.60/kW (GA) to $18.50/kW (AZ), https://www.cleanegroup.org/wp-content/uploads/NREL_BatteryStorage_2017.pdf . The $15 default is an illustrative example rate from electricrates.org, not measured. |
| Installed chiller cost | 1,000 $/ton | **placeholder** | **No source found.** Only a 2007 ACEEE case study's incremental water-cooled premium (>$500/ton) turned up, which is not an installed cost. The break-even chiller cost and the map's y-axis exist so this number can be replaced or bracketed. |
| PCM containment premium | 0 $/m² | **placeholder** | **No source found.** 0 means PCM panels cost the same as water panels, which is optimistic for corrosive, supercooling salt hydrates. The break-even containment premium shows how much the model can absorb. |
| Discount rate | 8 %/yr | assumption | Not sourced. |
| Water fill cost | 0 $/kg | assumption | Not costed; assumed negligible. |

Not sourced at all: heat-exchanger, encapsulation, installation and maintenance costs; PCM replacement/degradation; data-center-specific tariffs; thermal-storage tank costs (the water comparator is costed as a panel array identical to the PCM one).

Model limits: one simulated month is scaled to a year; billed demand is assumed to follow the cooling peak; chiller efficiency is constant; no design margin or N+1; flat tariff (the hourly-price hook in `evaluate` is unit-tested but not exposed in the UI). With the heuristic dispatch, PCM and/or water can raise the cooling peak above the no-storage peak at large panel counts; the NPV versus water is then not a saving versus doing nothing, and the app flags it.

## Explicitly not implemented
Cooling plant COP/free-cooling performance calibration, weather integration, time-of-use/demand tariffs in the UI, optimal dispatch, installed-cost build-up (heat exchangers, encapsulation, installation), replacement/maintenance, embodied CO2e, operational emissions, U.S. hypothetical carbon-price scenario, graphite experimentally measured effectiveness, repeated-cycle material degradation. These should be separate validated modules in later PRs.

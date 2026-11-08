"""Five-year techno-economics: PCM storage vs the water storage comparator.

Scope (milestone 2). Compares the PCM array with the *water* array that
``pcm.thermal.simulate`` already runs under identical geometry and dispatch.
Positive NPV means PCM is better than water. Nothing here is a validated
engineering estimate: see ``INPUT_META`` for which inputs are sourced and
which are placeholders, and ``EconResult.warnings`` for model limits.

Value streams counted (all relative to water storage):
  1. Avoided/added chiller capacity  = change in peak plant thermal load.
  2. Demand-charge change            = change in peak cooling electric kW.
  3. Energy-cost change              = hourly cooling electricity x price.
     Under a flat tariff and constant chiller efficiency this is zero by
     construction: storage shifts heat, it does not remove it.

Costs counted: PCM material, an optional PCM-specific containment premium,
and water fill. Panel hardware, heat exchangers and installation are assumed
identical for PCM and water and therefore cancel. That is optimistic for PCM
(salt hydrates are corrosive and need supercooling/phase-separation
mitigation) and is flagged in every result.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .materials import Material
from .thermal import Config

KW_TH_PER_TON = 3.5168525  # 1 ton of refrigeration = 12,000 Btu/h
WATER_DENSITY_KG_M3 = 1000.0  # same value the thermal model uses

SOURCED = "sourced"
RANGE = "range-sourced"
ASSUMPTION = "assumption"
PLACEHOLDER = "placeholder (no source found)"


@dataclass(frozen=True)
class InputMeta:
    key: str
    label: str
    default: float
    unit: str
    status: str
    source: str
    url: str = ""


INPUT_META: dict[str, InputMeta] = {
    m.key: m
    for m in (
        InputMeta(
            "electricity_c_per_kwh", "Electricity energy price", 14.0, "¢/kWh", SOURCED,
            "EIA STEO Table 7c, U.S. commercial average, 2026 forecast (13.41 ¢ in 2025, "
            "14.21 ¢ forecast 2027). National average, not a data-center or site tariff.",
            "https://www.eia.gov/outlooks/steo/tables/pdf/7ctab.pdf",
        ),
        InputMeta(
            "demand_usd_per_kw_month", "Demand charge", 15.0, "$/kW-month", RANGE,
            "No national average found. NREL (2017) reports state medians of utility "
            "maximum demand charges from $3.60/kW (GA) to $18.50/kW (AZ); the $15/kW "
            "default is an illustrative example rate, not a measured value.",
            "https://www.cleanegroup.org/wp-content/uploads/NREL_BatteryStorage_2017.pdf",
        ),
        InputMeta(
            "chiller_kw_per_ton", "Chiller electric intensity", 0.544, "kW/ton", SOURCED,
            "DOE FEMP full-load requirement for water-cooled centrifugal chillers of "
            "300-399 tons (IPLV 0.520). Compressor only: excludes towers and pumps, and "
            "is held constant (no weather dependence).",
            "https://www.energy.gov/femp/purchasing-energy-efficient-water-cooled-electric-chillers",
        ),
        InputMeta(
            "chiller_usd_per_ton", "Installed chiller cost", 1000.0, "$/ton", PLACEHOLDER,
            "No source found. Analyst placeholder; the break-even outputs show what "
            "value would flip the conclusion.",
        ),
        InputMeta(
            "discount_rate", "Discount rate", 0.08, "fraction/yr", ASSUMPTION,
            "Analyst assumption, not sourced.",
        ),
        InputMeta(
            "pcm_extra_usd_per_m2", "PCM-specific containment premium", 0.0, "$/m² of panel",
            PLACEHOLDER,
            "No source found. 0 assumes PCM panels cost the same as water panels, which "
            "is optimistic for corrosive, supercooling salt hydrates.",
        ),
        InputMeta(
            "water_usd_per_kg", "Water fill cost", 0.0, "$/kg", ASSUMPTION,
            "Not costed; assumed negligible next to PCM material cost.",
        ),
    )
}

# (low, default = midpoint, high) in $/kg. OSTI 1813229 (Hirschey/ORNL review of
# low-cost PCMs; cost data collected autumn 2020). Paraffin values are for GENERIC
# paraffin waxes: the branded Rubitherm price was not found.
PCM_PRICE_USD_PER_KG: dict[str, tuple[float, float, float]] = {
    "rt35hc": (0.45, 1.105, 1.76),
    "rt28hc": (0.45, 1.105, 1.76),
    "cacl2": (0.10, 0.145, 0.19),
    "na2so4": (0.03, 0.06, 0.09),
}
PCM_PRICE_SOURCE = "https://www.osti.gov/servlets/purl/1813229"
PCM_PRICE_NOTE = {
    "rt35hc": "Generic paraffin-wax proxy (0.45-1.76 $/kg); branded Rubitherm price not found.",
    "rt28hc": "Generic paraffin-wax proxy (0.45-1.76 $/kg); branded Rubitherm price not found.",
    "cacl2": "CaCl2·6H2O bulk material, 0.10-0.19 $/kg. Material only, not installed.",
    "na2so4": "Na2SO4·10H2O bulk material, 0.03-0.09 $/kg. Material only, not installed.",
}


def pcm_price_default(key: str) -> float:
    return PCM_PRICE_USD_PER_KG[key][1]


@dataclass(frozen=True)
class EconInputs:
    electricity_c_per_kwh: float = INPUT_META["electricity_c_per_kwh"].default
    demand_usd_per_kw_month: float = INPUT_META["demand_usd_per_kw_month"].default
    chiller_kw_per_ton: float = INPUT_META["chiller_kw_per_ton"].default
    chiller_usd_per_ton: float = INPUT_META["chiller_usd_per_ton"].default
    discount_rate: float = INPUT_META["discount_rate"].default
    years: int = 5
    pcm_usd_per_kg: float = 1.105
    pcm_extra_usd_per_m2: float = INPUT_META["pcm_extra_usd_per_m2"].default
    water_usd_per_kg: float = INPUT_META["water_usd_per_kg"].default


@dataclass
class EconResult:
    # physical drivers
    peak_none_kw: float
    peak_water_kw: float
    peak_pcm_kw: float
    delta_peak_kw: float  # water minus PCM; positive = PCM lowers the cooling peak
    delta_peak_pcm_vs_none_kw: float  # no-storage peak minus PCM peak; negative = PCM raises the peak
    delta_peak_water_vs_none_kw: float
    avoided_tons: float
    pcm_mass_kg: float
    panel_area_m2: float
    # cost lines
    pcm_material_cost: float
    pcm_extra_cost: float
    water_cost: float
    gross_extra_capex: float
    avoided_chiller_capex: float
    net_capex: float  # negative = PCM is cheaper up front than water
    # annual value
    demand_savings_year: float
    energy_savings_year: float
    annual_savings: float
    annuity_factor: float
    pv_savings: float
    npv: float
    payback_years: float | None
    break_even_pcm_usd_per_kg: float
    break_even_chiller_usd_per_ton: float | None
    break_even_extra_usd_per_m2: float  # max PCM-specific containment premium before NPV < 0
    cooling_kwh_water_month: float
    cooling_kwh_pcm_month: float
    cashflow: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    warnings: tuple[str, ...] = ()


def _validate(inp: EconInputs) -> None:
    if inp.years < 1 or int(inp.years) != inp.years:
        raise ValueError("Years must be a whole number of at least 1.")
    if inp.discount_rate <= -1:
        raise ValueError("Discount rate must be greater than -100%.")
    if inp.chiller_kw_per_ton <= 0:
        raise ValueError("Chiller kW/ton must be positive.")
    for name in ("electricity_c_per_kwh", "demand_usd_per_kw_month", "chiller_usd_per_ton",
                 "pcm_usd_per_kg", "pcm_extra_usd_per_m2", "water_usd_per_kg"):
        if getattr(inp, name) < 0:
            raise ValueError(f"{name} cannot be negative.")


def _annuity(rate: float, years: int) -> float:
    if rate == 0:
        return float(years)
    return float(sum(1.0 / (1.0 + rate) ** t for t in range(1, years + 1)))


def evaluate(
    result: pd.DataFrame,
    material: Material,
    cfg: Config,
    inp: EconInputs,
    hourly_price_usd_kwh: np.ndarray | None = None,
    synthetic: bool = False,
) -> EconResult:
    """Economics of PCM vs water from a ``simulate`` result (one hourly month)."""
    _validate(inp)
    n = len(result)
    if n == 0:
        raise ValueError("Empty simulation result.")
    if hourly_price_usd_kwh is None:
        price = np.full(n, inp.electricity_c_per_kwh / 100.0)
    else:
        price = np.asarray(hourly_price_usd_kwh, dtype=float)
        if price.shape != (n,):
            raise ValueError("hourly_price_usd_kwh must have one value per simulated hour.")

    k_e = inp.chiller_kw_per_ton / KW_TH_PER_TON  # electric kW per thermal kW
    it = result["it_power_kw"].to_numpy(float)
    plant_pcm = result["pcm_plant_thermal_kw"].to_numpy(float)
    plant_water = result["water_plant_thermal_kw"].to_numpy(float)
    store_pcm = result["pcm_storage_kw"].to_numpy(float)
    store_water = result["water_storage_kw"].to_numpy(float)

    def cooling_cost_and_kwh(plant_kw: np.ndarray, storage_kw: np.ndarray) -> tuple[float, float]:
        # Heat still sitting in storage at month end is rejected in the last hour, so
        # the comparison does not credit unreleased heat as a saving.
        load = plant_kw.copy()
        load[-1] += storage_kw.sum()
        electric_kwh = load * k_e  # 1-hour steps
        return float(np.sum(electric_kwh * price)), float(electric_kwh.sum())

    cost_pcm, kwh_pcm = cooling_cost_and_kwh(plant_pcm, store_pcm)
    cost_water, kwh_water = cooling_cost_and_kwh(plant_water, store_water)
    annualize = 365.0 / (n / 24.0)
    energy_savings_year = (cost_water - cost_pcm) * annualize

    peak_none = float(it.max())
    peak_pcm = float(plant_pcm.max())
    peak_water = float(plant_water.max())
    delta_peak = peak_water - peak_pcm
    avoided_tons = delta_peak / KW_TH_PER_TON
    avoided_capex = avoided_tons * inp.chiller_usd_per_ton
    demand_savings_year = delta_peak * k_e * inp.demand_usd_per_kw_month * 12.0

    volume_m3 = cfg.panels * cfg.area_per_panel_m2 * cfg.thickness_m
    panel_area_m2 = cfg.panels * cfg.area_per_panel_m2
    pcm_mass = material.density_kg_m3 * volume_m3
    pcm_material_cost = pcm_mass * inp.pcm_usd_per_kg
    pcm_extra = inp.pcm_extra_usd_per_m2 * panel_area_m2
    water_cost = WATER_DENSITY_KG_M3 * volume_m3 * inp.water_usd_per_kg
    gross_extra = pcm_material_cost + pcm_extra - water_cost
    net_capex = gross_extra - avoided_capex

    annual_savings = demand_savings_year + energy_savings_year
    annuity = _annuity(inp.discount_rate, int(inp.years))
    pv_savings = annual_savings * annuity
    npv = pv_savings - net_capex

    if net_capex <= 0:
        payback = 0.0
    elif annual_savings > 0:
        payback = net_capex / annual_savings
    else:
        payback = None

    be_price = (pv_savings + avoided_capex - pcm_extra + water_cost) / pcm_mass
    be_chiller = (gross_extra - pv_savings) / avoided_tons if avoided_tons > 0 else None
    be_extra = (pv_savings + avoided_capex - pcm_material_cost + water_cost) / panel_area_m2

    rows = [dict(year=0, capex_net=-net_capex, savings=0.0, discount_factor=1.0)]
    for t in range(1, int(inp.years) + 1):
        rows.append(dict(year=t, capex_net=0.0, savings=annual_savings,
                         discount_factor=1.0 / (1.0 + inp.discount_rate) ** t))
    cash = pd.DataFrame(rows)
    cash["discounted"] = (cash.capex_net + cash.savings) * cash.discount_factor
    cash["cumulative_discounted"] = cash.discounted.cumsum()

    warns = [
        "Panel hardware, heat exchangers and installation are assumed identical for PCM and "
        "water, so they cancel. Salt-hydrate corrosion, supercooling and phase-separation "
        "mitigation are not costed: this favours PCM.",
        "One simulated month is scaled to a year (demand charge x12, energy x365/days). "
        "Real facilities have seasonal load and weather variation.",
        "Billed demand is assumed to follow the cooling peak. Facility-wide peaks, ratchets "
        "and the utility tariff structure are not modelled.",
        "Chiller efficiency is a constant compressor-only value, with no weather or "
        "part-load dependence.",
        "Chiller capacity credit uses the simulated month's peak. No design margin or "
        "redundancy (N+1) is applied, and equipment comes in discrete sizes.",
    ]
    if hourly_price_usd_kwh is None:
        warns.append("Flat energy tariff: energy-cost savings are zero by construction, "
                     "because storage shifts heat rather than removing it.")
    if inp.chiller_usd_per_ton == INPUT_META["chiller_usd_per_ton"].default:
        warns.append("Chiller $/ton is an unsourced placeholder; see the break-even chiller "
                     "cost for what it would take to change the answer.")
    if delta_peak < 0:
        warns.append("Under this dispatch PCM RAISES the cooling peak versus water "
                     "(regeneration adds load in low-IT hours), so the capacity and "
                     "demand terms are negative.")
    tol = 1e-9
    if peak_pcm > peak_none + tol:
        warns.append("PCM's cooling peak EXCEEDS the no-storage peak under this dispatch "
                     "(regeneration creates new peaks). Any credit versus water is not a "
                     "saving versus doing nothing.")
    elif peak_water > peak_none + tol and delta_peak > 0:
        warns.append("Water's cooling peak exceeds the no-storage peak (its regeneration "
                     "creates new peaks), so part of PCM's advantage versus water comes "
                     "from water's dispatch spike, not from PCM performance.")
    if "graphite" in material.name.lower():
        warns.append("Nano-graphite cost is not included.")
    if synthetic:
        warns.append("Workload is the synthetic demonstration profile, not measured data. "
                     "Do not quote these results.")

    return EconResult(
        peak_none_kw=peak_none, peak_water_kw=peak_water, peak_pcm_kw=peak_pcm,
        delta_peak_kw=delta_peak, delta_peak_pcm_vs_none_kw=peak_none - peak_pcm,
        delta_peak_water_vs_none_kw=peak_none - peak_water,
        avoided_tons=avoided_tons, pcm_mass_kg=pcm_mass, panel_area_m2=panel_area_m2,
        pcm_material_cost=pcm_material_cost, pcm_extra_cost=pcm_extra, water_cost=water_cost,
        gross_extra_capex=gross_extra, avoided_chiller_capex=avoided_capex, net_capex=net_capex,
        demand_savings_year=demand_savings_year, energy_savings_year=energy_savings_year,
        annual_savings=annual_savings, annuity_factor=annuity, pv_savings=pv_savings, npv=npv,
        payback_years=payback, break_even_pcm_usd_per_kg=be_price,
        break_even_chiller_usd_per_ton=be_chiller, break_even_extra_usd_per_m2=be_extra,
        cooling_kwh_water_month=kwh_water, cooling_kwh_pcm_month=kwh_pcm,
        cashflow=cash, warnings=tuple(warns),
    )


def npv_grid(res: EconResult, prices_usd_per_kg: np.ndarray, chiller_usd_per_ton: np.ndarray) -> np.ndarray:
    """NPV over (chiller $/ton rows) x (PCM $/kg columns), without re-simulating.

    NPV is linear in both: NPV = (PV savings - extra + water) + tons*c - mass*p.
    """
    a = res.pv_savings - res.pcm_extra_cost + res.water_cost
    p = np.asarray(prices_usd_per_kg, float)[None, :]
    c = np.asarray(chiller_usd_per_ton, float)[:, None]
    return a + res.avoided_tons * c - res.pcm_mass_kg * p


def sensitivity(
    result: pd.DataFrame, material: Material, cfg: Config, inp: EconInputs,
    synthetic: bool = False,
) -> list[dict]:
    """One-at-a-time NPV swings over each uncertain input's low/high range."""
    lo_p, _, hi_p = PCM_PRICE_USD_PER_KG[material.key]
    ranges = [
        ("PCM price ($/kg)", "pcm_usd_per_kg", lo_p, hi_p),
        ("Demand charge ($/kW-mo)", "demand_usd_per_kw_month", 3.6, 18.5),
        ("Chiller cost ($/ton), placeholder range", "chiller_usd_per_ton", 500.0, 2000.0),
        ("Discount rate", "discount_rate", 0.04, 0.12),
    ]
    base = evaluate(result, material, cfg, inp, synthetic=synthetic).npv
    out = []
    for label, field_name, lo, hi in ranges:
        npv_lo = evaluate(result, material, cfg, replace(inp, **{field_name: lo}), synthetic=synthetic).npv
        npv_hi = evaluate(result, material, cfg, replace(inp, **{field_name: hi}), synthetic=synthetic).npv
        out.append(dict(label=label, low=lo, high=hi, npv_low=npv_lo, npv_high=npv_hi, base=base))
    return out

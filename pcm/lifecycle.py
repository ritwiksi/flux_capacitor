"""Illustrative full-facility electricity bills, installed costs, and CO2e.

No default is claimed to be the actual ESIF tariff, equipment quotation,
material LCA, or emissions factor. All adjustable defaults are scenarios.
The optional thermal-capacity credit is DISABLED unless both cyclic audits pass.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from .materials import Material
from .thermal import Config

KWTH_PER_TON = 3.5168525


@dataclass(frozen=True)
class LifecycleInputs:
    energy_price_usd_kwh: float = 0.14
    demand_charge_usd_kw_month: float = 15.0
    discount_rate: float = 0.08
    years: int = 5
    pcm_material_usd_kg: float = 0.145
    water_media_usd_kg: float = 0.0
    pcm_containment_usd_m2: float = 120.0
    water_containment_usd_m2: float = 65.0
    common_install_usd_m2: float = 60.0
    pcm_maintenance_fraction_year: float = 0.025
    water_maintenance_fraction_year: float = 0.015
    pcm_replace_years: int = 8
    water_replace_years: int = 15
    pcm_embodied_kgco2e_kg: float = 2.0
    water_embodied_kgco2e_kg: float = 0.002
    grid_kgco2e_kwh: float = 0.4
    shadow_price_usd_tco2e: float = 0.0
    chiller_installed_usd_per_ton: float = 1000.0
    allow_capacity_credit: bool = False


@dataclass
class LifecycleResult:
    pcm_capex_usd: float
    water_capex_usd: float
    pcm_month_bill_usd: float
    water_month_bill_usd: float
    pcm_month_energy_kwh: float
    water_month_energy_kwh: float
    pcm_month_operational_kgco2e: float
    water_month_operational_kgco2e: float
    pcm_embodied_kgco2e: float
    water_embodied_kgco2e: float
    chiller_credit_usd: float
    annual_operating_savings_usd: float
    npv_usd: float
    pcm_total_5y_kgco2e: float
    water_total_5y_kgco2e: float
    cashflows: pd.DataFrame
    warnings: tuple[str, ...]


def evaluate_lifecycle(
    plant: pd.DataFrame, material: Material, geometry: Config,
    options: LifecycleInputs,
    *, pcm_cycle_verified: bool = False, water_cycle_verified: bool = False,
) -> LifecycleResult:
    if options.years < 1 or int(options.years) != options.years:
        raise ValueError("Years must be a whole number >=1.")
    if options.discount_rate <= -1 or options.pcm_replace_years < 1 or options.water_replace_years < 1:
        raise ValueError("Invalid discount rate or replacement interval.")
    values = [v for k, v in vars(options).items() if k not in ("years", "pcm_replace_years",
              "water_replace_years", "allow_capacity_credit", "discount_rate")]
    if not np.isfinite(values).all() or min(values) < 0:
        raise ValueError("Cost and emissions assumptions must be finite and nonnegative.")
    if plant.empty:
        raise ValueError("Plant profile is empty.")

    volume = geometry.panels * geometry.area_per_panel_m2 * geometry.thickness_m
    area = geometry.panels * geometry.area_per_panel_m2
    pcm_mass = material.density_kg_m3 * volume
    water_mass = 1000.0 * volume
    pcm_media = pcm_mass * options.pcm_material_usd_kg
    water_media = water_mass * options.water_media_usd_kg
    pcm_replace = pcm_media + area * options.pcm_containment_usd_m2
    water_replace = water_media + area * options.water_containment_usd_m2
    common_installed = area * options.common_install_usd_m2
    pcm_capex = pcm_replace + common_installed
    water_capex = water_replace + common_installed

    def bill(kind):
        total = plant[f"{kind}_facility_electric_kw"].to_numpy(float)
        if not np.isfinite(total).all() or (total < 0).any():
            raise ValueError("Facility electricity cannot be invalid or negative.")
        return (float(total.sum() * options.energy_price_usd_kwh +
                      total.max() * options.demand_charge_usd_kw_month),
                float(plant[f"{kind}_cooling_electric_kw"].sum()))

    pcm_bill, pcm_kwh = bill("pcm")
    water_bill, water_kwh = bill("water")
    pcm_maintenance = pcm_capex * options.pcm_maintenance_fraction_year
    water_maintenance = water_capex * options.water_maintenance_fraction_year
    annual_saving = (water_bill - pcm_bill) * 12.0 + (water_maintenance - pcm_maintenance)
    capacity_credit = 0.0
    warnings = [
        "All costs, COP curves, embodied coefficients and grid carbon intensity are illustrative assumptions.",
        "One workload/weather month is repeated 12 times/year and cannot validate a five-year forecast.",
        "No pump/heat-exchanger pressure-drop curves, PCM hysteresis, N+1 redundancy, capacity increments, "
        "degradation, or vendor bids are modeled.",
    ]
    if options.allow_capacity_credit:
        if pcm_cycle_verified and water_cycle_verified:
            delta_kw = (float(plant.water_heat_rejection_kwth.max()) -
                        float(plant.pcm_heat_rejection_kwth.max()))
            capacity_credit = delta_kw / KWTH_PER_TON * options.chiller_installed_usd_per_ton
            warnings.append("Exploratory capacity credit: repeating one month does not prove seasonal equipment downsizing.")
        else:
            warnings.append("Chiller capacity credit suppressed: BOTH PCM and water must pass the repeated-cycle audit.")

    pcm_embodied = pcm_mass * options.pcm_embodied_kgco2e_kg
    water_embodied = water_mass * options.water_embodied_kgco2e_kg
    pcm_month_co2 = pcm_kwh * options.grid_kgco2e_kwh
    water_month_co2 = water_kwh * options.grid_kgco2e_kwh
    pcm_5y = pcm_embodied + 12 * options.years * pcm_month_co2
    water_5y = water_embodied + 12 * options.years * water_month_co2

    flows = []
    cash_zero = water_capex - pcm_capex + capacity_credit
    flows.append({"year": 0, "net_savings_usd": cash_zero, "discount_factor": 1.0,
                  "discounted_usd": cash_zero})
    for year in range(1, options.years + 1):
        replacement_delta = 0.0
        if year % options.water_replace_years == 0:
            replacement_delta += water_replace
            water_5y += water_embodied
        if year % options.pcm_replace_years == 0:
            replacement_delta -= pcm_replace
            pcm_5y += pcm_embodied
        value = annual_saving + replacement_delta
        # Shadow carbon price is an optional illustrative economic convention.
        # Applying it to *operational* emissions only avoids double-counting media
        # embodied costs and avoids implying a real federal carbon levy.
        value += ((water_month_co2 - pcm_month_co2) * 12 / 1000 *
                  options.shadow_price_usd_tco2e)
        fac = (1 + options.discount_rate) ** (-year)
        flows.append({"year": year, "net_savings_usd": value, "discount_factor": fac,
                      "discounted_usd": value * fac})
    cash = pd.DataFrame(flows)
    return LifecycleResult(
        pcm_capex_usd=pcm_capex, water_capex_usd=water_capex,
        pcm_month_bill_usd=pcm_bill, water_month_bill_usd=water_bill,
        pcm_month_energy_kwh=pcm_kwh, water_month_energy_kwh=water_kwh,
        pcm_month_operational_kgco2e=pcm_month_co2,
        water_month_operational_kgco2e=water_month_co2,
        pcm_embodied_kgco2e=pcm_embodied, water_embodied_kgco2e=water_embodied,
        chiller_credit_usd=capacity_credit, annual_operating_savings_usd=annual_saving,
        npv_usd=float(cash.discounted_usd.sum()),
        pcm_total_5y_kgco2e=pcm_5y, water_total_5y_kgco2e=water_5y,
        cashflows=cash, warnings=tuple(warnings),
    )

"""Annual cost model: Boston 2024, baseline (no PCM) vs PCM with LP dispatch.

Equations and defaults: see CLAUDE.md. Units: kW, kWh, $; one step = 1 h. All defaults below are ASSUMED unless
noted; the UI lists them. Electricity price is ISO-NE wholesale LMP only (no retail adder).
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import linprog
from .materials import Material, get_material

DATA = Path(__file__).resolve().parent.parent / "data" / "boston_2024_hourly.csv"
PCM_PRICE_DEFAULT = {"Organic / paraffin-based": 5.0, "Inorganic / salt hydrate-based": 2.0}  # $/kg, placeholders


@dataclass(frozen=True)
class Params:
    it_mw: float = 1.0                # peak IT power; ESIF shape is scaled to it
    material: str = "rt35hc"
    graphite: bool = False            # Ritwik's HYPOTHETICAL 2x conductivity case
    thickness_m: float = 0.05
    panels_per_mw: float = 100.0      # 1 m² panels (Ritwik's Config default for ~1 MW)
    panel_area_m2: float = 1.0
    supply_c: float = 27.0            # loop temperatures from thermal.Config
    return_c: float = 37.0
    h_w_m2k: float = 150.0
    cop_ref: float = 6.0              # chiller COP at cop_ref_twb_c wet-bulb
    cop_ref_twb_c: float = 20.0
    cop_slope: float = 0.15           # COP lost per K of wet-bulb
    cop_min: float = 3.0
    economiser: bool = True
    approach_k: float = 4.0           # cooling tower approach to wet-bulb
    cop_free: float = 25.0            # free cooling: tower fans + pumps only
    demand_usd_per_kw_month: float = 15.0
    chiller_usd_per_kw: float = 250.0
    chiller_life_yr: int = 20
    pcm_usd_per_kg: float | None = None   # None -> category default
    pcm_life_yr: int = 15
    discount: float = 0.07


def load_year(path: Path = DATA) -> pd.DataFrame:
    return pd.read_csv(path, index_col=0, parse_dates=True)


def wet_bulb_c(t_c, rh_pct):
    """Stull (2011), valid ~5-99 % RH, -20..50 C, sea-level pressure."""
    t, rh = np.asarray(t_c, float), np.asarray(rh_pct, float)
    return (t * np.arctan(0.151977 * np.sqrt(rh + 8.313659)) + np.arctan(t + rh) - np.arctan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh) - 4.686035)


def crf(rate: float, years: int) -> float:
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


def cooling_factor(twb, p: Params):
    """kW electric per kW thermal removed, and the free-cooling fraction f (1 = tower alone)."""
    cop_ch = np.maximum(p.cop_min, p.cop_ref - p.cop_slope * (twb - p.cop_ref_twb_c))
    f = np.clip((p.return_c - p.approach_k - twb) / (p.return_c - p.supply_c), 0, 1) if p.economiser else np.zeros_like(twb)
    return f / p.cop_free + (1 - f) / cop_ch, f


def pcm_limits(m: Material, p: Params) -> dict:
    area = p.panels_per_mw * p.it_mw * p.panel_area_m2
    mass = m.density_kg_m3 * area * p.thickness_m
    e_max = mass * (m.latent_heat_j_kg + m.heat_capacity_j_kg_k * (p.return_c - p.supply_c)) / 3.6e6
    ua = area / (1 / p.h_w_m2k + (p.thickness_m / 2) / m.conductivity_w_m_k) / 1000  # kW/K, mean melt-front depth
    t_melt = (m.melt_low_c + m.melt_high_c) / 2
    return dict(area_m2=area, mass_kg=mass, e_max_kwh=e_max,
                p_charge_kw=ua * max(0.0, p.return_c - t_melt), p_regen_kw=ua * max(0.0, t_melt - p.supply_c))


def _dispatch(q, k, f, price, month, lim, p: Params):
    """LP for PCM net heat s[t] (kW_th, + = absorbing) and stored energy E[t]. Zeros if the PCM cannot act."""
    T = len(q)
    if lim["e_max_kwh"] <= 0 or lim["p_charge_kw"] + lim["p_regen_kw"] <= 0:
        return np.zeros(T), np.zeros(T)
    nm = 12
    iS, iE, iD, iC = 0, T, 2 * T, 2 * T + nm
    n = iC + 1
    cost = np.zeros(n)
    cost[iS:iE] = -price * k                      # energy cost change per kW absorbed
    cost[iD:iC] = p.demand_usd_per_kw_month
    cost[iC] = p.chiller_usd_per_kw * crf(p.discount, p.chiller_life_yr)
    t = np.arange(T)
    # E[t+1] - E[t] - s[t] = 0, cyclic
    A_eq = sparse.csr_matrix((np.r_[np.ones(T), -np.ones(T), -np.ones(T)],
                              (np.r_[t, t, t], np.r_[iE + (t + 1) % T, iE + t, iS + t])), shape=(T, n))
    # demand: -k s - D_m <= -(P_IT + k q) ; chiller: -(1-f) s - C <= -(1-f) q
    A_ub = sparse.vstack([
        sparse.csr_matrix((np.r_[-k, -np.ones(T)], (np.r_[t, t], np.r_[iS + t, iD + month])), shape=(T, n)),
        sparse.csr_matrix((np.r_[-(1 - f), -np.ones(T)], (np.r_[t, t], np.r_[iS + t, np.full(T, iC)])), shape=(T, n)),
    ]).tocsr()
    b_ub = np.r_[-(q + k * q), -(1 - f) * q]       # P_IT = Q_IT
    bounds = ([(-lim["p_regen_kw"], min(lim["p_charge_kw"], qi)) for qi in q]
              + [(0, lim["e_max_kwh"])] * T + [(0, None)] * (nm + 1))
    r = linprog(cost, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=np.zeros(T), bounds=bounds, method="highs")
    if r.status != 0:
        raise RuntimeError(f"LP failed: {r.message}")
    return r.x[iS:iE], r.x[iE:iD]


def _costs(q_c, p_grid, k_f, f, price, month, p: Params) -> dict:
    demand = sum(p_grid[month == m].max() for m in range(12)) * p.demand_usd_per_kw_month
    chiller_kw = float(((1 - f) * q_c).max())
    return dict(energy_usd=float((price * p_grid).sum()), demand_usd=float(demand), chiller_kw=chiller_kw,
                chiller_usd=chiller_kw * p.chiller_usd_per_kw * crf(p.discount, p.chiller_life_yr),
                cooling_kwh=float((k_f * q_c).sum()), peak_grid_kw=float(p_grid.max()))


def run(df: pd.DataFrame, p: Params) -> dict:
    m = get_material(p.material, p.graphite)
    q = df.it_kw_esif.to_numpy() / df.it_kw_esif.max() * p.it_mw * 1000   # Q_IT = P_IT, kW
    twb = wet_bulb_c(df.temp_c, df.rh_pct)
    k, f = cooling_factor(twb, p)
    price = df.price_usd_per_kwh.to_numpy()
    month = (df.index.tz_convert("Etc/GMT+5").month - 1).to_numpy()   # local standard time months
    lim = pcm_limits(m, p)
    s, e = _dispatch(q, k, f, price, month, lim, p)
    q_pcm = q - s
    hourly = pd.DataFrame(dict(q_it_kw=q, twb_c=twb, free_frac=f, kwe_per_kwth=k, price=price, pcm_kw=s, pcm_kwh=e,
                               chiller_base_kw=(1 - f) * q, chiller_pcm_kw=(1 - f) * q_pcm,
                               grid_base_kw=q + k * q, grid_pcm_kw=q + k * q_pcm), index=df.index)
    base = _costs(q, hourly.grid_base_kw.to_numpy(), k, f, price, month, p)
    pcm = _costs(q_pcm, hourly.grid_pcm_kw.to_numpy(), k, f, price, month, p)
    for c in (base, pcm):
        c["total_usd"] = c["energy_usd"] + c["demand_usd"] + c["chiller_usd"]
    price_kg = p.pcm_usd_per_kg if p.pcm_usd_per_kg is not None else PCM_PRICE_DEFAULT[m.category]
    capex = lim["mass_kg"] * price_kg
    opex_saving = (base["energy_usd"] + base["demand_usd"]) - (pcm["energy_usd"] + pcm["demand_usd"])
    chiller_avoided_usd = (base["chiller_kw"] - pcm["chiller_kw"]) * p.chiller_usd_per_kw
    net_upfront = capex - chiller_avoided_usd
    pv = opex_saving / crf(p.discount, p.pcm_life_yr)
    it_kwh = q.sum()
    kpis = dict(
        material=m.name, category=m.category, pcm_usd_per_kg=price_kg, **lim, pcm_capex_usd=capex,
        base=base, pcm=pcm, saving_usd=base["total_usd"] - pcm["total_usd"],
        saving_pct=100 * (base["total_usd"] - pcm["total_usd"]) / base["total_usd"],
        opex_saving_usd=opex_saving, chiller_avoided_kw=base["chiller_kw"] - pcm["chiller_kw"],
        chiller_avoided_usd=chiller_avoided_usd,
        payback_yr=(0.0 if net_upfront <= 0 else net_upfront / opex_saving if opex_saving > 0 else None),
        breakeven_usd_per_kg=(pv + chiller_avoided_usd) / lim["mass_kg"] if lim["mass_kg"] > 0 else None,
        pue_base=(it_kwh + base["cooling_kwh"]) / it_kwh, pue_pcm=(it_kwh + pcm["cooling_kwh"]) / it_kwh,
        free_hours_full=int((f >= 1).sum()), free_hours_partial=int(((f > 0) & (f < 1)).sum()),
        it_filled_hours=int(df.it_filled.sum()),
    )
    return dict(kpis=kpis, hourly=hourly, params=asdict(p))


def hottest_week(hourly: pd.DataFrame) -> pd.DataFrame:
    i = int(hourly.twb_c.rolling(168).mean().to_numpy().argmax())
    return hourly.iloc[i - 167:i + 1]


def monthly_costs(hourly: pd.DataFrame, p: Params) -> pd.DataFrame:
    local = hourly.index - pd.Timedelta(hours=5)
    g = hourly.assign(m=local.month).groupby("m")
    out = pd.DataFrame({
        f"{x}_usd": g.apply(lambda d, x=x: (d.price * d[f"grid_{x}_kw"]).sum() + d[f"grid_{x}_kw"].max() * p.demand_usd_per_kw_month)
        for x in ("base", "pcm")})
    out.index.name = "month"
    return out


# Named starting points for the UI. Values come from a 192-run scan (see CLAUDE.md); nothing is tuned after the fact.
PRESETS = {
    "PCM showcase: chiller plant, salt hydrate, thin panels": dict(
        material="na2so4", economiser=False, panels_per_mw=500, thickness_m=0.02),
    "Boston as built: free cooling on, paraffin defaults": dict(),
}

"""Material property catalog.

SOURCES.md distinguishes measured values from assumed latent enthalpy and k.
Manufacturer *heat storage capacity over a temperature range* is NOT equal to
latent heat of fusion. In particular, no manufacturer total-storage quantity is
silently used as pure latent heat in the enthalpy solver.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Material:
    key: str
    category: str
    name: str
    density_kg_m3: float
    heat_capacity_j_kg_k: float
    conductivity_w_m_k: float
    latent_heat_j_kg: float
    melt_low_c: float
    melt_high_c: float
    source_url: str
    limitations: str


MATERIALS = {
    "rt35hc": Material(
        "rt35hc", "Organic / paraffin-based", "Rubitherm RT35HC",
        880.0, 2000.0, 0.20, 180_000.0, 34.0, 36.0,
        "https://www.rubitherm.com/media/products/datasheets/Techdata_-RT35HC_EN_09102020.PDF",
        "Latent heat set to 180 kJ/kg as an unvalidated placeholder. Datasheet reports "
        "240 kJ/kg total sensible+latent heat between 27 and 42 C, not latent heat alone.",
    ),
    "rt28hc": Material(
        "rt28hc", "Organic / paraffin-based", "Rubitherm RT28HC",
        880.0, 2000.0, 0.20, 190_000.0, 27.0, 29.0,
        "https://www.rubitherm.eu/media/products/datasheets/Techdata_-RT28HC_EN_09102020.PDF",
        "Latent heat set to 190 kJ/kg as an unvalidated placeholder. Datasheet "
        "reports 250 kJ/kg combined sensible+latent heat between 21 and 36 C.",
    ),
    "cacl2": Material(
        "cacl2", "Inorganic / salt hydrate-based", "Calcium chloride hexahydrate (CaCl2·6H2O)",
        1710.0, 2000.0, 0.54, 170_000.0, 28.4, 30.4,
        "https://ntrs.nasa.gov/api/citations/19720012306/downloads/19720012306.pdf",
        "NASA table supports melting point ~29.4 C and latent heat 170 kJ/kg; "
        "density, cp, conductivity and 2 C transition width are provisional assumptions. "
        "Supercooling and phase separation not simulated.",
    ),
    "na2so4": Material(
        "na2so4", "Inorganic / salt hydrate-based", "Sodium sulfate decahydrate (Na2SO4·10H2O)",
        1460.0, 1800.0, 0.50, 253_000.0, 31.4, 33.4,
        "https://ntrs.nasa.gov/api/citations/19720012306/downloads/19720012306.pdf",
        "NASA table supports melting point 32.4 C, latent heat 253 kJ/kg, "
        "density 1460 kg/m3. cp, conductivity and transition width assumed. "
        "Phase segregation/supercooling not simulated.",
    ),
}


def get_material(key: str, graphite: bool = False) -> Material:
    """Return material with an explicitly hypothetical nano-graphite variant.

    Factors are NOT transferable measured results. The enhancement switch is
    only for sensitivity testing until material-specific measurements are added.
    """
    base = MATERIALS[key]
    if not graphite:
        return base
    return replace(
        base,
        name=base.name + " + nano-graphite (hypothetical)",
        conductivity_w_m_k=base.conductivity_w_m_k * 2.0,
        latent_heat_j_kg=base.latent_heat_j_kg * 0.98,
        limitations=base.limitations + " Graphite case uses assumed 2x k, 0.98x latent heat; not validated for this material.",
    )

import math
import re

import altair as alt
import pandas as pd
import streamlit as st

SEC_PER_YEAR = 365.25 * 24 * 3600.0

# Airborne-chloride model constants (see notes at the bottom of this file)
CS_C1_DEFAULT = 0.6      # calibration constant of C_air = C1 * d^-n
CS_N_DEFAULT = 0.6       # distance decay exponent
CS_A_DEFAULT = 1.5       # airborne -> surface concentration conversion, factor
CS_B_DEFAULT = 0.4       # airborne -> surface concentration conversion, exponent

ELEMENT_TYPES = ["Reinforced", "Prestressed"]
CLASS_OPTIONS = ["Auto", "S1", "S2", "S3", "S4", "S5", "S6"]


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def sf(val, default=0.0):
    """Safe float conversion (blank / text / NaN -> default)."""
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def parse_grade(name):
    """'Custom: C32/40 Deck' -> (32, 40). Returns (None, None) if not a grade."""
    m = re.search(r"C\s*(\d{2,3})\s*/\s*(\d{2,3})", str(name), re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def inv_erf(y):
    """Inverse error function (no scipy dependency)."""
    if y <= -1.0:
        return -float("inf")
    if y >= 1.0:
        return float("inf")
    if y == 0.0:
        return 0.0
    a = 0.147
    ln1 = math.log(1.0 - y * y)
    t1 = 2.0 / (math.pi * a) + ln1 / 2.0
    inner = max(t1 * t1 - ln1 / a, 0.0)
    x = math.copysign(math.sqrt(max(math.sqrt(inner) - t1, 0.0)), y)
    for _ in range(60):
        err = math.erf(x) - y
        d = 2.0 / math.sqrt(math.pi) * math.exp(-x * x)
        if d == 0:
            break
        step = err / d
        x -= step
        if abs(step) < 1e-14:
            break
    return x


# ----------------------------------------------------------------------------
# EN 1992-1-1 structural class and minimum durability cover
# ----------------------------------------------------------------------------
# Column groups used by Tables 4.3N / 4.4N / 4.5N
_EXP_COL = {"X0": 0, "XC1": 1, "XC2": 2, "XC3": 2, "XC4": 3,
            "XD1": 4, "XS1": 4, "XD2": 5, "XS2": 5, "XD3": 6, "XS3": 6}

# Table 4.4N - cmin,dur for reinforcing steel (mm), rows S1..S6
_COVER_RC = {
    1: [10, 10, 10, 15, 20, 25, 30],
    2: [10, 10, 15, 20, 25, 30, 35],
    3: [10, 10, 20, 25, 30, 35, 40],
    4: [10, 15, 25, 30, 35, 40, 45],
    5: [15, 20, 30, 35, 40, 45, 50],
    6: [20, 25, 35, 40, 45, 50, 55],
}
# Table 4.5N - cmin,dur for prestressing steel = Table 4.4N + 10 mm
_COVER_PS = {s: [v + 10 for v in row] for s, row in _COVER_RC.items()}

# Table 4.3N - strength class at or above which the structural class drops by 1
_STRENGTH_REDUCTION = {"X0": 30, "XC1": 30, "XC2": 35, "XC3": 35, "XC4": 40,
                       "XD1": 40, "XS1": 40, "XD2": 40, "XS2": 45,
                       "XD3": 45, "XS3": 45}


def structural_class(exposure_class, fck_cyl, tsl_years, slab_geometry=False,
                     special_qc=False):
    """
    EN 1992-1-1 cl. 4.4.1.2(5) / Table 4.3N.
    Base class S4 (50-year design life), then:
      +2  design life of 100 years
      -1  strength class at or above the Table 4.3N threshold
      -1  member with slab geometry
      -1  special quality control of the concrete production ensured
    """
    s = 4
    if sf(tsl_years, 50) >= 100:
        s += 2
    thr = _STRENGTH_REDUCTION.get(str(exposure_class).upper())
    if thr is not None and sf(fck_cyl) >= thr:
        s -= 1
    if slab_geometry:
        s -= 1
    if special_qc:
        s -= 1
    return max(1, min(6, s))


def cmin_dur(exposure_class, s_class, element_type="Reinforced"):
    """Minimum durability cover from EN 1992-1-1 Table 4.4N / 4.5N (mm)."""
    col = _EXP_COL.get(str(exposure_class).upper())
    if col is None:
        return 0.0
    table = _COVER_PS if str(element_type).lower().startswith("pre") else _COVER_RC
    try:
        s = int(str(s_class).replace("S", ""))
    except (ValueError, TypeError):
        s = 4
    return float(table.get(max(1, min(6, s)), table[4])[col])


# ----------------------------------------------------------------------------
# reference data (Google Sheet tabs, with built-in fallbacks)
# ----------------------------------------------------------------------------
def _fallback_strength_table():
    d = {20: 5, 21: 5, 22: 5, 23: 5, 24: 5, 25: 5, 26: 5, 27: 6, 28: 6,
         29: 7, 30: 7, 31: 8, 32: 8, 33: 9, 34: 9}
    for f in range(35, 52):
        d[f] = 10
    d[52] = 11; d[53] = 11; d[54] = 12; d[55] = 12
    d[56] = 13; d[57] = 13; d[58] = 14; d[59] = 14
    rows = []
    for fck in range(20, 221):
        cube = fck + d.get(fck, 15)
        rows.append({"Grade": f"C{fck}/{cube}", "fck_cyl_MPa": fck,
                     "fck_cube_MPa": cube, "fcm_cyl_MPa": fck + 8,
                     "fcm_cube_MPa": cube + 8})
    return pd.DataFrame(rows)


FALLBACK_EXPOSURE = pd.DataFrame([
    ("XC1", "Carbonation", "Dry or permanently wet", "CARBONATION"),
    ("XC2", "Carbonation", "Wet, rarely dry", "CARBONATION"),
    ("XC3", "Carbonation", "Moderate humidity (sheltered from rain)", "CARBONATION"),
    ("XC4", "Carbonation", "Cyclic wet and dry (exposed to rain)", "CARBONATION"),
    ("XD1", "De-icing Cl-", "Moderate humidity, airborne chlorides (not sea water)", "CHLORIDE"),
    ("XD2", "De-icing Cl-", "Wet, rarely dry", "CHLORIDE"),
    ("XD3", "De-icing Cl-", "Cyclic wet and dry (de-icing spray, bridge decks)", "CHLORIDE"),
    ("XS1", "Marine Cl-", "Airborne salt, no direct contact with sea water", "CHLORIDE"),
    ("XS2", "Marine Cl-", "Permanently submerged in sea water", "CHLORIDE"),
    ("XS3", "Marine Cl-", "Tidal, splash and spray zones", "CHLORIDE"),
], columns=["Class", "Group", "Description", "Mechanism"])

FALLBACK_K1 = pd.DataFrame([
    ("Coastal", 0.90, "Literature value"),
    ("Rural", 1.00, "Reference / baseline"),
    ("Suburban", 1.30, "Literature value"),
    ("Urban", 1.40, "Literature value"),
    ("Internal", 2.00, "Enclosed environment"),
    ("Kuala Lumpur city centre (2019)", 1.06, "436 ppm / 410 ppm = 1.06"),
], columns=["Location_Type", "k1_default", "Note"])

FALLBACK_K400_DEFAULTS = pd.DataFrame([
    ("C140/155", "UHPC", 0.50, "Adopted design value for UHPC"),
    ("C70/85", "HSC", 2.00, "Adopted; vertical web elements critical"),
    ("C32/40", "NSC", 3.00, "Typical C32/40 literature value at 400 ppm, sheltered"),
    ("C40/50", "NSC", 3.00, "Assumed as C32/40"),
], columns=["Grade", "Concrete_Type", "k400_default", "Note"])

FALLBACK_DC = pd.DataFrame([
    ("C32/40", 10.0, "NSC case study"),
    ("C40/50", 6.0, "NSC case study"),
    ("C70/85", 4.5, "HSC case study"),
    ("C140/155", 0.1, "UHPC, NF P 18-470"),
], columns=["Grade", "Dc_x1e6_mm2_s", "Source"])

FALLBACK_BINDER_MAP = pd.DataFrame([
    ("CEMENT", "OP Cement"), ("CEMENT", "OPC"), ("CEMENT", "CEM I"),
    ("CEMENT", "Portland Cement"), ("CEMENT", "Cement"),
    ("ADDITIVE", "Fly Ash"), ("ADDITIVE", "PFA"), ("ADDITIVE", "Silica Fume"),
    ("ADDITIVE", "Microsilica"),
], columns=["Role", "Component_Keyword"])


def get_refs(db):
    """Pull the reference tabs out of the loaded database, with fallbacks."""
    def pick(key, fallback):
        v = db.get(key) if isinstance(db, dict) else None
        if isinstance(v, pd.DataFrame) and not v.empty:
            return v
        return fallback

    return {
        "strength": pick("strength_classes", _fallback_strength_table()),
        "k400_lit": pick("carbonation_k400", pd.DataFrame()),
        "k400_def": pick("carbonation_k400_defaults", FALLBACK_K400_DEFAULTS),
        "k1": pick("location_k1", FALLBACK_K1),
        "exposure": pick("exposure_classes", FALLBACK_EXPOSURE),
        "dc": pick("chloride_dc", FALLBACK_DC),
        "binder_map": pick("binder_mapping", FALLBACK_BINDER_MAP),
    }


def get_strength(material_name, refs, grade_override=None):
    """Return fck,cyl / fck,cube / fcm,cyl / fcm,cube for a material name or grade."""
    grade = grade_override if grade_override else material_name
    tbl = refs["strength"]
    out = {"Grade": "", "fck_cyl": 0.0, "fck_cube": 0.0, "fcm_cyl": 0.0, "fcm_cube": 0.0}

    fck, cube = parse_grade(grade)
    if fck is None:
        return out

    out["Grade"] = f"C{fck}/{cube}"
    if isinstance(tbl, pd.DataFrame) and "fck_cyl_MPa" in tbl.columns:
        hit = tbl[tbl["fck_cyl_MPa"].apply(sf) == float(fck)]
        if not hit.empty:
            r = hit.iloc[0]
            out.update({"fck_cyl": sf(r.get("fck_cyl_MPa")),
                        "fck_cube": sf(r.get("fck_cube_MPa")),
                        "fcm_cyl": sf(r.get("fcm_cyl_MPa")),
                        "fcm_cube": sf(r.get("fcm_cube_MPa"))})
            return out
    out.update({"fck_cyl": float(fck), "fck_cube": float(cube),
                "fcm_cyl": float(fck) + 8.0, "fcm_cube": float(cube) + 8.0})
    return out


# ----------------------------------------------------------------------------
# binder content auto-fill
# ----------------------------------------------------------------------------
def _role_of(component_name, binder_map):
    n = str(component_name).strip().lower()
    if not n:
        return None
    for role in ("ADDITIVE", "CEMENT"):
        kws = binder_map[binder_map["Role"].astype(str).str.upper() == role]
        for kw in kws["Component_Keyword"].astype(str):
            if kw.strip().lower() and kw.strip().lower() in n:
                return role
    return None


def autofill_binder(material_name, db, user_mixes, factors_df, refs):
    """Returns (cement_kg_m3, additive_kg_m3, found)."""
    bmap = refs["binder_map"]
    cement, additive, found = 0.0, 0.0, False

    if str(material_name).startswith("Custom: "):
        mix_n = str(material_name).replace("Custom: ", "")
        match = next((m for m in user_mixes if m.get("mix_name") == mix_n), None)
        if match:
            for c_name, c_val in (match.get("components") or {}).items():
                role = _role_of(c_name, bmap)
                if role == "CEMENT":
                    cement += sf(c_val); found = True
                elif role == "ADDITIVE":
                    additive += sf(c_val); found = True
            for adhoc in (match.get("adhoc_materials") or []):
                role = _role_of(adhoc.get("Material Name", ""), bmap)
                if role == "CEMENT":
                    cement += sf(adhoc.get("Quantity")); found = True
                elif role == "ADDITIVE":
                    additive += sf(adhoc.get("Quantity")); found = True
        return cement, additive, found

    mixes = db.get("mixes", pd.DataFrame())
    if isinstance(mixes, pd.DataFrame) and not mixes.empty and "Mix_Key" in mixes.columns:
        hit = mixes[mixes["Mix_Key"].astype(str).str.strip() == str(material_name).strip()]
        if not hit.empty:
            row = hit.iloc[0]
            if "Cement_Content_kg_m3" in row.index and pd.notna(row.get("Cement_Content_kg_m3")):
                cement = sf(row.get("Cement_Content_kg_m3")); found = True
            if "Additive_Content_kg_m3" in row.index and pd.notna(row.get("Additive_Content_kg_m3")):
                additive = sf(row.get("Additive_Content_kg_m3")); found = True
            if found:
                return cement, additive, True
            for comp in (factors_df.index if isinstance(factors_df, pd.DataFrame) else []):
                if comp in row.index and pd.notna(row[comp]):
                    role = _role_of(comp, bmap)
                    if role == "CEMENT":
                        cement += sf(row[comp]); found = True
                    elif role == "ADDITIVE":
                        additive += sf(row[comp]); found = True
            return cement, additive, found

    direct = db.get("direct", pd.DataFrame())
    if isinstance(direct, pd.DataFrame) and not direct.empty and "Material_Key" in direct.columns:
        hit = direct[direct["Material_Key"].astype(str).str.strip() == str(material_name).strip()]
        if not hit.empty:
            row = hit.iloc[0]
            if "Cement_Content_kg_m3" in row.index and pd.notna(row.get("Cement_Content_kg_m3")):
                cement = sf(row.get("Cement_Content_kg_m3")); found = True
            if "Additive_Content_kg_m3" in row.index and pd.notna(row.get("Additive_Content_kg_m3")):
                additive = sf(row.get("Additive_Content_kg_m3")); found = True

    return cement, additive, found


# ----------------------------------------------------------------------------
# k400 / Dc auto-fill
# ----------------------------------------------------------------------------
def _nearest_by_grade(table, grade_col, value_col, grade_label, fck):
    exact = table[table[grade_col].astype(str).str.strip().str.upper()
                  == str(grade_label).strip().upper()]
    if not exact.empty:
        return sf(exact.iloc[0][value_col]), "database"
    tmp = table.copy()
    tmp["_f"] = tmp[grade_col].apply(lambda g: parse_grade(g)[0] or 0)
    tmp["_d"] = (tmp["_f"] - sf(fck)).abs()
    tmp = tmp.sort_values("_d")
    if tmp.empty:
        return 0.0, "not found"
    return sf(tmp.iloc[0][value_col]), f"est. from {tmp.iloc[0][grade_col]}"


def default_k400(grade_label, fck_cyl, fcm_cyl, refs):
    """
    Adopted design k400,l.  The Carbonation_k400_Defaults tab is authoritative;
    the literature tab is only consulted when that tab does not know the grade.
    """
    d = refs["k400_def"]
    if isinstance(d, pd.DataFrame) and not d.empty and "k400_default" in d.columns:
        val, src = _nearest_by_grade(d, "Grade", "k400_default", grade_label, fck_cyl)
        if src != "not found":
            return round(val, 3), src
    lit = refs["k400_lit"]
    if isinstance(lit, pd.DataFrame) and not lit.empty and "k400" in lit.columns:
        tmp = lit.copy()
        if "fcm_cyl_MPa" in tmp.columns:
            tmp["_d"] = (tmp["fcm_cyl_MPa"].apply(sf) - sf(fcm_cyl)).abs()
            tmp = tmp.sort_values("_d").head(8)
        vals = sorted(sf(v) for v in tmp["k400"].tolist())
        if vals:
            n = len(vals)
            med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
            return round(med, 3), "literature median"
    return 0.0, "not found"


def default_dc(grade_label, fck_cyl, refs):
    d = refs["dc"]
    if not isinstance(d, pd.DataFrame) or d.empty:
        return 0.0, "not found"
    return _nearest_by_grade(d, "Grade", "Dc_x1e6_mm2_s", grade_label, fck_cyl)


# ----------------------------------------------------------------------------
# core physics
# ----------------------------------------------------------------------------
def carbonation_coefficient(k400, k1, k2):
    """k = k400,l * sqrt(k1 * k2)   [mm/year^0.5]"""
    return sf(k400) * math.sqrt(max(sf(k1) * sf(k2), 0.0))


def carbonation_life(cover_mm, k):
    """Xc(t) = k*sqrt(t)  ->  t = (X/k)^2  [years]."""
    if sf(k) <= 0:
        return float("inf")
    return (sf(cover_mm) / sf(k)) ** 2


def cs_air_from_distance(d_km, c1=CS_C1_DEFAULT, n=CS_N_DEFAULT,
                         a=CS_A_DEFAULT, b=CS_B_DEFAULT):
    """
    Surface chloride concentration from distance to the coastline [kg/m3].
        C_air = c1 * d^-n            (airborne salt, d in km)
        Cs    = a * (C_air)^b        (airborne -> concrete surface)
    Defaults reproduce Cs(d=0.001 km)=6.417 and Cs(d=10 km)=0.704 kg/m3.
    """
    d = max(sf(d_km), 1e-6)
    return a * ((c1 * (d ** (-n))) ** b)


def chloride_life(cover_mm, dc_e6, cx, cs):
    """Returns (t_years, erf_Y, Y, status)."""
    cs = sf(cs); cx = sf(cx)
    if cs <= 0:
        return float("nan"), float("nan"), float("nan"), "NO_CS"
    if cx >= cs:
        return float("inf"), 0.0, float("inf"), "NOT_CRITICAL"
    erf_y = 1.0 - cx / cs
    y = inv_erf(erf_y)
    da = sf(dc_e6) * 1e-6
    if da <= 0 or y <= 0 or math.isinf(y):
        return float("inf"), erf_y, y, "NOT_CRITICAL"
    return (sf(cover_mm) ** 2) / (4.0 * da * y * y) / SEC_PER_YEAR, erf_y, y, "OK"


def csepp(fck, tsl, eic_tonne):
    """CSEPP = fck * tsl / EIC   [MPa.yr / tonne CO2e]"""
    if sf(eic_tonne) <= 0:
        return float("nan")
    return sf(fck) * sf(tsl) / sf(eic_tonne)


# ----------------------------------------------------------------------------
# project grouping and EIC allocation
# ----------------------------------------------------------------------------
def group_component_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon):
    """One row per COMPONENT x MATERIAL pair, with Volume / Mass / GWP / EIC."""
    if results_df is None or not isinstance(results_df, pd.DataFrame) or results_df.empty:
        return pd.DataFrame()

    df = results_df.copy()
    if "Component" not in df.columns:
        df["Component"] = df.get("Item", "").astype(str).str.replace(
            r"^\s*\d+\.\s*", "", regex=True)

    agg = {"Total Mass (kg)": "sum", "Total GWP100 (kgCO2e)": "sum"}
    if "Total Volume (m³)" in df.columns:
        agg["Total Volume (m³)"] = "sum"
    g = df.groupby(["Component", "Material"], as_index=False).agg(agg)

    rows = []
    for _, r in g.iterrows():
        name = r["Material"]
        props = calc_mix_carbon(name, db, user_mixes, factors_df)
        density = sf(props.get("Mass (kg/m3)"), 0.0)
        mass = sf(r["Total Mass (kg)"])
        gwp = sf(r["Total GWP100 (kgCO2e)"])
        vol = sf(r.get("Total Volume (m³)")) if "Total Volume (m³)" in g.columns else 0.0
        if vol <= 0:
            vol = (mass / density) if density > 0 else 0.0
        rows.append({
            "Component": r["Component"], "Material": name,
            "Density (kg/m³)": density, "Volume (m³)": vol, "Mass (kg)": mass,
            "GWP100 (kgCO2e)": gwp, "EIC (tonne CO2e)": gwp / 1000.0,
            "Is Concrete": parse_grade(name)[0] is not None,
        })
    return (pd.DataFrame(rows).sort_values(["Component", "Material"])
            .reset_index(drop=True))


def group_project_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon):
    """One row per distinct material (roll-up)."""
    cm = group_component_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon)
    if cm.empty:
        return pd.DataFrame()
    g = (cm.groupby("Material", as_index=False)
         .agg({"Density (kg/m³)": "first", "Volume (m³)": "sum", "Mass (kg)": "sum",
               "GWP100 (kgCO2e)": "sum", "EIC (tonne CO2e)": "sum",
               "Is Concrete": "first"}))
    return g.sort_values("GWP100 (kgCO2e)", ascending=False).reset_index(drop=True)


def allocate_component_eic(cm_all, concrete_materials):
    """
    Charge every ancillary material in a component (strands, rebars, diesel...)
    to the concrete of that component.
    """
    rows = []
    for comp, g in cm_all.groupby("Component", sort=False):
        conc = g[g["Material"].isin(concrete_materials)]
        anc = g[~g["Material"].isin(concrete_materials)]
        anc_eic = sf(anc["EIC (tonne CO2e)"].sum())
        anc_names = ", ".join(anc["Material"].astype(str).tolist())
        tot_vol = sf(conc["Volume (m³)"].sum())
        n = len(conc)
        for _, c in conc.iterrows():
            share = (sf(c["Volume (m³)"]) / tot_vol) if tot_vol > 0 else (1.0 / n if n else 0.0)
            rows.append({
                "Component": comp, "Material": c["Material"],
                "Volume (m³)": sf(c["Volume (m³)"]),
                "Concrete EIC (tCO2e)": sf(c["EIC (tonne CO2e)"]),
                "Ancillary EIC (tCO2e)": anc_eic * share,
                "EIC (tonne CO2e)": sf(c["EIC (tonne CO2e)"]) + anc_eic * share,
                "Ancillary items": anc_names if anc_names else "-",
            })
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# input-table construction
# ----------------------------------------------------------------------------
def build_input_table(alloc_df, mechanism, exposure_class, db, user_mixes,
                      factors_df, refs, tsl_default, dcdev, special_qc):
    cache = {}
    rows = []
    for _, m in alloc_df.iterrows():
        name = m["Material"]
        if name not in cache:
            s = get_strength(name, refs)
            cem, add, found = autofill_binder(name, db, user_mixes, factors_df, refs)
            k400, k_src = default_k400(s["Grade"], s["fck_cyl"], s["fcm_cyl"], refs)
            dcv, d_src = default_dc(s["Grade"], s["fck_cyl"], refs)
            cache[name] = (s, cem, add, found, k400, k_src, dcv, d_src)
        s, cem, add, found, k400, k_src, dcv, d_src = cache[name]

        s_cls = structural_class(exposure_class, s["fck_cyl"], tsl_default, False, special_qc)
        cmin = cmin_dur(exposure_class, s_cls, "Reinforced")

        base = {
            "Component": m["Component"],
            "Material": name,
            "Grade": s["Grade"],
            "fck,cyl (MPa)": s["fck_cyl"],
            "fcm,cube (MPa)": s["fcm_cube"],
            "Element type": "Reinforced",
            "Slab geometry": False,
            "Structural Class": "Auto",
            "Class used": f"S{s_cls}",
            "Cement (kg/m³)": cem if found else None,
            "Additive (kg/m³)": add if found else None,
            "Binder (kg/m³)": (cem + add) if found else None,
            "cmin,dur (mm)": cmin,
            "Cover X (mm)": cmin + sf(dcdev, 10.0),
            "Used tsl (yr)": float(tsl_default),
        }
        if mechanism == "CARBONATION":
            base["k400,l (mm/yr^0.5)"] = k400
            base["k400 source"] = k_src
        else:
            base["CTL (% of binder)"] = 0.40
            base["Dc (×10⁻⁶ mm²/s)"] = dcv
            base["Dc source"] = d_src
        rows.append(base)

    df = pd.DataFrame(rows)
    order = ["Component", "Material", "Grade", "fck,cyl (MPa)", "fcm,cube (MPa)",
             "Element type", "Slab geometry", "Structural Class", "Class used",
             "Cement (kg/m³)", "Additive (kg/m³)", "Binder (kg/m³)"]
    order += (["k400,l (mm/yr^0.5)", "k400 source"] if mechanism == "CARBONATION"
              else ["CTL (% of binder)", "Dc (×10⁻⁶ mm²/s)", "Dc source"])
    order += ["cmin,dur (mm)", "Cover X (mm)", "Used tsl (yr)"]
    return df[[c for c in order if c in df.columns]]


def refresh_derived(df, exposure_class, dcdev, special_qc):
    """Recompute binder, structural class and cmin,dur after the user edits."""
    d = df.copy()
    d["Binder (kg/m³)"] = d["Cement (kg/m³)"].apply(sf) + d["Additive (kg/m³)"].apply(sf)
    classes, cmins = [], []
    for _, r in d.iterrows():
        manual = str(r.get("Structural Class", "Auto"))
        if manual.upper().startswith("S"):
            s_cls = int(manual.replace("S", ""))
        else:
            s_cls = structural_class(exposure_class, r.get("fck,cyl (MPa)"),
                                     r.get("Used tsl (yr)"),
                                     bool(r.get("Slab geometry", False)), special_qc)
        classes.append(f"S{s_cls}")
        cmins.append(cmin_dur(exposure_class, s_cls, r.get("Element type", "Reinforced")))
    d["Class used"] = classes
    d["cmin,dur (mm)"] = cmins
    return d


# ----------------------------------------------------------------------------
# calculation
# ----------------------------------------------------------------------------
def _pick(alloc, component, material, col):
    hit = alloc[(alloc["Component"] == component) & (alloc["Material"] == material)]
    return sf(hit[col].sum()) if not hit.empty else 0.0


def run_carbonation(edited, alloc, k1, k2):
    out = []
    for _, r in edited.iterrows():
        cem, add = sf(r.get("Cement (kg/m³)")), sf(r.get("Additive (kg/m³)"))
        cover = sf(r.get("Cover X (mm)"))
        k = carbonation_coefficient(r.get("k400,l (mm/yr^0.5)"), k1, k2)
        t_calc = carbonation_life(cover, k)
        t_used = sf(r.get("Used tsl (yr)"), 100.0)
        ok = (cover > 0) and (t_calc >= t_used)
        out.append({
            "Component": r["Component"], "Material": r["Material"],
            "Grade": r.get("Grade", ""), "fck (MPa)": sf(r.get("fck,cyl (MPa)")),
            "Class": r.get("Class used", ""),
            "Binder (kg/m³)": cem + add,
            "k400,l": sf(r.get("k400,l (mm/yr^0.5)")),
            "k (mm/yr^0.5)": k,
            "cmin,dur (mm)": sf(r.get("cmin,dur (mm)")),
            "Cover X (mm)": cover,
            "Calculated tsl,S (yr)": t_calc,
            "Used tsl (yr)": t_used,
            "Durability Check": "PASS" if ok else "FAIL",
            "Volume (m³)": _pick(alloc, r["Component"], r["Material"], "Volume (m³)"),
            "Concrete EIC (tCO2e)": _pick(alloc, r["Component"], r["Material"], "Concrete EIC (tCO2e)"),
            "Ancillary EIC (tCO2e)": _pick(alloc, r["Component"], r["Material"], "Ancillary EIC (tCO2e)"),
            "EIC (tonne CO2e)": _pick(alloc, r["Component"], r["Material"], "EIC (tonne CO2e)"),
        })
    return pd.DataFrame(out)


def run_chloride(edited, alloc, cs):
    out = []
    for _, r in edited.iterrows():
        binder = sf(r.get("Cement (kg/m³)")) + sf(r.get("Additive (kg/m³)"))
        cx = sf(r.get("CTL (% of binder)")) / 100.0 * binder
        cover = sf(r.get("Cover X (mm)"))
        t_calc, erf_y, y, status = chloride_life(cover, r.get("Dc (×10⁻⁶ mm²/s)"), cx, cs)
        t_used = sf(r.get("Used tsl (yr)"), 100.0)
        ok = (cover > 0) and (t_calc >= t_used)
        out.append({
            "Component": r["Component"], "Material": r["Material"],
            "Grade": r.get("Grade", ""), "fck (MPa)": sf(r.get("fck,cyl (MPa)")),
            "Class": r.get("Class used", ""),
            "Binder (kg/m³)": binder,
            "CTL (%)": sf(r.get("CTL (% of binder)")),
            "Cx (kg/m³)": cx, "Cs,air (kg/m³)": sf(cs),
            "erf(Y)": erf_y, "Y": y,
            "Dc (×10⁻⁶ mm²/s)": sf(r.get("Dc (×10⁻⁶ mm²/s)")),
            "cmin,dur (mm)": sf(r.get("cmin,dur (mm)")),
            "Cover X (mm)": cover,
            "Calculated tsl,S (yr)": t_calc,
            "Used tsl (yr)": t_used,
            "Status": "Cl- not critical" if status == "NOT_CRITICAL"
                      else ("No Cs given" if status == "NO_CS" else "Cl- governs"),
            "Durability Check": "PASS" if ok else "FAIL",
            "Volume (m³)": _pick(alloc, r["Component"], r["Material"], "Volume (m³)"),
            "Concrete EIC (tCO2e)": _pick(alloc, r["Component"], r["Material"], "Concrete EIC (tCO2e)"),
            "Ancillary EIC (tCO2e)": _pick(alloc, r["Component"], r["Material"], "Ancillary EIC (tCO2e)"),
            "EIC (tonne CO2e)": _pick(alloc, r["Component"], r["Material"], "EIC (tonne CO2e)"),
        })
    return pd.DataFrame(out)


def material_summary(detail_df):
    """Roll the component-level check up to material level and compute CSEPP."""
    rows = []
    for mat, g in detail_df.groupby("Material", sort=False):
        t_used = sf(g["Used tsl (yr)"].min(), 100.0)
        eic = sf(g["EIC (tonne CO2e)"].sum())
        fck = sf(g["fck (MPa)"].iloc[0])
        all_pass = bool((g["Durability Check"] == "PASS").all())
        rows.append({
            "Material": mat, "Grade": g["Grade"].iloc[0], "fck (MPa)": fck,
            "Components": ", ".join(g["Component"].astype(str).tolist()),
            "Volume (m³)": sf(g["Volume (m³)"].sum()),
            "Concrete EIC (tCO2e)": sf(g["Concrete EIC (tCO2e)"].sum()),
            "Ancillary EIC (tCO2e)": sf(g["Ancillary EIC (tCO2e)"].sum()),
            "EIC (tonne CO2e)": eic,
            "Governing tsl,S (yr)": g["Calculated tsl,S (yr)"].min(),
            "Used tsl (yr)": t_used,
            "Durability Check": "PASS" if all_pass else "FAIL",
            "CSEPP (MPa·yr/tCO2e)": csepp(fck, t_used, eic) if all_pass else float("nan"),
        })
    return pd.DataFrame(rows)


def structure_summary(mat_res_df):
    valid = mat_res_df[mat_res_df["Durability Check"] == "PASS"]
    tot_eic = sf(mat_res_df["EIC (tonne CO2e)"].sum())
    tot_vol = sf(mat_res_df["Volume (m³)"].sum())
    w_fck = (sf((mat_res_df["fck (MPa)"] * mat_res_df["Volume (m³)"]).sum()) / tot_vol) \
        if tot_vol > 0 else 0.0
    tsl_min = sf(mat_res_df["Used tsl (yr)"].min()) if not mat_res_df.empty else 0.0
    return {
        "n_materials": int(len(mat_res_df)), "n_pass": int(len(valid)),
        "all_pass": bool(len(valid) == len(mat_res_df)) and len(mat_res_df) > 0,
        "total_volume": tot_vol, "total_eic": tot_eic,
        "concrete_eic": sf(mat_res_df["Concrete EIC (tCO2e)"].sum()),
        "ancillary_eic": sf(mat_res_df["Ancillary EIC (tCO2e)"].sum()),
        "sum_csepp": sf(valid["CSEPP (MPa·yr/tCO2e)"].sum()),
        "weighted_fck": w_fck,
        "structure_csepp": (w_fck * tsl_min / tot_eic) if tot_eic > 0 else float("nan"),
        "governing_tsl": tsl_min,
    }


# ----------------------------------------------------------------------------
# table rendering (1-based index, highlighted result columns)
# ----------------------------------------------------------------------------
PRECISE_COLS = {"erf(Y)", "Y", "k (mm/yr^0.5)", "k400,l", "Cx (kg/m³)",
                "Cs,air (kg/m³)", "Dc (×10⁻⁶ mm²/s)", "CSEPP (MPa·yr/tCO2e)",
                "Concrete EIC (tCO2e)", "Ancillary EIC (tCO2e)", "EIC (tonne CO2e)"}


def _numfmt(nd):
    def f(x):
        if isinstance(x, str):
            return x
        if x is None:
            return "-"
        try:
            v = float(x)
        except (TypeError, ValueError):
            return str(x)
        if math.isnan(v):
            return "-"
        if math.isinf(v):
            return "∞"
        return f"{v:,.{nd}f}"
    return f


def show_table(df, highlight=()):
    """Static table, index starting at 1, with the result columns highlighted."""
    d = df.copy().reset_index(drop=True)
    d.index = d.index + 1
    fmt = {c: _numfmt(3 if c in PRECISE_COLS else 2)
           for c in d.columns if d[c].dtype.kind in "fci"}
    sty = d.style.format(fmt)
    hl = [c for c in highlight if c in d.columns]
    if hl:
        sty = sty.set_properties(subset=hl, **{
            "background-color": "#FEF9E7", "font-weight": "bold", "color": "#000"})
    if "Durability Check" in d.columns:
        sty = sty.apply(
            lambda s: ["background-color:#d4edda;color:#155724;font-weight:bold"
                       if str(v) == "PASS"
                       else "background-color:#f8d7da;color:#721c24;font-weight:bold"
                       for v in s], subset=["Durability Check"])
    st.table(sty)


# ----------------------------------------------------------------------------
# main page
# ----------------------------------------------------------------------------
def _clear_page_state():
    for k in ("sl_detail", "sl_materials", "sl_table", "sl_sig", "sl_alloc",
              "sl_exposure_class", "sl_project_label", "sl_project_id"):
        st.session_state[k] = None


def render_service_life_page(supabase, db, user_mixes, factors_df,
                             calc_mix_carbon, calculate_project_data):
    refs = get_refs(db)

    if st.session_state.get("sl_saved_flash"):
        st.success(st.session_state.sl_saved_flash)
        st.session_state.sl_saved_flash = None

    st.markdown("#### 1. Select the assessed structure")
    src = st.radio("Data source:", ["Saved Project", "Current Project Assessment"],
                   horizontal=True, key="sl_source")

    results_df, proj_label, proj_id = None, "", None

    if src == "Current Project Assessment":
        results_df = st.session_state.get("project_results_df")
        proj_label = st.session_state.get("draft_proj_name") or "(unsaved project)"
        if results_df is None:
            st.info("Nothing to assess yet. Open **Project Assessment**, assign materials "
                    "and press **Calculate Project Totals** first — or switch the selector "
                    "above to **Saved Project**.")
            return
    else:
        try:
            res = supabase.table("saved_projects").select("*") \
                .eq("user_id", st.session_state.user_id).execute()
            projects = res.data or []
        except Exception:
            projects = []
        if not projects:
            st.info("No saved projects on your account yet.")
            return
        names = list(dict.fromkeys([p["project_name"] for p in projects if p.get("project_name")]))
        pick = st.selectbox("Saved project:", ["--- Select a project ---"] + names,
                            key="sl_saved_proj")
        if pick == "--- Select a project ---":
            st.info("Select a project from the dropdown above to load its materials and start "
                    "the service life assessment.")
            return
        p = next((x for x in projects if x["project_name"] == pick), None)
        if not p:
            return
        proj_label, proj_id = p["project_name"], p.get("id")
        results_df, _, _ = calculate_project_data(rebuild_draft(p), db, user_mixes, factors_df)
        if results_df is None:
            st.error("This project has no calculable materials.")
            return

    cm_all = group_component_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon)
    if cm_all.empty:
        st.error("Could not group the project materials.")
        return

    st.markdown(f"**{proj_label}** — {cm_all['Material'].nunique()} material(s) across "
                f"{cm_all['Component'].nunique()} component(s):")
    show_table(cm_all.drop(columns=["Is Concrete"]))

    concrete_default = sorted(cm_all[cm_all["Is Concrete"]]["Material"].unique().tolist())
    chosen = st.multiselect(
        "Which materials are the concrete to be assessed?",
        sorted(cm_all["Material"].unique().tolist()), default=concrete_default,
        key="sl_concrete_pick",
        help="Everything NOT selected here (strands, rebars, diesel, ...) is treated as an "
             "ancillary material and its carbon is charged to the concrete of the same "
             "component, because the component only functions as a complete assembly.")
    if not chosen:
        st.info("Select at least one concrete material to continue.")
        return

    alloc = allocate_component_eic(cm_all, chosen)
    if alloc.empty:
        st.error("No concrete rows to assess.")
        return

    with st.expander("How the EIC of each component is made up"):
        show_table(alloc)

    # ---------------------------------------------------------------- exposure
    st.markdown("---")
    st.markdown("#### 2. Exposure environment and cover rules")
    exp = refs["exposure"]
    exp_labels = [f"{r['Class']} — {r['Description']}" for _, r in exp.iterrows()]
    default_idx = next((i for i, r in enumerate(exp.to_dict("records"))
                        if str(r.get("Class")) == "XS1"), 0)
    e_col1, e_col2 = st.columns([2, 1])
    with e_col1:
        pick_exp = st.selectbox("Exposure class (EN 206 / EN 1992-1-1):",
                                exp_labels, index=default_idx, key="sl_exposure")
    e_row = exp.iloc[exp_labels.index(pick_exp)]
    exposure_class = str(e_row["Class"]).upper()
    mechanism = str(e_row["Mechanism"]).upper()
    with e_col2:
        st.metric("Deterioration model",
                  "Carbonation" if mechanism == "CARBONATION"
                  else ("Chloride" if mechanism == "CHLORIDE" else "Not modelled"))
    if mechanism not in ("CARBONATION", "CHLORIDE"):
        st.warning("This exposure class is not a reinforcement-corrosion class. "
                   "Pick an XC / XD / XS class.")
        return

    g1, g2, g3 = st.columns(3)
    with g1:
        tsl_default = st.number_input("Used Design Life, tsl (years):", min_value=1.0,
                                      value=100.0, step=5.0, key="sl_tsl_default")
    with g2:
        dcdev = st.number_input("Allowance Δcdev (mm):", min_value=0.0, value=10.0,
                                step=5.0, key="sl_dcdev",
                                help="EN 1992-1-1 cl. 4.4.1.3. Suggested cover = cmin,dur + Δcdev.")
    with g3:
        special_qc = st.checkbox("Special quality control assured", value=False, key="sl_qc",
                                 help="EN 1992-1-1 Table 4.3N — reduces the structural class by 1.")

    k1_val, k2_val, cs_val = 1.0, 1.4, 0.0
    if mechanism == "CARBONATION":
        k1tab = refs["k1"]
        c1, c2, c3 = st.columns(3)
        with c1:
            loc = st.selectbox("Location type (suggests k1):",
                               k1tab["Location_Type"].astype(str).tolist(), key="sl_loc")
            k1_suggest = sf(k1tab[k1tab["Location_Type"].astype(str) == loc]["k1_default"].iloc[0], 1.0)
        with c2:
            k1_val = st.number_input("k1 (local CO₂ factor):", min_value=0.01,
                                     value=float(k1_suggest), step=0.01,
                                     format="%.2f", key=f"sl_k1_{loc}")
        with c3:
            k2_val = st.number_input("k2 (future CO₂ increase):", min_value=0.01,
                                     value=1.40, step=0.05, format="%.2f", key="sl_k2")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            d_km = st.number_input("Distance from coastline, d (km):", min_value=0.001,
                                   max_value=10.0, value=0.001, step=0.001, format="%.3f",
                                   key="sl_dkm",
                                   help="0.001 km = 1 m from the shore (most severe).")
        cs_calc = cs_air_from_distance(d_km)
        with c2:
            cs_val = st.number_input("Surface chloride, Cs,air (kg/m³):", min_value=0.0,
                                     value=float(round(cs_calc, 3)), step=0.1,
                                     format="%.3f", key=f"sl_cs_{d_km}")
        with c3:
            st.metric("Model value at this d", f"{cs_calc:,.3f} kg/m³")

    # ---------------------------------------------------------------- inputs
    st.markdown("---")
    st.markdown("#### 3. Confirm properties — one row per component × material")
    st.caption("Type freely — nothing recalculates until you press the button under the "
               "table, so keystrokes are never dropped. Blank cells could not be auto-filled; "
               "please type them in. Structural Class 'Auto' applies EN 1992-1-1 Table 4.3N; "
               "override it by picking S1–S6. Cover is pre-filled with cmin,dur + Δcdev — "
               "raise it where bond governs (e.g. a tendon duct).")

    sig = "|".join([str(proj_label), mechanism, exposure_class, ",".join(sorted(chosen)),
                    str(len(alloc)), f"{tsl_default:.0f}", f"{dcdev:.0f}", str(special_qc)])
    if st.session_state.get("sl_sig") != sig or st.session_state.get("sl_table") is None:
        st.session_state.sl_table = build_input_table(
            alloc, mechanism, exposure_class, db, user_mixes, factors_df, refs,
            tsl_default, dcdev, special_qc)
        st.session_state.sl_sig = sig

    cfg = {
        "Component": st.column_config.TextColumn(disabled=True, width="medium"),
        "Material": st.column_config.TextColumn(disabled=True, width="medium"),
        "Grade": st.column_config.TextColumn(disabled=True, width="small"),
        "fck,cyl (MPa)": st.column_config.NumberColumn(format="%.0f"),
        "fcm,cube (MPa)": st.column_config.NumberColumn(format="%.0f"),
        "Element type": st.column_config.SelectboxColumn(options=ELEMENT_TYPES),
        "Slab geometry": st.column_config.CheckboxColumn(
            help="Member whose reinforcement position is not affected by the construction "
                 "process (slabs). Reduces the structural class by 1."),
        "Structural Class": st.column_config.SelectboxColumn(options=CLASS_OPTIONS),
        "Class used": st.column_config.TextColumn(disabled=True, width="small"),
        "Binder (kg/m³)": st.column_config.NumberColumn(
            "Total Binder (kg/m³)", disabled=True, format="%.1f",
            help="Automatically = Cement + Additive"),
        "cmin,dur (mm)": st.column_config.NumberColumn(
            disabled=True, format="%.0f",
            help="EN 1992-1-1 Table 4.4N / 4.5N minimum durability cover."),
        "Cover X (mm)": st.column_config.NumberColumn(
            format="%.0f",
            help="Cover actually used. Bond requirements (e.g. tendon duct diameter) may "
                 "govern and are NOT automated — override this cell when they do."),
        "k400 source": st.column_config.TextColumn(disabled=True),
        "Dc source": st.column_config.TextColumn(disabled=True),
    }

    with st.form(key=f"sl_form_{sig}"):
        edited = st.data_editor(st.session_state.sl_table, use_container_width=True,
                                hide_index=True, column_config=cfg,
                                key=f"sl_editor_{sig}")
        submitted = st.form_submit_button("Apply & Calculate Service Life",
                                          use_container_width=True, type="primary")

    if submitted:
        edited = refresh_derived(edited, exposure_class, dcdev, special_qc)
        st.session_state.sl_table = edited
        st.session_state.sl_alloc = alloc
        st.session_state.sl_detail = (run_carbonation(edited, alloc, k1_val, k2_val)
                                      if mechanism == "CARBONATION"
                                      else run_chloride(edited, alloc, cs_val))
        st.session_state.sl_materials = material_summary(st.session_state.sl_detail)
        st.session_state.sl_mechanism = mechanism
        st.session_state.sl_exposure_class = exposure_class
        st.session_state.sl_project_label = proj_label
        st.session_state.sl_project_id = proj_id
        st.rerun()

    detail = st.session_state.get("sl_detail")
    mat_res = st.session_state.get("sl_materials")
    if detail is None or mat_res is None or detail.empty or mat_res.empty:
        return

    # ---------------------------------------------------------------- results
    st.markdown("#### 4. Durability check — per component")
    st.caption("The highlighted columns are the result of the calculation; everything to "
               "their left is the input you confirmed above.")
    show_table(detail, highlight=["k (mm/yr^0.5)", "Cx (kg/m³)", "erf(Y)", "Y",
                                  "Calculated tsl,S (yr)", "Durability Check"])

    for _, f in detail[detail["Durability Check"] == "FAIL"].iterrows():
        calc = f["Calculated tsl,S (yr)"]
        calc_txt = "∞" if (isinstance(calc, float) and math.isinf(calc)) else f"{sf(calc):,.1f}"
        if sf(f["Cover X (mm)"]) <= 0:
            st.error(f"**{f['Component']} — {f['Material']}**: no cover entered.")
        else:
            st.error(
                f"**{f['Component']} — {f['Material']} FAILS the durability gate.** "
                f"Calculated tsl,S = {calc_txt} years is shorter than the Used Design Life "
                f"tsl = {sf(f['Used tsl (yr)']):,.0f} years. CSEPP is withheld: crediting more "
                f"years than the cover and the mix can deliver would reward a design that needs "
                f"repair before that date, and the comparison would no longer sit on the same "
                f"functional basis. Increase the cover, lower k400,l / Dc, or reduce the Used "
                f"Design Life, then recalculate.")

    if "Status" in detail.columns:
        for _, r in detail[detail["Status"] == "Cl- not critical"].iterrows():
            st.info(f"**{r['Component']} — {r['Material']}**: Cx "
                    f"({sf(r['Cx (kg/m³)']):.3f} kg/m³) exceeds Cs,air "
                    f"({sf(r['Cs,air (kg/m³)']):.3f} kg/m³), so the threshold can never be "
                    f"reached — chloride corrosion is not critical for this mix here.")

    st.markdown("#### 5. CSEPP — per material")
    st.caption("EIC = the concrete's own GWP100 plus the GWP100 of every ancillary material in "
               "the same component (strands, rebars, diesel and so on), because the component "
               "only functions as a complete assembly.")
    show_table(mat_res, highlight=["EIC (tonne CO2e)", "Governing tsl,S (yr)",
                                   "Durability Check", "CSEPP (MPa·yr/tCO2e)"])

    summ = structure_summary(mat_res)

    st.markdown("#### 6. Structure-level CSEPP")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Concrete volume", f"{summ['total_volume']:,.2f} m³")
    s2.metric("Total EIC", f"{summ['total_eic']:,.3f} tCO2e",
              help=f"Concrete {summ['concrete_eic']:,.3f} + ancillary "
                   f"{summ['ancillary_eic']:,.3f} tCO2e")
    s3.metric("Σ CSEPP (sum of materials)", f"{summ['sum_csepp']:,.2f}")
    s4.metric("Structure CSEPP (volume-weighted)",
              f"{summ['structure_csepp']:,.2f}" if not math.isnan(summ["structure_csepp"]) else "-")

    st.markdown(f"""
    <div style="border:1px solid #d3d3d3;border-radius:6px;padding:16px;background:#f9f9f9;
                color:#000;font-family:sans-serif;font-size:14px;line-height:1.6;">
      <b>How to read the two figures</b><br>
      Both use an EIC that already includes the ancillary materials
      ({summ['concrete_eic']:,.3f} tCO2e of concrete + {summ['ancillary_eic']:,.3f} tCO2e of
      strands, rebars, diesel and the like), so they price the complete component rather than
      the concrete alone.<br><br>
      <b>Σ CSEPP = {summ['sum_csepp']:,.2f} MPa·yr/tCO2e</b> — the plain sum of every
      material's fck·tsl/EIC. It answers "how much strength-service does each mix buy per tonne
      of CO₂e", and it grows simply because there are more materials, so compare it only
      between structures with a similar make-up.<br>
      <b>Structure CSEPP =
      {("%.2f" % summ['structure_csepp']) if not math.isnan(summ['structure_csepp']) else "-"}
      MPa·yr/tCO2e</b> — volume-weighted mean fck ({summ['weighted_fck']:,.1f} MPa) ×
      governing tsl ({summ['governing_tsl']:,.0f} yr) ÷ total EIC. It treats the structure as
      one equivalent material, so it stays valid when two designs differ in size or in the
      number of mixes. Use this as the headline metric when benchmarking one bridge against
      another; report Σ CSEPP alongside as the per-material breakdown.<br>
      Higher is better for both. {summ['n_pass']} of {summ['n_materials']} materials passed the
      durability gate.
    </div>
    """, unsafe_allow_html=True)

    if not summ["all_pass"]:
        st.warning("At least one material failed the durability gate, so the figures above are "
                   "incomplete — the failed material still contributes EIC to the denominator "
                   "but no credited service life. Fix those rows before quoting these numbers.")

    if summ["n_pass"] > 0:
        chart_df = mat_res[mat_res["Durability Check"] == "PASS"][
            ["Material", "CSEPP (MPa·yr/tCO2e)"]]
        st.altair_chart(alt.Chart(chart_df).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("CSEPP (MPa·yr/tCO2e):Q", title="CSEPP (MPa·yr / tonne CO2e)"),
            y=alt.Y("Material:N", sort="-x", title=""),
            tooltip=["Material", "CSEPP (MPa·yr/tCO2e)"]
        ).properties(height=alt.Step(45)), use_container_width=True)

    c_dl1, c_dl2 = st.columns(2)
    c_dl1.download_button("📄 Download component detail (CSV)",
                          data=detail.to_csv(index=False).encode("utf-8"),
                          file_name=f"service_life_detail_{proj_label}.csv",
                          mime="text/csv", use_container_width=True)
    c_dl2.download_button("📄 Download material CSEPP (CSV)",
                          data=mat_res.to_csv(index=False).encode("utf-8"),
                          file_name=f"csepp_{proj_label}.csv",
                          mime="text/csv", use_container_width=True)

    # ------------------------------------------------------------ persistence
    st.markdown("---")
    if proj_id:
        st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
        if st.button("Save", key="sl_save"):
            payload = {"service_life_data": {
                "exposure_class": exposure_class, "mechanism": mechanism,
                "k1": k1_val, "k2": k2_val, "cs_air": cs_val, "dcdev": dcdev,
                "special_qc": bool(special_qc),
                "inputs": edited.fillna(0).to_dict("records"),
                "detail": detail.replace([float("inf")], 1e12).fillna(0).to_dict("records"),
                "materials": mat_res.replace([float("inf")], 1e12).fillna(0).to_dict("records"),
                "summary": summ,
            }}
            try:
                supabase.table("saved_projects").update(payload).eq("id", proj_id).execute()
                st.session_state.sl_saved_flash = (
                    f"Service life results for '{proj_label}' saved. The page has been cleared "
                    f"— select a project to start a new assessment.")
                _clear_page_state()
                st.rerun()
            except Exception as e:
                st.error(f"Could not save. Add a `service_life_data` (jsonb) column to the "
                         f"`saved_projects` table in Supabase. Details: {e}")
    else:
        st.caption("Save the project first (Project Assessment → Save Project) if you want to "
                   "store these results and use them in Project Comparison.")


# ----------------------------------------------------------------------------
# shared utility used by comparison.py
# ----------------------------------------------------------------------------
def rebuild_draft(p):
    """Rebuild the draft_components structure from a saved Supabase project row."""
    draft, raw = [], (p.get("component_data") or [])
    if isinstance(raw, dict):
        raw = [{"component_name": k, "multiplier_count": 1,
                "materials": [{"label": "", "quantity": v.get("quantity", 0.0),
                               "unit": v.get("unit", "m3"),
                               "ref_value": v.get("ref_value", 0.0),
                               "ref_per_unit": v.get("ref_per_unit", False),
                               "assigned_mix": v.get("assigned_mix", "")}]}
               for k, v in raw.items()]
    for comp in raw:
        draft.append({
            "base_name": comp.get("base_name", "Extra"),
            "custom_name": comp.get("component_name", ""),
            "count": comp.get("multiplier_count", 1),
            "materials": [{"label": m.get("label", ""), "qty": m.get("quantity", 0.0),
                           "unit": m.get("unit", "m3"), "ref_value": m.get("ref_value", 0.0),
                           "ref_per_unit": m.get("ref_per_unit", False),
                           "mix": m.get("assigned_mix", "")} for m in comp.get("materials", [])]})
    return draft

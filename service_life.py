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

K400_STRATEGIES = ["Most conservative (max)", "Median", "Least conservative (min)"]


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
    for _ in range(60):                      # Newton polish
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

FALLBACK_CTL = pd.DataFrame([
    (11, None, 0.40, "Reinforced concrete", "EN 206:2016", 2016),
    (12, None, 0.20, "Prestressed concrete", "EN 206:2016", 2016),
    (13, None, 0.40, "Reinforced concrete with CEM III", "EN 206:2016", 2016),
    (14, None, 0.65, "Reinforced concrete with CEM III (France)", "EN 206:2016", 2016),
    (15, None, 1.00, "Unreinforced concrete", "EN 206:2016", 2016),
    (1, 0.10, None, "Prestressed concrete", "BS 8110", 1985),
    (2, 0.20, None, "RC exposed to chloride in service", "BS 8110", 1985),
    (3, 0.40, None, "RC dry or protected from moisture", "BS 8110", 1985),
], columns=["No", "CTL_pct_cement", "CTL_pct_binder", "Condition", "Standard", "Year"])

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
    """Pull the new reference tabs out of the loaded database, with fallbacks."""
    def pick(key, fallback):
        v = db.get(key) if isinstance(db, dict) else None
        if isinstance(v, pd.DataFrame) and not v.empty:
            return v
        return fallback

    return {
        "strength": pick("strength_classes", _fallback_strength_table()),
        "k400": pick("carbonation_k400", pd.DataFrame()),
        "k1": pick("location_k1", FALLBACK_K1),
        "exposure": pick("exposure_classes", FALLBACK_EXPOSURE),
        "ctl": pick("chloride_ctl", FALLBACK_CTL),
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
    # ADDITIVE is tested first so that e.g. "GGBS cement" is not read as cement
    for role in ("ADDITIVE", "CEMENT"):
        kws = binder_map[binder_map["Role"].astype(str).str.upper() == role]
        for kw in kws["Component_Keyword"].astype(str):
            if kw.strip().lower() and kw.strip().lower() in n:
                return role
    return None


def autofill_binder(material_name, db, user_mixes, factors_df, refs):
    """
    Returns (cement_kg_m3, additive_kg_m3, found).
    found=False means we could not derive it -> the field is left blank for the user.
    """
    bmap = refs["binder_map"]
    cement, additive, found = 0.0, 0.0, False

    # 1. custom user mixes
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

    # 2. standard mixes (Mix_Designs)
    mixes = db.get("mixes", pd.DataFrame())
    if isinstance(mixes, pd.DataFrame) and not mixes.empty and "Mix_Key" in mixes.columns:
        hit = mixes[mixes["Mix_Key"].astype(str).str.strip() == str(material_name).strip()]
        if not hit.empty:
            row = hit.iloc[0]
            # explicit override columns win
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

    # 3. direct materials (Direct_Results) - only explicit columns
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
# k400 / Dc suggestions
# ----------------------------------------------------------------------------
def suggest_k400(grade_label, fcm_cyl, refs, top=12):
    """Literature entries sorted by closeness (exact grade first, then |d fcm|)."""
    k = refs["k400"]
    if not isinstance(k, pd.DataFrame) or k.empty or "k400" not in k.columns:
        return pd.DataFrame()
    d = k.copy()
    if "Concrete_Grade" in d.columns:
        d["_grade_match"] = (d["Concrete_Grade"].astype(str).str.strip().str.upper()
                             == str(grade_label).strip().upper()).astype(int)
    else:
        d["_grade_match"] = 0
    if "fcm_cyl_MPa" in d.columns:
        d["_dfcm"] = (d["fcm_cyl_MPa"].apply(sf) - sf(fcm_cyl)).abs()
    else:
        d["_dfcm"] = 0.0
    d = d.sort_values(["_grade_match", "_dfcm"], ascending=[False, True])
    return d.head(top).drop(columns=["_grade_match", "_dfcm"], errors="ignore")


def default_k400(grade_label, fcm_cyl, refs, strategy="Most conservative (max)"):
    """
    Auto-fill value of k400,l from the closest literature entries.

    Default strategy is the MAXIMUM of the matched set: the fastest carbonation
    rate, hence the shortest calculated design life -> the conservative choice.
    """
    s = suggest_k400(grade_label, fcm_cyl, refs, top=8)
    if s.empty:
        return 0.0
    vals = sorted(sf(v) for v in s["k400"].tolist())
    if not vals:
        return 0.0
    if strategy.startswith("Median"):
        n = len(vals)
        val = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
    elif strategy.startswith("Least"):
        val = vals[0]
    else:
        val = vals[-1]
    return round(val, 3)


def default_dc(grade_label, fck_cyl, refs):
    """(value, exact?) chloride diffusion coefficient in x10^-6 mm2/s."""
    d = refs["dc"]
    if not isinstance(d, pd.DataFrame) or d.empty:
        return 0.0, False
    exact = d[d["Grade"].astype(str).str.strip().str.upper() == str(grade_label).strip().upper()]
    if not exact.empty:
        return sf(exact.iloc[0]["Dc_x1e6_mm2_s"]), True
    tmp = d.copy()
    tmp["_f"] = tmp["Grade"].apply(lambda g: parse_grade(g)[0] or 0)
    tmp["_d"] = (tmp["_f"] - sf(fck_cyl)).abs()
    tmp = tmp.sort_values("_d")
    if tmp.empty:
        return 0.0, False
    return sf(tmp.iloc[0]["Dc_x1e6_mm2_s"]), False


# ----------------------------------------------------------------------------
# core physics
# ----------------------------------------------------------------------------
def carbonation_coefficient(k400, k1, k2):
    """k = k400,l * sqrt(k1 * k2)   [mm/year^0.5]"""
    return sf(k400) * math.sqrt(max(sf(k1) * sf(k2), 0.0))


def carbonation_life(cover_mm, k):
    """Xc(t) = k*sqrt(t)  ->  t = (X/k)^2  [years]. k=0 -> no carbonation."""
    if sf(k) <= 0:
        return float("inf")
    return (sf(cover_mm) / sf(k)) ** 2


def cs_air_from_distance(d_km, c1=CS_C1_DEFAULT, n=CS_N_DEFAULT,
                         a=CS_A_DEFAULT, b=CS_B_DEFAULT):
    """
    Surface chloride concentration from distance to the coastline [kg/m3].
        C_air = c1 * d^-n            (airborne salt, d in km)
        Cs    = a * (C_air)^b        (airborne -> concrete surface)
    Defaults reproduce Cs(d=0.001 km) = 6.417 and Cs(d=10 km) = 0.704 kg/m3.
    """
    d = max(sf(d_km), 1e-6)
    c_air = c1 * (d ** (-n))
    return a * (c_air ** b)


def chloride_life(cover_mm, dc_e6, cx, cs):
    """
    Returns (t_years, erf_Y, Y, status)
    C(x,t) = Cs [1 - erf(x / sqrt(4 Dc t))]  ->  t = X^2 / (4*Da*Y^2)
    """
    cs = sf(cs); cx = sf(cx)
    if cs <= 0:
        return float("nan"), float("nan"), float("nan"), "NO_CS"
    if cx >= cs:
        return float("inf"), 0.0, float("inf"), "NOT_CRITICAL"
    erf_y = 1.0 - cx / cs
    y = inv_erf(erf_y)
    da = sf(dc_e6) * 1e-6                     # mm2/s
    if da <= 0 or y <= 0 or math.isinf(y):
        return float("inf"), erf_y, y, "NOT_CRITICAL"
    t_sec = (sf(cover_mm) ** 2) / (4.0 * da * y * y)
    return t_sec / SEC_PER_YEAR, erf_y, y, "OK"


def csepp(fck, tsl, eic_tonne):
    """CSEPP = fck * tsl / EIC   [MPa.yr / tonne CO2e]"""
    if sf(eic_tonne) <= 0:
        return float("nan")
    return sf(fck) * sf(tsl) / sf(eic_tonne)


# ----------------------------------------------------------------------------
# project grouping
# ----------------------------------------------------------------------------
def group_component_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon):
    """
    One row per COMPONENT x MATERIAL pair, with Volume / Mass / GWP / EIC.
    This is the granularity at which concrete cover is entered.
    """
    if results_df is None or not isinstance(results_df, pd.DataFrame) or results_df.empty:
        return pd.DataFrame()

    df = results_df.copy()
    if "Component" not in df.columns:
        # legacy results: recover the component name from the "Item" label
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
            "Component": r["Component"],
            "Material": name,
            "Density (kg/m³)": density,
            "Volume (m³)": vol,
            "Mass (kg)": mass,
            "GWP100 (kgCO2e)": gwp,
            "EIC (tonne CO2e)": gwp / 1000.0,
            "Is Concrete": parse_grade(name)[0] is not None,
        })
    return (pd.DataFrame(rows)
            .sort_values(["Material", "Component"])
            .reset_index(drop=True))


def group_project_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon):
    """One row per distinct material (roll-up of group_component_materials)."""
    cm = group_component_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon)
    if cm.empty:
        return pd.DataFrame()
    g = (cm.groupby("Material", as_index=False)
         .agg({"Density (kg/m³)": "first", "Volume (m³)": "sum", "Mass (kg)": "sum",
               "GWP100 (kgCO2e)": "sum", "EIC (tonne CO2e)": "sum",
               "Is Concrete": "first"}))
    return g.sort_values("GWP100 (kgCO2e)", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------------------
# input-table construction
# ----------------------------------------------------------------------------
def build_input_table(cm_df, mechanism, db, user_mixes, factors_df, refs,
                      k1_default, k2_default, tsl_default, cs_default, k400_strategy):
    """Build the editable Component x Material input grid."""
    cache = {}
    rows = []
    for _, m in cm_df.iterrows():
        name = m["Material"]
        if name not in cache:
            s = get_strength(name, refs)
            cem, add, found = autofill_binder(name, db, user_mixes, factors_df, refs)
            k400 = default_k400(s["Grade"], s["fcm_cyl"], refs, k400_strategy)
            dcv, exact = default_dc(s["Grade"], s["fck_cyl"], refs)
            cache[name] = (s, cem, add, found, k400, dcv, exact)
        s, cem, add, found, k400, dcv, exact = cache[name]

        base = {
            "Component": m["Component"],
            "Material": name,
            "Grade": s["Grade"],
            "fck,cyl (MPa)": s["fck_cyl"],
            "fcm,cube (MPa)": s["fcm_cube"],
            "Cement (kg/m³)": cem if found else None,
            "Additive (kg/m³)": add if found else None,
            "Binder (kg/m³)": (cem + add) if found else None,
            "Used tsl (yr)": float(tsl_default),
        }
        if mechanism == "CARBONATION":
            base.update({
                "k400,l (mm/yr^0.5)": k400,
                "k1": float(k1_default),
                "k2": float(k2_default),
                "Cover X (mm)": 0.0,
            })
        else:
            base.update({
                "CTL (%)": 0.40,
                "CTL basis": "binder",
                "Cs,air (kg/m³)": float(cs_default),
                "Cover X (mm)": 0.0,
                "Dc (×10⁻⁶ mm²/s)": dcv,
                "Dc source": "database" if exact else "estimated",
            })
        rows.append(base)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# calculation
# ----------------------------------------------------------------------------
def _lookup(cm_df, component, material, col):
    hit = cm_df[(cm_df["Component"] == component) & (cm_df["Material"] == material)]
    return sf(hit[col].sum()) if not hit.empty else 0.0


def run_carbonation(edited, cm_df):
    out = []
    for _, r in edited.iterrows():
        cem = sf(r.get("Cement (kg/m³)"))
        add = sf(r.get("Additive (kg/m³)"))
        cover = sf(r.get("Cover X (mm)"))
        k = carbonation_coefficient(r.get("k400,l (mm/yr^0.5)"), r.get("k1"), r.get("k2"))
        t_calc = carbonation_life(cover, k)
        t_used = sf(r.get("Used tsl (yr)"), 100.0)
        ok = (cover > 0) and (t_calc >= t_used)
        out.append({
            "Component": r["Component"], "Material": r["Material"],
            "Grade": r.get("Grade", ""), "fck (MPa)": sf(r.get("fck,cyl (MPa)")),
            "Cement (kg/m³)": cem, "Additive (kg/m³)": add,
            "Total Binder (kg/m³)": cem + add,
            "k400,l": sf(r.get("k400,l (mm/yr^0.5)")),
            "k1": sf(r.get("k1")), "k2": sf(r.get("k2")),
            "k (mm/yr^0.5)": k,
            "Cover X (mm)": cover,
            "Calculated tsl,S (yr)": t_calc,
            "Used tsl (yr)": t_used,
            "Durability Check": "PASS" if ok else "FAIL",
            "Volume (m³)": _lookup(cm_df, r["Component"], r["Material"], "Volume (m³)"),
            "EIC (tonne CO2e)": _lookup(cm_df, r["Component"], r["Material"], "EIC (tonne CO2e)"),
        })
    return pd.DataFrame(out)


def run_chloride(edited, cm_df):
    out = []
    for _, r in edited.iterrows():
        cem = sf(r.get("Cement (kg/m³)"))
        add = sf(r.get("Additive (kg/m³)"))
        binder = cem + add
        basis_val = cem if str(r.get("CTL basis", "binder")).lower().startswith("cem") else binder
        cx = sf(r.get("CTL (%)")) / 100.0 * basis_val
        cs = sf(r.get("Cs,air (kg/m³)"))
        cover = sf(r.get("Cover X (mm)"))
        t_calc, erf_y, y, status = chloride_life(cover, r.get("Dc (×10⁻⁶ mm²/s)"), cx, cs)
        t_used = sf(r.get("Used tsl (yr)"), 100.0)
        ok = (cover > 0) and (t_calc >= t_used)
        out.append({
            "Component": r["Component"], "Material": r["Material"],
            "Grade": r.get("Grade", ""), "fck (MPa)": sf(r.get("fck,cyl (MPa)")),
            "Total Binder (kg/m³)": binder,
            "CTL (%)": sf(r.get("CTL (%)")),
            "Cx (kg/m³)": cx, "Cs,air (kg/m³)": cs,
            "erf(Y)": erf_y, "Y": y,
            "Dc (×10⁻⁶ mm²/s)": sf(r.get("Dc (×10⁻⁶ mm²/s)")),
            "Cover X (mm)": cover,
            "Calculated tsl,S (yr)": t_calc,
            "Used tsl (yr)": t_used,
            "Status": "Chloride NOT critical (Cx > Cs)" if status == "NOT_CRITICAL"
                      else ("No Cs given" if status == "NO_CS" else "Chloride governs"),
            "Durability Check": "PASS" if ok else "FAIL",
            "Volume (m³)": _lookup(cm_df, r["Component"], r["Material"], "Volume (m³)"),
            "EIC (tonne CO2e)": _lookup(cm_df, r["Component"], r["Material"], "EIC (tonne CO2e)"),
        })
    return pd.DataFrame(out)


def material_summary(detail_df):
    """
    Roll the component-level durability check up to material level and compute CSEPP.
    A material only passes if EVERY component that uses it passes; the governing
    calculated design life is the shortest of that material's components.
    """
    rows = []
    for mat, g in detail_df.groupby("Material", sort=False):
        gov_calc = g["Calculated tsl,S (yr)"].min()
        t_used = sf(g["Used tsl (yr)"].min(), 100.0)
        eic = sf(g["EIC (tonne CO2e)"].sum())
        vol = sf(g["Volume (m³)"].sum())
        fck = sf(g["fck (MPa)"].iloc[0])
        all_pass = bool((g["Durability Check"] == "PASS").all())
        rows.append({
            "Material": mat,
            "Grade": g["Grade"].iloc[0],
            "fck (MPa)": fck,
            "Components": ", ".join(g["Component"].astype(str).tolist()),
            "Governing tsl,S (yr)": gov_calc,
            "Used tsl (yr)": t_used,
            "Durability Check": "PASS" if all_pass else "FAIL",
            "Volume (m³)": vol,
            "EIC (tonne CO2e)": eic,
            "CSEPP (MPa·yr/tCO2e)": csepp(fck, t_used, eic) if all_pass else float("nan"),
        })
    return pd.DataFrame(rows)


def structure_summary(mat_res_df):
    """Both structure-level roll-ups of CSEPP."""
    valid = mat_res_df[mat_res_df["Durability Check"] == "PASS"]
    tot_eic = sf(mat_res_df["EIC (tonne CO2e)"].sum())
    tot_vol = sf(mat_res_df["Volume (m³)"].sum())
    w_fck = (sf((mat_res_df["fck (MPa)"] * mat_res_df["Volume (m³)"]).sum()) / tot_vol) \
        if tot_vol > 0 else 0.0
    tsl_min = sf(mat_res_df["Used tsl (yr)"].min()) if not mat_res_df.empty else 0.0
    return {
        "n_materials": int(len(mat_res_df)),
        "n_pass": int(len(valid)),
        "all_pass": bool(len(valid) == len(mat_res_df)) and len(mat_res_df) > 0,
        "total_volume": tot_vol,
        "total_eic": tot_eic,
        "sum_csepp": sf(valid["CSEPP (MPa·yr/tCO2e)"].sum()),
        "weighted_fck": w_fck,
        "structure_csepp": (w_fck * tsl_min / tot_eic) if tot_eic > 0 else float("nan"),
        "governing_tsl": tsl_min,
    }


# ----------------------------------------------------------------------------
# UI helpers
# ----------------------------------------------------------------------------
def _fmt(df, cols3=(), cols2=()):
    d = df.copy()

    def f(x, nd):
        if isinstance(x, float) and math.isinf(x):
            return "∞"
        if pd.isna(x):
            return "-"
        return f"{float(x):,.{nd}f}"

    for c in cols2:
        if c in d.columns:
            d[c] = d[c].apply(lambda x: f(x, 2))
    for c in cols3:
        if c in d.columns:
            d[c] = d[c].apply(lambda x: f(x, 3))
    return d


PRECISE_COLS = ["erf(Y)", "Y", "k (mm/yr^0.5)", "k400,l", "k1", "k2",
                "Cx (kg/m³)", "Cs,air (kg/m³)", "Dc (×10⁻⁶ mm²/s)",
                "CSEPP (MPa·yr/tCO2e)"]


def _show_table(df):
    num = [c for c in df.columns if df[c].dtype.kind in "fc" and c not in PRECISE_COLS]
    st.table(_fmt(df, cols3=PRECISE_COLS, cols2=num))


# ----------------------------------------------------------------------------
# main page
# ----------------------------------------------------------------------------
def render_service_life_page(supabase, db, user_mixes, factors_df,
                             calc_mix_carbon, calculate_project_data):
    refs = get_refs(db)

    st.markdown("#### 1. Select the assessed structure")
    src = st.radio("Data source:", ["Current Project Assessment", "Saved Project"],
                   horizontal=True, key="sl_source")

    results_df, proj_label, proj_id = None, "", None

    if src == "Current Project Assessment":
        results_df = st.session_state.get("project_results_df")
        proj_label = st.session_state.get("draft_proj_name") or "(unsaved project)"
        if results_df is None:
            st.warning("No calculated results found. Go to **Project Assessment**, assign "
                       "materials and press **Calculate Project Totals** first.")
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
        pick = st.selectbox("Saved project:", names, key="sl_saved_proj")
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

    n_mat = cm_all["Material"].nunique()
    st.markdown(f"**{proj_label}** uses **{n_mat}** distinct material(s)/mix(es) across "
                f"**{len(cm_all)}** component–material pairs:")
    _show_table(cm_all.drop(columns=["Is Concrete"]))

    concrete_default = sorted(cm_all[cm_all["Is Concrete"]]["Material"].unique().tolist())
    chosen = st.multiselect(
        "Which materials are concrete elements to be assessed for service life?",
        sorted(cm_all["Material"].unique().tolist()), default=concrete_default,
        key="sl_concrete_pick",
        help="Steel, timber and other non-cementitious items are excluded from the "
             "carbonation / chloride check but still count towards the project EIC.")
    if not chosen:
        st.info("Select at least one concrete material to continue.")
        return
    cm_df = cm_all[cm_all["Material"].isin(chosen)].reset_index(drop=True)

    # ---------------------------------------------------------------- exposure
    st.markdown("---")
    st.markdown("#### 2. Exposure environment")
    exp = refs["exposure"]
    exp_labels = [f"{r['Class']} — {r['Description']}" for _, r in exp.iterrows()]
    default_idx = next((i for i, r in enumerate(exp.to_dict("records"))
                        if str(r.get("Class")) == "XS1"), 0)
    e_col1, e_col2 = st.columns([2, 1])
    with e_col1:
        pick_exp = st.selectbox("Exposure class (EN 206 / EN 1992-1-1):",
                                exp_labels, index=default_idx, key="sl_exposure")
    e_row = exp.iloc[exp_labels.index(pick_exp)]
    mechanism = str(e_row["Mechanism"]).upper()
    with e_col2:
        st.metric("Deterioration model",
                  "Carbonation" if mechanism == "CARBONATION"
                  else ("Chloride" if mechanism == "CHLORIDE" else "Not modelled"))
    if mechanism not in ("CARBONATION", "CHLORIDE"):
        st.warning("This exposure class is not a reinforcement-corrosion class, so no "
                   "service-life model is applied. Pick an XC / XD / XS class.")
        return

    tsl_default = st.number_input(
        "Used Design Life, tsl (years) — applied to every row (editable per row below):",
        min_value=1.0, value=100.0, step=5.0, key="sl_tsl_default")

    k1_default, k2_default, cs_default = 1.0, 1.4, 6.417
    k400_strategy = K400_STRATEGIES[0]

    if mechanism == "CARBONATION":
        k1tab = refs["k1"]
        c1, c2, c3 = st.columns(3)
        with c1:
            loc = st.selectbox("Location type (suggests k1):",
                               k1tab["Location_Type"].astype(str).tolist(), key="sl_loc")
            k1_suggest = sf(k1tab[k1tab["Location_Type"].astype(str) == loc]["k1_default"].iloc[0], 1.0)
        with c2:
            k1_default = st.number_input("k1 (local CO₂ factor):", min_value=0.01,
                                         value=float(k1_suggest), step=0.01,
                                         format="%.2f", key=f"sl_k1_{loc}")
        with c3:
            k2_default = st.number_input("k2 (future CO₂ increase):", min_value=0.01,
                                         value=1.40, step=0.05, format="%.2f", key="sl_k2")
        k400_strategy = st.radio("k400,l auto-fill strategy:", K400_STRATEGIES,
                                 horizontal=True, index=0, key="sl_k400_strategy",
                                 help="Max = fastest carbonation = shortest life = safest "
                                      "assumption. Every value stays editable in the table.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            d_km = st.number_input("Distance from coastline, d (km):", min_value=0.001,
                                   max_value=10.0, value=0.001, step=0.001, format="%.3f",
                                   key="sl_dkm",
                                   help="0.001 km = 1 m from the shore (most severe). "
                                        "10 km is treated as urban / least severe.")
        cs_calc = cs_air_from_distance(d_km)
        with c2:
            cs_default = st.number_input("Surface chloride, Cs,air (kg/m³):", min_value=0.0,
                                         value=float(round(cs_calc, 3)), step=0.1,
                                         format="%.3f", key=f"sl_cs_{d_km}")
        with c3:
            st.metric("Model value at this d", f"{cs_calc:,.3f} kg/m³")
        with st.expander("Chloride Threshold Level (CTL) library — EN 206:2016 and others"):
            st.dataframe(refs["ctl"], use_container_width=True)

    # ---------------------------------------------------------------- inputs
    st.markdown("---")
    st.markdown("#### 3. Confirm properties — one row per component × material")
    st.caption("Auto-filled where the database knows the value; blank cells could not be "
               "derived, please type them in. Every cell is editable. The same concrete "
               "grade can take a different cover in each component (e.g. 40 mm rebar "
               "control in the deck, 90 mm tendon control in the girder).")

    sig = "|".join([proj_label, mechanism, k400_strategy, ",".join(sorted(chosen)),
                    str(len(cm_df))])
    if st.session_state.get("sl_sig") != sig or st.session_state.get("sl_table") is None:
        st.session_state.sl_table = build_input_table(
            cm_df, mechanism, db, user_mixes, factors_df, refs,
            k1_default, k2_default, tsl_default, cs_default, k400_strategy)
        st.session_state.sl_sig = sig

    base = st.session_state.sl_table.copy()
    if mechanism == "CARBONATION":
        for col, val in (("k1", k1_default), ("k2", k2_default)):
            if col in base.columns:
                base[col] = val
    elif "Cs,air (kg/m³)" in base.columns:
        base["Cs,air (kg/m³)"] = cs_default

    if "Binder (kg/m³)" in base.columns:
        base["Binder (kg/m³)"] = base["Cement (kg/m³)"].apply(sf) + \
            base["Additive (kg/m³)"].apply(sf)

    cfg = {
        "Component": st.column_config.TextColumn(disabled=True, width="medium"),
        "Material": st.column_config.TextColumn(disabled=True, width="medium"),
        "Binder (kg/m³)": st.column_config.NumberColumn(
            "Total Binder (kg/m³)", disabled=True, format="%.1f",
            help="Automatically = Cement + Additive"),
        "fck,cyl (MPa)": st.column_config.NumberColumn(format="%.0f"),
        "fcm,cube (MPa)": st.column_config.NumberColumn(format="%.0f"),
        "Cover X (mm)": st.column_config.NumberColumn(
            format="%.0f", help="Minimum concrete cover. Use the value that governs this "
                                "component — rebar control or tendon control."),
    }
    if mechanism == "CHLORIDE":
        cfg["CTL basis"] = st.column_config.SelectboxColumn(options=["binder", "cement"])
        cfg["Dc source"] = st.column_config.TextColumn(disabled=True)

    edited = st.data_editor(base, use_container_width=True, hide_index=True,
                            column_config=cfg, key=f"sl_editor_{sig}")
    st.session_state.sl_table = edited

    if mechanism == "CARBONATION":
        with st.expander("k400,l literature suggestions per material"):
            for mat in sorted(edited["Material"].unique()):
                row = edited[edited["Material"] == mat].iloc[0]
                s = suggest_k400(row.get("Grade", ""), sf(row.get("fcm,cube (MPa)")) - 8,
                                 refs, top=8)
                st.markdown(f"**{mat}** (grade {row.get('Grade', '?')})")
                if s.empty:
                    st.caption("No literature entries loaded — add the `Carbonation_k400` "
                               "tab to your Google Sheet.")
                else:
                    st.dataframe(s, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------------- run
    st.markdown("---")
    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
    if st.button("Calculate Service Life & CSEPP", use_container_width=True, key="sl_run"):
        detail = (run_carbonation(edited, cm_df) if mechanism == "CARBONATION"
                  else run_chloride(edited, cm_df))
        st.session_state.sl_detail = detail
        st.session_state.sl_materials = material_summary(detail)
        st.session_state.sl_mechanism = mechanism
        st.session_state.sl_exposure_class = str(e_row["Class"])
        st.session_state.sl_project_label = proj_label
        st.session_state.sl_project_id = proj_id
        st.rerun()

    detail = st.session_state.get("sl_detail")
    mat_res = st.session_state.get("sl_materials")
    if detail is None or detail.empty or mat_res is None or mat_res.empty:
        return

    # ---------------------------------------------------------------- results
    st.markdown("#### 4. Durability check — per component")
    _show_table(detail)

    fails = detail[detail["Durability Check"] == "FAIL"]
    for _, f in fails.iterrows():
        calc = f["Calculated tsl,S (yr)"]
        calc_txt = "∞" if (isinstance(calc, float) and math.isinf(calc)) else f"{sf(calc):,.1f}"
        if sf(f["Cover X (mm)"]) <= 0:
            st.error(f"**{f['Component']} — {f['Material']}**: no concrete cover entered. "
                     f"Fill in the Min. Concrete Cover, X (mm) before the check can run.")
        else:
            st.error(
                f"**{f['Component']} — {f['Material']} FAILS the durability gate.** "
                f"Calculated design life tsl,S = {calc_txt} years is shorter than the Used "
                f"Design Life tsl = {sf(f['Used tsl (yr)']):,.0f} years.\n\n"
                f"CSEPP is deliberately withheld for this material. The metric credits the mix "
                f"with fck × tsl of service, so crediting more years than the cover and the mix "
                f"can actually deliver would reward a design that needs repair or replacement "
                f"before that date, and the comparison against the other materials would no "
                f"longer sit on the same functional basis. Increase the cover, lower k400,l / "
                f"Dc (denser mix, more SCM), or reduce the Used Design Life, then recalculate.")

    if "Status" in detail.columns:
        for _, r in detail.iterrows():
            if str(r["Status"]).startswith("Chloride NOT"):
                st.info(f"**{r['Component']} — {r['Material']}**: Cx "
                        f"({sf(r['Cx (kg/m³)']):.3f} kg/m³) exceeds Cs,air "
                        f"({sf(r['Cs,air (kg/m³)']):.3f} kg/m³), so the threshold can never be "
                        f"reached at the surface — chloride-induced corrosion is not critical "
                        f"for this mix at this location.")

    st.markdown("#### 5. CSEPP — per material")
    st.caption("EIC is the GWP100 of that material summed over every component that uses it. "
               "The governing tsl,S is the shortest of that material's components.")
    _show_table(mat_res)

    summ = structure_summary(mat_res)

    st.markdown("#### 6. Structure-level CSEPP")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total concrete volume", f"{summ['total_volume']:,.2f} m³")
    s2.metric("Total EIC", f"{summ['total_eic']:,.3f} tCO2e")
    s3.metric("Σ CSEPP (sum of materials)", f"{summ['sum_csepp']:,.2f}")
    s4.metric("Structure CSEPP (volume-weighted)",
              f"{summ['structure_csepp']:,.2f}" if not math.isnan(summ["structure_csepp"]) else "-")

    st.markdown(f"""
    <div style="border:1px solid #d3d3d3;border-radius:6px;padding:16px;background:#f9f9f9;
                color:#000;font-family:sans-serif;font-size:14px;line-height:1.6;">
      <b>How to read the two figures</b><br>
      <b>Σ CSEPP = {summ['sum_csepp']:,.2f} MPa·yr/tCO2e</b> — the plain sum of every material's
      fck·tsl/EIC. It answers "how much strength-service does each mix in this structure buy per
      tonne of CO₂e", and it rises simply because there are more materials, so it is only
      comparable between structures with the same material count and the same size.<br>
      <b>Structure CSEPP = {("%.2f" % summ['structure_csepp']) if not math.isnan(summ['structure_csepp']) else "-"}
      MPa·yr/tCO2e</b> — volume-weighted mean fck ({summ['weighted_fck']:,.1f} MPa) ×
      governing tsl ({summ['governing_tsl']:,.0f} yr) ÷ total EIC
      ({summ['total_eic']:,.3f} tCO2e). It treats the structure as one equivalent material, so it
      stays valid when the two structures being compared differ in size, in number of mixes, or
      in how the volume is split between them. Use this one as the headline metric when you
      benchmark one bridge design against another; report Σ CSEPP alongside it as the
      per-material breakdown.<br>
      Higher is better for both. {summ['n_pass']} of {summ['n_materials']} materials passed the
      durability gate.
    </div>
    """, unsafe_allow_html=True)

    if not summ["all_pass"]:
        st.warning("At least one material failed the durability gate, so the structure-level "
                   "figures above are incomplete — the failed material still contributes its "
                   "EIC to the denominator but contributes no credited service life. Fix the "
                   "failing rows before quoting these numbers.")

    if summ["n_pass"] > 0:
        chart_df = mat_res[mat_res["Durability Check"] == "PASS"][
            ["Material", "CSEPP (MPa·yr/tCO2e)"]]
        bar = alt.Chart(chart_df).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("CSEPP (MPa·yr/tCO2e):Q", title="CSEPP (MPa·yr / tonne CO2e)"),
            y=alt.Y("Material:N", sort="-x", title=""),
            tooltip=["Material", "CSEPP (MPa·yr/tCO2e)"]).properties(height=alt.Step(45))
        st.altair_chart(bar, use_container_width=True)

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
    if proj_id:
        st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
        if st.button("Save service life results to this project", key="sl_save"):
            payload = {"service_life_data": {
                "exposure_class": st.session_state.get("sl_exposure_class"),
                "mechanism": mechanism,
                "k400_strategy": k400_strategy,
                "inputs": edited.fillna(0).to_dict("records"),
                "detail": detail.replace([float("inf")], 1e12).fillna(0).to_dict("records"),
                "materials": mat_res.replace([float("inf")], 1e12).fillna(0).to_dict("records"),
                "summary": summ,
            }}
            try:
                supabase.table("saved_projects").update(payload).eq("id", proj_id).execute()
                st.success("Saved. It will now appear in the Project Comparison tab.")
            except Exception as e:
                st.error(f"Could not save. Add a `service_life_data` (jsonb) column to the "
                         f"`saved_projects` table in Supabase. Details: {e}")
    else:
        st.caption("Save the project first (Project Assessment → Save Project) if you want to "
                   "store these service life results and use them in Project Comparison.")


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

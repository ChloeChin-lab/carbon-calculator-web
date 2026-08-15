import math
import re

import altair as alt
import pandas as pd
import streamlit as st

SECONDS_PER_YEAR = 365.25 * 24 * 3600.0

# Airborne chloride model constants
CS_C1_DEFAULT = 0.6      # calibration constant of the airborne salt relationship
CS_N_DEFAULT = 0.6       # distance decay exponent
CS_A_DEFAULT = 1.5       # airborne to surface conversion factor
CS_B_DEFAULT = 0.4       # airborne to surface conversion exponent

ELEMENT_TYPES = ["Reinforced", "Prestressed"]
CLASS_OPTIONS = ["Automatic", "S1", "S2", "S3", "S4", "S5", "S6", "Not applicable"]

INDEX_COLUMN = "Carbon efficiency index"
INDEX_UNITS = "megapascal years per tonne of carbon dioxide equivalent"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def sf(val, default=0.0):
    """Convert safely to a number. Blanks, text and missing values give the default."""
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
    """Read a concrete grade out of a material name. C32/40 gives (32, 40)."""
    m = re.search(r"C\s*(\d{2,3})\s*/\s*(\d{2,3})", str(name), re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def inv_erf(y):
    """Inverse of the error function, written out so that scipy is not needed."""
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


# ---------------------------------------------------------------------------
# safety net tables, used only when a worksheet is missing
# ---------------------------------------------------------------------------
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
        rows.append({"Grade": "C%d/%d" % (fck, cube), "fck_cyl_MPa": fck,
                     "fck_cube_MPa": cube, "fcm_cyl_MPa": fck + 8,
                     "fcm_cube_MPa": cube + 8})
    return pd.DataFrame(rows)


FALLBACK_EXPOSURE = pd.DataFrame([
    ("XC1", "Carbonation", "Dry or permanently wet", "CARBONATION"),
    ("XC2", "Carbonation", "Wet, rarely dry", "CARBONATION"),
    ("XC3", "Carbonation", "Moderate humidity, sheltered from rain", "CARBONATION"),
    ("XC4", "Carbonation", "Cyclic wet and dry, exposed to rain", "CARBONATION"),
    ("XD1", "Chloride other than sea water", "Moderate humidity", "CHLORIDE"),
    ("XD2", "Chloride other than sea water", "Wet, rarely dry", "CHLORIDE"),
    ("XD3", "Chloride other than sea water", "Cyclic wet and dry, de icing spray", "CHLORIDE"),
    ("XS1", "Sea water chloride", "Airborne salt, no direct contact with sea water", "CHLORIDE"),
    ("XS2", "Sea water chloride", "Permanently submerged in sea water", "CHLORIDE"),
    ("XS3", "Sea water chloride", "Tidal, splash and spray zones", "CHLORIDE"),
], columns=["Class", "Group", "Description", "Mechanism"])

FALLBACK_LOCATION = pd.DataFrame([
    ("Coastal", 0.90, "Literature value"),
    ("Rural", 1.00, "Reference baseline"),
    ("Suburban", 1.30, "Literature value"),
    ("Urban", 1.40, "Literature value"),
    ("Internal", 2.00, "Enclosed environment"),
    ("Kuala Lumpur city centre, 2019", 1.06, "436 ppm against a 410 ppm baseline"),
], columns=["Location_Type", "k1_default", "Note"])

FALLBACK_K400 = pd.DataFrame([
    ("C140/155", "UHPC", 0.50, "Adopted design value"),
    ("C70/85", "HSC", 2.00, "Adopted design value"),
    ("C32/40", "NSC", 3.00, "Adopted design value"),
    ("C40/50", "NSC", 3.00, "Adopted design value"),
], columns=["Grade", "Concrete_Type", "k400_default", "Note"])

FALLBACK_DC = pd.DataFrame([
    ("C32/40", 10.0, "Case study value"),
    ("C40/50", 6.0, "Case study value"),
    ("C70/85", 4.5, "Case study value"),
    ("C140/155", 0.1, "NF P 18-470"),
], columns=["Grade", "Dc_x1e6_mm2_s", "Source"])

FALLBACK_BINDER_MAP = pd.DataFrame([
    ("CEMENT", "OP Cement"), ("CEMENT", "OPC"), ("CEMENT", "CEM I"),
    ("CEMENT", "Portland Cement"), ("CEMENT", "Cement"),
    ("ADDITIVE", "Fly Ash"), ("ADDITIVE", "PFA"), ("ADDITIVE", "Silica Fume"),
    ("ADDITIVE", "Microsilica"),
], columns=["Role", "Component_Keyword"])

_FB_COVER_RC = {
    1: [10, 10, 10, 15, 20, 25, 30], 2: [10, 10, 15, 20, 25, 30, 35],
    3: [10, 10, 20, 25, 30, 35, 40], 4: [10, 15, 25, 30, 35, 40, 45],
    5: [15, 20, 30, 35, 40, 45, 50], 6: [20, 25, 35, 40, 45, 50, 55],
}
_FB_EXP_COL = {"X0": 0, "XC1": 1, "XC2": 2, "XC3": 2, "XC4": 3,
               "XD1": 4, "XS1": 4, "XD2": 5, "XS2": 5, "XD3": 6, "XS3": 6}


def _fallback_cover():
    rows = []
    for s in range(1, 7):
        for exp, col in _FB_EXP_COL.items():
            rows.append(("S%d" % s, exp, "Reinforced", _FB_COVER_RC[s][col]))
            rows.append(("S%d" % s, exp, "Prestressed", _FB_COVER_RC[s][col] + 10))
    return pd.DataFrame(rows, columns=["Structural_Class", "Exposure_Class",
                                       "Element_Type", "cmin_dur_mm"])


def _fallback_rules():
    rows = [("BASE", "ALL", None, 4, ""),
            ("DESIGN_LIFE", "ALL", 100, 2, ""),
            ("QUALITY_CONTROL", "ALL", None, -1, "")]
    thr = {"X0": 30, "XC1": 30, "XC2": 35, "XC3": 35, "XC4": 40, "XD1": 40,
           "XS1": 40, "XD2": 40, "XS2": 45, "XD3": 45, "XS3": 45}
    for exp, t in thr.items():
        rows.append(("STRENGTH", exp, t, -1, ""))
    return pd.DataFrame(rows, columns=["Rule_Type", "Exposure_Class", "Parameter",
                                       "Class_Adjustment", "Description"])


FALLBACK_DESCRIPTIONS = pd.DataFrame([], columns=["Applies_To", "Column_Name", "Description"])


def get_refs(db):
    """Collect the reference worksheets, noting which fell back to the safety net."""
    missing = []

    def pick(key, fallback, label):
        v = db.get(key) if isinstance(db, dict) else None
        if isinstance(v, pd.DataFrame) and not v.empty:
            return v
        if label:
            missing.append(label)
        return fallback

    refs = {
        "strength": pick("strength_classes", _fallback_strength_table(), "Strength_Classes"),
        "k400_lit": pick("carbonation_k400", pd.DataFrame(), ""),
        "k400_def": pick("carbonation_k400_defaults", FALLBACK_K400, "Carbonation_k400_Defaults"),
        "location": pick("location_k1", FALLBACK_LOCATION, "Location_k1"),
        "exposure": pick("exposure_classes", FALLBACK_EXPOSURE, "Exposure_Classes"),
        "dc": pick("chloride_dc", FALLBACK_DC, "Chloride_Dc"),
        "binder_map": pick("binder_mapping", FALLBACK_BINDER_MAP, "Binder_Mapping"),
        "cover": pick("cover_requirements", _fallback_cover(), "Cover_Requirements"),
        "rules": pick("structural_class_rules", _fallback_rules(), "Structural_Class_Rules"),
        "descriptions": pick("column_descriptions", FALLBACK_DESCRIPTIONS, "Column_Descriptions"),
    }
    refs["_missing"] = missing
    return refs


def description_map(refs, mechanism):
    """Column name to description, used for the small question mark on each heading."""
    d = refs["descriptions"]
    out = {}
    if isinstance(d, pd.DataFrame) and not d.empty:
        wanted = "CARBONATION" if mechanism == "CARBONATION" else "CHLORIDE"
        for _, r in d.iterrows():
            if str(r.get("Applies_To", "")).upper() in ("BOTH", wanted):
                out[str(r["Column_Name"]).strip()] = str(r["Description"]).strip()
    return out


# ---------------------------------------------------------------------------
# structural class and minimum durability cover, driven by the spreadsheet
# ---------------------------------------------------------------------------
def structural_class(exposure_class, fck_cyl, design_life_years,
                     special_quality_control, rules_df):
    """Apply the rules held in the spreadsheet to arrive at a structural class."""
    exp = str(exposure_class).upper()
    s = 4
    base = rules_df[rules_df["Rule_Type"].astype(str).str.upper() == "BASE"]
    if not base.empty:
        s = int(sf(base.iloc[0]["Class_Adjustment"], 4))

    for _, r in rules_df.iterrows():
        rule = str(r.get("Rule_Type", "")).upper()
        scope = str(r.get("Exposure_Class", "ALL")).upper()
        if scope not in ("ALL", exp):
            continue
        param = sf(r.get("Parameter"), 0.0)
        adj = int(sf(r.get("Class_Adjustment"), 0))
        if rule == "DESIGN_LIFE" and sf(design_life_years, 50) >= param > 0:
            s += adj
        elif rule == "STRENGTH" and sf(fck_cyl) >= param > 0:
            s += adj
        elif rule == "QUALITY_CONTROL" and special_quality_control:
            s += adj
    return max(1, min(6, s))


def minimum_durability_cover(exposure_class, class_label, element_type, cover_df):
    """Look the minimum durability cover up in the spreadsheet."""
    if str(class_label).lower().startswith("not"):
        return 0.0
    hit = cover_df[
        (cover_df["Structural_Class"].astype(str).str.upper() == str(class_label).upper())
        & (cover_df["Exposure_Class"].astype(str).str.upper() == str(exposure_class).upper())
        & (cover_df["Element_Type"].astype(str).str.lower() == str(element_type).lower())]
    if hit.empty:
        return 0.0
    return sf(hit.iloc[0]["cmin_dur_mm"])


# ---------------------------------------------------------------------------
# strength lookup
# ---------------------------------------------------------------------------
def get_strength(material_name, refs, grade_override=None):
    grade = grade_override if grade_override else material_name
    tbl = refs["strength"]
    out = {"Grade": "", "fck_cyl": 0.0, "fck_cube": 0.0, "fcm_cyl": 0.0, "fcm_cube": 0.0}

    fck, cube = parse_grade(grade)
    if fck is None:
        return out

    out["Grade"] = "C%d/%d" % (fck, cube)
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


# ---------------------------------------------------------------------------
# binder content, filled in from the mix design
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# coefficient lookups
# ---------------------------------------------------------------------------
def _nearest_by_grade(table, grade_col, value_col, grade_label, fck):
    exact = table[table[grade_col].astype(str).str.strip().str.upper()
                  == str(grade_label).strip().upper()]
    if not exact.empty:
        return sf(exact.iloc[0][value_col])
    tmp = table.copy()
    tmp["_f"] = tmp[grade_col].apply(lambda g: parse_grade(g)[0] or 0)
    tmp["_d"] = (tmp["_f"] - sf(fck)).abs()
    tmp = tmp.sort_values("_d")
    if tmp.empty:
        return 0.0
    return sf(tmp.iloc[0][value_col])


def default_carbonation_coefficient(grade_label, fck_cyl, fcm_cyl, refs):
    d = refs["k400_def"]
    if isinstance(d, pd.DataFrame) and not d.empty and "k400_default" in d.columns:
        val = _nearest_by_grade(d, "Grade", "k400_default", grade_label, fck_cyl)
        if val > 0:
            return round(val, 3)
    lit = refs["k400_lit"]
    if isinstance(lit, pd.DataFrame) and not lit.empty and "k400" in lit.columns:
        tmp = lit.copy()
        if "fcm_cyl_MPa" in tmp.columns:
            tmp["_d"] = (tmp["fcm_cyl_MPa"].apply(sf) - sf(fcm_cyl)).abs()
            tmp = tmp.sort_values("_d").head(8)
        vals = sorted(sf(v) for v in tmp["k400"].tolist())
        if vals:
            n = len(vals)
            return round(vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0, 3)
    return 0.0


def default_diffusion_coefficient(grade_label, fck_cyl, refs):
    d = refs["dc"]
    if not isinstance(d, pd.DataFrame) or d.empty:
        return 0.0
    return _nearest_by_grade(d, "Grade", "Dc_x1e6_mm2_s", grade_label, fck_cyl)


# ---------------------------------------------------------------------------
# the physics
# ---------------------------------------------------------------------------
def carbonation_coefficient(k400, k1, k2):
    """Site carbonation coefficient, in millimetres per square root of a year."""
    return sf(k400) * math.sqrt(max(sf(k1) * sf(k2), 0.0))


def carbonation_life(cover_mm, k):
    if sf(k) <= 0:
        return float("inf")
    return (sf(cover_mm) / sf(k)) ** 2


def surface_chloride_from_distance(d_km, c1=CS_C1_DEFAULT, n=CS_N_DEFAULT,
                                   a=CS_A_DEFAULT, b=CS_B_DEFAULT):
    """
    Surface chloride concentration in kilogrammes per cubic metre.
        airborne salt   = c1 multiplied by distance to the power of minus n
        surface value   = a multiplied by the airborne salt to the power of b
    Collapsing the two gives a single power law in distance, and with the
    published constants that reduces to 1.22279 multiplied by distance to the
    power of minus 0.24, giving 6.417 at one metre and 0.704 at ten kilometres.
    """
    d = max(sf(d_km), 1e-6)
    return a * ((c1 * (d ** (-n))) ** b)


def collapsed_constant(c1=CS_C1_DEFAULT, a=CS_A_DEFAULT, b=CS_B_DEFAULT):
    """The single leading constant of the collapsed power law."""
    return a * (sf(c1, CS_C1_DEFAULT) ** b)


def chloride_life(cover_mm, dc_e6, threshold, surface):
    surface = sf(surface); threshold = sf(threshold)
    if surface <= 0:
        return float("nan"), float("nan"), float("nan"), "NO_SURFACE"
    if threshold >= surface:
        return float("inf"), 0.0, float("inf"), "NOT_CRITICAL"
    erf_y = 1.0 - threshold / surface
    y = inv_erf(erf_y)
    da = sf(dc_e6) * 1e-6
    if da <= 0 or y <= 0 or math.isinf(y):
        return float("inf"), erf_y, y, "NOT_CRITICAL"
    return (sf(cover_mm) ** 2) / (4.0 * da * y * y) / SECONDS_PER_YEAR, erf_y, y, "OK"


def carbon_efficiency_index(fck, design_life, embodied_carbon_tonnes):
    if sf(embodied_carbon_tonnes) <= 0:
        return float("nan")
    return sf(fck) * sf(design_life) / sf(embodied_carbon_tonnes)


# ---------------------------------------------------------------------------
# grouping and carbon allocation
# ---------------------------------------------------------------------------
def group_component_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon):
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
            "Density (kg per m3)": density, "Volume (m3)": vol, "Mass (kg)": mass,
            "Embodied carbon (kg CO2e)": gwp,
            "Embodied carbon (tonne CO2e)": gwp / 1000.0,
            "Is Concrete": parse_grade(name)[0] is not None,
        })
    return (pd.DataFrame(rows).sort_values(["Component", "Material"])
            .reset_index(drop=True))


def group_project_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon):
    cm = group_component_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon)
    if cm.empty:
        return pd.DataFrame()
    g = (cm.groupby("Material", as_index=False)
         .agg({"Density (kg per m3)": "first", "Volume (m3)": "sum", "Mass (kg)": "sum",
               "Embodied carbon (kg CO2e)": "sum",
               "Embodied carbon (tonne CO2e)": "sum", "Is Concrete": "first"}))
    g = g.rename(columns={"Volume (m3)": "Volume (m³)",
                          "Embodied carbon (kg CO2e)": "GWP100 (kgCO2e)",
                          "Embodied carbon (tonne CO2e)": "EIC (tonne CO2e)"})
    return g.sort_values("GWP100 (kgCO2e)", ascending=False).reset_index(drop=True)


def allocate_component_carbon(cm_all, concrete_materials):
    """Charge the carbon of every supporting material in a component to its concrete."""
    rows = []
    for comp, g in cm_all.groupby("Component", sort=False):
        conc = g[g["Material"].isin(concrete_materials)]
        other = g[~g["Material"].isin(concrete_materials)]
        other_carbon = sf(other["Embodied carbon (tonne CO2e)"].sum())
        other_names = ", ".join(other["Material"].astype(str).tolist())
        tot_vol = sf(conc["Volume (m3)"].sum())
        n = len(conc)
        for _, c in conc.iterrows():
            share = (sf(c["Volume (m3)"]) / tot_vol) if tot_vol > 0 else (1.0 / n if n else 0.0)
            own = sf(c["Embodied carbon (tonne CO2e)"])
            rows.append({
                "Component": comp, "Material": c["Material"],
                "Volume (m3)": sf(c["Volume (m3)"]),
                "Concrete carbon (tonne CO2e)": own,
                "Supporting carbon (tonne CO2e)": other_carbon * share,
                "Total embodied carbon (tonne CO2e)": own + other_carbon * share,
                "Supporting materials": other_names if other_names else "None",
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# column names used by the input grid
# ---------------------------------------------------------------------------
COL_COMPONENT = "Component"
COL_MATERIAL = "Material"
COL_GRADE = "Concrete grade"
COL_FCK = "Characteristic cylinder strength (MPa)"
COL_FCM = "Mean cube strength (MPa)"
COL_ELEMENT = "Element type"
COL_CLASS = "Structural class"
COL_CEMENT = "Cement content (kg/m3)"
COL_ADDITIVE = "Additive content (kg/m3)"
COL_K400 = "Reference carbonation coefficient (mm/year^0.5)"
COL_CTL = "Chloride threshold level (% of binder)"
COL_DC = "Chloride diffusion coefficient (x10-6 mm2/s)"
COL_CMIN = "Minimum durability cover (mm)"
COL_COVER = "Concrete cover used (mm)"
COL_LIFE = "Used design life (years)"

CALCULATED_COLUMNS = {COL_GRADE, COL_CMIN}


def build_input_table(alloc_df, mechanism, exposure_class, db, user_mixes,
                      factors_df, refs, design_life, cover_allowance,
                      special_quality_control):
    cache = {}
    rows = []
    for _, m in alloc_df.iterrows():
        name = m["Material"]
        if name not in cache:
            s = get_strength(name, refs)
            cem, add, found = autofill_binder(name, db, user_mixes, factors_df, refs)
            k400 = default_carbonation_coefficient(s["Grade"], s["fck_cyl"], s["fcm_cyl"], refs)
            dcv = default_diffusion_coefficient(s["Grade"], s["fck_cyl"], refs)
            cache[name] = (s, cem, add, found, k400, dcv)
        s, cem, add, found, k400, dcv = cache[name]

        s_cls = "S%d" % structural_class(exposure_class, s["fck_cyl"], design_life,
                                         special_quality_control, refs["rules"])
        cmin = minimum_durability_cover(exposure_class, s_cls, "Reinforced", refs["cover"])

        base = {
            COL_COMPONENT: m["Component"],
            COL_MATERIAL: name,
            COL_GRADE: s["Grade"] if s["Grade"] else "Not recognised",
            COL_FCK: s["fck_cyl"],
            COL_FCM: s["fcm_cube"],
            COL_ELEMENT: "Reinforced",
            COL_CLASS: "Automatic",
            COL_CEMENT: cem if found else None,
            COL_ADDITIVE: add if found else None,
        }
        if mechanism == "CARBONATION":
            base[COL_K400] = k400
        else:
            base[COL_CTL] = 0.40
            base[COL_DC] = dcv
        base[COL_CMIN] = cmin
        base[COL_COVER] = cmin + sf(cover_allowance, 10.0)
        base[COL_LIFE] = float(design_life)
        rows.append(base)

    df = pd.DataFrame(rows)
    return df[[c for c in expected_columns(mechanism) if c in df.columns]]


def expected_columns(mechanism):
    order = [COL_COMPONENT, COL_MATERIAL, COL_GRADE, COL_FCK, COL_FCM,
             COL_ELEMENT, COL_CLASS, COL_CEMENT, COL_ADDITIVE]
    order += [COL_K400] if mechanism == "CARBONATION" else [COL_CTL, COL_DC]
    order += [COL_CMIN, COL_COVER, COL_LIFE]
    return order


def refresh_derived(df, exposure_class, cover_allowance, special_quality_control, refs):
    """Recompute the class and the minimum cover after the user has edited the grid."""
    d = df.copy()
    classes, cmins, covers = [], [], []
    for _, r in d.iterrows():
        chosen = str(r.get(COL_CLASS, "Automatic"))
        if chosen.lower().startswith("not"):
            label = "Not applicable"
        elif chosen.upper().startswith("S"):
            label = chosen.upper()
        else:
            label = "S%d" % structural_class(exposure_class, r.get(COL_FCK),
                                             r.get(COL_LIFE), special_quality_control,
                                             refs["rules"])
        cmin = minimum_durability_cover(exposure_class, label,
                                        r.get(COL_ELEMENT, "Reinforced"), refs["cover"])
        old_cmin = sf(r.get(COL_CMIN))
        cover = sf(r.get(COL_COVER))
        if abs(cover - (old_cmin + sf(cover_allowance, 10.0))) < 1e-6 and cmin > 0:
            cover = cmin + sf(cover_allowance, 10.0)
        classes.append(label)
        cmins.append(cmin)
        covers.append(cover)
    d["_resolved_class"] = classes
    d[COL_CMIN] = cmins
    d[COL_COVER] = covers
    return d


# ---------------------------------------------------------------------------
# calculation
# ---------------------------------------------------------------------------
def _pick(alloc, component, material, col):
    hit = alloc[(alloc["Component"] == component) & (alloc["Material"] == material)]
    return sf(hit[col].sum()) if not hit.empty else 0.0


def _carbon_columns(alloc, r):
    return {
        "Volume (m3)": _pick(alloc, r[COL_COMPONENT], r[COL_MATERIAL], "Volume (m3)"),
        "Concrete carbon (tonne CO2e)": _pick(alloc, r[COL_COMPONENT], r[COL_MATERIAL],
                                              "Concrete carbon (tonne CO2e)"),
        "Supporting carbon (tonne CO2e)": _pick(alloc, r[COL_COMPONENT], r[COL_MATERIAL],
                                                "Supporting carbon (tonne CO2e)"),
        "Total embodied carbon (tonne CO2e)": _pick(alloc, r[COL_COMPONENT], r[COL_MATERIAL],
                                                    "Total embodied carbon (tonne CO2e)"),
    }


def run_carbonation(edited, alloc, k1, k2):
    out = []
    for _, r in edited.iterrows():
        binder = sf(r.get(COL_CEMENT)) + sf(r.get(COL_ADDITIVE))
        cover = sf(r.get(COL_COVER))
        k = carbonation_coefficient(r.get(COL_K400), k1, k2)
        life = carbonation_life(cover, k)
        used = sf(r.get(COL_LIFE), 100.0)
        row = {
            "Component": r[COL_COMPONENT], "Material": r[COL_MATERIAL],
            "Concrete grade": r.get(COL_GRADE, ""),
            "Characteristic cylinder strength (MPa)": sf(r.get(COL_FCK)),
            "Structural class": r.get("_resolved_class", ""),
            "Total binder content (kg per m3)": binder,
            "Reference carbonation coefficient": sf(r.get(COL_K400)),
            "Site carbonation coefficient": k,
            "Minimum durability cover (mm)": sf(r.get(COL_CMIN)),
            "Concrete cover used (mm)": cover,
            "Calculated design life (years)": life,
            "Used design life (years)": used,
            "Durability check": "PASS" if (cover > 0 and life >= used) else "FAIL",
        }
        row.update(_carbon_columns(alloc, r))
        out.append(row)
    return pd.DataFrame(out)


def run_chloride(edited, alloc, surface_chloride):
    out = []
    for _, r in edited.iterrows():
        binder = sf(r.get(COL_CEMENT)) + sf(r.get(COL_ADDITIVE))
        threshold = sf(r.get(COL_CTL)) / 100.0 * binder
        cover = sf(r.get(COL_COVER))
        life, erf_y, y, status = chloride_life(cover, r.get(COL_DC), threshold, surface_chloride)
        used = sf(r.get(COL_LIFE), 100.0)
        row = {
            "Component": r[COL_COMPONENT], "Material": r[COL_MATERIAL],
            "Concrete grade": r.get(COL_GRADE, ""),
            "Characteristic cylinder strength (MPa)": sf(r.get(COL_FCK)),
            "Structural class": r.get("_resolved_class", ""),
            "Total binder content (kg per m3)": binder,
            "Chloride threshold level (%)": sf(r.get(COL_CTL)),
            "Threshold concentration (kg per m3)": threshold,
            "Surface concentration (kg per m3)": sf(surface_chloride),
            "Error function value": erf_y,
            "Inverse error function value": y,
            "Chloride diffusion coefficient": sf(r.get(COL_DC)),
            "Minimum durability cover (mm)": sf(r.get(COL_CMIN)),
            "Concrete cover used (mm)": cover,
            "Calculated design life (years)": life,
            "Used design life (years)": used,
            "Chloride status": ("Chloride not critical" if status == "NOT_CRITICAL"
                                else ("No surface value" if status == "NO_SURFACE"
                                      else "Chloride governs")),
            "Durability check": "PASS" if (cover > 0 and life >= used) else "FAIL",
        }
        row.update(_carbon_columns(alloc, r))
        out.append(row)
    return pd.DataFrame(out)


def material_summary(detail_df):
    rows = []
    for mat, g in detail_df.groupby("Material", sort=False):
        used = sf(g["Used design life (years)"].min(), 100.0)
        carbon = sf(g["Total embodied carbon (tonne CO2e)"].sum())
        fck = sf(g["Characteristic cylinder strength (MPa)"].iloc[0])
        all_pass = bool((g["Durability check"] == "PASS").all())
        rows.append({
            "Material": mat,
            "Concrete grade": g["Concrete grade"].iloc[0],
            "Characteristic cylinder strength (MPa)": fck,
            "Components": ", ".join(g["Component"].astype(str).tolist()),
            "Volume (m3)": sf(g["Volume (m3)"].sum()),
            "Concrete carbon (tonne CO2e)": sf(g["Concrete carbon (tonne CO2e)"].sum()),
            "Supporting carbon (tonne CO2e)": sf(g["Supporting carbon (tonne CO2e)"].sum()),
            "Total embodied carbon (tonne CO2e)": carbon,
            "Governing calculated life (years)": g["Calculated design life (years)"].min(),
            "Used design life (years)": used,
            "Durability check": "PASS" if all_pass else "FAIL",
            INDEX_COLUMN: carbon_efficiency_index(fck, used, carbon) if all_pass else float("nan"),
        })
    return pd.DataFrame(rows)


def structure_summary(mat_res_df):
    valid = mat_res_df[mat_res_df["Durability check"] == "PASS"]
    total_carbon = sf(mat_res_df["Total embodied carbon (tonne CO2e)"].sum())
    total_volume = sf(mat_res_df["Volume (m3)"].sum())
    weighted_fck = (sf((mat_res_df["Characteristic cylinder strength (MPa)"]
                        * mat_res_df["Volume (m3)"]).sum()) / total_volume) \
        if total_volume > 0 else 0.0
    life = sf(mat_res_df["Used design life (years)"].min()) if not mat_res_df.empty else 0.0
    whole = (weighted_fck * life / total_carbon) if total_carbon > 0 else float("nan")
    return {
        "n_materials": int(len(mat_res_df)), "n_pass": int(len(valid)),
        "all_pass": bool(len(valid) == len(mat_res_df)) and len(mat_res_df) > 0,
        "total_volume": total_volume, "total_carbon": total_carbon,
        "concrete_carbon": sf(mat_res_df["Concrete carbon (tonne CO2e)"].sum()),
        "supporting_carbon": sf(mat_res_df["Supporting carbon (tonne CO2e)"].sum()),
        "sum_index": sf(valid[INDEX_COLUMN].sum()),
        "weighted_fck": weighted_fck,
        "structure_index": whole,
        "governing_life": life,
        # legacy keys, so that anything saved earlier still reads correctly
        "total_eic": total_carbon, "sum_csepp": sf(valid[INDEX_COLUMN].sum()),
        "structure_csepp": whole, "governing_tsl": life,
    }


# ---------------------------------------------------------------------------
# table rendering
# ---------------------------------------------------------------------------
PRECISE_COLUMNS = {
    "Error function value", "Inverse error function value",
    "Site carbonation coefficient", "Reference carbonation coefficient",
    "Threshold concentration (kg per m3)", "Surface concentration (kg per m3)",
    "Chloride diffusion coefficient", INDEX_COLUMN,
    "Concrete carbon (tonne CO2e)", "Supporting carbon (tonne CO2e)",
    "Total embodied carbon (tonne CO2e)", "Embodied carbon (tonne CO2e)",
}


def _numfmt(nd):
    def f(x):
        if isinstance(x, str):
            return x
        if x is None:
            return "not given"
        try:
            v = float(x)
        except (TypeError, ValueError):
            return str(x)
        if math.isnan(v):
            return "not given"
        if math.isinf(v):
            return "no limit"
        return "{:,.{p}f}".format(v, p=nd)
    return f


def show_table(df, highlight=()):
    """Static table whose row numbers start at 1, with the results picked out."""
    d = df.copy().reset_index(drop=True)
    d.index = d.index + 1
    fmt = {c: _numfmt(3 if c in PRECISE_COLUMNS else 2)
           for c in d.columns if d[c].dtype.kind in "fci"}
    sty = d.style.format(fmt)
    hl = [c for c in highlight if c in d.columns]
    if hl:
        sty = sty.set_properties(subset=hl, **{
            "background-color": "#FEF9E7", "font-weight": "bold", "color": "#000"})
    if "Durability check" in d.columns:
        sty = sty.apply(
            lambda s: ["background-color:#d4edda;color:#155724;font-weight:bold"
                       if str(v) == "PASS"
                       else "background-color:#f8d7da;color:#721c24;font-weight:bold"
                       for v in s], subset=["Durability check"])
    st.table(sty)


# ---------------------------------------------------------------------------
# saved assessment records
# ---------------------------------------------------------------------------
def load_runs(supabase, project_id=None):
    """Fetch the saved assessments for this user, newest first."""
    try:
        q = supabase.table("service_life_runs").select("*") \
            .eq("user_id", st.session_state.user_id)
        if project_id:
            q = q.eq("project_id", project_id)
        res = q.order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def runs_overview(runs):
    """A short table of the saved assessments for display."""
    rows = []
    for r in runs:
        summ = r.get("summary") or {}
        rows.append({
            "Version": r.get("version_name", "unnamed"),
            "Project": r.get("project_name", ""),
            "Exposure class": r.get("exposure_class", ""),
            "Model": str(r.get("mechanism", "")).title(),
            "Materials passed": "%s of %s" % (int(sf(summ.get("n_pass"))),
                                              int(sf(summ.get("n_materials")))),
            "Sum of material values": sf(summ.get("sum_index", summ.get("sum_csepp"))),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
def _clear_page_state():
    for k in ("sl_detail", "sl_materials", "sl_table", "sl_sig", "sl_alloc",
              "sl_exposure_class", "sl_project_label", "sl_project_id",
              "sl_pending_inputs", "sl_pending_settings", "sl_opened_version"):
        st.session_state[k] = None


def render_service_life_page(supabase, db, user_mixes, factors_df,
                             calc_mix_carbon, calculate_project_data):
    refs = get_refs(db)

    if st.session_state.get("sl_saved_flash"):
        st.success(st.session_state.sl_saved_flash)
        st.session_state.sl_saved_flash = None

    if refs["_missing"]:
        st.warning("These reference worksheets were not found in the database, so built in "
                   "values are being used instead: %s. Add them to the spreadsheet so that "
                   "every number stays under your control." % ", ".join(refs["_missing"]))

    st.markdown("#### 1. Select the assessed structure")
    src = st.radio("Data source:", ["Saved Project", "Current Project"],
                   horizontal=True, key="sl_source")

    results_df, proj_label, proj_id = None, "", None

    if src == "Current Project":
        results_df = st.session_state.get("project_results_df")
        proj_label = st.session_state.get("draft_proj_name") or "Unsaved project"
        # This is what lets the Save button below work when you assess the
        # project you currently have open, instead of only when you reselect
        # it from the Saved Project dropdown: reuse the id that was recorded
        # when that project was saved from Project Design. If the project
        # on screen has never actually been saved yet, this stays None and
        # the save section further down will ask you to save it first.
        proj_id = st.session_state.get("current_project_id")
        if results_df is None:
            st.info("There is nothing to assess yet. Open Project Design, assign the "
                    "materials and press Calculate Project Totals, or switch the selector "
                    "above to Saved Project.")
            return
    else:
        try:
            res = supabase.table("saved_projects").select("*") \
                .eq("user_id", st.session_state.user_id).execute()
            projects = res.data or []
        except Exception:
            projects = []
        if not projects:
            st.info("There are no saved projects on your account yet.")
            return
        names = list(dict.fromkeys([p["project_name"] for p in projects if p.get("project_name")]))
        pick = st.selectbox("Saved project:", ["Select a project"] + names, key="sl_saved_proj")
        if pick == "Select a project":
            st.info("Choose a project from the list above to load its materials and begin "
                    "the assessment.")
            return
        p = next((x for x in projects if x["project_name"] == pick), None)
        if not p:
            return
        proj_label, proj_id = p["project_name"], p.get("id")
        results_df, _, _ = calculate_project_data(rebuild_draft(p), db, user_mixes, factors_df)
        if results_df is None:
            st.error("This project has no materials that can be calculated.")
            return

    # ------------------------------------------------------- earlier assessments
    if proj_id:
        runs = load_runs(supabase, proj_id)
        if runs:
            st.markdown("**Earlier assessments of this project**")
            show_table(runs_overview(runs).drop(columns=["Project"]))
            opts = ["Start a new assessment"] + [
                "Open version: %s" % r.get("version_name", "unnamed") for r in runs]
            choice = st.selectbox("Would you like to open one of these, or start again?",
                                  opts, key="sl_run_choice")
            if choice != "Start a new assessment":
                chosen = runs[opts.index(choice) - 1]
                if st.button("Load this assessment into the grid", key="sl_load_run"):
                    st.session_state.sl_pending_inputs = chosen.get("inputs") or []
                    st.session_state.sl_pending_settings = {
                        "exposure_class": chosen.get("exposure_class"),
                        "mechanism": chosen.get("mechanism"),
                        "settings": chosen.get("settings") or {},
                    }
                    # The "Which materials are concrete?" multiselect keeps whatever
                    # it was last set to (it is not re-created for every project), so
                    # without this it can silently stay on a stale selection from a
                    # previous project or run instead of the one that was saved.
                    saved_mats = chosen.get("materials") or []
                    st.session_state.sl_pending_concrete = sorted({
                        m.get("Material") for m in saved_mats if m.get("Material")})
                    # Restore the calculated results too, not just the input grid,
                    # so sections 4-7 (durability check, carbon efficiency, and the
                    # Save button) reappear immediately instead of only coming back
                    # once "Calculate" is pressed again.
                    saved_detail = chosen.get("detail") or []
                    if saved_detail:
                        st.session_state.sl_detail = pd.DataFrame(saved_detail)
                    if saved_mats:
                        st.session_state.sl_materials = pd.DataFrame(saved_mats)
                    st.session_state.sl_mechanism = chosen.get("mechanism")
                    st.session_state.sl_exposure_class = chosen.get("exposure_class")
                    st.session_state.sl_project_label = proj_label
                    st.session_state.sl_project_id = proj_id
                    st.session_state.sl_opened_version = chosen.get("version_name")
                    st.session_state.sl_sig = None
                    st.rerun()
            if st.session_state.get("sl_opened_version"):
                st.info("You are working from the saved version named %s. Saving will create "
                        "a new version and will leave that one untouched."
                        % st.session_state.sl_opened_version)
        else:
            st.caption("This project has not been assessed yet.")

    cm_all = group_component_materials(results_df, db, user_mixes, factors_df, calc_mix_carbon)
    if cm_all.empty:
        st.error("The project materials could not be grouped.")
        return

    st.markdown("**%s** uses %d material(s) across %d component(s)."
                % (proj_label, cm_all["Material"].nunique(), cm_all["Component"].nunique()))
    show_table(cm_all.drop(columns=["Is Concrete"]))

    concrete_default = sorted(cm_all[cm_all["Is Concrete"]]["Material"].unique().tolist())
    all_material_options = sorted(cm_all["Material"].unique().tolist())
    # If "Load this assessment into the grid" was just pressed, this holds the
    # materials that were treated as the concretes in that saved run. Only keep
    # the ones that still exist in this project so a stale name can never be
    # passed to the widget below.
    pending_concrete = st.session_state.pop("sl_pending_concrete", None)
    if pending_concrete:
        valid_restored = [m for m in pending_concrete if m in all_material_options]
        if valid_restored:
            st.session_state.sl_concrete_pick = valid_restored
    chosen_mats = st.multiselect(
        "Which of these materials are the concretes to be assessed?",
        all_material_options, default=concrete_default,
        key="sl_concrete_pick",
        help="Anything left out of this list, such as strands, reinforcing bars and diesel, "
             "is treated as a supporting material. Its carbon is charged to the concrete of "
             "the same component, because the component only works as a complete assembly.")
    if not chosen_mats:
        st.info("Select at least one concrete to continue.")
        return

    alloc = allocate_component_carbon(cm_all, chosen_mats)
    if alloc.empty:
        st.error("There are no concrete rows to assess.")
        return

    with st.expander("How the embodied carbon of each component is made up"):
        show_table(alloc)

    # ------------------------------------------------------------ exposure
    st.markdown("---")
    st.markdown("#### 2. Exposure environment and cover rules")

    # If "Load this assessment into the grid" was just pressed, this holds the
    # exposure class, mechanism and settings that produced that version, so
    # every widget below can be pre-filled with them instead of the plain
    # defaults. It is only meant to apply once, immediately after loading, so
    # it is popped out here rather than read with .get().
    restore = st.session_state.pop("sl_pending_settings", None)
    restore_settings = (restore or {}).get("settings") or {}

    def _seed(key, default, restored_value=None):
        """Set the starting value for a keyed widget without also passing a
        conflicting value=/index= argument: restored_value wins when a
        version is being loaded, otherwise the key keeps whatever it already
        holds, and only a brand new key falls back to default."""
        if restored_value is not None:
            st.session_state[key] = restored_value
        elif key not in st.session_state:
            st.session_state[key] = default

    exp = refs["exposure"]
    exp_labels = ["%s. %s" % (r["Class"], r["Description"]) for _, r in exp.iterrows()]
    exp_records = exp.to_dict("records")
    restored_label = None
    if restore and restore.get("exposure_class"):
        idx = next((i for i, r in enumerate(exp_records)
                   if str(r.get("Class")).upper() == str(restore["exposure_class"]).upper()), None)
        if idx is not None:
            restored_label = exp_labels[idx]
    default_idx = next((i for i, r in enumerate(exp_records)
                        if str(r.get("Class")) == "XS1"), 0)
    _seed("sl_exposure", exp_labels[default_idx], restored_label)
    e_col1, e_col2 = st.columns([2, 1])
    with e_col1:
        pick_exp = st.selectbox("Exposure class, to EN 206 and EN 1992-1-1:",
                                exp_labels, key="sl_exposure",
                                help="The class you pick decides which model runs. Classes "
                                     "beginning XC run the carbonation model. Classes "
                                     "beginning XS or XD run the chloride model.")
    e_row = exp.iloc[exp_labels.index(pick_exp)]
    exposure_class = str(e_row["Class"]).upper()
    mechanism = str(e_row["Mechanism"]).upper()
    with e_col2:
        st.metric("Deterioration model",
                  "Carbonation" if mechanism == "CARBONATION"
                  else ("Chloride" if mechanism == "CHLORIDE" else "Not modelled"))
    if mechanism not in ("CARBONATION", "CHLORIDE"):
        st.warning("This exposure class does not cause corrosion of the reinforcement, so no "
                   "service life model applies. Choose a class beginning XC, XD or XS.")
        return

    _seed("sl_design_life", 100.0, restore_settings.get("design_life"))
    _seed("sl_allowance", 10.0, restore_settings.get("cover_allowance"))
    _seed("sl_qc", False, restore_settings.get("special_quality_control"))
    g1, g2, g3 = st.columns(3)
    with g1:
        design_life = st.number_input(
            "Used design life (years):", min_value=1.0, step=5.0,
            key="sl_design_life",
            help="The service life you want to credit the structure with. It is compared "
                 "against the life the cover and the mix can deliver, and it also raises "
                 "the structural class by two once it reaches 100 years.")
    with g2:
        cover_allowance = st.number_input(
            "Allowance for deviation in cover (mm):", min_value=0.0, step=5.0,
            key="sl_allowance",
            help="The construction tolerance that EN 1992-1-1 clause 4.4.1.3 adds on top of "
                 "the minimum durability cover. Normally 10 mm. The suggested cover in the "
                 "grid below is the minimum durability cover plus this allowance.")
    with g3:
        special_qc = st.checkbox(
            "Special quality control assured", key="sl_qc",
            help="Tick this when the concrete production is monitored to the standard the "
                 "code describes. Ticking it lowers the structural class by one for every "
                 "row set to Automatic, which lowers the minimum durability cover by about "
                 "5 mm and therefore lengthens the calculated design life. Leave it clear "
                 "if you are not certain, because that is the safer assumption.")

    k1_value, k2_value, surface_chloride = 1.0, 1.4, 0.0
    if mechanism == "CARBONATION":
        loc_tab = refs["location"]
        c1, c2, c3 = st.columns(3)
        with c1:
            loc = st.selectbox("Location type:", loc_tab["Location_Type"].astype(str).tolist(),
                               key="sl_location",
                               help="Picking a location suggests a value for the local "
                                    "carbon dioxide factor. You may then type any value.")
        suggestion = sf(loc_tab[loc_tab["Location_Type"].astype(str) == loc]
                        ["k1_default"].iloc[0], 1.0)
        k1_restored = restore_settings.get("k1") if (restore and restore.get("mechanism") == "CARBONATION") else None
        _seed("sl_k1_%s" % loc, float(suggestion), k1_restored)
        with c2:
            k1_value = st.number_input(
                "Local carbon dioxide factor:", min_value=0.01,
                step=0.01, format="%.2f", key="sl_k1_%s" % loc,
                help="The carbon dioxide concentration at the site divided by the 400 parts "
                     "per million reference concentration.")
        k2_restored = restore_settings.get("k2") if (restore and restore.get("mechanism") == "CARBONATION") else None
        _seed("sl_k2", 1.40, k2_restored)
        with c3:
            k2_value = st.number_input(
                "Future carbon dioxide factor:", min_value=0.01, step=0.05,
                format="%.2f", key="sl_k2",
                help="Allows for the concentration rising over the life of the structure. "
                     "A value of 1.40 corresponds to roughly 560 parts per million.")
        st.caption("The site carbonation coefficient is calculated for you as the reference "
                   "coefficient multiplied by the square root of these two factors. You "
                   "only confirm the reference coefficient in the grid below.")
    else:
        _seed("sl_distance", 0.001)
        _seed("sl_c1", 0.60)
        c1, c2, c3 = st.columns(3)
        with c1:
            distance = st.number_input(
                "Distance from the coastline (km):", min_value=0.001, max_value=10.0,
                step=0.001, format="%.3f", key="sl_distance",
                help="0.001 km is one metre from the shore, the most severe case. Ten "
                     "kilometres is treated as an urban location, the least severe case.")
        with c2:
            c1_value = st.number_input(
                "Airborne salt constant:", min_value=0.01, step=0.05,
                format="%.2f", key="sl_c1",
                help="The calibration constant of the airborne salt relationship, which is "
                     "the salt concentration at one kilometre from the coast. The published "
                     "value is 0.6.")
        modelled = surface_chloride_from_distance(distance, c1=c1_value)
        chloride_restored = restore_settings.get("surface_chloride") if (restore and restore.get("mechanism") == "CHLORIDE") else None
        _seed("sl_surface_%.4f_%.2f" % (distance, c1_value), float(round(modelled, 3)), chloride_restored)
        with c3:
            surface_chloride = st.number_input(
                "Surface chloride concentration (kg per m3):", min_value=0.0,
                step=0.1, format="%.3f",
                key="sl_surface_%.4f_%.2f" % (distance, c1_value),
                help="Calculated from the two values on the left. Overwrite it only if you "
                     "have a measured value for the site.")
        st.caption("Airborne salt equals the constant multiplied by the distance to the "
                   "power of minus 0.6. The surface concentration equals 1.5 multiplied by "
                   "that value to the power of 0.4. Collapsing the two gives %.5f multiplied "
                   "by the distance to the power of minus 0.24, which returns 6.417 at one "
                   "metre and 0.704 at ten kilometres for the published constant."
                   % collapsed_constant(c1_value))

    # ------------------------------------------------------------ input grid
    st.markdown("---")
    st.markdown("#### 3. Confirm the properties of each component and material")
    st.caption("Hover the small question mark on any heading to see what that column is "
               "for. Nothing is recalculated while you type, so fill in the grid at your "
               "own pace and press Calculate when you are ready.")

    sig = "|".join([str(proj_label), mechanism, exposure_class, ",".join(sorted(chosen_mats)),
                    str(len(alloc)), "%.0f" % design_life, "%.0f" % cover_allowance,
                    str(special_qc)])

    if st.session_state.get("sl_pending_inputs"):
        restored = pd.DataFrame(st.session_state.sl_pending_inputs)
        for col in expected_columns(mechanism):
            if col not in restored.columns:
                restored[col] = None
        st.session_state.sl_table = restored[expected_columns(mechanism)]
        st.session_state.sl_sig = sig
        st.session_state.sl_pending_inputs = None
    elif st.session_state.get("sl_sig") != sig or st.session_state.get("sl_table") is None:
        st.session_state.sl_table = build_input_table(
            alloc, mechanism, exposure_class, db, user_mixes, factors_df, refs,
            design_life, cover_allowance, special_qc)
        st.session_state.sl_sig = sig

    grid = st.session_state.sl_table
    if "_resolved_class" in grid.columns:
        grid = grid.drop(columns=["_resolved_class"])

    notes = description_map(refs, mechanism)

    def label_for(col):
        return col + " (calculated)" if col in CALCULATED_COLUMNS else col

    cfg = {}
    for col in grid.columns:
        helptext = notes.get(col)
        if col in (COL_COMPONENT, COL_MATERIAL, COL_GRADE):
            cfg[col] = st.column_config.TextColumn(label_for(col), disabled=True,
                                                   help=helptext, width="medium")
        elif col == COL_ELEMENT:
            cfg[col] = st.column_config.SelectboxColumn(col, options=ELEMENT_TYPES,
                                                        help=helptext)
        elif col == COL_CLASS:
            cfg[col] = st.column_config.SelectboxColumn(col, options=CLASS_OPTIONS,
                                                        help=helptext)
        elif col == COL_CMIN:
            cfg[col] = st.column_config.NumberColumn(label_for(col), disabled=True,
                                                     format="%.0f", help=helptext)
        elif col in (COL_FCK, COL_FCM, COL_COVER, COL_LIFE):
            cfg[col] = st.column_config.NumberColumn(col, format="%.0f", help=helptext)
        else:
            cfg[col] = st.column_config.NumberColumn(col, help=helptext)

    with st.form(key="sl_form_%s" % sig):
        edited = st.data_editor(grid, use_container_width=True, hide_index=True,
                                column_config=cfg, key="sl_editor_%s" % sig)
        submitted = st.form_submit_button("Calculate", use_container_width=True,
                                          type="primary")

    with st.expander("What each column means"):
        if notes:
            for col in grid.columns:
                if col in notes:
                    st.markdown("**%s.** %s" % (col, notes[col]))
        else:
            st.caption("Add the Column_Descriptions worksheet to the database to show a "
                       "description of every column here.")

    if submitted:
        edited = refresh_derived(edited, exposure_class, cover_allowance, special_qc, refs)
        st.session_state.sl_table = edited
        st.session_state.sl_alloc = alloc
        st.session_state.sl_detail = (run_carbonation(edited, alloc, k1_value, k2_value)
                                      if mechanism == "CARBONATION"
                                      else run_chloride(edited, alloc, surface_chloride))
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

    # ------------------------------------------------------------ results
    st.markdown("---")
    st.markdown("#### 4. Durability check for each component")
    st.caption("The shaded columns hold the results of the calculation.")
    show_table(detail, highlight=[
        "Site carbonation coefficient", "Threshold concentration (kg per m3)",
        "Error function value", "Inverse error function value",
        "Calculated design life (years)", "Durability check"])

    for _, f in detail[detail["Durability check"] == "FAIL"].iterrows():
        life = f["Calculated design life (years)"]
        life_txt = "no limit" if (isinstance(life, float) and math.isinf(life)) \
            else "{:,.1f}".format(sf(life))
        if sf(f["Concrete cover used (mm)"]) <= 0:
            st.error("**%s, %s.** No concrete cover has been entered, so the check cannot run."
                     % (f["Component"], f["Material"]))
        else:
            st.error(
                "**%s, %s fails the durability check.** The calculated design life of %s years "
                "is shorter than the used design life of %s years. Increase the cover, choose "
                "a denser mix or one with more supplementary cementitious material, or reduce "
                "the used design life, then calculate again."
                % (f["Component"], f["Material"], life_txt,
                   "{:,.0f}".format(sf(f["Used design life (years)"]))))

    if "Chloride status" in detail.columns:
        for _, r in detail[detail["Chloride status"] == "Chloride not critical"].iterrows():
            st.info("**%s, %s.** The threshold concentration of %.3f kilogrammes per cubic "
                    "metre is higher than the surface concentration of %.3f, so the threshold "
                    "can never be reached and chloride corrosion is not critical here."
                    % (r["Component"], r["Material"],
                       sf(r["Threshold concentration (kg per m3)"]),
                       sf(r["Surface concentration (kg per m3)"])))

    st.markdown("#### 5. Carbon efficiency for each material")
    show_table(mat_res, highlight=["Total embodied carbon (tonne CO2e)",
                                   "Governing calculated life (years)", "Durability check",
                                   INDEX_COLUMN])

    summ = structure_summary(mat_res)

    st.markdown("#### 6. Results")
    s1, s2, s3 = st.columns(3)
    s1.metric("Concrete volume", "{:,.2f} m3".format(summ["total_volume"]))
    s2.metric("Total embodied carbon", "{:,.3f} tonne CO2e".format(summ["total_carbon"]))
    s3.metric("Sum of the material values", "{:,.2f}".format(summ["sum_index"]))

    passed = mat_res[mat_res["Durability check"] == "PASS"]
    if not passed.empty:
        chart_a = passed[["Material", INDEX_COLUMN]].rename(
            columns={INDEX_COLUMN: "Index"})
        st.altair_chart(alt.Chart(chart_a).mark_bar(cornerRadiusEnd=4, color="#2C5F2D").encode(
            x=alt.X("Index:Q", title="Carbon efficiency index"),
            y=alt.Y("Material:N", sort="-x", title=""),
            tooltip=["Material", "Index"]).properties(height=alt.Step(42)),
            use_container_width=True)
        st.caption("Carbon efficiency of each mix, in %s." % INDEX_UNITS)

    split = mat_res.melt(
        id_vars="Material",
        value_vars=["Concrete carbon (tonne CO2e)", "Supporting carbon (tonne CO2e)"],
        var_name="Source", value_name="Carbon")
    split["Source"] = split["Source"].str.replace(" carbon (tonne CO2e)", "", regex=False)
    st.altair_chart(alt.Chart(split).mark_bar().encode(
        x=alt.X("Carbon:Q", title="Embodied carbon, tonne CO2e"),
        y=alt.Y("Material:N", title=""),
        color=alt.Color("Source:N", title="",
                        scale=alt.Scale(range=["#2C5F2D", "#97BC62"]),
                        legend=alt.Legend(orient="bottom")),
        tooltip=["Material", "Source", "Carbon"]).properties(height=alt.Step(42)),
        use_container_width=True)
    st.caption("The concrete carbon and the supporting carbon that is charged to it.")

    lives = detail[["Component", "Material", "Calculated design life (years)",
                    "Used design life (years)"]].copy()
    lives["Row"] = lives["Component"] + ", " + lives["Material"]
    cap = max(sf(lives["Used design life (years)"].max()) * 3.0, 1.0)
    lives["Calculated"] = lives["Calculated design life (years)"].apply(
        lambda v: cap if (isinstance(v, float) and math.isinf(v)) else min(sf(v), cap))
    lives["Required"] = lives["Used design life (years)"]
    life_long = lives.melt(id_vars="Row", value_vars=["Calculated", "Required"],
                           var_name="Measure", value_name="Years")
    st.altair_chart(alt.Chart(life_long).mark_bar().encode(
        x=alt.X("Years:Q", title="Design life, years"),
        y=alt.Y("Row:N", title=""),
        yOffset="Measure:N",
        color=alt.Color("Measure:N", title="",
                        scale=alt.Scale(range=["#2C5F2D", "#C2662D"]),
                        legend=alt.Legend(orient="bottom")),
        tooltip=["Row", "Measure", "Years"]).properties(height=alt.Step(34)),
        use_container_width=True)
    st.caption("The calculated life against the life being claimed. Bars are capped at three "
               "times the required life so that very long lives do not flatten the chart.")

    if not summ["all_pass"]:
        st.warning("At least one material failed the durability check, so the values above are "
                   "incomplete. Correct those rows before quoting these numbers.")

    d1, d2 = st.columns(2)
    d1.download_button("Download the component results (CSV)",
                       data=detail.to_csv(index=False).encode("utf-8"),
                       file_name="durability_detail_%s.csv" % proj_label,
                       mime="text/csv", use_container_width=True)
    d2.download_button("Download the material results (CSV)",
                       data=mat_res.to_csv(index=False).encode("utf-8"),
                       file_name="carbon_efficiency_%s.csv" % proj_label,
                       mime="text/csv", use_container_width=True)

    # ------------------------------------------------------------ saving
    st.markdown("---")
    if proj_id:
        st.markdown("#### 7. Save this assessment as a version")
        v1, v2 = st.columns([3, 1])
        with v1:
            version_name = st.text_input(
                "Version name:", value="", key="sl_version_name",
                placeholder="e.g. Coastal XS1 with 50 mm cover",
                help="Give this assessment a name you will recognise later. Saving always "
                     "creates a new version and never overwrites an earlier one.")
        with v2:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
            do_save = st.button("Save", key="sl_save", use_container_width=True)
        if do_save:
            clean_version_name = version_name.strip()
            if not clean_version_name:
                st.error("Give this version a name before saving.")
            else:
                payload = {
                    "user_id": st.session_state.user_id,
                    "project_id": proj_id,
                    "project_name": proj_label,
                    "version_name": clean_version_name,
                    "exposure_class": exposure_class,
                    "mechanism": mechanism,
                    "settings": {"k1": k1_value, "k2": k2_value,
                                 "surface_chloride": surface_chloride,
                                 "cover_allowance": cover_allowance,
                                 "special_quality_control": bool(special_qc),
                                 "design_life": design_life},
                    "inputs": edited.fillna(0).to_dict("records"),
                    "detail": detail.replace([float("inf")], 1e12).fillna(0).to_dict("records"),
                    "materials": mat_res.replace([float("inf")], 1e12).fillna(0).to_dict("records"),
                    "summary": summ,
                }
                try:
                    supabase.table("service_life_runs").insert(payload).execute()
                    try:
                        supabase.table("saved_projects").update(
                            {"service_life_data": {"exposure_class": exposure_class,
                                                   "mechanism": mechanism,
                                                   "summary": summ,
                                                   "materials": payload["materials"]}}
                        ).eq("id", proj_id).execute()
                    except Exception:
                        pass
                    st.session_state.sl_saved_flash = (
                        "The assessment named %s has been saved against %s. You will find it in "
                        "My Library and in the list at the top of this page."
                        % (payload["version_name"], proj_label))
                    _clear_page_state()
                    st.rerun()
                except Exception as e:
                    st.error("The assessment could not be saved. Create the service_life_runs "
                             "table in Supabase using the statement in the setup notes. "
                             "Details: %s" % e)
    else:
        st.caption("Save the project first, from Project Design, if you want to store "
                   "this assessment and use it in the project comparison.")


# ---------------------------------------------------------------------------
# My Library section for saved assessments
# ---------------------------------------------------------------------------
def render_library_assessments(supabase, db, user_mixes, factors_df,
                               calc_mix_carbon, calculate_project_data):
    """The third view of My Library, listing every saved assessment."""
    runs = load_runs(supabase)
    if not runs:
        st.info("No assessments have been saved yet. Open the Durability and Performance "
                "page, run an assessment and press Save.")
        return

    overview = runs_overview(runs)
    st.markdown("#### All saved assessments")
    show_table(overview)

    labels = ["%s  (%s)" % (r.get("version_name", "unnamed"), r.get("project_name", ""))
              for r in runs]
    pick = st.selectbox("Open an assessment:", ["Select an assessment"] + labels,
                        key="lib_run_pick")
    if pick == "Select an assessment":
        st.info("Choose a saved assessment from the list above to see its full results.")
        return
    run = runs[labels.index(pick)]

    st.markdown("### %s" % run.get("version_name", "unnamed"))
    st.caption("Project %s, exposure class %s, %s model."
               % (run.get("project_name", ""), run.get("exposure_class", ""),
                  str(run.get("mechanism", "")).lower()))

    summ = run.get("summary") or {}
    m1, m2, m3 = st.columns(3)
    m1.metric("Concrete volume", "{:,.2f} m3".format(sf(summ.get("total_volume"))))
    m2.metric("Total embodied carbon",
              "{:,.3f} tonne CO2e".format(sf(summ.get("total_carbon", summ.get("total_eic")))))
    m3.metric("Sum of the material values",
              "{:,.2f}".format(sf(summ.get("sum_index", summ.get("sum_csepp")))))

    mats = pd.DataFrame(run.get("materials") or [])
    if not mats.empty:
        st.markdown("**Carbon efficiency for each material**")
        show_table(mats, highlight=["Durability check", INDEX_COLUMN])
        if INDEX_COLUMN in mats.columns:
            chart = mats[["Material", INDEX_COLUMN]].rename(columns={INDEX_COLUMN: "Index"})
            chart = chart[chart["Index"] > 0]
            if not chart.empty:
                st.altair_chart(
                    alt.Chart(chart).mark_bar(cornerRadiusEnd=4, color="#2C5F2D").encode(
                        x=alt.X("Index:Q", title="Carbon efficiency index"),
                        y=alt.Y("Material:N", sort="-x", title=""),
                        tooltip=["Material", "Index"]).properties(height=alt.Step(42)),
                    use_container_width=True)

    det = pd.DataFrame(run.get("detail") or [])
    if not det.empty:
        with st.expander("Durability check for each component"):
            show_table(det, highlight=["Calculated design life (years)", "Durability check"])

    with st.expander("The inputs that produced this assessment"):
        inputs = pd.DataFrame(run.get("inputs") or [])
        if not inputs.empty:
            show_table(inputs)

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("Download this assessment (CSV)",
                           data=(mats if not mats.empty else overview).to_csv(index=False)
                           .encode("utf-8"),
                           file_name="assessment_%s.csv" % run.get("version_name", "run"),
                           mime="text/csv", use_container_width=True)
    with c2:
        del_key = "del_run_%s" % run.get("id")
        if not st.session_state.get(del_key, False):
            st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
            if st.button("Delete this assessment", key="btn_%s" % del_key,
                         use_container_width=True):
                st.session_state[del_key] = True
                st.rerun()
        else:
            st.error("Are you sure? This cannot be undone.")
            y, n = st.columns(2)
            with y:
                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                if st.button("Yes, delete", key="yes_%s" % del_key):
                    try:
                        supabase.table("service_life_runs").delete() \
                            .eq("id", run.get("id")).execute()
                        st.session_state[del_key] = False
                        st.success("The assessment has been deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error("Could not delete. Details: %s" % e)
            with n:
                if st.button("Cancel", key="no_%s" % del_key):
                    st.session_state[del_key] = False
                    st.rerun()


# ---------------------------------------------------------------------------
# shared helper, also used by comparison.py
# ---------------------------------------------------------------------------
def rebuild_draft(p):
    """Rebuild the component structure from a saved project record."""
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

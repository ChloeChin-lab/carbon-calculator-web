import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os 
import requests
from io import BytesIO
import altair as alt
import uuid

# New modules: service life / CSEPP engine and the comparison workflows
import service_life as sl
import comparison as cmp_mod

# Try to load FPDF for PDF generation. If it is not installed, the app won't crash.
try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False

# Sets the browser tab title and forces the app to use the full width of the screen
st.set_page_config(page_title="Sustainability Assessment System", layout="wide")

# Custom CSS to style all the buttons and tables so they look like a professional dashboard
st.markdown("""
<style>
/* Primary Button Default (Blue) */
div[data-testid="stButton"] > button[kind="primary"],
div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background-color: #3b82f6;
    color: white;
    padding: 10px 20px;
    font-size: 16px;
    font-weight: bold;
    border-radius: 6px;
    border: none;
}
div[data-testid="stButton"] > button[kind="primary"]:hover,
div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
    background-color: #2563eb;
}

/* Green Save Buttons (Triggered by a hidden html span) */
div.element-container:has(span.btn-green) + div.element-container button {
    background-color: #10b981 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
div.element-container:has(span.btn-green) + div.element-container button:hover {
    background-color: #059669 !important;
}

/* Red Delete/Remove Buttons */
div.element-container:has(span.btn-red) + div.element-container button {
    background-color: #ef4444 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
div.element-container:has(span.btn-red) + div.element-container button:hover {
    background-color: #dc2626 !important;
}

/* Blue Action/Calculate Buttons */
div.element-container:has(span.btn-blue) + div.element-container button {
    background-color: #3b82f6 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
div.element-container:has(span.btn-blue) + div.element-container button:hover {
    background-color: #2563eb !important;
}

/* Grey Clone/Duplicate Buttons */
div.element-container:has(span.btn-grey) + div.element-container button {
    background-color: #64748b !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
div.element-container:has(span.btn-grey) + div.element-container button:hover {
    background-color: #475569 !important;
}

/* Style static tables to look like a clean engineering report */
.stTable {
    background-color: white;
}
th {
    background-color: #e0e0e0 !important;
    color: black !important;
    font-weight: bold !important;
    text-align: center !important;
}
</style>
""", unsafe_allow_html=True)

# Grab the secret passwords from the Streamlit Cloud environment to access the database
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

# Create the database connection once and cache it so the app runs faster
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# Set up the background memory (session state) so the app remembers who is logged in and what page they are on
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "current_page" not in st.session_state:
    st.session_state.current_page = "Home"
if "mix_mode_radio" not in st.session_state:
    st.session_state.mix_mode_radio = "View Standard Materials"

# RESET COUNTERS: The secret to flawless form clearing!
if "mix_reset_counter" not in st.session_state:
    st.session_state.mix_reset_counter = 0
if "project_reset_counter" not in st.session_state:
    st.session_state.project_reset_counter = 0

# Background memory specifically for the Project Design tab so it doesn't wipe when you click away
if "draft_proj_name" not in st.session_state:
    st.session_state.draft_proj_name = ""
if "draft_structure" not in st.session_state:
    st.session_state.draft_structure = "---"
if "draft_components" not in st.session_state:
    st.session_state.draft_components = []
if "project_results_df" not in st.session_state:
    st.session_state.project_results_df = None
if "project_totals" not in st.session_state:
    st.session_state.project_totals = None
if "project_clean_data" not in st.session_state:
    st.session_state.project_clean_data = []
# The id of whatever project is currently loaded in the Project Design tab,
# once it has actually been saved to the database. None means the project on
# screen has never been saved, so there is nothing yet for Durability and
# Performance to attach an assessment to.
if "current_project_id" not in st.session_state:
    st.session_state.current_project_id = None

def generate_pdf_report(df, best, worst, savings):
    """Generates a downloadable PDF report for the material comparison tab."""
    if not HAS_FPDF:
        return None
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "Sustainability Comparison Report", ln=True, align='C')
        pdf.set_font("Arial", '', 12)
        pdf.ln(10)
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, "Executive Summary", ln=True)
        pdf.set_font("Arial", '', 11)
        summary = (f"This comparative analysis evaluates the Embodied Carbon Intensity (ECI) across selected materials. "
                   f"Choosing the optimal material ({best['Material']}) instead of the highest-impact option ({worst['Material']}) "
                   f"results in a {savings:.1f}% reduction in environmental impact per cubic metre. "
                   f"For large-scale infrastructure applications, this material substitution represents a highly effective decarbonisation strategy.")
        pdf.multi_cell(0, 6, summary)
        pdf.ln(10)
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, "Data Summary", ln=True)
        pdf.set_font("Arial", '', 10)
        for _, row in df.iterrows():
            pdf.cell(0, 6, f"- {row['Material']}: Mass: {row['Total Mass (kg/m³)']:.2f} kg/m³ | GWP100: {row['Total GWP100 (kgCO2e/m³)']:.2f} kgCO2e/m³", ln=True)
            
        return pdf.output(dest='S').encode('latin-1')
    except Exception:
        return None

def clean_df(df):
    """Safely removes invisible spaces from Excel headers and text cells so the math engine doesn't break."""
    if isinstance(df, pd.DataFrame) and not df.empty:
        df.columns = df.columns.str.strip()
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
    return df

def safe_float(val, default=0.0):
    """Safely handles text, N/A, dashes, or blanks in Excel cells, converting them to zero instead of crashing."""
    if pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def _pack_database(xls):
    """Maps every worksheet in the workbook onto the internal database keys.
    Missing sheets simply come back empty, so adding a new tab never breaks the app."""
    def g(name):
        return clean_df(xls.get(name, pd.DataFrame()))
    return {
        # --- original tabs ---
        "factors":    g("Component_Factors"),
        "mixes":      g("Mix_Designs"),
        "structures": g("Project_Structures"),
        "unit_logic": g("Unit_Logic"),
        "direct":     g("Direct_Results"),
        # --- service life / durability reference tabs ---
        "strength_classes":          g("Strength_Classes"),
        "carbonation_k400":          g("Carbonation_k400"),
        "carbonation_k400_defaults": g("Carbonation_k400_Defaults"),
        "location_k1":               g("Location_k1"),
        "exposure_classes":          g("Exposure_Classes"),
        "chloride_ctl":              g("Chloride_CTL"),
        "chloride_dc":               g("Chloride_Dc"),
        "binder_mapping":            g("Binder_Mapping"),
        "cover_requirements":        g("Cover_Requirements"),
        "structural_class_rules":    g("Structural_Class_Rules"),
        "column_descriptions":       g("Column_Descriptions"),
    }

@st.cache_data(ttl=600, show_spinner="Loading materials database...")
def load_database():
    """Pulls the master data from Google Sheets (or a local file if offline).
    Always returns a dict; '_source' is None when nothing could be loaded and
    '_errors' explains exactly why."""
    errors = []

    if not SHEET_ID:
        errors.append("The GOOGLE_SHEET_ID environment variable is not set on this server.")
    elif len(SHEET_ID) <= 20:
        errors.append("GOOGLE_SHEET_ID is set but looks too short to be a real sheet ID.")
    else:
        export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
        for attempt in (1, 2):
            try:
                response = requests.get(export_url, timeout=45)
                if response.status_code != 200:
                    errors.append(f"Attempt {attempt}: Google Sheets returned HTTP "
                                  f"{response.status_code}.")
                    continue
                ctype = str(response.headers.get("content-type", "")).lower()
                if "html" in ctype:
                    errors.append("Google Sheets returned a sign in page instead of the file. "
                                  "The sheet is not shared as Anyone with the link, Viewer.")
                    break
                xls = pd.read_excel(BytesIO(response.content), sheet_name=None)
                data = _pack_database(xls)
                data["_source"] = "Google Sheets"
                data["_sheets"] = list(xls.keys())
                data["_errors"] = errors
                return data
            except Exception as e:
                errors.append(f"Attempt {attempt}: {type(e).__name__}: {e}")

    local_path = "materials_database.xlsx"
    if os.path.exists(local_path):
        try:
            xls = pd.read_excel(local_path, sheet_name=None)
            data = _pack_database(xls)
            data["_source"] = "Local file (materials_database.xlsx)"
            data["_sheets"] = list(xls.keys())
            data["_errors"] = errors
            return data
        except Exception as e:
            errors.append(f"Local fallback file failed: {type(e).__name__}: {e}")
    else:
        errors.append("No local materials_database.xlsx fallback exists in the repository.")

    return {"_source": None, "_sheets": [], "_errors": errors}

def wipe_project_form_memory():
    """Forces the Project Design form to completely clear by advancing the reset counter."""
    st.session_state.project_reset_counter += 1
    st.session_state.draft_proj_name = ""
    st.session_state.draft_structure = "---"
    st.session_state.draft_components = []
    st.session_state.project_results_df = None
    st.session_state.project_totals = None
    st.session_state.project_clean_data = []
    st.session_state.current_project_id = None
    for k in ("sl_detail", "sl_materials", "sl_table", "sl_sig", "sl_alloc"):
        if k in st.session_state:
            st.session_state[k] = None

def wipe_mix_form_memory():
    """Forces the Custom Mix form to completely clear by advancing the reset counter."""
    st.session_state.mix_reset_counter += 1
    st.session_state.adhoc_mats = pd.DataFrame(columns=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"])
    st.session_state.show_mix_preview = False
    
    if "draft_mix_name" in st.session_state:
        st.session_state.draft_mix_name = ""
    if "draft_mix_cat" in st.session_state:
        st.session_state.draft_mix_cat = "--- Select Category ---"
    if "draft_mix_comps" in st.session_state:
        st.session_state.draft_mix_comps = {}

def load_project_to_session(p_data, db):
    """Loads a saved project from My Library safely into the Project Design tab for editing."""
    st.session_state.current_page = "Project Design"
    wipe_project_form_memory()
    
    st.session_state.draft_proj_name = f"{p_data['project_name']} (Copy)"
    st.session_state.draft_structure = p_data['structure_type']
    
    known_components = []
    if db is not None and not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
        known_components = db["unit_logic"]["Component_Name"].dropna().astype(str).str.strip().tolist()
        
    new_draft = []
    raw_comp_data = p_data.get("component_data", [])
    
    if isinstance(raw_comp_data, dict):
        converted_list = []
        for c_name, c_details in raw_comp_data.items():
            converted_list.append({
                "component_name": c_name,
                "multiplier_count": 1,
                "materials": [{
                    "label": "",
                    "quantity": c_details.get("quantity", 0.0),
                    "unit": c_details.get("unit", "m3"),
                    "ref_value": c_details.get("ref_value", 0.0),
                    "ref_per_unit": c_details.get("ref_per_unit", False),
                    "assigned_mix": c_details.get("assigned_mix", "--- Select ---")
                }]
            })
        raw_comp_data = converted_list
        
    for c_data in raw_comp_data:
        c_name = c_data.get("component_name", "Unknown")
        b_name = c_data.get("base_name") 
        
        if not b_name:
            b_name = "Extra" 
            for kc in known_components:
                if kc.lower() in c_name.lower():
                    b_name = kc
                    break
        
        mats = []
        for m_data in c_data.get("materials", []):
            mats.append({
                "id": str(uuid.uuid4()),
                "label": m_data.get("label", ""),
                "qty": m_data.get("quantity", 0.0),
                "unit": m_data.get("unit", "m3"),
                "ref_value": m_data.get("ref_value", 0.0),
                "ref_per_unit": m_data.get("ref_per_unit", False),
                "mix": m_data.get("assigned_mix", "--- Select ---")
            })
            
        new_draft.append({
            "id": str(uuid.uuid4()),
            "base_name": b_name if "Extra" not in b_name else "Extra",
            "custom_name": c_name,
            "count": c_data.get("multiplier_count", 1),
            "materials": mats
        })
        
    st.session_state.draft_components = new_draft

def load_mix_to_session(m_data):
    """Loads a saved mix from My Library safely into the Materials & Mixes builder."""
    st.session_state.current_page = "Materials & Mixes"
    st.session_state.mix_mode_radio = "Create Custom Material / Mix"
    wipe_mix_form_memory()
    
    st.session_state.draft_mix_name = f"{m_data['mix_name']} (Copy)"
    st.session_state.draft_mix_cat = m_data['category']
    st.session_state.draft_mix_comps = m_data.get("components", {})
    
    adhoc_list = m_data.get("adhoc_materials", [])
    if adhoc_list:
        st.session_state.adhoc_mats = pd.DataFrame(adhoc_list)

def get_unit_logic_type(unit_string):
    """Reads the dropdown unit text (e.g. '% by weight') and returns a strict logic code for the math engine."""
    s = str(unit_string).lower()
    if "%" in s:
        if "wt" in s or "weight" in s: return "PERCENT_WEIGHT"
        return "PERCENT_VOL"
    if "/ unit" in s: return "PER_UNIT"
    if "l/m3" in s: return "LITER_PER_M3" 
    if s.strip() == "l" or s.strip() == "liters": return "BASIC_LITER"
    return "BASIC"

def calculate_mix_carbon(mix_name, db, user_mixes, factors_df):
    """Searches the database for a material name and calculates its Density (Mass) and GWP100 Carbon Factor."""
    m_mass, m_gwp = 0.0, 0.0
    
    if mix_name.startswith("Custom: "):
        mix_n = mix_name.replace("Custom: ", "")
        match_mix = next((m for m in user_mixes if m["mix_name"] == mix_n), None)
        if match_mix:
            if match_mix.get("components"):
                for c_name, c_val in match_mix["components"].items():
                    c_val = safe_float(c_val)
                    if c_name in factors_df.index:
                        factor_row = factors_df.loc[c_name]
                        m_gwp += c_val * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                    m_mass += c_val
                    
            if match_mix.get("adhoc_materials"):
                for adhoc in match_mix["adhoc_materials"]:
                    q = safe_float(adhoc.get("Quantity", 0))
                    m_mass += q
                    m_gwp += q * safe_float(adhoc.get("GWP100 (kgCO2e/kg)", 0))
    else:
        match_df = db["mixes"][db["mixes"]["Mix_Key"] == mix_name] if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else pd.DataFrame()
        if not match_df.empty:
            mix_row = match_df.iloc[0]
            for comp_factor in factors_df.index:
                if comp_factor in mix_row and pd.notna(mix_row[comp_factor]):
                    val = safe_float(mix_row[comp_factor])
                    factor_row = factors_df.loc[comp_factor]
                    m_mass += val
                    m_gwp += val * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
        else:
            match_direct = db["direct"][db["direct"]["Material_Key"] == mix_name] if not db["direct"].empty and "Material_Key" in db["direct"].columns else pd.DataFrame()
            if not match_direct.empty:
                direct_row = match_direct.iloc[0]
                m_mass = safe_float(direct_row.get("Total_Mass_kg_m3", 1.0)) 
                if m_mass == 0: m_mass = 1.0 
                
                m_gwp = safe_float(direct_row.get("GWP100_kgCO2e_m3", 0.0))
                if m_gwp == 0.0: m_gwp = safe_float(direct_row.get("ECFGWP100_kgCO2e_kg", 0.0)) * m_mass
                    
    return {
        "Mass (kg/m3)": m_mass,
        "Factor_GWP (kgCO2e/kg)": (m_gwp / m_mass) if m_mass > 0 else 0
    }

def calculate_project_data(draft_components, db, user_mixes, factors_df):
    """The master engineering engine that calculates total quantities, mass, volume and carbon for an entire project."""
    results_list = []
    grand_totals = {"mass": 0.0, "gwp": 0.0, "volume": 0.0}
    clean_project_data = []

    for comp_idx, comp in enumerate(draft_components):
        c_name = comp.get("custom_name", comp.get("base_name", "Unknown"))
        c_multiplier = int(comp.get("count", 1))
        c_materials = []

        for mat in comp.get("materials", []):
            qty = safe_float(mat.get("qty", 0.0))
            unit_str = mat.get("unit", "")
            mix = mat.get("mix", "--- Select ---")
            ref_val = safe_float(mat.get("ref_value", 0.0))
            ref_per_unit = mat.get("ref_per_unit", False)
            logic_type = get_unit_logic_type(unit_str)
            
            if mix != "--- Select ---" and qty > 0:
                props = calculate_mix_carbon(mix, db, user_mixes, factors_df)
                mass_per_m3 = props["Mass (kg/m3)"]
                total_mass_kg = 0.0
                
                if logic_type == "PERCENT_VOL" or logic_type == "LITER_PER_M3" or logic_type == "PERCENT_WEIGHT":
                    actual_ref_val = (ref_val * c_multiplier) if ref_per_unit else ref_val
                    if logic_type == "PERCENT_VOL":
                        vol_m3 = (qty / 100.0) * actual_ref_val
                        total_mass_kg = vol_m3 * mass_per_m3
                    elif logic_type == "LITER_PER_M3":
                        vol_L = qty * actual_ref_val
                        total_mass_kg = (vol_L / 1000.0) * mass_per_m3
                    elif logic_type == "PERCENT_WEIGHT":
                        weight_tonnes = (qty / 100.0) * actual_ref_val
                        total_mass_kg = weight_tonnes * 1000.0
                elif logic_type in ["PER_UNIT", "BASIC", "BASIC_LITER"]:
                    base_vol = qty * c_multiplier if logic_type == "PER_UNIT" else qty
                    if "tonne" in unit_str.lower():
                        total_mass_kg = base_vol * 1000.0
                    elif "kg" in unit_str.lower():
                        total_mass_kg = base_vol
                    elif logic_type == "BASIC_LITER":
                        total_mass_kg = (base_vol / 1000.0) * mass_per_m3
                    else:
                        total_mass_kg = base_vol * mass_per_m3

                item_gwp = total_mass_kg * props["Factor_GWP (kgCO2e/kg)"]
                total_vol_m3 = (total_mass_kg / mass_per_m3) if mass_per_m3 > 0 else 0.0

                grand_totals["mass"] += total_mass_kg
                grand_totals["gwp"] += item_gwp
                grand_totals["volume"] += total_vol_m3
                item_label = f"{comp_idx + 1}. {c_name} {mat.get('label', '')}".strip()
                
                if logic_type in ["PERCENT_VOL", "PERCENT_WEIGHT", "LITER_PER_M3"]:
                    mult_tag = " × Qty" if ref_per_unit else ""
                    display_qty = f"{qty} (Ref: {ref_val}{mult_tag})"
                else:
                    display_qty = f"{qty}"
                
                results_list.append({
                    "Item": item_label,
                    "Component": c_name,
                    "Material": mix,
                    "Volume/Amount": display_qty, 
                    "Unit": unit_str,
                    "Total Volume (m³)": total_vol_m3,
                    "Total Mass (kg)": total_mass_kg,
                    "Total GWP100 (kgCO2e)": item_gwp
                })
                
            c_materials.append({
                "label": mat.get("label", ""),
                "quantity": qty,
                "unit": unit_str,
                "ref_value": ref_val,
                "ref_per_unit": ref_per_unit,
                "assigned_mix": mix
            })
                
        clean_project_data.append({
            "base_name": comp.get("base_name", "Extra"),
            "component_name": c_name,
            "multiplier_count": c_multiplier,
            "materials": c_materials
        })
    
    results_df = pd.DataFrame(results_list) if len(results_list) > 0 else None
    return results_df, grand_totals, clean_project_data

def render_results_table_and_totals(df, totals):
    """Draws the standard engineering results table, index starting at 1."""
    display_df = df.copy().reset_index(drop=True)
    if "Component" in display_df.columns:
        display_df = display_df.drop(columns=["Component"])
    display_df.index = display_df.index + 1 
    
    if "Total Volume (m³)" in display_df.columns:
        display_df["Total Volume (m³)"] = display_df["Total Volume (m³)"].apply(lambda x: f"{float(x):,.3f}")
    display_df["Total Mass (kg)"] = display_df["Total Mass (kg)"].apply(lambda x: f"{float(x):,.2f}")
    display_df["Total GWP100 (kgCO2e)"] = display_df["Total GWP100 (kgCO2e)"].apply(lambda x: f"{float(x):,.2f}")
    
    st.table(display_df)
    
    vol_row = ""
    if "volume" in totals:
        vol_row = (f'<tr><td style="font-weight: bold; width: 250px; padding: 8px 0;">'
                   f'Total Volume:</td><td>{totals["volume"]:,.3f} m³</td></tr>')

    totals_html = f"""
    <div style="border: 1px solid #d3d3d3; border-radius: 5px; padding: 20px; background-color: #f9f9f9; margin-bottom: 20px;">
        <h4 style="margin-top: 0; color: #000; font-family: sans-serif;">Project Grand Totals</h4>
        <table style="width: 100%; border-collapse: collapse; font-size: 16px; color: #000; font-family: sans-serif;">
            {vol_row}
            <tr><td style="font-weight: bold; width: 250px; padding: 8px 0;">Total Mass:</td><td>{totals['mass']:,.2f} kg</td></tr>
            <tr><td style="font-weight: bold; padding: 8px 0; background-color: #f0f0f0;">Total GWP100:</td><td style="background-color: #f0f0f0;">{totals['gwp']:,.2f} kgCO2e</td></tr>
        </table>
    </div>
    """
    st.markdown(totals_html, unsafe_allow_html=True)

def login_page():
    """Draws the secure login screen."""
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    
    with col2:
        st.markdown("""
        <div style="text-align: center; padding-bottom: 20px;">
            <h1 style="font-size: 36px; margin-bottom: 5px;">Sustainability Assessment System</h1>
            <p style="font-size: 16px; opacity: 0.8;">Please log in to access.</p>
        </div>
        """, unsafe_allow_html=True)
        
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Secure Log In", use_container_width=True):
            try:
                response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user_id = response.user.id
                st.session_state.user_email = response.user.email
                st.session_state.current_page = "Home"
                st.rerun() 
            except Exception:
                st.error("Invalid email or password. Please contact your administrator for access.")

def database_error_screen(db):
    """Explains exactly why the materials database could not be loaded."""
    st.error("Cannot load the materials database.")
    st.markdown("**What the server reported:**")
    for e in (db.get("_errors") or ["No diagnostic information available."]):
        st.markdown(f"- {e}")
    st.markdown("""
**Most common causes, in order:**

1. **The Google Sheet is not shared publicly.** Open the sheet → Share → General access →
   *Anyone with the link* → *Viewer*. The app downloads the file anonymously, so a sheet
   restricted to your account returns a sign in page instead of a spreadsheet.
2. **The GOOGLE_SHEET_ID environment variable is missing or wrong on this server.**
   It is the long code between /d/ and /edit in the sheet address.
3. **A slow or blocked request.** Google occasionally rate-limits the export endpoint.
   Press Retry below; if it works on the second try, this was the cause.

This is not a Supabase problem. You are logged in, so Supabase is working, and your Supabase
free tier has nothing to do with the spreadsheet.
""")
    if st.button("Retry loading the database", type="primary"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

def welcome_dashboard():
    """Draws the home screen with the five main feature portals."""
    username = st.session_state.user_email.split('@')[0].capitalize() if st.session_state.user_email else "User"
    st.markdown(f"""
    <div style="padding: 40px; background: linear-gradient(135deg, #1e293b, #0f172a); border-radius: 12px; margin-bottom: 30px; color: white; border: 1px solid #334155;">
        <h1 style="margin-top: 0; color: white;">Welcome, {username}!</h1>
        <p style="font-size: 18px; color: #cbd5e1; max-width: 800px;">
            Manage your structural material libraries, assess project environmental impact, verify durability
            and design life, and optimise engineering designs for maximum sustainability.
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div style="background-color: #F0F4F8; padding: 20px; border-radius: 8px; border-top: 4px solid #3498DB; height: 150px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Materials & Mixes</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The master library. Configure ingredients, build custom mixes, and review properties.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_mats", use_container_width=True):
            st.session_state.current_page = "Materials & Mixes"
            st.rerun()
        
    with col2:
        st.markdown("""
        <div style="background-color: #E8F8F5; padding: 20px; border-radius: 8px; border-top: 4px solid #1ABC9C; height: 150px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Project Design</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The structural assembly. Configure components, assign materials, and generate assessments.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_proj", use_container_width=True):
            st.session_state.current_page = "Project Design"
            st.rerun()
        
    with col3:
        st.markdown("""
        <div style="background-color: #FEF5E7; padding: 20px; border-radius: 8px; border-top: 4px solid #E67E22; height: 150px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Durability and Performance</h3>
            <p style="color: #5D6D7E; font-size: 14px;">Durability engine. Carbonation and chloride design life, then the carbon efficiency index.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_sl", use_container_width=True):
            st.session_state.current_page = "Durability and Performance"
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    col4, col5, col6 = st.columns(3)
    with col4:
        st.markdown("""
        <div style="background-color: #F4ECF7; padding: 20px; border-radius: 8px; border-top: 4px solid #8E44AD; height: 150px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Comparison & Analysis</h3>
            <p style="color: #5D6D7E; font-size: 14px;">Benchmark mixes against mixes, and complete projects against each other on carbon and carbon efficiency.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_cmp", use_container_width=True):
            st.session_state.current_page = "Comparison and Analysis"
            st.rerun()

    with col5:
        st.markdown("""
        <div style="background-color: #F8F9F9; padding: 20px; border-radius: 8px; border-top: 4px solid #95A5A6; height: 150px;">
            <h3 style="color: #2C3E50; margin-top: 0;">My Library</h3>
            <p style="color: #5D6D7E; font-size: 14px;">Your historical database. Review, analyse, and manage your saved projects and custom mixes.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_saved", use_container_width=True):
            st.session_state.current_page = "My Library"
            st.rerun()

    with col6:
        st.markdown("")

def main_application():
    """The master router."""
    db = load_database()
    
    if not db or not db.get("_source"):
        database_error_screen(db or {})

    if db["factors"].empty and db["mixes"].empty and db["direct"].empty:
        st.error(f"The database loaded from {db['_source']} but contains no material data.")
        st.caption(f"Worksheets found: {', '.join(db.get('_sheets', [])) or 'none'}")
        st.caption("Check that the tab names are exactly Component_Factors, Mix_Designs, "
                   "Project_Structures, Unit_Logic and Direct_Results.")
        if st.button("Retry loading the database", type="primary"):
            st.cache_data.clear()
            st.rerun()
        st.stop()

    if st.session_state.current_page == "Home":
        st.sidebar.caption(f"User: {st.session_state.user_email}")
        st.sidebar.caption(f"Database: {db['_source']}")
        if st.sidebar.button("Log Out"):
            st.session_state.user_id = None
            st.session_state.current_page = "Home"
            st.rerun()
        welcome_dashboard()
        return

    if st.sidebar.button("Return to Home"):
        st.session_state.current_page = "Home"
        st.rerun()

    st.sidebar.markdown("---")
    
    nav_options = ["Materials & Mixes", "Project Design", "Durability and Performance",
                   "Comparison and Analysis", "My Library"]
    current_idx = nav_options.index(st.session_state.current_page) if st.session_state.current_page in nav_options else 0
    
    selected_nav = st.sidebar.radio("Navigation", nav_options, index=current_idx, label_visibility="collapsed")
    
    if selected_nav != st.session_state.current_page:
        st.session_state.current_page = selected_nav
        st.rerun()
    
    st.sidebar.markdown("---")
    st.sidebar.caption(f"User: {st.session_state.user_email}")
    st.sidebar.caption(f"Database: {db['_source']}")
        
    if st.sidebar.button("Log Out"):
        st.session_state.user_id = None
        st.session_state.current_page = "Home"
        st.rerun()

    st.title(st.session_state.current_page)
        
    user_mixes_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user_id).execute()
    user_mixes = user_mixes_res.data if user_mixes_res.data else []
    custom_mix_names = [m["mix_name"] for m in user_mixes]
    
    mix_mats = db["mixes"]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
    direct_mats = db["direct"]["Material_Key"].dropna().tolist() if not db["direct"].empty and "Material_Key" in db["direct"].columns else []
    standard_mixes = sorted(list(set(mix_mats + direct_mats)))
    all_available_mixes = standard_mixes + [f"Custom: {name}" for name in custom_mix_names]
    factors_df = db["factors"].drop_duplicates(subset=["Component"]).set_index("Component") if not db["factors"].empty and "Component" in db["factors"].columns else pd.DataFrame()

    if st.session_state.get("execute_mix_save") and st.session_state.current_page == "Materials & Mixes":
        payload = st.session_state.mix_payload_draft
        try:
            if st.session_state.get("existing_mix_id"):
                supabase.table("user_mixes").update(payload).eq("id", st.session_state.existing_mix_id).execute()
                msg = f"Mix '{payload['mix_name']}' successfully overwritten!"
            else:
                supabase.table("user_mixes").insert(payload).execute()
                msg = f"Custom item '{payload['mix_name']}' saved successfully!"
            
            st.session_state.mix_success_message = msg
            st.session_state.execute_mix_save = False
            st.session_state.existing_mix_id = None
            
            wipe_mix_form_memory() 
            st.rerun()
        except Exception as e:
            st.error(f"Database Save Error: Details: {e}")
            st.session_state.execute_mix_save = False
            
    if st.session_state.get("execute_save") and st.session_state.current_page == "Project Design":
        project_payload = {
            "user_id": st.session_state.user_id,
            "project_name": st.session_state.draft_proj_name,
            "structure_type": st.session_state.draft_structure,
            "total_embodied_carbon": st.session_state.project_totals['gwp'],
            "component_data": st.session_state.project_clean_data
        }
        try:
            if st.session_state.get("existing_proj_id"):
                supabase.table("saved_projects").update(project_payload).eq("id", st.session_state.existing_proj_id).execute()
                st.session_state.current_project_id = st.session_state.existing_proj_id
                msg = f"Project '{st.session_state.draft_proj_name}' successfully overwritten and updated!"
            else:
                insert_res = supabase.table("saved_projects").insert(project_payload).execute()
                st.session_state.current_project_id = insert_res.data[0]["id"] if insert_res.data else None
                msg = f"Project '{st.session_state.draft_proj_name}' saved successfully to your account!"

            st.session_state.proj_success_message = msg
            st.session_state.execute_save = False
            st.session_state.existing_proj_id = None

            # Note: we deliberately do NOT wipe the form/results here anymore.
            # The project is now saved (current_project_id is set), and the
            # calculated results stay on screen so the "Current Project" data
            # source on the Durability and Performance page has something to
            # attach a saved assessment to. Use "Clear All & Start Over" to
            # start a fresh, blank project.
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save project. Error: {e}")
            st.session_state.execute_save = False

    if st.session_state.current_page == "Materials & Mixes":
        
        default_mode_idx = 0
        if st.session_state.get("mix_mode_radio") == "Create Custom Material / Mix":
            default_mode_idx = 1
            
        mode = st.radio("Choose an action:", ["View Standard Materials", "Create Custom Material / Mix"], horizontal=True, index=default_mode_idx, key="mix_mode_radio_ui")
        
        if st.session_state.mix_mode_radio != mode:
            st.session_state.mix_mode_radio = mode

        st.caption("Looking for the mix comparison tool? It now lives in the "
                   "Comparison and Analysis page, together with project comparison.")
        
        mix_cats = set(db["mixes"]["Category"].dropna().unique()) if not db["mixes"].empty and "Category" in db["mixes"].columns else set()
        direct_cats = set(db["direct"]["Category"].dropna().unique()) if not db["direct"].empty and "Category" in db["direct"].columns else set()
        all_categories = sorted(list(mix_cats.union(direct_cats)))
        
        if mode == "View Standard Materials":
            st.markdown("#### View Standard Material Properties")
            
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                selected_cat = st.selectbox("Material Category:", ["--- Select Category ---"] + all_categories, key="view_cat")
            
            if selected_cat != "--- Select Category ---":
                cat_mix_mats = db["mixes"][db["mixes"]["Category"] == selected_cat]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
                cat_direct_mats = db["direct"][db["direct"]["Category"] == selected_cat]["Material_Key"].dropna().tolist() if not db["direct"].empty and "Material_Key" in db["direct"].columns else []
                cat_all_mats = sorted(list(set(cat_mix_mats + cat_direct_mats)))
                
                with col_sel2:
                    selected_mat = st.selectbox("Material Type/Grade:", ["--- Select Material ---"] + cat_all_mats, key="view_mat")
                
                if selected_mat != "--- Select Material ---":
                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                    if st.button("View Material Properties", type="primary"):
                        is_mix = selected_mat in cat_mix_mats
                        
                        final_props = {
                            "Total_Mass_kg_m3": 0,
                            "ECFGWP100_kgCO2e_kg": 0,
                            "GWP100_kgCO2e_m3": 0
                        }
                        
                        chart_components_mass = {}
                        chart_components_carbon = {}
                        
                        try:
                            if not is_mix:
                                match_df = db["direct"][(db["direct"]["Category"] == selected_cat) & (db["direct"]["Material_Key"] == selected_mat)]
                                if not match_df.empty:
                                    direct_row = match_df.iloc[0]
                                    for prop in final_props:
                                        if prop in direct_row and pd.notna(direct_row[prop]):
                                            final_props[prop] = safe_float(direct_row[prop])
                                else:
                                    st.error(f"Could not find exact data for '{selected_mat}'.")
                                    st.stop()
                            else:
                                match_df = db["mixes"][(db["mixes"]["Category"] == selected_cat) & (db["mixes"]["Mix_Key"] == selected_mat)]
                                if not match_df.empty:
                                    mix_row = match_df.iloc[0]
                                    total_mass = 0
                                    total_gwp = 0
                                    
                                    for comp in factors_df.index:
                                        if comp in mix_row and pd.notna(mix_row[comp]):
                                            mass = safe_float(mix_row[comp])
                                            if mass > 0:
                                                factor_row = factors_df.loc[comp]
                                                comp_gwp = mass * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                                                
                                                chart_components_mass[comp] = mass
                                                chart_components_carbon[comp] = comp_gwp
                                                
                                                total_mass += mass
                                                total_gwp += comp_gwp
                                    
                                    if total_mass > 0:
                                        final_props["Total_Mass_kg_m3"] = total_mass
                                        final_props["GWP100_kgCO2e_m3"] = total_gwp
                                        final_props["ECFGWP100_kgCO2e_kg"] = total_gwp / total_mass
                                else:
                                    st.error(f"Could not find exact data for mix '{selected_mat}'.")
                                    st.stop()
                            
                            st.markdown("---")
                            st.markdown(f"**Properties for {selected_mat}**")
                            
                            m_col1, m_col2, m_col3 = st.columns(3)
                            m_col1.metric("Total Mass", f"{final_props['Total_Mass_kg_m3']:,.2f} kg/m³")
                            m_col2.metric("GWP100 Factor", f"{final_props['ECFGWP100_kgCO2e_kg']:,.3f} kgCO2e/kg")
                            m_col3.metric("GWP100 Total", f"{final_props['GWP100_kgCO2e_m3']:,.2f} kgCO2e/m³")
                            
                            if is_mix and len(chart_components_mass) > 0:
                                st.markdown("#### Mix Breakdown Analysis")
                                pc_col1, pc_col2 = st.columns(2)
                                
                                with pc_col1:
                                    st.markdown("**1. By Mass / Weight**")
                                    chart_data_mass = pd.DataFrame({"Component": list(chart_components_mass.keys()), "Mass": list(chart_components_mass.values())})
                                    pie_mass = alt.Chart(chart_data_mass).mark_arc(innerRadius=40).encode(
                                        theta=alt.Theta(field="Mass", type="quantitative"),
                                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                        tooltip=["Component", "Mass"]
                                    ).properties(height=280)
                                    st.altair_chart(pie_mass, use_container_width=True)
                                    
                                with pc_col2:
                                    st.markdown("**2. By GWP100 Carbon**")
                                    chart_data_carbon = pd.DataFrame({"Component": list(chart_components_carbon.keys()), "Carbon": list(chart_components_carbon.values())})
                                    pie_carbon = alt.Chart(chart_data_carbon).mark_arc(innerRadius=40).encode(
                                        theta=alt.Theta(field="Carbon", type="quantitative"),
                                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                        tooltip=["Component", "Carbon"]
                                    ).properties(height=280)
                                    st.altair_chart(pie_carbon, use_container_width=True)
                        except Exception as e:
                            st.error(f"Error parsing data. Details: {e}")

        elif mode == "Create Custom Material / Mix":
            
            if st.session_state.get("mix_success_message"):
                st.success(st.session_state.mix_success_message)
                st.session_state.mix_success_message = None
            
            col_mix_header, col_mix_clear = st.columns([3, 1])
            with col_mix_header:
                st.markdown("#### Design a Custom Material or Mix")
                
            with col_mix_clear:
                if not st.session_state.get("confirm_clear_mix", False):
                    if st.button("Clear Form & Start Over", key=f"btn_clear_mix_init_{st.session_state.mix_reset_counter}"):
                        st.session_state.confirm_clear_mix = True
                        st.rerun()
                else:
                    st.error("Are you sure? Unsaved changes will be lost.")
                    col_y, col_n = st.columns(2)
                    with col_y:
                        st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                        if st.button("Yes, Clear", key=f"btn_mix_clear_yes_{st.session_state.mix_reset_counter}"):
                            st.session_state.confirm_clear_mix = False
                            wipe_mix_form_memory()
                            st.rerun()
                    with col_n:
                        if st.button("Cancel", key=f"btn_mix_clear_no_{st.session_state.mix_reset_counter}"):
                            st.session_state.confirm_clear_mix = False
                            st.rerun()
            
            d_name = st.session_state.get("draft_mix_name", "")
            custom_mix_name = st.text_input("Name your Custom Item:", value=d_name, placeholder="e.g., C40/50 or Recycled Steel", key=f"mix_name_input_{st.session_state.mix_reset_counter}")
            st.caption("Tip: include the strength class in the name, for example C70/85 HSC Girder Mix. "
                       "The service life engine reads the grade out of the name and uses it to fill in "
                       "the strength values and the suggested coefficients.")
            
            c_col1, c_col2 = st.columns(2)
            with c_col1:
                cat_options = ["--- Select Category ---", "➕ Create New Category..."] + all_categories
                d_cat = st.session_state.get("draft_mix_cat", "--- Select Category ---")
                d_cat_idx = cat_options.index(d_cat) if d_cat in cat_options else 0
                
                custom_cat_selection = st.selectbox("Assign to Category:", cat_options, index=d_cat_idx, key=f"cust_cat_dropdown_{st.session_state.mix_reset_counter}")
                
                if custom_cat_selection == "➕ Create New Category...":
                    custom_cat = st.text_input("Enter New Category Name:", key=f"cust_cat_new_{st.session_state.mix_reset_counter}")
                else:
                    custom_cat = custom_cat_selection
            with c_col2:
                pass
                
            st.markdown("---")
            creation_type = st.radio("What type of item are you creating?", 
                                     ["Multi-Ingredient Mix", "Standalone Material"],
                                     horizontal=True,
                                     key=f"creation_type_radio_{st.session_state.mix_reset_counter}")
            
            custom_mix_data = {}
            valid_adhoc = []
            
            if creation_type == "Standalone Material":
                st.markdown("##### Define Material Properties")
                
                s_col1, s_col2 = st.columns(2)
                with s_col1:
                    standalone_density = st.number_input("Density / Unit Weight (kg/m³)", min_value=0.1, value=7850.0, step=10.0, key=f"std_density_{st.session_state.mix_reset_counter}")
                with s_col2:
                    standalone_gwp = st.number_input("GWP100 (kgCO2e/kg)", min_value=0.0, value=1.50, step=0.01, format="%.3f", key=f"std_gwp_{st.session_state.mix_reset_counter}")
                
                if standalone_density > 0:
                    valid_adhoc = [{"Material Name": custom_mix_name if custom_mix_name else "New Material", "Quantity": standalone_density, "GWP100 (kgCO2e/kg)": standalone_gwp}]
                
                st.markdown("---")
                st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                if st.button("Preview Material Properties", use_container_width=True):
                    st.session_state.show_mix_preview = True
                    
            else:
                st.markdown("##### 1. Choose Input Units")
                unit_mode = st.radio("How are you inputting your mix ingredients?", 
                                     ["Standard (kg/m³)", "Total Batch Weight (kg)", "US Imperial (lb/yd³)"], 
                                     horizontal=True, key=f"unit_mode_radio_{st.session_state.mix_reset_counter}")
                
                batch_vol = 1.0
                if unit_mode == "Total Batch Weight (kg)":
                    batch_vol = st.number_input("What is the total batch volume? (m³):", min_value=0.1, value=1.0, step=0.1, key=f"mix_batch_vol_{st.session_state.mix_reset_counter}")
                    st.info(f"Your inputs will be automatically divided by {batch_vol} to standardise them to kg/m³.")
                elif unit_mode == "US Imperial (lb/yd³)":
                    st.info("Your inputs will be automatically converted to kg/m³ (1 lb/yd³ ≈ 0.5933 kg/m³).")
                    
                st.markdown("##### 2. Standard Ingredients")
                
                all_comps = factors_df.index.tolist() if not factors_df.empty else []
                
                raw_input_data = {}
                d_comps = st.session_state.get("draft_mix_comps", {})
                
                input_cols = st.columns(4)
                for i, comp in enumerate(all_comps):
                    default_val = float(d_comps.get(comp, 0.0))
                    val = input_cols[i % 4].number_input(comp, min_value=0.0, step=10.0, value=default_val, key=f"cust_comp_{comp}_{st.session_state.mix_reset_counter}")
                    if val > 0:
                        raw_input_data[comp] = val
                        
                st.markdown("##### 3. Add Custom Ingredients")
                st.caption("To delete a row, highlight it and press Delete on your keyboard.")
                
                if "adhoc_mats" not in st.session_state:
                    st.session_state.adhoc_mats = pd.DataFrame(columns=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"])
                    
                edited_adhoc_df = st.data_editor(
                    st.session_state.adhoc_mats, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    key=f"adhoc_editor_{st.session_state.mix_reset_counter}",
                    column_order=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"]
                )
                
                for comp, val in raw_input_data.items():
                    if unit_mode == "US Imperial (lb/yd³)":
                        custom_mix_data[comp] = val * 0.593276
                    elif unit_mode == "Total Batch Weight (kg)":
                        custom_mix_data[comp] = val / batch_vol
                    else:
                        custom_mix_data[comp] = val
                        
                for _, row in edited_adhoc_df.iterrows():
                    name = str(row.get("Material Name", "")).strip()
                    qty = safe_float(row.get("Quantity", 0))
                    gwp = safe_float(row.get("GWP100 (kgCO2e/kg)", 0))
                    
                    if name and qty > 0:
                        if unit_mode == "US Imperial (lb/yd³)":
                            qty = qty * 0.593276
                        elif unit_mode == "Total Batch Weight (kg)":
                            qty = qty / batch_vol
                        valid_adhoc.append({"Material Name": name, "Quantity": qty, "GWP100 (kgCO2e/kg)": gwp})

                st.markdown("---")
                st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                if st.button("Preview Mix Properties", use_container_width=True):
                    st.session_state.show_mix_preview = True
                
            if st.session_state.get("show_mix_preview") and (len(custom_mix_data) > 0 or len(valid_adhoc) > 0):
                total_mass = 0
                total_gwp = 0
                
                custom_mix_carbon = {}
                c_data_mass_list = []
                
                for comp, mass in custom_mix_data.items():
                    if comp in factors_df.index:
                        factor_row = factors_df.loc[comp]
                        comp_gwp = mass * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                        custom_mix_carbon[comp] = comp_gwp
                        
                        total_gwp += comp_gwp
                        total_mass += mass
                        c_data_mass_list.append({"Component": comp, "Mass": mass})
                
                for adhoc in valid_adhoc:
                    comp = adhoc["Material Name"]
                    mass = adhoc["Quantity"]
                    comp_gwp = mass * adhoc["GWP100 (kgCO2e/kg)"]
                    custom_mix_carbon[comp] = comp_gwp
                    total_gwp += comp_gwp
                    total_mass += mass
                    c_data_mass_list.append({"Component": comp, "Mass": mass})
                
                st.markdown("##### Live Properties (Standardised to 1 m³ volume)")
                r_col1, r_col2, r_col3 = st.columns(3)
                r_col1.metric("Total Mass (Density)", f"{total_mass:,.2f} kg/m³")
                r_col2.metric("GWP100 Factor", f"{(total_gwp / total_mass):,.3f} kgCO2e/kg" if total_mass > 0 else "0")
                r_col3.metric("GWP100 Total", f"{total_gwp:,.2f} kgCO2e/m³")
                
                if creation_type == "Multi-Ingredient Mix":
                    st.markdown("##### Mix Breakdown Analysis")
                    c_pc_col1, c_pc_col2 = st.columns(2)
                    
                    with c_pc_col1:
                        st.markdown("**1. By Mass / Weight**")
                        c_data_mass = pd.DataFrame(c_data_mass_list)
                        c_pie_mass = alt.Chart(c_data_mass).mark_arc(innerRadius=40).encode(
                            theta=alt.Theta(field="Mass", type="quantitative"),
                            color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                            tooltip=["Component", "Mass"]
                        ).properties(height=280)
                        st.altair_chart(c_pie_mass, use_container_width=True)
                        
                    with c_pc_col2:
                        st.markdown("**2. By GWP100 Carbon**")
                        c_data_carbon = pd.DataFrame({"Component": list(custom_mix_carbon.keys()), "Carbon": list(custom_mix_carbon.values())})
                        c_pie_carbon = alt.Chart(c_data_carbon).mark_arc(innerRadius=40).encode(
                            theta=alt.Theta(field="Carbon", type="quantitative"),
                            color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                            tooltip=["Component", "Carbon"]
                        ).properties(height=280)
                        st.altair_chart(c_pie_carbon, use_container_width=True)
            
                st.markdown("---")
                st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                if st.button("Save Custom Item"):
                    if custom_cat == "--- Select Category ---" or not custom_cat:
                        st.error("Please assign a category before saving.")
                    elif not custom_mix_name:
                        st.error("Please provide a name for your item.")
                    elif len(custom_mix_data) == 0 and len(valid_adhoc) == 0:
                        st.error("Please add at least one ingredient or property.")
                    else:
                        mix_payload = {
                            "user_id": st.session_state.user_id,
                            "mix_name": custom_mix_name.strip(),
                            "category": custom_cat.strip(),
                            "components": custom_mix_data,
                            "adhoc_materials": valid_adhoc
                        }
                        
                        clean_new_name = custom_mix_name.strip().lower()
                        clean_new_cat = custom_cat.strip().lower()
                        existing_mix = next((m for m in user_mixes if m['mix_name'].strip().lower() == clean_new_name and m['category'].strip().lower() == clean_new_cat), None)
                        
                        if existing_mix:
                            st.session_state.confirm_overwrite_mix_name = custom_mix_name
                            st.session_state.existing_mix_id = existing_mix['id']
                            st.session_state.mix_payload_draft = mix_payload
                            st.rerun()
                        else:
                            st.session_state.execute_mix_save = True
                            st.session_state.mix_payload_draft = mix_payload
                            st.rerun()
                            
            if st.session_state.get("confirm_overwrite_mix_name"):
                st.error(f"A mix named '{st.session_state.confirm_overwrite_mix_name}' already exists in this category. Do you want to overwrite it?")
                col_y, col_n = st.columns(2)
                with col_y:
                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                    if st.button("Yes, Overwrite"):
                        st.session_state.execute_mix_save = True
                        st.session_state.confirm_overwrite_mix_name = None
                        st.rerun()
                with col_n:
                    if st.button("No, Change Name"):
                        st.session_state.confirm_overwrite_mix_name = None
                        st.session_state.mix_payload_draft = None
                        st.rerun()

    elif st.session_state.current_page == "Project Design":
        
        if st.session_state.get("proj_success_message"):
            st.success(st.session_state.proj_success_message)
            st.session_state.proj_success_message = None 

        col_proj_details, col_clear = st.columns([3, 1])
        
        with col_proj_details:
            st.markdown("### 1. Project Details & Structure")
            st.session_state.draft_proj_name = st.text_input("Project Name:", value=st.session_state.draft_proj_name, placeholder="Enter project name...", key=f"proj_name_{st.session_state.project_reset_counter}")
            
        with col_clear:
            st.markdown("<br>", unsafe_allow_html=True)
            if not st.session_state.get("confirm_clear_all", False):
                if st.button("Clear All & Start Over", key=f"btn_clear_proj_init_{st.session_state.project_reset_counter}"):
                    st.session_state.confirm_clear_all = True
                    st.rerun()
            else:
                st.error("Are you sure? All progress will be lost.")
                col_y, col_n = st.columns(2)
                with col_y:
                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                    if st.button("Yes, Clear", key=f"btn_proj_clear_yes_{st.session_state.project_reset_counter}"):
                        st.session_state.confirm_clear_all = False
                        wipe_project_form_memory()
                        st.rerun()
                with col_n:
                    if st.button("Cancel", key=f"btn_proj_clear_no_{st.session_state.project_reset_counter}"):
                        st.session_state.confirm_clear_all = False
                        st.rerun()
        
        structure_options = db["structures"]["Structure_Name"].dropna().tolist() if not db["structures"].empty and "Structure_Name" in db["structures"].columns else []
        
        try:
            struct_index = (["---"] + structure_options).index(st.session_state.draft_structure)
        except ValueError:
            struct_index = 0

        col_struct, col_gen = st.columns([3, 1])
        with col_struct:
            selected_structure = st.selectbox("Select Project Template:", ["---"] + structure_options, index=struct_index, key=f"proj_template_{st.session_state.project_reset_counter}")
        
        with col_gen:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
            if st.button("Generate Components", use_container_width=True):
                if selected_structure != "---":
                    st.session_state.draft_structure = selected_structure
                    st.session_state.draft_components = []
                    st.session_state.project_results_df = None

                    components_str = db["structures"].loc[db["structures"]["Structure_Name"] == selected_structure, "Components"].values[0]
                    component_list = [c.strip() for c in components_str.split(",") if "Extra" not in c.strip()]
                    
                    for comp in component_list:
                        default_unit = "m3"
                        if not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
                            match_mask = db["unit_logic"]["Component_Name"].astype(str).str.strip().str.lower() == str(comp).strip().lower()
                            unit_row = db["unit_logic"][match_mask]
                            if not unit_row.empty and "Default_Unit" in unit_row.columns:
                                val = str(unit_row["Default_Unit"].values[0]).strip()
                                if val and val.lower() != "nan":
                                    default_unit = val

                        st.session_state.draft_components.append({
                            "id": str(uuid.uuid4()),
                            "base_name": comp,
                            "custom_name": comp, 
                            "count": 1,
                            "materials": [{
                                "id": str(uuid.uuid4()),
                                "label": "",
                                "qty": 0.0,
                                "unit": default_unit,
                                "ref_value": 0.0,
                                "ref_per_unit": False,
                                "mix": "--- Select ---"
                            }]
                        })
                    st.rerun()

        if st.session_state.draft_structure != "---":
            st.markdown("### 2. Configure Components & Assign Mixes")
            
            comps_to_remove = []

            for comp in st.session_state.draft_components:
                st.markdown("---")
                
                col_count, col_title, col_del_comp = st.columns([1.5, 3, 1])
                is_extra = "Extra" in comp["base_name"]

                with col_count:
                    comp["count"] = st.number_input("Quantity (Nos.)", min_value=1, step=1, value=int(comp.get("count", 1)), key=f"count_{comp['id']}")

                with col_title:
                    if is_extra:
                        comp["custom_name"] = st.text_input("Custom Component Name:", value=comp["custom_name"], key=f"name_{comp['id']}")
                    else:
                        comp["custom_name"] = st.text_input("Component Name:", value=comp["custom_name"], key=f"name_{comp['id']}")

                with col_del_comp:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if is_extra:
                        st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                        if st.button("Remove Component", key=f"del_comp_{comp['id']}"):
                            comps_to_remove.append(comp)

                units = []
                
                if not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
                    match_mask = db["unit_logic"]["Component_Name"].astype(str).str.strip().str.lower() == str(comp["base_name"]).strip().lower()
                    unit_row = db["unit_logic"][match_mask]
                    if not unit_row.empty and "Unit_Options" in unit_row.columns:
                        sheet_units = [u.strip() for u in str(unit_row["Unit_Options"].values[0]).split(",")]
                        units.extend([su for su in sheet_units if su]) 

                master_fallback_units = ["m3", "m3 / unit", "tonnes", "tonnes / unit", "kg", "L", "L/m3", "% by volume", "% by weight", "m", "m2", "units"]
                
                for fallback in master_fallback_units:
                    if fallback not in units:
                        units.append(fallback)
                        
                if not units:
                    units = ["m3"]

                mats_to_remove = []
                
                for mat in comp["materials"]:
                    
                    unit_key = f"unit_{mat['id']}"
                    if unit_key in st.session_state:
                        mat["unit"] = st.session_state[unit_key]
                        
                    logic_type = get_unit_logic_type(mat["unit"])
                    needs_ref = logic_type in ["PERCENT_VOL", "PERCENT_WEIGHT", "LITER_PER_M3"]
                    
                    if needs_ref:
                        col_label, col_mix, col_qty, col_unit, col_ref, col_mult, col_del = st.columns([1.8, 2.2, 1.0, 1.2, 1.2, 0.8, 0.8])
                    else:
                        col_label, col_mix, col_qty, col_unit, col_del = st.columns([2.5, 3, 1.5, 1.5, 1])
                    
                    with col_label:
                        mat["label"] = st.text_input("Label (Optional)", value=mat.get("label", ""), key=f"label_{mat['id']}", placeholder="e.g. Strands")
                    with col_mix:
                        mat["mix"] = st.selectbox("Select Material", ["--- Select ---"] + all_available_mixes, index=(["--- Select ---"] + all_available_mixes).index(mat["mix"]) if mat["mix"] in (["--- Select ---"] + all_available_mixes) else 0, key=f"mix_{mat['id']}")
                    with col_qty:
                        mat["qty"] = st.number_input("Amount", min_value=0.0, step=0.1, value=float(mat.get("qty", 0.0)), key=f"qty_{mat['id']}")
                    with col_unit:
                        if mat["unit"] not in units:
                            units.append(mat["unit"])
                        mat["unit"] = st.selectbox("Unit", units, index=units.index(mat["unit"]), key=f"unit_{mat['id']}")
                        
                    if needs_ref:
                        with col_ref:
                            ref_label = "Ref Wt (tonnes)" if logic_type == "PERCENT_WEIGHT" else "Ref Vol (m³)"
                            mat["ref_value"] = st.number_input(ref_label, min_value=0.0, step=0.1, value=float(mat.get("ref_value", 0.0)), key=f"ref_{mat['id']}")
                        with col_mult:
                            st.markdown("<br>", unsafe_allow_html=True) 
                            mat["ref_per_unit"] = st.checkbox("× Qty", value=bool(mat.get("ref_per_unit", False)), key=f"mult_{mat['id']}", help="Check if this reference is for ONE unit.")
                    else:
                        mat["ref_value"] = 0.0 
                        mat["ref_per_unit"] = False
                        
                    with col_del:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if len(comp["materials"]) > 1: 
                            st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                            if st.button("Delete", key=f"del_mat_{mat['id']}"):
                                mats_to_remove.append(mat)

                for mat in mats_to_remove:
                    comp["materials"].remove(mat)
                    st.rerun()

                col_add_mat, col_nav_mix, col_empty = st.columns([1.5, 1.5, 3])
                with col_add_mat:
                    if st.button(f"+ Add Material", key=f"add_mat_btn_{comp['id']}"):
                        comp["materials"].append({
                            "id": str(uuid.uuid4()),
                            "label": "",
                            "qty": 0.0,
                            "unit": units[0],
                            "ref_value": 0.0,
                            "ref_per_unit": False,
                            "mix": "--- Select ---"
                        })
                        st.rerun()
                with col_nav_mix:
                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                    if st.button("Create Custom Mix ➔", key=f"nav_btn_{comp['id']}"):
                        st.session_state.current_page = "Materials & Mixes"
                        st.rerun()

            for comp in comps_to_remove:
                st.session_state.draft_components.remove(comp)
                st.rerun()

            st.markdown("---")
            if st.button("+ Add an 'Extra' Component"):
                st.session_state.draft_components.append({
                    "id": str(uuid.uuid4()),
                    "base_name": "Extra",
                    "custom_name": "Extra Component", 
                    "count": 1,
                    "materials": [{
                        "id": str(uuid.uuid4()),
                        "label": "",
                        "qty": 0.0,
                        "unit": "m3",
                        "ref_value": 0.0,
                        "ref_per_unit": False,
                        "mix": "--- Select ---"
                    }]
                })
                st.rerun()

            st.markdown("---")
            
            st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
            if st.button("Calculate Project Totals", use_container_width=True):
                with st.spinner("Processing calculations..."):
                    df, totals, clean_data = calculate_project_data(st.session_state.draft_components, db, user_mixes, factors_df)
                    
                    if df is not None:
                        st.session_state.project_results_df = df
                        st.session_state.project_totals = totals
                        st.session_state.project_clean_data = clean_data
                        st.session_state.sl_detail = None
                        st.session_state.sl_materials = None
                        st.session_state.sl_sig = None
                    else:
                        st.error("Please assign at least one material with an amount > 0.")
                    st.rerun()

            if st.session_state.project_results_df is not None:
                st.markdown("---")
                
                render_results_table_and_totals(st.session_state.project_results_df, st.session_state.project_totals)

                st.info("Next step: open Durability and Performance in the sidebar to run the "
                        "carbonation or chloride design life check on these materials and "
                        "obtain the carbon efficiency index.")
                
                st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                if st.button("Save Project"):
                    if not st.session_state.draft_proj_name:
                        st.error("Please enter a Project Name at the top of the page to save.")
                    else:
                        projects_res = supabase.table("saved_projects").select("id, project_name").eq("user_id", st.session_state.user_id).execute()
                        local_user_projects = projects_res.data if projects_res.data else []
                        
                        clean_new_name = st.session_state.draft_proj_name.strip().lower()
                        existing_project = next((p for p in local_user_projects if p['project_name'].strip().lower() == clean_new_name), None)
                        
                        if existing_project:
                            st.session_state.confirm_overwrite_name = st.session_state.draft_proj_name
                            st.session_state.existing_proj_id = existing_project['id']
                            st.rerun()
                        else:
                            st.session_state.execute_save = True
                            st.rerun()
                
                if st.session_state.get("confirm_overwrite_name"):
                    st.error(f"A project named '{st.session_state.confirm_overwrite_name}' already exists. Do you want to overwrite it?")
                    col_y, col_n = st.columns(2)
                    with col_y:
                        st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                        if st.button("Yes, Overwrite"):
                            st.session_state.execute_save = True
                            st.session_state.confirm_overwrite_name = None
                            st.rerun()
                    with col_n:
                        if st.button("No, Change Name"):
                            st.session_state.confirm_overwrite_name = None
                            st.rerun()

    elif st.session_state.current_page == "Durability and Performance":
        sl.render_service_life_page(
            supabase, db, user_mixes, factors_df,
            calculate_mix_carbon, calculate_project_data)

    elif st.session_state.current_page == "Comparison and Analysis":
        cmp_mod.render_comparison_page(
            supabase, db, user_mixes, factors_df, all_available_mixes,
            calculate_mix_carbon, calculate_project_data,
            safe_float, generate_pdf_report, HAS_FPDF)

    elif st.session_state.current_page == "My Library":
        
        lib_view = st.radio("Select Library View:",
                            ["Saved Projects", "Saved Custom Mixes", "Saved Assessments"],
                            horizontal=True, label_visibility="collapsed")
        st.markdown("---")
        
        if lib_view == "Saved Projects":
            try:
                projects_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user_id).execute()
                user_projects = projects_res.data if projects_res.data else []
            except Exception:
                user_projects = []
            
            if user_projects:
                proj_names = list(dict.fromkeys([p['project_name'] for p in user_projects if p.get('project_name')]))
                
                if proj_names:
                    if "lib_proj_radio_ui" in st.session_state and st.session_state.lib_proj_radio_ui not in proj_names:
                        del st.session_state["lib_proj_radio_ui"]
                        
                    col_list, col_details = st.columns([1, 2.5])
                    
                    with col_list:
                        st.markdown("#### Project List")
                        selected_proj = st.radio("Select Project", proj_names, label_visibility="collapsed", key="lib_proj_radio_ui")
                            
                    with col_details:
                        p = next((proj for proj in user_projects if proj['project_name'] == selected_proj), None)
                        if p:
                            st.markdown(f"### {p['project_name']}")
                            st.caption(f"Structure Template: {p['structure_type']} | Baseline GWP100: {p['total_embodied_carbon']:,.2f} kgCO2e")

                            sl_data = p.get("service_life_data") or {}
                            sl_summary = sl_data.get("summary") or {}
                            if sl_summary:
                                st.caption(
                                    f"Service life assessed, exposure {sl_data.get('exposure_class','?')} | "
                                    f"Sum of material values {safe_float(sl_summary.get('sum_csepp')):,.2f} | "
                                    f"Whole structure value {safe_float(sl_summary.get('structure_csepp')):,.2f}")
                            
                            draft_comps = []
                            raw_data = p.get("component_data", [])
                            
                            if isinstance(raw_data, dict):
                                for c_name, c_details in raw_data.items():
                                    draft_comps.append({
                                        "custom_name": c_name,
                                        "base_name": "Extra",
                                        "count": 1,
                                        "materials": [{
                                            "label": "",
                                            "qty": c_details.get("quantity", 0.0),
                                            "unit": c_details.get("unit", "m3"),
                                            "ref_value": c_details.get("ref_value", 0.0),
                                            "ref_per_unit": c_details.get("ref_per_unit", False),
                                            "mix": c_details.get("assigned_mix", "")
                                        }]
                                    })
                            else:
                                for comp in raw_data:
                                    mats = []
                                    for mat in comp.get("materials", []):
                                        mats.append({
                                            "label": mat.get("label", ""),
                                            "qty": mat.get("quantity", 0.0),
                                            "unit": mat.get("unit", "m3"),
                                            "ref_value": mat.get("ref_value", 0.0),
                                            "ref_per_unit": mat.get("ref_per_unit", False),
                                            "mix": mat.get("assigned_mix", "")
                                        })
                                    draft_comps.append({
                                        "base_name": comp.get("base_name", "Extra"),
                                        "custom_name": comp.get("component_name", ""),
                                        "count": comp.get("multiplier_count", 1),
                                        "materials": mats
                                    })

                            df, totals, _ = calculate_project_data(draft_comps, db, user_mixes, factors_df)
                            
                            if df is not None:
                                render_results_table_and_totals(df, totals)
                            else:
                                st.info("No calculable materials found in this project.")
                            
                            st.markdown("---")
                            
                            proj_id = p.get('id', str(p.get('project_name')))
                            del_key = f"del_proj_confirm_{proj_id}"
                            
                            if not st.session_state.get(del_key, False):
                                btn_col_rn, btn_col_a, btn_col_b = st.columns([2, 1.5, 1.5])
                                
                                with btn_col_rn:
                                    new_p_name = st.text_input("Rename Project:", value=p['project_name'], key=f"rn_p_{proj_id}")
                                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                                    if st.button("Update Name", key=f"btn_rn_{proj_id}"):
                                        try:
                                            supabase.table("saved_projects").update({"project_name": new_p_name}).eq("id", proj_id).execute()
                                            st.success("Project renamed!")
                                            st.rerun()
                                        except Exception as e:
                                            st.error("Failed to rename. Ensure you have the Supabase UPDATE policy enabled.")
                                
                                with btn_col_a:
                                    st.markdown("<br>", unsafe_allow_html=True)
                                    st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                                    st.button("Clone for Editing", key=f"load_proj_{proj_id}", on_click=load_project_to_session, args=(p, db))
                                        
                                with btn_col_b:
                                    st.markdown("<br>", unsafe_allow_html=True)
                                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                    if st.button("Delete Project", key=f"btn_del_init_proj_{proj_id}"):
                                        st.session_state[del_key] = True
                                        st.rerun()
                            else:
                                st.error("Are you sure? This cannot be undone.")
                                y_col, n_col = st.columns(2)
                                with y_col:
                                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                    if st.button("Yes, Delete", key=f"btn_del_yes_proj_{proj_id}"):
                                        if 'id' in p:
                                            supabase.table("saved_projects").delete().eq("id", p["id"]).execute()
                                            st.session_state[del_key] = False
                                            st.success("Project deleted.")
                                            st.rerun()
                                        else:
                                            st.error("Missing 'id' column.")
                                with n_col:
                                    if st.button("Cancel", key=f"btn_del_no_proj_{proj_id}"):
                                        st.session_state[del_key] = False
                                        st.rerun()
            else:
                st.info("No projects saved under your account yet.")

        elif lib_view == "Saved Custom Mixes":
            if not user_mixes:
                st.info("No custom mixes found on your account. Create one in 'Materials & Mixes'!")
            else:
                mix_names = list(dict.fromkeys([m['mix_name'] for m in user_mixes if m.get('mix_name')]))
                
                if mix_names:
                    if "lib_mix_radio_ui" in st.session_state and st.session_state.lib_mix_radio_ui not in mix_names:
                        del st.session_state["lib_mix_radio_ui"]
                        
                    col_m_list, col_m_details = st.columns([1, 2.5])
                    
                    with col_m_list:
                        st.markdown("#### Material List")
                        selected_mix = st.radio("Select Mix", mix_names, label_visibility="collapsed", key="lib_mix_radio_ui")
                            
                    with col_m_details:
                        m = next((mix for mix in user_mixes if mix['mix_name'] == selected_mix), None)
                        if m:
                            st.markdown(f"### {m['mix_name']}")
                            st.caption(f"Assigned Category: {m['category']}")
                            
                            c_mix_name = f"Custom: {m['mix_name']}"
                            props = calculate_mix_carbon(c_mix_name, db, user_mixes, factors_df)
                            
                            st.markdown("##### Performance Metrics")
                            m_col1, m_col2, m_col3 = st.columns(3)
                            m_col1.metric("Total Mass", f"{props['Mass (kg/m3)']:,.2f} kg/m³")
                            m_col2.metric("GWP100 Factor", f"{props['Factor_GWP (kgCO2e/kg)']:,.3f} kgCO2e/kg")
                            m_col3.metric("GWP100 Total", f"{props['Factor_GWP (kgCO2e/kg)'] * props['Mass (kg/m3)']:,.2f} kgCO2e/m³")

                            refs = sl.get_refs(db)
                            s_props = sl.get_strength(c_mix_name, refs)
                            cem, add, found = sl.autofill_binder(c_mix_name, db, user_mixes, factors_df, refs)
                            if s_props["Grade"] or found:
                                d_col1, d_col2, d_col3 = st.columns(3)
                                d_col1.metric("Detected grade", s_props["Grade"] or "not recognised")
                                d_col2.metric("Characteristic cylinder strength", f"{s_props['fck_cyl']:,.0f} MPa" if s_props["fck_cyl"] else "not recognised")
                                d_col3.metric("Total binder content", f"{cem + add:,.1f} kg/m3" if found else "not known")
                                st.caption("These are the values the Durability and Performance page will fill in "
                                           "for this mix. All of them can still be edited there.")
                            
                            chart_components_mass = {}
                            chart_components_carbon = {}
                            
                            if m.get("components"):
                                for c, val in m["components"].items():
                                    if val > 0: 
                                        if c in factors_df.index:
                                            factor_row = factors_df.loc[c]
                                            c_gwp = val * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                                            chart_components_mass[c] = val
                                            chart_components_carbon[c] = c_gwp
                            if m.get("adhoc_materials"):
                                for adhoc in m["adhoc_materials"]:
                                    c = adhoc["Material Name"]
                                    val = adhoc["Quantity"]
                                    c_gwp = val * adhoc["GWP100 (kgCO2e/kg)"]
                                    chart_components_mass[c] = val
                                    chart_components_carbon[c] = c_gwp
                            
                            if len(chart_components_mass) > 0:
                                st.markdown("##### Mix Breakdown Analysis")
                                pc_col1, pc_col2 = st.columns(2)
                                
                                with pc_col1:
                                    st.markdown("**By Mass / Weight**")
                                    chart_data_mass = pd.DataFrame({"Component": list(chart_components_mass.keys()), "Mass": list(chart_components_mass.values())})
                                    pie_mass = alt.Chart(chart_data_mass).mark_arc(innerRadius=40).encode(
                                        theta=alt.Theta(field="Mass", type="quantitative"),
                                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                        tooltip=["Component", "Mass"]
                                    ).properties(height=280)
                                    st.altair_chart(pie_mass, use_container_width=True)
                                    
                                with pc_col2:
                                    st.markdown("**By GWP100 Carbon**")
                                    chart_data_carbon = pd.DataFrame({"Component": list(chart_components_carbon.keys()), "Carbon": list(chart_components_carbon.values())})
                                    pie_carbon = alt.Chart(chart_data_carbon).mark_arc(innerRadius=40).encode(
                                        theta=alt.Theta(field="Carbon", type="quantitative"),
                                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                        tooltip=["Component", "Carbon"]
                                    ).properties(height=280)
                                    st.altair_chart(pie_carbon, use_container_width=True)
                                    
                            st.markdown("---")
                            
                            del_m_key = f"del_mix_confirm_{m['id']}"
                            
                            if not st.session_state.get(del_m_key, False):
                                btn_col_rn, btn_col_a, btn_col_b = st.columns([2, 1.5, 1.5])
                                
                                with btn_col_rn:
                                    new_m_name = st.text_input("Rename Mix:", value=m['mix_name'], key=f"rn_m_{m['id']}")
                                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                                    if st.button("Update Name", key=f"btn_rn_m_{m['id']}"):
                                        try:
                                            supabase.table("user_mixes").update({"mix_name": new_m_name}).eq("id", m['id']).execute()
                                            st.success("Mix renamed!")
                                            st.rerun()
                                        except Exception as e:
                                            st.error("Failed to rename.")
                                            
                                with btn_col_a:
                                    st.markdown("<br>", unsafe_allow_html=True)
                                    st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                                    st.button("Clone for Editing", key=f"load_mix_{m['id']}", on_click=load_mix_to_session, args=(m,))
                                    
                                with btn_col_b:
                                    st.markdown("<br>", unsafe_allow_html=True)
                                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                    if st.button("Delete Mix", key=f"btn_del_init_mix_{m['id']}"):
                                        st.session_state[del_m_key] = True
                                        st.rerun()
                            else:
                                st.error("Are you sure? This cannot be undone.")
                                y_m_col, n_m_col = st.columns(2)
                                with y_m_col:
                                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                    if st.button("Yes, Delete", key=f"btn_del_yes_mix_{m['id']}"):
                                        supabase.table("user_mixes").delete().eq("id", m['id']).execute()
                                        st.session_state[del_m_key] = False
                                        st.success("Mix deleted.")
                                        st.rerun()
                                with n_m_col:
                                    if st.button("Cancel", key=f"btn_del_no_mix_{m['id']}"):
                                        st.session_state[del_m_key] = False
                                        st.rerun()

        elif lib_view == "Saved Assessments":
            sl.render_library_assessments(
                supabase, db, user_mixes, factors_df,
                calculate_mix_carbon, calculate_project_data)

# Execute application
if st.session_state.user_id is None:
    login_page()
else:
    main_application()

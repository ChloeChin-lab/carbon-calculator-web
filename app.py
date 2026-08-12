import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os 
import requests
from io import BytesIO
import altair as alt
import uuid

st.set_page_config(page_title="Sustainability Assessment System", layout="wide")

# Custom CSS for the green calculate button and table formatting
st.markdown("""
<style>
/* Target the Streamlit primary button specifically */
div[data-testid="stButton"] > button[kind="primary"] {
    background-color: #4CAF50;
    color: white;
    padding: 15px;
    font-size: 18px;
    font-weight: bold;
    border-radius: 8px;
    border: none;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background-color: #45a049;
}
/* Style static tables to look like the engineering report */
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

# ==========================================
# 1. CONNECT TO CLOUD SERVICES
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "current_page" not in st.session_state:
    st.session_state.current_page = "Home"

# Background Draft Memory for Project Assessment
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

def clean_df(df):
    """Safely removes invisible spaces from Excel headers and text cells."""
    if isinstance(df, pd.DataFrame) and not df.empty:
        df.columns = df.columns.str.strip()
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
    return df

def safe_float(val, default=0.0):
    """Safely handles text, N/A, dashes, or blanks in Excel cells without crashing."""
    if pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

# ==========================================
# 2. FETCH DATA SAFELY (RAM OPTIMISED)
# ==========================================
@st.cache_data(ttl=600) 
def load_database():
    required_sheets = ["Component_Factors", "Mix_Designs", "Project_Structures", "Unit_Logic", "Direct_Results"]
    
    # 1. Try fetching from Cloud (Google Sheets)
    if SHEET_ID and len(SHEET_ID) > 20: 
        export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
        try:
            # Added a 10-second timeout so the app never freezes!
            response = requests.get(export_url, timeout=10)
            response.raise_for_status()
            excel_data = BytesIO(response.content)
            xls = pd.read_excel(excel_data, sheet_name=required_sheets)
            return {
                "factors": clean_df(xls.get("Component_Factors", pd.DataFrame())),
                "mixes": clean_df(xls.get("Mix_Designs", pd.DataFrame())),
                "structures": clean_df(xls.get("Project_Structures", pd.DataFrame())),
                "unit_logic": clean_df(xls.get("Unit_Logic", pd.DataFrame())),
                "direct": clean_df(xls.get("Direct_Results", pd.DataFrame()))
            }
        except Exception as e:
            print(f"Warning: Cloud Database failed to load. Reason: {e}")
            pass # Fall back to local file
            
    # 2. Fall back to Local File
    local_path = "materials_database.xlsx"
    if os.path.exists(local_path):
        try:
            xls = pd.read_excel(local_path, sheet_name=required_sheets)
            return {
                "factors": clean_df(xls.get("Component_Factors", pd.DataFrame())),
                "mixes": clean_df(xls.get("Mix_Designs", pd.DataFrame())),
                "structures": clean_df(xls.get("Project_Structures", pd.DataFrame())),
                "unit_logic": clean_df(xls.get("Unit_Logic", pd.DataFrame())),
                "direct": clean_df(xls.get("Direct_Results", pd.DataFrame()))
            }
        except Exception as e:
            print(f"Warning: Local Database failed to load. Reason: {e}")
            return None
            
    print("Critical Error: Both Cloud and Local databases are missing or unreachable.")
    return None

# ==========================================
# 3. SECURE LOGIN UI & HELPERS
# ==========================================
def login_page():
    st.title("Sustainability Assessment System")
    st.markdown("Please authenticate to access the assessment modules.")
    
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_password")
    
    if st.button("Log In"):
        try:
            response = supabase.auth.sign_in_with_password({"email": email, "password": password})
            st.session_state.user_id = response.user.id
            st.session_state.user_email = response.user.email
            st.session_state.current_page = "Home"
            st.rerun() 
        except Exception:
            st.error("Invalid email or password. Please contact your administrator for access.")

def load_mix_to_session(mix_data, factors_dataframe):
    st.session_state["mix_mode_radio"] = "Create Custom Mix"
    st.session_state["cust_cat"] = mix_data["category"]
    st.session_state["mix_name_input"] = f"{mix_data['mix_name']} (Copy)"
    
    if not factors_dataframe.empty and "Component" in factors_dataframe.columns:
        for c in factors_dataframe["Component"].tolist():
            st.session_state[f"cust_comp_{c}"] = safe_float(mix_data.get("components", {}).get(c, 0.0))
            
    if mix_data.get("adhoc_materials"):
        st.session_state["adhoc_mats"] = pd.DataFrame(mix_data["adhoc_materials"])

def load_project_to_session(p_data, db):
    """Callback to load a saved project into the Project Assessment tab safely."""
    st.session_state.current_page = "Project Assessment"
    st.session_state.draft_proj_name = f"{p_data['project_name']} (Copy)"
    st.session_state.draft_structure = p_data['structure_type']
    st.session_state.project_results_df = None # Clear old results so they must recalculate
    
    new_draft = []
    for c_data in p_data.get("component_data", []):
        c_name = c_data.get("component_name", "Unknown")
        mats = []
        for m_data in c_data.get("materials", []):
            mats.append({
                "id": str(uuid.uuid4()),
                "label": m_data.get("label", ""),
                "qty": m_data.get("quantity", 0.0),
                "unit": m_data.get("unit", "m3"),
                "mix": m_data.get("assigned_mix", "--- Select ---")
            })
            
        new_draft.append({
            "id": str(uuid.uuid4()),
            "base_name": c_name if "Extra" not in c_name else "Extra",
            "custom_name": c_name,
            "count": c_data.get("multiplier_count", 1),
            "materials": mats
        })
        
    st.session_state.draft_components = new_draft

def get_unit_logic_type(unit_string):
    if "/ unit" in unit_string: return "PER_UNIT"
    if "% by conc. vol." in unit_string: return "PERCENT_VOL"
    if "% of wt." in unit_string: return "PERCENT_WEIGHT"
    if "L/m3 of UHPC vol." in unit_string: return "UHPC_REF_VOL"
    if "L" == unit_string: return "BASIC_LITER"
    return "BASIC"

def calculate_mix_carbon(mix_name, db, user_mixes, factors_df):
    """Upgraded calculation engine fetching Mass, EE, EC, and GWP100 metrics."""
    m_mass, m_gwp, m_ee, m_ec = 0.0, 0.0, 0.0, 0.0
    
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
                        m_ee += c_val * safe_float(factor_row.get('EEF_MJ_kg', 0))
                        m_ec += c_val * safe_float(factor_row.get('ECF_kgCO2_kg', 0))
                    m_mass += c_val
                    
            if match_mix.get("adhoc_materials"):
                for adhoc in match_mix["adhoc_materials"]:
                    q = safe_float(adhoc.get("Quantity", 0))
                    m_mass += q
                    m_gwp += q * safe_float(adhoc.get("GWP100 (kgCO2e/kg)", 0))
                    m_ec += q * safe_float(adhoc.get("ECF (kgCO2/kg)", 0))
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
                    m_ee += val * safe_float(factor_row.get('EEF_MJ_kg', 0))
                    m_ec += val * safe_float(factor_row.get('ECF_kgCO2_kg', 0))
        else:
            match_direct = db["direct"][db["direct"]["Material_Key"] == mix_name] if not db["direct"].empty and "Material_Key" in db["direct"].columns else pd.DataFrame()
            if not match_direct.empty:
                direct_row = match_direct.iloc[0]
                m_mass = safe_float(direct_row.get("Total_Mass_kg_m3", 1.0)) 
                
                # Fetch GWP
                m_gwp = safe_float(direct_row.get("GWP100_kgCO2e_m3", 0.0))
                if m_gwp == 0.0: m_gwp = safe_float(direct_row.get("ECFGWP100_kgCO2e_kg", 0.0)) * m_mass
                
                # Fetch EE
                m_ee = safe_float(direct_row.get("EE_GJ_m3", 0.0)) * 1000 
                if m_ee == 0.0: m_ee = safe_float(direct_row.get("EEF_MJ_kg", 0.0)) * m_mass
                
                # Fetch EC
                m_ec = safe_float(direct_row.get("EC_kgCO2_m3", 0.0))
                if m_ec == 0.0: m_ec = safe_float(direct_row.get("ECF_kgCO2_kg", 0.0)) * m_mass
                    
    return {
        "Mix": mix_name.replace("Custom: ", ""),
        "Mass (kg/m3)": m_mass,
        "Factor_GWP (kgCO2e/kg)": (m_gwp / m_mass) if m_mass > 0 else 0,
        "Factor_EE (MJ/kg)": (m_ee / m_mass) if m_mass > 0 else 0,
        "Factor_EC (kgCO2/kg)": (m_ec / m_mass) if m_mass > 0 else 0
    }

def welcome_dashboard():
    st.title("Sustainability Assessment System")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div style="background-color: #F0F4F8; padding: 20px; border-radius: 8px; border-top: 4px solid #3498DB; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Materials & Mixes</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The master library. Configure ingredients, build custom mixes, and view material properties.</p>
        </div><br>""", unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_mats", use_container_width=True):
            st.session_state.current_page = "Materials & Mixes"
            st.rerun()
        
    with col2:
        st.markdown("""
        <div style="background-color: #E8F8F5; padding: 20px; border-radius: 8px; border-top: 4px solid #1ABC9C; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Project Assessment</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The structural assembly. Configure components, assign materials, and generate assessments.</p>
        </div><br>""", unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_proj", use_container_width=True):
            st.session_state.current_page = "Project Assessment"
            st.rerun()
        
    with col3:
        st.markdown("""
        <div style="background-color: #F8F9F9; padding: 20px; border-radius: 8px; border-top: 4px solid #95A5A6; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Saved Projects</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The completed portfolio. Review, analyse, or duplicate previously completed structure assessments.</p>
        </div><br>""", unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_saved", use_container_width=True):
            st.session_state.current_page = "Saved Projects"
            st.rerun()

# ==========================================
# 4. MAIN APPLICATION UI
# ==========================================
def main_application():
    db = load_database()
    
    if db is None:
        st.error("Cannot start the application. Please check the database connection.")
        st.stop()

    if st.session_state.current_page == "Home":
        st.sidebar.caption(f"User: {st.session_state.user_email}")
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
    
    st.sidebar.radio("Navigation", ["Materials & Mixes", "Project Assessment", "Saved Projects"], 
                     key="nav_radio", 
                     index=["Materials & Mixes", "Project Assessment", "Saved Projects"].index(st.session_state.current_page),
                     on_change=lambda: st.session_state.update(current_page=st.session_state.nav_radio),
                     label_visibility="collapsed")
    
    st.sidebar.markdown("---")
    st.sidebar.caption(f"User: {st.session_state.user_email}")
        
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

    # ---------------------------------------------------------
    # MODULE 1: MATERIALS REFERENCE & CUSTOM MIX CREATOR
    # ---------------------------------------------------------
    if st.session_state.current_page == "Materials & Mixes":

        mode = st.radio("Choose an action:", ["View Standard Materials", "Create Custom Mix", "Compare Mixes"], horizontal=True, key="mix_mode_radio")
        
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
                    if st.button("View Material Properties", type="primary"):
                        is_mix = selected_mat in cat_mix_mats
                        
                        final_props = {
                            "Total_Mass_kg_m3": 0, "ECF_kgCO2_kg": 0,
                            "EC_kgCO2_m3": 0, "ECFGWP100_kgCO2e_kg": 0,
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
                                    st.error(f"Could not find exact data for '{selected_mat}'. Please verify the database formatting.")
                                    st.stop()
                            else:
                                match_df = db["mixes"][(db["mixes"]["Category"] == selected_cat) & (db["mixes"]["Mix_Key"] == selected_mat)]
                                if not match_df.empty:
                                    mix_row = match_df.iloc[0]
                                    total_mass = 0
                                    total_ec = 0
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
                                                total_ec += mass * safe_float(factor_row.get('ECF_kgCO2_kg', 0))
                                                total_gwp += comp_gwp
                                            
                                    if total_mass > 0:
                                        final_props["Total_Mass_kg_m3"] = total_mass
                                        final_props["EC_kgCO2_m3"] = total_ec
                                        final_props["GWP100_kgCO2e_m3"] = total_gwp
                                        final_props["ECF_kgCO2_kg"] = total_ec / total_mass
                                        final_props["ECFGWP100_kgCO2e_kg"] = total_gwp / total_mass
                                else:
                                    st.error(f"Could not find exact data for mix '{selected_mat}'. Please verify the database formatting.")
                                    st.stop()
                            
                            st.markdown("---")
                            st.markdown(f"**Properties for {selected_mat}**")
                            
                            m_col1, m_col2, m_col3 = st.columns(3)
                            m_col1.metric("Total Mass", f"{final_props['Total_Mass_kg_m3']:,.2f} kg/m³")
                            m_col2.metric("ECF", f"{final_props['ECF_kgCO2_kg']:,.3f} kgCO2/kg")
                            m_col3.metric("GWP100 Factor", f"{final_props['ECFGWP100_kgCO2e_kg']:,.3f} kgCO2e/kg")
                            
                            m_col4, m_col5 = st.columns(2)
                            m_col4.metric("Embodied Carbon", f"{final_props['EC_kgCO2_m3']:,.2f} kgCO2/m³")
                            m_col5.metric("GWP100 Total", f"{final_props['GWP100_kgCO2e_m3']:,.2f} kgCO2e/m³")
                            
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
                                    st.markdown("**2. By Embodied Carbon**")
                                    chart_data_carbon = pd.DataFrame({"Component": list(chart_components_carbon.keys()), "Carbon": list(chart_components_carbon.values())})
                                    pie_carbon = alt.Chart(chart_data_carbon).mark_arc(innerRadius=40).encode(
                                        theta=alt.Theta(field="Carbon", type="quantitative"),
                                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                        tooltip=["Component", "Carbon"]
                                    ).properties(height=280)
                                    st.altair_chart(pie_carbon, use_container_width=True)
                        except Exception as e:
                            st.error(f"Error parsing data. Details: {e}")

        elif mode == "Create Custom Mix":
            st.markdown("#### Design a Custom Mix")
            
            c_col1, c_col2 = st.columns(2)
            with c_col1:
                custom_cat = st.selectbox("Assign to Category:", ["--- Select Category ---"] + all_categories, key="cust_cat")
            with c_col2:
                custom_mix_name = st.text_input("Name your Custom Mix:", placeholder="e.g., C40/50", key="mix_name_input")
            
            st.markdown("---")
            st.markdown("##### 1. Choose Input Units")
            unit_mode = st.radio("How are you inputting your mix ingredients?", 
                                 ["Standard (kg/m³)", "Total Batch Weight (kg)", "US Imperial (lb/yd³)"], 
                                 horizontal=True)
            
            batch_vol = 1.0
            if unit_mode == "Total Batch Weight (kg)":
                batch_vol = st.number_input("What is the total batch volume? (m³):", min_value=0.1, value=1.0, step=0.1)
                st.info(f"Your inputs will be automatically divided by {batch_vol} to standardise them to kg/m³.")
            elif unit_mode == "US Imperial (lb/yd³)":
                st.info("Your inputs will be automatically converted to kg/m³ (1 lb/yd³ ≈ 0.5933 kg/m³).")
                
            st.markdown("##### 2. Standard Ingredients")
            
            if not factors_df.empty:
                all_comps = factors_df.index.tolist()
            else:
                all_comps = []
            
            raw_input_data = {}
            
            input_cols = st.columns(4)
            for i, comp in enumerate(all_comps):
                val = input_cols[i % 4].number_input(comp, min_value=0.0, step=10.0, key=f"cust_comp_{comp}")
                if val > 0:
                    raw_input_data[comp] = val
                    
            st.markdown("##### 3. Add Custom Ingredients")
            st.caption("To delete a row, click the grey box on the far left edge of the row to highlight it, then press Delete on your keyboard.")
            
            if "adhoc_mats" not in st.session_state:
                st.session_state.adhoc_mats = pd.DataFrame(columns=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)", "ECF (kgCO2/kg)"])
                
            edited_adhoc_df = st.data_editor(
                st.session_state.adhoc_mats, 
                num_rows="dynamic", 
                use_container_width=True,
                key="adhoc_editor",
                column_order=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)", "ECF (kgCO2/kg)"]
            )
                    
            st.markdown("---")
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                preview_mix = st.button("Preview Mix Properties", type="primary")
            with btn_col2:
                save_mix = st.button("Save Custom Mix to Account")
                
            custom_mix_data = {}
            for comp, val in raw_input_data.items():
                if unit_mode == "US Imperial (lb/yd³)":
                    custom_mix_data[comp] = val * 0.593276
                elif unit_mode == "Total Batch Weight (kg)":
                    custom_mix_data[comp] = val / batch_vol
                else:
                    custom_mix_data[comp] = val
                    
            valid_adhoc = []
            for _, row in edited_adhoc_df.iterrows():
                name = str(row.get("Material Name", "")).strip()
                qty = safe_float(row.get("Quantity", 0))
                gwp = safe_float(row.get("GWP100 (kgCO2e/kg)", 0))
                ecf = safe_float(row.get("ECF (kgCO2/kg)", 0))
                
                if name and qty > 0:
                    if unit_mode == "US Imperial (lb/yd³)":
                        qty = qty * 0.593276
                    elif unit_mode == "Total Batch Weight (kg)":
                        qty = qty / batch_vol
                    valid_adhoc.append({"Material Name": name, "Quantity": qty, "GWP100 (kgCO2e/kg)": gwp, "ECF (kgCO2/kg)": ecf})
                
            if preview_mix and (len(custom_mix_data) > 0 or len(valid_adhoc) > 0):
                total_mass = 0
                total_ec = 0
                total_gwp = 0
                
                custom_mix_carbon = {}
                c_data_mass_list = []
                
                for comp, mass in custom_mix_data.items():
                    if comp in factors_df.index:
                        factor_row = factors_df.loc[comp]
                        comp_gwp = mass * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                        custom_mix_carbon[comp] = comp_gwp
                        
                        total_ec += mass * safe_float(factor_row.get('ECF_kgCO2_kg', 0))
                        total_gwp += comp_gwp
                        total_mass += mass
                        c_data_mass_list.append({"Component": comp, "Mass": mass})
                
                for adhoc in valid_adhoc:
                    comp = adhoc["Material Name"]
                    mass = adhoc["Quantity"]
                    comp_gwp = mass * adhoc["GWP100 (kgCO2e/kg)"]
                    custom_mix_carbon[comp] = comp_gwp
                    total_ec += mass * adhoc["ECF (kgCO2/kg)"]
                    total_gwp += comp_gwp
                    total_mass += mass
                    c_data_mass_list.append({"Component": comp, "Mass": mass})
                
                st.markdown("##### Live Properties (Standardised to kg/m³)")
                r_col1, r_col2, r_col3, r_col4 = st.columns(4)
                r_col1.metric("Total Mass", f"{total_mass:,.2f} kg/m³")
                r_col2.metric("ECF", f"{(total_ec / total_mass):,.3f} kgCO2/kg" if total_mass > 0 else "0")
                r_col3.metric("GWP100 Factor", f"{(total_gwp / total_mass):,.3f} kgCO2e/kg" if total_mass > 0 else "0")
                r_col4.metric("GWP100 Total", f"{total_gwp:,.2f} kgCO2e/m³")
                
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
                    st.markdown("**2. By Embodied Carbon**")
                    c_data_carbon = pd.DataFrame({"Component": list(custom_mix_carbon.keys()), "Carbon": list(custom_mix_carbon.values())})
                    c_pie_carbon = alt.Chart(c_data_carbon).mark_arc(innerRadius=40).encode(
                        theta=alt.Theta(field="Carbon", type="quantitative"),
                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                        tooltip=["Component", "Carbon"]
                    ).properties(height=280)
                    st.altair_chart(c_pie_carbon, use_container_width=True)
            
            if save_mix:
                if custom_cat == "--- Select Category ---":
                    st.error("Please assign a category before saving.")
                elif not custom_mix_name:
                    st.error("Please provide a name for your custom mix (e.g., C40/50).")
                elif len(custom_mix_data) == 0 and len(valid_adhoc) == 0:
                    st.error("Please add at least one ingredient.")
                else:
                    existing_duplicate = [m for m in user_mixes if m['mix_name'] == custom_mix_name and m['category'] == custom_cat]
                    if len(existing_duplicate) > 0:
                        st.error(f"A mix named '{custom_mix_name}' already exists in the '{custom_cat}' category. Please choose a different name.")
                    else:
                        mix_payload = {
                            "user_id": st.session_state.user_id,
                            "mix_name": custom_mix_name,
                            "category": custom_cat,
                            "components": custom_mix_data,
                            "adhoc_materials": valid_adhoc
                        }
                        try:
                            supabase.table("user_mixes").insert(mix_payload).execute()
                            st.success(f"Custom mix '{custom_mix_name}' saved successfully.")
                            st.rerun() 
                        except Exception as e:
                            st.error(f"Database Save Error: Verify your table has an 'adhoc_materials' column set to jsonb. Details: {e}")

    # ---------------------------------------------------------
    # TAB 2: PROJECT ASSESSMENT
    # ---------------------------------------------------------
    elif st.session_state.current_page == "Project Assessment":

        col_proj_details, col_clear = st.columns([3, 1])
        
        with col_proj_details:
            st.markdown("### 1. Project Details & Structure")
        with col_clear:
            st.markdown("<br>", unsafe_allow_html=True)
            if not st.session_state.get("confirm_clear_all", False):
                if st.button("Clear All & Start Over"):
                    st.session_state.confirm_clear_all = True
                    st.rerun()
            else:
                st.warning("Are you sure? All progress will be lost.")
                col_y, col_n = st.columns(2)
                if col_y.button("Yes, Clear"):
                    st.session_state.draft_proj_name = ""
                    st.session_state.draft_structure = "---"
                    st.session_state.draft_components = []
                    st.session_state.project_results_df = None
                    st.session_state.confirm_clear_all = False
                    st.rerun()
                if col_n.button("Cancel"):
                    st.session_state.confirm_clear_all = False
                    st.rerun()
        
        st.session_state.draft_proj_name = st.text_input("Project Name:", value=st.session_state.draft_proj_name, placeholder="Enter project name...")

        structure_options = db["structures"]["Structure_Name"].dropna().tolist() if not db["structures"].empty and "Structure_Name" in db["structures"].columns else []
        
        try:
            struct_index = (["---"] + structure_options).index(st.session_state.draft_structure)
        except ValueError:
            struct_index = 0

        col_struct, col_gen = st.columns([3, 1])
        with col_struct:
            selected_structure = st.selectbox("Select Project Template:", ["---"] + structure_options, index=struct_index)
        
        with col_gen:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Generate Components", type="primary", use_container_width=True):
                if selected_structure != "---":
                    st.session_state.draft_structure = selected_structure
                    st.session_state.draft_components = []
                    st.session_state.project_results_df = None

                    components_str = db["structures"].loc[db["structures"]["Structure_Name"] == selected_structure, "Components"].values[0]
                    component_list = [c.strip() for c in components_str.split(",") if "Extra" not in c.strip()]
                    
                    for comp in component_list:
                        st.session_state.draft_components.append({
                            "id": str(uuid.uuid4()),
                            "base_name": comp,
                            "custom_name": comp, 
                            "count": 1,
                            "materials": [{
                                "id": str(uuid.uuid4()),
                                "label": "",
                                "qty": 0.0,
                                "unit": "m3",
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
                        if st.button("Remove Component", key=f"del_comp_{comp['id']}"):
                            comps_to_remove.append(comp)

                units = ["m3"]
                if not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
                    unit_row = db["unit_logic"][db["unit_logic"]["Component_Name"] == comp["base_name"]]
                    if not unit_row.empty and "Unit_Options" in unit_row.columns:
                        units = str(unit_row["Unit_Options"].values[0]).split(",")

                mats_to_remove = []
                
                # Material Data Entry
                for mat in comp["materials"]:
                    col_label, col_mix, col_qty, col_unit, col_del = st.columns([2.5, 3, 1.5, 1.5, 1])
                    
                    with col_label:
                        mat["label"] = st.text_input("Label (Optional)", value=mat.get("label", ""), key=f"label_{mat['id']}", placeholder="e.g. Strands")
                    with col_mix:
                        mat["mix"] = st.selectbox("Select Material", ["--- Select ---"] + all_available_mixes, index=(["--- Select ---"] + all_available_mixes).index(mat["mix"]) if mat["mix"] in (["--- Select ---"] + all_available_mixes) else 0, key=f"mix_{mat['id']}")
                    with col_qty:
                        mat["qty"] = st.number_input("Amount", min_value=0.0, step=0.1, value=float(mat.get("qty", 0.0)), key=f"qty_{mat['id']}")
                    with col_unit:
                        mat["unit"] = st.selectbox("Unit", units, index=units.index(mat["unit"]) if mat["unit"] in units else 0, key=f"unit_{mat['id']}")
                    with col_del:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if len(comp["materials"]) > 1: 
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
                            "mix": "--- Select ---"
                        })
                        st.rerun()
                with col_nav_mix:
                    if st.button("Create New Custom Mix ➔", key=f"nav_btn_{comp['id']}"):
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
                        "mix": "--- Select ---"
                    }]
                })
                st.rerun()

            st.markdown("---")
            
            # THE GREEN CALCULATE BUTTON
            if st.button("Calculate Project Totals", key="calc_btn_hidden", type="primary", use_container_width=True):
                with st.spinner("Processing calculations..."):
                    results_list = []
                    grand_totals = {"mass": 0.0, "ee": 0.0, "ec": 0.0, "gwp": 0.0}
                    clean_project_data = []

                    # PRE-SCAN
                    concrete_volumes_cache = {}
                    steel_weights_cache = {}
                    total_project_uhpc_volume_m3 = 0.0
                    
                    for comp in st.session_state.draft_components:
                        c_multiplier = int(comp.get("count", 1))
                        conc_vol_m3 = 0.0
                        steel_weight_tonnes = 0.0
                        
                        for mat in comp["materials"]:
                            qty = safe_float(mat["qty"])
                            unit_str = mat["unit"]
                            mix_name = mat["mix"]
                            logic_type = get_unit_logic_type(unit_str)
                            
                            total_vol = 0.0
                            if logic_type == "PER_UNIT":
                                total_vol = qty * c_multiplier
                            elif logic_type in ["BASIC", "BASIC_LITER"]:
                                total_vol = qty * c_multiplier
                                
                            if "m3" in unit_str and logic_type in ["BASIC", "PER_UNIT"]:
                                conc_vol_m3 += total_vol
                                if mix_name != "--- Select ---" and "UHPC" in mix_name.upper():
                                    total_project_uhpc_volume_m3 += total_vol
                            
                            if "tonnes" in unit_str and logic_type in ["BASIC", "PER_UNIT"]:
                                steel_weight_tonnes += total_vol
                                
                        concrete_volumes_cache[comp["id"]] = conc_vol_m3
                        if "Main Girders" in comp["base_name"]:
                            steel_weights_cache["Main Girders"] = steel_weights_cache.get("Main Girders", 0.0) + steel_weight_tonnes

                    # MAIN CALCULATION PASS
                    for comp_idx, comp in enumerate(st.session_state.draft_components):
                        c_name = comp["custom_name"] if comp["custom_name"] else comp["base_name"]
                        c_multiplier = int(comp.get("count", 1))
                        c_materials = []

                        ref_conc_vol = concrete_volumes_cache.get(comp["id"], 0.0)
                        ref_steel_weight = steel_weights_cache.get("Main Girders", 0.0)

                        for mat in comp["materials"]:
                            qty = safe_float(mat["qty"])
                            unit_str = mat["unit"]
                            mix = mat["mix"]
                            logic_type = get_unit_logic_type(unit_str)
                            
                            if mix != "--- Select ---" and qty > 0:
                                props = calculate_mix_carbon(mix, db, user_mixes, factors_df)
                                mass_per_m3 = props["Mass (kg/m3)"]
                                
                                # Convert to Total Mass (kg)
                                total_mass_kg = 0.0
                                
                                if logic_type == "PERCENT_VOL":
                                    vol_m3 = (qty / 100.0) * ref_conc_vol
                                    total_mass_kg = vol_m3 * mass_per_m3
                                elif logic_type == "UHPC_REF_VOL":
                                    vol_L = qty * total_project_uhpc_volume_m3
                                    total_mass_kg = (vol_L / 1000.0) * mass_per_m3
                                elif logic_type == "PERCENT_WEIGHT":
                                    weight_tonnes = (qty / 100.0) * ref_steel_weight
                                    total_mass_kg = weight_tonnes * 1000.0
                                elif logic_type == "PER_UNIT" or logic_type == "BASIC" or logic_type == "BASIC_LITER":
                                    base_vol = qty * c_multiplier if logic_type == "PER_UNIT" else qty
                                    if "tonnes" in unit_str:
                                        total_mass_kg = base_vol * 1000.0
                                    elif "kg" in unit_str:
                                        total_mass_kg = base_vol
                                    elif logic_type == "BASIC_LITER":
                                        total_mass_kg = (base_vol / 1000.0) * mass_per_m3
                                    else:
                                        total_mass_kg = base_vol * mass_per_m3

                                # Final Totals
                                item_ee_gj = (total_mass_kg * props["Factor_EE (MJ/kg)"]) / 1000.0
                                item_ec_kg = total_mass_kg * props["Factor_EC (kgCO2/kg)"]
                                item_gwp = total_mass_kg * props["Factor_GWP (kgCO2e/kg)"]
                                
                                grand_totals["mass"] += total_mass_kg
                                grand_totals["ee"] += item_ee_gj
                                grand_totals["ec"] += item_ec_kg
                                grand_totals["gwp"] += item_gwp
                                
                                item_label = f"{comp_idx + 1}. {c_name} {mat.get('label', '')}".strip()
                                
                                results_list.append({
                                    "Item": item_label,
                                    "Material": mix,
                                    "Volume": qty,
                                    "Unit": unit_str,
                                    "Total Mass (kg)": total_mass_kg,
                                    "Total EE (GJ)": item_ee_gj,
                                    "Total EC (kgCO2)": item_ec_kg,
                                    "Total GWP100 (kgCO2e)": item_gwp
                                })
                                
                            c_materials.append({
                                "label": mat.get("label", ""),
                                "quantity": qty,
                                "unit": unit_str,
                                "assigned_mix": mix
                            })
                                
                        clean_project_data.append({
                            "component_name": c_name,
                            "multiplier_count": c_multiplier,
                            "materials": c_materials
                        })
                    
                    if len(results_list) > 0:
                        st.session_state.project_results_df = pd.DataFrame(results_list)
                        st.session_state.project_totals = grand_totals
                        st.session_state.project_clean_data = clean_project_data
                    else:
                        st.error("Please assign at least one material with an amount > 0.")
                    st.rerun()

            # --- RESULTS DISPLAY ---
            if st.session_state.project_results_df is not None:
                st.markdown("---")
                st.markdown("### 3. Calculation Results")
                
                # Format dataframe for exact visual match with the screenshot
                display_df = st.session_state.project_results_df.copy()
                
                # Start index at 1 (instead of 0) to match the PySide6 table row numbers
                display_df.index = display_df.index + 1 
                
                # Format numbers cleanly with commas and 2 decimal places for the table
                display_df["Volume"] = display_df["Volume"].apply(lambda x: f"{float(x):,.2f}")
                display_df["Total Mass (kg)"] = display_df["Total Mass (kg)"].apply(lambda x: f"{float(x):,.2f}")
                display_df["Total EE (GJ)"] = display_df["Total EE (GJ)"].apply(lambda x: f"{float(x):,.2f}")
                display_df["Total EC (kgCO2)"] = display_df["Total EC (kgCO2)"].apply(lambda x: f"{float(x):,.2f}")
                display_df["Total GWP100 (kgCO2e)"] = display_df["Total GWP100 (kgCO2e)"].apply(lambda x: f"{float(x):,.2f}")
                
                # Render using st.table for the classic, static engineering report look
                st.table(display_df)
                
                # Render Grand Totals in a styled HTML box matching the PySide6 UI exactly
                totals_html = f"""
                <div style="border: 1px solid #d3d3d3; border-radius: 5px; padding: 20px; background-color: #f9f9f9; margin-bottom: 20px;">
                    <h4 style="margin-top: 0; color: #000; font-family: sans-serif;">Project Grand Totals</h4>
                    <table style="width: 100%; border-collapse: collapse; font-size: 16px; color: #000; font-family: sans-serif;">
                        <tr><td style="font-weight: bold; width: 250px; padding: 8px 0;">Total Mass:</td><td>{st.session_state.project_totals['mass']:,.2f} kg</td></tr>
                        <tr><td style="font-weight: bold; padding: 8px 0; background-color: #f0f0f0;">Total Embodied Energy:</td><td style="background-color: #f0f0f0;">{st.session_state.project_totals['ee']:,.2f} GJ</td></tr>
                        <tr><td style="font-weight: bold; padding: 8px 0;">Total Embodied Carbon:</td><td>{st.session_state.project_totals['ec']:,.2f} kgCO2</td></tr>
                        <tr><td style="font-weight: bold; padding: 8px 0; background-color: #f0f0f0;">Total GWP100:</td><td style="background-color: #f0f0f0;">{st.session_state.project_totals['gwp']:,.2f} kgCO2e</td></tr>
                    </table>
                </div>
                """
                st.markdown(totals_html, unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown("### 4. Save Project to Cloud")
                
                s_col1, s_col2 = st.columns([3, 1])
                with s_col1:
                    st.info(f"Saving as: **{st.session_state.draft_proj_name}** (To rename, edit the Project Name at the top of the page)")
                with s_col2:
                    if st.button("Save to Account", type="primary", use_container_width=True):
                        if not st.session_state.draft_proj_name:
                            st.error("Please enter a Project Name at the top of the page to save.")
                        else:
                            projects_res = supabase.table("saved_projects").select("id, project_name").eq("user_id", st.session_state.user_id).execute()
                            local_user_projects = projects_res.data if projects_res.data else []
                            
                            existing_project = next((p for p in local_user_projects if p['project_name'] == st.session_state.draft_proj_name), None)
                            
                            if existing_project:
                                st.session_state.confirm_overwrite_name = st.session_state.draft_proj_name
                                st.session_state.existing_proj_id = existing_project['id']
                                st.rerun()
                            else:
                                st.session_state.execute_save = True
                                st.rerun()
                
                # Conflict Resolution
                if st.session_state.get("confirm_overwrite_name"):
                    st.warning(f"A project named '{st.session_state.confirm_overwrite_name}' already exists. Do you want to overwrite it?")
                    col_y, col_n = st.columns(2)
                    if col_y.button("Yes, Overwrite"):
                        st.session_state.execute_save = True
                        st.session_state.confirm_overwrite_name = None
                        st.rerun()
                    if col_n.button("No, Rename"):
                        st.session_state.confirm_overwrite_name = None
                        st.rerun()
                
                # Final Save Execution
                if st.session_state.get("execute_save"):
                    project_payload = {
                        "user_id": st.session_state.user_id,
                        "project_name": st.session_state.draft_proj_name,
                        "structure_type": selected_structure,
                        "total_embodied_carbon": st.session_state.project_totals['gwp'],
                        "component_data": st.session_state.project_clean_data
                    }
                    try:
                        if st.session_state.get("existing_proj_id"):
                            supabase.table("saved_projects").update(project_payload).eq("id", st.session_state.existing_proj_id).execute()
                            st.success(f"Project '{st.session_state.draft_proj_name}' successfully overwritten and updated.")
                        else:
                            supabase.table("saved_projects").insert(project_payload).execute()
                            st.success(f"Project '{st.session_state.draft_proj_name}' saved successfully to your account.")
                            
                        # Do NOT clear the UI or the table so the user can still see their work!
                        st.session_state.execute_save = False
                        st.session_state.existing_proj_id = None
                        
                    except Exception as e:
                        st.error(f"Failed to save project. Error: {e}")
                        st.session_state.execute_save = False

    # ---------------------------------------------------------
    # TAB 3: SAVED PROJECTS 
    # ---------------------------------------------------------
    elif st.session_state.current_page == "Saved Projects":
        st.markdown("### Your Project Library")
        
        projects_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user_id).execute()
        user_projects = projects_res.data if projects_res.data else []
        
        if user_projects:
            for p in user_projects:
                with st.expander(f"{p['project_name']} | Structure: {p['structure_type']} | Carbon: {p['total_embodied_carbon']:,.2f} kgCO2e"):
                    
                    clean_data = []
                    if isinstance(p["component_data"], list):
                        for comp in p["component_data"]:
                            c_name = comp.get("component_name", "Unknown")
                            c_count = comp.get("multiplier_count", 1)
                            for mat in comp.get("materials", []):
                                clean_data.append({
                                    "Component": c_name,
                                    "Multiplier": c_count,
                                    "Label/Note": mat.get("label", ""),
                                    "Material": mat.get("assigned_mix", ""),
                                    "Amount": mat.get("quantity", 0),
                                    "Unit": mat.get("unit", "")
                                })
                    elif isinstance(p["component_data"], dict):
                        for c_name, c_details in p["component_data"].items():
                            clean_data.append({
                                "Component": c_name,
                                "Multiplier": 1,
                                "Label/Note": "",
                                "Material": c_details.get("assigned_mix", ""),
                                "Amount": c_details.get("quantity", 0),
                                "Unit": c_details.get("unit", "")
                            })
                        
                    st.markdown("**Component Details:**")
                    st.dataframe(pd.DataFrame(clean_data), hide_index=True, use_container_width=True)
                    
                    proj_id = p.get('id', str(p.get('project_name')))
                    del_key = f"del_proj_confirm_{proj_id}"
                    
                    btn_col_a, btn_col_b = st.columns(2)
                    with btn_col_a:
                        st.button(
                            "Duplicate and Edit", 
                            key=f"load_proj_{proj_id}", 
                            on_click=load_project_to_session, 
                            args=(p, db)
                        )
                            
                    with btn_col_b:
                        if not st.session_state.get(del_key, False):
                            if st.button("Delete Project", key=f"btn_del_init_proj_{proj_id}"):
                                st.session_state[del_key] = True
                                st.rerun()
                        else:
                            st.warning("Are you sure you want to permanently delete this project? This action cannot be undone.")
                            y_col, n_col = st.columns(2)
                            if y_col.button("Yes, Delete", key=f"btn_del_yes_proj_{proj_id}"):
                                if 'id' in p:
                                    supabase.table("saved_projects").delete().eq("id", p["id"]).execute()
                                    st.session_state[del_key] = False
                                    st.success("Project deleted.")
                                    st.rerun()
                                else:
                                    st.error("Missing 'id' column in Supabase.")
                            if n_col.button("Cancel", key=f"btn_del_no_proj_{proj_id}"):
                                st.session_state[del_key] = False
                                st.rerun()
        else:
            st.info("No projects saved under your account yet.")

if st.session_state.user_id is None:
    login_page()
else:
    main_application()

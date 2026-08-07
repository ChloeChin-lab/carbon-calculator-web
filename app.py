import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os 
import requests
from io import BytesIO
import altair as alt

# Force a clean, wide layout
st.set_page_config(page_title="Carbon Calculator", page_icon="🏢", layout="wide")

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

# ==========================================
# 2. FETCH LIVE DATA FROM GOOGLE SHEETS
# ==========================================
@st.cache_data(ttl=3600) 
def load_google_sheet_db():
    if not SHEET_ID:
        st.error("Google Sheet ID is missing. Please check your Environment Variables.")
        return None
        
    export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
    
    try:
        # Download the file once safely into memory to prevent crashing
        response = requests.get(export_url)
        response.raise_for_status()
        excel_data = BytesIO(response.content)
        
        # Load all sheets at once
        xls = pd.read_excel(excel_data, sheet_name=None)
        
        return {
            "factors": xls.get("Component_Factors"),
            "mixes": xls.get("Mix_Designs"),
            "structures": xls.get("Project_Structures"),
            "unit_logic": xls.get("Unit_Logic"),
            "direct": xls.get("Direct_Results")
        }
    except Exception as e:
        st.error(f"Failed to load database: {e}")
        return None

# ==========================================
# 3. SECURE LOGIN UI (INVITE-ONLY)
# ==========================================
def login_page():
    st.title("Embodied Carbon Calculator")
    
    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_password")
    
    if st.button("Log In"):
        try:
            response = supabase.auth.sign_in_with_password({"email": email, "password": password})
            st.session_state.user_id = response.user.id
            st.session_state.user_email = response.user.email
            st.rerun() 
        except Exception as e:
            st.error("Invalid email or password. Please contact your administrator for access.")

# ==========================================
# 4. MAIN CALCULATOR UI
# ==========================================
def main_calculator():
    st.sidebar.success(f"Logged in as: {st.session_state.user_email}")
        
    if st.sidebar.button("Log Out"):
        st.session_state.user_id = None
        st.rerun()

    st.title("Embodied Carbon Calculator")
    
    db = load_google_sheet_db()
    if db is None:
        st.warning("Cannot start the calculator without the reference database.")
        st.stop()

    tab1, tab2 = st.tabs(["Project Calculator", "Materials Calculator"])
    
    # ---------------------------------------------------------
    # TAB 1: PROJECT CALCULATOR (Your Tab 2 from PySide6)
    # ---------------------------------------------------------
    with tab1:
        st.markdown("### 1. Project Details")
        project_name = st.text_input("Project Name:")
        
        structure_options = db["structures"]["Structure_Name"].dropna().tolist() if db["structures"] is not None else []
        selected_structure = st.selectbox("Select Project Structure:", ["---"] + structure_options)
        
        if selected_structure != "---":
            st.markdown("### 2. Configure Components")
            
            components_str = db["structures"].loc[db["structures"]["Structure_Name"] == selected_structure, "Components"].values[0]
            component_list = [c.strip() for c in components_str.split(",")]
            
            project_data = {}
            
            for comp in component_list:
                col1, col2 = st.columns(2)
                with col1:
                    quantity = st.number_input(f"Amount of {comp}:", min_value=0.0, step=1.0, key=f"qty_{comp}")
                with col2:
                    selected_unit = "m3"
                    if db["unit_logic"] is not None:
                        unit_row = db["unit_logic"][db["unit_logic"]["Component_Name"] == comp]
                        if not unit_row.empty:
                            units = str(unit_row["Unit_Options"].values[0]).split(",")
                            selected_unit = st.selectbox("Unit:", units, key=f"unit_{comp}")
                        else:
                            st.write("Unit: m3")
                    else:
                        st.write("Unit: m3")
                
                project_data[comp] = {"quantity": quantity, "unit": selected_unit}
            
            st.markdown("---")
            
            if st.button("Calculate & Save Project"):
                if not project_name:
                    st.error("Please enter a Project Name to save.")
                else:
                    with st.spinner("Processing calculations..."):
                        # Basic placeholder total calculation
                        total_carbon = sum(item["quantity"] * 350 for item in project_data.values())
                        
                        project_payload = {
                            "user_id": st.session_state.user_id,
                            "project_name": project_name,
                            "structure_type": selected_structure,
                            "total_embodied_carbon": total_carbon,
                            "component_data": project_data 
                        }
                        
                        supabase.table("saved_projects").insert(project_payload).execute()
                        st.success(f"Project '{project_name}' saved successfully!")
                        st.metric(label="Total Embodied Carbon (kgCO2e)", value=f"{total_carbon:,.2f}")

    # ---------------------------------------------------------
    # TAB 2: MATERIALS CALCULATOR (Your original PySide6 logic!)
    # ---------------------------------------------------------
    with tab2:
        st.markdown("### Material Properties Calculator")
        
        # 1. Gather all categories
        mix_cats = set(db["mixes"]["Category"].dropna().unique()) if db["mixes"] is not None else set()
        direct_cats = set(db["direct"]["Category"].dropna().unique()) if db["direct"] is not None else set()
        all_categories = sorted(list(mix_cats.union(direct_cats)))
        
        col_left, col_right = st.columns([1, 1.5])
        
        with col_left:
            st.markdown("#### Select Material")
            selected_cat = st.selectbox("Material Category:", ["--- Select Category ---"] + all_categories)
            
            if selected_cat != "--- Select Category ---":
                # Get materials for this category
                mix_mats = db["mixes"][db["mixes"]["Category"] == selected_cat]["Mix_Key"].dropna().tolist() if db["mixes"] is not None else []
                direct_mats = db["direct"][db["direct"]["Category"] == selected_cat]["Material_Key"].dropna().tolist() if db["direct"] is not None else []
                all_mats = sorted(list(set(mix_mats + direct_mats)))
                
                selected_mat = st.selectbox("Material Type/Grade:", ["--- Select Material ---"] + all_mats)
                
                if selected_mat != "--- Select Material ---":
                    is_mix = selected_mat in mix_mats
                    custom_mix = {}
                    
                    if is_mix:
                        st.markdown("#### Customize Mix Design (Optional)")
                        mix_row = db["mixes"][(db["mixes"]["Category"] == selected_cat) & (db["mixes"]["Mix_Key"] == selected_mat)].iloc[0]
                        components = db["factors"]["Component"].dropna().tolist() if db["factors"] is not None else []
                        
                        # Dynamically generate inputs for components that exist in the mix
                        for comp in components:
                            if comp in mix_row and pd.notna(mix_row[comp]) and mix_row[comp] > 0:
                                val = st.number_input(f"{comp} (kg/m3):", value=float(mix_row[comp]), min_value=0.0, format="%.2f")
                                custom_mix[comp] = val
                    
                    # --- PERFORM CALCULATIONS ---
                    final_props = {
                        "Total_Mass_kg_m3": 0, "EEF_MJ_kg": 0, "ECF_kgCO2_kg": 0,
                        "EE_GJ_m3": 0, "EC_kgCO2_m3": 0, "ECFGWP100_kgCO2e_kg": 0,
                        "GWP100_kgCO2e_m3": 0
                    }
                    
                    if not is_mix:
                        # Direct Result Lookup
                        direct_row = db["direct"][(db["direct"]["Category"] == selected_cat) & (db["direct"]["Material_Key"] == selected_mat)].iloc[0]
                        for prop in final_props:
                            if prop in direct_row and pd.notna(direct_row[prop]):
                                final_props[prop] = float(direct_row[prop])
                    else:
                        # Mix Design Calculation
                        total_mass = 0
                        total_ee = 0
                        total_ec = 0
                        total_gwp = 0
                        
                        factors_df = db["factors"].set_index("Component")
                        
                        for comp, mass in custom_mix.items():
                            if mass > 0:
                                total_mass += mass
                                if comp in factors_df.index:
                                    factor_row = factors_df.loc[comp]
                                    total_ee += mass * float(factor_row.get('EEF_MJ_kg', 0))
                                    total_ec += mass * float(factor_row.get('ECF_kgCO2_kg', 0))
                                    total_gwp += mass * float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                                    
                        if total_mass > 0:
                            final_props["Total_Mass_kg_m3"] = total_mass
                            final_props["EE_GJ_m3"] = total_ee / 1000
                            final_props["EC_kgCO2_m3"] = total_ec
                            final_props["GWP100_kgCO2e_m3"] = total_gwp
                            final_props["EEF_MJ_kg"] = total_ee / total_mass
                            final_props["ECF_kgCO2_kg"] = total_ec / total_mass
                            final_props["ECFGWP100_kgCO2e_kg"] = total_gwp / total_mass
                    
                    # --- DISPLAY RESULTS (RIGHT SIDE) ---
                    with col_right:
                        st.markdown("#### Material Properties")
                        
                        m_col1, m_col2, m_col3 = st.columns(3)
                        m_col1.metric("Total Mass", f"{final_props['Total_Mass_kg_m3']:,.2f} kg/m³")
                        m_col2.metric("EEF", f"{final_props['EEF_MJ_kg']:,.3f} MJ/kg")
                        m_col3.metric("ECF", f"{final_props['ECF_kgCO2_kg']:,.3f} kgCO2/kg")
                        
                        m_col4, m_col5, m_col6 = st.columns(3)
                        m_col4.metric("GWP100 Factor", f"{final_props['ECFGWP100_kgCO2e_kg']:,.3f} kgCO2e/kg")
                        m_col5.metric("Embodied Energy", f"{final_props['EE_GJ_m3']:,.2f} GJ/m³")
                        m_col6.metric("Embodied Carbon", f"{final_props['EC_kgCO2_m3']:,.2f} kgCO2/m³")
                        
                        st.metric("GWP100 Total", f"{final_props['GWP100_kgCO2e_m3']:,.2f} kgCO2e/m³")
                        
                        # --- PIE CHART (For Mixes Only) ---
                        if is_mix and len(custom_mix) > 0:
                            st.markdown("---")
                            st.markdown("#### Mix Composition (Mass %)")
                            
                            # Prepare data for Altair Pie Chart
                            chart_data = pd.DataFrame({
                                "Component": list(custom_mix.keys()),
                                "Mass": list(custom_mix.values())
                            })
                            chart_data = chart_data[chart_data["Mass"] > 0]
                            
                            # Create an interactive donut/pie chart
                            pie_chart = alt.Chart(chart_data).mark_arc(innerRadius=40).encode(
                                theta=alt.Theta(field="Mass", type="quantitative"),
                                color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="right")),
                                tooltip=["Component", "Mass"]
                            ).properties(height=300)
                            
                            st.altair_chart(pie_chart, use_container_width=True)

if st.session_state.user_id is None:
    login_page()
else:
    main_calculator()

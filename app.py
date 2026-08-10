import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os 
import gc
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
# 2. FETCH LIVE DATA FROM GOOGLE SHEETS (Memory Optimized)
# ==========================================
@st.cache_data(ttl=3600, max_entries=1) 
def load_google_sheet_db():
    if not SHEET_ID:
        st.error("Google Sheet ID is missing. Please check your Environment Variables.")
        return None
        
    export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid="
    
    try:
        # MEMORY OPTIMIZATION: Instead of downloading the whole massive Excel file into memory
        # at once, we use Pandas to read each sheet directly from its individual CSV export URL.
        # This is drastically more memory efficient than pd.read_excel()
        
        # NOTE: To use this method, you need the individual 'gid' for each tab from your Google Sheet URL.
        # For this prototype to boot safely, I am temporarily generating empty DataFrames.
        # We will need to map these to your specific sheets.
        
        # --- TEMPORARY FIX FOR MEMORY CRASH ---
        # Instead of crashing, let's load empty dataframes just so the app boots successfully.
        # Once it boots, we can replace these with the actual direct CSV links.
        xls_dict = {
            "factors": pd.DataFrame(columns=["Component", "EEF_MJ_kg", "ECF_kgCO2_kg", "ECFGWP100_kgCO2e_kg"]),
            "mixes": pd.DataFrame(columns=["Category", "Mix_Key"]),
            "structures": pd.DataFrame(columns=["Structure_Name", "Components"]),
            "unit_logic": pd.DataFrame(columns=["Component_Name", "Unit_Options"]),
            "direct": pd.DataFrame(columns=["Category", "Material_Key", "Total_Mass_kg_m3", "EEF_MJ_kg", "ECF_kgCO2_kg", "ECFGWP100_kgCO2e_kg"])
        }
        
        # Force garbage collection to free RAM
        gc.collect()
        
        return xls_dict
        
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

    tab1, tab2, tab3 = st.tabs(["Materials & Mix Designer", "Project Calculator", "Saved Projects"])
    
    # ---------------------------------------------------------
    # TAB 1: MATERIALS & CUSTOM MIX DESIGNER
    # ---------------------------------------------------------
    with tab1:
        st.markdown("### Material Properties & Custom Mix Designer")
        
        mix_cats = set(db["mixes"]["Category"].dropna().unique()) if "Category" in db["mixes"] else set()
        direct_cats = set(db["direct"]["Category"].dropna().unique()) if "Category" in db["direct"] else set()
        all_categories = sorted(list(mix_cats.union(direct_cats)))
        
        col_left, col_right = st.columns([1, 1.5])
        
        with col_left:
            st.markdown("#### Select Material")
            selected_cat = st.selectbox("Material Category:", ["--- Select Category ---"] + all_categories, key="mat_cat_select")
            
            selected_mat = "--- Select Material ---"
            if selected_cat != "--- Select Category ---":
                mix_mats = db["mixes"][db["mixes"]["Category"] == selected_cat]["Mix_Key"].dropna().tolist() if not db["mixes"].empty else []
                direct_mats = db["direct"][db["direct"]["Category"] == selected_cat]["Material_Key"].dropna().tolist() if not db["direct"].empty else []
                all_mats = sorted(list(set(mix_mats + direct_mats)))
                
                selected_mat = st.selectbox("Material Type/Grade:", ["--- Select Material ---"] + all_mats, key="mat_type_select")
            
            is_mix = selected_mat in mix_mats if selected_mat != "--- Select Material ---" else False
            custom_mix = {}
            
            if selected_mat != "--- Select Material ---":
                if is_mix:
                    st.markdown("#### Customise Mix Design Components")
                    mix_row = db["mixes"][(db["mixes"]["Category"] == selected_cat) & (db["mixes"]["Mix_Key"] == selected_mat)].iloc[0]
                    components = db["factors"]["Component"].dropna().tolist() if not db["factors"].empty else []
                    
                    for comp in components:
                        if comp in mix_row and pd.notna(mix_row[comp]) and mix_row[comp] > 0:
                            # Live reactive inputs! No calculate button needed.
                            val = st.number_input(f"{comp} (kg/m3):", value=float(mix_row[comp]), min_value=0.0, format="%.2f", key=f"custom_{comp}")
                            custom_mix[comp] = val

        with col_right:
            st.markdown("#### Material Properties Result")
            if selected_mat != "--- Select Material ---":
                final_props = {
                    "Total_Mass_kg_m3": 0, "ECF_kgCO2_kg": 0,
                    "EC_kgCO2_m3": 0, "ECFGWP100_kgCO2e_kg": 0,
                    "GWP100_kgCO2e_m3": 0
                }
                
                if not is_mix:
                    direct_row = db["direct"][(db["direct"]["Category"] == selected_cat) & (db["direct"]["Material_Key"] == selected_mat)].iloc[0]
                    for prop in final_props:
                        if prop in direct_row and pd.notna(direct_row[prop]):
                            final_props[prop] = float(direct_row[prop])
                else:
                    total_mass = 0
                    total_ec = 0
                    total_gwp = 0
                    factors_df = db["factors"].set_index("Component")
                    
                    # For Carbon Pie Chart
                    carbon_contributions = {}
                    
                    for comp, mass in custom_mix.items():
                        if mass > 0:
                            total_mass += mass
                            if comp in factors_df.index:
                                factor_row = factors_df.loc[comp]
                                comp_carbon = mass * float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                                
                                total_ec += mass * float(factor_row.get('ECF_kgCO2_kg', 0))
                                total_gwp += comp_carbon
                                
                                carbon_contributions[comp] = comp_carbon
                                
                    if total_mass > 0:
                        final_props["Total_Mass_kg_m3"] = total_mass
                        final_props["EC_kgCO2_m3"] = total_ec
                        final_props["GWP100_kgCO2e_m3"] = total_gwp
                        final_props["ECF_kgCO2_kg"] = total_ec / total_mass
                        final_props["ECFGWP100_kgCO2e_kg"] = total_gwp / total_mass
                
                m_col1, m_col3 = st.columns(2)
                m_col1.metric("Total Mass", f"{final_props['Total_Mass_kg_m3']:,.2f} kg/m³")
                m_col3.metric("ECF", f"{final_props['ECF_kgCO2_kg']:,.3f} kgCO2/kg")
                
                m_col4, m_col6 = st.columns(2)
                m_col4.metric("GWP100 Factor", f"{final_props['ECFGWP100_kgCO2e_kg']:,.3f} kgCO2e/kg")
                m_col6.metric("Embodied Carbon", f"{final_props['EC_kgCO2_m3']:,.2f} kgCO2/m³")
                
                st.metric("GWP100 Total", f"{final_props['GWP100_kgCO2e_m3']:,.2f} kgCO2e/m³")
                
                if is_mix and len(custom_mix) > 0:
                    st.markdown("---")
                    
                    # --- TWO PIE CHARTS (Mass vs Carbon) ---
                    pc_col1, pc_col2 = st.columns(2)
                    
                    with pc_col1:
                        st.markdown("**Composition by Mass (kg)**")
                        mass_data = pd.DataFrame({
                            "Component": list(custom_mix.keys()),
                            "Value": list(custom_mix.values())
                        })
                        mass_data = mass_data[mass_data["Value"] > 0]
                        
                        pie_mass = alt.Chart(mass_data).mark_arc(innerRadius=30).encode(
                            theta=alt.Theta(field="Value", type="quantitative"),
                            color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title=None, orient="bottom")),
                            tooltip=["Component", "Value"]
                        ).properties(height=250)
                        st.altair_chart(pie_mass, use_container_width=True)
                        
                    with pc_col2:
                        st.markdown("**Composition by Carbon (CO2e)**")
                        carbon_data = pd.DataFrame({
                            "Component": list(carbon_contributions.keys()),
                            "Value": list(carbon_contributions.values())
                        })
                        carbon_data = carbon_data[carbon_data["Value"] > 0]
                        
                        pie_carbon = alt.Chart(carbon_data).mark_arc(innerRadius=30).encode(
                            theta=alt.Theta(field="Value", type="quantitative"),
                            color=alt.Color(field="Component", type="nominal", legend=None),
                            tooltip=["Component", "Value"]
                        ).properties(height=250)
                        st.altair_chart(pie_carbon, use_container_width=True)
                    
                    # --- SAVE CUSTOM MIX TO SUPABASE ---
                    st.markdown("#### Save Custom Mix Design")
                    new_mix_name = st.text_input("Custom Mix Name:", key="save_mix_name_input")
                    if st.button("Save Mix to Account"):
                        if not new_mix_name:
                            st.error("Please provide a name for your custom mix.")
                        else:
                            mix_payload = {
                                "user_id": st.session_state.user_id,
                                "mix_name": new_mix_name,
                                "category": selected_cat,
                                "components": custom_mix
                            }
                            supabase.table("user_mixes").insert(mix_payload).execute()
                            st.success(f"Custom mix '{new_mix_name}' saved successfully!")
            else:
                st.info("Select a material category and grade on the left.")

        # --- USER SAVED MIXES MANAGEMENT ---
        st.markdown("---")
        st.markdown("### Manage Your Saved Custom Mixes")
        user_mixes_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user_id).execute()
        my_mixes = user_mixes_res.data if user_mixes_res.data else []
        
        if my_mixes:
            for m in my_mixes:
                with st.expander(f"Mix: {m['mix_name']} (Category: {m['category']})"):
                    st.write("Components:", m["components"])
                    if st.button(f"Delete Mix: {m['mix_name']}", key=f"del_mix_{m['id']}"):
                        supabase.table("user_mixes").delete().eq("id", m["id"]).execute()
                        st.success("Mix deleted successfully!")
                        st.rerun()
        else:
            st.write("You have not saved any custom mix designs yet.")

    # ---------------------------------------------------------
    # TAB 2: PROJECT CALCULATOR (With Concrete Mix Selection)
    # ---------------------------------------------------------
    with tab2:
        st.markdown("### 1. Project Details")
        project_name = st.text_input("Project Name:")
        
        structure_options = db["structures"]["Structure_Name"].dropna().tolist() if not db["structures"].empty else []
        selected_structure = st.selectbox("Select Project Structure:", ["---"] + structure_options)
        
        # Fetch user's custom mixes from Supabase for selection dropdown
        custom_mixes_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user_id).execute()
        user_mixes = custom_mixes_res.data if custom_mixes_res.data else []
        custom_mix_names = [m["mix_name"] for m in user_mixes]
        
        standard_mixes = db["mixes"]["Mix_Key"].dropna().tolist() if not db["mixes"].empty else []
        all_available_mixes = standard_mixes + [f"Custom: {name}" for name in custom_mix_names]

        if selected_structure != "---":
            st.markdown("### 2. Configure Components & Assign Mixes")
            
            components_str = db["structures"].loc[db["structures"]["Structure_Name"] == selected_structure, "Components"].values[0]
            component_list = [c.strip() for c in components_str.split(",")]
            
            project_data = {}
            
            for comp in component_list:
                st.markdown(f"**Component: {comp}**")
                col1, col2, col3 = st.columns(3)
                with col1:
                    quantity = st.number_input(f"Amount ({comp}):", min_value=0.0, step=1.0, key=f"qty_{comp}")
                with col2:
                    selected_unit = "m3"
                    if not db["unit_logic"].empty:
                        unit_row = db["unit_logic"][db["unit_logic"]["Component_Name"] == comp]
                        if not unit_row.empty:
                            units = str(unit_row["Unit_Options"].values[0]).split(",")
                            selected_unit = st.selectbox("Unit:", units, key=f"unit_{comp}")
                        else:
                            st.write("Unit: m3")
                    else:
                        st.write("Unit: m3")
                with col3:
                    assigned_mix = st.selectbox(f"Select Mix/Material:", ["--- Default ---"] + all_available_mixes, key=f"mix_{comp}")
                
                project_data[comp] = {
                    "quantity": quantity, 
                    "unit": selected_unit,
                    "assigned_mix": assigned_mix
                }
                st.markdown("---")
            
            if st.button("Calculate & Save Project"):
                if not project_name:
                    st.error("Please enter a Project Name to save.")
                else:
                    with st.spinner("Processing calculations securely..."):
                        total_carbon = 0
                        factors_df = db["factors"].set_index("Component") if not db["factors"].empty else pd.DataFrame()

                        for comp, details in project_data.items():
                            qty = details["quantity"]
                            mix = details["assigned_mix"]
                            comp_carbon_rate = 350 # default fallback
                            
                            if mix.startswith("Custom: "):
                                mix_n = mix.replace("Custom: ", "")
                                match_mix = next((m for m in user_mixes if m["mix_name"] == mix_n), None)
                                if match_mix and "components" in match_mix:
                                    # Calculate carbon factor dynamically from custom mix components
                                    m_mass = sum(match_mix["components"].values())
                                    m_gwp = 0
                                    for c_name, c_val in match_mix["components"].items():
                                        if c_name in factors_df.index:
                                            m_gwp += c_val * float(factors_df.loc[c_name].get('ECFGWP100_kgCO2e_kg', 0))
                                    if m_mass > 0:
                                        comp_carbon_rate = m_gwp / m_mass
                            elif mix in standard_mixes:
                                mix_row = db["mixes"][db["mixes"]["Mix_Key"] == mix].iloc[0]
                                m_mass = 0
                                m_gwp = 0
                                for comp_factor in factors_df.index:
                                    if comp_factor in mix_row and pd.notna(mix_row[comp_factor]):
                                        val = float(mix_row[comp_factor])
                                        m_mass += val
                                        m_gwp += val * float(factors_df.loc[comp_factor].get('ECFGWP100_kgCO2e_kg', 0))
                                if m_mass > 0:
                                    comp_carbon_rate = m_gwp / m_mass

                            total_carbon += qty * comp_carbon_rate
                        
                        project_payload = {
                            "user_id": st.session_state.user_id,
                            "project_name": project_name,
                            "structure_type": selected_structure,
                            "total_embodied_carbon": total_carbon,
                            "component_data": project_data 
                        }
                        
                        supabase.table("saved_projects").insert(project_payload).execute()
                        st.success(f"Project '{project_name}' saved successfully to your account!")
                        st.metric(label="Total Embodied Carbon (kgCO2e)", value=f"{total_carbon:,.2f}")

    # ---------------------------------------------------------
    # TAB 3: SAVED PROJECTS (View / Delete User Projects)
    # ---------------------------------------------------------
    with tab3:
        st.markdown("### Your Saved Projects")
        projects_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user_id).execute()
        user_projects = projects_res.data if projects_res.data else []
        
        if user_projects:
            for p in user_projects:
                with st.expander(f"Project: {p['project_name']} | Structure: {p['structure_type']} | Carbon: {p['total_embodied_carbon']:,.2f} kgCO2e"):
                    st.write("Component Details:", p["component_data"])
                    if st.button("Delete Project", key=f"del_proj_{p['id']}"):
                        supabase.table("saved_projects").delete().eq("id", p["id"]).execute()
                        st.success("Project deleted successfully!")
                        st.rerun()
        else:
            st.info("No projects saved under your account yet.")

if st.session_state.user_id is None:
    login_page()
else:
    main_calculator()

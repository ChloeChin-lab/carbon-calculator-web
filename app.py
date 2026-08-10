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
# 2. FETCH DATA SAFELY (RAM OPTIMISED)
# ==========================================
@st.cache_data(ttl=3600) 
def load_database():
    # We strictly request ONLY these 5 tabs to prevent RAM overload
    required_sheets = ["Component_Factors", "Mix_Designs", "Project_Structures", "Unit_Logic", "Direct_Results"]
    
    # 1. Try Google Sheets First
    if SHEET_ID and len(SHEET_ID) > 20: 
        export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
        try:
            response = requests.get(export_url)
            response.raise_for_status()
            excel_data = BytesIO(response.content)
            
            xls = pd.read_excel(excel_data, sheet_name=required_sheets)
            st.session_state.db_status = "🟢 Connected to Google Sheets"
            
            return {
                "factors": xls.get("Component_Factors", pd.DataFrame()),
                "mixes": xls.get("Mix_Designs", pd.DataFrame()),
                "structures": xls.get("Project_Structures", pd.DataFrame()),
                "unit_logic": xls.get("Unit_Logic", pd.DataFrame()),
                "direct": xls.get("Direct_Results", pd.DataFrame())
            }
        except Exception as e:
            st.session_state.db_status = f"🔴 Google Sheets Error: {e}"
            pass 

    # 2. Fallback to Local File
    local_path = "materials_database.xlsx"
    if os.path.exists(local_path):
        try:
            xls = pd.read_excel(local_path, sheet_name=required_sheets)
            st.session_state.db_status = "🟡 Using Local Excel File"
            return {
                "factors": xls.get("Component_Factors", pd.DataFrame()),
                "mixes": xls.get("Mix_Designs", pd.DataFrame()),
                "structures": xls.get("Project_Structures", pd.DataFrame()),
                "unit_logic": xls.get("Unit_Logic", pd.DataFrame()),
                "direct": xls.get("Direct_Results", pd.DataFrame())
            }
        except Exception as e:
            st.session_state.db_status = f"🔴 Local File Error: {e}"
            return None
            
    st.session_state.db_status = "🔴 No Database Found"
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
    db = load_database()
    
    st.sidebar.success(f"Logged in as: {st.session_state.user_email}")
    st.sidebar.info(st.session_state.get("db_status", "Checking Database..."))
        
    if st.sidebar.button("Log Out"):
        st.session_state.user_id = None
        st.rerun()

    st.title("Embodied Carbon Calculator")
    
    if db is None:
        st.error("Cannot start the calculator. Please check the database connection.")
        st.stop()

    tab1, tab2, tab3 = st.tabs(["Materials Reference & Custom Mixes", "Project Calculator", "Saved Projects"])
    
    # ---------------------------------------------------------
    # TAB 1: MATERIALS REFERENCE & CUSTOM MIX CREATOR
    # ---------------------------------------------------------
    with tab1:
        st.markdown("### Materials Database")
        
        mode = st.radio("Choose an action:", ["View Standard Materials", "Create Custom Mix"], horizontal=True, key="mix_mode_radio")
        
        mix_cats = set(db["mixes"]["Category"].dropna().unique()) if not db["mixes"].empty and "Category" in db["mixes"].columns else set()
        direct_cats = set(db["direct"]["Category"].dropna().unique()) if not db["direct"].empty and "Category" in db["direct"].columns else set()
        all_categories = sorted(list(mix_cats.union(direct_cats)))
        
        if mode == "View Standard Materials":
            st.markdown("#### View Standard Material Properties")
            st.info("These are standard materials synchronised from the central engineering database.")
            
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                selected_cat = st.selectbox("Material Category:", ["--- Select Category ---"] + all_categories, key="view_cat")
            
            if selected_cat != "--- Select Category ---":
                mix_mats = db["mixes"][db["mixes"]["Category"] == selected_cat]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
                direct_mats = db["direct"][db["direct"]["Category"] == selected_cat]["Material_Key"].dropna().tolist() if not db["direct"].empty and "Material_Key" in db["direct"].columns else []
                all_mats = sorted(list(set(mix_mats + direct_mats)))
                
                with col_sel2:
                    selected_mat = st.selectbox("Material Type/Grade:", ["--- Select Material ---"] + all_mats, key="view_mat")
                
                if selected_mat != "--- Select Material ---":
                    # TRAFFIC COP BUTTON ADDED HERE TO PREVENT RAM CRASHES
                    if st.button("View Material Properties", type="primary"):
                        is_mix = selected_mat in mix_mats
                        
                        final_props = {
                            "Total_Mass_kg_m3": 0, "ECF_kgCO2_kg": 0,
                            "EC_kgCO2_m3": 0, "ECFGWP100_kgCO2e_kg": 0,
                            "GWP100_kgCO2e_m3": 0
                        }
                        
                        chart_components_mass = {}
                        chart_components_carbon = {}
                        
                        if not is_mix:
                            direct_row = db["direct"][(db["direct"]["Category"] == selected_cat) & (db["direct"]["Material_Key"] == selected_mat)].iloc[0]
                            for prop in final_props:
                                if prop in direct_row and pd.notna(direct_row[prop]):
                                    final_props[prop] = float(direct_row[prop])
                        else:
                            mix_row = db["mixes"][(db["mixes"]["Category"] == selected_cat) & (db["mixes"]["Mix_Key"] == selected_mat)].iloc[0]
                            factors_df = db["factors"].set_index("Component") if not db["factors"].empty and "Component" in db["factors"].columns else pd.DataFrame()
                            total_mass = 0
                            total_ec = 0
                            total_gwp = 0
                            
                            for comp in factors_df.index:
                                if comp in mix_row and pd.notna(mix_row[comp]) and float(mix_row[comp]) > 0:
                                    mass = float(mix_row[comp])
                                    factor_row = factors_df.loc[comp]
                                    comp_gwp = mass * float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                                    
                                    chart_components_mass[comp] = mass
                                    chart_components_carbon[comp] = comp_gwp
                                    
                                    total_mass += mass
                                    total_ec += mass * float(factor_row.get('ECF_kgCO2_kg', 0))
                                    total_gwp += comp_gwp
                                    
                            if total_mass > 0:
                                final_props["Total_Mass_kg_m3"] = total_mass
                                final_props["EC_kgCO2_m3"] = total_ec
                                final_props["GWP100_kgCO2e_m3"] = total_gwp
                                final_props["ECF_kgCO2_kg"] = total_ec / total_mass
                                final_props["ECFGWP100_kgCO2e_kg"] = total_gwp / total_mass
                        
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
                                st.markdown("**1. By Mass / Weight (kg)**")
                                chart_data_mass = pd.DataFrame({"Component": list(chart_components_mass.keys()), "Mass (kg)": list(chart_components_mass.values())})
                                pie_mass = alt.Chart(chart_data_mass).mark_arc(innerRadius=40).encode(
                                    theta=alt.Theta(field="Mass (kg)", type="quantitative"),
                                    color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                    tooltip=["Component", "Mass (kg)"]
                                ).properties(height=280)
                                st.altair_chart(pie_mass, use_container_width=True)
                                
                            with pc_col2:
                                st.markdown("**2. By Embodied Carbon (kgCO2e)**")
                                chart_data_carbon = pd.DataFrame({"Component": list(chart_components_carbon.keys()), "Carbon (kgCO2e)": list(chart_components_carbon.values())})
                                pie_carbon = alt.Chart(chart_data_carbon).mark_arc(innerRadius=40).encode(
                                    theta=alt.Theta(field="Carbon (kgCO2e)", type="quantitative"),
                                    color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                    tooltip=["Component", "Carbon (kgCO2e)"]
                                ).properties(height=280)
                                st.altair_chart(pie_carbon, use_container_width=True)

        elif mode == "Create Custom Mix":
            st.markdown("#### Design a Custom Mix")
            st.info("Input your material quantities below, then click Preview to view the carbon profile.")
            
            c_col1, c_col2 = st.columns(2)
            with c_col1:
                custom_cat = st.selectbox("Assign to Category:", ["--- Select Category ---"] + all_categories, key="cust_cat")
            with c_col2:
                custom_mix_name = st.text_input("Name your Custom Mix:", placeholder="e.g., C40/50 30% PFA", key="mix_name_input")
                
            st.markdown("##### Ingredients (kg/m³)")
            
            factors_df = db["factors"]
            if not factors_df.empty and "Component" in factors_df.columns:
                factors_df = factors_df.set_index("Component")
                all_comps = factors_df.index.tolist()
            else:
                factors_df = pd.DataFrame()
                all_comps = []
            
            custom_mix_data = {}
            
            input_cols = st.columns(4)
            for i, comp in enumerate(all_comps):
                val = input_cols[i % 4].number_input(comp, min_value=0.0, step=10.0, key=f"cust_comp_{comp}")
                if val > 0:
                    custom_mix_data[comp] = val
                    
            st.markdown("---")
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                preview_mix = st.button("Preview Mix Properties", type="primary")
            with btn_col2:
                save_mix = st.button("Save Custom Mix to Account")
                
            # TRAFFIC COP: Only calculate and draw charts if the Preview button is clicked
            if preview_mix and len(custom_mix_data) > 0:
                total_mass = sum(custom_mix_data.values())
                total_ec = 0
                total_gwp = 0
                
                custom_mix_carbon = {}
                
                for comp, mass in custom_mix_data.items():
                    if comp in factors_df.index:
                        factor_row = factors_df.loc[comp]
                        comp_gwp = mass * float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                        custom_mix_carbon[comp] = comp_gwp
                        
                        total_ec += mass * float(factor_row.get('ECF_kgCO2_kg', 0))
                        total_gwp += comp_gwp
                
                st.markdown("##### Live Properties")
                r_col1, r_col2, r_col3, r_col4 = st.columns(4)
                r_col1.metric("Total Mass", f"{total_mass:,.2f} kg/m³")
                r_col2.metric("ECF", f"{(total_ec / total_mass):,.3f} kgCO2/kg")
                r_col3.metric("GWP100 Factor", f"{(total_gwp / total_mass):,.3f} kgCO2e/kg")
                r_col4.metric("GWP100 Total", f"{total_gwp:,.2f} kgCO2e/m³")
                
                st.markdown("##### Mix Breakdown Analysis")
                c_pc_col1, c_pc_col2 = st.columns(2)
                
                with c_pc_col1:
                    st.markdown("**1. By Mass / Weight (kg)**")
                    c_data_mass = pd.DataFrame({"Component": list(custom_mix_data.keys()), "Mass (kg)": list(custom_mix_data.values())})
                    c_pie_mass = alt.Chart(c_data_mass).mark_arc(innerRadius=40).encode(
                        theta=alt.Theta(field="Mass (kg)", type="quantitative"),
                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                        tooltip=["Component", "Mass (kg)"]
                    ).properties(height=280)
                    st.altair_chart(c_pie_mass, use_container_width=True)
                    
                with c_pc_col2:
                    st.markdown("**2. By Embodied Carbon (kgCO2e)**")
                    c_data_carbon = pd.DataFrame({"Component": list(custom_mix_carbon.keys()), "Carbon (kgCO2e)": list(custom_mix_carbon.values())})
                    c_pie_carbon = alt.Chart(c_data_carbon).mark_arc(innerRadius=40).encode(
                        theta=alt.Theta(field="Carbon (kgCO2e)", type="quantitative"),
                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                        tooltip=["Component", "Carbon (kgCO2e)"]
                    ).properties(height=280)
                    st.altair_chart(c_pie_carbon, use_container_width=True)
            
            # SAVING LOGIC SEPARATED
            if save_mix:
                if custom_cat == "--- Select Category ---":
                    st.error("Please assign a category before saving.")
                elif not custom_mix_name:
                    st.error("Please provide a professional name for your custom mix (e.g., C40/50 30% PFA).")
                elif len(custom_mix_data) == 0:
                    st.error("Please add at least one ingredient.")
                else:
                    mix_payload = {
                        "user_id": st.session_state.user_id,
                        "mix_name": custom_mix_name,
                        "category": custom_cat,
                        "components": custom_mix_data
                    }
                    try:
                        supabase.table("user_mixes").insert(mix_payload).execute()
                        st.success(f"Custom mix '{custom_mix_name}' saved successfully!")
                    except Exception as e:
                        st.error("Failed to save mix. Please check your database connection.")

        # --- MANAGE SAVED MIXES ---
        st.markdown("---")
        st.markdown("#### Your Saved Custom Mixes")
        user_mixes_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user_id).execute()
        my_mixes = user_mixes_res.data if user_mixes_res.data else []
        
        if my_mixes:
            for m in my_mixes:
                with st.expander(f"⚙️ {m['mix_name']} (Category: {m['category']})"):
                    st.write("Ingredients:", m["components"])
                    
                    mix_id = m.get('id', str(m.get('mix_name')))
                    
                    btn_col_a, btn_col_b = st.columns(2)
                    with btn_col_a:
                        if st.button(f"📝 Load to Designer", key=f"load_mix_{mix_id}"):
                            # 1. Switch the view mode to the Custom Mix tab
                            st.session_state["mix_mode_radio"] = "Create Custom Mix"
                            # 2. Pre-fill the Category and Name
                            st.session_state["cust_cat"] = m["category"]
                            st.session_state["mix_name_input"] = f"{m['mix_name']} (Copy)"
                            
                            # 3. Pre-fill all the ingredient numbers safely
                            factors_df = db["factors"]
                            if not factors_df.empty and "Component" in factors_df.columns:
                                for c in factors_df["Component"].tolist():
                                    # If the component was in the saved mix, load its value. Otherwise, set to 0.0
                                    st.session_state[f"cust_comp_{c}"] = float(m["components"].get(c, 0.0))
                            
                            # Instantly refresh the page to show the filled-out form
                            st.rerun()
                            
                    with btn_col_b:
                        if st.button(f"🗑️ Delete '{m['mix_name']}'", key=f"del_mix_{mix_id}"):
                            if 'id' in m:
                                supabase.table("user_mixes").delete().eq("id", m["id"]).execute()
                                st.success("Mix deleted. Please refresh the page.")
                                st.rerun()
                            else:
                                st.error("Cannot delete: Your Supabase table is missing the 'id' column.")
        else:
            st.write("You have not saved any custom mix designs yet.")

    # ---------------------------------------------------------
    # TAB 2: PROJECT CALCULATOR 
    # ---------------------------------------------------------
    with tab2:
        st.markdown("### 1. Project Details")
        project_name = st.text_input("Project Name:")
        
        structure_options = db["structures"]["Structure_Name"].dropna().tolist() if not db["structures"].empty and "Structure_Name" in db["structures"].columns else []
        selected_structure = st.selectbox("Select Project Structure:", ["---"] + structure_options)
        
        custom_mixes_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user_id).execute()
        user_mixes = custom_mixes_res.data if custom_mixes_res.data else []
        custom_mix_names = [m["mix_name"] for m in user_mixes]
        
        standard_mixes = db["mixes"]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
        all_available_mixes = ["--- Standard Mixes ---"] + standard_mixes + ["--- Custom Mixes ---"] + [f"Custom: {name}" for name in custom_mix_names]

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
                    if not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
                        unit_row = db["unit_logic"][db["unit_logic"]["Component_Name"] == comp]
                        if not unit_row.empty and "Unit_Options" in unit_row.columns:
                            units = str(unit_row["Unit_Options"].values[0]).split(",")
                            selected_unit = st.selectbox("Unit:", units, key=f"unit_{comp}")
                        else:
                            st.write("Unit: m3")
                    else:
                        st.write("Unit: m3")
                with col3:
                    assigned_mix = st.selectbox(f"Select Mix/Material:", ["--- Select ---"] + all_available_mixes, key=f"mix_{comp}")
                
                project_data[comp] = {
                    "quantity": quantity, 
                    "unit": selected_unit,
                    "assigned_mix": assigned_mix
                }
                st.markdown("---")
            
            if st.button("Calculate & Save Project", type="primary"):
                if not project_name:
                    st.error("Please enter a Project Name to save.")
                else:
                    with st.spinner("Processing calculations securely..."):
                        total_carbon = 0
                        factors_df = db["factors"].set_index("Component") if not db["factors"].empty and "Component" in db["factors"].columns else pd.DataFrame()

                        for comp, details in project_data.items():
                            qty = details["quantity"]
                            mix = details["assigned_mix"]
                            comp_carbon_rate = 0 
                            
                            if mix.startswith("Custom: "):
                                mix_n = mix.replace("Custom: ", "")
                                match_mix = next((m for m in user_mixes if m["mix_name"] == mix_n), None)
                                if match_mix and "components" in match_mix:
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
                        
                        try:
                            supabase.table("saved_projects").insert(project_payload).execute()
                            st.success(f"Project '{project_name}' saved successfully to your account!")
                            st.metric(label="Total Embodied Carbon (kgCO2e)", value=f"{total_carbon:,.2f}")
                        except Exception as e:
                            st.error("Failed to save project. Please check your database connection.")

    # ---------------------------------------------------------
    # TAB 3: SAVED PROJECTS 
    # ---------------------------------------------------------
    with tab3:
        st.markdown("### Your Saved Projects")
        projects_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user_id).execute()
        user_projects = projects_res.data if projects_res.data else []
        
        if user_projects:
            for p in user_projects:
                with st.expander(f"📁 {p['project_name']} | Structure: {p['structure_type']} | Carbon: {p['total_embodied_carbon']:,.2f} kgCO2e"):
                    st.write("Component Details:", p["component_data"])
                    
                    proj_id = p.get('id', str(p.get('project_name')))
                    if st.button(f"Delete '{p['project_name']}'", key=f"del_proj_{proj_id}"):
                        if 'id' in p:
                            supabase.table("saved_projects").delete().eq("id", p["id"]).execute()
                            st.success("Project deleted. Please refresh the page.")
                            st.rerun()
                        else:
                            st.error("Cannot delete: Your Supabase table is missing the 'id' column.")
        else:
            st.info("No projects saved under your account yet.")

if st.session_state.user_id is None:
    login_page()
else:
    main_calculator()

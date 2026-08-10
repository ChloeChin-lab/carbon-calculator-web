import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os 
import requests
from io import BytesIO
import altair as alt

st.set_page_config(page_title="Embodied Carbon", layout="wide")

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
    st.session_state.current_page = "Welcome"

def clean_df(df):
    """Safely removes invisible spaces from Excel headers AND text cells."""
    if isinstance(df, pd.DataFrame) and not df.empty:
        df.columns = df.columns.str.strip()
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
    return df

def safe_float(val, default=0.0):
    """Safely handles N/A, dashes, or blanks in Excel cells without crashing."""
    if pd.isna(val):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

# ==========================================
# 2. FETCH DATA SAFELY (RAM OPTIMISED)
# ==========================================
@st.cache_data(ttl=3600) 
def load_database():
    required_sheets = ["Component_Factors", "Mix_Designs", "Project_Structures", "Unit_Logic", "Direct_Results"]
    
    if SHEET_ID and len(SHEET_ID) > 20: 
        export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
        try:
            response = requests.get(export_url)
            response.raise_for_status()
            excel_data = BytesIO(response.content)
            
            xls = pd.read_excel(excel_data, sheet_name=required_sheets)
            st.session_state.db_status = "Connected to Google Sheets"
            
            return {
                "factors": clean_df(xls.get("Component_Factors", pd.DataFrame())),
                "mixes": clean_df(xls.get("Mix_Designs", pd.DataFrame())),
                "structures": clean_df(xls.get("Project_Structures", pd.DataFrame())),
                "unit_logic": clean_df(xls.get("Unit_Logic", pd.DataFrame())),
                "direct": clean_df(xls.get("Direct_Results", pd.DataFrame()))
            }
        except Exception as e:
            st.session_state.db_status = f"Google Sheets Error: {e}"
            pass 

    local_path = "materials_database.xlsx"
    if os.path.exists(local_path):
        try:
            xls = pd.read_excel(local_path, sheet_name=required_sheets)
            st.session_state.db_status = "Using Local Excel File"
            return {
                "factors": clean_df(xls.get("Component_Factors", pd.DataFrame())),
                "mixes": clean_df(xls.get("Mix_Designs", pd.DataFrame())),
                "structures": clean_df(xls.get("Project_Structures", pd.DataFrame())),
                "unit_logic": clean_df(xls.get("Unit_Logic", pd.DataFrame())),
                "direct": clean_df(xls.get("Direct_Results", pd.DataFrame()))
            }
        except Exception as e:
            st.session_state.db_status = f"Local File Error: {e}"
            return None
            
    st.session_state.db_status = "No Database Found"
    return None

# ==========================================
# 3. SECURE LOGIN UI (INVITE-ONLY)
# ==========================================
def login_page():
    st.title("Embodied Carbon")
    
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

def load_mix_to_session(mix_data, factors_dataframe):
    """Callback to safely inject data for the Edit button."""
    st.session_state["mix_mode_radio"] = "Create Custom Mix"
    st.session_state["cust_cat"] = mix_data["category"]
    st.session_state["mix_name_input"] = f"{mix_data['mix_name']} (Copy)"
    
    if not factors_dataframe.empty and "Component" in factors_dataframe.columns:
        for c in factors_dataframe["Component"].tolist():
            st.session_state[f"cust_comp_{c}"] = safe_float(mix_data["components"].get(c, 0.0))
            
    if "adhoc_materials" in mix_data and mix_data["adhoc_materials"]:
        st.session_state["adhoc_mats"] = pd.DataFrame(mix_data["adhoc_materials"])

def calculate_mix_carbon(mix_name, db, user_mixes, factors_df):
    """Helper function to calculate carbon and mass for any mix (standard or custom)."""
    m_mass = 0
    m_gwp = 0
    
    if mix_name.startswith("Custom: "):
        mix_n = mix_name.replace("Custom: ", "")
        match_mix = next((m for m in user_mixes if m["mix_name"] == mix_n), None)
        if match_mix and "components" in match_mix:
            for c_name, c_val in match_mix["components"].items():
                c_val = safe_float(c_val)
                if c_name in factors_df.index:
                    m_gwp += c_val * safe_float(factors_df.loc[c_name].get('ECFGWP100_kgCO2e_kg', 0))
                m_mass += c_val
                
            if "adhoc_materials" in match_mix:
                for adhoc in match_mix["adhoc_materials"]:
                    q = safe_float(adhoc.get("Quantity", 0))
                    gwp_factor = safe_float(adhoc.get("GWP100 (kgCO2e/kg)", 0))
                    m_mass += q
                    m_gwp += q * gwp_factor
    else:
        match_df = db["mixes"][db["mixes"]["Mix_Key"] == mix_name]
        if not match_df.empty:
            mix_row = match_df.iloc[0]
            for comp_factor in factors_df.index:
                if comp_factor in mix_row and pd.notna(mix_row[comp_factor]):
                    val = safe_float(mix_row[comp_factor])
                    m_mass += val
                    m_gwp += val * safe_float(factors_df.loc[comp_factor].get('ECFGWP100_kgCO2e_kg', 0))
                    
    return {
        "Mix": mix_name.replace("Custom: ", ""),
        "Mass (kg/m3)": m_mass,
        "Carbon (kgCO2e/m3)": m_gwp,
        "Factor (kgCO2e/kg)": (m_gwp / m_mass) if m_mass > 0 else 0
    }

# ==========================================
# 4. MAIN APP UI
# ==========================================
def main_app():
    db = load_database()
    
    st.sidebar.markdown(f"**User:** {st.session_state.user_email}")
    st.sidebar.markdown(f"**Status:** {st.session_state.get('db_status', 'Checking...')}")
    
    if st.sidebar.button("Log Out"):
        st.session_state.user_id = None
        st.rerun()
        
    if db is None:
        st.error("Cannot start the system. Please check the database connection.")
        st.stop()

    # Dynamic Navigation Logic
    if st.session_state.current_page != "Welcome":
        st.sidebar.markdown("---")
        if st.sidebar.button("← Return to Home", use_container_width=True):
            st.session_state.current_page = "Welcome"
            st.rerun()
            
        pages = ["Materials & Mixes", "Project Assessment", "Saved Projects"]
        try:
            current_idx = pages.index(st.session_state.current_page)
        except ValueError:
            current_idx = 0
            
        selected_page = st.sidebar.radio(
            "Select Module:", 
            pages, 
            index=current_idx,
            label_visibility="collapsed"
        )
        
        if selected_page != st.session_state.current_page:
            st.session_state.current_page = selected_page
            st.rerun()

    nav_selection = st.session_state.current_page
    st.title("Embodied Carbon")

    user_mixes_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user_id).execute()
    user_mixes = user_mixes_res.data if user_mixes_res.data else []
    custom_mix_names = [m["mix_name"] for m in user_mixes]
    
    standard_mixes = db["mixes"]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
    all_available_mixes = standard_mixes + [f"Custom: {name}" for name in custom_mix_names]
    factors_df = db["factors"].drop_duplicates(subset=["Component"]).set_index("Component") if not db["factors"].empty and "Component" in db["factors"].columns else pd.DataFrame()

    # ---------------------------------------------------------
    # WELCOME PAGE
    # ---------------------------------------------------------
    if nav_selection == "Welcome":
        st.markdown("Please select a module below to begin.")
        st.markdown("---")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader("Materials & Mixes")
            st.write("Review standard material properties from the database, design custom mixes, and compare options.")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Access Materials", use_container_width=True):
                st.session_state.current_page = "Materials & Mixes"
                st.rerun()
        with col2:
            st.subheader("Project Assessment")
            st.write("Assign materials to structural components to calculate the total embodied carbon of your construction projects.")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Access Projects", use_container_width=True):
                st.session_state.current_page = "Project Assessment"
                st.rerun()
        with col3:
            st.subheader("Saved Projects")
            st.write("Access, review, and manage your previously saved construction projects.")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Access Saved Data", use_container_width=True):
                st.session_state.current_page = "Saved Projects"
                st.rerun()

    # ---------------------------------------------------------
    # MODULE: MATERIALS REFERENCE & CUSTOM MIX CREATOR
    # ---------------------------------------------------------
    elif nav_selection == "Materials & Mixes":
        st.markdown("### Materials Database")
        
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
                mix_mats = db["mixes"][db["mixes"]["Category"] == selected_cat]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
                direct_mats = db["direct"][db["direct"]["Category"] == selected_cat]["Material_Key"].dropna().tolist() if not db["direct"].empty and "Material_Key" in db["direct"].columns else []
                all_mats = sorted(list(set(mix_mats + direct_mats)))
                
                with col_sel2:
                    selected_mat = st.selectbox("Material Type/Grade:", ["--- Select Material ---"] + all_mats, key="view_mat")
                
                if selected_mat != "--- Select Material ---":
                    if st.button("View Material Properties", type="primary"):
                        is_mix = selected_mat in mix_mats
                        
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
                                    st.error(f"Could not find exact data for '{selected_mat}'. Check your Excel file for typos.")
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
                                    st.error(f"Could not find exact data for mix '{selected_mat}'. Check your Excel file for typos.")
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
                            st.error(f"Calculation Error: Something went wrong while parsing the Excel data for this material. Details: {e}")

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
                
            st.markdown("##### 2. Ingredients")
            
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
                    
            st.markdown("##### 3. Add Missing/Custom Ingredients")
            st.write("To delete a row, click the grey box on the far left of the row to highlight it, then press the Delete key.")
            
            if "adhoc_mats" not in st.session_state:
                st.session_state.adhoc_mats = pd.DataFrame(columns=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)", "ECF (kgCO2/kg)"])
                
            edited_adhoc_df = st.data_editor(
                st.session_state.adhoc_mats, 
                num_rows="dynamic", 
                use_container_width=True,
                key="adhoc_editor"
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
                    st.error("Please provide a professional name for your custom mix (e.g., C40/50).")
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
                            st.success(f"Custom mix '{custom_mix_name}' saved successfully!")
                            st.rerun() 
                        except Exception as e:
                            st.error(f"Failed to save mix. Details: {e}")

        elif mode == "Compare Mixes":
            st.markdown("#### Compare Mix Designs")
            
            selected_to_compare = st.multiselect("Select Mixes to Compare:", all_available_mixes)
            
            if len(selected_to_compare) > 0:
                comparison_data = []
                for mix in selected_to_compare:
                    props = calculate_mix_carbon(mix, db, user_mixes, factors_df)
                    comparison_data.append(props)
                    
                comp_df = pd.DataFrame(comparison_data)
                
                st.markdown("---")
                chart_col1, chart_col2 = st.columns(2)
                
                with chart_col1:
                    st.markdown("**Embodied Carbon Comparison (GWP100 Total)**")
                    bar_gwp = alt.Chart(comp_df).mark_bar().encode(
                        x=alt.X('Mix', sort='-y', title="Mix Name"),
                        y=alt.Y('Carbon (kgCO2e/m3)', title="Total kgCO2e/m³"),
                        color=alt.Color('Mix', legend=None),
                        tooltip=['Mix', alt.Tooltip('Carbon (kgCO2e/m3)', format='.2f')]
                    ).properties(height=300)
                    st.altair_chart(bar_gwp, use_container_width=True)
                    
                with chart_col2:
                    st.markdown("**Mass vs Carbon Factor (Efficiency)**")
                    scatter_eff = alt.Chart(comp_df).mark_circle(size=200).encode(
                        x=alt.X('Mass (kg/m3)', title="Total Mass (kg/m³)"),
                        y=alt.Y('Factor (kgCO2e/kg)', title="Carbon Factor (kgCO2e/kg)"),
                        color=alt.Color('Mix', legend=alt.Legend(orient="bottom")),
                        tooltip=['Mix', alt.Tooltip('Mass (kg/m3)', format='.2f'), alt.Tooltip('Factor (kgCO2e/kg)', format='.3f')]
                    ).properties(height=300)
                    st.altair_chart(scatter_eff, use_container_width=True)
                
                if len(comp_df) > 1:
                    lowest_carbon_mix = comp_df.loc[comp_df['Carbon (kgCO2e/m3)'].idxmin()]
                    highest_carbon_mix = comp_df.loc[comp_df['Carbon (kgCO2e/m3)'].idxmax()]
                    
                    st.success(f"**Conclusion:** The most sustainable choice is **{lowest_carbon_mix['Mix']}**, generating the lowest total embodied carbon ({lowest_carbon_mix['Carbon (kgCO2e/m3)']:,.2f} kgCO2e/m³).")
                    
                    diff_percent = ((highest_carbon_mix['Carbon (kgCO2e/m3)'] - lowest_carbon_mix['Carbon (kgCO2e/m3)']) / highest_carbon_mix['Carbon (kgCO2e/m3)']) * 100
                    if diff_percent > 0:
                        st.info(f"Choosing **{lowest_carbon_mix['Mix']}** over **{highest_carbon_mix['Mix']}** saves **{diff_percent:.1f}%** in carbon emissions per cubic meter.")

        st.markdown("---")
        st.markdown("#### Your Saved Custom Mix Library")

        if user_mixes:
            for m in user_mixes:
                with st.expander(f"{m['mix_name']} (Category: {m['category']})"):
                    st.write("Ingredients:", m["components"])
                    if "adhoc_materials" in m and m["adhoc_materials"]:
                        st.write("Custom Ingredients:", m["adhoc_materials"])
                    
                    mix_id = m.get('id', str(m.get('mix_name')))
                    del_key = f"del_mix_confirm_{mix_id}"
                    
                    btn_col_a, btn_col_b = st.columns(2)
                    with btn_col_a:
                        st.button(
                            "Duplicate and Edit", 
                            key=f"load_mix_{mix_id}", 
                            on_click=load_mix_to_session, 
                            args=(m, db["factors"])
                        )
                            
                    with btn_col_b:
                        if not st.session_state.get(del_key, False):
                            if st.button("Delete", key=f"btn_del_init_{mix_id}"):
                                st.session_state[del_key] = True
                                st.rerun()
                        else:
                            st.warning("Are you sure you want to permanently delete this mix design? This action cannot be undone.")
                            y_col, n_col = st.columns(2)
                            if y_col.button("Yes, Delete", key=f"btn_del_yes_{mix_id}"):
                                if 'id' in m:
                                    supabase.table("user_mixes").delete().eq("id", m["id"]).execute()
                                    st.session_state[del_key] = False
                                    st.success("Mix deleted.")
                                    st.rerun()
                                else:
                                    st.error("Missing 'id' column in Supabase.")
                            if n_col.button("Cancel", key=f"btn_del_no_{mix_id}"):
                                st.session_state[del_key] = False
                                st.rerun()
        else:
            st.write("You have not saved any custom mix designs yet.")

    # ---------------------------------------------------------
    # TAB 2: PROJECT ASSESSMENT 
    # ---------------------------------------------------------
    elif nav_selection == "Project Assessment":
        st.markdown("### 1. Project Details")
        project_name = st.text_input("Project Name:")
        
        structure_options = db["structures"]["Structure_Name"].dropna().tolist() if not db["structures"].empty and "Structure_Name" in db["structures"].columns else []
        selected_structure = st.selectbox("Select Project Structure:", ["---"] + structure_options)

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

                        for comp, details in project_data.items():
                            qty = details["quantity"]
                            mix = details["assigned_mix"]
                            comp_carbon_rate = 0 
                            
                            if mix != "--- Select ---":
                                props = calculate_mix_carbon(mix, db, user_mixes, factors_df)
                                comp_carbon_rate = props["Carbon (kgCO2e/m3)"]

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
                            st.success(f"Project '{project_name}' saved successfully!")
                            st.metric(label="Total Embodied Carbon (kgCO2e)", value=f"{total_carbon:,.2f}")
                        except Exception as e:
                            st.error(f"Failed to save project. Details: {e}")

    # ---------------------------------------------------------
    # TAB 3: SAVED PROJECTS 
    # ---------------------------------------------------------
    elif nav_selection == "Saved Projects":
        st.markdown("### Your Project Library")
        
        projects_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user_id).execute()
        user_projects = projects_res.data if projects_res.data else []
        
        if user_projects:
            for p in user_projects:
                with st.expander(f"{p['project_name']} | Structure: {p['structure_type']} | Carbon: {p['total_embodied_carbon']:,.2f} kgCO2e"):
                    st.write("Component Details:", p["component_data"])
                    
                    proj_id = p.get('id', str(p.get('project_name')))
                    del_key = f"del_proj_confirm_{proj_id}"
                    
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
    main_app()

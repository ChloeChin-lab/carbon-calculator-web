import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from supabase import create_client, Client
import time
from datetime import datetime
import json
import uuid
import os

# Silent import for FPDF - won't crash if not installed
try:
    from fpdf import FPDF
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

st.set_page_config(
    page_title="Sustainability Assessment System",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    /* Button Color Coding */
    .btn-green button { background-color: #10b981 !important; color: white !important; border: none !important; }
    .btn-green button:hover { background-color: #059669 !important; }
    
    .btn-red button { background-color: #ef4444 !important; color: white !important; border: none !important; }
    .btn-red button:hover { background-color: #dc2626 !important; }
    
    .btn-blue button { background-color: #3b82f6 !important; color: white !important; border: none !important; }
    .btn-blue button:hover { background-color: #2563eb !important; }
    
    .btn-grey button { background-color: #64748b !important; color: white !important; border: none !important; }
    .btn-grey button:hover { background-color: #475569 !important; }
    
    /* Login Page Styling */
    .login-container {
        max-width: 400px;
        margin: 100px auto;
        padding: 30px;
        border-radius: 10px;
        background-color: var(--background-color);
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        text-align: center;
    }
    .login-title {
        font-size: 24px;
        font-weight: bold;
        margin-bottom: 20px;
        /* Removed color: white to allow adaptive text (black in light mode, white in dark mode) */
    }
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def init_supabase():
    # 1. Try fetching from Environment Variables (Render, Heroku, etc.)
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    
    # 2. Try fetching from Streamlit Secrets (Local testing)
    if not SUPABASE_URL or not SUPABASE_KEY:
        try:
            SUPABASE_URL = st.secrets["SUPABASE_URL"]
            SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
        except Exception:
            pass
            
    # 3. Fallback dummy client if neither is found (prevents crash on boot)
    if not SUPABASE_URL or not SUPABASE_KEY or SUPABASE_URL == "YOUR_SUPABASE_URL":
        class DummySupabase:
            def auth(self): return self
            def sign_in_with_password(self, *args, **kwargs): raise Exception("Database credentials missing. Please configure Supabase URL and Key.")
        return DummySupabase()
        
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

if HAS_PDF:
    class PDFReport(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 15)
            self.cell(0, 10, 'Sustainability Comparison Report', 0, 1, 'C')
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')
else:
    class PDFReport:
        pass

def create_pdf_report(df, best_material, reduction_pct):
    if not HAS_PDF: return None
    pdf = PDFReport()
    pdf.add_page()
    
    # Summary
    pdf.set_font('Arial', 'B', 12)
    pdf.cell(0, 10, 'Executive Summary', 0, 1)
    pdf.set_font('Arial', '', 11)
    
    summary_text = (
        f"This report evaluates the global warming potential of selected materials. "
        f"The analysis identifies '{best_material}' as the optimal choice. "
        f"Choosing this material over the highest-impact option results in a "
        f"{reduction_pct}% reduction in embodied carbon per unit volume. For large-scale "
        f"infrastructure applications, this substitution represents a highly effective "
        f"decarbonisation strategy."
    )
    pdf.multi_cell(0, 10, summary_text)
    pdf.ln(5)
    
    # Data Table
    pdf.set_font('Arial', 'B', 10)
    columns = ['Material / Mix Name', 'Total Mass (kg)', 'GWP100 Total (kg CO2e)']
    col_widths = [80, 50, 50]
    
    for i, col in enumerate(columns):
        pdf.cell(col_widths[i], 10, col, 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font('Arial', '', 10)
    for index, row in df.iterrows():
        pdf.cell(col_widths[0], 10, str(row['Name'])[:40], 1, 0, 'L')
        pdf.cell(col_widths[1], 10, f"{row['Total Mass (kg)']:.2f}", 1, 0, 'C')
        pdf.cell(col_widths[2], 10, f"{row['GWP100 Total']:.2f}", 1, 0, 'C')
        pdf.ln()
        
    return pdf.output(dest='S').encode('latin-1')

@st.cache_data(ttl=600)
def load_database():
    try:
        # Replace these with your actual published Google Sheets CSV links
        DIRECT_URL = "YOUR_DIRECT_CSV_URL"
        UNIT_URL = "YOUR_UNIT_CSV_URL"
        
        # Using dummy data structure to ensure app runs perfectly out of the box
        direct_data = {
            "Category": ["Concrete", "Steel", "Timber", "Admixtures"],
            "Item_Name": ["Standard C30", "Rebar", "Plywood", "Superplasticiser"],
            "Density_kg_m3": [2400.0, 7850.0, 600.0, 1100.0],
            "GWP100_kgCO2e_kg": [0.15, 1.85, 0.45, 1.2]
        }
        unit_data = {
            "Component_Name": ["Girders", "Deck", "Rebars", "Extra"],
            "Unit_Options": ["m3, tonnes, kg, m, L", "m3, m2", "tonnes, kg, m3 / unit", "m3, L, L/m3"]
        }
        
        df_direct = pd.DataFrame(direct_data)
        df_units = pd.DataFrame(unit_data)
        
        return {"direct": df_direct, "units": df_units}
    except Exception as e:
        st.error(f"Error loading database: {e}")
        return {"direct": pd.DataFrame(), "units": pd.DataFrame()}

db = load_database()

if 'user' not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.markdown('<div class="login-container">', unsafe_allow_html=True)
    st.markdown('<div class="login-title">Sustainability Assessment System</div>', unsafe_allow_html=True)
    
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    
    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
    if st.button("Log In", use_container_width=True):
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            st.session_state.user = res.user
            st.rerun()
        except Exception as e:
            st.error("Invalid credentials. Please contact administration.")
            
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

if "project_data" not in st.session_state:
    st.session_state.project_data = []
if "custom_mixes" not in st.session_state:
    st.session_state.custom_mixes = {}
if "mix_ingredients" not in st.session_state:
    st.session_state.mix_ingredients = []
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Structural Carbon Calculator"

# Retrieve saved custom mixes for dropdowns
try:
    mix_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user.id).execute()
    st.session_state.custom_mixes = {m['mix_name']: m for m in mix_res.data}
except:
    pass

# Helper to clear workspace
def clear_workspace():
    st.session_state.project_data = []
    st.session_state.mix_ingredients = []
    if "edit_project_id" in st.session_state:
        del st.session_state.edit_project_id
    if "edit_mix_id" in st.session_state:
        del st.session_state.edit_mix_id

# Navigation
st.title("Sustainability Assessment System")
st.write(f"Logged in as: {st.session_state.user.email}")

tabs = st.tabs(["Structural Carbon Calculator", "Materials & Mixes", "My Library", "Compare Mixes"])

# Combine direct materials and custom mixes for dropdowns
direct_cats = set(db["direct"]["Category"].dropna().unique()) if not db["direct"].empty and "Category" in db["direct"].columns else set()
all_categories = sorted(list(direct_cats) + ["Custom Mixes"])

with tabs[0]:
    st.header("Project Builder")
    
    with st.expander("Add Component", expanded=True):
        comp_name = st.text_input("Component Name (e.g., Main Girder)")
        comp_qty = st.number_input("Component Quantity (Nos.)", min_value=1, value=1)
        
        cat_sel = st.selectbox("Material Category", all_categories)
        
        # Get specific items based on category
        available_items = []
        is_custom = False
        if cat_sel == "Custom Mixes":
            available_items = list(st.session_state.custom_mixes.keys())
            is_custom = True
        else:
            if not db["direct"].empty:
                available_items = db["direct"][db["direct"]["Category"] == cat_sel]["Item_Name"].tolist()
        
        item_sel = st.selectbox("Material / Mix", available_items if available_items else ["None Available"])
        
        # Unit logic mapping
        default_units = []
        if not db["units"].empty:
            match = db["units"][db["units"]["Component_Name"].str.contains(comp_name, case=False, na=False)]
            if not match.empty:
                default_units = [u.strip() for u in str(match.iloc[0]["Unit_Options"]).split(",")]
        
        master_units = ["m3", "tonnes", "kg", "L", "m3 / unit", "tonnes / unit", "L/m3"]
        combined_units = list(dict.fromkeys(default_units + master_units))
        
        unit_key = "current_unit_selection"
        unit_sel = st.selectbox("Unit", combined_units, key=unit_key)
        
        amount_val = st.number_input("Amount", min_value=0.0, value=0.0, format="%.4f")
        
        # Instant UI updates based on current unit selection
        current_unit = st.session_state.get(unit_key, unit_sel)
        needs_ref = "%" in current_unit or "L/m3" in current_unit
        
        ref_vol, ref_density = 1.0, 2400.0
        if needs_ref:
            st.info(f"Requires reference volume for '{current_unit}' calculation.")
            c1, c2 = st.columns(2)
            ref_vol = c1.number_input("Reference Volume (m³)", min_value=0.0, value=100.0)
            if "% by weight" in current_unit or "% of wt" in current_unit:
                ref_density = c2.number_input("Reference Density (kg/m³)", min_value=0.0, value=2400.0)

        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Add to Project"):
            if item_sel != "None Available":
                # Get Material Properties
                density = 0.0
                gwp = 0.0
                
                if is_custom:
                    mix_data = st.session_state.custom_mixes[item_sel]
                    density = mix_data.get("density", 2400.0)
                    gwp = mix_data.get("gwp100", 0.0)
                else:
                    mat_row = db["direct"][db["direct"]["Item_Name"] == item_sel]
                    if not mat_row.empty:
                        density = mat_row.iloc[0].get("Density_kg_m3", 0.0)
                        gwp = mat_row.iloc[0].get("GWP100_kgCO2e_kg", 0.0)

                # Execute Math Logic
                calc_amount = amount_val
                if "/ unit" in current_unit or "/unit" in current_unit:
                    calc_amount = amount_val * comp_qty
                
                total_mass = 0.0
                if current_unit == "tonnes" or current_unit == "tonnes / unit":
                    total_mass = calc_amount * 1000
                elif current_unit == "kg":
                    total_mass = calc_amount
                elif current_unit == "m3" or current_unit == "m3 / unit":
                    total_mass = calc_amount * density
                elif current_unit == "L":
                    total_mass = (calc_amount / 1000) * density
                elif current_unit == "L/m3":
                    total_mass = ((calc_amount * ref_vol) / 1000) * density
                elif "% by vol" in current_unit:
                    total_mass = (calc_amount / 100) * ref_vol * density
                elif "% by weight" in current_unit or "% of wt" in current_unit:
                    total_mass = (calc_amount / 100) * (ref_vol * ref_density)
                
                total_gwp = total_mass * gwp
                
                st.session_state.project_data.append({
                    "id": str(uuid.uuid4()),
                    "Component": comp_name,
                    "Quantity": comp_qty,
                    "Category": cat_sel,
                    "Material": item_sel,
                    "Unit": current_unit,
                    "Amount": amount_val,
                    "Total_Mass_kg": total_mass,
                    "Total_GWP100": total_gwp
                })
                st.success(f"Added {comp_name} to project!")
                st.rerun()

    # Display Project Data
    if st.session_state.project_data:
        st.subheader("Current Project Layout")
        df_proj = pd.DataFrame(st.session_state.project_data)
        
        display_df = df_proj[["Component", "Quantity", "Material", "Unit", "Amount", "Total_Mass_kg", "Total_GWP100"]]
        st.dataframe(display_df, use_container_width=True)
        
        st.write(f"**Total Project GWP100:** {df_proj['Total_GWP100'].sum():.2f} kg CO2e")
        
        proj_name = st.text_input("Project Name", value="My Sustainable Structure")
        
        col1, col2 = st.columns(2)
        with col1:
            st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
            if st.button("Save Project to Library", use_container_width=True):
                try:
                    # Check for overwrite
                    existing = supabase.table("saved_projects").select("id").eq("project_name", proj_name).eq("user_id", st.session_state.user.id).execute()
                    if existing.data:
                        supabase.table("saved_projects").update({
                            "project_data": json.dumps(st.session_state.project_data),
                            "updated_at": datetime.now().isoformat()
                        }).eq("id", existing.data[0]['id']).execute()
                        st.success("Project updated successfully!")
                    else:
                        supabase.table("saved_projects").insert({
                            "user_id": st.session_state.user.id,
                            "project_name": proj_name,
                            "project_data": json.dumps(st.session_state.project_data)
                        }).execute()
                        st.success("Project saved successfully!")
                    
                    time.sleep(1)
                    clear_workspace()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving project: {e}")
                    
        with col2:
            st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
            if st.button("Clear Workspace", use_container_width=True):
                clear_workspace()
                st.rerun()

with tabs[1]:
    st.header("Custom Material & Mix Builder")
    
    mix_name = st.text_input("Material / Mix Name", value="Custom High-Strength Mix")
    cat_assign = st.selectbox("Assign to Category (Optional)", ["Concrete", "Steel", "Timber", "Other"])
    
    creation_type = st.radio("What type of item are you creating?", 
                             ["Multi-Ingredient Mix (e.g., Concrete, Asphalt)", 
                              "Standalone Material (e.g., Steel, Timber, Polymer)"])
    
    if creation_type == "Standalone Material (e.g., Steel, Timber, Polymer)":
        st.info("Standalone materials do not require ingredient tables. Just input the physical properties.")
        s_col1, s_col2 = st.columns(2)
        stand_density = s_col1.number_input("Density (kg/m³)", value=7850.0)
        stand_gwp = s_col2.number_input("GWP100 (kg CO2e / kg)", value=1.85, format="%.4f")
        
        st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
        if st.button("Save Standalone Material"):
            try:
                supabase.table("user_mixes").insert({
                    "user_id": st.session_state.user.id,
                    "mix_name": mix_name,
                    "category": cat_assign,
                    "ingredients": json.dumps([]),
                    "density": stand_density,
                    "gwp100": stand_gwp
                }).execute()
                st.success("Material saved!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Save error: {e}")
                
    else:
        # Multi-Ingredient logic
        with st.expander("Add Ingredient to Mix", expanded=True):
            i_cat = st.selectbox("Ingredient Category", list(direct_cats))
            i_items = db["direct"][db["direct"]["Category"] == i_cat]["Item_Name"].tolist() if not db["direct"].empty else []
            i_name = st.selectbox("Ingredient", i_items + ["Custom Ad-hoc Material"])
            
            if i_name == "Custom Ad-hoc Material":
                custom_i_name = st.text_input("Ingredient Name")
                i_density = st.number_input("Density (kg/m³)", value=1000.0)
                i_gwp = st.number_input("GWP100 (kg CO2e / kg)", value=0.0)
                actual_name = custom_i_name
            else:
                mat_row = db["direct"][db["direct"]["Item_Name"] == i_name].iloc[0]
                i_density = mat_row.get("Density_kg_m3", 0.0)
                i_gwp = mat_row.get("GWP100_kgCO2e_kg", 0.0)
                actual_name = i_name
                
            i_unit = st.selectbox("Measurement Unit", ["kg/m³", "L/m³", "% by weight"])
            i_amount = st.number_input("Amount per m³", value=0.0)
            
            st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
            if st.button("Add Ingredient"):
                mass_per_m3 = 0.0
                if i_unit == "kg/m³":
                    mass_per_m3 = i_amount
                elif i_unit == "L/m³":
                    mass_per_m3 = (i_amount / 1000) * i_density
                elif i_unit == "% by weight":
                    # Rough approximation based on 2400 base
                    mass_per_m3 = (i_amount / 100) * 2400.0 
                    
                st.session_state.mix_ingredients.append({
                    "Ingredient": actual_name,
                    "Category": i_cat if i_name != "Custom Ad-hoc Material" else "Ad-hoc",
                    "Mass_kg": mass_per_m3,
                    "GWP100_per_kg": i_gwp,
                    "Total_GWP": mass_per_m3 * i_gwp
                })
                st.success("Ingredient added!")
                st.rerun()
                
        if st.session_state.mix_ingredients:
            df_mix = pd.DataFrame(st.session_state.mix_ingredients)
            st.dataframe(df_mix[["Ingredient", "Category", "Mass_kg", "Total_GWP"]], use_container_width=True)
            
            total_mix_density = df_mix["Mass_kg"].sum()
            total_mix_gwp = df_mix["Total_GWP"].sum()
            gwp_factor = total_mix_gwp / total_mix_density if total_mix_density > 0 else 0
            
            st.write(f"**Total Mix Density:** {total_mix_density:.2f} kg/m³")
            st.write(f"**GWP100 Factor:** {gwp_factor:.4f} kg CO2e / kg")
            
            st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
            if st.button("Save Mix Design"):
                try:
                    supabase.table("user_mixes").insert({
                        "user_id": st.session_state.user.id,
                        "mix_name": mix_name,
                        "category": cat_assign,
                        "ingredients": json.dumps(st.session_state.mix_ingredients),
                        "density": total_mix_density,
                        "gwp100": gwp_factor
                    }).execute()
                    st.success("Mix saved successfully!")
                    time.sleep(1)
                    clear_workspace()
                    st.rerun()
                except Exception as e:
                    st.error(f"Save error: {e}")

with tabs[2]:
    lib_tabs = st.tabs(["Saved Projects", "Saved Custom Mixes"])
    
    # 3.1 Saved Projects
    with lib_tabs[0]:
        try:
            proj_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user.id).execute()
            projects = proj_res.data
            
            if not projects:
                st.info("No saved projects found.")
            else:
                p_menu, p_details = st.columns([1, 2])
                
                with p_menu:
                    st.subheader("Project List")
                    selected_proj_id = st.radio("Select Project", [p['id'] for p in projects], format_func=lambda x: [p['project_name'] for p in projects if p['id'] == x][0])
                
                with p_details:
                    active_p = next(p for p in projects if p['id'] == selected_proj_id)
                    st.subheader(active_p['project_name'])
                    
                    # Rename capability
                    new_p_name = st.text_input("Rename Project", value=active_p['project_name'], key=f"rn_{active_p['id']}")
                    if new_p_name != active_p['project_name']:
                        st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                        if st.button("Update Name", key=f"btn_rn_{active_p['id']}"):
                            supabase.table("saved_projects").update({"project_name": new_p_name}).eq("id", active_p['id']).execute()
                            st.success("Name updated!")
                            time.sleep(1)
                            st.rerun()
                            
                    p_data = json.loads(active_p['project_data'])
                    df_p = pd.DataFrame(p_data)
                    st.dataframe(df_p[["Component", "Quantity", "Material", "Total_Mass_kg", "Total_GWP100"]], use_container_width=True)
                    st.write(f"**Total Structural GWP100:** {df_p['Total_GWP100'].sum():.2f} kg CO2e")
                    
                    ac1, ac2 = st.columns(2)
                    with ac1:
                        st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                        if st.button("Clone for Editing", key=f"edit_p_{active_p['id']}", use_container_width=True):
                            st.session_state.project_data = p_data
                            st.success("Project cloned to Builder! Navigate to Tab 1 to edit.")
                    
                    with ac2:
                        st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                        if st.button("Delete Project", key=f"del_p_{active_p['id']}", use_container_width=True):
                            st.session_state.delete_proj_confirm = active_p['id']
                            
                    # OUT-DENTED Delete Confirmation (fixes Streamlit nesting error)
                    if st.session_state.get("delete_proj_confirm") == active_p['id']:
                        st.error("Are you sure you want to permanently delete this project?")
                        yc, nc = st.columns(2)
                        with yc:
                            st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                            if st.button("Yes, Delete", key=f"y_del_p_{active_p['id']}", use_container_width=True):
                                supabase.table("saved_projects").delete().eq("id", active_p['id']).execute()
                                st.session_state.delete_proj_confirm = None
                                st.rerun()
                        with nc:
                            st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                            if st.button("Cancel", key=f"n_del_p_{active_p['id']}", use_container_width=True):
                                st.session_state.delete_proj_confirm = None
                                st.rerun()
        except Exception as e:
            st.error(f"Error loading projects: {e}")

    # 3.2 Saved Custom Mixes
    with lib_tabs[1]:
        if not st.session_state.custom_mixes:
            st.info("No custom materials/mixes found.")
        else:
            mix_list = list(st.session_state.custom_mixes.values())
            m_menu, m_details = st.columns([1, 2])
            
            with m_menu:
                st.subheader("Mix / Material List")
                selected_mix_id = st.radio("Select Mix", [m['id'] for m in mix_list], format_func=lambda x: [m['mix_name'] for m in mix_list if m['id'] == x][0])
            
            with m_details:
                active_m = next(m for m in mix_list if m['id'] == selected_mix_id)
                st.subheader(active_m['mix_name'])
                st.write(f"**Density:** {active_m['density']:.2f} kg/m³ | **GWP100 Factor:** {active_m['gwp100']:.4f} kg CO2e/kg")
                
                # Rename capability
                new_m_name = st.text_input("Rename Material", value=active_m['mix_name'], key=f"rn_{active_m['id']}")
                if new_m_name != active_m['mix_name']:
                    st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                    if st.button("Update Name", key=f"btn_rnm_{active_m['id']}"):
                        supabase.table("user_mixes").update({"mix_name": new_m_name}).eq("id", active_m['id']).execute()
                        st.success("Name updated!")
                        time.sleep(1)
                        st.rerun()
                
                m_ing = json.loads(active_m['ingredients'])
                if m_ing:
                    df_ing = pd.DataFrame(m_ing)
                    st.dataframe(df_ing[["Ingredient", "Mass_kg", "Total_GWP"]], use_container_width=True)
                    
                    # Re-render Pie Charts
                    pie_col1, pie_col2 = st.columns(2)
                    with pie_col1:
                        st.write("Mass Breakdown")
                        c_mass = alt.Chart(df_ing).mark_arc().encode(theta="Mass_kg:Q", color="Ingredient:N", tooltip=["Ingredient", "Mass_kg"])
                        st.altair_chart(c_mass, use_container_width=True)
                    with pie_col2:
                        st.write("Carbon Breakdown")
                        c_carb = alt.Chart(df_ing).mark_arc().encode(theta="Total_GWP:Q", color="Ingredient:N", tooltip=["Ingredient", "Total_GWP"])
                        st.altair_chart(c_carb, use_container_width=True)
                else:
                    st.info("Standalone material (no ingredient breakdown).")
                    
                ac1, ac2 = st.columns(2)
                with ac1:
                    st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                    if st.button("Clone for Editing", key=f"edit_m_{active_m['id']}", use_container_width=True):
                        st.session_state.mix_ingredients = m_ing
                        st.success("Material cloned to Builder! Navigate to Tab 2 to edit.")
                with ac2:
                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                    if st.button("Delete Material", key=f"del_m_{active_m['id']}", use_container_width=True):
                        st.session_state.delete_mix_confirm = active_m['id']
                        
                # OUT-DENTED Delete Confirmation
                if st.session_state.get("delete_mix_confirm") == active_m['id']:
                    st.error("Are you sure you want to permanently delete this material?")
                    yc, nc = st.columns(2)
                    with yc:
                        st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                        if st.button("Yes, Delete", key=f"y_del_m_{active_m['id']}", use_container_width=True):
                            supabase.table("user_mixes").delete().eq("id", active_m['id']).execute()
                            st.session_state.delete_mix_confirm = None
                            st.rerun()
                    with nc:
                        st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                        if st.button("Cancel", key=f"n_del_m_{active_m['id']}", use_container_width=True):
                            st.session_state.delete_mix_confirm = None
                            st.rerun()

with tabs[3]:
    st.header("Technical Material Comparison")
    st.write("Select multiple materials to analyse density-to-carbon trade-offs and ingredient compositions.")
    
    comp_options = db["direct"]["Item_Name"].tolist() if not db["direct"].empty else []
    comp_options += list(st.session_state.custom_mixes.keys())
    
    selected_for_comp = st.multiselect("Select Materials / Mixes to Compare", comp_options)
    
    if len(selected_for_comp) < 2:
        st.info("Please select at least two materials to generate a comparison report.")
    else:
        # Build comparison dataset
        comp_data = []
        ingredient_matrix_data = []
        
        for sel in selected_for_comp:
            if sel in st.session_state.custom_mixes:
                m_data = st.session_state.custom_mixes[sel]
                mass = m_data.get('density', 0.0)
                gwp_factor = m_data.get('gwp100', 0.0)
                gwp_total = mass * gwp_factor
                comp_data.append({"Name": sel, "Total Mass (kg)": mass, "GWP Factor": gwp_factor, "GWP100 Total": gwp_total, "Type": "Custom"})
                
                # Add to matrix
                ings = json.loads(m_data.get('ingredients', '[]'))
                for ing in ings:
                    ingredient_matrix_data.append({
                        "Mix": sel,
                        "Ingredient": ing["Ingredient"],
                        "Amount_kg": ing["Mass_kg"]
                    })
            else:
                mat_row = db["direct"][db["direct"]["Item_Name"] == sel].iloc[0]
                mass = mat_row.get("Density_kg_m3", 0.0)
                gwp_factor = mat_row.get("GWP100_kgCO2e_kg", 0.0)
                gwp_total = mass * gwp_factor
                comp_data.append({"Name": sel, "Total Mass (kg)": mass, "GWP Factor": gwp_factor, "GWP100 Total": gwp_total, "Type": "Standard"})
        
        comp_df = pd.DataFrame(comp_data)
        
        # Sort best to worst
        comp_df = comp_df.sort_values("GWP100 Total").reset_index(drop=True)
        best_name = comp_df.iloc[0]["Name"]
        worst_val = comp_df.iloc[-1]["GWP100 Total"]
        best_val = float(comp_df.iloc[0]["GWP100 Total"]) # Cast to standard float for Altair safety
        reduction_pct = round(((worst_val - best_val) / worst_val) * 100, 1) if worst_val > 0 else 0
        
        st.success(f"**Sustainability Insight:** Choosing '{best_name}' instead of the highest-impact option results in a {reduction_pct}% reduction in embodied carbon per cubic metre.")
        
        c_tabs = st.tabs(["Carbon Leaderboard", "Density vs Carbon Scatter", "Ingredient Matrix"])
        
        with c_tabs[0]:
            st.subheader("Global Warming Potential per m³")
            bar_chart = alt.Chart(comp_df).mark_bar().encode(
                x=alt.X('GWP100 Total:Q', title="Total GWP100 (kg CO2e)"),
                y=alt.Y('Name:N', sort='-x', title="Material"),
                color=alt.condition(
                    alt.datum['GWP100 Total'] == best_val,
                    alt.value('#10b981'),  # Green for best
                    alt.value('#3b82f6')   # Blue for rest
                ),
                tooltip=['Name', 'GWP100 Total', 'Total Mass (kg)']
            ).properties(height=alt.Step(60))
            st.altair_chart(bar_chart, use_container_width=True)
            
        with c_tabs[1]:
            st.subheader("Density vs. Carbon Trade-off")
            st.write("*The bottom-left quadrant represents the ideal engineering zone—materials here are lightweight (reducing structural dead load) while maintaining low embodied carbon.*")
            scatter = alt.Chart(comp_df).mark_circle(size=150).encode(
                x=alt.X('Total Mass (kg):Q', title='Density (kg/m³)', scale=alt.Scale(zero=False)),
                y=alt.Y('GWP100 Total:Q', title='Embodied Carbon (kg CO2e)', scale=alt.Scale(zero=False)),
                color='Type:N',
                tooltip=['Name', 'Total Mass (kg)', 'GWP100 Total']
            ).interactive()
            st.altair_chart(scatter, use_container_width=True)
            
        with c_tabs[2]:
            st.subheader("Side-by-Side Ingredient Matrix")
            if ingredient_matrix_data:
                matrix_df = pd.DataFrame(ingredient_matrix_data)
                pivot_df = matrix_df.pivot(index='Ingredient', columns='Mix', values='Amount_kg').fillna(0)
                st.dataframe(pivot_df.style.format("{:.2f} kg"), use_container_width=True)
            else:
                st.info("None of the selected materials are multi-ingredient custom mixes.")
        
        # Bottom Data Table & Export
        st.subheader("Detailed Metric Breakdown")
        
        def highlight_best(s):
            is_min = s == s.min()
            return ['background-color: #064e3b; color: white' if v else '' for v in is_min]
            
        styled_df = comp_df.style.apply(highlight_best, subset=['Total Mass (kg)', 'GWP Factor', 'GWP100 Total']).format({
            'Total Mass (kg)': "{:.2f}",
            'GWP Factor': "{:.4f}",
            'GWP100 Total': "{:.2f}"
        })
        st.dataframe(styled_df, use_container_width=True)
        
        export_col1, export_col2 = st.columns(2)
        with export_col1:
            csv_data = comp_df.to_csv(index=False).encode('utf-8')
            st.download_button("Download CSV Data", data=csv_data, file_name="material_comparison.csv", mime="text/csv", use_container_width=True)
        
        with export_col2:
            if HAS_PDF:
                pdf_bytes = create_pdf_report(comp_df, best_name, reduction_pct)
                if pdf_bytes:
                    st.download_button("Export PDF Report", data=pdf_bytes, file_name="Sustainability_Report.pdf", mime="application/pdf", use_container_width=True)

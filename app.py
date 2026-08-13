import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from supabase import create_client, Client
import datetime
import io
import time
import os

try:
    from fpdf import FPDF
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

if HAS_PDF:
    class PDFReport(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 15)
            self.cell(0, 10, 'Sustainability Assessment Report', 0, 1, 'C')

        def footer(self):
            self.set_y(-15)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')
else:
    class PDFReport:
        pass

st.set_page_config(page_title="Sustainability Assessment System", layout="wide")

# CSS for intelligent button styling
st.markdown("""
<style>
    .btn-green button { background-color: #10b981 !important; color: white !important; border: none !important; }
    .btn-green button:hover { background-color: #059669 !important; }
    
    .btn-red button { background-color: #ef4444 !important; color: white !important; border: none !important; }
    .btn-red button:hover { background-color: #dc2626 !important; }
    
    .btn-blue button { background-color: #3b82f6 !important; color: white !important; border: none !important; }
    .btn-blue button:hover { background-color: #2563eb !important; }
    
    .btn-grey button { background-color: #64748b !important; color: white !important; border: none !important; }
    .btn-grey button:hover { background-color: #475569 !important; }
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def init_supabase() -> Client:
    # Check Render environment variables first, then fallback to local secrets
    url = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY")
    
    if not url or not key:
        st.error("Database credentials are not configured properly.")
        st.stop()
        
    return create_client(url, key)

supabase = init_supabase()

if 'user' not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    # Centered login portal
    _, col_login, _ = st.columns([1, 1.2, 1])
    
    with col_login:
        st.write("") 
        st.write("")
        st.write("")
        st.markdown("<h2 style='text-align: center;'>Sustainability Assessment System</h2>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #64748b; margin-bottom: 20px;'>Secure Engineering Portal</p>", unsafe_allow_html=True)
        
        with st.form("login_form", border=True):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            
            st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
            submitted = st.form_submit_button("Log In", use_container_width=True)
            
            if submitted:
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = res.user
                    st.rerun()
                except Exception as e:
                    st.error("Invalid credentials. Please contact administration.")
                    
    st.stop()

if "project_data" not in st.session_state:
    st.session_state.project_data = []
if "custom_mixes" not in st.session_state:
    st.session_state.custom_mixes = []
if "mix_ingredients" not in st.session_state:
    st.session_state.mix_ingredients = []

# Fetch custom mixes from database
def fetch_custom_mixes():
    try:
        response = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user.id).execute()
        st.session_state.custom_mixes = response.data
    except Exception as e:
        st.error(f"Error fetching mixes: {e}")

fetch_custom_mixes()

@st.cache_data
def load_database():
    try:
        db = {
            "concrete": pd.read_csv("https://raw.githubusercontent.com/tanchun/calculator/refs/heads/main/Concrete.csv"),
            "steel": pd.read_csv("https://raw.githubusercontent.com/tanchun/calculator/refs/heads/main/Steel.csv"),
            "timber": pd.read_csv("https://raw.githubusercontent.com/tanchun/calculator/refs/heads/main/Timber.csv"),
            "direct": pd.read_csv("https://raw.githubusercontent.com/tanchun/calculator/refs/heads/main/Direct.csv"),
            "unit_logic": pd.read_csv("https://raw.githubusercontent.com/tanchun/calculator/refs/heads/main/Unit_Logic.csv")
        }
        for key, df in db.items():
            if 'GWP_100' in df.columns:
                df['GWP_100'] = pd.to_numeric(df['GWP_100'], errors='coerce').fillna(0)
            if 'Density_kg_m3' in df.columns:
                df['Density_kg_m3'] = pd.to_numeric(df['Density_kg_m3'], errors='coerce').fillna(0)
        return db
    except Exception as e:
        st.error(f"Error loading master database: {e}")
        return None

db = load_database()
if db is None:
    st.stop()

# Build universal units list
universal_units = ["kg", "tonnes", "m3", "m2", "m", "L", "% by vol.", "% of wt."]

def calculate_concrete_gwp(row):
    return float(row.get('GWP_100', 0))

def calculate_steel_gwp(row):
    return float(row.get('GWP_100', 0))

def calculate_timber_gwp(row):
    return float(row.get('GWP_100', 0))

# Standardize unit conversion
def get_unit_multiplier(unit):
    if unit == 'tonnes':
        return 1000.0
    elif unit in ['% by vol.', '% of wt.']:
        return 0.01
    return 1.0

def main_application():
    st.title("Sustainability Assessment System")
    st.write(f"Logged in as: {st.session_state.user.email}")
    
    if st.button("Log Out"):
        supabase.auth.sign_out()
        st.session_state.user = None
        st.rerun()
        
    st.markdown("---")

    tab_materials, tab_builder, tab_compare, tab_library = st.tabs([
        "Materials & Mixes", "Project Builder", "Compare Mixes", "My Library"
    ])

    with tab_materials:
        st.header("Create Custom Material / Mix")
        
        mix_type = st.radio("What type of item are you creating?", ["Multi-Ingredient Mix (e.g., Concrete, Asphalt)", "Standalone Material (e.g., Steel, Timber, Polymer)"])
        
        mix_name = st.text_input("Material / Mix Name (e.g., Ultra-High Performance Concrete)")
        category = st.selectbox("Assign to Category", ["Concrete", "Steel", "Timber", "Other"])
        
        if mix_type == "Standalone Material (e.g., Steel, Timber, Polymer)":
            st.info("Standalone materials do not require a complex recipe. Please define the standard properties below.")
            mat_density = st.number_input("Density (kg/m³)", min_value=0.0, value=7850.0)
            mat_gwp = st.number_input("Embodied Carbon (kg CO₂e per kg)", min_value=0.0, value=1.5, format="%.3f")
            
            st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
            if st.button("Save Standalone Material"):
                if mix_name:
                    new_mix = {
                        "user_id": st.session_state.user.id,
                        "mix_name": mix_name,
                        "category": category,
                        "ingredients": [{"name": mix_name, "quantity": 1.0, "unit": "kg", "gwp_factor": mat_gwp, "gwp_total": mat_gwp}],
                        "total_mass_kg": mat_density,
                        "total_gwp_100": mat_gwp * mat_density
                    }
                    try:
                        response = supabase.table("user_mixes").insert(new_mix).execute()
                        st.success(f"Successfully saved material: {mix_name}")
                        fetch_custom_mixes()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving material: {e}")
                else:
                    st.warning("Please enter a name for the material.")

        else:
            # Multi-Ingredient Mix Builder
            col1, col2 = st.columns([1, 1])
            with col1:
                st.subheader("Add Standard Material")
                
                sel_cat = st.selectbox("Database Category", ["Concrete", "Steel", "Timber", "Direct"], key="mix_cat")
                
                if sel_cat == "Direct":
                    direct_cats = set(db["direct"]["Category"].dropna().unique()) if not db["direct"].empty and "Category" in db["direct"].columns else set()
                    if direct_cats:
                        sel_subcat = st.selectbox("Direct Impact Category", list(direct_cats))
                        filtered_db = db["direct"][db["direct"]["Category"] == sel_subcat]
                    else:
                        filtered_db = db["direct"]
                else:
                    filtered_db = db[sel_cat.lower()]

                if not filtered_db.empty and 'Item' in filtered_db.columns:
                    sel_item = st.selectbox("Item", filtered_db["Item"].unique(), key="mix_item")
                    item_data = filtered_db[filtered_db["Item"] == sel_item].iloc[0]
                    gwp_factor = float(item_data.get('GWP_100', 0))
                    
                    st.write(f"**GWP100 Factor:** {gwp_factor:.4f} kg CO₂e / unit")
                    
                    unit = st.selectbox("Unit", ["kg", "tonnes", "L", "m3", "% by vol.", "% of wt."], key="mix_unit")
                    qty = st.number_input("Quantity", min_value=0.0, value=1.0, format="%.4f", key="mix_qty")
                    
                    ref_vol = 1.0
                    # Trigger pop-up instantly based on live widget state
                    if unit in ['L', '% by vol.', '% of wt.']:
                        ref_vol = st.number_input("Reference Amount (e.g., Total m³ or Total kg)", min_value=0.1, value=1.0)
                    
                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                    if st.button("Add to Mix"):
                        mult = get_unit_multiplier(unit)
                        actual_qty = qty * mult
                        
                        if unit in ['L', '% by vol.', '% of wt.']:
                             actual_qty = (qty / 100.0) * ref_vol if '%' in unit else qty * ref_vol
                             
                        gwp_total = actual_qty * gwp_factor
                        
                        st.session_state.mix_ingredients.append({
                            "name": sel_item,
                            "quantity": qty,
                            "unit": unit,
                            "actual_kg": actual_qty,
                            "gwp_factor": gwp_factor,
                            "gwp_total": gwp_total
                        })
                        st.rerun()

            with col2:
                st.subheader("Add Ad-Hoc Material")
                ah_name = st.text_input("Custom Material Name")
                ah_qty = st.number_input("Quantity (kg)", min_value=0.0, value=1.0, format="%.4f")
                ah_gwp = st.number_input("GWP100 Factor (kg CO₂e/kg)", min_value=0.0, value=1.0, format="%.4f")
                
                st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                if st.button("Add Ad-Hoc"):
                    if ah_name:
                        st.session_state.mix_ingredients.append({
                            "name": ah_name,
                            "quantity": ah_qty,
                            "unit": "kg",
                            "actual_kg": ah_qty,
                            "gwp_factor": ah_gwp,
                            "gwp_total": ah_qty * ah_gwp
                        })
                        st.rerun()
            
            st.markdown("---")
            st.subheader("Current Recipe")
            if len(st.session_state.mix_ingredients) > 0:
                df_mix = pd.DataFrame(st.session_state.mix_ingredients)
                st.dataframe(df_mix[["name", "quantity", "unit", "gwp_factor", "gwp_total"]], use_container_width=True)
                
                total_mass = df_mix['actual_kg'].sum()
                total_gwp = df_mix['gwp_total'].sum()
                
                st.write(f"**Total Mass (kg):** {total_mass:,.2f}")
                st.write(f"**Total Embodied Carbon (kg CO₂e):** {total_gwp:,.2f}")
                
                st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                if st.button("Save Mix to Library"):
                    if mix_name:
                        new_mix = {
                            "user_id": st.session_state.user.id,
                            "mix_name": mix_name,
                            "category": category,
                            "ingredients": st.session_state.mix_ingredients,
                            "total_mass_kg": float(total_mass),
                            "total_gwp_100": float(total_gwp)
                        }
                        
                        try:
                            # Check if name exists
                            existing = supabase.table("user_mixes").select("id").eq("user_id", st.session_state.user.id).eq("mix_name", mix_name).execute()
                            if existing.data:
                                supabase.table("user_mixes").update(new_mix).eq("mix_name", mix_name).execute()
                                st.success(f"Overwritten existing mix: {mix_name}")
                            else:
                                supabase.table("user_mixes").insert(new_mix).execute()
                                st.success(f"Saved new mix: {mix_name}")
                                
                            st.session_state.mix_ingredients = []
                            fetch_custom_mixes()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Database error: {e}")
                    else:
                        st.warning("Please provide a name before saving.")
                        
                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                if st.button("Clear Recipe"):
                    st.session_state.mix_ingredients = []
                    st.rerun()
            else:
                st.info("No ingredients added yet.")

    with tab_builder:
        st.header("Project Component Builder")
        
        proj_name = st.text_input("Project Name", "New Infrastructure Project")
        
        col_c1, col_c2 = st.columns([1, 1])
        with col_c1:
            comp_name = st.text_input("Component Name (e.g., North Pier, Main Girder)")
            
            # Combine standard and custom mixes for dropdown
            all_options = []
            for k in ["concrete", "steel", "timber"]:
                if db[k] is not None and not db[k].empty:
                    for item in db[k]["Item"].unique():
                        all_options.append(f"Standard {k.capitalize()}: {item}")
            
            if st.session_state.custom_mixes:
                for mx in st.session_state.custom_mixes:
                    all_options.append(f"Custom Mix: {mx['mix_name']}")
                    
            sel_material = st.selectbox("Select Material", all_options)
        
        with col_c2:
            # Determine suggested units
            suggested_units = []
            if db["unit_logic"] is not None and not db["unit_logic"].empty:
                matches = db["unit_logic"][db["unit_logic"]["Component_Name"].str.contains(comp_name, case=False, na=False)]
                if not matches.empty:
                    opts = str(matches.iloc[0]["Unit_Options"]).split(",")
                    suggested_units = [o.strip() for o in opts]
            
            final_units = suggested_units + [u for u in universal_units if u not in suggested_units]
            comp_unit = st.selectbox("Unit of Measurement", final_units, key="proj_unit")
            comp_qty = st.number_input("Component Volume / Quantity", min_value=0.0, value=1.0, format="%.2f")

        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Add Component"):
            if comp_name:
                gwp_factor = 0.0
                mass = 0.0
                
                if sel_material.startswith("Standard"):
                    parts = sel_material.split(":", 1)
                    cat = parts[0].replace("Standard ", "").lower()
                    item_name = parts[1].strip()
                    
                    row = db[cat][db[cat]["Item"] == item_name].iloc[0]
                    gwp_factor = float(row.get('GWP_100', 0))
                    mass = float(row.get('Density_kg_m3', 0))
                else:
                    mx_name = sel_material.replace("Custom Mix: ", "").strip()
                    mx_data = next((m for m in st.session_state.custom_mixes if m['mix_name'] == mx_name), None)
                    if mx_data:
                        gwp_factor = mx_data['total_gwp_100']
                        mass = mx_data['total_mass_kg']

                mult = get_unit_multiplier(comp_unit)
                total_impact = comp_qty * mult * gwp_factor
                
                st.session_state.project_data.append({
                    "component": comp_name,
                    "material": sel_material,
                    "quantity": comp_qty,
                    "unit": comp_unit,
                    "gwp_total": total_impact,
                    "mass_total": comp_qty * mult * mass
                })
                st.rerun()
        
        st.markdown("---")
        st.subheader("Project Inventory")
        if len(st.session_state.project_data) > 0:
            df_proj = pd.DataFrame(st.session_state.project_data)
            st.dataframe(df_proj, use_container_width=True)
            
            grand_total = df_proj['gwp_total'].sum()
            st.write(f"### Grand Total Embodied Carbon: {grand_total:,.2f} kg CO₂e")
            
            st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
            if st.button("Save Project Archive"):
                if proj_name:
                    record = {
                        "user_id": st.session_state.user.id,
                        "project_name": proj_name,
                        "components": st.session_state.project_data,
                        "total_gwp": float(grand_total)
                    }
                    try:
                        existing = supabase.table("saved_projects").select("id").eq("user_id", st.session_state.user.id).eq("project_name", proj_name).execute()
                        if existing.data:
                            supabase.table("saved_projects").update(record).eq("project_name", proj_name).execute()
                            st.success(f"Overwritten project: {proj_name}")
                        else:
                            supabase.table("saved_projects").insert(record).execute()
                            st.success(f"Saved new project: {proj_name}")
                    except Exception as e:
                        st.error(f"Error saving project: {e}")
            
            st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
            if st.button("Clear Project"):
                st.session_state.project_data = []
                st.rerun()
        else:
            st.info("No components added to the project yet.")

    with tab_compare:
        st.header("Comparative Material Analysis")
        
        all_materials = []
        for cat in ["concrete", "steel", "timber"]:
            if db[cat] is not None:
                for item in db[cat]["Item"].unique():
                    all_materials.append(f"Standard {cat.capitalize()}: {item}")
        for mx in st.session_state.custom_mixes:
            all_materials.append(f"Custom: {mx['mix_name']}")
            
        selected_for_comp = st.multiselect("Select Materials/Mixes to Compare", all_materials)
        
        if len(selected_for_comp) > 0:
            comp_data = []
            for sel in selected_for_comp:
                if sel.startswith("Standard"):
                    parts = sel.split(":", 1)
                    c = parts[0].replace("Standard ", "").lower()
                    i_name = parts[1].strip()
                    row = db[c][db[c]["Item"] == i_name].iloc[0]
                    comp_data.append({
                        "Material": sel,
                        "Total Mass (kg)": float(row.get('Density_kg_m3', 0)),
                        "GWP Factor (kg CO₂e)": float(row.get('GWP_100', 0)),
                        "Total GWP (kg CO₂e)": float(row.get('GWP_100', 0) * row.get('Density_kg_m3', 0))
                    })
                else:
                    m_name = sel.replace("Custom: ", "").strip()
                    mx = next((m for m in st.session_state.custom_mixes if m['mix_name'] == m_name), None)
                    if mx:
                        comp_data.append({
                            "Material": sel,
                            "Total Mass (kg)": float(mx['total_mass_kg']),
                            "GWP Factor (kg CO₂e)": float(mx['total_gwp_100'] / mx['total_mass_kg'] if mx['total_mass_kg'] > 0 else 0),
                            "Total GWP (kg CO₂e)": float(mx['total_gwp_100'])
                        })
            
            comp_df = pd.DataFrame(comp_data)
            comp_df = comp_df.sort_values(by="Total GWP (kg CO₂e)")
            
            if len(selected_for_comp) < 2:
                st.info("Please select at least two materials to generate the full comparison report and visualisations.")
                st.dataframe(comp_df, use_container_width=True)
            else:
                best = float(comp_df["Total GWP (kg CO₂e)"].min())
                worst = float(comp_df["Total GWP (kg CO₂e)"].max())
                reduction = ((worst - best) / worst) * 100 if worst > 0 else 0
                
                st.success(f"**Sustainability Insight:** Choosing the optimal material instead of the highest-impact option results in a **{reduction:.1f}% reduction** in embodied carbon per unit volume.")
                
                c1, c2 = st.tabs(["Carbon Leaderboard", "Density vs. Carbon Trade-off"])
                
                with c1:
                    chart = alt.Chart(comp_df).mark_bar().encode(
                        x=alt.X("Total GWP (kg CO₂e):Q", title="Embodied Carbon (kg CO₂e per m³)"),
                        y=alt.Y("Material:N", sort="-x", title=""),
                        color=alt.condition(
                            alt.datum['Total GWP (kg CO₂e)'] == best,
                            alt.value('#10b981'),
                            alt.value('#3b82f6')
                        ),
                        tooltip=["Material", "Total GWP (kg CO₂e)"]
                    ).properties(height=alt.Step(60)).configure_axis(labelFontSize=12, titleFontSize=14)
                    st.altair_chart(chart, use_container_width=True)
                
                with c2:
                    scatter = alt.Chart(comp_df).mark_circle(size=200).encode(
                        x=alt.X("Total Mass (kg):Q", title="Density (kg/m³) - Lower is lighter", scale=alt.Scale(zero=False)),
                        y=alt.Y("Total GWP (kg CO₂e):Q", title="Total Carbon (kg CO₂e) - Lower is better", scale=alt.Scale(zero=False)),
                        color=alt.condition(
                            alt.datum['Total GWP (kg CO₂e)'] == best,
                            alt.value('#10b981'),
                            alt.value('#ef4444')
                        ),
                        tooltip=["Material", "Total Mass (kg)", "Total GWP (kg CO₂e)"]
                    ).interactive()
                    st.altair_chart(scatter, use_container_width=True)
                    st.caption("The bottom-left quadrant represents the ideal engineering zone—materials here are lightweight (reducing structural dead load) while maintaining low embodied carbon.")

                st.subheader("Detailed Metric Breakdown")
                
                def highlight_best(s):
                    is_min = s == s.min()
                    return ['background-color: rgba(16, 185, 129, 0.2); color: #065f46; font-weight: bold' if v else '' for v in is_min]
                
                st.dataframe(
                    comp_df.style.apply(highlight_best, subset=['Total Mass (kg)', 'GWP Factor (kg CO₂e)', 'Total GWP (kg CO₂e)']),
                    use_container_width=True
                )
                
                st.subheader("Side-by-Side Ingredient Matrix")
                matrix_data = []
                for sel in selected_for_comp:
                    if sel.startswith("Custom: "):
                        m_name = sel.replace("Custom: ", "").strip()
                        mx = next((m for m in st.session_state.custom_mixes if m['mix_name'] == m_name), None)
                        if mx and isinstance(mx.get('ingredients'), list):
                            for ing in mx['ingredients']:
                                matrix_data.append({
                                    "Material": sel,
                                    "Ingredient": ing.get('name', 'Unknown'),
                                    "Quantity (kg)": float(ing.get('actual_kg', 0))
                                })
                
                if matrix_data:
                    df_matrix = pd.DataFrame(matrix_data)
                    pivot_matrix = df_matrix.pivot_table(index="Ingredient", columns="Material", values="Quantity (kg)", fill_value=0)
                    st.dataframe(pivot_matrix, use_container_width=True)
                else:
                    st.info("Ingredient matrix requires custom mixes to display side-by-side data.")

                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    csv = comp_df.to_csv(index=False).encode('utf-8')
                    st.download_button("Download CSV Data", csv, "comparison_data.csv", "text/csv")
                
                with col_btn2:
                    if HAS_PDF:
                        if st.button("Generate PDF Report"):
                            pdf = PDFReport()
                            pdf.add_page()
                            pdf.set_font('Arial', 'B', 12)
                            pdf.cell(0, 10, f'Report Generated: {datetime.datetime.now().strftime("%Y-%m-%d")}', 0, 1)
                            pdf.set_font('Arial', '', 10)
                            pdf.multi_cell(0, 10, f"Analysis: Choosing the optimal material over the highest-impact option yields a {reduction:.1f}% reduction in embodied carbon.")
                            
                            pdf.cell(0, 10, '', 0, 1) # Space
                            pdf.set_font('Arial', 'B', 10)
                            # Header
                            pdf.cell(70, 10, 'Material', 1)
                            pdf.cell(40, 10, 'Mass (kg)', 1)
                            pdf.cell(40, 10, 'Total CO2e', 1)
                            pdf.cell(0, 10, '', 0, 1)
                            
                            pdf.set_font('Arial', '', 9)
                            for idx, row in comp_df.iterrows():
                                pdf.cell(70, 10, str(row['Material'])[:35], 1)
                                pdf.cell(40, 10, f"{row['Total Mass (kg)']:.2f}", 1)
                                pdf.cell(40, 10, f"{row['Total GWP (kg CO₂e)']:.2f}", 1)
                                pdf.cell(0, 10, '', 0, 1)
                                
                            pdf_bytes = pdf.output(dest='S').encode('latin-1')
                            st.download_button("Download PDF", data=pdf_bytes, file_name="sustainability_report.pdf", mime="application/pdf")

    with tab_library:
        lib_tab1, lib_tab2 = st.tabs(["Saved Projects", "Saved Custom Mixes"])
        
        with lib_tab1:
            try:
                proj_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user.id).execute()
                projects = proj_res.data
            except:
                projects = []
                
            if projects:
                row_col1, row_col2 = st.columns([1, 2])
                with row_col1:
                    st.subheader("Project List")
                    selected_proj = None
                    for p in projects:
                        if st.button(f"{p['project_name']}", key=f"p_{p['id']}", use_container_width=True):
                            st.session_state.active_proj_id = p['id']
                    
                    active_p_id = st.session_state.get('active_proj_id')
                    if active_p_id:
                        selected_proj = next((p for p in projects if p['id'] == active_p_id), None)
                        
                with row_col2:
                    if selected_proj:
                        st.subheader(selected_proj['project_name'])
                        st.write(f"**Total Carbon:** {selected_proj['total_gwp']:,.2f} kg CO₂e")
                        st.write(f"**Saved on:** {selected_proj['created_at'][:10]}")
                        
                        st.dataframe(pd.DataFrame(selected_proj['components']), use_container_width=True)
                        
                        st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                        if st.button("Clone for Editing", key=f"edit_p_{selected_proj['id']}"):
                            st.session_state.project_data = selected_proj['components']
                            st.success("Project loaded into Project Builder! Navigate to that tab to edit.")
                        
                        st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                        if st.button("Delete Project", key=f"del_p_init_{selected_proj['id']}"):
                            st.session_state.delete_confirm_p = selected_proj['id']
                            
                        # Un-nested delete confirmation
                        if st.session_state.get('delete_confirm_p') == selected_proj['id']:
                            st.error("Are you sure you want to permanently delete this project?")
                            if st.button("Yes, Delete", key=f"del_p_yes_{selected_proj['id']}"):
                                supabase.table("saved_projects").delete().eq("id", selected_proj['id']).execute()
                                st.session_state.active_proj_id = None
                                st.session_state.delete_confirm_p = None
                                st.rerun()
                            if st.button("Cancel", key=f"del_p_no_{selected_proj['id']}"):
                                st.session_state.delete_confirm_p = None
                                st.rerun()
                    else:
                        st.info("Select a project from the left menu to view details.")
            else:
                st.info("No saved projects found.")

        with lib_tab2:
            if st.session_state.custom_mixes:
                col_m1, col_m2 = st.columns([1, 2])
                with col_m1:
                    st.subheader("Custom Mixes")
                    selected_mix = None
                    for m in st.session_state.custom_mixes:
                        if st.button(f"{m['mix_name']}", key=f"m_{m['id']}", use_container_width=True):
                            st.session_state.active_mix_id = m['id']
                    
                    active_m_id = st.session_state.get('active_mix_id')
                    if active_m_id:
                        selected_mix = next((m for m in st.session_state.custom_mixes if m['id'] == active_m_id), None)
                        
                with col_m2:
                    if selected_mix:
                        st.subheader(selected_mix['mix_name'])
                        st.write(f"**Category:** {selected_mix.get('category', 'N/A')}")
                        st.write(f"**Total Mass:** {selected_mix['total_mass_kg']:,.2f} kg")
                        st.write(f"**Total GWP100:** {selected_mix['total_gwp_100']:,.2f} kg CO₂e")
                        
                        ing_df = pd.DataFrame(selected_mix['ingredients'])
                        st.dataframe(ing_df, use_container_width=True)
                        
                        st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                        if st.button("Clone for Editing", key=f"edit_m_{selected_mix['id']}"):
                            st.session_state.mix_ingredients = selected_mix['ingredients']
                            st.success("Mix loaded into Materials & Mixes! Navigate to that tab to edit.")
                            
                        st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                        if st.button("Delete Mix", key=f"del_m_init_{selected_mix['id']}"):
                            st.session_state.delete_confirm_m = selected_mix['id']
                            
                        # Un-nested delete confirmation
                        if st.session_state.get('delete_confirm_m') == selected_mix['id']:
                            st.error("Are you sure you want to permanently delete this mix?")
                            if st.button("Yes, Delete", key=f"del_m_yes_{selected_mix['id']}"):
                                supabase.table("user_mixes").delete().eq("id", selected_mix['id']).execute()
                                st.session_state.active_mix_id = None
                                st.session_state.delete_confirm_m = None
                                fetch_custom_mixes()
                                st.rerun()
                            if st.button("Cancel", key=f"del_m_no_{selected_mix['id']}"):
                                st.session_state.delete_confirm_m = None
                                st.rerun()
                                
                        if 'name' in ing_df.columns and 'actual_kg' in ing_df.columns:
                            st.markdown("---")
                            ch1, ch2 = st.columns(2)
                            with ch1:
                                pie_mass = alt.Chart(ing_df).mark_arc().encode(
                                    theta="actual_kg:Q", color="name:N", tooltip=["name", "actual_kg"]
                                ).properties(title="Mass Breakdown")
                                st.altair_chart(pie_mass, use_container_width=True)
                            with ch2:
                                if 'gwp_total' in ing_df.columns:
                                    pie_gwp = alt.Chart(ing_df).mark_arc().encode(
                                        theta="gwp_total:Q", color="name:N", tooltip=["name", "gwp_total"]
                                    ).properties(title="Carbon Breakdown")
                                    st.altair_chart(pie_gwp, use_container_width=True)
                    else:
                        st.info("Select a mix from the left menu to view details.")
            else:
                st.info("No custom mixes found.")

if __name__ == "__main__":
    main_application()

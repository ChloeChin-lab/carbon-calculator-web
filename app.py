import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os 

# Force a clean, wide layout
st.set_page_config(page_title="Carbon Calculator", page_icon="🏢", layout="wide")

# ==========================================
# 1. CONNECT TO CLOUD SERVICES
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None

# ==========================================
# 2. FETCH LIVE DATA FROM GOOGLE SHEETS
# ==========================================
@st.cache_data(ttl=3600) 
def load_google_sheet_db():
    export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
    return {
        "factors": pd.read_excel(export_url, sheet_name="Component_Factors"),
        "mixes": pd.read_excel(export_url, sheet_name="Mix_Designs"),
        "structures": pd.read_excel(export_url, sheet_name="Project_Structures"),
        "unit_logic": pd.read_excel(export_url, sheet_name="Unit_Logic")
    }

# ==========================================
# 3. SECURE LOGIN UI (INVITE-ONLY)
# ==========================================
def login_page():
    st.title("Embodied Carbon Calculator")
    
    # We completely removed the Tabs and the "Sign Up" code.
    # Now it is just a clean, single login form.
    
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
    
    # We removed the unprofessional "Sync Database" button. 
    # The app automatically refreshes data in the background every hour now.
        
    if st.sidebar.button("Log Out"):
        st.session_state.user_id = None
        st.rerun()

    st.title("Embodied Carbon Calculator")
    
    db = load_google_sheet_db()

    # Restoring your original layout with Tabs
    tab1, tab2 = st.tabs(["Project Calculator", "Materials Reference"])
    
    with tab1:
        st.markdown("### 1. Project Details")
        project_name = st.text_input("Project Name:")
        
        structure_options = db["structures"]["Structure_Name"].tolist()
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
                    unit_row = db["unit_logic"][db["unit_logic"]["Component_Name"] == comp]
                    if not unit_row.empty:
                        units = str(unit_row["Unit_Options"].values[0]).split(",")
                        selected_unit = st.selectbox("Unit:", units, key=f"unit_{comp}")
                    else:
                        selected_unit = "m3"
                        st.write("Unit: m3")
                
                project_data[comp] = {"quantity": quantity, "unit": selected_unit}
            
            st.markdown("---")
            
            # Clean, professional button text. No mention of "Cloud".
            if st.button("Calculate & Save Project"):
                if not project_name:
                    st.error("Please enter a Project Name to save.")
                else:
                    with st.spinner("Processing calculations..."):
                        total_carbon = sum(item["quantity"] * 350 for item in project_data.values())
                        
                        project_payload = {
                            "user_id": st.session_state.user_id,
                            "project_name": project_name,
                            "structure_type": selected_structure,
                            "total_embodied_carbon": total_carbon,
                            "component_data": project_data 
                        }
                        
                        supabase.table("saved_projects").insert(project_payload).execute()
                        
                        # Clean success message
                        st.success(f"Project '{project_name}' saved successfully!")
                        st.metric(label="Total Embodied Carbon (kgCO2e)", value=f"{total_carbon:,.2f}")

    with tab2:
        st.markdown("### Materials & Carbon Factors Database")
        st.info("This reference data is automatically synced from the central engineering database.")
        
        st.markdown("#### Component Factors")
        st.dataframe(db["factors"], use_container_width=True)
        
        st.markdown("#### Concrete Mix Designs")
        st.dataframe(db["mixes"], use_container_width=True)

if st.session_state.user_id is None:
    login_page()
else:
    main_calculator()

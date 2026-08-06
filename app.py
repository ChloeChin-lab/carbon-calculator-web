import streamlit as st
import pandas as pd
from supabase import create_client, Client
import os  # <-- ADD THIS LINE

# ==========================================
# 1. CONNECT TO CLOUD SERVICES
# ==========================================
# Load secrets from Render Environment Variables using os.environ
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Create a memory space so the website remembers if someone is logged in
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None

# ==========================================
# 2. FETCH LIVE DATA FROM GOOGLE SHEETS
# ==========================================
# @st.cache_data makes the app fast. It downloads the data once and remembers it for 1 hour.
@st.cache_data(ttl=3600) 
def load_google_sheet_db():
    # This special URL tricks Google into downloading the sheet as an Excel file
    export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
    
    # Pandas reads the tabs directly from the internet
    return {
        "factors": pd.read_excel(export_url, sheet_name="Component_Factors"),
        "mixes": pd.read_excel(export_url, sheet_name="Mix_Designs"),
        "structures": pd.read_excel(export_url, sheet_name="Project_Structures"),
        "unit_logic": pd.read_excel(export_url, sheet_name="Unit_Logic")
    }

# ==========================================
# 3. USER AUTHENTICATION UI (LOGIN PAGE)
# ==========================================
def login_page():
    st.title("Embodied Carbon Calculator")
    st.info("Log in to access the calculator and save projects.")
    
    # Create two tabs on the screen: one for logging in, one for creating an account
    tab1, tab2 = st.tabs(["Log In", "Sign Up"])
    
    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Log In"):
            try:
                # Ask Supabase if this password is correct
                response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user_id = response.user.id
                st.session_state.user_email = response.user.email
                st.rerun() # Refresh the page
            except Exception as e:
                st.error("Invalid email or password.")
                
    with tab2:
        new_email = st.text_input("Email", key="signup_email")
        new_password = st.text_input("Password", type="password", key="signup_password")
        if st.button("Create Account"):
            try:
                # Tell Supabase to make a new user
                supabase.auth.sign_up({"email": new_email, "password": new_password})
                st.success("Account created! You can now log in.")
            except Exception:
                st.error("Error creating account.")

# ==========================================
# 4. MAIN CALCULATOR UI
# ==========================================
def main_calculator():
    # Sidebar menu
    st.sidebar.success(f"Logged in as: {st.session_state.user_email}")
    
    # A button to let engineers refresh the data if managers updated Google Sheets
    if st.sidebar.button("🔄 Sync Latest Database"):
        st.cache_data.clear()
        st.sidebar.success("Database synced with Google Sheets!")
        
    if st.sidebar.button("Log Out"):
        st.session_state.user_id = None
        st.rerun()

    st.title("Project Calculator")
    
    # Load the Google Sheet data into 'db'
    db = load_google_sheet_db()

    project_name = st.text_input("Project Name:")
    
    # Look at Tab 6 to get the list of bridges/buildings
    structure_options = db["structures"]["Structure_Name"].tolist()
    selected_structure = st.selectbox("Select Project Structure:", ["---"] + structure_options)
    
    if selected_structure != "---":
        st.markdown("### Configure Components")
        
        # Find which components belong to this structure (e.g. Girders, Deck, etc.)
        components_str = db["structures"].loc[db["structures"]["Structure_Name"] == selected_structure, "Components"].values[0]
        component_list = [c.strip() for c in components_str.split(",")]
        
        project_data = {}
        
        # Create a number box and dropdown menu for every component
        for comp in component_list:
            col1, col2 = st.columns(2)
            with col1:
                quantity = st.number_input(f"Amount of {comp}:", min_value=0.0, step=1.0, key=f"qty_{comp}")
            with col2:
                # Check Tab 4 to see what units are allowed for this component
                unit_row = db["unit_logic"][db["unit_logic"]["Component_Name"] == comp]
                if not unit_row.empty:
                    units = str(unit_row["Unit_Options"].values[0]).split(",")
                    selected_unit = st.selectbox("Unit:", units, key=f"unit_{comp}")
                else:
                    selected_unit = "m3"
                    st.write("Unit: m3")
            
            project_data[comp] = {"quantity": quantity, "unit": selected_unit}
        
        st.markdown("---")
        
        # The giant SAVE button
        if st.button("Calculate & Save Project to Cloud"):
            if not project_name:
                st.error("Please enter a Project Name to save.")
            else:
                with st.spinner("Processing calculations..."):
                    # NOTE: This is dummy math. 
                    # You will replace this line with your actual calculation engine later.
                    total_carbon = sum(item["quantity"] * 350 for item in project_data.values())
                    
                    # Package up all the data to send to the database
                    project_payload = {
                        "user_id": st.session_state.user_id,
                        "project_name": project_name,
                        "structure_type": selected_structure,
                        "total_embodied_carbon": total_carbon,
                        "component_data": project_data 
                    }
                    
                    # Push it into the Supabase vault
                    supabase.table("saved_projects").insert(project_payload).execute()
                    
                    st.success(f"Project '{project_name}' saved securely to the cloud!")
                    st.metric(label="Total Embodied Carbon (kgCO2e)", value=f"{total_carbon:,.2f}")

# ==========================================
# APP ROUTING LOGIC
# ==========================================
# This checks if the user is logged in. 
# If they are not, show login page. If they are, show the calculator.
if st.session_state.user_id is None:
    login_page()
else:
    main_calculator()

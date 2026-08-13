import streamlit as st # The main library used to build the web app interface
import pandas as pd # Used to handle data tables and Excel files easily
from supabase import create_client, Client # Used to connect to your Supabase cloud database
import os # Used to securely fetch hidden passwords/keys from the server environment
import requests # Used to download the Excel database from Google Sheets via the internet
from io import BytesIO # Used to hold the downloaded Excel file in the computer's memory
import altair as alt # Used to draw the beautiful interactive charts (pie charts, scatter plots)
import uuid # Used to generate unique random ID codes for new components or materials
import time # Used to create short pauses (like waiting 1 second after saving before refreshing)

# We try to load the PDF library. If the server doesn't have it installed, we just turn off PDF features without crashing.
try:
    from fpdf import FPDF # Imports the PDF generator
    HAS_FPDF = True # Flag to tell the app that PDF generation is allowed
except ImportError:
    HAS_FPDF = False # Flag to tell the app to hide PDF buttons safely

# Sets up the basic page layout to use the full width of the screen and gives the browser tab a title
st.set_page_config(page_title="Sustainability Assessment System", layout="wide")

# This block of HTML/CSS code changes the colours of our buttons so they look professional (Blue, Green, Red, Grey)
st.markdown("""
<style>
/* Primary Button Default (Blue) */
div[data-testid="stButton"] > button[kind="primary"] {
    background-color: #3b82f6;
    color: white;
    padding: 10px 20px;
    font-size: 16px;
    font-weight: bold;
    border-radius: 6px;
    border: none;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background-color: #2563eb; /* Darker blue when hovering */
}

/* Green Save Buttons */
div.element-container:has(span.btn-green) + div.element-container button {
    background-color: #10b981 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
div.element-container:has(span.btn-green) + div.element-container button:hover {
    background-color: #059669 !important; /* Darker green when hovering */
}

/* Red Delete/Remove Buttons */
div.element-container:has(span.btn-red) + div.element-container button {
    background-color: #ef4444 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
div.element-container:has(span.btn-red) + div.element-container button:hover {
    background-color: #dc2626 !important; /* Darker red when hovering */
}

/* Blue Action/Calculate Buttons */
div.element-container:has(span.btn-blue) + div.element-container button {
    background-color: #3b82f6 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
div.element-container:has(span.btn-blue) + div.element-container button:hover {
    background-color: #2563eb !important; /* Darker blue when hovering */
}

/* Grey Clone/Duplicate Buttons */
div.element-container:has(span.btn-grey) + div.element-container button {
    background-color: #64748b !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
div.element-container:has(span.btn-grey) + div.element-container button:hover {
    background-color: #475569 !important; /* Darker grey when hovering */
}

/* Style static tables to look clean like an engineering report */
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

# Fetch the secret connection keys from the server's environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

# Create a cached connection to Supabase so it doesn't reconnect on every single click
@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY) # Logs into the database

supabase = init_supabase() # Stores the database connection in a variable

# Streamlit forgets everything when a button is clicked. "session_state" forces it to remember things.
if "user_id" not in st.session_state:
    st.session_state.user_id = None # Remembers if a user is logged in
if "user_email" not in st.session_state:
    st.session_state.user_email = None # Remembers the user's email
if "current_page" not in st.session_state:
    st.session_state.current_page = "Home" # Remembers which tab we are currently looking at
if "mix_mode_radio" not in st.session_state:
    st.session_state.mix_mode_radio = "View Standard Materials" # Remembers the sub-tab in Materials & Mixes

# Background Draft Memory for Project Assessment (Remembers what the user is currently typing)
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

def generate_pdf_report(df, best, worst, savings):
    """Creates a downloadable PDF report comparing materials."""
    if not HAS_FPDF: # If the PDF library is missing, stop here
        return None
    try:
        pdf = FPDF() # Create a blank PDF document
        pdf.add_page() # Add a white page
        pdf.set_font("Arial", 'B', 16) # Set font to bold, size 16
        pdf.cell(0, 10, "Sustainability Comparison Report", ln=True, align='C') # Add the main title
        pdf.set_font("Arial", '', 12) # Reset font to normal, size 12
        pdf.ln(10) # Add empty space
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, "Executive Summary", ln=True) # Add Summary title
        pdf.set_font("Arial", '', 11)
        # Create a text paragraph summarising the carbon savings
        summary = (f"This comparative analysis evaluates the Embodied Carbon Intensity (ECI) across selected materials. "
                   f"Choosing the optimal material ({best['Material']}) instead of the highest-impact option ({worst['Material']}) "
                   f"results in a {savings:.1f}% reduction in environmental impact per cubic metre. "
                   f"For large-scale infrastructure applications, this material substitution represents a highly effective decarbonisation strategy.")
        pdf.multi_cell(0, 6, summary) # Print the paragraph to the PDF
        pdf.ln(10) # Add empty space
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, "Data Summary", ln=True) # Add Data title
        pdf.set_font("Arial", '', 10)
        # Loop through the data table and print each material's stats line by line
        for _, row in df.iterrows():
            pdf.cell(0, 6, f"- {row['Material']}: Mass: {row['Total Mass (kg/m³)']:.2f} kg/m³ | GWP100: {row['Total GWP100 (kgCO2e/m³)']:.2f} kgCO2e/m³", ln=True)
            
        return pdf.output(dest='S').encode('latin-1') # Package the PDF into a downloadable file format
    except Exception:
        return None # If anything crashes, fail silently

def clean_df(df):
    """Safely removes invisible spaces from Excel headers and text cells so the app doesn't crash."""
    if isinstance(df, pd.DataFrame) and not df.empty: # Check if it's actually a valid data table
        df.columns = df.columns.str.strip() # Remove spaces from column names
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x) # Remove spaces from text inside cells
    return df

def safe_float(val, default=0.0):
    """Safely handles text, N/A, dashes, or blanks in Excel cells by turning them into 0.0 instead of crashing."""
    if pd.isna(val): # If cell is literally empty
        return default
    try:
        return float(val) # Try to turn it into a decimal number
    except (ValueError, TypeError):
        return default # If it's a word like "N/A", just return 0.0

@st.cache_data(ttl=600) # Caches the Excel data for 10 minutes so it doesn't re-download constantly
def load_database():
    """Downloads the Google Sheet or reads a local Excel file containing master properties."""
    required_sheets = ["Component_Factors", "Mix_Designs", "Project_Structures", "Unit_Logic", "Direct_Results"]
    
    if SHEET_ID and len(SHEET_ID) > 20: # If we have a Google Sheet ID configured
        export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
        try:
            response = requests.get(export_url, timeout=10) # Download the file from the internet
            response.raise_for_status() # Check for download errors
            excel_data = BytesIO(response.content) # Load it into memory
            xls = pd.read_excel(excel_data, sheet_name=required_sheets) # Read the specific tabs we need
            return {
                "factors": clean_df(xls.get("Component_Factors", pd.DataFrame())), # Clean and save each tab
                "mixes": clean_df(xls.get("Mix_Designs", pd.DataFrame())),
                "structures": clean_df(xls.get("Project_Structures", pd.DataFrame())),
                "unit_logic": clean_df(xls.get("Unit_Logic", pd.DataFrame())),
                "direct": clean_df(xls.get("Direct_Results", pd.DataFrame()))
            }
        except Exception as e:
            print(f"Warning: Cloud Database failed to load. Reason: {e}")
            pass 
            
    # Fallback: Try reading from a local file on the computer if the cloud download failed
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
            
    return None # Return nothing if both cloud and local methods fail

def login_page():
    """Displays a clean, centered login portal."""
    st.markdown("<br><br><br>", unsafe_allow_html=True) # Push down from the top of the screen
    col1, col2, col3 = st.columns([1, 1.2, 1]) # Create 3 columns, putting the login box in the middle column
    
    with col2:
        st.markdown("""
        <div style="text-align: center; padding-bottom: 20px;">
            <h1 style="font-size: 36px; margin-bottom: 5px;">Sustainability Assessment System</h1>
            <p style="font-size: 16px;">Please log in to access.</p>
        </div>
        """, unsafe_allow_html=True)
        
        email = st.text_input("Email", key="login_email") # Ask for email
        password = st.text_input("Password", type="password", key="login_password") # Ask for password (hidden as stars)
        
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True) # Make button blue
        if st.button("Log In", use_container_width=True):
            try:
                # Try to log into Supabase securely
                response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.user_id = response.user.id # Remember their ID
                st.session_state.user_email = response.user.email # Remember their Email
                st.session_state.current_page = "Home" # Send them to the Home page
                st.rerun() # Refresh the screen
            except Exception:
                st.error("Invalid email or password. Please contact your administrator for access.")

def load_project_to_session(p_data, db):
    """Loads a previously saved project from the library back into the Project Builder tab so it can be edited."""
    st.session_state.current_page = "Project Assessment" # Switch to the builder tab
    st.session_state.draft_proj_name = f"{p_data['project_name']} (Copy)" # Add (Copy) to prevent accidental overwrites
    st.session_state.draft_structure = p_data['structure_type'] # Load the structural template
    st.session_state.project_results_df = None # Clear old math results
    
    known_components = []
    if db is not None and not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
        known_components = db["unit_logic"]["Component_Name"].dropna().astype(str).str.strip().tolist()
        
    new_draft = []
    raw_comp_data = p_data.get("component_data", []) # Get the saved materials
    
    # Check if data is stored in the old dictionary format and convert it safely
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
        
    # Rebuild the exact component structure for the user interface
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
                "id": str(uuid.uuid4()), # Create a new unique ID for the button logic
                "label": m_data.get("label", ""),
                "qty": m_data.get("quantity", 0.0),
                "unit": m_data.get("unit", "m3"),
                "ref_value": m_data.get("ref_value", 0.0),
                "ref_per_unit": m_data.get("ref_per_unit", False),
                "mix": m_data.get("assigned_mix", "--- Select ---")
            })
            
        new_draft.append({
            "id": str(uuid.uuid4()), # Create a new unique ID for the component block
            "base_name": b_name if "Extra" not in b_name else "Extra",
            "custom_name": c_name,
            "count": c_data.get("multiplier_count", 1),
            "materials": mats
        })
        
    st.session_state.draft_components = new_draft # Inject all this rebuilt data into memory

def load_mix_to_session(m_data):
    """Loads a previously saved mix from the library back into the Material Builder tab so it can be edited."""
    st.session_state.current_page = "Materials & Mixes" # Switch to the material tab
    st.session_state.mix_mode_radio = "Create Custom Material / Mix" # Switch to the creation sub-tab
    
    st.session_state.draft_mix_name = f"{m_data['mix_name']} (Copy)" # Add (Copy) to the name
    st.session_state.draft_mix_cat = m_data['category'] # Load its category
    st.session_state.draft_mix_comps = m_data.get("components", {}) # Load its standard ingredients
    
    adhoc_list = m_data.get("adhoc_materials", []) # Load its custom ingredients
    if adhoc_list:
        st.session_state.adhoc_mats = pd.DataFrame(adhoc_list) # Put custom ingredients into a table
    else:
        st.session_state.adhoc_mats = pd.DataFrame(columns=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"])

def get_unit_logic_type(unit_string):
    """Looks at the word a user chose (e.g., 'kg', '% by volume') and decides what math rules to apply."""
    s = str(unit_string).lower()
    if "%" in s:
        if "wt" in s or "weight" in s: return "PERCENT_WEIGHT"
        return "PERCENT_VOL"
    if "/ unit" in s: return "PER_UNIT"
    if "l/m3" in s: return "LITER_PER_M3" 
    if s.strip() == "l" or s.strip() == "liters": return "BASIC_LITER"
    return "BASIC" # Default standard math

def calculate_mix_carbon(mix_name, db, user_mixes, factors_df):
    """Calculates the total mass and carbon emissions for exactly 1 cubic metre of a specific mix."""
    m_mass, m_gwp = 0.0, 0.0
    
    if mix_name.startswith("Custom: "): # If it's a mix created by the user
        mix_n = mix_name.replace("Custom: ", "") # Remove the "Custom: " tag to find the real name
        match_mix = next((m for m in user_mixes if m["mix_name"] == mix_n), None) # Find it in their saved mixes
        if match_mix:
            if match_mix.get("components"):
                for c_name, c_val in match_mix["components"].items(): # Loop through standard ingredients
                    c_val = safe_float(c_val)
                    if c_name in factors_df.index:
                        factor_row = factors_df.loc[c_name]
                        m_gwp += c_val * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0)) # Add to total carbon
                    m_mass += c_val # Add to total mass
                    
            if match_mix.get("adhoc_materials"):
                for adhoc in match_mix["adhoc_materials"]: # Loop through custom ingredients
                    q = safe_float(adhoc.get("Quantity", 0))
                    m_mass += q
                    m_gwp += q * safe_float(adhoc.get("GWP100 (kgCO2e/kg)", 0))
    else:
        # If it's a standard mix from the master Excel sheet
        match_df = db["mixes"][db["mixes"]["Mix_Key"] == mix_name] if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else pd.DataFrame()
        if not match_df.empty:
            mix_row = match_df.iloc[0]
            for comp_factor in factors_df.index: # Look for every known ingredient in this row
                if comp_factor in mix_row and pd.notna(mix_row[comp_factor]):
                    val = safe_float(mix_row[comp_factor])
                    factor_row = factors_df.loc[comp_factor]
                    m_mass += val
                    m_gwp += val * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
        else:
            # If it's a standalone structural material (like Steel) from the Direct Results sheet
            match_direct = db["direct"][db["direct"]["Material_Key"] == mix_name] if not db["direct"].empty and "Material_Key" in db["direct"].columns else pd.DataFrame()
            if not match_direct.empty:
                direct_row = match_direct.iloc[0]
                m_mass = safe_float(direct_row.get("Total_Mass_kg_m3", 1.0)) 
                if m_mass == 0: m_mass = 1.0 # Prevent dividing by zero crashes
                
                m_gwp = safe_float(direct_row.get("GWP100_kgCO2e_m3", 0.0))
                if m_gwp == 0.0: m_gwp = safe_float(direct_row.get("ECFGWP100_kgCO2e_kg", 0.0)) * m_mass
                    
    return {
        "Mass (kg/m3)": m_mass,
        "Factor_GWP (kgCO2e/kg)": (m_gwp / m_mass) if m_mass > 0 else 0
    }

def calculate_project_data(draft_components, db, user_mixes, factors_df):
    """The master math engine. It looks at the whole project, reads all volumes/units, and calculates the final grand totals."""
    results_list = []
    grand_totals = {"mass": 0.0, "gwp": 0.0}
    clean_project_data = []

    for comp_idx, comp in enumerate(draft_components): # Loop through every component (e.g., Girders, Deck)
        c_name = comp.get("custom_name", comp.get("base_name", "Unknown"))
        c_multiplier = int(comp.get("count", 1)) # Get how many of these exist
        c_materials = []

        for mat in comp.get("materials", []): # Loop through every material assigned to this component
            qty = safe_float(mat.get("qty", 0.0))
            unit_str = mat.get("unit", "")
            mix = mat.get("mix", "--- Select ---")
            
            ref_val = safe_float(mat.get("ref_value", 0.0))
            ref_per_unit = mat.get("ref_per_unit", False)
            
            logic_type = get_unit_logic_type(unit_str) # Ask our helper function what math rule to use
            
            if mix != "--- Select ---" and qty > 0:
                props = calculate_mix_carbon(mix, db, user_mixes, factors_df) # Ask the other helper function for this material's properties
                mass_per_m3 = props["Mass (kg/m3)"]
                
                total_mass_kg = 0.0
                
                # Complex math for percentages based on a Reference Volume (e.g., "Steel is 2% of the Concrete's volume")
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
                    
                # Standard math for simple units (e.g., "I have 5 tonnes of steel")
                elif logic_type in ["PER_UNIT", "BASIC", "BASIC_LITER"]:
                    base_vol = qty * c_multiplier if logic_type == "PER_UNIT" else qty
                    if "tonne" in unit_str.lower():
                        total_mass_kg = base_vol * 1000.0 # Convert tonnes to kg
                    elif "kg" in unit_str.lower():
                        total_mass_kg = base_vol # Already in kg
                    elif logic_type == "BASIC_LITER":
                        total_mass_kg = (base_vol / 1000.0) * mass_per_m3 # Convert Liters to kg based on density
                    else:
                        total_mass_kg = base_vol * mass_per_m3 # Standard volume * density

                item_gwp = total_mass_kg * props["Factor_GWP (kgCO2e/kg)"] # Final carbon footprint for this specific item
                
                grand_totals["mass"] += total_mass_kg # Add to project grand total
                grand_totals["gwp"] += item_gwp # Add to project grand total
                
                item_label = f"{comp_idx + 1}. {c_name} {mat.get('label', '')}".strip()
                
                if logic_type in ["PERCENT_VOL", "PERCENT_WEIGHT", "LITER_PER_M3"]:
                    mult_tag = " × Qty" if ref_per_unit else ""
                    display_qty = f"{qty} (Ref: {ref_val}{mult_tag})"
                else:
                    display_qty = f"{qty}"
                
                # Add this calculated row to our final display table
                results_list.append({
                    "Item": item_label,
                    "Material": mix,
                    "Volume/Amount": display_qty, 
                    "Unit": unit_str,
                    "Total Mass (kg)": total_mass_kg,
                    "Total GWP100 (kgCO2e)": item_gwp
                })
                
            # Keep a clean record of what the user inputted so we can save it to the database
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
    """Draws a clean, styled table on the screen and prints the grand totals below it."""
    display_df = df.copy()
    display_df.index = display_df.index + 1 # Make the row numbers start at 1 instead of 0
    
    # Format the large numbers with commas and 2 decimal places (e.g., 1,234.56)
    display_df["Total Mass (kg)"] = display_df["Total Mass (kg)"].apply(lambda x: f"{float(x):,.2f}")
    display_df["Total GWP100 (kgCO2e)"] = display_df["Total GWP100 (kgCO2e)"].apply(lambda x: f"{float(x):,.2f}")
    
    st.table(display_df) # Draw the table
    
    # Draw a styled box below the table highlighting the grand totals
    totals_html = f"""
    <div style="border: 1px solid #d3d3d3; border-radius: 5px; padding: 20px; background-color: #f9f9f9; margin-bottom: 20px;">
        <h4 style="margin-top: 0; color: #000; font-family: sans-serif;">Project Grand Totals</h4>
        <table style="width: 100%; border-collapse: collapse; font-size: 16px; color: #000; font-family: sans-serif;">
            <tr><td style="font-weight: bold; width: 250px; padding: 8px 0;">Total Mass:</td><td>{totals['mass']:,.2f} kg</td></tr>
            <tr><td style="font-weight: bold; padding: 8px 0; background-color: #f0f0f0;">Total GWP100:</td><td style="background-color: #f0f0f0;">{totals['gwp']:,.2f} kgCO2e</td></tr>
        </table>
    </div>
    """
    st.markdown(totals_html, unsafe_allow_html=True)

def welcome_dashboard():
    """Draws the main landing page with the 3 large navigation buttons."""
    username = st.session_state.user_email.split('@')[0].capitalize() # Extract their name from their email address
    st.markdown(f"""
    <div style="padding: 40px; background: linear-gradient(135deg, #1e293b, #0f172a); border-radius: 12px; margin-bottom: 30px; color: white; border: 1px solid #334155;">
        <h1 style="margin-top: 0; color: white;">Welcome back, {username}!</h1>
        <p style="font-size: 18px; color: #cbd5e1; max-width: 800px;">
            Manage your structural material libraries, assess project embodied carbon, and optimise engineering designs for maximum sustainability.
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div style="background-color: #F0F4F8; padding: 20px; border-radius: 8px; border-top: 4px solid #3498DB; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Materials & Mixes</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The master library. Configure ingredients, build custom mixes, and compare properties.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_mats", use_container_width=True):
            st.session_state.current_page = "Materials & Mixes"
            st.rerun() # Refresh page to go to new tab
        
    with col2:
        st.markdown("""
        <div style="background-color: #E8F8F5; padding: 20px; border-radius: 8px; border-top: 4px solid #1ABC9C; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Project Assessment</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The structural assembly. Configure components, assign materials, and generate assessments.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_proj", use_container_width=True):
            st.session_state.current_page = "Project Assessment"
            st.rerun() # Refresh page to go to new tab
        
    with col3:
        st.markdown("""
        <div style="background-color: #F8F9F9; padding: 20px; border-radius: 8px; border-top: 4px solid #95A5A6; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">My Library</h3>
            <p style="color: #5D6D7E; font-size: 14px;">Your historical database. Review, analyse, and manage your saved projects and custom mixes.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("View Records", key="btn_nav_saved", use_container_width=True):
            st.session_state.current_page = "My Library"
            st.rerun() # Refresh page to go to new tab

def main_application():
    """This function controls the entire application once a user has logged in."""
    db = load_database() # Load the Excel data
    
    if db is None:
        st.error("Cannot start the application. Please check the database connection.")
        st.stop() # Freeze the app if database is missing

    # --- Sidebar Navigation Menu ---
    if st.session_state.current_page == "Home":
        st.sidebar.caption(f"User: {st.session_state.user_email}")
        if st.sidebar.button("Log Out"):
            st.session_state.user_id = None
            st.session_state.current_page = "Home"
            st.rerun()
        welcome_dashboard()
        return # Stop running code here so we only show the dashboard

    if st.sidebar.button("Return to Home"):
        st.session_state.current_page = "Home"
        st.rerun()

    st.sidebar.markdown("---")
    
    # Create the radio buttons on the left menu so the user can switch tabs
    st.sidebar.radio("Navigation", ["Materials & Mixes", "Project Assessment", "My Library"], 
                     key="nav_radio", 
                     index=["Materials & Mixes", "Project Assessment", "My Library"].index(st.session_state.current_page),
                     on_change=lambda: st.session_state.update(current_page=st.session_state.nav_radio),
                     label_visibility="collapsed")
    
    st.sidebar.markdown("---")
    st.sidebar.caption(f"User: {st.session_state.user_email}")
        
    if st.sidebar.button("Log Out"):
        st.session_state.user_id = None
        st.session_state.current_page = "Home"
        st.rerun()

    st.title(st.session_state.current_page) # Print the current tab title at the top of the page
        
    # --- Fetching Custom Data from Supabase ---
    # We download the user's custom mixes so we can append them to the standard dropdowns
    user_mixes_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user_id).execute()
    user_mixes = user_mixes_res.data if user_mixes_res.data else []
    custom_mix_names = [m["mix_name"] for m in user_mixes]
    
    # Create master lists of all available materials (Excel + User Custom)
    mix_mats = db["mixes"]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
    direct_mats = db["direct"]["Material_Key"].dropna().tolist() if not db["direct"].empty and "Material_Key" in db["direct"].columns else []
    standard_mixes = sorted(list(set(mix_mats + direct_mats)))
    all_available_mixes = standard_mixes + [f"Custom: {name}" for name in custom_mix_names]
    
    # Get the environmental factors table ready
    factors_df = db["factors"].drop_duplicates(subset=["Component"]).set_index("Component") if not db["factors"].empty and "Component" in db["factors"].columns else pd.DataFrame()

    if st.session_state.current_page == "Materials & Mixes":
        
        # Decide which sub-tab we should be looking at
        default_mode_idx = 0
        if st.session_state.get("mix_mode_radio") == "Create Custom Material / Mix":
            default_mode_idx = 1
        elif st.session_state.get("mix_mode_radio") == "Compare Mixes":
            default_mode_idx = 2
            
        mode = st.radio("Choose an action:", ["View Standard Materials", "Create Custom Material / Mix", "Compare Mixes"], horizontal=True, index=default_mode_idx, key="mix_mode_radio_ui")
        
        if st.session_state.mix_mode_radio != mode:
            st.session_state.mix_mode_radio = mode
        
        # Build a master list of all Categories so we can populate the dropdowns
        mix_cats = set(db["mixes"]["Category"].dropna().unique()) if not db["mixes"].empty and "Category" in db["mixes"].columns else set()
        direct_cats = set(db["direct"]["Category"].dropna().unique()) if not db["direct"].empty and "Category" in db["direct"].columns else set()
        user_cats = set([m['category'] for m in user_mixes if 'category' in m])
        all_categories = sorted(list(mix_cats.union(direct_cats).union(user_cats)))
        
        # Sub-tab: View existing materials
        if mode == "View Standard Materials":
            st.markdown("#### View Standard Material Properties")
            
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                selected_cat = st.selectbox("Material Category:", ["--- Select Category ---"] + all_categories, key="view_cat")
            
            # If a category is picked, show the materials inside that category
            if selected_cat != "--- Select Category ---":
                cat_mix_mats = db["mixes"][db["mixes"]["Category"] == selected_cat]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
                cat_direct_mats = db["direct"][db["direct"]["Category"] == selected_cat]["Material_Key"].dropna().tolist() if not db["direct"].empty and "Material_Key" in db["direct"].columns else []
                cat_user_mats = [f"Custom: {m['mix_name']}" for m in user_mixes if m.get('category') == selected_cat]
                cat_all_mats = sorted(list(set(cat_mix_mats + cat_direct_mats + cat_user_mats)))
                
                with col_sel2:
                    selected_mat = st.selectbox("Material Type/Grade:", ["--- Select Material ---"] + cat_all_mats, key="view_mat")
                
                # If a material is picked, show its properties
                if selected_mat != "--- Select Material ---":
                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                    if st.button("View Material Properties", type="primary"):
                        try:
                            # Ask the math engine for the numbers
                            props = calculate_mix_carbon(selected_mat, db, user_mixes, factors_df)
                            
                            st.markdown("---")
                            st.markdown(f"**Properties for {selected_mat}**")
                            
                            # Print the numbers in 3 clean columns
                            m_col1, m_col2, m_col3 = st.columns(3)
                            m_col1.metric("Total Mass", f"{props['Mass (kg/m3)']:,.2f} kg/m³")
                            m_col2.metric("GWP100 Factor", f"{props['Factor_GWP (kgCO2e/kg)']:,.3f} kgCO2e/kg")
                            m_col3.metric("GWP100 Total", f"{props['Factor_GWP (kgCO2e/kg)'] * props['Mass (kg/m3)']:,.2f} kgCO2e/m³")
                            
                        except Exception as e:
                            st.error(f"Error parsing data. Details: {e}")

        # Sub-tab: Create a new material
        elif mode == "Create Custom Material / Mix":
            st.markdown("#### Design a Custom Material or Mix")
            
            # Retrieve drafted names from memory (if we clicked "Clone for Editing" earlier)
            d_name = st.session_state.get("draft_mix_name", "")
            d_cat = st.session_state.get("draft_mix_cat", "--- Select Category ---")
            
            c_col1, c_col2 = st.columns(2)
            with c_col1:
                # Add an option to type in a brand new category
                cat_options = ["--- Select Category ---"] + all_categories + ["➕ Create New Category..."]
                cat_index = cat_options.index(d_cat) if d_cat in cat_options else 0
                custom_cat_sel = st.selectbox("Assign to Category:", cat_options, index=cat_index, key="cust_cat_sel")
                
                if custom_cat_sel == "➕ Create New Category...":
                    custom_cat = st.text_input("Enter New Category Name:", key="cust_cat_new_input") # Let user type
                else:
                    custom_cat = custom_cat_sel
                    
            with c_col2:
                custom_mix_name = st.text_input("Name your Custom Item:", value=d_name, placeholder="e.g., C40/50 or Recycled Steel", key="mix_name_input")
            
            st.markdown("---")
            # Ask the user if they are building a complex concrete mix or a simple block of steel
            creation_type = st.radio("What type of item are you creating?", 
                                     ["Multi-Ingredient Mix (e.g., Concrete, Asphalt)", "Standalone Material (e.g., Steel, Timber)"],
                                     horizontal=True, key="creation_type_radio")
            
            custom_mix_data = {}
            valid_adhoc = []
            
            # --- Pathway 1: Simple Standalone Material ---
            if creation_type == "Standalone Material (e.g., Steel, Timber)":
                st.markdown("##### Define Material Properties")
                
                s_col1, s_col2 = st.columns(2)
                with s_col1:
                    standalone_density = st.number_input("Density / Unit Weight (kg/m³)", min_value=0.1, value=7850.0, step=10.0, key="std_density")
                with s_col2:
                    standalone_gwp = st.number_input("GWP100 (kgCO2e/kg)", min_value=0.0, value=1.50, step=0.01, format="%.3f", key="std_gwp")
                
                # Package this single item up as a "custom ingredient" so the engine understands it
                if standalone_density > 0:
                    valid_adhoc = [{"Material Name": custom_mix_name if custom_mix_name else "New Material", "Quantity": standalone_density, "GWP100 (kgCO2e/kg)": standalone_gwp}]
                
                st.markdown("---")
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                    preview_mix = st.button("Preview Properties")
                with btn_col2:
                    st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                    save_mix = st.button("Save Custom Material")
                    
            # --- Pathway 2: Complex Mix Builder ---
            else:
                st.markdown("##### 1. Choose Input Units")
                unit_mode = st.radio("How are you inputting your mix ingredients?", 
                                     ["Standard (kg/m³)", "Total Batch Weight (kg)", "US Imperial (lb/yd³)"], 
                                     horizontal=True, key="unit_mode_radio")
                
                batch_vol = 1.0
                if unit_mode == "Total Batch Weight (kg)":
                    batch_vol = st.number_input("What is the total batch volume? (m³):", min_value=0.1, value=1.0, step=0.1, key="batch_vol_input")
                    st.info(f"Your inputs will be automatically divided by {batch_vol} to standardise them to kg/m³.")
                elif unit_mode == "US Imperial (lb/yd³)":
                    st.info("Your inputs will be automatically converted to kg/m³ (1 lb/yd³ ≈ 0.5933 kg/m³).")
                    
                st.markdown("##### 2. Standard Ingredients")
                
                # Get the list of master ingredients from the Excel sheet
                if not factors_df.empty:
                    all_comps = factors_df.index.tolist()
                else:
                    all_comps = []
                
                raw_input_data = {}
                d_comps = st.session_state.get("draft_mix_comps", {}) # Retrieve drafted ingredients (if cloning)
                
                # Draw the number boxes in 4 neat columns
                input_cols = st.columns(4)
                for i, comp in enumerate(all_comps):
                    default_val = float(d_comps.get(comp, 0.0))
                    val = input_cols[i % 4].number_input(comp, min_value=0.0, step=10.0, value=default_val, key=f"cust_comp_{comp}")
                    if val > 0:
                        raw_input_data[comp] = val # Save the user's input
                        
                st.markdown("##### 3. Add Custom Ingredients")
                st.caption("To delete a row, highlight it and press Delete on your keyboard.")
                
                # Create a mini-spreadsheet so the user can type in unlisted ingredients
                if "adhoc_mats" not in st.session_state:
                    st.session_state.adhoc_mats = pd.DataFrame(columns=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"])
                    
                edited_adhoc_df = st.data_editor(
                    st.session_state.adhoc_mats, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    key="adhoc_editor",
                    column_order=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"]
                )
                
                # Convert the standard ingredient math based on the unit mode they selected
                for comp, val in raw_input_data.items():
                    if unit_mode == "US Imperial (lb/yd³)":
                        custom_mix_data[comp] = val * 0.593276
                    elif unit_mode == "Total Batch Weight (kg)":
                        custom_mix_data[comp] = val / batch_vol
                    else:
                        custom_mix_data[comp] = val
                        
                # Convert the custom ingredient math based on the unit mode they selected
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
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                    preview_mix = st.button("Preview Mix Properties")
                with btn_col2:
                    st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                    save_mix = st.button("Save Custom Mix")
                
            # --- Live Preview Engine for Custom Materials ---
            if preview_mix and (len(custom_mix_data) > 0 or len(valid_adhoc) > 0):
                total_mass = 0
                total_gwp = 0
                
                custom_mix_carbon = {}
                c_data_mass_list = []
                
                # Calculate carbon for standard ingredients
                for comp, mass in custom_mix_data.items():
                    if comp in factors_df.index:
                        factor_row = factors_df.loc[comp]
                        comp_gwp = mass * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                        custom_mix_carbon[comp] = comp_gwp
                        
                        total_gwp += comp_gwp
                        total_mass += mass
                        c_data_mass_list.append({"Component": comp, "Mass": mass})
                
                # Calculate carbon for custom ingredients
                for adhoc in valid_adhoc:
                    comp = adhoc["Material Name"]
                    mass = adhoc["Quantity"]
                    comp_gwp = mass * adhoc["GWP100 (kgCO2e/kg)"]
                    custom_mix_carbon[comp] = comp_gwp
                    total_gwp += comp_gwp
                    total_mass += mass
                    c_data_mass_list.append({"Component": comp, "Mass": mass})
                
                # Print the final calculated numbers
                st.markdown("##### Live Properties (Standardised to 1 m³ volume)")
                r_col1, r_col2, r_col3 = st.columns(3)
                r_col1.metric("Total Mass (Density)", f"{total_mass:,.2f} kg/m³")
                r_col2.metric("GWP100 Factor", f"{(total_gwp / total_mass):,.3f} kgCO2e/kg" if total_mass > 0 else "0")
                r_col3.metric("GWP100 Total", f"{total_gwp:,.2f} kgCO2e/m³")
                
                # If it's a mix, draw the pie charts so the engineer can see what is causing the carbon footprint
                if creation_type == "Multi-Ingredient Mix (e.g., Concrete, Asphalt)":
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
                        st.markdown("**2. By GWP100 Impact**")
                        c_data_carbon = pd.DataFrame({"Component": list(custom_mix_carbon.keys()), "Carbon": list(custom_mix_carbon.values())})
                        c_pie_carbon = alt.Chart(c_data_carbon).mark_arc(innerRadius=40).encode(
                            theta=alt.Theta(field="Carbon", type="quantitative"),
                            color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                            tooltip=["Component", "Carbon"]
                        ).properties(height=280)
                        st.altair_chart(c_pie_carbon, use_container_width=True)
            
            # --- Database Saving Logic for Custom Materials ---
            if save_mix:
                if not custom_cat or custom_cat == "--- Select Category ---" or custom_cat.strip() == "":
                    st.error("Please assign or enter a valid category before saving.")
                elif not custom_mix_name:
                    st.error("Please provide a name for your item.")
                elif len(custom_mix_data) == 0 and len(valid_adhoc) == 0:
                    st.error("Please add at least one ingredient or property.")
                else:
                    # Package the data to be sent to Supabase
                    mix_payload = {
                        "user_id": st.session_state.user_id,
                        "mix_name": custom_mix_name,
                        "category": custom_cat.strip(),
                        "components": custom_mix_data,
                        "adhoc_materials": valid_adhoc
                    }
                    
                    # Check if a mix with this exact name already exists in the database
                    existing_mix = next((m for m in user_mixes if m['mix_name'] == custom_mix_name and m['category'] == custom_cat.strip()), None)
                    
                    if existing_mix:
                        # If it exists, pause the save and ask the user if they want to overwrite it
                        st.session_state.confirm_overwrite_mix_name = custom_mix_name
                        st.session_state.existing_mix_id = existing_mix['id']
                        st.session_state.mix_payload_draft = mix_payload
                        st.rerun()
                    else:
                        # If it doesn't exist, proceed to save it
                        st.session_state.execute_mix_save = True
                        st.session_state.mix_payload_draft = mix_payload
                        st.rerun()
                        
            # Ask the user for confirmation to overwrite
            if st.session_state.get("confirm_overwrite_mix_name"):
                st.warning(f"A mix named '{st.session_state.confirm_overwrite_mix_name}' already exists in this category. Do you want to overwrite it?")
                col_y, col_n = st.columns(2)
                with col_y:
                    st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                    if st.button("Yes, Overwrite"):
                        st.session_state.execute_mix_save = True # Give permission to save
                        st.session_state.confirm_overwrite_mix_name = None # Hide the warning
                        st.rerun()
                with col_n:
                    if st.button("No, Change Name"):
                        st.session_state.confirm_overwrite_mix_name = None # Hide the warning
                        st.session_state.mix_payload_draft = None # Delete the draft
                        st.rerun()
                        
            # Actually talk to Supabase and perform the save/update
            if st.session_state.get("execute_mix_save"):
                payload = st.session_state.mix_payload_draft
                try:
                    if st.session_state.get("existing_mix_id"):
                        supabase.table("user_mixes").update(payload).eq("id", st.session_state.existing_mix_id).execute()
                        st.success(f"Mix '{payload['mix_name']}' successfully overwritten! Clearing form...")
                    else:
                        supabase.table("user_mixes").insert(payload).execute()
                        st.success(f"'{payload['mix_name']}' saved successfully. Clearing form...")
                    
                    # WIPE THE FORM CLEAN SO IT'S READY FOR THE NEXT MIX
                    if "draft_mix_name" in st.session_state: del st.session_state.draft_mix_name
                    if "draft_mix_cat" in st.session_state: del st.session_state.draft_mix_cat
                    if "draft_mix_comps" in st.session_state: del st.session_state.draft_mix_comps
                    
                    # Erase every single number input box from the session memory
                    keys_to_clear = ["mix_name_input", "cust_cat_sel", "cust_cat_new_input", "adhoc_mats", "adhoc_editor", "creation_type_radio", "std_density", "std_gwp", "unit_mode_radio", "batch_vol_input"]
                    for key in list(st.session_state.keys()):
                        if key.startswith("cust_comp_") or key in keys_to_clear:
                            del st.session_state[key]
                            
                    st.session_state.execute_mix_save = False # Turn off the save engine
                    st.session_state.existing_mix_id = None
                    time.sleep(1.5) # Wait a moment so the user can read the success message
                    st.rerun() # Refresh the page to show the clean form
                except Exception as e:
                    st.error(f"Database Save Error: Details: {e}")
                    st.session_state.execute_mix_save = False

        # Sub-tab: Compare multiple materials
        elif mode == "Compare Mixes":
            st.markdown("#### Compare Materials & Mixes")
            st.info("Select multiple materials or custom mixes below to analyse their sustainability metrics side-by-side.")
            
            # The big dropdown where you can pick as many materials as you want
            selected_for_comp = st.multiselect("Select Mixes to Compare:", all_available_mixes, key="compare_multiselect")
            
            if selected_for_comp:
                comp_data = []
                # Loop through every material they picked and run the math engine on it
                for mix_name in selected_for_comp:
                    props = calculate_mix_carbon(mix_name, db, user_mixes, factors_df)
                    mass = props["Mass (kg/m3)"]
                    gwp = props["Factor_GWP (kgCO2e/kg)"] * mass
                    comp_data.append({
                        "Material": mix_name,
                        "Total Mass (kg/m³)": mass,
                        "GWP100 Factor (kgCO2e/kg)": props["Factor_GWP (kgCO2e/kg)"],
                        "Total GWP100 (kgCO2e/m³)": gwp
                    })
                    
                comp_df = pd.DataFrame(comp_data) # Turn the results into a table
                
                # If they picked at least two things, we can actually compare them!
                if len(comp_data) > 1:
                    st.markdown("---")
                    
                    # Sort the table to find the winner and loser
                    sorted_df = comp_df.sort_values("Total GWP100 (kgCO2e/m³)")
                    best = sorted_df.iloc[0]
                    worst = sorted_df.iloc[-1]
                    
                    # Calculate the percentage difference
                    if worst["Total GWP100 (kgCO2e/m³)"] > 0:
                        savings_pct = ((worst["Total GWP100 (kgCO2e/m³)"] - best["Total GWP100 (kgCO2e/m³)"]) / worst["Total GWP100 (kgCO2e/m³)"]) * 100
                    else:
                        savings_pct = 0
                        
                    # Print the written Executive Summary paragraph
                    st.markdown(f"""
                    <div style="background-color: #E8F8F5; padding: 20px; border-radius: 8px; border-left: 6px solid #1ABC9C; margin-bottom: 20px;">
                        <h4 style="margin-top: 0; color: #2C3E50;">Executive Summary & Technical Insight</h4>
                        <p style="font-size: 16px; color: #34495E; line-height: 1.6;">
                        This comparative analysis evaluates the <strong>Embodied Carbon Intensity (ECI)</strong> across your selected structural materials. 
                        Based on the dataset, <strong>{best['Material']}</strong> demonstrates optimal environmental performance, 
                        yielding a Global Warming Potential (GWP100) of <strong>{best['Total GWP100 (kgCO2e/m³)']:,.2f} kgCO2e/m³</strong> at a density of <strong>{best['Total Mass (kg/m³)']:,.2f} kg/m³</strong>.
                        <br><br>
                        Choosing the optimal material (<strong>{best['Material']}</strong>) instead of the highest-impact option (<strong>{worst['Material']}</strong>) results in a 
                        <strong>{savings_pct:.1f}% reduction</strong> in environmental impact per cubic metre. For large-scale infrastructure applications, this material substitution represents a highly effective decarbonisation strategy.
                    </p>
                </div>
                """, unsafe_allow_html=True)
            
                    # Draw the comparison charts
                    st.markdown("##### Visual Analytics")
                    tab_bar, tab_scatter = st.tabs(["GWP100 Leaderboard", "Density vs. Carbon Trade-off"])
                    
                    # Draw the Bar Chart
                    with tab_bar:
                        best_val = float(best['Total GWP100 (kgCO2e/m³)']) # Identify the lowest carbon number
                        
                        # Set up the basic bar chart axes
                        base_chart = alt.Chart(comp_df).encode(
                            x=alt.X("Total GWP100 (kgCO2e/m³):Q", title="Global Warming Potential (kgCO2e/m³)", scale=alt.Scale(domain=[0, comp_df["Total GWP100 (kgCO2e/m³)"].max() * 1.15])),
                            y=alt.Y("Material:N", sort="-x", title="")
                        )
                        
                        # Draw the bars, colouring the winning bar green
                        bars = base_chart.mark_bar(cornerRadiusEnd=4, height=40).encode(
                            color=alt.condition(
                                alt.datum['Total GWP100 (kgCO2e/m³)'] == best_val,
                                alt.value('#27ae60'),  # Green for the winner
                                alt.value('#95a5a6')   # Grey for the rest
                            ),
                            tooltip=["Material", "Total Mass (kg/m³)", "Total GWP100 (kgCO2e/m³)"]
                        )
                        
                        # Print the actual number next to the bar
                        text = base_chart.mark_text(
                            align='left', baseline='middle', dx=5, fontWeight='bold'
                        ).encode(
                            text=alt.Text('Total GWP100 (kgCO2e/m³):Q', format=',.2f')
                        )
                        
                        final_bar_chart = (bars + text).properties(height=alt.Step(60)) 
                        st.altair_chart(final_bar_chart, use_container_width=True)
                        
                    # Draw the Scatter Plot
                    with tab_scatter:
                        scatter = alt.Chart(comp_df).mark_circle(size=200).encode(
                            x=alt.X("Total Mass (kg/m³):Q", title="Density (kg/m³)", scale=alt.Scale(zero=False, padding=20)),
                            y=alt.Y("Total GWP100 (kgCO2e/m³):Q", title="Total GWP100 (kgCO2e/m³)", scale=alt.Scale(zero=False, padding=20)),
                            color=alt.Color("Material:N", legend=alt.Legend(title="Material")),
                            tooltip=["Material", "Total Mass (kg/m³)", "Total GWP100 (kgCO2e/m³)"]
                        ).properties(height=350)
                        st.altair_chart(scatter, use_container_width=True)
                        st.caption("*The bottom-left quadrant represents the ideal engineering zone—materials here are lightweight (reducing structural dead load) while maintaining low embodied carbon.*")
                
                    st.markdown("##### Detailed Metric Breakdown & Data Export")
                    
                    # Highlight the winning numbers in green on the data table
                    def highlight_best(s):
                        is_min = s == s.min()
                        return ['background-color: #d4edda; color: #155724; font-weight: bold' if v else '' for v in is_min]
                        
                    display_df = comp_df.set_index("Material")
                    styled_df = display_df.style.apply(highlight_best).format({
                        "Total Mass (kg/m³)": "{:,.2f}",
                        "GWP100 Factor (kgCO2e/kg)": "{:,.3f}",
                        "Total GWP100 (kgCO2e/m³)": "{:,.2f}"
                    })
                    st.table(styled_df)
                    
                    # --- Engine to extract ingredients for the Side-by-Side Matrix ---
                    matrix_data = []
                    for mix_name in selected_for_comp:
                        # If it's a custom mix, crack it open and read the recipe dictionary
                        if mix_name.startswith("Custom: "):
                            m_name = mix_name.replace("Custom: ", "")
                            mx = next((m for m in user_mixes if m['mix_name'] == m_name), None)
                            if mx:
                                if mx.get("components"):
                                    for c, v in mx["components"].items():
                                        if v > 0: matrix_data.append({"Material": mix_name, "Ingredient": c, "Quantity (kg)": v})
                                if mx.get("adhoc_materials"):
                                    for adhoc in mx["adhoc_materials"]:
                                        matrix_data.append({"Material": mix_name, "Ingredient": adhoc["Material Name"], "Quantity (kg)": adhoc["Quantity"]})
                        else:
                            # If it's a standard mix, read the Excel row to find its recipe
                            match_df = db["mixes"][db["mixes"]["Mix_Key"] == mix_name] if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else pd.DataFrame()
                            if not match_df.empty:
                                mix_row = match_df.iloc[0]
                                for comp_factor in factors_df.index:
                                    if comp_factor in mix_row and pd.notna(mix_row[comp_factor]):
                                        mass = safe_float(mix_row[comp_factor])
                                        if mass > 0:
                                            matrix_data.append({"Material": mix_name, "Ingredient": comp_factor, "Quantity (kg)": mass})

                    # If we found any ingredients, draw the matrix
                    if matrix_data:
                        st.markdown("##### Side-by-Side Ingredient Matrix")
                        df_matrix = pd.DataFrame(matrix_data)
                        # Pivot the table so Materials are columns and Ingredients are rows
                        pivot_matrix = df_matrix.pivot_table(index="Ingredient", columns="Material", values="Quantity (kg)", fill_value=0)
                        st.dataframe(pivot_matrix, use_container_width=True)
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    col_csv, col_pdf, _ = st.columns([1, 1, 1.5])
                    
                    # Create the CSV download button
                    csv_data = comp_df.to_csv(index=False).encode('utf-8')
                    col_csv.download_button(
                        label="📄 Download Data (CSV)",
                        data=csv_data,
                        file_name="material_comparison.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
                    # Create the PDF download button (only if the server has FPDF installed)
                    if HAS_FPDF:
                        pdf_bytes = generate_pdf_report(comp_df, best, worst, savings_pct)
                        if pdf_bytes:
                            col_pdf.download_button(
                                label="📊 Download PDF Report",
                                data=pdf_bytes,
                                file_name="sustainability_report.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                else:
                    # If they only picked one material, politely ask them to pick another
                    st.info("Please select at least one more material from the dropdown above to generate the side-by-side comparison report and visual charts.")
                    st.dataframe(comp_df.set_index("Material").style.format({
                        "Total Mass (kg/m³)": "{:,.2f}",
                        "GWP100 Factor (kgCO2e/kg)": "{:,.3f}",
                        "Total GWP100 (kgCO2e/m³)": "{:,.2f}"
                    }), use_container_width=True)

    elif st.session_state.current_page == "Project Assessment":

        col_proj_details, col_clear = st.columns([3, 1])
        
        with col_proj_details:
            st.markdown("### 1. Project Details & Structure")
            st.session_state.draft_proj_name = st.text_input("Project Name:", value=st.session_state.draft_proj_name, placeholder="Enter project name...")
            
        with col_clear:
            st.markdown("<br>", unsafe_allow_html=True)
            # Create the 2-step Clear All button logic
            if not st.session_state.get("confirm_clear_all", False):
                if st.button("Clear All & Start Over"):
                    st.session_state.confirm_clear_all = True # Trigger the warning
                    st.rerun()
            else:
                st.warning("Are you sure? All progress will be lost.")
                col_y, col_n = st.columns(2)
                with col_y:
                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                    if st.button("Yes, Clear"):
                        st.session_state.draft_proj_name = ""
                        st.session_state.draft_structure = "---"
                        st.session_state.draft_components = []
                        st.session_state.project_results_df = None
                        st.session_state.confirm_clear_all = False
                        st.rerun() # Refresh to show clean page
                with col_n:
                    if st.button("Cancel"):
                        st.session_state.confirm_clear_all = False # Hide warning
                        st.rerun()
        
        # Load structural templates from the Excel sheet
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
            st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
            if st.button("Generate Components", use_container_width=True):
                # When they click Generate, read the Excel sheet to find out what parts make up this structure
                if selected_structure != "---":
                    st.session_state.draft_structure = selected_structure
                    st.session_state.draft_components = []
                    st.session_state.project_results_df = None

                    components_str = db["structures"].loc[db["structures"]["Structure_Name"] == selected_structure, "Components"].values[0]
                    component_list = [c.strip() for c in components_str.split(",") if "Extra" not in c.strip()]
                    
                    # For every part (like a Girder), figure out its default measurement unit (like m3)
                    for comp in component_list:
                        default_unit = "m3"
                        if not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
                            match_mask = db["unit_logic"]["Component_Name"].astype(str).str.strip().str.lower() == str(comp).strip().lower()
                            unit_row = db["unit_logic"][match_mask]
                            if not unit_row.empty and "Default_Unit" in unit_row.columns:
                                val = str(unit_row["Default_Unit"].values[0]).strip()
                                if val and val.lower() != "nan":
                                    default_unit = val

                        # Add the part to the project's memory
                        st.session_state.draft_components.append({
                            "id": str(uuid.uuid4()), # Give it a unique digital ID
                            "base_name": comp,
                            "custom_name": comp, 
                            "count": 1,
                            "materials": [{
                                "id": str(uuid.uuid4()), # Give its material row a unique ID
                                "label": "",
                                "qty": 0.0,
                                "unit": default_unit,
                                "ref_value": 0.0,
                                "ref_per_unit": False,
                                "mix": "--- Select ---"
                            }]
                        })
                    st.rerun() # Refresh to draw all the newly generated components

        if st.session_state.draft_structure != "---":
            st.markdown("### 2. Configure Components & Assign Mixes")
            
            comps_to_remove = []

            # Draw the UI for every single component block
            for comp in st.session_state.draft_components:
                st.markdown("---")
                
                col_count, col_title, col_del_comp = st.columns([1.5, 3, 1])
                is_extra = "Extra" in comp["base_name"] # Check if this is a custom-added part

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
                            comps_to_remove.append(comp) # Tag it to be deleted

                # Build the master list of measurement units
                units = ["m3", "m3 / unit", "tonnes", "tonnes / unit", "kg", "L", "L/m3", "% by volume", "% by weight", "m", "m2", "units"]
                
                # Check Excel to see if this specific part has a priority unit (like tonnes for Rebar)
                if not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
                    match_mask = db["unit_logic"]["Component_Name"].astype(str).str.strip().str.lower() == str(comp["base_name"]).strip().lower()
                    unit_row = db["unit_logic"][match_mask]
                    if not unit_row.empty and "Unit_Options" in unit_row.columns:
                        sheet_units = [u.strip() for u in str(unit_row["Unit_Options"].values[0]).split(",")]
                        for su in sheet_units:
                            if su not in units:
                                units.append(su) # Ensure all possible units are available

                mats_to_remove = []
                
                # Draw the material assignment rows inside this component block
                for mat in comp["materials"]:
                    
                    unit_key = f"unit_{mat['id']}"
                    if unit_key in st.session_state:
                        mat["unit"] = st.session_state[unit_key] # Update the unit if the user changed it
                        
                    logic_type = get_unit_logic_type(mat["unit"])
                    needs_ref = logic_type in ["PERCENT_VOL", "PERCENT_WEIGHT", "LITER_PER_M3"] # Check if we need to draw extra input boxes for percentages
                    
                    # Squeeze the layout if we need more boxes
                    if needs_ref:
                        col_label, col_mix, col_qty, col_unit, col_ref, col_mult, col_del = st.columns([1.8, 2.2, 1.0, 1.2, 1.2, 0.8, 0.8])
                    else:
                        col_label, col_mix, col_qty, col_unit, col_del = st.columns([2.5, 3, 1.5, 1.5, 1])
                    
                    # Draw the actual input boxes
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
                            mat["ref_per_unit"] = st.checkbox("× Qty", value=bool(mat.get("ref_per_unit", False)), key=f"mult_{mat['id']}", help="Check if this reference is for ONE unit (will multiply by the Component Quantity).")
                    else:
                        mat["ref_value"] = 0.0 
                        mat["ref_per_unit"] = False
                        
                    with col_del:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if len(comp["materials"]) > 1: # Only allow deleting if it's not the last remaining material
                            st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                            if st.button("Delete", key=f"del_mat_{mat['id']}"):
                                mats_to_remove.append(mat) # Tag it to be deleted

                # Delete the tagged materials
                for mat in mats_to_remove:
                    comp["materials"].remove(mat)
                    st.rerun()

                # Add Material button and Jump to Mixes button
                col_add_mat, col_nav_mix, col_empty = st.columns([1.5, 1.5, 3])
                with col_add_mat:
                    if st.button(f"+ Add Material", key=f"add_mat_btn_{comp['id']}"):
                        comp["materials"].append({
                            "id": str(uuid.uuid4()), # Give the new blank row a unique ID
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
                        st.session_state.current_page = "Materials & Mixes" # Teleport user to Tab 1
                        st.rerun()

            # Delete the tagged components
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
            
            # --- Project Calculation Button ---
            st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
            if st.button("Calculate Project Totals", use_container_width=True):
                with st.spinner("Processing calculations..."): # Show a loading spinner
                    df, totals, clean_data = calculate_project_data(st.session_state.draft_components, db, user_mixes, factors_df)
                    
                    if df is not None:
                        st.session_state.project_results_df = df # Save math to memory
                        st.session_state.project_totals = totals
                        st.session_state.project_clean_data = clean_data
                    else:
                        st.error("Please assign at least one material with an amount > 0.")
                    st.rerun()

            # --- Results and Database Saving ---
            if st.session_state.project_results_df is not None:
                st.markdown("---")
                
                render_results_table_and_totals(st.session_state.project_results_df, st.session_state.project_totals)
                
                st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                if st.button("Save Project"):
                    if not st.session_state.draft_proj_name:
                        st.error("Please enter a Project Name at the top of the page to save.")
                    else:
                        # Fetch user's saved projects to see if they are accidentally overwriting an old one
                        projects_res = supabase.table("saved_projects").select("id, project_name").eq("user_id", st.session_state.user_id).execute()
                        local_user_projects = projects_res.data if projects_res.data else []
                        existing_project = next((p for p in local_user_projects if p['project_name'] == st.session_state.draft_proj_name), None)
                        
                        if existing_project:
                            st.session_state.confirm_overwrite_name = st.session_state.draft_proj_name # Trigger overwrite warning
                            st.session_state.existing_proj_id = existing_project['id']
                            st.rerun()
                        else:
                            st.session_state.execute_save = True # Give permission to save
                            st.rerun()
                
                # The 2-step Overwrite warning logic
                if st.session_state.get("confirm_overwrite_name"):
                    st.warning(f"A project named '{st.session_state.confirm_overwrite_name}' already exists. Do you want to overwrite it?")
                    col_y, col_n = st.columns(2)
                    with col_y:
                        st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                        if st.button("Yes, Overwrite"):
                            st.session_state.execute_save = True
                            st.session_state.confirm_overwrite_name = None
                            st.rerun()
                    with col_n:
                        if st.button("No, Change Name"):
                            st.session_state.confirm_overwrite_name = None
                            st.rerun()
                
                # Execute the save to Supabase
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
                            st.success(f"Project '{st.session_state.draft_proj_name}' successfully overwritten and updated. Clearing board...")
                        else:
                            supabase.table("saved_projects").insert(project_payload).execute()
                            st.success(f"Project '{st.session_state.draft_proj_name}' saved successfully to your account. Clearing board...")
                            
                        st.session_state.execute_save = False
                        st.session_state.existing_proj_id = None
                        
                        # Wipe the builder tab clean now that it is saved
                        time.sleep(1.5)
                        st.session_state.draft_proj_name = ""
                        st.session_state.draft_structure = "---"
                        st.session_state.draft_components = []
                        st.session_state.project_results_df = None
                        st.session_state.project_totals = None
                        st.session_state.project_clean_data = []
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Failed to save project. Error: {e}")
                        st.session_state.execute_save = False

    elif st.session_state.current_page == "My Library":
        
        tab_proj, tab_mix = st.tabs(["Saved Projects", "Saved Custom Mixes"])
        
        # --- Library Tab: Saved Projects ---
        with tab_proj:
            projects_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user_id).execute()
            user_projects = projects_res.data if projects_res.data else []
            
            if user_projects:
                proj_names = [p['project_name'] for p in user_projects]
                
                # Default to looking at the very first project in their list
                if "lib_selected_proj" not in st.session_state or st.session_state.lib_selected_proj not in proj_names:
                    st.session_state.lib_selected_proj = proj_names[0]
                    
                # Master-Detail Layout Setup (Left Column = List, Right Column = Details)
                col_list, col_details = st.columns([1, 2.5])
                
                with col_list:
                    st.markdown("#### Project List")
                    selected_proj = st.radio("Select Project", proj_names, label_visibility="collapsed", key="lib_proj_radio")
                    if selected_proj != st.session_state.lib_selected_proj:
                        st.session_state.lib_selected_proj = selected_proj
                        st.rerun() # Refresh the page to show the new project's details
                        
                with col_details:
                    # Find the specific project the user clicked on
                    p = next((proj for proj in user_projects if proj['project_name'] == st.session_state.lib_selected_proj), None)
                    if p:
                        st.markdown(f"### {p['project_name']}")
                        st.caption(f"Structure Template: {p['structure_type']} | Baseline GWP100: {p['total_embodied_carbon']:,.2f} kgCO2e")
                        
                        # Rebuild the components from the database so the math engine can read them
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

                        # Recalculate and draw the table
                        df, totals, _ = calculate_project_data(draft_comps, db, user_mixes, factors_df)
                        if df is not None:
                            render_results_table_and_totals(df, totals)
                        else:
                            st.info("No calculable materials found in this project.")
                        
                        st.markdown("---")
                        
                        proj_id = p.get('id', str(p.get('project_name')))
                        del_key = f"del_proj_confirm_{proj_id}"
                        
                        # --- The Library Buttons Engine (Rename, Clone, Delete) ---
                        if not st.session_state.get(del_key, False):
                            btn_col_rn, btn_col_a, btn_col_b = st.columns([2, 1.5, 1.5])
                            
                            with btn_col_rn:
                                new_p_name = st.text_input("Rename Project:", value=p['project_name'], key=f"rn_p_{proj_id}")
                                st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                                if st.button("Update Name", key=f"btn_rn_{proj_id}"):
                                    try:
                                        supabase.table("saved_projects").update({"project_name": new_p_name}).eq("id", proj_id).execute()
                                        st.success("Project renamed!")
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error("Failed to rename. Ensure you have the Supabase UPDATE policy enabled.")
                            
                            with btn_col_a:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                                # Calling 'load_project_to_session' function instantly teleports them to Tab 2
                                st.button("Clone for Editing", key=f"load_proj_{proj_id}", on_click=load_project_to_session, args=(p, db))
                                    
                            with btn_col_b:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                if st.button("Delete Project", key=f"btn_del_init_proj_{proj_id}"):
                                    st.session_state[del_key] = True # Activate the warning sequence
                                    st.rerun() # Refresh to hide these buttons and show the warning
                                    
                        # --- Un-nested 2-Step Delete Warning ---
                        else:
                            st.warning("Are you sure? This cannot be undone.")
                            y_col, n_col = st.columns(2)
                            with y_col:
                                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                if st.button("Yes, Delete", key=f"btn_del_yes_proj_{proj_id}"):
                                    if 'id' in p:
                                        supabase.table("saved_projects").delete().eq("id", p["id"]).execute()
                                        st.session_state[del_key] = False
                                        st.success("Project deleted.")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.error("Missing 'id' column.")
                            with n_col:
                                if st.button("Cancel", key=f"btn_del_no_proj_{proj_id}"):
                                    st.session_state[del_key] = False # Hide the warning
                                    st.rerun() # Refresh to bring the normal buttons back
            else:
                st.info("No projects saved under your account yet.")

        # --- Library Tab: Saved Custom Mixes ---
        with tab_mix:
            if not user_mixes:
                st.info("No custom materials found on your account. Create one in 'Materials & Mixes'!")
            else:
                mix_names = [m['mix_name'] for m in user_mixes]
                
                # Default to looking at the very first mix in their list
                if "lib_selected_mix" not in st.session_state or st.session_state.lib_selected_mix not in mix_names:
                    st.session_state.lib_selected_mix = mix_names[0]
                    
                # Master-Detail Layout Setup (Left Column = List, Right Column = Details)
                col_m_list, col_m_details = st.columns([1, 2.5])
                
                with col_m_list:
                    st.markdown("#### Material List")
                    selected_mix = st.radio("Select Mix", mix_names, label_visibility="collapsed", key="lib_mix_radio")
                    if selected_mix != st.session_state.lib_selected_mix:
                        st.session_state.lib_selected_mix = selected_mix
                        st.rerun() # Refresh the page to show the new mix's details
                        
                with col_m_details:
                    # Find the specific mix the user clicked on
                    m = next((mix for mix in user_mixes if mix['mix_name'] == st.session_state.lib_selected_mix), None)
                    if m:
                        st.markdown(f"### {m['mix_name']}")
                        st.caption(f"Assigned Category: {m['category']}")
                        
                        # Recalculate its properties
                        c_mix_name = f"Custom: {m['mix_name']}"
                        props = calculate_mix_carbon(c_mix_name, db, user_mixes, factors_df)
                        
                        st.markdown("##### Performance Metrics")
                        m_col1, m_col2, m_col3 = st.columns(3)
                        m_col1.metric("Total Mass", f"{props['Mass (kg/m3)']:,.2f} kg/m³")
                        m_col2.metric("GWP100 Factor", f"{props['Factor_GWP (kgCO2e/kg)']:,.3f} kgCO2e/kg")
                        m_col3.metric("GWP100 Total", f"{props['Factor_GWP (kgCO2e/kg)'] * props['Mass (kg/m3)']:,.2f} kgCO2e/m³")
                        
                        # Extract the ingredients so we can draw the pie charts again
                        chart_components_mass = {}
                        chart_components_carbon = {}
                        recipe_data = []
                        
                        if m.get("components"):
                            for c, val in m["components"].items():
                                if val > 0: 
                                    recipe_data.append({"Material": c, "Quantity": val, "Type": "Standard"})
                                    if c in factors_df.index:
                                        factor_row = factors_df.loc[c]
                                        c_gwp = val * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                                        chart_components_mass[c] = val
                                        chart_components_carbon[c] = c_gwp
                        if m.get("adhoc_materials"):
                            for adhoc in m["adhoc_materials"]:
                                recipe_data.append({"Material": adhoc["Material Name"], "Quantity": adhoc["Quantity"], "Type": "Custom"})
                                c = adhoc["Material Name"]
                                val = adhoc["Quantity"]
                                c_gwp = val * adhoc["GWP100 (kgCO2e/kg)"]
                                chart_components_mass[c] = val
                                chart_components_carbon[c] = c_gwp
                        
                        # Draw the breakdown charts
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
                        
                        # Draw the raw ingredient table
                        st.markdown("##### Ingredient Recipe")
                        if recipe_data:
                            st.dataframe(pd.DataFrame(recipe_data), use_container_width=True, hide_index=True)
                        
                        st.markdown("---")
                        del_m_key = f"del_mix_confirm_{m['id']}"
                        
                        # --- The Library Buttons Engine (Rename, Clone, Delete) ---
                        if not st.session_state.get(del_m_key, False):
                            col_rn, col_dup, col_del = st.columns([1.5, 1, 1])
                            with col_rn:
                                new_m_name = st.text_input("Rename Material:", value=m['mix_name'], key=f"rn_in_{m['id']}")
                                st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                                if st.button("Update Name", key=f"rn_btn_{m['id']}"):
                                    try:
                                        supabase.table("user_mixes").update({"mix_name": new_m_name}).eq("id", m['id']).execute()
                                        st.success("Material renamed successfully!")
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error("Failed to rename. Ensure you have the Supabase UPDATE policy enabled.")
                            
                            with col_dup:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                                # Calling 'load_mix_to_session' function instantly teleports them to Tab 1
                                st.button("Clone for Editing", key=f"dup_m_{m['id']}", on_click=load_mix_to_session, args=(m,))
    
                            with col_del:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                if st.button("Delete Material", key=f"btn_del_init_mix_{m['id']}"):
                                    st.session_state[del_m_key] = True # Activate the warning sequence
                                    st.rerun() # Refresh to hide these buttons and show the warning
                                    
                        # --- Un-nested 2-Step Delete Warning ---
                        else:
                            st.warning("Are you sure? This cannot be undone.")
                            y_m_col, n_m_col = st.columns(2)
                            with y_m_col:
                                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                if st.button("Yes, Delete", key=f"btn_del_yes_mix_{m['id']}"):
                                    supabase.table("user_mixes").delete().eq("id", m['id']).execute()
                                    st.session_state[del_m_key] = False
                                    st.success("Material deleted.")
                                    time.sleep(1)
                                    st.rerun()
                            with n_m_col:
                                if st.button("Cancel", key=f"btn_del_no_mix_{m['id']}"):
                                    st.session_state[del_m_key] = False # Hide the warning
                                    st.rerun() # Refresh to bring the normal buttons back

# This acts as the gatekeeper. If you are not logged in, show the login screen. If you are, launch the app.
if st.session_state.user_id is None:
    login_page()
else:
    main_application()

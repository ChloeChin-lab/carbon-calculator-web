# Import Streamlit for building the web application interface
import streamlit as st
# Import pandas for handling data tables and excel-like operations
import pandas as pd
# Import Supabase to connect to our cloud database
from supabase import create_client, Client
# Import os to safely read environment variables (like passwords) from the server
import os 
# Import requests to download files from the internet (like our Google Sheet)
import requests
# Import BytesIO to handle downloaded files in memory without saving to the hard drive
from io import BytesIO
# Import Altair for drawing beautiful, interactive charts
import altair as alt
# Import uuid to generate unique random IDs for components
import uuid
# Import time to add short pauses (like waiting 1 second after saving before refreshing)
import time

# Try to import FPDF to generate PDF reports
try:
    from fpdf import FPDF
    # If successful, remember that we have the PDF tool available
    HAS_FPDF = True
except ImportError:
    # If the tool is missing, remember that we cannot generate PDFs, but do not crash
    HAS_FPDF = False

# Safely define the PDF report structure only if the tool is installed
if HAS_FPDF:
    class PDFReport(FPDF):
        pass
else:
    # Create a fake, empty class if the tool is missing so the code doesn't break
    class PDFReport(object):
        pass

# Set the title of the browser tab and make the page take up the full width of the screen
st.set_page_config(page_title="Sustainability Assessment System", layout="wide")

# Apply custom CSS styles to make our buttons look professional and match engineering reports
st.markdown("""
<style>
/* Make the default primary button a nice professional blue */
div[data-testid="stButton"] > button[kind="primary"] {
    background-color: #3b82f6;
    color: white;
    padding: 10px 20px;
    font-size: 16px;
    font-weight: bold;
    border-radius: 6px;
    border: none;
}
/* Make the blue button slightly darker when the mouse hovers over it */
div[data-testid="stButton"] > button[kind="primary"]:hover {
    background-color: #2563eb;
}

/* Create a special class for Green Save/Confirm buttons */
div.element-container:has(span.btn-green) + div.element-container button {
    background-color: #10b981 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
/* Darken the green button on hover */
div.element-container:has(span.btn-green) + div.element-container button:hover {
    background-color: #059669 !important;
}

/* Create a special class for Red Delete/Remove/Warning buttons */
div.element-container:has(span.btn-red) + div.element-container button {
    background-color: #ef4444 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
/* Darken the red button on hover */
div.element-container:has(span.btn-red) + div.element-container button:hover {
    background-color: #dc2626 !important;
}

/* Create a special class for standard Blue Action buttons */
div.element-container:has(span.btn-blue) + div.element-container button {
    background-color: #3b82f6 !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
/* Darken the blue button on hover */
div.element-container:has(span.btn-blue) + div.element-container button:hover {
    background-color: #2563eb !important;
}

/* Create a special class for Grey Clone/Duplicate buttons */
div.element-container:has(span.btn-grey) + div.element-container button {
    background-color: #64748b !important;
    color: white !important;
    border: none !important;
    font-weight: bold !important;
}
/* Darken the grey button on hover */
div.element-container:has(span.btn-grey) + div.element-container button:hover {
    background-color: #475569 !important;
}

/* Make all standard data tables look clean with white backgrounds */
.stTable {
    background-color: white;
}
/* Style the table headers to be grey with bold centered black text */
th {
    background-color: #e0e0e0 !important;
    color: black !important;
    font-weight: bold !important;
    text-align: center !important;
}
</style>
""", unsafe_allow_html=True)

# Read our secret database passwords from the server's secure environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")

# Create a function to connect to Supabase, and cache it so it doesn't reconnect every time we click a button
@st.cache_resource
def init_supabase():
    # Return the active connection to the database
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# Actually start the connection using our function above
supabase = init_supabase()

# If the user hasn't logged in yet, create a blank memory slot for their user ID
if "user_id" not in st.session_state:
    st.session_state.user_id = None
# Create a blank memory slot for their email address
if "user_email" not in st.session_state:
    st.session_state.user_email = None
# Set the starting page to the Home dashboard
if "current_page" not in st.session_state:
    st.session_state.current_page = "Home"
# Set the default action in the Materials tab to viewing standard materials
if "mix_mode_radio" not in st.session_state:
    st.session_state.mix_mode_radio = "View Standard Materials"

# Set up blank memory slots for a Project Assessment so it remembers our work while we click around
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

# Create a function to generate a downloadable PDF report for our material comparisons
def generate_pdf_report(df, best, worst, savings):
    # If the PDF tool isn't installed, quietly stop and return nothing
    if not HAS_FPDF:
        return None
    try:
        # Start a new blank PDF document
        pdf = FPDF()
        # Add a single page to the document
        pdf.add_page()
        
        # Set the font to big bold Arial for the main title
        pdf.set_font("Arial", 'B', 16)
        # Write the title in the center of the page
        pdf.cell(0, 10, "Sustainability Comparison Report", ln=True, align='C')
        # Add a blank line for spacing
        pdf.ln(10)
        
        # Set the font to a smaller bold Arial for the sub-heading
        pdf.set_font("Arial", 'B', 12)
        # Write the sub-heading
        pdf.cell(0, 8, "Executive Summary", ln=True)
        # Change the font back to normal (not bold) for the paragraph
        pdf.set_font("Arial", '', 11)
        
        # Create the executive summary text using the math passed into the function
        summary = (f"This comparative analysis evaluates the Embodied Carbon Intensity (ECI) across selected materials. "
                   f"Choosing the optimal material ({best['Material']}) instead of the highest-impact option ({worst['Material']}) "
                   f"results in a {savings:.1f}% reduction in embodied carbon per cubic metre. "
                   f"For large-scale infrastructure applications, this material substitution represents a highly effective decarbonisation strategy.")
        
        # Write the paragraph onto the PDF page
        pdf.multi_cell(0, 6, summary)
        # Add another blank line
        pdf.ln(10)
        
        # Write the second sub-heading for the raw data
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 8, "Data Summary", ln=True)
        # Change font back to normal
        pdf.set_font("Arial", '', 10)
        
        # Loop through every material we compared and print its exact numbers
        for _, row in df.iterrows():
            pdf.cell(0, 6, f"- {row['Material']}: Mass: {row['Total Mass (kg/m³)']:.2f} kg/m³ | GWP100: {row['Total GWP100 (kgCO2e/m³)']:.2f} kgCO2e/m³", ln=True)
            
        # Finish the PDF and convert it into a computer-readable format for downloading
        return pdf.output(dest='S').encode('latin-1')
    except Exception:
        # If anything crashes, quietly return nothing
        return None

# Create a function to clean up messy data from Excel
def clean_df(df):
    # Check if the data is a valid table and isn't empty
    if isinstance(df, pd.DataFrame) and not df.empty:
        # Remove any invisible spaces from the column titles
        df.columns = df.columns.str.strip()
        # Look at every text column in the table
        for col in df.select_dtypes(include=['object']).columns:
            # Remove any invisible spaces from the beginning or end of the text
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
    # Return the perfectly clean table
    return df

# Create a function to safely convert text into math numbers without crashing
def safe_float(val, default=0.0):
    # If the box is blank (N/A), just return 0
    if pd.isna(val):
        return default
    try:
        # Try to turn it into a decimal number
        return float(val)
    except (ValueError, TypeError):
        # If it's a word or a dash that can't be a number, return 0 instead of crashing
        return default

# Cache this function for 10 minutes so it doesn't download the massive excel file every single click
@st.cache_data(ttl=600) 
def load_database():
    # Tell the system exactly which tabs we need from the Excel file
    required_sheets = ["Component_Factors", "Mix_Designs", "Project_Structures", "Unit_Logic", "Direct_Results"]
    
    # Check if we have a Google Sheet ID provided in our environment variables
    if SHEET_ID and len(SHEET_ID) > 20: 
        # Create the secret download link
        export_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
        try:
            # Try to download the file from Google, giving it 10 seconds before timing out
            response = requests.get(export_url, timeout=10)
            response.raise_for_status()
            # Store the downloaded file in the server's active memory
            excel_data = BytesIO(response.content)
            # Read the required tabs into pandas dataframes
            xls = pd.read_excel(excel_data, sheet_name=required_sheets)
            
            # Package all the tables neatly into a dictionary, cleaning them as we go
            return {
                "factors": clean_df(xls.get("Component_Factors", pd.DataFrame())),
                "mixes": clean_df(xls.get("Mix_Designs", pd.DataFrame())),
                "structures": clean_df(xls.get("Project_Structures", pd.DataFrame())),
                "unit_logic": clean_df(xls.get("Unit_Logic", pd.DataFrame())),
                "direct": clean_df(xls.get("Direct_Results", pd.DataFrame()))
            }
        except Exception as e:
            # If the cloud download fails, print an error to the server console but don't crash yet
            print(f"Warning: Cloud Database failed to load. Reason: {e}")
            pass 
            
    # If the cloud failed or no ID was provided, look for a local backup copy on the hard drive
    local_path = "materials_database.xlsx"
    if os.path.exists(local_path):
        try:
            # Read the local file
            xls = pd.read_excel(local_path, sheet_name=required_sheets)
            # Package it exactly like we did for the cloud version
            return {
                "factors": clean_df(xls.get("Component_Factors", pd.DataFrame())),
                "mixes": clean_df(xls.get("Mix_Designs", pd.DataFrame())),
                "structures": clean_df(xls.get("Project_Structures", pd.DataFrame())),
                "unit_logic": clean_df(xls.get("Unit_Logic", pd.DataFrame())),
                "direct": clean_df(xls.get("Direct_Results", pd.DataFrame()))
            }
        except Exception as e:
            # If both cloud and local fail, the app is completely broken
            print(f"Warning: Local Database failed to load. Reason: {e}")
            return None
            
    # If no file exists at all, return None
    return None

# Create the beautiful, centered login screen
def login_page():
    # Add some empty space at the top to push the box down into the center
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    # Create three columns to act as invisible margins (left, center box, right)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    
    # Only put things inside the middle column
    with col2:
        # Create a clean title area using standard markdown (no hardcoded colours so it adapts to light/dark mode)
        st.markdown("""
        <div style="text-align: center; padding-bottom: 20px;">
            <h1 style="font-size: 36px; margin-bottom: 5px;">Sustainability Assessment System</h1>
            <p style="font-size: 16px; color: grey;">Please log in to access.</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Create standard Streamlit text boxes for email and password
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        
        # Add a tiny gap
        st.markdown("<br>", unsafe_allow_html=True)
        # Apply our custom Blue Button style to the next button
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        
        # When the user clicks Log In
        if st.button("Log In", use_container_width=True):
            try:
                # Ask Supabase if this email and password are correct
                response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                # If correct, save their unique ID to memory
                st.session_state.user_id = response.user.id
                # Save their email address to memory
                st.session_state.user_email = response.user.email
                # Move them away from the login screen to the Home dashboard
                st.session_state.current_page = "Home"
                # Refresh the entire application to apply the changes
                st.rerun() 
            except Exception:
                # If the password is wrong or the account doesn't exist, show a big red error box
                st.error("Invalid email or password. Please contact your administrator for access.")

# Create a function that safely unpacks a saved project from the database back into the live app memory
def load_project_to_session(p_data, db):
    # Switch the user's view to the Project Assessment tab
    st.session_state.current_page = "Project Assessment"
    # Load the project name, adding "(Copy)" so they don't accidentally overwrite the original immediately
    st.session_state.draft_proj_name = f"{p_data['project_name']} (Copy)"
    # Load the type of bridge or building
    st.session_state.draft_structure = p_data['structure_type']
    # Clear any old math results
    st.session_state.project_results_df = None 
    
    # Look up our master list of structural components (like "Girders") so we know what's normal vs "Extra"
    known_components = []
    if db is not None and not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
        known_components = db["unit_logic"]["Component_Name"].dropna().astype(str).str.strip().tolist()
        
    # Start a blank list for the components we are unpacking
    new_draft = []
    # Grab the raw data stored in Supabase
    raw_comp_data = p_data.get("component_data", [])
    
    # If the data is in an older, outdated format (a dictionary instead of a list), convert it automatically
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
        
    # Loop through every piece of the bridge/building in the saved file
    for c_data in raw_comp_data:
        c_name = c_data.get("component_name", "Unknown")
        b_name = c_data.get("base_name") 
        
        # If it doesn't have a base category (like "Girder" or "Deck"), figure it out
        if not b_name:
            b_name = "Extra" 
            for kc in known_components:
                # If the name is something like "East Girder", we know it belongs to the "Girders" family
                if kc.lower() in c_name.lower():
                    b_name = kc
                    break
        
        # Unpack all the materials assigned to this component
        mats = []
        for m_data in c_data.get("materials", []):
            mats.append({
                "id": str(uuid.uuid4()), # Give it a fresh random ID for the UI
                "label": m_data.get("label", ""),
                "qty": m_data.get("quantity", 0.0),
                "unit": m_data.get("unit", "m3"),
                "ref_value": m_data.get("ref_value", 0.0),
                "ref_per_unit": m_data.get("ref_per_unit", False),
                "mix": m_data.get("assigned_mix", "--- Select ---")
            })
            
        # Put the fully unpacked component into our draft list
        new_draft.append({
            "id": str(uuid.uuid4()),
            "base_name": b_name if "Extra" not in b_name else "Extra",
            "custom_name": c_name,
            "count": c_data.get("multiplier_count", 1),
            "materials": mats
        })
        
    # Save the completely rebuilt list into the live app memory
    st.session_state.draft_components = new_draft

# Create a function that safely unpacks a custom material recipe back into the mix builder
def load_mix_to_session(m_data):
    # Switch the user's view to the Materials & Mixes tab
    st.session_state.current_page = "Materials & Mixes"
    # Force the radio button to the "Create Custom" mode
    st.session_state.mix_mode_radio = "Create Custom Material / Mix"
    
    # Load the mix name, adding "(Copy)"
    st.session_state.draft_mix_name = f"{m_data['mix_name']} (Copy)"
    # Remember its category (like Concrete or Steel)
    st.session_state.draft_mix_cat = m_data['category']
    # Load the standard ingredients (like cement and water)
    st.session_state.draft_mix_comps = m_data.get("components", {})
    
    # Unpack any weird, non-standard ingredients the user added manually
    adhoc_list = m_data.get("adhoc_materials", [])
    if adhoc_list:
        # Load them back into a pandas table so the data editor grid can read it
        st.session_state.adhoc_mats = pd.DataFrame(adhoc_list)
    else:
        # If there were none, create a blank table ready for input
        st.session_state.adhoc_mats = pd.DataFrame(columns=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"])

# Create a smart function that figures out how to calculate math based purely on the word they chose for their unit
def get_unit_logic_type(unit_string):
    # Make everything lowercase to avoid capitalisation bugs
    s = str(unit_string).lower()
    if "%" in s:
        # If they chose "% by weight", it's a mass multiplier
        if "wt" in s or "weight" in s: return "PERCENT_WEIGHT"
        # Otherwise, it's "% by volume", which is a cubic volume multiplier
        return "PERCENT_VOL"
    # If they chose "per unit", we multiply by the number of components
    if "/ unit" in s: return "PER_UNIT"
    # If they chose "Liters per m3", it's a specific chemical dosage formula
    if "l/m3" in s: return "LITER_PER_M3" 
    # If they chose flat liters, we divide by 1000
    if s.strip() == "l" or s.strip() == "liters": return "BASIC_LITER"
    # Otherwise, it's standard mass or volume
    return "BASIC"

# Create the engine that calculates exactly how heavy and how polluting a specific material is
def calculate_mix_carbon(mix_name, db, user_mixes, factors_df):
    m_mass, m_gwp = 0.0, 0.0
    
    # Check if the user selected a custom mix they built themselves
    if mix_name.startswith("Custom: "):
        # Remove the "Custom: " tag to find the real name in the database
        mix_n = mix_name.replace("Custom: ", "")
        # Search their personal Supabase file for the recipe
        match_mix = next((m for m in user_mixes if m["mix_name"] == mix_n), None)
        
        if match_mix:
            # If the recipe has standard ingredients
            if match_mix.get("components"):
                for c_name, c_val in match_mix["components"].items():
                    c_val = safe_float(c_val)
                    if c_name in factors_df.index:
                        # Look up the carbon factor for this specific ingredient from the master Google Sheet
                        factor_row = factors_df.loc[c_name]
                        # Add up the carbon pollution (Amount x Pollution Factor)
                        m_gwp += c_val * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                    # Add up the total weight
                    m_mass += c_val
                    
            # If the recipe has custom manually-typed ingredients
            if match_mix.get("adhoc_materials"):
                for adhoc in match_mix["adhoc_materials"]:
                    q = safe_float(adhoc.get("Quantity", 0))
                    m_mass += q
                    # Multiply by the custom carbon factor they typed in
                    m_gwp += q * safe_float(adhoc.get("GWP100 (kgCO2e/kg)", 0))
    else:
        # If it's a standard, official material, look it up in the Master Mix list
        match_df = db["mixes"][db["mixes"]["Mix_Key"] == mix_name] if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else pd.DataFrame()
        
        if not match_df.empty:
            # It's a standard mix (like C40/50 Concrete). Extract the official recipe row
            mix_row = match_df.iloc[0]
            # Check every possible ingredient to see if it's inside this recipe
            for comp_factor in factors_df.index:
                if comp_factor in mix_row and pd.notna(mix_row[comp_factor]):
                    val = safe_float(mix_row[comp_factor])
                    factor_row = factors_df.loc[comp_factor]
                    m_mass += val
                    m_gwp += val * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
        else:
            # If it wasn't a mix, check if it's a Direct Standalone Material (like Steel or Timber)
            match_direct = db["direct"][db["direct"]["Material_Key"] == mix_name] if not db["direct"].empty and "Material_Key" in db["direct"].columns else pd.DataFrame()
            if not match_direct.empty:
                direct_row = match_direct.iloc[0]
                # It doesn't have ingredients, it just has a flat Density (Mass) and Carbon value
                m_mass = safe_float(direct_row.get("Total_Mass_kg_m3", 1.0)) 
                # Prevent dividing by zero later if the sheet is missing data
                if m_mass == 0: m_mass = 1.0 
                
                # Get the flat carbon value
                m_gwp = safe_float(direct_row.get("GWP100_kgCO2e_m3", 0.0))
                # If they only provided a per-kg factor instead of a per-m3 total, multiply it out
                if m_gwp == 0.0: m_gwp = safe_float(direct_row.get("ECFGWP100_kgCO2e_kg", 0.0)) * m_mass
                    
    # Return the final calculated density (kg/m3) and efficiency factor (kgCO2e/kg) for this specific material
    return {
        "Mass (kg/m3)": m_mass,
        "Factor_GWP (kgCO2e/kg)": (m_gwp / m_mass) if m_mass > 0 else 0
    }

# Create the massive engine that calculates the entire project totals, handling all the different unit mathematics
def calculate_project_data(draft_components, db, user_mixes, factors_df):
    results_list = []
    # Start the running grand totals at zero
    grand_totals = {"mass": 0.0, "gwp": 0.0}
    clean_project_data = []

    # Loop through every piece of the bridge/building
    for comp_idx, comp in enumerate(draft_components):
        c_name = comp.get("custom_name", comp.get("base_name", "Unknown"))
        c_multiplier = int(comp.get("count", 1))
        c_materials = []

        # Loop through every material inside this piece of the bridge
        for mat in comp.get("materials", []):
            qty = safe_float(mat.get("qty", 0.0))
            unit_str = mat.get("unit", "")
            mix = mat.get("mix", "--- Select ---")
            
            ref_val = safe_float(mat.get("ref_value", 0.0))
            ref_per_unit = mat.get("ref_per_unit", False)
            
            # Determine the mathematical rule for this unit
            logic_type = get_unit_logic_type(unit_str)
            
            # Only do math if they actually selected a material and gave it an amount
            if mix != "--- Select ---" and qty > 0:
                # Ask the mix engine for the density and carbon factor
                props = calculate_mix_carbon(mix, db, user_mixes, factors_df)
                mass_per_m3 = props["Mass (kg/m3)"]
                
                total_mass_kg = 0.0
                
                # If the unit is a percentage or dosage (meaning it depends on the "Reference Value")
                if logic_type == "PERCENT_VOL" or logic_type == "LITER_PER_M3" or logic_type == "PERCENT_WEIGHT":
                    # If they ticked the "x Qty" box, multiply the reference by the number of components
                    actual_ref_val = (ref_val * c_multiplier) if ref_per_unit else ref_val
                    
                    if logic_type == "PERCENT_VOL":
                        # Ex: 2% of a 10m3 girder = 0.2m3 volume
                        vol_m3 = (qty / 100.0) * actual_ref_val
                        # Multiply by density to find the actual kg weight
                        total_mass_kg = vol_m3 * mass_per_m3
                    elif logic_type == "LITER_PER_M3":
                        # Ex: 5 Liters per every m3 of a 10m3 girder = 50 Liters
                        vol_L = qty * actual_ref_val
                        # Convert Liters to kg using the material's density
                        total_mass_kg = (vol_L / 1000.0) * mass_per_m3
                    elif logic_type == "PERCENT_WEIGHT":
                        # Ex: 5% of a 100-tonne girder's weight = 5 tonnes
                        weight_tonnes = (qty / 100.0) * actual_ref_val
                        # Convert to kg
                        total_mass_kg = weight_tonnes * 1000.0
                    
                # If the unit is a standard standalone unit
                elif logic_type in ["PER_UNIT", "BASIC", "BASIC_LITER"]:
                    # Multiply by the component count if the unit says "per unit"
                    base_vol = qty * c_multiplier if logic_type == "PER_UNIT" else qty
                    
                    if "tonne" in unit_str.lower():
                        # Just multiply by 1000
                        total_mass_kg = base_vol * 1000.0
                    elif "kg" in unit_str.lower():
                        # Already in kg!
                        total_mass_kg = base_vol
                    elif logic_type == "BASIC_LITER":
                        # Convert flat Liters to kg using density
                        total_mass_kg = (base_vol / 1000.0) * mass_per_m3
                    else:
                        # It's an m3 volume. Multiply by density to get kg weight
                        total_mass_kg = base_vol * mass_per_m3

                # Final step: Multiply the final massive kg weight by the material's carbon factor
                item_gwp = total_mass_kg * props["Factor_GWP (kgCO2e/kg)"]
                
                # Add these results to the running grand totals at the bottom of the page
                grand_totals["mass"] += total_mass_kg
                grand_totals["gwp"] += item_gwp
                
                # Format the label nicely for the table
                item_label = f"{comp_idx + 1}. {c_name} {mat.get('label', '')}".strip()
                
                # If it was a reference calculation, write out exactly how we calculated it for transparency
                if logic_type in ["PERCENT_VOL", "PERCENT_WEIGHT", "LITER_PER_M3"]:
                    mult_tag = " × Qty" if ref_per_unit else ""
                    display_qty = f"{qty} (Ref: {ref_val}{mult_tag})"
                else:
                    display_qty = f"{qty}"
                
                # Add this fully calculated line item to the final table
                results_list.append({
                    "Item": item_label,
                    "Material": mix,
                    "Volume/Amount": display_qty, 
                    "Unit": unit_str,
                    "Total Mass (kg)": total_mass_kg,
                    "Total GWP100 (kgCO2e)": item_gwp
                })
                
            # Keep a clean, raw record of what they selected so we can save it to the database
            c_materials.append({
                "label": mat.get("label", ""),
                "quantity": qty,
                "unit": unit_str,
                "ref_value": ref_val,
                "ref_per_unit": ref_per_unit,
                "assigned_mix": mix
            })
                
        # Attach the raw component data to the save payload
        clean_project_data.append({
            "base_name": comp.get("base_name", "Extra"),
            "component_name": c_name,
            "multiplier_count": c_multiplier,
            "materials": c_materials
        })
    
    # Convert the results list into a beautiful pandas table, ready for Streamlit
    results_df = pd.DataFrame(results_list) if len(results_list) > 0 else None
    return results_df, grand_totals, clean_project_data

# Create a function to draw the final calculation table and the big Grand Total box
def render_results_table_and_totals(df, totals):
    display_df = df.copy()
    # Start the row numbers at 1 instead of 0 (like normal humans count)
    display_df.index = display_df.index + 1 
    
    # Add commas and round to 2 decimal places so the numbers look professional (e.g. 1,000,000.00)
    display_df["Total Mass (kg)"] = display_df["Total Mass (kg)"].apply(lambda x: f"{float(x):,.2f}")
    display_df["Total GWP100 (kgCO2e)"] = display_df["Total GWP100 (kgCO2e)"].apply(lambda x: f"{float(x):,.2f}")
    
    # Draw the table on the screen
    st.table(display_df)
    
    # Create a nice grey box using HTML for the final grand totals
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

# Create the landing page you see when you first log in
def welcome_dashboard():
    # Capitalise their name based on their email address
    username = st.session_state.user_email.split('@')[0].capitalize()
    
    # Draw the big dark blue welcome banner
    st.markdown(f"""
    <div style="padding: 40px; background: linear-gradient(135deg, #1e293b, #0f172a); border-radius: 12px; margin-bottom: 30px; color: white; border: 1px solid #334155;">
        <h1 style="margin-top: 0; color: white;">Welcome, {username}!</h1>
        <p style="font-size: 18px; color: #cbd5e1; max-width: 800px;">
            Manage your structural material libraries, assess project sustainability, and optimise engineering designs.
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Split the screen into 3 columns for our three main tools
    col1, col2, col3 = col1, col2, col3 = st.columns(3)
    
    with col1:
        # Draw the description box for the Materials tab
        st.markdown("""
        <div style="background-color: #F0F4F8; padding: 20px; border-radius: 8px; border-top: 4px solid #3498DB; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Materials & Mixes</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The master library. Configure ingredients, build custom mixes, and compare properties.</p>
        </div><br>""", unsafe_allow_html=True)
        # Add the action button that teleports them to that tab
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Access", key="btn_nav_mats", use_container_width=True):
            st.session_state.current_page = "Materials & Mixes"
            st.rerun()
        
    with col2:
        # Draw the description box for the Project Assessment tab
        st.markdown("""
        <div style="background-color: #E8F8F5; padding: 20px; border-radius: 8px; border-top: 4px solid #1ABC9C; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">Project Assessment</h3>
            <p style="color: #5D6D7E; font-size: 14px;">The structural assembly. Configure components, assign materials, and generate assessments.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("Start Assessment", key="btn_nav_proj", use_container_width=True):
            st.session_state.current_page = "Project Assessment"
            st.rerun()
        
    with col3:
        # Draw the description box for the My Library tab
        st.markdown("""
        <div style="background-color: #F8F9F9; padding: 20px; border-radius: 8px; border-top: 4px solid #95A5A6; height: 140px;">
            <h3 style="color: #2C3E50; margin-top: 0;">My Library</h3>
            <p style="color: #5D6D7E; font-size: 14px;">Your historical database. Review, analyse, and manage your saved projects and custom mixes.</p>
        </div><br>""", unsafe_allow_html=True)
        st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
        if st.button("View Records", key="btn_nav_saved", use_container_width=True):
            st.session_state.current_page = "My Library"
            st.rerun()

# This is the master function that runs everything after you log in
def main_application():
    # Attempt to load the master database
    db = load_database()
    
    # If the database fails completely, crash the app safely and tell the user
    if db is None:
        st.error("Cannot start the application. Please check the database connection.")
        st.stop()

    # If we are on the Home page, show the Welcome dashboard and skip the rest of the file
    if st.session_state.current_page == "Home":
        st.sidebar.caption(f"User: {st.session_state.user_email}")
        if st.sidebar.button("Log Out"):
            st.session_state.user_id = None
            st.session_state.current_page = "Home"
            st.rerun()
        welcome_dashboard()
        return

    # Draw the persistent sidebar navigation menu
    if st.sidebar.button("Return to Home"):
        st.session_state.current_page = "Home"
        st.rerun()

    st.sidebar.markdown("---")
    
    # Use a radio button block to switch between tabs instantly
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

    # Draw the main title of whatever tab we are currently viewing
    st.title(st.session_state.current_page)
        
    # Download the user's specific custom saved mixes from Supabase
    user_mixes_res = supabase.table("user_mixes").select("*").eq("user_id", st.session_state.user_id).execute()
    user_mixes = user_mixes_res.data if user_mixes_res.data else []
    custom_mix_names = [m["mix_name"] for m in user_mixes]
    
    # Compile a master list of all official mixes AND all official direct materials
    mix_mats = db["mixes"]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
    direct_mats = db["direct"]["Material_Key"].dropna().tolist() if not db["direct"].empty and "Material_Key" in db["direct"].columns else []
    standard_mixes = sorted(list(set(mix_mats + direct_mats)))
    
    # Combine the official list with the user's custom list to create the ultimate master dropdown list
    all_available_mixes = standard_mixes + [f"Custom: {name}" for name in custom_mix_names]
    
    # Prepare the carbon factors reference table
    factors_df = db["factors"].drop_duplicates(subset=["Component"]).set_index("Component") if not db["factors"].empty and "Component" in db["factors"].columns else pd.DataFrame()

    # ---------------------------------------------------------
    # TAB 1: MATERIALS & MIXES
    # ---------------------------------------------------------
    if st.session_state.current_page == "Materials & Mixes":
        
        # Remember which sub-tab (radio button) they were looking at
        default_mode_idx = 0
        if st.session_state.get("mix_mode_radio") == "Create Custom Material / Mix":
            default_mode_idx = 1
        elif st.session_state.get("mix_mode_radio") == "Compare Mixes":
            default_mode_idx = 2
            
        # Draw the three horizontal action choices
        mode = st.radio("Choose an action:", ["View Standard Materials", "Create Custom Material / Mix", "Compare Mixes"], horizontal=True, index=default_mode_idx, key="mix_mode_radio_ui")
        
        # Keep memory updated if they click a different one
        if st.session_state.mix_mode_radio != mode:
            st.session_state.mix_mode_radio = mode
        
        # Build the dropdown list of material categories (like Concrete, Steel, etc.)
        mix_cats = set(db["mixes"]["Category"].dropna().unique()) if not db["mixes"].empty and "Category" in db["mixes"].columns else set()
        direct_cats = set(db["direct"]["Category"].dropna().unique()) if not db["direct"].empty and "Category" in db["direct"].columns else set()
        all_categories = sorted(list(mix_cats.union(direct_cats)))
        
        # ACTION 1: VIEW STANDARD MATERIALS
        if mode == "View Standard Materials":
            st.markdown("#### View Standard Material Properties")
            
            # Create two dropdowns side-by-side
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                selected_cat = st.selectbox("Material Category:", ["--- Select Category ---"] + all_categories, key="view_cat")
            
            # If they pick a category, show only the materials inside that category
            if selected_cat != "--- Select Category ---":
                cat_mix_mats = db["mixes"][db["mixes"]["Category"] == selected_cat]["Mix_Key"].dropna().tolist() if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else []
                cat_direct_mats = db["direct"][db["direct"]["Category"] == selected_cat]["Material_Key"].dropna().tolist() if not db["direct"].empty and "Material_Key" in db["direct"].columns else []
                cat_all_mats = sorted(list(set(cat_mix_mats + cat_direct_mats)))
                
                with col_sel2:
                    selected_mat = st.selectbox("Material Type/Grade:", ["--- Select Material ---"] + cat_all_mats, key="view_mat")
                
                # If they select a specific material, show a button to calculate it
                if selected_mat != "--- Select Material ---":
                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                    if st.button("View Material Properties", type="primary"):
                        
                        # Determine if this is a recipe (mix) or a solid item (direct)
                        is_mix = selected_mat in cat_mix_mats
                        
                        # Set up the blank property buckets
                        final_props = {
                            "Total_Mass_kg_m3": 0,
                            "ECFGWP100_kgCO2e_kg": 0,
                            "GWP100_kgCO2e_m3": 0
                        }
                        
                        # Prepare data buckets for the pie charts
                        chart_components_mass = {}
                        chart_components_carbon = {}
                        
                        try:
                            # IF IT'S A SOLID DIRECT MATERIAL
                            if not is_mix:
                                match_df = db["direct"][(db["direct"]["Category"] == selected_cat) & (db["direct"]["Material_Key"] == selected_mat)]
                                if not match_df.empty:
                                    # Grab the raw values
                                    direct_row = match_df.iloc[0]
                                    for prop in final_props:
                                        if prop in direct_row and pd.notna(direct_row[prop]):
                                            final_props[prop] = safe_float(direct_row[prop])
                                            
                                    # Since it's a solid block, it is 100% composed of itself. Feed this to the pie charts!
                                    chart_components_mass[selected_mat] = final_props["Total_Mass_kg_m3"]
                                    chart_components_carbon[selected_mat] = final_props["GWP100_kgCO2e_m3"]
                                else:
                                    st.error(f"Could not find exact data for '{selected_mat}'.")
                                    st.stop()
                            
                            # IF IT'S A RECIPE MIX (Like Concrete)
                            else:
                                match_df = db["mixes"][(db["mixes"]["Category"] == selected_cat) & (db["mixes"]["Mix_Key"] == selected_mat)]
                                if not match_df.empty:
                                    mix_row = match_df.iloc[0]
                                    total_mass = 0
                                    total_gwp = 0
                                    
                                    # Loop through all ingredients and tally them up
                                    for comp in factors_df.index:
                                        if comp in mix_row and pd.notna(mix_row[comp]):
                                            mass = safe_float(mix_row[comp])
                                            if mass > 0:
                                                factor_row = factors_df.loc[comp]
                                                comp_gwp = mass * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                                                
                                                # Add these pieces to the pie chart data buckets
                                                chart_components_mass[comp] = mass
                                                chart_components_carbon[comp] = comp_gwp
                                                
                                                # Update running totals
                                                total_mass += mass
                                                total_gwp += comp_gwp
                                    
                                    # Lock in the final calculated values
                                    if total_mass > 0:
                                        final_props["Total_Mass_kg_m3"] = total_mass
                                        final_props["GWP100_kgCO2e_m3"] = total_gwp
                                        final_props["ECFGWP100_kgCO2e_kg"] = total_gwp / total_mass
                                else:
                                    st.error(f"Could not find exact data for mix '{selected_mat}'.")
                                    st.stop()
                            
                            # Draw the final results on the screen!
                            st.markdown("---")
                            st.markdown(f"**Properties for {selected_mat}**")
                            
                            m_col1, m_col2, m_col3 = st.columns(3)
                            m_col1.metric("Total Mass", f"{final_props['Total_Mass_kg_m3']:,.2f} kg/m³")
                            m_col2.metric("GWP100 Factor", f"{final_props['ECFGWP100_kgCO2e_kg']:,.3f} kgCO2e/kg")
                            m_col3.metric("GWP100 Total", f"{final_props['GWP100_kgCO2e_m3']:,.2f} kgCO2e/m³")
                            
                            # Check if we successfully gathered data for the pie charts, and draw them
                            if len(chart_components_mass) > 0:
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
                                    st.markdown("**2. By GWP100**")
                                    chart_data_carbon = pd.DataFrame({"Component": list(chart_components_carbon.keys()), "Carbon": list(chart_components_carbon.values())})
                                    pie_carbon = alt.Chart(chart_data_carbon).mark_arc(innerRadius=40).encode(
                                        theta=alt.Theta(field="Carbon", type="quantitative"),
                                        color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                        tooltip=["Component", "Carbon"]
                                    ).properties(height=280)
                                    st.altair_chart(pie_carbon, use_container_width=True)
                        except Exception as e:
                            st.error(f"Error parsing data. Details: {e}")

        # ACTION 2: CREATE CUSTOM MATERIAL
        elif mode == "Create Custom Material / Mix":
            st.markdown("#### Design a Custom Material or Mix")
            
            # Load draft names if we arrived here by clicking "Clone for Editing"
            d_name = st.session_state.get("draft_mix_name", "")
            d_cat = st.session_state.get("draft_mix_cat", "--- Select Category ---")
            
            # Create the naming inputs
            c_col1, c_col2 = st.columns(2)
            with c_col1:
                cat_index = all_categories.index(d_cat) + 1 if d_cat in all_categories else 0
                # By enabling `allow_custom_value=True` (or similar logic), we let them type their own. Streamlit natively supports typing in selectboxes now if configured, but let's just add an option.
                # Actually, standard Streamlit selectbox doesn't allow typing new strings easily without a separate text box. 
                # I will add a "➕ Create New Category..." option to make it foolproof.
                cat_options = ["--- Select Category ---"] + all_categories + ["➕ Create New Category..."]
                try:
                    cat_index = cat_options.index(d_cat)
                except ValueError:
                    cat_index = 0
                custom_cat_select = st.selectbox("Assign to Category:", cat_options, index=cat_index, key="cust_cat")
                
                # If they choose to create a new one, show a text box instantly
                if custom_cat_select == "➕ Create New Category...":
                    custom_cat = st.text_input("Type new category name:", placeholder="e.g., Polymers", key="cust_cat_new")
                else:
                    custom_cat = custom_cat_select
                    
            with c_col2:
                custom_mix_name = st.text_input("Name your Custom Item:", value=d_name, placeholder="e.g., C40/50 or Recycled Steel", key="mix_name_input")
            
            st.markdown("---")
            # Ask if they are building a recipe or a single block of material
            creation_type = st.radio("What type of item are you creating?", 
                                     ["Multi-Ingredient Mix (e.g., Concrete)", "Standalone Material (e.g., Steel, Timber)"],
                                     horizontal=True, key="creation_type_radio")
            
            # Buckets to hold what they type in
            custom_mix_data = {}
            valid_adhoc = []
            
            # IF IT'S A STANDALONE MATERIAL
            if creation_type == "Standalone Material (e.g., Steel, Timber)":
                st.markdown("##### Define Material Properties")
                
                s_col1, s_col2 = st.columns(2)
                with s_col1:
                    standalone_density = st.number_input("Density / Unit Weight (kg/m³)", min_value=0.1, value=7850.0, step=10.0, key="std_density")
                with s_col2:
                    standalone_gwp = st.number_input("GWP100 (kgCO2e/kg)", min_value=0.0, value=1.50, step=0.01, format="%.3f", key="std_gwp")
                
                # If they typed something valid, pack it into the adhoc bucket
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
                    
            # IF IT'S A MULTI-INGREDIENT MIX
            else:
                st.markdown("##### 1. Choose Input Units")
                unit_mode = st.radio("How are you inputting your mix ingredients?", 
                                     ["Standard (kg/m³)", "Total Batch Weight (kg)", "US Imperial (lb/yd³)"], 
                                     horizontal=True, key="unit_mode_radio")
                
                # Handle automatic math conversions if they pick weird units
                batch_vol = 1.0
                if unit_mode == "Total Batch Weight (kg)":
                    batch_vol = st.number_input("What is the total batch volume? (m³):", min_value=0.1, value=1.0, step=0.1, key="batch_vol_input")
                    st.info(f"Your inputs will be automatically divided by {batch_vol} to standardise them to kg/m³.")
                elif unit_mode == "US Imperial (lb/yd³)":
                    st.info("Your inputs will be automatically converted to kg/m³ (1 lb/yd³ ≈ 0.5933 kg/m³).")
                    
                st.markdown("##### 2. Standard Ingredients")
                
                # Create a grid of number boxes for every single official ingredient
                if not factors_df.empty:
                    all_comps = factors_df.index.tolist()
                else:
                    all_comps = []
                
                raw_input_data = {}
                d_comps = st.session_state.get("draft_mix_comps", {})
                
                input_cols = st.columns(4)
                for i, comp in enumerate(all_comps):
                    default_val = float(d_comps.get(comp, 0.0))
                    val = input_cols[i % 4].number_input(comp, min_value=0.0, step=10.0, value=default_val, key=f"cust_comp_{comp}")
                    if val > 0:
                        raw_input_data[comp] = val
                        
                st.markdown("##### 3. Add Custom Ingredients")
                st.caption("To delete a row, highlight it and press Delete on your keyboard.")
                
                # Create the Excel-style grid for typing their own secret ingredients
                if "adhoc_mats" not in st.session_state:
                    st.session_state.adhoc_mats = pd.DataFrame(columns=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"])
                    
                edited_adhoc_df = st.data_editor(
                    st.session_state.adhoc_mats, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    key="adhoc_editor",
                    column_order=["Material Name", "Quantity", "GWP100 (kgCO2e/kg)"]
                )
                
                # Apply the unit math conversions to all the standard inputs
                for comp, val in raw_input_data.items():
                    if unit_mode == "US Imperial (lb/yd³)":
                        custom_mix_data[comp] = val * 0.593276
                    elif unit_mode == "Total Batch Weight (kg)":
                        custom_mix_data[comp] = val / batch_vol
                    else:
                        custom_mix_data[comp] = val
                        
                # Apply the unit math conversions to all the custom Excel grid inputs
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
            
            # IF THEY CLICK PREVIEW (Works for both Standalone and Multi-Ingredient)
            if preview_mix and (len(custom_mix_data) > 0 or len(valid_adhoc) > 0):
                total_mass = 0
                total_gwp = 0
                
                custom_mix_carbon = {}
                c_data_mass_list = []
                
                # Tally up the standard ingredients
                for comp, mass in custom_mix_data.items():
                    if comp in factors_df.index:
                        factor_row = factors_df.loc[comp]
                        comp_gwp = mass * safe_float(factor_row.get('ECFGWP100_kgCO2e_kg', 0))
                        custom_mix_carbon[comp] = comp_gwp
                        
                        total_gwp += comp_gwp
                        total_mass += mass
                        c_data_mass_list.append({"Component": comp, "Mass": mass})
                
                # Tally up the custom ingredients
                for adhoc in valid_adhoc:
                    comp = adhoc["Material Name"]
                    mass = adhoc["Quantity"]
                    comp_gwp = mass * adhoc["GWP100 (kgCO2e/kg)"]
                    custom_mix_carbon[comp] = comp_gwp
                    total_gwp += comp_gwp
                    total_mass += mass
                    c_data_mass_list.append({"Component": comp, "Mass": mass})
                
                # Draw the final preview numbers
                st.markdown("##### Live Properties (Standardised to 1 m³ volume)")
                r_col1, r_col2, r_col3 = st.columns(3)
                r_col1.metric("Total Mass (Density)", f"{total_mass:,.2f} kg/m³")
                r_col2.metric("GWP100 Factor", f"{(total_gwp / total_mass):,.3f} kgCO2e/kg" if total_mass > 0 else "0")
                r_col3.metric("GWP100 Total", f"{total_gwp:,.2f} kgCO2e/m³")
                
                # Draw the pie charts, but ONLY if they built a multi-ingredient mix
                if creation_type == "Multi-Ingredient Mix (e.g., Concrete)":
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
                        st.markdown("**2. By GWP100**")
                        c_data_carbon = pd.DataFrame({"Component": list(custom_mix_carbon.keys()), "Carbon": list(custom_mix_carbon.values())})
                        c_pie_carbon = alt.Chart(c_data_carbon).mark_arc(innerRadius=40).encode(
                            theta=alt.Theta(field="Carbon", type="quantitative"),
                            color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                            tooltip=["Component", "Carbon"]
                        ).properties(height=280)
                        st.altair_chart(c_pie_carbon, use_container_width=True)
            
            # IF THEY CLICK SAVE
            if save_mix:
                if custom_cat == "--- Select Category ---" or not custom_cat:
                    st.error("Please assign or type a category before saving.")
                elif not custom_mix_name:
                    st.error("Please provide a name for your item.")
                elif len(custom_mix_data) == 0 and len(valid_adhoc) == 0:
                    st.error("Please add at least one ingredient or property.")
                else:
                    # Package the data safely for the database
                    mix_payload = {
                        "user_id": st.session_state.user_id,
                        "mix_name": custom_mix_name,
                        "category": custom_cat,
                        "components": custom_mix_data,
                        "adhoc_materials": valid_adhoc
                    }
                    
                    # Check if this exact name already exists in their database
                    existing_mix = next((m for m in user_mixes if m['mix_name'] == custom_mix_name and m['category'] == custom_cat), None)
                    
                    if existing_mix:
                        # If it exists, trigger the Red Warning Box overwrite workflow
                        st.session_state.confirm_overwrite_mix_name = custom_mix_name
                        st.session_state.existing_mix_id = existing_mix['id']
                        st.session_state.mix_payload_draft = mix_payload
                        st.rerun()
                    else:
                        # If it's brand new, trigger the save workflow immediately
                        st.session_state.execute_mix_save = True
                        st.session_state.mix_payload_draft = mix_payload
                        st.rerun()
                        
            # OVERWRITE WARNING WORKFLOW
            if st.session_state.get("confirm_overwrite_mix_name"):
                st.error(f"A mix named '{st.session_state.confirm_overwrite_mix_name}' already exists in this category. Do you want to overwrite it?")
                col_y, col_n = st.columns(2)
                with col_y:
                    st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                    if st.button("Yes, Overwrite"):
                        st.session_state.execute_mix_save = True
                        st.session_state.confirm_overwrite_mix_name = None
                        st.rerun()
                with col_n:
                    if st.button("No, Change Name"):
                        st.session_state.confirm_overwrite_mix_name = None
                        st.session_state.mix_payload_draft = None
                        st.rerun()
                        
            # EXECUTE THE DATABASE SAVE
            if st.session_state.get("execute_mix_save"):
                payload = st.session_state.mix_payload_draft
                try:
                    if st.session_state.get("existing_mix_id"):
                        # If overwriting, UPDATE the existing row
                        supabase.table("user_mixes").update(payload).eq("id", st.session_state.existing_mix_id).execute()
                        st.success(f"Mix '{payload['mix_name']}' successfully overwritten! Clearing form...")
                    else:
                        # If new, INSERT a new row
                        supabase.table("user_mixes").insert(payload).execute()
                        st.success(f"'{payload['mix_name']}' saved successfully. Clearing form...")
                    
                    # WIPE ALL INPUT FIELDS COMPLETELY CLEAN
                    keys_to_delete = ["draft_mix_name", "draft_mix_cat", "draft_mix_comps", "mix_name_input", "cust_cat", "cust_cat_new", "adhoc_mats", "std_density", "std_gwp", "creation_type_radio", "unit_mode_radio", "batch_vol_input"]
                    for key in list(st.session_state.keys()):
                        # Wipe out all the standard ingredient text boxes which start with "cust_comp_"
                        if key.startswith("cust_comp_") or key in keys_to_delete:
                            del st.session_state[key]
                            
                    st.session_state.execute_mix_save = False
                    st.session_state.existing_mix_id = None
                    time.sleep(1.5)
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Save Error: Details: {e}")
                    st.session_state.execute_mix_save = False

        # ACTION 3: COMPARE MIXES
        elif mode == "Compare Mixes":
            st.markdown("#### Compare Materials & Mixes")
            st.info("Select multiple materials or custom mixes below to analyse their sustainability metrics side-by-side.")
            
            # Show a giant multi-select dropdown for everything they have access to
            selected_for_comp = st.multiselect("Select Mixes to Compare:", all_available_mixes, key="compare_multiselect")
            
            if selected_for_comp:
                comp_data = []
                # Loop through every selected material and calculate it using our master engine
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
                    
                comp_df = pd.DataFrame(comp_data)
                
                # We can only draw charts if they selected at least 2 things to compare
                if len(comp_data) > 1:
                    st.markdown("---")
                    # Sort the table from cleanest (top) to dirtiest (bottom)
                    sorted_df = comp_df.sort_values("Total GWP100 (kgCO2e/m³)")
                    best = sorted_df.iloc[0]
                    worst = sorted_df.iloc[-1]
                    
                    if worst["Total GWP100 (kgCO2e/m³)"] > 0:
                        savings_pct = ((worst["Total GWP100 (kgCO2e/m³)"] - best["Total GWP100 (kgCO2e/m³)"]) / worst["Total GWP100 (kgCO2e/m³)"]) * 100
                    else:
                        savings_pct = 0
                        
                    # Draw the Executive Summary text block automatically generated from the math
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
            
                    st.markdown("##### Visual Analytics")
                    # Split into tabs for the charts
                    tab_bar, tab_scatter = st.tabs(["GWP100 Leaderboard", "Density vs. GWP100 Trade-off"])
                    
                    with tab_bar:
                        # Grab the exact winning carbon number to pass to the chart engine
                        best_val = float(best['Total GWP100 (kgCO2e/m³)']) 
                        
                        # Set up the basic bar chart axes
                        base_chart = alt.Chart(comp_df).encode(
                            x=alt.X("Total GWP100 (kgCO2e/m³):Q", title="Global Warming Potential (kgCO2e/m³)", scale=alt.Scale(domain=[0, comp_df["Total GWP100 (kgCO2e/m³)"].max() * 1.15])),
                            y=alt.Y("Material:N", sort="-x", title="")
                        )
                        
                        # Draw the bars, colouring the winning bar green using the PERFECT match of the column name (with the ³ symbol)
                        bars = base_chart.mark_bar(cornerRadiusEnd=4, height=40).encode(
                            color=alt.condition(
                                alt.datum['Total GWP100 (kgCO2e/m³)'] == best_val,
                                alt.value('#27ae60'),  # Green for the winner
                                alt.value('#95a5a6')   # Grey for the rest
                            ),
                            tooltip=["Material", "Total Mass (kg/m³)", "Total GWP100 (kgCO2e/m³)"]
                        )
                        
                        # Print the actual numbers at the end of the bars
                        text = base_chart.mark_text(
                            align='left',
                            baseline='middle',
                            dx=5,
                            fontWeight='bold'
                        ).encode(
                            text=alt.Text('Total GWP100 (kgCO2e/m³):Q', format=',.2f')
                        )
                        
                        final_bar_chart = (bars + text).properties(height=alt.Step(60)) 
                        st.altair_chart(final_bar_chart, use_container_width=True)
                        
                    with tab_scatter:
                        # Draw the scatter plot using Density as the X axis
                        scatter = alt.Chart(comp_df).mark_circle(size=200).encode(
                            x=alt.X("Total Mass (kg/m³):Q", title="Density (kg/m³)", scale=alt.Scale(zero=False, padding=20)),
                            y=alt.Y("Total GWP100 (kgCO2e/m³):Q", title="Total GWP100 (kgCO2e/m³)", scale=alt.Scale(zero=False, padding=20)),
                            color=alt.Color("Material:N", legend=alt.Legend(title="Material")),
                            tooltip=["Material", "Total Mass (kg/m³)", "Total GWP100 (kgCO2e/m³)"]
                        ).properties(height=350)
                        st.altair_chart(scatter, use_container_width=True)
                
                    st.markdown("##### Detailed Metric Breakdown & Data Export")
                    
                    # Highlight the winning row in the table in pale green
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
                    
                    # Build the PDF and CSV download buttons
                    st.markdown("<br>", unsafe_allow_html=True)
                    col_csv, col_pdf, _ = st.columns([1, 1, 1.5])
                    
                    csv_data = comp_df.to_csv(index=False).encode('utf-8')
                    col_csv.download_button(
                        label="📄 Download Data (CSV)",
                        data=csv_data,
                        file_name="material_comparison.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
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
                            
                    # --- NEW FEATURE: SIDE-BY-SIDE INGREDIENT MATRIX ---
                    st.markdown("---")
                    st.markdown("##### Side-by-Side Ingredient Matrix")
                    st.info("Compare the exact recipes of all your selected materials side-by-side.")
                    
                    matrix_data = []
                    # Crack open every selected mix to find its ingredients
                    for mix_name in selected_for_comp:
                        if mix_name.startswith("Custom: "):
                            mix_n = mix_name.replace("Custom: ", "")
                            match_mix = next((m for m in user_mixes if m["mix_name"] == mix_n), None)
                            if match_mix:
                                if match_mix.get("components"):
                                    for c_name, c_val in match_mix["components"].items():
                                        mass = safe_float(c_val)
                                        if mass > 0:
                                            matrix_data.append({"Material": mix_name, "Ingredient": c_name, "Quantity (kg)": mass})
                                if match_mix.get("adhoc_materials"):
                                    for adhoc in match_mix["adhoc_materials"]:
                                        mass = safe_float(adhoc.get("Quantity", 0))
                                        if mass > 0:
                                            matrix_data.append({"Material": mix_name, "Ingredient": adhoc["Material Name"], "Quantity (kg)": mass})
                                # Fallback if they selected a Custom Standalone Material (treat the material as the ingredient)
                                if not match_mix.get("components") and not match_mix.get("adhoc_materials"):
                                    matrix_data.append({"Material": mix_name, "Ingredient": mix_name, "Quantity (kg)": safe_float(match_mix.get("Total_Mass_kg_m3", 1.0))})
                        else:
                            # Official Mix (like Concrete)
                            match_df = db["mixes"][db["mixes"]["Mix_Key"] == mix_name] if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns else pd.DataFrame()
                            if not match_df.empty:
                                mix_row = match_df.iloc[0]
                                for comp_factor in factors_df.index:
                                    if comp_factor in mix_row and pd.notna(mix_row[comp_factor]):
                                        mass = safe_float(mix_row[comp_factor])
                                        if mass > 0:
                                            matrix_data.append({"Material": mix_name, "Ingredient": comp_factor, "Quantity (kg)": mass})
                            else:
                                # Official Direct Material (like Steel). Treat the material as the ingredient!
                                match_direct = db["direct"][db["direct"]["Material_Key"] == mix_name] if not db["direct"].empty and "Material_Key" in db["direct"].columns else pd.DataFrame()
                                if not match_direct.empty:
                                    direct_row = match_direct.iloc[0]
                                    mass = safe_float(direct_row.get("Total_Mass_kg_m3", 1.0))
                                    matrix_data.append({"Material": mix_name, "Ingredient": mix_name, "Quantity (kg)": mass})

                    # If we found any ingredients, use pandas to create a massive side-by-side pivot table
                    if matrix_data:
                        matrix_df = pd.DataFrame(matrix_data)
                        pivot_df = matrix_df.pivot_table(index="Ingredient", columns="Material", values="Quantity (kg)", aggfunc='sum').fillna(0)
                        st.dataframe(pivot_df.style.format("{:,.2f}"), use_container_width=True)
                            
                else:
                    st.error("Please select at least one more material from the dropdown above to generate the side-by-side comparison report and visual charts.")
                    st.dataframe(comp_df.set_index("Material").style.format({
                        "Total Mass (kg/m³)": "{:,.2f}",
                        "GWP100 Factor (kgCO2e/kg)": "{:,.3f}",
                        "Total GWP100 (kgCO2e/m³)": "{:,.2f}"
                    }), use_container_width=True)

    # ---------------------------------------------------------
    # TAB 2: PROJECT ASSESSMENT
    # ---------------------------------------------------------
    elif st.session_state.current_page == "Project Assessment":

        col_proj_details, col_clear = st.columns([3, 1])
        
        with col_proj_details:
            st.markdown("### 1. Project Details & Structure")
            st.session_state.draft_proj_name = st.text_input("Project Name:", value=st.session_state.draft_proj_name, placeholder="Enter project name...")
            
        with col_clear:
            st.markdown("<br>", unsafe_allow_html=True)
            # WORKFLOW: CLEAR ALL (Un-nested and red)
            if not st.session_state.get("confirm_clear_all", False):
                if st.button("Clear All & Start Over"):
                    st.session_state.confirm_clear_all = True
                    st.rerun()
            else:
                st.error("Are you sure? All progress will be lost.")
                col_y, col_n = st.columns(2)
                with col_y:
                    st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                    if st.button("Yes, Clear"):
                        st.session_state.draft_proj_name = ""
                        st.session_state.draft_structure = "---"
                        st.session_state.draft_components = []
                        st.session_state.project_results_df = None
                        st.session_state.confirm_clear_all = False
                        st.rerun()
                with col_n:
                    if st.button("Cancel"):
                        st.session_state.confirm_clear_all = False
                        st.rerun()
        
        # Pull the available bridge/building templates from the master Excel file
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
                # When they click Generate, create all the standard bridge pieces instantly
                if selected_structure != "---":
                    st.session_state.draft_structure = selected_structure
                    st.session_state.draft_components = []
                    st.session_state.project_results_df = None

                    components_str = db["structures"].loc[db["structures"]["Structure_Name"] == selected_structure, "Components"].values[0]
                    component_list = [c.strip() for c in components_str.split(",") if "Extra" not in c.strip()]
                    
                    for comp in component_list:
                        # Automatically fetch the best starting unit from the Unit_Logic sheet
                        default_unit = "m3"
                        if not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
                            match_mask = db["unit_logic"]["Component_Name"].astype(str).str.strip().str.lower() == str(comp).strip().lower()
                            unit_row = db["unit_logic"][match_mask]
                            if not unit_row.empty and "Default_Unit" in unit_row.columns:
                                val = str(unit_row["Default_Unit"].values[0]).strip()
                                if val and val.lower() != "nan":
                                    default_unit = val

                        st.session_state.draft_components.append({
                            "id": str(uuid.uuid4()),
                            "base_name": comp,
                            "custom_name": comp, 
                            "count": 1,
                            "materials": [{
                                "id": str(uuid.uuid4()),
                                "label": "",
                                "qty": 0.0,
                                "unit": default_unit,
                                "ref_value": 0.0,
                                "ref_per_unit": False,
                                "mix": "--- Select ---"
                            }]
                        })
                    st.rerun()

        # If a template is active, draw the massive component list
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
                    # If they added an "Extra" custom component, let them completely rename it
                    if is_extra:
                        comp["custom_name"] = st.text_input("Custom Component Name:", value=comp["custom_name"], key=f"name_{comp['id']}")
                    else:
                        comp["custom_name"] = st.text_input("Component Name:", value=comp["custom_name"], key=f"name_{comp['id']}")

                with col_del_comp:
                    st.markdown("<br>", unsafe_allow_html=True)
                    # Only allow deleting components if they are the special "Extra" ones
                    if is_extra:
                        st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                        if st.button("Remove Component", key=f"del_comp_{comp['id']}"):
                            comps_to_remove.append(comp)

                # Set up the master unit list
                units = ["m3", "m3 / unit", "tonnes", "tonnes / unit", "kg", "L", "L/m3", "% by volume", "% by weight", "m", "m2", "units"]
                
                # Fetch special units from the database specific to this component (like m2 for decks)
                if not db["unit_logic"].empty and "Component_Name" in db["unit_logic"].columns:
                    match_mask = db["unit_logic"]["Component_Name"].astype(str).str.strip().str.lower() == str(comp["base_name"]).strip().lower()
                    unit_row = db["unit_logic"][match_mask]
                    if not unit_row.empty and "Unit_Options" in unit_row.columns:
                        sheet_units = [u.strip() for u in str(unit_row["Unit_Options"].values[0]).split(",")]
                        for su in sheet_units:
                            if su not in units:
                                units.append(su)

                mats_to_remove = []
                
                # Draw the materials specifically attached to this component
                for mat in comp["materials"]:
                    
                    unit_key = f"unit_{mat['id']}"
                    if unit_key in st.session_state:
                        mat["unit"] = st.session_state[unit_key]
                        
                    # Figure out if this unit requires the special "Reference Math" boxes
                    logic_type = get_unit_logic_type(mat["unit"])
                    needs_ref = logic_type in ["PERCENT_VOL", "PERCENT_WEIGHT", "LITER_PER_M3"]
                    
                    if needs_ref:
                        col_label, col_mix, col_qty, col_unit, col_ref, col_mult, col_del = st.columns([1.8, 2.2, 1.0, 1.2, 1.2, 0.8, 0.8])
                    else:
                        col_label, col_mix, col_qty, col_unit, col_del = st.columns([2.5, 3, 1.5, 1.5, 1])
                    
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
                        if len(comp["materials"]) > 1: 
                            st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                            if st.button("Delete", key=f"del_mat_{mat['id']}"):
                                mats_to_remove.append(mat)

                # Delete things they clicked delete on
                for mat in mats_to_remove:
                    comp["materials"].remove(mat)
                    st.rerun()

                col_add_mat, col_nav_mix, col_empty = st.columns([1.5, 1.5, 3])
                with col_add_mat:
                    # Add a new material row inside this component
                    if st.button(f"+ Add Material", key=f"add_mat_btn_{comp['id']}"):
                        comp["materials"].append({
                            "id": str(uuid.uuid4()),
                            "label": "",
                            "qty": 0.0,
                            "unit": units[0],
                            "ref_value": 0.0,
                            "ref_per_unit": False,
                            "mix": "--- Select ---"
                        })
                        st.rerun()
                with col_nav_mix:
                    # Fast teleport button to go build a new custom mix
                    st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                    if st.button("Create Custom Mix ➔", key=f"nav_btn_{comp['id']}"):
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
                        "ref_value": 0.0,
                        "ref_per_unit": False,
                        "mix": "--- Select ---"
                    }]
                })
                st.rerun()

            st.markdown("---")
            
            # BIG CALCULATION BUTTON
            st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
            if st.button("Calculate Project Totals", use_container_width=True):
                with st.spinner("Processing calculations..."):
                    # Fire up the massive calculation engine we built at the top of the file
                    df, totals, clean_data = calculate_project_data(st.session_state.draft_components, db, user_mixes, factors_df)
                    
                    if df is not None:
                        st.session_state.project_results_df = df
                        st.session_state.project_totals = totals
                        st.session_state.project_clean_data = clean_data
                    else:
                        st.error("Please assign at least one material with an amount > 0.")
                    st.rerun()

            # IF THE CALCULATION WORKED, SHOW RESULTS
            if st.session_state.project_results_df is not None:
                st.markdown("---")
                
                # Draw the final table
                render_results_table_and_totals(st.session_state.project_results_df, st.session_state.project_totals)
                
                st.markdown('<span class="btn-green"></span>', unsafe_allow_html=True)
                if st.button("Save Project"):
                    if not st.session_state.draft_proj_name:
                        st.error("Please enter a Project Name at the top of the page to save.")
                    else:
                        projects_res = supabase.table("saved_projects").select("id, project_name").eq("user_id", st.session_state.user_id).execute()
                        local_user_projects = projects_res.data if projects_res.data else []
                        
                        existing_project = next((p for p in local_user_projects if p['project_name'] == st.session_state.draft_proj_name), None)
                        
                        if existing_project:
                            # Trigger Overwrite Workflow
                            st.session_state.confirm_overwrite_name = st.session_state.draft_proj_name
                            st.session_state.existing_proj_id = existing_project['id']
                            st.rerun()
                        else:
                            # Trigger Instant Save Workflow
                            st.session_state.execute_save = True
                            st.rerun()
                
                # OVERWRITE PROJECT WORKFLOW (Red Error box)
                if st.session_state.get("confirm_overwrite_name"):
                    st.error(f"A project named '{st.session_state.confirm_overwrite_name}' already exists. Do you want to overwrite it?")
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
                
                # EXECUTE DATABASE SAVE
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
                        
                        # Wipe memory clean after saving
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

    # ---------------------------------------------------------
    # TAB 3: MY LIBRARY (Saved Projects & Mixes)
    # ---------------------------------------------------------
    elif st.session_state.current_page == "My Library":
        
        tab_proj, tab_mix = st.tabs(["Saved Projects", "Saved Custom Mixes"])
        
        with tab_proj:
            # Download all their saved projects
            projects_res = supabase.table("saved_projects").select("*").eq("user_id", st.session_state.user_id).execute()
            user_projects = projects_res.data if projects_res.data else []
            
            if user_projects:
                proj_names = [p['project_name'] for p in user_projects]
                
                if "lib_selected_proj" not in st.session_state or st.session_state.lib_selected_proj not in proj_names:
                    st.session_state.lib_selected_proj = proj_names[0]
                    
                col_list, col_details = st.columns([1, 2.5])
                
                with col_list:
                    st.markdown("#### Project List")
                    # Draw a radio button list of their projects on the left
                    selected_proj = st.radio("Select Project", proj_names, label_visibility="collapsed", key="lib_proj_radio")
                    if selected_proj != st.session_state.lib_selected_proj:
                        st.session_state.lib_selected_proj = selected_proj
                        st.rerun()
                        
                with col_details:
                    # Draw the selected project's details on the right
                    p = next((proj for proj in user_projects if proj['project_name'] == st.session_state.lib_selected_proj), None)
                    if p:
                        st.markdown(f"### {p['project_name']}")
                        st.caption(f"Structure Template: {p['structure_type']} | Baseline GWP100: {p['total_embodied_carbon']:,.2f} kgCO2e")
                        
                        # Re-calculate the project to draw the table
                        draft_comps = []
                        raw_data = p.get("component_data", [])
                        if isinstance(raw_data, dict):
                            # Backwards compatibility for old saved files
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

                        df, totals, _ = calculate_project_data(draft_comps, db, user_mixes, factors_df)
                        
                        if df is not None:
                            render_results_table_and_totals(df, totals)
                        else:
                            st.info("No calculable materials found in this project.")
                        
                        st.markdown("---")
                        
                        proj_id = p.get('id', str(p.get('project_name')))
                        del_key = f"del_proj_confirm_{proj_id}"
                        
                        # DELETE WORKFLOW - Un-nested properly!
                        if st.session_state.get(del_key, False):
                            # The delete state is active, so hide the normal buttons and show the red warning!
                            st.error("Are you sure? This cannot be undone.")
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
                                    st.session_state[del_key] = False
                                    st.rerun()
                        else:
                            # Normal state, show Rename, Clone, and initial Delete button
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
                                st.button("Clone for Editing", key=f"load_proj_{proj_id}", on_click=load_project_to_session, args=(p, db))
                                    
                            with btn_col_b:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                if st.button("Delete Project", key=f"btn_del_init_proj_{proj_id}"):
                                    st.session_state[del_key] = True
                                    st.rerun()
            else:
                st.info("No projects saved under your account yet.")

        with tab_mix:
            if not user_mixes:
                st.info("No custom mixes found on your account. Create one in 'Materials & Mixes'!")
            else:
                mix_names = [m['mix_name'] for m in user_mixes]
                
                if "lib_selected_mix" not in st.session_state or st.session_state.lib_selected_mix not in mix_names:
                    st.session_state.lib_selected_mix = mix_names[0]
                    
                col_m_list, col_m_details = st.columns([1, 2.5])
                
                with col_m_list:
                    st.markdown("#### Material List")
                    selected_mix = st.radio("Select Mix", mix_names, label_visibility="collapsed", key="lib_mix_radio")
                    if selected_mix != st.session_state.lib_selected_mix:
                        st.session_state.lib_selected_mix = selected_mix
                        st.rerun()
                        
                with col_m_details:
                    m = next((mix for mix in user_mixes if mix['mix_name'] == st.session_state.lib_selected_mix), None)
                    if m:
                        st.markdown(f"### {m['mix_name']}")
                        st.caption(f"Assigned Category: {m['category']}")
                        
                        # Re-calculate to show the stats
                        c_mix_name = f"Custom: {m['mix_name']}"
                        props = calculate_mix_carbon(c_mix_name, db, user_mixes, factors_df)
                        
                        st.markdown("##### Performance Metrics")
                        m_col1, m_col2, m_col3 = st.columns(3)
                        m_col1.metric("Total Mass", f"{props['Mass (kg/m3)']:,.2f} kg/m³")
                        m_col2.metric("GWP100 Factor", f"{props['Factor_GWP (kgCO2e/kg)']:,.3f} kgCO2e/kg")
                        m_col3.metric("GWP100 Total", f"{props['Factor_GWP (kgCO2e/kg)'] * props['Mass (kg/m3)']:,.2f} kgCO2e/m³")
                        
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
                                st.markdown("**By GWP100**")
                                chart_data_carbon = pd.DataFrame({"Component": list(chart_components_carbon.keys()), "Carbon": list(chart_components_carbon.values())})
                                pie_carbon = alt.Chart(chart_data_carbon).mark_arc(innerRadius=40).encode(
                                    theta=alt.Theta(field="Carbon", type="quantitative"),
                                    color=alt.Color(field="Component", type="nominal", legend=alt.Legend(title="Material", orient="bottom")),
                                    tooltip=["Component", "Carbon"]
                                ).properties(height=280)
                                st.altair_chart(pie_carbon, use_container_width=True)
                        
                        st.markdown("##### Ingredient Recipe")
                        if recipe_data:
                            st.dataframe(pd.DataFrame(recipe_data), use_container_width=True, hide_index=True)
                        
                        st.markdown("---")
                        
                        del_m_key = f"del_mix_confirm_{m['id']}"
                        
                        # DELETE MIX WORKFLOW - Un-nested!
                        if st.session_state.get(del_m_key, False):
                            st.error("Are you sure? This cannot be undone.")
                            y_m_col, n_m_col = st.columns(2)
                            with y_m_col:
                                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                if st.button("Yes, Delete", key=f"btn_del_yes_mix_{m['id']}"):
                                    supabase.table("user_mixes").delete().eq("id", m['id']).execute()
                                    st.session_state[del_m_key] = False
                                    st.success("Mix deleted.")
                                    time.sleep(1)
                                    st.rerun()
                            with n_m_col:
                                if st.button("Cancel", key=f"btn_del_no_mix_{m['id']}"):
                                    st.session_state[del_m_key] = False
                                    st.rerun()
                        else:
                            # Normal state for mix management
                            col_rn, col_dup, col_del = st.columns([1.5, 1, 1])
                            with col_rn:
                                new_m_name = st.text_input("Rename Mix:", value=m['mix_name'], key=f"rn_in_{m['id']}")
                                st.markdown('<span class="btn-blue"></span>', unsafe_allow_html=True)
                                if st.button("Update Name", key=f"rn_btn_{m['id']}"):
                                    try:
                                        supabase.table("user_mixes").update({"mix_name": new_m_name}).eq("id", m['id']).execute()
                                        st.success("Mix renamed successfully!")
                                        time.sleep(1)
                                        st.rerun()
                                    except Exception as e:
                                        st.error("Failed to rename. Ensure you have the Supabase UPDATE policy enabled.")
                            
                            with col_dup:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.markdown('<span class="btn-grey"></span>', unsafe_allow_html=True)
                                st.button("Clone for Editing", key=f"dup_m_{m['id']}", on_click=load_mix_to_session, args=(m,))

                            with col_del:
                                st.markdown("<br>", unsafe_allow_html=True)
                                st.markdown('<span class="btn-red"></span>', unsafe_allow_html=True)
                                if st.button("Delete Mix", key=f"btn_del_init_mix_{m['id']}"):
                                    st.session_state[del_m_key] = True
                                    st.rerun()

# If they are not logged in, show the login page
if st.session_state.user_id is None:
    login_page()
# If they are logged in, run the main app
else:
    main_application()

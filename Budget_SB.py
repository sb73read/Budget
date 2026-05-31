import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from streamlit_oauth import OAuth2Component
import gspread
from google.oauth2.service_account import Credentials
import base64
import json

# --- APP CONFIGURATION ---
st.set_page_config(page_title="Personal Budget Tracker", layout="wide")
st.title("💰 Personal Budget & Expense Tracker")

# --- CUSTOM COLOR MAP FOR CATEGORIES ---
CATEGORY_COLORS = {
    "Grocery": "#3498db", "OTT Bills": "#9b59b6", "Mobile Bills": "#8e44ad", 
    "Rent and Utilities": "#e67e22", "Movies and Concerts": "#95a5a6",
    "Charity and Gift": "#e74c3c", "For House": "#1abc9c", "Travel to Work": "#f1c40f", 
    "Eat Out": "#d35400", "Others": "#7f8c8d",
    # Investment Vehicles
    "Deposit": "#16a085", "Gold": "#f39c12", "Mutual Funds": "#27ae60", 
    "Stock": "#2980b9", "Forex": "#d35400", "Insurance": "#c0392b",
    # Trip & Vacation Categories
    "Food": "#e74c3c", "Accommodation": "#2c3e50", "Travel": "#2980b9",
    "Activities": "#2ecc71", "Shopping": "#f1c40f"
}

# --- GOOGLE OAUTH CONFIGURATION ---
CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

if "auth" not in st.session_state:
    st.session_state.auth = None

oauth2 = OAuth2Component(CLIENT_ID, CLIENT_SECRET, AUTHORIZE_URL, TOKEN_URL, TOKEN_URL, REVOKE_URL)

if st.session_state.auth is None:
    st.subheader("🔒 Secure Access Required")
    st.write("Please sign in with your Google Account to access your budget & savings tracker.")
    result = oauth2.authorize_button(
        name="Sign in with Google",
        icon="https://upload.wikimedia.org/wikipedia/commons/5/53/Google_%22G%22_Logo.svg",
        redirect_uri=st.secrets.get("REDIRECT_URI", "https://budget-sb.streamlit.app/"),
        scope="openid email profile", key="google_auth"
    )
    if result and "token" in result:
        st.session_state.auth = result
        st.rerun()
else:
    # --- IDENTITY CAPTURE ---
    try:
        id_token = st.session_state.auth["token"]["id_token"]
        payload = id_token.split(".")[1]
        padded_payload = payload + "=" * (4 - len(payload) % 4)
        user_name = json.loads(base64.b64decode(padded_payload)).get("email", "Authenticated User")
    except Exception:
        user_name = "Authenticated User"
    
    st.sidebar.success(f"👋 Logged in as: {user_name}")
    if st.sidebar.button("Log Out"):
        st.session_state.auth = None
        st.rerun()

    # --- CONNECT TO GOOGLE DRIVE ---
    @st.cache_resource(ttl="0d")
    def get_google_client():
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        fixed_key = st.secrets["GSHEETS_PRIVATE_KEY"].replace(r'\\n', '\n').replace(r'\n', '\n')
        creds_dict = {
            "type": "service_account", "project_id": st.secrets["GSHEETS_PROJECT_ID"],
            "private_key_id": st.secrets["GSHEETS_PRIVATE_KEY_ID"], "private_key": fixed_key,  
            "client_email": st.secrets["GSHEETS_CLIENT_EMAIL"], "client_id": st.secrets["GSHEETS_CLIENT_ID"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['GSHEETS_CLIENT_EMAIL']}"
        }
        return gspread.authorize(Credentials.from_service_account_info(creds_dict, scopes=scopes))

    expected_headers = ["Date", "Type", "Category", "Place/Shop", "Amount", "User"]
    
    try:
        gc = get_google_client()
        sh = gc.open_by_url(st.secrets["GSHEETS_SPREADSHEET"])
        
        sheet_names = [sheet.title for sheet in sh.worksheets()]
        if "savings" not in sheet_names:
            sb_ws = sh.add_worksheet(title="savings", rows=500, cols=10)
            sb_ws.append_row(expected_headers)
            sheet_names.append("savings")
            
        monthly_tabs = [name for name in sheet_names if name != "savings"]
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("📅 Select Month View")
        target_month_sheet = st.sidebar.selectbox("Active Ledger Tab", monthly_tabs if monthly_tabs else ["None"])
        
        if target_month_sheet != "None":
            raw_budget_rows = sh.worksheet(target_month_sheet).get_all_values()
            existing_data = pd.DataFrame(raw_budget_rows[1:], columns=raw_budget_rows[0]) if raw_budget_rows else pd.DataFrame(columns=expected_headers)
        else:
            existing_data = pd.DataFrame(columns=expected_headers)
            
        raw_savings_rows = sh.worksheet("savings").get_all_values()
        savings_data = pd.DataFrame(raw_savings_rows[1:], columns=raw_savings_rows[0]) if raw_savings_rows else pd.DataFrame(columns=expected_headers)
            
    except Exception as e:
        st.error(f"❌ Core File Synchronization Failure: {e}")
        existing_data = pd.DataFrame(columns=expected_headers)
        savings_data = pd.DataFrame(columns=expected_headers)

    EXPENSE_CATEGORIES = ["Grocery", "OTT Bills", "Mobile Bills", "Rent and Utilities", "Movies and Concerts", "Charity and Gift", "For House", "Travel to Work", "Eat Out", "Others"]
    INCOME_CATEGORIES = ["Salary", "Interest", "Investment", "Freelance/Side Hustle", "Others"]
    INVESTMENT_CATEGORIES = ["Deposit", "Gold", "Mutual Funds", "Stock", "Forex", "Insurance"]
    TRIP_CATEGORIES = ["Food", "Accommodation", "Travel", "Activities", "Shopping"]

    tab1, tab2, tab3 = st.tabs(["📝 Log Workspace", "📊 Dashboard & Analytics", "📋 Ledger Archives"])

    # --- TAB 1: WORKSPACE FOR ENTRY CORES ---
    with tab1:
        # GUI BLOCK 1: STANDARD CASH FLOW
        st.subheader("💳 Log Income / Expense")
        with st.container(border=True):
            transaction_type = st.radio("Transaction Type", ["Expense", "Income"], horizontal=True, key="budget_type_rad")
            col1, col2 = st.columns(2)
            with col1:
                b_date = st.date_input("Date", datetime.now(), key="b_date_in")
                b_category = st.selectbox("Category", EXPENSE_CATEGORIES if transaction_type == "Expense" else INCOME_CATEGORIES, key="b_cat_in")
            with col2:
                b_place = st.text_input("Place / Shop / Description", placeholder="e.g., Tesco, Office", key="b_place_in")
                b_amount = st.number_input("Amount (£)", min_value=0.0, step=0.01, format="%.2f", key="b_amt_in")
            
            if st.button("Submit Budget Entry", type="primary", key="b_btn"):
                if b_amount > 0:
                    c_sheet_name = b_date.strftime("%Y-%m")
                    new_row = [b_date.strftime("%Y-%m-%d"), transaction_type, b_category, b_place, float(b_amount), user_name]
                    try:
                        if c_sheet_name not in [s.title for s in sh.worksheets()]:
                            sh.add_worksheet(title=c_sheet_name, rows=100, cols=10).append_row(expected_headers)
                        sh.worksheet(c_sheet_name).append_row(new_row)
                        st.success(f"Budget item appended directly to tab: '{c_sheet_name}'")
                        
                        # 🔄 CHANGE THIS LINE HERE:
                        st.cache_resource.clear() 
                        st.rerun()
                    except Exception as e: st.error(f"Error: {e}")

        st.markdown("<br>", unsafe_allow_html=True)

        # TOGGLE BLOCKS FOR WORK TRIPS & VACATIONS
        trip_col, vac_col = st.columns(2)
        
        with trip_col:
            show_work_trip = st.toggle("👔 Enable Work Trip Tracker", value=False)
        with vac_col:
            show_vacation = st.toggle("✈️ Enable Vacation Tracker", value=False)

        # GUI BLOCK 2: WORK TRIPS (CONDITIONAL)
        if show_work_trip:
            st.subheader("👔 Log Work Trip Expense")
            with st.container(border=True):
                col1_t, col2_t = st.columns(2)
                with col1_t:
                    t_date = st.date_input("Trip Date", datetime.now(), key="t_date_in")
                    t_category = st.selectbox("Trip Category", TRIP_CATEGORIES, key="t_cat_in")
                with col2_t:
                    t_title = st.text_input("Trip / Client Reference", placeholder="e.g., London Conference", key="t_title_in")
                    t_amount = st.number_input("Amount (£)", min_value=0.0, step=0.01, format="%.2f", key="t_amt_in")
                
                if st.button("Submit Work Trip Cost", type="secondary", key="t_btn"):
                    if t_amount > 0:
                        c_sheet_name = t_date.strftime("%Y-%m")
                        new_row = [t_date.strftime("%Y-%m-%d"), "Work Trip", t_category, t_title, float(t_amount), user_name]
                        try:
                            if c_sheet_name not in [s.title for s in sh.worksheets()]:
                                sh.add_worksheet(title=c_sheet_name, rows=100, cols=10).append_row(expected_headers)
                            sh.worksheet(c_sheet_name).append_row(new_row)
                            st.success(f"Work Trip cost recorded to: '{c_sheet_name}'")
                            
                            # 🔄 CHANGE THIS LINE HERE:
                            st.cache_resource.clear()
                            st.rerun()
                        except Exception as e: st.error(f"Error: {e}")

        # GUI BLOCK 3: VACATIONS (CONDITIONAL)
        if show_vacation:
            st.subheader("✈️ Log Vacation Expense")
            with st.container(border=True):
                col1_v, col2_v = st.columns(2)
                with col1_v:
                    v_date = st.date_input("Vacation Date", datetime.now(), key="v_date_in")
                    v_category = st.selectbox("Vacation Category", TRIP_CATEGORIES, key="v_cat_in")
                with col2_v:
                    v_dest = st.text_input("Destination / Trip Name", placeholder="e.g., Weekend in Paris", key="v_dest_in")
                    v_amount = st.number_input("Amount (£)", min_value=0.0, step=0.01, format="%.2f", key="v_amt_in")
                
                if st.button("Submit Vacation Cost", type="secondary", key="v_btn"):
                    if v_amount > 0:
                        c_sheet_name = v_date.strftime("%Y-%m")
                        new_row = [v_date.strftime("%Y-%m-%d"), "Vacation", v_category, v_dest, float(v_amount), user_name]
                        try:
                            if c_sheet_name not in [s.title for s in sh.worksheets()]:
                                sh.add_worksheet(title=c_sheet_name, rows=100, cols=10).append_row(expected_headers)
                            sh.worksheet(c_sheet_name).append_row(new_row)
                            st.success(f"Vacation expense recorded to: '{c_sheet_name}'")
                            
                            # 🔄 CHANGE THIS LINE HERE:
                            st.cache_resource.clear()
                            st.rerun()
                        except Exception as e: st.error(f"Error: {e}")

        st.markdown("<br>", unsafe_allow_html=True)

        # GUI BLOCK 4: SAVINGS & INVESTMENTS
        st.subheader("📈 Log Savings & Investment Allocation")
        with st.container(border=True):
            col1_inv, col2_inv = st.columns(2)
            with col1_inv:
                inv_date = st.date_input("Investment Date", datetime.now(), key="inv_date_in")
                inv_category = st.selectbox("Asset Class / Vehicle", INVESTMENT_CATEGORIES, key="inv_cat_in")
            with col2_inv:
                inv_platform = st.text_input("Brokerage / Platform", placeholder="e.g., Trading212, Vanguard", key="inv_plat_in")
                inv_amount = st.number_input("Invested Principal (£)", min_value=0.0, step=0.01, format="%.2f", key="inv_amt_in")
                
            if st.button("Submit Investment Asset", type="secondary", key="inv_btn"):
                if inv_amount > 0:
                    new_inv_row = [inv_date.strftime("%Y-%m-%d"), "Investment", inv_category, inv_platform, float(inv_amount), user_name]
                    try:
                        sh.worksheet("savings").append_row(new_inv_row)
                        st.success("Asset logged securely inside 'savings' worksheet!")
                        
                        # 🔄 CHANGE THIS LINE HERE:
                        st.cache_resource.clear()
                        st.rerun()
                    except Exception as e: st.error(f"Failed: {e}")

    # --- TAB 2: ANALYTICS CHANNELS ---
    with tab2:
        st.header(f"Financial Analytics — Month view: {target_month_sheet}")
        
        if not existing_data.empty:
            existing_data["Amount"] = pd.to_numeric(existing_data["Amount"], errors='coerce').fillna(0.0)
            t_income = existing_data[existing_data["Type"] == "Income"]["Amount"].sum()
            t_expense = existing_data[existing_data["Type"] == "Expense"]["Amount"].sum()
            t_work_trip = existing_data[existing_data["Type"] == "Work Trip"]["Amount"].sum()
            t_vacation = existing_data[existing_data["Type"] == "Vacation"]["Amount"].sum()
        else:
            t_income, t_expense, t_work_trip, t_vacation = 0.0, 0.0, 0.0, 0.0
            
        if not savings_data.empty:
            savings_data

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
    "Vacation": "#2ecc71", "Rent and Utilities": "#e67e22", "Movies and Concerts": "#95a5a6",
    "Charity and Gift": "#e74c3c", "For House": "#1abc9c", "Travel to Work": "#f1c40f", 
    "Eat Out": "#d35400", "Others": "#7f8c8d",
    # Investment Vehicles
    "Deposit": "#16a085", "Gold": "#f39c12", "Mutual Funds": "#27ae60", 
    "Stock": "#2980b9", "Forex": "#d35400", "Insurance": "#c0392b"
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
        
        # --- INITIALIZE PERMANENT SAVINGS TAB ---
        sheet_names = [sheet.title for sheet in sh.worksheets()]
        if "savings" not in sheet_names:
            sb_ws = sh.add_worksheet(title="savings", rows=500, cols=10)
            sb_ws.append_row(expected_headers)
            sheet_names.append("savings")
            
        # --- SIDEBAR NAV FILTERING OUT 'SAVINGS' FROM DYNAMIC MONTHLY VIEWS ---
        monthly_tabs = [name for name in sheet_names if name != "savings"]
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("📅 Select Month View")
        target_month_sheet = st.sidebar.selectbox("Active Ledger Tab", monthly_tabs if monthly_tabs else ["None"])
        
        # Pull Monthly Budget Tab Data
        if target_month_sheet != "None":
            raw_budget_rows = sh.worksheet(target_month_sheet).get_all_values()
            existing_data = pd.DataFrame(raw_budget_rows[1:], columns=raw_budget_rows[0]) if raw_budget_rows else pd.DataFrame(columns=expected_headers)
        else:
            existing_data = pd.DataFrame(columns=expected_headers)
            
        # Pull Permanent Savings Sheet Data
        raw_savings_rows = sh.worksheet("savings").get_all_values()
        savings_data = pd.DataFrame(raw_savings_rows[1:], columns=raw_savings_rows[0]) if raw_savings_rows else pd.DataFrame(columns=expected_headers)
            
    except Exception as e:
        st.error(f"❌ Core File Synchronization Failure: {e}")
        existing_data = pd.DataFrame(columns=expected_headers)
        savings_data = pd.DataFrame(columns=expected_headers)

    EXPENSE_CATEGORIES = ["Grocery", "OTT Bills", "Mobile Bills", "Vacation", "Rent and Utilities", "Movies and Concerts", "Charity and Gift", "For House", "Travel to Work", "Eat Out", "Others"]
    INCOME_CATEGORIES = ["Salary", "Interest", "Investment", "Freelance/Side Hustle", "Others"]
    INVESTMENT_CATEGORIES = ["Deposit", "Gold", "Mutual Funds", "Stock", "Forex", "Insurance"]

    tab1, tab2, tab3 = st.tabs(["📝 Log Workspace", "📊 Dashboard & Analytics", "📋 Ledger Archives"])

    # --- TAB 1: SEPARATE GUI BLOCKS ---
    with tab1:
        # GUI BLOCK 1: INCOME & EXPENSE BUDGETING
        st.subheader("💳 Log Income / Expense")
        with st.container(border=True):
            transaction_type = st.radio("Transaction Type", ["Expense", "Income"], horizontal=True, key="budget_type_rad")
            col1, col2 = st.columns(2)
            with col1:
                b_date = st.date_input("Date", datetime.now(), key="b_date_in")
                b_category = st.selectbox("Category", EXPENSE_CATEGORIES if transaction_type == "Expense" else INCOME_CATEGORIES, key="b_cat_in")
            with col2:
                b_place = st.text_input("Place / Shop / Description", placeholder="e.g., Target, Office", key="b_place_in")
                b_amount = st.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f", key="b_amt_in")
            
            if st.button("Submit Budget Entry", type="primary", key="b_btn"):
                if b_amount > 0:
                    c_sheet_name = b_date.strftime("%Y-%m")
                    new_row = [b_date.strftime("%Y-%m-%d"), transaction_type, b_category, b_place, float(b_amount), user_name]
                    try:
                        if c_sheet_name not in [s.title for s in sh.worksheets()]:
                            sh.add_worksheet(title=c_sheet_name, rows=100, cols=10).append_row(expected_headers)
                        sh.worksheet(c_sheet_name).append_row(new_row)
                        st.success(f"Budget item appended directly to tab: '{c_sheet_name}'")
                        st.clear_cache(); st.rerun()
                    except Exception as e: st.error(f"Error: {e}")

        st.markdown("<br>", unsafe_allow_html=True)

        # GUI BLOCK 2: SAVINGS & INVESTMENTS
        st.subheader("📈 Log Savings & Investment Allocation")
        with st.container(border=True):
            col1_inv, col2_inv = st.columns(2)
            with col1_inv:
                inv_date = st.date_input("Investment Date", datetime.now(), key="inv_date_in")
                inv_category = st.selectbox("Asset Class / Vehicle", INVESTMENT_CATEGORIES, key="inv_cat_in")
            with col2_inv:
                inv_platform = st.text_input("Brokerage / Platform / Location", placeholder="e.g., Robinhood, Charles Schwab", key="inv_plat_in")
                inv_amount = st.number_input("Invested Principal ($)", min_value=0.0, step=0.01, format="%.2f", key="inv_amt_in")
                
            if st.button("Submit Investment Asset", type="secondary", key="inv_btn"):
                if inv_amount > 0:
                    # Enforces typing to "Investment" and routes directly to the isolated "savings" sheet
                    new_inv_row = [inv_date.strftime("%Y-%m-%d"), "Investment", inv_category, inv_platform, float(inv_amount), user_name]
                    try:
                        sh.worksheet("savings").append_row(new_inv_row)
                        st.success("Asset logged securely inside the centralized 'savings' worksheet!")
                        st.clear_cache(); st.rerun()
                    except Exception as e: st.error(f"Failed routing asset parameters: {e}")

    # --- TAB 2: DETACHED PORTFOLIO GRAPHING ---
    with tab2:
        st.header(f"Financial Analytics — Month view: {target_month_sheet}")
        
        # Cash Flow Calculations
        if not existing_data.empty:
            existing_data["Amount"] = pd.to_numeric(existing_data["Amount"], errors='coerce').fillna(0.0)
            t_income = existing_data[existing_data["Type"] == "Income"]["Amount"].sum()
            t_expense = existing_data[existing_data["Type"] == "Expense"]["Amount"].sum()
        else:
            t_income, t_expense = 0.0, 0.0
            
        if not savings_data.empty:
            savings_data["Amount"] = pd.to_numeric(savings_data["Amount"], errors='coerce').fillna(0.0)
            t_investment = savings_data["Amount"].sum()
        else:
            t_investment = 0.0

        card1, card2, card3, card4 = st.columns(4)
        card1.metric("Selected Month Income", f"${t_income:,.2f}")
        card2.metric("Selected Month Expenses", f"${t_expense:,.2f}")
        card3.metric("Lifetime Invested Wealth", f"${t_investment:,.2f}")
        card4.metric("Month Cash Balance", f"${t_income - t_expense:,.2f}")
        
        st.markdown("---")
        
        # Budget Visualization Plots
        if not existing_data.empty:
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.subheader("Monthly Expense Volume Allocation")
                exp_df = existing_data[existing_data["Type"] == "Expense"]
                if not exp_df.empty:
                    st.plotly_chart(px.pie(exp_df, values="Amount", names="Category", hole=0.4, color="Category", color_discrete_map=CATEGORY_COLORS), use_container_width=True)
            with chart_col2:
                st.subheader("Monthly Income vs Expense Spread")
                st.plotly_chart(px.bar(existing_data, x="Date", y="Amount", color="Type", barmode="group", color_discrete_map={"Income": "#2ecc71", "Expense": "#e74c3c"}), use_container_width=True)

        # --- SEPARATE GUI DASHBOARD BLOCK FOR INVESTMENT INSIGHTS ---
        st.markdown("---")
        st.subheader("💼 Lifetime Centralized Savings & Investment Portfolio")
        if savings_data.empty:
            st.info("Your centralized 'savings' sheet is empty. Log assets in Tab 1 to populate portfolio tracking dashboards.")
        else:
            # Generate total matrix row for requested classes
            inv_sums = savings_data.groupby("Category")["Amount"].sum().reset_index()
            cols_inv = st.columns(len(INVESTMENT_CATEGORIES))
            for idx, asset in enumerate(INVESTMENT_CATEGORIES):
                asset_sum = inv_sums[inv_sums["Category"] == asset]["Amount"].sum()
                with cols_inv[idx]:
                    st.metric(label=f"💰 Total {asset}", value=f"${asset_sum:,.2f}")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Lifetime Asset Mix Pie Chart
            col_graph_inv1, col_graph_inv2 = st.columns([1, 1])
            with col_graph_inv1:
                st.subheader("Asset Distribution Summary")
                st.plotly_chart(px.pie(savings_data, values="Amount", names="Category", hole=0.4, color="Category", color_discrete_map=CATEGORY_COLORS), use_container_width=True)
            with col_graph_inv2:
                st.subheader("Growth Chronology Trend")
                st.plotly_chart(px.bar(savings_data.sort_values(by="Date"), x="Date", y="Amount", color="Category", title="Cumulative Growth Inflow Timeline", color_discrete_map=CATEGORY_COLORS), use_container_width=True)

    # --- TAB 3: DUAL ARCHIVES VIEW ---
    with tab3:
        ledger_sel = st.radio("Choose Ledger Workspace to View", ["Dynamic Budget Sheet", "Centralized Savings Sheet"], horizontal=True)
        if ledger_sel == "Dynamic Budget Sheet":
            st.subheader(f"📋 Cash Flow Archives — Sheet View: {target_month_sheet}")
            if not existing_data.empty: st.dataframe(existing_data.sort_values(by="Date", ascending=False), use_container_width=True)
            else: st.write("No transaction data inside this month container.")
        else:
            st.subheader("📋 Centralized Vault Archive — Sheet View: savings")
            if not savings_data.empty: st.dataframe(savings_data.sort_values(by="Date", ascending=False), use_container_width=True)
            else: st.write("Centralized vault contains no parameters yet.")

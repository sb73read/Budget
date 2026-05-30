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
    "Grocery": "#3498db",           # Blue
    "OTT Bills": "#9b59b6",          # Purple
    "Mobile Bills": "#8e44ad",       # Dark Purple
    "Vacation": "#2ecc71",           # Green
    "Rent and Utilities": "#e67e22", # Orange
    "Movies and Concerts": "#95a5a6",# Gray
    "Charity and Gift": "#e74c3c",   # Red
    "For House": "#1abc9c",          # Teal
    "Travel to Work": "#f1c40f",      # Yellow
    "Eat Out": "#d35400",            # Dark Orange
    "Others": "#7f8c8d"              # Slate Gray
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

# --- CHECK AUTHENTICATION ---
if st.session_state.auth is None:
    st.subheader("🔒 Secure Access Required")
    st.write("Please sign in with your Google Account to access and manage your secure budget ledger.")
    
    result = oauth2.authorize_button(
        name="Sign in with Google",
        icon="https://upload.wikimedia.org/wikipedia/commons/5/53/Google_%22G%22_Logo.svg",
        redirect_uri=st.secrets.get("REDIRECT_URI", "https://budget-sb.streamlit.app/"),
        scope="openid email profile",
        key="google_auth"
    )
    if result and "token" in result:
        st.session_state.auth = result
        st.rerun()

else:
    # --- FIXED: EXTRACT ACTUAL GOOGLE USER IDENTITY ---
    try:
        id_token = st.session_state.auth["token"]["id_token"]
        payload = id_token.split(".")[1]
        padded_payload = payload + "=" * (4 - len(payload) % 4)
        decoded_bytes = base64.b64decode(padded_payload)
        user_data = json.loads(decoded_bytes)
        user_name = user_data.get("email", "Authenticated User")
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
        raw_key = st.secrets["GSHEETS_PRIVATE_KEY"]
        fixed_key = raw_key.replace(r'\\n', '\n').replace(r'\n', '\n')
        creds_dict = {
            "type": "service_account",
            "project_id": st.secrets["GSHEETS_PROJECT_ID"],
            "private_key_id": st.secrets["GSHEETS_PRIVATE_KEY_ID"],
            "private_key": fixed_key,  
            "client_email": st.secrets["GSHEETS_CLIENT_EMAIL"],
            "client_id": st.secrets["GSHEETS_CLIENT_ID"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['GSHEETS_CLIENT_EMAIL']}"
        }
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)

    # Global structural properties
    expected_headers = ["Date", "Type", "Category", "Place/Shop", "Amount", "User"]
    spreadsheet_link = st.secrets["GSHEETS_SPREADSHEET"]
    
    # Dynamic Navigation Control for Subsheets
    try:
        gc = get_google_client()
        sh = gc.open_by_url(spreadsheet_link)
        
        # Pull list of worksheet tab names
        all_worksheets = sh.worksheets()
        sheet_names = [sheet.title for sheet in all_worksheets]
        
        # Build month selector widget in sidebar
        st.sidebar.markdown("---")
        st.sidebar.subheader("📅 Select Month View")
        target_month_sheet = st.sidebar.selectbox("Active Ledger Tab", sheet_names)
        
        # Extract target tab values
        active_worksheet = sh.worksheet(target_month_sheet)
        raw_rows = active_worksheet.get_all_values()
        
        if not raw_rows:
            active_worksheet.append_row(expected_headers)
            existing_data = pd.DataFrame(columns=expected_headers)
        else:
            existing_data = pd.DataFrame(raw_rows[1:], columns=raw_rows[0])
            
    except Exception as e:
        st.error(f"❌ Core File Synchronization Failure: {e}")
        existing_data = pd.DataFrame(columns=expected_headers)

    # --- EXPENSE & INCOME LISTS ---
    EXPENSE_CATEGORIES = list(CATEGORY_COLORS.keys())
    INCOME_CATEGORIES = ["Salary", "Interest", "Investment", "Freelance/Side Hustle", "Others"]

    tab1, tab2, tab3 = st.tabs(["📝 Log Transaction", "📊 Dashboard & Analytics", "📋 View Records"])

    # --- TAB 1: INPUT DATA ---
    with tab1:
        st.header("Add New Entry")
        transaction_type = st.radio("Transaction Type", ["Expense", "Income"], horizontal=True)
        
        col1, col2 = st.columns(2)
        with col1:
            date = st.date_input("Date", datetime.now())
            if transaction_type == "Expense":
                category = st.selectbox("Category of Expense", EXPENSE_CATEGORIES)
            else:
                category = st.selectbox("Source of Income", INCOME_CATEGORIES)
                
        with col2:
            place = st.text_input("Place / Shop / Source Description", placeholder="e.g., Walmart")
            amount = st.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f")

        if st.button("Submit Entry", type="primary"):
            # Automatically calculate destination worksheet name based on user transaction date (e.g., "2026-05")
            computed_sheet_name = date.strftime("%Y-%m")
            
            new_row_data = [date.strftime("%Y-%m-%d"), transaction_type, category, place, float(amount), user_name]
            
            try:
                # Self-healing monthly tab generator
                if computed_sheet_name not in sheet_names:
                    new_ws = sh.add_worksheet(title=computed_sheet_name, rows=100, cols=10)
                    new_ws.append_row(expected_headers)
                    destination_ws = new_ws
                else:
                    destination_ws = sh.worksheet(computed_sheet_name)
                
                destination_ws.append_row(new_row_data)
                st.success(f"Success! Appended data directly to monthly tab sheet: '{computed_sheet_name}'")
                st.clear_cache()
                st.rerun()
            except Exception as e:
                st.error(f"Failed to record data element to spreadsheet: {e}")

    # --- TAB 2: METRICS & MONTH-OVER-MONTH ANALYTICS ---
    with tab2:
        st.header(f"Financial Analytics — View: {target_month_sheet}")
        
        if existing_data.empty or len(existing_data) < 1:
            st.info("No transaction records populated in this specific monthly tab variant yet.")
        else:
            existing_data["Amount"] = pd.to_numeric(existing_data["Amount"], errors='coerce').fillna(0.0)
            
            total_income = existing_data[existing_data["Type"] == "Income"]["Amount"].sum()
            total_expense = existing_data[existing_data["Type"] == "Expense"]["Amount"].sum()
            net_savings = total_income - total_expense
            
            card1, card2, card3 = st.columns(3)
            card1.metric("Total Income", f"${total_income:,.2f}")
            card2.metric("Total Expenses", f"${total_expense:,.2f}", delta=f"-${total_expense:,.2f}", delta_color="inverse")
            card3.metric("Net Savings", f"${net_savings:,.2f}")
            
            st.markdown("---")
            
            # Category Sum Displays
            expense_df = existing_data[existing_data["Type"] == "Expense"]
            if not expense_df.empty:
                st.subheader("📊 Individual Expense Metrics Summary")
                category_sums = expense_df.groupby("Category")["Amount"].sum().reset_index()
                cols = st.columns(4)
                for index, row in category_sums.iterrows():
                    with cols[index % 4]:
                        st.metric(label=row["Category"], value=f"${row['Amount']:,.2f}")
                st.markdown("---")
            
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.subheader("Expense Volume Allocation")
                if not expense_df.empty:
                    fig_pie = px.pie(
                        expense_df, values="Amount", names="Category", hole=0.4,
                        color="Category", color_discrete_map=CATEGORY_COLORS
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)
                else:
                    st.write("No active monthly expenses.")
                    
            with chart_col2:
                st.subheader("Cash Flow Profile Breakdown")
                fig_bar = px.bar(existing_data, x="Date", y="Amount", color="User", barmode="group")
                st.plotly_chart(fig_bar, use_container_width=True)

            # --- NEW ADDITION: MONTH-OVER-MONTH CROSS ANALYSIS ---
            st.markdown("---")
            st.subheader("📈 Multi-Month Comparative Analysis")
            
            # Fetch all rows from all tabs dynamically to build a historical trend graph
            all_historical_data = []
            for name in sheet_names:
                try:
                    tab_rows = sh.worksheet(name).get_all_values()
                    if len(tab_rows) > 1:
                        tab_df = pd.DataFrame(tab_rows[1:], columns=tab_rows[0])
                        tab_df["Month_Source"] = name  # Record historical label origin
                        all_historical_data.append(tab_df)
                except Exception:
                    pass
            
            if all_historical_data:
                full_historical_df = pd.concat(all_historical_data, ignore_index=True)
                full_historical_df["Amount"] = pd.to_numeric(full_historical_df["Amount"], errors='coerce').fillna(0.0)
                hist_expense_df = full_historical_df[full_historical_df["Type"] == "Expense"]
                
                if not hist_expense_df.empty:
                    # Group data elements by month tab index source and cross categories
                    comparison_df = hist_expense_df.groupby(["Month_Source", "Category"])["Amount"].sum().reset_index()
                    
                    fig_trend = px.bar(
                        comparison_df, 
                        x="Month_Source", 
                        y="Amount", 
                        color="Category",
                        title="Month-over-Month Category Trend Spends Comparison",
                        barmode="group",
                        color_discrete_map=CATEGORY_COLORS
                    )
                    st.plotly_chart(fig_trend, use_container_width=True)
                else:
                    st.write("Add expense data across multiple tabs to generate historical trends.")

    # --- TAB 3: DATA LEDGER ---
    with tab3:
        st.header(f"📋 Records for Sheet: {target_month_sheet}")
        if not existing_data.empty:
            st.dataframe(existing_data.sort_values(by="Date", ascending=False), use_container_width=True)
        else:
            st.write("No entries detected in this sheet view tab.")

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from streamlit_oauth import OAuth2Component
import gspread
from google.oauth2.service_account import Credentials

# --- APP CONFIGURATION ---
st.set_page_config(page_title="Personal Budget Tracker", layout="wide")
st.title("💰 Personal Budget & Expense Tracker")

# --- CUSTOM COLOR MAP FOR CATEGORIES ---
# This ensures each category keeps a beautiful, distinct color across all charts
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
    # --- USER PROFILE RECOGNITION ---
    # Decoding the token payload to automatically fetch the user's real name
    user_info = st.session_state.auth.get("id_token", {})
    # Fallback to email or "Unknown User" if profile name mapping is restricted
    user_name = st.session_state.auth.get("token", {}).get("email", "Default User")
    
    st.sidebar.success(f"👋 Welcome, {user_name}!")
    if st.sidebar.button("Log Out"):
        st.session_state.auth = None
        st.rerun()

    # --- CONNECT TO GOOGLE SHEETS ---
    @st.cache_resource(ttl="0d")
    def get_google_sheet():
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        fixed_key = st.secrets["GSHEETS_PRIVATE_KEY"].replace(r'\\n', '\n').replace(r'\n', '\n')

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
        client = gspread.authorize(creds)
        sheet = client.open_by_url(st.secrets["GSHEETS_SPREADSHEET"])
        return sheet.get_worksheet(0)

    worksheet = None
    # Updated default tracking DataFrame with a dedicated 'User' tracking column
    expected_headers = ["Date", "Type", "Category", "Place/Shop", "Amount", "User"]
    existing_data = pd.DataFrame(columns=expected_headers)

    try:
        worksheet = get_google_sheet()
        raw_rows = worksheet.get_all_values()
        
        if not raw_rows or len(raw_rows) <= 1:
            if not raw_rows:
                worksheet.append_row(expected_headers)
            existing_data = pd.DataFrame(columns=expected_headers)
        else:
            # Rebuild dataframe checking that old versions without the 'User' column don't crash
            headers = raw_rows[0]
            existing_data = pd.DataFrame(raw_rows[1:], columns=headers)
            if "User" not in existing_data.columns:
                existing_data["User"] = "Legacy Entry"
    except Exception as e:
        st.error(f"❌ Actual API Error Caught: {str(e)}")

    # --- CATEGORY LISTS ---
    EXPENSE_CATEGORIES = list(CATEGORY_COLORS.keys())
    INCOME_CATEGORIES = ["Salary", "Interest", "Investment", "Freelance/Side Hustle", "Others"]

    # --- APP NAVIGATION TABS ---
    tab1, tab2, tab3 = st.tabs(["📝 Log Transaction", "📊 Dashboard & Analytics", "📋 View Records"])

    # --- TAB 1: INPUT FORM ---
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
            place = st.text_input("Place / Shop / Source Description", placeholder="e.g., Target, Office, Landlord")
            amount = st.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f")

        button_disabled = worksheet is None
        
        if st.button("Submit Entry", type="primary", disabled=button_disabled):
            # Automated user tagging payload row
            new_row_data = [
                date.strftime("%Y-%m-%d"),
                transaction_type,
                category,
                place,
                float(amount),
                user_name  # <-- Automatically logs who spent the money
            ]
            
            try:
                worksheet.append_row(new_row_data)
                st.success(f"Success! Appended {transaction_type} of ${amount:.2f} to your spreadsheet.")
                st.clear_cache()
                st.rerun()
            except Exception as e:
                st.error(f"Could not save row to Google Sheet: {e}")

    # --- TAB 2: METRICS & VISUALIZATIONS ---
    with tab2:
        st.header("Financial Analytics")
        
        if existing_data.empty:
            st.info("No transaction data found in Google Sheets yet. Log an entry to populate charts.")
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
            
            # --- NEW ADDITION: SEPARATED CATEGORICAL CALCULATIONS SUMS ---
            st.subheader("📊 Expense Breakdown Summary Table")
            expense_df = existing_data[existing_data["Type"] == "Expense"]
            
            if not expense_df.empty:
                # Group by and aggregate to sum up each individual category separately
                category_sums = expense_df.groupby("Category")["Amount"].sum().reset_index()
                category_sums = category_sums.sort_values(by="Amount", ascending=False).reset_index(drop=True)
                
                # Format for presentation
                category_sums_display = category_sums.copy()
                category_sums_display["Amount"] = category_sums_display["Amount"].map("${:,.2f}".format)
                
                # Display individual sums side by side using clean UI columns
                cols = st.columns(4)
                for index, row in category_sums.iterrows():
                    col_index = index % 4
                    with cols[col_index]:
                        st.metric(label=row["Category"], value=f"${row['Amount']:,.2f}")
                
                st.markdown("---")
            
            # Visualizations Side-by-Side
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.subheader("Expense Volume Allocation")
                if not expense_df.empty:
                    # Injects custom color coding map directly into the Pie layout
                    fig_pie = px.pie(
                        expense_df, 
                        values="Amount", 
                        names="Category", 
                        hole=0.4,
                        color="Category",
                        color_discrete_map=CATEGORY_COLORS
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)
                else:
                    st.write("No expenses logged to generate a chart.")
                    
            with chart_col2:
                st.subheader("Cash Flow Trend via Purchaser Profile")
                # Group bars by user profile so you can see who logged what amount
                fig_bar = px.bar(
                    existing_data, 
                    x="Date", 
                    y="Amount", 
                    color="User", 
                    barmode="group",
                    hover_data=["Category", "Place/Shop"]
                )
                st.plotly_chart(fig_bar, use_container_width=True)

    # --- TAB 3: DATA LEDGER ---
    with tab3:
        st.header("Live Google Sheets Ledger")
        if not existing_data.empty:
            st.dataframe(existing_data.sort_values(by="Date", ascending=False), use_container_width=True)
        else:
            st.write("No transaction history detected.")

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from streamlit_oauth import OAuth2Component
from streamlit_gsheets import GSheetsConnection

# --- APP CONFIGURATION ---
st.set_page_config(page_title="Personal Budget Tracker", layout="wide")
st.title("💰 Personal Budget & Expense Tracker")

# --- GOOGLE OAUTH CONFIGURATION ---
CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

if "auth" not in st.session_state:
    st.session_state.auth = None

# Initialize OAuth Component
oauth2 = OAuth2Component(CLIENT_ID, CLIENT_SECRET, AUTHORIZE_URL, TOKEN_URL, TOKEN_URL, REVOKE_URL)

# --- CHECK AUTHENTICATION ---
if st.session_state.auth is None:
    st.subheader("🔒 Secure Access Required")
    st.write("Please sign in with your Google Account to access and manage your secure budget ledger.")
    
    # Render Google Sign-In Button
    # Note: When deploying, change redirect_uri to your actual production URL (e.g., https://your-app.streamlit.app)
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
    # --- USER IS LOGGED IN: UNLOCK APP ---
    st.sidebar.success("🔒 Authenticated via Google")
    if st.sidebar.button("Log Out"):
        st.session_state.auth = None
        st.rerun()

    # --- CONNECT TO GOOGLE SHEETS DATABASE ---
   # --- CONNECT TO GOOGLE SHEETS DATABASE ---

# 1. Rebuild the exact dictionary configuration Google expects
service_account_info = {
    "type": "service_account",
    "project_id": st.secrets["GSHEETS_PROJECT_ID"],
    "private_key_id": st.secrets["GSHEETS_PRIVATE_KEY_ID"],
    "private_key": st.secrets["GSHEETS_PRIVATE_KEY"],
    "client_email": st.secrets["GSHEETS_CLIENT_EMAIL"],
    "client_id": st.secrets["GSHEETS_CLIENT_ID"],
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{st.secrets['GSHEETS_CLIENT_EMAIL']}"
}

# 2. Force the connection to initialize using this dictionary explicitly
conn = st.connection(
    "gsheets",
    type=GSheetsConnection,
    spreadsheet=st.secrets["GSHEETS_SPREADSHEET"],
    **service_account_info
)

    # Read existing rows from Google Sheet
    try:
        existing_data = conn.read(ttl="0d")  # ttl="0d" ensures live sync without aggressive caching
    except Exception:
        # Fallback structure if the sheet is completely blank
        existing_data = pd.DataFrame(columns=["Date", "Type", "Category", "Place/Shop", "Amount"])

    # --- CATEGORY LISTS ---
    EXPENSE_CATEGORIES = [
        "Grocery", "OTT Bills", "Mobile Bills", "Vacation", 
        "Rent and Utilities", "Movies and Concerts", "Charity and Gift", 
        "For House", "Travel to Work", "Eat Out", "Others"
    ]
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
            amount = st.number_input("Amount (£)", min_value=0.0, step=0.01, format="%.2f")

        if st.button("Submit Entry", type="primary"):
            # Format data array
            new_row = pd.DataFrame([{
                "Date": date.strftime("%Y-%m-%d"),
                "Type": transaction_type,
                "Category": category,
                "Place/Shop": place,
                "Amount": amount
            }])
            
            # Merge existing database rows with our new entry
            updated_df = pd.concat([existing_data, new_row], ignore_index=True)
            
            # Push changes straight to Google Sheet
            conn.update(data=updated_df)
            
            st.success(f"Success! Saved {transaction_type} of £{amount:.2f} under '{category}' to your Google Sheet.")
            st.rerun()

    # --- TAB 2: METRICS & VISUALIZATIONS ---
    with tab2:
        st.header("Financial Analytics")
        
        if existing_data.empty:
            st.info("No transaction data found in Google Sheets yet. Log an entry to populate charts.")
        else:
            # Enforce float type for analytics
            existing_data["Amount"] = existing_data["Amount"].astype(float)
            
            total_income = existing_data[existing_data["Type"] == "Income"]["Amount"].sum()
            total_expense = existing_data[existing_data["Type"] == "Expense"]["Amount"].sum()
            net_savings = total_income - total_expense
            
            # Performance Cards
            card1, card2, card3 = st.columns(3)
            card1.metric("Total Income", f"£{total_income:,.2f}")
            card2.metric("Total Expenses", f"£{total_expense:,.2f}", delta=f"-£{total_expense:,.2f}", delta_color="inverse")
            card3.metric("Net Savings", f"£{net_savings:,.2f}")
            
            st.markdown("---")
            
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.subheader("Expense Breakdown")
                expense_df = existing_data[existing_data["Type"] == "Expense"]
                if not expense_df.empty:
                    fig_pie = px.pie(expense_df, values="Amount", names="Category", hole=0.4,
                                     color_discrete_sequence=px.colors.qualitative.Pastel)
                    st.plotly_chart(fig_pie, use_container_width=True)
                else:
                    st.write("No expenses logged to generate a layout chart.")
                    
            with chart_col2:
                st.subheader("Cash Flow Trend")
                fig_bar = px.bar(existing_data, x="Date", y="Amount", color="Type", barmode="group",
                                 color_discrete_map={"Income": "#2ecc71", "Expense": "#e74c3c"})
                st.plotly_chart(fig_bar, use_container_width=True)

    # --- TAB 3: DATA LEDGER ---
    with tab3:
        st.header("Live Google Sheets Ledger")
        if not existing_data.empty:
            st.dataframe(existing_data.sort_values(by="Date", ascending=False), use_container_width=True)
        else:
            st.write("No transaction history detected.")

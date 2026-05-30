import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from streamlit_oauth import OAuth2Component
import json

# --- APP CONFIGURATION ---
st.set_page_config(page_title="Personal Budget Tracker", layout="wide")
st.title("💰 Personal Budget & Expense Tracker")

# --- GOOGLE OAUTH CONFIG (Get these from Google Cloud Console) ---
# In production, use st.secrets for these!
CLIENT_ID = st.secrets.get("GOOGLE_CLIENT_ID", "YOUR_CLIENT_ID.apps.googleusercontent.com")
CLIENT_SECRET = st.secrets.get("GOOGLE_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# --- SESSION STATE INITIALIZATION ---
if "auth" not in st.session_state:
    st.session_state.auth = None
if "expenses_db" not in st.session_state:
    # Temporary local fallback dataframe if Google Drive isn't synced yet
    st.session_state.expenses_db = pd.DataFrame(columns=["Date", "Type", "Category", "Place/Shop", "Amount"])

# --- GOOGLE LOGIN ---
oauth2 = OAuth2Component(CLIENT_ID, CLIENT_SECRET, AUTHORIZE_URL, TOKEN_URL, TOKEN_URL, REVOKE_URL)

if st.session_state.auth is None:
    st.subheader("Please login with your Google Account to manage your budget secured in Google Drive.")
    result = oauth2.authorize_button(
        name="Continue with Google",
        icon="https://upload.wikimedia.org/wikipedia/commons/5/53/Google_%22G%22_Logo.svg",
        redirect_uri="https://budget-sb.streamlit.app/", # Change to streamlit sharing URL in prod
        scope="openid email profile https://www.googleapis.com/auth/drive.file",
        key="google_auth"
    )
    if result and "token" in result:
        st.session_state.auth = result
        st.rerun()
else:
    # User is logged in
    st.sidebar.success("Logged in successfully!")
    if st.sidebar.button("Logout"):
        st.session_state.auth = None
        st.rerun()

    # --- CATEGORY LISTS ---
    EXPENSE_CATEGORIES = [
        "Grocery", "OTT Bills", "Mobile Bills", "Vacation", 
        "Rent and Utilities", "Movies and Concerts", "Charity and Gift", 
        "For House", "Travel to Work", "Eat Out", "Others"
    ]
    
    INCOME_CATEGORIES = ["Salary", "Interest", "Investment", "Freelance/Side Hustle", "Others"]

    # --- APP LAYOUT ---
    tab1, tab2, tab3 = st.tabs(["📝 Log Transaction", "📊 Dashboard & Analytics", "📋 View Records"])

    # --- TAB 1: INPUT DATA ---
    with tab1:
        st.header("Add New Entry")
        
        # Select between Income and Expense
        transaction_type = st.radio("Transaction Type", ["Expense", "Income"], horizontal=True)
        
        col1, col2 = st.columns(2)
        with col1:
            date = st.date_input("Date", datetime.now())
            if transaction_type == "Expense":
                category = st.selectbox("Category of Expense", EXPENSE_CATEGORIES)
            else:
                category = st.selectbox("Source of Income", INCOME_CATEGORIES)
                
        with col2:
            place = st.text_input("Place / Shop / Source Description", placeholder="e.g., Walmart, Landlord, Salary Credit")
            amount = st.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f")

        if st.button("Submit Entry", type="primary"):
            new_data = pd.DataFrame([{
                "Date": date.strftime("%Y-%m-%d"),
                "Type": transaction_type,
                "Category": category,
                "Place/Shop": place,
                "Amount": amount
            }])
            
            # Append to session state (In a real app, you'd use gspread here to upload to Google Drive)
            st.session_state.expenses_db = pd.concat([st.session_state.expenses_db, new_data], ignore_index=True)
            st.success(f"Successfully recorded {transaction_type}: ${amount:.2f} for {category}!")

    # --- TAB 2: ANALYTICS & CHARTS ---
    with tab2:
        st.header("Financial Analytics")
        df = st.session_state.expenses_db
        
        if df.empty:
            st.info("No data available yet. Please log some transactions first.")
        else:
            # Ensure correct data types
            df["Amount"] = df["Amount"].astype(float)
            
            # High-Level Summary Cards
            total_income = df[df["Type"] == "Income"]["Amount"].sum()
            total_expense = df[df["Type"] == "Expense"]["Amount"].sum()
            net_savings = total_income - total_expense
            
            card1, card2, card3 = st.columns(3)
            card1.metric("Total Income", f"${total_income:,.2f}")
            card2.metric("Total Expenses", f"${total_expense:,.2f}", delta=f"-${total_expense:,.2f}", delta_color="inverse")
            card3.metric("Net Savings", f"${net_savings:,.2f}", delta=f"${net_savings:,.2f}")
            
            st.markdown("---")
            
            # Visualizations
            chart_col1, chart_col2 = st.columns(2)
            
            with chart_col1:
                st.subheader("Expense Breakdown by Category")
                expense_df = df[df["Type"] == "Expense"]
                if not expense_df.empty:
                    fig_pie = px.pie(expense_df, values="Amount", names="Category", hole=0.4,
                                     color_discrete_sequence=px.colors.sequential.RdBu)
                    st.plotly_chart(fig_pie, use_container_width=True)
                else:
                    st.write("No expense data to display chart.")
                    
            with chart_col2:
                st.subheader("Income vs Expense Trend")
                if not df.empty:
                    fig_bar = px.bar(df, x="Date", y="Amount", color="Type", barmode="group",
                                     color_discrete_map={"Income": "#2ecc71", "Expense": "#e74c3c"})
                    st.plotly_chart(fig_bar, use_container_width=True)

    # --- TAB 3: DATA TABLE ---
    with tab3:
        st.header("Transaction History")
        if not st.session_state.expenses_db.empty:
            st.dataframe(st.session_state.expenses_db.sort_values(by="Date", ascending=False), use_container_width=True)
        else:
            st.write("No records found.")

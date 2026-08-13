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

    # --- ACCESS CONTROL: restrict to the household's Google accounts ---
    # Configure ALLOWED_EMAILS in secrets as a comma-separated list, e.g.
    # ALLOWED_EMAILS = "person.one@gmail.com,person.two@gmail.com"
    # Leave unset/empty to allow any Google account to sign in.
    allowed_raw = st.secrets.get("ALLOWED_EMAILS", "")
    allowed_emails = [e.strip().lower() for e in allowed_raw.split(",") if e.strip()]
    if allowed_emails and user_name.lower() not in allowed_emails:
        st.error(f"🚫 Access denied. '{user_name}' is not on the household allowlist.")
        if st.button("Sign out and try a different account"):
            st.session_state.auth = None
            st.rerun()
        st.stop()

    st.sidebar.success(f"👋 Logged in as: {user_name}")
    if st.sidebar.button("Log Out"):
        st.session_state.auth = None
        st.rerun()

    @st.cache_resource
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

    def _dedupe_headers(header):
        """Sheets sometimes carry blank/repeated trailing header cells (e.g. from the
        cols=10 worksheets this app creates) which produce duplicate column labels and
        break pandas. Give every blank/duplicate header a unique name so the DataFrame
        can always be built, then downstream code just keeps the columns it expects."""
        seen = {}
        clean = []
        for i, h in enumerate(header):
            h = (h or "").strip() or f"_blank{i}"
            if h in seen:
                seen[h] += 1
                h = f"{h}_{seen[h]}"
            else:
                seen[h] = 0
            clean.append(h)
        return clean

    def load_sheet(sheet_name):
        """Read of one worksheet, tolerant of duplicate/blank/extra header cells."""
        raw_rows = sh.worksheet(sheet_name).get_all_values()
        if not raw_rows:
            return pd.DataFrame(columns=expected_headers)
        header = _dedupe_headers(raw_rows[0])
        df = pd.DataFrame(raw_rows[1:], columns=header)
        for col in expected_headers:
            if col not in df.columns:
                df[col] = ""
        return df[expected_headers]

    @st.cache_data(ttl=60, show_spinner=False)
    def load_sheet_cached(sheet_name):
        return load_sheet(sheet_name)

    @st.cache_data(ttl=60, show_spinner="Loading full ledger history…")
    def load_all_months(month_names):
        frames = []
        skipped = []
        for name in month_names:
            try:
                df = load_sheet_cached(name)
            except Exception as sheet_err:
                skipped.append((name, str(sheet_err)))
                continue
            if not df.empty:
                df = df.copy()
                df["Month"] = name
                frames.append(df)
        if skipped:
            for name, err in skipped:
                st.warning(f"⚠️ Skipped tab '{name}' while loading history: {err}")
        if not frames:
            return pd.DataFrame(columns=expected_headers + ["Month"])
        combined = pd.concat(frames, ignore_index=True)
        combined["Amount"] = pd.to_numeric(combined["Amount"], errors="coerce").fillna(0.0)
        combined["Date"] = pd.to_datetime(combined["Date"], errors="coerce")
        return combined

    try:
        gc = get_google_client()
        sh = gc.open_by_url(st.secrets["GSHEETS_SPREADSHEET"])

        sheet_names = [sheet.title for sheet in sh.worksheets()]
        if "savings" not in sheet_names:
            sb_ws = sh.add_worksheet(title="savings", rows=500, cols=10)
            sb_ws.append_row(expected_headers)
            sheet_names.append("savings")

        monthly_tabs = sorted(name for name in sheet_names if name != "savings")

        st.sidebar.markdown("---")
        st.sidebar.subheader("📅 Select Month View")
        default_month_idx = len(monthly_tabs) - 1 if monthly_tabs else 0
        target_month_sheet = st.sidebar.selectbox(
            "Active Ledger Tab", monthly_tabs if monthly_tabs else ["None"], index=default_month_idx if monthly_tabs else 0
        )

        if target_month_sheet != "None":
            existing_data = load_sheet_cached(target_month_sheet)
        else:
            existing_data = pd.DataFrame(columns=expected_headers)

        savings_data = load_sheet_cached("savings")

        # Combined, cleaned data across every monthly tab — powers trend / ledger / household views.
        all_data = load_all_months(tuple(monthly_tabs))

        if st.sidebar.button("🔄 Refresh data from Google Sheet"):
            load_sheet_cached.clear()
            load_all_months.clear()
            st.rerun()

    except Exception as e:
        st.error(f"❌ Core File Synchronization Failure: {e}")
        existing_data = pd.DataFrame(columns=expected_headers)
        savings_data = pd.DataFrame(columns=expected_headers)
        all_data = pd.DataFrame(columns=expected_headers + ["Month"])

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
                        load_sheet_cached.clear()
                        load_all_months.clear()
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
                            load_sheet_cached.clear()
                            load_all_months.clear()
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
                            load_sheet_cached.clear()
                            load_all_months.clear()
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
                        load_sheet_cached.clear()
                        load_all_months.clear()
                        st.rerun()
                    except Exception as e: st.error(f"Failed: {e}")

    # --- TAB 2: ANALYTICS CHANNELS ---
    with tab2:
        st.header("📊 Financial Analytics")

        analysis_mode = st.radio(
            "Choose an analysis view",
            [
                "📊 Monthly Summary",
                "🥧 Category Breakdown",
                "📈 Trend Over Time",
                "✈️ Trips & Vacations",
                "💹 Savings & Investments",
                "👥 Household Split",
            ],
            horizontal=True,
            key="analysis_mode",
        )
        st.markdown("---")

        # Clean the single-month frame used by month-scoped views
        month_df = existing_data.copy()
        if not month_df.empty:
            month_df["Amount"] = pd.to_numeric(month_df["Amount"], errors="coerce").fillna(0.0)

        # ---------------- MONTHLY SUMMARY ----------------
        if analysis_mode == "📊 Monthly Summary":
            st.subheader(f"Month view: {target_month_sheet}")

            t_income = month_df.loc[month_df["Type"] == "Income", "Amount"].sum() if not month_df.empty else 0.0
            t_expense = month_df.loc[month_df["Type"] == "Expense", "Amount"].sum() if not month_df.empty else 0.0
            t_work_trip = month_df.loc[month_df["Type"] == "Work Trip", "Amount"].sum() if not month_df.empty else 0.0
            t_vacation = month_df.loc[month_df["Type"] == "Vacation", "Amount"].sum() if not month_df.empty else 0.0
            net = t_income - t_expense - t_work_trip - t_vacation
            savings_rate = (net / t_income * 100) if t_income > 0 else 0.0

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Income", f"£{t_income:,.2f}")
            c2.metric("Expense", f"£{t_expense:,.2f}")
            c3.metric("Work Trips", f"£{t_work_trip:,.2f}")
            c4.metric("Vacations", f"£{t_vacation:,.2f}")
            c5.metric("Net", f"£{net:,.2f}", delta=f"{savings_rate:.1f}% of income")

            if not month_df.empty:
                colA, colB = st.columns(2)
                with colA:
                    flow_df = pd.DataFrame({
                        "Flow": ["Income", "Expense", "Work Trip", "Vacation"],
                        "Amount": [t_income, t_expense, t_work_trip, t_vacation],
                    })
                    fig = px.bar(flow_df, x="Flow", y="Amount", color="Flow", text_auto=".2f",
                                 title="Income vs. Outgoings this month")
                    st.plotly_chart(fig, use_container_width=True)
                with colB:
                    exp_cat = month_df[month_df["Type"] == "Expense"]
                    if not exp_cat.empty:
                        fig2 = px.pie(exp_cat, names="Category", values="Amount", hole=0.4,
                                      color="Category", color_discrete_map=CATEGORY_COLORS,
                                      title="Where expense money went")
                        st.plotly_chart(fig2, use_container_width=True)
                    else:
                        st.info("No expense entries logged for this month yet.")

                st.subheader("Top 10 single transactions this month")
                top10 = month_df.sort_values("Amount", ascending=False).head(10)
                st.dataframe(top10[["Date", "Type", "Category", "Place/Shop", "Amount", "User"]], use_container_width=True, hide_index=True)
            else:
                st.info("No entries logged for this month yet — add some in the Log Workspace tab.")

        # ---------------- CATEGORY BREAKDOWN ----------------
        elif analysis_mode == "🥧 Category Breakdown":
            st.subheader(f"Category breakdown — {target_month_sheet}")
            type_choice = st.selectbox("Transaction type", ["Expense", "Income", "Work Trip", "Vacation"], key="cat_type_choice")
            scoped = month_df[month_df["Type"] == type_choice] if not month_df.empty else pd.DataFrame()

            if scoped.empty:
                st.info(f"No '{type_choice}' entries logged for this month.")
            else:
                colA, colB = st.columns(2)
                with colA:
                    fig = px.pie(scoped, names="Category", values="Amount", hole=0.4,
                                 color="Category", color_discrete_map=CATEGORY_COLORS,
                                 title=f"{type_choice} share by category")
                    st.plotly_chart(fig, use_container_width=True)
                with colB:
                    by_cat = scoped.groupby("Category", as_index=False)["Amount"].sum().sort_values("Amount", ascending=True)
                    fig2 = px.bar(by_cat, x="Amount", y="Category", orientation="h", text_auto=".2f",
                                  color="Category", color_discrete_map=CATEGORY_COLORS,
                                  title=f"{type_choice} total by category")
                    st.plotly_chart(fig2, use_container_width=True)

                st.subheader("Top places / shops")
                by_place = scoped.groupby("Place/Shop", as_index=False)["Amount"].sum().sort_values("Amount", ascending=False).head(15)
                st.dataframe(by_place, use_container_width=True, hide_index=True)

        # ---------------- TREND OVER TIME ----------------
        elif analysis_mode == "📈 Trend Over Time":
            st.subheader("Multi-month trend")
            if all_data.empty:
                st.info("No historical data across months yet.")
            else:
                min_d, max_d = all_data["Date"].min(), all_data["Date"].max()
                date_range = st.date_input("Date range", value=(min_d.date(), max_d.date()), key="trend_date_range")
                type_filter = st.multiselect("Transaction types", sorted(all_data["Type"].unique()),
                                              default=sorted(all_data["Type"].unique()), key="trend_type_filter")

                trend_df = all_data[all_data["Type"].isin(type_filter)]
                if isinstance(date_range, tuple) and len(date_range) == 2:
                    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
                    trend_df = trend_df[(trend_df["Date"] >= start) & (trend_df["Date"] <= end)]

                if trend_df.empty:
                    st.info("No entries match this filter.")
                else:
                    by_month_type = trend_df.groupby(["Month", "Type"], as_index=False)["Amount"].sum()
                    fig = px.line(by_month_type, x="Month", y="Amount", color="Type", markers=True,
                                  title="Monthly total by transaction type")
                    st.plotly_chart(fig, use_container_width=True)

                    net_by_month = trend_df.pivot_table(index="Month", columns="Type", values="Amount", aggfunc="sum", fill_value=0)
                    for col in ["Income", "Expense", "Work Trip", "Vacation"]:
                        if col not in net_by_month.columns:
                            net_by_month[col] = 0.0
                    net_by_month["Net"] = net_by_month["Income"] - net_by_month["Expense"] - net_by_month["Work Trip"] - net_by_month["Vacation"]
                    net_by_month = net_by_month.reset_index()
                    fig2 = px.bar(net_by_month, x="Month", y="Net", title="Net cash flow by month",
                                  color=net_by_month["Net"] >= 0, color_discrete_map={True: "#27ae60", False: "#e74c3c"})
                    fig2.update_layout(showlegend=False)
                    st.plotly_chart(fig2, use_container_width=True)

                    st.subheader("Category trend (stacked)")
                    cat_trend = trend_df[trend_df["Type"] == "Expense"].groupby(["Month", "Category"], as_index=False)["Amount"].sum()
                    if not cat_trend.empty:
                        fig3 = px.area(cat_trend, x="Month", y="Amount", color="Category",
                                       color_discrete_map=CATEGORY_COLORS, title="Expense category trend")
                        st.plotly_chart(fig3, use_container_width=True)

        # ---------------- TRIPS & VACATIONS ----------------
        elif analysis_mode == "✈️ Trips & Vacations":
            st.subheader("Work trips & vacations, all-time")
            trips = all_data[all_data["Type"].isin(["Work Trip", "Vacation"])] if not all_data.empty else pd.DataFrame()
            if trips.empty:
                st.info("No work trip or vacation entries logged yet.")
            else:
                colA, colB = st.columns(2)
                with colA:
                    by_type = trips.groupby("Type", as_index=False)["Amount"].sum()
                    fig = px.bar(by_type, x="Type", y="Amount", color="Type", text_auto=".2f",
                                 title="Total spend: Work Trips vs Vacations")
                    st.plotly_chart(fig, use_container_width=True)
                with colB:
                    fig2 = px.pie(trips, names="Category", values="Amount", hole=0.4,
                                  color="Category", color_discrete_map=CATEGORY_COLORS,
                                  title="Spend by category (Food, Travel, etc.)")
                    st.plotly_chart(fig2, use_container_width=True)

                st.subheader("Cost per trip / destination")
                by_place = trips.groupby(["Place/Shop", "Type"], as_index=False)["Amount"].sum().sort_values("Amount", ascending=False)
                by_place.columns = ["Trip / Destination", "Type", "Total Amount"]
                st.dataframe(by_place, use_container_width=True, hide_index=True)

        # ---------------- SAVINGS & INVESTMENTS ----------------
        elif analysis_mode == "💹 Savings & Investments":
            st.subheader("Savings & investment allocation, all-time")
            sav = savings_data.copy()
            if sav.empty:
                st.info("No savings or investment entries logged yet.")
            else:
                sav["Amount"] = pd.to_numeric(sav["Amount"], errors="coerce").fillna(0.0)
                sav["Date"] = pd.to_datetime(sav["Date"], errors="coerce")
                sav = sav.sort_values("Date")

                total_invested = sav["Amount"].sum()
                st.metric("Total invested to date", f"£{total_invested:,.2f}")

                colA, colB = st.columns(2)
                with colA:
                    fig = px.pie(sav, names="Category", values="Amount", hole=0.4,
                                 color="Category", color_discrete_map=CATEGORY_COLORS,
                                 title="Allocation by asset class")
                    st.plotly_chart(fig, use_container_width=True)
                with colB:
                    by_platform = sav.groupby("Place/Shop", as_index=False)["Amount"].sum().sort_values("Amount", ascending=True)
                    fig2 = px.bar(by_platform, x="Amount", y="Place/Shop", orientation="h", text_auto=".2f",
                                  title="Total by brokerage / platform")
                    st.plotly_chart(fig2, use_container_width=True)

                st.subheader("Cumulative contributions over time")
                cum = sav.copy()
                cum["Cumulative"] = cum["Amount"].cumsum()
                fig3 = px.line(cum, x="Date", y="Cumulative", markers=True, title="Running total invested")
                st.plotly_chart(fig3, use_container_width=True)

        # ---------------- HOUSEHOLD SPLIT ----------------
        elif analysis_mode == "👥 Household Split":
            st.subheader("Who's spending / earning what")
            if all_data.empty:
                st.info("No historical data across months yet.")
            else:
                users = sorted(u for u in all_data["User"].dropna().unique() if u)
                if len(users) < 2:
                    st.info("Only one household member has logged entries so far.")

                by_user_type = all_data.groupby(["User", "Type"], as_index=False)["Amount"].sum()
                fig = px.bar(by_user_type, x="User", y="Amount", color="Type", barmode="group",
                             title="Total by household member and transaction type")
                st.plotly_chart(fig, use_container_width=True)

                exp_by_user = all_data[all_data["Type"] == "Expense"]
                if not exp_by_user.empty:
                    fig2 = px.bar(exp_by_user.groupby(["User", "Category"], as_index=False)["Amount"].sum(),
                                  x="User", y="Amount", color="Category", barmode="stack",
                                  color_discrete_map=CATEGORY_COLORS, title="Expense category split by household member")
                    st.plotly_chart(fig2, use_container_width=True)

                st.subheader("Per-person totals (all-time)")
                summary = all_data.pivot_table(index="User", columns="Type", values="Amount", aggfunc="sum", fill_value=0).reset_index()
                st.dataframe(summary, use_container_width=True, hide_index=True)

    # --- TAB 3: LEDGER ARCHIVES ---
    with tab3:
        st.header("📋 Ledger Archives")
        st.write("Search and filter every entry ever logged, across all months.")

        if all_data.empty:
            st.info("No entries logged yet.")
        else:
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                min_d, max_d = all_data["Date"].min(), all_data["Date"].max()
                date_range = st.date_input("Date range", value=(min_d.date(), max_d.date()), key="archive_date_range")
            with f2:
                type_filter = st.multiselect("Type", sorted(all_data["Type"].unique()),
                                              default=sorted(all_data["Type"].unique()), key="archive_type_filter")
            with f3:
                cat_filter = st.multiselect("Category", sorted(all_data["Category"].unique()), key="archive_cat_filter")
            with f4:
                user_filter = st.multiselect("User", sorted(u for u in all_data["User"].dropna().unique() if u), key="archive_user_filter")

            search_text = st.text_input("Search Place / Shop / Description", key="archive_search")

            filtered = all_data.copy()
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
                filtered = filtered[(filtered["Date"] >= start) & (filtered["Date"] <= end)]
            if type_filter:
                filtered = filtered[filtered["Type"].isin(type_filter)]
            if cat_filter:
                filtered = filtered[filtered["Category"].isin(cat_filter)]
            if user_filter:
                filtered = filtered[filtered["User"].isin(user_filter)]
            if search_text:
                filtered = filtered[filtered["Place/Shop"].str.contains(search_text, case=False, na=False)]

            filtered = filtered.sort_values("Date", ascending=False)

            m1, m2 = st.columns(2)
            m1.metric("Matching entries", f"{len(filtered):,}")
            m2.metric("Total amount", f"£{filtered['Amount'].sum():,.2f}")

            st.dataframe(
                filtered[["Date", "Month", "Type", "Category", "Place/Shop", "Amount", "User"]],
                use_container_width=True, hide_index=True,
            )

            st.download_button(
                "⬇️ Download filtered results as CSV",
                data=filtered.to_csv(index=False).encode("utf-8"),
                file_name="budget_ledger_export.csv",
                mime="text/csv",
            )

import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import time

# --- CONFIGURATION ---
st.set_page_config(page_title="Vinted Manager", layout="wide", page_icon="📦")
PRODUCTS = ["Black Belt", "Brown Belt", "White Belt", "Bordeaux Belt", "LV Belt"]

# --- CONNECTION ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- SINGLE LOAD FUNCTION (MEMORY) ---
if "data_loaded" not in st.session_state:
    try:
        # Read everything at startup
        st.session_state.stock = conn.read(worksheet="Stock", usecols=[0,1,2], ttl=0)
        st.session_state.orders = conn.read(worksheet="Orders", ttl=0)
        st.session_state.financials = conn.read(worksheet="Financials", ttl=0)
        st.session_state.history = conn.read(worksheet="History", ttl=0)
        
        # Clean numbers
        def clean(val):
            if isinstance(val, str): return float(val.replace(',', '.').replace('€', '').strip())
            return float(val) if val else 0.0

        if "Avg_Cost" in st.session_state.stock.columns:
            st.session_state.stock["Avg_Cost"] = st.session_state.stock["Avg_Cost"].apply(clean)
        
        for c in ["price", "profit"]:
            if c in st.session_state.orders.columns: st.session_state.orders[c] = st.session_state.orders[c].apply(clean)
            
        for c in ["Revenue", "Profit", "Expenses"]:
            if c in st.session_state.financials.columns: st.session_state.financials[c] = st.session_state.financials[c].apply(clean)

        st.session_state.data_loaded = True
        
    except Exception as e:
        st.error(f"Startup Error: {e}")
        st.stop()

# --- TARGETED SAVE FUNCTION ---
def update_google(sheet_name, df):
    """Sends only the modified sheet to Google."""
    try:
        conn.update(worksheet=sheet_name, data=df)
    except Exception:
        st.toast(f"⚠️ Google busy. {sheet_name} save delayed.", icon="⏳")

# --- SIDEBAR ---
st.sidebar.title("Dressing Manager")
menu = st.sidebar.radio("Menu", ["Dashboard", "Orders", "Stock", "Admin"])

if st.sidebar.button("🔄 Force Reload"):
    st.cache_data.clear()
    del st.session_state.data_loaded
    st.rerun()

# --- PAGES ---
if menu == "Dashboard":
    st.title("📊 Dashboard")
    fin = st.session_state.financials.iloc[0]
    ords = st.session_state.orders
    
    pending = ords[ords["status"] != "Delivered"]["price"].sum() if not ords.empty else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Revenue (Received)", f"{fin['Revenue']:.2f}€")
    c2.metric("Net Profit", f"{fin['Profit']:.2f}€")
    c3.metric("Pending", f"{pending:.2f}€")
    
    st.divider()
    st.write("📦 **Current Stock**")
    st.dataframe(st.session_state.stock, use_container_width=True, hide_index=True)

elif menu == "Orders":
    st.title("📦 Order Tracking")
    
    # 1. NEW SALE
    with st.expander("➕ New Sale"):
        c1, c2, c3 = st.columns(3)
        prod = c1.selectbox("Product", PRODUCTS)
        client = c2.text_input("Buyer Name")
        price = c3.number_input("Sold Price (€)", 0.0, step=0.5)
        
        if st.button("Confirm Sale"):
            stock = st.session_state.stock
            idx = stock.index[stock["Product"] == prod].tolist()
            
            if idx and stock.at[idx[0], "Qty"] > 0:
                # Local Update
                idx = idx[0]
                st.session_state.stock.at[idx, "Qty"] -= 1
                profit = price - stock.at[idx, "Avg_Cost"]
                
                new_row = pd.DataFrame([{
                    "id": len(st.session_state.orders) + 1000,
                    "date": datetime.now().strftime('%Y-%m-%d'),
                    "client": client, "product": prod,
                    "price": price, "profit": profit, "status": "Processing"
                }])
                st.session_state.orders = pd.concat([st.session_state.orders, new_row], ignore_index=True)
                
                # Cloud Save
                update_google("Stock", st.session_state.stock)
                update_google("Orders", st.session_state.orders)
                st.toast("Sale Recorded Successfully!", icon="💰")
                time.sleep(1) # Wait 1s so user sees the toast
                st.rerun()
            else:
                st.error("Out of Stock!")

    st.divider()
    
    # 2. ORDERS LIST
    df = st.session_state.orders
    if not df.empty:
        cols = st.columns([1, 2, 2, 1, 2])
        cols[0].write("**Date**")
        cols[1].write("**Product**")
        cols[2].write("**Buyer**")
        cols[3].write("**Price**")
        cols[4].write("**Action**")
        st.write("---")
        
        for i in range(len(df)-1, -1, -1):
            row = df.iloc[i]
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 1, 2])
            
            c1.write(row['date'])
            c2.write(row['product'])
            c3.write(row['client'])
            c4.write(f"{row['price']:.2f}€")
            
            status = row['status']
            key_base = f"btn_{row['id']}"
            
            if status == "Processing":
                if c5.button("🔴 Mark Shipped", key=key_base):
                    st.session_state.orders.at[i, "status"] = "Shipped"
                    update_google("Orders", st.session_state.orders)
                    st.rerun()
                    
            elif status == "Shipped":
                if c5.button("🟠 Mark Delivered", key=key_base):
                    st.session_state.orders.at[i, "status"] = "Delivered"
                    st.session_state.financials.at[0, "Revenue"] += row['price']
                    st.session_state.financials.at[0, "Profit"] += row['profit']
                    
                    update_google("Orders", st.session_state.orders)
                    update_google("Financials", st.session_state.financials)
                    st.balloons()
                    st.rerun()
                    
            else:
                c5.button("🟢 Completed", key=key_base, disabled=True)

elif menu == "Stock":
    st.title("🏭 Stock Management")
    c1, c2, c3 = st.columns(3)
    p = c1.selectbox("Product", PRODUCTS)
    q = c2.number_input("Qty Received", 1)
    cost = c3.number_input("Total Cost (€)", 0.0)
    
    if st.button("Add Stock"):
        stock = st.session_state.stock
        idx = stock.index[stock["Product"] == p].tolist()
        
        if idx:
            idx = idx[0]
            curr_q = stock.at[idx, "Qty"]
            curr_av = stock.at[idx, "Avg_Cost"]
            
            new_val = (curr_q * curr_av) + cost
            new_q = curr_q + q
            new_avg = new_val / new_q if new_q > 0 else 0
            
            st.session_state.stock.at[idx, "Qty"] = new_q
            st.session_state.stock.at[idx, "Avg_Cost"] = new_avg
            st.session_state.financials.at[0, "Expenses"] += cost
            
            update_google("Stock", st.session_state.stock)
            update_google("Financials", st.session_state.financials)
            
            # --- ICI LA MODIFICATION ---
            st.toast("Stock Added Successfully!", icon="✅")
            time.sleep(1) # On attend 1 seconde pour que tu le voies
            st.rerun()

elif menu == "Admin":
    st.title("⚙️ Admin")
    if st.button("Start New Month (Reset Revenue)"):
        st.session_state.financials.at[0, "Revenue"] = 0
        st.session_state.financials.at[0, "Profit"] = 0
        update_google("Financials", st.session_state.financials)
        st.success("Month Reset Done")
        st.rerun()

import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import time
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

st.set_page_config(page_title="Vinted Manager", layout="wide", page_icon="📦")

conn = st.connection("gsheets", type=GSheetsConnection)

if "data_loaded" not in st.session_state:
    try:
        st.session_state.stock = conn.read(worksheet="Stock", usecols=[0,1,2], ttl=0)
        st.session_state.orders = conn.read(worksheet="Orders", ttl=0)
        st.session_state.financials = conn.read(worksheet="Financials", ttl=0)
        st.session_state.history = conn.read(worksheet="History", ttl=0)
        
        def clean(val):
            if pd.isna(val): return 0.0
            if isinstance(val, str):
                cleaned = val.replace(',', '.').replace('€', '').strip()
                return float(cleaned) if cleaned else 0.0
            return float(val)

        if "Avg_Cost" in st.session_state.stock.columns:
            st.session_state.stock["Avg_Cost"] = st.session_state.stock["Avg_Cost"].apply(clean)
        
        for c in ["price", "profit"]:
            if c in st.session_state.orders.columns: st.session_state.orders[c] = st.session_state.orders[c].apply(clean)
            
        for c in ["Revenue", "Profit", "Expenses"]:
            if c in st.session_state.financials.columns: st.session_state.financials[c] = st.session_state.financials[c].apply(clean)

        if st.session_state.history.empty:
             st.session_state.history = pd.DataFrame(columns=["log"])

        st.session_state.data_loaded = True
    except Exception as e:
        st.error(f"Startup Error: {e}")
        st.stop()

def update_google(sheet_name, df):
    try:
        conn.update(worksheet=sheet_name, data=df)
    except Exception:
        st.toast(f"⚠️ Google busy. {sheet_name} save delayed.", icon="⏳")

def log_action(msg):
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {msg}"
    new_row = pd.DataFrame([{"log": entry}])
    st.session_state.history = pd.concat([new_row, st.session_state.history], ignore_index=True)
    update_google("History", st.session_state.history)

def generate_pdf(df_fin, df_orders):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 800, f"Monthly Report - {datetime.now().strftime('%B %Y')}")
    
    c.setFont("Helvetica", 12)
    fin = df_fin.iloc[0]
    c.drawString(50, 760, f"Total Revenue: {fin['Revenue']:.2f} EUR")
    c.drawString(50, 740, f"Net Profit: {fin['Profit']:.2f} EUR")
    c.drawString(50, 720, f"Total Expenses: {fin['Expenses']:.2f} EUR")
    
    c.drawString(50, 680, "Delivered Orders (This Month):")
    y = 660
    c.setFont("Helvetica", 10)
    
    delivered = df_orders[df_orders["status"] == "Delivered"]
    if not delivered.empty:
        for index, row in delivered.iterrows():
            if y < 50: c.showPage(); y = 800
            line = f"{row['date']} | {row['product']} | {row['client']} | +{row['profit']:.2f} EUR"
            c.drawString(50, y, line)
            y -= 15
    else:
        c.drawString(50, y, "No delivered orders yet.")
        
    c.save()
    buffer.seek(0)
    return buffer

st.sidebar.title("Dressing Manager")
menu = st.sidebar.radio("Menu", ["Dashboard", "Orders", "Stock", "Admin"])

if st.sidebar.button("🔄 Force Reload"):
    st.cache_data.clear()
    del st.session_state.data_loaded
    st.rerun()

if menu == "Dashboard":
    st.title("📊 Dashboard")
    fin = st.session_state.financials.iloc[0]
    ords = st.session_state.orders
    stk = st.session_state.stock
    
    pending = ords[ords["status"] != "Delivered"]["price"].sum() if not ords.empty else 0
    stock_value = (stk["Qty"] * stk["Avg_Cost"]).sum()
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue (Received)", f"{fin['Revenue']:.2f}€")
    c2.metric("Net Profit", f"{fin['Profit']:.2f}€")
    c3.metric("Pending", f"{pending:.2f}€")
    c4.metric("Total Stock Value", f"{stock_value:.2f}€")
    
    st.divider()
    st.write("📦 **Current Stock Detail**")
    st.dataframe(st.session_state.stock, use_container_width=True, hide_index=True)

elif menu == "Orders":
    st.title("📦 Order Tracking")
    product_list = st.session_state.stock["Product"].unique().tolist() if not st.session_state.stock.empty else []
    
    with st.expander("➕ New Sale"):
        c1, c2, c3 = st.columns(3)
        prod = c1.selectbox("Product", product_list)
        client = c2.text_input("Buyer Name")
        price = c3.number_input("Sold Price (€)", 0.0, step=0.5)
        
        if st.button("Confirm Sale"):
            stock = st.session_state.stock
            idx = stock.index[stock["Product"] == prod].tolist()
            
            if idx and stock.at[idx[0], "Qty"] > 0:
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
                
                log_action(f"SALE: {prod} to {client} ({price}€)")
                update_google("Stock", st.session_state.stock)
                update_google("Orders", st.session_state.orders)
                
                st.toast("Sale Recorded Successfully!", icon="💰")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Out of Stock!")

    st.divider()
    
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
                    log_action(f"SHIPPED: Order #{row['id']}")
                    update_google("Orders", st.session_state.orders)
                    st.rerun()
                    
            elif status == "Shipped":
                if c5.button("🟠 Mark Delivered", key=key_base):
                    st.session_state.orders.at[i, "status"] = "Delivered"
                    st.session_state.financials.at[0, "Revenue"] += row['price']
                    st.session_state.financials.at[0, "Profit"] += row['profit']
                    
                    log_action(f"DELIVERED: Order #{row['id']} (+{row['profit']}€)")
                    update_google("Orders", st.session_state.orders)
                    update_google("Financials", st.session_state.financials)
                    st.balloons()
                    st.rerun()
                    
            else:
                c5.button("🟢 Completed", key=key_base, disabled=True)

elif menu == "Stock":
    st.title("🏭 Stock Management")

    with st.expander("✨ Create New Item"):
        new_prod = st.text_input("New Product Name")
        if st.button("Create Item"):
            if new_prod and new_prod not in st.session_state.stock["Product"].values:
                new_row = pd.DataFrame([{"Product": new_prod, "Qty": 0, "Avg_Cost": 0.0}])
                st.session_state.stock = pd.concat([st.session_state.stock, new_row], ignore_index=True)
                update_google("Stock", st.session_state.stock)
                log_action(f"CREATED: {new_prod}")
                st.success(f"Added {new_prod}")
                time.sleep(1)
                st.rerun()
            else:
                st.warning("Invalid name or already exists.")

    st.divider()

    product_list = st.session_state.stock["Product"].unique().tolist() if not st.session_state.stock.empty else []
    c1, c2, c3 = st.columns(3)
    p = c1.selectbox("Product", product_list)
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
            
            log_action(f"RESTOCK: {q}x {p} (-{cost}€)")
            update_google("Stock", st.session_state.stock)
            update_google("Financials", st.session_state.financials)
            
            st.toast("Stock Added Successfully!", icon="✅")
            time.sleep(1)
            st.rerun()

elif menu == "Admin":
    st.title("⚙️ Admin")
    
    st.subheader("📄 Monthly Report")
    pdf_file = generate_pdf(st.session_state.financials, st.session_state.orders)
    st.download_button("Download PDF Report", pdf_file, f"Report_{datetime.now().strftime('%B')}.pdf", "application/pdf")
    
    st.divider()
    
    if st.button("Start New Month (Reset Revenue)"):
        st.session_state.financials.at[0, "Revenue"] = 0
        st.session_state.financials.at[0, "Profit"] = 0
        log_action("RESET: New Month Started")
        update_google("Financials", st.session_state.financials)
        st.success("Month Reset Done")
        st.rerun()
        
    st.divider()
    st.subheader("📜 Activity Logs")
    st.dataframe(st.session_state.history, use_container_width=True)

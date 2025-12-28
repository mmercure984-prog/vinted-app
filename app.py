import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io

# Config
st.set_page_config(page_title="Vinted Manager", layout="wide", page_icon="📦")
PRODUCTS = ["Black Belt", "Brown Belt", "White Belt", "Bordeaux Belt", "LV Belt"]

# --- CONNEXION GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

def get_data():
    # On force le rechargement pour être sûr d'avoir les données fraîches
    df_stock = conn.read(worksheet="Stock", usecols=[0,1,2], ttl=0)
    df_orders = conn.read(worksheet="Orders", ttl=0)
    df_fin = conn.read(worksheet="Financials", ttl=0)
    df_hist = conn.read(worksheet="History", ttl=0)
    
    # Init si vide
    if df_stock.empty or len(df_stock.columns) < 2:
        df_stock = pd.DataFrame({"Product": PRODUCTS, "Qty": [0]*5, "Avg_Cost": [0.0]*5})
    if df_fin.empty:
        df_fin = pd.DataFrame([{"Revenue": 0.0, "Profit": 0.0, "Expenses": 0.0}])
    if "Status" not in df_orders.columns: # Init colonnes orders
        df_orders = pd.DataFrame(columns=["id", "date", "client", "product", "price", "profit", "status"])
    if df_hist.empty:
        df_hist = pd.DataFrame(columns=["log"])
        
    return df_stock, df_orders, df_fin, df_hist

def save_all(df_stock, df_orders, df_fin, df_hist):
    conn.update(worksheet="Stock", data=df_stock)
    conn.update(worksheet="Orders", data=df_orders)
    conn.update(worksheet="Financials", data=df_fin)
    conn.update(worksheet="History", data=df_hist)
    st.cache_data.clear() # Vide le cache pour forcer la maj visuelle

def log_action(msg, df_hist):
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {msg}"
    new_row = pd.DataFrame([{"log": entry}])
    return pd.concat([new_row, df_hist], ignore_index=True)

# --- PDF GENERATOR ---
def generate_pdf(df_fin, df_orders):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    month_str = datetime.now().strftime("%B %Y")
    c.drawString(50, 800, f"Report - {month_str}")
    
    c.setFont("Helvetica", 12)
    fin = df_fin.iloc[0]
    c.drawString(50, 760, f"Realized Revenue: {fin['Revenue']:.2f} EUR")
    c.drawString(50, 740, f"Realized Profit: {fin['Profit']:.2f} EUR")
    c.drawString(50, 720, f"Expenses: {fin['Expenses']:.2f} EUR")
    
    c.drawString(50, 680, "Delivered Orders this month:")
    y = 660
    c.setFont("Helvetica", 10)
    for index, row in df_orders.iterrows():
        if row["status"] == "Delivered":
            if y < 50: c.showPage(); y = 800
            c.drawString(50, y, f"{row['date']} - {row['client']} - {row['product']} - {row['price']} EUR")
            y -= 15
    c.save()
    buffer.seek(0)
    return buffer

# --- LOAD DATA ---
try:
    df_stock, df_orders, df_fin, df_hist = get_data()
except Exception:
    st.error("⚠️ Connexion Google Sheets en cours d'initialisation ou erreur de configuration.")
    st.stop()

# --- SIDEBAR ---
st.sidebar.title("Dressing Manager")
menu = st.sidebar.radio("Menu", ["Dashboard", "Orders", "Stock Management", "Admin"])

# --- PAGES ---
if menu == "Dashboard":
    st.title("📊 Dashboard")
    fin = df_fin.iloc[0]
    
    # Calcul Pending
    pending_rev = df_orders[df_orders["status"] != "Delivered"]["price"].sum() if not df_orders.empty else 0.0
    pending_prof = df_orders[df_orders["status"] != "Delivered"]["profit"].sum() if not df_orders.empty else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Realized Revenue", f"{fin['Revenue']:.2f}€")
    c2.metric("Realized Profit", f"{fin['Profit']:.2f}€")
    c3.metric("Pending Revenue", f"{pending_rev:.2f}€")
    c4.metric("Pending Profit", f"{pending_prof:.2f}€")
    
    st.divider()
    st.subheader("📦 Current Stock")
    
    # Clean display for stock
    display_stock = df_stock.copy()
    display_stock["Total Value"] = display_stock["Qty"] * display_stock["Avg_Cost"]
    st.dataframe(display_stock, use_container_width=True, hide_index=True)

elif menu == "Orders":
    st.title("📦 Order Tracking")
    
    with st.expander("➕ New Order (Sell)", expanded=False):
        c1, c2, c3 = st.columns(3)
        sel_prod = c1.selectbox("Product", PRODUCTS)
        client = c2.text_input("Customer Name")
        price = c3.number_input("Selling Price (€)", min_value=0.0, step=1.0)
        
        if st.button("Create Order"):
            # Check Stock
            idx = df_stock.index[df_stock["Product"] == sel_prod].tolist()[0]
            current_qty = df_stock.at[idx, "Qty"]
            avg_cost = df_stock.at[idx, "Avg_Cost"]
            
            if current_qty > 0:
                # Update Stock
                df_stock.at[idx, "Qty"] -= 1
                
                # Add Order
                profit = price - avg_cost
                new_id = len(df_orders) + 1000
                new_ord = pd.DataFrame([{
                    "id": new_id, "date": datetime.now().strftime('%Y-%m-%d'),
                    "client": client, "product": sel_prod,
                    "price": price, "profit": profit, "status": "Processing"
                }])
                df_orders = pd.concat([df_orders, new_ord], ignore_index=True)
                
                # Log & Save
                df_hist = log_action(f"ORDER: {sel_prod} for {client}", df_hist)
                save_all(df_stock, df_orders, df_fin, df_hist)
                st.success("Order Created!")
                st.rerun()
            else:
                st.error("Out of Stock!")

    st.divider()
    if not df_orders.empty:
        # Show only active columns
        st.dataframe(df_orders, use_container_width=True, hide_index=True)
        
        st.subheader("Update Order Status")
        # Filter pending orders for selection
        pending_list = df_orders[df_orders["status"] != "Delivered"]
        
        if not pending_list.empty:
            opts = {f"{row['id']} - {row['client']}": row['id'] for idx, row in pending_list.iterrows()}
            sel_order_str = st.selectbox("Select Order", list(opts.keys()))
            sel_id = opts[sel_order_str]
            
            c1, c2 = st.columns(2)
            if c1.button("Mark Shipped"):
                idx = df_orders.index[df_orders["id"] == sel_id].tolist()[0]
                df_orders.at[idx, "status"] = "Shipped"
                df_hist = log_action(f"SHIPPED: Order #{sel_id}", df_hist)
                save_all(df_stock, df_orders, df_fin, df_hist)
                st.success("Updated to Shipped")
                st.rerun()
                
            if c2.button("Mark Delivered (Money In)"):
                idx = df_orders.index[df_orders["id"] == sel_id].tolist()[0]
                df_orders.at[idx, "status"] = "Delivered"
                
                # Update Money
                ord_price = df_orders.at[idx, "price"]
                ord_prof = df_orders.at[idx, "profit"]
                df_fin.at[0, "Revenue"] += ord_price
                df_fin.at[0, "Profit"] += ord_prof
                
                df_hist = log_action(f"DELIVERED: Order #{sel_id} (+{ord_prof:.2f}€)", df_hist)
                save_all(df_stock, df_orders, df_fin, df_hist)
                st.balloons()
                st.rerun()
        else:
            st.info("No pending orders.")

elif menu == "Stock Management":
    st.title("🏭 Restock")
    c1, c2, c3 = st.columns(3)
    p_restock = c1.selectbox("Product", PRODUCTS)
    q_restock = c2.number_input("Qty Received", 1)
    cost_restock = c3.number_input("Total Cost (€)", 0.0)
    
    if st.button("Add Stock"):
        idx = df_stock.index[df_stock["Product"] == p_restock].tolist()[0]
        curr_qty = df_stock.at[idx, "Qty"]
        curr_avg = df_stock.at[idx, "Avg_Cost"]
        
        new_val = (curr_qty * curr_avg) + cost_restock
        new_qty = curr_qty + q_restock
        new_avg = new_val / new_qty if new_qty > 0 else 0
        
        df_stock.at[idx, "Qty"] = new_qty
        df_stock.at[idx, "Avg_Cost"] = new_avg
        
        df_fin.at[0, "Expenses"] += cost_restock
        df_hist = log_action(f"BUY: {q_restock}x {p_restock} (-{cost_restock}€)", df_hist)
        save_all(df_stock, df_orders, df_fin, df_hist)
        st.success("Stock Added!")
        st.rerun()

elif menu == "Admin":
    st.title("⚙️ Admin")
    st.write(f"Total Expenses: {df_fin.iloc[0]['Expenses']:.2f}€")
    
    if st.button("📄 Download Report PDF"):
        pdf_file = generate_pdf(df_fin, df_orders)
        st.download_button("Download Now", pdf_file, file_name=f"Report_{datetime.now().strftime('%B')}.pdf", mime="application/pdf")
        
    st.divider()
    if st.button("📅 Start New Month (Reset Revenue)"):
        df_fin.at[0, "Revenue"] = 0.0
        df_fin.at[0, "Profit"] = 0.0
        df_fin.at[0, "Expenses"] = 0.0
        df_hist = log_action("NEW MONTH STARTED", df_hist)
        save_all(df_stock, df_orders, df_fin, df_hist)
        st.warning("Month reset done.")
        st.rerun()
        
    st.subheader("Logs")
    st.dataframe(df_hist, use_container_width=True)

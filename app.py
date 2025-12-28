import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import time

# --- CONFIGURATION ---
st.set_page_config(page_title="Vinted Manager", layout="wide", page_icon="📦")
PRODUCTS = ["Black Belt", "Brown Belt", "White Belt", "Bordeaux Belt", "LV Belt"]

# --- CONNEXION GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FONCTIONS UTILITAIRES ---
def clean_decimal(val):
    """Transforme '12,50' (texte) en 12.50 (nombre) pour éviter les crashs."""
    if isinstance(val, str):
        clean_val = val.replace(',', '.').replace('€', '').strip()
        try:
            return float(clean_val)
        except ValueError:
            return 0.0
    return float(val) if val else 0.0

def get_data():
    """Récupère les données avec 3 tentatives automatiques (Anti-Crash)."""
    for attempt in range(3):
        try:
            df_stock = conn.read(worksheet="Stock", usecols=[0,1,2], ttl=0)
            df_orders = conn.read(worksheet="Orders", ttl=0)
            df_fin = conn.read(worksheet="Financials", ttl=0)
            df_hist = conn.read(worksheet="History", ttl=0)
            break 
        except Exception as e:
            if attempt == 2:
                st.error(f"⚠️ Google Connection Error: {e}")
                st.stop()
            time.sleep(1)
    
    # Initialisation
    if df_stock.empty or len(df_stock.columns) < 2:
        df_stock = pd.DataFrame({"Product": PRODUCTS, "Qty": [0]*5, "Avg_Cost": [0.0]*5})
    if df_fin.empty:
        df_fin = pd.DataFrame([{"Revenue": 0.0, "Profit": 0.0, "Expenses": 0.0}])
    if "Status" not in df_orders.columns:
        df_orders = pd.DataFrame(columns=["id", "date", "client", "product", "price", "profit", "status"])
    if df_hist.empty:
        df_hist = pd.DataFrame(columns=["log"])

    # Nettoyage des nombres
    if "Avg_Cost" in df_stock.columns:
        df_stock["Avg_Cost"] = df_stock["Avg_Cost"].apply(clean_decimal)
        df_stock["Qty"] = pd.to_numeric(df_stock["Qty"], errors='coerce').fillna(0).astype(int)

    for c in ["price", "profit"]:
        if c in df_orders.columns:
            df_orders[c] = df_orders[c].apply(clean_decimal)

    for c in ["Revenue", "Profit", "Expenses"]:
        if c in df_fin.columns:
            df_fin[c] = df_fin[c].apply(clean_decimal)
        
    return df_stock, df_orders, df_fin, df_hist

def save_all(df_stock, df_orders, df_fin, df_hist):
    """Sauvegarde avec retry (Anti-Crash)."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn.update(worksheet="Stock", data=df_stock)
            conn.update(worksheet="Orders", data=df_orders)
            conn.update(worksheet="Financials", data=df_fin)
            conn.update(worksheet="History", data=df_hist)
            st.cache_data.clear()
            # st.toast("Saved!", icon="✅") # Optionnel pour moins de notifs
            return
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(1.5)
                continue
            else:
                st.error("❌ Save failed. Google API is busy. Wait a few seconds.")

def log_action(msg, df_hist):
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {msg}"
    new_row = pd.DataFrame([{"log": entry}])
    return pd.concat([new_row, df_hist], ignore_index=True)

# --- PDF GENERATOR ---
def generate_pdf(df_fin, df_orders):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 800, f"Report - {datetime.now().strftime('%B %Y')}")
    c.setFont("Helvetica", 12)
    fin = df_fin.iloc[0]
    c.drawString(50, 760, f"Revenue: {fin['Revenue']:.2f} EUR")
    c.drawString(50, 740, f"Profit: {fin['Profit']:.2f} EUR")
    c.drawString(50, 720, f"Expenses: {fin['Expenses']:.2f} EUR")
    c.drawString(50, 680, "Delivered Orders:")
    y = 660
    c.setFont("Helvetica", 10)
    for index, row in df_orders.iterrows():
        if row["status"] == "Delivered":
            if y < 50: c.showPage(); y = 800
            c.drawString(50, y, f"{row['date']} - {row['client']} - {row['product']} - {row['price']:.2f} EUR")
            y -= 15
    c.save()
    buffer.seek(0)
    return buffer

# --- LOAD DATA ---
df_stock, df_orders, df_fin, df_hist = get_data()

# --- SIDEBAR ---
st.sidebar.title("Dressing Manager")
menu = st.sidebar.radio("Navigation", ["Dashboard", "Order Tracking", "Stock Management", "Admin"])

# --- PAGES ---
if menu == "Dashboard":
    st.title("📊 Dashboard")
    try:
        fin = df_fin.iloc[0]
    except:
        fin = {"Revenue": 0, "Profit": 0, "Expenses": 0}
    
    pending_rev = df_orders[df_orders["status"] != "Delivered"]["price"].sum() if not df_orders.empty else 0.0
    pending_prof = df_orders[df_orders["status"] != "Delivered"]["profit"].sum() if not df_orders.empty else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue", f"{fin['Revenue']:.2f}€")
    c2.metric("Profit", f"{fin['Profit']:.2f}€")
    c3.metric("Pending", f"{pending_rev:.2f}€")
    c4.metric("Expenses", f"{fin['Expenses']:.2f}€")
    
    st.divider()
    st.subheader("📦 Stock Level")
    display_stock = df_stock.copy()
    display_stock["Total Value"] = display_stock["Qty"] * display_stock["Avg_Cost"]
    st.dataframe(display_stock, width="stretch", hide_index=True)

elif menu == "Order Tracking":
    st.title("📦 Order Tracking")
    
    # Formulaire création
    with st.expander("➕ New Order", expanded=False):
        c1, c2, c3 = st.columns(3)
        sel_prod = c1.selectbox("Product", PRODUCTS)
        client = c2.text_input("Buyer Name")
        price = c3.number_input("Sold Price (€)", min_value=0.0, step=0.01, format="%.2f")
        
        if st.button("Add Order", type="primary"):
            idx_list = df_stock.index[df_stock["Product"] == sel_prod].tolist()
            if idx_list:
                idx = idx_list[0]
                current_qty = df_stock.at[idx, "Qty"]
                avg_cost = df_stock.at[idx, "Avg_Cost"]
                
                if current_qty > 0:
                    df_stock.at[idx, "Qty"] -= 1
                    profit = price - avg_cost
                    new_id = len(df_orders) + 1000
                    new_ord = pd.DataFrame([{
                        "id": new_id, "date": datetime.now().strftime('%Y-%m-%d'),
                        "client": client, "product": sel_prod,
                        "price": price, "profit": profit, "status": "Processing"
                    }])
                    df_orders = pd.concat([df_orders, new_ord], ignore_index=True)
                    df_hist = log_action(f"SOLD: {sel_prod} to {client}", df_hist)
                    save_all(df_stock, df_orders, df_fin, df_hist)
                    st.success("Order Added!")
                    st.rerun()
                else:
                    st.error("No Stock!")
            else:
                st.error("Product invalid.")

    st.divider()
    st.subheader("Active Orders")
    
    if df_orders.empty:
        st.info("No orders yet.")
    else:
        # En-têtes de colonnes
        h1, h2, h3, h4, h5 = st.columns([1, 2, 2, 1, 2])
        h1.markdown("**Date**")
        h2.markdown("**Product**")
        h3.markdown("**Client**")
        h4.markdown("**Price**")
        h5.markdown("**Status (Click to update)**")
        st.markdown("---")

        # Affichage Ligne par Ligne
        # On trie pour avoir les plus récents en haut
        for index, row in df_orders.sort_values("id", ascending=False).iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 1, 2])
            
            c1.write(row['date'])
            c2.write(row['product'])
            c3.write(row['client'])
            c4.write(f"{row['price']:.2f}€")
            
            # --- LOGIQUE DES BOUTONS COULEURS ---
            status = row['status']
            unique_key = f"btn_{row['id']}" # Clé unique obligatoire
            
            if status == "Processing":
                # ÉTAT 1 : Rouge -> Orange
                if c5.button("🔴 To Ship", key=unique_key, type="primary"):
                    df_orders.at[index, "status"] = "Shipped"
                    df_hist = log_action(f"SHIPPED: Order #{row['id']}", df_hist)
                    save_all(df_stock, df_orders, df_fin, df_hist)
                    st.rerun()
            
            elif status == "Shipped":
                # ÉTAT 2 : Orange (simulé par emoji) -> Vert
                if c5.button("🟠 Mark Delivered", key=unique_key):
                    df_orders.at[index, "status"] = "Delivered"
                    # Encaissement
                    df_fin.at[0, "Revenue"] += row['price']
                    df_fin.at[0, "Profit"] += row['profit']
                    df_hist = log_action(f"PAID: Order #{row['id']}", df_hist)
                    save_all(df_stock, df_orders, df_fin, df_hist)
                    st.balloons()
                    st.rerun()
            
            elif status == "Delivered":
                # ÉTAT 3 : Vert (Fini)
                c5.button("🟢 Received", key=unique_key, disabled=True)

elif menu == "Stock Management":
    st.title("🏭 Restock")
    c1, c2, c3 = st.columns(3)
    p_restock = c1.selectbox("Product", PRODUCTS)
    q_restock = c2.number_input("Qty Received", 1)
    cost_restock = c3.number_input("Total Cost (€)", 0.0, step=0.01, format="%.2f")
    
    if st.button("Add Stock"):
        idx_list = df_stock.index[df_stock["Product"] == p_restock].tolist()
        if idx_list:
            idx = idx_list[0]
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
        else:
            st.error("Product error.")

elif menu == "Admin":
    st.title("⚙️ Admin")
    if st.button("Download PDF Report"):
        pdf_file = generate_pdf(df_fin, df_orders)
        st.download_button("Download PDF", pdf_file, "Report.pdf", "application/pdf")
        
    st.divider()
    if st.button("Start New Month (Reset Revenue)"):
        df_fin.at[0, "Revenue"] = 0.0
        df_fin.at[0, "Profit"] = 0.0
        df_fin.at[0, "Expenses"] = 0.0
        df_hist = log_action("NEW MONTH", df_hist)
        save_all(df_stock, df_orders, df_fin, df_hist)
        st.rerun()
        
    st.subheader("Logs")
    st.dataframe(df_hist, width="stretch")

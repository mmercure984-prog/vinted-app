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

# --- CONNEXION ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FONCTIONS UTILITAIRES ---
def clean_decimal(val):
    if isinstance(val, str):
        clean_val = val.replace(',', '.').replace('€', '').strip()
        try:
            return float(clean_val)
        except ValueError:
            return 0.0
    return float(val) if val else 0.0

def init_empty_dfs():
    """Crée des DataFrames vides si chargement échoue."""
    return (
        pd.DataFrame({"Product": PRODUCTS, "Qty": [0]*5, "Avg_Cost": [0.0]*5}),
        pd.DataFrame(columns=["id", "date", "client", "product", "price", "profit", "status"]),
        pd.DataFrame([{"Revenue": 0.0, "Profit": 0.0, "Expenses": 0.0}]),
        pd.DataFrame(columns=["log"])
    )

def load_data_from_google():
    """Charge depuis Google Sheets (consomme du quota)."""
    try:
        df_stock = conn.read(worksheet="Stock", usecols=[0,1,2], ttl=0)
        df_orders = conn.read(worksheet="Orders", ttl=0)
        df_fin = conn.read(worksheet="Financials", ttl=0)
        df_hist = conn.read(worksheet="History", ttl=0)
        
        # Nettoyage
        if "Avg_Cost" in df_stock.columns:
            df_stock["Avg_Cost"] = df_stock["Avg_Cost"].apply(clean_decimal)
            df_stock["Qty"] = pd.to_numeric(df_stock["Qty"], errors='coerce').fillna(0).astype(int)
        for c in ["price", "profit"]:
            if c in df_orders.columns: df_orders[c] = df_orders[c].apply(clean_decimal)
        for c in ["Revenue", "Profit", "Expenses"]:
            if c in df_fin.columns: df_fin[c] = df_fin[c].apply(clean_decimal)
            
        return df_stock, df_orders, df_fin, df_hist
    except Exception as e:
        st.error(f"Erreur de chargement Google : {e}")
        return init_empty_dfs()

# --- GESTION DE LA MÉMOIRE (SESSION STATE) ---
if "data_loaded" not in st.session_state:
    st.session_state.df_stock, st.session_state.df_orders, st.session_state.df_fin, st.session_state.df_hist = load_data_from_google()
    st.session_state.data_loaded = True

def force_reload():
    """Force le rechargement manuel depuis Google."""
    st.session_state.df_stock, st.session_state.df_orders, st.session_state.df_fin, st.session_state.df_hist = load_data_from_google()
    st.toast("Données rechargées depuis Google !", icon="🔄")
    st.rerun()

def save_changes(sheets_to_update=["Orders"]):
    """
    Sauvegarde uniquement les feuilles modifiées vers Google.
    NE RELIT PAS les données pour économiser le quota.
    """
    try:
        if "Stock" in sheets_to_update:
            conn.update(worksheet="Stock", data=st.session_state.df_stock)
        if "Orders" in sheets_to_update:
            conn.update(worksheet="Orders", data=st.session_state.df_orders)
        if "Financials" in sheets_to_update:
            conn.update(worksheet="Financials", data=st.session_state.df_fin)
        if "History" in sheets_to_update:
            conn.update(worksheet="History", data=st.session_state.df_hist)
        # On ne clear PAS le cache ici, on fait confiance à session_state
    except Exception as e:
        st.warning(f"Sauvegarde Cloud échouée (Quota ?), mais données locales OK. Erreur: {e}")

def log_action(msg):
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {msg}"
    new_row = pd.DataFrame([{"log": entry}])
    st.session_state.df_hist = pd.concat([new_row, st.session_state.df_hist], ignore_index=True)
    save_changes(["History"])

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

# --- SIDEBAR ---
st.sidebar.title("Dressing Manager")
menu = st.sidebar.radio("Navigation", ["Dashboard", "Order Tracking", "Stock Management", "Admin"])
if st.sidebar.button("🔄 Forcer Actualisation"):
    force_reload()

# --- PAGES ---
if menu == "Dashboard":
    st.title("📊 Dashboard")
    df_fin = st.session_state.df_fin
    df_orders = st.session_state.df_orders
    
    fin = df_fin.iloc[0] if not df_fin.empty else {"Revenue": 0, "Profit": 0, "Expenses": 0}
    pending_rev = df_orders[df_orders["status"] != "Delivered"]["price"].sum() if not df_orders.empty else 0.0
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("CA Encaissé", f"{fin['Revenue']:.2f}€")
    c2.metric("Bénéfice Net", f"{fin['Profit']:.2f}€")
    c3.metric("En attente", f"{pending_rev:.2f}€")
    c4.metric("Dépenses", f"{fin['Expenses']:.2f}€")
    
    st.divider()
    st.subheader("📦 Niveau de Stock")
    display_stock = st.session_state.df_stock.copy()
    display_stock["Total Value"] = display_stock["Qty"] * display_stock["Avg_Cost"]
    st.dataframe(display_stock, use_container_width=True, hide_index=True)

elif menu == "Order Tracking":
    st.title("📦 Suivi des Commandes")
    
    with st.expander("➕ Nouvelle Commande", expanded=False):
        c1, c2, c3 = st.columns(3)
        sel_prod = c1.selectbox("Produit", PRODUCTS)
        client = c2.text_input("Acheteur")
        price = c3.number_input("Prix Vente (€)", min_value=0.0, step=0.01, format="%.2f")
        
        if st.button("Ajouter", type="primary"):
            df_stock = st.session_state.df_stock
            idx_list = df_stock.index[df_stock["Product"] == sel_prod].tolist()
            
            if idx_list:
                idx = idx_list[0]
                current_qty = df_stock.at[idx, "Qty"]
                avg_cost = df_stock.at[idx, "Avg_Cost"]
                
                if current_qty > 0:
                    # 1. Mise à jour Locale (Instantané)
                    st.session_state.df_stock.at[idx, "Qty"] -= 1
                    profit = price - avg_cost
                    new_id = len(st.session_state.df_orders) + 1000
                    new_ord = pd.DataFrame([{
                        "id": new_id, "date": datetime.now().strftime('%Y-%m-%d'),
                        "client": client, "product": sel_prod,
                        "price": price, "profit": profit, "status": "Processing"
                    }])
                    st.session_state.df_orders = pd.concat([st.session_state.df_orders, new_ord], ignore_index=True)
                    log_action(f"VENTE: {sel_prod} à {client}")
                    
                    # 2. Sauvegarde Cloud ciblée
                    save_changes(["Stock", "Orders"])
                    st.success("Commande ajoutée !")
                    st.rerun()
                else:
                    st.error("Pas de stock !")
            else:
                st.error("Produit introuvable.")

    st.divider()
    df_orders = st.session_state.df_orders
    if df_orders.empty:
        st.info("Aucune commande.")
    else:
        h1, h2, h3, h4, h5 = st.columns([1, 2, 2, 1, 2])
        h1.markdown("**Date**")
        h2.markdown("**Produit**")
        h3.markdown("**Client**")
        h4.markdown("**Prix**")
        h5.markdown("**Statut**")
        st.markdown("---")

        for index, row in df_orders.sort_values("id", ascending=False).iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 1, 2])
            c1.write(row['date'])
            c2.write(row['product'])
            c3.write(row['client'])
            c4.write(f"{row['price']:.2f}€")
            
            status = row['status']
            unique_key = f"btn_{row['id']}" 
            
            if status == "Processing":
                if c5.button("🔴 Envoyer", key=unique_key, type="primary"):
                    st.session_state.df_orders.at[index, "status"] = "Shipped"
                    log_action(f"ENVOI: Cmd #{row['id']}")
                    save_changes(["Orders"])
                    st.rerun()
            
            elif status == "Shipped":
                if c5.button("🟠 Livré (Encaisser)", key=unique_key):
                    st.session_state.df_orders.at[index, "status"] = "Delivered"
                    st.session_state.df_fin.at[0, "Revenue"] += row['price']
                    st.session_state.df_fin.at[0, "Profit"] += row['profit']
                    log_action(f"PAYÉ: Cmd #{row['id']}")
                    save_changes(["Orders", "Financials"])
                    st.balloons()
                    st.rerun()
            
            elif status == "Delivered":
                c5.button("🟢 Reçu", key=unique_key, disabled=True)

elif menu == "Stock Management":
    st.title("🏭 Achat / Stock")
    c1, c2, c3 = st.columns(3)
    p_restock = c1.selectbox("Produit", PRODUCTS)
    q_restock = c2.number_input("Qté Reçue", 1)
    cost_restock = c3.number_input("Coût Total (€)", 0.0, step=0.01, format="%.2f")
    
    if st.button("Ajouter Stock"):
        df_stock = st.session_state.df_stock
        idx_list = df_stock.index[df_stock["Product"] == p_restock].tolist()
        
        if idx_list:
            idx = idx_list[0]
            curr_qty = df_stock.at[idx, "Qty"]
            curr_avg = df_stock.at[idx, "Avg_Cost"]
            
            new_val = (curr_qty * curr_avg) + cost_restock
            new_qty = curr_qty + q_restock
            new_avg = new_val / new_qty if new_qty > 0 else 0
            
            st.session_state.df_stock.at[idx, "Qty"] = new_qty
            st.session_state.df_stock.at[idx, "Avg_Cost"] = new_avg
            st.session_state.df_fin.at[0, "Expenses"] += cost_restock
            
            log_action(f"ACHAT: {q_restock}x {p_restock}")
            save_changes(["Stock", "Financials"])
            st.success("Stock ajouté !")
            st.rerun()

elif menu == "Admin":
    st.title("⚙️ Admin")
    if st.button("Télécharger Rapport PDF"):
        pdf_file = generate_pdf(st.session_state.df_fin, st.session_state.df_orders)
        st.download_button("Download PDF", pdf_file, "Report.pdf", "application/pdf")
        
    st.divider()
    if st.button("Nouveau Mois (Reset CA)"):
        st.session_state.df_fin.at[0, "Revenue"] = 0.0
        st.session_state.df_fin.at[0, "Profit"] = 0.0
        st.session_state.df_fin.at[0, "Expenses"] = 0.0
        log_action("RESET MOIS")
        save_changes(["Financials"])
        st.rerun()
        
    st.subheader("Logs")
    st.dataframe(st.session_state.df_hist, use_container_width=True)

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

# --- UTILITAIRES ---
def clean_decimal(val):
    if isinstance(val, str):
        clean_val = val.replace(',', '.').replace('€', '').strip()
        try:
            return float(clean_val)
        except ValueError:
            return 0.0
    return float(val) if val else 0.0

def init_empty_dfs():
    """Génère des données vides pour le mode Hors Ligne."""
    return (
        pd.DataFrame({"Product": PRODUCTS, "Qty": [0]*5, "Avg_Cost": [0.0]*5}),
        pd.DataFrame(columns=["id", "date", "client", "product", "price", "profit", "status"]),
        pd.DataFrame([{"Revenue": 0.0, "Profit": 0.0, "Expenses": 0.0}]),
        pd.DataFrame(columns=["log"])
    )

def load_data_initial():
    """Charge les données UNE SEULE FOIS au démarrage."""
    try:
        # On enlève ttl=0 pour utiliser le cache et économiser le quota
        df_stock = conn.read(worksheet="Stock", usecols=[0,1,2])
        df_orders = conn.read(worksheet="Orders")
        df_fin = conn.read(worksheet="Financials")
        df_hist = conn.read(worksheet="History")
        
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
        st.warning(f"⚠️ Démarrage en mode hors ligne (Google saturé). Tes modifs seront locales.")
        return init_empty_dfs()

# --- GESTION ÉTAT (SESSION STATE) ---
# C'est le cœur du système : on ne charge qu'une fois
if "data_loaded" not in st.session_state:
    st.session_state.df_stock, st.session_state.df_orders, st.session_state.df_fin, st.session_state.df_hist = load_data_initial()
    st.session_state.data_loaded = True
    st.session_state.unsaved_changes = False # Pour suivre l'état de la sauvegarde

def try_save_to_cloud():
    """Tente de sauvegarder sans faire planter l'appli."""
    try:
        conn.update(worksheet="Stock", data=st.session_state.df_stock)
        conn.update(worksheet="Orders", data=st.session_state.df_orders)
        conn.update(worksheet="Financials", data=st.session_state.df_fin)
        conn.update(worksheet="History", data=st.session_state.df_hist)
        st.session_state.unsaved_changes = False
        st.toast("Sauvegarde Cloud OK !", icon="✅")
        return True
    except Exception as e:
        st.session_state.unsaved_changes = True
        # On n'affiche pas d'erreur bloquante, juste un toast discret
        st.toast("Google saturé. Sauvegarde reportée.", icon="⚠️")
        return False

def log_action(msg):
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {msg}"
    new_row = pd.DataFrame([{"log": entry}])
    st.session_state.df_hist = pd.concat([new_row, st.session_state.df_hist], ignore_index=True)
    st.session_state.unsaved_changes = True # On marque qu'il y a des changements

# --- PDF ---
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

# --- INTERFACE ---
st.sidebar.title("Dressing Manager")

# INDICATEUR D'ÉTAT
if st.session_state.unsaved_changes:
    st.sidebar.warning("⚠️ Changements non synchronisés")
    if st.sidebar.button("💾 Forcer la sauvegarde maintenant"):
        try_save_to_cloud()
else:
    st.sidebar.success("✅ Synchronisé avec Google")

menu = st.sidebar.radio("Navigation", ["Dashboard", "Commandes", "Stock", "Admin"])

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
    st.subheader("📦 Stock Actuel")
    ds = st.session_state.df_stock.copy()
    ds["Total Value"] = ds["Qty"] * ds["Avg_Cost"]
    st.dataframe(ds, use_container_width=True, hide_index=True)

elif menu == "Commandes":
    st.title("📦 Suivi Commandes")
    
    with st.expander("➕ Ajouter Commande", expanded=False):
        c1, c2, c3 = st.columns(3)
        sel_prod = c1.selectbox("Produit", PRODUCTS)
        client = c2.text_input("Client")
        price = c3.number_input("Prix (€)", 0.0, step=0.5, format="%.2f")
        
        if st.button("Valider", type="primary"):
            df_s = st.session_state.df_stock
            idx_l = df_s.index[df_s["Product"] == sel_prod].tolist()
            if idx_l:
                idx = idx_l[0]
                if df_s.at[idx, "Qty"] > 0:
                    # 1. Update Mémoire (Immédiat)
                    st.session_state.df_stock.at[idx, "Qty"] -= 1
                    profit = price - df_s.at[idx, "Avg_Cost"]
                    new_id = len(st.session_state.df_orders) + 1000
                    new_ord = pd.DataFrame([{
                        "id": new_id, "date": datetime.now().strftime('%Y-%m-%d'),
                        "client": client, "product": sel_prod,
                        "price": price, "profit": profit, "status": "Processing"
                    }])
                    st.session_state.df_orders = pd.concat([st.session_state.df_orders, new_ord], ignore_index=True)
                    log_action(f"VENTE: {sel_prod}")
                    
                    # 2. Tentative Sauvegarde (Silencieuse)
                    try_save_to_cloud()
                    st.success("Commande ajoutée (Mémoire OK)")
                    st.rerun()
                else:
                    st.error("Pas de stock !")
            else:
                st.error("Produit inconnu")

    st.divider()
    df_o = st.session_state.df_orders
    if df_o.empty:
        st.info("Aucune commande")
    else:
        h1, h2, h3, h4, h5 = st.columns([1,2,2,1,2])
        h1.write("**Date**")
        h2.write("**Produit**")
        h3.write("**Client**")
        h4.write("**Prix**")
        h5.write("**Action**")
        st.markdown("---")
        
        for idx, row in df_o.sort_values("id", ascending=False).iterrows():
            c1, c2, c3, c4, c5 = st.columns([1,2,2,1,2])
            c1.write(row['date'])
            c2.write(row['product'])
            c3.write(row['client'])
            c4.write(f"{row['price']:.2f}€")
            
            key = f"btn_{row['id']}"
            if row['status'] == "Processing":
                if c5.button("🔴 Envoyer", key=key, type="primary"):
                    st.session_state.df_orders.at[idx, "status"] = "Shipped"
                    log_action(f"ENVOI #{row['id']}")
                    try_save_to_cloud()
                    st.rerun()
            elif row['status'] == "Shipped":
                if c5.button("🟠 Encaisser", key=key):
                    st.session_state.df_orders.at[idx, "status"] = "Delivered"
                    st.session_state.df_fin.at[0, "Revenue"] += row['price']
                    st.session_state.df_fin.at[0, "Profit"] += row['profit']
                    log_action(f"ENC # {row['id']}")
                    try_save_to_cloud()
                    st.balloons()
                    st.rerun()
            else:
                c5.button("🟢 Terminé", key=key, disabled=True)

elif menu == "Stock":
    st.title("🏭 Achat / Stock")
    c1, c2, c3 = st.columns(3)
    p = c1.selectbox("Produit", PRODUCTS)
    q = c2.number_input("Qté", 1)
    cost = c3.number_input("Coût (€)", 0.0)
    
    if st.button("Ajouter Stock"):
        df_s = st.session_state.df_stock
        idx_l = df_s.index[df_s["Product"] == p].tolist()
        if idx_l:
            idx = idx_l[0]
            curr_q = df_s.at[idx, "Qty"]
            curr_avg = df_s.at[idx, "Avg_Cost"]
            new_val = (curr_q * curr_avg) + cost
            new_q = curr_q + q
            new_avg = new_val / new_q if new_q > 0 else 0
            
            st.session_state.df_stock.at[idx, "Qty"] = new_q
            st.session_state.df_stock.at[idx, "Avg_Cost"] = new_avg
            st.session_state.df_fin.at[0, "Expenses"] += cost
            log_action(f"ACHAT {q} {p}")
            try_save_to_cloud()
            st.success("Stock mis à jour")
            st.rerun()

elif menu == "Admin":
    st.title("⚙️ Admin")
    if st.button("Download PDF"):
        pdf = generate_pdf(st.session_state.df_fin, st.session_state.df_orders)
        st.download_button("PDF", pdf, "report.pdf")
    
    if st.button("Reset Mois"):
        st.session_state.df_fin.at[0, "Revenue"] = 0
        st.session_state.df_fin.at[0, "Profit"] = 0
        st.session_state.df_fin.at[0, "Expenses"] = 0
        log_action("RESET")
        try_save_to_cloud()
        st.rerun()
        
    st.write("Logs:")
    st.dataframe(st.session_state.df_hist, use_container_width=True)

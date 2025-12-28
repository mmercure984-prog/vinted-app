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

# --- LECTURE INTELLIGENTE (CACHE) ---
# Le décorateur ci-dessous active la mémoire. ttl=300 veut dire "Garde en mémoire 5 min"
@st.cache_data(ttl=300)
def get_data_from_cache():
    """Charge les données depuis Google uniquement si le cache est vide/expiré."""
    try:
        # On ne met pas ttl=0 ici, on laisse le connecteur gérer
        df_stock = conn.read(worksheet="Stock", usecols=[0,1,2])
        df_orders = conn.read(worksheet="Orders")
        df_fin = conn.read(worksheet="Financials")
        df_hist = conn.read(worksheet="History")
        return df_stock, df_orders, df_fin, df_hist
    except Exception as e:
        # Si erreur de quota, on renvoie None pour gérer plus tard
        return None, None, None, None

def get_data():
    """Wrapper pour nettoyer les données après chargement."""
    df_stock, df_orders, df_fin, df_hist = get_data_from_cache()
    
    # Si Google bloque encore, on attend un peu et on réessaie une fois
    if df_stock is None:
        time.sleep(2)
        st.cache_data.clear() # On force le nettoyage
        df_stock, df_orders, df_fin, df_hist = get_data_from_cache()
        if df_stock is None:
            st.error("🚨 Google sature. Attends 1 minute avant de rafraîchir.")
            st.stop()

    # Initialisation sécurisée
    if df_stock.empty or len(df_stock.columns) < 2:
        df_stock = pd.DataFrame({"Product": PRODUCTS, "Qty": [0]*5, "Avg_Cost": [0.0]*5})
    if df_fin.empty:
        df_fin = pd.DataFrame([{"Revenue": 0.0, "Profit": 0.0, "Expenses": 0.0}])
    if "Status" not in df_orders.columns:
        df_orders = pd.DataFrame(columns=["id", "date", "client", "product", "price", "profit", "status"])
    if df_hist.empty:
        df_hist = pd.DataFrame(columns=["log"])

    # Nettoyage des virgules
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
    """Sauvegarde et VIDE le cache pour voir les changements."""
    try:
        conn.update(worksheet="Stock", data=df_stock)
        conn.update(worksheet="Orders", data=df_orders)
        conn.update(worksheet="Financials", data=df_fin)
        conn.update(worksheet="History", data=df_hist)
        
        # C'est ici la magie : on vide le cache SEULEMENT après une modif
        st.cache_data.clear() 
        return True
    except Exception as e:
        if "Quota" in str(e) or "429" in str(e):
            st.warning("⚠️ Trop rapide ! Attends 30 secondes et réessaie.")
        else:
            st.error(f"Erreur de sauvegarde : {e}")
        return False

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
    c1.metric("CA Encaissé", f"{fin['Revenue']:.2f}€")
    c2.metric("Bénéfice Net", f"{fin['Profit']:.2f}€")
    c3.metric("En attente", f"{pending_rev:.2f}€")
    c4.metric("Dépenses", f"{fin['Expenses']:.2f}€")
    
    st.divider()
    st.subheader("📦 Niveau de Stock")
    display_stock = df_stock.copy()
    display_stock["Total Value"] = display_stock["Qty"] * display_stock["Avg_Cost"]
    st.dataframe(display_stock, width="stretch", hide_index=True)

elif menu == "Order Tracking":
    st.title("📦 Suivi des Commandes")
    
    # Formulaire
    with st.expander("➕ Nouvelle Commande", expanded=False):
        c1, c2, c3 = st.columns(3)
        sel_prod = c1.selectbox("Produit", PRODUCTS)
        client = c2.text_input("Acheteur")
        price = c3.number_input("Prix Vente (€)", min_value=0.0, step=0.01, format="%.2f")
        
        if st.button("Ajouter", type="primary"):
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
                    df_hist = log_action(f"VENTE: {sel_prod} à {client}", df_hist)
                    if save_all(df_stock, df_orders, df_fin, df_hist):
                        st.success("Commande ajoutée !")
                        st.rerun()
                else:
                    st.error("Pas de stock !")
            else:
                st.error("Erreur produit.")

    st.divider()
    
    if df_orders.empty:
        st.info("Aucune commande.")
    else:
        # En-têtes
        h1, h2, h3, h4, h5 = st.columns([1, 2, 2, 1, 2])
        h1.markdown("**Date**")
        h2.markdown("**Produit**")
        h3.markdown("**Client**")
        h4.markdown("**Prix**")
        h5.markdown("**Statut (Clic pour changer)**")
        st.markdown("---")

        # Liste commandes
        for index, row in df_orders.sort_values("id", ascending=False).iterrows():
            c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 1, 2])
            
            c1.write(row['date'])
            c2.write(row['product'])
            c3.write(row['client'])
            c4.write(f"{row['price']:.2f}€")
            
            status = row['status']
            unique_key = f"btn_{row['id']}" 
            
            if status == "Processing":
                # Rouge -> Orange
                if c5.button("🔴 Envoyer", key=unique_key, type="primary"):
                    df_orders.at[index, "status"] = "Shipped"
                    df_hist = log_action(f"ENVOI: Cmd #{row['id']}", df_hist)
                    if save_all(df_stock, df_orders, df_fin, df_hist):
                        st.rerun()
            
            elif status == "Shipped":
                # Orange -> Vert
                if c5.button("🟠 Livré (Encaisser)", key=unique_key):
                    df_orders.at[index, "status"] = "Delivered"
                    df_fin.at[0, "Revenue"] += row['price']
                    df_fin.at[0, "Profit"] += row['profit']
                    df_hist = log_action(f"PAYÉ: Cmd #{row['id']}", df_hist)
                    if save_all(df_stock, df_orders, df_fin, df_hist):
                        st.balloons()
                        st.rerun()
            
            elif status == "Delivered":
                # Vert (Terminé)
                c5.button("🟢 Reçu", key=unique_key, disabled=True)

elif menu == "Stock Management":
    st.title("🏭 Achat / Stock")
    c1, c2, c3 = st.columns(3)
    p_restock = c1.selectbox("Produit", PRODUCTS)
    q_restock = c2.number_input("Qté Reçue", 1)
    cost_restock = c3.number_input("Coût Total (€)", 0.0, step=0.01, format="%.2f")
    
    if st.button("Ajouter Stock"):
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
            df_hist = log_action(f"ACHAT: {q_restock}x {p_restock} (-{cost_restock}€)", df_hist)
            if save_all(df_stock, df_orders, df_fin, df_hist):
                st.success("Stock ajouté !")
                st.rerun()
        else:
            st.error("Erreur produit.")

elif menu == "Admin":
    st.title("⚙️ Admin")
    if st.button("Télécharger Rapport PDF"):
        pdf_file = generate_pdf(df_fin, df_orders)
        st.download_button("Download PDF", pdf_file, "Report.pdf", "application/pdf")
        
    st.divider()
    if st.button("Nouveau Mois (Reset CA)"):
        df_fin.at[0, "Revenue"] = 0.0
        df_fin.at[0, "Profit"] = 0.0
        df_fin.at[0, "Expenses"] = 0.0
        df_hist = log_action("RESET MOIS", df_hist)
        save_all(df_stock, df_orders, df_fin, df_hist)
        st.rerun()
        
    st.subheader("Logs")
    st.dataframe(df_hist, width="stretch")

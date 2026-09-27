"""
app.py
=======
Interface générale de l'atelier, façon "control tower" :
  1. Upload des 3 fichiers Excel source (barre latérale).
  2. Sur upload -> transform_v3 (avec surcharge "Nombre de machines" par
     poste, optionnelle) -> KPIs.
  3. Onglet SCÉNARIO : définir les hypothèses (capacité/attente par poste et
     par intervalle de temps) puis LANCER la simulation (théorique + réelle,
     une seule fois -- son historique est enregistré en session).
  4. CURSEUR TEMPOREL GLOBAL (barre latérale, actif dès qu'une simulation a
     été lancée) : en choisissant une date dans l'horizon simulé, TOUTE
     l'application (Accueil, Postes, OF) se recalcule sur l'état PROJETÉ à
     cette date -- pas seulement l'onglet Scénario.

5 onglets : Accueil, Postes, OF, Scénario, Export.

Lancement : streamlit run app.py
"""

import datetime

import streamlit as st
from streamlit_option_menu import option_menu

from backend.transform import executer_transform
from backend.simulation import projeter_etat_a_date, lancer_simulation_complete
from theme import css_global
from ui import dashboard_tab, poste_tab, of_tab, scenario_tab, donnees_tab, vsm_tab

st.set_page_config(page_title="Digitalisation et Visualisation - Figeac AERO", layout="wide", page_icon="🏭")
st.markdown(css_global(), unsafe_allow_html=True)

for cle, defaut in [
    ("scenario_evenements", []), ("scenario_attente_of", {}),
    ("capacite_externe", 1500), ("t_vue_h", 0.0),
]:
    st.session_state.setdefault(cle, defaut)

# ------------------------------------------------------------------
# Bandeau supérieur (logo Figeac Aero + titre)
# ------------------------------------------------------------------
col_logo, col_header = st.columns([1, 5], vertical_alignment="center")
with col_logo:
    st.image("assets/figeac_logo.png", use_container_width=True)
with col_header:
    st.markdown("""
    <div class="header-bar">
        <div>
            <h1>DIGITALISATION ET VISUALISATION — FIGEAC AERO</h1>
            <p>Suivi des flux, des postes et des OF</p>
        </div>
        <div style="font-size:13px; opacity:0.85;">🔔 &nbsp; 👤 Admin</div>
    </div>
    """, unsafe_allow_html=True)

# ------------------------------------------------------------------
# Barre latérale : upload + nombre de machines + curseur temporel global
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown("#### 📤 IMPORT DES DONNÉES")
    mode = st.radio("Mode d'entrée", ["Upload (navigateur)", "Chemins locaux (sur ce poste)"], index=0, label_visibility="collapsed")

    if mode == "Upload (navigateur)":
        fichier_operations = st.file_uploader("1. Opérations OF.xlsx", type=["xlsx"], key="up_ops")
        fichier_postes = st.file_uploader("2. Postes de charge.xlsx", type=["xlsx"], key="up_postes")
        fichier_encours = st.file_uploader("3. Encours.xlsx", type=["xlsx"], key="up_encours")
    else:
        fichier_operations = st.text_input("1. Chemin — Opérations OF", value=r"operation_des_OF.xlsx") or None
        fichier_postes = st.text_input("2. Chemin — Postes de charge", value=r"postes_de_charge.xlsx") or None
        fichier_encours = st.text_input("3. Chemin — Encours", value=r"encours.xlsx") or None

    st.markdown("#### 🌐 CAPACITÉ EXTERNE (pièces/jour)")
    st.session_state["capacite_externe"] = st.number_input(
        "Capacité externe", min_value=1, value=st.session_state["capacite_externe"], step=50, label_visibility="collapsed")
    st.caption("Le nombre de machines par poste ne se change plus que dans l'onglet SCÉNARIO "
               "(un seul endroit pour toucher à la capacité).")

    lancer = st.button("🚀 UPLOAD & TRAITEMENT", type="primary", use_container_width=True)

    if "tables" in st.session_state:
        st.markdown(
            "<div class='status-box-ok'>✅ Traitement terminé avec succès<br>"
            "transform_v3 exécuté</div>", unsafe_allow_html=True,
        )
    if "derniere_maj" in st.session_state:
        st.markdown("#### 🕐 DERNIÈRE MISE À JOUR")
        st.caption(st.session_state["derniere_maj"])

    # -- Curseur temporel GLOBAL : actif dès qu'une simulation a été lancée --
    if "sim_reel" in st.session_state:
        st.divider()
        st.markdown("#### 🕐 NAVIGATION TEMPORELLE (simulation)")
        _, _, extra_sb = st.session_state["sim_reel"]
        infos_sb = extra_sb["infos"]
        st.caption(f"t=0 = le moment où l'ERP (encours.xlsx) a été extrait → "
                   f"{infos_sb['maintenant'].strftime('%d/%m/%Y %Hh')}. "
                   f"t=fin (OF le plus long) : {infos_sb['date_fin_horizon'].strftime('%d/%m/%Y %Hh')}.")

        mode_nav = st.radio("Naviguer par :", ["Curseur (jours)", "📅 Date précise"], horizontal=True, key="mode_nav_temporelle")
        if mode_nav == "Curseur (jours)":
            st.session_state["t_vue_h"] = st.slider(
                "Jours écoulés depuis maintenant", 0.0, max(infos_sb["horizon_jours"], 0.1),
                float(st.session_state.get("t_vue_h", 0.0)) / 24, step=0.5,
            ) * 24
        else:
            date_choisie = st.date_input(
                "Date affichée", value=infos_sb["maintenant"].date(),
                min_value=infos_sb["maintenant"].date(), max_value=infos_sb["date_fin_horizon"].date(),
            )
            # Intervalle en nombre de jours entre t=0 (extraction ERP) et la date choisie.
            nb_jours_ecoules = (date_choisie - infos_sb["maintenant"].date()).days
            st.session_state["t_vue_h"] = max(nb_jours_ecoules, 0) * 24

        date_vue_sb = infos_sb["maintenant"] + datetime.timedelta(hours=st.session_state["t_vue_h"])
        st.caption(f"📍 Application affichée à l'état projeté du **{date_vue_sb.strftime('%d/%m/%Y %Hh%M')}**"
                   if st.session_state["t_vue_h"] > 0 else "📍 Application affichée à l'état **réel actuel**")

# ------------------------------------------------------------------
# Pipeline transform
# ------------------------------------------------------------------
if lancer:
    if not (fichier_operations and fichier_postes and fichier_encours):
        st.error("Merci de fournir les 3 fichiers avant de lancer le traitement.")
    else:
        try:
            with st.spinner("Nettoyage et fusion des données (transform_v3)... (peut prendre 1-2 min sur un gros fichier)"):
                tables, logs = executer_transform(
                    fichier_operations, fichier_postes, fichier_encours,
                    st.session_state["capacite_externe"],
                )
                st.session_state["tables"] = tables
                st.session_state["logs"] = logs
                st.session_state["derniere_maj"] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                st.session_state["t_vue_h"] = 0.0
            st.success("Traitement terminé — lancement de la simulation de référence (état normal)...")
            with st.spinner("Simulation de référence en cours (théorique + réelle, sans scénario)..."):
                resultat = lancer_simulation_complete(tables, capacite_externe_jour=st.session_state["capacite_externe"])
                st.session_state["sim_theo"] = resultat["sim_theo"]
                st.session_state["sim_reel"] = resultat["sim_reel"]
                st.session_state["sim_maintenant"] = resultat["maintenant"]
            st.success("Simulation de référence prête. Modifie des hypothèses dans l'onglet SCÉNARIO si besoin.")
        except ValueError as e:
            st.error(f"❌ Fichier(s) source incompatible(s) :\n\n{e}")
            st.stop()

if "tables" not in st.session_state:
    st.info("👈 Fournis les 3 fichiers Excel source dans la barre latérale, puis clique sur "
            "**UPLOAD & TRAITEMENT**.")
    st.stop()

tables = st.session_state["tables"]

# -- Tables "vue" : projetées à la date choisie par le curseur temporel --
# (état réel si t=0 ou pas de simulation ; état simulé sinon) -- c'est ce
# dictionnaire qui alimente Accueil/Postes/OF pour que le curseur transforme
# TOUTE l'application, pas seulement l'onglet Scénario.
sim_extra = st.session_state["sim_reel"][2] if "sim_reel" in st.session_state else None
tables_vue = projeter_etat_a_date(tables, sim_extra, st.session_state.get("t_vue_h", 0.0))

# ------------------------------------------------------------------
# Navigation horizontale
# ------------------------------------------------------------------
onglet = option_menu(
    menu_title=None,
    options=["ACCUEIL", "POSTES", "OF", "VSM", "SCÉNARIO", "EXPORT"],
    icons=["house", "diagram-3", "box-seam", "signpost-split", "graph-up-arrow", "table"],
    orientation="horizontal",
    styles={
        "container": {"padding": "4px", "background-color": "#F4F6F8", "border-radius": "8px"},
        "icon": {"color": "#2C6E9B", "font-size": "14px"},
        "nav-link": {"font-size": "13px", "font-weight": "600", "text-align": "center", "margin": "2px", "border-radius": "6px"},
        "nav-link-selected": {"background-color": "#2C6E9B", "color": "white"},
    },
)

with st.expander("Journal du traitement (transform_v3)"):
    for ligne in st.session_state["logs"]:
        st.text(ligne)

if onglet == "ACCUEIL":
    dashboard_tab.afficher(tables_vue)
elif onglet == "POSTES":
    poste_tab.afficher(tables_vue)
elif onglet == "OF":
    of_tab.afficher(tables_vue)
elif onglet == "VSM":
    vsm_tab.afficher(tables_vue)
elif onglet == "SCÉNARIO":
    scenario_tab.afficher(tables)  # capacités/postes de référence = état réel, pas la vue projetée
elif onglet == "EXPORT":
    donnees_tab.afficher(tables)  # export = fichier transformé réel + résultats de simulation bruts

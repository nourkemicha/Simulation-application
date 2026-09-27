"""
ui/of_tab.py
=============
Onglet OF : fiche par OF en cours -- CT, Lead Time, % VA, retard, état actuel
-- + le diagramme VSM du CYCLE COMPLET par OF (clôturé/en cours/à venir) et
la comparaison théorique/simulé, si une simulation a déjà été lancée (onglet
SCÉNARIO). Le diagramme VSM fonctionne même SANS simulation (montre juste le
clôturé + en cours, sans projection des étapes à venir).

Si l'app reçoit les tables PROJETÉES par le curseur temporel global (voir
backend.simulation.projeter_etat_a_date), "Poste actuel"/"État encours"
reflètent déjà l'état simulé à la date choisie -- rien à faire ici, cet
onglet consomme simplement la table qu'on lui passe.
"""

import datetime

import pandas as pd
import streamlit as st

from backend.kpi_postes import calculer_kpi_of, calculer_otd_of
from ui.vsm_render import construire_cycle_complet_vsm, rendu_vsm_html


def _fmt_h_j(heures: float) -> str:
    if pd.isna(heures):
        heures = 0.0
    return f"{heures:.0f} h ({heures / 24:.1f} j)"


def afficher(tables: dict[str, pd.DataFrame]):
    kof = calculer_kpi_of(tables)
    en_cours = kof[kof["Etat_OF_encours"] == "En cours"].copy()
    otd = calculer_otd_of(tables)

    st.subheader("Vue d'ensemble WIP")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("WIP (OF en cours)", len(en_cours))
    c2.metric("En retard", int((en_cours["En_retard"].astype(str).str.strip().str.upper() == "OUI").sum()))
    c3.metric("Lead Time médian", _fmt_h_j(en_cours['Lead_Time_h'].median()))
    c4.metric("% VA médian", f"{en_cours['Pct_VA'].median():.0f} %")
    c5.metric("OTD (OF clôturés)", f"{otd['otd_pct']}%" if otd["otd_pct"] is not None else "n/a")
    st.caption(f"OTD = OF clôturés à temps (date de fin réelle ≤ date de fin planifiée) / OF clôturés total "
               f"({otd['nb_a_temps']} / {otd['nb_total']}).")

    st.divider()
    st.subheader("Rechercher un OF")
    liste_of = en_cours["N° ordre (OF)"].tolist()
    of_choisi = st.selectbox("N° ordre :", liste_of)
    _afficher_fiche_of(tables, kof, of_choisi)

    st.divider()
    st.subheader("Tableau CT / Lead Time / %VA (filtrable)")
    colonnes = ["N° ordre (OF)", "Article", "Qte_OF", "Poste_travail_actuel", "Etat_OF_encours",
                "Nombre_operations", "Nb_operations_restantes", "Age_OF_jours_ouvres", "Jours_retard_ouvres",
                "En_retard", "CT_h", "Lead_Time_h", "Attente_totale_h", "Pct_VA"]
    st.dataframe(en_cours[[c for c in colonnes if c in en_cours.columns]], use_container_width=True, hide_index=True)


def _afficher_fiche_of(tables: dict[str, pd.DataFrame], kof: pd.DataFrame, of_id: str):
    ligne = kof[kof["N° ordre (OF)"] == of_id]
    if ligne.empty:
        st.info("OF introuvable.")
        return
    r = ligne.iloc[0]

    st.markdown(f"### OF {of_id} — {r.get('Article', '')} ({r.get('Article_Description', '')})")
    en_retard = str(r.get("En_retard", "")).strip().upper() == "OUI"
    badge = "🟧 EN RETARD" if en_retard else "🟩 Dans les temps"
    st.markdown(f"**{badge}** — Département : {r.get('Departement', 'n/a')}, Chaîne : {r.get('Chaine_production', 'n/a')}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Poste actuel", str(r.get("Poste_travail_actuel", "n/a")))
    c2.metric("État encours", str(r.get("Etat_OF_encours", "n/a")))
    c3.metric("Âge (j. ouvrés)", f"{r.get('Age_OF_jours_ouvres', 0):.0f}")
    c4.metric("Retard (j. ouvrés)", f"{r.get('Jours_retard_ouvres', 0):.0f}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("CT (temps de traitement pur)", _fmt_h_j(r.get('CT_h', 0)))
    c6.metric("Lead Time (CT + attente)", _fmt_h_j(r.get('Lead_Time_h', 0)))
    c7.metric("Attente totale", _fmt_h_j(r.get('Attente_totale_h', 0)))
    c8.metric("% Temps VA", f"{r.get('Pct_VA', 0):.0f} %")
    st.caption("CT = Σ(Temps opération − Attente_calculee_h) sur la gamme restante. "
               "Lead Time = Σ Temps opération (CT + attente). "
               "% VA = Σ(Facteur exécution machine × Capacite_pour_formule) / Lead Time × 100.")

    if "sim_reel" in st.session_state:
        vsm, detail, extra = st.session_state["sim_reel"]
        ligne_vsm = vsm[vsm["N° ordre"] == of_id]
        if not ligne_vsm.empty:
            rv = ligne_vsm.iloc[0]
            c9, c10, c11 = st.columns(3)
            c9.metric("Cycle théorique restant (cet OF)", f"{rv.get('Cycle_theorique_jours', 0):.1f} j")
            c10.metric("Durée simulée de CET OF", f"{rv.get('Duree_simulee_jours', 0):.1f} j")
            c11.metric("Écart (goulot réel)", f"{rv.get('Ecart_goulot_h', 0):.0f} h")
            if pd.notna(rv.get("Date_fin")):
                st.markdown(f"**Date de fin simulée de CET OF : {pd.Timestamp(rv['Date_fin']).strftime('%d/%m/%Y %Hh%M')}**")
            st.caption("⚠️ Ne pas confondre avec l'horizon global affiché ailleurs (barre latérale, onglet SCÉNARIO) : "
                       "celui-ci correspond à l'OF le PLUS LONG de toute la simulation, pas à cet OF précis. "
                       "Chaque OF a sa propre date de fin ≤ l'horizon global.")
    else:
        st.caption("Astuce : lance une simulation (onglet SCÉNARIO) pour voir la projection des étapes à venir "
                   "et la date de fin de cet OF -- le cycle déjà clôturé/en cours reste visible dès maintenant.")

    st.markdown("<br>", unsafe_allow_html=True)
    _afficher_vsm_of(tables, of_id, r)


def _afficher_vsm_of(tables: dict[str, pd.DataFrame], of_id: str, r: pd.Series):
    """Diagramme VSM du cycle COMPLET de cet OF -- fonctionne sans simulation
    (montre le clôturé + en cours), et ajoute les étapes à venir projetées
    dès qu'une simulation a été lancée."""
    t_vue_h = st.session_state.get("t_vue_h", 0.0)
    if "sim_reel" in st.session_state and t_vue_h > 0:
        _, _, extra = st.session_state["sim_reel"]
        date_vue = extra["infos"]["maintenant"] + datetime.timedelta(hours=t_vue_h)
        sous_titre = f"État projeté au {date_vue.strftime('%d/%m/%Y')} (curseur temporel)"
    else:
        sous_titre = "État réel actuel"

    etapes = construire_cycle_complet_vsm(tables, of_id, t_vue_h)
    html = rendu_vsm_html(etapes, titre=f"Industrial Process Flow Chart — OF {of_id} (cycle complet, poste actuel : {r.get('Poste_travail_actuel', 'n/a')})",
                          sous_titre=sous_titre)
    st.markdown(html, unsafe_allow_html=True)

    if etapes:
        with st.expander("Voir le détail brut du cycle complet"):
            st.dataframe(pd.DataFrame(etapes), use_container_width=True, hide_index=True)

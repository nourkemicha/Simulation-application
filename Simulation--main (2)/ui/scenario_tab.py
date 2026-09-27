"""
ui/scenario_tab.py
=====================
Onglet SCÉNARIO :
1. Définir des ÉVÉNEMENTS PLANIFIÉS DANS LE TEMPS, par poste : un
   changement de CAPACITÉ (panne = machines en moins, ou renfort = machines
   en plus -- même mécanisme, signe opposé) ou d'ATTENTE. Chaque événement a
   une DATE DE DÉBUT (calendrier) et soit une DATE DE FIN, soit "pour
   toujours". Un même poste peut avoir plusieurs événements successifs.
   La capacité de base de CHAQUE poste = son "Nombre de machines" (1 par
   défaut si non documenté, comme n'importe quel poste où ce nombre est
   connu -- pas de distinction "confirmé / par défaut", c'est la même chose
   pour la simulation). Un scénario peut changer la capacité de N'IMPORTE
   QUEL poste, y compris ceux à capacité par défaut.
2. Un override d'attente ponctuel par OF (statique, sans notion d'intervalle).
3. Le bouton qui LANCE la simulation (théorique + réelle). Une simulation
   de référence (sans scénario) est déjà lancée automatiquement après le
   traitement des fichiers -- ce bouton sert à la RELANCER avec les
   événements définis ci-dessus. Le curseur temporel de la barre latérale
   reflète alors la dernière simulation lancée, quelle qu'elle soit.
"""

import datetime as dt

import pandas as pd
import streamlit as st

from backend.simulation import (capacites_postes_de_base, POSTES_OPERATEURS_MULTIPLES,
                                 evenements_dates_vers_heures, lancer_simulation_complete)


def afficher(tables: dict[str, pd.DataFrame]):
    st.markdown("### 🧪 Scénario")
    st.caption("Chaque événement a une date de début et soit une date de fin, soit \"pour toujours\". "
               "Plusieurs événements sur un même poste s'appliquent chacun sur leur fenêtre.")

    postes = sorted(tables["Poste_de_charge"]["Poste de charge"].dropna().unique().tolist())
    capacites_actuelles = capacites_postes_de_base(tables)
    st.session_state.setdefault("scenario_evenements", [])
    st.session_state.setdefault("scenario_attente_of", {})
    aujourdhui = dt.date.today()

    st.divider()
    st.subheader("1) Capacité d'un poste (panne = négatif, renfort = positif)")
    with st.form("form_evenement_capacite"):
        c1, c2 = st.columns(2)
        poste_c = c1.selectbox("Poste", postes, key="ev_cap_poste")
        delta_c = c2.number_input("Delta machines (− panne / + renfort)", value=-1, step=1, key="ev_cap_delta")
        c3, c4, c5 = st.columns([1, 1, 1])
        date_debut_c = c3.date_input("📅 Date de début", value=aujourdhui, key="ev_cap_debut")
        fin_type_c = c4.radio("Fin", ["📅 Date de fin", "♾️ Pour toujours"], key="ev_cap_fin_type", label_visibility="visible")
        date_fin_c = c5.date_input("Date de fin", value=aujourdhui + dt.timedelta(days=7), key="ev_cap_fin",
                                    disabled=(fin_type_c == "♾️ Pour toujours"))
        ajouter_cap = st.form_submit_button("➕ Ajouter cet événement de capacité")

    if ajouter_cap:
        cap_base = capacites_actuelles.get(poste_c, 1)
        if poste_c in POSTES_OPERATEURS_MULTIPLES:
            st.warning(f"⚠️ {poste_c} est un poste à opérateurs multiples (nombre de personnes variable, pas "
                       f"de nombre de machines fixe) — cet événement n'aura pas d'effet réel. Ajouté quand "
                       f"même, à titre indicatif.")
        elif delta_c < 0 and abs(delta_c) > cap_base:
            st.error(f"❌ Le poste {poste_c} a {cap_base} machine(s) — impossible d'en retirer {abs(delta_c):.0f}. "
                     f"Corrige la saisie.")
        if not (delta_c < 0 and abs(delta_c) > cap_base and poste_c not in POSTES_OPERATEURS_MULTIPLES):
            date_fin_valeur = None if fin_type_c == "♾️ Pour toujours" else date_fin_c
            st.session_state["scenario_evenements"].append({
                "poste": poste_c, "date_debut": date_debut_c, "date_fin": date_fin_valeur,
                "type": "capacite", "valeur": float(delta_c),
            })
            fin_txt = "pour toujours" if date_fin_valeur is None else f"jusqu'au {date_fin_valeur.strftime('%d/%m/%Y')}"
            st.success(f"Événement ajouté : {poste_c}, {'panne' if delta_c < 0 else 'renfort'} de {abs(delta_c):.0f} "
                       f"machine(s), du {date_debut_c.strftime('%d/%m/%Y')} {fin_txt}.")

    st.divider()
    st.subheader("2) Temps d'attente d'un poste")
    with st.form("form_evenement_attente"):
        c1, c2 = st.columns(2)
        poste_a = c1.selectbox("Poste", postes, key="ev_att_poste")
        valeur_a = c2.number_input("Attente ajoutée (h)", min_value=0.0, value=5.0, step=1.0, key="ev_att_valeur")
        c3, c4, c5 = st.columns([1, 1, 1])
        date_debut_a = c3.date_input("📅 Date de début", value=aujourdhui, key="ev_att_debut")
        fin_type_a = c4.radio("Fin", ["📅 Date de fin", "♾️ Pour toujours"], key="ev_att_fin_type")
        date_fin_a = c5.date_input("Date de fin", value=aujourdhui + dt.timedelta(days=7), key="ev_att_fin",
                                    disabled=(fin_type_a == "♾️ Pour toujours"))
        ajouter_att = st.form_submit_button("➕ Ajouter cet événement d'attente")

    if ajouter_att:
        date_fin_valeur = None if fin_type_a == "♾️ Pour toujours" else date_fin_a
        st.session_state["scenario_evenements"].append({
            "poste": poste_a, "date_debut": date_debut_a, "date_fin": date_fin_valeur,
            "type": "attente", "valeur": float(valeur_a),
        })
        fin_txt = "pour toujours" if date_fin_valeur is None else f"jusqu'au {date_fin_valeur.strftime('%d/%m/%Y')}"
        st.success(f"Événement ajouté : {poste_a}, +{valeur_a:.0f}h d'attente, du {date_debut_a.strftime('%d/%m/%Y')} {fin_txt}.")

    if st.session_state["scenario_evenements"]:
        st.markdown("**Événements actifs pour la prochaine simulation :**")
        df_ev = pd.DataFrame(st.session_state["scenario_evenements"])
        df_ev["date_fin"] = df_ev["date_fin"].apply(lambda d: "toujours" if d is None else d.strftime("%d/%m/%Y"))
        df_ev["date_debut"] = df_ev["date_debut"].apply(lambda d: d.strftime("%d/%m/%Y"))
        st.dataframe(df_ev, use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        idx_a_supprimer = c1.number_input("Index à supprimer (voir tableau ci-dessus)", min_value=0,
                                           max_value=max(len(df_ev) - 1, 0), value=0, step=1)
        if c1.button("🗑️ Supprimer cet événement"):
            st.session_state["scenario_evenements"].pop(int(idx_a_supprimer))
            st.rerun()
        if c2.button("🧹 Effacer tous les événements"):
            st.session_state["scenario_evenements"] = []
            st.rerun()

    st.divider()
    st.subheader("3) Attente ponctuelle par OF (statique, sur sa 1ère opération restante)")
    of_df = tables["OF"]
    liste_of = of_df.loc[of_df["Etat_OF_encours"] == "En cours", "N° ordre (OF)"].tolist()
    c1, c2 = st.columns([2, 1])
    of_att = c1.selectbox("N° ordre (OF en cours)", liste_of, key="att_of")
    delta_att = c2.number_input("Delta attente (h, + ou -)", value=0.0, step=1.0, key="att_of_val")
    if st.button("➕ Appliquer ce delta d'attente"):
        st.session_state["scenario_attente_of"][of_att] = float(delta_att)
        st.success(f"OF {of_att} : delta d'attente de {delta_att} h sur sa 1ère opération restante.")
    if st.session_state["scenario_attente_of"]:
        st.dataframe(st.session_state["scenario_attente_of"], use_container_width=True)

    st.divider()
    if st.button("🧹 Réinitialiser TOUT le scénario"):
        st.session_state["scenario_evenements"] = []
        st.session_state["scenario_attente_of"] = {}
        st.rerun()

    st.divider()
    st.subheader("▶️ Lancer la simulation")
    st.caption("Une simulation de référence (sans scénario) tourne déjà automatiquement après le traitement "
               "des fichiers. Ce bouton relance avec les événements définis ci-dessus.")
    if st.button("▶️ Lancer / relancer la simulation avec ce scénario", type="primary", use_container_width=True):
        with st.spinner("Simulation en cours (théorique puis réelle, ~30-90s sur un gros jeu de données)..."):
            maintenant = dt.datetime.now()
            evenements_h = evenements_dates_vers_heures(st.session_state.get("scenario_evenements", []), maintenant)
            resultat = lancer_simulation_complete(
                tables, capacite_externe_jour=st.session_state["capacite_externe"],
                evenements=evenements_h, attente_override_of=st.session_state.get("scenario_attente_of", {}),
                maintenant=maintenant,
            )
            st.session_state["sim_theo"] = resultat["sim_theo"]
            st.session_state["sim_reel"] = resultat["sim_reel"]
            st.session_state["sim_maintenant"] = resultat["maintenant"]
            st.session_state["t_vue_h"] = 0.0
        st.success("Simulation relancée avec le scénario — le curseur temporel (barre latérale) est à jour.")

    if "sim_reel" in st.session_state:
        _resume_derniere_simulation()


def _resume_derniere_simulation():
    vsm, df_detail, extra = st.session_state["sim_reel"]
    infos = extra["infos"]
    st.markdown("**Dernière simulation lancée :**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("t = 0", infos["maintenant"].strftime("%d/%m/%Y %Hh%M"))
    c2.metric("t = fin (OF le plus long)", infos["date_fin_horizon"].strftime("%d/%m/%Y %Hh%M"))
    c3.metric("Horizon global simulé", f"{infos['horizon_jours']:.1f} j")
    c4.metric("OF simulés", infos["nb_of_simules"])
    st.caption("« Horizon global » = la durée de l'OF le PLUS LONG à finir. Chaque OF individuel a sa propre "
               "durée, généralement bien plus courte (voir sa fiche dans l'onglet OF).")

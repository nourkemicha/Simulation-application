"""
ui/dashboard_tab.py
======================
Onglet ACCUEIL : vue d'ensemble condensée, l'essentiel pour voir l'état des
encours d'un coup d'œil -- statuts des OF, charge par département, retard,
et LE poste goulot actuel mis en avant clairement.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.kpi import calculer_kpi_postes, calculer_kpi_departements, calculer_otd, calculer_rejection_rate_par_poste
from backend.kpi_postes import (calculer_charge_capacite_postes, calculer_distribution_statuts_of,
                                 calculer_of_retard_par_departement)
from theme import COULEURS


def afficher(tables: dict[str, pd.DataFrame]):
    of_df = tables["OF"]
    df_postes = calculer_kpi_postes(tables)
    df_dept = calculer_kpi_departements(tables)
    otd = calculer_otd(tables)
    df_rejet = calculer_rejection_rate_par_poste(tables)
    taux_rejet_global = (df_rejet["Qte_rebut"].sum() / df_rejet["Qte_totale"].sum() * 100) if df_rejet["Qte_totale"].sum() else 0.0

    st.markdown("### 🏠 Vue d'ensemble")
    cols = st.columns(6)
    cols[0].metric("OF en cours", int((of_df["Etat_OF_encours"] == "En cours").sum()))
    cols[1].metric("OF en attente", int(of_df["Etat_OF_encours"].isin(["Libérée", "En attente", "Partiellement déclarée"]).sum()))
    cols[2].metric("Postes actifs", len(df_postes))
    cols[3].metric("Poste le + chargé", df_postes.sort_values("Taux_utilisation", ascending=False).iloc[0]["Poste de Charge"] if len(df_postes) else "n/a")
    cols[4].metric("OTD (tous OF connus)", f"{otd['otd_pct']:.0f}%" if otd["otd_pct"] is not None else "n/a")
    cols[5].metric("Taux de rebut global", f"{taux_rejet_global:.1f}%")

    st.divider()
    _message_goulot(tables)

    st.divider()
    st.markdown("**Charge par département**")
    df = df_dept.sort_values("Taux_utilisation", ascending=False)
    largeur_dept = 0.4 if len(df) <= 3 else None
    fig = go.Figure(go.Bar(
        x=df["Departement"], y=df["Taux_utilisation"] * 100, width=largeur_dept,
        marker_color=[COULEURS["orange"] if v >= 0.9 else COULEURS["bleu"] for v in df["Taux_utilisation"]],
        text=[f"{v * 100:.0f}%" for v in df["Taux_utilisation"]], textposition="outside",
    ))
    fig.update_layout(height=360, yaxis_title="Utilisation (%)", margin=dict(t=10, b=80))
    fig.update_xaxes(tickangle=-20)
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**Statuts des OF (avant filtrage sur les encours)**")
        dist = calculer_distribution_statuts_of(tables)
        palette = [COULEURS["bleu_fonce"], COULEURS["bleu"], COULEURS["vert"],
                   COULEURS["orange"], COULEURS["gris_moyen"], "#B0342A", "#8E9AAE"]
        fig3 = go.Figure(go.Pie(labels=dist["Statut"], values=dist["Nb_OF"], hole=0.5,
                                 marker_colors=palette[:len(dist)]))
        fig3.update_layout(height=360, margin=dict(t=10))
        st.plotly_chart(fig3, use_container_width=True)
        st.caption("Répartition de TOUS les OF par statut d'encours, avant le filtrage sur « En cours » "
                   "utilisé partout ailleurs dans l'interface.")

    with col4:
        st.markdown("**OF en cours par département — retard / dans les temps**")
        g = calculer_of_retard_par_departement(tables)
        largeur_retard = 0.4 if g["Departement"].nunique() <= 3 else None
        fig4 = go.Figure()
        for retard, couleur in [("Dans les temps", COULEURS["vert"]), ("En retard", COULEURS["orange"]),
                                 ("Non renseigné", COULEURS["gris_moyen"])]:
            sous = g[g["Retard"] == retard]
            if sous.empty:
                continue
            fig4.add_trace(go.Bar(name=retard, x=sous["Departement"], y=sous["Nb_OF"], marker_color=couleur, width=largeur_retard))
        fig4.update_layout(barmode="stack", height=360, yaxis_title="Nb OF", margin=dict(t=10, b=60))
        fig4.update_xaxes(tickangle=-20)
        st.plotly_chart(fig4, use_container_width=True)

    st.caption("Détails complets : onglets POSTES, OF, SCÉNARIO, EXPORT.")


def _message_goulot(tables: dict[str, pd.DataFrame]):
    """Message clair sur le goulot actuel, plutôt qu'un classement dense."""
    df_charge = calculer_charge_capacite_postes(tables)
    if df_charge.empty:
        return
    top = df_charge.iloc[0]
    st.markdown(f"""
    <div style="background:#FBEEE4; border-left:6px solid {COULEURS['orange_fonce']}; border-radius:8px;
                padding:16px 20px;">
      <div style="font-size:15px; font-weight:700; color:{COULEURS['orange_fonce']};">
        🔴 Poste goulot actuel : {top['Poste de Charge']} — {top.get('Description', '')}
      </div>
      <div style="font-size:13px; color:{COULEURS['gris_fonce']}; margin-top:4px;">
        Taux de charge <b>{top['Taux_charge_pct']:.0f}%</b> · {top['Jours_de_charge']:.1f} jours de charge à
        capacité pleine · <b>{int(top['Nb_OF_concernes'])} OF</b> en attente sur ce poste.
      </div>
    </div>""", unsafe_allow_html=True)

    autres = df_charge.iloc[1:3]
    if len(autres):
        noms = ", ".join(f"{r['Poste de Charge']} ({r['Taux_charge_pct']:.0f}%)" for _, r in autres.iterrows())
        st.caption(f"Ensuite : {noms}. Détail complet dans l'onglet POSTES.")

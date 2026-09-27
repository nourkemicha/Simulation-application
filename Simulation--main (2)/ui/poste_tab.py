"""
ui/poste_tab.py
=================
Onglet POSTES : UNE SEULE PAGE (pas de toggle département/poste).
1. Bandeau KPI + message goulot global + charge par département.
2. Détail HIÉRARCHIQUE : Département -> (option) Sous-département (chaîne)
   -> (option) Poste précis. À chaque niveau : charge par poste dans ce
   périmètre + goulot + taux d'utilisation par période (jour/semaine/mois,
   basé sur la date de fin PRÉVUE des opérations encours) + répartition
   des temps + OF en retard (par poste, et en pie chart au niveau
   département). Si un poste précis est choisi, détail complet (jauge,
   charge/capacité/goulot) -- sans Îlots ni TRS, sans WIP par poste.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from backend.kpi import calculer_kpi_postes, calculer_kpi_departements, detail_poste
from backend.kpi_postes import (calculer_charge_capacite_postes, calculer_taux_utilisation_periodique_perimetre,
                                 calculer_of_retard_par_poste_perimetre, calculer_of_retard_departement)
from theme import COULEURS

SEUIL_GOULOT_PCT = 90


def _fmt_h_j(heures: float) -> str:
    """Affiche une durée en heures ET en jours, ex: '1234 h (51.4 j)'."""
    if pd.isna(heures):
        heures = 0.0
    return f"{heures:.0f} h ({heures / 24:.1f} j)"


def afficher(tables: dict[str, pd.DataFrame]):
    st.markdown("### 📍 ANALYSE DES POSTES DE CHARGE")

    df_dept = calculer_kpi_departements(tables)
    df_postes = calculer_kpi_postes(tables)
    of_df = tables["OF"]

    dept_goulot = df_dept.loc[df_dept["Taux_utilisation"].idxmax()] if len(df_dept) else None
    nb_of_en_cours = int((of_df["Etat_OF_encours"] == "En cours").sum())
    capacite_utilisee_jour = (df_dept["Capacite_h_jour_totale"] * df_dept["Taux_utilisation"]).sum()

    # -- Bandeau KPI --
    cols = st.columns(5)
    cols[0].markdown(_carte_kpi("🏭", str(len(df_dept)), "Départements"), unsafe_allow_html=True)
    cols[1].markdown(_carte_kpi("📦", str(nb_of_en_cours), "OF en cours"), unsafe_allow_html=True)
    cols[2].markdown(_carte_kpi("📈", f"{df_dept['Taux_utilisation'].mean() * 100:.0f} %", "Charge moyenne"), unsafe_allow_html=True)
    cols[3].markdown(_carte_kpi("⚠️", dept_goulot["Departement"].split()[0] if dept_goulot is not None else "n/a",
                                  "Département goulot", alerte=True), unsafe_allow_html=True)
    cols[4].markdown(_carte_kpi("🕐", _fmt_h_j(capacite_utilisee_jour), "Capacité utilisée / jour"), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_chart, col_tiles = st.columns([1.3, 1])
    with col_chart:
        st.markdown("**CHARGE MOYENNE PAR DÉPARTEMENT**")
        _bar_departements(df_dept)
    with col_tiles:
        st.markdown("**RÉPARTITION DE LA CHARGE PAR DÉPARTEMENT**")
        _tuiles_departements(df_dept)

    st.markdown("<br>", unsafe_allow_html=True)
    _message_goulot_postes(df_postes)

    st.divider()
    _section_detail_hierarchique(tables, df_dept, df_postes, dept_goulot)


# ========================================================================
# DÉTAIL HIÉRARCHIQUE : Département -> Sous-département -> Poste
# ========================================================================
def _section_detail_hierarchique(tables: dict[str, pd.DataFrame], df_dept: pd.DataFrame,
                                  df_postes: pd.DataFrame, dept_goulot):
    st.markdown("### 🔍 DÉTAIL")
    ops = tables["Operations_par_OF"].copy()
    ops["Temps opération"] = pd.to_numeric(ops["Temps opération"], errors="coerce").fillna(0)
    ops_restantes = ops[ops["Statut d'opération"] != "Clôturé"]

    c1, c2, c3 = st.columns(3)
    dept_choisi = c1.selectbox("Département :", df_dept["Departement"].tolist(),
                                index=df_dept["Departement"].tolist().index(dept_goulot["Departement"]) if dept_goulot is not None else 0)

    perimetre = ops_restantes[ops_restantes["Département Description"] == dept_choisi]
    chaines_dispo = sorted(perimetre["Chaîne production Description"].dropna().unique().tolist())
    chaine_choisie = c2.selectbox("Sous-département (chaîne) :", ["Tous"] + chaines_dispo, key=f"chaine_{dept_choisi}")
    if chaine_choisie != "Tous":
        perimetre = perimetre[perimetre["Chaîne production Description"] == chaine_choisie]

    postes_dispo = sorted(perimetre["Poste de Charge"].dropna().unique().tolist())
    poste_choisi = c3.selectbox("Poste :", ["Tous"] + postes_dispo, key=f"poste_{dept_choisi}_{chaine_choisie}")

    if poste_choisi != "Tous":
        _afficher_detail_poste(df_postes, tables, poste_choisi)
        return

    titre = chaine_choisie if chaine_choisie != "Tous" else dept_choisi
    _charge_et_goulot_perimetre(tables, perimetre, titre)

    st.divider()
    st.markdown(f"**OF en retard — {titre}**")
    if chaine_choisie == "Tous":
        col_bar, col_pie = st.columns([1.4, 1])
        with col_bar:
            _bar_retard_par_poste(tables, postes_dispo)
        with col_pie:
            _pie_retard_departement(tables, dept_choisi)
    else:
        _bar_retard_par_poste(tables, postes_dispo)

    if chaine_choisie == "Tous":
        st.divider()
        col3, col4 = st.columns(2)
        with col3:
            st.markdown("**RÉPARTITION DES TEMPS**")
            _donut_va_nonva(tables, dept_choisi)
        with col4:
            st.markdown("**ÉVOLUTION RÉCENTE (réel)**")
            _tendance_reelle(tables, dept_choisi)


def _charge_et_goulot_perimetre(tables: dict[str, pd.DataFrame], ops_perimetre: pd.DataFrame, titre: str):
    """Charge par poste + goulot, dans un périmètre donné (département OU
    chaîne) -- la MÊME logique à n'importe quel niveau de la hiérarchie."""
    if ops_perimetre.empty:
        st.caption("Pas de données pour ce périmètre.")
        return

    charge_par_poste = ops_perimetre.groupby("Poste de Charge")["Temps opération"].sum().sort_values(ascending=False)
    nb_of = ops_perimetre["N° ordre"].nunique()

    st.markdown(f"**Charge par poste — {titre}**")
    c1, c2 = st.columns(2)
    c1.metric("Charge totale du périmètre", _fmt_h_j(charge_par_poste.sum()))
    c2.metric("OF concernés", nb_of)

    top = charge_par_poste.head(10)
    fig = go.Figure(go.Bar(x=top.index, y=top.values, marker_color=COULEURS["bleu"], width=0.4,
                            text=[f"{v:.0f}h ({v/24:.1f}j)" for v in top.values], textposition="outside"))
    fig.update_layout(height=340, yaxis_title="Charge (h)", margin=dict(t=10, b=60))
    fig.update_xaxes(tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)

    df_charge_globale = calculer_charge_capacite_postes(tables)
    df_charge_perimetre = df_charge_globale[df_charge_globale["Poste de Charge"].isin(charge_par_poste.index)]
    if not df_charge_perimetre.empty:
        goulot = df_charge_perimetre.sort_values("Taux_charge_pct", ascending=False).iloc[0]
        st.markdown(f"""
        <div style="background:#FBEEE4; border-left:6px solid {COULEURS['orange_fonce']}; border-radius:8px; padding:12px 16px;">
          🔴 Goulot dans ce périmètre : <b>{goulot['Poste de Charge']}</b> — taux de charge <b>{goulot['Taux_charge_pct']:.0f}%</b>
          ({goulot['Jours_de_charge']:.1f} jours de charge, {int(goulot['Nb_OF_concernes'])} OF)
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    _graphe_taux_utilisation_periode(tables, list(charge_par_poste.index), titre)


def _graphe_taux_utilisation_periode(tables: dict[str, pd.DataFrame], postes_perimetre: list[str], titre: str):
    st.markdown(f"**Taux d'utilisation par période — {titre}**")
    st.caption("Les OF de chaque période sont repérés par la date de fin PRÉVUE de leurs opérations encours "
               "(\"Dt/hre fin opération\", ERP) -- quand ce travail doit être fini d'après le planning actuel.")
    granularite_label = st.radio("Période :", ["Jour", "Semaine", "Mois"], index=1, horizontal=True, key=f"gran_taux_{titre}")
    code_granularite = {"Jour": "D", "Semaine": "W", "Mois": "M"}[granularite_label]

    df_periode = calculer_taux_utilisation_periodique_perimetre(tables, postes_perimetre, granularite=code_granularite)
    if df_periode.empty:
        st.caption("Pas de dates de fin d'opération exploitables pour ce périmètre.")
        return

    # Dépassement (>= 100%, poste en surcharge) -> bleu foncé ; le reste -> bleu clair.
    couleurs = [COULEURS["bleu_fonce"] if v >= 100 else COULEURS["bleu"] for v in df_periode["Taux_utilisation_pct"]]
    largeur = 0.4 if len(df_periode) <= 3 else None
    fig = go.Figure(go.Bar(
        x=df_periode["Date_periode"], y=df_periode["Taux_utilisation_pct"], marker_color=couleurs, width=largeur,
        text=[f"{v:.0f}%" for v in df_periode["Taux_utilisation_pct"]], textposition="outside",
        customdata=df_periode["Charge_j"], hovertemplate="%{x}<br>Taux : %{y:.0f}%<br>Charge : %{customdata:.1f} j<extra></extra>",
    ))
    fig.add_hline(y=100, line_dash="dash", line_color="#C0392B", annotation_text="100% (pleine capacité)")
    fig.update_layout(height=360, yaxis_title="Taux d'utilisation (%)", margin=dict(t=30, b=40))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Bleu foncé = poste en dépassement (≥ 100%). Bleu clair = sous la capacité. "
               "Taux plafonné à 200% à l'affichage (au-delà, la barre reste à 200% mais la charge réelle peut être plus grande).")


def _bar_retard_par_poste(tables: dict[str, pd.DataFrame], postes_perimetre: list[str]):
    df = calculer_of_retard_par_poste_perimetre(tables, postes_perimetre)
    if df.empty:
        st.caption("Aucun OF en cours sur ces postes actuellement.")
        return
    nb_postes = df["Poste_travail_actuel"].nunique()
    largeur = 0.4 if nb_postes <= 3 else None
    fig = go.Figure()
    for retard, couleur in [("Dans les temps", COULEURS["vert"]), ("En retard", COULEURS["orange"]),
                             ("Non renseigné", COULEURS["gris_moyen"])]:
        sous = df[df["Retard"] == retard]
        if sous.empty:
            continue
        fig.add_trace(go.Bar(name=retard, x=sous["Poste_travail_actuel"], y=sous["Nb_OF"], marker_color=couleur, width=largeur))
    fig.update_layout(barmode="stack", height=340, yaxis_title="Nb OF", margin=dict(t=10, b=60))
    fig.update_xaxes(tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)


def _pie_retard_departement(tables: dict[str, pd.DataFrame], dept: str):
    df = calculer_of_retard_departement(tables, dept)
    if df.empty:
        st.caption("Aucun OF en cours dans ce département.")
        return
    couleurs_map = {"Dans les temps": COULEURS["vert"], "En retard": COULEURS["orange"], "Non renseigné": COULEURS["gris_moyen"]}
    fig = go.Figure(go.Pie(labels=df["Retard"], values=df["Nb_OF"], hole=0.5,
                            marker_colors=[couleurs_map.get(r, COULEURS["gris_moyen"]) for r in df["Retard"]]))
    fig.update_layout(height=340, margin=dict(t=10))
    st.plotly_chart(fig, use_container_width=True)



# ========================================================================
# Cartes / helpers département
# ========================================================================
def _carte_kpi(icone: str, valeur: str, label: str, alerte: bool = False) -> str:
    bg = "#FBEEE4" if alerte else COULEURS["blanc"]
    couleur_valeur = COULEURS["orange_fonce"] if alerte else COULEURS["bleu_fonce"]
    border = f"2px solid {COULEURS['orange']}" if alerte else f"1px solid {COULEURS['gris_moyen']}"
    return f"""
    <div style="background:{bg}; border:{border}; border-radius:10px; padding:14px; text-align:left; min-height:90px;">
      <div style="font-size:22px;">{icone}</div>
      <div style="font-size:22px; font-weight:700; color:{couleur_valeur};">{valeur}</div>
      <div style="font-size:12px; color:{COULEURS['gris_fonce']};">{label}</div>
    </div>"""


def _bar_departements(df_dept: pd.DataFrame):
    df = df_dept.sort_values("Taux_utilisation", ascending=False)
    valeurs_pct = df["Taux_utilisation"] * 100
    couleurs = [COULEURS["orange"] if v >= SEUIL_GOULOT_PCT else COULEURS["bleu_fonce"] for v in valeurs_pct]
    largeur = 0.4 if len(df) <= 3 else None
    fig = go.Figure(go.Bar(
        x=df["Departement"], y=valeurs_pct, marker_color=couleurs, width=largeur,
        text=[f"{v:.0f}%" for v in valeurs_pct], textposition="outside",
    ))
    fig.add_hline(y=SEUIL_GOULOT_PCT, line_dash="dash", line_color="#C0392B",
                  annotation_text=f"Seuil goulot ({SEUIL_GOULOT_PCT}%)", annotation_position="top right")
    fig.update_layout(height=420, yaxis_title="Charge moyenne (%)", yaxis_range=[0, max(105, valeurs_pct.max() * 1.1)],
                       margin=dict(t=30, b=90))
    fig.update_xaxes(tickangle=-20)
    st.plotly_chart(fig, use_container_width=True)


def _tuiles_departements(df_dept: pd.DataFrame):
    df = df_dept.sort_values("Taux_utilisation", ascending=False)
    lignes_html = "<div style='display:grid; grid-template-columns:1fr 1fr; gap:8px;'>"
    for _, r in df.iterrows():
        pct = r["Taux_utilisation"] * 100
        est_goulot = pct >= SEUIL_GOULOT_PCT
        bg = COULEURS["orange"] if est_goulot else COULEURS["bleu_fonce"]
        cap_utilisee = r["Capacite_h_jour_totale"] * r["Taux_utilisation"]
        lignes_html += f"""
        <div style="background:{bg}; color:white; border-radius:8px; padding:12px;">
          <div style="font-size:13px; font-weight:700;">{r['Departement'].replace(' TUNISIE','').replace('UAP ','')}</div>
          <div style="font-size:24px; font-weight:700;">{pct:.0f}%</div>
          <div style="font-size:11px; opacity:0.9;">Capacité utilisée</div>
          <div style="font-size:13px; font-weight:600;">{cap_utilisee:.0f} h / jour</div>
        </div>"""
    lignes_html += "</div>"
    st.markdown(lignes_html, unsafe_allow_html=True)


def _message_goulot_postes(df_postes: pd.DataFrame):
    """Message clair sur le poste goulot GLOBAL, plutôt qu'un classement dense."""
    if df_postes.empty:
        return
    top = df_postes.sort_values("Taux_utilisation", ascending=False).iloc[0]
    st.markdown(f"""
    <div style="background:#FBEEE4; border-left:6px solid {COULEURS['orange_fonce']}; border-radius:8px;
                padding:16px 20px;">
      <div style="font-size:15px; font-weight:700; color:{COULEURS['orange_fonce']};">
        🔴 Poste goulot global : {top['Poste de Charge']} {'(externe, sous-traitance)' if top['Est_operation_externe'] else ''}
      </div>
      <div style="font-size:13px; color:{COULEURS['gris_fonce']}; margin-top:4px;">
        Taux d'utilisation <b>{top['Taux_utilisation'] * 100:.0f}%</b> ·
        charge restante <b>{_fmt_h_j(top['Charge_totale_restante_h'])}</b>.
      </div>
    </div>""", unsafe_allow_html=True)
    reste = df_postes.sort_values("Taux_utilisation", ascending=False).iloc[1:3]
    if len(reste):
        noms = ", ".join(f"{r['Poste de Charge']} ({r['Taux_utilisation'] * 100:.0f}%)" for _, r in reste.iterrows())
        st.caption(f"Ensuite : {noms}.")


def _donut_va_nonva(tables: dict[str, pd.DataFrame], dept: str):
    ops = tables["Operations_par_OF"]
    sous = ops[ops["Département Description"] == dept].copy()
    for c in ["Temps préparation machine (ajusté)", "Capacite_pour_formule", "Facteur exécution machine",
              "Temps transport", "Attente_calculee_h"]:
        if c in sous.columns:
            sous[c] = pd.to_numeric(sous[c], errors="coerce").fillna(0)
        else:
            sous[c] = 0.0

    va = (sous["Capacite_pour_formule"] * sous["Facteur exécution machine"]).sum()
    preparation = sous["Temps préparation machine (ajusté)"].sum()
    attente = sous["Attente_calculee_h"].sum()
    sous_traitance = sous.loc[sous.get("Est_operation_externe", False) == True, "Temps opération"].sum() if "Est_operation_externe" in sous.columns else 0

    labels = ["Temps opération (VA)", "Attente / File (NVA)", "Préparation", "Sous-traitance"]
    valeurs = [va, attente, preparation, sous_traitance]
    if sum(valeurs) == 0:
        st.caption("Pas assez de données pour ce département.")
        return
    fig = go.Figure(go.Pie(
        labels=labels, values=valeurs, hole=0.55,
        marker_colors=[COULEURS["bleu_fonce"], COULEURS["bleu"], COULEURS["orange"], COULEURS["gris_moyen"]],
        textinfo="percent",
    ))
    fig.update_layout(height=340, margin=dict(t=10, b=10), showlegend=True,
                       legend=dict(orientation="h", y=-0.15, font=dict(size=9)))
    st.plotly_chart(fig, use_container_width=True)


def _tendance_reelle(tables: dict[str, pd.DataFrame], dept: str):
    """Tendance RÉELLE (pas fabriquée) : nombre d'opérations clôturées par
    semaine pour ce département, à partir de 'Date fin op. réelle'."""
    ops = tables["Operations_par_OF"]
    sous = ops[(ops["Département Description"] == dept) & (ops["Statut d'opération"] == "Clôturé")].copy()
    if "Date fin op. réelle" not in sous.columns or sous.empty:
        st.caption("Historique quotidien non disponible pour ce département.")
        return
    sous["Date fin op. réelle"] = pd.to_datetime(sous["Date fin op. réelle"], errors="coerce")
    sous = sous.dropna(subset=["Date fin op. réelle"])
    if sous.empty:
        st.caption("Pas de dates réelles exploitables pour ce département.")
        return
    hebdo = sous.set_index("Date fin op. réelle").resample("W").size().tail(10)
    fig = go.Figure(go.Scatter(
        x=hebdo.index, y=hebdo.values, mode="lines+markers",
        line=dict(color=COULEURS["orange"], width=2), marker=dict(size=6),
    ))
    fig.update_layout(height=340, yaxis_title="Opérations clôturées / semaine", margin=dict(t=10, b=40))
    st.plotly_chart(fig, use_container_width=True)


# ========================================================================
# Détail d'UN poste précis (jauge + charge/capacité/goulot) -- SANS Îlots ni TRS
# ========================================================================
def _jauge(valeur_pct: float, titre: str, cle: str):
    couleur = COULEURS["vert"] if valeur_pct < 70 else (COULEURS["orange"] if valeur_pct < 90 else "#B0342A")
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=valeur_pct, title={"text": titre, "font": {"size": 13}},
        number={"suffix": "%", "font": {"size": 22}},
        gauge={
            "axis": {"range": [0, 150]},
            "bar": {"color": couleur},
            "bgcolor": COULEURS["gris_clair"],
            "steps": [
                {"range": [0, 70], "color": "#EAF3EE"},
                {"range": [70, 90], "color": "#FBEEE4"},
                {"range": [90, 150], "color": "#FBE4E1"},
            ],
        },
    ))
    fig.update_layout(height=190, margin=dict(t=40, b=10, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True, key=cle)


def _afficher_detail_poste(df_kpi: pd.DataFrame, tables: dict[str, pd.DataFrame], poste: str):
    detail = detail_poste(df_kpi, tables, poste)
    if not detail:
        st.info("Aucune donnée pour ce poste.")
        return
    kpi = detail["kpi"]

    est_externe = kpi.get("Est_operation_externe", False)
    badge = "🟧 Poste EXTERNE (sous-traitance)" if est_externe else "🟦 Poste INTERNE"
    st.markdown(f"#### {poste} — {kpi.get('Description', '')}  &nbsp; {badge}")

    g1, m1, m2 = st.columns([1, 1, 1])
    with g1:
        _jauge(kpi.get("Taux_utilisation", 0) * 100, "Taux d'utilisation", f"gauge_util_{poste}")
    with m1:
        st.metric("Temps opération moyen", f"{kpi.get('Temps_operation_moyen_h', 0):.1f} h")
        st.metric("Capacité", _fmt_h_j(kpi.get('Capacite_h_jour', 0)) + "/jour")
    with m2:
        st.metric("Charge totale restante", _fmt_h_j(kpi.get('Charge_totale_restante_h', 0)))
        st.metric("OF distincts concernés", f"{int(kpi.get('Nb_OF_distincts_restants', 0))}")

    with st.expander("Voir les opérations de ce poste (détail brut)"):
        st.dataframe(detail["operations"], use_container_width=True, hide_index=True)

    _section_charge_capacite_goulot(tables, poste)


def _section_charge_capacite_goulot(tables: dict[str, pd.DataFrame], poste: str):
    st.markdown("#### 📦 Charge / Capacité / Goulot")
    df_charge = calculer_charge_capacite_postes(tables)
    ligne = df_charge[df_charge["Poste de Charge"] == poste]
    if ligne.empty:
        return
    r = ligne.iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Charge restante", _fmt_h_j(r['Charge_h']))
    c2.metric("Capacité dispo", _fmt_h_j(r['Capacite_dispo_h_jour']) + "/jour")
    c3.metric("Jours de charge", f"{r['Jours_de_charge']:.1f} j")
    c4.metric("Taux de charge", f"{r['Taux_charge_pct']:.0f} %")
    c5.metric("OF concernés", f"{int(r['Nb_OF_concernes'])}")
    if r["Est_goulot"]:
        st.markdown("🔴 **Ce poste est le GOULOT actuel (taux de charge le plus élevé de l'atelier).**")
    if "Charge_non_simulee_h" in r and r["Charge_non_simulee_h"] > 0:
        st.caption(f"Dont {_fmt_h_j(r['Charge_simulee_h'])} simulée (OF 'En cours', suit le curseur temporel) et "
                   f"{_fmt_h_j(r['Charge_non_simulee_h'])} non simulée (OF pas encore démarrés -- Libérée/En attente/"
                   f"Partiellement déclarée -- ne bouge pas avec le curseur, hors du périmètre simulé).")
    st.caption("Charge = Σ Temps opération (opérations non clôturées) sur ce poste. "
               "Capacité dispo = Nbre Max Heures Par Op. × Nombre de machines. "
               "Taux de charge = Charge / (Capacité × horizon auto-calibré sur le poste le plus chargé).")

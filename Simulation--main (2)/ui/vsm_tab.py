"""
ui/vsm_tab.py
===============
Onglet VSM (Value Stream Mapping) PAR FAMILLE DE PRODUITS -- au sens Lean
classique, complémentaire du diagramme VSM par OF déjà présent dans
l'onglet OF (ui/vsm_render.py, cycle complet d'un seul OF).

1. Détection automatique des familles de produits (signature de gamme,
   recouvrement >= 80%, cf backend.vsm.detecter_familles) -- calculée sur
   `tables` (indépendante du curseur temporel : la gamme d'un produit ne
   change pas avec le temps).
2. Sélection d'une famille -> construction du VSM (backend.vsm.
   construire_vsm_famille) à partir de `tables` (déjà `tables_vue`, donc
   curseur temporel pris en compte pour le stock mesuré en encours réel,
   comme les autres onglets de l'application).
3. Rendu du schéma (boîtes + triangles de stock + timeline alignée,
   ui.vsm_famille_render) + KPI de synthèse (Lead Time, PCE) + détail
   chiffré pour la traçabilité.
"""

import datetime

import pandas as pd
import streamlit as st

from backend.vsm import detecter_familles, construire_vsm_famille
from ui.vsm_famille_render import rendu_vsm_famille_html
from theme import COULEURS


def _carte_kpi(icone: str, valeur: str, label: str, alerte: bool = False) -> str:
    couleur = COULEURS["orange_fonce"] if alerte else COULEURS["bleu_fonce"]
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{icone} {label}</div>
        <div class="kpi-value" style="color:{couleur};">{valeur}</div>
    </div>
    """


def afficher(tables: dict[str, pd.DataFrame]):
    st.markdown("### 🧭 VSM DIGITALISÉ — CARTOGRAPHIE PAR FAMILLE DE PRODUITS")
    st.caption(
        "Value Stream Mapping au sens Lean classique : une famille = un ensemble d'articles qui partagent "
        "globalement la même gamme de postes (recouvrement ≥ 80%). Le stock entre les postes est mesuré "
        "sur l'encours réel (OF actuellement en attente) — il suit donc le curseur temporel global."
    )

    df_familles = detecter_familles(tables)
    if df_familles.empty:
        st.warning("Aucune famille de produits détectée (données de gamme insuffisantes).")
        return

    with st.expander("📋 Familles détectées (voir le détail du regroupement)"):
        st.dataframe(
            df_familles[["Famille", "Nb_articles", "Nb_OF", "Nb_postes"]].rename(columns={
                "Nb_articles": "Nb articles", "Nb_OF": "Nb OF", "Nb_postes": "Nb postes (gamme type)",
            }),
            use_container_width=True, hide_index=True,
        )

    options = [
        f'{row.Famille} — {row.Nb_OF} OF, {row.Nb_articles} article(s), {row.Nb_postes} poste(s)'
        for row in df_familles.itertuples()
    ]
    choix = st.selectbox("Choisir la famille à cartographier", options, index=0)
    idx = options.index(choix)
    ligne_famille = df_familles.iloc[idx]

    if ligne_famille["Nb_postes"] < 2:
        st.info("Cette famille n'a qu'un seul poste dans sa gamme type — pas de stock à représenter entre "
                "postes, mais le schéma reste affiché ci-dessous.")

    vsm_data = construire_vsm_famille(tables, ligne_famille["Gamme_type"], ligne_famille["Articles"])
    kpi = vsm_data["kpi"]

    cols = st.columns(4)
    cols[0].markdown(_carte_kpi("⏱️", f'{kpi["Lead_time_jours"]:.1f} j', "Lead Time total"), unsafe_allow_html=True)
    cols[1].markdown(_carte_kpi("✅", f'{kpi["Valeur_ajoutee_h"]:.2f} h', "Temps à valeur ajoutée (Σ C/T)"), unsafe_allow_html=True)
    alerte_pce = kpi["PCE_pct"] < 5
    cols[2].markdown(_carte_kpi("📐", f'{kpi["PCE_pct"]:.2f} %', "PCE (efficience du cycle)", alerte=alerte_pce), unsafe_allow_html=True)
    cols[3].markdown(_carte_kpi("📦", str(kpi["Nb_OF_en_cours_famille"]), "OF en cours (famille)"), unsafe_allow_html=True)

    if alerte_pce:
        st.markdown(
            '<div class="bloc-alerte">⚠️ PCE très faible : c\'est normal et attendu en VSM classique '
            "(le temps de traitement pur pèse peu face aux jours de stock/attente) — c'est justement "
            "ce ratio qui indique le potentiel d'amélioration Lean.</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    t_vue_h = st.session_state.get("t_vue_h", 0.0)
    if "sim_reel" in st.session_state and t_vue_h > 0:
        _, _, extra = st.session_state["sim_reel"]
        date_vue = extra["infos"]["maintenant"] + datetime.timedelta(hours=t_vue_h)
        sous_titre = f"État projeté au {date_vue.strftime('%d/%m/%Y')} (curseur temporel) — stock mesuré à cette date"
    else:
        sous_titre = "État réel actuel — stock mesuré maintenant"

    html = rendu_vsm_famille_html(
        vsm_data,
        titre=f'VSM — {ligne_famille["Famille"]} ({int(ligne_famille["Nb_OF"])} OF, {int(ligne_famille["Nb_articles"])} article(s))',
        sous_titre=sous_titre,
    )
    st.markdown(html, unsafe_allow_html=True)

    with st.expander("🔎 Détail chiffré (data-box par poste)"):
        st.dataframe(pd.DataFrame(vsm_data["postes"]), use_container_width=True, hide_index=True)

    if vsm_data["stocks"]:
        with st.expander("🔎 Détail chiffré (stock entre postes, mesuré en encours réel)"):
            st.dataframe(pd.DataFrame(vsm_data["stocks"]), use_container_width=True, hide_index=True)

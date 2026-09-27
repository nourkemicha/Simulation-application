"""
ui/donnees_tab.py
====================
Onglet DONNÉES : visualisation façon tableur des tables produites par
transform_v3 (OF, Poste_de_charge, Operation, Operations_par_OF,
Verification_encours) et des résultats de simulation (théorique et réelle,
si déjà lancées dans l'onglet SCÉNARIO) -- avec export CSV/Excel.

IMPORTANT (perf) : l'export est déclenché EXPLICITEMENT par un bouton et mis
en cache dans session_state -- jamais recalculé à chaque rerender. Sur une
table volumineuse (Operations_par_OF : ~67 000 lignes x 133 colonnes), écrire
un .xlsx colonne par colonne (moteur xlsxwriter) peut prendre plusieurs
minutes ; le CSV (quelques secondes) est donc proposé en premier pour ces
tables, l'Excel restant disponible mais avec un avertissement de durée.
"""

import io

import pandas as pd
import streamlit as st

SEUIL_LIGNES_LOURD = 15_000


def afficher(tables: dict[str, pd.DataFrame]):
    st.markdown("### 📋 Données : fichier transformé & résultats de simulation")

    st.subheader("Fichier transformé (transform_v3)")
    feuilles_transform = ["OF", "Poste_de_charge", "Operation", "Operations_par_OF", "Verification_encours"]
    feuille = st.selectbox("Feuille :", feuilles_transform)
    df = tables.get(feuille, pd.DataFrame())
    st.caption(f"{len(df)} ligne(s) × {df.shape[1] if len(df) else 0} colonne(s)")
    st.dataframe(df.head(500), use_container_width=True, hide_index=True, height=420)
    if len(df) > 500:
        st.caption("Aperçu limité aux 500 premières lignes (export complet ci-dessous).")

    _bloc_export(f"{feuille}", {feuille: df})

    st.divider()
    st.subheader("Résultats de simulation")
    choix_sim = st.radio("Jeu de résultats :", ["Théorique", "Réelle (SimPy)"], horizontal=True)

    if choix_sim == "Théorique":
        if "sim_theo" not in st.session_state:
            st.info("Lance la simulation (onglet SCÉNARIO) pour voir ces résultats.")
            return
        df_theo, df_detail_theo = st.session_state["sim_theo"]
        sous_onglet = st.selectbox("Table :", ["Projection_par_OF", "Detail_operations"])
        table_choisie = df_theo if sous_onglet == "Projection_par_OF" else df_detail_theo
        st.dataframe(table_choisie.head(500), use_container_width=True, hide_index=True, height=420)
        _bloc_export("resultats_theorique", {"Projection_par_OF": df_theo, "Detail_operations": df_detail_theo})
    else:
        if "sim_reel" not in st.session_state:
            st.info("Lance la simulation (onglet SCÉNARIO) pour voir ces résultats.")
            return
        vsm, df_detail, extra = st.session_state["sim_reel"]
        tables_sim = {
            "Resultats_OF": vsm, "Journal_operations": extra["journal"],
            "Goulots_postes": extra["goulots"], "Goulot_externe": extra["goulot_externe"],
            "Anomalies_donnees": extra["anomalies"],
        }
        sous_onglet = st.selectbox("Table :", list(tables_sim.keys()))
        st.dataframe(tables_sim[sous_onglet].head(500), use_container_width=True, hide_index=True, height=420)
        _bloc_export("resultats_simulation_REEL", tables_sim)


def _bloc_export(nom_base: str, tables_dict: dict[str, pd.DataFrame]):
    """Boutons d'export à la demande (jamais calculés automatiquement).
    CSV proposé pour chaque table individuellement (rapide, toujours dispo) ;
    Excel multi-feuilles généré uniquement sur clic, avec avertissement si
    une table dépasse SEUIL_LIGNES_LOURD lignes."""
    nb_lignes_max = max((len(df) for df in tables_dict.values() if df is not None), default=0)
    cle = f"export_{nom_base}"

    c1, c2 = st.columns(2)
    with c1:
        for nom, df in tables_dict.items():
            if df is None or df.empty:
                continue
            st.download_button(f"⬇️ CSV — {nom}", data=_vers_csv(df), file_name=f"{nom}.csv",
                                key=f"{cle}_csv_{nom}", use_container_width=True)

    with c2:
        if nb_lignes_max > SEUIL_LIGNES_LOURD:
            st.caption(f"⚠️ Jusqu'à {nb_lignes_max:,} lignes dans ces tables — la génération Excel peut prendre "
                       f"plusieurs minutes. Le CSV (ci-contre) est recommandé.".replace(",", " "))
        if st.button(f"🧮 Générer le fichier Excel ({nom_base}.xlsx)", key=f"{cle}_gen"):
            with st.spinner("Génération du fichier Excel..."):
                st.session_state[cle] = _vers_excel(tables_dict)
        if cle in st.session_state:
            st.download_button("⬇️ Télécharger l'Excel généré", data=st.session_state[cle],
                                file_name=f"{nom_base}.xlsx", key=f"{cle}_dl", use_container_width=True)


def _vers_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def _vers_excel(tables_dict: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        for nom, df in tables_dict.items():
            if df is None:
                continue
            df_export = df.copy()
            for c in df_export.columns:
                if pd.api.types.is_datetime64tz_dtype(df_export[c]):
                    df_export[c] = df_export[c].dt.tz_localize(None)
            df_export.to_excel(writer, sheet_name=str(nom)[:31], index=False)
    return buffer.getvalue()

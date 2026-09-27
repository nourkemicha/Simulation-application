"""
backend/vsm.py
=================
VSM (Value Stream Mapping) PAR FAMILLE DE PRODUITS -- au sens Lean
classique (Rother & Shook, "Learning to See") : une famille = un ensemble
d'articles qui partagent globalement la même gamme de postes. On ne fait
jamais un VSM par référence produit individuelle ni par OF isolé -- c'est
ui/vsm_render.py qui s'occupe déjà de ça (diagramme du cycle complet d'UN
SEUL OF, dans l'onglet OF) ; celui-ci est complémentaire, pas un remplacement.

Ce module ne fait QUE le calcul (données) -- le rendu (boîtes HTML +
timeline SVG alignée) est dans ui/vsm_famille_render.py, comme la
convention déjà en place dans ce projet (ui/vsm_render.py).

--------------------------------------------------------------------
ÉTAPE 1 -- Détection des familles (indépendant du curseur temporel)
--------------------------------------------------------------------
Pour chaque Article : on reconstitue sa signature de gamme = la séquence
ordonnée des postes distincts traversés (toutes opérations confondues,
peu importe leur statut -- la gamme est une caractéristique du PRODUIT,
pas de son état d'avancement).
On regroupe ensuite les articles par recouvrement de gamme (indice de
Jaccard sur l'ensemble des postes) >= seuil (0.8 par défaut, validé avec
l'utilisateur = "signature approximative, 80% de recouvrement").
Algorithme glouton simple : un article rejoint le premier cluster
existant dont le recouvrement avec sa gamme est suffisant, sinon il crée
un nouveau cluster.

--------------------------------------------------------------------
ÉTAPE 2 -- Construction du VSM pour une famille choisie
--------------------------------------------------------------------
Recalculée à CHAQUE appel à partir de `tables` -- si on lui passe
`tables_vue` (déjà projeté par backend.simulation.projeter_etat_a_date à
la date du curseur temporel global, comme les autres onglets dans
app.py), le VSM devient lui aussi piloté par le curseur (validé avec
l'utilisateur) :
  - data-box par poste (C/T, C/O, disponibilité, nb machines, taille de
    lot) : caractéristique du PROCESS, calculée sur l'historique complet
    de la famille (toutes opérations, peu importe le statut) -- ne bouge
    pas avec le curseur, c'est une donnée structurelle.
  - stock entre 2 postes consécutifs de la gamme : MESURÉ EN TEMPS RÉEL
    -- nb d'OF de la famille actuellement "En cours" avec
    Poste_travail_actuel == poste amont, et jours de stock =
    Temps_sur_poste_actuel_h (déjà en JOURS malgré son nom, cf.
    backend/simulation.py) -- DÉPEND du curseur puisque `tables["OF"]`
    (Etat_OF_encours / Poste_travail_actuel) change avec lui dans
    projeter_etat_a_date.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

SEUIL_RECOUVREMENT_DEFAUT = 0.8


# ======================================================================
# ÉTAPE 1 -- Détection des familles de produits (signature de gamme)
# ======================================================================
def _gamme_par_article(ops: pd.DataFrame) -> pd.Series:
    """Pour chaque Article : tuple ordonné des postes distincts traversés
    (ordre = position moyenne de "Séq. opération" sur cet article, tous OF
    confondus, TOUTES opérations -- clôturées ou non : la gamme est une
    caractéristique du produit, indépendante de l'avancement actuel)."""
    df = ops.dropna(subset=["Article", "Poste de Charge", "Séq. opération"]).copy()
    df["Séq. opération"] = pd.to_numeric(df["Séq. opération"], errors="coerce")
    df = df.dropna(subset=["Séq. opération"])
    if df.empty:
        return pd.Series(dtype=object)
    pos = df.groupby(["Article", "Poste de Charge"])["Séq. opération"].mean().reset_index()
    pos = pos.sort_values(["Article", "Séq. opération"])
    return pos.groupby("Article")["Poste de Charge"].apply(lambda s: tuple(s.tolist()))


def _recouvrement(a: tuple, b: tuple) -> float:
    """Indice de Jaccard entre 2 gammes = |postes communs| / |union|.
    C'est la "signature approximative, X% de recouvrement" retenue avec
    l'utilisateur (recouvrement d'ENSEMBLE de postes, pas de sous-suite
    ordonnée -- volontairement simple et robuste aux variantes de gamme)."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _gamme_type(gammes: list[tuple]) -> list[str]:
    """Gamme représentative d'un cluster : ne garde que les postes présents
    dans au moins la moitié des gammes du cluster (évite qu'un poste
    exceptionnel, présent sur 1 seul article, pollue la gamme type),
    ordonnés par leur position moyenne (normalisée 0-1) observée."""
    positions: dict[str, list[float]] = defaultdict(list)
    for g in gammes:
        denom = max(len(g) - 1, 1)
        for i, poste in enumerate(g):
            positions[poste].append(i / denom)
    seuil_presence = len(gammes) / 2
    postes_retenus = [p for p, v in positions.items() if len(v) >= seuil_presence]
    postes_retenus.sort(key=lambda p: sum(positions[p]) / len(positions[p]))
    return postes_retenus


def detecter_familles(tables: dict[str, pd.DataFrame], seuil: float = SEUIL_RECOUVREMENT_DEFAUT) -> pd.DataFrame:
    """1 ligne par famille détectée : Famille, Nb_articles, Nb_OF,
    Nb_postes, Gamme_type (liste de postes, dans l'ordre), Articles (liste
    des articles du cluster). Triée par Nb_OF décroissant (les familles à
    fort volume d'abord)."""
    ops = tables["Operations_par_OF"]
    gammes = _gamme_par_article(ops)
    if gammes.empty:
        return pd.DataFrame(columns=["Famille", "Nb_articles", "Nb_OF", "Nb_postes", "Gamme_type", "Articles"])

    clusters: list[dict] = []
    for article, gamme in gammes.items():
        if not gamme:
            continue
        place = False
        for c in clusters:
            if _recouvrement(gamme, c["gamme_ref"]) >= seuil:
                c["articles"].append(article)
                c["gammes"].append(gamme)
                place = True
                break
        if not place:
            clusters.append({"gamme_ref": gamme, "articles": [article], "gammes": [gamme]})

    nb_of_par_article = ops.dropna(subset=["Article"]).groupby("Article")["N° ordre"].nunique()

    lignes = []
    for c in clusters:
        gamme_type = _gamme_type(c["gammes"])
        if not gamme_type:
            continue
        nb_of = int(nb_of_par_article.reindex(c["articles"]).fillna(0).sum())
        lignes.append({
            "Nb_articles": len(c["articles"]),
            "Nb_OF": nb_of,
            "Nb_postes": len(gamme_type),
            "Gamme_type": gamme_type,
            "Articles": c["articles"],
        })

    df = pd.DataFrame(lignes).sort_values("Nb_OF", ascending=False).reset_index(drop=True)
    df.insert(0, "Famille", [f"Famille {i + 1}" for i in range(len(df))])
    return df


# ======================================================================
# ÉTAPE 2 -- Construction du VSM pour une famille choisie
# ======================================================================
def _disponibilite_par_poste(tables: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Réutilise le TRS déjà calculé (backend.kpi_postes) pour la
    disponibilité machine par poste. Retombe sur un dict vide (->
    disponibilité affichée à 100%, comme documenté partout ailleurs dans
    le projet : aucune donnée d'arrêt machine dans l'ERP fourni) si le
    calcul échoue ou si la colonne n'existe pas."""
    try:
        from backend.kpi_postes import calculer_trs_periodique
        df_trs = calculer_trs_periodique(tables, granularite="M")
    except Exception:
        return {}
    if df_trs is None or df_trs.empty:
        return {}
    col_dispo = next((c for c in df_trs.columns if c.lower().startswith("disponibilit")), None)
    col_poste = next((c for c in df_trs.columns if "poste" in c.lower()), None)
    if not col_dispo or not col_poste:
        return {}
    return df_trs.groupby(col_poste)[col_dispo].mean().to_dict()


def construire_vsm_famille(tables: dict[str, pd.DataFrame], gamme_type: list[str],
                            articles_famille: list[str]) -> dict:
    """Construit les données du VSM pour une famille (gamme_type + la
    liste d'articles qui la composent), à partir de `tables` -- passer
    `tables_vue` (projeté au curseur temporel) pour que le stock (mesuré
    en encours réel) suive le curseur, comme les autres onglets.

    Retourne :
      {
        "postes": [ {Poste, Description, CT_h, CO_h, Disponibilite_pct,
                     Nb_machines, Ouverture_h_jour, Taille_lot,
                     Nb_operations_historique}, ... ]   # dans l'ordre de la gamme
        "stocks": [ {Apres_poste, Nb_OF_en_attente, Qte_en_attente,
                     Jours_stock}, ... ]                 # len = len(postes) - 1
        "kpi": {Lead_time_h, Lead_time_jours, Valeur_ajoutee_h, PCE_pct,
                Nb_OF_en_cours_famille}
      }
    """
    ops = tables["Operations_par_OF"].copy()
    of_df = tables["OF"].copy()
    postes_ref = tables["Poste_de_charge"].drop_duplicates(subset="Poste de charge").set_index("Poste de charge")

    ops_f = ops[ops["Article"].isin(articles_famille)].copy()
    of_f = of_df[of_df["Article"].isin(articles_famille)].copy()

    for c in ["Facteur exécution machine", "Temps préparation machine (ajusté)",
              "Taille lot ordre fabrication", "Qté opération"]:
        if c in ops_f.columns:
            ops_f[c] = pd.to_numeric(ops_f[c], errors="coerce")

    disponibilites = _disponibilite_par_poste(tables)

    postes_kpi = []
    for poste in gamme_type:
        lignes = ops_f[ops_f["Poste de Charge"] == poste]
        ref = postes_ref.loc[poste] if poste in postes_ref.index else None

        ct_h = float(lignes["Facteur exécution machine"].mean()) if len(lignes) else 0.0
        co_h = float(lignes["Temps préparation machine (ajusté)"].mean()) if len(lignes) else 0.0
        lot = float(lignes["Taille lot ordre fabrication"].mean()) if len(lignes) else 0.0
        nb_machines = int(ref["Nombre de machines"]) if ref is not None and pd.notna(ref.get("Nombre de machines")) else 1
        ouverture = float(ref["Nbre Max Heures Par Op."]) if ref is not None and pd.notna(ref.get("Nbre Max Heures Par Op.")) else 0.0
        description = str(ref["Description poste de charge"]) if ref is not None and pd.notna(ref.get("Description poste de charge")) else poste
        dispo_pct = round(disponibilites.get(poste, 1.0) * 100, 1)
        # Externe (sous-traitance) : lu depuis le référentiel Poste_de_charge
        # (colonne déjà calculée par transform_v3 -- même source que
        # partout ailleurs dans l'appli, ex: kpi_postes.py).
        externe = bool(ref["Est_operation_externe"]) if ref is not None and pd.notna(ref.get("Est_operation_externe")) else False

        postes_kpi.append({
            "Poste": poste,
            "Description": description,
            "CT_h": round(ct_h, 3),
            "CO_h": round(co_h, 2),
            "Disponibilite_pct": dispo_pct,
            "Nb_machines": nb_machines,
            "Ouverture_h_jour": round(ouverture, 1),
            "Taille_lot": round(lot, 0) if pd.notna(lot) else 0,
            "Nb_operations_historique": int(len(lignes)),
            "Est_operation_externe": externe,
        })

    stocks = []
    for i in range(len(gamme_type) - 1):
        poste_amont = gamme_type[i]
        en_attente = of_f[(of_f["Etat_OF_encours"] == "En cours") & (of_f["Poste_travail_actuel"] == poste_amont)]
        nb_of_stock = int(len(en_attente))
        qte_stock = float(en_attente["Qte_OF"].sum()) if nb_of_stock and "Qte_OF" in en_attente.columns else 0.0
        jours_stock = float(en_attente["Temps_sur_poste_actuel_h"].mean()) if nb_of_stock else 0.0
        stocks.append({
            "Apres_poste": poste_amont,
            "Nb_OF_en_attente": nb_of_stock,
            "Qte_en_attente": round(qte_stock, 0),
            "Jours_stock": round(jours_stock, 1),
        })

    lead_time_h = sum(s["Jours_stock"] * 24 for s in stocks) + sum(p["CT_h"] for p in postes_kpi)
    valeur_ajoutee_h = sum(p["CT_h"] for p in postes_kpi)
    pce_pct = round(valeur_ajoutee_h / lead_time_h * 100, 2) if lead_time_h > 0 else 0.0

    return {
        "postes": postes_kpi,
        "stocks": stocks,
        "kpi": {
            "Lead_time_h": round(lead_time_h, 2),
            "Lead_time_jours": round(lead_time_h / 24, 2),
            "Valeur_ajoutee_h": round(valeur_ajoutee_h, 3),
            "PCE_pct": pce_pct,
            "Nb_OF_en_cours_famille": int((of_f["Etat_OF_encours"] == "En cours").sum()),
        },
    }

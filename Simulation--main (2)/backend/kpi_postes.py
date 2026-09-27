"""
backend/kpi_postes.py
========================
KPIs "métier" demandés spécifiquement :

POSTES
------
- Charge (h)        = Σ Temps opération, opérations NON clôturées, pour ce poste
                       (le travail qui reste à absorber sur ce poste).
- Capacité dispo (h/jour) = Nbre Max Heures Par Op. (heures d'ouverture/jour)
                       x Nombre de machines (poste_de_charge, cf transform_v3 /
                       surcharge utilisateur).
- Taux de charge (%) = Charge / (Capacité dispo x horizon en jours). L'horizon
                       est auto-calibré (le poste le plus chargé sert de
                       référence, comme dans backend/kpi.py) -- affiché aussi
                       en "jours de charge" = Charge / Capacité dispo (plus
                       lisible : combien de jours d'ouverture à pleine
                       capacité pour écouler le poste).
- Goulot            = le(s) poste(s) au taux de charge le plus élevé.
- Nb OF concernés   = nb OF distincts avec au moins une opération non
                       clôturée sur ce poste.

TRS (par jour / semaine / mois), calculé sur l'HISTORIQUE RÉEL (opérations
clôturées, "Date fin op. réelle") :
- Disponibilité = 1 par défaut (aucune donnée d'arrêt machine dans l'ERP
                  fourni -- prévu pour être remplacé par
                  temps de fonctionnement réel / temps d'ouverture dès que
                  cette donnée existe, ou par un scénario de panne, voir
                  onglet Scénarios).
- Performance   = (Cycle paramétré moyen du poste x Qté produite période)
                  / Temps d'ouverture période. Le "cycle paramétré" n'existe
                  qu'au niveau OF/opération courante (encours.xlsx, colonne
                  "Cycle paramétré") -- on utilise ici, à défaut, le temps
                  d'exécution unitaire réel du poste ("Facteur exécution
                  machine", h/pièce) moyenné sur les opérations clôturées.
- Qualité       = (Qté produite - Qté rebut) / Qté produite.
- TRS           = Disponibilité x Performance x Qualité.

OF (par OF en cours)
---------------------
- Takt time (par poste) = Temps d'ouverture poste / Nb OF "Libéré" en attente
                           sur ce poste (rythme demandé par la charge actuelle).
- CT (Cycle Time)  = Σ (Temps opération - Attente_calculee_h) sur la gamme
                     restante -> temps de TRAITEMENT pur, sans attente.
- Lead Time (LT)   = Σ Temps opération (= CT + attente), gamme restante.
- % Temps VA       = Σ (Facteur exécution machine x Capacite_pour_formule)
                     / LT x 100 -- part du Lead Time qui est du temps
                     d'exécution machine (valeur ajoutée), le reste étant
                     préparation/attente/transport.
- OTD              = OF clôturés dans les temps (Date_fin_reelle <=
                     Date_fin_planifiee) / OF clôturés total x 100.
"""

from __future__ import annotations

import pandas as pd

STATUT_CLOTURE = "Clôturé"
STATUT_LIBERE = "Libéré"


# ------------------------------------------------------------------
# POSTES : charge / capacité / taux de charge / goulot
# ------------------------------------------------------------------
def calculer_charge_capacite_postes(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ops = tables["Operations_par_OF"].copy()
    postes = tables["Poste_de_charge"].copy()
    of_df = tables["OF"]

    ops["Temps opération"] = pd.to_numeric(ops["Temps opération"], errors="coerce").fillna(0)
    ops_restantes = ops[ops["Statut d'opération"] != STATUT_CLOTURE].copy()

    # -- Charge SIMULÉE (OF "En cours", suit le curseur temporel -- va à 0 à
    # la fin de l'horizon simulé) vs NON SIMULÉE (OF pas encore démarrés :
    # Libérée/En attente/Partiellement déclarée -- hors périmètre de la
    # simulation, reste constante quel que soit le curseur).
    etat_par_of = of_df.set_index("N° ordre (OF)")["Etat_OF_encours"]
    ops_restantes["Est_simule"] = ops_restantes["N° ordre"].map(etat_par_of) == "En cours"

    charge = ops_restantes.groupby("Poste de Charge")["Temps opération"].sum().rename("Charge_h")
    charge_simulee = ops_restantes[ops_restantes["Est_simule"]].groupby("Poste de Charge")["Temps opération"].sum().rename("Charge_simulee_h")
    charge_non_simulee = ops_restantes[~ops_restantes["Est_simule"]].groupby("Poste de Charge")["Temps opération"].sum().rename("Charge_non_simulee_h")
    nb_of = ops_restantes.groupby("Poste de Charge")["N° ordre"].nunique().rename("Nb_OF_concernes")
    nb_ops_libre = (
        ops[ops["Statut d'opération"] == STATUT_LIBERE]
        .groupby("Poste de Charge")["N° ordre"].nunique().rename("Nb_OF_Libere")
    )

    df = postes[["Poste de charge", "Description poste de charge", "Département Description",
                 "Est_operation_externe", "Nbre Max Heures Par Op.", "Nombre de machines"]].copy()
    df = df.rename(columns={
        "Poste de charge": "Poste de Charge", "Description poste de charge": "Description",
        "Département Description": "Departement", "Nbre Max Heures Par Op.": "Heures_ouverture_jour",
    })
    df["Capacite_dispo_h_jour"] = df["Heures_ouverture_jour"].fillna(0) * df["Nombre de machines"].fillna(1)

    df = df.merge(charge, on="Poste de Charge", how="left")
    df = df.merge(charge_simulee, on="Poste de Charge", how="left")
    df = df.merge(charge_non_simulee, on="Poste de Charge", how="left")
    df = df.merge(nb_of, on="Poste de Charge", how="left")
    df = df.merge(nb_ops_libre, on="Poste de Charge", how="left")
    colonnes_a_combler = ["Charge_h", "Charge_simulee_h", "Charge_non_simulee_h", "Nb_OF_concernes", "Nb_OF_Libere"]
    df[colonnes_a_combler] = df[colonnes_a_combler].fillna(0)

    # Horizon auto-calibré (le poste le + chargé sert de référence, transparent)
    ratio = df["Charge_h"] / df["Capacite_dispo_h_jour"].replace(0, pd.NA)
    horizon_jours = max(float(ratio.max()) if ratio.notna().any() else 1.0, 1.0)

    df["Jours_de_charge"] = (df["Charge_h"] / df["Capacite_dispo_h_jour"].replace(0, pd.NA)).fillna(0)
    df["Taux_charge_pct"] = (df["Charge_h"] / (df["Capacite_dispo_h_jour"].replace(0, pd.NA) * horizon_jours) * 100).fillna(0)
    df["Taux_charge_pct"] = df["Taux_charge_pct"].clip(upper=150)

    # Takt time = temps ouverture (jour) / nb OF "Libéré" en attente sur ce poste
    df["Takt_time_h"] = (df["Capacite_dispo_h_jour"] / df["Nb_OF_Libere"].replace(0, pd.NA))

    df["Est_goulot"] = df["Taux_charge_pct"] >= df["Taux_charge_pct"].max() - 1e-9 if len(df) else False
    df.attrs["horizon_jours"] = horizon_jours
    return df.sort_values("Taux_charge_pct", ascending=False).reset_index(drop=True)


# ------------------------------------------------------------------
# TRS périodique (jour / semaine / mois), sur historique réel (Clôturé)
# ------------------------------------------------------------------
def calculer_trs_periodique(tables: dict[str, pd.DataFrame], granularite: str = "D",
                             disponibilite_par_poste: dict[str, float] | None = None) -> pd.DataFrame:
    """granularite : 'D' (jour), 'W' (semaine), 'M' (mois).
    disponibilite_par_poste : {poste: valeur 0-1} pour simuler un arrêt
    machine (scénario panne) -- défaut 1.0 (aucune donnée d'arrêt réelle)."""
    ops = tables["Operations_par_OF"].copy()
    postes = tables["Poste_de_charge"].copy()
    disponibilite_par_poste = disponibilite_par_poste or {}

    clot = ops[ops["Statut d'opération"] == STATUT_CLOTURE].copy()
    if "Date fin op. réelle" not in clot.columns or clot.empty:
        return pd.DataFrame()
    clot["Date fin op. réelle"] = pd.to_datetime(clot["Date fin op. réelle"], errors="coerce")
    clot = clot.dropna(subset=["Date fin op. réelle"])
    if clot.empty:
        return pd.DataFrame()

    for c in ["Qté complétée", "Qté mise au rebut", "Qté opération", "Facteur exécution machine"]:
        if c in clot.columns:
            clot[c] = pd.to_numeric(clot[c], errors="coerce").fillna(0)
        else:
            clot[c] = 0.0
    clot["Qte_produite"] = clot["Qté complétée"].where(clot["Qté complétée"] > 0, clot["Qté opération"])

    ouverture = postes.set_index("Poste de charge")[["Nbre Max Heures Par Op.", "Nombre de machines"]]
    ouverture["Capacite_h_jour"] = ouverture["Nbre Max Heures Par Op."].fillna(0) * ouverture["Nombre de machines"].fillna(1)
    cycle_moyen = clot.groupby("Poste de Charge")["Facteur exécution machine"].mean()

    clot["Periode"] = clot["Date fin op. réelle"].dt.to_period(granularite)

    lignes = []
    for (poste, periode), g in clot.groupby(["Poste de Charge", "Periode"]):
        cap_jour = ouverture["Capacite_h_jour"].get(poste, 0.0)
        nb_jours = _nb_jours_periode(periode, granularite)
        temps_ouverture = cap_jour * nb_jours
        qte_produite = g["Qte_produite"].sum()
        qte_rebut = g["Qté mise au rebut"].sum()
        cycle = cycle_moyen.get(poste, 0.0)

        disponibilite = disponibilite_par_poste.get(poste, 1.0)
        performance = min((cycle * qte_produite) / temps_ouverture, 1.5) if temps_ouverture > 0 else 0.0
        qualite = (qte_produite - qte_rebut) / qte_produite if qte_produite > 0 else 1.0
        trs = disponibilite * performance * qualite

        lignes.append({
            "Poste de Charge": poste, "Periode": str(periode), "Date_periode": periode.start_time,
            "Qte_produite": qte_produite, "Qte_rebut": qte_rebut,
            "Temps_ouverture_h": round(temps_ouverture, 1),
            "Disponibilite": round(disponibilite, 3), "Performance": round(performance, 3),
            "Qualite": round(qualite, 3), "TRS": round(trs, 3),
        })
    return pd.DataFrame(lignes).sort_values(["Poste de Charge", "Date_periode"]).reset_index(drop=True)


def _nb_jours_periode(periode, granularite: str) -> float:
    if granularite == "D":
        return 1.0
    if granularite == "W":
        return 7.0
    return periode.days_in_month if hasattr(periode, "days_in_month") else 30.0


# ------------------------------------------------------------------
# OF : takt time (via postes), CT, Lead Time, %VA, OTD
# ------------------------------------------------------------------
def calculer_kpi_of(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ops = tables["Operations_par_OF"].copy()
    of_df = tables["OF"]

    for c in ["Temps opération", "Attente_calculee_h", "Facteur exécution machine", "Capacite_pour_formule"]:
        if c in ops.columns:
            ops[c] = pd.to_numeric(ops[c], errors="coerce").fillna(0)
        else:
            ops[c] = 0.0

    ops_restantes = ops[ops["Statut d'opération"] != STATUT_CLOTURE].copy()
    ops_restantes["CT_h"] = (ops_restantes["Temps opération"] - ops_restantes["Attente_calculee_h"]).clip(lower=0)
    ops_restantes["VA_h"] = ops_restantes["Facteur exécution machine"] * ops_restantes["Capacite_pour_formule"]

    g = ops_restantes.groupby("N° ordre").agg(
        CT_h=("CT_h", "sum"), Lead_Time_h=("Temps opération", "sum"),
        VA_h=("VA_h", "sum"), Attente_totale_h=("Attente_calculee_h", "sum"),
        Nb_operations_restantes=("Séq. opération", "count"),
    ).reset_index().rename(columns={"N° ordre": "N° ordre (OF)"})
    g["Pct_VA"] = (g["VA_h"] / g["Lead_Time_h"].replace(0, pd.NA) * 100).fillna(0)

    df = of_df.merge(g, on="N° ordre (OF)", how="left")
    for c in ["CT_h", "Lead_Time_h", "VA_h", "Attente_totale_h", "Nb_operations_restantes", "Pct_VA"]:
        df[c] = df[c].fillna(0)
    return df


def calculer_otd_of(tables: dict[str, pd.DataFrame]) -> dict:
    """OTD = OF CLÔTURÉS dans les temps (Date_fin_reelle <= Date_fin_planifiee)
    / OF clôturés total x 100 (comparaison sur la date réelle de fin vs
    planifiée, pour les OF réellement terminés)."""
    of_df = tables["OF"]
    fermes = of_df[of_df["Etat_OF_encours"] == "Fermé"].copy()
    fermes = fermes.dropna(subset=["Date_fin_reelle", "Date_fin_planifiee"])
    if fermes.empty:
        return {"otd_pct": None, "nb_total": 0, "nb_a_temps": 0}
    a_temps = int((fermes["Date_fin_reelle"] <= fermes["Date_fin_planifiee"]).sum())
    return {"otd_pct": round(a_temps / len(fermes) * 100, 1), "nb_total": len(fermes), "nb_a_temps": a_temps}


# ------------------------------------------------------------------
# Statuts OF (avant filtrage sur les encours) + retard par département
# ------------------------------------------------------------------
def calculer_distribution_statuts_of(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    of_df = tables["OF"]
    dist = of_df["Etat_OF_encours"].fillna("Non renseigné").value_counts().reset_index()
    dist.columns = ["Statut", "Nb_OF"]
    return dist


def calculer_of_retard_par_departement(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Nb d'OF EN COURS, en retard vs dans les temps, par département --
    en LIBELLÉ complet ("SUPPLY TUNISIE"), pas le code interne ("SUP_T")
    utilisé par la feuille OF (celui-ci ne veut rien dire pour l'utilisateur ;
    la correspondance vient de la feuille Operations_par_OF, qui a les 2)."""
    of_df = tables["OF"].copy()
    ops = tables["Operations_par_OF"]
    correspondance = ops[["Département", "Département Description"]].drop_duplicates().dropna()
    code_vers_libelle = correspondance.set_index("Département")["Département Description"]

    en_cours = of_df[of_df["Etat_OF_encours"] == "En cours"].copy()
    en_cours["Departement"] = en_cours["Departement"].map(code_vers_libelle).fillna(en_cours["Departement"]).fillna("Non renseigné")
    en_cours["Retard"] = en_cours["En_retard"].astype(str).str.strip().str.upper().map(
        {"OUI": "En retard", "NON": "Dans les temps"}
    ).fillna("Non renseigné")
    g = en_cours.groupby(["Departement", "Retard"]).size().reset_index(name="Nb_OF")
    return g


# ------------------------------------------------------------------
# État du WIP (Lead Time / CT / %VA / retard / OTD) agrégé PAR POSTE
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Répartition de la charge par DÉPARTEMENT et par SOUS-DÉPARTEMENT
# (Chaîne production / Chaîne production Description, feuille Poste_de_charge)
# ------------------------------------------------------------------
def _base_charge_par_poste(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Charge (Temps opération, opérations NON clôturées) par ligne, avec le
    département, la sous-chaîne de production et le statut externe/interne
    -- déjà présents directement sur chaque ligne d'Operations_par_OF
    (transform_v3 les reprend du fichier d'opérations / de la jointure
    poste, inutile de refaire un join)."""
    ops = tables["Operations_par_OF"].copy()
    ops["Temps opération"] = pd.to_numeric(ops["Temps opération"], errors="coerce").fillna(0)
    ops = ops[ops["Statut d'opération"] != STATUT_CLOTURE]

    df = ops.rename(columns={"Département Description": "Departement", "Chaîne production Description": "Sous_departement"})
    df["Departement"] = df["Departement"].fillna("Non renseigné")
    df["Sous_departement"] = df["Sous_departement"].fillna("Non renseigné")
    df["Est_operation_externe"] = df["Est_operation_externe"].fillna(False)
    return df


def calculer_repartition_departement(tables: dict[str, pd.DataFrame], inclure_externe: bool = False) -> pd.DataFrame:
    """Répartition de la charge par DÉPARTEMENT (colonne "Département").
    inclure_externe=False (par défaut) : les postes externes (sous-traitance)
    sont RETIRÉS -- ne montre que la charge propre à l'atelier interne.
    inclure_externe=True : les postes externes sont conservés, avec une
    colonne "Type" (Interne / Externe) pour les distinguer (couleur
    différente côté UI) et leur part (%) du département affichée à part."""
    df = _base_charge_par_poste(tables)
    if not inclure_externe:
        df = df[~df["Est_operation_externe"]]
        g = df.groupby("Departement")["Temps opération"].sum().reset_index(name="Charge_h")
        total = g["Charge_h"].sum()
        g["Pct"] = (g["Charge_h"] / total * 100).round(1) if total else 0.0
        return g.sort_values("Charge_h", ascending=False).reset_index(drop=True)

    df["Type"] = df["Est_operation_externe"].map({True: "Externe (sous-traitance)", False: "Interne"})
    g = df.groupby(["Departement", "Type"])["Temps opération"].sum().reset_index(name="Charge_h")
    total_par_dep = g.groupby("Departement")["Charge_h"].transform("sum")
    g["Pct_du_departement"] = (g["Charge_h"] / total_par_dep * 100).round(1)
    return g.sort_values(["Departement", "Type"]).reset_index(drop=True)


def calculer_repartition_sous_departement(tables: dict[str, pd.DataFrame], inclure_externe: bool = False) -> pd.DataFrame:
    """Idem, mais regroupé par (Département, Sous-département) -- le
    sous-département = "Chaîne production Description" (feuille
    Poste_de_charge). Mêmes règles inclure_externe que ci-dessus."""
    df = _base_charge_par_poste(tables)
    if not inclure_externe:
        df = df[~df["Est_operation_externe"]]
        g = df.groupby(["Departement", "Sous_departement"])["Temps opération"].sum().reset_index(name="Charge_h")
        total = g["Charge_h"].sum()
        g["Pct"] = (g["Charge_h"] / total * 100).round(1) if total else 0.0
        return g.sort_values(["Departement", "Charge_h"], ascending=[True, False]).reset_index(drop=True)

    df["Type"] = df["Est_operation_externe"].map({True: "Externe (sous-traitance)", False: "Interne"})
    g = df.groupby(["Departement", "Sous_departement", "Type"])["Temps opération"].sum().reset_index(name="Charge_h")
    total_par_grp = g.groupby(["Departement", "Sous_departement"])["Charge_h"].transform("sum")
    g["Pct_du_groupe"] = (g["Charge_h"] / total_par_grp * 100).round(1)
    return g.sort_values(["Departement", "Sous_departement", "Type"]).reset_index(drop=True)


# ------------------------------------------------------------------
# Taux d'utilisation par période (jour / semaine / mois), pour un
# périmètre donné (département, chaîne, ou poste seul dans le détail
# hiérarchique de l'onglet POSTES).
# ------------------------------------------------------------------
def calculer_taux_utilisation_periodique_perimetre(tables: dict[str, pd.DataFrame], postes_perimetre: list[str],
                                                     granularite: str = "W") -> pd.DataFrame:
    """Regroupe la charge des opérations ENCOURS (non clôturées) du
    périmètre par période, en utilisant la date de fin PRÉVUE de chaque
    opération ("Dt/hre fin opération", ERP) -- pas la date de fin réelle,
    puisqu'il s'agit d'opérations pas encore terminées : c'est la date à
    laquelle l'ERP prévoit que ce travail doit être fini ("must be done").
    granularite : "D" (jour), "W" (semaine), "M" (mois)."""
    ops = tables["Operations_par_OF"].copy()
    postes = tables["Poste_de_charge"]
    ops = ops[ops["Poste de Charge"].isin(postes_perimetre) & (ops["Statut d'opération"] != STATUT_CLOTURE)].copy()
    if "Dt/hre fin opération" not in ops.columns or ops.empty:
        return pd.DataFrame()

    ops["Temps opération"] = pd.to_numeric(ops["Temps opération"], errors="coerce").fillna(0)
    ops["Dt/hre fin opération"] = pd.to_datetime(ops["Dt/hre fin opération"], errors="coerce")
    ops = ops.dropna(subset=["Dt/hre fin opération"])
    if ops.empty:
        return pd.DataFrame()

    cap = postes.set_index("Poste de charge")
    cap_h_jour = cap["Nbre Max Heures Par Op."].fillna(0) * cap["Nombre de machines"].fillna(1)
    capacite_perimetre_jour = cap_h_jour.reindex(postes_perimetre).fillna(0).sum()

    ops["Periode"] = ops["Dt/hre fin opération"].dt.to_period(granularite)
    g = ops.groupby("Periode")["Temps opération"].sum().reset_index(name="Charge_h")
    g["Date_periode"] = g["Periode"].apply(lambda p: p.start_time)
    g["Nb_jours_periode"] = g["Periode"].apply(
        lambda p: p.days_in_month if granularite == "M" else (7 if granularite == "W" else 1)
    )
    g["Capacite_periode_h"] = capacite_perimetre_jour * g["Nb_jours_periode"]
    g["Taux_utilisation_pct"] = (g["Charge_h"] / g["Capacite_periode_h"].replace(0, pd.NA) * 100).fillna(0).clip(upper=200)
    g["Charge_j"] = g["Charge_h"] / 24
    return g.sort_values("Date_periode").reset_index(drop=True)


def calculer_of_retard_par_poste_perimetre(tables: dict[str, pd.DataFrame], postes_perimetre: list[str]) -> pd.DataFrame:
    """Nb d'OF EN COURS, en retard vs dans les temps, groupés par leur
    poste de travail actuel -- restreint à un périmètre de postes donné."""
    of_df = tables["OF"]
    en_cours = of_df[
        (of_df["Etat_OF_encours"] == "En cours") & (of_df["Poste_travail_actuel"].isin(postes_perimetre))
    ].copy()
    if en_cours.empty:
        return pd.DataFrame()
    en_cours["Retard"] = en_cours["En_retard"].astype(str).str.strip().str.upper().map(
        {"OUI": "En retard", "NON": "Dans les temps"}
    ).fillna("Non renseigné")
    return en_cours.groupby(["Poste_travail_actuel", "Retard"]).size().reset_index(name="Nb_OF")


def calculer_of_retard_departement(tables: dict[str, pd.DataFrame], dept_description: str) -> pd.DataFrame:
    """Nb d'OF EN COURS, en retard vs dans les temps, agrégé pour TOUT un
    département (pour un pie chart, pas de détail par poste).
    `dept_description` = le libellé complet ("SUPPLY TUNISIE", etc., comme
    utilisé partout ailleurs dans l'onglet POSTES) -- la feuille OF utilise
    en interne un CODE court ("SUP_T") différent de ce libellé ; on
    retrouve le code correspondant via la feuille Operations_par_OF, qui a
    les deux colonnes ("Département" = code, "Département Description")."""
    ops = tables["Operations_par_OF"]
    of_df = tables["OF"]
    correspondance = ops[["Département", "Département Description"]].drop_duplicates().dropna()
    code = correspondance.loc[correspondance["Département Description"] == dept_description, "Département"]
    if code.empty:
        return pd.DataFrame()
    code = code.iloc[0]

    en_cours = of_df[(of_df["Etat_OF_encours"] == "En cours") & (of_df["Departement"] == code)].copy()
    if en_cours.empty:
        return pd.DataFrame()
    en_cours["Retard"] = en_cours["En_retard"].astype(str).str.strip().str.upper().map(
        {"OUI": "En retard", "NON": "Dans les temps"}
    ).fillna("Non renseigné")
    return en_cours.groupby("Retard").size().reset_index(name="Nb_OF")

"""
backend/kpi.py
================
KPIs par poste de charge et par OF, calculés à partir des tables produites
par backend/transform.py (feuilles OF / Poste_de_charge / Operations_par_OF).

Aucune simulation ici : uniquement des agrégations directes sur les
données (moyennes, sommes, taux) -- la partie "simulation" (SimPy) est
dans backend/simulation.py.
"""

from __future__ import annotations

import pandas as pd

STATUTS_OPERATION_TERMINEE = ["Clôturé"]


def calculer_kpi_postes(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """1 ligne par poste de charge :
    - Temps_operation_moyen_h : moyenne de "Temps opération" (toutes les
      occurrences de ce poste, opérations restantes ET clôturées confondues
      -> donne une moyenne représentative du temps de traitement réel).
    - Capacite_h_jour : "Nbre Max Heures Par Op." (feuille Poste_de_charge)
      -- c'est la capacité calendaire déjà présente dans la donnée source.
    - Charge_totale_restante_h : somme de "Temps opération" pour les
      opérations NON encore clôturées (le travail qu'il reste à absorber).
    - Taux_utilisation : Charge_totale_restante_h / (Capacite_h_jour *
      Horizon_jours_estime), Horizon_jours_estime = Charge_totale_restante_h
      du poste le plus chargé / sa capacité (auto-calibré, transparent).
    - TRS_estime : ESTIMATION SIMPLIFIÉE (pas un vrai TRS/OEE -- il faudrait
      des données d'arrêts machine et de qualité qu'on n'a pas) : on
      l'assimile ici au taux d'utilisation. Affiché avec ce nom pour
      rester proche du vocabulaire industrie, mais ce n'est PAS un TRS au
      sens strict (Disponibilité x Performance x Qualité).
    """
    ops = tables["Operations_par_OF"].copy()
    postes = tables["Poste_de_charge"].copy()

    ops_restantes = ops[~ops["Statut d'opération"].isin(STATUTS_OPERATION_TERMINEE)]

    temps_moyen = ops.groupby("Poste de Charge")["Temps opération"].mean().rename("Temps_operation_moyen_h")
    charge_restante = ops_restantes.groupby("Poste de Charge")["Temps opération"].sum().rename("Charge_totale_restante_h")
    nb_of_restants = ops_restantes.groupby("Poste de Charge")["N° ordre"].nunique().rename("Nb_OF_distincts_restants")
    nb_operations = ops.groupby("Poste de Charge").size().rename("Nb_operations_total")

    colonnes_dispo = ["Poste de charge", "Description poste de charge", "Est_operation_externe", "Nbre Max Heures Par Op."]
    if "Nombre de machines" in postes.columns:
        colonnes_dispo.append("Nombre de machines")
    df = postes[colonnes_dispo].copy()
    df = df.rename(columns={
        "Poste de charge": "Poste de Charge",
        "Description poste de charge": "Description",
        "Nbre Max Heures Par Op.": "Capacite_h_jour",
    })
    if "Nombre de machines" in df.columns:
        # Capacité dispo = heures d'ouverture x nombre de machines du poste
        # (donnée absente de l'ERP, cf. transform_v3.py / surcharge utilisateur).
        df["Capacite_h_jour"] = df["Capacite_h_jour"].fillna(0) * df["Nombre de machines"].fillna(1)
    df = df.merge(temps_moyen, on="Poste de Charge", how="left")
    df = df.merge(charge_restante, on="Poste de Charge", how="left")
    df = df.merge(nb_of_restants, on="Poste de Charge", how="left")
    df = df.merge(nb_operations, on="Poste de Charge", how="left")
    df[["Temps_operation_moyen_h", "Charge_totale_restante_h", "Nb_OF_distincts_restants", "Nb_operations_total"]] = (
        df[["Temps_operation_moyen_h", "Charge_totale_restante_h", "Nb_OF_distincts_restants", "Nb_operations_total"]].fillna(0)
    )

    # Horizon auto-calibré sur le poste le plus chargé (transparent, pas arbitraire)
    if (df["Capacite_h_jour"] > 0).any():
        ratio_max = (df["Charge_totale_restante_h"] / df["Capacite_h_jour"].replace(0, pd.NA)).max()
        horizon_jours = max(float(ratio_max) if pd.notna(ratio_max) else 1.0, 1.0)
    else:
        horizon_jours = 1.0

    df["Taux_utilisation"] = df["Charge_totale_restante_h"] / (df["Capacite_h_jour"].replace(0, pd.NA) * horizon_jours)
    df["Taux_utilisation"] = df["Taux_utilisation"].clip(upper=1.5).fillna(0)
    df["TRS_estime"] = df["Taux_utilisation"]  # cf. docstring : approximation, pas un vrai OEE

    # KPI supplémentaire (interface_KPIs.py) : taux de rebut par poste
    df_rebut = calculer_rejection_rate_par_poste(tables)[["Poste de Charge", "Taux_rebut_pct"]]
    df = df.merge(df_rebut, on="Poste de Charge", how="left")
    df["Taux_rebut_pct"] = df["Taux_rebut_pct"].fillna(0)

    return df.sort_values("Charge_totale_restante_h", ascending=False).reset_index(drop=True)


def calculer_kpi_departements(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Agrégation au niveau DÉPARTEMENT (ex: 'UAP TOLERIE & MONTAGE TUNISIE',
    'SUPPLY TUNISIE'...), à partir de la colonne réelle 'Département
    Description'. Construit sur les KPIs déjà calculés par poste
    (calculer_kpi_postes) -- pas de recalcul séparé, pour rester cohérent :
    'Nbre Max Heures Par Op.' n'existe que dans Poste_de_charge, pas dans
    Operations_par_OF, donc on passe par la table déjà jointe."""
    ops = tables["Operations_par_OF"]
    df_kpi_postes = calculer_kpi_postes(tables)

    poste_vers_dept = (
        ops[["Poste de Charge", "Département Description"]].dropna(subset=["Poste de Charge"])
        .fillna("Non renseigné").drop_duplicates(subset="Poste de Charge")
    )
    df = df_kpi_postes.merge(poste_vers_dept, on="Poste de Charge", how="left")
    df["Département Description"] = df["Département Description"].fillna("Non renseigné")

    g = df.groupby("Département Description").agg(
        Charge_totale_restante_h=("Charge_totale_restante_h", "sum"),
        Capacite_h_jour_totale=("Capacite_h_jour", "sum"),
        Nb_postes=("Poste de Charge", "nunique"),
        Nb_OF_distincts_restants=("Nb_OF_distincts_restants", "sum"),
        Temps_operation_moyen_h=("Temps_operation_moyen_h", "mean"),
    ).reset_index().rename(columns={"Département Description": "Departement"})

    if (g["Capacite_h_jour_totale"] > 0).any():
        ratio_max = (g["Charge_totale_restante_h"] / g["Capacite_h_jour_totale"].replace(0, pd.NA)).max()
        horizon_jours = max(float(ratio_max) if pd.notna(ratio_max) else 1.0, 1.0)
    else:
        horizon_jours = 1.0
    g["Taux_utilisation"] = g["Charge_totale_restante_h"] / (g["Capacite_h_jour_totale"].replace(0, pd.NA) * horizon_jours)
    g["Taux_utilisation"] = g["Taux_utilisation"].clip(upper=1.5).fillna(0)

    return g.sort_values("Charge_totale_restante_h", ascending=False).reset_index(drop=True)


def detail_departement(tables: dict[str, pd.DataFrame], departement: str, df_kpi_postes: pd.DataFrame) -> pd.DataFrame:
    """Les postes appartenant à CE département (pour le panneau détail)."""
    ops = tables["Operations_par_OF"]
    postes_dept = set(ops.loc[ops["Département Description"] == departement, "Poste de Charge"])
    return df_kpi_postes[df_kpi_postes["Poste de Charge"].isin(postes_dept)].sort_values(
        "Taux_utilisation", ascending=False
    )


def detail_poste(df_kpi_postes: pd.DataFrame, tables: dict[str, pd.DataFrame], poste: str) -> dict:
    """Zoom sur UN poste (pour le clic dans l'interface) : ses KPIs +
    la liste des îlots/outils rencontrés (Info_outil_ordo_moyen) et des OF
    qui l'utilisent actuellement."""
    ligne = df_kpi_postes[df_kpi_postes["Poste de Charge"] == poste]
    if ligne.empty:
        return {}
    ops = tables["Operations_par_OF"]
    ops_poste = ops[ops["Poste de Charge"] == poste]

    ilots = (
        ops_poste["Info_outil_ordo_moyen"].dropna().value_counts().reset_index()
        if "Info_outil_ordo_moyen" in ops_poste.columns else pd.DataFrame()
    )
    if not ilots.empty:
        ilots.columns = ["Ilot_outil_moyen", "Nb_occurrences"]

    return {
        "kpi": ligne.iloc[0].to_dict(),
        "ilots": ilots,
        "operations": ops_poste,
    }


# ----------------------------------------------------------------------
# KPIs VSM complémentaires (inspirés de interface_KPIs.py, mais calculés
# sur les VRAIES données -- pas de saisie manuelle) : taux de rebut réel,
# split VA/non-VA, OTD, Takt Time.
# ----------------------------------------------------------------------
def calculer_va_non_va(tables: dict[str, pd.DataFrame]) -> dict:
    """Découpage Valeur Ajoutée / non-Valeur Ajoutée GLOBAL, façon VSM
    classique (toutes les opérations restantes confondues) :
    - VA  = temps de préparation machine (ajusté) + temps d'exécution
      (Capacite_pour_formule x Facteur exécution machine) -> la
      transformation physique de la pièce.
    - non-VA = Attente_calculee_h (attente/staging) + Temps transport.
    Efficacité de flux = VA / (VA + non-VA) x 100, comme dans
    interface_KPIs.py (Eff = VA / LT x 100), mais sur le temps réellement
    calculé plutôt que saisi à la main. Voir calculer_efficacite_flux()
    pour la version PAR OF (utilisée dans l'onglet OF)."""
    ops = tables["Operations_par_OF"].copy()
    for c in ["Temps préparation machine (ajusté)", "Capacite_pour_formule", "Facteur exécution machine",
              "Temps transport", "Attente_calculee_h"]:
        if c in ops.columns:
            ops[c] = pd.to_numeric(ops[c], errors="coerce").fillna(0)
        else:
            ops[c] = 0.0  # colonne absente (ex: fichier généré par une version antérieure de transform_v3)

    va_h = (ops["Temps préparation machine (ajusté)"] + ops["Capacite_pour_formule"] * ops["Facteur exécution machine"]).sum()
    non_va_h = (ops["Attente_calculee_h"] + ops["Temps transport"]).sum()
    lt_h = va_h + non_va_h
    efficacite_flux = (va_h / lt_h * 100) if lt_h > 0 else 0.0
    return {"VA_h": va_h, "Non_VA_h": non_va_h, "Lead_Time_h": lt_h, "Efficacite_flux_pct": efficacite_flux}


# ------------------------------------------------------------------------
# KPIs SUPPLÉMENTAIRES (inspirés de interface_KPIs.py -- Takt Time, OTD,
# Rejection Rate, Efficacité flux VA/LT). Ajoutés en plus de l'existant,
# pas en remplacement. Formules adaptées à nos vraies données (pas de
# saisie manuelle "Pièces produites/rejetées" par étape comme dans le
# fichier de référence -- on utilise les vraies colonnes ERP).
# ------------------------------------------------------------------------
PREFIXES_NON_VA_PAR_DEFAUT = ("CTL", "CST", "C3S", "PRP", "MRQ")  # contrôle/marquage/préparation = non-VA par défaut


def poste_est_va_par_defaut(poste: str) -> bool:
    """Heuristique de départ (modifiable par l'utilisateur dans l'interface,
    comme la case à cocher VA de interface_KPIs.py) : un poste de
    contrôle/marquage/préparation n'ajoute pas de valeur au sens VSM."""
    return not str(poste).upper().startswith(PREFIXES_NON_VA_PAR_DEFAUT)


def calculer_rejection_rate_par_poste(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Rejection Rate par poste = Σ Qté mise au rebut / Σ Qté opération x100
    (cf. interface_KPIs.py : Rej_i = Rejetées_i / Prod_i x 100)."""
    ops = tables["Operations_par_OF"].copy()
    for c in ["Qté mise au rebut", "Qté opération"]:
        if c in ops.columns:
            ops[c] = pd.to_numeric(ops[c], errors="coerce").fillna(0)
    g = ops.groupby("Poste de Charge").agg(
        Qte_totale=("Qté opération", "sum"),
        Qte_rebut=("Qté mise au rebut", "sum"),
    ).reset_index()
    g["Taux_rebut_pct"] = (g["Qte_rebut"] / g["Qte_totale"].replace(0, pd.NA) * 100).fillna(0)
    g["Taux_rejet_pct"] = g["Taux_rebut_pct"]  # alias (utilisé par ui/vsm_global_tab.py)
    return g.sort_values("Taux_rebut_pct", ascending=False)


def calculer_otd(tables: dict[str, pd.DataFrame]) -> dict:
    """OTD (On-Time Delivery) = OF pas en retard / OF total x100.
    cf. interface_KPIs.py : OTD = Cmd_à_temps / Cmd_total x100.
    Calculé sur tous les OF pour lesquels En_retard est connu.
    NB : "En_retard" contient les chaînes "Oui"/"Non" (pas un booléen)."""
    of_df = tables["OF"]
    if "En_retard" not in of_df.columns:
        return {"otd_pct": None, "nb_total": 0, "nb_a_temps": 0, "nb_ok": 0}
    connus = of_df[of_df["En_retard"].notna()]
    if connus.empty:
        return {"otd_pct": None, "nb_total": 0, "nb_a_temps": 0, "nb_ok": 0}
    a_temps = int((connus["En_retard"].astype(str).str.strip().str.upper() == "NON").sum())
    otd_pct = round(a_temps / len(connus) * 100, 1)
    return {"otd_pct": otd_pct, "nb_total": len(connus), "nb_a_temps": a_temps, "nb_ok": a_temps}


def calculer_efficacite_flux(vsm_par_of: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Efficacité flux par OF = Temps VA / Lead Time théorique x100
    (cf. interface_KPIs.py : Eff = VA / LT x100). VA = somme des durées
    d'opération sur les postes marqués VA (heuristique poste_est_va_par_defaut,
    modifiable dans l'interface)."""
    detail = tables.get("_detail_theorique")
    if detail is None or detail.empty:
        return vsm_par_of
    detail = detail.copy()
    detail["Est_VA"] = detail["Poste de Charge"].apply(poste_est_va_par_defaut)
    va_par_of = detail[detail["Est_VA"]].groupby("N° ordre")["Duree_operation_h"].sum().rename("VA_time_h")
    vsm = vsm_par_of.merge(va_par_of, on="N° ordre", how="left")
    vsm["VA_time_h"] = vsm["VA_time_h"].fillna(0)
    vsm["Efficacite_flux_pct"] = (vsm["VA_time_h"] / vsm["Cycle_theorique_h"].replace(0, pd.NA) * 100).fillna(0)
    return vsm


def calculer_takt_time(demande_hebdo: float, temps_dispo_h_semaine: float) -> float | None:
    """Takt Time = Temps disponible / Demande (cf. interface_KPIs.py).
    À renseigner manuellement (pas de "demande client hebdo" dans l'ERP) :
    retourne None si la demande n'est pas renseignée (>0)."""
    if demande_hebdo <= 0:
        return None
    return temps_dispo_h_semaine / demande_hebdo

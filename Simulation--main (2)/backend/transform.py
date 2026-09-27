"""
backend/transform.py
======================
Reprise fonctionnelle de transform_v3.py (même logique, mêmes formules,
mêmes corrections validées) mais sous forme de fonction appelable depuis
l'interface, acceptant des fichiers uploadés (BytesIO) au lieu de chemins
disque fixes, et retournant les DataFrames + un journal de log au lieu
d'écrire un Excel et d'imprimer sur la console.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

MOTS_CLES_DESCRIPTION_POSTE = ["USI", "PROTECTION"]
MOTS_CLES_CHAINE_PRODUCTION = [r"SOUS[ -]TRAITANCE"]  # tolère espace ET tiret (CST01/CST02/C3S01/STA01)
CAPACITE_EXTERNE_JOUR_DEFAUT = 1500
COLONNE_DATE_JOUR = "Dt/hre début opération"

# --------------------------------------------------------------------
# NOMBRE DE MACHINES PAR POSTE (donnée absente de l'ERP -- reprise de
# transform_v3.py). Valeur par défaut = 1 pour tout poste non listé.
# Une surcharge utilisateur (interface, dict {poste: nb}) prime toujours.
# --------------------------------------------------------------------
NOMBRE_MACHINES_PAR_DEFAUT: dict[str, int] = {
    "A61NX": 1, "NH4-A": 11, "DA3-A": 2, "NM5-A": 9, "MAM-A": 2,
    "CIN-A": 9, "CHR01": 1, "VCF-A": 4,
    "MIN01": 2, "MIN03": 1, "V2P01": 1, "V2P02": 1,
    "MC401": 3, "MC501": 3, "NHD-A": 2, "NM8-A": 2,
    "MEC01": 1, "CRENO": 1,
}


def fusionner_nombre_machines(overrides: dict[str, int] | None = None) -> dict[str, int]:
    """Dictionnaire par défaut + surcharge utilisateur (prime toujours).
    Clés normalisées en MAJUSCULES (postes normalisés ainsi partout)."""
    valeurs = {k.upper(): v for k, v in NOMBRE_MACHINES_PAR_DEFAUT.items()}
    if overrides:
        valeurs.update({str(k).upper(): int(v) for k, v in overrides.items() if v})
    return valeurs

ID_COLS_OPERATIONS = ["N° ordre", "N° opération", "ID opération", "ID bloc opération", "Poste de Charge"]
ID_COLS_POSTES = ["Poste de charge", "Code poste de charge"]
ID_COLS_ENCOURS = ["N° OF", "N° opé actuelle", "Poste de Travail"]


def _parser_dates_rapide(serie: pd.Series) -> pd.Series:
    """Parse une colonne de dates BEAUCOUP plus vite que
    pd.to_datetime(..., dayfirst=True) seul quand le format n'est pas
    homogène : pandas retombe alors sur un parsing élément par élément via
    `dateutil` (des dizaines de fois plus lent) -- visible dans les logs
    par l'avertissement "Could not infer format... falling back to
    dateutil". Avec 10+ colonnes de dates sur le fichier Opérations, c'est
    la cause principale de lenteur du nettoyage.

    Stratégie : on essaie d'abord un format FIXE explicite (le plus
    courant sur un échantillon de la colonne) -- vectorisé, rapide. Si ça
    couvre >= 95% des valeurs non vides, on garde ce résultat (les valeurs
    isolées qui ne matchent pas restent NaT, comme avant). Sinon, on
    retombe sur le parsing lent d'origine (dayfirst=True) pour rester
    correct sur un format vraiment hétérogène."""
    if serie.empty:
        return pd.to_datetime(serie, errors="coerce")

    echantillon = serie.dropna().astype(str)
    echantillon = echantillon[echantillon.str.strip() != ""]
    if echantillon.empty:
        return pd.to_datetime(serie, errors="coerce")

    formats_courants = [
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S", "%d.%m.%Y",
    ]
    echantillon_test = echantillon.sample(min(200, len(echantillon)), random_state=0)
    for fmt in formats_courants:
        essai = pd.to_datetime(echantillon_test, format=fmt, errors="coerce")
        if essai.notna().mean() >= 0.95:
            resultat = pd.to_datetime(serie, format=fmt, errors="coerce")
            # Les valeurs qui ne matchent pas ce format (rares, minoritaires)
            # sont retentées avec le chemin lent, sans pénaliser toute la colonne.
            manquantes = serie.notna() & resultat.isna()
            if manquantes.any():
                resultat.loc[manquantes] = pd.to_datetime(serie[manquantes], errors="coerce", dayfirst=True)
            return resultat

    # Aucun format fixe ne couvre 95% de l'échantillon -> vraiment hétérogène,
    # on garde le comportement d'origine (correct mais plus lent).
    return pd.to_datetime(serie, errors="coerce", dayfirst=True)


# --------------------------------------------------------------------
# Résolution robuste des colonnes attendues (tolère les variations de
# casse/espaces entre 2 exports ERP du même fichier -- évite un KeyError
# cryptique de pandas quand une colonne s'appelle "Poste de Charge" au
# lieu de "Poste de charge" dans un fichier donné, par exemple).
# --------------------------------------------------------------------
def _resoudre_colonnes(df: pd.DataFrame, colonnes_requises: list[str], nom_table: str) -> pd.DataFrame:
    """Renomme les colonnes du DataFrame vers leur nom EXACT attendu par le
    pipeline, en les retrouvant de façon insensible à la casse et aux
    espaces. Lève une erreur claire (colonnes disponibles listées) si une
    colonne requise est vraiment introuvable, plutôt qu'un KeyError."""
    index_normalise = {re.sub(r"\s+", " ", str(c).strip()).lower(): c for c in df.columns}
    renommage = {}
    manquantes = []
    for attendue in colonnes_requises:
        cle = re.sub(r"\s+", " ", attendue.strip()).lower()
        if cle in index_normalise:
            trouvee = index_normalise[cle]
            if trouvee != attendue:
                renommage[trouvee] = attendue
        else:
            manquantes.append(attendue)
    if manquantes:
        raise ValueError(
            f"Colonne(s) attendue(s) introuvable(s) dans [{nom_table}] : {manquantes}.\n"
            f"Colonnes réellement présentes ({len(df.columns)}) : {list(df.columns)}\n"
            f"-> Vérifie que c'est bien le bon fichier, ou que l'export n'a pas une ligne de titre "
            f"en plus avant les en-têtes."
        )
    return df.rename(columns=renommage) if renommage else df


COLONNES_REQUISES_OPERATIONS = [
    "N° ordre", "N° opération", "ID opération", "Poste de Charge", "Article", "Article Description",
    "Statut OF", "Type ordre", "Catégorie priorité", "Date de début ordre fabrication",
    "Date de fin ordre fabrication", "Date début op. réelle", "Date fin op. réelle",
    "Taille lot ordre fabrication", "En retard", "Chaîne production", "Département", "Projet",
    "Temps préparation machine", "Facteur exécution machine", "Temps transport", "Qté opération",
    "Séq. opération", "Statut d'opération", "Dt/hre début opération",
]
COLONNES_REQUISES_POSTES = [
    "Poste de charge", "Description poste de charge", "Nbre Max Heures Par Op.", "Temps d'attente",
]
COLONNES_REQUISES_ENCOURS = [
    "N° OF", "N° opé actuelle", "Poste de Travail", "Info outil/ordo/moyen", "Statut Opé",
    "Temps Attente actuel", "Age de l'OF (jours ouvrés)", "Jours Retards (ouvrés)",
]


# ----------------------------------------------------------------------
# Nettoyage (identique à transform_v3.py)
# ----------------------------------------------------------------------
def _dedupliquer_colonnes_measure_unit(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(df.columns)
    for i, col in enumerate(cols):
        if str(col).strip().lower().startswith("measure unit") and i > 0:
            precedente = re.sub(r"[^\w]+", "_", str(cols[i - 1])).strip("_")
            cols[i] = f"Unite_{precedente}"
    df.columns = cols
    return df


def _nettoyer_dataframe(df: pd.DataFrame, nom_table: str, logs: list[str]) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c).strip().replace("\n", " ")) for c in df.columns]
    df = _dedupliquer_colonnes_measure_unit(df)

    n_col_avant = df.shape[1]
    df = df.dropna(axis=1, how="all")
    logs.append(f"[{nom_table}] {n_col_avant - df.shape[1]} colonne(s) vide(s) supprimée(s)")

    n_lig_avant = len(df)
    df = df.dropna(axis=0, how="all").drop_duplicates()
    logs.append(f"[{nom_table}] {n_lig_avant - len(df)} ligne(s) vide(s)/doublon(s) supprimée(s)")

    for c in df.select_dtypes(include=["object", "string"]).columns:
        df[c] = df[c].astype(str).str.strip()
        df[c] = df[c].replace({"nan": pd.NA, "None": pd.NA, "": pd.NA, "NaT": pd.NA})

    for c in df.columns:
        if re.search(r"date|dt[/ ]?hre", c, flags=re.IGNORECASE):
            df[c] = _parser_dates_rapide(df[c])

    return df


def _normaliser_texte(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper()


def _charger_excel(fichier, colonnes_texte=None) -> pd.DataFrame:
    """fichier : chemin OU objet fichier uploadé (BytesIO) -- pandas gère les deux.
    Moteur `calamine` (python-calamine, basé sur Rust) au lieu d'openpyxl par
    défaut : 3 à 4x plus rapide sur un gros fichier (mesuré : 52s -> 14s sur
    un fichier de 67 000 lignes x 160 colonnes) -- openpyxl est un parseur
    Excel pur Python, notoirement lent sur les gros classeurs. Repli
    automatique sur openpyxl si python-calamine n'est pas installé, pour ne
    jamais bloquer le traitement."""
    converters = {c: str for c in (colonnes_texte or [])}
    try:
        return pd.read_excel(fichier, sheet_name=0, converters=converters, engine="calamine")
    except (ImportError, ValueError):
        if hasattr(fichier, "seek"):
            fichier.seek(0)
        return pd.read_excel(fichier, sheet_name=0, converters=converters, engine="openpyxl")


def _verifier_conflits_encours(agg_of: pd.DataFrame, df_postes: pd.DataFrame, df_operations: pd.DataFrame) -> pd.DataFrame:
    en_cours = agg_of[agg_of["Etat_OF_encours"] == "En cours"].copy()
    if en_cours.empty:
        return pd.DataFrame()
    conflits = (
        en_cours.groupby(["Poste_travail_actuel", "N_operation_actuelle"])["N° ordre (OF)"]
        .apply(list).reset_index(name="OF_en_conflit")
    )
    conflits["Nb_OF_simultanes"] = conflits["OF_en_conflit"].str.len()
    conflits = conflits[conflits["Nb_OF_simultanes"] > 1]
    if conflits.empty:
        return pd.DataFrame()
    postes_externes = set(df_postes.loc[df_postes["Est_operation_externe"], "Poste de charge"])
    conflits["Poste_externe"] = conflits["Poste_travail_actuel"].isin(postes_externes)

    def outils_par_of(row):
        infos = []
        for of_id in row["OF_en_conflit"]:
            ligne = df_operations[
                (df_operations["N° ordre"] == of_id)
                & (df_operations["N° opération"] == row["N_operation_actuelle"])
                & (df_operations["Poste de Charge"] == row["Poste_travail_actuel"])
            ]
            info = ligne["Info outillage / ordo / moyen"].iloc[0] if len(ligne) else pd.NA
            infos.append(f"{of_id}:{info}")
        return " | ".join(infos)

    conflits["Detail_outil_ordo_moyen_par_OF"] = conflits.apply(outils_par_of, axis=1)
    return conflits.sort_values("Nb_OF_simultanes", ascending=False)


def executer_transform(
    fichier_operations,
    fichier_postes,
    fichier_encours,
    capacite_externe_jour: float = CAPACITE_EXTERNE_JOUR_DEFAUT,
    overrides_nb_machines: dict[str, int] | None = None,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Exécute tout le pipeline transform_v3 et retourne :
    - un dict {nom_feuille: DataFrame} avec les 5 tables habituelles
      (OF, Poste_de_charge, Operation, Operations_par_OF, Verification_encours)
    - la liste des messages de log (à afficher dans l'interface)
    """
    logs: list[str] = []

    logs.append("Chargement des fichiers...")
    df_operations = _nettoyer_dataframe(_charger_excel(fichier_operations, ID_COLS_OPERATIONS), "OPERATIONS_OF", logs)
    df_postes = _nettoyer_dataframe(_charger_excel(fichier_postes, ID_COLS_POSTES), "POSTES_CHARGE", logs)
    df_encours = _nettoyer_dataframe(_charger_excel(fichier_encours, ID_COLS_ENCOURS), "ENCOURS", logs)

    # Tolère les variations de casse/espaces d'un export à l'autre du même
    # fichier ERP (ex: "Poste de Charge" vs "Poste de charge") -- sans ça,
    # le pipeline plante avec un KeyError peu clair sur la 1ère colonne
    # attendue qui ne matche pas exactement.
    df_operations = _resoudre_colonnes(df_operations, COLONNES_REQUISES_OPERATIONS, "OPERATIONS_OF")
    df_postes = _resoudre_colonnes(df_postes, COLONNES_REQUISES_POSTES, "POSTES_CHARGE")
    df_encours = _resoudre_colonnes(df_encours, COLONNES_REQUISES_ENCOURS, "ENCOURS")

    df_postes = df_postes.rename(columns={"Temps d'attente": "Temps_attente_poste"})

    df_operations["Poste de Charge"] = _normaliser_texte(df_operations["Poste de Charge"])
    df_operations["N° ordre"] = _normaliser_texte(df_operations["N° ordre"])
    df_operations["N° opération"] = _normaliser_texte(df_operations["N° opération"])
    df_postes["Poste de charge"] = _normaliser_texte(df_postes["Poste de charge"])
    df_postes["Description poste de charge"] = df_postes["Description poste de charge"].astype(str).str.strip()
    if "Chaîne production Description" in df_postes.columns:
        df_postes["Chaîne production Description"] = df_postes["Chaîne production Description"].astype(str).str.strip()

    df_encours["N° ordre"] = _normaliser_texte(df_encours["N° OF"])
    df_encours["N° opération"] = _normaliser_texte(df_encours["N° opé actuelle"])
    df_encours["Poste de Charge"] = _normaliser_texte(df_encours["Poste de Travail"])

    n_avant = len(df_encours)
    df_encours = df_encours.drop_duplicates(subset="N° ordre")
    if n_avant != len(df_encours):
        logs.append(f"[ENCOURS] {n_avant - len(df_encours)} doublon(s) de N° OF supprimé(s)")

    num_cols_operations = [
        "Qté opération", "Qté complétée", "Qté restante", "Qté mise au rebut",
        "Temps préparation machine", "Temps préparation MO", "Temps transport",
        "Temps d'attente", "Facteur exécution machine", "Facteur MO",
        "Taille lot ordre fabrication",
    ]
    for c in num_cols_operations:
        if c in df_operations.columns:
            df_operations[c] = pd.to_numeric(df_operations[c], errors="coerce")

    num_cols_postes = ["Temps_attente_poste", "Nbre Max Heures Par Op.", "Capacité moyenne", "Capacité établie", "Utilisation"]
    for c in num_cols_postes:
        if c in df_postes.columns:
            df_postes[c] = pd.to_numeric(df_postes[c], errors="coerce")

    # -- B. Détection des postes externes (3 signaux combinés) --
    pattern_description = "|".join(MOTS_CLES_DESCRIPTION_POSTE + MOTS_CLES_CHAINE_PRODUCTION)
    pattern_chaine = "|".join(MOTS_CLES_CHAINE_PRODUCTION)
    mask_description = df_postes["Description poste de charge"].astype(str).str.upper().str.contains(pattern_description, regex=True, na=False)
    mask_chaine = df_postes.get("Chaîne production Description", pd.Series("", index=df_postes.index)).astype(str).str.upper().str.contains(pattern_chaine, regex=True, na=False)
    mask_heures_1 = df_postes["Nbre Max Heures Par Op."] == 1
    df_postes["Est_operation_externe"] = mask_description | mask_chaine | mask_heures_1
    logs.append(f"Postes externes détectés : {df_postes['Est_operation_externe'].sum()} / {len(df_postes)} "
                f"(mots-clés : {(mask_description | mask_chaine).sum()}, Nbre Max Heures Par Op.==1 : {mask_heures_1.sum()})")

    # -- C. Attente calculée (identique pour tous les postes) --
    df_postes["Attente_calculee_h"] = (
        df_postes["Temps_attente_poste"] * 24 / df_postes["Nbre Max Heures Par Op."].replace(0, pd.NA)
    )

    # -- D. Fusion opérations <-> postes --
    colonnes_jointure_poste = ["Poste de charge", "Est_operation_externe", "Attente_calculee_h"]
    df_complet = df_operations.merge(
        df_postes[colonnes_jointure_poste].drop_duplicates(subset="Poste de charge"),
        left_on="Poste de Charge", right_on="Poste de charge",
        how="left", suffixes=("", "_poste"), indicator="match_poste",
    )
    df_complet["Est_operation_externe"] = df_complet["Est_operation_externe"].fillna(False)
    logs.append(f"Opérations sans poste de charge trouvé : {(df_complet['match_poste'] == 'left_only').sum()}")

    # -- D2. Fusion avec l'encours (Info outil/ordo/moyen) --
    df_info_outil = df_encours[["N° ordre", "N° opération", "Poste de Charge", "Info outil/ordo/moyen"]].rename(
        columns={"Info outil/ordo/moyen": "Info_outil_ordo_moyen"}
    )
    df_complet = df_complet.merge(df_info_outil, on=["N° ordre", "N° opération", "Poste de Charge"], how="left")

    # -- E. Capacité corrigée (externe vs interne) + charge journalière --
    capacite_externe_heure = capacite_externe_jour / 24
    df_complet["Date_jour"] = df_complet[COLONNE_DATE_JOUR].dt.date
    charge_jour_poste = (
        df_complet[df_complet["Est_operation_externe"]]
        .groupby(["Poste de Charge", "Date_jour"])
        .agg(Nombre_OF_jour_poste=("N° ordre", "nunique"), Qte_totale_jour_poste=("Qté opération", "sum"))
        .reset_index()
    )
    df_complet = df_complet.merge(charge_jour_poste, on=["Poste de Charge", "Date_jour"], how="left")
    df_complet["Charge_jour_poste_estimee"] = df_complet["Nombre_OF_jour_poste"].fillna(0) * df_complet["Qté opération"].fillna(0)
    df_complet["Taux_occupation_capacite_externe"] = df_complet["Qte_totale_jour_poste"] / capacite_externe_jour
    df_complet["Capacite_pour_formule"] = np.where(
        df_complet["Est_operation_externe"], capacite_externe_heure, df_complet["Qté opération"].fillna(0),
    )

    # -- F. Temps préparation machine (ajusté) + Temps opération --
    temps_prepa_brut = df_complet["Temps préparation machine"].fillna(0)
    df_complet["Temps préparation machine (ajusté)"] = np.where(
        df_complet["Est_operation_externe"], temps_prepa_brut * 24, temps_prepa_brut,
    )
    for c in ["Facteur exécution machine", "Temps transport"]:
        df_complet[c] = pd.to_numeric(df_complet[c], errors="coerce").fillna(0)
    df_complet["Temps opération"] = (
        df_complet["Attente_calculee_h"].fillna(0)
        + df_complet["Temps préparation machine (ajusté)"]
        + (df_complet["Capacite_pour_formule"] * df_complet["Facteur exécution machine"])
        + df_complet["Temps transport"]
    )

    # -- G1. Feuille OF --
    agg_of = df_complet.groupby("N° ordre").agg(
        Article=("Article", "first"), Article_Description=("Article Description", "first"),
        Qte_OF=("Taille lot ordre fabrication", "first"), Statut_OF=("Statut OF", "first"),
        Type_ordre=("Type ordre", "first"), Categorie_priorite=("Catégorie priorité", "first"),
        Date_debut_planifiee=("Date de début ordre fabrication", "first"),
        Date_fin_planifiee=("Date de fin ordre fabrication", "first"),
        Date_debut_reelle=("Date début op. réelle", "min"), Date_fin_reelle=("Date fin op. réelle", "max"),
        Nombre_operations=("ID opération", "nunique"), Nombre_operations_externes=("Est_operation_externe", "sum"),
        En_retard=("En retard", "first"), Chaine_production=("Chaîne production", "first"),
        Departement=("Département", "first"), Projet=("Projet", "first"),
        Temps_operation_total_h=("Temps opération", "sum"),
    ).reset_index()

    colonnes_encours_of = {
        "Statut Opé": "Etat_OF_encours", "Poste de Charge": "Poste_travail_actuel",
        "N° opération": "N_operation_actuelle", "Temps Attente actuel": "Temps_sur_poste_actuel_h",
        "Age de l'OF (jours ouvrés)": "Age_OF_jours_ouvres", "Jours Retards (ouvrés)": "Jours_retard_ouvres",
    }
    df_encours_of = df_encours[["N° ordre"] + list(colonnes_encours_of.keys())].rename(columns=colonnes_encours_of)
    n_of_avant = len(agg_of)
    agg_of = agg_of.merge(df_encours_of, on="N° ordre", how="left")
    logs.append(f"OF avec état encours trouvé : {agg_of['Etat_OF_encours'].notna().sum()} / {n_of_avant}")
    agg_of = agg_of.rename(columns={"N° ordre": "N° ordre (OF)"})

    df_conflits_encours = _verifier_conflits_encours(agg_of, df_postes, df_operations)
    if len(df_conflits_encours):
        nb_externe = df_conflits_encours["Poste_externe"].sum()
        logs.append(f"Vérification encours : {len(df_conflits_encours)} conflit(s) poste/opération "
                    f"({nb_externe} sur poste externe = normal, {len(df_conflits_encours) - nb_externe} sur poste interne = à vérifier)")

    # -- G2. Feuille Poste_de_charge (+ Nombre de machines, cf transform_v3.py) --
    nombre_machines = fusionner_nombre_machines(overrides_nb_machines)
    df_postes["Nombre de machines"] = df_postes["Poste de charge"].map(nombre_machines).fillna(1).astype(int)
    df_postes["Nombre_machines_connu"] = df_postes["Poste de charge"].isin(nombre_machines.keys())

    colonnes_calculees = ["Est_operation_externe", "Attente_calculee_h", "Nombre de machines", "Nombre_machines_connu"]
    autres_colonnes_postes = [c for c in df_postes.columns if c not in colonnes_calculees]
    df_poste_sortie = df_postes[colonnes_calculees + autres_colonnes_postes].drop_duplicates(subset="Poste de charge")
    logs.append(f"[Nombre de machines] {sum(1 for p in nombre_machines if p in set(df_postes['Poste de charge']))} "
                f"poste(s) avec valeur connue ; défaut = 1 pour les autres "
                f"({sum(overrides_nb_machines.values()) if overrides_nb_machines else 0} valeur(s) surchargée(s) par l'utilisateur).")

    # -- G3. Feuille Operation (catalogue) --
    df_op_catalogue = df_complet.groupby(["N° opération", "Description opération", "Poste de Charge"]).agg(
        Poste_de_Charge_Description=("Poste de Charge Description", "first"),
        Departement=("Département", "first"), Chaine_production=("Chaîne production", "first"),
        Temps_preparation_machine_moyen=("Temps préparation machine", "mean"),
        Facteur_execution_machine_moyen=("Facteur exécution machine", "mean"),
        Temps_transport_moyen=("Temps transport", "mean"), Est_operation_externe=("Est_operation_externe", "first"),
        Nombre_occurrences=("N° ordre", "nunique"),
        Info_outil_ordo_moyen=("Info_outil_ordo_moyen", lambda s: ", ".join(sorted(set(s.dropna()))) or pd.NA),
    ).reset_index()

    # -- G4. Feuille Operations_par_OF (détail) --
    colonnes_tete = [
        "Est_operation_externe", "Temps préparation machine (ajusté)", "Attente_calculee_h",
        "Capacite_pour_formule", "Temps opération", "Nombre_OF_jour_poste", "Qte_totale_jour_poste",
        "Charge_jour_poste_estimee", "Taux_occupation_capacite_externe", "Info_outil_ordo_moyen",
    ]
    autres_colonnes = [c for c in df_operations.columns if c in df_complet.columns]
    df_detail = df_complet[colonnes_tete + autres_colonnes]

    tables = {
        "OF": agg_of,
        "Poste_de_charge": df_poste_sortie,
        "Operation": df_op_catalogue,
        "Operations_par_OF": df_detail,
        "Verification_encours": df_conflits_encours,
    }
    logs.append("Transformation terminée.")
    return tables, logs

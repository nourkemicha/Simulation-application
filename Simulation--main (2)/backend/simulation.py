"""
backend/simulation.py
=======================
Deux projections calculées pour chaque OF "En cours" :

  1. THÉORIQUE (formule pure, `projeter_theorique`) : Date_fin = maintenant +
     somme des temps d'opération restants de la gamme de CET OF, AUCUNE file
     d'attente, chaque OF est indépendant des autres (cf. simulation_theorique.py).

  2. RÉEL / SimPy (`simuler_reel`) : simulation à événements discrets avec :
     - ordre FIFO RÉEL (ordre atelier réel, puis date de début réelle, puis
       temps déjà écoulé, puis n° d'ordre -- cf. cle_fifo_reelle) au lieu de
       l'ordre arbitraire d'insertion ;
     - capacité par poste = "Nombre de machines" (feuille Poste_de_charge,
       transform_v3 + surcharge utilisateur) ;
     - capacité externe partagée (sous-traitance), remise à plein tous les
       jours (simpy.Container) ;
     - SCÉNARIOS = une liste d'ÉVÉNEMENTS PLANIFIÉS DANS LE TEMPS, chacun
       {"poste", "t_debut_h", "duree_h", "type", "valeur"} :
         - type="capacite" : `valeur` = delta de machines (signé). Négatif =
           panne (retire des machines pendant l'intervalle) ; positif =
           renfort temporaire (ajoute des machines pendant l'intervalle,
           capacité de base retrouvée après). Un seul mécanisme pour les 2
           cas ("panne" et "ajout de machine" ne sont que le signe opposé
           du même événement).
         - type="attente" : `valeur` = heures d'attente ajoutées pour toute
           opération dont le début simulé tombe dans [t_debut_h,
           t_debut_h+duree_h) sur ce poste.
       C'est le même mécanisme, répété/juxtaposé pour chaque poste et chaque
       intervalle défini (onglet Scénario) -- capacité/attente réellement
       VARIABLE au fil du temps simulé, pas seulement à t=0.

`projeter_etat_a_date` permet de rejouer l'état de l'atelier (postes/OF) à
une date choisie dans l'horizon déjà simulé -- utilisé par le curseur
temporel GLOBAL de l'application (toutes les pages, pas seulement Scénario).

L'écart entre les deux (Ecart_goulot_h) isole ce qui est dû à la contention
réelle (files d'attente, pannes), du reste (charge de travail propre à l'OF).
"""

from __future__ import annotations
from datetime import datetime, timedelta

import pandas as pd
import simpy

SEUIL_DUREE_ABERRANTE_H = 500
ETATS_ENCOURS_A_SIMULER = ["En cours"]
STATUTS_OPERATION_TERMINEE = ["Clôturé"]

COL_ORDRE_ATELIER = "Ordre de passage ATELIER"
COL_DATE_DEBUT_OP = "Date début op. réelle"
HORIZON_INFINI_H = 10 ** 7  # "jusqu'à la fin de la simulation", pratique

# Postes à opérateurs multiples (montage, contrôle, FAI, traitement thermique) :
# nombre d'opérateurs inconnu et variable -> capacité non contrainte plutôt
# qu'un chiffre inventé (cf. simulation_encours.py, validé avec l'encadrant).
POSTES_OPERATEURS_MULTIPLES: set[str] = {
    "MCT01", "MCD01", "FAI01", "FAI02", "FAI03", "FAI04", "FAI05", "FAI06",
    "CTL01", "CTL02", "CTL03", "CTL04", "CTL05", "CTL06", "CMT01", "CMT02",
    "TTH01", "TTH02", "TTH03",
}
CAPACITE_ILLIMITEE = 10 ** 6


def evenements_dates_vers_heures(evenements_dates: list[dict], maintenant: datetime) -> list[dict]:
    """Convertit des événements définis en DATES CALENDRIER -- {"poste",
    "date_debut" (date), "date_fin" (date ou None = "pour toujours"), "type",
    "valeur"} -- en événements en HEURES depuis `maintenant` ({"poste",
    "t_debut_h", "duree_h", "type", "valeur"}), consommés par simuler_reel.
    Une date de début antérieure à "maintenant" est ramenée à t=0 (l'horizon
    simulé ne remonte pas avant aujourd'hui)."""
    out = []
    for e in evenements_dates:
        debut_dt = datetime.combine(e["date_debut"], datetime.min.time())
        t_debut_h = max((debut_dt - maintenant).total_seconds() / 3600, 0.0)
        if e.get("date_fin") is None:
            duree_h = HORIZON_INFINI_H
        else:
            fin_dt = datetime.combine(e["date_fin"], datetime.min.time())
            t_fin_h = max((fin_dt - maintenant).total_seconds() / 3600, 0.0)
            duree_h = max(t_fin_h - t_debut_h, 0.1)
        out.append({"poste": e["poste"], "t_debut_h": t_debut_h, "duree_h": duree_h,
                     "type": e["type"], "valeur": e["valeur"]})
    return out


# ----------------------------------------------------------------------
# Ordre FIFO réel (cf. simulation_encours.py)
# ----------------------------------------------------------------------
def cle_fifo_reelle(row, of_id: str, temps_deja_ecoule_h: float) -> tuple:
    atelier = pd.to_numeric(row.get(COL_ORDRE_ATELIER), errors="coerce")
    atelier_key = float(atelier) if pd.notna(atelier) else 1e30
    date_debut = row.get(COL_DATE_DEBUT_OP)
    date_key = float(date_debut.value) if pd.notna(date_debut) else 1e30
    temps_ecoule_key = -float(temps_deja_ecoule_h)
    of_num = pd.to_numeric(of_id, errors="coerce")
    of_num_key = float(of_num) if pd.notna(of_num) else 0.0
    return (atelier_key, date_key, temps_ecoule_key, of_num_key)


# ----------------------------------------------------------------------
# Gammes restantes (communes aux 2 projections)
# ----------------------------------------------------------------------
def _gammes_restantes(tables: dict[str, pd.DataFrame], attente_override_of: dict[str, float] | None = None):
    """Retourne {of_id: [operations...]} avec, pour chaque opération, la
    durée de traitement seule (Temps opération - Attente_calculee_h, pour ne
    pas compter deux fois l'attente ERP + la contention simulée), la clé
    FIFO réelle (1ère opération restante seulement), et les infos externe.
    attente_override_of : {N° ordre: delta_h ajouté à l'attente de sa
    1ère opération restante} (scénario "cet OF attend + longtemps ici", pas
    lié à un poste ni à un intervalle de temps -- voir `evenements` de
    `simuler_reel` pour l'attente PAR POSTE et PAR INTERVALLE)."""
    attente_override_of = attente_override_of or {}

    of_df = tables["OF"]
    ops_df = tables["Operations_par_OF"]

    of_en_cours = of_df[of_df["Etat_OF_encours"].isin(ETATS_ENCOURS_A_SIMULER)]
    ids_en_cours = set(of_en_cours["N° ordre (OF)"])
    temps_ecoule_par_of = of_en_cours.set_index("N° ordre (OF)")["Temps_sur_poste_actuel_h"].to_dict()

    ops_restantes = ops_df[
        ops_df["N° ordre"].isin(ids_en_cours) & ~ops_df["Statut d'opération"].isin(STATUTS_OPERATION_TERMINEE)
    ].sort_values(["N° ordre", "Séq. opération"])

    gammes: dict[str, list[dict]] = {}
    anomalies = []
    for of_id, groupe in ops_restantes.groupby("N° ordre"):
        temps_ecoule_jours = temps_ecoule_par_of.get(of_id, 0)
        temps_ecoule_jours = 0.0 if pd.isna(temps_ecoule_jours) else float(temps_ecoule_jours)
        temps_ecoule_h = temps_ecoule_jours * 24  # colonne source en jours malgré son nom "_h"

        operations = []
        for i, (_, ligne) in enumerate(groupe.iterrows()):
            temps_total = float(ligne["Temps opération"]) if pd.notna(ligne["Temps opération"]) else 0.0
            attente_erp = float(ligne["Attente_calculee_h"]) if pd.notna(ligne.get("Attente_calculee_h")) else 0.0
            poste = str(ligne["Poste de Charge"])
            attente_effective = attente_erp
            if i == 0 and of_id in attente_override_of:
                attente_effective = max(attente_effective + float(attente_override_of[of_id]), 0.0)

            duree_traitement = max(temps_total - attente_erp, 0.0)  # durée pure, sans l'attente ERP
            anomalie = duree_traitement > SEUIL_DUREE_ABERRANTE_H
            duree = min(duree_traitement, SEUIL_DUREE_ABERRANTE_H) if anomalie else duree_traitement
            if anomalie:
                anomalies.append({"N° ordre": of_id, "Poste de Charge": poste,
                                   "Duree_calculee_h": round(duree_traitement, 1), "Duree_retenue_h": round(duree, 1)})

            priorite_fifo = cle_fifo_reelle(ligne, of_id, temps_ecoule_h) if i == 0 else (1e30, 1e30, 0.0, 0.0)

            operations.append({
                "poste": poste, "duree_h": duree, "operation": ligne["Séq. opération"],
                "externe": bool(ligne["Est_operation_externe"]),
                "qte": float(ligne["Qté opération"]) if pd.notna(ligne.get("Qté opération")) else 0.0,
                "attente_erp_h": attente_effective, "anomalie": anomalie, "priorite_fifo": priorite_fifo,
            })
        gammes[of_id] = operations
    df_anomalies = pd.DataFrame(anomalies).sort_values("Duree_calculee_h", ascending=False) if anomalies else pd.DataFrame()
    return gammes, df_anomalies


# ----------------------------------------------------------------------
# 1. Projection théorique (formule pure, sans file d'attente)
# ----------------------------------------------------------------------
def projeter_theorique(tables: dict[str, pd.DataFrame], maintenant: datetime | None = None):
    maintenant = maintenant or datetime.now()
    gammes, _ = _gammes_restantes(tables)

    lignes_of, lignes_detail = [], []
    for of_id, operations in gammes.items():
        cumul = 0.0
        for op in operations:
            duree_totale = op["duree_h"] + op["attente_erp_h"]
            cumul += duree_totale
            lignes_detail.append({
                "N° ordre": of_id, "N° opération": op["operation"], "Poste de Charge": op["poste"],
                "Duree_operation_h": round(duree_totale, 2), "Temps_cumule_h": round(cumul, 2),
                "Anomalie": op["anomalie"],
            })
        lignes_of.append({
            "N° ordre": of_id, "Nb_operations_restantes": len(operations),
            "Cycle_theorique_h": round(cumul, 2), "Cycle_theorique_jours": round(cumul / 24, 1),
            "Date_fin_theorique": maintenant + timedelta(hours=cumul),
        })
    return pd.DataFrame(lignes_of), pd.DataFrame(lignes_detail)


# ----------------------------------------------------------------------
# 2. Capacité par poste (Nombre de machines + surcharges scénario)
# ----------------------------------------------------------------------
def capacites_postes_de_base(tables: dict[str, pd.DataFrame], overrides: dict[str, int] | None = None) -> dict[str, int]:
    """Capacité (nb de machines/lignes en parallèle) par poste interne.

    RÈGLE UNIQUE, sans distinction "confirmé / par défaut" (demande
    explicite : la colonne "Nombre de machines" de la feuille Poste_de_charge
    vaut TOUJOURS un nombre réel -- 1 par défaut pour un poste non documenté,
    tout comme n'importe quel poste où ce nombre est connu. On prend cette
    valeur telle quelle, poste par poste, sans traitement spécial.

    Seule exception RÉELLE conservée : les postes à OPÉRATEURS MULTIPLES
    (POSTES_OPERATEURS_MULTIPLES -- montage, contrôle, FAI, traitement
    thermique) où le nombre de personnes est structurellement variable, pas
    un nombre de machines -- capacité non contrainte par défaut, modifiable
    par un événement de scénario comme n'importe quel autre poste.

    `overrides` (surcharge barre latérale/scénario) prime toujours."""
    overrides = overrides or {}
    postes = tables["Poste_de_charge"]
    nb_machines = postes.set_index("Poste de charge")["Nombre de machines"].to_dict() if "Nombre de machines" in postes.columns else {}

    capacites = {}
    for poste in postes["Poste de charge"]:
        if poste in POSTES_OPERATEURS_MULTIPLES:
            capacites[poste] = CAPACITE_ILLIMITEE
        else:
            capacites[poste] = max(int(nb_machines.get(poste, 1)), 1)
    capacites.update({str(k).upper(): int(v) for k, v in overrides.items() if v})
    return capacites


def _capacite_dynamique(capacite_base: int, evenements_capacite: list[dict]) -> tuple[int, list[tuple]]:
    """À partir de la capacité de base d'un poste et des événements de type
    "capacite" qui le concernent, renvoie (capacité RÉSERVÉE pour la
    ressource SimPy, segments à bloquer [(t_debut_h, duree_h, nb_slots)...]).

    Mécanisme unique pour panne (delta<0) ET renfort (delta>0) :
    - panne (delta<0) : on bloque |delta| machines pendant [début, début+durée) ;
    - renfort (delta>0) : la ressource est créée avec (base + delta) machines,
      mais les `delta` machines en trop sont bloquées EN DEHORS de
      l'intervalle [début, début+durée) -- avant, et de nouveau après (retour
      à la capacité de base).
    Un poste à opérateurs multiples (capacité illimitée, POSTES_OPERATEURS_MULTIPLES)
    n'est pas affecté par défaut -- seul cas où l'événement reste sans effet."""
    if capacite_base >= CAPACITE_ILLIMITEE or not evenements_capacite:
        return capacite_base, []

    capacite_max = capacite_base + sum(max(0, e["valeur"]) for e in evenements_capacite)
    segments = []
    for e in evenements_capacite:
        t_debut, duree, delta = max(float(e["t_debut_h"]), 0.0), float(e["duree_h"]), float(e["valeur"])
        if delta < 0:
            segments.append((t_debut, duree, min(abs(delta), capacite_max)))
        elif delta > 0:
            if t_debut > 0:
                segments.append((0.0, t_debut, delta))
            segments.append((t_debut + duree, HORIZON_INFINI_H, delta))
    return int(capacite_max), segments


# ----------------------------------------------------------------------
# 3. Simulation réelle (SimPy, FIFO réel, pannes, capacité externe)
# ----------------------------------------------------------------------
def simuler_reel(
    tables: dict[str, pd.DataFrame],
    capacite_externe_jour: float = 1500,
    evenements: list[dict] | None = None,
    attente_override_of: dict[str, float] | None = None,
    maintenant: datetime | None = None,
):
    """evenements : liste de {"poste", "t_debut_h", "duree_h", "type", "valeur"}
    -- voir le docstring du module. type="capacite" (valeur = delta machines,
    signé) et/ou type="attente" (valeur = heures ajoutées) peuvent coexister
    sur un même poste, à des intervalles différents ou superposés. C'est le
    SEUL mécanisme de changement de capacité (pas de 2e surcharge séparée --
    la capacité de base vient de "Nombre de machines", modifiable soit à la
    source (barre latérale, avant transform_v3) soit ici via un événement,
    jamais les deux en même temps sur le même paramètre)."""
    maintenant = maintenant or datetime.now()
    evenements = evenements or []
    gammes, df_anomalies = _gammes_restantes(tables, attente_override_of)
    capacites_base = capacites_postes_de_base(tables)

    evenements_par_poste: dict[str, list[dict]] = {}
    for e in evenements:
        evenements_par_poste.setdefault(e["poste"], []).append(e)

    env = simpy.Environment()
    postes_utilises = {op["poste"] for ops in gammes.values() for op in ops if not op["externe"]}

    ressources: dict[str, simpy.PriorityResource] = {}
    segments_a_bloquer: list[tuple] = []  # (poste, t_debut, duree, n)
    evenements_attente: dict[str, list[dict]] = {}
    for p in postes_utilises:
        evs = evenements_par_poste.get(p, [])
        cap_max, segments = _capacite_dynamique(capacites_base.get(p, 1), [e for e in evs if e["type"] == "capacite"])
        ressources[p] = simpy.PriorityResource(env, capacity=max(cap_max, 1))
        for (t_debut, duree, n) in segments:
            segments_a_bloquer.append((p, t_debut, duree, n))
        evenements_attente[p] = [e for e in evs if e["type"] == "attente"]
    stats_postes = {p: {"attente_totale": 0.0, "attente_max": 0.0, "nb": 0, "occupation": 0.0} for p in postes_utilises}

    container_externe = simpy.Container(env, capacity=capacite_externe_jour, init=capacite_externe_jour)
    stats_externe = {"attente_totale": 0.0, "attente_max": 0.0, "nb": 0, "qte": 0.0}

    def reset_quotidien():
        while True:
            yield env.timeout(24)
            if container_externe.level < capacite_externe_jour:
                yield container_externe.put(capacite_externe_jour - container_externe.level)
    env.process(reset_quotidien())

    # -- Blocage planifié (panne et/ou renfort, cf. _capacite_dynamique) --
    def process_blocage(poste: str, t_debut: float, duree: float, n: float):
        if n <= 0 or poste not in ressources:
            return
        if t_debut > 0:
            yield env.timeout(t_debut)
        reqs = [ressources[poste].request(priority=-1e18) for _ in range(int(n))]
        for r in reqs:
            yield r
        yield env.timeout(duree)
        for r in reqs:
            ressources[poste].release(r)

    for (p, t_debut, duree, n) in segments_a_bloquer:
        env.process(process_blocage(p, t_debut, duree, n))

    def attente_supplementaire(poste: str, t_now: float) -> float:
        for e in evenements_attente.get(poste, []):
            if e["t_debut_h"] <= t_now < e["t_debut_h"] + e["duree_h"]:
                return float(e["valeur"])
        return 0.0

    resultats: dict[str, dict] = {}
    journal: list[dict] = []

    def process_of(of_id, operations):
        debut = env.now
        for op in operations:
            t_op_debut = env.now
            if op["externe"] and op["qte"] > 0:
                qte = min(op["qte"], capacite_externe_jour)
                t0 = env.now
                yield container_externe.get(qte)
                attente = env.now - t0
                stats_externe["attente_totale"] += attente
                stats_externe["attente_max"] = max(stats_externe["attente_max"], attente)
                stats_externe["nb"] += 1
                stats_externe["qte"] += qte
                extra = attente_supplementaire(op["poste"], env.now)
                if extra > 0:
                    yield env.timeout(extra)
                yield env.timeout(op["duree_h"])
            elif op["poste"] in ressources:
                res = ressources[op["poste"]]
                t0 = env.now
                with res.request(priority=op["priorite_fifo"]) as req:
                    yield req
                    attente = env.now - t0
                    s = stats_postes[op["poste"]]
                    s["attente_totale"] += attente
                    s["attente_max"] = max(s["attente_max"], attente)
                    s["nb"] += 1
                    extra = attente_supplementaire(op["poste"], env.now)
                    if extra > 0:
                        yield env.timeout(extra)
                    yield env.timeout(op["duree_h"])
                    s["occupation"] += op["duree_h"]
            else:
                yield env.timeout(op["duree_h"])
            journal.append({
                "N° ordre": of_id, "N° opération": op["operation"], "Poste de Charge": op["poste"],
                "Externe": op["externe"], "Debut_sim_h": t_op_debut, "Fin_sim_h": env.now,
                "Duree_h": env.now - t_op_debut,
            })
        resultats[of_id] = {"N° ordre": of_id, "Debut_sim_h": debut, "Fin_sim_h": env.now, "Duree_simulee_h": env.now - debut}

    total = len(gammes)
    fin = {"n": 0, "total": total, "event": env.event()}

    def wrapper(of_id, operations):
        yield from process_of(of_id, operations)
        fin["n"] += 1
        if fin["n"] >= fin["total"] and not fin["event"].triggered:
            fin["event"].succeed()

    for of_id, operations in gammes.items():
        env.process(wrapper(of_id, operations))
    horizon_h = 0.0
    if total > 0:
        env.run(until=fin["event"])
        horizon_h = env.now

    df_resultats = pd.DataFrame(list(resultats.values()))
    if not df_resultats.empty:
        df_resultats["Duree_simulee_jours"] = round(df_resultats["Duree_simulee_h"] / 24, 1)
        df_resultats["Date_debut"] = df_resultats["Debut_sim_h"].apply(lambda h: maintenant + timedelta(hours=h))
        df_resultats["Date_fin"] = df_resultats["Fin_sim_h"].apply(lambda h: maintenant + timedelta(hours=h))

    df_journal = pd.DataFrame(journal)
    if not df_journal.empty:
        df_journal["Date_debut"] = df_journal["Debut_sim_h"].apply(lambda h: maintenant + timedelta(hours=h))
        df_journal["Date_fin"] = df_journal["Fin_sim_h"].apply(lambda h: maintenant + timedelta(hours=h))
        df_journal = df_journal.sort_values(["N° ordre", "N° opération"])

    df_goulots = pd.DataFrame([
        {"Poste de Charge": p, "Capacite": ressources[p].capacity, "Nb_operations": s["nb"],
         "Attente_moyenne_h": round(s["attente_totale"] / s["nb"], 2) if s["nb"] else 0.0,
         "Attente_max_h": round(s["attente_max"], 2),
         "Taux_utilisation": round(s["occupation"] / (horizon_h * ressources[p].capacity), 3) if horizon_h > 0 and ressources[p].capacity > 0 else 0.0}
        for p, s in stats_postes.items()
    ])
    if not df_goulots.empty:
        df_goulots = df_goulots.sort_values("Taux_utilisation", ascending=False).reset_index(drop=True)

    df_goulot_externe = pd.DataFrame([{
        "Capacite_jour": capacite_externe_jour, "Nb_operations_externes": stats_externe["nb"],
        "Attente_moyenne_h": round(stats_externe["attente_totale"] / stats_externe["nb"], 2) if stats_externe["nb"] else 0.0,
        "Attente_max_h": round(stats_externe["attente_max"], 2), "Qte_totale_consommee": round(stats_externe["qte"], 1),
    }])

    infos = {"horizon_h": horizon_h, "horizon_jours": round(horizon_h / 24, 1),
             "date_fin_horizon": maintenant + timedelta(hours=horizon_h), "maintenant": maintenant,
             "nb_of_simules": total}
    return df_resultats, df_journal, df_goulots, df_goulot_externe, df_anomalies, infos


# ----------------------------------------------------------------------
# VSM par OF -- combine théorique + réel
# ----------------------------------------------------------------------
def construire_vsm_par_of(tables: dict[str, pd.DataFrame], maintenant: datetime | None = None,
                           capacite_externe_jour: float = 1500,
                           evenements: list[dict] | None = None, attente_override_of: dict | None = None):
    maintenant = maintenant or datetime.now()
    of_df = tables["OF"]

    df_theo, df_detail = projeter_theorique(tables, maintenant)
    df_sim, df_journal, df_goulots, df_goulot_externe, df_anomalies, infos = simuler_reel(
        tables, capacite_externe_jour, evenements, attente_override_of, maintenant,
    )

    vsm = of_df[of_df["Etat_OF_encours"].isin(ETATS_ENCOURS_A_SIMULER)][[
        "N° ordre (OF)", "Article", "Article_Description", "Qte_OF", "Statut_OF", "Etat_OF_encours",
        "Poste_travail_actuel", "N_operation_actuelle", "Temps_sur_poste_actuel_h",
        "Age_OF_jours_ouvres", "Jours_retard_ouvres", "En_retard", "Chaine_production", "Departement",
        "Date_debut_planifiee", "Date_fin_planifiee", "Nombre_operations", "Temps_operation_total_h",
    ]].rename(columns={"N° ordre (OF)": "N° ordre"})

    vsm = vsm.merge(df_theo, on="N° ordre", how="left")
    if not df_sim.empty:
        vsm = vsm.merge(df_sim[["N° ordre", "Duree_simulee_h", "Duree_simulee_jours", "Date_debut", "Date_fin"]],
                         on="N° ordre", how="left")
    else:
        vsm["Duree_simulee_h"] = 0.0
        vsm["Duree_simulee_jours"] = 0.0
    vsm["Ecart_goulot_h"] = vsm["Duree_simulee_h"] - vsm["Cycle_theorique_h"]
    vsm["WIP"] = 1

    return vsm.sort_values("Duree_simulee_h", ascending=False).reset_index(drop=True), df_detail, {
        "journal": df_journal, "goulots": df_goulots, "goulot_externe": df_goulot_externe,
        "anomalies": df_anomalies, "infos": infos,
    }


def lancer_simulation_complete(tables: dict[str, pd.DataFrame], capacite_externe_jour: float = 1500,
                                evenements: list[dict] | None = None, attente_override_of: dict | None = None,
                                maintenant: datetime | None = None) -> dict:
    """Point d'entrée unique pour lancer les 2 projections (théorique +
    réelle) -- utilisé à la fois pour la simulation de référence
    (auto-lancée après le traitement des fichiers, sans scénario) et pour
    une relance depuis l'onglet Scénario (avec événements). `evenements`
    doit déjà être en heures (voir evenements_dates_vers_heures)."""
    maintenant = maintenant or datetime.now()
    df_theo, df_detail_theo = projeter_theorique(tables, maintenant)
    vsm, df_detail, extra = construire_vsm_par_of(
        tables, maintenant=maintenant, capacite_externe_jour=capacite_externe_jour,
        evenements=evenements, attente_override_of=attente_override_of,
    )
    return {
        "sim_theo": (df_theo, df_detail_theo), "sim_reel": (vsm, df_detail, extra), "maintenant": maintenant,
    }


# ----------------------------------------------------------------------
# Curseur temporel GLOBAL : état projeté de l'atelier à une date choisie
# ----------------------------------------------------------------------
def projeter_etat_a_date(tables: dict[str, pd.DataFrame], extra: dict | None, t_h: float) -> dict[str, pd.DataFrame]:
    """Reconstruit un jeu de tables où "OF" et "Operations_par_OF" reflètent
    l'état PROJETÉ par la simulation réelle à l'instant t_h (heures depuis
    "maintenant", le t=0 de la simulation) -- c'est ce dictionnaire qui doit
    être passé aux pages (Accueil/Postes/OF) pour que le curseur temporel
    transforme TOUTE l'application, pas seulement l'onglet Scénario.

    t_h <= 0, ou aucune simulation disponible -> renvoie `tables` INCHANGÉ
    (état réel actuel). Ne couvre que l'horizon FUTUR déjà simulé (pas de
    rejeu de l'historique passé, qu'on n'a pas au détail opération par
    opération). Les OF qui n'étaient pas "En cours" au moment de la
    simulation (donc absents du journal) restent inchangés à toute date."""
    if t_h <= 0 or not extra or extra.get("journal") is None or extra["journal"].empty:
        return tables

    journal = extra["journal"]
    of_df = tables["OF"].copy()
    ops_df = tables["Operations_par_OF"].copy()

    j = journal.copy()
    j["Statut_simule"] = "Libéré"
    j.loc[j["Fin_sim_h"] <= t_h, "Statut_simule"] = "Clôturé"
    j.loc[(j["Debut_sim_h"] <= t_h) & (j["Fin_sim_h"] > t_h), "Statut_simule"] = "En cours"
    j = j.rename(columns={"N° opération": "Séq. opération"})

    ops_df = ops_df.merge(j[["N° ordre", "Séq. opération", "Statut_simule"]], on=["N° ordre", "Séq. opération"], how="left")
    ops_df["Statut d'opération"] = ops_df["Statut d'opération"].astype(object)
    ops_df["Statut d'opération"] = ops_df["Statut_simule"].fillna(ops_df["Statut d'opération"])
    ops_df = ops_df.drop(columns=["Statut_simule"])

    en_cours_t = j[j["Statut_simule"] == "En cours"][["N° ordre", "Séq. opération", "Poste de Charge"]].rename(
        columns={"N° ordre": "N° ordre (OF)", "Séq. opération": "N_operation_actuelle_sim", "Poste de Charge": "Poste_travail_actuel_sim"}
    )
    fin_par_of = j.groupby("N° ordre")["Fin_sim_h"].max()
    of_termines = set(fin_par_of[fin_par_of <= t_h].index)
    of_simules = set(j["N° ordre"].unique())

    of_df = of_df.merge(en_cours_t, on="N° ordre (OF)", how="left")
    masque_simule = of_df["N° ordre (OF)"].isin(of_simules)
    masque_termine = of_df["N° ordre (OF)"].isin(of_termines)

    # Cast en 'object' avant assignation : "Poste_travail_actuel"/"N_operation_actuelle"
    # peuvent être en dtype "string" (pandas), incompatible en assignation
    # directe avec les valeurs venant du journal (int/float/objet mixte).
    of_df["Poste_travail_actuel"] = of_df["Poste_travail_actuel"].astype(object)
    of_df["N_operation_actuelle"] = of_df["N_operation_actuelle"].astype(object)
    of_df["Etat_OF_encours"] = of_df["Etat_OF_encours"].astype(object)

    of_df.loc[masque_simule & ~masque_termine, "Poste_travail_actuel"] = of_df.loc[masque_simule & ~masque_termine, "Poste_travail_actuel_sim"]
    of_df.loc[masque_simule & ~masque_termine, "N_operation_actuelle"] = of_df.loc[masque_simule & ~masque_termine, "N_operation_actuelle_sim"]
    of_df.loc[masque_simule & ~masque_termine, "Etat_OF_encours"] = "En cours"
    of_df.loc[masque_simule & masque_termine, "Etat_OF_encours"] = "Fermé"
    of_df = of_df.drop(columns=["Poste_travail_actuel_sim", "N_operation_actuelle_sim"])

    tables_vue = dict(tables)
    tables_vue["OF"] = of_df
    tables_vue["Operations_par_OF"] = ops_df
    return tables_vue

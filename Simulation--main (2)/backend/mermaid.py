"""
backend/mermaid.py
=====================
Génère un diagramme de flux Mermaid pour LA gamme réelle d'un OF (repris
du style de interface_VSM.py -- ERP central, flux d'info en pointillés,
flux physique en bas -- mais construit à partir des vraies opérations
restantes de l'OF, pas d'une saisie SQLite manuelle).
"""

from __future__ import annotations

import pandas as pd


def construire_mermaid_of(detail_of: pd.DataFrame, of_id: str, poste_actuel: str | None = None) -> str:
    """detail_of : sous-ensemble de df_detail (backend.simulation.projeter_theorique)
    pour CET OF, trié par Séq. opération, avec les colonnes Poste de Charge
    et Duree_operation_h."""
    if detail_of.empty:
        return "graph LR\n    VIDE[Aucune opération restante]"

    lignes = ["graph TB", "    ERP{{\"ERP Central\"}}", f"    CLIENT[Client]"]

    noeuds = []
    for i, (_, op) in enumerate(detail_of.iterrows()):
        poste = str(op["Poste de Charge"]).replace('"', "")
        duree = op["Duree_operation_h"]
        est_actuel = poste_actuel is not None and poste == str(poste_actuel)
        libelle = f'{poste} <br> {duree:.1f} h'
        noeud_id = f"E{i}"
        noeuds.append((noeud_id, poste, est_actuel))
        lignes.append(f'    {noeud_id}["{libelle}"]')
        lignes.append(f"    ERP -. Ordre .-> {noeud_id}")

    lignes.append("    subgraph Flux physique")
    for i in range(len(noeuds) - 1):
        lignes.append(f"    {noeuds[i][0]} --> {noeuds[i + 1][0]}")
    if noeuds:
        lignes.append(f"    {noeuds[-1][0]} --> CLIENT")
    lignes.append("    end")

    lignes.append("    style ERP fill:#2C6E9B,stroke:#1E3A5F,stroke-width:2px,color:#fff")
    lignes.append("    style CLIENT fill:#fff,stroke:#4A5568,stroke-width:2px")
    for noeud_id, poste, est_actuel in noeuds:
        if est_actuel:
            lignes.append(f"    style {noeud_id} fill:#E8955F,stroke:#C9702E,stroke-width:3px,color:#fff")
        else:
            lignes.append(f"    style {noeud_id} fill:#DCEAF5,stroke:#2C6E9B,stroke-width:1px")

    return "\n".join(lignes)

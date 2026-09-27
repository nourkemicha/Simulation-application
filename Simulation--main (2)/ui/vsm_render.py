"""
ui/vsm_render.py
===================
Diagramme VSM par OF -- CYCLE COMPLET (pas seulement la gamme restante) :
- Opérations déjà CLÔTURÉES (✓ vert, dates réelles de l'ERP/historique).
- L'opération EN COURS (surlignée, info ERP/historique -- poste actuel réel).
- Les opérations À VENIR (grisées/pointillées, dates PROJETÉES par la
  simulation réelle si elle a été lancée -- sinon affichées sans date).
Le curseur temporel global (t_vue_h) déplace la frontière clôturé/en cours/
à venir -- mêmes règles que backend.simulation.projeter_etat_a_date.

Style visuel inspiré d'un tableau de bord de référence (boîtes process
navy/orange, connecteurs flux matière, échelle de temps en dents de scie).
"""

from datetime import timedelta

import pandas as pd
import streamlit as st

from backend.kpi_postes import calculer_charge_capacite_postes, calculer_of_retard_par_poste_perimetre
from backend.simulation import SEUIL_DUREE_ABERRANTE_H
from theme import COULEURS

BOX_W = 172
GAP_W = 56
LADDER_H = 78
Y_TOP = 18
Y_BOT = 58

_NAVY = COULEURS["bleu_fonce"]
_ORANGE = COULEURS["orange_fonce"]
_VERT = "#2E9E5B"
_TEXTE_ATTENUE = "#7A8699"
_BORDURE = "#E2E6EC"
_FOND_CARTE = COULEURS["blanc"]


def construire_cycle_complet_vsm(tables: dict[str, pd.DataFrame], of_id: str, t_vue_h: float = 0.0) -> list[dict]:
    """Cycle COMPLET de l'OF : toutes les opérations (clôturées incluses),
    avec leur statut à l'instant t_vue_h -- "termine" (réel, ERP), "en_cours"
    (réel si pas de simulation ; sinon peut redevenir "termine_simule" si le
    curseur temporel a dépassé sa fin simulée), "a_venir" (projeté par la
    simulation)."""
    ops = tables["Operations_par_OF"]
    gamme = ops[ops["N° ordre"] == of_id].copy()
    if gamme.empty:
        return []
    gamme = gamme.sort_values("Séq. opération")
    for c in ["Temps opération", "Attente_calculee_h", "Qté opération"]:
        gamme[c] = pd.to_numeric(gamme[c], errors="coerce").fillna(0)

    postes_gamme = gamme["Poste de Charge"].dropna().unique().tolist()
    df_charge = calculer_charge_capacite_postes(tables).set_index("Poste de Charge")
    df_retard = calculer_of_retard_par_poste_perimetre(tables, postes_gamme)
    retard_par_poste = (
        df_retard[df_retard["Retard"] == "En retard"].set_index("Poste_travail_actuel")["Nb_OF"]
        if not df_retard.empty else pd.Series(dtype=float)
    )

    # Journal de simulation (si une simulation a été lancée) pour les dates projetées.
    journal = None
    maintenant = None
    if "sim_reel" in st.session_state:
        _, _, extra = st.session_state["sim_reel"]
        journal = extra.get("journal")
        maintenant = extra["infos"]["maintenant"]
    j_of = None
    if journal is not None and not journal.empty:
        j_of = journal[journal["N° ordre"] == of_id].set_index("N° opération")

    trouve_en_cours = False
    etapes = []
    for _, row in gamme.iterrows():
        poste = row["Poste de Charge"]
        seq = row["Séq. opération"]
        externe = bool(row.get("Est_operation_externe", False))
        attente_h = row["Attente_calculee_h"]
        ct_h_brut = max(row["Temps opération"] - attente_h, 0.0)
        anomalie = ct_h_brut > SEUIL_DUREE_ABERRANTE_H
        ct_h = min(ct_h_brut, SEUIL_DUREE_ABERRANTE_H) if anomalie else ct_h_brut
        infos_poste = df_charge.loc[poste] if poste in df_charge.index else None

        etape = {
            "poste": str(poste), "externe": externe, "anomalie": bool(anomalie),
            "ct_min": ct_h * 60, "attente_min": attente_h * 60,
            "wip_pcs": row["Qté opération"],
            "occ": f"{infos_poste['Taux_charge_pct']:.0f}%" if infos_poste is not None else "n/a",
            "cap": f"{infos_poste['Capacite_dispo_h_jour']:.0f} h/j" if infos_poste is not None else "n/a",
            "retard": f"{int(retard_par_poste.get(poste, 0))} OF",
            "wait_jours": round(attente_h / 24, 2), "va_min": round(ct_h * 60),
        }

        if row["Statut d'opération"] == "Clôturé":
            date_fin = row.get("Date fin op. réelle")
            etape.update({"statut": "termine", "date_fin": date_fin if pd.notna(date_fin) else None})
        elif j_of is not None and seq in j_of.index:
            ligne_sim = j_of.loc[seq]
            debut_h, fin_h = float(ligne_sim["Debut_sim_h"]), float(ligne_sim["Fin_sim_h"])
            date_fin = maintenant + timedelta(hours=fin_h) if maintenant else None
            if fin_h <= t_vue_h:
                statut = "termine_simule"
            elif debut_h <= t_vue_h < fin_h:
                statut = "en_cours"
                trouve_en_cours = True
            else:
                statut = "a_venir"
            etape.update({"statut": statut, "date_fin": date_fin})
        else:
            if not trouve_en_cours:
                etape.update({"statut": "en_cours", "date_fin": None})
                trouve_en_cours = True
            else:
                etape.update({"statut": "a_venir", "date_fin": None})
        etapes.append(etape)
    return etapes


def _ligne_metrique(label: str, valeur: str) -> str:
    return (f'<div style="display:flex;justify-content:space-between;font-size:11px;padding:1px 0;">'
            f'<span style="color:{_TEXTE_ATTENUE};">{label} :</span>'
            f'<span style="font-weight:600;color:{_NAVY};">{valeur}</span></div>')


def _boite_processus(e: dict) -> str:
    termine = e["statut"] in ("termine", "termine_simule")
    en_cours = e["statut"] == "en_cours"
    a_venir = e["statut"] == "a_venir"

    if termine:
        couleur_bar = _VERT
    elif e["externe"]:
        couleur_bar = _ORANGE
    else:
        couleur_bar = _NAVY

    bordure = f"3px solid {_NAVY}" if en_cours else f"1px solid {_BORDURE}"
    style_bordure = "border-style:dashed;opacity:0.75;" if a_venir else ""
    icone = "✓ " if termine else ("⏱ " if en_cours else "")
    marqueur_anomalie = " ⚠️" if e.get("anomalie") else ""
    bandeau_statut = ""
    if en_cours:
        bandeau_statut = f'<div style="background:{_NAVY}22;color:{_NAVY};font-size:9px;font-weight:700;text-align:center;padding:3px;">EN COURS</div>'
    elif a_venir:
        bandeau_statut = f'<div style="background:#F1F3F5;color:{_TEXTE_ATTENUE};font-size:9px;font-weight:500;text-align:center;padding:3px;">à venir (simulé)</div>'

    return f'''
    <div style="width:{BOX_W - 12}px;border:{bordure};{style_bordure}border-radius:8px;background:{_FOND_CARTE};
                box-shadow:0 1px 3px rgba(20,30,50,.08);">
      <div style="background:{couleur_bar};color:#fff;font-size:11px;font-weight:700;text-align:center;
                  padding:7px 6px;border-radius:6px 6px 0 0;line-height:1.25;">
        {icone}{e['poste']}{' (Ext.)' if e['externe'] else ''}{marqueur_anomalie}
      </div>
      <div style="padding:8px 10px;display:flex;flex-direction:column;gap:1px;">
        {_ligne_metrique("CT", f"{e['ct_min']:.0f} min")}
        {_ligne_metrique("Attente", f"{e['attente_min']:.0f} min")}
        {_ligne_metrique("WIP", f"{e['wip_pcs']:.0f} pcs")}
        {_ligne_metrique("Occ.", e['occ'])}
        {_ligne_metrique("Cap.", e['cap'])}
        {_ligne_metrique("Retard", e['retard'])}
      </div>
      {bandeau_statut}
    </div>'''


def _connecteur(pcs_aval: float) -> str:
    return f'''
    <div style="width:{GAP_W}px;flex-shrink:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;">
      <div style="font-size:9px;color:{_TEXTE_ATTENUE};">{pcs_aval:.0f} pcs</div>
      <div style="display:flex;align-items:center;">
        <div style="height:1px;width:22px;background:{_NAVY};"></div>
        <div style="width:0;height:0;border-top:4px solid transparent;border-bottom:4px solid transparent;
                    border-left:6px solid {_NAVY};"></div>
      </div>
      <div style="width:9px;height:9px;border-right:1px solid {_TEXTE_ATTENUE};border-top:1px solid {_TEXTE_ATTENUE};
                  transform:rotate(45deg);"></div>
    </div>'''


def _echelle_temps(etapes: list[dict]) -> tuple[str, int]:
    x = 0
    points = [(0, Y_TOP)]
    labels_attente, labels_va = [], []
    for e in etapes:
        gap_start = x
        est_termine = e["statut"] in ("termine", "termine_simule")
        labels_attente.append((gap_start + GAP_W / 2, "✓" if est_termine else f"{e['wait_jours']:.1f} j", est_termine))
        x += GAP_W
        points.append((x, Y_TOP)); points.append((x, Y_BOT))
        box_start = x
        x += BOX_W
        points.append((x, Y_BOT))
        labels_va.append((box_start + BOX_W / 2, f"{e['va_min']:.0f} min"))
        points.append((x, Y_TOP))

    chemin = " ".join(f"{'M' if i == 0 else 'L'} {px} {py}" for i, (px, py) in enumerate(points))
    txt_attente = "".join(
        f'<text x="{lx:.0f}" y="{Y_TOP - 6}" text-anchor="middle" font-size="10" font-weight="600" '
        f'fill="{_VERT if termine else _NAVY}">{lv}</text>' for lx, lv, termine in labels_attente
    )
    txt_va = "".join(
        f'<text x="{lx:.0f}" y="{Y_BOT + 16}" text-anchor="middle" font-size="10" fill="{_TEXTE_ATTENUE}">{lv}</text>'
        for lx, lv in labels_va
    )
    svg = (f'<svg width="{x}" height="{LADDER_H}" style="overflow:visible;">'
           f'<path d="{chemin}" fill="none" stroke="{_NAVY}" stroke-width="1.5"/>{txt_attente}{txt_va}</svg>')
    return svg, x


def _legende() -> str:
    return f'''
    <div style="display:flex;gap:20px;align-items:center;padding:12px 4px 0 4px;font-size:11px;
                color:{_TEXTE_ATTENUE};flex-wrap:wrap;border-top:1px solid {_BORDURE};margin-top:12px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="color:{_VERT};">✓</span><span>Opération clôturée</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:10px;height:10px;border:2px solid {_NAVY};border-radius:2px;display:inline-block;"></span>
        <span>En cours</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:10px;height:10px;border:1px dashed {_TEXTE_ATTENUE};border-radius:2px;display:inline-block;"></span>
        <span>À venir (simulé)</span>
      </div>
      <div style="margin-left:auto;display:flex;gap:16px;">
        <div style="display:flex;align-items:center;gap:6px;">
          <span style="width:11px;height:11px;background:{_NAVY};border-radius:2px;display:inline-block;"></span>Interne
        </div>
        <div style="display:flex;align-items:center;gap:6px;">
          <span style="width:11px;height:11px;background:{_ORANGE};border-radius:2px;display:inline-block;"></span>Externe
        </div>
      </div>
    </div>'''


def rendu_vsm_html(etapes: list[dict], titre: str, sous_titre: str) -> str:
    if not etapes:
        return (f'<div style="border:1px solid {_BORDURE};border-radius:10px;padding:20px;color:{_TEXTE_ATTENUE};">'
                f'Aucune opération pour cet OF.</div>')

    nb_termines = sum(1 for e in etapes if e["statut"] in ("termine", "termine_simule"))

    boites_html = f'<div style="width:{GAP_W}px;flex-shrink:0;"></div>'
    for i, e in enumerate(etapes):
        boites_html += f'<div style="width:{BOX_W}px;flex-shrink:0;display:flex;justify-content:center;">{_boite_processus(e)}</div>'
        if i < len(etapes) - 1:
            boites_html += _connecteur(etapes[i + 1]["wip_pcs"])
        else:
            boites_html += f'<div style="width:{GAP_W}px;flex-shrink:0;"></div>'

    svg_echelle, largeur_totale = _echelle_temps(etapes)

    return f'''
    <div style="border:1px solid {_BORDURE};border-radius:10px;background:{_FOND_CARTE};padding:18px;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px;flex-wrap:wrap;gap:6px;">
        <div style="font-size:14px;font-weight:700;color:{_NAVY};">{titre}</div>
        <div style="font-size:11px;color:{_TEXTE_ATTENUE};">{sous_titre} · <span style="color:{_VERT};font-weight:600;">
          {nb_termines}/{len(etapes)} terminées</span></div>
      </div>
      <div style="overflow-x:auto;padding-bottom:6px;">
        <div style="min-width:{largeur_totale}px;">
          <div style="display:flex;align-items:stretch;">{boites_html}</div>
          <div style="margin-top:2px;">{svg_echelle}</div>
        </div>
      </div>
      {_legende()}
    </div>'''

"""
ui/vsm_famille_render.py
===========================
Rendu du VSM (Value Stream Mapping) PAR FAMILLE DE PRODUITS -- le VSM au
sens Lean classique (Rother & Shook), COMPLET : fournisseur, ERP/pilotage
de production, client, flux d'information (pointillés) et flux physique
(flèches pleines) en plus des boîtes process + data-box et des triangles
de stock -- à ne pas confondre avec ui/vsm_render.py (diagramme du cycle
complet d'UN SEUL OF, dans l'onglet OF, qui reste inchangé).

STRUCTURE (3 rangées empilées, toutes calées sur LA MÊME suite de
largeurs cumulées -- GAP_W pour un stock, BOX_W pour un poste) :
  1. Flux ERP/fournisseur/client (SVG) -- pilotage en haut, fournisseur à
     gauche, client à droite, flèches pointillées (info) vers chaque
     poste + flèches pleines (flux physique) fournisseur->1er poste et
     dernier poste->client.
  2. Boîtes process (data-box) + triangles de stock -- HTML/flex.
  3. Timeline en dents de scie (SVG) -- pic = jours de stock (non-valeur
     ajoutée), creux = C/T (valeur ajoutée).

Les 3 rangées partagent EXACTEMENT les mêmes positions x (calculées une
seule fois par `_positions`) : c'est ce qui garantit que tout reste
aligné verticalement (flèches ERP au-dessus de la bonne boîte, timeline
en dessous de la bonne boîte), sans calage manuel.
"""

import pandas as pd

from theme import COULEURS

BOX_W = 176
GAP_W = 96
LADDER_H = 78
Y_TOP = 18
Y_BOT = 58

_NAVY = COULEURS["bleu_fonce"]
_ORANGE = COULEURS["orange_fonce"]
_BLEU = COULEURS["bleu"]
_TEXTE_ATTENUE = "#7A8699"
_BORDURE = "#E2E6EC"
_FOND_CARTE = COULEURS["blanc"]

# -- Hauteur de la rangée "flux ERP / fournisseur / client" --
_H_FLUX = 170
_Y_BANDEAU_HAUT = 22
_Y_BANDEAU_BAS = 68
_LARGEUR_BANDEAU = 150


def _echap(texte) -> str:
    return str(texte).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _positions(postes: list[dict], stocks: list[dict]) -> tuple[list[float], list[float], int]:
    """Calculé UNE SEULE FOIS, réutilisé par les 3 rangées du schéma :
    - centres[i]      : centre x de la boîte process i
    - debuts_stock[i] : x de début du triangle de stock i (entre process i et i+1)
    - largeur_totale  : largeur totale du diagramme (spacer de tête + n
      boîtes + (n-1) stocks + spacer de fin)."""
    x = GAP_W
    centres, debuts_stock = [], []
    for i in range(len(postes)):
        centres.append(x + BOX_W / 2)
        x += BOX_W
        if i < len(stocks):
            debuts_stock.append(x)
            x += GAP_W
    x += GAP_W
    return centres, debuts_stock, x


def _ligne_metrique(label: str, valeur: str) -> str:
    return (f'<div style="display:flex;justify-content:space-between;font-size:11px;padding:1px 0;">'
            f'<span style="color:{_TEXTE_ATTENUE};">{label} :</span>'
            f'<span style="font-weight:600;color:{_NAVY};">{valeur}</span></div>')


def _boite_poste(p: dict) -> str:
    externe = p.get("Est_operation_externe", False)
    couleur_bandeau = _ORANGE if externe else _NAVY
    suffixe = " (Ext.)" if externe else ""
    return f'''
    <div style="width:{BOX_W - 12}px;border:1px solid {_BORDURE};border-radius:8px;background:{_FOND_CARTE};
                box-shadow:0 1px 3px rgba(20,30,50,.08);">
      <div style="background:{couleur_bandeau};color:#fff;font-size:11px;font-weight:700;text-align:center;
                  padding:7px 6px;border-radius:6px 6px 0 0;line-height:1.25;">
        {p['Poste']}{suffixe}
      </div>
      <div style="padding:8px 10px;display:flex;flex-direction:column;gap:1px;">
        <div style="font-size:9px;color:{_TEXTE_ATTENUE};margin-bottom:3px;
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{p['Description']}</div>
        {_ligne_metrique("C/T", f"{p['CT_h']:.2f} h/pièce")}
        {_ligne_metrique("C/O", f"{p['CO_h']:.2f} h")}
        {_ligne_metrique("Disponibilité", f"{p['Disponibilite_pct']:.0f} %")}
        {_ligne_metrique("Machines", str(p['Nb_machines']))}
        {_ligne_metrique("Lot", f"{p['Taille_lot']:.0f} pcs")}
        {_ligne_metrique("Ouverture", f"{p['Ouverture_h_jour']:.1f} h/j")}
      </div>
    </div>'''


def _fleche_push_css() -> str:
    """Petite flèche de flux physique 'poussé' (CSS, style déjà utilisé
    ailleurs dans l'appli pour les connecteurs) -- affichée au-dessus du
    triangle de stock, entre 2 postes."""
    return (
        f'<div style="display:flex;align-items:center;">'
        f'<div style="height:2px;width:26px;background:{_NAVY};"></div>'
        f'<div style="width:0;height:0;border-top:5px solid transparent;border-bottom:5px solid transparent;'
        f'border-left:7px solid {_NAVY};"></div></div>'
    )


def _connecteur_stock(s: dict) -> str:
    """Triangle de stock (icône VSM classique) + petite flèche de flux
    physique -- largeur GAP_W, identique à celle utilisée pour ce même
    segment dans la timeline (_echelle_temps) et dans le flux du haut
    (_flux_svg) : cette largeur partagée garantit l'alignement des 3 rangées."""
    a_du_stock = s["Nb_OF_en_attente"] > 0
    couleur = _ORANGE if a_du_stock else _TEXTE_ATTENUE
    return f'''
    <div style="width:{GAP_W}px;flex-shrink:0;display:flex;flex-direction:column;align-items:center;
                justify-content:center;gap:3px;">
      {_fleche_push_css()}
      <div style="width:0;height:0;border-left:15px solid transparent;border-right:15px solid transparent;
                  border-bottom:20px solid {couleur};"></div>
      <div style="font-size:11px;font-weight:700;color:{couleur};">{s['Jours_stock']:.1f} j</div>
      <div style="font-size:9px;color:{_TEXTE_ATTENUE};">{s['Nb_OF_en_attente']} OF en attente</div>
    </div>'''


def _echelle_temps(postes: list[dict], stocks: list[dict], centres: list[float], largeur_totale: int) -> str:
    """Timeline en dents de scie : pic (haut) = stock en jours (non-valeur
    ajoutée), creux (bas) = C/T du poste (valeur ajoutée) -- construite à
    partir des MÊMES centres de boîtes que la rangée process au-dessus et
    que le flux ERP en dessous -> alignement garanti par construction."""
    points = [(0, Y_TOP), (GAP_W, Y_TOP)]
    labels_stock, labels_va = [], []
    for i, p in enumerate(postes):
        box_start = centres[i] - BOX_W / 2
        box_end = centres[i] + BOX_W / 2
        points.append((box_start, Y_BOT))
        points.append((box_end, Y_BOT))
        labels_va.append((centres[i], f"{p['CT_h']:.2f} h"))
        points.append((box_end, Y_TOP))
        if i < len(stocks):
            s = stocks[i]
            gap_end = box_end + GAP_W
            labels_stock.append((box_end + GAP_W / 2, f"{s['Jours_stock']:.1f} j"))
            points.append((gap_end, Y_TOP))

    chemin = " ".join(f"{'M' if i == 0 else 'L'} {px} {py}" for i, (px, py) in enumerate(points))
    txt_stock = "".join(
        f'<text x="{lx:.0f}" y="{Y_TOP - 6}" text-anchor="middle" font-size="10" font-weight="600" '
        f'fill="{_ORANGE}">{lv}</text>' for lx, lv in labels_stock
    )
    txt_va = "".join(
        f'<text x="{lx:.0f}" y="{Y_BOT + 16}" text-anchor="middle" font-size="10" fill="{_TEXTE_ATTENUE}">{lv}</text>'
        for lx, lv in labels_va
    )
    return (f'<svg width="{largeur_totale}" height="{LADDER_H}" style="overflow:visible;">'
            f'<path d="{chemin}" fill="none" stroke="{_NAVY}" stroke-width="1.5"/>{txt_stock}{txt_va}</svg>')


def _boite_acteur(cx: float, label: str, sous_label: str = "") -> str:
    x1 = cx - _LARGEUR_BANDEAU / 2
    lignes = (
        f'<rect x="{x1:.0f}" y="{_Y_BANDEAU_HAUT}" width="{_LARGEUR_BANDEAU}" height="{_Y_BANDEAU_BAS - _Y_BANDEAU_HAUT}" '
        f'rx="4" fill="{_FOND_CARTE}" stroke="{_NAVY}" stroke-width="1.6"/>'
        f'<text x="{cx:.0f}" y="{(_Y_BANDEAU_HAUT + _Y_BANDEAU_BAS) / 2 + (0 if sous_label else 4):.0f}" '
        f'text-anchor="middle" font-size="12" font-weight="700" fill="{_NAVY}">{_echap(label)}</text>'
    )
    if sous_label:
        lignes += (
            f'<text x="{cx:.0f}" y="{_Y_BANDEAU_BAS - 6}" text-anchor="middle" font-size="9" '
            f'fill="{_TEXTE_ATTENUE}">{_echap(sous_label)}</text>'
        )
    return lignes


def _fleche_info_svg(x1: float, y1: float, x2: float, y2: float) -> str:
    """Flèche de flux d'INFORMATION (pointillé fin, bleu) -- planification/
    commandes, style VSM classique."""
    return (f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
            f'stroke="{_BLEU}" stroke-width="1.2" stroke-dasharray="4,3" marker-end="url(#fleche_info)"/>')


def _fleche_physique_svg(x1: float, y1: float, x2: float, y2: float) -> str:
    """Flèche de flux PHYSIQUE (trait plein épais, navy) -- matière/produit
    fini, style VSM classique (fournisseur -> 1er poste, dernier poste ->
    client)."""
    return (f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
            f'stroke="{_NAVY}" stroke-width="3" marker-end="url(#fleche_physique)"/>')


def _flux_svg(centres: list[float], largeur_totale: int, kpi: dict) -> str:
    """Rangée du haut, complète : Fournisseur (gauche) -- ERP / Contrôle de
    production (centre) -- Client (droite), avec :
      - flèches pointillées (info) : Client -> ERP (commandes), ERP ->
        Fournisseur (prévisions), ERP -> chaque poste (ordonnancement) ;
      - flèches pleines (physique) : Fournisseur -> 1er poste (livraison
        matière), dernier poste -> Client (expédition produit fini)."""
    erp_cx = largeur_totale / 2
    fournisseur_cx = max(_LARGEUR_BANDEAU / 2 + 6, centres[0] - _LARGEUR_BANDEAU * 0.7)
    client_cx = min(largeur_totale - _LARGEUR_BANDEAU / 2 - 6, centres[-1] + _LARGEUR_BANDEAU * 0.7)

    parties = [
        f'<svg width="{largeur_totale}" height="{_H_FLUX}" style="overflow:visible;">',
        "<defs>",
        f'<marker id="fleche_info" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">'
        f'<path d="M0,0 L7,3 L0,6 Z" fill="{_BLEU}"/></marker>',
        f'<marker id="fleche_physique" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto">'
        f'<path d="M0,0 L8,3 L0,6 Z" fill="{_NAVY}"/></marker>',
        "</defs>",
    ]

    # -- flèches d'info : ERP -> chaque poste (ordonnancement/planification) --
    for cx in centres:
        parties.append(_fleche_info_svg(erp_cx, _Y_BANDEAU_BAS, cx, _H_FLUX - 2))
    parties.append(
        f'<text x="{erp_cx:.0f}" y="{_Y_BANDEAU_BAS + 14}" text-anchor="middle" font-size="9" '
        f'fill="{_BLEU}">ordonnancement</text>'
    )

    # -- flèche d'info : Client -> ERP (commandes) --
    parties.append(_fleche_info_svg(client_cx, _Y_BANDEAU_HAUT + 22, erp_cx + 76, _Y_BANDEAU_HAUT + 22))
    parties.append(
        f'<text x="{(client_cx + erp_cx) / 2:.0f}" y="{_Y_BANDEAU_HAUT + 14}" text-anchor="middle" '
        f'font-size="9" fill="{_BLEU}">commandes</text>'
    )

    # -- flèche d'info : ERP -> Fournisseur (prévisions) --
    parties.append(_fleche_info_svg(erp_cx - 76, _Y_BANDEAU_HAUT + 22, fournisseur_cx, _Y_BANDEAU_HAUT + 22))
    parties.append(
        f'<text x="{(fournisseur_cx + erp_cx) / 2:.0f}" y="{_Y_BANDEAU_HAUT + 14}" text-anchor="middle" '
        f'font-size="9" fill="{_BLEU}">prévisions</text>'
    )

    # -- flèches physiques : Fournisseur -> 1er poste, dernier poste -> Client --
    parties.append(_fleche_physique_svg(fournisseur_cx, _Y_BANDEAU_BAS, centres[0], _H_FLUX - 2))
    parties.append(
        f'<text x="{(fournisseur_cx + centres[0]) / 2:.0f}" y="{_H_FLUX - 8}" text-anchor="middle" '
        f'font-size="10" fill="{_NAVY}">🚚 livraison matière</text>'
    )
    parties.append(_fleche_physique_svg(centres[-1], _H_FLUX - 2, client_cx, _Y_BANDEAU_BAS))
    parties.append(
        f'<text x="{(centres[-1] + client_cx) / 2:.0f}" y="{_H_FLUX - 8}" text-anchor="middle" '
        f'font-size="10" fill="{_NAVY}">🚚 expédition</text>'
    )

    # -- les 3 acteurs (dessinés en dernier pour rester au-dessus des flèches) --
    parties.append(_boite_acteur(fournisseur_cx, "FOURNISSEUR"))
    parties.append(_boite_acteur(erp_cx, "ERP", "Contrôle de production"))
    parties.append(_boite_acteur(client_cx, "CLIENT", f'{kpi["Nb_OF_en_cours_famille"]} OF en cours'))

    parties.append("</svg>")
    return "".join(parties)


def _legende() -> str:
    return f'''
    <div style="display:flex;gap:20px;align-items:center;padding:12px 4px 0 4px;font-size:11px;
                color:{_TEXTE_ATTENUE};flex-wrap:wrap;border-top:1px solid {_BORDURE};margin-top:12px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="height:0;width:22px;border-top:2px dashed {_BLEU};"></div>
        <span>Flux d'information (ERP / planification / commandes)</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="height:3px;width:22px;background:{_NAVY};"></div>
        <span>Flux physique (matière / produit)</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:11px;height:11px;background:{_NAVY};border-radius:2px;display:inline-block;"></span>
        <span>Poste interne</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:11px;height:11px;background:{_ORANGE};border-radius:2px;display:inline-block;"></span>
        <span>Poste externe (sous-traitance)</span>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;
                    border-bottom:9px solid {_ORANGE};display:inline-block;"></span>
        <span>Stock (OF en attente actuellement) — non-valeur ajoutée</span>
      </div>
      <div style="margin-left:auto;">
        Timeline : pic = jours de stock, creux = C/T — alignée verticalement sous chaque bloc correspondant.
      </div>
    </div>'''


def rendu_vsm_famille_html(vsm_data: dict, titre: str, sous_titre: str) -> str:
    postes = vsm_data["postes"]
    stocks = vsm_data["stocks"]
    kpi = vsm_data["kpi"]

    if not postes:
        return (f'<div style="border:1px solid {_BORDURE};border-radius:10px;padding:20px;color:{_TEXTE_ATTENUE};">'
                f'Aucun poste dans la gamme type de cette famille.</div>')

    centres, debuts_stock, largeur_totale = _positions(postes, stocks)

    # -- Rangée 1 : flux ERP / fournisseur / client (SVG) --
    svg_flux = _flux_svg(centres, largeur_totale, kpi)

    # -- Rangée 2 : boîtes process + triangles de stock (HTML/flex) --
    boites_html = f'<div style="width:{GAP_W}px;flex-shrink:0;"></div>'
    for i, p in enumerate(postes):
        boites_html += f'<div style="width:{BOX_W}px;flex-shrink:0;display:flex;justify-content:center;">{_boite_poste(p)}</div>'
        if i < len(stocks):
            boites_html += _connecteur_stock(stocks[i])
        else:
            boites_html += f'<div style="width:{GAP_W}px;flex-shrink:0;"></div>'

    # -- Rangée 3 : timeline, construite avec EXACTEMENT les mêmes positions --
    svg_echelle = _echelle_temps(postes, stocks, centres, largeur_totale)

    resume_kpi = (
        f'Lead Time = <strong style="color:{_NAVY};">{kpi["Lead_time_jours"]:.1f} j</strong> · '
        f'Valeur ajoutée = <strong style="color:{_NAVY};">{kpi["Valeur_ajoutee_h"]:.2f} h</strong> · '
        f'PCE = <strong style="color:{_ORANGE};">{kpi["PCE_pct"]:.2f} %</strong> · '
        f'{kpi["Nb_OF_en_cours_famille"]} OF en cours dans la famille'
    )

    return f'''
    <div style="border:1px solid {_BORDURE};border-radius:10px;background:{_FOND_CARTE};padding:18px;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:14px;flex-wrap:wrap;gap:6px;">
        <div style="font-size:14px;font-weight:700;color:{_NAVY};">{titre}</div>
        <div style="font-size:11px;color:{_TEXTE_ATTENUE};">{sous_titre}</div>
      </div>
      <div style="overflow-x:auto;padding-bottom:6px;">
        <div style="min-width:{largeur_totale}px;">
          <div>{svg_flux}</div>
          <div style="display:flex;align-items:stretch;">{boites_html}</div>
          <div style="margin-top:2px;">
            <div style="font-size:10px;font-weight:600;color:{_TEXTE_ATTENUE};text-transform:uppercase;
                        letter-spacing:.03em;margin-bottom:2px;">
              Timeline (stock = non-valeur ajoutée, C/T = valeur ajoutée) — alignée sous chaque bloc
            </div>
            {svg_echelle}
          </div>
        </div>
      </div>
      <div style="text-align:right;font-size:12px;padding-top:10px;">{resume_kpi}</div>
      {_legende()}
    </div>'''

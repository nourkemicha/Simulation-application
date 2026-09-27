# Interface Atelier — Suivi OF & Postes

## Installation
```bash
pip install -r requirements.txt
```

## Lancement
```bash
streamlit run app.py
```
Ça ouvre l'interface dans le navigateur (http://localhost:8501 par défaut).

## Utilisation
1. Dans la barre latérale, choisis **Upload** (glisser-déposer les 3 fichiers)
   ou **Chemins locaux** (si tu lances l'app sur ton propre poste, tu peux
   coller directement les chemins de tes 3 fichiers — modifie les valeurs
   par défaut dans `app.py` si tu veux qu'elles soient pré-remplies avec
   TES chemins habituels).
2. Clique sur **Lancer le traitement complet** : ça exécute `transform_v3`
   (nettoyage + fusion + formules), calcule les KPIs, puis la projection
   théorique + la simulation SimPy (sous-traitance).
3. Les onglets **POSTE** et **OF** s'affichent avec les graphes et tableaux.

## Structure du projet
```
app.py                  -> point d'entrée Streamlit (upload, orchestration)
theme.py                -> palette de couleurs + style Plotly
backend/
  transform.py          -> reprise de transform_v3.py (fonction, pas de fichiers en dur)
  kpi.py                -> KPIs par poste (temps op. moyen, capacité, taux util., TRS estimé)
  simulation.py          -> projection théorique (formule) + simulation SimPy (sous-traitance)
ui/
  poste_tab.py           -> onglet POSTE (histogramme, détail au clic)
  of_tab.py              -> onglet OF (VSM, WIP, lead time, théorique vs simulé)
```

## Notes importantes
- **Aucun chemin de fichier n'est plus codé en dur dans `backend/transform.py`**
  (contrairement à l'ancien `transform_v3.py`) — tout passe par l'upload ou
  par les champs de saisie de chemin dans la barre latérale.
- Le "TRS estimé" affiché dans l'onglet POSTE est une **approximation** : on
  n'a pas de données d'arrêts machine ni de qualité pour un vrai calcul
  OEE (Disponibilité x Performance x Qualité) — c'est explicitement signalé
  dans l'interface.
- La simulation ne modélise la contention (file d'attente) QUE sur la
  capacité externe partagée (sous-traitance) — pas sur les postes internes,
  suite aux corrections validées précédemment (voir l'historique du
  projet : capacity=1 sur les postes internes créait des files d'attente
  que la donnée ne justifiait pas).
- Seuls les OF avec `Etat_OF_encours == "En cours"` sont simulés/projetés
  (les OF "en attente" sont exclus de la projection, cf. demande précédente).

## À compléter
- La partie **VSM avancée** (calcul des moyennes à partir des OF clôturés,
  répartition futur théorique / futur simulé façon VSM classique) sera
  affinée dès réception du code de référence mentionné mais pas encore
  transmis dans la conversation.

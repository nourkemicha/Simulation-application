"""
theme.py
=========
Palette de couleurs et style Plotly partagés par toute l'interface.
Dominante gris/bleu demandée, avec de l'orange en accent (alertes/goulots).
"""

import plotly.graph_objects as go
import plotly.io as pio

COULEURS = {
    "blanc": "#FFFFFF",
    "gris_clair": "#F4F6F8",
    "gris_moyen": "#B7C0CC",
    "gris_fonce": "#4A5568",
    "bleu": "#2C6E9B",
    "bleu_fonce": "#1E3A5F",
    "bleu_clair": "#DCEAF5",
    "orange": "#E8955F",       # accent : alertes / goulots
    "orange_fonce": "#C9702E",
    "vert": "#6FA98A",         # accent secondaire discret : OK / dans les temps
    "navy_header": "#0B1F3A",  # bandeau supérieur, façon control tower
}

# Dégradé gris -> bleu utilisé pour les histogrammes de postes (le "TS"
# séparateur externe/interne est mis en évidence à part, en orange).
DEGRADE_POSTES = [COULEURS["gris_moyen"], COULEURS["bleu"], COULEURS["bleu_fonce"]]

TEMPLATE_PLOTLY = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=COULEURS["blanc"],
        plot_bgcolor=COULEURS["gris_clair"],
        font=dict(family="Segoe UI, Arial, sans-serif", color=COULEURS["gris_fonce"], size=13),
        colorway=[COULEURS["bleu"], COULEURS["orange"], COULEURS["gris_moyen"], COULEURS["bleu_fonce"]],
        xaxis=dict(gridcolor=COULEURS["gris_moyen"], zerolinecolor=COULEURS["gris_moyen"]),
        yaxis=dict(gridcolor=COULEURS["gris_moyen"], zerolinecolor=COULEURS["gris_moyen"]),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
)
pio.templates["atelier"] = TEMPLATE_PLOTLY
pio.templates.default = "atelier"


def css_global() -> str:
    """CSS injecté une fois dans st.markdown pour habiller les composants
    natifs Streamlit (métriques, onglets, cartes) dans la même palette."""
    return f"""
    <style>
    .stApp {{ background-color: {COULEURS['blanc']}; }}
    [data-testid="stMetric"] {{
        background-color: {COULEURS['gris_clair']};
        border: 1px solid {COULEURS['gris_moyen']};
        border-radius: 8px;
        padding: 12px 16px;
    }}
    [data-testid="stMetricValue"] {{ color: {COULEURS['bleu_fonce']}; }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{
        background-color: {COULEURS['gris_clair']};
        border-radius: 6px 6px 0 0;
        padding: 8px 18px;
    }}
    .stTabs [aria-selected="true"] {{
        background-color: {COULEURS['bleu']} !important;
        color: white !important;
    }}
    .bloc-alerte {{
        background-color: #FBEEE4;
        border-left: 4px solid {COULEURS['orange']};
        padding: 10px 14px;
        border-radius: 4px;
        margin-bottom: 10px;
    }}
    .bloc-info {{
        background-color: {COULEURS['bleu_clair']};
        border-left: 4px solid {COULEURS['bleu']};
        padding: 10px 14px;
        border-radius: 4px;
        margin-bottom: 10px;
    }}
    .kpi-card {{
        background: {COULEURS['blanc']}; border: 1px solid {COULEURS['gris_moyen']};
        border-radius: 8px; padding: 14px 16px; margin-bottom: 8px;
    }}
    .kpi-label {{ font-size: 12px; color: {COULEURS['gris_fonce']}; margin-bottom: 4px; text-transform: uppercase; letter-spacing: .03em; }}
    .kpi-value {{ font-size: 26px; font-weight: 700; color: {COULEURS['bleu_fonce']}; }}
    .kpi-unit  {{ font-size: 11px; color: {COULEURS['gris_moyen']}; }}
    .kpi-formula {{ font-size: 10px; color: {COULEURS['gris_moyen']}; font-style: italic; margin-top: 6px;
                    border-top: 1px solid {COULEURS['gris_clair']}; padding-top: 4px; }}
    .kpi-good {{ color: #2F7A54; }}
    .kpi-warn {{ color: {COULEURS['orange_fonce']}; }}
    .kpi-bad  {{ color: #B0342A; }}

    .header-bar {{
        background: {COULEURS['navy_header']}; color: white; padding: 14px 24px;
        border-radius: 10px; margin-bottom: 14px; display:flex; align-items:center; justify-content:space-between;
    }}
    .header-bar h1 {{ font-size: 20px; margin:0; color:white; }}
    .header-bar p {{ font-size: 12px; margin:0; color:#B9C6D8; }}

    .sidebar-file-card {{
        background:{COULEURS['blanc']}; border:1px solid {COULEURS['gris_moyen']}; border-radius:8px;
        padding:8px 10px; margin-bottom:6px; font-size:12px;
    }}
    .status-box-ok {{
        background:#EAF3EE; border-left:4px solid {COULEURS['vert']}; border-radius:6px;
        padding:8px 10px; font-size:12px; margin-top:8px;
    }}

    /* --- MODE SOMBRE : barre latérale (upload / capacité externe / échelle
       temporelle) -- inversion clair<->sombre, toujours en bleu/orange --- */
    [data-testid="stSidebar"] {{
        background-color: #0F2138;
    }}
    [data-testid="stSidebar"] * {{
        color: #E8EDF3;
    }}
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4, [data-testid="stSidebar"] h5, [data-testid="stSidebar"] strong {{
        color: #FFFFFF;
    }}
    [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea {{
        background-color: #16283F !important;
        color: #FFFFFF !important;
        border: 1px solid {COULEURS['bleu']} !important;
    }}
    [data-testid="stSidebar"] [data-baseweb="select"] > div {{
        background-color: #16283F !important;
        border-color: {COULEURS['bleu']} !important;
    }}
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{
        background-color: #16283F;
        border: 1px dashed {COULEURS['bleu']};
    }}
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {{
        background-color: {COULEURS['bleu']};
        color: #FFFFFF;
        border: none;
    }}
    [data-testid="stSidebar"] .stButton button {{
        background-color: {COULEURS['orange']} !important;
        color: #0F2138 !important;
        border: none !important;
        font-weight: 700;
    }}
    [data-testid="stSidebar"] .stButton button:hover {{
        background-color: {COULEURS['orange_fonce']} !important;
        color: #FFFFFF !important;
    }}
    [data-testid="stSidebar"] .sidebar-file-card {{
        background: #16283F;
        border: 1px solid {COULEURS['bleu']};
        color: #E8EDF3;
    }}
    [data-testid="stSidebar"] .status-box-ok {{
        background: #0F3A2A;
        border-left: 4px solid {COULEURS['vert']};
        color: #E8EDF3;
    }}
    [data-testid="stSidebar"] [role="radiogroup"] label, [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
        color: #B9C6D8 !important;
    }}
    [data-testid="stSidebar"] hr {{
        border-color: {COULEURS['bleu']};
    }}
    </style>
    """

import io
import plotly.graph_objects as go
import streamlit as st
import pandas as pd
from datetime import datetime, date
from models import (
    Movement, Income, MovementOneShot, MovementAnnuel, MovementInterval,
    MovementRemboursement, MovementRemboursementNb, Souhait, Echeancier
)

st.set_page_config(page_title="Échéancier", layout="wide")
st.title("Échéancier financier")


# ── Chargement de fichier CSV ─────────────────────────────────────────────────
def _parse_date(s):
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


# Mapping des types CSV → types UI (le CSV historique utilise "empreunt")
_TYPE_MAP = {
    "1 / mois":  "1 / mois",
    "1 / an":    "1 / an",
    "revenu":    "revenu",
    "unique":    "unique",
    "empreunt":  "emprunt",   # faute historique dans le CSV
    "emprunt":   "emprunt",
    "souhait":   "souhait",
}


def _df_to_csv(df: pd.DataFrame, start_amount: float, start_date, nb_month: int) -> str:
    """Convertit le DataFrame de la vue vers le format CSV d'origine."""
    def fmt_date(d):
        if d is None or (isinstance(d, float) and pd.isna(d)):
            return ""
        try:
            if isinstance(d, str):
                d = pd.to_datetime(d).date()
            return d.strftime("%d/%m/%Y")
        except Exception:
            return ""

    rows = []
    for _, row in df.dropna(how="all").iterrows():
        rows.append({
            "frequency":   row.get("type", ""),
            "description": row.get("description", ""),
            "amount":      row.get("montant", ""),
            "start_date":  fmt_date(row.get("date_debut")),
            "end_date":    fmt_date(row.get("date_fin")),
            "a":           row.get("mensualite", "") if pd.notna(row.get("mensualite")) else "",
            "remb":        "yes" if row.get("interruptible") else "",
            "active":      "" if row.get("active", True) else "false",
        })

    header = (
        f"#solde_initial={start_amount}\n"
        f"#date_debut={fmt_date(start_date)}\n"
        f"#nb_mois={nb_month}\n"
    )
    out = pd.DataFrame(rows)
    return header + out.to_csv(sep=";", index=False)


def _csv_to_df(content: str) -> tuple[pd.DataFrame, list[str], dict]:
    """Parse le contenu CSV et retourne (DataFrame, liste d'erreurs, paramètres)."""
    errors = []
    rows = []
    params = {}
    for line in content.splitlines():
        if line.startswith("#"):
            key, _, val = line[1:].partition("=")
            params[key.strip()] = val.strip()
    reader = pd.read_csv(
        io.StringIO(content),
        sep=";",
        dtype=str,
        keep_default_na=False,
        comment="#",
    )
    # Normalise les noms de colonnes (strip + lowercase)
    reader.columns = [c.strip().lower() for c in reader.columns]

    for i, row in reader.iterrows():
        freq = _TYPE_MAP.get(row.get("frequency", "").strip())
        if not freq:
            errors.append(f"Ligne {i+2} : type « {row.get('frequency', '')} » inconnu, ligne ignorée.")
            continue

        desc = row.get("description", "").strip()
        if not desc:
            errors.append(f"Ligne {i+2} : description vide, ligne ignorée.")
            continue

        try:
            montant = float(row.get("amount", "0").strip() or 0)
        except ValueError:
            errors.append(f"Ligne {i+2} ({desc}) : montant invalide.")
            continue

        date_debut = _parse_date(row.get("start_date", ""))
        date_fin   = _parse_date(row.get("end_date", ""))

        mensualite_raw = row.get("a", "").strip()
        mensualite = float(mensualite_raw) if mensualite_raw else None

        remb_raw = row.get("remb", "").strip().lower()
        interruptible = remb_raw == "yes"

        active_raw = row.get("active", "").strip().lower()
        active = active_raw != "false" and active_raw != "0"  # True par défaut

        rows.append({
            "type":          freq,
            "description":   desc,
            "montant":       montant,
            "date_debut":    date_debut,
            "date_fin":      date_fin,
            "mensualite":    mensualite,
            "nb_mois":       None,
            "interruptible": interruptible,
            "active":        active,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame(), errors, params

with st.expander("📥 Chargement des données", expanded=True):
    uploaded_file = st.file_uploader(
        "Fichier CSV",
        type=["csv"],
        label_visibility="collapsed",
    )

    if uploaded_file is not None and uploaded_file.name != st.session_state.get("loaded_file"):
        content = uploaded_file.read().decode("utf-8")
        df_loaded, load_errors, params = _csv_to_df(content)
        if load_errors:
            for err in load_errors:
                st.warning(err)
        if not df_loaded.empty:
            st.session_state.mouvements_df = df_loaded
            st.session_state.loaded_file = uploaded_file.name
            st.session_state.pop("data_editor", None)
            if "solde_initial" in params:
                try:
                    st.session_state.param_solde_initial = float(params["solde_initial"])
                except ValueError:
                    pass
            if "date_debut" in params:
                d = _parse_date(params["date_debut"])
                if d:
                    st.session_state.param_date_debut = d
            if "nb_mois" in params:
                try:
                    st.session_state.param_nb_mois = int(params["nb_mois"])
                except ValueError:
                    pass
            st.success(f"{len(df_loaded)} mouvement(s) chargé(s) depuis « {uploaded_file.name} ».")
        elif not load_errors:
            st.error("Aucun mouvement valide trouvé dans le fichier.")

# ── Paramètres de l'échéancier ────────────────────────────────────────────────
with st.expander("⚙️ Paramètres de l'échéancier", expanded=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        start_amount = st.number_input("Solde initial (€)", value=st.session_state.get("param_solde_initial", 0.0), step=100.0)
    with col2:
        start_date = st.date_input("Date de début", value=st.session_state.get("param_date_debut", date.today().replace(day=1)))
    with col3:
        nb_month = st.number_input("Nombre de mois", min_value=1, max_value=360, value=st.session_state.get("param_nb_mois", 24), step=1)

# ── Aide ─────────────────────────────────────────────────────────────────────
with st.expander("ℹ️ Guide des types de mouvements"):
    st.markdown("""
| Type | Description | Montant | Date fin | Mensualité | Nb mois | Interruptible |
|---|---|---|---|---|---|---|
| **1 / mois** | Charge mensuelle récurrente | Montant mensuel (négatif) | Optionnel | — | — | — |
| **1 / an** | Charge annuelle | Montant annuel (négatif) | Optionnel | — | — | — |
| **revenu** | Revenu mensuel | Montant (positif) | Optionnel | — | — | — |
| **unique** | Opération ponctuelle | Montant | — | — | — | — |
| **emprunt** | Remboursement d'emprunt | Capital total | Date fin **ou** | Mensualité | **ou** Nb mois | Remboursement anticipé |
| **souhait** | Dépense souhaitée dès que le solde le permet | Montant total | Après (date fin = date plancher) | — | — | — |
""")
    
# ── Table des mouvements ──────────────────────────────────────────────────────
st.subheader("Plan de dépenses et revenus")

FREQ_OPTIONS = ["1 / mois", "1 / an", "revenu", "unique", "emprunt", "souhait"]

default_data = pd.DataFrame([
    {
        "active":        True,
        "type":          "1 / mois",
        "description":   "",
        "montant":       0.0,
        "date_debut":    date.today().replace(day=1),
        "date_fin":      None,
        "mensualite":    None,
        "nb_mois":       None,
        "interruptible": False,
    }
])

if "mouvements_df" not in st.session_state:
    st.session_state.mouvements_df = default_data.copy()

edited_df = st.data_editor(
    st.session_state.mouvements_df,
    num_rows="dynamic",
    width='stretch',
    column_config={
        "type": st.column_config.SelectboxColumn(
            "Type",
            options=FREQ_OPTIONS,
            required=True,
            width="small",
        ),
        "description": st.column_config.TextColumn("Description", width="medium"),
        "montant": st.column_config.NumberColumn("Montant (€)", format="%.2f", width="small"),
        "date_debut": st.column_config.DateColumn("Date début", width="small"),
        "date_fin": st.column_config.DateColumn("Date fin", width="small"),
        "mensualite": st.column_config.NumberColumn(
            "Mensualité (€)",
            help="Pour emprunt : montant de la mensualité (optionnel si date fin fournie)",
            format="%.2f",
            width="small",
        ),
        "nb_mois": st.column_config.NumberColumn(
            "Nb mois",
            help="Pour emprunt : nombre de mensualités (alternative à date fin)",
            width="small",
        ),
        "active": st.column_config.CheckboxColumn(
            "Actif",
            help="Décocher pour exclure ce mouvement du calcul",
            width="small",
        ),
        "interruptible": st.column_config.CheckboxColumn(
            "Interruptible",
            help="Remboursement anticipé si solde suffisant",
            width="small",
        ),
    },
    column_order=["active", "type", "description", "montant", "date_debut", "date_fin", "mensualite", "nb_mois", "interruptible"],
    key="data_editor",
)
st.download_button(
    label="💾 Sauvegarder en CSV",
    data=_df_to_csv(edited_df, start_amount, start_date, nb_month),
    file_name="echeancier.csv",
    mime="text/csv",
)

# ── Calcul ────────────────────────────────────────────────────────────────────
if st.button("▶ Calculer l'échéancier", type="primary"):
    errors = []
    mouvements = []
    souhaits = []

    df = edited_df.dropna(how="all")

    for i, row in df.iterrows():
        desc = str(row.get("description", "") or "").strip()
        typ = row.get("type", "")
        montant = float(row.get("montant") or 0)
        date_debut_raw = row.get("date_debut")
        date_fin_raw = row.get("date_fin")
        mensualite = row.get("mensualite")
        nb_mois_row = row.get("nb_mois")
        interruptible = bool(row.get("interruptible", False))
        active = bool(row.get("active", True))

        if not desc:
            errors.append(f"Ligne {i+1} : description manquante.")
            continue

        try:
            d_debut = datetime(date_debut_raw.year, date_debut_raw.month, date_debut_raw.day) if date_debut_raw else datetime.now()
        except Exception:
            errors.append(f"Ligne {i+1} ({desc}) : date de début invalide.")
            continue

        d_fin = None
        if date_fin_raw:
            try:
                d_fin = datetime(date_fin_raw.year, date_fin_raw.month, date_fin_raw.day)
            except Exception:
                errors.append(f"Ligne {i+1} ({desc}) : date de fin invalide.")
                continue

        if not active:
            continue

        try:
            if typ == "1 / mois":
                m = Movement(desc, montant, d_debut, income=False, end_date=d_fin, active=active)
                mouvements.append(m)

            elif typ == "revenu":
                m = Income(desc, montant, d_debut)
                if d_fin:
                    m.end_date = d_fin
                mouvements.append(m)

            elif typ == "1 / an":
                m = MovementAnnuel(desc, montant, d_debut, end_date=d_fin)
                mouvements.append(m)

            elif typ == "unique":
                m = MovementOneShot(desc, montant, d_debut)
                mouvements.append(m)

            elif typ == "emprunt":
                if nb_mois_row and not pd.isna(nb_mois_row):
                    m = MovementRemboursementNb(desc, abs(montant), d_debut, int(nb_mois_row))
                elif mensualite and not pd.isna(mensualite) and d_fin:
                    m = MovementRemboursement(desc, abs(montant), d_debut, end_date=d_fin, amount=abs(mensualite))
                elif d_fin:
                    m = MovementRemboursement(desc, abs(montant), d_debut, end_date=d_fin)
                else:
                    errors.append(f"Ligne {i+1} ({desc}) : emprunt nécessite date fin, mensualité ou nb mois.")
                    continue
                m.interuptible = interruptible
                mouvements.append(m)

            elif typ == "souhait":
                after = d_fin  # date fin = date plancher pour les souhaits
                s = Souhait(desc, abs(montant), after=after)
                souhaits.append(s)

        except Exception as e:
            errors.append(f"Ligne {i+1} ({desc}) : {e}")

    if errors:
        for err in errors:
            st.error(err)
    else:
        try:
            ech = Echeancier(
                nb_month=int(nb_month),
                start_amount=start_amount,
                start_date=datetime(start_date.year, start_date.month, start_date.day),
            )
            for s in souhaits:
                ech.append_souhait(s)

            ech.compute(mouvements)

            # Mise à plat du bilan
            rows = []
            for dt, entries in sorted(ech.balance.items()):
                for entry in entries:
                    rows.append({
                        "Date": entry.date,                          # datetime, pour le tri
                        "Description": entry.payement.description,
                        "Montant (€)": round(entry.payement.amount, 2),
                        "Solde (€)": round(entry.current_amount, 2),
                        "Spécial": "✔" if entry.payement.special else "",
                    })

            result_df = pd.DataFrame(rows)
            result_df["Date"] = pd.to_datetime(result_df["Date"])
            result_df.sort_values("Date", inplace=True)

            st.success(f"{len(result_df)} opérations calculées.")

            # Graphique : dernier solde connu par mois
            MOIS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                       "juil.", "août", "sept.", "oct.", "nov.", "déc."]
            chart_df = (
                result_df
                .set_index("Date")["Solde (€)"]
                .resample("ME")
                .last()
                .dropna()
            )
            labels = [f"{MOIS_FR[d.month-1]} {d.year}" for d in chart_df.index]
            year_end_mask = chart_df.index.month == 12
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=labels, y=chart_df.values,
                mode="lines", name="Solde",
            ))
            fig.add_trace(go.Scatter(
                x=[l for l, m in zip(labels, year_end_mask) if m],
                y=chart_df[year_end_mask].values,
                mode="markers",
                marker=dict(color="red", size=10, symbol="circle"),
                name="Fin d'année",
            ))
            st.plotly_chart(fig, width="stretch")
          
            # Tableau : date affichée en DD/MM/YYYY
            year_end_rows = (result_df["Date"].dt.month == 1) & (result_df["Date"].dt.day == 1)
            result_df["Date"] = result_df["Date"].dt.strftime("%d/%m/%Y")

            # Tableau détaillé
            def _highlight_year_end(row):
                color = "background-color: #ffcccc" if year_end_rows[row.name] else ""
                return [color] * len(row)

            st.dataframe(
                result_df.style.apply(_highlight_year_end, axis=1)
                    .format({"Montant (€)": "{:.2f} €", "Solde (€)": "{:.2f} €"}),
                width='stretch',
                hide_index=True,
            )

        except Exception as e:
            st.error(f"Erreur lors du calcul : {e}")

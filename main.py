import io
import plotly.graph_objects as go
import streamlit as st
import pandas as pd
from datetime import datetime, date
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode
from models import (
    Movement, Income, MovementOneShot, MovementAnnuel, MovementInterval,
    MovementRemboursement, MovementRemboursementNb, Souhait, Echeancier
)

st.set_page_config(page_title="Échéancier", layout="wide")
st.title("Échéancier financier")


# ── Helpers AgGrid ───────────────────────────────────────────────────────────
_GRID_COLUMNS = ["active", "type", "description", "montant", "date_debut", "date_fin", "mensualite", "nb_mois", "interruptible"]

def _df_for_grid(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    for col in ["date_debut", "date_fin"]:
        df[col] = df[col].apply(
            lambda d: d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else ""
        )
    df["active"] = df["active"].fillna(True).astype(bool)
    df["interruptible"] = df["interruptible"].fillna(False).astype(bool)
    df["montant"] = pd.to_numeric(df["montant"], errors="coerce").fillna(0.0)
    return df[_GRID_COLUMNS]


def _df_from_grid(data) -> pd.DataFrame:
    df = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    if df.empty:
        return df
    for col in ["date_debut", "date_fin"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda d: _parse_date(str(d)) if d else None)
    df["montant"] = pd.to_numeric(df["montant"], errors="coerce").fillna(0.0)
    df["mensualite"] = pd.to_numeric(df["mensualite"], errors="coerce")
    df["nb_mois"] = pd.to_numeric(df["nb_mois"], errors="coerce")
    df["active"] = df["active"].apply(
        lambda x: x if isinstance(x, bool) else str(x).lower() not in ("false", "0", "")
    )
    df["interruptible"] = df["interruptible"].apply(
        lambda x: x if isinstance(x, bool) else str(x).lower() == "true"
    )
    return df.reset_index(drop=True)


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
            "active":      "" if row.get("active", True) else "false",
            "frequency":   row.get("type", ""),
            "description": row.get("description", ""),
            "amount":      row.get("montant", ""),
            "start_date":  fmt_date(row.get("date_debut")),
            "end_date":    fmt_date(row.get("date_fin")),
            "a":           row.get("mensualite", "") if pd.notna(row.get("mensualite")) else "",
            "remb":        "yes" if row.get("interruptible") else "",
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
            existing_df = st.session_state.get("mouvements_df")
            has_existing = existing_df is not None and not existing_df.empty and not (
                len(existing_df) == 1 and existing_df.iloc[0]["description"] == ""
            )
            if has_existing:
                st.session_state.mouvements_df = pd.concat([existing_df, df_loaded], ignore_index=True)
            else:
                st.session_state.mouvements_df = df_loaded
            st.session_state.loaded_file = uploaded_file.name
            st.session_state.pop("ag_grid", None)
            if "solde_initial" in params:
                try:
                    new_solde = float(params["solde_initial"])
                    current_solde = st.session_state.get("param_solde_initial", 0.0)
                    st.session_state.param_solde_initial = current_solde + new_solde
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
            msg = f"{len(df_loaded)} mouvement(s) ajouté(s) depuis « {uploaded_file.name} »." if has_existing else f"{len(df_loaded)} mouvement(s) chargé(s) depuis « {uploaded_file.name} »."
            st.success(msg)
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
if "grid_key" not in st.session_state:
    st.session_state.grid_key = 0
if "scroll_to_last" not in st.session_state:
    st.session_state.scroll_to_last = False

gb = GridOptionsBuilder.from_dataframe(_df_for_grid(st.session_state.mouvements_df))
gb.configure_default_column(editable=True, resizable=True, sortable=False, filter=False)
gb.configure_column("active", headerName="Actif", width=75,
                     cellRenderer="agCheckboxCellRenderer",
                     cellEditor="agCheckboxCellEditor", rowDrag=True)
gb.configure_column("type", headerName="Type", width=120,
                     cellEditor="agSelectCellEditor",
                     cellEditorParams={"values": FREQ_OPTIONS})
gb.configure_column("description", headerName="Description", flex=2, minWidth=150)
gb.configure_column("montant", headerName="Montant (€)", width=120, type=["numericColumn"])
gb.configure_column("date_debut", headerName="Date début", width=110)
gb.configure_column("date_fin", headerName="Date fin", width=110)
gb.configure_column("mensualite", headerName="Mensualité (€)", width=130, type=["numericColumn"])
gb.configure_column("nb_mois", headerName="Nb mois", width=90, type=["numericColumn"])
gb.configure_column("interruptible", headerName="Interruptible", width=115,
                     cellRenderer="agCheckboxCellRenderer",
                     cellEditor="agCheckboxCellEditor")
gb.configure_selection("single", use_checkbox=False)
grid_opts = gb.build()
grid_opts["rowDragManaged"] = True
grid_opts["animateRows"] = True
if st.session_state.scroll_to_last:
    last_idx = len(st.session_state.mouvements_df) - 1
    grid_opts["onFirstDataRendered"] = JsCode(f"""
        function(params) {{
            params.api.ensureIndexVisible({last_idx}, 'bottom');
            params.api.setFocusedCell({last_idx}, 'description');
            params.api.startEditingCell({{rowIndex: {last_idx}, colKey: 'description'}});
        }}
    """)
    st.session_state.scroll_to_last = False

response = AgGrid(
    _df_for_grid(st.session_state.mouvements_df),
    gridOptions=grid_opts,
    update_mode=GridUpdateMode.MODEL_CHANGED,
    data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
    fit_columns_on_grid_load=True,
    allow_unsafe_jscode=True,
    height=300,
    key=f"ag_grid_{st.session_state.grid_key}",
)
edited_df = _df_from_grid(response["data"])
if edited_df.empty:
    edited_df = st.session_state.mouvements_df.copy()

col_add, col_del, _ = st.columns([1, 1, 6])
with col_add:
    if st.button("➕ Ajouter une ligne"):
        new_row = pd.DataFrame([{
            "active": True, "type": "unique", "description": "une description",
            "montant": 0.0, "date_debut": date.today().replace(day=1),
            "date_fin": None, "mensualite": None, "nb_mois": None, "interruptible": False,
        }])
        base = edited_df if not edited_df.empty else st.session_state.mouvements_df
        st.session_state.mouvements_df = pd.concat([base, new_row], ignore_index=False)
        st.session_state.scroll_to_last = True
        st.session_state.grid_key += 1
        st.rerun()
with col_del:
    _sel = response.get("selected_rows")
    selected = _sel.to_dict("records") if isinstance(_sel, pd.DataFrame) else (_sel or [])
    if st.button("🗑 Supprimer la ligne", disabled=len(selected) == 0):
        sel = selected[0]
        base = st.session_state.mouvements_df
        mask = pd.Series([True] * len(base))
        for col in ["type", "description", "montant", "date_debut", "date_fin"]:
            if col in sel:
                mask &= base[col].astype(str) == str(sel[col])
        idx = mask.idxmax() if mask.any() else None
        if idx is not None:
            st.session_state.mouvements_df = base.drop(index=idx).reset_index(drop=True)
            st.session_state.pop("ag_grid", None)
            st.rerun()
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
            for dt, entries in ech.balance.items():
                for entry in entries:
                    rows.append({
                        "Date": entry.date,
                        "Description": entry.payement.description,
                        "Montant (€)": round(entry.payement.amount, 2),
                        "Solde (€)": round(entry.current_amount, 2),
                        "Spécial": "✔" if entry.payement.special else "",
                        "_order": entry.payement.order,
                    })

            result_df = pd.DataFrame(rows)
            result_df["Date"] = pd.to_datetime(result_df["Date"])
            result_df.sort_values("_order", inplace=True)
            result_df.drop(columns=["_order"], inplace=True)
            result_df.reset_index(drop=True, inplace=True)

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

            xlsx_buf = io.BytesIO()
            with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
                result_df.to_excel(writer, index=False, sheet_name="Paiements")
            st.download_button(
                label="📥 Télécharger en Excel",
                data=xlsx_buf.getvalue(),
                file_name="echeancier.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"Erreur lors du calcul : {e}")

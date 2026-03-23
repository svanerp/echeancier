# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
source venv/bin/activate
streamlit run main.py
```

Install dependencies:
```bash
pip install -r requirements.txt
```

## Architecture

Two files make up the entire app:

- **`models.py`** — Pure Python domain model, no Streamlit dependency. Contains the class hierarchy for movements and the computation engine.
- **`main.py`** — Streamlit UI layer. Imports from `models.py`, handles CSV I/O, the AgGrid editable table, and renders results.

### Domain model (`models.py`)

```
Movement (base: monthly recurring)
├── Income                  (revenu)
├── MovementOneShot         (unique)
├── MovementAnnuel          (1/an — matches only the start month each year)
├── MovementInterval        (n times/year)
└── MovementRemboursement   (emprunt — computes monthly installment from total + duration)
    └── MovementRemboursementNb  (emprunt by number of months)

Souhait                     (deferred purchase — triggered when balance is sufficient)
Payement                    (a concrete payment instance at a specific date)
BalanceEntry                (one row in the final balance: date + running balance + payment)
Echeancier                  (orchestrator: holds movements, runs compute(), produces balance dict)
```

`Echeancier.compute(mouvements)` iterates month-by-month, calls `m.match(date)` on each movement, creates `Payement` objects, then processes them in chronological order while tracking the running balance. *Souhaits* and interruptible loans (`interuptible=True`) are handled via `appurements`: the engine checks `check_souhait()` before each payment and may trigger an early repayment or a *souhait* when the balance allows it.

### CSV format

The CSV uses `;` as separator and supports comment-style header lines for global parameters:

```
#solde_initial=10000
#date_debut=01/01/2026
#nb_mois=24
frequency;description;amount;start_date;end_date;a;remb
```

Column mapping (CSV → UI internal name):
- `frequency` → `type` (values: `1 / mois`, `1 / an`, `revenu`, `unique`, `emprunt`/`empreunt`, `souhait`)
- `amount` → `montant`
- `start_date` / `end_date` → `date_debut` / `date_fin` (format `DD/MM/YYYY`)
- `a` → `mensualite` (monthly installment for loans)
- `remb` → `interruptible` (`yes` = early repayment enabled)

Note: the legacy CSV spelling `empreunt` is accepted and normalized to `emprunt` via `_TYPE_MAP`.

### Streamlit session state keys

- `mouvements_df` — the working DataFrame of movements
- `loaded_file` — filename of the last loaded CSV (prevents reload on rerun)
- `ag_grid` — AgGrid component key; deleted to force grid refresh after add/delete
- `param_solde_initial`, `param_date_debut`, `param_nb_mois` — parameters loaded from CSV headers

### AgGrid integration note

Dates are stored as Python `date` objects internally but must be converted to `DD/MM/YYYY` strings for AgGrid display (`_df_for_grid`) and parsed back on return (`_df_from_grid`). The grid key `ag_grid` must be popped from `session_state` and `st.rerun()` called to refresh the grid after programmatic row changes.

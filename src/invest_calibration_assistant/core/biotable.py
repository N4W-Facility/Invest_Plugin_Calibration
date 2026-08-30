# -*- coding: utf-8 -*-
"""Apply calibration factors to an InVEST biophysical table.

``factor_biophysical_table`` is the original ``Spotpy_InVEST.Factor_BioTable``
with its behaviour unchanged: for each row where the matching ``Status_Cal_*``
flag equals 1, the gated column is multiplied by the calibrated factor, then
rounded and clamped exactly as before. Rows flagged 0 keep their original value.

``required_status_columns`` / ``factor_caps`` expose that same knowledge for
config validation so problems surface *before* a calibration run starts.
"""

from __future__ import annotations

# model -> {factor param name: (gated column(s), Status_Cal flag, cap)}
# cap is the max allowed value of the gated column after scaling (None = no cap)
_GATES = {
    "AWY": {
        "Factor-Kc": (["Kc"], "Status_Cal_Kc", 1.2),
    },
    "SWY": {
        "Factor-Kc_m": ([f"Kc_{i}" for i in range(1, 13)], "Status_Cal_Kc", 1.2),
    },
    "SDR": {
        "Factor-C": (["usle_c"], "Status_Cal_C", 1.0),
        "Factor-P": (["usle_p"], "Status_Cal_P", 1.0),
    },
    "NDR_N": {
        "Factor_Load_N": (["load_n"], "Status_Cal_Load_N", None),
        "Factor_Eff_N": (["eff_n"], "Status_Cal_Eff_N", 1.0),
    },
    "NDR_P": {
        "Factor_Load_P": (["load_p"], "Status_Cal_Load_P", None),
        "Factor_Eff_P": (["eff_p"], "Status_Cal_Eff_P", 1.0),
    },
}


def required_status_columns(model: str) -> list[str]:
    """Status_Cal_* columns the biophysical table must contain for ``model``."""
    return [flag for _, flag, _ in _GATES.get(model, {}).values()]


def gated_columns(model: str) -> list[str]:
    cols: list[str] = []
    for target_cols, _, _ in _GATES.get(model, {}).values():
        cols.extend(target_cols)
    return cols


def factor_caps(model: str) -> dict[str, float]:
    """Max factor per parameter given the current table, i.e. cap / max(column).

    Returns ``{}`` for models/params without a cap. Requires reading the table.
    """
    return {}  # computed by the caller with the table in hand; see validate_config


# biophysical columns a calibration factor may scale -> must be float so the
# in-place assignment below does not raise on an all-integer column (pandas >= 2.1
# refuses to silently upcast int64 -> float64). This is the intended v0.2.4
# "pandas Copy-on-Write" fix, applied once and centrally.
_SCALABLE_COLUMNS = (
    "Kc", *[f"Kc_{i}" for i in range(1, 13)],
    "usle_c", "usle_p", "load_n", "eff_n", "load_p", "eff_p",
)


def factor_biophysical_table(path_bio_table, params, user_data):
    """Return a modified biophysical-table DataFrame (logic unchanged; the only
    addition is the up-front float coercion of the scalable columns)."""
    import pandas as pd  # noqa: PLC0415

    Table = pd.read_csv(path_bio_table, encoding="latin-1")
    for _col in _SCALABLE_COLUMNS:
        if _col in Table.columns:
            Table[_col] = Table[_col].astype("float64")

    if user_data.get("Status_AWY"):
        Values = round(Table["Kc"] * params["Factor-Kc"], 2)
        Values[Values >= 1.2] = 1.2
        Table.loc[Table["Status_Cal_Kc"] == 1, "Kc"] = Values.loc[Table["Status_Cal_Kc"] == 1]

    if user_data.get("Status_SWY"):
        for ij in range(1, 13):
            Values = round(Table["Kc_" + str(ij)] * round(params["Factor-Kc_m"], 2), 2)
            Values[Values >= 1.2] = 1.2
            Table.loc[Table["Status_Cal_Kc"] == 1, "Kc_" + str(ij)] = \
                Values.loc[Table["Status_Cal_Kc"] == 1]

    if user_data.get("Status_SDR") == 1:
        Values = round(Table["usle_c"] * round(params["Factor-C"], 2), 5)
        Values[Values > 1] = 1
        Table.loc[Table["Status_Cal_C"] == 1, "usle_c"] = Values.loc[Table["Status_Cal_C"] == 1]

        Values = round(Table["usle_p"] * round(params["Factor-P"], 2), 2)
        Values[Values > 1] = 1
        Table.loc[Table["Status_Cal_P"] == 1, "usle_p"] = Values.loc[Table["Status_Cal_P"] == 1]

    if user_data.get("Status_NDR_N") == 1:
        Values = round(Table["load_n"] * params["Factor_Load_N"], 3)
        Table.loc[Table["Status_Cal_Load_N"] == 1, "load_n"] = \
            Values.loc[Table["Status_Cal_Load_N"] == 1]
        Values = round(Table["eff_n"] * params["Factor_Eff_N"], 2)
        Table.loc[Table["Status_Cal_Eff_N"] == 1, "eff_n"] = \
            Values.loc[Table["Status_Cal_Eff_N"] == 1]

    if user_data.get("Status_NDR_P") == 1:
        Values = round(Table["load_p"] * params["Factor_Load_P"], 3)
        Table.loc[Table["Status_Cal_Load_P"] == 1, "load_p"] = \
            Values.loc[Table["Status_Cal_Load_P"] == 1]
        Values = round(Table["eff_p"] * params["Factor_Eff_P"], 2)
        Table.loc[Table["Status_Cal_Eff_P"] == 1, "eff_p"] = \
            Values.loc[Table["Status_Cal_Eff_P"] == 1]

    return Table


# Backwards-compatible alias.
Factor_BioTable = factor_biophysical_table  # noqa: N816

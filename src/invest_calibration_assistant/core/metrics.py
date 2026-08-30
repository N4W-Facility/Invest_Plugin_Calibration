# -*- coding: utf-8 -*-
"""Goodness-of-fit metrics.

Kept identical to the values the Workbench plugin has always produced (thin
wrappers over ``spotpy.objectivefunctions``), but the public entry point accepts
both the long labels used by the Workbench UI
(``"Root Mean Square Error (RMSE)"``) and the short codes preferred by the
shared-core / MCP config (``"RMSE"``).
"""

from __future__ import annotations

# short code -> long label (long label is what the original Cal_FunObj matched on)
_LONG = {
    "MSE": "Mean Square Error (MSE)",
    "MAE": "Mean Absolute Error (MAE)",
    "RMSE": "Root Mean Square Error (RMSE)",
    "RRMSE": "Relative Root Mean Squared Error (RRMSE)",
}
_SHORT = {v: k for k, v in _LONG.items()}
_SHORT.update({k: k for k in _LONG})  # allow short codes through unchanged


def metric_code(name: str) -> str:
    """Normalise any accepted spelling to the short code (MSE/MAE/RMSE/RRMSE)."""
    if name in _SHORT:
        return _SHORT[name]
    raise ValueError(
        f"Unknown evaluation metric {name!r}. "
        f"Use one of: {', '.join(_LONG)} (or their long names)."
    )


def objective(obs, sim, name: str) -> float:
    """Return the goodness-of-fit metric between observed and simulated arrays."""
    import spotpy  # noqa: PLC0415  (heavy import, deferred)

    code = metric_code(name)
    fn = {
        "MSE": spotpy.objectivefunctions.mse,
        "MAE": spotpy.objectivefunctions.mae,
        "RMSE": spotpy.objectivefunctions.rmse,
        "RRMSE": spotpy.objectivefunctions.rrmse,
    }[code]
    return float(fn(obs, sim))


# Backwards-compatible alias for code that imported the old name.
def Cal_FunObj(Obs, Sim, NameFunObj):  # noqa: N802,N803 - legacy signature
    return objective(Obs, Sim, NameFunObj)

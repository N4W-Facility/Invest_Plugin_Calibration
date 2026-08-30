# -*- coding: utf-8 -*-
"""Pick the best-fit parameter set and derive calibration diagnostics from the
per-iteration ``EVALUATIONS/<MODEL>_Metric_<suffix>.csv`` file.

This logic used to live *inside* ``Spotpy_InVEST.Plot_<MODEL>`` (which both drew
the figure and returned the best params). It is separated here so the engine can
select the best run and report diagnostics with no matplotlib dependency; the
plotting module reuses these functions.

Sign handling matches the original: the metric column already has
``factor_metric`` applied (``-1`` for DDS), so ``factor_metric * stored`` recovers
the real error and ``argmin`` on that is the best fit regardless of algorithm.
"""

from __future__ import annotations

import os

import numpy as np


def _load_metric_csv(metric_csv: str, n_params: int):
    tmp = np.loadtxt(metric_csv, delimiter=",", skiprows=1, ndmin=2)
    params = tmp[:, :n_params]
    metric = tmp[:, n_params]
    return params, metric


def pick_best(metric_csv: str, param_order: list[str], factor_metric: int) -> dict:
    """Return ``{"index", "parameters", "objective", "n_iterations"}``.

    ``objective`` is the real metric value (sign-corrected, always "lower = better").
    """
    params, metric = _load_metric_csv(metric_csv, len(param_order))
    real = factor_metric * metric
    idx = int(np.argmin(real))
    return {
        "index": idx,
        "parameters": {k: float(v) for k, v in zip(param_order, params[idx, :])},
        "objective": float(real[idx]),
        "n_iterations": int(len(metric)),
    }


def diagnostics(metric_csv: str, param_order: list[str], factor_metric: int) -> dict:
    """Per-parameter sensitivity / identifiability from the dotty-plot cloud.

    For each parameter: Spearman rank correlation |rho| between the sampled value
    and the real error, the value at the best iteration, and the tested range.
    ``sensitive`` is a coarse flag (|rho| >= 0.3).
    """
    params, metric = _load_metric_csv(metric_csv, len(param_order))
    real = factor_metric * metric
    best_idx = int(np.argmin(real))
    out: dict[str, dict] = {}
    for j, name in enumerate(param_order):
        col = params[:, j]
        rho = _spearman(col, real)
        out[name] = {
            "best": float(col[best_idx]),
            "tested_min": float(np.min(col)),
            "tested_max": float(np.max(col)),
            "spearman_abs": None if rho is None else round(abs(rho), 3),
            "sensitive": bool(rho is not None and abs(rho) >= 0.3),
        }
    return out


def obs_vs_sim(evaluations_dir: str, model: str, suffix: str, best_index: int) -> list[dict]:
    """Rebuild the labelled observed-vs-simulated table for the best iteration."""
    obs_p = os.path.join(evaluations_dir, f"{model}_Obs_{suffix}.csv")
    sim_p = os.path.join(evaluations_dir, f"{model}_Sim_{suffix}.csv")
    wsid_p = os.path.join(evaluations_dir, f"{model}_WsId_{suffix}.csv")
    if not (os.path.isfile(obs_p) and os.path.isfile(sim_p)):
        return []

    obs = np.loadtxt(obs_p, delimiter=",", skiprows=1, ndmin=1)
    sim = np.loadtxt(sim_p, delimiter=",", skiprows=1, ndmin=1)

    ws_ids = None
    if os.path.isfile(wsid_p):
        ws_ids = np.loadtxt(wsid_p, delimiter=",", skiprows=1, ndmin=1)
        n_gauges = int(ws_ids.size)
    else:
        # obs holds one block of n_gauges values per iteration, all blocks equal
        n_gauges = int(np.gcd(obs.size, sim.size)) if obs.size else sim.size
    n_gauges = max(1, n_gauges)
    if sim.size % n_gauges or obs.size % n_gauges:
        return []
    n_iter = sim.size // n_gauges
    sim_best = sim.reshape(n_iter, n_gauges)[best_index]
    obs_vec = obs.reshape(-1, n_gauges)[0]

    rows = []
    for k in range(n_gauges):
        row = {"obs": float(obs_vec[k]), "sim": float(sim_best[k])}
        if ws_ids is not None:
            row = {"ws_id": int(ws_ids[k]), **row}
        rows.append(row)
    return rows


def _spearman(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.size < 3 or np.all(a == a[0]) or np.all(b == b[0]):
        return None
    ar = _rankdata(a)
    br = _rankdata(b)
    ar -= ar.mean()
    br -= br.mean()
    denom = np.sqrt((ar**2).sum() * (br**2).sum())
    if denom == 0:
        return None
    return float((ar * br).sum() / denom)


def _rankdata(x):
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=float)
    ranks[order] = np.arange(1, len(x) + 1, dtype=float)
    # average ties
    _, inv, counts = np.unique(x, return_inverse=True, return_counts=True)
    csum = np.cumsum(counts)
    start = csum - counts
    avg = (start + csum + 1) / 2.0
    return avg[inv]

# -*- coding: utf-8 -*-
"""Calibration figures + machine-readable dotty-plot data.

Two outputs per model (both to ``<workspace>/FIGURES/``):

* ``dotty_data_<MODEL>.json`` -- always written, pure numpy, cannot fail: per
  parameter the sampled values + the best point, the real (sign-corrected)
  error per iteration, and the observed-vs-simulated pairs for the best
  iteration. Anything can plot from this (notebook, Workbench, spreadsheet).
* ``Calibration_<MODEL>.jpg`` -- the dotty / scatter grid, rendered by
  :mod:`invest_calibration_assistant.core._plot_worker` in a **separate
  process** so a broken native matplotlib (some headless conda builds crash in
  the Agg backend with ``0xc06d007f``) degrades to "no jpg" instead of killing
  the calibration.

``make_figures`` is only called when ``config["make_plots"]`` is true.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np

from . import selection

SUPPORTED = ("AWY", "SWY", "SDR", "NDR_N", "NDR_P")
_PLOT_TIMEOUT_S = 120


def dotty_data(model, workspace, suffix, factor_metric, param_order) -> str:
    """Write ``FIGURES/dotty_data_<MODEL>.json`` and return its path."""
    ev = os.path.join(workspace, "EVALUATIONS")
    metric_csv = os.path.join(ev, f"{model}_Metric_{suffix}.csv")
    n = len(param_order)
    tmp = np.loadtxt(metric_csv, delimiter=",", skiprows=1, ndmin=2)
    params = tmp[:, :n]
    real = factor_metric * tmp[:, n]                      # lower = better
    best = selection.pick_best(metric_csv, param_order, factor_metric)
    ovs = selection.obs_vs_sim(ev, model, suffix, best["index"])

    payload = {
        "model": model,
        "objective_is_error": True,
        "best_index": best["index"],
        "best_objective": best["objective"],
        "parameters": {
            name: {
                "values": params[:, j].round(6).tolist(),
                "best": float(params[best["index"], j]),
            }
            for j, name in enumerate(param_order)
        },
        "objective": real.round(6).tolist(),
        "obs_vs_sim": ovs,
    }
    out = os.path.join(workspace, "FIGURES", f"dotty_data_{model}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return out


def make_figures(model, workspace, suffix, metric_label, factor_metric, param_order) -> list[str]:
    if model not in SUPPORTED:
        return []
    made: list[str] = []
    try:
        made.append(dotty_data(model, workspace, suffix, factor_metric, param_order))
    except Exception:  # noqa: BLE001 - never let the JSON step break a run
        pass

    jpg = os.path.join(workspace, "FIGURES", f"Calibration_{model}.jpg")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "invest_calibration_assistant.core._plot_worker",
             model, workspace, suffix, metric_label, str(int(factor_metric)),
             ",".join(param_order)],
            capture_output=True, text=True, timeout=_PLOT_TIMEOUT_S,
        )
        if proc.returncode == 0 and os.path.isfile(jpg):
            made.append(jpg)
    except Exception:  # noqa: BLE001 - subprocess/timeout/native crash -> skip the jpg
        pass
    return made

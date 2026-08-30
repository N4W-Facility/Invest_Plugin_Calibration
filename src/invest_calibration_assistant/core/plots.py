# -*- coding: utf-8 -*-
"""Calibration figures: observed-vs-simulated scatter + one dotty plot per
parameter, for every supported model.

Replaces the five near-identical ``Spotpy_InVEST.Plot_<MODEL>`` functions with a
single generic renderer driven by per-model label/unit tables. Behaviour kept:

* best-iteration pick delegated to :mod:`selection` (sign handled there),
* AWY metric/obs/sim are shown in m3/s (value / 31_536_000) as in the original,
* matplotlib is imported lazily with the Agg backend; ``make_figures`` is only
  called when ``config["make_plots"]`` is true (default False — some headless
  conda ``matplotlib-base`` builds crash in ``savefig``).
"""

from __future__ import annotations

import os

import numpy as np

from . import selection

# param axis labels (LaTeX-ish) in vector order
_LABELS = {
    "AWY": [r"$Z$", r"Factor$_{K_c}$"],
    "SWY": [r"$\alpha$", r"$\beta$", r"$\gamma$", r"Factor$_{K_c}$"],
    "SDR": [r"SDR$_{max}$", r"$K$", r"IC$_{0}$", r"L$_{max}$", r"Factor$_{C}$", r"Factor$_{P}$"],
    "NDR_N": [r"SubCri$_{Len_N}$", r"Sub$_{Eff_N}$", r"Borselli$_{K}$",
              r"Factor$_{Load_N}$", r"Factor$_{Eff_N}$"],
    "NDR_P": [r"SubCri$_{Len_P}$", r"Sub$_{Eff_P}$", r"Borselli$_{K}$",
              r"Factor$_{Load_P}$", r"Factor$_{Eff_P}$"],
}
_UNIT = {"AWY": r"$(\mathrm{m}^3/\mathrm{s})$", "SWY": r"$(mm)$",
         "SDR": r"$(ton/year)$", "NDR_N": r"$(kg/year)$", "NDR_P": r"$(kg/year)$"}
# display scaling applied to metric + obs + sim (AWY: m3/year -> m3/s)
_SCALE = {"AWY": 1.0 / (3600 * 24 * 365)}
_GRID = {"AWY": (1, 3), "SWY": (2, 3), "SDR": (2, 4), "NDR_N": (2, 4), "NDR_P": (2, 4)}


def _mpl():
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    try:
        matplotlib.rcParams["font.family"] = "Times New Roman"
    except Exception:  # noqa: BLE001
        pass
    return plt


def make_figures(model, workspace, suffix, metric_label, factor_metric, param_order) -> list[str]:
    if model not in _LABELS:
        return []
    return [_plot(model, workspace, suffix, metric_label, factor_metric, param_order)]


def _plot(model, workspace, suffix, metric_label, factor_metric, param_order) -> str:
    plt = _mpl()
    ev = os.path.join(workspace, "EVALUATIONS")
    metric_csv = os.path.join(ev, f"{model}_Metric_{suffix}.csv")
    n = len(param_order)
    scale = _SCALE.get(model, 1.0)

    tmp = np.loadtxt(metric_csv, delimiter=",", skiprows=1, ndmin=2)
    params = tmp[:, :n]
    metric = factor_metric * tmp[:, n] * scale             # real error, lower=better

    best = selection.pick_best(metric_csv, param_order, factor_metric)
    id_min = best["index"]
    best_metric = best["objective"] * scale
    best_params = params[id_min, :]

    ovs = selection.obs_vs_sim(ev, model, suffix, id_min)
    obs = np.array([r["obs"] for r in ovs]) * scale if ovs else np.array([])
    sim = np.array([r["sim"] for r in ovs]) * scale if ovs else np.array([])

    rows, cols = _GRID[model]
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 5 * rows), squeeze=False)
    flat = axes.ravel()
    unit = _UNIT[model]

    ax = flat[0]
    if obs.size:
        mx = max(obs.max(), sim.max()) * 1.1
        ax.plot([0, mx], [0, mx], lw=1.2, color=[0.8, 0.8, 0.8])
        ax.scatter(obs, sim, s=90, edgecolor=[0, 0.5, 0.5],
                   facecolor=[0, 0.7, 0.7], alpha=0.4, linewidth=1.2)
    ax.set_xlabel(f"Observed {unit}", fontsize=14)
    ax.set_ylabel(f"Simulated {unit}", fontsize=14)
    ax.set_title(f"{metric_label} = {round(best_metric, 2)} {unit}", fontsize=14)

    for j in range(n):
        ax = flat[j + 1]
        ax.scatter(params[:, j], metric, s=30, color=[1, 0.66, 0], alpha=0.25)
        ax.scatter(best_params[j], best_metric, s=60, color=[1, 0, 0])
        ax.set_xlabel(_LABELS[model][j], fontsize=14)
        ax.set_ylabel(f"{metric_label} {unit}", fontsize=12)
        ax.set_title(f"{_LABELS[model][j]} = {round(float(best_params[j]), 3)}", fontsize=13)
    for k in range(n + 1, len(flat)):
        flat[k].axis("off")

    out = os.path.join(workspace, "FIGURES", f"Calibration_{model}.jpg")
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close(fig)
    return out

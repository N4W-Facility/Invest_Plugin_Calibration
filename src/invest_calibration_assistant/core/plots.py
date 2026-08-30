# -*- coding: utf-8 -*-
"""Calibration figures (dotty plots + observed-vs-simulated scatter).

Ported from ``Spotpy_InVEST.Plot_<MODEL>`` with two changes:

* best-iteration selection is delegated to :mod:`selection` (no duplicated
  ``argmin`` logic, no return-value coupling),
* matplotlib is imported lazily with the ``Agg`` backend and a safe font, so a
  headless subprocess without "Times New Roman" installed still works.

Only SDR is wired for the shared-core milestone; the others slot in the same way.
"""

from __future__ import annotations

import os

import numpy as np

from . import selection

# axis labels per model parameter (LaTeX-ish, matching the original figures)
_LABELS = {
    "SDR": [r"SDR$_{max}$", r"$K$", r"IC$_{0}$", r"L$_{max}$", r"Factor$_{C}$", r"Factor$_{P}$"],
}
_UNITS = {"SDR": r"$(ton/year)$"}


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
    if model != "SDR":
        return []
    return [_plot_sdr(workspace, suffix, metric_label, factor_metric, param_order)]


def _plot_sdr(workspace, suffix, metric_label, factor_metric, param_order) -> str:
    plt = _mpl()
    ev = os.path.join(workspace, "EVALUATIONS")

    tmp = np.loadtxt(os.path.join(ev, f"SDR_Metric_{suffix}.csv"),
                     delimiter=",", skiprows=1, ndmin=2)
    params = tmp[:, :6]
    metric = factor_metric * tmp[:, 6]        # real error, lower = better
    best = selection.pick_best(os.path.join(ev, f"SDR_Metric_{suffix}.csv"),
                               param_order, factor_metric)
    id_min = best["index"]
    best_metric = best["objective"]
    best_params = params[id_min, :]

    ovs = selection.obs_vs_sim(ev, "SDR", suffix, id_min)
    obs = np.array([r["obs"] for r in ovs]) if ovs else np.array([])
    sim = np.array([r["sim"] for r in ovs]) if ovs else np.array([])

    fig, axes = plt.subplots(2, 4, figsize=(16, 10))
    unit = _UNITS["SDR"]

    ax = axes[0, 0]
    if obs.size:
        mx = max(obs.max(), sim.max()) * 1.1
        ax.plot([0, mx], [0, mx], lw=1.2, color=[0.8, 0.8, 0.8])
        ax.scatter(obs, sim, s=100, edgecolor=[0, 0.5, 0.5],
                   facecolor=[0, 0.7, 0.7], alpha=0.4, linewidth=1.2)
    ax.set_xlabel(f"Observed {unit}", fontsize=14)
    ax.set_ylabel(f"Simulated {unit}", fontsize=14)
    ax.set_title(f"{metric_label} = {round(best_metric, 2)} {unit}", fontsize=14)

    positions = [(0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2)]
    for j, (r, c) in enumerate(positions):
        ax = axes[r, c]
        ax.scatter(params[:, j], metric, s=30, color=[1, 0.66, 0], alpha=0.25)
        ax.scatter(best_params[j], best_metric, s=60, color=[1, 0, 0])
        ax.set_xlabel(_LABELS["SDR"][j], fontsize=14)
        ax.set_ylabel(f"{metric_label} {unit}", fontsize=12)
        ax.set_title(f"{_LABELS['SDR'][j]} = {round(float(best_params[j]), 3)}", fontsize=13)
    axes[1, 3].axis("off")

    out = os.path.join(workspace, "FIGURES", "Calibration_SDR.jpg")
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close(fig)
    return out

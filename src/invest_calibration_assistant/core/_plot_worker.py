# -*- coding: utf-8 -*-
"""Render one ``Calibration_<MODEL>.jpg`` -- runs as its own process.

    python -m invest_calibration_assistant.core._plot_worker \
        <model> <workspace> <suffix> <metric_label> <factor_metric> <p1,p2,...>

Isolated from the engine on purpose: some headless conda matplotlib builds crash
natively in the Agg backend, and a dead subprocess must not take the calibration
down with it. One generic renderer replaces the five ``Plot_<MODEL>`` functions
(AWY is shown in m3/s, as in the original).
"""

from __future__ import annotations

import os
import sys

import numpy as np

from . import selection

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
_SCALE = {"AWY": 1.0 / (3600 * 24 * 365)}
_GRID = {"AWY": (1, 3), "SWY": (2, 3), "SDR": (2, 4), "NDR_N": (2, 4), "NDR_P": (2, 4)}


def render(model, workspace, suffix, metric_label, factor_metric, param_order) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        matplotlib.rcParams["font.family"] = "Times New Roman"
    except Exception:  # noqa: BLE001
        pass

    ev = os.path.join(workspace, "EVALUATIONS")
    metric_csv = os.path.join(ev, f"{model}_Metric_{suffix}.csv")
    n = len(param_order)
    scale = _SCALE.get(model, 1.0)

    tmp = np.loadtxt(metric_csv, delimiter=",", skiprows=1, ndmin=2)
    params = tmp[:, :n]
    metric = factor_metric * tmp[:, n] * scale
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


def main(argv) -> int:
    model, workspace, suffix, metric_label, factor_metric, param_csv = argv[:6]
    render(model, workspace, suffix, metric_label, int(factor_metric), param_csv.split(","))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

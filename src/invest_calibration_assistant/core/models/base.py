# -*- coding: utf-8 -*-
"""Model-plugin contract for the calibration engine.

Each supported InVEST model (AWY, SWY, SDR, NDR_N, NDR_P) provides one
``ModelPlugin`` describing:

* ``param_order``  – internal parameter keys in the order the spotpy vector
                     delivers them (must match ``PARAM_ORDER`` used everywhere)
* ``obs_column``   – column of ``Obs_Data.csv`` holding the observed values
* ``required_inputs`` – keys expected in ``config["model_inputs"]``
* ``run_iteration(ctx, vector) -> float`` – one calibration iteration: perturb
  the biophysical table, run the InVEST model on the *calibration* watersheds,
  aggregate the simulated values, return ``factor_metric * metric``. It also
  appends the per-iteration rows to ``EVALUATIONS/<MODEL>_{Metric,Obs,Sim}_*.csv``
  exactly as the Workbench plugin does.
* ``run_best(ctx, params_val) -> str`` – final InVEST run on the *full*
  watersheds with the best-fit parameters; returns the output workspace path.

The engine stays model-agnostic and just drives spotpy over these.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class IterationContext:
    workspace: str
    model: str
    suffix: str                     # label appended to output filenames
    model_inputs: dict              # resolved absolute paths + scalars
    obs_df: "object"               # pandas.DataFrame (kept untyped to avoid import)
    metric_name: str               # short code: MSE | MAE | RMSE | RRMSE
    factor_metric: int             # -1 for DDS (maximises), +1 otherwise
    user_data: dict                # Status_* flags for factor_biophysical_table
    log: Callable[[str], None] = print

    # derived directories
    tmp_dir: str = field(init=False)
    outputs_dir: str = field(init=False)
    evaluations_dir: str = field(init=False)
    figures_dir: str = field(init=False)
    parameters_dir: str = field(init=False)

    def __post_init__(self):
        self.tmp_dir = os.path.join(self.workspace, "TMP")
        self.outputs_dir = os.path.join(self.workspace, "OUTPUTS")
        self.evaluations_dir = os.path.join(self.workspace, "EVALUATIONS")
        self.figures_dir = os.path.join(self.workspace, "FIGURES")
        self.parameters_dir = os.path.join(self.workspace, "PARAMETERS")


def append_eval_csv(evaluations_dir: str, name: str, header: str, rows: list[str]) -> None:
    """Append one iteration's data to an EVALUATIONS CSV (creates it with the
    header on first write). Identical to the plugin's ``_save_eval_csv``."""
    path = os.path.join(evaluations_dir, name)
    exists = os.path.isfile(path)
    with open(path, "a", encoding="utf-8") as f:
        if not exists:
            f.write(header + "\n")
        for row in rows:
            f.write(row + "\n")


def write_iteration_eval(ctx, model: str, metric_header: str, param_row: str,
                         obs_val, sim_val, matched_ws_ids) -> None:
    """Append the per-iteration rows every model writes: ``<MODEL>_Metric``,
    ``_Obs``, ``_Sim`` (byte-for-byte as the Workbench plugin) plus ``_WsId``
    (written once) so the engine can label the best obs-vs-sim table."""
    sfx = ctx.suffix
    ev = ctx.evaluations_dir
    append_eval_csv(ev, f"{model}_Metric_{sfx}.csv", metric_header, [param_row])
    append_eval_csv(ev, f"{model}_Obs_{sfx}.csv", "Obs", [f"{v:.2f}" for v in obs_val])
    append_eval_csv(ev, f"{model}_Sim_{sfx}.csv", "Sim", [f"{v:.2f}" for v in sim_val])
    wsid_csv = os.path.join(ev, f"{model}_WsId_{sfx}.csv")
    if not os.path.isfile(wsid_csv):
        append_eval_csv(ev, f"{model}_WsId_{sfx}.csv", "ws_id",
                        [str(int(w)) for w in matched_ws_ids])


class ModelPlugin:
    name: str = ""
    param_order: list[str] = []
    obs_column: str = ""
    required_inputs: list[str] = []
    #: gated biophysical columns that must exist for this model
    biophysical_gated_columns: list[str] = []

    def run_iteration(self, ctx: IterationContext, vector) -> float:  # pragma: no cover
        raise NotImplementedError

    def run_best(self, ctx: IterationContext, params_val: dict) -> str:  # pragma: no cover
        raise NotImplementedError

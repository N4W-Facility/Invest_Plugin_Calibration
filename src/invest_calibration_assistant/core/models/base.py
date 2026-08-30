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

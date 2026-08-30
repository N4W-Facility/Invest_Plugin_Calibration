# -*- coding: utf-8 -*-
"""The calibration loop, model-agnostic.

``calibrate(config)`` is the single shared entry point used by both the InVEST
Workbench plugin (``calibration_assistant.execute``) and the invest-mcp
``run_calibration`` tool. It:

1. normalises + validates the config (refuses to start on any error),
2. drives spotpy (DDS / LHS / SCE-UA) over the selected model-plugin,
3. selects the best-fit parameter set from the per-iteration metric CSV,
4. optionally re-runs the model on the full watersheds with those parameters,
5. optionally draws the dotty / scatter figures,
6. returns a JSON-able result dict.

The per-iteration EVALUATIONS / PARAMETERS / OUTPUTS / TMP layout is byte-for-byte
what the Workbench plugin has always written, so existing downstream tooling and
the figures keep working.
"""

from __future__ import annotations

import os

from . import selection
from .config import normalize, validate
from .models import REGISTRY, IterationContext


def _mkdirs(workspace: str) -> None:
    for sub in ("EVALUATIONS", "PARAMETERS", "OUTPUTS", "FIGURES", "TMP"):
        os.makedirs(os.path.join(workspace, sub), exist_ok=True)


def _user_data(model: str, suffix: str) -> dict:
    return {
        "Suffix": suffix,
        "Status_AWY": 1 if model == "AWY" else 0,
        "Status_SWY": 1 if model == "SWY" else 0,
        "Status_SDR": 1 if model == "SDR" else 0,
        "Status_NDR_N": 1 if model == "NDR_N" else 0,
        "Status_NDR_P": 1 if model == "NDR_P" else 0,
    }


def calibrate(config: dict, *, progress_cb=None, log=print) -> dict:
    """Run a calibration. ``progress_cb(iter, n, objective, params)`` is called
    after every iteration if given. Returns a result dict (see module docstring).
    """
    cfg = normalize(config)
    issues = validate(cfg)
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    if errors:
        return {"ok": False, "stage": "validation", "errors": errors, "warnings": warnings}

    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415
    import spotpy  # noqa: PLC0415

    model = cfg["model"]
    plugin = REGISTRY[model]
    workspace = cfg["workspace_dir"]
    suffix = cfg["results_suffix"]
    method = cfg["optimizer"]["method"]
    n_sim = cfg["optimizer"]["n_simulations"]
    factor_metric = -1 if method == "DDS" else 1

    _mkdirs(workspace)
    obs_df = pd.read_csv(cfg["observed_data_path"])

    ctx = IterationContext(
        workspace=workspace, model=model, suffix=suffix,
        model_inputs=cfg["model_inputs"], obs_df=obs_df,
        metric_name=cfg["objective"], factor_metric=factor_metric,
        user_data=_user_data(model, suffix), log=log,
    )

    lo = [cfg["parameters"][k]["min"] for k in plugin.param_order]
    hi = [cfg["parameters"][k]["max"] for k in plugin.param_order]
    _spotpy_params = [
        spotpy.parameter.Uniform(k, lo[i], hi[i]) for i, k in enumerate(plugin.param_order)
    ]

    iterations: list[dict] = []

    class _Setup:
        def parameters(self):
            return spotpy.parameter.generate(_spotpy_params)

        def simulation(self, vector):
            return np.array(vector)

        def evaluation(self):
            return obs_df

        def objectivefunction(self, simulation, evaluation, **kwargs):
            obj = plugin.run_iteration(ctx, simulation)
            it = len(iterations) + 1
            pdict = {k: float(v) for k, v in zip(plugin.param_order, simulation)}
            real = factor_metric * obj
            iterations.append({"iter": it, "objective": real, "params": pdict})
            if progress_cb:
                try:
                    progress_cb(it, n_sim, real, pdict)
                except Exception:  # noqa: BLE001 - never let reporting kill the run
                    pass
            return obj

    log(f"Calibration start: model={model} method={method} n_sim={n_sim} "
        f"objective={cfg['objective']}")

    db_path = os.path.join(workspace, "PARAMETERS", f"{model}_{method.replace('-', '')}")
    algo = {"DDS": spotpy.algorithms.dds,
            "LHS": spotpy.algorithms.lhs,
            "SCE-UA": spotpy.algorithms.sceua}[method]
    sampler = algo(_Setup(), parallel="seq", dbname=db_path, dbformat="csv", sim_timeout=2)

    seed = cfg["optimizer"].get("seed")
    if seed is not None:
        np.random.seed(int(seed))
    sampler.sample(n_sim)

    metric_csv = os.path.join(workspace, "EVALUATIONS", f"{model}_Metric_{suffix}.csv")
    best = selection.pick_best(metric_csv, plugin.param_order, factor_metric)
    diag = selection.diagnostics(metric_csv, plugin.param_order, factor_metric)
    ovs = selection.obs_vs_sim(ctx.evaluations_dir, model, suffix, best["index"])

    figures: list[str] = []
    if cfg.get("make_plots"):
        try:
            from . import plots  # noqa: PLC0415
            figures = plots.make_figures(model, workspace, suffix, cfg["objective"],
                                         factor_metric, plugin.param_order)
        except Exception as exc:  # noqa: BLE001 - figures are optional
            log(f"Figure generation skipped: {exc}")

    best_run_ws = None
    if cfg.get("run_best"):
        initial = {k: (cfg["parameters"][k].get("value")
                       if cfg["parameters"][k].get("value") is not None
                       else best["parameters"][k])
                   for k in plugin.param_order}
        final_params = {**initial, **best["parameters"]}
        log(f"Best-fit parameters: {best['parameters']}")
        try:
            best_run_ws = plugin.run_best(ctx, final_params)
        except Exception as exc:  # noqa: BLE001
            log(f"Best-parameters run failed: {exc}")

    return {
        "ok": True,
        "model": model,
        "objective_metric": cfg["objective"],
        "optimizer": {"method": method, "n_simulations": n_sim},
        "n_iterations": len(iterations),
        "best_parameters": best["parameters"],
        "best_objective": best["objective"],
        "obs_vs_sim": ovs,
        "iterations": iterations,
        "diagnostics": diag,
        "warnings": warnings,
        "artifacts": {
            "metric_csv": metric_csv,
            "spotpy_db": db_path + ".csv",
            "figures": figures,
            "best_run_workspace": best_run_ws,
            "evaluations_dir": ctx.evaluations_dir,
        },
    }

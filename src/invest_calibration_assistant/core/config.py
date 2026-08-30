# -*- coding: utf-8 -*-
"""Calibration config: normalisation + pre-run validation.

The config is a plain dict so it round-trips through JSON (the MCP server builds
it and hands it to the engine in a subprocess). Both the Workbench adapter and
the MCP tool call :func:`normalize` then :func:`validate` before
:func:`invest_calibration_assistant.core.engine.calibrate`.

Shape::

    {
      "model": "SDR",
      "workspace_dir": "<abs>",
      "results_suffix": "cal01",                 # optional; default = model name
      "optimizer": {"method": "DDS", "n_simulations": 150, "seed": None},
      "objective": "RMSE",                        # MSE|MAE|RMSE|RRMSE (long names ok)
      "parameters": {"sdr_max": {"min": .3, "max": .9, "value": .6}, ...},
      "observed_data_path": "<abs>/Obs_Data.csv",
      "model_inputs": {"lulc_path": "...", "biophysical_table_path": "...", ...},
      "run_best": true,
      "make_plots": true
    }
"""

from __future__ import annotations

import os

from .metrics import metric_code
from .models import OBS_COLUMN_ALL, PARAM_ORDER_ALL, SUPPORTED_MODELS
from .biotable import required_status_columns

_METHOD_ALIASES = {
    "DDS": "DDS", "Dynamical dimensional search (DDS)": "DDS",
    "Dynamically Dimensioned Search (DDS)": "DDS",
    "LHS": "LHS", "Latin Hypercube Sampling (LHS)": "LHS",
    "SCE-UA": "SCE-UA", "SCEUA": "SCE-UA",
    "Shuffled Complex Evolution (SCE-UA)": "SCE-UA",
}


def _issue(field, message, level="error"):
    return {"field": field, "message": message, "level": level}


# ---------------------------------------------------------------------------
def normalize(config: dict) -> dict:
    cfg = dict(config or {})
    cfg["model"] = str(cfg.get("model", "")).strip().upper()
    cfg["results_suffix"] = str(cfg.get("results_suffix") or cfg["model"] or "Calibration")

    opt = dict(cfg.get("optimizer") or {})
    opt["method"] = _METHOD_ALIASES.get(str(opt.get("method", "DDS")).strip(), str(opt.get("method", "DDS")))
    opt["n_simulations"] = int(opt.get("n_simulations", 0) or 0)
    opt.setdefault("seed", None)
    cfg["optimizer"] = opt

    try:
        cfg["objective"] = metric_code(cfg.get("objective", "RMSE"))
    except ValueError:
        cfg["objective"] = cfg.get("objective", "RMSE")  # let validate() flag it

    params = {}
    for key, spec in (cfg.get("parameters") or {}).items():
        if isinstance(spec, dict):
            params[key] = {
                "min": _f(spec.get("min")), "max": _f(spec.get("max")),
                "value": _f(spec.get("value")) if spec.get("value") is not None else None,
            }
        elif isinstance(spec, (list, tuple)) and len(spec) >= 2:
            params[key] = {"min": _f(spec[0]), "max": _f(spec[1]),
                           "value": _f(spec[2]) if len(spec) > 2 else None}
    cfg["parameters"] = params

    mi = dict(cfg.get("model_inputs") or {})
    if mi.get("threshold_flow_accumulation") not in (None, ""):
        mi["threshold_flow_accumulation"] = float(mi["threshold_flow_accumulation"])
    cfg["model_inputs"] = mi

    cfg.setdefault("run_best", True)
    # Figures are opt-in: they need a fully working matplotlib (some headless
    # conda-forge matplotlib-base builds crash in the Agg backend). The engine's
    # structured `diagnostics` / `obs_vs_sim` cover interpretation without them.
    cfg.setdefault("make_plots", False)
    return cfg


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
def validate(config: dict) -> list[dict]:
    """Return a list of issues (``level`` in ``{"error","warning"}``). Empty =
    ready to run. Callers should refuse to start if any ``error`` is present."""
    cfg = normalize(config)
    issues: list[dict] = []
    model = cfg["model"]

    if model not in PARAM_ORDER_ALL:
        issues.append(_issue("model", f"Unknown model {model!r}. "
                             f"Known: {', '.join(PARAM_ORDER_ALL)}."))
        return issues
    if model not in SUPPORTED_MODELS:
        issues.append(_issue("model",
                             f"{model} is not yet wired in the shared core "
                             f"(available: {', '.join(SUPPORTED_MODELS)})."))

    # workspace
    if not cfg.get("workspace_dir"):
        issues.append(_issue("workspace_dir", "workspace_dir is required."))

    # optimizer
    if cfg["optimizer"]["method"] not in ("DDS", "LHS", "SCE-UA"):
        issues.append(_issue("optimizer.method",
                             f"Unknown method {cfg['optimizer']['method']!r}; "
                             "use DDS, LHS or SCE-UA."))
    if cfg["optimizer"]["n_simulations"] < 10:
        issues.append(_issue("optimizer.n_simulations",
                             "n_simulations must be >= 10 (DDS init phase)."))

    # objective
    try:
        metric_code(cfg["objective"])
    except ValueError as e:
        issues.append(_issue("objective", str(e)))

    # parameters
    expected = PARAM_ORDER_ALL[model]
    got = set(cfg["parameters"])
    for missing in [p for p in expected if p not in got]:
        issues.append(_issue(f"parameters.{missing}",
                             f"{model} requires a search range for {missing!r}."))
    for extra in sorted(got - set(expected)):
        issues.append(_issue(f"parameters.{extra}",
                             f"{extra!r} is not a {model} calibration parameter; ignored.",
                             "warning"))
    for k, s in cfg["parameters"].items():
        if k not in expected:
            continue
        lo, hi, val = s["min"], s["max"], s["value"]
        if lo is None or hi is None:
            issues.append(_issue(f"parameters.{k}", "min and max are required."))
            continue
        if lo > hi:
            issues.append(_issue(f"parameters.{k}", f"min ({lo}) > max ({hi})."))
        elif lo == hi:
            issues.append(_issue(f"parameters.{k}",
                                 f"min == max ({lo}); parameter will not be explored.",
                                 "warning"))
        if val is not None and not (lo <= val <= hi):
            issues.append(_issue(f"parameters.{k}",
                                 f"initial value {val} outside [{lo}, {hi}]."))

    # observed data
    obs_path = cfg.get("observed_data_path")
    obs_col = OBS_COLUMN_ALL[model]
    if not obs_path or not os.path.isfile(obs_path):
        issues.append(_issue("observed_data_path", f"file not found: {obs_path!r}"))
    else:
        header = _csv_header(obs_path)
        if "ws_id" not in header:
            issues.append(_issue("observed_data_path", "missing 'ws_id' column."))
        if obs_col not in header:
            issues.append(_issue("observed_data_path",
                                 f"missing '{obs_col}' column (observed values for {model})."))

    # model inputs
    plugin_reqs = _required_inputs(model)
    mi = cfg["model_inputs"]
    for key in plugin_reqs:
        v = mi.get(key)
        if v in (None, ""):
            issues.append(_issue(f"model_inputs.{key}", f"required for {model}."))
        elif key.endswith("_path") and not os.path.exists(str(v)):
            issues.append(_issue(f"model_inputs.{key}", f"file not found: {v}"))

    # biophysical Status_Cal_* columns
    bio = mi.get("biophysical_table_path")
    if bio and os.path.isfile(bio):
        header = _csv_header(bio)
        for col in required_status_columns(model):
            if col not in header:
                issues.append(_issue("model_inputs.biophysical_table_path",
                                     f"missing calibration flag column {col!r}. "
                                     "Add it (value 1 on every row unless you want to "
                                     "exclude specific LULC classes)."))
        _check_factor_caps(model, cfg["parameters"], bio, header, issues)

    return issues


# ---------------------------------------------------------------------------
def _required_inputs(model: str) -> list[str]:
    from .models import REGISTRY
    if model in REGISTRY:
        return list(REGISTRY[model].required_inputs)
    return ["lulc_path", "biophysical_table_path", "calibration_watersheds_path"]


def _csv_header(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="latin-1") as f:
            return [c.strip() for c in f.readline().strip().split(",")]
    except OSError:
        return []


_CAP_BY_PARAM = {
    "Factor-Kc": ("Kc", 1.2), "Factor-Kc_m": ("Kc_1", 1.2),
    "Factor-C": ("usle_c", 1.0), "Factor-P": ("usle_p", 1.0),
    "Factor_Eff_N": ("eff_n", 1.0), "Factor_Eff_P": ("eff_p", 1.0),
}


def _check_factor_caps(model, parameters, bio_path, header, issues):
    caps = {k: v for k, v in _CAP_BY_PARAM.items() if k in parameters}
    if not caps:
        return
    try:
        import csv
        with open(bio_path, "r", encoding="latin-1") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return
    for param, (col, cap) in caps.items():
        if col not in header:
            continue
        vals = [float(r[col]) for r in rows if r.get(col) not in (None, "", "NA")]
        if not vals:
            continue
        mx = max(vals)
        pmax = parameters[param]["max"]
        if pmax is not None and mx > 0 and pmax * mx > cap + 1e-9:
            issues.append(_issue(
                f"parameters.{param}",
                f"max factor {pmax} x max({col})={mx:g} = {pmax*mx:g} exceeds the "
                f"InVEST cap {cap}; iterations above {cap/mx:.3g} are clamped, "
                "shrinking the effective search range.",
                "warning"))

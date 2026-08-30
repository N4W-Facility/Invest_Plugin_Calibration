# -*- coding: utf-8 -*-
"""Shared calibration core — UI-independent.

Consumed by:
* ``invest_calibration_assistant.calibration_assistant`` (the InVEST Workbench
  plugin adapter — turns Workbench ``args`` into a config and calls ``calibrate``)
* ``invest-mcp``'s ``run_calibration`` tool (builds the config from an MCP request
  and calls ``calibrate`` in a subprocess)

Public API::

    from invest_calibration_assistant.core import calibrate, validate_config, normalize_config

    cfg = { "model": "SDR", "workspace_dir": ..., "optimizer": {...},
            "objective": "RMSE", "parameters": {...}, "observed_data_path": ...,
            "model_inputs": {...} }
    issues = validate_config(cfg)            # [] means ready
    result = calibrate(cfg, progress_cb=...) # {"ok": True, "best_parameters": {...}, ...}
"""

from __future__ import annotations

from .config import normalize as normalize_config
from .config import validate as validate_config
from .engine import calibrate
from .models import SUPPORTED_MODELS

__all__ = ["calibrate", "validate_config", "normalize_config", "SUPPORTED_MODELS"]

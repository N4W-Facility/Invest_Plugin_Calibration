# -*- coding: utf-8 -*-
"""Registry of calibration model-plugins.

SDR is wired first (shared-core milestone 1). AWY / SWY / NDR_N / NDR_P follow
the same ``ModelPlugin`` contract and will register here as they are ported from
``calibration_assistant._execute_*_direct``.
"""

from __future__ import annotations

from .base import IterationContext, ModelPlugin, append_eval_csv
from .sdr import PLUGIN as _SDR

REGISTRY: dict[str, ModelPlugin] = {
    _SDR.name: _SDR,
}

SUPPORTED_MODELS = tuple(REGISTRY)

# Parameter order per model (also the spotpy vector order). Mirrors
# calibration_assistant._build_spotpy_params so the two stay in lock-step.
PARAM_ORDER: dict[str, list[str]] = {name: plugin.param_order for name, plugin in REGISTRY.items()}
# Known keys for models not yet ported (used only for config validation messages).
PARAM_ORDER_ALL = {
    "AWY":   ["Z", "Factor-Kc"],
    "SWY":   ["Alpha", "Beta", "Gamma", "Factor-Kc_m"],
    "SDR":   ["sdr_max", "Borselli-K_SDR", "IC0", "L_max", "Factor-C", "Factor-P"],
    "NDR_N": ["SubCri_Len_N", "Sub_Eff_N", "Borselli-K_NDR", "Factor_Load_N", "Factor_Eff_N"],
    "NDR_P": ["SubCri_Len_P", "Sub_Eff_P", "Borselli-K_NDR", "Factor_Load_P", "Factor_Eff_P"],
}
OBS_COLUMN_ALL = {"AWY": "AWY", "SWY": "SWY", "SDR": "SDR", "NDR_N": "NDR_N", "NDR_P": "NDR_P"}

__all__ = [
    "REGISTRY", "SUPPORTED_MODELS", "PARAM_ORDER", "PARAM_ORDER_ALL", "OBS_COLUMN_ALL",
    "IterationContext", "ModelPlugin", "append_eval_csv",
]

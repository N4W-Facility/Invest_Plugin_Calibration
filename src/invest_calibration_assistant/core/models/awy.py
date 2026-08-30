# -*- coding: utf-8 -*-
"""AWY (Annual Water Yield) calibration model-plugin.

Ported from ``calibration_assistant._execute_awy_direct`` and the AWY branch of
``_run_best_params`` (behaviour unchanged).

Calibrated: ``Z`` (Zhang seasonality constant, a model argument) and
``Factor-Kc`` (multiplier on the biophysical ``Kc`` column). Observed variable:
annual streamflow ``AWY`` (m3/year); simulated: ``wyield_vol`` from
``output/watershed_results_wyield_<suffix>.csv``.
"""

from __future__ import annotations

import os

import pandas as pd

from ..biotable import factor_biophysical_table
from ..metrics import objective
from ..zonal import ismember
from .base import IterationContext, ModelPlugin, write_iteration_eval

_PARAM_ORDER = ["Z", "Factor-Kc"]


class AwyPlugin(ModelPlugin):
    name = "AWY"
    param_order = _PARAM_ORDER
    obs_column = "AWY"
    required_inputs = [
        "lulc_path", "biophysical_table_path", "depth_to_root_rest_layer_path",
        "eto_path", "pawc_path", "precipitation_path", "calibration_watersheds_path",
    ]
    biophysical_gated_columns = ["Kc", "Status_Cal_Kc"]

    def _args(self, ctx, tmp_bio, out_dir, z, watersheds):
        mp = ctx.model_inputs
        a = {
            "lulc_path":                     mp["lulc_path"],
            "biophysical_table_path":        tmp_bio,
            "depth_to_root_rest_layer_path": mp["depth_to_root_rest_layer_path"],
            "eto_path":                      mp["eto_path"],
            "pawc_path":                     mp["pawc_path"],
            "precipitation_path":            mp["precipitation_path"],
            "watersheds_path":               watersheds,
            "seasonality_constant":          "%.2f" % z,
            "results_suffix":                ctx.suffix,
            "workspace_dir":                 out_dir,
        }
        if mp.get("sub_watersheds_path"):
            a["sub_watersheds_path"] = mp["sub_watersheds_path"]
        return a

    def run_iteration(self, ctx: IterationContext, vector) -> float:
        import natcap.invest.annual_water_yield as _awy  # noqa: PLC0415

        z, kc = float(vector[0]), float(vector[1])
        ctx.log(f"AWY  Z={z:.2f}  Factor-Kc={kc:.2f}")

        mp = ctx.model_inputs
        table = factor_biophysical_table(mp["biophysical_table_path"],
                                         {"Z": z, "Factor-Kc": kc}, ctx.user_data)
        tmp_bio = os.path.join(ctx.tmp_dir, "AWY_biophysical.csv")
        table.to_csv(tmp_bio, index=False)

        out_dir = os.path.join(ctx.outputs_dir, "01-AWY")
        _awy.execute(self._args(ctx, tmp_bio, out_dir, z, mp["calibration_watersheds_path"]))

        suffix_part = f"_{ctx.suffix}" if ctx.suffix else ""
        sim_df = pd.read_csv(os.path.join(out_dir, "output",
                                          f"watershed_results_wyield{suffix_part}.csv"))
        sim_val = sim_df["wyield_vol"].values
        I, idx = ismember(sim_df["ws_id"].values, ctx.obs_df["ws_id"].values)
        obs_val = ctx.obs_df[self.obs_column].values[idx]
        sim_val = sim_val[I]
        obj = ctx.factor_metric * objective(obs_val, sim_val, ctx.metric_name)

        write_iteration_eval(
            ctx, "AWY", f"Z,Factor-Kc,{ctx.metric_name}",
            f"{z:.2f},{kc:.2f},{obj:.2f}",
            obs_val, sim_val, ctx.obs_df["ws_id"].values[idx],
        )
        return obj

    def run_best(self, ctx: IterationContext, params_val: dict) -> str:
        import natcap.invest.annual_water_yield as _awy  # noqa: PLC0415

        mp = ctx.model_inputs
        table = factor_biophysical_table(mp["biophysical_table_path"], params_val, ctx.user_data)
        tmp_bio = os.path.join(ctx.tmp_dir, "AWY_BioTable_best.csv")
        table.to_csv(tmp_bio, index=False)
        out_dir = os.path.join(ctx.outputs_dir, "AWY_best")
        watersheds = mp.get("watersheds_path") or mp["calibration_watersheds_path"]
        _awy.execute(self._args(ctx, tmp_bio, out_dir, params_val.get("Z", 3.0), watersheds))
        ctx.log(f"AWY best-parameters run complete -> {out_dir}")
        return out_dir


PLUGIN = AwyPlugin()

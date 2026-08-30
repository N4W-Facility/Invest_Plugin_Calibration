# -*- coding: utf-8 -*-
"""SWY (Seasonal Water Yield) calibration model-plugin.

Ported from ``calibration_assistant._execute_swy_direct`` and the SWY branch of
``_run_best_params``.

Calibrated: ``Alpha`` (alpha_m), ``Beta`` (beta_i), ``Gamma`` (model arguments)
and ``Factor-Kc_m`` (multiplier on the monthly ``Kc_1``..``Kc_12`` columns).
Observed variable: ``SWY`` (mm/year). Simulated: zonal mean of
``intermediate_outputs/aet_<suffix>.tif`` over the calibration watersheds
(as in the original — note the calibration loop aggregates AET, while the final
best-run below writes the standard SWY outputs).
"""

from __future__ import annotations

import os

from ..biotable import factor_biophysical_table
from ..metrics import objective
from ..zonal import calculate_zonal_stats, ismember
from .base import IterationContext, ModelPlugin, write_iteration_eval

_PARAM_ORDER = ["Alpha", "Beta", "Gamma", "Factor-Kc_m"]


class SwyPlugin(ModelPlugin):
    name = "SWY"
    param_order = _PARAM_ORDER
    obs_column = "SWY"
    required_inputs = [
        "lulc_path", "biophysical_table_path", "eto_raster_table",
        "precip_raster_table", "rain_events_table_path", "soil_group_path",
        "dem_path", "calibration_watersheds_path", "threshold_flow_accumulation",
    ]
    biophysical_gated_columns = ["Kc_1", "Status_Cal_Kc"]

    def _args(self, ctx, tmp_bio, out_dir, aoi, alpha, beta, gamma):
        mp = ctx.model_inputs
        tfa = mp.get("threshold_flow_accumulation")
        a = {
            "lulc_raster_path":            mp["lulc_path"],
            "biophysical_table_path":      tmp_bio,
            "et0_raster_table":            mp["eto_raster_table"],
            "precip_raster_table":         mp["precip_raster_table"],
            "rain_events_table_path":      mp["rain_events_table_path"],
            "soil_group_path":             mp["soil_group_path"],
            "dem_raster_path":             mp["dem_path"],
            "aoi_path":                    aoi,
            "threshold_flow_accumulation": "%0.0f" % tfa if tfa is not None else "",
            "flow_dir_algorithm":          "D8",
            "alpha_m":                     "%.3f" % alpha,
            "beta_i":                      "%.3f" % beta,
            "gamma":                       "%.3f" % gamma,
            "monthly_alpha":               False,
            "user_defined_climate_zones":  False,
            "user_defined_local_recharge": False,
            "results_suffix":              ctx.suffix,
            "workspace_dir":               out_dir,
        }
        if mp.get("sub_watersheds_path"):
            a["sub_watersheds_path"] = mp["sub_watersheds_path"]
        return a

    def run_iteration(self, ctx: IterationContext, vector) -> float:
        from natcap.invest.seasonal_water_yield import seasonal_water_yield as _swy  # noqa: PLC0415,E501

        alpha, beta, gamma, kc_m = (float(vector[i]) for i in range(4))
        ctx.log(f"SWY  Alpha={alpha:.3f}  Beta={beta:.3f}  Gamma={gamma:.3f}  Kc_m={kc_m:.2f}")

        mp = ctx.model_inputs
        table = factor_biophysical_table(
            mp["biophysical_table_path"],
            {"Alpha": alpha, "Beta": beta, "Gamma": gamma, "Factor-Kc_m": kc_m},
            ctx.user_data)
        tmp_bio = os.path.join(ctx.tmp_dir, "SWY_biophysical.csv")
        table.to_csv(tmp_bio, index=False)

        out_dir = os.path.join(ctx.outputs_dir, "02-SWY")
        _swy.execute(self._args(ctx, tmp_bio, out_dir,
                                mp["calibration_watersheds_path"], alpha, beta, gamma))

        raster = os.path.join(out_dir, "intermediate_outputs", f"aet_{ctx.suffix}.tif")
        sim_df = calculate_zonal_stats(mp["calibration_watersheds_path"], raster,
                                       ctx.tmp_dir, Suffix="SWY")
        sim_val = sim_df["mean"].values
        I, idx = ismember(sim_df["ws_id"].values, ctx.obs_df["ws_id"].values)
        obs_val = ctx.obs_df[self.obs_column].values[idx]
        sim_val = sim_val[I]
        obj = ctx.factor_metric * objective(obs_val, sim_val, ctx.metric_name)

        write_iteration_eval(
            ctx, "SWY", f"Alpha,Beta,Gamma,Factor-Kc_m,{ctx.metric_name}",
            f"{alpha:.3f},{beta:.3f},{gamma:.3f},{kc_m:.2f},{obj:.2f}",
            obs_val, sim_val, ctx.obs_df["ws_id"].values[idx],
        )
        return obj

    def run_best(self, ctx: IterationContext, params_val: dict) -> str:
        from natcap.invest.seasonal_water_yield import seasonal_water_yield as _swy  # noqa: PLC0415,E501

        mp = ctx.model_inputs
        table = factor_biophysical_table(mp["biophysical_table_path"], params_val, ctx.user_data)
        tmp_bio = os.path.join(ctx.tmp_dir, "SWY_BioTable_best.csv")
        table.to_csv(tmp_bio, index=False)
        out_dir = os.path.join(ctx.outputs_dir, "SWY_best")
        aoi = mp.get("watersheds_path") or mp["calibration_watersheds_path"]
        _swy.execute(self._args(ctx, tmp_bio, out_dir, aoi,
                                params_val.get("Alpha", 1.0),
                                params_val.get("Beta", 1.0),
                                params_val.get("Gamma", 1.0)))
        ctx.log(f"SWY best-parameters run complete -> {out_dir}")
        return out_dir


PLUGIN = SwyPlugin()

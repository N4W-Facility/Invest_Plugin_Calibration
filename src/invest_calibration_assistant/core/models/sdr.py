# -*- coding: utf-8 -*-
"""SDR (Sediment Delivery Ratio) calibration model-plugin.

Ported verbatim (behaviour-wise) from ``calibration_assistant._execute_sdr_direct``
and the SDR branch of ``_run_best_params``. The only substantive change is that
the per-watershed simulated values are read through
``zonal.read_watershed_table`` (CSV first, vector attributes as fallback) instead
of ``simpledbf.Dbf5`` — so the pip-only ``simpledbf`` dependency is gone.
"""

from __future__ import annotations

import os

import numpy as np

from ..biotable import factor_biophysical_table
from ..metrics import objective
from ..zonal import ismember, read_watershed_table
from .base import IterationContext, ModelPlugin, append_eval_csv

_PARAM_ORDER = ["sdr_max", "Borselli-K_SDR", "IC0", "L_max", "Factor-C", "Factor-P"]


class SdrPlugin(ModelPlugin):
    name = "SDR"
    param_order = _PARAM_ORDER
    obs_column = "SDR"
    required_inputs = [
        "lulc_path", "biophysical_table_path", "dem_path",
        "erosivity_path", "erodibility_path",
        "calibration_watersheds_path", "threshold_flow_accumulation",
    ]
    biophysical_gated_columns = ["usle_c", "Status_Cal_C", "usle_p", "Status_Cal_P"]

    # ------------------------------------------------------------------
    def run_iteration(self, ctx: IterationContext, vector) -> float:
        from natcap.invest.sdr import sdr as _sdr  # noqa: PLC0415

        sdr_max, k_sdr, ic0, l_max, fc, fp = (float(vector[i]) for i in range(6))
        params = {
            "sdr_max": sdr_max, "Borselli-K_SDR": k_sdr, "IC0": ic0,
            "L_max": l_max, "Factor-C": fc, "Factor-P": fp,
        }
        ctx.log(f"SDR  sdr_max={sdr_max:.2f}  K={k_sdr:.2f}  IC0={ic0:.2f}  "
                f"L_max={l_max:.2f}  C={fc:.5f}  P={fp:.5f}")

        mp = ctx.model_inputs
        table = factor_biophysical_table(mp["biophysical_table_path"], params, ctx.user_data)
        tmp_bio = os.path.join(ctx.tmp_dir, "SDR_biophysical.csv")
        table.to_csv(tmp_bio, index=False)

        out_dir = os.path.join(ctx.outputs_dir, "03-SDR")
        suffix = ctx.suffix
        sdr_args = {
            "lulc_path":                   mp["lulc_path"],
            "biophysical_table_path":      tmp_bio,
            "dem_path":                    mp["dem_path"],
            "erosivity_path":              mp["erosivity_path"],
            "erodibility_path":            mp["erodibility_path"],
            "watersheds_path":             mp["calibration_watersheds_path"],
            "threshold_flow_accumulation": "%0.0f" % mp["threshold_flow_accumulation"],
            "sdr_max":                     "%.2f" % sdr_max,
            "ic_0_param":                  "%.2f" % ic0,
            "l_max":                       "%.2f" % l_max,
            "k_param":                     "%.2f" % k_sdr,
            "flow_dir_algorithm":          "MFD",
            "results_suffix":              suffix,
            "workspace_dir":               out_dir,
        }
        if mp.get("sub_watersheds_path"):
            sdr_args["sub_watersheds_path"] = mp["sub_watersheds_path"]

        _sdr.execute(sdr_args)

        sim_df = read_watershed_table(out_dir, f"watershed_results_sdr_{suffix}")
        sim_val = sim_df["sed_export"].values
        I, idx = ismember(sim_df["ws_id"].values, ctx.obs_df["ws_id"].values)
        obs_val = ctx.obs_df[self.obs_column].values[idx]
        sim_val = sim_val[I]
        obj = ctx.factor_metric * objective(obs_val, sim_val, ctx.metric_name)

        append_eval_csv(
            ctx.evaluations_dir, f"SDR_Metric_{suffix}.csv",
            f"sdr_max,k_param,ic_0_param,l_max,Factor-C,Factor-P,{ctx.metric_name}",
            [f"{sdr_max:.2f},{k_sdr:.2f},{ic0:.2f},{l_max:.2f},{fc:.5f},{fp:.5f},{obj:.2f}"],
        )
        append_eval_csv(ctx.evaluations_dir, f"SDR_Obs_{suffix}.csv", "Obs",
                        [f"{v:.2f}" for v in obs_val])
        append_eval_csv(ctx.evaluations_dir, f"SDR_Sim_{suffix}.csv", "Sim",
                        [f"{v:.2f}" for v in sim_val])
        # ws_id order for the Obs/Sim rows (written once) so the engine can
        # rebuild a labelled obs-vs-sim table for the best iteration.
        wsid_csv = os.path.join(ctx.evaluations_dir, f"SDR_WsId_{suffix}.csv")
        if not os.path.isfile(wsid_csv):
            append_eval_csv(ctx.evaluations_dir, f"SDR_WsId_{suffix}.csv", "ws_id",
                            [str(int(w)) for w in ctx.obs_df["ws_id"].values[idx]])
        return obj

    # ------------------------------------------------------------------
    def run_best(self, ctx: IterationContext, params_val: dict) -> str:
        from natcap.invest.sdr import sdr as _sdr  # noqa: PLC0415

        mp = ctx.model_inputs
        table = factor_biophysical_table(mp["biophysical_table_path"], params_val, ctx.user_data)
        tmp_bio = os.path.join(ctx.tmp_dir, "SDR_BioTable_best.csv")
        table.to_csv(tmp_bio, index=False)

        out_dir = os.path.join(ctx.outputs_dir, "SDR_best")
        tfa = ("%0.0f" % mp["threshold_flow_accumulation"]
               if mp.get("threshold_flow_accumulation") is not None else "")
        invest_args = {
            "lulc_path":                   mp["lulc_path"],
            "biophysical_table_path":      tmp_bio,
            "dem_path":                    mp["dem_path"],
            "erosivity_path":              mp["erosivity_path"],
            "erodibility_path":            mp["erodibility_path"],
            "watersheds_path":             mp.get("watersheds_path") or mp["calibration_watersheds_path"],
            "threshold_flow_accumulation": tfa,
            "sdr_max":                     "%.2f" % params_val.get("sdr_max", 0.8),
            "ic_0_param":                  "%.2f" % params_val.get("IC0", 0.5),
            "l_max":                       "%.2f" % params_val.get("L_max", 122.0),
            "k_param":                     "%.2f" % params_val.get("Borselli-K_SDR", 2.0),
            "flow_dir_algorithm":          "MFD",
            "results_suffix":              ctx.suffix,
            "workspace_dir":               out_dir,
        }
        if mp.get("sub_watersheds_path"):
            invest_args["sub_watersheds_path"] = mp["sub_watersheds_path"]
        _sdr.execute(invest_args)
        ctx.log(f"SDR best-parameters run complete -> {out_dir}")
        return out_dir


PLUGIN = SdrPlugin()

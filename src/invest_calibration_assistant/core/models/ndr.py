# -*- coding: utf-8 -*-
"""NDR_N / NDR_P (Nutrient Delivery Ratio) calibration model-plugins.

Ported from ``calibration_assistant._execute_ndr_direct`` and the NDR branch of
``_run_best_params``. NDR_N and NDR_P share everything except the nutrient
letter, so both are instances of :class:`NdrPlugin`.

Calibrated (N shown; P analogous): ``SubCri_Len_N`` (subsurface_critical_length_n),
``Sub_Eff_N`` (subsurface_eff_n), ``Borselli-K_NDR`` (k_param), ``Factor_Load_N``
(x ``load_n``), ``Factor_Eff_N`` (x ``eff_n``). Observed: ``NDR_N`` (kg/year).
Simulated: zonal sum of ``n_total_export_<suffix>.tif`` (``p_surface_export`` for P).
"""

from __future__ import annotations

import os

from ..biotable import factor_biophysical_table
from ..metrics import objective
from ..zonal import calculate_zonal_stats, ismember
from .base import IterationContext, ModelPlugin, write_iteration_eval


class NdrPlugin(ModelPlugin):
    def __init__(self, nutrient: str):
        n = nutrient  # "N" or "P"
        self.name = f"NDR_{n}"
        self.obs_column = f"NDR_{n}"
        self.param_order = [f"SubCri_Len_{n}", f"Sub_Eff_{n}", "Borselli-K_NDR",
                            f"Factor_Load_{n}", f"Factor_Eff_{n}"]
        self.required_inputs = [
            "lulc_path", "biophysical_table_path", "dem_path", "precipitation_path",
            "calibration_watersheds_path", "threshold_flow_accumulation",
        ]
        self.biophysical_gated_columns = [
            f"load_{n.lower()}", f"Status_Cal_Load_{n}",
            f"eff_{n.lower()}", f"Status_Cal_Eff_{n}",
        ]
        self._n = n
        self._lower = n.lower()
        self._export_raster = "n_total_export" if n == "N" else "p_surface_export"

    # ------------------------------------------------------------------
    def _args(self, ctx, tmp_bio, out_dir, watersheds, k_ndr, subcri, sub_eff):
        mp = ctx.model_inputs
        tfa = mp.get("threshold_flow_accumulation")
        is_n = self._n == "N"
        a = {
            "lulc_path":                   mp["lulc_path"],
            "biophysical_table_path":      tmp_bio,
            "dem_path":                    mp["dem_path"],
            "runoff_proxy_path":           mp["precipitation_path"],
            "watersheds_path":             watersheds,
            "threshold_flow_accumulation": "%0.0f" % tfa if tfa is not None else "",
            "k_param":                     "%.2f" % k_ndr,
            "flow_dir_algorithm":          "MFD",
            "calc_n":                      is_n,
            "calc_p":                      not is_n,
            "results_suffix":              ctx.suffix,
            "workspace_dir":               out_dir,
        }
        if is_n:
            a["subsurface_critical_length_n"] = "%.2f" % subcri
            a["subsurface_eff_n"] = "%.2f" % sub_eff
        else:
            a["subsurface_critical_length_p"] = "%.2f" % subcri
            a["subsurface_eff_p"] = "%.2f" % sub_eff
        if mp.get("sub_watersheds_path"):
            a["sub_watersheds_path"] = mp["sub_watersheds_path"]
        return a

    def _prep_table(self, ctx, params, tag):
        mp = ctx.model_inputs
        table = factor_biophysical_table(mp["biophysical_table_path"], params, ctx.user_data)
        col = f"load_type_{self._lower}"
        if col not in table.columns:
            table[col] = "measured-runoff"
        tmp_bio = os.path.join(ctx.tmp_dir, f"NDR_{self._n}_{tag}.csv")
        table.to_csv(tmp_bio, index=False)
        return tmp_bio

    # ------------------------------------------------------------------
    def run_iteration(self, ctx: IterationContext, vector) -> float:
        from natcap.invest.ndr import ndr as _ndr  # noqa: PLC0415

        subcri, sub_eff, k_ndr, load_f, eff_f = (float(vector[i]) for i in range(5))
        n = self._n
        params = {f"SubCri_Len_{n}": subcri, f"Sub_Eff_{n}": sub_eff,
                  "Borselli-K_NDR": k_ndr, f"Factor_Load_{n}": load_f,
                  f"Factor_Eff_{n}": eff_f}
        ctx.log(f"NDR_{n}  SubCri={subcri:.2f}  SubEff={sub_eff:.2f}  "
                f"K={k_ndr:.2f}  Load={load_f:.2f}  Eff={eff_f:.2f}")

        mp = ctx.model_inputs
        tmp_bio = self._prep_table(ctx, params, "biophysical")
        out_dir = os.path.join(ctx.outputs_dir, f"04-NDR_{n}")
        _ndr.execute(self._args(ctx, tmp_bio, out_dir,
                                mp["calibration_watersheds_path"], k_ndr, subcri, sub_eff))

        raster = os.path.join(out_dir, f"{self._export_raster}_{ctx.suffix}.tif")
        sim_df = calculate_zonal_stats(mp["calibration_watersheds_path"], raster,
                                       ctx.tmp_dir, Suffix=f"NDR_{n}")
        sim_val = sim_df["sum"].values
        I, idx = ismember(sim_df["ws_id"].values, ctx.obs_df["ws_id"].values)
        obs_val = ctx.obs_df[self.obs_column].values[idx]
        sim_val = sim_val[I]
        obj = ctx.factor_metric * objective(obs_val, sim_val, ctx.metric_name)

        write_iteration_eval(
            ctx, f"NDR_{n}",
            f"SubCri_Len_{n},Sub_Eff_{n},Borselli-K,Factor_Load_{n},Factor_Eff_{n},{ctx.metric_name}",
            f"{subcri:.2f},{sub_eff:.2f},{k_ndr:.2f},{load_f:.2f},{eff_f:.2f},{obj:.2f}",
            obs_val, sim_val, ctx.obs_df["ws_id"].values[idx],
        )
        return obj

    def run_best(self, ctx: IterationContext, params_val: dict) -> str:
        from natcap.invest.ndr import ndr as _ndr  # noqa: PLC0415

        n = self._n
        mp = ctx.model_inputs
        tmp_bio = self._prep_table(ctx, params_val, "BioTable_best")
        out_dir = os.path.join(ctx.outputs_dir, f"NDR_{n}_best")
        watersheds = mp.get("watersheds_path") or mp["calibration_watersheds_path"]
        _ndr.execute(self._args(
            ctx, tmp_bio, out_dir, watersheds,
            params_val.get("Borselli-K_NDR", 2.0),
            params_val.get(f"SubCri_Len_{n}", 150),
            params_val.get(f"Sub_Eff_{n}", 0.8)))
        ctx.log(f"NDR_{n} best-parameters run complete -> {out_dir}")
        return out_dir


PLUGIN_N = NdrPlugin("N")
PLUGIN_P = NdrPlugin("P")

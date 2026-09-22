# -*- coding: utf-8 -*-
"""InVEST Calibration Assistant - MODEL_SPEC

Declarative GUI/validation spec consumed by the InVEST Workbench. Split out
of ``calibration_assistant.py`` because it is purely declarative (no
calibration logic) and accounts for roughly a quarter of that module's size.
"""

from natcap.invest import gettext
from natcap.invest import spec
from natcap.invest.unit_registry import u

# ---------------------------------------------------------------------------
# Condition helpers  (kept as module constants for readability)
# ---------------------------------------------------------------------------
_AWY            = 'model_name == "AWY"'
_SWY            = 'model_name == "SWY"'
_SDR            = 'model_name == "SDR"'
_NDR_N          = 'model_name == "NDR_N"'
_NDR_P          = 'model_name == "NDR_P"'
_SWY_SDR_NDR    = 'model_name in ["SWY", "SDR", "NDR_N", "NDR_P"]'
_AWY_NDR        = 'model_name in ["AWY", "NDR_N", "NDR_P"]'
_NDR            = 'model_name in ["NDR_N", "NDR_P"]'


# ---------------------------------------------------------------------------
# MODEL SPEC
# ---------------------------------------------------------------------------
MODEL_SPEC = spec.ModelSpec(
    model_id="invest_calibration_assistant",
    model_title=gettext("InVEST Calibration Assistant"),
    # Hard-coded rather than __name__: the InVEST framework re-imports this
    # module by name (importlib.import_module(MODEL_SPEC.module_name)) to
    # find execute()/validate(), which live in calibration_assistant.py, not
    # here. Using __name__ here would point it at the wrong module.
    module_name="invest_calibration_assistant.calibration_assistant",
    userguide='https://github.com/N4W-Facility/Invest_Plugin_Calibration/blob/main/CALIBRATION_PROCESS.md',
    input_field_order=[
        ['workspace_dir'],
        ['model_name'],

        # ── Inputs shared by all models ──────────────────────────────────
        ['lulc_path'],
        ['biophysical_table_path'],
        ['calibration_watersheds_path'],
        ['watersheds_path'],
        ['awy_sub_watersheds_path'],
        ['threshold_flow_accumulation', 'project_suffix'],

        # ── Annual rasters: AWY + NDR (annual P / runoff proxy) ──────────
        ['precipitation_path'],

        # ── AWY only ─────────────────────────────────────────────────────
        ['eto_path'],

        # ── AWY only ──────────────────────────────────────────────────────
        ['depth_to_root_rest_layer_path'],
        ['pawc_path'],

        # ── SWY, SDR, NDR (DEM) ──────────────────────────────────────────
        ['dem_path'],

        # ── SWY only (soil group) ─────────────────────────────────────────
        ['soil_group_path'],

        # ── SWY only: monthly folders + rain table ────────────────────────
        ['eto_raster_table'],
        ['precip_raster_table'],
        ['rain_events_table_path'],

        # ── SDR only: erosivity + erodibility ────────────────────────────
        ['erosivity_path'],
        ['erodibility_path'],

        # ── Calibration settings (all models) ────────────────────────────
        ['parameter_search_ranges_path'],
        ['observed_data_path'],
        ['evaluation_metric', 'optimization_method'],
        ['n_simulations'],
    ],
    inputs=[

        # ------------------------------------------------------------------
        # Standard InVEST workspace / suffix
        # ------------------------------------------------------------------
        spec.WORKSPACE.model_copy(update=dict(
            about=gettext(
                'Output folder for all calibration results. '
                'Sub-folders EVALUATIONS, PARAMETERS, OUTPUTS, FIGURES '
                'and TMP are created automatically.')
        )),
        spec.NumberInput(
            id='n_workers',
            name=gettext('taskgraph n_workers'),
            about=gettext('Parallel workers (-1 = synchronous).'),
            units=None,
            required=False,
            expression='value >= -1',
            hidden=True,
        ),

        # ------------------------------------------------------------------
        # Model selection
        # ------------------------------------------------------------------
        spec.OptionStringInput(
            id='model_name',
            name=gettext('Name Of The Model To Calibrate'),
            about=gettext(
                'Select the InVEST model to calibrate. '
                'The input fields below will update accordingly.'),
            options=[
                spec.Option(key='AWY',   display_name=gettext('AWY – Annual Water Yield')),
                spec.Option(key='SWY',   display_name=gettext('SWY – Seasonal Water Yield')),
                spec.Option(key='SDR',   display_name=gettext('SDR – Sediment Delivery Ratio')),
                spec.Option(key='NDR_N', display_name=gettext('NDR_N – Nutrient Delivery Ratio (N)')),
                spec.Option(key='NDR_P', display_name=gettext('NDR_P – Nutrient Delivery Ratio (P)')),
            ],
        ),

        # ==================================================================
        # SPATIAL INPUTS – shared by all models
        # ==================================================================
        spec.SingleBandRasterInput(
            id='lulc_path',
            name=gettext('Land Use / Land Cover'),
            about=gettext(
                'LULC raster. Each code must have a corresponding row '
                'in the biophysical table.'),
            projected=True,
            units=None,
        ),
        spec.CSVInput(
            id='biophysical_table_path',
            name=gettext('Biophysical Table'),
            about=gettext(
                'CSV table mapping LULC codes to biophysical coefficients. '
                'Standard columns vary by model (kc, usle_c/usle_p, '
                'load_n/eff_n, load_p/eff_p — see InVEST documentation). '
                'Must also include one boolean "Status_Cal_*" column per '
                'calibrated parameter (1 = row calibrated, 0 = held fixed): '
                'Status_Cal_Kc (AWY/SWY), Status_Cal_C/Status_Cal_P (SDR), '
                'Status_Cal_Load_N/Status_Cal_Eff_N (NDR_N), '
                'Status_Cal_Load_P/Status_Cal_Eff_P (NDR_P). Full '
                'explanation and examples: plugin User\'s Guide, section 3.'),
            columns=[],
        ),
        spec.VectorInput(
            id='calibration_watersheds_path',
            name=gettext('Calibration Watersheds'),
            about=gettext(
                'Watershed shapefile used during calibration iterations '
                '(the sub-set of watersheds with observed data). '
                'Must contain a "ws_id" integer field.'),
            geometry_types={'POLYGON', 'MULTIPOLYGON'},
            fields=[],
            projected=True,
        ),
        spec.VectorInput(
            id='watersheds_path',
            name=gettext('Full Watersheds (Final Run)'),
            about=gettext(
                'Watershed shapefile used for the final InVEST run with the '
                'best-fit calibrated parameters. Optional: if left blank, '
                'the Calibration Watersheds shapefile is used for the final run too.'),
            geometry_types={'POLYGON', 'MULTIPOLYGON'},
            fields=[],
            projected=True,
            required=False,
        ),
        spec.VectorInput(
            id='awy_sub_watersheds_path',
            name=gettext('Sub-Watersheds (optional)'),
            about=gettext(
                'Sub-watershed shapefile. Optional for all models.'),
            geometry_types={'POLYGON', 'MULTIPOLYGON'},
            fields=[],
            projected=True,
            required=False,
        ),
        spec.NumberInput(
            id='threshold_flow_accumulation',
            name=gettext('Threshold Flow Accumulation'),
            about=gettext(
                'Number of upstream cells required to define a stream. '
                'Used for stream delineation. '
                'Required for SWY, SDR, and NDR only.'),
            units=None,
            expression='value > 0',
            required=_SWY_SDR_NDR,
            allowed=_SWY_SDR_NDR,
        ),
        spec.StringInput(
            id='project_suffix',
            name=gettext('Project Name / Suffix'),
            about=gettext(
                'Short label appended to output file names '
                '(e.g. "MyProject2025"). Optional.'),
            required=False,
            regexp='[a-zA-Z0-9_-]*',
        ),

        # ==================================================================
        # ANNUAL PRECIPITATION  –  AWY (precipitation) + NDR (runoff proxy)
        # ==================================================================
        spec.SingleBandRasterInput(
            id='precipitation_path',
            name=gettext('Annual Precipitation'),
            about=gettext(
                'Annual precipitation raster (mm/year). '
                'Used as precipitation for AWY; as runoff proxy for NDR.'),
            projected=True,
            units=u.millimeter,
            required=_AWY_NDR,
            allowed=_AWY_NDR,
        ),

        # ==================================================================
        # AWY ONLY – Annual ETP
        # ==================================================================
        spec.SingleBandRasterInput(
            id='eto_path',
            name=gettext('Reference Evapotranspiration'),
            about=gettext(
                'Annual reference evapotranspiration raster (mm/year). '
                'Required for AWY only.'),
            projected=True,
            units=u.millimeter,
            required=_AWY,
            allowed=_AWY,
        ),

        # ==================================================================
        # AWY only – Root depth and PAWC
        # ==================================================================
        spec.SingleBandRasterInput(
            id='depth_to_root_rest_layer_path',
            name=gettext('Root Restricting Layer Depth'),
            about=gettext(
                'Depth to the root restricting layer raster (mm). '
                'Required for AWY only.'),
            projected=True,
            units=u.millimeter,
            required=_AWY,
            allowed=_AWY,
        ),
        spec.SingleBandRasterInput(
            id='pawc_path',
            name=gettext('Plant Available Water Content'),
            about=gettext(
                'Plant available water content raster (fraction 0–1). '
                'Required for AWY only.'),
            projected=True,
            units=None,
            required=_AWY,
            allowed=_AWY,
        ),

        # ==================================================================
        # SWY + SDR + NDR – Digital Elevation Model
        # ==================================================================
        spec.SingleBandRasterInput(
            id='dem_path',
            name=gettext('Digital Elevation Model'),
            about=gettext(
                'Digital elevation model raster (m). '
                'Required for SWY, SDR, NDR.'),
            projected=True,
            units=u.meter,
            required=_SWY_SDR_NDR,
            allowed=_SWY_SDR_NDR,
        ),

        # ==================================================================
        # SWY only – Hydrologic Soil Group
        # ==================================================================
        spec.SingleBandRasterInput(
            id='soil_group_path',
            name=gettext('Hydrologic Soil Group'),
            about=gettext(
                'Hydrologic soil group raster. Values must be integers '
                '1–4 representing groups A, B, C, D. '
                'Required for SWY only.'),
            projected=True,
            units=None,
            required=_SWY,
            allowed=_SWY,
        ),

        # ==================================================================
        # SWY ONLY – Monthly ETP folder, Monthly P folder, Rain events table
        # ==================================================================
        spec.CSVInput(
            id='eto_raster_table',
            name=gettext('Monthly ETP Raster Table'),
            about=gettext(
                'CSV with columns "month" (1–12) and "path" mapping each '
                'month to its reference evapotranspiration raster (.tif). '
                'Required for SWY only.'),
            columns=[],
            required=_SWY,
            allowed=_SWY,
        ),
        spec.CSVInput(
            id='precip_raster_table',
            name=gettext('Monthly Precipitation Raster Table'),
            about=gettext(
                'CSV with columns "month" (1–12) and "path" mapping each '
                'month to its precipitation raster (.tif). '
                'Required for SWY only.'),
            columns=[],
            required=_SWY,
            allowed=_SWY,
        ),
        spec.CSVInput(
            id='rain_events_table_path',
            name=gettext('Rain Events Table'),
            about=gettext(
                'CSV table with the number of monthly rain events per '
                'month. Required columns: month (1–12), events. '
                'Required for SWY only.'),
            columns=[],
            required=_SWY,
            allowed=_SWY,
        ),

        # ==================================================================
        # SDR ONLY – Erosivity (R) and Erodibility (K)
        # ==================================================================
        spec.SingleBandRasterInput(
            id='erosivity_path',
            name=gettext('Rainfall Erosivity (R factor)'),
            about=gettext(
                'Rainfall erosivity raster (MJ·mm / ha·h·year). '
                'Required for SDR only.'),
            projected=True,
            units=None,
            required=_SDR,
            allowed=_SDR,
        ),
        spec.SingleBandRasterInput(
            id='erodibility_path',
            name=gettext('Soil Erodibility (K factor)'),
            about=gettext(
                'Soil erodibility raster (t·ha·h / ha·MJ·mm). '
                'Required for SDR only.'),
            projected=True,
            units=None,
            required=_SDR,
            allowed=_SDR,
        ),

        # ==================================================================
        # CALIBRATION SETTINGS – shared by all models
        # ==================================================================
        spec.CSVInput(
            id='parameter_search_ranges_path',
            name=gettext('Table Of Parameter Search Ranges'),
            about=gettext(
                'CSV file (Parameters.csv) with columns: '
                '"Params", "Model", "Min", "Max", "Value". '
                'All parameters for all models can be in one file; '
                'only the rows for the selected model are used during calibration. '
                'The "Model" column is informational (AWY / SWY / SDR / NDR). '
                'Full list of parameter names and typical ranges per model: '
                'see the plugin User\'s Guide, section 2.'),
            index_col='Params',
            columns=[
                spec.StringInput(
                    id='Params',
                    name=gettext('Params'),
                    about=gettext('Parameter name (e.g. Z, Factor-Kc, sdr_max …)'),
                ),
                spec.StringInput(
                    id='Model',
                    name=gettext('Model'),
                    about=gettext('Model this parameter belongs to (AWY / SWY / SDR / NDR)'),
                    required=False,
                ),
                spec.NumberInput(
                    id='Min',
                    name=gettext('Min'),
                    about=gettext('Lower search bound for calibration'),
                    units=None,
                ),
                spec.NumberInput(
                    id='Max',
                    name=gettext('Max'),
                    about=gettext('Upper search bound for calibration'),
                    units=None,
                ),
                spec.NumberInput(
                    id='Value',
                    name=gettext('Value'),
                    about=gettext('Best-guess / initial parameter value'),
                    units=None,
                ),
            ],
        ),
        spec.CSVInput(
            id='observed_data_path',
            name=gettext('Table Of Observed Data'),
            about=gettext(
                'CSV file (Obs_Data.csv) with one row per calibration watershed. '
                'Required columns: "ws_id" (integer watershed ID matching the '
                'shapefile), plus one column per model to calibrate: '
                '"AWY" (m³/year), "SWY" (mm/year), "SDR" (tonnes/year), '
                '"NDR_N" (kg/year), "NDR_P" (kg/year). '
                'Unused model columns are ignored. Values must be '
                'incremental (per-gauge), not cumulative, and each is an '
                'absolute annual amount, never a concentration — see the '
                'plugin User\'s Guide, sections 1.2 and 5, before building '
                'this table.'),
            index_col='ws_id',
            columns=[
                spec.IntegerInput(
                    id='ws_id',
                    name=gettext('ws_id'),
                    about=gettext('Watershed identifier — must match ws_id in the shapefile'),
                ),
                spec.NumberInput(
                    id='AWY',
                    name=gettext('AWY'),
                    about=gettext('Observed streamflow for AWY calibration (m³/year)'),
                    units=None,
                    required=False,
                ),
                spec.NumberInput(
                    id='SWY',
                    name=gettext('SWY'),
                    about=gettext('Observed streamflow for SWY calibration (mm/year)'),
                    units=None,
                    required=False,
                ),
                spec.NumberInput(
                    id='SDR',
                    name=gettext('SDR'),
                    about=gettext('Observed sediment export for SDR calibration (tonnes/year)'),
                    units=None,
                    required=False,
                ),
                spec.NumberInput(
                    id='NDR_N',
                    name=gettext('NDR_N'),
                    about=gettext('Observed nitrogen load for NDR_N calibration (kg/year)'),
                    units=None,
                    required=False,
                ),
                spec.NumberInput(
                    id='NDR_P',
                    name=gettext('NDR_P'),
                    about=gettext('Observed phosphorus load for NDR_P calibration (kg/year)'),
                    units=None,
                    required=False,
                ),
            ],
        ),
        spec.OptionStringInput(
            id='evaluation_metric',
            name=gettext('Evaluation Metric'),
            about=gettext('Objective function used to compare simulated vs observed values.'),
            options=[
                spec.Option(key='Mean Square Error (MSE)',
                            display_name=gettext('Mean Square Error (MSE)')),
                spec.Option(key='Mean Absolute Error (MAE)',
                            display_name=gettext('Mean Absolute Error (MAE)')),
                spec.Option(key='Root Mean Square Error (RMSE)',
                            display_name=gettext('Root Mean Square Error (RMSE)')),
                spec.Option(key='Relative Root Mean Squared Error (RRMSE)',
                            display_name=gettext('Relative Root Mean Squared Error (RRMSE)')),
            ],
        ),
        spec.OptionStringInput(
            id='optimization_method',
            name=gettext('Optimization Method'),
            about=gettext('Optimization algorithm used to search the parameter space.'),
            options=[
                spec.Option(key='Dynamical dimensional search (DDS)',
                            display_name=gettext('Dynamical Dimensional Search (DDS)')),
                spec.Option(key='Shuffled Complex Evolution (SCE-UA)',
                            display_name=gettext('Shuffled Complex Evolution (SCE-UA)')),
                spec.Option(key='Latin Hypercube Sampling (LHS)',
                            display_name=gettext('Latin Hypercube Sampling (LHS)')),
            ],
        ),
        spec.IntegerInput(
            id='n_simulations',
            name=gettext('Number Of Simulations'),
            about=gettext(
                'Total model evaluations during calibration. Must be >= 10. '
                'The DDS algorithm requires at least 10 iterations for its '
                'initialization phase. '
                'Larger values improve parameter estimation at the cost of '
                'computation time.'),
            expression='value >= 10',
        ),
    ],

    outputs=[
        spec.FileOutput(
            id='calibration_results',
            path='PARAMETERS',
            about=gettext('Spotpy parameter CSV files with best-fit values.'),
        ),
        spec.FileOutput(
            id='calibration_figures',
            path='FIGURES',
            about=gettext('Scatter plots comparing simulated vs observed values.'),
        ),
        spec.FileOutput(
            id='calibration_report',
            path='REPORT',
            about=gettext(
                'Self-contained HTML report summarizing the run (inputs, '
                'algorithm, parameter table, dotty plots, and how to '
                'interpret them). Opens automatically when the run finishes.'),
        ),
    ],
)

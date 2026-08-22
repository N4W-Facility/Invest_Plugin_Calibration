# InVEST Calibration Assistant

> **InVEST Workbench Plugin — v1.0.0**  
> Nature For Water Facility · The Nature Conservancy  
> Authors: Jonathan Nogales Pimentel · Carlos A. Rogéliz Prada · Miguel Angel Cañon 
> Contact: jonathan.nogales@tnc.org · carlos.rogeliz@tnc.org · miguel.canon@tnc.org  

---

## What it does

The **InVEST Calibration Assistant** is a plugin for the [InVEST Workbench](https://naturalcapitalproject.stanford.edu/software/invest) that automates the calibration of InVEST hydrological models.

Given a set of observed field measurements (streamflow, sediment, nutrients) and a search range for each model parameter, the plugin iteratively runs the selected InVEST model, evaluates how well each parameter combination reproduces the observations, and finds the best-fitting set of parameters — all from within the Workbench UI.

No scripting or external tools are required.

---

## Supported models

| Model | Full name | Calibrated parameters |
|-------|-----------|-----------------------|
| **AWY** | Annual Water Yield | `Z`, `Factor-Kc` |
| **SWY** | Seasonal Water Yield | `Alpha`, `Beta`, `Gamma`, `Factor-Kc_m` |
| **SDR** | Sediment Delivery Ratio | `sdr_max`, `Borselli-K`, `IC0`, `L_max`, `Factor-C`, `Factor-P` |
| **NDR\_N** | Nutrient Delivery Ratio – Nitrogen | `SubCri_Len_N`, `Sub_Eff_N`, `Borselli-K`, `Factor_Load_N`, `Factor_Eff_N` |
| **NDR\_P** | Nutrient Delivery Ratio – Phosphorus | `SubCri_Len_P`, `Sub_Eff_P`, `Borselli-K`, `Factor_Load_P`, `Factor_Eff_P` |

---

## Key features

- **Dynamic UI** — fields shown in the Workbench change automatically based on the selected model. Only the inputs relevant to the chosen model are displayed.
- **No extra CSV configuration file** — all model inputs are specified directly as individual fields in the Workbench.
- **Multiple optimization algorithms** — choose between DDS, LHS, or SCE-UA depending on your computational budget and calibration goal.
- **Multiple objective metrics** — MSE, RMSE, MAE, or RRMSE.
- **Automatic output organization** — results are written to clearly separated folders: parameter CSVs, calibration figures (dotty plots + Obs vs Sim scatter), and a final InVEST run with the best-fit parameters.

---

## Input files

### Parameters.csv — Parameter search ranges

Defines the minimum and maximum search range for each parameter. A single file covers all models; the plugin reads only the rows relevant to the selected model.

```csv
Params,Model,Min,Max,Value
Z,AWY,1.00,100.00,17.94
Factor-Kc,AWY,0.50,2.00,0.62
Alpha,SWY,0.083,0.083,0.912
Beta,SWY,0.00,1.00,0.977
...
```

### Obs_Data.csv — Observed data

One row per watershed, one column per model. The `ws_id` column must match the integer IDs in the calibration watershed shapefile.

```csv
ws_id,AWY,SWY,SDR,NDR_N,NDR_P
1,37843200,1100,2358.62,3500,800
2,25100000,980,1750.00,2900,650
```

| Column | Units | Description |
|--------|-------|-------------|
| `ws_id` | integer | Watershed ID (must match shapefile attribute) |
| `AWY` | m³/year | Observed annual streamflow |
| `SWY` | mm/year | Observed seasonal streamflow |
| `SDR` | tonnes/year | Observed sediment export |
| `NDR_N` | kg/year | Observed nitrogen load |
| `NDR_P` | kg/year | Observed phosphorus load |

### Biophysical table — required `Status_Cal_*` columns

The biophysical table you point the plugin to must include **extra `Status_Cal_*` columns** on top of the standard InVEST biophysical table columns. These are **not** standard InVEST fields — InVEST itself ignores them — but the calibration plugin requires them to know, row by row (LULC class by LULC class), which biophysical values are allowed to be adjusted by the calibration factor and which must stay fixed at their original value.

If a required `Status_Cal_*` column is missing for the model you're calibrating, the run fails with a `KeyError` (e.g. `KeyError: 'Status_Cal_C'`).

| Column | Required for | Gates | Behavior |
|--------|---------------|-------|----------|
| `Status_Cal_Kc` | AWY, SWY | `Kc` (AWY) / `Kc_1` … `Kc_12` (SWY) | `1` = row's Kc value is multiplied by the calibrated `Factor-Kc`; `0` = Kc kept as-is |
| `Status_Cal_C` | SDR | `usle_c` | `1` = row's C value is multiplied by the calibrated `Factor-C`; `0` = C kept as-is |
| `Status_Cal_P` | SDR | `usle_p` | `1` = row's P value is multiplied by the calibrated `Factor-P`; `0` = P kept as-is |
| `Status_Cal_Load_N` | NDR_N | `load_n` | `1` = row's N load is multiplied by the calibrated `Factor_Load_N`; `0` = kept as-is |
| `Status_Cal_Eff_N` | NDR_N | `eff_n` | `1` = row's N efficiency is multiplied by the calibrated `Factor_Eff_N`; `0` = kept as-is |
| `Status_Cal_Load_P` | NDR_P | `load_p` | `1` = row's P load is multiplied by the calibrated `Factor_Load_P`; `0` = kept as-is |
| `Status_Cal_Eff_P` | NDR_P | `eff_p` | `1` = row's P efficiency is multiplied by the calibrated `Factor_Eff_P`; `0` = kept as-is |

Only the column(s) relevant to the model you're running are required — e.g. calibrating SDR only requires `Status_Cal_C` and `Status_Cal_P`, not the NDR or Kc columns.

If you don't need to exclude specific LULC classes from calibration, the simplest fix is to add the required column(s) with the value `1` on every row.

See the [Dummy dataset](#dummy-dataset) below for a biophysical table that already includes these columns as a reference.

### Dummy dataset

A complete set of sample input files (rasters, shapefiles, biophysical table, Parameters.csv, and Obs_Data.csv) is available for testing all five models:

> **[Download dummy dataset](https://tnc.box.com/s/m3gtuoj1hw5ijf95fxh7t0saii10ksln)**

---

## Output structure

```
workspace_dir/
├── EVALUATIONS/    ← metric, observed, and simulated values per iteration (CSV)
├── PARAMETERS/     ← full Spotpy parameter log (CSV)
├── FIGURES/        ← calibration plots (dotty plots + Obs vs Sim scatter, JPG)
├── OUTPUTS/        ← InVEST results for each calibration iteration
│   └── AWY_best/   ← final run with the best-fit parameters
└── TMP/            ← temporary modified biophysical tables
```

---

## Optimization algorithms

| Algorithm | Description | Best for |
|-----------|-------------|----------|
| **DDS** – Dynamically Dimensioned Search | Explores broadly early, converges late. Maximizes coverage with few model runs. | Limited budget (< 200 runs) |
| **LHS** – Latin Hypercube Sampling | Stratified random sampling. Uniform coverage of the parameter space. | Sensitivity analysis, initial exploration |
| **SCE-UA** – Shuffled Complex Evolution | Population-based evolutionary search. Robust against local minima. | Higher budget, complex response surfaces |

---

## Installation

### Via InVEST Workbench (recommended)

This is the standard way to install the plugin for end users.

1. Open the **InVEST Workbench**.
2. In the right sidebar, click **Manage Plugins**.
3. Click **Add Plugin**.
4. In the source field, paste the URL of this GitHub repository:
   ```
   https://github.com/N4W-Facility/Invest_Plugin_Calibration.git
   ```
5. Click **Install**. The Workbench will automatically:
   - Create an isolated conda environment
   - Install all dependencies (GDAL, InVEST, spotpy, etc.)
   - Register the plugin in the model list

6. Once installed, the plugin appears as **"InVEST Calibration Assistant"** in the model list. Click it to open.

> **Note:** Installation requires an internet connection the first time. Subsequent runs
> use the cached environment and are much faster to start.

---

## Requirements

- InVEST Workbench ≥ 3.15.1
- Python ≥ 3.11
- GDAL ≥ 3.11 (installed automatically via conda-forge)
- Windows or macOS (cross-platform)

---

## How calibration works

See [CALIBRATION_PROCESS.md](CALIBRATION_PROCESS.md) for a detailed explanation of the calibration loop, how Spotpy interacts with InVEST, how to interpret dotty plots, and a glossary of terms.

---

## Changelog

| Version | Date | Notes |
|---------|------|-------|
| 0.1.0 | 2025-04 | Initial plugin — CSV-based input configuration |
| 0.1.1 | 2025-04 | AWY: individual field inputs; other models keep legacy CSV |
| 0.2.0 | 2025-04 | All models: individual field inputs; legacy CSV removed |
| 0.2.1 | 2026-04 | Spotpy interface fix; `execute()` returns file registry dict |
| 0.2.2 | 2026-04 | SWY fixes for InVEST 3.18: `aoi_path`, raster tables, `flow_dir_algorithm` |
| 0.2.3 | 2026-04 | SDR/NDR fix: `lulc_raster_path` → `lulc_path` in calibration loop and best-run |
| 0.2.4 | 2026-04 | NDR fix for InVEST 3.18: auto-inject `load_type_n`/`load_type_p = measured-runoff`; pandas Copy-on-Write fix in `Factor_BioTable` |
| 1.0.0 | 2026-04 | First stable release: all 5 models validated (AWY, SWY, SDR, NDR_N, NDR_P) |

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

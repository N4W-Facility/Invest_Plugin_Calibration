=======
# TNC InVEST Calibration Assistant

> **InVEST Workbench Plugin — v0.2.1 (pre-release)**  
> Nature For Water Facility · The Nature Conservancy  
> Authors: Jonathan Nogales Pimentel · Miguel Angel Cañon  
> Contact: jonathan.nogales@tnc.org

---

## What it does

The **TNC InVEST Calibration Assistant** is a plugin for the [InVEST Workbench](https://naturalcapitalproject.stanford.edu/software/invest) that automates the calibration of InVEST hydrological models.

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
| **NDR\_P** | Nutrient Delivery Ratio – Phosphorus | `Borselli-K`, `Factor_Load_P`, `Factor_Eff_P` |

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
2. In the left sidebar, click **Manage Plugins**.

   ![Manage Plugins](docs/img/workbench_manage_plugins.png)

3. Click **Add Plugin**.
4. In the source field, paste the URL of this GitHub repository:
   ```
   https://github.com/<org>/invest_calibration_assistant
   ```
5. Click **Install**. The Workbench will automatically:
   - Create an isolated conda environment
   - Install all dependencies (GDAL, InVEST, spotpy, etc.)
   - Register the plugin in the model list

6. Once installed, the plugin appears as **"InVEST Calibration Assistant"** in the model list. Click it to open.

> **Note:** Installation requires an internet connection the first time. Subsequent runs
> use the cached environment and are much faster to start.

---

### Via pip (development / advanced)

For developers who want to modify the plugin source:

```bash
git clone https://github.com/<org>/invest_calibration_assistant.git
cd invest_calibration_assistant
pip install -e .
```

> **Note:** Do not install `spotpy` from conda-forge. The conda-forge build includes
> MPI support (`mpi4py` → `msmpi`) which conflicts with the Workbench plugin server.
> The `pip` version (used automatically by both methods above) does not include MPI.

---

## Requirements

- InVEST Workbench ≥ 3.15.1
- Python ≥ 3.11
- GDAL ≥ 3.11 (installed automatically via conda-forge)
- Windows (required for `pywin32`; the `Spotpy_InVEST.py` engine uses win32 COM)

---

## How calibration works

See [CALIBRATION_PROCESS.md](../CALIBRATION_PROCESS.md) for a detailed explanation of the calibration loop, how Spotpy interacts with InVEST, how to interpret dotty plots, and a glossary of terms.

---

## Changelog

| Version | Date | Notes |
|---------|------|-------|
| 0.1.0 | 2025-04 | Initial plugin — CSV-based input configuration |
| 0.1.1 | 2025-04 | AWY: individual field inputs; other models keep legacy CSV |
| 0.2.0 | 2025-04 | All models: individual field inputs; legacy CSV removed |
| 0.2.1 | 2026-04 | Spotpy interface fix; `execute()` returns file registry dict |
| 0.2.2 | 2026-04 | SWY fixes for InVEST 3.18: `aoi_path`, raster tables, `flow_dir_algorithm` |

---

## License

This program is free software distributed under the **GNU General Public License v3**.  
See [http://www.gnu.org/licenses/](http://www.gnu.org/licenses/) for details.


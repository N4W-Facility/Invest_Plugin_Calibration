# Calibration Process — InVEST Calibration Assistant

**Authors:** Jonathan Nogales Pimentel · Carlos A. Rogéliz Prada · Miguel Angel Cañon  
**Organization:** Nature For Water Facility – The Nature Conservancy  
**Plugin version:** 1.0.0

---

## What is hydrological model calibration?

Calibrating a model means **adjusting its internal parameters** until the model outputs match field observations (measured streamflow, sediment loads, nutrient exports, etc.) as closely as possible.  
The input data (land use maps, precipitation rasters, etc.) are not changed — only the parameters that control how the model transforms those inputs into results.

---

## What is Spotpy?

**Spotpy** (Statistical Parameter Optimization Tool for Python) is a Python library designed specifically for calibrating environmental models.  
Given a search space (min–max range per parameter), Spotpy intelligently generates parameter combinations, runs the model with each combination, evaluates how well the result matches the observations, and records everything.

Spotpy requires three methods from the user:

| Method | What it does |
|--------|-------------|
| `simulation(vector)` | Receives a parameter vector; returns the vector for Spotpy bookkeeping |
| `evaluation()` | Returns the observed data DataFrame |
| `objectivefunction(simulation, evaluation)` | Runs InVEST, compares Sim vs Obs, returns the metric |

---

## Supported models and calibration parameters

The plugin supports five InVEST models. Each model calibrates a specific set of parameters that act as multipliers or constants applied to the biophysical table or directly to the model arguments.

### AWY – Annual Water Yield

Calculates annual water yield per watershed as a function of precipitation, evapotranspiration, and soil characteristics.

| Parameter | Type | Description | Typical range |
|-----------|------|-------------|---------------|
| `Z` | Model argument | Zhang seasonality constant | 1 – 100 |
| `Factor-Kc` | Table multiplier | Scales the `kc` column (crop coefficient) | 0.5 – 2.0 |

**Observed variable:** Annual streamflow (m³/year) — column `AWY` in `Obs_Data.csv`  
**InVEST output used:** `wyield_vol` from `watershed_results_wyield_<suffix>.csv`

---

### SWY – Seasonal Water Yield

Calculates baseflow, quickflow, and local recharge at monthly time steps.

| Parameter | Type | Description | Typical range |
|-----------|------|-------------|---------------|
| `Alpha` | Model argument | Monthly baseflow recession coefficient | 0.083 – 0.5 |
| `Beta` | Model argument | Soil water retention factor | 0.0 – 1.0 |
| `Gamma` | Model argument | Fraction of pixel recharge to stream | 0.0 – 1.0 |
| `Factor-Kc_m` | Table multiplier | Scales monthly `kc_1`…`kc_12` columns | 0.5 – 2.0 |

**Observed variable:** Annual baseflow (mm/year) — column `SWY` in `Obs_Data.csv`  
**InVEST output used:** `B_sum` from `aggregated_results_swy_<suffix>.shp`

---

### SDR – Sediment Delivery Ratio

Models erosion and sediment delivery to streams using the USLE framework and the Borselli connectivity index.

| Parameter | Type | Description | Typical range |
|-----------|------|-------------|---------------|
| `sdr_max` | Model argument | Maximum SDR value | 0.01 – 1.0 |
| `Borselli-K_SDR` | Model argument | Borselli calibration constant (k) | 0.5 – 10.0 |
| `Borselli-IC0` | Model argument | Connectivity index threshold (IC₀) | 0.01 – 2.0 |
| `L_max` | Model argument | Maximum slope length (m) | 30 – 300 |
| `Factor-C` | Table multiplier | Scales the `usle_c` column | 0.1 – 10.0 |
| `Factor-P` | Table multiplier | Scales the `usle_p` column (capped at 1.0) | 0.1 – 1.0 |

**Observed variable:** Annual sediment export (tonnes/year) — column `SDR` in `Obs_Data.csv`  
**InVEST output used:** `sed_export` from `watershed_results_sdr_<suffix>.csv`

---

### NDR_N – Nutrient Delivery Ratio (Nitrogen)

Models nitrogen loading, retention, and export to streams.

| Parameter | Type | Description | Typical range |
|-----------|------|-------------|---------------|
| `SubCri_Len_N` | Model argument | Subsurface critical flow path length N (m) | 30 – 500 |
| `Sub_Eff_N` | Model argument | Subsurface retention efficiency N | 0.0 – 0.8 |
| `Borselli-K_NDR` | Model argument | Borselli calibration constant (k) | 0.5 – 10.0 |
| `Factor_Load_N` | Table multiplier | Scales the `load_n` column | 0.5 – 2.0 |
| `Factor_Eff_N` | Table multiplier | Scales the `eff_n` column (capped at 1.0) | 0.5 – 1.25¹ |

> ¹ Upper bound depends on `max(eff_n)` in the biophysical table: `Factor_Eff_N_max = 1.0 / max(eff_n)`

**Observed variable:** Annual nitrogen export (kg/year) — column `NDR_N` in `Obs_Data.csv`  
**InVEST output used:** `n_total_export` raster, aggregated by zonal statistics

---

### NDR_P – Nutrient Delivery Ratio (Phosphorus)

Models phosphorus loading, retention, and export to streams.

| Parameter | Type | Description | Typical range |
|-----------|------|-------------|---------------|
| `Borselli-K_NDR` | Model argument | Borselli calibration constant (k) | 0.5 – 10.0 |
| `Factor_Load_P` | Table multiplier | Scales the `load_p` column | 0.5 – 2.0 |
| `Factor_Eff_P` | Table multiplier | Scales the `eff_p` column (capped at 1.0) | 0.5 – 1.49¹ |

> ¹ Upper bound depends on `max(eff_p)` in the biophysical table: `Factor_Eff_P_max = 1.0 / max(eff_p)`

**Observed variable:** Annual phosphorus export (kg/year) — column `NDR_P` in `Obs_Data.csv`  
**InVEST output used:** `p_surface_export` raster, aggregated by zonal statistics

---

## The calibration loop — step by step

```
Start
  │
  ├─ 1. Read inputs (rasters, shapefiles, CSVs)
  ├─ 2. Read parameter search ranges  (Parameters.csv)
  ├─ 3. Read observed data            (Obs_Data.csv)
  ├─ 4. Build Spotpy object           (_SpotpyPlugin)
  │
  ├─ 5. CALIBRATION LOOP  ────────────────────────────────────┐
  │      For each iteration i = 1 … N_simulations:            │
  │        a) Spotpy generates parameter vector               │
  │        b) Plugin modifies biophysical table (TMP/)        │
  │        c) Run InVEST on calibration watersheds            │
  │        d) Extract simulated values (zonal stats)          │
  │        e) Compute metric (Sim vs Obs)                     │
  │        f) Save to EVALUATIONS/                            │
  │        g) Spotpy updates best solution                   ◄┘
  │
  ├─ 6. Generate calibration plots  → FIGURES/
  │        - Obs vs Sim scatter (best run)
  │        - Dotty plots: metric vs each parameter
  │
  ├─ 7. Final run with best-fit parameters
  │        - Uses full watersheds (Full Watersheds input)
  │        - Saves results to OUTPUTS/<MODEL>_best/
  │
  └─ End
```

### One iteration in detail (example: NDR_N)

```
Spotpy vector: [SubCri=150, SubEff=0.3, K=2.5, Load=1.2, Eff=0.9]
      │
      ▼
Plugin modifies biophysical table (TMP/):
  load_n_new = load_n_original × 1.2   (rows where Status_Cal_Load_N = 1)
  eff_n_new  = eff_n_original  × 0.9   (rows where Status_Cal_Eff_N  = 1)
      │
      ▼
InVEST NDR runs with:
  subsurface_critical_length_n = 150
  subsurface_eff_n             = 0.3
  k_param                      = 2.5
  modified biophysical table
      │
      ▼
Zonal stats on n_total_export_<suffix>.tif
  → Sim = [4120 kg/yr]
  Obs   = [3500 kg/yr]   (from Obs_Data.csv)
      │
      ▼
MSE = mean((3500 - 4120)²) = 384400  → returned to Spotpy (×-1 for DDS)
```

---

## Available goodness-of-fit metrics

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **MSE** – Mean Square Error | `mean((Obs − Sim)²)` | Penalizes large errors; units are squared |
| **RMSE** – Root Mean Square Error | `√(MSE)` | Same units as data; more interpretable |
| **MAE** – Mean Absolute Error | `mean(|Obs − Sim|)` | Less sensitive to extreme values |
| **RRMSE** – Relative RMSE | `RMSE / mean(Obs)` | Dimensionless; useful across different watersheds |

> **Sign note:** DDS internally *maximizes* the objective function, so the plugin multiplies the metric by `–1` when using DDS. LHS and SCE-UA minimize directly.

---

## Available optimization algorithms

### Latin Hypercube Sampling (LHS)

Stratified random sampling. Divides each parameter dimension into `N` equal intervals and draws one sample per interval, guaranteeing full-space coverage.

- **Best for:** Sensitivity analysis, initial exploration of the parameter space.
- **Budget:** Any — results do not improve with more iterations (each run is independent).

### Dynamically Dimensioned Search (DDS)

Algorithm designed for hydrological calibration with many parameters and few evaluations. Perturbs all parameters early (exploration) and progressively fewer parameters later (exploitation around the current best).

- **Best for:** Limited computational budget (< 200 simulations).
- **Budget:** 50 – 200 simulations recommended.

### Shuffled Complex Evolution (SCE-UA)

Population-based evolutionary algorithm. Maintains multiple candidate solutions and improves them through shuffling and evolution of subgroups.

- **Best for:** Complex response surfaces, multiple local minima.
- **Budget:** 200+ simulations recommended.

---

## Output files

| Folder | Contents |
|--------|----------|
| `EVALUATIONS/` | One CSV per run type per model: `<MODEL>_Metric_<suffix>.csv` (parameters + metric per iteration), `<MODEL>_Obs_<suffix>.csv`, `<MODEL>_Sim_<suffix>.csv` |
| `PARAMETERS/` | Spotpy CSV log with all sampled parameter vectors and objective function values |
| `FIGURES/` | `.jpg` with dotty plots (metric vs each parameter) and Obs vs Sim scatter for the best run |
| `OUTPUTS/<MODEL>_best/` | Full InVEST output for the best-fit parameter set, run on the complete watershed |
| `TMP/` | Temporary modified biophysical tables generated each iteration |

---

## Interpreting dotty plots

Dotty plots show the metric value (Y axis) for each parameter value sampled (X axis).

- **Sensitive parameter:** Cloud has a clear U-shape (or inverted U for DDS) — the model responds to this parameter.
- **Insensitive parameter:** Horizontal band — the model output is independent of this parameter.
- **Well-identified parameter:** Narrow, clear minimum — a single optimal value exists.
- **Equifinality:** Wide or flat minimum — many parameter values produce equally good fits.

```
Metric
  │         ●  ●
  │       ●      ●
  │     ●          ●         ← Sensitive, well-identified
  │   ●              ●
  └────────────────────── Z

Metric
  │  ● ● ● ● ● ● ● ● ● ●   ← Insensitive parameter
  └────────────────────── Factor-Kc
```

---

## Important notes on parameter bounds

Factor parameters multiply the original biophysical table values. The maximum factor must not push any value beyond the range accepted by InVEST:

| Column | Valid range | Max factor |
|--------|------------|------------|
| `kc`, `kc_1`…`kc_12` | [0, 1.2] | `1.2 / max(kc)` |
| `eff_n`, `eff_p` | [0, 1] | `1.0 / max(eff_*)` |
| `usle_c`, `usle_p` | [0, 1] | `1.0 / max(usle_*)` |

For NDR models, the biophysical table must include columns `load_type_n` and `load_type_p` with values `measured-runoff` or `application-rate`. The plugin injects `measured-runoff` automatically if these columns are absent.

---

## Quick glossary

| Term | Meaning |
|------|---------|
| **Objective function** | Numerical metric quantifying error between Sim and Obs |
| **Parameter space** | Region defined by the min–max ranges of all calibration parameters |
| **Iteration / simulation** | One complete InVEST model run with a given parameter vector |
| **Equifinality** | Multiple parameter combinations producing equally good results |
| **Dotty plot** | Scatter of metric vs one parameter; standard calibration diagnostic |
| **Factor-Kc** | Multiplier on the `kc` column to scale evapotranspiration |
| **Z (AWY)** | Zhang seasonality constant controlling rainfall–runoff partitioning |
| **measured-runoff** | `load_type` value: `load_n`/`load_p` are measured export values |
| **application-rate** | `load_type` value: `load_n`/`load_p` are fertilizer input rates |
| **Status_Cal_*** | Biophysical table column: 1 = row is modified during calibration, 0 = row kept fixed |

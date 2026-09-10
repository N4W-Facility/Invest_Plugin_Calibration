# Calibration Process — InVEST Calibration Assistant

**Authors:** Jonathan Nogales Pimentel · Carlos A. Rogéliz Prada · Miguel Angel Cañon
**Organization:** Nature For Water Facility – The Nature Conservancy
**Plugin version:** 1.0.0

---

## Contents

1. [Calibration as a parameter-estimation problem](#1-calibration-as-a-parameter-estimation-problem)
2. [Supported models and calibrated parameters](#2-supported-models-and-calibrated-parameters)
3. [The `Status_Cal_*` indicator mechanism](#3-the-status_cal_-indicator-mechanism)
4. [Bound enforcement and physical admissibility](#4-bound-enforcement-and-physical-admissibility)
5. [Multi-gauge control points under a steady-state formulation](#5-multi-gauge-control-points-under-a-steady-state-formulation)
6. [Aggregation of the multi-point objective](#6-aggregation-of-the-multi-point-objective)
7. [The calibration loop, step by step](#7-the-calibration-loop-step-by-step)
8. [Goodness-of-fit metrics](#8-goodness-of-fit-metrics)
9. [Optimization algorithms](#9-optimization-algorithms)
10. [Interpreting dotty plots](#10-interpreting-dotty-plots)
11. [Pre-flight checklist / diagnosing failures](#11-pre-flight-checklist--diagnosing-failures)
12. [Visual reference log (placeholder)](#12-visual-reference-log-placeholder)
13. [Glossary](#13-glossary)

---

## 1. Calibration as a parameter-estimation problem

### 1.1 Theoretical basis

Formally, InVEST acts as a forward model `M(θ)` that maps a parameter vector `θ` to a predicted response `M(θ)` — a water yield volume, a sediment export, a nutrient load. The forward model's structural equations are never altered during calibration: the same USLE formulation, the same Zhang curve, the same routing algorithm runs on every iteration. Calibration is the inverse problem of that fixed mapping — given a vector of field observations `y_obs`, find the parameter vector `θ*`, within an admissible region `Θ` bounded by the `Min`/`Max` search ranges declared in `Parameters.csv`, that minimizes a scalar loss `J(θ) = f(y_obs, M(θ))`. `Spotpy` performs the search over `Θ`; the input rasters, shapefiles, and the structure of the biophysical table remain fixed throughout — only `θ` moves from one evaluation to the next.

`θ` is not homogeneous. It is composed of two structurally different families of unknowns, and the distinction is load-bearing for everything that follows in this document.

**Direct model arguments.** A subset of `θ` maps one-to-one onto InVEST's own numerical arguments — `Z` for AWY, `Alpha`/`Beta`/`Gamma` for SWY, `sdr_max`/`Borselli-K`/`IC0`/`L_max` for SDR, `SubCri_Len_N`/`Sub_Eff_N` for NDR_N. Each of these is a single scalar applied uniformly across the entire watershed; there is no spatial or land-cover disaggregation at this level — the same numeric value governs every pixel.

**Table-perturbation coefficients.** A second subset of `θ` never reaches InVEST as a standalone argument. Instead, each coefficient rescales one column of the **biophysical table** before that table is written out and handed to InVEST. Biophysical tables assign one value per land-cover class — `usle_c` for SDR is the canonical example — typically transcribed from published literature or from studies conducted in a different region. Those tabulated values carry a well-documented source of error when transferred to a new catchment: the true coefficient is spatially non-stationary, and the literature value for a given cover class is systematically high or low for the specific soils, slopes, and management practices of the study area.

Re-estimating every row of the biophysical table independently, as an unrestricted per-class inverse problem, is statistically ill-posed here: a table with dozens of land-cover rows produces far more unknowns than the handful of gauges available to constrain them, and nothing prevents the optimizer from finding many unrelated row-by-row combinations that fit the gauges equally well while bearing no resemblance to physically consistent erosion behavior. It is also destructive of information already available: it discards the *relative ordering* between cover classes that the literature values encode reasonably well even when their absolute magnitude is biased. The plugin sidesteps both problems by collapsing the estimation to a **single multiplicative coefficient per column**, applied only to the subset of rows flagged for calibration — one unknown instead of dozens, and the relative ordering between classes is preserved by construction because every gated row is scaled by the same factor.

### 1.2 What physical quantity each model is calibrated against

Before any parameter table means anything, it must be clear exactly *what number* the plugin is trying to reproduce for each model — and, just as importantly, what that number is **not**. Every quantity involved, on both the simulated and the observed side, is an **absolute annual amount** — a volume or a mass accumulated over a year — never an instantaneous concentration or mixing ratio. This single fact governs how `Obs_Data.csv` must be built, and getting it wrong is one of the most common ways to silently corrupt a calibration.

- **AWY** is calibrated against the **mean multi-annual water yield volume** produced by the watershed — the annual water balance output of `P − AET − ΔS`, resolved through the Zhang curve (governed by `Z`). There is no "delivery ratio" concept in this model: `wyield_vol` *is* the full yield leaving the watershed, already an integrated annual volume (m³ yr⁻¹). If you have a gauge time series, the corresponding observed quantity is the multi-year mean of the annual discharge volume, not an instantaneous flow reading.

- **SDR** separates two physically distinct quantities that are easy to conflate. **Gross erosion** is the potential soil loss computed pixel-by-pixel from the USLE factors (`usle_c`, `usle_p`, rainfall erosivity, soil erodibility, slope length) — how much soil is detached upslope. The **delivery ratio** (governed by `sdr_max`, `Borselli-K`, `IC0`) is the fraction of that gross erosion that survives hillslope routing and redeposition to actually reach the stream network. `sed_export` — the value the plugin reads and compares against `Obs_Data.csv` — is *already* the delivered quantity, i.e. gross erosion multiplied by the connectivity-dependent delivery ratio, expressed as a mass per year (t yr⁻¹). The observed side must match that definition: a suspended-sediment **export** at the gauge, in mass per year — not a gross-erosion estimate from an erosion-plot study, and not an instantaneous turbidity or TSS concentration reading.

- **NDR_N / NDR_P** follow the identical logic for nutrients. A gross load is assigned per pixel (`load_n`/`load_p`, or an application rate, depending on `load_type_n`/`load_type_p`), and a retention efficiency along the surface and subsurface flow path (governed by `Sub_Eff_N`/`Sub_Eff_P`, `SubCri_Len_N`/`SubCri_Len_P`, and the Borselli connectivity constant) determines how much of that gross load is retained versus delivered. `n_total_export`/`p_surface_export` — again, what the plugin compares against `Obs_Data.csv` — are the **delivered** loads reaching the stream, in mass per year (kg yr⁻¹), not the gross load applied to the landscape and not a nutrient concentration.

**Practical consequence.** Water-quality monitoring programs frequently report concentrations (mg L⁻¹ of TSS, total N, or total P) rather than annual loads. Entering a raw concentration value into `Obs_Data.csv` is a unit and conceptual mismatch that the plugin has no way to detect — it will run the calibration anyway, silently comparing a mass-per-year simulated quantity against a mass-per-volume observed number, and the optimizer will search for whatever `θ` numerically minimizes that meaningless difference. Concentration data must first be converted to an annual export load. For a mean concentration `C` (mg L⁻¹) and a mean discharge `Q` (m³ s⁻¹) over the period of record:

```
Load (t yr⁻¹) = C (mg/L) × Q (m³/s) × 31.536
```

(`31.536` collapses the unit chain `mg/L → g/m³`, multiplication by `Q` in m³ s⁻¹ to get g s⁻¹, then `× 86,400 s/day × 365 day/yr ÷ 1,000,000 g/t`.) A flow-weighted mean load — computed from paired concentration and discharge samples rather than from separate long-term means of each — is preferable whenever the underlying sampling record supports it, since sediment and nutrient transport are strongly discharge-dependent and a simple mean-of-means can be biased low.

### 1.3 Operational mechanics

Mechanically, `θ` is assembled and consumed as follows on every Spotpy iteration:

1. `_read_param_ranges()` parses `Parameters.csv` into three dictionaries — initial value, `Min`, `Max` — keyed by parameter name.
2. `_build_spotpy_params()` wraps each entry relevant to the selected model in a `spotpy.parameter.Uniform(name, Min, Max)` object; Spotpy draws one value per parameter, per iteration, from that uniform distribution.
3. For a **direct model argument**, the sampled value is written straight into the InVEST `args` dictionary (e.g. `awy_args['seasonality_constant'] = '%.2f' % z`).
4. For a **table-perturbation coefficient**, the sampled value is passed instead to `Factor_BioTable()`, which rescales the relevant biophysical-table column on the rows where the matching `Status_Cal_*` flag equals `1`:

```python
Values = round(Table['usle_c'] * round(Params['Factor-C'], 2), 5)
Values[Values > 1] = 1
Table.loc[Table['Status_Cal_C'] == 1, 'usle_c'] = Values.loc[Table['Status_Cal_C'] == 1]
```

`Factor-C` scales every gated row proportionally, preserving the ratios between land-cover classes while correcting a systematic bias for the study area. The trade-off is explicit: this assumes the bias is *constant and multiplicative* across every gated class — a simplification, not a physical law. The same pattern implements `Factor-Kc`/`Factor-Kc_m` (AWY/SWY), `Factor-P` (SDR), and `Factor_Load_N`/`Factor_Eff_N`/`Factor_Load_P`/`Factor_Eff_P` (NDR). The rewritten table is written to a temporary file in `TMP/` and passed to InVEST as `biophysical_table_path` for that iteration only — the original file on disk is never modified.

### 1.4 Practical guidance — worked example

Consider calibrating SDR on a watershed where a sediment rating curve at the outlet gauge gives a mean concentration of `C = 45 mg/L` at a mean discharge of `Q = 8.2 m³/s`. Converting to an annual export load, per the formula in §1.2:

```
Load = 45 × 8.2 × 31.536 ≈ 11,631 t/yr
```

This is the number that belongs in the `SDR` column of `Obs_Data.csv` for that gauge's `ws_id` — **not** `45`, and not a gross-erosion figure from a separate erosion-plot or RUSLE-only study for the same watershed, which would typically be several times larger than the delivered export because it excludes the delivery ratio.

Now suppose the initial, uncalibrated run (using the literature `usle_c` values as-is, `Factor-C = 1`) produces `sed_export = 4,200 t/yr` — well below the observed `11,631 t/yr`. Raising `Factor-C` increases gross erosion for every gated cover proportionally, which raises `sed_export` after routing. A `Factor-C` search range of `0.1–10.0` (the typical range from [section 2](#2-supported-models-and-calibrated-parameters)) gives the optimizer enough headroom to reach the observed export without immediately saturating the `usle_c ≤ 1` clamp described in [section 4](#4-bound-enforcement-and-physical-admissibility) — but if the gap between simulated and observed export is very large, watch the resulting `Factor-C` dotty plot: a best-fit value sitting at or near the clamp boundary is diagnostic of `Factor-C` alone being asked to compensate for a discrepancy that may in fact require revisiting `sdr_max`, `Borselli-K`, or `IC0` (the delivery-ratio side of the model) rather than the gross-erosion side alone.

> **Visual reference — placeholder.** Side-by-side capture of a biophysical-table row before and after `Factor_BioTable()` is applied for one iteration, to make the multiplicative transformation concrete for a reader unfamiliar with the code.

---

## 2. Supported models and calibrated parameters

| Model | Full name | Direct model arguments | Table-perturbation coefficients |
|-------|-----------|--------------------------|-------------------------------------|
| **AWY** | Annual Water Yield | `Z` | `Factor-Kc` |
| **SWY** | Seasonal Water Yield | `Alpha`, `Beta`, `Gamma` | `Factor-Kc_m` |
| **SDR** | Sediment Delivery Ratio | `sdr_max`, `Borselli-K`, `IC0`, `L_max` | `Factor-C`, `Factor-P` |
| **NDR_N** | Nutrient Delivery Ratio – Nitrogen | `SubCri_Len_N`, `Sub_Eff_N`, `Borselli-K` | `Factor_Load_N`, `Factor_Eff_N` |
| **NDR_P** | Nutrient Delivery Ratio – Phosphorus | `SubCri_Len_P`, `Sub_Eff_P`, `Borselli-K` | `Factor_Load_P`, `Factor_Eff_P` |

`SubCri_Len_P`/`Sub_Eff_P` mirror `SubCri_Len_N`/`Sub_Eff_N` structurally — InVEST's subsurface critical flow-path length and subsurface retention efficiency, applied to the phosphorus branch of NDR. A prior implementation defect fed these two arguments from `Factor_Load_P`/`Factor_Eff_P` (the biophysical-table coefficients) instead of their own dedicated parameters; this has been corrected. Results from a calibration run predating that fix used the wrong physical quantities for these two arguments and should be discarded.

| Parameter | Description | Typical range |
|-----------|-------------|----------------|
| `Z` | Zhang seasonality constant | 1 – 100 |
| `Factor-Kc` | Scales the `kc` column | 0.5 – 2.0 |
| `Alpha` | Monthly baseflow recession coefficient | 0.083 – 0.5 |
| `Beta` | Soil water retention factor | 0.0 – 1.0 |
| `Gamma` | Fraction of pixel recharge routed to stream | 0.0 – 1.0 |
| `Factor-Kc_m` | Scales the monthly `kc_1`…`kc_12` columns | 0.5 – 2.0 |
| `sdr_max` | Maximum sediment delivery ratio | 0.01 – 1.0 |
| `Borselli-K` (SDR) | Borselli connectivity constant | 0.5 – 10.0 |
| `IC0` | Connectivity-index threshold | 0.01 – 2.0 |
| `L_max` | Maximum hillslope length (m) | 30 – 300 |
| `Factor-C` | Scales the `usle_c` column | 0.1 – 10.0 |
| `Factor-P` | Scales the `usle_p` column (capped at 1.0) | 0.1 – 1.0 |
| `SubCri_Len_N` | Subsurface critical flow-path length, N (m) | 30 – 500 |
| `Sub_Eff_N` | Subsurface retention efficiency, N | 0.0 – 0.8 |
| `Borselli-K` (NDR) | Borselli connectivity constant | 0.5 – 10.0 |
| `Factor_Load_N` | Scales the `load_n` column | 0.5 – 2.0 |
| `Factor_Eff_N` | Scales the `eff_n` column (capped at 1.0) | 0.5 – 1.25¹ |
| `SubCri_Len_P` | Subsurface critical flow-path length, P (m) | 30 – 500² |
| `Sub_Eff_P` | Subsurface retention efficiency, P | 0.0 – 0.8² |
| `Factor_Load_P` | Scales the `load_p` column | 0.5 – 2.0 |
| `Factor_Eff_P` | Scales the `eff_p` column (capped at 1.0) | 0.5 – 1.49¹ |

> ¹ The theoretical upper bound is a function of the table itself: `Factor_max = 1.0 / max(eff_n)` (or `eff_p`) — any value above that guarantees at least one row exceeds unity before the clamp described in [section 4](#4-bound-enforcement-and-physical-admissibility) intervenes.
> ² These ranges are provisional, mirroring the nitrogen parameters. Phosphorus is known to adsorb more strongly to soil particles and is generally less mobile in the subsurface than nitrate-nitrogen; treat these as a starting point to be revised against site-specific or regional literature, not as a validated default.

**Observed variable and InVEST output consumed, per model:**

| Model | Observed column (`Obs_Data.csv`) | Units | InVEST output |
|-------|-----------------------------------|-------|------------------|
| AWY | `AWY` | m³ yr⁻¹ | `wyield_vol`, `watershed_results_wyield_<suffix>.csv` |
| SWY | `SWY` | mm yr⁻¹ | `aet_<suffix>.tif`, zonal mean over the calibration watersheds |
| SDR | `SDR` | t yr⁻¹ | `sed_export`, `watershed_results_sdr_<suffix>.dbf` |
| NDR_N | `NDR_N` | kg yr⁻¹ | `n_total_export_<suffix>.tif`, zonal sum |
| NDR_P | `NDR_P` | kg yr⁻¹ | `p_surface_export_<suffix>.tif`, zonal sum |

---

## 3. The `Status_Cal_*` indicator mechanism

### 3.1 Theoretical basis

Section 1 collapsed the per-row re-estimation of a biophysical column to a single multiplicative coefficient, on the assumption that the bias between literature and reality is roughly constant across gated rows. That assumption is strongest when the gated rows are already similar in nature, and weakest when it is applied indiscriminately across land covers with unrelated error sources — a systematic bias in a locally-derived cropland `usle_c` has no reason to share the same magnitude or even the same sign as an error in a textbook forest value. `Status_Cal_*` exists to decouple two decisions that would otherwise be conflated into one coefficient: **how much** to perturb (`Factor-C`, one continuous unknown, searched by Spotpy) and **which subset of rows** the perturbation applies to (`Status_Cal_C`, a discrete restriction chosen a priori by the analyst, not calibrated). Fixing the restriction outside the search keeps the estimation problem at exactly one continuous degree of freedom regardless of how many land-cover classes the table contains, while still letting the analyst encode prior knowledge — "this class is already well characterized locally, do not touch it" — that a single blanket coefficient cannot express on its own.

### 3.2 Operational mechanics

Every table-perturbation coefficient is gated by a companion boolean-indicator column in the biophysical table, `Status_Cal_<name>`, that restricts which rows participate in the transformation. Rows flagged `1` are rescaled by the calibrated coefficient; rows flagged `0` are excluded and retain their original tabulated value exactly, unmodified. The column is not part of InVEST's own schema — InVEST does not read it, does not validate it, and would ignore it if it were present in an ordinary InVEST run — it exists solely to parameterize this masking step inside `Factor_BioTable()`.

| Column | Required for | Restricts | Ceiling |
|--------|---------------|------------|---------|
| `Status_Cal_Kc` | AWY, SWY | `Kc` (AWY) / `Kc_1`…`Kc_12` (SWY) | ≤ 1.2 |
| `Status_Cal_C` | SDR | `usle_c` | ≤ 1 |
| `Status_Cal_P` | SDR | `usle_p` | ≤ 1 |
| `Status_Cal_Load_N` | NDR_N | `load_n` | none |
| `Status_Cal_Eff_N` | NDR_N | `eff_n` | none |
| `Status_Cal_Load_P` | NDR_P | `load_p` | none |
| `Status_Cal_Eff_P` | NDR_P | `eff_p` | none |

Only the column(s) relevant to the selected model are required — calibrating SDR requires `Status_Cal_C`/`Status_Cal_P` alone; the other four columns can be absent from the table entirely.

Omitting a required `Status_Cal_*` column is a fatal condition, not a silently-tolerated one: `Factor_BioTable()` indexes the column directly, with no default and no fallback, and the run terminates immediately with `KeyError: 'Status_Cal_C'` (or the corresponding name) before a single InVEST evaluation has run. If no covers are to be excluded, the minimal valid table sets the column to `1` on every row — the restriction mechanism is then present but inactive.

### 3.3 Practical guidance

The indicator supports three distinct restriction regimes, selectable purely by how the column is populated, with no change to the underlying code or to `Parameters.csv`:

- **Unrestricted** — `1` on every row: the coefficient rescales the whole table uniformly. Appropriate when there is no specific reason to trust some covers more than others.
- **Partial restriction** — `1` on the subset of covers judged less reliable, `0` on covers considered already well characterized for the study area, which are then held fixed at their literature value irrespective of the sampled coefficient.
- **Point restriction** — `1` on exactly one row, isolating the correction to a single land-cover class suspected of driving the observed mismatch.

A concrete partial-restriction scenario, for a table with four land-cover classes calibrating SDR's `Factor-C`:

| `lucode` | Land cover | `usle_c` (literature) | `Status_Cal_C` | Rationale |
|----------|------------|--------------------------|------------------|-----------|
| 1 | Primary forest | 0.003 | `0` | Well-constrained regionally; low erosion, low leverage on the calibration signal |
| 2 | Secondary forest / shrubland | 0.05 | `0` | Same reasoning as class 1 |
| 3 | Pasture | 0.15 | `1` | Locally managed grazing intensity not reflected in the generic literature value |
| 4 | Row-crop agriculture | 0.35 | `1` | Tillage practice in the study area diverges from the source study's assumptions |

With this table, a sampled `Factor-C = 1.8` leaves classes 1 and 2 at `0.003` and `0.05` exactly, while classes 3 and 4 become `0.15 × 1.8 = 0.27` and `0.35 × 1.8 = 0.63` respectively — both still comfortably under the `usle_c ≤ 1` clamp from [section 4](#4-bound-enforcement-and-physical-admissibility). Forest and shrubland stay anchored to values the analyst already trusts; only the two covers suspected of carrying the bias move.

> **Visual reference — placeholder.** Screenshot of a biophysical table with a mixed `0`/`1` `Status_Cal_*` column, annotated to show which rows are perturbed and which are held fixed.

---

## 4. Bound enforcement and physical admissibility

### 4.1 Theoretical basis

`Min`/`Max` in `Parameters.csv` define the **search space** — the region Spotpy is permitted to sample `θ` from. They say nothing about whether every value inside that box, once run through the nonlinear chain of multiplication, clamping, and InVEST's own internal equations, remains a physically admissible input at every downstream step. A uniform prior over a wide `Factor-C` range and a hard post-hoc ceiling on `usle_c` are two different mechanisms answering two different questions — "where should the optimizer look?" versus "is the transformed value itself meaningful?" — and the plugin only answers the second question for three specific columns. Everywhere else, admissibility is entirely delegated to the analyst's choice of `Min`/`Max`, which is a deliberate but easy-to-overlook asymmetry in the design.

### 4.2 Operational mechanics

**Parameters with an enforced ceiling.** Three columns are clamped after multiplication, independent of the coefficient's magnitude:

| Column | Enforced ceiling |
|--------|--------------------|
| `Kc`, `Kc_1`…`Kc_12` | any value ≥ 1.2 is set to exactly 1.2 |
| `usle_c` | any value > 1 is set to exactly 1 |
| `usle_p` | any value > 1 is set to exactly 1 |

**Parameters with no enforced bound.** The remaining four table-perturbation coefficients, and **every** direct model argument, pass through unconstrained:

| Parameter | Bound enforcement |
|-----------|----------------------|
| `load_n`, `eff_n`, `load_p`, `eff_p` | none — rounded, never clamped |
| `Z`, `Alpha`, `Beta`, `Gamma`, `sdr_max`, `Borselli-K`, `IC0`, `L_max`, `SubCri_Len_N`/`P`, `Sub_Eff_N`/`P` | none — sampled directly from `Parameters.csv` and passed to InVEST as-is |

### 4.3 Practical guidance

**Case 1 — a clamped column, pushed hard.** `usle_c = 0.30` for a given cover, `Factor-C = 1000`: the raw product is `300`, and the clamp sets it to `1`. The transformation does not raise an exception, and InVEST receives an admissible value — nothing in the run fails. What it silently discards is the inter-class variability the biophysical table was meant to encode: every row gated by `Status_Cal_C = 1` converges to the same ceiling, and the estimation problem degenerates from *"correct a systematic bias"* to *"assign a flat, saturated coefficient."* The clamp guarantees a numerically valid input to InVEST; it makes no claim about the calibration remaining meaningful. Diagnostic signature: a `Factor-C`/`Factor-P`/`Factor-Kc` dotty plot ([section 10](#10-interpreting-dotty-plots)) with its best-fit point pinned at the range boundary.

**Case 2 — an unclamped column, pushed past its physical limit.** `eff_n = 0.6`, `Factor_Eff_N = 3.0`: the code writes `eff_n = 1.8` into the table. A retention efficiency above unity has no physical interpretation — no process can retain more mass than arrives — yet nothing intercepts the value before it reaches InVEST. Depending on the InVEST version, the result is either an internal validation failure (the iteration is lost, or the whole run halts if the exception is fatal) or a completed run whose output has no physical meaning. Diagnostic signature: intermittent iteration failures logged to the console during an otherwise-running calibration, or a best-fit `Factor_Eff_N`/`Factor_Eff_P` above `1.0 / max(eff_*)` (see the footnote in [section 2](#2-supported-models-and-calibrated-parameters)).

**Case 3 — a direct model argument with an unrealistic range.** `Z` (AWY) carries no bound anywhere in the code path. If `Parameters.csv` declares `Min=1, Max=100000` rather than the admissible `1–100`, Spotpy samples values such as `54000` with the same probability as any other value in the range. Zhang's curve has no defined behavior in that regime; the run may fail outright, or return `wyield_vol` values with no hydrological interpretation. This failure mode is the hardest of the three to notice, because nothing distinguishes it from a legitimate result until the dotty plot is inspected and shows a flat or erratic response across the entire tested range.

### Operational rule

**The declared `Min`/`Max` in `Parameters.csv` is the only reliable admissibility constraint.** The three hard-coded ceilings exist to absorb small overshoots on the columns most likely to drift slightly past unity during normal exploration of a reasonable range — they are not a general-purpose validity check, and no mechanism in the plugin verifies that a declared search range is physically sensible for any parameter. Treat the "Typical range" column in [section 2](#2-supported-models-and-calibrated-parameters) as a starting point to be narrowed with site-specific knowledge before a production calibration run.

---

## 5. Multi-gauge control points under a steady-state formulation

### 5.1 Theoretical basis

InVEST's hydrological models resolve **long-term averages** — annual or seasonal totals — rather than a time-stepped hydrograph; there is no transient series against which to fit a trajectory the way a rainfall-runoff model calibrated against a daily hydrograph would. With only a steady-state output per watershed, a single gauge supplies exactly one scalar constraint per run — insufficient, in general, to uniquely identify a parameter vector `θ` with more than one free dimension. A model with two free parameters and one observation is under-determined: infinitely many `(θ_1, θ_2)` pairs can reproduce the same single observed value, which is a textbook instance of the equifinality problem introduced conceptually in [section 6](#6-aggregation-of-the-multi-point-objective) and revisited operationally in [section 10](#10-interpreting-dotty-plots). Multiple, spatially distinct gauges substitute for the temporal replication this class of model does not have: each additional *independent* control point adds one more constraint to the system, improving — though not guaranteeing — identifiability. The word *independent* is doing real work here: two gauges only add independent information if they are not simply reporting the same upstream signal twice, which is exactly why cumulative (nested) observations are inadmissible and incremental ones are required, developed next.

### 5.2 Operational mechanics

Consider a river reach instrumented with five streamflow gauges, each with an independently derived multi-year mean flow. In the InVEST framework, each gauge is represented as one `ws_id` polygon in the calibration-watersheds shapefile. Because the gauges lie on the same drainage network, their contributing areas are nested — the watershed to gauge 5 contains that of gauge 4, which contains that of gauge 3, and so on:

```
            ┌───────────────────────────────┐
            │  Watershed to Gauge 5 (outlet)  │
            │   ┌───────────────────────┐    │
            │   │  Watershed to Gauge 4  │    │
            │   │   ┌─────────────────┐  │    │
            │   │   │  ...  Gauge 1   │  │    │
            │   │   └─────────────────┘  │    │
            │   └───────────────────────┘    │
            └───────────────────────────────┘
```

The plugin requires **incremental**, not cumulative, contributing areas: each `ws_id` polygon must represent the inter-basin draining directly to that gauge, with every upstream gauge's contributing area excluded. This delineation is performed manually in a GIS prior to running the plugin, and the corresponding observed value must be adjusted symmetrically — the observed contribution of each upstream gauge is subtracted from each downstream gauge's observed total before it is entered in `Obs_Data.csv`. Entering cumulative observed values instead of incremental ones would not only violate the independence argument in §5.1, it would also bias the estimation toward whichever parameters best explain the largest, most downstream watershed, at the expense of the headwater sub-catchments — the downstream gauge's cumulative signal numerically dominates the aggregated loss described in [section 6](#6-aggregation-of-the-multi-point-objective).

**Identifier correspondence.** The `ws_id` field in `Obs_Data.csv` must correspond exactly to the `ws_id` attribute in the calibration-watersheds shapefile. A shapefile `ws_id` without a matching row in `Obs_Data.csv` is not flagged as an error: `ismember()` filters unmatched rows silently, so the run completes normally but calibrates against fewer, and less identifiable, control points than intended. Cross-checking both identifier sets before execution is not optional — see [section 11](#11-pre-flight-checklist--diagnosing-failures).

### 5.3 Practical guidance — worked example

Continuing the five-gauge AWY network, suppose field measurements give the following cumulative mean annual discharge at each gauge (largest, most downstream gauge last):

| Gauge (`ws_id`) | Cumulative area (km²) | Cumulative mean `Q` (m³/s) | Cumulative volume (m³/yr) |
|---|---|---|---|
| 1 | 120 | 1.20 | 37,843,200 |
| 2 | 210 | 2.05 | 64,657,320 |
| 3 | 340 | 3.40 | 107,222,400 |
| 4 | 505 | 4.95 | 156,110,760 |
| 5 | 690 | 6.80 | 214,444,800 |

Delineating the shapefile as five **inter-basins** (gauge 1's own contributing area; the ring between gauge 1 and gauge 2; the ring between gauge 2 and gauge 3; and so on) and subtracting cumulative discharge accordingly gives the **incremental** values that actually belong in `Obs_Data.csv`:

| `ws_id` | Incremental volume (m³/yr) | Derivation |
|---|---|---|
| 1 | 37,843,200 | headwater gauge — no upstream subtraction |
| 2 | 26,814,120 | `64,657,320 − 37,843,200` |
| 3 | 42,565,080 | `107,222,400 − 64,657,320` |
| 4 | 48,888,360 | `156,110,760 − 107,222,400` |
| 5 | 58,334,040 | `214,444,800 − 156,110,760` |

Each row of this second table — not the first — is what `Obs_Data.csv` should contain, and each `ws_id` must correspond to the inter-basin polygon actually delineated in the shapefile, not the cumulative watershed to that gauge. Using the first table by mistake (a common shortcut when the incremental-delineation step is skipped) systematically overstates every downstream gauge's target volume, since it still carries the upstream contribution the calibration watersheds shapefile has already excluded from that `ws_id`'s drainage area.

Unit conversion used above:

```
V (m³ yr⁻¹) = Q (m³ s⁻¹) × 86,400 s day⁻¹ × 365 day yr⁻¹
```

The same incremental-delineation requirement applies to SWY, SDR, and NDR_N/NDR_P; only the observed variable and its units differ (mm yr⁻¹, t yr⁻¹, kg yr⁻¹ respectively, per [section 1.2](#12-what-physical-quantity-each-model-is-calibrated-against)).

> **Visual reference — placeholder.** Annotated map of the nested five-gauge network above alongside its inter-basin delineation, and a side-by-side of the shapefile attribute table and `Obs_Data.csv` with matching `ws_id` values highlighted.

---

## 6. Aggregation of the multi-point objective

### 6.1 Theoretical basis

`Cal_FunObj()` evaluates the selected metric over the **full, stacked vector** of observed and simulated values across every matched gauge at once, returning one scalar. Formally, if gauge `k` contributes residual `(y_obs,k − y_sim,k)`, the loss is computed over the concatenation of all `k`, not as a weighted combination of `K` separate per-gauge losses. This has a consequence that is easy to miss: MSE, RMSE, and MAE are all computed on the **absolute** residual scale, so a gauge with a naturally larger observed magnitude contributes proportionally larger absolute errors even at the same *relative* level of misfit, and will dominate the aggregate loss. A parameter vector that fits a large downstream gauge almost exactly while performing poorly, in relative terms, at a small headwater gauge can still register as the best available aggregate fit — the optimizer has no way to "know" that the headwater signal matters as much as the large gauge's unless the metric itself is scale-aware. RRMSE, by normalizing each residual against the observed mean before aggregating, is the one metric in [section 8](#8-goodness-of-fit-metrics) that partially corrects for this; MSE/RMSE/MAE do not.

### 6.2 Operational mechanics

`ismember()` first restricts both the simulated and observed vectors to matched `ws_id` pairs only (see [section 5.2](#52-operational-mechanics)); `Cal_FunObj()` then dispatches to the corresponding `spotpy.objectivefunctions` routine (`mse`, `mae`, `rmse`, or `rrmse`) on those two aligned, filtered vectors. The result is multiplied by `FactorMetric` (`−1` under DDS, `1` otherwise — [section 8](#8-goodness-of-fit-metrics)) and returned as the single scalar Spotpy uses to rank the iteration.

### 6.3 Practical guidance

Consider two gauges calibrated jointly on SDR, with the following true and candidate-simulated sediment exports:

| Gauge | Observed (t/yr) | Simulated (t/yr) | Absolute error | Relative error |
|---|---|---|---|---|
| Large downstream gauge | 12,000 | 12,600 | 600 | 5.0% |
| Small headwater gauge | 400 | 700 | 300 | 75.0% |

The headwater gauge is off by 75% in relative terms — a poor fit by any hydrological judgment — while the large gauge is off by only 5%. Under MSE, the headwater's contribution (`300² = 90,000`) is smaller than the large gauge's (`600² = 360,000`); the aggregate metric is dominated by the large gauge, and a calibration run driven by MSE or RMSE would happily accept this candidate as a strong fit while essentially ignoring the headwater's poor performance. Under RRMSE, both residuals are normalized by their own gauge's observed mean before combining, so the headwater's 75% miss is not drowned out by the downstream gauge's small absolute error. **Practical rule:** whenever the calibration watersheds span more than roughly one order of magnitude in observed magnitude, prefer RRMSE over MSE/RMSE/MAE, and inspect the per-gauge Obs-vs-Sim scatter — not only the aggregate metric — before accepting a result.

---

## 7. The calibration loop, step by step

```
Start
  │
  ├─ 1. Read inputs (rasters, shapefiles, CSVs)
  ├─ 2. Read parameter search ranges  (Parameters.csv)
  ├─ 3. Read observed data            (Obs_Data.csv)
  ├─ 4. Build the Spotpy setup object (_SpotpyPlugin)
  │
  ├─ 5. CALIBRATION LOOP  ────────────────────────────────────┐
  │      For each iteration i = 1 … N_simulations:            │
  │        a) Spotpy proposes a parameter vector θ_i           │
  │        b) Plugin rewrites the biophysical table (TMP/)     │
  │        c) InVEST executes on the calibration watersheds    │
  │        d) Simulated values are extracted (zonal statistics)│
  │        e) The objective is computed (Sim vs Obs, all gauges)│
  │        f) The iteration is logged to EVALUATIONS/          │
  │        g) Spotpy updates the incumbent best solution       ◄┘
  │
  ├─ 6. Generate calibration diagnostics  → FIGURES/
  │        - Obs vs Sim scatter (best-fit run)
  │        - Dotty plots: objective vs each parameter
  │
  ├─ 7. Final run with θ*
  │        - Uses the best-fit vector actually recovered in step 6
  │        - Uses the full watersheds (not the calibration subset)
  │        - Writes results to OUTPUTS/<MODEL>_best/
  │
  └─ End
```

### One iteration, worked in detail (NDR_N)

```
Spotpy vector: [SubCri=150, SubEff=0.3, K=2.5, Load=1.2, Eff=0.9]
      │
      ▼
Biophysical table rewritten (TMP/):
  load_n_new = load_n_original × 1.2   (rows where Status_Cal_Load_N = 1)
  eff_n_new  = eff_n_original  × 0.9   (rows where Status_Cal_Eff_N  = 1)
      │
      ▼
InVEST NDR executes with:
  subsurface_critical_length_n = 150
  subsurface_eff_n             = 0.3
  k_param                      = 2.5
  the rewritten biophysical table
      │
      ▼
Zonal statistics on n_total_export_<suffix>.tif
  → Sim = [4120 kg yr⁻¹]
  Obs   = [3500 kg yr⁻¹]   (Obs_Data.csv)
      │
      ▼
MSE = mean((3500 − 4120)²) = 384,400  → returned to Spotpy (×−1 under DDS)
```

> **Display note (AWY only).** The AWY calibration figure reports Observed/Simulated flow in m³ s⁻¹, while `Obs_Data.csv` and the stored objective value are in m³ yr⁻¹ — `Plot_AWY` divides by `86,400 × 365` solely to render a more legible flow-rate axis. This is a display-only rescaling; multiplying by a positive constant does not change which iteration minimizes the objective.

> **Visual reference — placeholder.** Console/log excerpt of one iteration's print output alongside the corresponding row appended to `EVALUATIONS/NDR_N_Metric_<suffix>.csv`, to make the loop's data flow legible end-to-end.

---

## 8. Goodness-of-fit metrics

| Metric | Formula | Interpretation |
|--------|---------|------------------|
| **MSE** – Mean Square Error | `mean((Obs − Sim)²)` | Penalizes large errors disproportionately; units are squared |
| **RMSE** – Root Mean Square Error | `√(MSE)` | Same units as the observed variable; directly interpretable |
| **MAE** – Mean Absolute Error | `mean(\|Obs − Sim\|)` | Less sensitive to outliers than MSE/RMSE |
| **RRMSE** – Relative RMSE | `RMSE / mean(Obs)` | Dimensionless; comparable across watersheds of different scale |

> **Sign convention.** DDS is formulated internally as a maximization algorithm, so the plugin multiplies the metric by `−1` before storing it whenever DDS is selected; LHS and SCE-UA minimize directly, so the multiplier is `1` for those.
>
> **Best-iteration selection.** Because the stored metric already carries that sign flip under DDS, recovering the best row requires undoing it (`FactorMetric × Metric`) before comparison — an unguarded `argmin` over the raw DDS-stored values would select the iteration with the *largest* true error. This was reported as [GitHub issue #2](https://github.com/N4W-Facility/Invest_Plugin_Calibration/issues/2) and is corrected in every `Plot_*` function.

---

## 9. Optimization algorithms

### Latin Hypercube Sampling (LHS)

Stratified random sampling: each parameter dimension is partitioned into `N` equal intervals, with one sample drawn per interval, guaranteeing coverage of the full parameter space.

- **Suited to:** sensitivity analysis and initial exploration of the parameter space.
- **Budget:** arbitrary — results do not improve with additional iterations, as each draw is independent of the others.

### Dynamically Dimensioned Search (DDS)

Purpose-built for calibration problems with many parameters and a constrained evaluation budget. Perturbs all dimensions of `θ` early in the search (exploration) and progressively fewer as the search advances (exploitation around the incumbent best). Requires a minimum of 10 evaluations for its initialization phase — enforced by the plugin as `n_simulations >= 10`.

- **Suited to:** limited computational budgets (< 200 simulations).
- **Recommended budget:** 50 – 200 simulations.

### Shuffled Complex Evolution (SCE-UA)

A population-based evolutionary algorithm that maintains multiple candidate solutions concurrently and improves them through shuffling and evolution of sub-populations.

- **Suited to:** complex, multi-modal response surfaces.
- **Recommended budget:** 200+ simulations.

---

## 10. Interpreting dotty plots

A dotty plot maps the objective value (Y axis) against one sampled parameter value (X axis), one point per iteration.

- **Sensitive parameter:** the point cloud traces a clear U-shape (or an inverted U, when reading DDS's internally-maximized stored value) — the model output responds appreciably to this parameter.
- **Insensitive parameter:** a horizontal band — the model output is essentially invariant to this parameter over the tested range.
- **Well-identified parameter:** a narrow, well-defined minimum — the data support a single optimal value.
- **Equifinality:** a wide or flat minimum — multiple parameter values yield statistically indistinguishable fits (compare with the multi-gauge equifinality discussed in [section 6](#6-aggregation-of-the-multi-point-objective)).

```
Objective
  │         ●  ●
  │       ●      ●
  │     ●          ●         ← Sensitive, well-identified
  │   ●              ●
  └────────────────────── Z

Objective
  │  ● ● ● ● ● ● ● ● ● ●   ← Insensitive parameter
  └────────────────────── Factor-Kc
```

A dotty plot for a table-perturbation coefficient that appears unnaturally flat, with its best-fit value pinned at the declared upper bound, is diagnostic of the ceiling described in [section 4](#4-bound-enforcement-and-physical-admissibility) rather than of true parameter insensitivity — check `Factor-C`/`Factor-P`/`Factor-Kc` against the corresponding table column's clamp before concluding the model is insensitive to that coefficient.

> **Visual reference — placeholder.** A real `Calibration_<MODEL>.jpg` figure from a completed run, annotated to identify one sensitive, one insensitive, and (if present) one clamp-degenerate dotty plot.

---

## 11. Pre-flight checklist / diagnosing failures

| Symptom | Root cause | Resolution |
|---------|------------|------------|
| `KeyError: 'Status_Cal_C'` (or `_P`, `_Load_N`, `_Eff_N`, `_Load_P`, `_Eff_P`, `_Kc`) | The biophysical table lacks the `Status_Cal_*` column required by the selected model | Add the column; set `1` on every row if no covers are to be excluded |
| A gauge is absent from the results, or the Obs-vs-Sim scatter has fewer points than expected | The shapefile `ws_id` has no matching row in `Obs_Data.csv` — `ismember()` drops the mismatch without raising an error | Verify every calibration-watershed `ws_id` has a corresponding `Obs_Data.csv` row before running |
| A coefficient's dotty plot is flat and pinned at a range boundary | The clamp on `Kc`/`usle_c`/`usle_p` is being hit (see [section 4](#4-bound-enforcement-and-physical-admissibility)) | Narrow the coefficient's `Max` so the product stays under the physical ceiling for most rows |
| Calibration completes, but the best-fit parameters are physically implausible | `load_*`/`eff_*` and every model-argument parameter are unconstrained; an overly wide search range went unchecked | Tighten `Min`/`Max` to the "Typical range" in [section 2](#2-supported-models-and-calibrated-parameters) |
| NDR run applies `load_type_n`/`load_type_p = measured-runoff` unexpectedly | The plugin auto-injects `measured-runoff` whenever that column is absent from the biophysical table, without prompting | Add `load_type_n`/`load_type_p` explicitly if `application-rate` semantics are intended |
| `n_simulations` validation error | DDS requires at least 10 evaluations for its initialization phase | Set `Number Of Simulations >= 10` |
| Sub-watersheds field left empty | Optional input for AWY/SWY (`awy_sub_watersheds_path`); consumed only when supplied | Leave blank unless sub-watershed disaggregation of the AWY/SWY output is required |

---

## 12. Visual reference log (placeholder)

The material below is deliberately unwritten — it consolidates, for future tracking, every in-context visual placeholder inserted through this document. None of this section is authored yet; it exists to be worked through in a dedicated pass with the Workbench open.

- [ ] §1 — biophysical-table row before/after `Factor_BioTable()`
- [ ] §3 — mixed `0`/`1` `Status_Cal_*` column, annotated
- [ ] §5 — nested five-gauge network map + `ws_id` correspondence between shapefile and `Obs_Data.csv`
- [ ] §7 — one iteration's console output alongside its `EVALUATIONS/` CSV row
- [ ] §10 — annotated real dotty-plot figure (sensitive / insensitive / clamp-degenerate)
- [ ] Plugin installation walkthrough in the Workbench ("Manage Plugins" → "Add Plugin")
- [ ] Dynamic input-field behavior: one before/after capture per model showing `model_name` changing the visible fields
- [ ] One populated input form per model (AWY, SWY, SDR, NDR_N, NDR_P)
- [ ] Output folder tree after a completed run (`EVALUATIONS/`, `PARAMETERS/`, `FIGURES/`, `OUTPUTS/<MODEL>_best/`, `TMP/`), one example file opened from each
- [ ] A `KeyError: 'Status_Cal_*'` failure dialog, end-to-end, tied to [section 11](#11-pre-flight-checklist--diagnosing-failures)

---

## 13. Glossary

| Term | Meaning |
|------|---------|
| **Forward model** | The InVEST model itself: maps a parameter vector to a predicted response |
| **Inverse problem** | Recovering the parameter vector that best explains the observed response — what calibration solves |
| **Direct model argument** | A calibrated value passed to InVEST as a single global scalar argument (e.g. `Z`, `Borselli-K`) |
| **Table-perturbation coefficient** | A calibrated multiplier applied to one biophysical-table column, restricted by `Status_Cal_*` (e.g. `Factor-C`) |
| **Objective function** | The scalar loss quantifying disagreement between simulated and observed values |
| **Admissible / feasible region (`Θ`)** | The parameter space bounded by the `Min`/`Max` ranges in `Parameters.csv` |
| **Iteration / evaluation** | One complete InVEST run for a single sampled parameter vector |
| **Inter-basin (incremental watershed)** | The area draining directly to one gauge, net of upstream gauges' contributing area — required in place of the cumulative watershed |
| **Equifinality** | Multiple parameter vectors (or, at the multi-gauge level, multiple per-gauge trade-offs) yielding statistically indistinguishable aggregate fits |
| **Dotty plot** | Scatter of the objective value against one parameter, across all iterations |
| **Bound enforcement / clamp** | A hard-coded ceiling applied after a table column is rescaled — present only for `Kc`/`usle_c`/`usle_p` |
| **`Status_Cal_*`** | Boolean-indicator biophysical-table column: `1` = row participates in the transformation, `0` = row held fixed |
| **`measured-runoff`** | NDR `load_type` value: `load_n`/`load_p` represent measured export values |
| **`application-rate`** | NDR `load_type` value: `load_n`/`load_p` represent fertilizer input rates |

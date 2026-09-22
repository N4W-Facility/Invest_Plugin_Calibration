# Contributing & Development History

This document traces the origin and evolution of the calibration methodology
and codebase in this repository across organizations and repositories, so
that authorship of any part of the code — and responsibility for it — can be
clearly identified and corrected if needed.

## Timeline

### 2021 — Original calibration scripts (WaterProof project)
The calibration workflow for InVEST models (built against InVEST 3.9) was
first developed as a set of standalone scripts within the WaterProof project.

- **Conceptual design:** Jonathan Nogales Pimentel and Carlos Andrés Rogéliz Prada
- **Code development:** Jonathan Nogales Pimentel
- **Published methodology:** Rogéliz, C.A., Vigerstol, K., Galindo, P.,
  Nogales, J., Raepple, J., Delgado, J., Piragauta, E., González, L. (2022).
  *WaterProof—A Web-Based System to Provide Rapid ROI Calculation and Early
  Indication of a Preferred Portfolio of Nature-Based Solutions in
  Watersheds*. Water, 14(21), 3447. https://doi.org/10.3390/w14213447
- **Original repository:** https://github.com/The-Nature-Conservancy-NASCA/InVEST-Calibration

### 2024–2025 — Standalone calibration tool
To make the calibration process easier to run across InVEST models, the
scripts were rebuilt into a dedicated, reusable tool.

- **Conceptual design:** Jonathan Nogales Pimentel and Carlos Andrés Rogéliz Prada
- **Code development:** Jonathan Nogales Pimentel
- **Repository:** https://github.com/N4W-Facility/InVEST_Automatic_Calibration_Assistant

### 2026 — InVEST Plugin (this repository)
Under a Natural Capital proposal, Miguel Angel Cañón Ramos joined the project
to convert the calibration tool into a standard InVEST plugin, restructuring
the code to the InVEST plugin architecture and creating this repository.

- **Plugin architecture / InVEST standard integration:** Miguel Angel Cañón Ramos
- **Repository:** https://github.com/N4W-Facility/Invest_Plugin_Calibration

From this point forward, all changes are tracked in this repository's git
history (see below).

## Contributors

| Name | Role | Profile |
|---|---|---|
| Jonathan Nogales Pimentel | Conceptual design (2021, 2024-25); code development (2021-2025); ongoing maintenance | https://www.linkedin.com/in/jonathan-nogales-14508916b/ |
| Carlos Andrés Rogéliz Prada | Conceptual design (2021, 2024-25) | https://www.linkedin.com/in/carlos-andr%C3%A9s-rog%C3%A9liz-prada-9b1a09127/ |
| Miguel Angel Cañón Ramos | Plugin architecture and InVEST standard integration (2026) | https://www.linkedin.com/in/miguel-angel-ca%C3%B1on-ramos-0650668a/ |

## A note on this repository's git history

This repository's history begins with an **"Initial commit" (April 2026)**
that imported the pre-existing calibration codebase (2021–2025) and
restructured it to the InVEST plugin standard. Because of this, `git blame`
on that initial commit attributes those lines to whoever performed the
import — not to the original author of that logic.

- For authorship of the core calibration methodology and algorithms
  (2021–2025), refer to the **Timeline** above, not to `git blame` on the
  initial commit.
- For all changes made from April 2026 onward, `git log` / `git blame` in
  this repository is the authoritative record.

## Tracing a specific change

- Line-by-line attribution for changes after April 2026: `git blame <file>`
  and `git log --follow <file>`.
- Origin of pre-2026 logic: see the repositories linked in the Timeline above.
- If something looks incorrect, please open an issue referencing the
  file/line/commit so it can be traced to the right author and fixed.

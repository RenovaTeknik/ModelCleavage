# Changelog

## v0.2.0 — Multiple Parts · 17 October 2026

- Accept and name sequential cuts from the remaining body, retaining stable part identities.
- Export selected accepted parts and/or the remaining body in their original assembly alignment, with per-cut settings and validation reports.
- Hide/show and separate accepted parts; undo the last cut or reset all cuts.
- Reject cuts that damage earlier sockets; disable paint regions changed by earlier cuts.
- Correct false paint-boundary gaps by retaining odd edge incidences, and preserve normal-array indexing for degenerate faces.
- Join eligible tiny painted cut fragments through bounded existing source material, retaining coverage and insertion checks and recording repair dimensions.
- Compare remaining paint against the cleaned source so microscopic cleanup does not hide whole untouched regions.
- Upgrade older worker snapshots for compatibility with the new assembly fields.
- Validate with 73 Python tests, a multi-part browser workflow, and real starter-model and private organic-model sequential-cut checks.

Sessions remain in memory. Project save/load, arbitrary earlier-cut replay and preservation of base paint in exports are still pending.

## v0.1.0 — First Cut · 16 October 2026

First published application source release.

- Painted single-mesh 3MF loading, region selection, repair review and repaired-3MF saving.
- Solid excision with matching socket, flat internal cap and full returning-feature sweep.
- Seam-anchored plug taper, internal smoothing, shared-bottom protection and body/part/shared fit allowances.
- Effective 0.05 mm minimum clearance; optional paired undercut glue recesses.
- Bounded numerical cleanup, detached-fragment filtering, cancellation and validation reports.
- Aligned multipart 3MF and precision-checked STL export, stamped with the release version.
- Collapsible Cut Check, stable viewer layout, accurate export-readiness footer and clearer connection labels.
- Bundled BasicShapes001.3mf example and portable developer setup.

Known limits and planned work are recorded in [README](README.md) and [ROADMAP](ROADMAP.md).

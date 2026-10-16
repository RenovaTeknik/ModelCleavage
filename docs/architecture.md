# Architecture — v0.1.0

The loopback HTTP service (`server.py`) serves the bundled browser interface and owns the active working model. A model ID and result ID reject stale selections and exports. The current application supports one active session and one excision result, not a persistent multi-part document.

## Source layout

- `model.py`: archive parsing, transforms, paint-tree decoding, region construction and tiny-island grouping.
- `repair.py` / `repair_export.py`: proposed topology repairs, explicit approval and writing a new repaired 3MF.
- `border_edit.py`: bounded edits of shared border vertices, preview/apply/cancel/undo.
- `interface.py`: paint boundary reconstruction, directional feature sweep and root construction.
- `seam_root.py`: drafted mating walls anchored to local three-dimensional seam heights; flat cap; outward escape envelope. Tip profiles use local-depth boundary erosion and constrained internal smoothing. Mirroring and trimming protect supported shared flat bottoms.
- `root_profile.py`: profile offsets and planar-root support.
- `engine.py`: nominal split, fit allocation, cleanup, geometry and assembly checks.
- `relief.py` / `printability.py`: bounded generated-skin relief and detached cut-fragment handling.
- `jobs.py` / `cut_worker.py`: cancellable worker processes, stage progress and result transfer.
- `exporter.py`: aligned multipart 3MF, precision-checked STL files, release metadata and validation reports.
- `web/`: Three.js viewer and local controls. `examples/`: distributable BasicShapes input. `tests/`: synthetic fixtures and regressions.

Module paths above are relative to `src/cutting_engine/`, except the explicitly named root, web, example and test paths.

## Validation boundaries

Nominal reconstruction is checked before intentional fit changes. Effective side/depth allowance is at least 0.05 mm, allocated to body, part or both. Part-side changes use a contracted mating root; surface validation separately records permitted seam-band trimming, bounded source cleanup and numerical skin relief. Missing painted interior outside those allowances blocks export.

Checks include manifold status, winding, positive-volume pieces, surface samples, overlap, nominal recombination, sampled withdrawal positions and bounded material-side probes. They are not exhaustive physical wall-thickness, strength or assembly guarantees. Numerical relief is limited to source-proven prismatic intervals. No model-name-specific cutting rules are used.

The server accepts model archives in memory and writes generated data only to local output locations. The original source file is not overwritten. Runtime environments, temporary jobs, exports and private model investigations are excluded from Git.

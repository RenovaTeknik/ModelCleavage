# Model Cleavage Roadmap

Updated **17 October 2026**. This roadmap describes the v0.2.0 release and intended next stages. It is not a release schedule; priorities can change as geometry and printing tests expose new requirements. The current release is **v0.2.0 — Multiple Parts**.

## Working foundation

- [x] Load and reconstruct painted single-mesh OrcaSlicer 3MF files.
- [x] Select individual connected painted regions in a local 3D viewer.
- [x] Review and approve supported topology repairs; save approved repairs to a new 3MF.
- [x] Excise complete solid features with a matching pocket and hidden flat mating cap.
- [x] Retain returning features such as a curled tail in the directional cutting envelope.
- [x] Provide adjustable depth, hidden-profile smoothing, taper and fit allowances.
- [x] Preserve supported shared flat bottoms when tapering plugs.
- [x] Add optional paired undercut glue-key recesses with adjustable geometry and material checks.
- [x] Group nearby tiny same-colour paint islands for selection and calculation.
- [x] Preview, apply, cancel and undo bounded whole-border smoothing on existing mesh vertices.
- [x] Repair bounded, surface-supported gaps when attachment-profile construction collapses; reject unresolved shell-like profiles.
- [x] Filter small detached cut-created body fragments by configurable width.
- [x] Run cuts in cancellable workers with stage progress.
- [x] Export aligned multipart 3MF assemblies, validation settings and precision-checked STLs.
- [x] Keep desktop viewer height stable with independently scrolling panels.

## Continuing geometry reliability and inspection

- [ ] Expand regression coverage across organic meshes, imperfect paint borders, narrow features, holes and returning geometry.
- [ ] Detect attached thin walls, fins and spurs, beyond the current detached-fragment filter.
- [ ] Show local thickness and problem locations in the viewer, with clear explanations of proposed corrections.
- [ ] Broaden boundary reconstruction and profile-validity checks so a closed mesh is never the sole evidence of a useful solid part.
- [ ] Add a non-destructive section view of plugs, pockets, glue recesses and surrounding wall structure.
- [ ] Preserve remaining original paint regions in exported base meshes.
- [ ] Improve cut performance through profiling, reusable computations and local geometry processing while retaining full-feature coverage checks.

## v0.2.0 — Multiple parts

- [x] Excise several parts within one working model.
- [x] Give parts stable identities and user-defined names.
- [x] Undo the last accepted cut.
- [ ] Reverse an arbitrary earlier cut, explicitly handling later cuts that depend on it.
- [x] Reset the model to its original project state.
- [x] Export only selected parts while retaining assembly alignment.
- [ ] Save and load local projects, including source geometry, approved repairs, edits, named parts, cut settings and reversible history.
- [x] Publish the application source, BasicShapes example and documented dependency setup.

Project persistence and section inspection are provisional v0.3.0 goals. A v1.0.0 release needs a dependable documented workflow and broader model and physical-print validation.

Stable part identities are in place. Dependency-aware replay is still needed for arbitrary earlier-cut reversal and project persistence.

## Later revisions — Interactive junction editing

- [ ] Add a local brush for selected stretches of a paint boundary.
- [ ] Add adaptive remeshing where existing triangles cannot support a smooth junction.
- [ ] Provide separate border and surface smoothing controls while keeping paint ownership and shared geometry aligned.
- [ ] Expose clear panning controls and discoverable navigation hints alongside orbit and zoom.
- [ ] Extend editing history and support standalone saving of edited meshes.

## Later revisions — Connections and manufacturing fit

- [ ] Add ball/socket connections.
- [ ] Add slide-fit connections and assembly lead-ins.
- [ ] Support configurable glue-key count, placement and distribution beyond the current single automatic pair.
- [ ] Add connector-specific clearance, minimum-material and assembly-path checks.
- [ ] Develop printer/material fit presets and calibration coupons from physical measurements.
- [ ] Validate glue-key dimensions, printability and retention with printed assemblies.

Connection strength, adhesive behaviour and practical fit need physical testing; geometric checks alone cannot establish them.

## Beyond the initial scope

- [ ] Evaluate support for multiple mesh instances and more general assembly inputs.
- [ ] Evaluate arbitrary insertion directions once profile construction and assembly validation are sufficiently robust.

The initial priority remains reliable paint-driven separation of a single mesh into printable, reassemblable parts.

See [README](README.md) for the current capabilities and limitations.

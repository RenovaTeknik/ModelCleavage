# Model Cleavage

Model Cleavage is a local web application for turning painted regions of a single-mesh OrcaSlicer 3MF into separate solid parts, with matching pockets for assembly after printing.

Instead of redrawing a model or splitting it in CAD, the user selects a particular painted area, chooses an insertion direction and a depth into the body, then previews the separated part and its matching cavity.

**Status:** working local prototype, under active development. These documents describe the current local application. Application source, dependencies and installation instructions have not yet been published in this repository.

## What works today

- **Painted 3MF inspection:** decode Orca/Prusa TriangleSelector paint subdivisions, display the coloured surface, and select connected regions independently. Supported inputs contain one mesh instance and use millimetres.
- **Repair review:** highlight problematic geometry, preview a proposed repair, and require explicit approval before applying it to the working copy. An approved repair can be saved into a new 3MF independently of cutting. Paint is retained on unchanged faces; changed faces can require colour approximation.
- **Solid excision:** form a solid removable feature and matching body pocket from the painted profile. The complete painted surface is included, including features that curl back behind the attachment plane. Hidden mating surfaces can be flat.
- **Plug shaping and fit:** adjust cut depth, hidden-profile smoothing, inward taper, per-side pocket clearance and extra pocket depth. Shared flat undersides are protected from tapering.
- **Glue-key recesses:** optionally add one aligned pair of shallow rectangular dovetail recesses in the hidden flat mating faces. Openings are narrower than their interiors so cured adhesive can form a butterfly-shaped key. Opening size, depth, undercut angle and surrounding material margin are adjustable. Placement is rejected when the requested pockets do not fit safely.
- **Junction smoothing:** preview a bounded adjustment of the selected border and nearby existing mesh vertices, compare before and after, then apply, cancel or undo. Sharp corners and flat bottoms are protected. This first editor smooths the whole selected boundary; it does not yet provide a local brush or adaptive remeshing.
- **Artifact handling:** group nearby tiny paint islands of the same colour; close tightly bounded, surface-supported boundary gaps when an attachment profile collapses; and filter small detached cut-created body strips by width. Suitable strips join the removable part rather than becoming impractical independent pieces.
- **Local preview and export:** orbit and zoom, inspect an exploded preview, cancel an active cut, and export an aligned multipart 3MF with settings and validation. Individual STLs are included when their precision checks pass. On desktop, side panels scroll independently of the viewer.

## How the engine checks its work

Checks cover closed and consistently oriented solids, retained painted-surface samples, nominal recombination, significant overlap, disconnected fragments and sampled withdrawal positions. Glue pockets also receive material-envelope and expected-volume checks. Computational tolerances are distinct from intentional fit clearances.

The local prototype currently has **51 passing geometry tests**, with browser checks for major interaction and export flows. These checks do not certify every mesh or guarantee printability, manufacturing fit or adhesive strength. Failed checks block export; the user should still inspect the part, pocket and assembly direction.

## Current boundaries

- One excision per export; persistent projects and multiple named cuts are planned.
- Pull directions are limited to the six Cartesian axes.
- Exported parts have solid filament assignments. Other original paint regions on the remaining body are not yet preserved in cut exports.
- Tiny-island grouping changes selection ownership, not the underlying paint. Border editing remains constrained by existing triangle layout.
- The minimum-width filter handles detached cut fragments. General detection and correction of attached thin walls or spurs remains future work.
- Glue keys are available for interface cuts; ball/socket and slide-fit connectors are not implemented.
- Repair and smoothing have distinct export paths: applying smoothing invalidates repair-only archive export. Standalone smoothed-model saving is planned.

## Local by design

The application runs a Python geometry service on the loopback interface and uses a browser-based 3D viewer. With its dependencies installed locally, normal model processing does not require a cloud service. Uploaded models, calculations and exports stay on the computer. Original model files are not overwritten by repair, smoothing or cutting.

See the [roadmap](ROADMAP.md) for planned development and [LICENSE](LICENSE) for the repository licence.

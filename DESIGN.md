# blockSketch Design Notes

## What it is
Interactive viewer and editor for OpenFOAM blockMeshDict files.
Python-based: PyVista for 3D display, PyQt6 for application frame.

## Dependencies

### Required
    pip install pyvista pyvistaqt PyQt6 numpy scipy

### Optional
    pip install tetgen      # tetrahedral meshing (Meshing panel Tab 2)

pyvistaqt provides QtInteractor for embedding PyVista inside PyQt6.
scipy is required for BSpline interpolation (scipy.interpolate.BSpline).
tetgen is optional — blockSketch runs without it but the tetgen tab is
disabled with a clear install hint. meshio is NOT required; OpenFOAM
conversion uses tetgenToFoam directly.

## OpenFOAM compatibility
Tested against:
- OpenFOAM 2406 (ESI/openfoam.com) ✓
- OpenFOAM 12 (Foundation/openfoam.org) ✓

Both branches use compatible blockMeshDict and snappyHexMeshDict
formats. Other versions are likely to work but have not been tested.

## Current status
Write-back complete (2026-04-13). All six panels implemented; save/load
round-trip working. Boundary layer addition via snappyHexMesh implemented
(2026-04-14), with post-layer checkMesh, quality update, and polyMesh
backup/restore protection. Refactored into core/ / desktop/ package structure
(2026-04-17): parser, model, writer, and geometry helpers moved to core/;
desktop app and panels moved to desktop/. Two-way vertex selection implemented
(2026-04-21): right-click vertex in 3D view selects row in Vertices panel and
populates edit fields. Two-way block selection implemented (2026-04-21):
right-click block label in 3D view switches to Blocks panel and expands the
selected block. Bounding box coordinate display and scale bar added (2026-04-21).
Two-way edge selection implemented (2026-04-21): right-click edge line in 3D
view switches to Edges panel and expands the selected edge. Arc origin format
(arc vStart vEnd origin (cx cy cz)) supported in parser, model, writer, and
geometry (2026-04-21). Cell zone support added (2026-04-21): Block.zone_name
parsed, written, and editable via per-block QComboBox; '+ New zone…' entry
opens QInputDialog and propagates the new name to all block dropdowns; viewport
block labels show zone name when set (e.g. 'B0 (gas)'). defaultPatch support
added (2026-04-21): parser reads defaultPatch { name …; type …; } block into
BlockMesh.default_patch_name / default_patch_type; writer emits it back; viewer
synthesises a BoundaryPatch covering all block faces not listed in any explicit
patch and displays it with its own colour/legend entry; Patches panel shows an
interactive card at the top (checkbox enables/disables, name/type editable).
mergePatchPairs support added (2026-04-21): parsed into
BlockMesh.merge_patch_pairs; written back as mergePatchPairs ( (p1 p2) … );
Patches panel shows a MERGE PATCH PAIRS card at the bottom with per-row combos
and delete buttons. Topology validator checks 4–5 (crossed edges, degenerate
blocks) implemented (2026-04-21). All planned features complete.
Meshing panel refactored to QTabWidget with two tabs (2026-04-24): Tab 1
retains all blockMesh/checkMesh/boundary-layer content unchanged; Tab 2
'tetgen' implements tet mesh generation via the Python tetgen API with a
QThread worker, watertight surface check (n_open_edges), and OpenFOAM
conversion via tetgenToFoam subprocess. Boundary patch preservation complete
(2026-04-25): `_build_tetgen_surface` tags patch markers as cell data;
markers passed directly to `tetgen.TetGen(pts, faces, markers)` via
`load_facet_markers`; `tet.triface_markers` used to write the `.face` file;
`_rename_tet_patches` parses tetgenToFoam stdout for
'Mapping tetgen region N to patch M' lines to build the authoritative
region→patch mapping without any file-format inference.
Tetgen integration complete and tested (2026-04-27): curved edge tessellation
gaps resolved by tessellating all quad faces consistently at n=20 and merging
with `.clean(tolerance=1e-6)`; confirmed working on cases with curved edges.
Spline and polyLine edge tessellation fixed (2026-04-27): `_get_edge_points`
now uses `pv.Spline` + control-point snap for spline/polySpline/simpleSpline
(smooth curve with exact control-point positions), and per-segment
`_interpolating_edge_sample` for polyLine (exact piecewise-linear kinks);
confirmed working on cases with spline and polyLine edges.

## Key design decisions
- Standalone Python parser (NOT using blockMesh library) for tolerance of 
  incomplete/malformed input — this is a core requirement
- Parser accumulates warnings rather than crashing
- Orphaned vertices (not referenced by any block) are valid intermediate state
- blockMesh called as external subprocess once description is complete

## Authors
- Gavin Tabor, University of Exeter — concept, domain expertise, design, testing
- Claude (Anthropic) — design consultation, architecture, code review
- Claude Code (Anthropic) — implementation

## Files

```
blockSketch/
├── main.py                        — entry point, finds blockMeshDict automatically
├── README.md                      — user-facing documentation
├── DESIGN.md                      — this file
│
├── core/                          — shared logic; no GUI dependency
│   ├── model.py                   — dataclasses: Vertex, Block, ArcEdge, SplineEdge,
│   │                                ProjectEdge, BoundaryPatch, BlockMesh
│   ├── parser.py                  — tolerant blockMeshDict parser
│   ├── writer.py                  — blockMeshDict serialiser (BlockMesh → text)
│   └── geometry.py                — edge interpolation and face tessellation:
│                                    _arc_points, _bspline_points,
│                                    _interpolating_edge_sample,
│                                    _build_edge_chain, _get_edge_points,
│                                    _face_has_curved_edge, _tessellate_quad,
│                                    build_surface_mesh
│
└── desktop/                       — PyQt6 + PyVista desktop application
    ├── app.py                     — QMainWindow: toolbar, panels, viewport,
    │                                dirty tracking, save logic
    ├── viewer.py                  — PyVista rendering; populate() / show();
    │                                imports geometry helpers from core/
    └── panels/
        ├── general.py             — scale display, display toggles, SHM geometry, screenshot
        ├── vertices.py            — vertex table, inline edit, add/delete
        ├── blocks.py              — block accordion, vertex indices, cells, grading
        ├── edges.py               — edge accordion, type-switching control points
        ├── patches.py             — patch accordion, face list
        └── meshing.py             — blockMesh + checkMesh subprocess, quality metrics,
                                     boundary layers
```

## UI design
Six-panel QStackedWidget layout:
- Top button bar: General | Vertices | Blocks | Edges | Patches | Meshing
- Top right: Save ▾ QToolButton (InstantPopup) — full-button click opens
  drop-down with Save (Ctrl+S), Save As… (Ctrl+Shift+S), Save and Exit
  (Ctrl+Q), Exit without saving
- Left side panel switches content based on active button
- Right side: PyVista QtInteractor viewport
- Bottom: topology validator status bar (green/amber/red)
- Window title shows case directory name (two levels above blockMeshDict,
  i.e. <case>/system/blockMeshDict → title shows <case>); prefixed with •
  when there are unsaved changes

### General panel
- Scale factor (convertToMeters / scale) — edits write back to model on commit
- Display toggles: vertex labels, block numbers, patch faces, bounding box,
  scale bar, legend
- Bounding box: drawn from vertex extents (pv.Box with explicit bounds, not
  plotter.bounds) so picking markers and the scale bar do not inflate it; when
  active, adds two legend entries showing the min and max corner coordinates in
  :.3g format: 'Bounding box' + '  (x1,y1,z1) – (x2,y2,z2)'
- Scale bar: drawn in 3D world space below the bounding box; length chosen by
  _nice_number() to be a round 1/2/5 × 10^n value ≈ 20% of the longest
  dimension; rendered as a PolyData line with end-cap ticks and a centred label
- SHM TARGET GEOMETRY section: Load geometry… button (supports STL/OBJ/VTK/PLY),
  Clear geometry button; loaded meshes persist across viewport refreshes and are
  re-added after every plotter.clear(); label shows filename (1 file) or
  'STL files loaded: N' (multiple); signals: geometry_load_requested,
  geometry_cleared
- SCREENSHOT section: 'blockSketch_screenshot.png' button (Ctrl+P) opens a
  save dialog defaulting to <case dir>/blockSketch_screenshot.png; emits
  screenshot_requested; confirmation shown in status bar

### Vertices panel
- QTableWidget: columns #, x, y, z — one row per vertex
- Clicking row selects vertex, populates edit fields below
- Edit fields for x, y, z with Update button
- Add vertex button
- Two-way link: right-click vertex in 3D view selects row in table
  and populates edit fields

### Blocks panel
- Accordion list (one collapsible item per block) — starts collapsed
- Expand state preserved across model-change rebuilds
- Each item: vertex list (8 indices), cell counts (nx ny nz), grading type + values
- Add block button — new item opens expanded
- Vertex indices field has a ⓘ button that opens a monospace QDialog showing
  the hex (a b c d e f g h) vertex ordering diagram and axis directions;
  plain QLabel tooltips are unreliable inside scroll areas in Qt — use
  clickable ⓘ + QDialog with <pre> HTML for any ASCII art help text
- Cell zone: QComboBox per block; blank = no zone; '+ New zone…' fires
  QInputDialog and propagates name to all block combos immediately; zone
  written to blockMeshDict only if non-empty
- Two-way link: right-click block label in 3D view collapses all blocks and
  expands selected block in panel

### Edges panel
- Accordion list (one collapsible item per edge) — starts collapsed
- Expand state preserved across model-change rebuilds
- Each item: type dropdown (arc/spline/polyLine/BSpline), v_start, v_end,
  type-specific fields (point for arc, control points for spline/polyLine)
- Arc items have an 'Arc defined by' dropdown: 'Point on arc' (classic midpoint
  format) or 'Circle centre' (origin format); label and tooltip update accordingly;
  is_origin flag written correctly on Apply
- Add edge button: creates a pending 'newEdge' item in the accordion but does
  NOT add it to the mesh or scene until Apply is clicked; Delete on a pending
  item discards it with no effect on the mesh
- Bug note: _on_pending_apply must NOT null self._pending_item before calling
  _rebuild_items — _rebuild_items checks the reference to remove the widget;
  pre-clearing it leaves an orphaned ghost entry with no Delete button
- Two-way link: right-click edge line in 3D view collapses all edges and
  expands the selected edge in panel

### Patches panel
- A dashed 'default patch' card is always shown at the top of the patch list,
  above a separator and the explicit patches; it does not appear in `mesh.patches`
- The card has a colored header strip (matching the explicit patch accordion style)
  containing a '☑ Default patch' checkbox; strip is teal-pastel when checked,
  grey when unchecked — making the enabled/disabled state immediately visible
- The checkbox indicator is explicitly styled: white fill + grey border when
  unchecked (so the box is always visible against any background), native
  platform rendering (tick + fill) when checked via `::indicator:unchecked` only
- Checked → name and type fields appear in the card body and are editable;
  `mesh.default_patch_name` is set from the name field
- Unchecked → body hidden entirely; `mesh.default_patch_name` cleared;
  `defaultPatch` section omitted from the written file
- Checkbox is pre-checked on load when the parsed file contained a `defaultPatch`
  block; unchecked otherwise (new meshes default to no default patch)
- Name field commits on Enter / focus-out (`editingFinished`); type combo commits
  immediately (`currentTextChanged`); both emit `patch_changed` → viewport updates
- Accordion list (one collapsible item per patch) — starts collapsed
- Expand state preserved across model-change rebuilds
- Each item: name, type dropdown (patch/wall/empty/symmetry/symmetryPlane/cyclic/wedge),
  variable-length face list with free-text entry per face, add/remove face buttons
- Add patch button
- MERGE PATCH PAIRS section below the explicit patch list: always shown; each
  row has two QComboBoxes populated from current patch names (including the
  default patch name if active) plus a × delete button; '+ Add pair' appends
  a blank row; combo changes and deletions write back to
  `mesh.merge_patch_pairs` immediately and emit `patch_changed`; only written
  to file if at least one pair exists; combos refresh via `refresh_names()`
  when the default patch name changes

### Meshing panel
The Meshing panel uses a QTabWidget with two tabs:

#### Tab 1 — blockMesh
- Run blockMesh button (QProcess, stdout streamed to log)
  — gated: disabled when topology validator reports red errors
- On successful blockMesh exit, automatically runs checkMesh and appends its
  output to the same log
- Mesh quality parsed from checkMesh output: Max aspect ratio, Max
  non-orthogonality, Max skewness — colour coded green/amber/red
  Thresholds: aspect ratio (5/20), non-ortho (70/85), skewness (4/20)
  Non-orthogonality regex matches both OpenFOAM v2406 format
  ('Mesh non-orthogonality Max: N average: N') and older '= N' form
- Boundary Layers section: shows wall patches only (patch/empty/cyclic/wedge/
  symmetry/symmetryPlane excluded); shows 'No wall patches defined' message
  when none exist; auto-refreshes when patch types change in Patches panel;
  ⓘ button replaces inline labels for section help text
- Each wall patch row: checkbox, n (layers), exp (expansion ratio)
- Run layer addition button writes system/snappyHexMeshDict and optionally
  system/meshQualityDict (written only if not already present), then runs
  snappyHexMesh -overwrite; stdout streamed to the shared log
  — gated: disabled until blockMesh + checkMesh have completed successfully,
  and during snappyHexMesh execution
- After successful snappyHexMesh exit, checkMesh is run automatically and
  its output appended to the log under a '--- checkMesh after layer addition ---'
  separator; quality metrics update to reflect the layered mesh; status bar
  shows '✓ Boundary layers added — mesh quality updated'
- Restore original mesh button (↩, outline style) appears below Run layer
  addition; enabled only when constant/polyMesh_noLayers exists; runs checkMesh
  after restore and shows '✓ Original mesh restored — mesh quality updated'

#### Tab 2 — tetgen
- Install hint shown when tetgen is not installed; Generate and Write
  buttons disabled with `pip install tetgen` message
- Mesh density: four QRadioButtons (Coarse / Medium / Fine / Custom); Coarse selected by default:
    Coarse  → maxvolume = V/100
    Medium  → maxvolume = V/1000
    Fine    → maxvolume = V/10000
    Custom  → QLineEdit for direct entry
  V = (xmax−xmin)·(ymax−ymin)·(zmax−zmin) from current mesh vertices;
  a single QLineEdit always shows the maxvolume value; read-only (grey) for
  Coarse/Medium/Fine (computed from V), editable for Custom
- Advanced collapsible section (collapsed by default): minratio (default 1.5),
  mindihedral (default 20)
- Generate tet mesh button: calls _build_tetgen_surface(n_curved=20) to
  produce a triangulated, patch-marked surface, cleans the surface to merge
  coincident boundary vertices, passes points/faces/markers directly to the
  Python tetgen API, checks n_open_edges > 0 (not is_manifold — more
  informative), runs tetgen in a _TetWorker(QThread) to avoid blocking the UI
- 'Display tet mesh in viewport' QCheckBox (checked by default): when checked,
  emits tet_mesh_ready signal after generation; app.py adds the
  UnstructuredGrid to the plotter as a semi-transparent light-blue overlay
- Write to OpenFOAM button (enabled only after successful Generate):
  writes constant/tetgen/tetmesh.node, .ele, and .face from tet.node,
  tet.elem, tet.trifaces, and tet.triface_markers (returned directly by
  the Python API), runs tetgenToFoam, then renames patches in
  constant/polyMesh/boundary via _rename_tet_patches
- 'Also save tetgen files (.node, .ele, .face)' QCheckBox (unchecked by
  default): intermediate files in constant/tetgen/ deleted after conversion
  unless checked

The two tabs share the same log area (white background, monospace) and mesh
quality display at the bottom of the panel — only one meshing operation runs
at a time, so post-run output naturally belongs to whichever tab triggered it.

#### tetgenToFoam conversion
The Python tetgen API returns `tet.trifaces` and `tet.triface_markers`
directly — no `.poly` file, no subprocess, no KDTree centroid matching:
- `_write_face_file` filters `triface_markers > 0` (boundary faces only;
  interior faces are 0), writes `constant/tetgen/tetmesh.face` in standard
  tetgen format with 1-based patch markers taken directly from
  `tet.triface_markers`
- All intermediate files go to `constant/tetgen/` (created automatically)
- `tetgenToFoam -case <dir> constant/tetgen/tetmesh` converts to polyMesh
- `_rename_tet_patches(tetgen_output)` post-processes `constant/polyMesh/boundary`:
  parses the tetgenToFoam stdout for lines of the form
  `Mapping tetgen region N to patch M`; builds `patch_idx_to_patch[M] =
  mesh.patches[N-1]` (region N = marker N = 1-based index assigned in
  `_build_tetgen_surface`); renames each `patchM` to the correct name and
  restores the correct type (`wall`, `empty`, `symmetry`, etc.) — tetgenToFoam
  writes `type patch; physicalType patch;` for every patch regardless of the
  original type; regex fallback if `physicalType` is absent; logs a warning
  if no mapping lines are found in the output
- Log reports: `[✓ boundary patches preserved: name1, name2, …]`
- Intermediate .node/.ele/.face files deleted unless 'Save tetgen files' checked

#### checkMesh helper
`_run_checkMesh(context=)` is a shared helper called from three places:
- `'post_bm'`      — after blockMesh succeeds; sets _bm_success, enables layer button
- `'post_layers'`  — after snappyHexMesh succeeds; updates quality, emits layer status
- `'post_restore'` — after polyMesh restore; updates quality, emits restore status
`_on_cm_finished` branches on `_cm_context` to apply the right side-effects in each case.
`_parse_quality` scans the full log text and takes the last regex match per metric,
so post-layer values naturally overwrite pre-layer values without any special handling.

#### polyMesh backup / restore
Before the first layer addition run, `constant/polyMesh` is copied to
`constant/polyMesh_noLayers`. On subsequent runs a QMessageBox warns the user
that layers are already present, offering 'Restore and re-run' or 'Cancel';
choosing restore copies `polyMesh_noLayers` back to `polyMesh` and the existing
backup is reused. When blockMesh is re-run it deletes any stale `polyMesh_noLayers`
backup (mesh topology has changed). The restore button's enabled state is always
derived from `os.path.isdir(polyMesh_noLayers)` and refreshed via
`_update_restore_btn()` at every relevant transition.

#### snappyHexMeshDict
Hardcoded; not adapted from a tutorial template. A template-based approach was
attempted but abandoned: sHM reads the geometry section even when
`castellatedMesh false`, causing errors when the template referenced STL files
not present in the user's case. Emptying the geometry section via text
manipulation was fragile across OF versions.

The hardcoded dict (`_snappy_dict_content`) is known to work on OF 2406 ESI:
- Empty `geometry { }` block (explicit multi-line form)
- `castellatedMesh false; snap false; addLayers true;`
- Minimal but complete castellatedMeshControls and snapControls
- `addLayersControls` built from `_build_add_layers_controls(layers_block)`;
  per-patch block includes both `nSurfaceLayers` and `expansionRatio`
- `mergeTolerance 1e-6;` at top level
- `meshQualityDict` written to system/ if not already present
- OF version detected via `foamVersion` subprocess and logged
- Warning appended to meshing log on every write advising manual check on
  other OF versions

## Right-click picking
A single `enable_point_picking` callback handles all three target types.
Three setup functions are called in order from `_refresh_viewport`, each
stashing data on the plotter before `enable_vertex_picking` registers the
combined picker:

1. `enable_block_picking` — adds semi-transparent green centroid markers
   (opacity=0.15, point_size=12), stashes `plotter._block_pick`
2. `enable_edge_picking` — stashes `plotter._edge_pick` (the gold control-point
   cloud added by `populate()` with `pickable=True` is the hit target)
3. `enable_vertex_picking` — reads `_block_pick` and `_edge_pick`, then calls
   `plotter.disable_picking()` + `enable_point_picking` with a combined callback

Priority order in the right-click point picker (first match wins):
- Vertices — 5 % of bounding-box diagonal
- Block centroids — 10 % of bounding-box diagonal

Edge picking uses a separate raw VTK observer (`vtkCellPicker` on
`RightButtonPressEvent`) rather than PyVista's `enable_cell_picking`.
Reason: `enable_cell_picking` internally calls `enable_rectangle_picking`
which goes through `_validate_picker_not_in_use()` and conflicts with the
active point picker. The VTK observer bypasses this check and coexists with
the point picker — both fire on right-click independently.
Each curved edge PolyData is tagged with an `edge_index` point scalar in
`populate()` so the observer can identify which edge was hit.
The observer tag is stored on the plotter and removed before re-registering
on each viewport refresh to prevent observer stacking.

`disable_picking()` is called before `enable_point_picking` to avoid
PyVista's `PyVistaPickingError: Picking is already enabled` on viewport refresh.

## Legend
The 3D viewport legend is built explicitly using [label, color, face] triples
rather than PyVista's implicit label= mechanism, giving per-entry symbol control:
- Vertices, Edge ctrl pts → 'circle' (sphere)
- All edge types → '-' (line)
- Boundary patches → 'rectangle'
- SHM Target Geometry → grey rectangle; only appears when geometry is loaded
- Bounding box → two gray '-' entries (header + coordinate range); only present
  when Bounding box is checked
- Legend visibility toggled by the 'Legend' checkbox in the General panel
- Legend size fixed at (0.25, 0.25); dynamic sizing was abandoned because PyVista
  anchors the legend by its centre, so changing the height shifts its position
- Patch face entries always present regardless of show_patch_faces toggle
  (patch meshes added at opacity=0 when hidden, so legend entries are registered)

## Write-back (writer.py)
Serialises BlockMesh model to valid blockMeshDict text. Key details:
- Integers written as integers (not 1.0), floats with up to 10 sig figs
- Grading: handles flat scalars, single (n weight expansion) triples, and
  nested multi-grading lists — simpleGrading and edgeGrading both supported
- Edges: arc (inline point or `origin (cx cy cz)` depending on is_origin flag),
  spline/polyLine/BSpline (indented point list), project edges included
- Boundary section uses `boundary` keyword (OpenFOAM v6+ / v2406)
- defaultPatch section written after boundary if `default_patch_name` is
  non-empty; omitted otherwise (user unchecked the card)
- mergePatchPairs section written after defaultPatch if list is non-empty;
  omitted otherwise
- Backs up existing file to blockMeshDict.bak before overwriting
- Dirty tracking: window title prefixed with • ; closeEvent prompts
  Yes/No/Cancel if unsaved changes exist

## Topology validator
Runs automatically on every model change. Reports to status bar.
Colour coded: green = clean, amber = warnings, red = errors.
All five checks implemented:
1. Orphaned vertices (not referenced by any block) — amber warning
2. Out-of-range vertex indices in blocks — red error
3. Duplicate vertices (two vertices at identical coordinates) — amber warning
4. Crossed edges / inverted block — red error: computes the Jacobian at vertex 0
   from the three axis vectors (0→1, 0→3, 0→4); negative Jacobian means the
   block is inverted or vertices are swapped
5. Degenerate blocks (near-zero volume) — red error: only checked when Jacobian
   is positive (avoids double-reporting with check 4); volume compared against
   bbox_vol × 1e-10 where bbox_vol is the axis-aligned bounding box volume of
   all vertices; bbox_vol computed once outside the block loop

### Stress-testing notes
Stress testing has confirmed that orphaned vertices display correctly and are treated as a
valid intermediate state. Malformed blocks (e.g. swapped vertex indices) are displayed with
crossed edges, which makes the error immediately visually obvious. The topology validator
should highlight these cases rather than refusing to display.

## Curved edge support
All types tested and working: arc, spline, polyLine, BSpline.

### Arc edge formats
Two arc formats are supported:
- `arc vStart vEnd (px py pz)` — point on the arc (classic format); `is_origin=False`
- `arc vStart vEnd origin (cx cy cz)` — circle centre; `is_origin=True`

The `is_origin` flag is stored on `ArcEdge` and propagated through parser,
model, writer, geometry, and the Edges panel UI.  When `is_origin=True`,
`_arc_midpoint_from_origin(p0, p1, centre)` converts the centre to the arc
midpoint using Rodrigues' rotation (half the subtended angle) before passing
to `_arc_points`.  Circle-centre arcs show no gold control-point marker in the
viewport since the centre is not a meaningful visual landmark.  Both formats
round-trip correctly through the writer.
BSpline uses scipy's uniform clamped B-spline (SciPyBSpline) — degree 3 where
possible, reduced for fewer control points. End conditions are clamped so the
curve passes exactly through the start and end vertices. Intermediate control
points are approximated (not interpolated), verified by checking the curve peak
falls short of the apex control point. Rendered in purple to distinguish from
interpolating spline (green).
Boundary patch faces tessellated to follow curved edges, including BSpline.

### Edge sampling strategy in `_get_edge_points`
- **arc**: circumcircle sampling — unchanged
- **BSpline**: uniform clamped B-spline via `_bspline_points` — control points
  are NOT on the curve, so uniform parameter sampling is correct
- **polyLine**: `_interpolating_edge_sample(chain, n)` — piecewise linear;
  distributes `max(2, n // segments)` points per segment between consecutive
  control points, which are always exact segment endpoints.
- **spline, polySpline, simpleSpline**: `pv.Spline(chain, n_points=n)` for a
  smooth curve, then each interior control point is snapped to the nearest
  sample position so it appears exactly on the boundary.  This preserves smooth
  curvature while fixing Gordon-Hall face tessellation corners.

## Web viewer architecture (future)

A lightweight browser-based blockMeshDict viewer is planned as a
complement to the desktop editor. The web viewer would be read-only
(no editing, no blockMesh execution) but requires no installation —
users visit a URL, upload a blockMeshDict, and see it rendered in 3D.

### Architectural principle: shared core

The codebase uses a `core/` / `desktop/` split so both desktop and web
frontends share the same parser, model, writer, and geometry logic:

```
blockSketch/
├── core/                     # shared — no GUI dependency  ✓ implemented
│   ├── model.py              # dataclasses
│   ├── parser.py             # blockMeshDict parser
│   ├── writer.py             # blockMeshDict serialiser
│   └── geometry.py           # edge interpolation, tessellation
│                             # (_arc_points, _bspline_points,
│                             #  _tessellate_quad, _build_edge_chain,
│                             #  build_surface_mesh, ...)
│
├── desktop/                  # current desktop application  ✓ implemented
│   ├── viewer.py             # PyVista QtInteractor rendering
│   ├── app.py                # PyQt6 main window
│   └── panels/               # PyQt6 panel widgets
│
└── web/                      # lightweight web viewer (future)
    ├── app_web.py            # Panel/Solara web server
    ├── viewer_web.py         # PyVista Trame WebGL rendering
    └── templates/            # HTML templates
```

The `core/` layer is shared between both frontends. Only the
visualisation and interaction layers differ.

### Key technology: PyVista Trame backend

PyVista supports a web rendering backend called Trame that renders
the same PyVista scene in a browser using WebGL:

```python
import pyvista as pv
pv.set_jupyter_backend('trame')
```

This means the same `populate(plotter, mesh, ...)` function in
`desktop/viewer.py` can potentially drive both the desktop QtInteractor
AND a browser-based Trame viewer — the geometry code is unchanged.

### Remaining work for web viewer

The `core/` / `desktop/` refactoring is complete (2026-04-17).
The one remaining step before a web viewer is possible:

4. Create `web/app_web.py` using Panel + PyVista Trame

### Web viewer user experience
```
User visits: https://gavintabor.github.io/blockSketch/
↓
[ Upload blockMeshDict ] or [ Try example ]
↓
3D viewer in browser (WebGL via PyVista Trame)
- Rotate, zoom, pan
- Toggle vertex labels, patch faces, bounding box
- All edge types supported (arc, spline, polyLine, BSpline)
- Patch faces with colours and legend
- Read-only — no editing
↓
[ Download blockMeshDict ] (unchanged)
```

No installation required. No OpenFOAM required. Works on any
device with a modern browser including mobile.

### Picking and interaction

Desktop: click vertex/block/edge in 3D view → highlights
corresponding row in side panel table

Web: click vertex/block/edge → popup overlay showing:
- Vertex: index, x, y, z coordinates, which blocks reference it
- Edge: type, v_start, v_end, control points
- Block: index, vertex list, cell counts, grading

Shared function in core/:
```python
def get_pick_info(mesh: BlockMesh,
                  picked_point: np.ndarray) -> dict:
    """
    Given a picked 3D point, return info about the nearest
    mesh entity (vertex, block centroid, or edge midpoint).
    Used by both desktop and web frontends.
    """
```

Note: `get_pick_info()` is not yet implemented in `core/` —
add when starting web viewer development.

PyVista Trame supports picking callbacks in the browser using
the same API as the desktop — no separate implementation needed.

### Unified look and feel

Both desktop and web versions share:
- Same colour scheme (patch colours, edge colours, vertex colours)
- Same panel colour coding (red=General, green=Vertices etc.)
- Same legend style and vertex label appearance
- Same parser and geometry code — identical rendering results

### Hosting

The web viewer can be hosted on GitHub Pages as a static site.
PyVista Trame can export self-contained HTML files that run
without a Python server, making GitHub Pages hosting straightforward.

### Dependencies (web viewer, additional)
```
pip install panel trame trame-vtk trame-vuetify
```

### Notes
- Trame backend for PyVista is well-supported from PyVista 0.38+
- The refactoring into `core/` is recommended before the GitHub
  release as it improves architecture regardless of web plans
- Liam Berrisford (Exeter RSE) is a potential collaborator on
  the web viewer implementation

## Extended meshing options

### Tetrahedral meshing via tetgen
Implemented (2026-04-24) in Meshing panel Tab 2 'tetgen'. Use cases:
- Comparing hex (blockMesh) vs tet mesh results for the same geometry
- Users who want a quick tet mesh without defining block topology
- Validation studies on mesh topology effects

#### Surface preparation — `_build_tetgen_surface`
A dedicated function `_build_tetgen_surface(mesh, verts, n_curved=20)` builds
the surface for tetgen. It is separate from `build_surface_mesh` (which remains
unchanged — `merge_points=False` and quad output are correct for display).

`_build_tetgen_surface` iterates patches in index order and tessellates **all**
quad faces with `_tessellate_quad` at `n_curved` resolution (not just those with
curved edges). This ensures consistent shared-edge sampling: straight edges on
both sides of a patch boundary both produce `np.linspace(p0,p1,n)`, and curved
edges on both sides call the same `_get_edge_points`. After merging with
`merge_points=False`, `.clean(tolerance=1e-6)` collapses the coincident
shared-edge points and produces a closed, watertight surface.

```python
for patch_idx, patch in enumerate(mesh.patches):
    marker = patch_idx + 1
    for face in patch.faces:
        if len(face) == 4:
            poly = _tessellate_quad(face, mesh, verts, n=n_curved)
        else:
            # triangles: use vertices directly
            poly = pv.PolyData(local_pts, cells)
        poly = poly.triangulate()
        poly.cell_data['patch_marker'] = np.full(poly.n_cells, marker, dtype=np.int32)
        pieces.append(poly)
merged = pieces[0]
for p in pieces[1:]:
    merged = merged.merge(p, merge_points=False)
# Returns (merged, cleaned): cleaned used for watertight check and tetgen input
return merged, merged.clean(tolerance=1e-6)
```

The function returns `(merged, cleaned)`: the caller uses `cleaned` for both the
open-edges check and as the tetgen input — `clean()` only merges points, so
`patch_marker` cell data is preserved.

Key properties confirmed by testing:
- `build_surface_mesh()` with `n_curved=20` followed by `.clean(tolerance=1e-6)`
  produces a watertight surface for tetgen including curved edge cases
- The clean tolerance `1e-6` is appropriate for typical OpenFOAM mesh scales;
  tighter tolerances may fail to merge near-coincident points on curved edges
- Curved edge tessellation gaps (flat face adjacent to curved face) are fully
  resolved by the clean operation merging the coincident shared-edge points

#### Watertight check
`surface_check.n_open_edges > 0` is used rather than `surface.is_manifold`.
`n_open_edges` is more informative (the count appears in the error message)
and directly meaningful: open edges are holes in the surface. Common causes:
- Some block faces not assigned to any patch
- 2D/extruded cases with empty patches (not a true closed 3D surface)
- Incorrect face vertex ordering at patch boundaries

#### Tetrahedralisation — `_TetWorker`
Runs in a `_TetWorker(QThread)` to avoid blocking the UI.

The Python tetgen API accepts face markers directly via the three-argument
constructor `TetGen(points, faces, face_markers)` which calls
`load_facet_markers` internally. The `switches` string is used for quality
control; `tet.triface_markers` returns output boundary face markers directly —
no `.poly` file, no subprocess, no KDTree matching needed.

```python
surface_clean = surface.clean(tolerance=1e-8)   # merge coincident boundary pts
pts     = surface_clean.points.astype(np.float64)
faces   = surface_clean.faces.reshape(-1, 4)[:, 1:].astype(np.int32)
markers = surface_clean.cell_data['patch_marker'].astype(np.int32)

tet = tetgen.TetGen(pts, faces, markers)
switches = f'pq{minratio}/{mindihedral}a{maxvolume}'
tet.tetrahedralize(switches=switches)
# tet.triface_markers contains 1-based patch markers for boundary faces
```

`_TetWorker.finished` emits `(tet.grid, tet.node, tet.elem, tet.trifaces,
tet.triface_markers)` as a tuple. `_on_tet_finished` stores all five on
`self._tet_*` for use by the Write step.

#### OpenFOAM conversion and patch preservation
meshio does not support OpenFOAM as a write format. The conversion path is:

1. Write `constant/tetgen/tetmesh.node` from `tet.node` (1-indexed)
2. Write `constant/tetgen/tetmesh.ele` from `tet.elem` (1-indexed)
3. Write `constant/tetgen/tetmesh.face` via `_write_face_file`:
   filters `tet.triface_markers > 0` (boundary faces; interior = 0),
   writes `i v0+1 v1+1 v2+1 marker` — markers come directly from tetgen,
   no post-hoc centroid matching required
4. Run `tetgenToFoam -case <dir> constant/tetgen/tetmesh`
5. Post-process `constant/polyMesh/boundary` via `_rename_tet_patches`:
   tetgenToFoam names patches `patch0`, `patch1`, … (0-based) from the face
   markers; rename each `patchN` to the original name and restore the correct
   type — tetgenToFoam writes `type patch; physicalType patch;` for every
   patch regardless of the original type; regex fallback if `physicalType`
   is absent
6. Log: `[✓ boundary patches preserved: movingWall, fixedWalls, frontAndBack]`
7. Delete `constant/tetgen/` files unless 'Save tetgen files' is checked

#### Dependencies
```bash
pip install tetgen
```
tetgen is optional — blockSketch runs without it but the tetgen tab is
disabled with a clear install hint. meshio is no longer required; the
conversion path uses tetgenToFoam directly.

### Boundary layer meshing via snappyHexMesh layer addition
Implemented (2026-04-14). See Meshing panel description above for full details.

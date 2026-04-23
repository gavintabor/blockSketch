# blockSketch

An interactive viewer and editor for OpenFOAM `blockMeshDict` files.
Built with Python, PyVista and PyQt6.

Developed by Gavin Tabor, University of Exeter.

## Authors

**Gavin Tabor**, University of Exeter  
g.r.tabor@ex.ac.uk  
— concept, domain expertise, design, testing

**Claude** (Anthropic)  
— design consultation, architecture, code review

**Claude Code** (Anthropic)  
— implementation

## What it does

- Displays blockMesh geometry (vertices, blocks, curved edges, boundary patches)
- Supports all curved edge types: arc, spline, polyLine, BSpline
- Edit vertices, blocks, edges and patches interactively
- Saves modified blockMeshDict back to file
- Runs blockMesh and checkMesh from within the interface
- Adds boundary layers via snappyHexMesh (wall patches only)
- Loads reference STL/OBJ/VTK/PLY geometry for positioning

## Requirements

Python 3.10 or later, plus:

```bash
pip install -r requirements.txt
```

| Package    | Purpose                                  |
|------------|------------------------------------------|
| pyvista    | 3D visualisation                         |
| pyvistaqt  | Embed PyVista inside PyQt6               |
| PyQt6      | GUI framework                            |
| numpy      | Numerical arrays                         |
| scipy      | BSpline interpolation                    |

An OpenFOAM installation is required to run blockMesh, checkMesh
and snappyHexMesh. Tested against OpenFOAM 2406 (ESI/openfoam.com).

## Installation

No installation needed — just unzip the directory and run from within it.

## Running blockSketch

Run from your OpenFOAM case directory:

```bash
cd /path/to/your/case
python /path/to/blockSketch/main.py
```

Or specify the blockMeshDict directly:

```bash
python main.py path/to/blockMeshDict
```

blockSketch will look for the blockMeshDict in these locations:
- `system/blockMeshDict` (modern OF, v6+)
- `constant/polyMesh/blockMeshDict` (older OF)

If no blockMeshDict is found, you will be prompted to create a new one.

## Quick start

1. Open a case directory containing a blockMeshDict
2. The 3D viewport shows vertices, blocks and patches automatically
3. Use the six panel buttons to edit different aspects of the mesh:
   - **General** — scale factor, display options, load reference geometry
   - **Vertices** — add, move and delete vertices
   - **Blocks** — define hex blocks, cell counts and grading
   - **Edges** — add curved edges (arc, spline, polyLine, BSpline)
   - **Patches** — define boundary patches and face lists
   - **Meshing** — run blockMesh, checkMesh, boundary layer addition
4. Click **Save** (or Ctrl+S) to write the modified blockMeshDict

## Known limitations

- Boundary layer addition tested on OF 2406 ESI only — may need
  manual adjustment of system/snappyHexMeshDict on other versions
- Two-way selection (click vertex in 3D view → highlight in table)
  not yet implemented
- Topology validator does not yet detect crossed edges or degenerate blocks
- `#include` directives in blockMeshDict are not followed

## Boundary layer meshing — known limitations

Boundary layer addition uses snappyHexMesh in layers-only mode.
Results depend heavily on the mesh geometry and snappyHexMesh's own
capabilities and limitations:

**Works well:**
- Simple geometries with smooth wall patches
- Extruded 2D cases with clear wall boundaries
- Cylindrical/pipe geometries (O-grid blocks)

**May produce poor results or fail:**
- Complex geometries with sharp concave corners
- T-junctions and highly non-orthogonal patches
- Cases where wall patches share edges at acute angles
- Very thin regions between opposing walls

These are limitations of snappyHexMesh layer addition, not blockSketch.
If layer addition fails or produces poor quality layers, consider:
- Adjusting n (fewer layers) and exp (smaller expansion ratio)
- Running checkMesh first to check base mesh quality
- Using a dedicated boundary layer meshing tool

**Tested and working:**
- Simple duct/pipe cases
- 5-block cylinder O-grid mesh (OF 2406 ESI and OF 12 Foundation)

**Known issues:**
- T-junction cases: incomplete or malformed layers on some patches

## Tested cases

- cavity (icoFoam tutorial) — single block
- backwardFacingStep — multi-block
- pipe bend with arc edges — curved edges
- cylinder O-grid — arc edges, multi-block 3D
- 5-block cylinder O-grid — boundary layer addition (OF 2406 ESI and OF 12 Foundation)

## Feedback

This is a beta release. Please report any issues, crashes or missing
features to:

**Gavin Tabor**
g.r.tabor@ex.ac.uk
University of Exeter

Please include:
- Your OpenFOAM version
- Operating system
- The blockMeshDict file that caused the issue (if applicable)
- Any error messages from the terminal

## Acknowledgements

Built with:
- [PyVista](https://pyvista.org) — 3D visualisation
- [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) — GUI framework
- [SciPy](https://scipy.org) — BSpline interpolation

## License

blockSketch is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

See the LICENSE file for full details.

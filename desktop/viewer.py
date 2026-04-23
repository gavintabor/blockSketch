"""
3-D visualisation of a BlockMesh using PyVista.
"""
import numpy as np
import pyvista as pv
import vtk
from vtk.util.numpy_support import numpy_to_vtk

import math

from core.model import ArcEdge, BlockMesh, BoundaryPatch, SplineEdge
from core.geometry import (
    _arc_points, _arc_midpoint_from_origin, _bspline_points, _polyline_sample,
    _build_edge_chain, _get_edge_points, _face_has_curved_edge,
    _tessellate_quad, build_surface_mesh,
)


# ---------------------------------------------------------------------------
# Build PyVista geometry from BlockMesh
# ---------------------------------------------------------------------------

def _build_vertex_cloud(mesh: BlockMesh) -> pv.PolyData:
    verts = mesh.scaled_vertices()
    if not verts:
        return pv.PolyData()
    pts = np.array(verts, dtype=np.float64)
    # Build via VTK directly so coincident points are never merged.
    # pv.PolyData(pts) may collapse duplicate coordinates internally.
    vtk_pts = vtk.vtkPoints()
    vtk_pts.SetData(numpy_to_vtk(pts, deep=True))
    vtk_verts = vtk.vtkCellArray()
    for i in range(len(verts)):
        vtk_verts.InsertNextCell(1)
        vtk_verts.InsertCellPoint(i)
    vtk_pd = vtk.vtkPolyData()
    vtk_pd.SetPoints(vtk_pts)
    vtk_pd.SetVerts(vtk_verts)
    cloud = pv.wrap(vtk_pd)
    cloud['label'] = [str(v.index) for v in mesh.vertices]
    return cloud


def _build_block_edges(mesh: BlockMesh) -> pv.PolyData:
    """Return a PolyData of straight block edges (lines)."""
    verts = mesh.scaled_vertices()
    if not verts or not mesh.blocks:
        return pv.PolyData()

    edge_set: set = set()
    for block in mesh.blocks:
        for a, b in block.edge_vertex_pairs():
            edge_set.add((min(a, b), max(a, b)))

    # Check if any edge has a curved override
    curved_pairs: set = set()
    for edge in mesh.edges:
        if hasattr(edge, 'v_start'):
            a, b = edge.v_start, edge.v_end
            curved_pairs.add((min(a, b), max(a, b)))

    straight_edges = edge_set - curved_pairs

    edge_pairs = [
        (a, b) for a, b in straight_edges
        if a < len(verts) and b < len(verts)
    ]
    if not edge_pairs:
        return pv.PolyData()

    # Build via VTK directly: one point per vertex index even when coordinates
    # are identical (mergePatchPairs case).  PyVista constructors may invoke
    # vtkCleanPolyData which would collapse coincident points and remap indices.
    all_pts = np.array(verts, dtype=np.float64)
    vtk_pts = vtk.vtkPoints()
    vtk_pts.SetData(numpy_to_vtk(all_pts, deep=True))

    cell_arr = vtk.vtkCellArray()
    for a, b in edge_pairs:
        cell_arr.InsertNextCell(2)
        cell_arr.InsertCellPoint(a)
        cell_arr.InsertCellPoint(b)

    vtk_pd = vtk.vtkPolyData()
    vtk_pd.SetPoints(vtk_pts)
    vtk_pd.SetLines(cell_arr)
    return pv.wrap(vtk_pd)


def _build_curved_edges(mesh: BlockMesh, n_pts: int = 40) -> list:
    """Return a list of (kind, pts, edge_idx) triples for curved edges."""
    verts = mesh.scaled_vertices()
    actors = []
    for edge_idx, edge in enumerate(mesh.edges):
        v0_idx = edge.v_start
        v1_idx = edge.v_end
        if v0_idx >= len(verts) or v1_idx >= len(verts):
            continue
        p0 = verts[v0_idx]
        p1 = verts[v1_idx]

        if isinstance(edge, ArcEdge):
            raw = np.array(edge.point) * mesh.scale
            pmid = _arc_midpoint_from_origin(p0, p1, raw) if edge.is_origin else raw
            pts = _arc_points(p0, p1, pmid, n=n_pts)
            actors.append(('arc', pts, edge_idx))

        elif isinstance(edge, SplineEdge):
            all_pts = _build_edge_chain(edge, v0_idx, v1_idx, verts, mesh.scale)
            if edge.kind == 'BSpline':
                tag = 'bspline'
            elif edge.kind in ('polyLine', 'polySpline'):
                tag = 'polyline'
            else:
                tag = 'spline'
            actors.append((tag, all_pts, edge_idx))

    return actors


def _make_spline_polydata(pts: np.ndarray) -> pv.PolyData:
    spline = pv.Spline(pts, n_points=max(len(pts) * 8, 64))
    return spline


def _build_control_points(mesh: BlockMesh) -> pv.PolyData:
    """Return a PolyData of intermediate edge control points (not start/end vertices).

    These are shown as a distinct gold point cloud so the user can see the
    control polygon — especially useful for BSpline where the curve only
    approximates the control points rather than passing through them.
    """
    pts = []
    for edge in mesh.edges:
        if isinstance(edge, ArcEdge):
            if not edge.is_origin:   # circle-centre points are not meaningful to display
                pts.append(np.array(edge.point) * mesh.scale)
        elif isinstance(edge, SplineEdge):
            for pt in edge.points:
                pts.append(np.array(pt) * mesh.scale)
    if not pts:
        return pv.PolyData()
    return pv.PolyData(np.array(pts))


# ---------------------------------------------------------------------------
# Bounding box annotation helpers
# ---------------------------------------------------------------------------

def _nice_number(x: float) -> float:
    """Round x to the nearest 1, 2 or 5 × 10^n (for scale bar labels)."""
    if x <= 0:
        return 1.0
    exp = math.floor(math.log10(x))
    base = x / 10 ** exp
    if base < 1.5:
        nice = 1
    elif base < 3.5:
        nice = 2
    elif base < 7.5:
        nice = 5
    else:
        nice = 10
    return nice * 10 ** exp



def _add_scale_bar(pl: pv.Plotter, bounds: tuple) -> None:
    """Draw a scale bar with end caps and a length label below the bounding box.

    bounds is the PyVista (xmin, xmax, ymin, ymax, zmin, zmax) tuple captured
    from plotter.bounds after all mesh geometry is added.
    """
    xmin, xmax, ymin, ymax, zmin, zmax = bounds

    max_dim = max(xmax - xmin, ymax - ymin, zmax - zmin)
    bar_len = _nice_number(max_dim * 0.2)
    tick_h = max_dim * 0.03

    # Place bar below the bottom-left corner of the bounding box
    sx = xmin
    sy = ymin - (ymax - ymin) * 0.12
    sz = zmin
    ex = sx + bar_len

    # Bar + end caps as a single PolyData
    bar_pts = np.array([
        [sx, sy, sz], [ex, sy, sz],                          # main bar
        [sx, sy - tick_h / 2, sz], [sx, sy + tick_h / 2, sz],  # left cap
        [ex, sy - tick_h / 2, sz], [ex, sy + tick_h / 2, sz],  # right cap
    ])
    bar_lines = np.array([2, 0, 1,  2, 2, 3,  2, 4, 5], dtype=np.int_)
    bar = pv.PolyData()
    bar.points = bar_pts
    bar.lines = bar_lines
    pl.add_mesh(bar, color='black', line_width=3)

    mid = np.array([[(sx + ex) / 2, sy + tick_h * 1.2, sz]])
    lbl = pv.PolyData(mid)
    lbl['label'] = [f'{bar_len:g} m']
    pl.add_point_labels(lbl, 'label',
                        font_size=10, text_color='black',
                        show_points=False, always_visible=True, shape=None)


# ---------------------------------------------------------------------------
# Main viewer — populate() draws onto any Plotter; show() owns the window
# ---------------------------------------------------------------------------

def populate(pl: pv.Plotter, mesh: BlockMesh, *,
             show_vertex_labels: bool = True,
             show_block_labels: bool = True,
             show_block_edges: bool = True,
             show_curved_edges: bool = True,
             show_patch_faces: bool = True,
             show_bounding_box: bool = False,
             show_scale_bar: bool = False,
             show_legend: bool = True,
             extra_legend_entries: list | None = None,
             background: str = 'white') -> None:
    """Draw *mesh* onto an existing :class:`pv.Plotter` (or QtInteractor).

    Does not call ``pl.show()`` — the caller is responsible for that.
    Safe to call repeatedly after ``pl.clear()``.
    """
    pl.set_background(background)

    verts = mesh.scaled_vertices()
    n_verts = len(verts)

    if n_verts == 0:
        return

    # Legend entries accumulated as [label, color, face] triples.
    # face: 'circle' for points, '-' for lines, 'rectangle' for surfaces.
    legend_entries: list = []

    # --- Vertices ---
    cloud = _build_vertex_cloud(mesh)
    pl.add_mesh(cloud, color='red', point_size=10, render_points_as_spheres=True)
    legend_entries.append(['Vertices', 'red', 'circle'])

    if show_vertex_labels:
        pl.add_point_labels(
            cloud,
            'label',
            font_size=14,
            text_color='darkblue',
            bold=True,
            show_points=False,
            always_visible=True,
        )

    # --- Straight block edges ---
    if show_block_edges:
        edge_poly = _build_block_edges(mesh)
        if edge_poly.n_points > 0:
            pl.add_mesh(edge_poly, color='steelblue', line_width=2)
            legend_entries.append(['Block edges', 'steelblue', '-'])

    # --- Curved edges ---
    if show_curved_edges and mesh.edges:
        curved = _build_curved_edges(mesh)
        arc_seen = spline_seen = polyline_seen = bspline_seen = False
        for kind, pts, edge_idx in curved:
            if len(pts) < 2:
                continue
            if kind == 'arc':
                poly = pv.lines_from_points(pts)
                poly['edge_index'] = np.full(poly.n_points, edge_idx, dtype=int)
                pl.add_mesh(poly, color='darkorange', line_width=3)
                if not arc_seen:
                    legend_entries.append(['Arc edges', 'darkorange', '-'])
                    arc_seen = True
            elif kind == 'spline':
                spline_poly = _make_spline_polydata(pts)
                spline_poly['edge_index'] = np.full(spline_poly.n_points, edge_idx, dtype=int)
                pl.add_mesh(spline_poly, color='green', line_width=3)
                if not spline_seen:
                    legend_entries.append(['Spline edges', 'green', '-'])
                    spline_seen = True
            elif kind == 'polyline':
                poly = pv.lines_from_points(pts)
                poly['edge_index'] = np.full(poly.n_points, edge_idx, dtype=int)
                pl.add_mesh(poly, color='teal', line_width=3)
                if not polyline_seen:
                    legend_entries.append(['PolyLine edges', 'teal', '-'])
                    polyline_seen = True
            elif kind == 'bspline':
                bspline_pts = _bspline_points(pts)
                poly = pv.lines_from_points(bspline_pts)
                poly['edge_index'] = np.full(poly.n_points, edge_idx, dtype=int)
                pl.add_mesh(poly, color='purple', line_width=3)
                if not bspline_seen:
                    legend_entries.append(['BSpline edges', 'purple', '-'])
                    bspline_seen = True

        ctrl_cloud = _build_control_points(mesh)
        if ctrl_cloud.n_points > 0:
            pl.add_mesh(ctrl_cloud, color='gold', point_size=7,
                        render_points_as_spheres=True, pickable=True)
            legend_entries.append(['Edge ctrl pts', 'gold', 'circle'])

    # --- Block centroid labels ---
    if show_block_labels and mesh.blocks:
        _add_block_labels(pl, mesh, verts)

    # --- Boundary patch face highlights ---
    _add_boundary_patches(pl, mesh, verts,
                          opacity=0.35 if show_patch_faces else 0.0,
                          legend_entries=legend_entries)

    # Capture bounds NOW — after all mesh geometry (vertices, edges, patch faces)
    # but before any annotations (bounding box, scale bar, axes, text).
    # This ensures curved edges are included and annotations don't inflate it.
    mesh_bounds = pl.bounds   # (xmin, xmax, ymin, ymax, zmin, zmax)

    # --- Bounding box ---
    if show_bounding_box:
        xmin, xmax, ymin, ymax, zmin, zmax = mesh_bounds
        mn = np.array([xmin, ymin, zmin])
        mx = np.array([xmax, ymax, zmax])
        box = pv.Box(bounds=(xmin, xmax, ymin, ymax, zmin, zmax))
        pl.add_mesh(box, color='gray', line_width=1, style='wireframe')
        legend_entries.append(['Bounding box', 'gray', '-'])
        legend_entries.append([
            f'  ({mn[0]:.3g},{mn[1]:.3g},{mn[2]:.3g})'
            f' – ({mx[0]:.3g},{mx[1]:.3g},{mx[2]:.3g})',
            'gray', '-',
        ])

    # --- Scale bar ---
    if show_scale_bar:
        _add_scale_bar(pl, mesh_bounds)

    pl.add_axes()
    if extra_legend_entries:
        legend_entries.extend(extra_legend_entries)
    if show_legend and legend_entries:
        pl.add_legend(legend_entries, bcolor='white', border=True, size=(0.25, 0.25))


def show(mesh: BlockMesh, *,
         show_vertex_labels: bool = True,
         show_block_labels: bool = True,
         show_block_edges: bool = True,
         show_curved_edges: bool = True,
         background: str = 'white',
         window_size: tuple = (1200, 900)) -> None:
    """Display a :class:`BlockMesh` interactively with PyVista (standalone)."""

    pl = pv.Plotter(window_size=window_size)

    if not mesh.vertices:
        print("[viewer] No vertices to display.")
        pl.show()
        return

    populate(pl, mesh,
             show_vertex_labels=show_vertex_labels,
             show_block_labels=show_block_labels,
             show_block_edges=show_block_edges,
             show_curved_edges=show_curved_edges,
             background=background)

    for w in mesh.warnings:
        print(f"[parser warning] {w}")
    print(f"\nBlockMesh summary:")
    print(f"  scale       : {mesh.scale}")
    print(f"  vertices    : {len(mesh.vertices)}")
    print(f"  blocks      : {len(mesh.blocks)}")
    print(f"  edges       : {len(mesh.edges)}")
    print(f"  patches     : {len(mesh.patches)}")
    if mesh.patches:
        for p in mesh.patches:
            print(f"    {p.name:20s}  type={p.patch_type}  faces={len(p.faces)}")

    pl.show(title='blockSketch')


def _add_block_labels(pl: pv.Plotter, mesh: BlockMesh, verts: list) -> None:
    """Display block index at the centroid of each hex block."""
    centroids = []
    labels = []
    for i, block in enumerate(mesh.blocks):
        pts = [verts[vi] for vi in block.vertex_ids if vi < len(verts)]
        if not pts:
            continue
        centroid = np.mean(pts, axis=0)
        centroids.append(centroid)
        label = f'B{i} ({block.zone_name})' if block.zone_name else f'B{i}'
        labels.append(label)

    if not centroids:
        return

    cloud = pv.PolyData(np.array(centroids))
    cloud['label'] = labels
    pl.add_point_labels(
        cloud,
        'label',
        font_size=18,
        text_color='green',
        bold=True,
        show_points=False,
        always_visible=True,
        shape=None,
    )


def enable_block_picking(plotter: pv.Plotter, mesh: BlockMesh,
                         verts: list, callback) -> None:
    """Add pickable centroid markers for block picking.

    Does NOT register a point picker — call enable_vertex_picking() afterwards
    to register a combined picker that handles both vertices and blocks.
    """
    if not mesh.blocks or not verts:
        return

    centroids = []
    block_indices = []
    for i, block in enumerate(mesh.blocks):
        pts = [verts[vi] for vi in block.vertex_ids if vi < len(verts)]
        if pts:
            centroids.append(np.mean(pts, axis=0))
            block_indices.append(i)

    if not centroids:
        return

    centroids_arr = np.array(centroids)
    pts_arr = np.array(verts)
    diag = np.linalg.norm(pts_arr.max(axis=0) - pts_arr.min(axis=0))
    threshold = 0.1 * diag if diag > 0 else 1.0

    marker_cloud = pv.PolyData(centroids_arr)
    plotter.add_mesh(
        marker_cloud,
        color='green',
        point_size=12,
        render_points_as_spheres=True,
        opacity=0.15,
        name='block_centroids',
        pickable=True,
    )

    # Stash data so enable_vertex_picking can include blocks in the combined picker
    plotter._block_pick = (centroids_arr, block_indices, threshold, callback)


def enable_edge_picking(plotter: pv.Plotter, mesh: BlockMesh,
                        verts: list, callback) -> None:
    """Pick curved edges by right-clicking on the rendered line geometry.

    Uses a raw VTK vtkCellPicker observer rather than PyVista's
    enable_cell_picking, which cannot coexist with enable_point_picking
    (both go through _validate_picker_not_in_use).  The VTK observer fires
    on the same RightButtonPressEvent as the point picker; both run
    independently — the point picker handles vertices/blocks, this handles
    edges via the 'edge_index' point scalar tagged on each edge PolyData.

    Re-registering on viewport refresh is safe: the previous observer is
    removed via the stored tag before a new one is added.
    """
    if not mesh.edges:
        return

    # Remove stale observer from a previous refresh
    old_tag = getattr(plotter, '_edge_pick_observer', None)
    if old_tag is not None:
        try:
            plotter.iren.interactor.RemoveObserver(old_tag)
        except Exception:
            pass

    def _on_right_click(obj, event):
        x, y = plotter.iren.interactor.GetEventPosition()
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.005)
        picker.Pick(x, y, 0, plotter.renderer)
        actor = picker.GetActor()
        if actor is None:
            return
        mapper = actor.GetMapper()
        if mapper is None:
            return
        data = mapper.GetInput()
        if data is None:
            return
        arr = data.GetPointData().GetArray('edge_index')
        if arr is None:
            return
        edge_idx = int(arr.GetValue(0))
        callback(edge_idx)

    tag = plotter.iren.interactor.AddObserver(
        'RightButtonPressEvent', _on_right_click)
    plotter._edge_pick_observer = tag


def enable_vertex_picking(plotter: pv.Plotter, mesh: BlockMesh,
                          verts: list, callback) -> None:
    """Register a combined right-click picker for vertices and block centroids.

    Priority order: vertices (5 % threshold) → block centroids (10 %).
    Edge picking is handled separately by enable_edge_picking() via cell
    picking on the rendered line geometry — call that AFTER this function.
    """
    if not verts:
        return

    verts_arr = np.array(verts)
    diag = np.linalg.norm(verts_arr.max(axis=0) - verts_arr.min(axis=0))
    v_threshold = 0.05 * diag if diag > 0 else 1.0

    block_pick = getattr(plotter, '_block_pick', None)

    def _on_pick(point):
        if point is None:
            return
        pt = np.asarray(point)

        # 1. Vertices — most precise, checked first
        v_dists = np.linalg.norm(verts_arr - pt, axis=1)
        v_nearest = int(np.argmin(v_dists))
        if v_dists[v_nearest] < v_threshold:
            callback(v_nearest)
            return

        # 2. Block centroids
        if block_pick is not None:
            centroids_arr, block_indices, b_threshold, b_callback = block_pick
            b_dists = np.linalg.norm(centroids_arr - pt, axis=1)
            b_nearest = int(np.argmin(b_dists))
            if b_dists[b_nearest] < b_threshold:
                b_callback(block_indices[b_nearest])

    plotter.disable_picking()
    plotter.enable_point_picking(callback=_on_pick,
                                 show_message=False, show_point=False,
                                 picker='point', pickable_window=False)




# Local index pairs for the 6 faces of a hex (a b c d e f g h) — outward winding.
_HEX_FACE_LOCAL = [
    (0, 3, 7, 4),   # x-
    (1, 2, 6, 5),   # x+
    (0, 1, 5, 4),   # y-
    (3, 2, 6, 7),   # y+
    (0, 1, 2, 3),   # z-
    (4, 5, 6, 7),   # z+
]


def _synthesise_default_patch(mesh: BlockMesh) -> BoundaryPatch | None:
    """Return a synthetic BoundaryPatch covering all block faces not in any explicit patch."""
    if not mesh.default_patch_name or not mesh.blocks:
        return None
    n_verts = len(mesh.vertices)
    explicit: set[frozenset] = {
        frozenset(face)
        for patch in mesh.patches
        for face in patch.faces
    }
    unclaimed: list[tuple[int, ...]] = []
    for block in mesh.blocks:
        ids = block.vertex_ids
        if len(ids) != 8 or any(v >= n_verts for v in ids):
            continue
        for local in _HEX_FACE_LOCAL:
            face = tuple(ids[i] for i in local)
            if frozenset(face) not in explicit:
                unclaimed.append(face)
    if not unclaimed:
        return None
    return BoundaryPatch(
        name=mesh.default_patch_name,
        patch_type=mesh.default_patch_type,
        faces=unclaimed,
    )


def _add_boundary_patches(pl: pv.Plotter, mesh: BlockMesh, verts: list,
                          n_curved: int = 20, opacity: float = 0.35,
                          legend_entries: list | None = None) -> None:
    """Render boundary patch faces as semi-transparent coloured surfaces.

    Quad faces whose edges include a curved edge are tessellated via
    transfinite interpolation so the surface follows the arc/spline.
    Flat faces are rendered as simple quads.
    """
    synthetic = _synthesise_default_patch(mesh)
    patches = list(mesh.patches) + ([synthetic] if synthetic else [])
    if not patches or not verts:
        return

    palette = [
        '#e6194b', '#3cb44b', '#4363d8', '#f58231',
        '#911eb4', '#42d4f4', '#f032e6', '#bfef45',
        '#fabed4', '#469990', '#dcbeff', '#9a6324',
    ]

    verts_arr = np.array(verts)
    has_any_curved = bool(mesh.edges)

    for i, patch in enumerate(patches):
        color = palette[i % len(palette)]

        pieces = []   # list of PolyData to merge for this patch

        for face in patch.faces:
            if not all(fi < len(verts) for fi in face):
                continue

            if has_any_curved and len(face) == 4 and _face_has_curved_edge(face, mesh):
                pieces.append(_tessellate_quad(face, mesh, verts, n=n_curved))
            else:
                # Flat face — simple polygon
                local_pts = verts_arr[list(face)]
                cells = [len(face)] + list(range(len(face)))
                poly = pv.PolyData()
                poly.points = local_pts
                poly.faces = np.array(cells, dtype=np.int_)
                pieces.append(poly)

        if not pieces:
            continue

        combined = pv.merge(pieces, merge_points=False) if len(pieces) > 1 else pieces[0]
        pl.add_mesh(combined, color=color, opacity=opacity,
                    show_edges=opacity > 0, edge_color='black')
        if legend_entries is not None:
            legend_entries.append([f'{patch.name} ({patch.patch_type})', color, 'rectangle'])

"""
3-D visualisation of a BlockMesh using PyVista.
"""
import numpy as np
import pyvista as pv
from scipy.interpolate import BSpline as SciPyBSpline

from model import ArcEdge, BlockMesh, SplineEdge


# ---------------------------------------------------------------------------
# Arc interpolation helpers
# ---------------------------------------------------------------------------

def _arc_points(p0: np.ndarray, p1: np.ndarray, pmid: np.ndarray,
                n: int = 32) -> np.ndarray:
    """
    Return *n* points along the circular arc defined by three points:
    the start *p0*, the end *p1*, and a point on the arc *pmid*.

    Falls back to a straight line if the three points are collinear.
    """
    # Find circle centre in the plane of the three points
    # Using the circumcircle approach in 3D
    v1 = p1 - p0
    v2 = pmid - p0

    # Normal to the plane
    normal = np.cross(v1, v2)
    norm_len = np.linalg.norm(normal)
    if norm_len < 1e-15:
        # Degenerate / collinear – straight line
        return np.linspace(p0, p1, n)

    normal /= norm_len

    # Circumcenter lies at intersection of perpendicular bisector planes
    # of p0-p1 and p0-pmid.
    # mid01 + s*(v1 x normal) = mid02 + t*(v2 x normal)
    mid01 = (p0 + p1) / 2.0
    mid02 = (p0 + pmid) / 2.0
    d1 = np.cross(v1, normal)
    d2 = np.cross(v2, normal)

    # Solve for s: mid01 + s*d1 = mid02 + t*d2
    # (mid02 - mid01) = s*d1 - t*d2
    rhs = mid02 - mid01
    # two equations from x and y components
    A = np.column_stack([d1, -d2])
    try:
        # least-squares solve for [s, t]
        st, _, _, _ = np.linalg.lstsq(A, rhs, rcond=None)
        s = st[0]
    except Exception:
        return np.linspace(p0, p1, n)

    centre = mid01 + s * d1

    r0 = p0 - centre
    r1 = p1 - centre
    radius = np.linalg.norm(r0)
    if radius < 1e-15:
        return np.linspace(p0, p1, n)

    # Sweep angle (signed, using normal)
    cos_a = np.clip(np.dot(r0, r1) / (radius ** 2), -1.0, 1.0)
    # Choose sign by checking which side pmid is on
    rmid = pmid - centre
    cross = np.cross(r0, rmid)
    sign = 1.0 if np.dot(cross, normal) >= 0 else -1.0
    angle = sign * np.arccos(cos_a)

    thetas = np.linspace(0.0, angle, n)
    # Rodrigues' rotation formula for each theta
    pts = []
    for theta in thetas:
        c, s_r = np.cos(theta), np.sin(theta)
        rotated = (c * r0
                   + s_r * np.cross(normal, r0)
                   + (1 - c) * np.dot(normal, r0) * normal)
        pts.append(centre + rotated)
    return np.array(pts)


# ---------------------------------------------------------------------------
# B-spline approximation helper
# ---------------------------------------------------------------------------

def _bspline_points(ctrl_pts: np.ndarray, n: int = 64) -> np.ndarray:
    """
    Evaluate a uniform clamped B-spline that approximates *ctrl_pts*.

    ctrl_pts should be an (m, 3) array including the start and end vertices.
    Degree is cubic where possible, reduced for fewer control points.
    The curve passes exactly through the first and last control point (clamped
    end conditions) but only approximates the intermediate ones — this is the
    key difference from the interpolating Catmull-Rom used for 'spline'.

    Falls back to a straight line if fewer than 2 points are given.
    """
    m = len(ctrl_pts)
    if m < 2:
        return ctrl_pts if m else np.empty((0, 3))
    if m == 2:
        return np.linspace(ctrl_pts[0], ctrl_pts[1], n)

    k = min(3, m - 1)          # cubic where possible, lower degree otherwise

    # Clamped (open) uniform knot vector:
    # k+1 zeros, uniform interior knots, k+1 ones.
    # Total knot count = m + k + 1  (since n_ctrl = m = n+1, so n+k+2 = m+k+1)
    n_interior = m - k - 1     # may be 0 for small m
    if n_interior > 0:
        interior = np.linspace(0.0, 1.0, n_interior + 2)[1:-1]
        knots = np.concatenate([np.zeros(k + 1), interior, np.ones(k + 1)])
    else:
        knots = np.concatenate([np.zeros(k + 1), np.ones(k + 1)])

    spline = SciPyBSpline(knots, ctrl_pts, k)
    return spline(np.linspace(0.0, 1.0, n))


# ---------------------------------------------------------------------------
# Build PyVista geometry from BlockMesh
# ---------------------------------------------------------------------------

def _build_vertex_cloud(mesh: BlockMesh) -> pv.PolyData:
    verts = mesh.scaled_vertices()
    if not verts:
        return pv.PolyData()
    pts = np.array(verts)
    cloud = pv.PolyData(pts)
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

    lines = []
    for a, b in straight_edges:
        if a < len(verts) and b < len(verts):
            lines.append(2)
            lines.append(a)
            lines.append(b)

    if not lines:
        return pv.PolyData()

    all_pts = np.array(verts)
    poly = pv.PolyData()
    poly.points = all_pts
    poly.lines = np.array(lines, dtype=np.int_)
    return poly


def _build_curved_edges(mesh: BlockMesh, n_pts: int = 40) -> list:
    """Return a list of pv.Spline / pv.PolyData objects for curved edges."""
    verts = mesh.scaled_vertices()
    actors = []
    for edge in mesh.edges:
        v0_idx = edge.v_start
        v1_idx = edge.v_end
        if v0_idx >= len(verts) or v1_idx >= len(verts):
            continue
        p0 = verts[v0_idx]
        p1 = verts[v1_idx]

        if isinstance(edge, ArcEdge):
            pmid = np.array(edge.point) * mesh.scale
            pts = _arc_points(p0, p1, pmid, n=n_pts)
            actors.append(('arc', pts))

        elif isinstance(edge, SplineEdge):
            all_pts = _build_edge_chain(edge, v0_idx, v1_idx, verts, mesh.scale)
            if edge.kind == 'BSpline':
                tag = 'bspline'
            elif edge.kind in ('polyLine', 'polySpline'):
                tag = 'polyline'
            else:
                tag = 'spline'
            actors.append((tag, all_pts))

    return actors


def _make_spline_polydata(pts: np.ndarray) -> pv.PolyData:
    spline = pv.Spline(pts, n_points=max(len(pts) * 8, 64))
    return spline


def _polyline_sample(chain: np.ndarray, n: int) -> np.ndarray:
    """Sample *n* points uniformly by arc length along a piecewise-linear chain."""
    segs = np.linalg.norm(np.diff(chain, axis=0), axis=1)
    dists = np.concatenate([[0.0], np.cumsum(segs)])
    total = dists[-1]
    if total < 1e-15:
        return np.tile(chain[0], (n, 1))
    t = np.linspace(0.0, total, n)
    return np.column_stack([np.interp(t, dists, chain[:, i]) for i in range(3)])


def _build_control_points(mesh: BlockMesh) -> pv.PolyData:
    """Return a PolyData of intermediate edge control points (not start/end vertices).

    These are shown as a distinct gold point cloud so the user can see the
    control polygon — especially useful for BSpline where the curve only
    approximates the control points rather than passing through them.
    """
    pts = []
    for edge in mesh.edges:
        if isinstance(edge, ArcEdge):
            pts.append(np.array(edge.point) * mesh.scale)
        elif isinstance(edge, SplineEdge):
            for pt in edge.points:
                pts.append(np.array(pt) * mesh.scale)
    if not pts:
        return pv.PolyData()
    return pv.PolyData(np.array(pts))


# ---------------------------------------------------------------------------
# Face tessellation helpers
# ---------------------------------------------------------------------------

def _build_edge_chain(edge: SplineEdge, va: int, vb: int,
                      verts: list, scale: float) -> np.ndarray:
    """
    Return the full point chain for *edge* traversed from vertex *va* to *vb*.

    The returned array shape is (m+2, 3) and is always ordered
    [p_va, c1, c2, ..., p_vb].  If edge.v_start == va the control points are
    taken in dict order (forward); if edge.v_start == vb they are reversed and
    the endpoints swapped (backward).
    """
    p_va = np.asarray(verts[va])
    p_vb = np.asarray(verts[vb])
    inner = [np.array(pt) * scale for pt in edge.points]
    if edge.v_start != va:      # backward: edge stored as vb→va
        inner = list(reversed(inner))
    return np.vstack([p_va.reshape(1, 3)]
                     + [p.reshape(1, 3) for p in inner]
                     + [p_vb.reshape(1, 3)])


def _get_edge_points(va: int, vb: int, mesh: BlockMesh, verts: list,
                     n: int) -> np.ndarray:
    """Return *n* points along the edge va→vb, following any curved definition."""
    p0 = verts[va]
    p1 = verts[vb]
    for edge in mesh.edges:
        ea, eb = edge.v_start, edge.v_end
        forward = (ea == va and eb == vb)
        backward = (ea == vb and eb == va)
        if not (forward or backward):
            continue
        if isinstance(edge, ArcEdge):
            pmid = np.array(edge.point) * mesh.scale
            pts = _arc_points(p0, p1, pmid, n=n) if forward else _arc_points(p1, p0, pmid, n=n)[::-1]
            return pts
        elif isinstance(edge, SplineEdge):
            chain = _build_edge_chain(edge, va, vb, verts, mesh.scale)
            if edge.kind == 'BSpline':
                return _bspline_points(chain, n=n)
            if edge.kind in ('polyLine', 'polySpline'):
                return _polyline_sample(chain, n=n)
            return pv.Spline(chain, n_points=n).points
    return np.linspace(p0, p1, n)


def _face_has_curved_edge(face: tuple, mesh: BlockMesh) -> bool:
    curved = {(min(e.v_start, e.v_end), max(e.v_start, e.v_end)) for e in mesh.edges}
    n = len(face)
    return any((min(face[i], face[(i+1) % n]), max(face[i], face[(i+1) % n])) in curved
               for i in range(n))


def _tessellate_quad(face: tuple, mesh: BlockMesh, verts: list,
                     n: int) -> pv.PolyData:
    """
    Bilinear (Gordon-Hall) transfinite interpolation for a quad face.

    For face (v0, v1, v2, v3):
      s direction  v0→v1  (bottom, t=0)  and  v3→v2  (top, t=1)
      t direction  v0→v3  (left,   s=0)  and  v1→v2  (right, s=1)
    """
    v0, v1, v2, v3 = face

    C_b = _get_edge_points(v0, v1, mesh, verts, n)   # bottom  s, t=0
    C_t = _get_edge_points(v3, v2, mesh, verts, n)   # top     s, t=1
    C_l = _get_edge_points(v0, v3, mesh, verts, n)   # left    t, s=0
    C_r = _get_edge_points(v1, v2, mesh, verts, n)   # right   t, s=1

    P00 = np.asarray(verts[v0])
    P10 = np.asarray(verts[v1])
    P11 = np.asarray(verts[v2])
    P01 = np.asarray(verts[v3])

    s = np.linspace(0.0, 1.0, n)
    t = np.linspace(0.0, 1.0, n)

    # Shapes for broadcasting: s axis = rows (i), t axis = cols (j)
    S = s[:, np.newaxis, np.newaxis]   # (n,1,1)
    T = t[np.newaxis, :, np.newaxis]   # (1,n,1)

    grid = ((1 - T) * C_b[:, np.newaxis, :]    # (n,1,3)
            + T      * C_t[:, np.newaxis, :]
            + (1 - S) * C_l[np.newaxis, :, :]  # (1,n,3)
            + S       * C_r[np.newaxis, :, :]
            - ((1-S)*(1-T)*P00 + S*(1-T)*P10
               + S*T*P11 + (1-S)*T*P01))        # (n,n,3)

    pts = grid.reshape(-1, 3)

    cells = []
    for i in range(n - 1):
        for j in range(n - 1):
            a, b = i * n + j, (i+1) * n + j
            c, d = (i+1) * n + j+1, i * n + j+1
            cells += [3, a, b, c, 3, a, c, d]

    poly = pv.PolyData()
    poly.points = pts
    poly.faces = np.array(cells, dtype=np.int_)
    return poly



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
        for kind, pts in curved:
            if len(pts) < 2:
                continue
            if kind == 'arc':
                poly = pv.lines_from_points(pts)
                pl.add_mesh(poly, color='darkorange', line_width=3)
                if not arc_seen:
                    legend_entries.append(['Arc edges', 'darkorange', '-'])
                    arc_seen = True
            elif kind == 'spline':
                spline_poly = _make_spline_polydata(pts)
                pl.add_mesh(spline_poly, color='green', line_width=3)
                if not spline_seen:
                    legend_entries.append(['Spline edges', 'green', '-'])
                    spline_seen = True
            elif kind == 'polyline':
                poly = pv.lines_from_points(pts)
                pl.add_mesh(poly, color='teal', line_width=3)
                if not polyline_seen:
                    legend_entries.append(['PolyLine edges', 'teal', '-'])
                    polyline_seen = True
            elif kind == 'bspline':
                bspline_pts = _bspline_points(pts)
                poly = pv.lines_from_points(bspline_pts)
                pl.add_mesh(poly, color='purple', line_width=3)
                if not bspline_seen:
                    legend_entries.append(['BSpline edges', 'purple', '-'])
                    bspline_seen = True

        ctrl_cloud = _build_control_points(mesh)
        if ctrl_cloud.n_points > 0:
            pl.add_mesh(ctrl_cloud, color='gold', point_size=7,
                        render_points_as_spheres=True)
            legend_entries.append(['Edge ctrl pts', 'gold', 'circle'])

    # --- Block centroid labels ---
    if show_block_labels and mesh.blocks:
        _add_block_labels(pl, mesh, verts)

    # --- Boundary patch face highlights ---
    _add_boundary_patches(pl, mesh, verts,
                          opacity=0.35 if show_patch_faces else 0.0,
                          legend_entries=legend_entries)

    # --- Bounding box ---
    if show_bounding_box and verts:
        pl.add_bounding_box(color='gray', line_width=1)

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
        labels.append(f'B{i}')

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


def _add_boundary_patches(pl: pv.Plotter, mesh: BlockMesh, verts: list,
                          n_curved: int = 20, opacity: float = 0.35,
                          legend_entries: list | None = None) -> None:
    """Render boundary patch faces as semi-transparent coloured surfaces.

    Quad faces whose edges include a curved edge are tessellated via
    transfinite interpolation so the surface follows the arc/spline.
    Flat faces are rendered as simple quads.
    """
    if not mesh.patches or not verts:
        return

    palette = [
        '#e6194b', '#3cb44b', '#4363d8', '#f58231',
        '#911eb4', '#42d4f4', '#f032e6', '#bfef45',
        '#fabed4', '#469990', '#dcbeff', '#9a6324',
    ]

    verts_arr = np.array(verts)
    has_any_curved = bool(mesh.edges)

    for i, patch in enumerate(mesh.patches):
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

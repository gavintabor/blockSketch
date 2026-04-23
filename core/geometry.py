"""
Geometry helpers — edge interpolation, face tessellation.

Shared between the desktop viewer and any future web/batch frontends.
No Qt or display-framework dependency.
"""
import numpy as np
import pyvista as pv
from scipy.interpolate import BSpline as SciPyBSpline

from core.model import ArcEdge, BlockMesh, SplineEdge


# ---------------------------------------------------------------------------
# Arc interpolation
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
# Arc midpoint from origin format
# ---------------------------------------------------------------------------

def _arc_midpoint_from_origin(p0: np.ndarray, p1: np.ndarray,
                               centre: np.ndarray) -> np.ndarray:
    """Return the arc midpoint given circle centre instead of midpoint.

    Rotates p0 around the centre by half the subtended angle using
    Rodrigues' formula so the result lies exactly on the circle.
    """
    r0 = p0 - centre
    r1 = p1 - centre
    normal = np.cross(r0, r1)
    norm_len = np.linalg.norm(normal)
    if norm_len < 1e-15:
        return (p0 + p1) / 2.0   # degenerate — fall back to linear midpoint
    normal /= norm_len
    cos_a = np.clip(np.dot(r0, r1) / (np.linalg.norm(r0) * np.linalg.norm(r1)),
                    -1.0, 1.0)
    theta = np.arccos(cos_a) / 2.0
    c, s = np.cos(theta), np.sin(theta)
    rotated = (c * r0
               + s * np.cross(normal, r0)
               + (1 - c) * np.dot(normal, r0) * normal)
    return centre + rotated


# ---------------------------------------------------------------------------
# B-spline approximation
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
# Polyline arc-length sampler
# ---------------------------------------------------------------------------

def _polyline_sample(chain: np.ndarray, n: int) -> np.ndarray:
    """Sample *n* points uniformly by arc length along a piecewise-linear chain."""
    segs = np.linalg.norm(np.diff(chain, axis=0), axis=1)
    dists = np.concatenate([[0.0], np.cumsum(segs)])
    total = dists[-1]
    if total < 1e-15:
        return np.tile(chain[0], (n, 1))
    t = np.linspace(0.0, total, n)
    return np.column_stack([np.interp(t, dists, chain[:, i]) for i in range(3)])


# ---------------------------------------------------------------------------
# Edge chain builder
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


# ---------------------------------------------------------------------------
# Edge point sampler (with curve following)
# ---------------------------------------------------------------------------

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
            raw = np.array(edge.point) * mesh.scale
            if edge.is_origin:
                pmid = _arc_midpoint_from_origin(p0, p1, raw)
            else:
                pmid = raw
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


# ---------------------------------------------------------------------------
# Face curvature predicate
# ---------------------------------------------------------------------------

def _face_has_curved_edge(face: tuple, mesh: BlockMesh) -> bool:
    curved = {(min(e.v_start, e.v_end), max(e.v_start, e.v_end)) for e in mesh.edges}
    n = len(face)
    return any((min(face[i], face[(i+1) % n]), max(face[i], face[(i+1) % n])) in curved
               for i in range(n))


# ---------------------------------------------------------------------------
# Face tessellation
# ---------------------------------------------------------------------------

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
# Surface mesh builder (for display and future tetgen integration)
# ---------------------------------------------------------------------------

def build_surface_mesh(mesh: BlockMesh, verts: list,
                       n_curved: int = 50) -> pv.PolyData:
    """
    Build a triangulated surface mesh of all boundary patches,
    following curved edges where present.
    Returns a single merged pv.PolyData suitable for tetgen input.
    Used both for display (_add_boundary_patches) and tet mesh generation.
    """
    verts_arr = np.array(verts)
    pieces = []
    for patch in mesh.patches:
        for face in patch.faces:
            if not all(fi < len(verts) for fi in face):
                continue
            if len(face) == 4 and _face_has_curved_edge(face, mesh):
                poly = _tessellate_quad(face, mesh, verts, n=n_curved)
            else:
                local_pts = verts_arr[list(face)]
                cells = [len(face)] + list(range(len(face)))
                poly = pv.PolyData()
                poly.points = local_pts
                poly.faces = np.array(cells, dtype=np.int_)
            pieces.append(poly)
    if not pieces:
        return pv.PolyData()
    return pv.merge(pieces, merge_points=False) if len(pieces) > 1 else pieces[0]

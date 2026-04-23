"""
blockMeshDict serialiser — converts a BlockMesh model back to valid OpenFOAM text.
"""
from __future__ import annotations

from model import ArcEdge, Block, BlockMesh, BoundaryPatch, ProjectEdge, SplineEdge

# ---------------------------------------------------------------------------
# Number formatter
# ---------------------------------------------------------------------------

def _fmt(x) -> str:
    """Format a scalar for blockMeshDict output — integers stay integers."""
    if x is None:
        return '0'
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        if x == int(x) and abs(x) < 1e15:
            return str(int(x))
        return f'{x:.10g}'
    return str(x)


def _xyz(pt) -> str:
    return f'{_fmt(pt[0])} {_fmt(pt[1])} {_fmt(pt[2])}'


# ---------------------------------------------------------------------------
# Section writers
# ---------------------------------------------------------------------------

def _foam_header() -> str:
    top = '/*' + '-' * 32 + '*- C++ -*' + '-' * 34 + '*\\'
    bot = '\\*' + '-' * 75 + '*/'
    div = '// ' + '* ' * 37 + '//'
    return (
        f'{top}\n'
        f'{bot}\n'
        'FoamFile\n'
        '{\n'
        '    version     2.0;\n'
        '    format      ascii;\n'
        '    class       dictionary;\n'
        '    object      blockMeshDict;\n'
        '}\n'
        f'{div}'
    )


def _write_vertices(mesh: BlockMesh) -> str:
    lines = ['vertices', '(']
    for v in mesh.vertices:
        lines.append(f'    ({_fmt(v.x)} {_fmt(v.y)} {_fmt(v.z)})'
                     f'  // {v.index}')
    lines.append(');')
    return '\n'.join(lines)


def _fmt_grading(grading_type: str, grading: list) -> str:
    """Serialise grading data for simpleGrading or edgeGrading."""
    parts: list[str] = []
    for item in grading:
        if isinstance(item, list):
            if item and isinstance(item[0], list):
                # List of (n weight expansion) triples — multi-grading
                inner = ' '.join(
                    f'({" ".join(_fmt(x) for x in triple)})' for triple in item)
                parts.append(f'({inner})')
            else:
                # Single (n weight expansion) triple
                parts.append(f'({" ".join(_fmt(x) for x in item)})')
        elif item is not None:
            parts.append(_fmt(item))
    return f'{grading_type} ({" ".join(parts)})'


def _write_blocks(mesh: BlockMesh) -> str:
    lines = ['blocks', '(']
    for block in mesh.blocks:
        vids = ' '.join(str(v) for v in block.vertex_ids)
        nx, ny, nz = block.cells
        grading = _fmt_grading(block.grading_type, block.grading)
        lines.append(f'    hex ({vids}) ({nx} {ny} {nz}) {grading}')
    lines.append(');')
    return '\n'.join(lines)


def _write_edges(mesh: BlockMesh) -> str:
    lines = ['edges', '(']
    for edge in mesh.edges:
        if isinstance(edge, ArcEdge):
            lines.append(
                f'    arc {edge.v_start} {edge.v_end} ({_xyz(edge.point)})')
        elif isinstance(edge, SplineEdge):
            pts = '\n'.join(
                f'        ({_xyz(p)})' for p in edge.points)
            lines.append(
                f'    {edge.kind} {edge.v_start} {edge.v_end}\n'
                f'    (\n{pts}\n    )')
        elif isinstance(edge, ProjectEdge):
            lines.append(
                f'    project {edge.v_start} {edge.v_end} ({edge.surface})')
    lines.append(');')
    return '\n'.join(lines)


def _write_boundary(mesh: BlockMesh) -> str:
    lines = ['boundary', '(']
    for patch in mesh.patches:
        face_lines = '\n'.join(
            f'            ({" ".join(str(v) for v in face)})'
            for face in patch.faces)
        lines.append(
            f'    {patch.name}\n'
            f'    {{\n'
            f'        type {patch.patch_type};\n'
            f'        faces\n'
            f'        (\n'
            f'{face_lines}\n'
            f'        );\n'
            f'    }}')
    lines.append(');')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_blockmesh(mesh: BlockMesh) -> str:
    """Serialise *mesh* to a blockMeshDict string."""
    div = '// ' + '* ' * 37 + '//'
    sections = [
        _foam_header(),
        '',
        f'{mesh.scale_keyword} {_fmt(mesh.scale)};',
        '',
        _write_vertices(mesh),
        '',
        _write_blocks(mesh),
        '',
        _write_edges(mesh),
        '',
        _write_boundary(mesh),
        '',
        div,
        '',
    ]
    return '\n'.join(sections)

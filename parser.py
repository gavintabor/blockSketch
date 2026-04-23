"""
Parser for OpenFOAM blockMeshDict files.

Design goals:
- Tolerate incomplete / malformed input (best-effort parsing).
- No dependency on OpenFOAM libraries.
- Record warnings rather than raising hard errors where possible.
"""
import re
from typing import List, Optional, Tuple

from model import (
    ArcEdge, Block, BlockMesh, BoundaryPatch,
    Edge, ProjectEdge, SplineEdge, Vertex,
)


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r'//[^\n]*'                  # line comment
    r'|/\*.*?\*/'                # block comment  (non-greedy, re.DOTALL needed)
    r'|"[^"]*"'                  # quoted string
    r'|[(){};]'                  # single-char punctuation
    r'|[^\s(){};]+'              # word / number
    , re.DOTALL
)


def _tokenise(text: str) -> List[str]:
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok.startswith('//') or tok.startswith('/*'):
            continue  # discard comments
        tokens.append(tok)
    return tokens


class _TokenStream:
    def __init__(self, tokens: List[str]):
        self._tokens = tokens
        self._pos = 0

    def peek(self) -> Optional[str]:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def next(self) -> Optional[str]:
        tok = self.peek()
        if tok is not None:
            self._pos += 1
        return tok

    def expect(self, value: str) -> bool:
        """Consume a token that must equal *value*. Return False if it doesn't."""
        tok = self.next()
        if tok != value:
            return False
        return True

    def skip_to(self, *stoppers: str) -> None:
        """Advance until one of *stoppers* is seen (but don't consume it)."""
        while self.peek() is not None and self.peek() not in stoppers:
            self.next()

    def skip_balanced(self, open_: str = '(', close_: str = ')') -> None:
        """Skip a balanced pair starting at the current '(' (consumes it)."""
        depth = 0
        while self.peek() is not None:
            tok = self.next()
            if tok == open_:
                depth += 1
            elif tok == close_:
                depth -= 1
                if depth == 0:
                    return

    @property
    def pos(self) -> int:
        return self._pos


# ---------------------------------------------------------------------------
# Number / vector helpers
# ---------------------------------------------------------------------------

_VARIABLES: dict = {}   # module-level dict, reset per parse call


def _resolve(tok: Optional[str]) -> Optional[str]:
    """Replace $varName tokens with their string value, if known."""
    if tok is not None and tok.startswith('$'):
        name = tok[1:]
        return str(_VARIABLES.get(name))   # returns 'None' string if missing
    return tok


def _parse_float(tok: Optional[str]) -> Optional[float]:
    tok = _resolve(tok)
    if tok is None:
        return None
    try:
        return float(tok)
    except (ValueError, TypeError):
        return None


def _parse_int(tok: Optional[str]) -> Optional[int]:
    tok = _resolve(tok)
    if tok is None:
        return None
    try:
        return int(tok)
    except (ValueError, TypeError):
        return None


def _read_vector(ts: _TokenStream) -> Optional[Tuple[float, float, float]]:
    """Read  ( x y z )  and return a tuple, or None on failure."""
    if ts.peek() != '(':
        return None
    ts.next()  # consume '('
    x = _parse_float(ts.next())
    y = _parse_float(ts.next())
    z = _parse_float(ts.next())
    if ts.peek() == ')':
        ts.next()
    if None in (x, y, z):
        return None
    return (x, y, z)


def _read_int_list(ts: _TokenStream) -> Optional[List[int]]:
    """Read  ( i0 i1 ... )  and return a list of ints, or None on failure."""
    if ts.peek() != '(':
        return None
    ts.next()
    values = []
    while ts.peek() not in (None, ')'):
        v = _parse_int(ts.next())
        if v is None:
            return None
        values.append(v)
    if ts.peek() == ')':
        ts.next()
    return values


def _read_point_list(ts: _TokenStream) -> List[Tuple[float, float, float]]:
    """Read  ( (x y z) (x y z) ... )  returning a list of tuples."""
    points: List[Tuple[float, float, float]] = []
    if ts.peek() != '(':
        return points
    ts.next()  # outer '('
    while ts.peek() == '(':
        v = _read_vector(ts)
        if v is not None:
            points.append(v)
    if ts.peek() == ')':
        ts.next()  # outer ')'
    return points


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------

def _parse_vertices(ts: _TokenStream, mesh: BlockMesh) -> None:
    if ts.peek() != '(':
        mesh.warnings.append("vertices: expected '(' not found")
        return
    ts.next()
    idx = 0
    while ts.peek() not in (None, ')'):
        v = _read_vector(ts)
        if v is None:
            mesh.warnings.append(f"vertices[{idx}]: malformed, skipping rest")
            ts.skip_to(')')
            break
        mesh.vertices.append(Vertex(x=v[0], y=v[1], z=v[2], index=idx))
        idx += 1
    if ts.peek() == ')':
        ts.next()
    if ts.peek() == ';':
        ts.next()


def _parse_blocks(ts: _TokenStream, mesh: BlockMesh) -> None:
    if ts.peek() != '(':
        mesh.warnings.append("blocks: expected '(' not found")
        return
    ts.next()
    while ts.peek() not in (None, ')'):
        kind = ts.next()
        if kind != 'hex':
            mesh.warnings.append(f"blocks: unsupported block type '{kind}', skipping")
            # skip to end of this block entry (next keyword or outer ')')
            ts.skip_to(')', 'hex', 'simpleGrading', 'edgeGrading')
            continue
        # vertex ids
        vids = _read_int_list(ts)
        if vids is None or len(vids) != 8:
            mesh.warnings.append("blocks: bad vertex list in hex, skipping block")
            ts.skip_to(')', 'hex')
            continue
        # cell counts
        cells_raw = _read_int_list(ts)
        if cells_raw is None or len(cells_raw) < 3:
            mesh.warnings.append("blocks: bad cell count in hex, skipping block")
            ts.skip_to(')', 'hex')
            continue
        cells = (cells_raw[0], cells_raw[1], cells_raw[2])
        # grading
        grading_type = ts.next()
        if grading_type not in ('simpleGrading', 'edgeGrading'):
            mesh.warnings.append(
                f"blocks: unknown grading type '{grading_type}', defaulting"
            )
            grading_type = grading_type or 'simpleGrading'
        grading_raw = _read_grading(ts, mesh)
        mesh.blocks.append(Block(
            vertex_ids=vids,
            cells=cells,
            grading_type=grading_type,
            grading=grading_raw,
        ))
    if ts.peek() == ')':
        ts.next()
    if ts.peek() == ';':
        ts.next()


def _read_grading(ts: _TokenStream, mesh: BlockMesh) -> list:
    """Read grading data - either simple (x y z) or complex nested form."""
    if ts.peek() != '(':
        return []
    save = ts.pos
    # try to read as a flat 3-element list first
    depth_before = ts.pos
    outer = ts.next()  # '('
    vals = []
    try:
        while ts.peek() not in (None, ')'):
            if ts.peek() == '(':
                # nested grading list (edgeGrading) - read whole balanced group
                nested = []
                ts.next()  # inner '('
                while ts.peek() not in (None, ')'):
                    if ts.peek() == '(':
                        # multi-grading entry: (n weight expansion)
                        sub = _read_grading_entry(ts)
                        nested.append(sub)
                    else:
                        v = _parse_float(ts.next())
                        nested.append(v)
                if ts.peek() == ')':
                    ts.next()
                vals.append(nested)
            else:
                v = _parse_float(ts.next())
                vals.append(v)
        if ts.peek() == ')':
            ts.next()
    except Exception:
        pass
    return vals


def _read_grading_entry(ts: _TokenStream) -> list:
    """Read  ( n weight expansion )  nested grading entry."""
    ts.next()  # '('
    vals = []
    while ts.peek() not in (None, ')'):
        vals.append(_parse_float(ts.next()))
    if ts.peek() == ')':
        ts.next()
    return vals


def _parse_edges(ts: _TokenStream, mesh: BlockMesh) -> None:
    if ts.peek() != '(':
        mesh.warnings.append("edges: expected '(' not found")
        return
    ts.next()
    while ts.peek() not in (None, ')'):
        kind = ts.peek()
        if kind is None:
            break
        if kind in ('arc',):
            ts.next()
            v0 = _parse_int(ts.next())
            v1 = _parse_int(ts.next())
            pt = _read_vector(ts)
            if None not in (v0, v1) and pt is not None:
                mesh.edges.append(ArcEdge(v_start=v0, v_end=v1, point=pt))
            else:
                mesh.warnings.append(f"edges: malformed arc entry")
        elif kind in ('spline', 'polyLine', 'polySpline', 'BSpline', 'simpleSpline'):
            ts.next()
            v0 = _parse_int(ts.next())
            v1 = _parse_int(ts.next())
            pts = _read_point_list(ts)
            if None not in (v0, v1):
                mesh.edges.append(SplineEdge(kind=kind, v_start=v0, v_end=v1, points=pts))
            else:
                mesh.warnings.append(f"edges: malformed {kind} entry")
        elif kind in ('line',):
            ts.next()
            v0 = _parse_int(ts.next())
            v1 = _parse_int(ts.next())
            # 'line' edges are straight – nothing extra to store
        elif kind in ('project',):
            ts.next()
            v0 = _parse_int(ts.next())
            v1 = _parse_int(ts.next())
            surface_list = _read_int_list(ts)  # actually a name list
            surface = str(surface_list[0]) if surface_list else ''
            if None not in (v0, v1):
                mesh.edges.append(ProjectEdge(v_start=v0, v_end=v1, surface=surface))
        else:
            mesh.warnings.append(f"edges: unknown edge type '{kind}', skipping")
            ts.next()
    if ts.peek() == ')':
        ts.next()
    if ts.peek() == ';':
        ts.next()


def _parse_boundary(ts: _TokenStream, mesh: BlockMesh) -> None:
    if ts.peek() != '(':
        mesh.warnings.append("boundary: expected '(' not found")
        return
    ts.next()
    while ts.peek() not in (None, ')'):
        name = ts.next()
        if name == ')':
            break
        if ts.peek() != '{':
            mesh.warnings.append(f"boundary: expected '{{' after patch name '{name}'")
            ts.skip_to('}', ')')
            if ts.peek() == '}':
                ts.next()
            continue
        ts.next()  # '{'
        patch_type = 'patch'
        faces: list = []
        while ts.peek() not in (None, '}'):
            key = ts.next()
            if key == 'type':
                t = ts.next()
                if t:
                    patch_type = t
                if ts.peek() == ';':
                    ts.next()
            elif key == 'faces':
                if ts.peek() == '(':
                    ts.next()  # outer '('
                    while ts.peek() == '(':
                        face = _read_int_list(ts)
                        if face:
                            faces.append(tuple(face))
                    if ts.peek() == ')':
                        ts.next()
                if ts.peek() == ';':
                    ts.next()
            elif key == ';':
                pass
            else:
                # unknown key – skip value up to ';'
                ts.skip_to(';', '}')
                if ts.peek() == ';':
                    ts.next()
        if ts.peek() == '}':
            ts.next()
        mesh.patches.append(BoundaryPatch(name=name, patch_type=patch_type, faces=faces))
    if ts.peek() == ')':
        ts.next()
    if ts.peek() == ';':
        ts.next()


# ---------------------------------------------------------------------------
# Top-level FoamFile header skip
# ---------------------------------------------------------------------------

def _skip_foam_header(ts: _TokenStream) -> None:
    """Consume optional FoamFile { ... } header block."""
    if ts.peek() == 'FoamFile':
        ts.next()
        if ts.peek() == '{':
            ts.skip_balanced('{', '}')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_KNOWN_KEYWORDS = frozenset({
    'FoamFile', 'scale', 'convertToMeters',
    'vertices', 'blocks', 'edges', 'boundary', 'patches',
    'geometry', 'defaultPatch', 'mergeType', 'mergedMeshes',
})


def _collect_variables(tokens: List[str]) -> None:
    """Pre-pass: collect simple  name value ;  variable definitions."""
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        # Skip the FoamFile block
        if tok == 'FoamFile':
            i += 1
            depth = 0
            while i < n:
                if tokens[i] == '{':
                    depth += 1
                elif tokens[i] == '}':
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            continue
        # Potential variable: identifier (no $, not a keyword), followed by
        # a numeric literal, followed by ';'
        if (tok not in _KNOWN_KEYWORDS
                and not tok.startswith('$')
                and tok not in ('{', '}', '(', ')', ';')
                and i + 2 < n
                and tokens[i + 2] == ';'):
            val_tok = tokens[i + 1]
            try:
                _VARIABLES[tok] = float(val_tok)
                i += 3
                continue
            except ValueError:
                pass
        i += 1


def parse(text: str) -> BlockMesh:
    """Parse *text* as a blockMeshDict and return a :class:`BlockMesh`.

    Partial / malformed input is tolerated; issues are recorded in
    ``BlockMesh.warnings``.
    """
    global _VARIABLES
    _VARIABLES = {}   # reset for this parse call

    tokens = _tokenise(text)
    _collect_variables(tokens)

    ts = _TokenStream(tokens)
    mesh = BlockMesh()

    _skip_foam_header(ts)

    # Scan for recognised top-level keywords (order-independent)
    seen = set()
    while ts.peek() is not None:
        kw = ts.next()
        if kw is None:
            break

        if kw == 'scale' and 'scale' not in seen:
            seen.add('scale')
            val = _parse_float(ts.next())
            if val is not None:
                mesh.scale = val
                mesh.scale_keyword = 'scale'
            if ts.peek() == ';':
                ts.next()

        elif kw == 'convertToMeters' and 'scale' not in seen:
            seen.add('scale')
            val = _parse_float(ts.next())
            if val is not None:
                mesh.scale = val
                mesh.scale_keyword = 'convertToMeters'
            if ts.peek() == ';':
                ts.next()

        elif kw == 'vertices' and 'vertices' not in seen:
            seen.add('vertices')
            _parse_vertices(ts, mesh)

        elif kw == 'blocks' and 'blocks' not in seen:
            seen.add('blocks')
            _parse_blocks(ts, mesh)

        elif kw == 'edges' and 'edges' not in seen:
            seen.add('edges')
            _parse_edges(ts, mesh)

        elif kw == 'boundary' and 'boundary' not in seen:
            seen.add('boundary')
            _parse_boundary(ts, mesh)

        elif kw == 'patches' and 'boundary' not in seen:
            # older-style patches keyword
            seen.add('boundary')
            _parse_boundary(ts, mesh)

        elif kw in ('{', '}', '(', ')', ';'):
            pass  # stray punctuation – ignore

        # else: unknown keyword or variable definition – skip

    return mesh


def parse_file(path: str) -> BlockMesh:
    """Read a file and parse it."""
    with open(path, 'r', errors='replace') as fh:
        text = fh.read()
    return parse(text)

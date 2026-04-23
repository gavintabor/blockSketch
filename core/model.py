"""
Data model for blockMeshDict contents.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union
import numpy as np


@dataclass
class Vertex:
    x: float
    y: float
    z: float
    index: int

    def as_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z])


@dataclass
class Block:
    vertex_ids: List[int]          # 8 vertex indices (hex)
    cells: Tuple[int, int, int]    # (nx, ny, nz)
    grading_type: str              # 'simpleGrading' | 'edgeGrading'
    grading: list                  # raw grading data
    zone_name: str = ''            # cell zone (optional, written only if non-empty)

    HEX_EDGES = [
        (0, 1), (1, 2), (2, 3), (3, 0),   # bottom face
        (4, 5), (5, 6), (6, 7), (7, 4),   # top face
        (0, 4), (1, 5), (2, 6), (3, 7),   # pillars
    ]

    def edge_vertex_pairs(self) -> List[Tuple[int, int]]:
        """Return (global_v0, global_v1) pairs for all 12 edges."""
        return [
            (self.vertex_ids[a], self.vertex_ids[b])
            for a, b in self.HEX_EDGES
        ]


@dataclass
class ArcEdge:
    """arc vStart vEnd (px py pz)  — midpoint on arc (default)
    arc vStart vEnd origin (cx cy cz) — circle centre"""
    v_start: int
    v_end: int
    point: Tuple[float, float, float]
    is_origin: bool = False   # True → point is circle centre, False → midpoint on arc


@dataclass
class SplineEdge:
    """spline / polyLine / BSpline vStart vEnd ((p1...) ...)"""
    kind: str   # 'spline', 'polyLine', 'BSpline', 'polySpline'
    v_start: int
    v_end: int
    points: List[Tuple[float, float, float]]


@dataclass
class ProjectEdge:
    """project vStart vEnd (surfaceName)"""
    v_start: int
    v_end: int
    surface: str


Edge = Union[ArcEdge, SplineEdge, ProjectEdge]


@dataclass
class BoundaryPatch:
    name: str
    patch_type: str
    faces: List[Tuple[int, ...]]


@dataclass
class BlockMesh:
    scale: float = 1.0
    scale_keyword: str = 'scale'   # 'scale' or 'convertToMeters' — preserved on write-back
    vertices: List[Vertex] = field(default_factory=list)
    blocks: List[Block] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    patches: List[BoundaryPatch] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    default_patch_name: str = ''
    default_patch_type: str = 'patch'
    merge_patch_pairs: List[Tuple[str, str]] = field(default_factory=list)

    def scaled_vertices(self) -> List[np.ndarray]:
        return [v.as_array() * self.scale for v in self.vertices]

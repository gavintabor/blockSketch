"""
Meshing panel — blockMesh / checkMesh / boundary layers (Tab 1)
                and tet mesh via tetgen (Tab 2).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame, QScrollArea,
    QCheckBox, QLineEdit, QSizePolicy, QGridLayout,
    QDialog, QDialogButtonBox, QMessageBox,
    QTabWidget, QRadioButton, QButtonGroup,
)
from PyQt6.QtCore import Qt, QProcess, pyqtSignal, QThread
from PyQt6.QtGui import QTextCursor, QFont

from core.model import BlockMesh
from core.geometry import (build_surface_mesh, _tessellate_quad,
                           _face_has_curved_edge)

try:
    import tetgen as _tetgen      # noqa: F401
    TET_AVAILABLE = True
except ImportError:
    TET_AVAILABLE = False

ACCENT = '#6030a0'
PASTEL = '#e8d8f8'
GREEN  = '#1a6b30'
AMBER  = '#8a5c00'
RED    = '#a02010'

_DENSITY_LABELS   = ['Coarse', 'Medium', 'Fine', 'Custom']
_DENSITY_DIVISORS = [100, 1000, 10000, None]   # None → custom entry
_DENSITY_HINTS    = [
    'Coarse — maxvolume = V / 100',
    'Medium — maxvolume = V / 1,000',
    'Fine — maxvolume = V / 10,000',
    'Custom — enter maxvolume directly',
]

# Quality metric thresholds — (ok_limit, warn_limit).
_THRESHOLDS: dict[str, tuple[float, float]] = {
    'Max aspect ratio':      ( 5.0,  20.0),
    'Max non-orthogonality': (70.0,  85.0),
    'Max skewness':          ( 4.0,  20.0),
}

_QUALITY_RE: dict[str, re.Pattern] = {
    'Max aspect ratio':      re.compile(
        r'Max aspect ratio\s*=\s*([\d.eE+\-]+)'),
    'Max non-orthogonality': re.compile(
        r'(?:Max non-orthogonality\s*=\s*|Mesh non-orthogonality Max:\s*)([\d.eE+\-]+)'),
    'Max skewness':          re.compile(
        r'Max skewness\s*=\s*([\d.eE+\-]+)'),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_of_version() -> str:
    """Detect the installed OpenFOAM branch and version."""
    try:
        r = subprocess.run(
            ['foamVersion'], capture_output=True, text=True, timeout=5)
        v = (r.stdout.strip() or r.stderr.strip()).lstrip('v')
        if v:
            return f'OpenFOAM version: {v} (ESI/openfoam.com)'
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        r2 = subprocess.run(
            ['of-version'], capture_output=True, text=True, timeout=5)
        v2 = (r2.stdout.strip() or r2.stderr.strip()).lstrip('v')
        if v2:
            return f'OpenFOAM version: {v2} (Foundation/openfoam.org)'
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ('OpenFOAM version: unknown'
            ' — if errors occur check your OF installation')


def _colour_for(metric: str, value: float) -> str:
    ok, warn = _THRESHOLDS[metric]
    if value <= ok:
        return GREEN
    if value <= warn:
        return AMBER
    return RED


def _case_dir_from_path(mesh_path: str) -> str:
    """Derive the OpenFOAM case directory from the blockMeshDict path."""
    parent = os.path.dirname(mesh_path)
    if os.path.basename(parent) == 'system':
        return os.path.dirname(parent)
    return parent


# ---------------------------------------------------------------------------
# snappyHexMeshDict generation helpers
# ---------------------------------------------------------------------------

def _build_layers_block(checked: list[tuple[str, int, float]]) -> str:
    return '\n'.join(
        f'        {name}\n'
        f'        {{\n'
        f'            nSurfaceLayers {n};\n'
        f'            expansionRatio  {exp};\n'
        f'        }}'
        for name, n, exp in checked
    )


def _build_add_layers_controls(layers_block: str) -> str:
    lines = [
        'addLayersControls',
        '{',
        '    relativeSizes               true;',
        '',
        '    layers',
        '    {',
        layers_block,
        '    }',
        '',
        '    expansionRatio              1.2;',
        '    finalLayerThickness         0.3;',
        '    minThickness                0.1;',
        '    nGrow                       0;',
        '',
        '    featureAngle                60;',
        '    slipFeatureAngle            30;',
        '    nRelaxIter                  3;',
        '    nSmoothSurfaceNormals       1;',
        '    nSmoothNormals              3;',
        '    nSmoothThickness            10;',
        '    maxFaceThicknessRatio       0.5;',
        '    maxThicknessToMedialRatio   0.3;',
        '    minMedialAxisAngle          90;',
        '    nBufferCellsNoExtrude       0;',
        '    nLayerIter                  50;',
        '    nRelaxedIter                20;',
        '}',
    ]
    return '\n'.join(lines)


def _snappy_dict_content(layers_block: str) -> str:
    """Complete snappyHexMeshDict for boundary layer addition only (OF 2406 ESI)."""
    alc = _build_add_layers_controls(layers_block)
    header = (
        '/*--------------------------------*- C++ -*----------------------------------*\\\n'
        '  =========                 |\n'
        '  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox\n'
        '   \\    /   O peration     | blockSketch generated\n'
        '    \\  /    A nd           |\n'
        '     \\/     M anipulation  |\n'
        '\\*---------------------------------------------------------------------------*/\n'
        'FoamFile\n'
        '{\n'
        '    version     2.0;\n'
        '    format      ascii;\n'
        '    class       dictionary;\n'
        '    object      snappyHexMeshDict;\n'
        '}\n'
        '// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n'
    )
    body = (
        '\ncastellatedMesh false;\n'
        'snap            false;\n'
        'addLayers       true;\n'
        '\n'
        'geometry\n'
        '{\n'
        '}\n'
        '\n'
        'castellatedMeshControls\n'
        '{\n'
        '    maxLocalCells           100000;\n'
        '    maxGlobalCells          2000000;\n'
        '    minRefinementCells      0;\n'
        '    maxLoadUnbalance        0.10;\n'
        '    nCellsBetweenLevels     3;\n'
        '\n'
        '    features                ( );\n'
        '    refinementSurfaces      { }\n'
        '    refinementRegions       { }\n'
        '    resolveFeatureAngle     30;\n'
        '    allowFreeStandingZoneFaces true;\n'
        '    locationInMesh          (0 0 0);\n'
        '}\n'
        '\n'
        'snapControls\n'
        '{\n'
        '    nSmoothPatch            3;\n'
        '    tolerance               2.0;\n'
        '    nSolveIter              30;\n'
        '    nRelaxIter              5;\n'
        '    nFeatureSnapIter        10;\n'
        '    implicitFeatureSnap     false;\n'
        '    explicitFeatureSnap     true;\n'
        '    multiRegionFeatureSnap  false;\n'
        '}\n'
        '\n'
    )
    quality = (
        '\n'
        'meshQualityControls\n'
        '{\n'
        '    maxNonOrtho             65;\n'
        '    maxBoundarySkewness     20;\n'
        '    maxInternalSkewness     4;\n'
        '    maxConcave              80;\n'
        '    minVol                  1e-13;\n'
        '    minTetQuality           1e-15;\n'
        '    minArea                 -1;\n'
        '    minTwist                0.05;\n'
        '    minDeterminant          0.001;\n'
        '    minFaceWeight           0.05;\n'
        '    minVolRatio             0.01;\n'
        '    minTriangleTwist        -1;\n'
        '\n'
        '    relaxed\n'
        '    {\n'
        '        maxNonOrtho     75;\n'
        '    }\n'
        '\n'
        '    nSmoothScale            4;\n'
        '    errorReduction          0.75;\n'
        '}\n'
        '\n'
        'debug           0;\n'
        'mergeTolerance  1e-6;\n'
        '\n'
        '// ************************************************************************* //\n'
    )
    return header + body + alc + quality


# ---------------------------------------------------------------------------
# Tetgen surface preparation
# ---------------------------------------------------------------------------

def _build_tetgen_surface(mesh: BlockMesh, verts: list,
                          n_curved: int = 20):
    """Build a triangulated surface for tetgen with 1-based patch index markers.

    ALL quad faces are tessellated with _tessellate_quad at n_curved resolution,
    not just curved ones.  This ensures shared edges between adjacent faces (one
    curved, one flat) sample the same n points — straight edges both produce
    np.linspace(p0,p1,n), curved edges both call the same _get_edge_points result.
    After merging with merge_points=False, .clean() can then collapse the
    coincident shared-edge points and produce a closed, watertight surface.

    Returns (merged, cleaned): merged has patch_marker cell data intact;
    cleaned is merged.clean(tolerance=1e-6) and is used for both the
    watertight check and as the tetgen input.
    """
    import pyvista as pv
    verts_arr = np.array(verts)
    pieces = []

    for patch_idx, patch in enumerate(mesh.patches):
        marker = patch_idx + 1
        for face in patch.faces:
            if not all(fi < len(verts) for fi in face):
                continue
            if len(face) == 4:
                poly = _tessellate_quad(face, mesh, verts, n=n_curved)
            else:
                local_pts = verts_arr[list(face)]
                cells = np.array([len(face)] + list(range(len(face))))
                poly = pv.PolyData(local_pts, cells)
            poly = poly.triangulate()
            poly.cell_data['patch_marker'] = np.full(
                poly.n_cells, marker, dtype=np.int32)
            pieces.append(poly)

    if not pieces:
        return pv.PolyData(), pv.PolyData()

    merged = pieces[0]
    for p in pieces[1:]:
        merged = merged.merge(p, merge_points=False)
    cleaned = merged.clean(tolerance=1e-6)
    return merged, cleaned


# ---------------------------------------------------------------------------
# Tetgen worker thread
# ---------------------------------------------------------------------------

class _TetWorker(QThread):
    # Emits (grid, node, elem, trifaces, triface_markers)
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, points, faces, face_markers, minratio: float,
                 maxvolume: float, mindihedral: float):
        super().__init__()
        self._points       = points
        self._faces        = faces
        self._face_markers = face_markers
        self._minratio     = minratio
        self._maxvolume    = maxvolume
        self._mindihedral  = mindihedral

    def run(self) -> None:
        try:
            import tetgen
            tet = tetgen.TetGen(self._points, self._faces, self._face_markers)
            switches = f'pq{self._minratio}/{self._mindihedral}a{self._maxvolume}'
            tet.tetrahedralize(switches=switches)
            markers = tet.triface_markers
            self.finished.emit(
                (tet.grid, tet.node, tet.elem, tet.trifaces, markers))
        except Exception as exc:
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# MeshingPanel
# ---------------------------------------------------------------------------

class MeshingPanel(QWidget):

    status_message = pyqtSignal(str, str)   # message, level ('ok'|'warning'|'error')
    tet_mesh_ready = pyqtSignal(object)     # pv.UnstructuredGrid — display in viewport

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._case_dir: str = ''
        self._mesh: BlockMesh | None = None
        self._bm_success: bool = False
        self._patch_rows: list[tuple[QCheckBox, QLineEdit, QLineEdit]] = []
        self._of_version: str | None = None

        self._tet_grid:           object       = None   # pv.UnstructuredGrid once generated
        self._tet_patch_names:    list[str]    = []
        self._tet_worker: _TetWorker | None    = None
        self._tet_node:           object       = None   # np.ndarray — output nodes
        self._tet_elem:           object       = None   # np.ndarray — output tets
        self._tet_trifaces:       object       = None   # np.ndarray — boundary face indices
        self._tet_triface_markers: object      = None   # np.ndarray — per-face patch markers

        self._bm_process    = QProcess(self)
        self._cm_process    = QProcess(self)
        self._layer_process = QProcess(self)
        self._cm_context: str = 'post_bm'
        self._setup_processes()

        self._build_ui()

    # ------------------------------------------------------------------
    # Qt event overrides
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._of_version is None:
            self._of_version = _detect_of_version()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_case_dir(self, path: str) -> None:
        self._case_dir = path
        self._update_restore_btn()

    def load_mesh(self, mesh: BlockMesh) -> None:
        self._mesh = mesh
        self._rebuild_patch_list()
        self._update_maxvolume_display()

    def set_topology_errors(self, has_errors: bool) -> None:
        self._run_bm_btn.setEnabled(not has_errors)
        if has_errors:
            self._run_bm_btn.setToolTip('Fix topology errors before running blockMesh.')
        else:
            self._run_bm_btn.setToolTip('')

    # ------------------------------------------------------------------
    # Process setup
    # ------------------------------------------------------------------

    def _setup_processes(self) -> None:
        for proc in (self._bm_process, self._cm_process, self._layer_process):
            proc.setProcessChannelMode(
                QProcess.ProcessChannelMode.MergedChannels)

        self._bm_process.readyReadStandardOutput.connect(self._on_bm_output)
        self._bm_process.finished.connect(self._on_bm_finished)

        self._cm_process.readyReadStandardOutput.connect(self._on_cm_output)
        self._cm_process.finished.connect(self._on_cm_finished)

        self._layer_process.readyReadStandardOutput.connect(self._on_layer_output)
        self._layer_process.finished.connect(self._on_layer_finished)

    # ------------------------------------------------------------------
    # UI construction — top-level
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #ddd; border-radius: 3px;
                background: #f7f5f0;
            }
            QTabBar::tab {
                background: #e0d8f0; color: #5a4080;
                border: 1px solid #ddd; border-bottom: none;
                border-top-left-radius: 3px; border-top-right-radius: 3px;
                padding: 4px 14px; font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #f7f5f0; color: #6030a0; font-weight: bold;
            }
            QTabBar::tab:hover:!selected { background: #ede8f8; }
        """)
        self._tabs.addTab(self._make_blockmesh_tab(), 'blockMesh')
        self._tabs.addTab(self._make_tet_tab(),       'tetgen')
        layout.addWidget(self._tabs, stretch=2)

        layout.addWidget(self._make_quality_section())
        layout.addWidget(self._make_shared_log(), stretch=1)

    # ------------------------------------------------------------------
    # Tab 1 — blockMesh
    # ------------------------------------------------------------------

    def _make_blockmesh_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        lay.addLayout(self._make_section_header('MESHING'))

        self._run_bm_btn = QPushButton('▶  Run blockMesh')
        self._run_bm_btn.setStyleSheet(self._primary_btn_style())
        self._run_bm_btn.clicked.connect(self._on_run_blockmesh)
        lay.addWidget(self._run_bm_btn)

        lay.addWidget(self._make_hsep())
        lay.addLayout(self._make_layers_section())
        lay.addStretch()
        return tab

    # ------------------------------------------------------------------
    # Tab 2 — Tet mesh
    # ------------------------------------------------------------------

    def _make_tet_tab(self) -> QWidget:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Install hint (shown when tetgen not installed)
        if not TET_AVAILABLE:
            hint = QLabel(
                'Requires tetgen:\n'
                '  pip install tetgen'
            )
            hint.setStyleSheet(
                'color: #a06010; font-size: 11px; font-family: monospace;'
                ' background: #fff8e8; border: 1px solid #e8c060;'
                ' border-radius: 3px; padding: 6px;')
            hint.setWordWrap(True)
            lay.addWidget(hint)

        lay.addLayout(self._make_section_header('TET MESH'))
        lay.addWidget(self._make_density_section())
        lay.addWidget(self._make_advanced_section())

        # Generate button + display checkbox
        self._generate_btn = QPushButton('▶  Generate tet mesh')
        self._generate_btn.setEnabled(TET_AVAILABLE)
        self._generate_btn.setStyleSheet(self._primary_btn_style())
        self._generate_btn.clicked.connect(self._on_generate_tet)
        lay.addWidget(self._generate_btn)

        self._display_tet_cb = QCheckBox('Display tet mesh in viewport')
        self._display_tet_cb.setChecked(True)
        self._display_tet_cb.setStyleSheet('color: #222; font-size: 12px;')
        lay.addWidget(self._display_tet_cb)

        lay.addWidget(self._make_hsep())

        # Write button + save tetgen files checkbox
        self._write_tet_btn = QPushButton('Write to OpenFOAM')
        self._write_tet_btn.setEnabled(False)
        self._write_tet_btn.setStyleSheet(self._secondary_btn_style())
        self._write_tet_btn.clicked.connect(self._on_write_tet)
        lay.addWidget(self._write_tet_btn)

        self._save_tetgen_cb = QCheckBox('Also save tetgen files (.node, .ele)')
        self._save_tetgen_cb.setChecked(False)
        self._save_tetgen_cb.setStyleSheet('color: #222; font-size: 12px;')
        lay.addWidget(self._save_tetgen_cb)

        lay.addStretch()
        return tab

    def _make_density_section(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # Radio buttons: Coarse | Medium | Fine | Custom
        radio_row = QHBoxLayout()
        radio_row.setContentsMargins(0, 0, 0, 0)
        self._density_bg = QButtonGroup(box)
        for i, text in enumerate(_DENSITY_LABELS):
            rb = QRadioButton(text)
            rb.setStyleSheet(f'color: #444; font-size: 12px;')
            if i == 0:
                rb.setChecked(True)
            self._density_bg.addButton(rb, i)
            radio_row.addWidget(rb, stretch=1)
        lay.addLayout(radio_row)

        self._density_bg.idToggled.connect(self._on_density_changed)

        # maxvolume field — always visible; read-only for Coarse/Medium/Fine,
        # editable for Custom
        self._maxvol_edit = QLineEdit()
        self._maxvol_edit.setPlaceholderText('maxvolume')
        self._maxvol_edit.setReadOnly(True)
        self._maxvol_edit.setStyleSheet(_field_style() + """
            QLineEdit[readOnly="true"] {
                background: #f0f0f0; color: #666;
            }
        """)
        lay.addWidget(self._maxvol_edit)

        # Hint label
        self._density_hint = QLabel(_DENSITY_HINTS[0])
        self._density_hint.setStyleSheet(
            'color: #888; font-size: 11px; font-style: italic;')
        self._density_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._density_hint)

        self._update_maxvolume_display()
        return box

    def _make_advanced_section(self) -> QWidget:
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        toggle = QPushButton('▸ Advanced quality settings')
        toggle.setCheckable(True)
        toggle.setChecked(False)
        toggle.setFlat(True)
        toggle.setStyleSheet(f"""
            QPushButton {{
                color: {ACCENT}; font-size: 11px; text-align: left;
                background: transparent; border: none; padding: 2px 0;
            }}
            QPushButton:hover {{ color: #4a2080; }}
        """)

        container = QWidget()
        container.setVisible(False)
        grid = QGridLayout(container)
        grid.setContentsMargins(8, 4, 0, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        for row_i, (label, default) in enumerate(
                [('minratio', '1.5'), ('mindihedral', '20')]):
            lbl = QLabel(label)
            lbl.setStyleSheet('color: #444; font-size: 12px;')
            grid.addWidget(lbl, row_i, 0)
            edit = QLineEdit(default)
            edit.setFixedWidth(60)
            edit.setStyleSheet(_field_style())
            grid.addWidget(edit, row_i, 1)
            if label == 'minratio':
                self._minratio_edit = edit
            else:
                self._mindihedral_edit = edit

        def _toggle(checked: bool) -> None:
            container.setVisible(checked)
            toggle.setText(
                ('▾ ' if checked else '▸ ') + 'Advanced quality settings')

        toggle.toggled.connect(_toggle)
        outer.addWidget(toggle)
        outer.addWidget(container)
        return box

    # ------------------------------------------------------------------
    # Density / maxvolume helpers
    # ------------------------------------------------------------------

    def _bbox_volume(self) -> float | None:
        if self._mesh is None:
            return None
        verts = self._mesh.scaled_vertices()
        if not verts:
            return None
        pts = np.array(verts)
        diffs = pts.max(axis=0) - pts.min(axis=0)
        vol = float(np.prod(diffs))
        return vol if vol > 0 else None

    def _on_density_changed(self, pos: int, checked: bool) -> None:
        if not checked:
            return
        is_custom = (pos == 3)
        self._maxvol_edit.setReadOnly(not is_custom)
        self._maxvol_edit.setStyleSheet(_field_style() + (
            "" if is_custom else
            "QLineEdit[readOnly=\"true\"] { background: #f0f0f0; color: #666; }"
        ))
        self._density_hint.setText(_DENSITY_HINTS[pos])
        if is_custom:
            self._maxvol_edit.clear()
            self._maxvol_edit.setFocus()
        else:
            self._update_maxvolume_display()

    def _update_maxvolume_display(self) -> None:
        pos = self._density_bg.checkedId() if hasattr(self, '_density_bg') else 0
        if pos == 3:
            return
        vol = self._bbox_volume()
        divisor = _DENSITY_DIVISORS[pos]
        if vol is not None:
            self._maxvol_edit.setText(f'{vol / divisor:.3g}')
        else:
            self._maxvol_edit.setText('')

    def _get_maxvolume(self) -> float | None:
        try:
            return float(self._maxvol_edit.text())
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Shared quality section and log
    # ------------------------------------------------------------------

    def _make_quality_section(self) -> QFrame:
        box = QFrame()
        box.setStyleSheet("""
            QFrame {
                background: #f7f5f0;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
        """)
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)

        sub = QLabel('MESH QUALITY')
        sub.setStyleSheet('color: #888; font-size: 10px; letter-spacing: 2px; border: none;')
        grid.addWidget(sub, 0, 0, 1, 2)

        self._quality_labels: dict[str, QLabel] = {}
        for row_i, metric in enumerate(_THRESHOLDS, start=1):
            name_lbl = QLabel(metric)
            name_lbl.setStyleSheet('color: #444; font-size: 12px; border: none;')
            grid.addWidget(name_lbl, row_i, 0)

            val_lbl = QLabel('—')
            val_lbl.setStyleSheet('color: #888; font-size: 12px; border: none;')
            val_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(val_lbl, row_i, 1)
            self._quality_labels[metric] = val_lbl

        return box

    def _make_shared_log(self) -> QTextEdit:
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont('Monospace', 9))
        self._log.setStyleSheet("""
            QTextEdit {
                background: white; color: #111;
                border: 1px solid #ccc; border-radius: 3px;
                padding: 4px;
            }
        """)
        self._log.setMinimumHeight(100)
        self._log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return self._log

    # ------------------------------------------------------------------
    # blockMesh section helpers
    # ------------------------------------------------------------------

    def _make_section_header(self, text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f'color: {ACCENT}; font-weight: bold; font-size: 11px;'
            ' letter-spacing: 2px;')
        row.addWidget(lbl)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f'color: {ACCENT};')
        row.addWidget(sep)
        return row

    def _make_layers_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(6)

        hdr = self._make_section_header('BOUNDARY LAYERS')

        def _show_layers_help():
            dlg = QDialog()
            dlg.setWindowTitle('Boundary layers')
            vlay = QVBoxLayout(dlg)
            lbl = QLabel(
                '<pre style="font-family: Courier, monospace; font-size: 12px;">'
                'Select wall patches and set layer parameters,\n'
                'then run layer addition after a successful\n'
                'blockMesh run.\n'
                '\n'
                'Boundary layers are applied to wall patches only.\n'
                'Other patch types (patch, empty, cyclic, wedge,\n'
                'symmetry, symmetryPlane) are excluded.\n'
                '\n'
                'This functionality uses snappyHexMesh to build\n'
                'the boundary layer mesh, which may not work\n'
                'perfectly for all cases.'
                '</pre>'
            )
            vlay.addWidget(lbl)
            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btns.accepted.connect(dlg.accept)
            vlay.addWidget(btns)
            dlg.adjustSize()
            dlg.exec()

        info_btn = QPushButton('ⓘ')
        info_btn.setFixedSize(20, 20)
        info_btn.setStyleSheet("""
            QPushButton {
                color: #888; font-size: 12px; background: transparent;
                border: none; padding: 0;
            }
            QPushButton:hover { color: #555; }
        """)
        info_btn.clicked.connect(_show_layers_help)
        hdr.addWidget(info_btn)

        section.addLayout(hdr)

        self._patch_scroll = QScrollArea()
        self._patch_scroll.setWidgetResizable(True)
        self._patch_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._patch_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._patch_scroll.setMaximumHeight(180)

        self._patch_container = QWidget()
        self._patch_layout = QVBoxLayout(self._patch_container)
        self._patch_layout.setContentsMargins(0, 0, 0, 0)
        self._patch_layout.setSpacing(3)

        self._no_walls_label = QLabel(
            'No wall patches defined — add wall patches in the Patches panel.')
        self._no_walls_label.setStyleSheet(
            'color: #aaa; font-size: 11px; font-style: italic;')
        self._no_walls_label.setWordWrap(True)
        self._no_walls_label.setVisible(False)
        self._patch_layout.addWidget(self._no_walls_label)
        self._patch_layout.addStretch()

        self._patch_scroll.setWidget(self._patch_container)
        section.addWidget(self._patch_scroll)

        self._run_layer_btn = QPushButton('▶  Run layer addition')
        self._run_layer_btn.setEnabled(False)
        self._run_layer_btn.setToolTip(
            'Run blockMesh successfully before adding boundary layers.')
        self._run_layer_btn.setStyleSheet(self._primary_btn_style())
        self._run_layer_btn.clicked.connect(self._on_run_layers)
        section.addWidget(self._run_layer_btn)

        self._restore_mesh_btn = QPushButton('↩  Restore original mesh')
        self._restore_mesh_btn.setEnabled(False)
        self._restore_mesh_btn.setToolTip(
            'Copy constant/polyMesh_noLayers back to constant/polyMesh, '
            'removing the boundary layers.')
        self._restore_mesh_btn.setStyleSheet(self._secondary_btn_style())
        self._restore_mesh_btn.clicked.connect(self._on_restore_mesh)
        section.addWidget(self._restore_mesh_btn)

        return section

    # ------------------------------------------------------------------
    # Patch list
    # ------------------------------------------------------------------

    def _rebuild_patch_list(self) -> None:
        for i in reversed(range(self._patch_layout.count())):
            item = self._patch_layout.itemAt(i)
            if item and item.widget() and item.widget() is not self._no_walls_label:
                item.widget().deleteLater()
                self._patch_layout.takeAt(i)
        self._patch_rows.clear()

        if self._mesh is None:
            self._no_walls_label.setVisible(False)
            return

        wall_patches = [p for p in self._mesh.patches if p.patch_type == 'wall']

        if not wall_patches:
            self._no_walls_label.setVisible(True)
            return

        self._no_walls_label.setVisible(False)
        stretch = self._patch_layout.takeAt(self._patch_layout.count() - 1)

        for patch in wall_patches:
            row_w = self._make_patch_row(patch.name)
            self._patch_layout.addWidget(row_w)

        self._patch_layout.addItem(stretch)

    def _make_patch_row(self, name: str) -> QWidget:
        row_w = QWidget()
        row_layout = QHBoxLayout(row_w)
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.setSpacing(6)

        cb = QCheckBox(name)
        cb.setStyleSheet('color: #222; font-size: 12px;')
        cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row_layout.addWidget(cb)

        n_lbl = QLabel('n')
        n_lbl.setStyleSheet(f'color: {ACCENT}; font-size: 11px;')
        row_layout.addWidget(n_lbl)

        n_edit = QLineEdit('3')
        n_edit.setFixedWidth(36)
        n_edit.setStyleSheet(_field_style())
        row_layout.addWidget(n_edit)

        exp_lbl = QLabel('exp')
        exp_lbl.setStyleSheet(f'color: {ACCENT}; font-size: 11px;')
        row_layout.addWidget(exp_lbl)

        exp_edit = QLineEdit('1.2')
        exp_edit.setFixedWidth(44)
        exp_edit.setStyleSheet(_field_style())
        row_layout.addWidget(exp_edit)

        self._patch_rows.append((cb, n_edit, exp_edit))
        return row_w

    # ------------------------------------------------------------------
    # blockMesh process
    # ------------------------------------------------------------------

    def _on_run_blockmesh(self) -> None:
        if not self._case_dir:
            self._log.append('[error] Case directory not set.')
            return

        self._log.clear()
        self._run_bm_btn.setEnabled(False)
        self._bm_success = False
        self._run_layer_btn.setEnabled(False)

        for metric, lbl in self._quality_labels.items():
            lbl.setText('—')
            lbl.setStyleSheet('color: #888; font-size: 12px; border: none;')

        if self._of_version is None:
            self._of_version = _detect_of_version()
        self._log.append(self._of_version + '\n')

        self._bm_process.start('blockMesh', ['-case', self._case_dir])

    def _on_bm_output(self) -> None:
        data = self._bm_process.readAllStandardOutput()
        text = bytes(data).decode('utf-8', errors='replace')
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()

    def _on_bm_finished(self, exit_code: int, _status) -> None:
        if exit_code == 0:
            stale = self._no_layers_dir()
            if os.path.isdir(stale):
                try:
                    shutil.rmtree(stale)
                    self._log.append('[removed stale polyMesh_noLayers backup]\n')
                except OSError:
                    pass
            self._update_restore_btn()
            self._run_checkMesh(context='post_bm')
        else:
            self._run_bm_btn.setEnabled(True)
            self._log.append(f'\n[blockMesh exited with code {exit_code}]')

    def _on_cm_output(self) -> None:
        data = self._cm_process.readAllStandardOutput()
        text = bytes(data).decode('utf-8', errors='replace')
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()

    def _on_cm_finished(self, exit_code: int, _status) -> None:
        self._run_bm_btn.setEnabled(True)
        if exit_code == 0:
            if self._cm_context == 'post_bm':
                self._bm_success = True
                self._run_layer_btn.setToolTip('')
            self._run_layer_btn.setEnabled(self._bm_success)
            self._log.append('\n[checkMesh finished]')
            self._parse_quality(self._log.toPlainText())
            if self._cm_context == 'post_layers':
                self._update_restore_btn()
                self.status_message.emit(
                    '✓ Boundary layers added — mesh quality updated', 'ok')
            elif self._cm_context == 'post_restore':
                self._update_restore_btn()
                self.status_message.emit(
                    '✓ Original mesh restored — mesh quality updated', 'ok')
        else:
            self._run_layer_btn.setEnabled(self._bm_success)
            self._log.append(f'\n[checkMesh exited with code {exit_code}]')
            if self._cm_context == 'post_layers':
                self._update_restore_btn()
                self.status_message.emit(
                    'snappyHexMesh succeeded but checkMesh failed', 'warning')
            elif self._cm_context == 'post_restore':
                self._update_restore_btn()
                self.status_message.emit(
                    'Mesh restored but checkMesh failed', 'warning')

    # ------------------------------------------------------------------
    # checkMesh helper
    # ------------------------------------------------------------------

    def _run_checkMesh(self, context: str = 'post_bm') -> None:
        self._cm_context = context
        if context == 'post_layers':
            self._log.append('\n--- checkMesh after layer addition ---\n')
        elif context == 'post_restore':
            self._log.append('\n--- checkMesh after restore ---\n')
        else:
            self._log.append('\n[blockMesh finished — running checkMesh…]\n')
        self._cm_process.start('checkMesh', ['-case', self._case_dir])

    # ------------------------------------------------------------------
    # Quality parsing
    # ------------------------------------------------------------------

    def _parse_quality(self, log_text: str) -> None:
        for metric, pattern in _QUALITY_RE.items():
            matches = pattern.findall(log_text)
            if not matches:
                continue
            try:
                value = float(matches[-1])
            except ValueError:
                continue
            colour = _colour_for(metric, value)
            lbl = self._quality_labels[metric]
            lbl.setText(f'{value:.4g}')
            lbl.setStyleSheet(
                f'color: {colour}; font-size: 12px; font-weight: bold; border: none;')

    # ------------------------------------------------------------------
    # Layer addition process
    # ------------------------------------------------------------------

    def _on_run_layers(self) -> None:
        if not self._case_dir:
            self._log.append('[error] Case directory not set.')
            return

        checked = self._get_checked_patches()
        if not checked:
            self._log.append('[error] No patches selected for layer addition.')
            return

        if os.path.isdir(self._no_layers_dir()):
            dlg = QMessageBox(self)
            dlg.setWindowTitle('Boundary layers already added')
            dlg.setText(
                'Boundary layers have already been added to this mesh.\n'
                'Running again will add layers on top of existing layers.\n\n'
                'Restore the original mesh and re-run, or cancel?'
            )
            restore_btn = dlg.addButton('Restore and re-run',
                                        QMessageBox.ButtonRole.AcceptRole)
            dlg.addButton('Cancel', QMessageBox.ButtonRole.RejectRole)
            dlg.exec()
            if dlg.clickedButton() is not restore_btn:
                return
            self._log.append('\n[restoring original mesh before re-running layers…]')
            if not self._restore_polymesh():
                return
        else:
            if not self._backup_polymesh():
                return

        self._write_mesh_quality_dict()
        dict_path = self._write_snappy_dict(checked)
        if dict_path is None:
            return

        self._log.append(f'\n[wrote {dict_path}]')
        if self._of_version is None:
            self._of_version = _detect_of_version()
        self._log.append(self._of_version)
        self._log.append('[running snappyHexMesh -overwrite …]\n')
        self._run_layer_btn.setEnabled(False)
        self._run_bm_btn.setEnabled(False)
        self._layer_process.start(
            'snappyHexMesh', ['-case', self._case_dir, '-overwrite'])

    def _on_layer_output(self) -> None:
        data = self._layer_process.readAllStandardOutput()
        text = bytes(data).decode('utf-8', errors='replace')
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()

    def _on_layer_finished(self, exit_code: int, _status) -> None:
        if exit_code == 0:
            self._log.append('\n[snappyHexMesh layer addition finished successfully]')
            self._run_checkMesh(context='post_layers')
        else:
            self._run_layer_btn.setEnabled(self._bm_success)
            self._run_bm_btn.setEnabled(True)
            self._log.append(f'\n[snappyHexMesh exited with code {exit_code}]')
            self.status_message.emit(
                f'snappyHexMesh failed (exit code {exit_code})', 'error')

    def _on_restore_mesh(self) -> None:
        if not os.path.isdir(self._no_layers_dir()):
            self.status_message.emit('No backup found to restore', 'warning')
            return
        self._log.append('\n[restoring original mesh…]')
        self._restore_mesh_btn.setEnabled(False)
        self._run_layer_btn.setEnabled(False)
        self._run_bm_btn.setEnabled(False)
        if not self._restore_polymesh():
            self.status_message.emit('Failed to restore original mesh', 'error')
            self._update_restore_btn()
            self._run_bm_btn.setEnabled(True)
            self._run_layer_btn.setEnabled(self._bm_success)
            return
        self._run_checkMesh(context='post_restore')

    # ------------------------------------------------------------------
    # polyMesh backup / restore helpers
    # ------------------------------------------------------------------

    def _no_layers_dir(self) -> str:
        return os.path.join(self._case_dir, 'constant', 'polyMesh_noLayers')

    def _polymesh_dir(self) -> str:
        return os.path.join(self._case_dir, 'constant', 'polyMesh')

    def _update_restore_btn(self) -> None:
        exists = bool(self._case_dir) and os.path.isdir(self._no_layers_dir())
        self._restore_mesh_btn.setEnabled(exists)

    def _backup_polymesh(self) -> bool:
        src, dst = self._polymesh_dir(), self._no_layers_dir()
        try:
            shutil.copytree(src, dst)
            self._log.append('[backed up polyMesh → polyMesh_noLayers]\n')
            self._update_restore_btn()
            return True
        except OSError as exc:
            self._log.append(f'[error] Could not back up polyMesh: {exc}')
            return False

    def _restore_polymesh(self) -> bool:
        src, dst = self._no_layers_dir(), self._polymesh_dir()
        try:
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            self._log.append('[restored polyMesh_noLayers → polyMesh]\n')
            return True
        except OSError as exc:
            self._log.append(f'[error] Could not restore polyMesh: {exc}')
            return False

    # ------------------------------------------------------------------
    # snappyHexMeshDict writer
    # ------------------------------------------------------------------

    def _get_checked_patches(self) -> list[tuple[str, int, float]]:
        result = []
        for cb, n_edit, exp_edit in self._patch_rows:
            if not cb.isChecked():
                continue
            try:
                n = max(1, int(n_edit.text()))
            except ValueError:
                n = 3
            try:
                exp = float(exp_edit.text())
            except ValueError:
                exp = 1.2
            result.append((cb.text(), n, exp))
        return result

    def _write_mesh_quality_dict(self) -> None:
        path = os.path.join(self._case_dir, 'system', 'meshQualityDict')
        if os.path.exists(path):
            return
        content = """\
/*--------------------------------*- C++ -*----------------------------------*\\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     | blockSketch generated
    \\  /    A nd           |
     \\/     M anipulation  |
\\*---------------------------------------------------------------------------*/
FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      meshQualityDict;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

maxNonOrtho             65;
maxBoundarySkewness     20;
maxInternalSkewness     4;
maxConcave              80;
minVol                  1e-13;
minTetQuality           1e-15;
minArea                 -1;
minTwist                0.05;
minDeterminant          0.001;
minFaceWeight           0.05;
minVolRatio             0.01;
minTriangleTwist        -1;

relaxed
{
    maxNonOrtho     75;
}

nSmoothScale            4;
errorReduction          0.75;

// ************************************************************************* //
"""
        try:
            with open(path, 'w') as fh:
                fh.write(content)
            self._log.append(f'[wrote {path}]')
        except OSError as exc:
            self._log.append(f'[warning] Could not write meshQualityDict: {exc}')

    def _write_snappy_dict(
            self, checked: list[tuple[str, int, float]]) -> str | None:
        content = _snappy_dict_content(_build_layers_block(checked))
        self._log.append(
            '[⚠ snappyHexMeshDict written by blockSketch — tested on OF 2406 ESI.\n'
            '   If you encounter errors on other versions, check\n'
            '   system/snappyHexMeshDict and adjust manually.]'
        )
        path = os.path.join(self._case_dir, 'system', 'snappyHexMeshDict')
        try:
            with open(path, 'w') as fh:
                fh.write(content)
            return path
        except OSError as exc:
            self._log.append(f'[error] Could not write snappyHexMeshDict: {exc}')
            return None

    # ------------------------------------------------------------------
    # Tet mesh — generate
    # ------------------------------------------------------------------

    def _on_generate_tet(self) -> None:
        if self._mesh is None:
            self.status_message.emit('No mesh loaded', 'error')
            return

        maxvolume = self._get_maxvolume()
        if maxvolume is None or maxvolume <= 0:
            self.status_message.emit('Invalid maxvolume — check settings', 'error')
            return

        try:
            minratio    = float(self._minratio_edit.text())
            mindihedral = float(self._mindihedral_edit.text())
        except ValueError:
            self.status_message.emit('Invalid advanced quality settings', 'error')
            return

        verts = self._mesh.scaled_vertices()
        self._log.clear()
        self._log.append(f'[building surface mesh for tetgen (maxvolume={maxvolume:.3g})…]')

        # Build triangulated surface with patch markers for the .face file.
        # _build_tetgen_surface tessellates all quads at n=20 for consistent
        # shared-edge sampling; returns (merged, cleaned).
        _surface, surface_clean = _build_tetgen_surface(self._mesh, verts)
        self._tet_patch_names = [p.name for p in self._mesh.patches]

        if surface_clean.n_open_edges > 0:
            self._log.append(
                f'[error] Surface has {surface_clean.n_open_edges} open edge(s) —'
                ' tetgen cannot proceed.\n'
                'Common causes:\n'
                '  • Some block faces are not assigned to any patch\n'
                '  • 2D/extruded case with empty patches (not a closed 3D surface)\n'
                '  • Incorrect face vertex ordering at patch boundaries'
            )
            self.status_message.emit(
                f'Surface has {surface_clean.n_open_edges} open edge(s) — check patch assignments',
                'error')
            return

        pts     = surface_clean.points.astype(np.float64)
        faces   = surface_clean.faces.reshape(-1, 4)[:, 1:].astype(np.int32)
        markers = surface_clean.cell_data['patch_marker'].astype(np.int32)

        self._log.append('[surface is closed — running tetgen…]')
        self._generate_btn.setEnabled(False)
        self._write_tet_btn.setEnabled(False)

        self._tet_worker = _TetWorker(pts, faces, markers, minratio,
                                      maxvolume, mindihedral)
        self._tet_worker.finished.connect(self._on_tet_finished)
        self._tet_worker.error.connect(self._on_tet_error)
        self._tet_worker.start()

    def _on_tet_finished(self, result) -> None:
        grid, node, elem, trifaces, triface_markers = result
        self._tet_grid            = grid
        self._tet_node            = node
        self._tet_elem            = elem
        self._tet_trifaces        = trifaces
        self._tet_triface_markers = triface_markers
        self._log.append(
            f'[tetgen finished — {grid.n_points} nodes, {grid.n_cells} tetrahedra]')
        self._generate_btn.setEnabled(True)
        self._write_tet_btn.setEnabled(True)
        self.status_message.emit(
            f'Tet mesh generated: {grid.n_cells} cells', 'ok')
        if self._display_tet_cb.isChecked():
            self.tet_mesh_ready.emit(grid)

    def _on_tet_error(self, msg: str) -> None:
        self._log.append(f'[tetgen error] {msg}')
        self._generate_btn.setEnabled(True)
        self.status_message.emit(f'Tet mesh failed: {msg}', 'error')

    # ------------------------------------------------------------------
    # Tet mesh — write
    # ------------------------------------------------------------------

    def _on_write_tet(self) -> None:
        if self._tet_node is None:
            return
        if not self._case_dir:
            self.status_message.emit('Case directory not set', 'error')
            return

        tetgen_dir = os.path.join(self._case_dir, 'constant', 'tetgen')
        os.makedirs(tetgen_dir, exist_ok=True)
        base = os.path.join(tetgen_dir, 'tetmesh')

        try:
            self._write_node_file(base + '.node', self._tet_node)
            self._write_ele_file(base + '.ele', self._tet_elem)
            self._write_face_file(base + '.face',
                                  self._tet_trifaces, self._tet_triface_markers)
            self._log.append('[wrote constant/tetgen/tetmesh.node/.ele/.face]')
        except OSError as exc:
            self._log.append(f'[error writing tetgen files] {exc}')
            self.status_message.emit(f'Write failed: {exc}', 'error')
            return

        cmd = ['tetgenToFoam', '-case', self._case_dir, base]
        self._log.append('[converting constant/tetgen/ → constant/polyMesh/…]')
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                cwd=self._case_dir,
            )
            output = (result.stdout + result.stderr).strip()
            if output:
                self._log.append(output)
            if result.returncode == 0:
                renamed = self._rename_tet_patches(output)
                if renamed:
                    names_str = ', '.join(renamed)
                    self._log.append(f'[✓ boundary patches preserved: {names_str}]')
                    self.status_message.emit(
                        f'Tet mesh written — patches: {names_str}', 'ok')
                else:
                    self._log.append('[✓ polyMesh written to constant/polyMesh]')
                    self.status_message.emit(
                        'Tet mesh written to constant/polyMesh', 'ok')
            else:
                self.status_message.emit('tetgenToFoam failed — check log', 'error')
        except FileNotFoundError:
            self._log.append(
                '[error] tetgenToFoam not found'
                ' — is OpenFOAM sourced in this shell?')
            self.status_message.emit(
                'tetgenToFoam not found — check OpenFOAM installation', 'error')
        except subprocess.TimeoutExpired:
            self._log.append('[error] tetgenToFoam timed out')
            self.status_message.emit('tetgenToFoam timed out', 'error')

        if not self._save_tetgen_cb.isChecked():
            for ext in ('.node', '.ele', '.face'):
                try:
                    os.remove(base + ext)
                except OSError:
                    pass
        else:
            self._log.append('[tetgen files in constant/tetgen/]')

    def _rename_tet_patches(self, tetgen_output: str) -> list[str]:
        """Post-process constant/polyMesh/boundary: rename patchN entries to
        original blockMesh patch names and restore correct patch types.

        Parses the tetgenToFoam stdout for lines of the form
            Mapping tetgen region N to patch M
        to build the authoritative region→patchM mapping, then renames each
        patchM to mesh.patches[N-1].name (region N was assigned marker N = patch
        index N-1 + 1 in _build_tetgen_surface).

        Returns the list of patch names successfully renamed.
        """
        if self._mesh is None:
            return []
        boundary_path = os.path.join(
            self._case_dir, 'constant', 'polyMesh', 'boundary')
        if not os.path.exists(boundary_path):
            return []
        try:
            # Parse tetgenToFoam output for region → polyMesh patch index
            # "Mapping tetgen region N to patch M" → patchM = mesh.patches[N-1]
            patch_idx_to_patch = {}
            for line in tetgen_output.split('\n'):
                m = re.match(
                    r'Mapping tetgen region (\d+) to patch (\d+)', line.strip())
                if m:
                    region    = int(m.group(1))
                    patch_idx = int(m.group(2))
                    if 1 <= region <= len(self._mesh.patches):
                        patch_idx_to_patch[patch_idx] = self._mesh.patches[region - 1]

            if not patch_idx_to_patch:
                self._log.append(
                    '[warning] No region→patch mapping found in tetgenToFoam output'
                    ' — boundary patches not renamed')
                return []

            with open(boundary_path, 'r') as fh:
                content = fh.read()

            renamed = []
            for patch_idx, patch in patch_idx_to_patch.items():
                old_name = f'patch{patch_idx}'
                if f'\n    {old_name}\n' not in content:
                    continue
                content = content.replace(
                    f'\n    {old_name}\n',
                    f'\n    {patch.name}\n',
                )
                renamed.append(patch.name)

                # Restore type and physicalType
                old_block = (
                    f'    {patch.name}\n    {{\n'
                    f'        type            patch;\n'
                    f'        physicalType    patch;'
                )
                new_block = (
                    f'    {patch.name}\n    {{\n'
                    f'        type            {patch.patch_type};\n'
                    f'        physicalType    {patch.patch_type};'
                )
                if old_block in content:
                    content = content.replace(old_block, new_block)
                else:
                    content = re.sub(
                        rf'(    {re.escape(patch.name)}\n    {{\n'
                        rf'        type\s+)patch;',
                        rf'\g<1>{patch.patch_type};',
                        content,
                    )

            with open(boundary_path, 'w') as fh:
                fh.write(content)

            return renamed
        except OSError:
            return []

    def _write_node_file(self, path: str, node: np.ndarray) -> None:
        with open(path, 'w') as fh:
            fh.write(f'{len(node)} 3 0 0\n')
            for i, (x, y, z) in enumerate(node):
                fh.write(f'{i + 1}  {x}  {y}  {z}\n')

    def _write_ele_file(self, path: str, elem: np.ndarray) -> None:
        with open(path, 'w') as fh:
            fh.write(f'{len(elem)} 4 0\n')
            for i, (a, b, c, d) in enumerate(elem):
                fh.write(f'{i + 1}  {a + 1}  {b + 1}  {c + 1}  {d + 1}\n')

    def _write_face_file(self, path: str, trifaces: np.ndarray,
                         triface_markers: np.ndarray) -> None:
        """Write tetgen .face file from tet.trifaces and tet.triface_markers.

        Filters to boundary faces only (markers > 0; interior faces are 0).
        trifaces indices are 0-based into tet.node; written 1-based.
        """
        mask = triface_markers > 0
        faces   = trifaces[mask]
        markers = triface_markers[mask]
        with open(path, 'w') as fh:
            fh.write(f'{len(faces)} 1\n')
            for i, ((v0, v1, v2), m) in enumerate(zip(faces, markers)):
                fh.write(f'{i + 1}  {v0 + 1}  {v1 + 1}  {v2 + 1}  {m}\n')

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------

    def _make_hsep(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color: #ddd;')
        return sep

    def _primary_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {ACCENT}; color: white;
                border: none; border-radius: 4px;
                padding: 6px 16px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: #4a2080; }}
            QPushButton:disabled {{ background-color: #bbb; color: #eee; }}
        """

    def _secondary_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: transparent; color: {ACCENT};
                border: 1px solid {ACCENT}; border-radius: 4px;
                padding: 5px 16px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {PASTEL}; }}
            QPushButton:disabled {{ color: #bbb; border-color: #bbb; }}
        """


# ---------------------------------------------------------------------------
# Shared field style
# ---------------------------------------------------------------------------

def _field_style() -> str:
    return f"""
        QLineEdit {{
            border: 1px solid #bbb; border-radius: 3px;
            padding: 2px 4px; font-size: 12px; background: white;
        }}
        QLineEdit:focus {{ border-color: {ACCENT}; }}
    """

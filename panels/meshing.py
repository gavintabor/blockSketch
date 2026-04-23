"""
Meshing panel — run blockMesh, view quality metrics, add boundary layers.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QFrame, QScrollArea,
    QCheckBox, QLineEdit, QSizePolicy, QGridLayout,
    QDialog, QDialogButtonBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QProcess, pyqtSignal
from PyQt6.QtGui import QTextCursor, QFont

from model import BlockMesh, BoundaryPatch

ACCENT = '#6030a0'
PASTEL = '#e8d8f8'
GREEN  = '#1a6b30'
AMBER  = '#8a5c00'
RED    = '#a02010'

# Quality metric thresholds — (ok_limit, warn_limit).
# Values ≤ ok_limit → green; ok_limit < value ≤ warn_limit → amber; above → red.
# Sourced from checkMesh output; thresholds reflect OpenFOAM community norms.
_THRESHOLDS: dict[str, tuple[float, float]] = {
    'Max aspect ratio':      ( 5.0,  20.0),
    'Max non-orthogonality': (70.0,  85.0),
    'Max skewness':          ( 4.0,  20.0),
}

# Patterns match checkMesh output lines of the form:
#   Max aspect ratio = 9.69232
#   Max non-orthogonality = 64.18
#   Max skewness = 3.76
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
    """Detect the installed OpenFOAM branch and version.

    Tries ESI (foamVersion) first, then Foundation (of-version).
    Returns a single-line string ready to log, e.g.:
        'OpenFOAM version: 2406 (ESI/openfoam.com)'
        'OpenFOAM version: 12 (Foundation/openfoam.org)'
        'OpenFOAM version: unknown — if errors occur check your OF installation'
    """
    # ESI / openfoam.com
    try:
        r = subprocess.run(
            ['foamVersion'], capture_output=True, text=True, timeout=5)
        v = (r.stdout.strip() or r.stderr.strip()).lstrip('v')
        if v:
            return f'OpenFOAM version: {v} (ESI/openfoam.com)'
    except (OSError, subprocess.TimeoutExpired):
        pass
    # Foundation / openfoam.org
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
    """Build the per-patch entries inside the layers { } sub-dict."""
    return '\n'.join(
        f'        {name}\n'
        f'        {{\n'
        f'            nSurfaceLayers {n};\n'
        f'            expansionRatio  {exp};\n'
        f'        }}'
        for name, n, exp in checked
    )


def _build_add_layers_controls(layers_block: str) -> str:
    """Build the complete addLayersControls { ... } block as a string."""
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
    """Build a complete snappyHexMeshDict for boundary layer addition only.

    Hardcoded and known to work with OF 2406 ESI.  All three stages are
    present but only addLayers is active; castellatedMesh and snap are both
    false.  The geometry section is intentionally empty — sHM reads it even
    when castellatedMesh is false on some OF versions.
    """
    alc = _build_add_layers_controls(layers_block)
    # Use str.join to avoid f-string brace escaping entirely.
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
# MeshingPanel
# ---------------------------------------------------------------------------

class MeshingPanel(QWidget):

    # str: message,  str: level — 'ok' | 'warning' | 'error'
    status_message = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._case_dir: str = ''
        self._mesh: BlockMesh | None = None
        self._bm_success: bool = False
        self._patch_rows: list[tuple[QCheckBox, QLineEdit, QLineEdit]] = []
        self._of_version: str | None = None   # detected lazily on first show

        self._bm_process    = QProcess(self)
        self._cm_process    = QProcess(self)   # checkMesh, run after blockMesh or layer addition
        self._layer_process = QProcess(self)
        self._cm_context: str = 'post_bm'      # 'post_bm' | 'post_layers' | 'post_restore'
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

    def set_topology_errors(self, has_errors: bool) -> None:
        """Disable Run blockMesh when the topology validator reports red errors."""
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

        self._layer_process.readyReadStandardOutput.connect(
            self._on_layer_output)
        self._layer_process.finished.connect(self._on_layer_finished)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addLayout(self._make_section_header('MESHING'))
        layout.addLayout(self._make_blockmesh_section())
        layout.addWidget(self._make_hsep())
        layout.addWidget(self._make_quality_section())
        layout.addWidget(self._make_hsep())
        layout.addLayout(self._make_layers_section())

    def _make_section_header(self, text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f'color: {ACCENT}; font-weight: bold; font-size: 11px; letter-spacing: 2px;')
        row.addWidget(lbl)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f'color: {ACCENT};')
        row.addWidget(sep)
        return row

    def _make_blockmesh_section(self) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(6)

        # Run button
        self._run_bm_btn = QPushButton('▶  Run blockMesh')
        self._run_bm_btn.setStyleSheet(self._primary_btn_style())
        self._run_bm_btn.clicked.connect(self._on_run_blockmesh)
        section.addWidget(self._run_bm_btn)

        # Log area
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
        self._log.setMinimumHeight(160)
        self._log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        section.addWidget(self._log)

        return section

    def _make_quality_section(self) -> QFrame:
        box = QFrame()
        box.setStyleSheet(f"""
            QFrame {{
                background: #f7f5f0;
                border: 1px solid #ddd;
                border-radius: 4px;
            }}
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
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(val_lbl, row_i, 1)
            self._quality_labels[metric] = val_lbl

        return box

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
                'symmetry, symmetryPlane) are excluded.'
                '</pre>'
            )
            vlay.addWidget(lbl)
            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btns.accepted.connect(dlg.accept)
            vlay.addWidget(btns)
            dlg.adjustSize()
            dlg.exec()

        info_btn = QPushButton('\u24d8')
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

        # Scrollable patch list
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

        # Run layer addition button
        self._run_layer_btn = QPushButton('▶  Run layer addition')
        self._run_layer_btn.setEnabled(False)
        self._run_layer_btn.setToolTip(
            'Run blockMesh successfully before adding boundary layers.')
        self._run_layer_btn.setStyleSheet(self._primary_btn_style())
        self._run_layer_btn.clicked.connect(self._on_run_layers)
        section.addWidget(self._run_layer_btn)

        # Restore original mesh button
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
        # Clear existing rows (preserve the no_walls_label and trailing stretch)
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
        cb.setStyleSheet(f'color: #222; font-size: 12px;')
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
            # blockMesh has produced a fresh base mesh — any existing backup is stale
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
    # checkMesh helper — shared by post-blockMesh and post-layer paths
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
            # Take the last match (blockMesh may report for multiple mesh passes)
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

        # Guard against layering an already-layered mesh
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
            # polyMesh_noLayers is still in place — reuse it as the backup
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
            # buttons re-enabled by _on_cm_finished once checkMesh completes
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
        """Copy constant/polyMesh → constant/polyMesh_noLayers. Returns True on success."""
        src, dst = self._polymesh_dir(), self._no_layers_dir()
        try:
            shutil.copytree(src, dst)
            self._log.append(f'[backed up polyMesh → polyMesh_noLayers]\n')
            self._update_restore_btn()
            return True
        except OSError as exc:
            self._log.append(f'[error] Could not back up polyMesh: {exc}')
            return False

    def _restore_polymesh(self) -> bool:
        """Copy constant/polyMesh_noLayers → constant/polyMesh. Returns True on success."""
        src, dst = self._no_layers_dir(), self._polymesh_dir()
        try:
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            self._log.append(f'[restored polyMesh_noLayers → polyMesh]\n')
            return True
        except OSError as exc:
            self._log.append(f'[error] Could not restore polyMesh: {exc}')
            return False

    # ------------------------------------------------------------------
    # snappyHexMeshDict writer
    # ------------------------------------------------------------------

    def _get_checked_patches(self) -> list[tuple[str, int, float]]:
        """Return (name, n_layers, expansion_ratio) for every ticked patch."""
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
        """Write system/meshQualityDict if it does not already exist."""
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
        """Write system/snappyHexMeshDict; return the path or None on failure."""
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

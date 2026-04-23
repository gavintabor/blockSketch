"""
blockSketch — main application window.

Six-panel layout:
  Top: panel-selector buttons + Save
  Left: QStackedWidget (one panel per button)
  Right: PyVista QtInteractor viewport
  Bottom: topology-validator status bar
"""
import sys
import os
import shutil
import numpy as np

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout,
    QPushButton, QToolButton, QMenu, QStackedWidget, QLabel,
    QButtonGroup, QSizePolicy, QFrame,
    QFileDialog, QMessageBox,
)
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtCore import Qt
import pyvista as pv
from pyvistaqt import QtInteractor

from core.parser import parse_file
from core.model import BlockMesh
import desktop.viewer as viewer
from desktop.panels.general import GeneralPanel
from desktop.panels.vertices import VerticesPanel
from desktop.panels.blocks import BlocksPanel
from desktop.panels.edges import EdgesPanel
from desktop.panels.patches import PatchesPanel
from desktop.panels.meshing import MeshingPanel, _case_dir_from_path
import core.writer as writer


# ---------------------------------------------------------------------------
# Colour palette for panel buttons
# (accent colour, pastel fill when active)
# ---------------------------------------------------------------------------
PANEL_NAMES = ['General', 'Vertices', 'Blocks', 'Edges', 'Patches', 'Meshing']

_COLORS: dict[str, tuple[str, str]] = {
    'General':  ('#b03020', '#f5ddd9'),   # red
    'Vertices': ('#1e7a40', '#d4f0de'),   # green
    'Blocks':   ('#1a5c96', '#d4e8f8'),   # blue
    'Edges':    ('#a06010', '#f5e8d0'),   # amber
    'Patches':  ('#0d7060', '#cceee8'),   # teal
    'Meshing':  ('#6030a0', '#e8d8f8'),   # purple
}


def _btn_style(accent: str, pastel: str) -> str:
    return f"""
        QPushButton {{
            color: {accent};
            border: 2px solid {accent};
            background-color: transparent;
            border-radius: 4px;
            padding: 4px 14px;
            font-size: 13px;
            font-weight: normal;
        }}
        QPushButton:checked {{
            background-color: {pastel};
            font-weight: bold;
        }}
        QPushButton:hover:!checked {{
            background-color: {pastel};
        }}
    """


# ---------------------------------------------------------------------------
# Topology validator
# ---------------------------------------------------------------------------

def _topology_check(mesh: BlockMesh) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) lists from a quick topology scan."""
    errors: list[str] = []
    warnings: list[str] = []

    n = len(mesh.vertices)
    referenced: set[int] = set()

    for bi, block in enumerate(mesh.blocks):
        for vi in block.vertex_ids:
            if vi >= n or vi < 0:
                errors.append(f'Block {bi} references out-of-range vertex index {vi}')
            else:
                referenced.add(vi)

    # Orphaned vertices
    if mesh.blocks:
        orphaned = set(range(n)) - referenced
        if orphaned:
            warnings.append(
                f'{len(orphaned)} orphaned vertex/vertices not referenced by any block')

    verts = mesh.scaled_vertices()

    # Duplicate vertices (check only first collision found)
    if n > 1:
        found = False
        for i in range(n):
            if found:
                break
            for j in range(i + 1, n):
                if np.linalg.norm(verts[i] - verts[j]) < 1e-10:
                    warnings.append(
                        f'Vertices {i} and {j} have identical coordinates')
                    found = True
                    break

    # Bounding-box volume — used to scale the degenerate-block threshold
    bbox_vol = 0.0
    if verts:
        all_pts = np.array(verts)
        bbox_vol = float(np.prod(all_pts.max(axis=0) - all_pts.min(axis=0)))

    # Checks 4 & 5 — Jacobian sign and near-zero volume
    for bi, block in enumerate(mesh.blocks):
        if not all(0 <= vi < n for vi in block.vertex_ids):
            continue   # already flagged by check 2
        pts = [verts[vi] for vi in block.vertex_ids]
        v0 = np.array(pts[0])
        ex = np.array(pts[1]) - v0   # x direction: vertex 0 → 1
        ey = np.array(pts[3]) - v0   # y direction: vertex 0 → 3
        ez = np.array(pts[4]) - v0   # z direction: vertex 0 → 4
        jacobian = float(np.dot(ex, np.cross(ey, ez)))
        if jacobian <= 0:
            errors.append(
                f'Block {bi} has negative Jacobian — '
                f'vertices may be swapped or block is inverted')
        else:
            if bbox_vol > 0 and jacobian < bbox_vol * 1e-10:
                errors.append(
                    f'Block {bi} has near-zero volume — '
                    f'check for duplicate or coincident vertices')

    return errors, warnings


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, mesh_path: str):
        super().__init__()
        self.setWindowTitle('blockSketch')
        self.resize(1400, 900)

        self._mesh_path = mesh_path
        self._mesh: BlockMesh | None = None
        self._dirty: bool = False
        self._stl_meshes: list[tuple] = []  # (pv.DataSet, filepath)

        # Display state — kept in sync with General panel checkboxes
        self._show_vertex_labels = True
        self._show_block_labels  = True
        self._show_patch_faces   = True
        self._show_bounding_box  = False
        self._show_scale_bar     = False
        self._show_legend        = True

        self._build_ui()
        self._load_mesh(mesh_path)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 0)
        root.setSpacing(4)

        root.addLayout(self._make_top_bar())
        root.addLayout(self._make_content_area())

    def _make_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._panel_btns: dict[str, QPushButton] = {}

        for name in PANEL_NAMES:
            accent, pastel = _COLORS[name]
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setStyleSheet(_btn_style(accent, pastel))
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._btn_group.addButton(btn)
            self._panel_btns[name] = btn
            bar.addWidget(btn)

        bar.addStretch()

        # Save drop-down button — click for quick save, arrow for all options
        save_menu = QMenu(self)

        save_act = QAction('Save blockMeshDict', self)
        save_act.setShortcut(QKeySequence.StandardKey.Save)
        save_act.triggered.connect(self._on_save)
        save_menu.addAction(save_act)

        save_as_act = QAction('Save As\u2026', self)
        save_as_act.setShortcut(QKeySequence('Ctrl+Shift+S'))
        save_as_act.triggered.connect(self._on_save_as)
        save_menu.addAction(save_as_act)

        save_menu.addSeparator()

        save_exit_act = QAction('Save and Exit', self)
        save_exit_act.setShortcut(QKeySequence('Ctrl+Q'))
        save_exit_act.triggered.connect(self._on_save_and_exit)
        save_menu.addAction(save_exit_act)

        exit_act = QAction('Exit without saving', self)
        exit_act.triggered.connect(self._on_exit_without_saving)
        save_menu.addAction(exit_act)

        # Register shortcuts on the window so they work without opening the menu
        for act in (save_act, save_as_act, save_exit_act):
            self.addAction(act)

        save_btn = QToolButton()
        save_btn.setText('Save  ▾')
        save_btn.setMenu(save_menu)
        save_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        save_btn.setStyleSheet("""
            QToolButton {
                border: 2px solid #666;
                border-radius: 4px;
                padding: 4px 14px;
                font-size: 13px;
                background-color: transparent;
                color: #555;
            }
            QToolButton:hover { background-color: #eee; }
            QToolButton::menu-indicator { image: none; }
        """)
        bar.addWidget(save_btn)

        return bar

    def _make_content_area(self) -> QHBoxLayout:
        content = QHBoxLayout()
        content.setSpacing(6)

        # ---- Left: stacked panels ----
        self._stack = QStackedWidget()
        self._stack.setFixedWidth(360)
        self._stack.setStyleSheet('QStackedWidget { background: #f7f5f0; }')

        self._general_panel = GeneralPanel()
        self._stack.addWidget(self._general_panel)

        self._vertices_panel = VerticesPanel()
        self._stack.addWidget(self._vertices_panel)

        self._blocks_panel = BlocksPanel()
        self._stack.addWidget(self._blocks_panel)

        self._edges_panel = EdgesPanel()
        self._stack.addWidget(self._edges_panel)

        self._patches_panel = PatchesPanel()
        self._stack.addWidget(self._patches_panel)

        self._meshing_panel = MeshingPanel()
        self._stack.addWidget(self._meshing_panel)

        # All panels now implemented — no placeholders remain
        for name in PANEL_NAMES[6:]:
            accent, _ = _COLORS[name]
            lbl = QLabel(f'{name} panel\n— coming soon —')
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f'color: {accent}; font-size: 14px;')
            self._stack.addWidget(lbl)

        # Wire buttons → stack index
        for idx, name in enumerate(PANEL_NAMES):
            self._panel_btns[name].clicked.connect(
                lambda _checked, i=idx: self._stack.setCurrentIndex(i))

        self._panel_btns['General'].setChecked(True)
        content.addWidget(self._stack)

        # ---- Right: PyVista viewport ----
        self._plotter = QtInteractor(self)
        self._plotter.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._plotter.setToolTip(
            'Right-click vertex to select in Vertices panel\n'
            'Right-click curved edge to select in Edges panel\n'
            'Right-click block label to select in Blocks panel')
        content.addWidget(self._plotter)

        # ---- Connect General panel signals ----
        gp = self._general_panel
        gp.toggle_vertex_labels.stateChanged.connect(
            lambda s: self._update_display(show_vertex_labels=bool(s)))
        gp.toggle_block_labels.stateChanged.connect(
            lambda s: self._update_display(show_block_labels=bool(s)))
        gp.toggle_patch_faces.stateChanged.connect(
            lambda s: self._update_display(show_patch_faces=bool(s)))
        gp.toggle_bounding_box.stateChanged.connect(
            lambda s: self._update_display(show_bounding_box=bool(s)))
        gp.toggle_scale_bar.stateChanged.connect(
            lambda s: self._update_display(show_scale_bar=bool(s)))
        gp.toggle_legend.stateChanged.connect(
            lambda s: self._update_display(show_legend=bool(s)))
        gp.geometry_load_requested.connect(self._on_load_stl)
        gp.geometry_cleared.connect(self._on_clear_stl)
        gp.scale_changed.connect(self._on_scale_changed)
        gp.screenshot_requested.connect(self._on_screenshot)

        self._vertices_panel.vertex_changed.connect(self._on_model_changed)
        self._blocks_panel.block_changed.connect(self._on_model_changed)
        self._edges_panel.edge_changed.connect(self._on_model_changed)
        self._patches_panel.patch_changed.connect(self._on_model_changed)
        self._patches_panel.patch_changed.connect(
            lambda: self._meshing_panel.load_mesh(self._mesh))
        self._meshing_panel.status_message.connect(self._on_meshing_status)

        return content

    # ------------------------------------------------------------------
    # Mesh loading
    # ------------------------------------------------------------------

    def _load_mesh(self, path: str):
        self.statusBar().showMessage('Parsing…')
        try:
            self._mesh = parse_file(path)
        except Exception as exc:
            self._set_status_error(f'Parse error: {exc}')
            return

        self._general_panel.set_scale(self._mesh.scale, self._mesh.scale_keyword)
        self._vertices_panel.load_mesh(self._mesh)
        self._blocks_panel.load_mesh(self._mesh)
        self._edges_panel.load_mesh(self._mesh)
        self._patches_panel.load_mesh(self._mesh)
        case_dir = _case_dir_from_path(self._mesh_path)
        self._general_panel.set_case_dir(case_dir)
        self._meshing_panel.set_case_dir(case_dir)
        self._meshing_panel.load_mesh(self._mesh)
        self._refresh_viewport()
        self._run_topology_check()
        self._set_dirty(False)

    # ------------------------------------------------------------------
    # Viewport
    # ------------------------------------------------------------------

    def _refresh_viewport(self):
        if self._mesh is None:
            return
        self._plotter.clear()
        extra = ([['SHM Target Geometry', 'gray', 'rectangle']]
                 if self._stl_meshes else None)
        verts = self._mesh.scaled_vertices()
        viewer.populate(
            self._plotter,
            self._mesh,
            show_vertex_labels=self._show_vertex_labels,
            show_block_labels=self._show_block_labels,
            show_patch_faces=self._show_patch_faces,
            show_bounding_box=self._show_bounding_box,
            show_scale_bar=self._show_scale_bar,
            show_legend=self._show_legend,
            extra_legend_entries=extra,
        )
        for stl_mesh, _ in self._stl_meshes:
            self._plotter.add_mesh(stl_mesh, color='gray', opacity=0.7)
        viewer.enable_block_picking(
            self._plotter, self._mesh, verts, self._on_block_picked)
        viewer.enable_vertex_picking(
            self._plotter, self._mesh, verts, self._on_vertex_picked)
        viewer.enable_edge_picking(
            self._plotter, self._mesh, verts, self._on_edge_picked)
        self._plotter.render()

    def _update_display(self, *,
                        show_vertex_labels: bool | None = None,
                        show_block_labels:  bool | None = None,
                        show_patch_faces:   bool | None = None,
                        show_bounding_box:  bool | None = None,
                        show_scale_bar:     bool | None = None,
                        show_legend:        bool | None = None):
        if show_vertex_labels is not None:
            self._show_vertex_labels = show_vertex_labels
        if show_block_labels is not None:
            self._show_block_labels = show_block_labels
        if show_patch_faces is not None:
            self._show_patch_faces = show_patch_faces
        if show_bounding_box is not None:
            self._show_bounding_box = show_bounding_box
        if show_scale_bar is not None:
            self._show_scale_bar = show_scale_bar
        if show_legend is not None:
            self._show_legend = show_legend
        self._refresh_viewport()

    # ------------------------------------------------------------------
    # Topology validator
    # ------------------------------------------------------------------

    def _run_topology_check(self):
        if self._mesh is None:
            return
        errors, warnings = _topology_check(self._mesh)
        self._meshing_panel.set_topology_errors(bool(errors))
        if errors:
            self._set_status_error(errors[0])
        elif warnings:
            self._set_status_warning(warnings[0])
        else:
            self._set_status_ok('No issues found — mesh looks clean')

    def _on_meshing_status(self, msg: str, level: str) -> None:
        if level == 'ok':
            self._set_status_ok(msg)
        elif level == 'warning':
            self._set_status_warning(msg)
        else:
            self._set_status_error(msg)

    def _set_status_ok(self, msg: str):
        self.statusBar().setStyleSheet('QStatusBar { color: #1e7a40; }')
        self.statusBar().showMessage(f'\u2713 {msg}')

    def _set_status_warning(self, msg: str):
        self.statusBar().setStyleSheet('QStatusBar { color: #a06010; }')
        self.statusBar().showMessage(f'\u26a0 {msg}')

    def _set_status_error(self, msg: str):
        self.statusBar().setStyleSheet('QStatusBar { color: #b03020; }')
        self.statusBar().showMessage(f'\u2717 {msg}')

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_edge_picked(self, edge_index: int) -> None:
        """Called when the user right-clicks on a curved edge."""
        self._stack.setCurrentIndex(3)
        self._panel_btns['Edges'].setChecked(True)
        self._edges_panel.select_edge(edge_index)

    def _on_vertex_picked(self, vertex_index: int) -> None:
        """Called when the user right-clicks near a vertex in the viewport."""
        self._stack.setCurrentIndex(1)
        self._panel_btns['Vertices'].setChecked(True)
        self._vertices_panel.select_vertex(vertex_index)
        # Highlight the picked vertex with a yellow sphere until the next refresh
        if self._mesh and vertex_index < len(self._mesh.vertices):
            verts = self._mesh.scaled_vertices()
            pt = pv.PolyData(np.array([verts[vertex_index]]))
            self._plotter.add_mesh(pt, color='yellow', point_size=16,
                                   render_points_as_spheres=True,
                                   name='vertex_highlight')
            self._plotter.render()

    def _on_block_picked(self, block_index: int) -> None:
        """Called when the user right-clicks near a block centroid in the viewport."""
        self._stack.setCurrentIndex(2)
        self._panel_btns['Blocks'].setChecked(True)
        self._blocks_panel.select_block(block_index)

    def _on_scale_changed(self, value: float) -> None:
        """Called when the user edits the scale field in the General panel."""
        if value <= 0 or self._mesh is None:
            return
        self._mesh.scale = value
        self._on_model_changed()

    def _on_model_changed(self):
        """Called whenever a panel modifies the mesh model."""
        self._set_dirty(True)
        self._refresh_viewport()
        self._run_topology_check()

    # ------------------------------------------------------------------
    # Dirty-state tracking
    # ------------------------------------------------------------------

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        fname = os.path.basename(os.path.dirname(os.path.dirname(self._mesh_path))) if self._mesh_path else 'blockMeshDict'
        title = f'blockSketch \u2014 {fname}'
        if dirty:
            title = '\u2022 ' + title
        self.setWindowTitle(title)

    # ------------------------------------------------------------------
    # Save / exit actions
    # ------------------------------------------------------------------

    def _on_save(self) -> bool:
        """Save to the current path. Returns True on success."""
        if self._mesh_path:
            return self._save_to_path(self._mesh_path)
        return self._on_save_as()

    def _on_save_as(self) -> bool:
        """Prompt for a new path and save. Returns True on success."""
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save blockMeshDict',
            self._mesh_path or '',
            'OpenFOAM dict (blockMeshDict);;All files (*)',
        )
        if not path:
            return False
        return self._save_to_path(path)

    def _save_to_path(self, path: str) -> bool:
        """Write the mesh to *path*, backing up any existing file first."""
        if self._mesh is None:
            return False

        # Backup existing file before overwriting
        if os.path.exists(path):
            bak = path + '.bak'
            try:
                shutil.copy2(path, bak)
            except OSError as exc:
                self._set_status_warning(f'Could not create backup: {exc}')

        try:
            content = writer.write_blockmesh(self._mesh)
            with open(path, 'w') as fh:
                fh.write(content)
        except OSError as exc:
            self._set_status_error(f'Save failed: {exc}')
            return False

        self._mesh_path = path
        self._set_dirty(False)
        self._set_status_ok(f'Saved: {os.path.basename(path)}')
        return True

    def _on_save_and_exit(self) -> None:
        if self._on_save():
            self._plotter.close()
            QApplication.quit()

    def _on_exit_without_saving(self) -> None:
        if self._dirty:
            reply = QMessageBox.question(
                self, 'Exit without saving',
                'Are you sure you want to exit without saving?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._plotter.close()
        QApplication.quit()

    def _on_load_stl(self, path: str):
        try:
            stl = pv.read(path)
            self._stl_meshes.append((stl, path))
            self._refresh_viewport()
            self._general_panel.notify_stl_loaded(
                os.path.basename(path), len(self._stl_meshes))
            self._set_status_ok(f'Geometry loaded: {os.path.basename(path)}')
        except Exception as exc:
            self._set_status_error(f'STL load failed: {exc}')

    def _on_clear_stl(self):
        self._stl_meshes.clear()
        self._general_panel.notify_stl_cleared()
        self._refresh_viewport()
        self._set_status_ok('Geometry cleared')

    def _on_screenshot(self, path: str):
        try:
            self._plotter.screenshot(path)
            self._set_status_ok(f'Screenshot saved to {os.path.basename(path)}')
        except Exception as exc:
            self._set_status_error(f'Screenshot failed: {exc}')

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(
                self, 'Unsaved changes',
                'You have unsaved changes. Save before exiting?',
                (QMessageBox.StandardButton.Yes |
                 QMessageBox.StandardButton.No  |
                 QMessageBox.StandardButton.Cancel),
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                if not self._on_save():
                    event.ignore()
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self._plotter.close()
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def launch(mesh_path: str) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet("""
        QToolTip {
            color: black;
            background-color: #fffde7;
            border: 1px solid #aaa;
            font-size: 13px;
            padding: 4px 6px;
        }
    """)
    win = MainWindow(mesh_path)
    win.show()
    sys.exit(app.exec())

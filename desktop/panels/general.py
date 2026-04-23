"""
General panel — scale editor, display toggles, Load geometry.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QPushButton, QFrame, QFileDialog, QLineEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator


class GeneralPanel(QWidget):
    geometry_load_requested = pyqtSignal(str)   # file path when user picks geometry
    geometry_cleared     = pyqtSignal()      # user clicked Clear geometry
    scale_changed        = pyqtSignal(float) # new scale value when user edits it
    screenshot_requested = pyqtSignal(str)   # file path chosen by user

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_scale: float = 1.0
        self._case_dir: str = ''
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # ---- Header ----
        header = QLabel('GENERAL')
        header.setStyleSheet(
            'color: #c0392b; font-weight: bold; font-size: 11px; letter-spacing: 2px;')
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color: #c0392b; margin-bottom: 4px;')
        layout.addWidget(sep)

        # ---- Scale factor ----
        scale_row = QHBoxLayout()
        scale_row.setSpacing(6)

        # Label shows which keyword the file uses ('scale' or 'convertToMeters')
        self._scale_kw_lbl = QLabel('scale')
        self._scale_kw_lbl.setStyleSheet('color: #555;')
        scale_row.addWidget(self._scale_kw_lbl)

        scale_row.addStretch()

        validator = QDoubleValidator()
        validator.setBottom(1e-30)   # must be > 0
        validator.setNotation(QDoubleValidator.Notation.ScientificNotation)

        self._scale_edit = QLineEdit('1')
        self._scale_edit.setFixedWidth(90)
        self._scale_edit.setValidator(validator)
        self._scale_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 3px 6px;
                font-size: 12px;
                background: white;
            }
            QLineEdit:focus { border-color: #c0392b; }
        """)
        self._scale_edit.editingFinished.connect(self._on_scale_commit)
        scale_row.addWidget(self._scale_edit)

        layout.addLayout(scale_row)

        layout.addSpacing(10)

        # ---- Display toggles ----
        disp_lbl = QLabel('DISPLAY')
        disp_lbl.setStyleSheet(
            'color: #888; font-size: 10px; letter-spacing: 2px;')
        layout.addWidget(disp_lbl)

        self.toggle_vertex_labels = QCheckBox('Vertex labels')
        self.toggle_vertex_labels.setChecked(True)
        layout.addWidget(self.toggle_vertex_labels)

        self.toggle_block_labels = QCheckBox('Block numbers')
        self.toggle_block_labels.setChecked(True)
        layout.addWidget(self.toggle_block_labels)

        self.toggle_patch_faces = QCheckBox('Patch faces')
        self.toggle_patch_faces.setChecked(True)
        layout.addWidget(self.toggle_patch_faces)

        self.toggle_bounding_box = QCheckBox('Bounding box')
        self.toggle_bounding_box.setChecked(False)
        layout.addWidget(self.toggle_bounding_box)

        self.toggle_scale_bar = QCheckBox('Scale bar')
        self.toggle_scale_bar.setChecked(False)
        layout.addWidget(self.toggle_scale_bar)

        self.toggle_legend = QCheckBox('Legend')
        self.toggle_legend.setChecked(True)
        layout.addWidget(self.toggle_legend)

        layout.addSpacing(10)

        hint = QLabel('ⓘ Right-click vertex, curved edge or block to select')
        hint.setStyleSheet('color: #888; font-size: 10px; font-style: italic;')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(10)

        # ---- Reference geometry ----
        ref_lbl = QLabel('SHM TARGET GEOMETRY')
        ref_lbl.setStyleSheet(
            'color: #888; font-size: 10px; letter-spacing: 2px;')
        layout.addWidget(ref_lbl)

        _btn_style = """
            QPushButton {
                border: 1px solid #888;
                border-radius: 3px;
                padding: 4px 10px;
                background: transparent;
                color: #444;
                text-align: left;
            }
            QPushButton:hover { background-color: #ece9e3; }
        """

        stl_row = QHBoxLayout()
        stl_row.setSpacing(4)

        self._stl_btn = QPushButton('Load geometry\u2026')
        self._stl_btn.setStyleSheet(_btn_style)
        self._stl_btn.clicked.connect(self._on_load_stl)
        stl_row.addWidget(self._stl_btn)

        self._stl_clear_btn = QPushButton('Clear geometry')
        self._stl_clear_btn.setStyleSheet(_btn_style)
        self._stl_clear_btn.clicked.connect(self._on_clear_stl)
        self._stl_clear_btn.setEnabled(False)
        stl_row.addWidget(self._stl_clear_btn)

        layout.addLayout(stl_row)

        self._stl_path_lbl = QLabel('')
        self._stl_path_lbl.setStyleSheet('color: #777; font-size: 10px;')
        self._stl_path_lbl.setWordWrap(True)
        layout.addWidget(self._stl_path_lbl)

        layout.addSpacing(10)

        # ---- Output ----
        out_lbl = QLabel('SCREENSHOT')
        out_lbl.setStyleSheet(
            'color: #888; font-size: 10px; letter-spacing: 2px;')
        layout.addWidget(out_lbl)

        self._screenshot_btn = QPushButton('blockSketch_screenshot.png')
        self._screenshot_btn.setStyleSheet(_btn_style)
        self._screenshot_btn.setShortcut('Ctrl+P')
        self._screenshot_btn.clicked.connect(self._on_screenshot)
        layout.addWidget(self._screenshot_btn)

        layout.addStretch()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_scale(self, scale: float, keyword: str = 'scale') -> None:
        """Populate the field from the model — called on mesh load."""
        self._current_scale = scale
        self._scale_edit.setText(_fmt(scale))
        self._scale_kw_lbl.setText(keyword)

    def set_case_dir(self, path: str) -> None:
        """Set the default directory for the screenshot save dialog."""
        self._case_dir = path

    def notify_stl_loaded(self, filename: str, total: int) -> None:
        """Update the STL label and enable Clear after a file is loaded."""
        if total == 1:
            self._stl_path_lbl.setText(filename)
        else:
            self._stl_path_lbl.setText(f'STL files loaded: {total}')
        self._stl_clear_btn.setEnabled(True)

    def notify_stl_cleared(self) -> None:
        """Reset the STL label and disable Clear after meshes are cleared."""
        self._stl_path_lbl.setText('')
        self._stl_clear_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_screenshot(self) -> None:
        import os
        default = os.path.join(self._case_dir, 'blockSketch_screenshot.png')
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Screenshot', default,
            'PNG images (*.png);;JPEG images (*.jpg);;All files (*)')
        if path:
            self.screenshot_requested.emit(path)

    def _on_scale_commit(self) -> None:
        """Validate and apply the scale field on Enter or focus-out."""
        text = self._scale_edit.text().strip()
        try:
            value = float(text)
        except ValueError:
            value = 0.0

        if value <= 0:
            # Invalid — revert and ask app.py to show a warning
            self._scale_edit.setText(_fmt(self._current_scale))
            # Emit a special sentinel value of -1 to signal 'bad input'
            # App.py checks for this and shows the status bar warning.
            self.scale_changed.emit(-1.0)
            return

        if value != self._current_scale:
            self._current_scale = value
            self.scale_changed.emit(value)

    def _on_load_stl(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Load geometry', '',
            'Geometry files (*.stl *.STL *.obj *.OBJ *.vtk *.vtp *.ply *.PLY)'
            ';;STL files (*.stl *.STL)'
            ';;OBJ files (*.obj *.OBJ)'
            ';;VTK files (*.vtk *.vtp)'
            ';;PLY files (*.ply *.PLY)'
            ';;All files (*)')
        if path:
            self.geometry_load_requested.emit(path)

    def _on_clear_stl(self):
        self.geometry_cleared.emit()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _fmt(x: float) -> str:
    """Clean float → string: integers without decimal point."""
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f'{x:.10g}'

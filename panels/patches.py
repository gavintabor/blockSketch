"""
Patches panel — scrollable accordion list of boundary patches.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QFrame,
    QScrollArea,
)
from PyQt6.QtCore import Qt, pyqtSignal

from model import BlockMesh, BoundaryPatch

ACCENT = '#0d7060'
PASTEL = '#cceee8'

PATCH_TYPES = ['patch', 'wall', 'empty', 'symmetry', 'symmetryPlane', 'cyclic', 'wedge']


# ---------------------------------------------------------------------------
# Face helpers
# ---------------------------------------------------------------------------

def _face_str(face: tuple) -> str:
    return ' '.join(str(v) for v in face)


def _parse_face(text: str) -> tuple[int, ...] | None:
    parts = text.split()
    if not parts:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Single patch accordion item
# ---------------------------------------------------------------------------

class _PatchItem(QFrame):
    delete_requested = pyqtSignal()
    apply_requested  = pyqtSignal()

    def __init__(self, patch_index: int, patch: BoundaryPatch,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._patch_index = patch_index
        self._patch       = patch
        self._expanded    = False

        self._face_edits:       list[QLineEdit] = []
        self._face_row_widgets: list[QWidget]   = []

        self._build_ui()
        self.setObjectName('patchItem')
        self.setStyleSheet(
            'QFrame#patchItem { border: 1px solid #a8ddd4; border-radius: 4px; }')

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Header ----
        header = QFrame()
        header.setStyleSheet(f'background-color: {PASTEL}; border-radius: 3px;')
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.mousePressEvent = lambda _e: self._toggle()

        h = QHBoxLayout(header)
        h.setContentsMargins(8, 5, 8, 5)
        h.setSpacing(6)

        self._arrow = QLabel('▶')
        self._arrow.setStyleSheet(
            f'color: {ACCENT}; font-size: 10px; background: transparent;')
        self._arrow.setFixedWidth(14)
        h.addWidget(self._arrow)

        self._title_label = QLabel(
            self._make_title(self._patch.name, self._patch.patch_type))
        self._title_label.setStyleSheet(
            f'color: {ACCENT}; font-weight: bold; font-size: 12px; background: transparent;')
        h.addWidget(self._title_label)
        h.addStretch()

        del_btn = QPushButton('Delete')
        del_btn.setStyleSheet("""
            QPushButton {
                color: #b03020; border: 1px solid #b03020;
                border-radius: 3px; padding: 2px 8px;
                font-size: 11px; background: transparent;
            }
            QPushButton:hover { background-color: #f5ddd9; }
        """)
        del_btn.clicked.connect(self.delete_requested)
        h.addWidget(del_btn)

        root.addWidget(header)

        # ---- Content ----
        self._content = QFrame()
        self._content.setStyleSheet('background: white;')
        c = QVBoxLayout(self._content)
        c.setContentsMargins(10, 8, 10, 8)
        c.setSpacing(6)

        # Name
        name_row = QHBoxLayout()
        name_lbl = QLabel('name')
        name_lbl.setStyleSheet('color: #555; font-size: 11px;')
        name_lbl.setFixedWidth(40)
        name_row.addWidget(name_lbl)
        self._name_edit = QLineEdit(self._patch.name)
        self._name_edit.setStyleSheet(_field_style())
        self._name_edit.textChanged.connect(self._update_title)
        name_row.addWidget(self._name_edit)
        c.addLayout(name_row)

        # Type
        type_row = QHBoxLayout()
        type_lbl = QLabel('type')
        type_lbl.setStyleSheet('color: #555; font-size: 11px;')
        type_lbl.setFixedWidth(40)
        type_row.addWidget(type_lbl)
        self._type_combo = QComboBox()
        self._type_combo.addItems(PATCH_TYPES)
        idx = self._type_combo.findText(self._patch.patch_type)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        self._type_combo.setStyleSheet(_combo_style())
        self._type_combo.currentTextChanged.connect(self._update_title)
        type_row.addWidget(self._type_combo)
        type_row.addStretch()
        c.addLayout(type_row)

        # Face list header
        faces_lbl = QLabel('FACES')
        faces_lbl.setStyleSheet(
            'color: #888; font-size: 10px; letter-spacing: 2px;')
        c.addWidget(faces_lbl)

        # Face rows container
        self._faces_layout = QVBoxLayout()
        self._faces_layout.setSpacing(2)
        c.addLayout(self._faces_layout)

        for face in self._patch.faces:
            self._add_face_row(_face_str(face))

        # + Add face
        add_face_btn = QPushButton('+ Add face')
        add_face_btn.setStyleSheet(f"""
            QPushButton {{
                color: {ACCENT}; border: 1px solid {ACCENT};
                border-radius: 3px; padding: 3px 8px;
                font-size: 11px; background: transparent;
            }}
            QPushButton:hover {{ background-color: {PASTEL}; }}
        """)
        add_face_btn.clicked.connect(lambda: self._add_face_row())
        c.addWidget(add_face_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Apply
        apply_row = QHBoxLayout()
        apply_row.addStretch()
        apply_btn = QPushButton('Apply')
        apply_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT}; color: white;
                border: none; border-radius: 3px;
                padding: 4px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #095048; }}
        """)
        apply_btn.clicked.connect(self._on_apply)
        apply_row.addWidget(apply_btn)
        c.addLayout(apply_row)

        self._content.setVisible(False)
        root.addWidget(self._content)

    # ------------------------------------------------------------------
    # Face row management
    # ------------------------------------------------------------------

    def _add_face_row(self, face_str: str = '') -> None:
        row_w = QWidget()
        row_layout = QHBoxLayout(row_w)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        edit = QLineEdit(face_str)
        edit.setPlaceholderText('vertex indices, e.g.  0 1 5 4')
        edit.setStyleSheet(_field_style())
        row_layout.addWidget(edit)

        del_btn = QPushButton('×')
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet("""
            QPushButton {
                color: #b03020; border: 1px solid #b03020;
                border-radius: 3px; font-size: 13px;
                background: transparent; padding: 0;
            }
            QPushButton:hover { background-color: #f5ddd9; }
        """)
        del_btn.clicked.connect(lambda: self._remove_face_row(row_w))
        row_layout.addWidget(del_btn)

        self._faces_layout.addWidget(row_w)
        self._face_edits.append(edit)
        self._face_row_widgets.append(row_w)

    def _remove_face_row(self, row_w: QWidget) -> None:
        try:
            i = self._face_row_widgets.index(row_w)
        except ValueError:
            return
        self._face_row_widgets.pop(i)
        self._face_edits.pop(i)
        self._faces_layout.removeWidget(row_w)
        row_w.deleteLater()

    # ------------------------------------------------------------------
    # Title
    # ------------------------------------------------------------------

    @staticmethod
    def _make_title(name: str, patch_type: str) -> str:
        return f'{name or "unnamed"} \u2014 {patch_type}'

    def _update_title(self) -> None:
        self._title_label.setText(
            self._make_title(self._name_edit.text(),
                             self._type_combo.currentText()))

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------

    def set_expanded(self, expanded: bool) -> None:
        if expanded != self._expanded:
            self._toggle()

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._arrow.setText('▼' if self._expanded else '▶')

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        name = self._name_edit.text().strip()
        if name:
            self._patch.name = name
        self._patch.patch_type = self._type_combo.currentText()

        faces: list[tuple[int, ...]] = []
        for edit in self._face_edits:
            f = _parse_face(edit.text())
            if f is not None:
                faces.append(f)
        self._patch.faces = faces

        self.apply_requested.emit()


# ---------------------------------------------------------------------------
# Patches panel
# ---------------------------------------------------------------------------

class PatchesPanel(QWidget):
    patch_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mesh:  BlockMesh | None = None
        self._items: list[_PatchItem] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header = QLabel('PATCHES')
        header.setStyleSheet(
            f'color: {ACCENT}; font-weight: bold; font-size: 11px; letter-spacing: 2px;')
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f'color: {ACCENT};')
        layout.addWidget(sep)

        # Scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._accordion = QVBoxLayout(self._container)
        self._accordion.setContentsMargins(0, 0, 4, 0)
        self._accordion.setSpacing(6)
        self._accordion.addStretch()

        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

        # Add patch button
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet('color: #ddd;')
        layout.addWidget(sep2)

        add_btn = QPushButton('+ Add patch')
        add_btn.setStyleSheet(f"""
            QPushButton {{
                color: {ACCENT}; border: 1px solid {ACCENT};
                border-radius: 3px; padding: 5px 12px;
                font-size: 12px; background: transparent;
            }}
            QPushButton:hover {{ background-color: {PASTEL}; }}
        """)
        add_btn.clicked.connect(self._on_add)
        layout.addWidget(add_btn)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load_mesh(self, mesh: BlockMesh) -> None:
        self._mesh = mesh
        self._rebuild_items()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_items(self) -> None:
        expanded = {i: item._expanded for i, item in enumerate(self._items)}

        for item in self._items:
            self._accordion.removeWidget(item)
            item.deleteLater()
        self._items.clear()

        if self._mesh is None:
            return

        stretch = self._accordion.takeAt(self._accordion.count() - 1)

        for i, patch in enumerate(self._mesh.patches):
            item = _PatchItem(i, patch)
            item.delete_requested.connect(
                lambda _=False, idx=i: self._on_delete(idx))
            item.apply_requested.connect(self._on_apply)
            self._accordion.addWidget(item)
            self._items.append(item)
            if expanded.get(i, False):
                item.set_expanded(True)

        self._accordion.addItem(stretch)

    def _on_apply(self) -> None:
        self.patch_changed.emit()

    def _on_delete(self, index: int) -> None:
        if self._mesh is None:
            return
        self._mesh.patches.pop(index)
        self._rebuild_items()
        self.patch_changed.emit()

    def _on_add(self) -> None:
        if self._mesh is None:
            return
        self._mesh.patches.append(
            BoundaryPatch(name='newPatch', patch_type='patch', faces=[]))
        self._rebuild_items()
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum())
        self.patch_changed.emit()


# ---------------------------------------------------------------------------
# Shared styles
# ---------------------------------------------------------------------------

def _field_style() -> str:
    return f"""
        QLineEdit {{
            border: 1px solid #bbb; border-radius: 3px;
            padding: 3px 6px; font-size: 12px; background: white;
        }}
        QLineEdit:focus {{ border-color: {ACCENT}; }}
    """


def _combo_style() -> str:
    return """
        QComboBox {
            border: 1px solid #bbb; border-radius: 3px;
            padding: 3px 6px; font-size: 12px; background: white;
        }
        QComboBox::drop-down { border: none; }
    """

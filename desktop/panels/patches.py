"""
Patches panel — scrollable accordion list of boundary patches.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QFrame,
    QScrollArea, QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.model import BlockMesh, BoundaryPatch

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
# Default patch interactive card
# ---------------------------------------------------------------------------

_DP_HEADER_ON  = PASTEL          # teal pastel — active
_DP_HEADER_OFF = '#e0e0e0'       # grey — inactive


class _DefaultPatchWidget(QFrame):
    """Interactive card for the defaultPatch entry — always shown at the top."""

    changed = pyqtSignal()

    def __init__(self, mesh: BlockMesh, parent: QWidget | None = None):
        super().__init__(parent)
        self._mesh = mesh
        self.setObjectName('defaultPatchWidget')
        self.setStyleSheet(
            'QFrame#defaultPatchWidget {'
            '  border: 1px solid #a8ddd4; border-radius: 4px;'
            '}')
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Colored header strip containing the checkbox ----
        self._header = QFrame()
        self._header.setObjectName('dpHeader')
        h = QHBoxLayout(self._header)
        h.setContentsMargins(8, 5, 8, 5)
        h.setSpacing(6)

        self._checkbox = QCheckBox('Default patch')
        self._checkbox.setStyleSheet(
            'font-weight: bold; font-size: 12px; background: transparent;')
        self._checkbox.setChecked(bool(self._mesh.default_patch_name))
        self._checkbox.toggled.connect(self._on_toggled)
        h.addWidget(self._checkbox)
        h.addStretch()
        root.addWidget(self._header)

        # ---- Editable fields (shown below the header) ----
        self._body = QFrame()
        self._body.setStyleSheet('background: white;')
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(10, 8, 10, 8)
        body_lay.setSpacing(6)

        # Name row
        name_row = QHBoxLayout()
        name_lbl = QLabel('name')
        name_lbl.setStyleSheet('color: #555; font-size: 11px;')
        name_lbl.setFixedWidth(40)
        name_row.addWidget(name_lbl)
        self._name_edit = QLineEdit(
            self._mesh.default_patch_name or 'defaultPatch')
        self._name_edit.setStyleSheet(_field_style())
        self._name_edit.editingFinished.connect(self._on_name_edited)
        name_row.addWidget(self._name_edit)
        body_lay.addLayout(name_row)

        # Type row
        type_row = QHBoxLayout()
        type_lbl = QLabel('type')
        type_lbl.setStyleSheet('color: #555; font-size: 11px;')
        type_lbl.setFixedWidth(40)
        type_row.addWidget(type_lbl)
        self._type_combo = QComboBox()
        self._type_combo.addItems(PATCH_TYPES)
        idx = self._type_combo.findText(self._mesh.default_patch_type or 'patch')
        self._type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._type_combo.setStyleSheet(_combo_style())
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        type_row.addWidget(self._type_combo)
        type_row.addStretch()
        body_lay.addLayout(type_row)

        # Explanatory note
        note = QLabel('Catches all block faces not listed in any explicit patch.')
        note.setStyleSheet('color: #888; font-size: 10px;')
        note.setWordWrap(True)
        body_lay.addWidget(note)

        root.addWidget(self._body)

        self._apply_enabled_state(bool(self._mesh.default_patch_name))

    # ------------------------------------------------------------------
    # Enable / disable editable fields
    # ------------------------------------------------------------------

    def _apply_enabled_state(self, enabled: bool) -> None:
        color = _DP_HEADER_ON if enabled else _DP_HEADER_OFF
        text_color = ACCENT if enabled else '#666'
        self._header.setStyleSheet(
            f'QFrame {{ background-color: {color}; border-radius: 3px; }}')
        self._checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {text_color};
                font-weight: bold;
                font-size: 12px;
                background: transparent;
            }}
            QCheckBox::indicator:unchecked {{
                width: 14px;
                height: 14px;
                border: 2px solid #888;
                border-radius: 3px;
                background-color: white;
            }}
        """)
        self._body.setVisible(enabled)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_toggled(self, checked: bool) -> None:
        self._apply_enabled_state(checked)
        if checked:
            name = self._name_edit.text().strip() or 'defaultPatch'
            self._name_edit.setText(name)
            self._mesh.default_patch_name = name
            self._mesh.default_patch_type = self._type_combo.currentText()
        else:
            self._mesh.default_patch_name = ''
        self.changed.emit()

    def _on_name_edited(self) -> None:
        if not self._checkbox.isChecked():
            return
        name = self._name_edit.text().strip()
        if not name:
            name = 'defaultPatch'
            self._name_edit.setText(name)
        self._mesh.default_patch_name = name
        self.changed.emit()

    def _on_type_changed(self, text: str) -> None:
        if not self._checkbox.isChecked():
            return
        self._mesh.default_patch_type = text
        self.changed.emit()


# ---------------------------------------------------------------------------
# Merge patch pairs section
# ---------------------------------------------------------------------------

class _MergePatchPairsWidget(QFrame):
    """Section card listing (patch1, patch2) merge pairs."""

    changed = pyqtSignal()

    def __init__(self, mesh: BlockMesh, patch_names: list[str],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._mesh = mesh
        # Each entry: (combo1, combo2, row_widget)
        self._rows: list[tuple[QComboBox, QComboBox, QWidget]] = []
        self.setObjectName('mppWidget')
        self.setStyleSheet(
            'QFrame#mppWidget {'
            '  border: 1px solid #a8ddd4; border-radius: 4px;'
            '}')
        self._build_ui(patch_names)

    def _build_ui(self, patch_names: list[str]) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header strip
        header = QFrame()
        header.setStyleSheet(f'background-color: {PASTEL}; border-radius: 3px;')
        h = QHBoxLayout(header)
        h.setContentsMargins(8, 5, 8, 5)
        lbl = QLabel('MERGE PATCH PAIRS')
        lbl.setStyleSheet(
            f'color: {ACCENT}; font-weight: bold; font-size: 11px;'
            ' letter-spacing: 1px; background: transparent;')
        h.addWidget(lbl)
        h.addStretch()
        root.addWidget(header)

        # Body
        body = QFrame()
        body.setStyleSheet('background: white;')
        self._body_lay = QVBoxLayout(body)
        self._body_lay.setContentsMargins(10, 8, 10, 8)
        self._body_lay.setSpacing(4)

        # Rows container
        self._rows_lay = QVBoxLayout()
        self._rows_lay.setSpacing(4)
        self._body_lay.addLayout(self._rows_lay)

        for p1, p2 in self._mesh.merge_patch_pairs:
            self._add_row(patch_names, p1, p2)

        # + Add pair button
        add_btn = QPushButton('+ Add pair')
        add_btn.setStyleSheet(f"""
            QPushButton {{
                color: {ACCENT}; border: 1px solid {ACCENT};
                border-radius: 3px; padding: 3px 8px;
                font-size: 11px; background: transparent;
            }}
            QPushButton:hover {{ background-color: {PASTEL}; }}
        """)
        add_btn.clicked.connect(lambda: self._on_add(patch_names))
        self._add_btn = add_btn
        self._body_lay.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        root.addWidget(body)

    def _make_combo(self, patch_names: list[str], current: str) -> QComboBox:
        cb = QComboBox()
        cb.addItem('')
        for name in patch_names:
            cb.addItem(name)
        idx = cb.findText(current)
        cb.setCurrentIndex(idx if idx >= 0 else 0)
        cb.setStyleSheet(_combo_style())
        cb.currentTextChanged.connect(self._write_back)
        return cb

    def _add_row(self, patch_names: list[str],
                 p1: str = '', p2: str = '') -> None:
        row_w = QWidget()
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)

        c1 = self._make_combo(patch_names, p1)
        c2 = self._make_combo(patch_names, p2)
        row_lay.addWidget(c1)
        row_lay.addWidget(c2)

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
        entry = (c1, c2, row_w)
        del_btn.clicked.connect(lambda: self._delete_row(entry))
        row_lay.addWidget(del_btn)

        self._rows_lay.addWidget(row_w)
        self._rows.append(entry)

    def _delete_row(self, entry: tuple) -> None:
        if entry not in self._rows:
            return
        self._rows.remove(entry)
        _, _, row_w = entry
        self._rows_lay.removeWidget(row_w)
        row_w.deleteLater()
        self._write_back()

    def _on_add(self, patch_names: list[str]) -> None:
        self._add_row(patch_names)
        self._write_back()

    def _write_back(self) -> None:
        self._mesh.merge_patch_pairs = [
            (c1.currentText(), c2.currentText())
            for c1, c2, _ in self._rows
            if c1.currentText() and c2.currentText()
        ]
        self.changed.emit()

    def refresh_names(self, patch_names: list[str]) -> None:
        """Repopulate all combo dropdowns after patch names change."""
        for c1, c2, _ in self._rows:
            for cb in (c1, c2):
                current = cb.currentText()
                cb.blockSignals(True)
                cb.clear()
                cb.addItem('')
                for name in patch_names:
                    cb.addItem(name)
                idx = cb.findText(current)
                cb.setCurrentIndex(idx if idx >= 0 else 0)
                cb.blockSignals(False)
        # Rebind + Add pair button to use fresh names
        try:
            self._add_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._add_btn.clicked.connect(lambda: self._on_add(patch_names))


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
        return f'{name or "unnamed"} — {patch_type}'

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
        self._dp_widget:   _DefaultPatchWidget | None = None
        self._dp_sep:      QFrame | None = None
        self._mpp_sep:     QFrame | None = None
        self._mpp_widget:  _MergePatchPairsWidget | None = None
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

    def _patch_names(self) -> list[str]:
        """Current list of patch names for combo population."""
        names = [p.name for p in self._mesh.patches] if self._mesh else []
        if self._mesh and self._mesh.default_patch_name:
            names = [self._mesh.default_patch_name] + names
        return names

    def _rebuild_items(self) -> None:
        expanded = {i: item._expanded for i, item in enumerate(self._items)}

        # Remove old widgets
        for w in (self._dp_widget, self._dp_sep,
                  self._mpp_sep, self._mpp_widget):
            if w is not None:
                self._accordion.removeWidget(w)
                w.deleteLater()
        self._dp_widget = self._dp_sep = None
        self._mpp_sep = self._mpp_widget = None

        for item in self._items:
            self._accordion.removeWidget(item)
            item.deleteLater()
        self._items.clear()

        if self._mesh is None:
            return

        stretch = self._accordion.takeAt(self._accordion.count() - 1)

        # Default patch card — always shown; checkbox reflects model state
        dp = _DefaultPatchWidget(self._mesh)
        dp.changed.connect(self._on_dp_changed)
        self._dp_widget = dp
        self._accordion.addWidget(dp)

        # Separator between default-patch card and explicit patches
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color: #c8e8e0;')
        self._dp_sep = sep
        self._accordion.addWidget(sep)

        for i, patch in enumerate(self._mesh.patches):
            item = _PatchItem(i, patch)
            item.delete_requested.connect(
                lambda _=False, idx=i: self._on_delete(idx))
            item.apply_requested.connect(self._on_apply)
            self._accordion.addWidget(item)
            self._items.append(item)
            if expanded.get(i, False):
                item.set_expanded(True)

        # Separator before merge patch pairs section
        mpp_sep = QFrame()
        mpp_sep.setFrameShape(QFrame.Shape.HLine)
        mpp_sep.setStyleSheet('color: #c8e8e0;')
        self._mpp_sep = mpp_sep
        self._accordion.addWidget(mpp_sep)

        # Merge patch pairs card — always shown
        mpp = _MergePatchPairsWidget(self._mesh, self._patch_names())
        mpp.changed.connect(self._on_apply)
        self._mpp_widget = mpp
        self._accordion.addWidget(mpp)

        self._accordion.addItem(stretch)

    def _on_apply(self) -> None:
        self.patch_changed.emit()

    def _on_dp_changed(self) -> None:
        """Default patch toggled or renamed — refresh merge pair combos too."""
        if self._mpp_widget is not None:
            self._mpp_widget.refresh_names(self._patch_names())
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

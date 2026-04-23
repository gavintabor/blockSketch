"""
Blocks panel — scrollable accordion list of hex blocks.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QFrame,
    QScrollArea, QSizePolicy, QMessageBox,
    QDialog, QDialogButtonBox, QInputDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator

from core.model import Block, BlockMesh

ACCENT = '#1a5c96'
PASTEL = '#d4e8f8'


# ---------------------------------------------------------------------------
# Grading serialisation helpers
# ---------------------------------------------------------------------------

def _grading_to_str(grading: list) -> str:
    """Flatten grading list to a human-readable space-separated string."""
    parts: list[str] = []
    for item in grading:
        if isinstance(item, list):
            parts.extend(_fmt(x) for x in item)
        else:
            parts.append(_fmt(item))
    return ' '.join(parts)


def _fmt(x) -> str:
    if x is None:
        return '0'
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def _str_to_grading(text: str) -> list:
    """Parse space-separated numbers back to a flat grading list."""
    result: list = []
    for tok in text.split():
        try:
            v = float(tok)
            result.append(int(v) if v == int(v) else v)
        except ValueError:
            pass
    return result


# ---------------------------------------------------------------------------
# Single block accordion item
# ---------------------------------------------------------------------------

class _BlockItem(QFrame):
    """Collapsible accordion card representing one hex block."""

    delete_requested  = pyqtSignal()
    apply_requested   = pyqtSignal()   # main window uses this to trigger refresh
    new_zone_created  = pyqtSignal(str)

    def __init__(self, block_index: int, block: Block, parent: QWidget | None = None):
        super().__init__(parent)
        self._block = block
        self._block_index = block_index
        self._expanded = False
        self._build_ui()
        self.setStyleSheet('QFrame#blockItem { border: 1px solid #c8daf0; border-radius: 4px; }')
        self.setObjectName('blockItem')

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Header ----
        self._header = QFrame()
        self._header.setStyleSheet(
            f'background-color: {PASTEL}; border-radius: 3px;')
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = lambda _e: self._toggle()

        h_layout = QHBoxLayout(self._header)
        h_layout.setContentsMargins(8, 5, 8, 5)
        h_layout.setSpacing(6)

        self._arrow = QLabel('▶')
        self._arrow.setStyleSheet(
            f'color: {ACCENT}; font-size: 10px; background: transparent;')
        self._arrow.setFixedWidth(14)
        h_layout.addWidget(self._arrow)

        title = QLabel(f'B{self._block_index} — hex')
        title.setStyleSheet(
            f'color: {ACCENT}; font-weight: bold; font-size: 12px; background: transparent;')
        h_layout.addWidget(title)
        h_layout.addStretch()

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
        h_layout.addWidget(del_btn)

        root.addWidget(self._header)

        # ---- Content ----
        self._content = QFrame()
        self._content.setStyleSheet('background: white;')
        c_layout = QVBoxLayout(self._content)
        c_layout.setContentsMargins(10, 8, 10, 8)
        c_layout.setSpacing(6)

        # Vertex indices
        _VERT_TOOLTIP = (
            'Hex vertex ordering: hex (a b c d e f g h)\n\n'
            '    h ---- g\n'
            '   /|     /|    z\n'
            '  e ---- f |    |  y\n'
            '  | d ---| c    | /\n'
            '  |/     |/     0 ---- x\n'
            '  a ---- b\n\n'
            'x-direction: a\u2192b\n'
            'y-direction: a\u2192d\n'
            'z-direction: a\u2192e\n\n'
            'simpleGrading (x-ratio  y-ratio  z-ratio)'
        )
        verts_row = self._make_row('vertices', '')
        info_btn = QPushButton('\u24d8')
        info_btn.setFixedSize(20, 20)
        info_btn.setStyleSheet("""
            QPushButton {
                color: #888; font-size: 12px; background: transparent;
                border: none; padding: 0;
            }
            QPushButton:hover { color: #555; }
        """)
        def _show_vert_help():
            dlg = QDialog(self)
            dlg.setWindowTitle('Hex vertex ordering')
            vlay = QVBoxLayout(dlg)
            lbl = QLabel()
            lbl.setText(
                '<pre style="font-family: Courier, monospace; font-size: 12px;">'
                'hex (a b c d e f g h)\n'
                '\n'
                '    h -------- g\n'
                '   /|         /|    z\n'
                '  e -------- f |    |  y\n'
                '  | d --------| c   | /\n'
                '  |/         |/     0 ---- x\n'
                '  a -------- b\n'
                '\n'
                'x-direction: a\u2192b\n'
                'y-direction: a\u2192d\n'
                'z-direction: a\u2192e\n'
                '\n'
                'simpleGrading (x-ratio  y-ratio  z-ratio)'
                '</pre>'
            )
            vlay.addWidget(lbl)
            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btns.accepted.connect(dlg.accept)
            vlay.addWidget(btns)
            dlg.exec()

        info_btn.clicked.connect(_show_vert_help)
        verts_row.addWidget(info_btn)
        c_layout.addLayout(verts_row)
        self._verts_edit = QLineEdit(
            ' '.join(str(v) for v in self._block.vertex_ids))
        self._verts_edit.setPlaceholderText('0 1 2 3 4 5 6 7')
        self._verts_edit.setStyleSheet(_field_style())
        c_layout.addWidget(self._verts_edit)

        # Cell counts
        c_layout.addLayout(self._make_row('cells', ''))
        cell_row = QHBoxLayout()
        cell_row.setSpacing(4)
        pos_int = QIntValidator(1, 9999)
        self._cell_edits: list[QLineEdit] = []
        for label, val in zip(('nx', 'ny', 'nz'), self._block.cells):
            lbl = QLabel(label)
            lbl.setStyleSheet(f'color: {ACCENT}; font-size: 11px;')
            lbl.setFixedWidth(18)
            cell_row.addWidget(lbl)
            edit = QLineEdit(str(val))
            edit.setValidator(pos_int)
            edit.setStyleSheet(_field_style())
            edit.setFixedWidth(52)
            cell_row.addWidget(edit)
            self._cell_edits.append(edit)
        cell_row.addStretch()
        c_layout.addLayout(cell_row)

        # Grading type + values
        c_layout.addLayout(self._make_row('grading', ''))
        grad_row = QHBoxLayout()
        grad_row.setSpacing(6)
        self._grading_combo = QComboBox()
        self._grading_combo.addItems(['simpleGrading', 'edgeGrading'])
        idx = self._grading_combo.findText(self._block.grading_type)
        if idx >= 0:
            self._grading_combo.setCurrentIndex(idx)
        self._grading_combo.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid #bbb; border-radius: 3px;
                padding: 3px 6px; font-size: 12px; background: white;
            }}
            QComboBox::drop-down {{ border: none; }}
        """)
        grad_row.addWidget(self._grading_combo)
        self._grading_edit = QLineEdit(_grading_to_str(self._block.grading))
        self._grading_edit.setPlaceholderText('1 1 1')
        self._grading_edit.setStyleSheet(_field_style())
        grad_row.addWidget(self._grading_edit)
        c_layout.addLayout(grad_row)

        # Zone name
        c_layout.addLayout(self._make_row('zone', ''))
        self._zone_combo = QComboBox()
        self._zone_combo.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid #bbb; border-radius: 3px;
                padding: 3px 6px; font-size: 12px; background: white;
            }}
            QComboBox::drop-down {{ border: none; }}
        """)
        self._zone_combo.activated.connect(self._on_zone_activated)
        c_layout.addWidget(self._zone_combo)

        # Apply button
        apply_row = QHBoxLayout()
        apply_row.addStretch()
        apply_btn = QPushButton('Apply')
        apply_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT}; color: white;
                border: none; border-radius: 3px;
                padding: 4px 14px; font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #123f6e; }}
        """)
        apply_btn.clicked.connect(self._on_apply)
        apply_row.addWidget(apply_btn)
        c_layout.addLayout(apply_row)

        self._content.setVisible(False)
        root.addWidget(self._content)

    @staticmethod
    def _make_row(label: str, tooltip: str) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet('color: #555; font-size: 11px;')
        if tooltip:
            lbl.setToolTip(tooltip)
        row.addWidget(lbl)
        row.addStretch()
        return row

    # ------------------------------------------------------------------
    # Zone combo interaction
    # ------------------------------------------------------------------

    def _on_zone_activated(self, index: int) -> None:
        if self._zone_combo.itemText(index) != '+ New zone…':
            return
        name, ok = QInputDialog.getText(self, 'New zone', 'Zone name:')
        name = name.strip()
        if ok and name:
            self.new_zone_created.emit(name)
        else:
            prev = self._block.zone_name
            revert_idx = self._zone_combo.findText(prev)
            self._zone_combo.setCurrentIndex(revert_idx if revert_idx >= 0 else 0)

    # ------------------------------------------------------------------
    # Zone combo population
    # ------------------------------------------------------------------

    def populate_zones(self, zone_names: list[str]) -> None:
        """Rebuild the zone dropdown from the current master zone list.

        Called by BlocksPanel whenever the zone list changes so all items
        stay in sync.  Preserves the block's current zone_name selection.
        """
        current = self._block.zone_name
        self._zone_combo.blockSignals(True)
        self._zone_combo.clear()
        self._zone_combo.addItem('')          # blank = no zone
        for name in zone_names:
            self._zone_combo.addItem(name)
        self._zone_combo.addItem('+ New zone…')
        idx = self._zone_combo.findText(current)
        self._zone_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._zone_combo.blockSignals(False)

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
    # Read back field values into the Block model
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        # Vertex indices
        try:
            ids = [int(t) for t in self._verts_edit.text().split()]
        except ValueError:
            ids = self._block.vertex_ids
        if len(ids) != 8:
            QMessageBox.warning(
                self, 'Invalid vertex list',
                f'A hex block requires exactly 8 vertex indices; got {len(ids)}.')
            return
        self._block.vertex_ids = ids

        # Cell counts
        try:
            cells = tuple(int(e.text()) for e in self._cell_edits)
        except ValueError:
            cells = self._block.cells
        self._block.cells = cells

        # Grading
        self._block.grading_type = self._grading_combo.currentText()
        grading_text = self._grading_edit.text().strip()
        if grading_text:
            self._block.grading = _str_to_grading(grading_text)

        # Zone
        zone = self._zone_combo.currentText()
        if zone == '+ New zone…':
            zone = self._block.zone_name   # revert if user applied without confirming
        self._block.zone_name = zone

        self.apply_requested.emit()


# ---------------------------------------------------------------------------
# Blocks panel
# ---------------------------------------------------------------------------

class BlocksPanel(QWidget):
    block_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mesh: BlockMesh | None = None
        self._items: list[_BlockItem] = []
        self._zone_names: list[str] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Header
        header = QLabel('BLOCKS')
        header.setStyleSheet(
            f'color: {ACCENT}; font-weight: bold; font-size: 11px; letter-spacing: 2px;')
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f'color: {ACCENT};')
        layout.addWidget(sep)

        # Scroll area containing the accordion
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._container = QWidget()
        self._accordion = QVBoxLayout(self._container)
        self._accordion.setContentsMargins(0, 0, 4, 0)
        self._accordion.setSpacing(6)
        self._accordion.addStretch()

        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

        # Add block button
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet('color: #ddd;')
        layout.addWidget(sep2)

        add_btn = QPushButton('+ Add block')
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

    def select_block(self, index: int) -> None:
        """Collapse all items, expand item at *index*, and scroll to it."""
        for i, item in enumerate(self._items):
            item.set_expanded(i == index)
        if 0 <= index < len(self._items):
            self._scroll.ensureWidgetVisible(self._items[index])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_items(self) -> None:
        """Tear down and rebuild all accordion items from the current mesh."""
        expanded = {i: item._expanded for i, item in enumerate(self._items)}

        for item in self._items:
            self._accordion.removeWidget(item)
            item.deleteLater()
        self._items.clear()

        if self._mesh is None:
            return

        # Rebuild master zone list from current block data, preserving order.
        seen: list[str] = []
        for b in self._mesh.blocks:
            if b.zone_name and b.zone_name not in seen:
                seen.append(b.zone_name)
        # Merge with any names added interactively this session.
        for name in self._zone_names:
            if name not in seen:
                seen.append(name)
        self._zone_names = seen

        stretch_item = self._accordion.takeAt(self._accordion.count() - 1)

        for i, block in enumerate(self._mesh.blocks):
            item = _BlockItem(i, block)
            item.delete_requested.connect(
                lambda _=False, idx=i: self._on_delete(idx))
            item.apply_requested.connect(self._on_apply)
            item.new_zone_created.connect(self._on_new_zone)
            item.populate_zones(self._zone_names)
            self._accordion.addWidget(item)
            self._items.append(item)
            if expanded.get(i, False):
                item.set_expanded(True)

        self._accordion.addItem(stretch_item)

    def _on_apply(self) -> None:
        self.block_changed.emit()

    def _on_new_zone(self, name: str) -> None:
        if name not in self._zone_names:
            self._zone_names.append(name)
        for item in self._items:
            item.populate_zones(self._zone_names)

    def _on_delete(self, index: int) -> None:
        if self._mesh is None:
            return
        self._mesh.blocks.pop(index)
        self._rebuild_items()
        self.block_changed.emit()

    def _on_add(self) -> None:
        if self._mesh is None:
            return
        self._mesh.blocks.append(Block(
            vertex_ids=[0, 1, 2, 3, 4, 5, 6, 7],
            cells=(8, 8, 8),
            grading_type='simpleGrading',
            grading=[1, 1, 1],
        ))
        self._rebuild_items()
        if self._items:
            self._items[-1].set_expanded(True)
        # Scroll to the new item
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum())
        self.block_changed.emit()


# ---------------------------------------------------------------------------
# Shared field style
# ---------------------------------------------------------------------------

def _field_style() -> str:
    return """
        QLineEdit {
            border: 1px solid #bbb; border-radius: 3px;
            padding: 3px 6px; font-size: 12px; background: white;
        }
        QLineEdit:focus { border-color: #1a5c96; }
    """

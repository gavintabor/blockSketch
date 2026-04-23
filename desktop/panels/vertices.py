"""
Vertices panel — table view of all vertices with inline editing.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QLineEdit,
    QPushButton, QFrame, QHeaderView, QMessageBox,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator

from core.model import BlockMesh, Vertex

ACCENT = '#1e7a40'
PASTEL = '#d4f0de'


class VerticesPanel(QWidget):
    vertex_changed = pyqtSignal()   # emitted whenever the model is modified

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mesh: BlockMesh | None = None
        self._selected_row: int = -1
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        # Header
        header = QLabel('VERTICES')
        header.setStyleSheet(
            f'color: {ACCENT}; font-weight: bold; font-size: 11px; letter-spacing: 2px;')
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f'color: {ACCENT};')
        layout.addWidget(sep)

        # ---- Table ----
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(['#', 'x', 'y', 'z'])
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in (1, 2, 3):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

        self._table.setStyleSheet(f"""
            QTableWidget {{
                border: 1px solid #ccc;
                gridline-color: #e0e0e0;
                font-size: 12px;
            }}
            QTableWidget::item:selected {{
                background-color: {PASTEL};
                color: #111;
            }}
            QHeaderView::section {{
                background-color: #f0f0f0;
                border: none;
                border-bottom: 1px solid #ccc;
                padding: 3px 6px;
                font-weight: bold;
                font-size: 11px;
                color: {ACCENT};
            }}
        """)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self._table)

        # ---- Edit fields ----
        edit_sep = QFrame()
        edit_sep.setFrameShape(QFrame.Shape.HLine)
        edit_sep.setStyleSheet('color: #ddd;')
        layout.addWidget(edit_sep)

        edit_lbl = QLabel('SELECTED VERTEX')
        edit_lbl.setStyleSheet('color: #888; font-size: 10px; letter-spacing: 2px;')
        layout.addWidget(edit_lbl)

        validator = QDoubleValidator()
        validator.setNotation(QDoubleValidator.Notation.ScientificNotation)

        self._edits: dict[str, QLineEdit] = {}
        for coord in ('x', 'y', 'z'):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            lbl = QLabel(coord)
            lbl.setFixedWidth(12)
            lbl.setStyleSheet(f'color: {ACCENT}; font-weight: bold;')
            row_layout.addWidget(lbl)
            edit = QLineEdit()
            edit.setValidator(validator)
            edit.setEnabled(False)
            edit.setStyleSheet("""
                QLineEdit {
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    padding: 3px 6px;
                    font-size: 12px;
                    background: white;
                }
                QLineEdit:disabled { background: #f5f5f5; color: #aaa; }
            """)
            row_layout.addWidget(edit)
            self._edits[coord] = edit
            layout.addLayout(row_layout)

        self._update_btn = QPushButton('Update')
        self._update_btn.setEnabled(False)
        self._update_btn.setStyleSheet(self._primary_btn_style())
        self._update_btn.clicked.connect(self._on_update)
        layout.addWidget(self._update_btn)

        layout.addSpacing(6)

        # ---- Add / Delete ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._add_btn = QPushButton('+ Add vertex')
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(self._secondary_btn_style())
        self._add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(self._add_btn)

        self._del_btn = QPushButton('Delete')
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(self._danger_btn_style())
        self._del_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._del_btn)

        layout.addLayout(btn_row)
        layout.addStretch()

    # ------------------------------------------------------------------
    # Button styles
    # ------------------------------------------------------------------

    def _primary_btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: {ACCENT};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 5px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background-color: #155d30; }}
            QPushButton:disabled {{ background-color: #bbb; color: #eee; }}
        """

    def _secondary_btn_style(self) -> str:
        return f"""
            QPushButton {{
                color: {ACCENT};
                border: 1px solid {ACCENT};
                border-radius: 3px;
                padding: 4px 10px;
                font-size: 12px;
                background: transparent;
            }}
            QPushButton:hover {{ background-color: {PASTEL}; }}
            QPushButton:disabled {{ color: #bbb; border-color: #bbb; }}
        """

    def _danger_btn_style(self) -> str:
        return """
            QPushButton {
                color: #b03020;
                border: 1px solid #b03020;
                border-radius: 3px;
                padding: 4px 10px;
                font-size: 12px;
                background: transparent;
            }
            QPushButton:hover { background-color: #f5ddd9; }
            QPushButton:disabled { color: #bbb; border-color: #bbb; }
        """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def load_mesh(self, mesh: BlockMesh) -> None:
        """Populate the table from *mesh*. Call whenever mesh is (re)loaded."""
        self._mesh = mesh
        self._selected_row = -1
        self._populate_table()
        self._clear_edit_fields()
        self._add_btn.setEnabled(True)

    def select_vertex(self, index: int) -> None:
        """Select a row by vertex index — called from main window on 3D pick."""
        if self._mesh is None or index >= len(self._mesh.vertices):
            return
        # Block signals to avoid re-entrant selection loop
        self._table.blockSignals(True)
        self._table.selectRow(index)
        self._table.blockSignals(False)
        self._table.scrollTo(self._table.model().index(index, 0))
        self._selected_row = index
        self._populate_edit_fields(index)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        if self._mesh is None:
            return
        for v in self._mesh.vertices:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, _cell(str(v.index), center=True))
            self._table.setItem(r, 1, _cell(f'{v.x:g}'))
            self._table.setItem(r, 2, _cell(f'{v.y:g}'))
            self._table.setItem(r, 3, _cell(f'{v.z:g}'))

    def _populate_edit_fields(self, row: int) -> None:
        if self._mesh is None or row >= len(self._mesh.vertices):
            return
        v = self._mesh.vertices[row]
        self._edits['x'].setText(f'{v.x:g}')
        self._edits['y'].setText(f'{v.y:g}')
        self._edits['z'].setText(f'{v.z:g}')
        for edit in self._edits.values():
            edit.setEnabled(True)
        self._update_btn.setEnabled(True)
        self._del_btn.setEnabled(True)

    def _clear_edit_fields(self) -> None:
        for edit in self._edits.values():
            edit.clear()
            edit.setEnabled(False)
        self._update_btn.setEnabled(False)
        self._del_btn.setEnabled(False)

    def _referenced_by_blocks(self, vertex_index: int) -> list[int]:
        """Return list of block indices that reference *vertex_index*."""
        if self._mesh is None:
            return []
        return [bi for bi, b in enumerate(self._mesh.blocks)
                if vertex_index in b.vertex_ids]

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_row_selected(self) -> None:
        if not self._table.selectedItems():
            self._selected_row = -1
            self._clear_edit_fields()
            return
        row = self._table.currentRow()
        self._selected_row = row
        self._populate_edit_fields(row)

    def _on_update(self) -> None:
        if self._mesh is None or self._selected_row < 0:
            return
        row = self._selected_row
        if row >= len(self._mesh.vertices):
            return
        try:
            x = float(self._edits['x'].text())
            y = float(self._edits['y'].text())
            z = float(self._edits['z'].text())
        except ValueError:
            return

        v = self._mesh.vertices[row]
        v.x, v.y, v.z = x, y, z

        # Update table cells in place (no full repopulate needed)
        self._table.item(row, 1).setText(f'{x:g}')
        self._table.item(row, 2).setText(f'{y:g}')
        self._table.item(row, 3).setText(f'{z:g}')

        self.vertex_changed.emit()

    def _on_add(self) -> None:
        if self._mesh is None:
            return
        try:
            x = float(self._edits['x'].text())
            y = float(self._edits['y'].text())
            z = float(self._edits['z'].text())
        except ValueError:
            x = y = z = 0.0
        new_index = len(self._mesh.vertices)
        self._mesh.vertices.append(Vertex(x=x, y=y, z=z, index=new_index))

        r = self._table.rowCount()
        self._table.insertRow(r)
        self._table.setItem(r, 0, _cell(str(new_index), center=True))
        self._table.setItem(r, 1, _cell(f'{x:g}'))
        self._table.setItem(r, 2, _cell(f'{y:g}'))
        self._table.setItem(r, 3, _cell(f'{z:g}'))

        self._table.selectRow(r)
        self._table.scrollToBottom()
        self.vertex_changed.emit()

    def _on_delete(self) -> None:
        if self._mesh is None or self._selected_row < 0:
            return
        row = self._selected_row
        v = self._mesh.vertices[row]
        vi = v.index

        in_blocks = self._referenced_by_blocks(vi)
        if in_blocks:
            block_list = ', '.join(f'Block {bi}' for bi in in_blocks)
            QMessageBox.warning(
                self,
                'Vertex in use',
                f'Vertex {vi} is referenced by {block_list}.\n\n'
                'Remove or update those blocks before deleting this vertex.',
            )
            return

        # Safe to delete — remove from model and renumber remaining vertices
        self._mesh.vertices.pop(row)
        for i, vert in enumerate(self._mesh.vertices):
            vert.index = i

        # Rebuild table from scratch (indices have shifted)
        self._populate_table()
        self._selected_row = -1
        self._clear_edit_fields()
        self.vertex_changed.emit()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _cell(text: str, center: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    align = Qt.AlignmentFlag.AlignVCenter
    align |= Qt.AlignmentFlag.AlignCenter if center else Qt.AlignmentFlag.AlignRight
    item.setTextAlignment(align)
    return item

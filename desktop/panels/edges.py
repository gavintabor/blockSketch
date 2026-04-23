"""
Edges panel — scrollable accordion list of curved edges.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QFrame,
    QScrollArea, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator

from core.model import ArcEdge, BlockMesh, SplineEdge

ACCENT = '#aa7722'
PASTEL = '#f5eddd'

EDGE_TYPES = ['arc', 'spline', 'polyLine', 'BSpline']


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _xyz_str(pt: tuple | list) -> str:
    return ' '.join(_fmt(v) for v in pt)


def _fmt(x) -> str:
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def _parse_xyz(text: str) -> tuple[float, float, float] | None:
    parts = text.split()
    if len(parts) != 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Single edge accordion item
# ---------------------------------------------------------------------------

class _EdgeItem(QFrame):
    delete_requested = pyqtSignal()
    apply_requested  = pyqtSignal()

    def __init__(self, edge_index: int, edge, parent: QWidget | None = None,
                 is_new: bool = False):
        super().__init__(parent)
        self._edge_index = edge_index
        self._expanded = False
        self._is_new = is_new

        # Unpack initial state
        if isinstance(edge, ArcEdge):
            self._init_type     = 'arc'
            self._init_vs       = edge.v_start
            self._init_ve       = edge.v_end
            self._init_mid      = _xyz_str(edge.point)
            self._init_is_origin: bool = edge.is_origin
            self._init_pts: list[str] = []
        else:                                     # SplineEdge
            self._init_type     = edge.kind
            self._init_vs       = edge.v_start
            self._init_ve       = edge.v_end
            self._init_mid      = ''
            self._init_is_origin = False
            self._init_pts      = [_xyz_str(p) for p in edge.points]

        # Mutable state for multi-point rows
        self._point_edits:       list[QLineEdit] = []
        self._point_row_widgets: list[QWidget]   = []
        self._point_idx_labels:  list[QLabel]    = []

        self._build_ui()
        self.setObjectName('edgeItem')
        self.setStyleSheet(
            'QFrame#edgeItem { border: 1px solid #e0d0b0; border-radius: 4px; }')

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
            'newEdge' if self._is_new
            else self._make_title(self._init_type, self._init_vs, self._init_ve))
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

        int_v = QIntValidator(0, 99999)

        # Type
        type_row = QHBoxLayout()
        type_lbl = QLabel('type')
        type_lbl.setStyleSheet('color: #555; font-size: 11px;')
        type_lbl.setFixedWidth(55)
        type_row.addWidget(type_lbl)
        self._type_combo = QComboBox()
        self._type_combo.addItems(EDGE_TYPES)
        self._type_combo.setCurrentText(self._init_type)
        self._type_combo.setStyleSheet(_combo_style())
        type_row.addWidget(self._type_combo)
        type_row.addStretch()
        c.addLayout(type_row)

        # v start
        vs_row = QHBoxLayout()
        vs_lbl = QLabel('v start')
        vs_lbl.setStyleSheet('color: #555; font-size: 11px;')
        vs_lbl.setFixedWidth(55)
        vs_row.addWidget(vs_lbl)
        self._vstart_edit = QLineEdit(str(self._init_vs))
        self._vstart_edit.setValidator(int_v)
        self._vstart_edit.setFixedWidth(60)
        self._vstart_edit.setStyleSheet(_field_style())
        vs_row.addWidget(self._vstart_edit)
        vs_row.addStretch()
        c.addLayout(vs_row)

        # v end
        ve_row = QHBoxLayout()
        ve_lbl = QLabel('v end')
        ve_lbl.setStyleSheet('color: #555; font-size: 11px;')
        ve_lbl.setFixedWidth(55)
        ve_row.addWidget(ve_lbl)
        self._vend_edit = QLineEdit(str(self._init_ve))
        self._vend_edit.setValidator(int_v)
        self._vend_edit.setFixedWidth(60)
        self._vend_edit.setStyleSheet(_field_style())
        ve_row.addWidget(self._vend_edit)
        ve_row.addStretch()
        c.addLayout(ve_row)

        # Control points section header
        self._ctrl_lbl = QLabel(
            'CONTROL POINT' if self._init_type == 'arc' else 'CONTROL POINTS')
        self._ctrl_lbl.setStyleSheet(
            'color: #888; font-size: 10px; letter-spacing: 2px;')
        c.addWidget(self._ctrl_lbl)

        # ---- Arc widget ----
        self._arc_widget = QWidget()
        arc_layout = QVBoxLayout(self._arc_widget)
        arc_layout.setContentsMargins(0, 0, 0, 0)
        arc_layout.setSpacing(4)

        # Arc definition method selector
        method_row = QHBoxLayout()
        method_row.setSpacing(6)
        method_lbl = QLabel('Arc defined by:')
        method_lbl.setStyleSheet('color: #555; font-size: 11px;')
        method_row.addWidget(method_lbl)
        self._arc_method_combo = QComboBox()
        self._arc_method_combo.addItems(['Point on arc', 'Circle centre'])
        self._arc_method_combo.setStyleSheet(_combo_style())
        method_row.addWidget(self._arc_method_combo)
        method_row.addStretch()
        arc_layout.addLayout(method_row)

        # Point field — label updates with method selection
        mid_row = QHBoxLayout()
        self._arc_pt_lbl = QLabel('Arc pt')
        self._arc_pt_lbl.setStyleSheet('color: #555; font-size: 11px;')
        self._arc_pt_lbl.setFixedWidth(55)
        mid_row.addWidget(self._arc_pt_lbl)
        self._mid_edit = QLineEdit(self._init_mid)
        self._mid_edit.setPlaceholderText('x  y  z')
        self._mid_edit.setStyleSheet(_field_style())
        mid_row.addWidget(self._mid_edit)
        arc_layout.addLayout(mid_row)

        # Set initial method and label, then wire signal
        init_method = 'Circle centre' if self._init_is_origin else 'Point on arc'
        self._arc_method_combo.setCurrentText(init_method)
        self._on_arc_method_changed(init_method)
        self._arc_method_combo.currentTextChanged.connect(self._on_arc_method_changed)

        c.addWidget(self._arc_widget)

        # ---- Multi-point widget ----
        self._multi_widget = QWidget()
        multi_layout = QVBoxLayout(self._multi_widget)
        multi_layout.setContentsMargins(0, 0, 0, 0)
        multi_layout.setSpacing(2)

        self._points_layout = QVBoxLayout()
        self._points_layout.setSpacing(2)
        multi_layout.addLayout(self._points_layout)

        add_pt_btn = QPushButton('+ Add point')
        add_pt_btn.setStyleSheet(f"""
            QPushButton {{
                color: {ACCENT}; border: 1px solid {ACCENT};
                border-radius: 3px; padding: 3px 8px;
                font-size: 11px; background: transparent;
            }}
            QPushButton:hover {{ background-color: {PASTEL}; }}
        """)
        add_pt_btn.clicked.connect(lambda: self._add_point_row())
        multi_layout.addWidget(add_pt_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        c.addWidget(self._multi_widget)

        # Populate initial multi-point rows
        for xyz_str in self._init_pts:
            self._add_point_row(xyz_str)

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
            QPushButton:hover {{ background-color: #7a5515; }}
        """)
        apply_btn.clicked.connect(self._on_apply)
        apply_row.addWidget(apply_btn)
        c.addLayout(apply_row)

        self._content.setVisible(False)
        root.addWidget(self._content)

        # Wire type combo
        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._vstart_edit.textChanged.connect(self._update_title)
        self._vend_edit.textChanged.connect(self._update_title)

        # Set initial visibility
        is_arc = (self._init_type == 'arc')
        self._arc_widget.setVisible(is_arc)
        self._multi_widget.setVisible(not is_arc)

    # ------------------------------------------------------------------
    # Point row management
    # ------------------------------------------------------------------

    def _add_point_row(self, xyz_str: str = '') -> None:
        index = len(self._point_edits)

        row_w = QWidget()
        row_layout = QHBoxLayout(row_w)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)

        idx_lbl = QLabel(str(index))
        idx_lbl.setStyleSheet(f'color: {ACCENT}; font-size: 11px; min-width: 14px;')
        row_layout.addWidget(idx_lbl)

        edit = QLineEdit(xyz_str)
        edit.setPlaceholderText('x  y  z')
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
        del_btn.clicked.connect(lambda: self._remove_point_row(row_w))
        row_layout.addWidget(del_btn)

        self._points_layout.addWidget(row_w)
        self._point_edits.append(edit)
        self._point_row_widgets.append(row_w)
        self._point_idx_labels.append(idx_lbl)

    def _remove_point_row(self, row_w: QWidget) -> None:
        try:
            i = self._point_row_widgets.index(row_w)
        except ValueError:
            return
        self._point_row_widgets.pop(i)
        self._point_edits.pop(i)
        self._point_idx_labels.pop(i)
        self._points_layout.removeWidget(row_w)
        row_w.deleteLater()
        # Renumber remaining labels
        for j, lbl in enumerate(self._point_idx_labels):
            lbl.setText(str(j))

    # ------------------------------------------------------------------
    # Type change
    # ------------------------------------------------------------------

    def _on_arc_method_changed(self, method: str) -> None:
        if method == 'Circle centre':
            self._arc_pt_lbl.setText('Centre')
            self._arc_pt_lbl.setToolTip('The centre of the circle')
        else:
            self._arc_pt_lbl.setText('Arc pt')
            self._arc_pt_lbl.setToolTip('A point on the arc between v_start and v_end')

    def _on_type_changed(self, new_type: str) -> None:
        was_arc = self._arc_widget.isVisible()
        is_arc  = (new_type == 'arc')

        if was_arc and not is_arc:
            # Carry arc midpoint across as first control point
            mid = self._mid_edit.text().strip()
            if mid and not self._point_edits:
                self._add_point_row(mid)

        elif not was_arc and is_arc:
            # Carry first control point across as midpoint
            if self._point_edits and not self._mid_edit.text().strip():
                self._mid_edit.setText(self._point_edits[0].text())

        self._ctrl_lbl.setText('CONTROL POINT' if is_arc else 'CONTROL POINTS')
        self._arc_widget.setVisible(is_arc)
        self._multi_widget.setVisible(not is_arc)
        self._update_title()

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
    # Title
    # ------------------------------------------------------------------

    @staticmethod
    def _make_title(typ: str, vs, ve) -> str:
        return f'{typ} {vs}\u2192{ve}'

    def _update_title(self) -> None:
        self._title_label.setText(self._make_title(
            self._type_combo.currentText(),
            self._vstart_edit.text() or '?',
            self._vend_edit.text()   or '?',
        ))

    # ------------------------------------------------------------------
    # Apply / read back
    # ------------------------------------------------------------------

    def get_edge(self):
        """Return the current state as an ArcEdge or SplineEdge model object."""
        try:
            vs = int(self._vstart_edit.text())
        except ValueError:
            vs = 0
        try:
            ve = int(self._vend_edit.text())
        except ValueError:
            ve = 0

        typ = self._type_combo.currentText()

        if typ == 'arc':
            mid = _parse_xyz(self._mid_edit.text()) or (0.0, 0.0, 0.0)
            is_origin = self._arc_method_combo.currentText() == 'Circle centre'
            return ArcEdge(v_start=vs, v_end=ve, point=mid, is_origin=is_origin)
        else:
            pts = []
            for edit in self._point_edits:
                p = _parse_xyz(edit.text())
                if p is not None:
                    pts.append(p)
            return SplineEdge(kind=typ, v_start=vs, v_end=ve, points=pts)

    def _on_apply(self) -> None:
        self._is_new = False
        self._update_title()
        self.apply_requested.emit()


# ---------------------------------------------------------------------------
# Edges panel
# ---------------------------------------------------------------------------

class EdgesPanel(QWidget):
    edge_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mesh: BlockMesh | None = None
        self._items: list[_EdgeItem] = []
        self._pending_item: _EdgeItem | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header = QLabel('EDGES')
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

        # Add edge button
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet('color: #ddd;')
        layout.addWidget(sep2)

        add_btn = QPushButton('+ Add edge')
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

    def select_edge(self, index: int) -> None:
        """Collapse all items, expand item at *index*, and scroll to it."""
        for i, item in enumerate(self._items):
            item.set_expanded(i == index)
        if 0 <= index < len(self._items):
            self._scroll.ensureWidgetVisible(self._items[index])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_items(self) -> None:
        # Discard any pending (unapplied) new edge
        if self._pending_item is not None:
            self._accordion.removeWidget(self._pending_item)
            self._pending_item.deleteLater()
            self._pending_item = None

        expanded = {i: item._expanded for i, item in enumerate(self._items)}

        for item in self._items:
            self._accordion.removeWidget(item)
            item.deleteLater()
        self._items.clear()

        if self._mesh is None:
            return

        stretch = self._accordion.takeAt(self._accordion.count() - 1)

        for i, edge in enumerate(self._mesh.edges):
            item = _EdgeItem(i, edge)
            item.delete_requested.connect(
                lambda _=False, idx=i: self._on_delete(idx))
            item.apply_requested.connect(
                lambda _=False, idx=i, it=item: self._on_apply(idx, it))
            self._accordion.addWidget(item)
            self._items.append(item)
            if expanded.get(i, False):
                item.set_expanded(True)

        self._accordion.addItem(stretch)

    def _on_apply(self, index: int, item: _EdgeItem) -> None:
        if self._mesh is None:
            return
        if index < len(self._mesh.edges):
            self._mesh.edges[index] = item.get_edge()
        self.edge_changed.emit()

    def _on_delete(self, index: int) -> None:
        if self._mesh is None:
            return
        self._mesh.edges.pop(index)
        self._rebuild_items()
        self.edge_changed.emit()

    def _on_add(self) -> None:
        if self._mesh is None:
            return
        # Discard any previous pending item before creating a new one
        if self._pending_item is not None:
            self._accordion.removeWidget(self._pending_item)
            self._pending_item.deleteLater()
            self._pending_item = None

        item = _EdgeItem(len(self._mesh.edges),
                         ArcEdge(v_start=0, v_end=1, point=(0.0, 0.0, 0.0)),
                         is_new=True)
        item.apply_requested.connect(self._on_pending_apply)
        item.delete_requested.connect(self._on_pending_cancel)
        # Insert before the trailing stretch
        self._accordion.insertWidget(self._accordion.count() - 1, item)
        self._pending_item = item
        item.set_expanded(True)
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum())

    def _on_pending_apply(self) -> None:
        if self._pending_item is None or self._mesh is None:
            return
        self._mesh.edges.append(self._pending_item.get_edge())
        self._rebuild_items()
        self.edge_changed.emit()

    def _on_pending_cancel(self) -> None:
        if self._pending_item is None:
            return
        self._accordion.removeWidget(self._pending_item)
        self._pending_item.deleteLater()
        self._pending_item = None


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

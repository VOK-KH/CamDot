"""Tree view adapter: package rows with Video / Audio / Image children."""
from PySide6.QtCore import QAbstractProxyModel, QModelIndex, Qt


class _TreeNode:
    __slots__ = ("flat_row", "parent", "children")

    def __init__(self, flat_row, parent=None):
        self.flat_row = flat_row
        self.parent = parent
        self.children = []


class ReelTreeProxy(QAbstractProxyModel):
    """Present the flat reel filter model as a package tree for QTreeView."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roots = []
        self._nodes = {}
        self._folder_group = False

    def set_folder_group(self, enabled):
        enabled = bool(enabled)
        if enabled == self._folder_group:
            return
        self._folder_group = enabled
        self._rebuild()

    def setSourceModel(self, model):
        old = self.sourceModel()
        if old is not None:
            for signal in (
                old.modelReset,
                old.layoutChanged,
                old.rowsInserted,
                old.rowsRemoved,
            ):
                try:
                    signal.disconnect(self._rebuild)
                except (RuntimeError, TypeError):
                    pass
        super().setSourceModel(model)
        if model is not None:
            model.modelReset.connect(self._rebuild)
            model.layoutChanged.connect(self._rebuild)
            model.rowsInserted.connect(self._rebuild)
            model.rowsRemoved.connect(self._rebuild)
        self._rebuild()

    def _reel_model(self):
        source = self.sourceModel()
        if source is None:
            return None
        return source.sourceModel()

    def _node(self, index):
        if not index.isValid():
            return None
        return self._nodes.get(index.internalId())

    def _visible(self, src_row):
        source = self.sourceModel()
        if source is None:
            return False
        return source.filterAcceptsRow(src_row, QModelIndex())

    def _register(self, node):
        self._nodes[id(node)] = node
        return id(node)

    def _rebuild(self, *_args):
        self.beginResetModel()
        self._roots = []
        self._nodes = {}
        model = self._reel_model()
        if model is not None:
            packages = {}
            for src_row in range(model.rowCount()):
                if not self._visible(src_row):
                    continue
                reel = model.reel_at(src_row)
                if reel.variant and self._folder_group:
                    parent = packages.get(reel.url)
                    if parent is None:
                        continue
                    node = _TreeNode(src_row, parent)
                    parent.children.append(node)
                    self._register(node)
                else:
                    node = _TreeNode(src_row)
                    if self._folder_group and not reel.variant:
                        packages[reel.url] = node
                    self._roots.append(node)
                    self._register(node)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        node = self._node(parent)
        if node is None:
            return len(self._roots)
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        source = self.sourceModel()
        return source.columnCount() if source is not None else 0

    def index(self, row, column, parent=QModelIndex()):
        if row < 0 or column < 0:
            return QModelIndex()
        node = self._node(parent)
        if node is None:
            if row >= len(self._roots):
                return QModelIndex()
            child = self._roots[row]
        else:
            if row >= len(node.children):
                return QModelIndex()
            child = node.children[row]
        return self.createIndex(row, column, id(child))

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = self._node(index)
        if node is None or node.parent is None:
            return QModelIndex()
        parent = node.parent
        grand = parent.parent
        row = self._roots.index(parent) if grand is None else grand.children.index(parent)
        return self.createIndex(row, 0, id(parent))

    def mapToSource(self, proxy_index):
        if not proxy_index.isValid():
            return QModelIndex()
        node = self._node(proxy_index)
        source = self.sourceModel()
        if node is None or source is None:
            return QModelIndex()
        return source.index(node.flat_row, proxy_index.column())

    def mapFromSource(self, source_index):
        if not source_index.isValid():
            return QModelIndex()
        node = None
        for candidate in self._nodes.values():
            if candidate.flat_row == source_index.row():
                node = candidate
                break
        if node is None:
            return QModelIndex()
        if node.parent is None:
            row = self._roots.index(node)
        else:
            row = node.parent.children.index(node)
        return self.createIndex(row, source_index.column(), id(node))

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        source = self.mapToSource(index)
        model = self.sourceModel()
        return model.data(source, role) if model is not None and source.isValid() else None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        source = self.mapToSource(index)
        model = self.sourceModel()
        return model.setData(source, value, role) if model is not None and source.isValid() else False

    def flags(self, index):
        source = self.mapToSource(index)
        model = self.sourceModel()
        return model.flags(source) if model is not None and source.isValid() else Qt.ItemFlag.NoItemFlags

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        source = self.sourceModel()
        return source.headerData(section, orientation, role) if source is not None else None

    def hasChildren(self, parent=QModelIndex()):
        node = self._node(parent)
        if node is None:
            return bool(self._roots)
        return bool(node.children)

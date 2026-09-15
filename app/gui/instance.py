"""One running CamDot window: lock file plus a local socket to raise it."""
import os

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from app.core.runtime import state_dir

SERVER_NAME = "CamDotGui"
LOCK_NAME = "gui.lock"


class InstanceGuard(QObject):
    """Keeps a second launch from stacking another window and tray icon."""

    activate = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = QLockFile(os.path.join(state_dir(), LOCK_NAME))
        self._lock.setStaleLockTime(10_000)
        self._server = None

    def acquire(self):
        """True when this process owns the GUI lock."""
        os.makedirs(state_dir(), exist_ok=True)
        self._lock.removeStaleLockFile()
        if not self._lock.tryLock(100):
            return False
        QLocalServer.removeServer(SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(SERVER_NAME)
        return True

    def ping_existing(self):
        """Ask the running instance to show its window. False if nobody listens."""
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if not sock.waitForConnected(400):
            return False
        sock.write(b"raise\n")
        sock.waitForBytesWritten(400)
        sock.disconnectFromServer()
        return True

    def release(self):
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(SERVER_NAME)
            self._server = None
        if self._lock.isLocked():
            self._lock.unlock()

    def _on_connection(self):
        sock = self._server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(self.activate)
        self.activate.emit()
        sock.disconnectFromServer()

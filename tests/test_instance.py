"""Single-instance guard for the desktop GUI."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.gui.instance import InstanceGuard


class InstanceGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self._state = patch(
            "app.gui.instance.state_dir", return_value=self.folder.name
        )
        self._state.start()
        self.guards = []

    def tearDown(self):
        for guard in self.guards:
            guard.release()
        self._state.stop()
        self.folder.cleanup()

    def _guard(self):
        guard = InstanceGuard()
        self.guards.append(guard)
        return guard

    def test_second_acquire_fails_while_first_holds_the_lock(self):
        first = self._guard()
        second = self._guard()
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())

    def test_ping_existing_notifies_the_owner(self):
        first = self._guard()
        second = self._guard()
        raised = []
        first.activate.connect(lambda: raised.append(True))
        self.assertTrue(first.acquire())
        self.assertTrue(second.ping_existing())
        QApplication.processEvents()
        self.assertTrue(raised)

    def test_release_allows_another_owner(self):
        first = self._guard()
        second = self._guard()
        self.assertTrue(first.acquire())
        first.release()
        self.assertTrue(second.acquire())

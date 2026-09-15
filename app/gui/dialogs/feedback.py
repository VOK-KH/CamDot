"""Send feedback to the CamDot maintainer."""
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from app.core.telegram_report import report_feedback


class FeedbackDialog(QDialog):
    def __init__(self, device_id="", log_text="", parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._log_text = log_text
        self.setWindowTitle("Send feedback")
        self.resize(480, 320)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Describe the issue or suggestion. Recent log lines are attached automatically.")
        )
        self.message = QPlainTextEdit()
        self.message.setPlaceholderText("What happened? What did you expect?")
        layout.addWidget(self.message, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._send)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _send(self):
        text = self.message.toPlainText().strip()
        if not text:
            self.message.setFocus()
            return
        excerpt = self._log_text.strip()
        if len(excerpt) > 2500:
            excerpt = excerpt[-2500:]
        report_feedback(text, device_id=self._device_id, log_excerpt=excerpt)
        self.accept()

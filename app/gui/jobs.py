"""Background collect/download jobs for the GUI (runs off the UI thread)."""
import threading
import time

from PySide6.QtCore import QObject, Signal, Slot

from app.core.collect import collect_entries
from app.core.download import DEFAULT_FRAGMENTS, DEFAULT_WORKERS, download_urls
from app.core.jobs import StopRequested
from app.core.runtime import default_output_root


class JobWorker(QObject):
    """Runs scraping and downloading off the UI thread."""

    log_line = Signal(str)
    waiting_login = Signal()
    urls_ready = Signal(list)
    progress = Signal(str, dict)
    finished = Signal(str)

    def __init__(
        self, mode, channel, url="", urls=None, workers=DEFAULT_WORKERS,
        fragments=DEFAULT_FRAGMENTS, output_root=None, chrome_binary="",
        ffmpeg_location="", cookies_browser="", feed=None, filename_template="",
        cookies_file="", dateafter="", limit_rate="",
        media_kinds=None, source_folders=None,
    ):
        super().__init__()
        self.mode = mode
        self.channel = channel
        self.url = url
        self.urls = urls or []
        self.workers = workers
        self.fragments = fragments
        self.output_root = output_root or default_output_root()
        self.chrome_binary = chrome_binary
        self.ffmpeg_location = ffmpeg_location
        self.cookies_browser = cookies_browser
        self.feed = feed
        self.filename_template = filename_template
        self.cookies_file = cookies_file
        self.dateafter = dateafter
        self.limit_rate = limit_rate
        self.media_kinds = media_kinds
        self.source_folders = source_folders or {}
        self._stop = False
        self._login = threading.Event()
        self._last_emit = {}
        self._emit_lock = threading.Lock()

    def request_stop(self):
        self._stop = True
        self._login.set()

    def continue_login(self):
        self._login.set()

    def _log(self, message):
        self.log_line.emit(str(message).rstrip())

    def _should_stop(self):
        return self._stop

    def _wait_for_login(self):
        self._login.clear()
        self.waiting_login.emit()
        while not self._login.wait(timeout=0.2):
            if self._stop:
                raise StopRequested("Cancelled.")

    def _on_progress(self, url, event):
        # Progress arrives from every download thread at once; throttle the noisy
        # "downloading" updates so the table repaints instead of queueing signals.
        if event.get("status") == "downloading":
            now = time.monotonic()
            with self._emit_lock:
                if now - self._last_emit.get(url, 0.0) < 0.2:
                    return
                self._last_emit[url] = now
        self.progress.emit(url, event)

    @Slot()
    def run(self):
        try:
            # Collecting only fills the table; downloading is a separate click,
            # so the whole list can be reviewed first.
            if self.mode == "collect":
                streamed = []

                def on_entries(batch):
                    streamed.extend(batch)
                    self.urls_ready.emit(batch)

                _, entries = collect_entries(
                    self.channel,
                    self.url,
                    log=self._log,
                    wait_for_login=self._wait_for_login,
                    should_stop=self._should_stop,
                    output_root=self.output_root,
                    chrome_binary=self.chrome_binary,
                    cookies_browser=self.cookies_browser,
                    feed=self.feed,
                    on_entries=on_entries,
                    cookies_file=self.cookies_file,
                    dateafter=self.dateafter,
                )
                if not streamed:
                    self.urls_ready.emit(entries)
                self.finished.emit("")
                return
            failures = download_urls(
                self.channel,
                self.urls,
                log=self._log,
                should_stop=self._should_stop,
                on_progress=self._on_progress,
                workers=self.workers,
                fragments=self.fragments,
                output_root=self.output_root,
                ffmpeg_location=self.ffmpeg_location,
                cookies_browser=self.cookies_browser,
                filename_template=self.filename_template,
                cookies_file=self.cookies_file,
                dateafter=self.dateafter,
                limit_rate=self.limit_rate,
                media_kinds=self.media_kinds,
                source_folders=self.source_folders,
            )
            self.finished.emit("" if not failures else f"{failures} item(s) failed.")
        except StopRequested:
            self.finished.emit("Cancelled.")
        except Exception as exc:
            self._log(f"Error: {exc}")
            try:
                from app.core.telegram_report import device_id_from_state, report_job_error

                report_job_error(
                    exc,
                    device_id=device_id_from_state(),
                    mode=self.mode,
                    channel=self.channel,
                )
            except Exception:
                pass
            self.finished.emit(str(exc))

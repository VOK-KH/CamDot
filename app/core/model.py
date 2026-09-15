"""The table model behind the reel list, plus its status/text filter."""
import os
import time
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from app.core import icons, platform_icons
from app.core.download import post_label, reel_id
from app.core.urls import detect_platform

COLUMNS = (
    "#", "", "Hoster", "Status", "Progress", "Name", "Uploader", "ID", "Size",
    "Duration", "Speed", "ETA", "Save to", "Download from", "Added",
)
(
    COL_INDEX, COL_CHECK, COL_HOST, COL_STATUS, COL_PROGRESS, COL_TITLE, COL_UPLOADER,
    COL_ID, COL_SIZE, COL_DURATION, COL_SPEED, COL_ETA, COL_FILE, COL_URL, COL_ADDED,
) = range(15)

STATUSES = ("queued", "downloading", "done", "failed", "cancelled")
STATUS_LABELS = {
    "queued": "Queued",
    "downloading": "Downloading",
    "done": "Done",
    "failed": "Failed",
    "cancelled": "Cancelled",
}
STATUS_COLORS = {
    "queued": "#8c98a8",
    "downloading": "#1877f2",
    "done": "#2f9e4f",
    "failed": "#c0392b",
    "cancelled": "#e08733",
}
STATUS_COLORS_DARK = {
    "queued": "#8c98a8",
    "downloading": "#4a9bff",
    "done": "#3ecf6a",
    "failed": "#ff6b6b",
    "cancelled": "#ffa94d",
}

PERCENT_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1

# (key, menu label, what the search box asks for) for the bottom bar filter.
FILTER_FIELDS = (
    ("all", "All fields", "Filter"),
    ("title", "Title", "Title"),
    ("id", "ID", "ID"),
    ("uploader", "Uploader", "Uploader"),
    ("host", "Host", "Host"),
    ("url", "URL", "URL"),
)

MEDIA_KINDS = (("video", "Video"), ("music", "Music"), ("image", "Image"))
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}
_ALL_KINDS = frozenset(key for key, _label in MEDIA_KINDS)


def format_bytes(value):
    if not value:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "-"


def format_eta(seconds):
    if seconds is None:
        return "-"
    seconds = int(seconds)
    return f"{seconds // 60:d}:{seconds % 60:02d}"


def parse_added_at(value):
    """Unix timestamp from a float, numeric string, or ISO datetime."""
    if value in (None, ""):
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def format_added(value):
    if value in (None, ""):
        return "-"
    try:
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return "-"


def host_label(reel):
    """The domain shown next to the host logo, e.g. "tiktok.com"."""
    host = reel.webpage_url_domain or (urlparse(reel.url).hostname or "")
    return host.lower().removeprefix("www.") or "-"


def media_kind(reel):
    """video, music, or image — used by the right-hand Views checks."""
    path = (reel.filepath or "").lower()
    ext = os.path.splitext(path)[1]
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _AUDIO_EXT:
        return "music"
    url = (reel.url or "").lower()
    host = host_label(reel)
    if "pinterest." in host or host == "pin.it":
        if reel.duration or ext in {".mp4", ".webm", ".mkv", ".mov"}:
            return "video"
        if "/pin/" in url:
            return "image"
    if "music.youtube" in host or "soundcloud" in host or "/audio" in url:
        return "music"
    if any(token in url for token in ("/photo", "/photos", "/p/", "/img")):
        if "/reel/" not in url and "/video/" not in url and "/watch" not in url:
            return "image"
    return "video"


def _tooltip(reel):
    lines = [reel.url]
    label = post_label(reel.title, reel.description, reel.rid)
    if label and label != reel.rid:
        lines.append(label)
    if reel.uploader:
        lines.append(reel.uploader)
    if reel.platform:
        lines.append(reel.platform)
    if reel.duration:
        lines.append(format_eta(reel.duration))
    if reel.filepath:
        lines.append(reel.filepath)
        folder = os.path.dirname(reel.filepath)
        if folder:
            lines.append(folder)
    return "\n".join(lines)


class Reel:
    __slots__ = (
        "url", "rid", "status", "percent", "total", "speed", "eta",
        "title", "description", "uploader", "duration", "filepath", "checked",
        "platform", "extractor_key", "webpage_url_domain",
        "comment", "added_at",
    )

    def __init__(self, url, **meta):
        self.url = url
        self.rid = meta.get("id") or reel_id(url)
        status = meta.get("status") or "queued"
        self.status = status if status in STATUSES else "queued"
        try:
            self.percent = float(meta.get("percent") or 0.0)
        except (TypeError, ValueError):
            self.percent = 0.0
        total = meta.get("total")
        try:
            self.total = float(total) if total not in (None, "") else None
        except (TypeError, ValueError):
            self.total = None
        self.speed = None
        self.eta = None
        self.title = meta.get("title") or ""
        self.description = meta.get("description") or ""
        self.uploader = meta.get("uploader") or ""
        self.duration = meta.get("duration")
        self.filepath = meta.get("filepath") or ""
        self.checked = False
        self.platform = meta.get("platform") or detect_platform(url)
        self.extractor_key = meta.get("extractor_key") or ""
        self.webpage_url_domain = meta.get("webpage_url_domain") or ""
        self.comment = meta.get("comment") or ""
        self.added_at = parse_added_at(meta.get("added_at"))

    def as_entry(self):
        return {
            "url": self.url,
            "id": self.rid,
            "status": self.status,
            "percent": self.percent,
            "total": self.total,
            "title": self.title,
            "description": self.description,
            "uploader": self.uploader,
            "duration": self.duration,
            "filepath": self.filepath,
            "platform": self.platform,
            "extractor_key": self.extractor_key,
            "webpage_url_domain": self.webpage_url_domain,
            "comment": self.comment,
            "added_at": self.added_at,
        }


class ReelModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._reels = []
        self._row_by_url = {}
        self._counts = Counter()
        self._dark = True

    # ------------------------------------------------------------ Qt model

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._reels)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_CHECK:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        reel = self._reels[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.CheckStateRole and column == COL_CHECK:
            return Qt.CheckState.Checked if reel.checked else Qt.CheckState.Unchecked

        if role == Qt.ItemDataRole.DisplayRole:
            if column == COL_HOST:
                return host_label(reel)
            if column == COL_INDEX:
                return str(index.row() + 1)
            if column == COL_STATUS:
                return STATUS_LABELS[reel.status]
            if column == COL_ID:
                return reel.rid
            if column == COL_TITLE:
                return post_label(reel.title, reel.description, "") or "-"
            if column == COL_UPLOADER:
                return reel.uploader or "-"
            if column == COL_SIZE:
                return format_bytes(reel.total)
            if column == COL_DURATION:
                return format_eta(reel.duration) if reel.duration else "-"
            if column == COL_SPEED:
                return f"{format_bytes(reel.speed)}/s" if reel.speed else "-"
            if column == COL_ETA:
                return format_eta(reel.eta) if reel.status == "downloading" else "-"
            if column == COL_FILE:
                return os.path.basename(reel.filepath) if reel.filepath else "-"
            if column == COL_URL:
                return reel.url
            if column == COL_ADDED:
                return format_added(reel.added_at)
            return None

        if role == PERCENT_ROLE and column == COL_PROGRESS:
            return reel.percent
        if role == Qt.ItemDataRole.DecorationRole and column == COL_HOST:
            color = "#e7ecf3" if self._dark else "#1c1e21"
            return platform_icons.icon_for(
                reel.platform, reel.webpage_url_domain, reel.extractor_key, color=color,
            )
        if role == Qt.ItemDataRole.DecorationRole and column == COL_STATUS:
            return icons.icon(f"status-{reel.status}", self.status_color(reel.status).name(), 14)
        if role == Qt.ItemDataRole.ForegroundRole and column == COL_STATUS:
            return self.status_color(reel.status)
        if role == Qt.ItemDataRole.TextAlignmentRole and column in (
            COL_INDEX, COL_SIZE, COL_DURATION, COL_SPEED, COL_ETA,
        ):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip(reel)
        if role == SORT_ROLE:
            if column == COL_CHECK:
                return int(reel.checked)
            if column == COL_HOST:
                return host_label(reel)
            if column == COL_INDEX:
                return index.row()
            if column == COL_STATUS:
                return STATUSES.index(reel.status)
            if column == COL_PROGRESS:
                return reel.percent
            if column == COL_SIZE:
                return reel.total or 0
            if column == COL_DURATION:
                return reel.duration or 0
            if column == COL_SPEED:
                return reel.speed or 0
            if column == COL_ETA:
                return reel.eta if reel.eta is not None else 1 << 30
            if column == COL_ADDED:
                return reel.added_at or 0
            return str(self.data(index, Qt.ItemDataRole.DisplayRole) or "").lower()
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        self._reels[index.row()].checked = Qt.CheckState(value) == Qt.CheckState.Checked
        self.dataChanged.emit(index, index, [role])
        return True

    # --------------------------------------------------------------- state

    def status_color(self, status):
        colors = STATUS_COLORS_DARK if self._dark else STATUS_COLORS
        return QColor(colors[status])

    def set_dark(self, dark):
        if dark == self._dark:
            return
        self._dark = dark
        if self._reels:
            self.dataChanged.emit(
                self.index(0, COL_HOST),
                self.index(len(self._reels) - 1, COL_STATUS),
            )

    def set_urls(self, urls):
        entries = []
        for item in urls:
            if isinstance(item, dict):
                entries.append(item)
            else:
                entries.append({"url": item})
        self.set_entries(entries)

    def set_entries(self, entries):
        self.beginResetModel()
        reels = []
        for entry in entries:
            data = dict(entry)
            url = data.pop("url", "")
            if url:
                reels.append(Reel(url, **data))
        self._reels = reels
        self._row_by_url = {reel.url: row for row, reel in enumerate(self._reels)}
        self._counts = Counter(reel.status for reel in self._reels)
        self.endResetModel()

    def add_entries(self, entries, prepend=False):
        """Append (or prepend) new entries; fill title/caption on listed rows."""
        additions = []
        seen = set(self._row_by_url)
        last = len(COLUMNS) - 1
        for entry in entries:
            data = dict(entry) if isinstance(entry, dict) else {"url": entry}
            url = data.pop("url", "")
            if not url:
                continue
            if url in self._row_by_url:
                row = self._row_by_url[url]
                reel = self._reels[row]
                changed = False
                for field in ("title", "description", "uploader", "comment"):
                    value = data.get(field)
                    if value and not getattr(reel, field):
                        setattr(reel, field, value)
                        changed = True
                if data.get("duration") is not None and not reel.duration:
                    reel.duration = data["duration"]
                    changed = True
                if changed:
                    self.dataChanged.emit(
                        self.index(row, COL_HOST), self.index(row, last),
                    )
                continue
            if url not in seen:
                seen.add(url)
                additions.append(Reel(url, **data))
        if not additions:
            return 0
        if prepend:
            self.beginInsertRows(QModelIndex(), 0, len(additions) - 1)
            self._reels = additions + self._reels
            self._row_by_url = {reel.url: row for row, reel in enumerate(self._reels)}
        else:
            first = len(self._reels)
            self.beginInsertRows(QModelIndex(), first, first + len(additions) - 1)
            self._reels.extend(additions)
            self._row_by_url.update(
                (reel.url, row) for row, reel in enumerate(self._reels[first:], first)
            )
        for reel in additions:
            self._counts[reel.status] += 1
        self.endInsertRows()
        return len(additions)

    def update_reel(self, url, **fields):
        """Patch title, comment, or filepath for the properties panel."""
        row = self._row_by_url.get(url)
        if row is None:
            return False
        reel = self._reels[row]
        changed = False
        for field in ("title", "comment", "filepath"):
            if field not in fields:
                continue
            value = fields[field]
            if value is None:
                continue
            setattr(reel, field, value)
            changed = True
        if changed:
            self.dataChanged.emit(
                self.index(row, COL_HOST), self.index(row, len(COLUMNS) - 1),
            )
        return changed

    def entries(self):
        return [reel.as_entry() for reel in self._reels]

    def pending_urls(self, urls=None):
        wanted = None if urls is None else set(urls)
        return [
            reel.url for reel in self._reels
            if reel.status != "done" and (wanted is None or reel.url in wanted)
        ]

    def requeue_failed(self):
        """Reset failed rows to queued so they can be downloaded again."""
        count = 0
        last = len(COLUMNS) - 1
        for row, reel in enumerate(self._reels):
            if reel.status != "failed":
                continue
            self._counts["failed"] -= 1
            self._counts["queued"] += 1
            reel.status = "queued"
            reel.percent = 0.0
            reel.speed = 0.0
            reel.eta = 0.0
            count += 1
            self.dataChanged.emit(self.index(row, COL_STATUS), self.index(row, last))
        return count

    def clear(self):
        self.set_urls([])

    def urls(self):
        return [reel.url for reel in self._reels]

    def host_kind_counts(self):
        """Counts for the Views strip: host label and video/music/image."""
        hosts = Counter()
        kinds = Counter()
        for reel in self._reels:
            hosts[host_label(reel)] += 1
            kinds[media_kind(reel)] += 1
        return hosts, kinds

    def checked_urls(self):
        return [reel.url for reel in self._reels if reel.checked]

    def set_checked_rows(self, rows, checked):
        changed = False
        for row in rows:
            reel = self._reels[row]
            if reel.checked != checked:
                reel.checked = checked
                changed = True
        if changed and self._reels:
            self.dataChanged.emit(
                self.index(0, COL_CHECK),
                self.index(len(self._reels) - 1, COL_CHECK),
                [Qt.ItemDataRole.CheckStateRole],
            )

    def check_state_for_rows(self, rows):
        if not rows:
            return Qt.CheckState.Unchecked
        flags = {self._reels[row].checked for row in rows}
        if flags == {True}:
            return Qt.CheckState.Checked
        if flags == {False}:
            return Qt.CheckState.Unchecked
        return Qt.CheckState.PartiallyChecked

    def remove_urls(self, urls):
        drop = set(urls)
        keep = [reel for reel in self._reels if reel.url not in drop]
        removed = len(self._reels) - len(keep)
        if not removed:
            return 0
        self.beginResetModel()
        self._reels = keep
        self._row_by_url = {reel.url: row for row, reel in enumerate(self._reels)}
        self._counts = Counter(reel.status for reel in self._reels)
        self.endResetModel()
        return removed

    def move_rows(self, rows, delta):
        """Shift selected source rows by `delta` (−1 up, +1 down), skipping neighbors."""
        indexes = sorted({int(row) for row in rows if 0 <= int(row) < len(self._reels)})
        if not indexes or delta == 0:
            return indexes
        chosen = set(indexes)
        reels = list(self._reels)
        n = len(reels)
        for row in (indexes if delta < 0 else reversed(indexes)):
            other = row + delta
            if other < 0 or other >= n or other in chosen:
                continue
            reels[row], reels[other] = reels[other], reels[row]
            chosen.remove(row)
            chosen.add(other)
        if reels == self._reels:
            return indexes
        self.beginResetModel()
        self._reels = reels
        self._row_by_url = {reel.url: row for row, reel in enumerate(self._reels)}
        self.endResetModel()
        return sorted(chosen)

    def reel_at(self, row):
        return self._reels[row]

    def status_at(self, row):
        return self._reels[row].status

    def counts(self):
        return dict(self._counts)

    def overview(self):
        """Raw totals for the Overview strip; the window formats them."""
        total = loaded = speed = 0.0
        sized = 0
        hosts = set()
        for reel in self._reels:
            hosts.add(host_label(reel))
            if reel.total:
                sized += 1
                total += reel.total
                loaded += reel.total * min(max(reel.percent, 0.0), 100.0) / 100.0
            if reel.status == "downloading":
                speed += reel.speed or 0
        return {
            "links": len(self._reels),
            "checked": sum(1 for reel in self._reels if reel.checked),
            "hosts": len(hosts),
            "sized": sized,
            "unsized": len(self._reels) - sized,
            "bytes_total": total,
            "bytes_loaded": loaded,
            "bytes_left": max(total - loaded, 0.0),
            "speed": speed,
            # Only rows of known size can be timed, so the estimate covers those.
            "eta": (total - loaded) / speed if speed and total > loaded else None,
            "counts": dict(self._counts),
        }

    def active(self):
        """(rows downloading, their combined speed in bytes/s) for the status bar."""
        if not self._counts.get("downloading"):
            return 0, 0.0
        speed = sum(
            reel.speed or 0 for reel in self._reels if reel.status == "downloading"
        )
        return self._counts["downloading"], speed

    def apply_event(self, url, event):
        """Fold one progress event into its row. Returns False for unknown URLs."""
        row = self._row_by_url.get(url)
        if row is None:
            return False
        reel = self._reels[row]
        status = event.get("status")

        if status and status != reel.status:
            self._counts[reel.status] -= 1
            self._counts[status] += 1
            reel.status = status

        for field in ("title", "description", "uploader", "filepath", "platform",
                      "extractor_key", "webpage_url_domain"):
            value = event.get(field)
            if value:
                setattr(reel, field, value)
        if event.get("id"):
            reel.rid = event["id"]
        if event.get("duration") is not None:
            reel.duration = event["duration"]

        if status == "done":
            reel.percent = 100.0
            reel.speed = None
            reel.eta = None
        elif status == "downloading":
            if event.get("percent") is not None:
                reel.percent = event["percent"]
            if event.get("total") is not None:
                reel.total = event["total"]
            reel.speed = event.get("speed")
            reel.eta = event.get("eta")
        elif status:
            reel.speed = None
            reel.eta = None

        self.dataChanged.emit(self.index(row, COL_HOST), self.index(row, len(COLUMNS) - 1))
        return True


class ReelFilterProxy(QSortFilterProxyModel):
    """Filters by status and by a text match on one field, or on all of them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self._status = None
        self._text = ""
        self._field = "all"
        self._kinds = set(_ALL_KINDS)
        self._hosts = None

    def set_status(self, status):
        self._status = status
        self.invalidate()

    def set_text(self, text):
        self._text = text.strip().lower()
        self.invalidate()

    def set_field(self, field):
        self._field = field or "all"
        self.invalidate()

    def set_kinds(self, kinds):
        self._kinds = set(kinds) if kinds is not None else set(_ALL_KINDS)
        self.invalidate()

    def set_hosts(self, hosts):
        self._hosts = set(hosts) if hosts is not None else None
        self.invalidate()

    def _haystack(self, reel):
        """The text the filter searches, narrowed to the chosen field."""
        if self._field == "title":
            return " ".join((reel.title, reel.description))
        if self._field == "id":
            return reel.rid
        if self._field == "uploader":
            return reel.uploader
        if self._field == "host":
            return host_label(reel)
        if self._field == "url":
            return reel.url
        return " ".join(
            (reel.url, reel.rid, reel.title, reel.description, reel.uploader, reel.platform)
        )

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        if model is None:
            return True
        reel = model.reel_at(row)
        if self._status and reel.status != self._status:
            return False
        if media_kind(reel) not in self._kinds:
            return False
        if self._hosts is not None and host_label(reel) not in self._hosts:
            return False
        if self._text and self._text not in self._haystack(reel).lower():
            return False
        return True

"""The table model behind the reel list, plus its status/text filter."""
import os
import time
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor

from app.core import icons, platform_icons, theme
from app.core.download import post_label, reel_id
from app.core.urls import detect_platform

COLUMNS = (
    "#", "", "", "Name", "Variant", "Hoster", "Status", "Progress", "Uploader", "ID",
    "Size", "Duration", "Speed", "ETA", "Save to", "Download from", "Added",
)
(
    COL_INDEX, COL_CHECK, COL_ICON, COL_TITLE, COL_VARIANT, COL_HOST, COL_STATUS,
    COL_PROGRESS, COL_UPLOADER, COL_ID, COL_SIZE, COL_DURATION, COL_SPEED, COL_ETA,
    COL_FILE, COL_URL, COL_ADDED,
) = range(17)

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
VARIANT_OPTIONS_ROLE = Qt.ItemDataRole.UserRole + 2

# (key, menu label, what the search box asks for) for the bottom bar filter.
FILTER_FIELDS = (
    ("all", "All fields", "Filter"),
    ("title", "Title", "Title"),
    ("id", "ID", "ID"),
    ("uploader", "Uploader", "Uploader"),
    ("host", "Host", "Host"),
    ("url", "URL", "URL"),
)

MEDIA_KINDS = (
    ("video", "Video"),
    ("music", "Music"),
    ("image", "Image"),
    ("document", "Document"),
)
IMAGE_QUALITIES = (
    ("best", "Best Quality Image"),
    ("high", "High Quality Image"),
    ("medium", "Medium Quality Image"),
    ("low", "Low Quality Image"),
)
_KIND_ICONS = {
    "video": "kind-video",
    "music": "kind-music",
    "image": "kind-image",
    "document": "kind-document",
}
KIND_ICON_COLORS = {
    "video": "#e87d0d",
    "music": "#19c37d",
    "image": "#3b82f6",
    "document": "#8b9cb3",
    "folder": "#e6b422",
}
_VARIANT_ORDER = {"": 0, "video": 1, "music": 2, "image": 3, "document": 4}
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}
_DOCUMENT_EXT = {".txt", ".json", ".srt", ".vtt", ".nfo", ".xml", ".description"}
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
    if getattr(reel, "variant", "") in _ALL_KINDS:
        return reel.variant
    path = (reel.filepath or "").lower()
    ext = os.path.splitext(path)[1]
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _AUDIO_EXT:
        return "music"
    if ext in _DOCUMENT_EXT:
        return "document"
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
    elif reel.save_dir:
        lines.append(reel.save_dir)
    return "\n".join(lines)


_KIND_FOLDER_NAMES = frozenset({"video", "audio", "image"})


def output_folder(reel):
    """The save folder for a package and every file it writes into it."""
    folder = (getattr(reel, "save_dir", None) or "").strip()
    if not folder and getattr(reel, "filepath", None):
        folder = os.path.dirname(reel.filepath)
    if folder and os.path.basename(folder).lower() in _KIND_FOLDER_NAMES:
        parent = os.path.dirname(folder)
        if parent:
            folder = parent
    return folder


def output_file_kind(path):
    ext = os.path.splitext(path or "")[1].lower()
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _AUDIO_EXT:
        return "music"
    if ext in _DOCUMENT_EXT:
        return "document"
    if ext in {".mp4", ".webm", ".mkv", ".mov"}:
        return "video"
    return ""


def media_output_files(paths):
    """Finished media paths only — skip sidecars and stray thumbnails."""
    return [path for path in (paths or []) if path and output_file_kind(path)]


def primary_output_files(files, media_kinds=None):
    """Files that should drive the row layout (one video, not video+thumb)."""
    media_paths = media_output_files(files)
    videos = [path for path in media_paths if output_file_kind(path) == "video"]
    if len(videos) == 1:
        extras = [path for path in media_paths if path not in videos]
        if not extras or all(output_file_kind(path) == "image" for path in extras):
            return videos
    kinds = set(media_kinds or [])
    if len(kinds) == 1:
        kind = next(iter(kinds))
        picked = [path for path in media_paths if output_file_kind(path) == kind]
        if len(picked) == 1:
            return picked
    return media_paths


_PLACEHOLDER_TITLES = frozenset({"", "default", "video", "untitled", "na", "none"})


def row_title(reel):
    """Name column: caption/title, else file stem, else id."""
    if reel.variant:
        if reel.filepath:
            return os.path.basename(reel.filepath)
        return post_label(reel.title, reel.description, reel.rid) or variant_label(reel)
    label = post_label(reel.title, reel.description, reel.rid)
    if (label or "").lower().strip() in _PLACEHOLDER_TITLES:
        if reel.filepath:
            return os.path.splitext(os.path.basename(reel.filepath))[0]
        return reel.rid or "-"
    return label or "-"


def package_has_children(reels, url):
    """True when a link has variant/file rows under its package."""
    return any(reel.url == url and reel.variant for reel in reels)


def save_to_text(reel, as_folder=False, reels=None):
    """Package rows show the folder; file rows show a file in that same folder."""
    folder = output_folder(reel)
    peers = reels if reels is not None else []
    has_children = (
        as_folder
        or (peers and not reel.variant and package_has_children(peers, reel.url))
    )
    if getattr(reel, "variant", ""):
        if reel.filepath:
            name = os.path.basename(reel.filepath)
            return os.path.join(folder, name) if folder else reel.filepath
        return folder or "-"
    if has_children:
        return folder or "-"
    if reel.filepath:
        return reel.filepath
    return folder or "-"


def reel_key(url, variant=""):
    return f"{url}\n{variant or ''}"


def variant_label(reel):
    """Grabber child row: Video / Audio / Image: Best Quality Image."""
    kind = getattr(reel, "variant", "") or ""
    if kind == "video":
        return "Video"
    if kind == "music":
        return "Audio"
    if kind == "image":
        wanted = getattr(reel, "image_quality", "") or "best"
        for key, label in IMAGE_QUALITIES:
            if key == wanted:
                return f"Image: {label}"
        return "Image: Best Quality Image"
    if kind == "document":
        return "Document"
    return ""


def extract_package_rows(entry, kinds=None, kind_folders=None, folder_group=False):
    """Flat row per link, or a package folder with Video / Audio / Image children."""
    data = dict(entry) if isinstance(entry, dict) else {"url": entry}
    if data.get("variant"):
        return [data]
    kinds = tuple(kinds) if kinds else ("video",)
    folders = kind_folders or {}
    has_kind_folders = any(str(folders.get(key) or "").strip() for key in kinds)
    if not folder_group:
        row = dict(data)
        row["variant"] = ""
        row["media_kinds"] = kinds[0] if len(kinds) == 1 else set(kinds)
        return [row]
    if len(kinds) == 1 and not has_kind_folders:
        row = dict(data)
        row["variant"] = ""
        row["media_kinds"] = kinds[0]
        package = dict(data)
        package["variant"] = ""
        child = dict(data)
        child["variant"] = kinds[0]
        if kinds[0] == "image":
            child["image_quality"] = child.get("image_quality") or "best"
        return [package, child]
    package = dict(data)
    package["variant"] = ""
    rows = [package]
    for key, _label in MEDIA_KINDS:
        if key not in kinds:
            continue
        child = dict(data)
        child["variant"] = key
        dest = str(folders.get(key) or "").strip()
        if dest:
            child["save_dir"] = dest
        if key == "image":
            child["image_quality"] = child.get("image_quality") or "best"
        rows.append(child)
    return rows


class Reel:
    __slots__ = (
        "url", "rid", "status", "percent", "total", "speed", "eta",
        "title", "description", "uploader", "duration", "filepath", "save_dir", "checked",
        "platform", "extractor_key", "webpage_url_domain",
        "comment", "added_at", "variant", "image_quality", "media_kinds", "expanded",
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
        self.save_dir = meta.get("save_dir") or ""
        self.checked = False
        self.platform = meta.get("platform") or detect_platform(url)
        self.extractor_key = meta.get("extractor_key") or ""
        self.webpage_url_domain = meta.get("webpage_url_domain") or ""
        self.comment = meta.get("comment") or ""
        self.added_at = parse_added_at(meta.get("added_at"))
        self.variant = meta.get("variant") or ""
        self.image_quality = meta.get("image_quality") or ""
        raw_kinds = meta.get("media_kinds")
        if isinstance(raw_kinds, str):
            self.media_kinds = {part for part in raw_kinds.split(",") if part}
        elif raw_kinds:
            self.media_kinds = set(raw_kinds)
        else:
            self.media_kinds = set()
        raw_expanded = meta.get("expanded")
        if raw_expanded in (None, ""):
            self.expanded = False
        else:
            self.expanded = str(raw_expanded).lower() not in ("0", "false", "no")

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
            "save_dir": self.save_dir,
            "platform": self.platform,
            "extractor_key": self.extractor_key,
            "webpage_url_domain": self.webpage_url_domain,
            "comment": self.comment,
            "added_at": self.added_at,
            "variant": self.variant,
            "image_quality": self.image_quality,
            "media_kinds": ",".join(sorted(self.media_kinds)) if self.media_kinds else "",
            "expanded": self.expanded,
        }


class ReelModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._reels = []
        self._row_by_url = {}
        self._row_by_key = {}
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
                return row_title(reel)
            if column == COL_VARIANT:
                return variant_label(reel) if reel.variant else ""
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
                return save_to_text(reel, reels=self._reels)
            if column == COL_URL:
                return reel.url
            if column == COL_ADDED:
                return format_added(reel.added_at)
            return None

        if role == PERCENT_ROLE and column == COL_PROGRESS:
            return self._display_percent(reel)
        if role == VARIANT_OPTIONS_ROLE and column == COL_VARIANT and reel.variant == "image":
            return [label for _key, label in IMAGE_QUALITIES]
        if role == Qt.ItemDataRole.DecorationRole and column == COL_ICON:
            if reel.variant in _KIND_ICONS:
                return icons.icon(
                    _KIND_ICONS[reel.variant], KIND_ICON_COLORS[reel.variant], 16,
                )
            if not reel.variant and package_has_children(self._reels, reel.url):
                return icons.icon("folder", KIND_ICON_COLORS["folder"], 16)
            return None
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
            COL_INDEX, COL_ICON, COL_SIZE, COL_DURATION, COL_SPEED, COL_ETA,
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
            if column == COL_VARIANT:
                return _VARIANT_ORDER.get(reel.variant or "", 9)
            if column == COL_PROGRESS:
                return self._display_percent(reel)
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
        if status == "downloading":
            return QColor(theme.primary_color())
        colors = STATUS_COLORS_DARK if self._dark else STATUS_COLORS
        return QColor(colors[status])

    def set_dark(self, dark):
        if dark == self._dark:
            return
        self._dark = dark
        if self._reels:
            self.dataChanged.emit(
                self.index(0, COL_ICON),
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
        self._reindex()
        self._counts = Counter(reel.status for reel in self._reels)
        self.endResetModel()

    def _reindex(self):
        self._row_by_key = {}
        self._row_by_url = {}
        for row, reel in enumerate(self._reels):
            self._row_by_key[reel_key(reel.url, reel.variant)] = row
            if reel.url not in self._row_by_url or not reel.variant:
                self._row_by_url[reel.url] = row

    def add_entries(self, entries, prepend=False):
        """Append (or prepend) new entries; fill title/caption on listed rows."""
        additions = []
        seen = set(self._row_by_key)
        last = len(COLUMNS) - 1
        for entry in entries:
            data = dict(entry) if isinstance(entry, dict) else {"url": entry}
            url = data.pop("url", "")
            if not url:
                continue
            variant = data.get("variant") or ""
            key = reel_key(url, variant)
            if key in self._row_by_key:
                row = self._row_by_key[key]
                reel = self._reels[row]
                changed = False
                for field in ("title", "description", "uploader", "comment", "image_quality"):
                    value = data.get(field)
                    if value and not getattr(reel, field):
                        setattr(reel, field, value)
                        changed = True
                if data.get("duration") is not None and not reel.duration:
                    reel.duration = data["duration"]
                    changed = True
                if changed:
                    self.dataChanged.emit(
                        self.index(row, 0), self.index(row, last),
                    )
                continue
            if key not in seen:
                seen.add(key)
                additions.append(Reel(url, **data))
        if not additions:
            return 0
        if prepend:
            self.beginInsertRows(QModelIndex(), 0, len(additions) - 1)
            self._reels = additions + self._reels
        else:
            first = len(self._reels)
            self.beginInsertRows(QModelIndex(), first, first + len(additions) - 1)
            self._reels.extend(additions)
        self._reindex()
        for reel in additions:
            self._counts[reel.status] += 1
        self.endInsertRows()
        return len(additions)

    def update_reel(self, url, **fields):
        """Patch title, comment, folder, or variant fields for matching rows."""
        match_variant = fields.pop("match_variant", None)
        changed_rows = []
        for row, reel in enumerate(self._reels):
            if reel.url != url:
                continue
            if match_variant is not None and reel.variant != match_variant:
                continue
            local = False
            for field in ("title", "comment", "filepath", "save_dir", "image_quality", "media_kinds"):
                if field not in fields:
                    continue
                value = fields[field]
                if value is None:
                    continue
                if field == "media_kinds" and not isinstance(value, set):
                    value = set(value) if value else set()
                setattr(reel, field, value)
                local = True
            if local:
                changed_rows.append(row)
        if not changed_rows:
            return False
        self.dataChanged.emit(
            self.index(changed_rows[0], 0),
            self.index(changed_rows[-1], len(COLUMNS) - 1),
        )
        return True

    def toggle_expanded(self, url):
        """Show or hide Video/Audio/Image rows under a collected package."""
        row = self._row_by_url.get(url)
        if row is None:
            return False
        reel = self._reels[row]
        if reel.variant:
            return False
        reel.expanded = not reel.expanded
        last = len(COLUMNS) - 1
        self.dataChanged.emit(self.index(0, 0), self.index(len(self._reels) - 1, last))
        return reel.expanded

    def set_all_expanded(self, expanded):
        changed = False
        for reel in self._reels:
            if reel.variant or reel.expanded == expanded:
                continue
            reel.expanded = bool(expanded)
            changed = True
        if changed and self._reels:
            last = len(COLUMNS) - 1
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._reels) - 1, last))
        return changed

    def package_reel(self, url):
        row = self._row_by_url.get(url)
        if row is None:
            return None
        return self._reels[row]

    def _rows_for_url(self, url):
        return [index for index, reel in enumerate(self._reels) if reel.url == url]

    def _active_variants(self, url):
        """Kinds included in the download job, or None when every child row counts."""
        pkg = self.package_reel(url)
        if pkg is None:
            return None
        kinds = set(pkg.media_kinds or ())
        return kinds if kinds else None

    def _variant_rows(self, url, active_only=False):
        rows = [reel for reel in self._reels if reel.url == url and reel.variant]
        if not active_only:
            return rows
        active = self._active_variants(url)
        if active is None:
            return rows
        return [reel for reel in rows if reel.variant in active]

    def _event_applies_to_reel(self, reel, url):
        if not reel.variant:
            return True
        active = self._active_variants(url)
        return active is None or reel.variant in active

    def _display_percent(self, reel):
        """Package rows roll up progress from their active variant children."""
        if reel.variant or not package_has_children(self._reels, reel.url):
            return reel.percent
        children = self._variant_rows(reel.url, active_only=True)
        if not children:
            return reel.percent
        if all(child.status == "done" for child in children):
            return 100.0
        if any(child.status == "downloading" for child in children):
            return max(child.percent for child in children)
        return max(child.percent for child in children)

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
        seen = []
        for reel in self._reels:
            if reel.url not in seen:
                seen.append(reel.url)
        return seen

    def package_count(self):
        """Collected links: package rows only, not Video/Audio/Image children."""
        return sum(1 for reel in self._reels if not reel.variant)

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
        self._reindex()
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
        self._reindex()
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
        has_tree = any(reel.variant for reel in self._reels)
        rows = [reel for reel in self._reels if not reel.variant] if has_tree else self._reels
        total = loaded = speed = 0.0
        sized = 0
        hosts = set()
        for reel in rows:
            hosts.add(host_label(reel))
            if reel.total:
                sized += 1
                total += reel.total
                loaded += reel.total * min(max(reel.percent, 0.0), 100.0) / 100.0
            if reel.status == "downloading":
                speed += reel.speed or 0
        return {
            "links": len(rows),
            "checked": sum(1 for reel in rows if reel.checked),
            "hosts": len(hosts),
            "sized": sized,
            "unsized": len(rows) - sized,
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

    def _apply_event_to_reel(self, reel, event):
        status = event.get("status")
        if status and status != reel.status:
            self._counts[reel.status] -= 1
            self._counts[status] += 1
            reel.status = status

        if not reel.variant:
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
            if event.get("total") is not None and not reel.variant:
                reel.total = event["total"]
            reel.speed = event.get("speed")
            reel.eta = event.get("eta")
        elif status:
            reel.speed = None
            reel.eta = None
        return True

    def apply_event(self, url, event):
        """Fold one progress event into the package and its active variant rows."""
        rows = self._rows_for_url(url)
        if not rows:
            return False
        changed = []
        for row in rows:
            reel = self._reels[row]
            if not self._event_applies_to_reel(reel, url):
                continue
            self._apply_event_to_reel(reel, event)
            changed.append(row)
        if not changed:
            return False
        self.dataChanged.emit(
            self.index(changed[0], 0),
            self.index(changed[-1], len(COLUMNS) - 1),
        )
        return True

    def _package_snapshot(self, url):
        rows = [reel for reel in self._reels if reel.url == url]
        if not rows:
            return None
        variants = {reel.variant: reel for reel in rows if reel.variant}
        pkg = next((reel for reel in rows if not reel.variant), None)
        if pkg is None:
            base = rows[0]
            pkg = Reel(
                base.url,
                id=base.rid,
                title=base.title,
                description=base.description,
                uploader=base.uploader,
                save_dir=base.save_dir,
                platform=base.platform,
                extractor_key=base.extractor_key,
                webpage_url_domain=base.webpage_url_domain,
                comment=base.comment,
                added_at=base.added_at,
                status=base.status,
                percent=base.percent,
                total=base.total,
                speed=base.speed,
                eta=base.eta,
            )
            if base.media_kinds:
                pkg.media_kinds = set(base.media_kinds)
        files = {}
        for kind, reel in variants.items():
            if reel.filepath:
                files[kind] = reel.filepath
        if pkg.filepath and not pkg.variant:
            kind = output_file_kind(pkg.filepath) or "video"
            files.setdefault(kind, pkg.filepath)
        kinds = set(variants)
        if pkg.media_kinds:
            kinds.update(pkg.media_kinds)
        kinds.update(files)
        if not kinds:
            kinds = {"video"}
        return {
            "url": url,
            "pkg": pkg,
            "variants": variants,
            "files": files,
            "kinds": kinds,
        }

    def _copy_reel_state(self, reel, source):
        reel.status = source.status
        reel.percent = source.percent
        reel.total = source.total
        reel.speed = source.speed
        reel.eta = source.eta
        reel.checked = source.checked
        if source.comment:
            reel.comment = source.comment
        if source.added_at:
            reel.added_at = source.added_at

    def _rows_for_folder_layout(self, snap, folder_group, kind_folders=None):
        pkg = snap["pkg"]
        entry = pkg.as_entry()
        files = snap["files"]
        kinds = set(snap["kinds"])
        kinds.update(files)
        kind_folders = kind_folders or {}
        ordered_kinds = sorted(kinds, key=lambda key: _VARIANT_ORDER.get(key, 9))

        if folder_group:
            rows_data = extract_package_rows(
                entry,
                kinds=tuple(ordered_kinds),
                kind_folders=kind_folders,
                folder_group=True,
            )
        elif len(files) > 1:
            rows_data = []
            for kind in ordered_kinds:
                path = files.get(kind)
                if not path:
                    continue
                row = dict(entry)
                row["variant"] = kind
                row["filepath"] = path
                row["save_dir"] = os.path.dirname(path) or pkg.save_dir
                rows_data.append(row)
        elif len(files) == 1:
            path = next(iter(files.values()))
            row = dict(entry)
            row["variant"] = ""
            row["filepath"] = path
            row["save_dir"] = os.path.dirname(path) or pkg.save_dir
            rows_data = [row]
        else:
            rows_data = extract_package_rows(
                entry,
                kinds=tuple(ordered_kinds),
                kind_folders=kind_folders,
                folder_group=False,
            )

        old_rows = [snap["pkg"], *snap["variants"].values()]
        old_by_key = {reel_key(reel.url, reel.variant): reel for reel in old_rows}
        new_reels = []
        for data in rows_data:
            url = data.get("url", snap["url"])
            variant = data.get("variant") or ""
            meta = dict(data)
            meta.pop("url", None)
            media_kinds = meta.pop("media_kinds", None)
            reel = Reel(url, **meta)
            if media_kinds:
                if isinstance(media_kinds, str):
                    reel.media_kinds = {media_kinds}
                else:
                    reel.media_kinds = set(media_kinds)
            source = old_by_key.get(reel_key(url, variant))
            if source is None and variant:
                source = snap["variants"].get(variant) or snap["pkg"]
            elif source is None:
                source = snap["pkg"]
            self._copy_reel_state(reel, source)
            if variant and files.get(variant):
                reel.filepath = files[variant]
                reel.save_dir = os.path.dirname(files[variant]) or reel.save_dir
                if source.status == "done":
                    reel.status = "done"
                    reel.percent = 100.0
                    reel.speed = None
                    reel.eta = None
            elif not variant and len(files) == 1 and not folder_group:
                path = next(iter(files.values()))
                reel.filepath = path
                reel.save_dir = os.path.dirname(path) or reel.save_dir
            elif folder_group and not variant:
                reel.filepath = ""
            new_reels.append(reel)
        return new_reels

    def reshape_folder_layout(self, folder_group, kind_folders=None):
        """Rebuild rows so Save to and the tree match Views → Folder group."""
        urls = []
        seen = set()
        for reel in self._reels:
            if reel.url in seen:
                continue
            seen.add(reel.url)
            urls.append(reel.url)
        if not urls:
            return False

        new_reels = []
        for url in urls:
            snap = self._package_snapshot(url)
            if snap is None:
                continue
            new_reels.extend(self._rows_for_folder_layout(snap, folder_group, kind_folders))

        self.beginResetModel()
        self._reels = new_reels
        self._reindex()
        self._counts = Counter(reel.status for reel in self._reels)
        self.endResetModel()
        return True

    def attach_output_files(self, url, folder, files, expand=False, folder_group=False):
        """Point package/file rows at the real save folder and files in it."""
        snap = self._package_snapshot(url)
        if snap is None:
            return False
        folder = folder or output_folder(snap["pkg"])
        all_media = media_output_files(files)
        if not all_media:
            return False
        layout_media = primary_output_files(files, snap["pkg"].media_kinds)
        if len(layout_media) == 1:
            all_media = layout_media
        snap["files"] = {}
        for path in all_media:
            kind = output_file_kind(path)
            if kind and kind not in snap["files"]:
                snap["files"][kind] = path
        if folder:
            snap["pkg"].save_dir = folder
        new_rows = self._rows_for_folder_layout(snap, folder_group, kind_folders=None)
        if folder_group and expand:
            for reel in new_rows:
                if not reel.variant:
                    reel.expanded = True
        first = next(index for index, reel in enumerate(self._reels) if reel.url == url)
        last = max(index for index, reel in enumerate(self._reels) if reel.url == url)
        self.beginResetModel()
        self._reels = self._reels[:first] + new_rows + self._reels[last + 1:]
        self._reindex()
        self._counts = Counter(reel.status for reel in self._reels)
        self.endResetModel()
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
        self._tree_mode = False

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

    def set_tree_mode(self, enabled):
        self._tree_mode = bool(enabled)
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

    def _reel_matches(self, reel):
        if self._status and reel.status != self._status:
            return False
        if media_kind(reel) not in self._kinds:
            return False
        if self._hosts is not None and host_label(reel) not in self._hosts:
            return False
        if self._text and self._text not in self._haystack(reel).lower():
            return False
        return True

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        if model is None:
            return True
        reel = model.reel_at(row)
        if not reel.variant and self._tree_mode:
            for other in model._reels:
                if other.url == reel.url and other.variant and self._reel_matches(other):
                    return True
        if not self._reel_matches(reel):
            return False
        if reel.variant and not self._tree_mode:
            pkg = model.package_reel(reel.url)
            if pkg is not None and not pkg.variant and not pkg.expanded:
                return False
        return True

    def lessThan(self, left, right):
        """Keep a package and its Video/Audio/Image rows together."""
        model = self.sourceModel()
        if model is None:
            return super().lessThan(left, right)
        a = model.reel_at(left.row())
        b = model.reel_at(right.row())
        if a.url != b.url:
            row_a = model._row_by_url.get(a.url, left.row())
            row_b = model._row_by_url.get(b.url, right.row())
            if row_a != left.row() or row_b != right.row():
                return super().lessThan(
                    model.index(row_a, left.column()),
                    model.index(row_b, right.column()),
                )
            return super().lessThan(left, right)
        return _VARIANT_ORDER.get(a.variant or "", 9) < _VARIANT_ORDER.get(b.variant or "", 9)

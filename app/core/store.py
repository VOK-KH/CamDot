"""Persist the table list and download progress in AppData (not next to videos)."""
import json
import os

from app.core.download import reel_id
from app.core.runtime import channel_state_dir
from app.core.web_media import mp4_video_info, resolution_label

LIST_NAME = "list.json"
ARCHIVE_NAME = ".downloaded.txt"
SKIP_SUFFIXES = (".part", ".ytdl", ".json", ".txt")


def list_path(output_root, channel):
    return os.path.join(channel_state_dir(channel), LIST_NAME)


def archive_path(output_root, channel):
    return os.path.join(channel_state_dir(channel), ARCHIVE_NAME)


def freeze_status(status):
    """In-flight rows pause as queued so a restart can continue them."""
    return "queued" if status == "downloading" else status


def save_list(path, entries):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = []
    for entry in entries:
        item = dict(entry)
        item["status"] = freeze_status(item.get("status") or "queued")
        payload.append(item)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_list(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        return []
    entries = []
    for item in payload:
        if isinstance(item, str) and item.strip():
            entries.append({"url": item.strip()})
        elif isinstance(item, dict) and item.get("url"):
            entries.append(item)
    return entries


def read_archive_ids(path):
    ids = set()
    if not os.path.isfile(path):
        return ids
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2:
                ids.add(parts[-1])
            elif parts:
                ids.add(parts[0])
    return ids


def _matches_id(name, rid):
    return f"[{rid}]" in name or name.startswith(f"{rid}.") or name.startswith(f"{rid} ")


def _find_in_dir(folder, rid, partial=False, dir_cache=None):
    if not rid or not folder:
        return ""
    if dir_cache is not None and folder in dir_cache:
        names = dir_cache[folder]
    else:
        if not os.path.isdir(folder):
            if dir_cache is not None:
                dir_cache[folder] = ()
            return ""
        try:
            names = tuple(os.listdir(folder))
        except OSError:
            names = ()
        if dir_cache is not None:
            dir_cache[folder] = names
    for name in names:
        is_part = name.endswith(".part")
        if partial != is_part:
            continue
        if not partial and name.endswith(SKIP_SUFFIXES):
            continue
        if _matches_id(name, rid):
            return os.path.join(folder, name)
    return ""


def _iter_search_dirs(output_dir, subdirs_cache=None):
    if not output_dir:
        return
    if subdirs_cache is not None and output_dir in subdirs_cache:
        yield from subdirs_cache[output_dir]
        return
    found = [output_dir]
    if os.path.isdir(output_dir):
        try:
            for name in os.listdir(output_dir):
                path = os.path.join(output_dir, name)
                if os.path.isdir(path):
                    found.append(path)
                    try:
                        for sub in os.listdir(path):
                            subpath = os.path.join(path, sub)
                            if os.path.isdir(subpath):
                                found.append(subpath)
                    except OSError:
                        continue
        except OSError:
            pass
    if subdirs_cache is not None:
        subdirs_cache[output_dir] = tuple(found)
    yield from found


def find_output_file(output_dir, rid, partial=False, dir_cache=None, subdirs_cache=None):
    for folder in _iter_search_dirs(output_dir, subdirs_cache=subdirs_cache):
        found = _find_in_dir(folder, rid, partial=partial, dir_cache=dir_cache)
        if found:
            return found
    return ""


def list_output_files(output_dir, rid, filepath=""):
    """Every leftover file for a reel: the saved path, .part/.ytdl sidecars, and id matches."""
    found, seen = [], set()

    def add(path):
        if not path:
            return
        try:
            real = os.path.abspath(path)
        except OSError:
            return
        name = os.path.basename(real)
        if name in (LIST_NAME, ARCHIVE_NAME):
            return
        if not os.path.isfile(real) or real in seen:
            return
        seen.add(real)
        found.append(real)

    add(filepath)
    if filepath:
        add(filepath + ".part")
        add(filepath + ".ytdl")
    if rid:
        for folder in _iter_search_dirs(output_dir):
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                if _matches_id(name, rid):
                    add(os.path.join(folder, name))
    return found


def forget_archive_ids(path, rids):
    """Drop archive lines so a deleted file can be downloaded again."""
    drop = {str(rid) for rid in rids if rid}
    if not drop or not os.path.isfile(path):
        return
    keep = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            last = parts[-1] if parts else ""
            if last in drop:
                continue
            keep.append(line)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(keep)


def _lookup_output(rid, *roots, partial=False, dir_cache=None, subdirs_cache=None):
    """Search each root (and its subfolders) for a finished or .part file."""
    for root in roots:
        root = (root or "").strip()
        if not root:
            continue
        found = find_output_file(
            root, rid, partial=partial, dir_cache=dir_cache, subdirs_cache=subdirs_cache,
        )
        if found:
            return found
    return ""


def reconcile_entries(entries, output_dir, archive_file=None):
    """Mark finished files done and keep percent for leftover .part files.

    Looks in each row's ``save_dir`` first (movie/series folders), then
    ``output_dir`` / channel folder, so progress reloads after restart.
    """
    archive = read_archive_ids(archive_file or os.path.join(output_dir, ARCHIVE_NAME))
    dir_cache = {}
    subdirs_cache = {}
    reconciled = []
    for entry in entries:
        item = dict(entry)
        url = item.get("url") or ""
        rid = str(item.get("id") or reel_id(url))
        item["id"] = rid
        save_dir = (item.get("save_dir") or "").strip()
        existing_fp = (item.get("filepath") or "").strip()
        if (
            existing_fp
            and not existing_fp.endswith(SKIP_SUFFIXES)
            and os.path.isfile(existing_fp)
        ):
            finished = existing_fp
            part = ""
        else:
            finished = _lookup_output(
                rid, save_dir, output_dir,
                partial=False, dir_cache=dir_cache, subdirs_cache=subdirs_cache,
            )
            part = "" if finished else _lookup_output(
                rid, save_dir, output_dir,
                partial=True, dir_cache=dir_cache, subdirs_cache=subdirs_cache,
            )
        if finished:
            item["status"] = "done"
            item["percent"] = 100.0
            item["filepath"] = finished
            if not save_dir:
                item["save_dir"] = os.path.dirname(finished)
            if not item.get("total"):
                try:
                    size = os.path.getsize(finished)
                    if size > 0:
                        item["total"] = size
                except OSError:
                    pass
            if not item.get("duration") or not item.get("quality"):
                dur, w, h = mp4_video_info(finished)
                if dur and not item.get("duration"):
                    item["duration"] = dur
                qual = resolution_label(w, h, finished)
                if qual and not item.get("quality"):
                    item["quality"] = qual
        elif rid in archive:
            item["status"] = "done"
            item["percent"] = 100.0
        else:
            item["status"] = freeze_status(item.get("status") or "queued")
            if part:
                item["filepath"] = part
                if not save_dir:
                    item["save_dir"] = os.path.dirname(part)
                total = item.get("total")
                try:
                    size = os.path.getsize(part)
                    if total:
                        item["percent"] = max(
                            float(item.get("percent") or 0.0),
                            min(99.0, size / float(total) * 100.0),
                        )
                    elif not item.get("percent"):
                        item["percent"] = item.get("percent") or 0.0
                except OSError:
                    pass
        reconciled.append(item)
    return reconciled

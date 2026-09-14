"""Persist the table list and download progress next to the files."""
import json
import os

from app.core.download import reel_id

LIST_NAME = "list.json"
ARCHIVE_NAME = ".downloaded.txt"
SKIP_SUFFIXES = (".part", ".ytdl", ".json", ".txt")


def list_path(output_root, channel):
    return os.path.join(output_root, channel, LIST_NAME)


def archive_path(output_root, channel):
    return os.path.join(output_root, channel, ARCHIVE_NAME)


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


def find_output_file(output_dir, rid, partial=False):
    if not rid or not os.path.isdir(output_dir):
        return ""
    for name in os.listdir(output_dir):
        is_part = name.endswith(".part")
        if partial != is_part:
            continue
        if not partial and name.endswith(SKIP_SUFFIXES):
            continue
        if _matches_id(name, rid):
            return os.path.join(output_dir, name)
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
    if rid and os.path.isdir(output_dir):
        for name in os.listdir(output_dir):
            if _matches_id(name, rid):
                add(os.path.join(output_dir, name))
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


def reconcile_entries(entries, output_dir):
    """Mark finished files done and keep percent for leftover .part files."""
    archive = read_archive_ids(os.path.join(output_dir, ARCHIVE_NAME))
    reconciled = []
    for entry in entries:
        item = dict(entry)
        url = item.get("url") or ""
        rid = str(item.get("id") or reel_id(url))
        item["id"] = rid
        finished = find_output_file(output_dir, rid, partial=False)
        part = find_output_file(output_dir, rid, partial=True)
        if finished:
            item["status"] = "done"
            item["percent"] = 100.0
            item["filepath"] = finished
        elif rid in archive:
            item["status"] = "done"
            item["percent"] = 100.0
        else:
            item["status"] = freeze_status(item.get("status") or "queued")
            if part:
                item["filepath"] = part
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

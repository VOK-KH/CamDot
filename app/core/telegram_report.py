"""Send CamDot system reports to a Telegram bot (background, non-blocking)."""
import html
import json
import os
import platform
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

from app import __version__
from app.core.runtime import APP_NAME, state_dir

try:
    from app.core import telegram_secrets
except ImportError:
    telegram_secrets = None

EVENT_CRASH = "crash"
EVENT_FEEDBACK = "feedback"
EVENT_VERSION_LAUNCH = "version_launch"
EVENT_FIRST_ACTIVATE = "first_activate"
EVENT_TOOLS = "tools"
EVENT_APP_UPDATE = "app_update"
EVENT_JOB_ERROR = "job_error"

EVENT_EMOJI = {
    EVENT_CRASH: "💥",
    EVENT_FEEDBACK: "💬",
    EVENT_VERSION_LAUNCH: "🚀",
    EVENT_FIRST_ACTIVATE: "🆕",
    EVENT_TOOLS: "🛠️",
    EVENT_APP_UPDATE: "⬆️",
    EVENT_JOB_ERROR: "⚠️",
}

FIELD_EMOJI = {
    "version": "📦",
    "device_id": "🖥️",
    "platform": "🌐",
    "python": "🐍",
    "frozen": "📀",
    "source": "🔧",
    "ok": "✅",
}

_MAX_TEXT = 3900
_send_lock = threading.Lock()


def _credentials():
    token = os.environ.get("CAMDOT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("CAMDOT_TELEGRAM_CHAT_ID", "").strip()
    if telegram_secrets is not None:
        token = token or getattr(telegram_secrets, "BOT_TOKEN", "").strip()
        chat_id = chat_id or getattr(telegram_secrets, "CHAT_ID", "").strip()
    return token, chat_id


def _platform_label():
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def _device_id_path():
    return os.path.join(state_dir(), "device-id.txt")


def _persist_device_id(device_id):
    path = _device_id_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(device_id)
    os.replace(temp, path)


def device_id_from_state():
    path = _device_id_path()
    try:
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
            if value:
                return value
    except OSError:
        pass
    return ""


def device_id_from_settings(settings):
    """Return a stable device id, creating and storing one when missing."""
    existing = settings.value("device_id", "", str).strip() or device_id_from_state()
    if existing:
        if not settings.value("device_id", "", str).strip():
            settings.setValue("device_id", existing)
        return existing
    new_id = str(uuid.uuid4())
    settings.setValue("device_id", new_id)
    settings.sync()
    _persist_device_id(new_id)
    return new_id


def _base_context(device_id=""):
    frozen = getattr(sys, "frozen", False)
    return {
        "app": APP_NAME,
        "version": __version__,
        "device_id": device_id or "unknown",
        "platform": _platform_label(),
        "python": platform.python_version(),
        "frozen": frozen,
        "pid": os.getpid(),
    }


def _format_field(key, value):
    if isinstance(value, bool):
        if key == "ok":
            icon = "✅" if value else "❌"
            label = "Success" if value else "Failed"
            return f"{icon} <b>{label}</b>"
        if key == "frozen":
            icon = "📀" if value else "🐍"
            label = "Installed app" if value else "Dev / Python"
            return f"{icon} <b>{label}</b>"
        value = "yes" if value else "no"
    icon = FIELD_EMOJI.get(key, "•")
    label = key.replace("_", " ").title()
    return f"{icon} <b>{html.escape(label)}:</b> {html.escape(str(value))}"


def _format_message(event, title, body, context=None):
    context = context or {}
    icon = EVENT_EMOJI.get(event, "📣")
    lines = [
        f"{icon} <b>{html.escape(APP_NAME)} Report</b>",
        f"📌 <b>Event:</b> {html.escape(event.replace('_', ' ').title())}",
        f"📋 <b>Title:</b> {html.escape(title)}",
    ]
    for key in ("version", "device_id", "platform", "python", "frozen", "source", "ok"):
        if key in context and context[key] not in ("", None):
            lines.append(_format_field(key, context[key]))
    if body:
        lines.append("")
        lines.append(f"📝 {html.escape(body)}")
    text = "\n".join(lines)
    if len(text) > _MAX_TEXT:
        text = text[: _MAX_TEXT - 20] + "\n… (truncated)"
    return text


def _post_message(token, chat_id, text):
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def reporting_enabled():
    """Respect Settings → Privacy → send anonymous reports."""
    enabled = os.environ.get("CAMDOT_TELEGRAM_REPORTS", "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return False
    if enabled in ("1", "true", "yes", "on"):
        return True
    try:
        from app.core.runtime import gui_settings

        settings = gui_settings()
        return settings.value("telegram_reports", True, bool)
    except Exception:
        return True


def send_report(event, title, body="", *, device_id="", extra=None, block=False):
    """Queue a Telegram report. Returns True when queued (or sent if block=True)."""
    if not reporting_enabled():
        return False
    token, chat_id = _credentials()
    if not token or not chat_id:
        return False
    context = _base_context(device_id)
    if extra:
        context.update(extra)
    text = _format_message(event, title, body, context)

    def _send():
        with _send_lock:
            try:
                _post_message(token, chat_id, text)
            except (urllib.error.URLError, OSError, TimeoutError):
                pass

    if block:
        _send()
        return True
    threading.Thread(target=_send, name="telegram-report", daemon=True).start()
    return True


def report_launch(settings, device_id):
    """Report first activation and/or first launch of a new app version."""
    first = not settings.contains("first_activate_reported")
    last_version = settings.value("telegram_last_launch_version", "", str).strip()
    version_changed = last_version != __version__

    if first:
        send_report(
            EVENT_FIRST_ACTIVATE,
            "New device activated",
            f"First run at {datetime.now(timezone.utc).isoformat()}",
            device_id=device_id,
        )
        settings.setValue("first_activate_reported", True)

    if version_changed:
        body = f"Previous: {last_version or '(none)'}\nCurrent: {__version__}"
        send_report(
            EVENT_VERSION_LAUNCH,
            "App version launch",
            body,
            device_id=device_id,
        )
        settings.setValue("telegram_last_launch_version", __version__)

    if first or version_changed:
        settings.sync()


def report_crash(exc_type, exc_value, exc_tb, *, device_id="", thread_name=""):
    trace = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    title = f"{getattr(exc_type, '__name__', 'Exception')}: {exc_value}"
    body = trace
    if thread_name:
        body = f"Thread: {thread_name}\n\n{body}"
    send_report(EVENT_CRASH, title, body, device_id=device_id)


def report_feedback(message, *, device_id="", log_excerpt=""):
    body = message.strip()
    if log_excerpt:
        body = f"{body}\n\n--- log ---\n{log_excerpt.strip()}"
    send_report(EVENT_FEEDBACK, "User feedback", body, device_id=device_id)


def report_tools_use(*, device_id="", source="auto", ok=True, versions=None):
    versions = versions or {}
    body = json.dumps(versions, indent=2) if versions else ""
    send_report(
        EVENT_TOOLS,
        "Download tools update",
        body,
        device_id=device_id,
        extra={"source": source, "ok": ok},
    )


def format_github_release_notice(info):
    """HTML Telegram body for a published GitHub release (tag, links, notes)."""
    tag = html.escape(info.get("tag") or info.get("latest") or "")
    lines = [
        f"⬆️ <b>{html.escape(APP_NAME)} {tag}</b>",
        f"🏷️ <b>Tag:</b> <code>{tag}</code>",
    ]
    assets = info.get("assets") or []
    if assets:
        lines.append("")
        lines.append("💻 <b>Platform downloads</b>")
        for asset in assets:
            label = html.escape(asset.get("label") or asset.get("name") or "Download")
            name = html.escape(asset.get("name") or label)
            href = html.escape(asset.get("url") or "", quote=True)
            lines.append(f"• {label}: <a href=\"{href}\">{name}</a>")
    page = info.get("page_url") or ""
    if page:
        lines.append("")
        lines.append(
            f"🔗 <a href=\"{html.escape(page, quote=True)}\">GitHub release page</a>"
        )
    notes = (info.get("notes") or "").strip()
    if notes:
        clipped = notes[:2500]
        lines.append("")
        lines.append("📝 <b>Patch notes</b>")
        lines.append(f"<pre>{html.escape(clipped)}</pre>")
    text = "\n".join(lines)
    if len(text) > _MAX_TEXT:
        text = text[: _MAX_TEXT - 20] + "\n… (truncated)"
    return text


def send_html(text, *, block=True):
    """Post a preformatted HTML Telegram message. Skips privacy wrapping."""
    token, chat_id = _credentials()
    if not token or not chat_id:
        return False

    def _send():
        with _send_lock:
            try:
                _post_message(token, chat_id, text)
            except (urllib.error.URLError, OSError, TimeoutError):
                pass

    if block:
        _send()
        return True
    threading.Thread(target=_send, name="telegram-release", daemon=True).start()
    return True


def notify_github_release(info=None, *, tag="", block=True):
    """Announce a GitHub release. Only the Release workflow should call this."""
    flag = os.environ.get("CAMDOT_TELEGRAM_RELEASE_NOTICE", "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    if info is None:
        from app.core.updates import fetch_release, parse_release

        info = parse_release(fetch_release(tag=tag), current="")
    text = format_github_release_notice(info)
    return send_html(text, block=block)


def report_job_error(exc, *, device_id="", mode="", channel=""):
    body = f"Mode: {mode}\nChannel: {channel}\n\n{exc}"
    send_report(EVENT_JOB_ERROR, "Background job error", body, device_id=device_id)


def install_crash_handlers(*, device_id=""):
    """Install process-wide crash hooks (main thread + worker threads)."""
    previous = sys.excepthook
    previous_thread = getattr(threading, "excepthook", None)

    def _hook(exc_type, exc_value, exc_tb):
        if exc_type is KeyboardInterrupt:
            if previous:
                previous(exc_type, exc_value, exc_tb)
            return
        report_crash(exc_type, exc_value, exc_tb, device_id=device_id, thread_name="main")
        if previous:
            previous(exc_type, exc_value, exc_tb)

    def _thread_hook(args):
        if args.exc_type is KeyboardInterrupt:
            if previous_thread:
                previous_thread(args)
            return
        report_crash(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            device_id=device_id,
            thread_name=args.thread.name if args.thread else "thread",
        )
        if previous_thread:
            previous_thread(args)

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook

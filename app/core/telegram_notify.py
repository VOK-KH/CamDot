"""User Telegram bot: approve chats, then push download-done messages."""
import html
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

from app.core.telegram_report import _post_message

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_LABELS = {
    STATUS_PENDING: "Pending",
    STATUS_APPROVED: "Approved",
    STATUS_REJECTED: "Rejected",
}

SETTING_ENABLED = "telegram_notify_enabled"
SETTING_TOKEN = "telegram_notify_bot_token"
SETTING_ACCOUNTS = "telegram_notify_accounts"
SETTING_OFFSET = "telegram_notify_update_offset"

_poll_lock = threading.Lock()


def enabled(settings):
    return bool(settings.value(SETTING_ENABLED, False, bool))


def bot_token(settings):
    return (settings.value(SETTING_TOKEN, "", str) or "").strip()


def load_accounts(settings):
    raw = settings.value(SETTING_ACCOUNTS, "[]", str) or "[]"
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(rows, list):
        return []
    accounts = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict):
            continue
        chat_id = str(item.get("chat_id") or "").strip()
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        status = item.get("status") or STATUS_PENDING
        if status not in STATUS_LABELS:
            status = STATUS_PENDING
        accounts.append({
            "chat_id": chat_id,
            "username": str(item.get("username") or "").lstrip("@"),
            "name": str(item.get("name") or ""),
            "status": status,
        })
    return accounts


def save_state(settings, accounts, offset=None, token=None, enabled_flag=None):
    settings.setValue(SETTING_ACCOUNTS, json.dumps(accounts, ensure_ascii=False))
    if offset is not None:
        settings.setValue(SETTING_OFFSET, int(offset))
    if token is not None:
        settings.setValue(SETTING_TOKEN, token.strip())
    if enabled_flag is not None:
        settings.setValue(SETTING_ENABLED, bool(enabled_flag))


def update_offset(settings):
    try:
        return int(settings.value(SETTING_OFFSET, 0) or 0)
    except (TypeError, ValueError):
        return 0


def approved_chat_ids(accounts):
    return [
        item["chat_id"] for item in accounts
        if item.get("status") == STATUS_APPROVED
    ]


def account_label(account):
    name = (account.get("name") or "").strip()
    user = (account.get("username") or "").strip()
    if name and user:
        return f"{name} (@{user})"
    if name:
        return name
    if user:
        return f"@{user}"
    return account.get("chat_id") or "Unknown"


def set_status(accounts, chat_id, status):
    chat_id = str(chat_id)
    changed = None
    for item in accounts:
        if item["chat_id"] == chat_id:
            item["status"] = status
            changed = item
            break
    return accounts, changed


def upsert_start(accounts, chat):
    """Add or revive a chat that sent /start. Approved stays approved."""
    chat_id = str(chat["chat_id"])
    for item in accounts:
        if item["chat_id"] != chat_id:
            continue
        item["username"] = chat.get("username") or item.get("username") or ""
        item["name"] = chat.get("name") or item.get("name") or ""
        if item.get("status") == STATUS_APPROVED:
            return accounts, item, False
        was_pending = item.get("status") == STATUS_PENDING
        item["status"] = STATUS_PENDING
        return accounts, item, not was_pending
    fresh = {
        "chat_id": chat_id,
        "username": chat.get("username") or "",
        "name": chat.get("name") or "",
        "status": STATUS_PENDING,
    }
    accounts.append(fresh)
    return accounts, fresh, True


def _is_start(text):
    value = (text or "").strip()
    if value == "/start":
        return True
    return value.startswith("/start ") or value.startswith("/start@")


def start_chats(updates):
    chats = []
    seen = set()
    for item in updates or []:
        message = item.get("message") or item.get("edited_message") or {}
        if not _is_start(message.get("text") or ""):
            continue
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        key = str(chat_id)
        if key in seen:
            continue
        seen.add(key)
        first = chat.get("first_name") or sender.get("first_name") or ""
        last = chat.get("last_name") or sender.get("last_name") or ""
        name = " ".join(part for part in (first, last) if part) or chat.get("title") or ""
        chats.append({
            "chat_id": key,
            "username": (
                chat.get("username") or sender.get("username") or ""
            ).lstrip("@"),
            "name": name,
        })
    return chats


def fetch_updates(token, offset=0):
    params = urllib.parse.urlencode({
        "offset": int(offset or 0),
        "timeout": 0,
        "allowed_updates": json.dumps(["message"]),
    })
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getUpdates?{params}",
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description") or "Telegram getUpdates failed")
    results = payload.get("result") or []
    next_offset = int(offset or 0)
    if results:
        next_offset = max(int(row.get("update_id") or 0) for row in results) + 1
    return results, next_offset


def _reply(token, chat_id, text):
    try:
        _post_message(token, chat_id, html.escape(text))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        pass


def poll_starts(token, offset, accounts, *, reply=True):
    """Pull /start messages. Returns (accounts, offset, new_pending)."""
    token = (token or "").strip()
    if not token:
        return list(accounts), int(offset or 0), []
    with _poll_lock:
        updates, next_offset = fetch_updates(token, offset)
        accounts = [dict(item) for item in accounts]
        pending = []
        for chat in start_chats(updates):
            accounts, row, is_new = upsert_start(accounts, chat)
            if reply:
                if row["status"] == STATUS_APPROVED:
                    _reply(
                        token, row["chat_id"],
                        "This account already receives CamDot download notifications.",
                    )
                else:
                    _reply(
                        token, row["chat_id"],
                        "CamDot received your request. Approve this account in "
                        "Settings → Notifications to get download messages.",
                    )
            if is_new and row["status"] == STATUS_PENDING:
                pending.append(row)
        return accounts, next_offset, pending


def send_status_reply(token, account):
    token = (token or "").strip()
    if not token or not account:
        return False
    status = account.get("status")
    if status == STATUS_APPROVED:
        text = "Approved. CamDot will message you when a download finishes."
    elif status == STATUS_REJECTED:
        text = "This account will not receive CamDot notifications."
    else:
        text = "Your CamDot notification request is pending approval."
    _reply(token, account["chat_id"], text)
    return True


def notify_download_done(settings, title, body, *, block=False):
    """Message every approved chat. Returns True when at least one send is queued."""
    if not enabled(settings):
        return False
    token = bot_token(settings)
    chat_ids = approved_chat_ids(load_accounts(settings))
    if not token or not chat_ids:
        return False
    text = f"<b>{html.escape(title)}</b>\n{html.escape(body)}"

    def _send():
        with _poll_lock:
            for chat_id in chat_ids:
                try:
                    _post_message(token, chat_id, text)
                except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                    pass

    if block:
        _send()
        return True
    threading.Thread(target=_send, name="telegram-notify", daemon=True).start()
    return True

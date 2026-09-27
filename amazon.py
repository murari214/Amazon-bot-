import os
import re
import io
import time
import html as html_lib
import logging
import sqlite3
import threading
import functools

import requests
import telebot
from telebot import types

try:
    import qrcode
    _HAS_QR = True
except ImportError:
    _HAS_QR = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("giftcredit_bot")


# ════════════════════════════════════════════════
#                   CONFIG
# ════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "8816319709:AAFov-LJQlGJ5VtmsgwjkZ9fkVGL9Dsyn6U")
BOT_USERNAME = os.getenv("BOT_USERNAME", "amzoncards_bot")  # without @

ADMIN_IDS = [
    8679787798,  # replace with your telegram numeric user id(s)
]

# ── the 4 mandatory channels a user must join before the bot works ──────
# "id" = the channel's numeric chat id (e.g. -1001234567890), used to check
# membership with get_chat_member. "link" = the public invite link shown to
# the user. Replace ALL FOUR with your real channels before going live.
FORCE_JOIN_CHANNELS = [
    {"id": "-1003902227125", "link": "https://t.me/errorarmy1", "name": "channel 1"},
    {"id": "-1004341222043", "link": "https://t.me/astropulsesmm", "name": "channel 2"},
    {"id": "-1003813830079", "link": "https://t.me/astrobackupp", "name": "channel 3"},
    {"id": "-1004382656203", "link": "https://t.me/elsewayshortcut", "name": "channel 4"},
]

# ── "join updates" button on the dashboard (not part of the force-join gate) ──
JOIN_UPDATES_LINK = "https://t.me/errorarmy1"

# ── human support contact shown on failure/help screens ─────────────────
HUMAN_SUPPORT_USERNAME = "astropulsesmm"
HUMAN_SUPPORT_LINK = f"https://t.me/{HUMAN_SUPPORT_USERNAME}"

# ── default dashboard gif ────────────────────────────────────────────────
DEFAULT_DASHBOARD_GIF = "https://media.giphy.com/media/L1R1tvI9svkIWwpVYr/giphy.gif"

# ── database ──────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "giftcredit_bot.db")
LOCK_PATH = os.getenv("BOT_LOCK_PATH", os.path.join(os.getcwd(), "giftcredit_bot.lock"))


def acquire_single_instance_lock():
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        return lock_fd
    except FileExistsError:
        return None


# ── default economy settings (all overridable live by admin) ────────────
DEFAULT_SETTINGS = {
    "admin_upi_id": "8707210511@fam",
    "upi_payee_name": "Credits Bot",
    "rate_inr": "4",            # ── "4 rs = 10 credits"
    "rate_credits": "10",
    "min_buy_credits": "10",
    "gift_card_cost_credits": "10",
    "referral_reward_credits": "1",
    "currency_name": "credits",
    "dashboard_gif_file_id": DEFAULT_DASHBOARD_GIF,
    "dashboard_sticker_file_id": "",
    "amazon_premium_sticker_file_id": "",
}

MAX_GIFT_CODES_PER_BATCH = 10


# ════════════════════════════════════════════════
#                UI HELPERS (small-caps & premium emojis)
# ════════════════════════════════════════════════

_SC = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ',
    'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ',
    'q': 'Q', 'r': 'ʀ', 's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ',
}


def sc(text: str) -> str:
    return "".join(_SC.get(c.lower(), c) if c.isalpha() else c for c in text)


DIV = "<b>━━━━━━━━━━━━━━━━━━━━━━━━</b>"
DIV2 = "<b>────────────────────────</b>"


def B(t): return f"<b>{t}</b>"
def C(t): return f"<code>{t}</code>"


def esc(t) -> str:
    return html_lib.escape(str(t), quote=False)


# premium custom emoji ids (generic telegram premium emoji set — any bot
# can reference a valid custom_emoji_id in a "custom_emoji" text entity).
CUSTOM_EMOJIS: dict[str, tuple[str, str]] = {
    "dashboard":  ("📱", "5346056560537779652"),
    "profile":    ("👩‍🚀", "5429128173004529431"),
    "credit":     ("💳", "5445353829304387411"),
    "gift":       ("🎁", "6093890283227848557"),
    "amazon":     ("💎", "5427168083074628963"),
    "premium":    ("💎", "5427168083074628963"),
    "crown":      ("👑", "6237864166879663987"),
    "referral":   ("📩", "5285184156555306745"),
    "share":      ("🫂", "6291721892835365542"),
    "join":       ("👀", "6298788673110410889"),
    "verify":     ("✅", "6084779072750097974"),
    "cross":      ("❌", "5210952531676504517"),
    "blocked":    ("🚫", "5240241223632954241"),
    "back":       ("🔙", "5253997076169115797"),
    "pin":        ("📌", "5397782960512444700"),
    "money":      ("💵", "5321506952675597305"),
    "fire":       ("🔥", "6235628846855492222"),
    "bolt":       ("⚡", "5456140674028019486"),
    "call_me":    ("🤙", "5458820471627733662"),
    "idea":       ("💡", "5224596414415256150"),
    "clock":      ("🚨", "5395695537687123235"),  # was duplicated from "back" — fixed to a distinct id; verify/replace with your own real custom-emoji id
    "below":      ("👇", "6147439566107186310"),
}

_CE_OPEN, _CE_CLOSE = "\uE000", "\uE001"
_CE_MARKER_RE = re.compile(f"{_CE_OPEN}([a-zA-Z0-9_]+){_CE_CLOSE}")
_TAG_RE = re.compile(r"<b>|</b>|<code>|</code>|" + _CE_MARKER_RE.pattern)
_TAG_ENTITY_TYPES = {"b": "bold", "code": "code"}


def ce(key: str) -> str:
    if key not in CUSTOM_EMOJIS:
        raise KeyError(f"unknown custom emoji key: {key!r}")
    return f"{_CE_OPEN}{key}{_CE_CLOSE}"


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def render_entities(html_text: str):
    plain_parts: list[str] = []
    entities: list = []
    utf16_len = 0
    open_stack: list[tuple[str, int]] = []

    pos = 0
    for m in _TAG_RE.finditer(html_text):
        chunk = html_text[pos:m.start()]
        if chunk:
            chunk = html_lib.unescape(chunk)
            plain_parts.append(chunk)
            utf16_len += _utf16_len(chunk)
        pos = m.end()
        token = m.group(0)

        ce_match = _CE_MARKER_RE.fullmatch(token)
        if ce_match:
            key = ce_match.group(1)
            char, emoji_id = CUSTOM_EMOJIS[key]
            plain_parts.append(char)
            length = _utf16_len(char)
            entities.append(types.MessageEntity(
                type="custom_emoji", offset=utf16_len, length=length,
                custom_emoji_id=str(emoji_id),
            ))
            utf16_len += length
            continue

        if token.startswith("</"):
            tag = token[2:-1]
            entity_type = _TAG_ENTITY_TYPES.get(tag)
            for i in range(len(open_stack) - 1, -1, -1):
                if open_stack[i][0] == tag:
                    _, start = open_stack.pop(i)
                    if entity_type and utf16_len > start:
                        entities.append(types.MessageEntity(
                            type=entity_type, offset=start, length=utf16_len - start,
                        ))
                    break
        else:
            tag = token[1:-1]
            open_stack.append((tag, utf16_len))

    tail = html_text[pos:]
    if tail:
        tail = html_lib.unescape(tail)
        plain_parts.append(tail)
        utf16_len += _utf16_len(tail)

    plain_text = "".join(plain_parts)
    entities.sort(key=lambda e: e.offset)
    return plain_text, entities


def render(text: str):
    return render_entities(text)


def _to_plain_html(text: str) -> str:
    return _CE_MARKER_RE.sub(lambda m: CUSTOM_EMOJIS[m.group(1)][0], text)


def fmt_dt(ts: int) -> str:
    if not ts:
        return sc("unknown")
    return time.strftime("%d %b %Y, %H:%M", time.localtime(ts))


# ════════════════════════════════════════════════
#              SAFE SEND / EDIT WRAPPERS
# ════════════════════════════════════════════════

def _strip_button_styles(reply_markup):
    if reply_markup is None or not hasattr(reply_markup, "keyboard"):
        return reply_markup
    for row in reply_markup.keyboard:
        for button in row:
            if hasattr(button, "style"):
                button.style = None
            if hasattr(button, "icon_custom_emoji_id"):
                button.icon_custom_emoji_id = None
    return reply_markup


def _send_with_relaxation(send_fn, reply_markup):
    try:
        return send_fn(reply_markup)
    except Exception as e:
        first_error = e
    try:
        import copy
        return send_fn(_strip_button_styles(copy.deepcopy(reply_markup)))
    except Exception:
        try:
            return send_fn(None)
        except Exception:
            raise first_error


def _is_missing_entities_kwarg(exc: Exception) -> bool:
    return isinstance(exc, TypeError) and "entities" in str(exc)


def safe_send(chat_id, text, reply_markup=None):
    plain, entities = render(text)
    try:
        return bot.send_message(chat_id, plain, reply_markup=reply_markup, entities=entities, disable_web_page_preview=True)
    except telebot.apihelper.ApiException as e:
        err = str(e)
        if "Flood" in err:
            try:
                wait = int(err.split("Retry after ")[1].split(" ")[0])
            except Exception:
                wait = 5
            time.sleep(wait)
            return safe_send(chat_id, text, reply_markup)
        if any(x in err for x in ("blocked", "not found", "deactivated", "chat not found")):
            return None
        log.warning(f"safe_send {chat_id}: {e} — retrying with a relaxed keyboard")
        try:
            return _send_with_relaxation(
                lambda markup: bot.send_message(chat_id, plain, reply_markup=markup, disable_web_page_preview=True),
                reply_markup,
            )
        except Exception as e2:
            log.error(f"safe_send {chat_id} (fallback): {e2}")
            return None
    except Exception as e:
        if _is_missing_entities_kwarg(e):
            return bot.send_message(chat_id, _to_plain_html(text), reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)
        log.error(f"safe_send {chat_id}: {e}")
        return None


def safe_edit(chat_id, msg_id, text, reply_markup=None):
    plain, entities = render(text)
    if plain is None or plain.strip() == "":
        return None
    try:
        return bot.edit_message_text(plain, chat_id, msg_id, reply_markup=reply_markup, entities=entities, disable_web_page_preview=True)
    except telebot.apihelper.ApiException as e:
        err = str(e)
        if "message is not modified" in err.lower():
            return None
        if "there is no text in the message to edit" in err.lower():
            try:
                return bot.edit_message_caption(
                    plain,
                    chat_id,
                    msg_id,
                    reply_markup=reply_markup,
                    caption_entities=entities,
                )
            except Exception as e2:
                log.warning(f"safe_edit {chat_id}/{msg_id}: {e2} — media caption edit failed")
                return None
        if "Flood" in err:
            try:
                wait = int(err.split("Retry after ")[1].split(" ")[0])
            except Exception:
                wait = 5
            time.sleep(wait)
            return safe_edit(chat_id, msg_id, text, reply_markup)
        log.warning(f"safe_edit {chat_id}/{msg_id}: {e} — retrying with a relaxed keyboard")
        try:
            return _send_with_relaxation(
                lambda markup: bot.edit_message_text(plain, chat_id, msg_id, reply_markup=markup, disable_web_page_preview=True),
                reply_markup,
            )
        except Exception as e2:
            log.error(f"safe_edit {chat_id}/{msg_id} (fallback): {e2}")
            return None
    except Exception as e:
        if _is_missing_entities_kwarg(e):
            return bot.edit_message_text(_to_plain_html(text), chat_id, msg_id, reply_markup=reply_markup, parse_mode="HTML", disable_web_page_preview=True)
        log.error(f"safe_edit {chat_id}/{msg_id}: {e}")
        return None


def safe_send_animation(chat_id, animation, caption=None, reply_markup=None, timeout=15):
    cap_plain, cap_entities = render(caption) if caption is not None else (None, None)
    try:
        # `timeout` is forwarded by telebot straight into the underlying HTTP
        # request's (connect, read) timeout, so a slow/hanging gif URL fails
        # fast instead of tying up a worker thread for telebot's default 30s.
        return bot.send_animation(chat_id, animation, caption=cap_plain, reply_markup=reply_markup, caption_entities=cap_entities, timeout=timeout)
    except telebot.apihelper.ApiException as e:
        err = str(e)
        if "Flood" in err:
            try:
                wait = int(err.split("Retry after ")[1].split(" ")[0])
            except Exception:
                wait = 5
            time.sleep(wait)
            return safe_send_animation(chat_id, animation, caption, reply_markup, timeout)
        if any(x in err for x in ("blocked", "not found", "deactivated", "chat not found")):
            return None
        log.warning(f"safe_send_animation {chat_id}: {e} — retrying with a relaxed keyboard")
        try:
            return _send_with_relaxation(
                lambda markup: bot.send_animation(chat_id, animation, caption=cap_plain, reply_markup=markup, timeout=timeout),
                reply_markup,
            )
        except Exception as e2:
            log.error(f"safe_send_animation {chat_id} (fallback): {e2}")
            return None
    except Exception as e:
        log.warning(f"safe_send_animation {chat_id}: {e} — retrying with a relaxed keyboard")
        try:
            return _send_with_relaxation(
                lambda markup: bot.send_animation(chat_id, animation, caption=cap_plain, reply_markup=markup, timeout=timeout),
                reply_markup,
            )
        except Exception as e2:
            log.error(f"safe_send_animation {chat_id} (fallback): {e2}")
            return None


def safe_send_sticker(chat_id, sticker, reply_markup=None):
    try:
        return bot.send_sticker(chat_id, sticker, reply_markup=reply_markup)
    except Exception as e:
        log.warning(f"safe_send_sticker {chat_id}: {e}")
        return None


def safe_send_photo(chat_id, photo, caption=None, reply_markup=None):
    cap_plain, cap_entities = render(caption) if caption is not None else (None, None)
    try:
        return bot.send_photo(chat_id, photo, caption=cap_plain, reply_markup=reply_markup, caption_entities=cap_entities)
    except Exception as e:
        log.warning(f"safe_send_photo {chat_id}: {e} — sending as text instead")
        return safe_send(chat_id, caption or "", reply_markup=reply_markup)


# ════════════════════════════════════════════════
#                   DATABASE
# ════════════════════════════════════════════════

_lock = threading.RLock()


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception as e:
        log.warning(f"could not apply sqlite pragmas: {e}")
    return conn


def init_db():
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance INTEGER DEFAULT 0,
                created_at INTEGER,
                last_seen INTEGER,
                banned INTEGER DEFAULT 0,
                referred_by INTEGER DEFAULT 0,
                referral_rewarded INTEGER DEFAULT 0,
                referrals_count INTEGER DEFAULT 0,
                gate_passed INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS gift_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                added_at INTEGER,
                used INTEGER DEFAULT 0,
                used_by INTEGER,
                used_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS gift_claims (
                claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                cost INTEGER,
                status TEXT DEFAULT 'pending',
                code TEXT,
                created_at INTEGER,
                decided_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS deposits (
                deposit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                inr_amount TEXT,
                credits INTEGER,
                utr TEXT,
                status TEXT DEFAULT 'awaiting_payment',
                created_at INTEGER,
                decided_at INTEGER
            );
            """
        )
        conn.commit()
        for k, v in DEFAULT_SETTINGS.items():
            cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()
        conn.close()
    log.info("database ready.")


# ── users ────────────────────────────────────────────────────────────────

def get_or_create_user(user_id: int, username: str, first_name: str, referrer_id: int = 0):
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        now = int(time.time())
        is_new = False
        if row is None:
            is_new = True
            cur.execute(
                "INSERT INTO users (user_id, username, first_name, balance, created_at, last_seen, referred_by) "
                "VALUES (?, ?, ?, 0, ?, ?, ?)",
                (user_id, username, first_name, now, now, referrer_id),
            )
            conn.commit()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
        else:
            # existing user: username/name refreshed, but referred_by is
            # NEVER overwritten — this is what guarantees that referring an
            # already-registered user rewards nobody.
            cur.execute(
                "UPDATE users SET username = ?, first_name = ?, last_seen = ? WHERE user_id = ?",
                (username, first_name, now, user_id),
            )
            conn.commit()
        conn.close()
        return dict(row), is_new


def get_user(user_id: int):
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def get_user_by_username(username: str):
    username = (username or "").lstrip("@").strip()
    if not username:
        return None
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def resolve_user(identifier: str):
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    if identifier.lstrip("-").isdigit():
        return get_user(int(identifier))
    return get_user_by_username(identifier)


def set_banned(user_id: int, banned: bool):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE users SET banned = ? WHERE user_id = ?", (1 if banned else 0, user_id))
        conn.commit()
        conn.close()


def mark_gate_passed(user_id: int):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE users SET gate_passed = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()


def mark_referral_rewarded(user_id: int):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE users SET referral_rewarded = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()


def increment_referral_count(user_id: int):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()


def add_balance(user_id: int, amount: int):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()


def deduct_balance(user_id: int, amount: int) -> bool:
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row is None or row["balance"] < amount:
            conn.close()
            return False
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        return True


def admin_adjust_balance(user_id: int, delta: int) -> int:
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = MAX(0, balance + ?) WHERE user_id = ?", (delta, user_id))
        conn.commit()
        cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return row["balance"] if row else 0


def all_user_ids():
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE banned = 0")
        rows = [r["user_id"] for r in cur.fetchall()]
        conn.close()
        return rows


def stats_summary():
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) c FROM users")
        total_users = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM users WHERE banned = 1")
        banned = cur.fetchone()["c"]
        cur.execute("SELECT COALESCE(SUM(balance),0) s FROM users")
        total_balance = cur.fetchone()["s"]
        cur.execute("SELECT COUNT(*) c FROM gift_codes WHERE used = 0")
        codes_left = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM gift_codes WHERE used = 1")
        codes_used = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM gift_claims WHERE status = 'pending'")
        pending_claims = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM deposits WHERE status = 'pending'")
        pending_deposits = cur.fetchone()["c"]
        conn.close()
        return {
            "total_users": total_users, "banned": banned, "total_balance": total_balance,
            "codes_left": codes_left, "codes_used": codes_used,
            "pending_claims": pending_claims, "pending_deposits": pending_deposits,
        }


# ── settings ─────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = None):
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()
        conn.close()


# ── gift codes / claims ─────────────────────────────────────────────────

def add_gift_codes(codes: list[str]):
    added, skipped = 0, 0
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        for code in codes:
            code = code.strip()
            if not code:
                continue
            try:
                cur.execute(
                    "INSERT INTO gift_codes (code, added_at, used) VALUES (?, ?, 0)",
                    (code, int(time.time())),
                )
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit()
        conn.close()
    return added, skipped


def count_available_gift_codes() -> int:
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) c FROM gift_codes WHERE used = 0")
        c = cur.fetchone()["c"]
        conn.close()
        return c


def assign_gift_code(user_id: int):
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, code FROM gift_codes WHERE used = 0 ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if row is None:
            conn.close()
            return None
        cur.execute(
            "UPDATE gift_codes SET used = 1, used_by = ?, used_at = ? WHERE id = ?",
            (user_id, int(time.time()), row["id"]),
        )
        conn.commit()
        conn.close()
        return row["code"]


def create_gift_claim(user_id: int, cost: int) -> int:
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO gift_claims (user_id, cost, status, created_at) VALUES (?, ?, 'pending', ?)",
            (user_id, cost, int(time.time())),
        )
        conn.commit()
        claim_id = cur.lastrowid
        conn.close()
        return claim_id


def get_gift_claim(claim_id: int):
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM gift_claims WHERE claim_id = ?", (claim_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def set_gift_claim_status(claim_id: int, status: str, code: str = None):
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE gift_claims SET status = ?, code = ?, decided_at = ? WHERE claim_id = ?",
            (status, code, int(time.time()), claim_id),
        )
        conn.commit()
        conn.close()


def list_pending_gift_claims():
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM gift_claims WHERE status = 'pending' ORDER BY claim_id ASC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows


# ── deposits ─────────────────────────────────────────────────────────────

def create_deposit(user_id: int, inr_amount: str, credits: int) -> int:
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO deposits (user_id, inr_amount, credits, status, created_at) "
            "VALUES (?, ?, ?, 'awaiting_payment', ?)",
            (user_id, inr_amount, credits, int(time.time())),
        )
        conn.commit()
        dep_id = cur.lastrowid
        conn.close()
        return dep_id


def get_deposit(deposit_id: int):
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM deposits WHERE deposit_id = ?", (deposit_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None


def set_deposit_status(deposit_id: int, status: str):
    with _lock:
        conn = get_conn()
        conn.execute(
            "UPDATE deposits SET status = ?, decided_at = ? WHERE deposit_id = ?",
            (status, int(time.time()), deposit_id),
        )
        conn.commit()
        conn.close()


def set_deposit_utr(deposit_id: int, utr: str):
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE deposits SET utr = ? WHERE deposit_id = ?", (utr, deposit_id))
        conn.commit()
        conn.close()


def list_pending_deposits():
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM deposits WHERE status = 'pending' ORDER BY deposit_id ASC")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows


# ── backup / restore ────────────────────────────────────────────────────

def backup_db(dest_path: str):
    import shutil
    with _lock:
        shutil.copyfile(DB_PATH, dest_path)
    return dest_path


def restore_db(src_path: str):
    import shutil
    with _lock:
        shutil.copyfile(src_path, DB_PATH)


def _is_valid_sqlite_db(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            header = f.read(16)
        if header[:16] != b"SQLite format 3\x00":
            return False
        conn = sqlite3.connect(path)
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            result = cur.fetchone()
            return bool(result) and result[0] == "ok"
        finally:
            conn.close()
    except Exception:
        return False


# ════════════════════════════════════════════════
#                     BOT INSTANCE
# ════════════════════════════════════════════════

class _LoggingExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        log.error("unhandled exception in a bot handler", exc_info=exception)
        return True


bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode=None,
    exception_handler=_LoggingExceptionHandler(),
    # pyTelegramBotAPI only spins up 2 worker threads by default. Every
    # incoming message/callback across every chat is handled by one of these
    # threads, so if a couple of them get tied up waiting on something slow
    # (e.g. Telegram fetching an external gif URL for the dashboard), the
    # whole bot appears to freeze — buttons stop responding for everyone
    # until those calls finish. Give it real headroom.
    num_threads=16,
)

user_states: dict[int, dict] = {}


def set_state(user_id: int, state: str, data: dict | None = None):
    user_states[user_id] = {"state": state, "data": data or {}}


def get_state(user_id: int) -> dict:
    return user_states.get(user_id, {"state": None, "data": {}})


def clear_state(user_id: int):
    user_states.pop(user_id, None)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_group_chat(chat) -> bool:
    """True for any chat that is not a 1:1 private chat with the bot."""
    return getattr(chat, "type", "private") != "private"


def guarded_message(fn):
    @functools.wraps(fn)
    def wrapper(message: types.Message, *args, **kwargs):
        if is_group_chat(message.chat):
            # The bot stays in groups/supergroups/channels if added, but it
            # never sends or reacts to messages there — only in 1:1 private
            # chats. So just do nothing here.
            return
        try:
            return fn(message, *args, **kwargs)
        except Exception as e:
            log.error(f"unhandled error in {fn.__name__}: {e}", exc_info=True)
            try:
                clear_state(message.from_user.id)
                safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('something went wrong. please try again from the menu.')}\n{DIV}")
            except Exception:
                pass
    return wrapper


def guarded_callback(fn):
    @functools.wraps(fn)
    def wrapper(call: types.CallbackQuery, *args, **kwargs):
        if is_group_chat(call.message.chat):
            # Never act on button presses inside a group either. We still
            # answer the callback query (required by Telegram so the
            # user's client doesn't show a loading spinner forever), but
            # send no message and run no handler logic.
            try:
                bot.answer_callback_query(call.id)
            except Exception:
                pass
            return
        try:
            return fn(call, *args, **kwargs)
        except Exception as e:
            log.error(f"unhandled error in {fn.__name__}: {e}", exc_info=True)
            try:
                bot.answer_callback_query(call.id, sc("something went wrong. please try again."), show_alert=True)
            except Exception:
                pass
    return wrapper


def setup_bot_menu():
    try:
        bot.set_my_commands([types.BotCommand("start", sc("start the bot"))])
        bot.set_chat_menu_button(menu_button=types.MenuButtonCommands())
    except Exception as e:
        log.error(f"failed to set bot menu: {e}")


# ════════════════════════════════════════════════
#                     KEYBOARDS
# ════════════════════════════════════════════════

def _button_kwargs(style: str, emoji: str | None) -> dict:
    kwargs = {"style": style}
    if emoji and emoji in CUSTOM_EMOJIS:
        kwargs["icon_custom_emoji_id"] = CUSTOM_EMOJIS[emoji][1]
    return kwargs


def btn(text, cb, style: str = "primary", emoji: str | None = None):
    label = sc(text)
    kwargs = _button_kwargs(style, emoji)
    try:
        return types.InlineKeyboardButton(label, callback_data=cb, **kwargs)
    except TypeError:
        pass
    try:
        return types.InlineKeyboardButton(label, callback_data=cb, style=style)
    except TypeError:
        pass
    return types.InlineKeyboardButton(label, callback_data=cb)


def url_btn(text, url, style: str = "primary", emoji: str | None = None):
    label = sc(text)
    kwargs = _button_kwargs(style, emoji)
    try:
        return types.InlineKeyboardButton(label, url=url, **kwargs)
    except TypeError:
        pass
    try:
        return types.InlineKeyboardButton(label, url=url, style=style)
    except TypeError:
        pass
    return types.InlineKeyboardButton(label, url=url)


def force_join_kb(missing: list[dict]):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch in missing:
        kb.add(url_btn(f"join {ch['name']}", ch["link"], style="primary"))
    kb.add(btn("check again", "check_join", style="success", emoji="verify"))
    return kb


def main_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("profile", "menu_profile", style="primary", emoji="profile"),
        btn("buy credits", "menu_buycredits", style="primary", emoji="credit"),
    )
    kb.add(
        btn("gift card", "menu_gift", style="primary", emoji="amazon"),
        btn("refer & earn", "menu_refer", style="primary", emoji="referral"),
    )
    kb.add(btn("join updates", "menu_joinupdates", style="success", emoji="join"))
    return kb


def back_kb(target="back_main", label="back"):
    kb = types.InlineKeyboardMarkup()
    kb.add(btn(label, target, style="danger", emoji="back"))
    return kb


def gift_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("buy gift card", "gift_buy_prompt", style="success", emoji="amazon"),
        btn("back", "back_main", style="danger", emoji="back"),
    )
    return kb


def gift_confirm_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("buy gift card", "gift_confirm", style="success", emoji="verify"),
        btn("cancel", "menu_gift", style="danger", emoji="cross"),
    )
    return kb


def buy_credits_cancel_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(btn("back", "back_main", style="danger", emoji="back"))
    return kb


def buy_payment_kb(deposit_id: int):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("paid", f"buy_paid_{deposit_id}", style="success", emoji="verify"),
        btn("cancel", f"buy_cancel_{deposit_id}", style="danger", emoji="cross"),
    )
    return kb


def buy_awaiting_utr_kb(deposit_id: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(btn("cancel", f"buy_cancel_{deposit_id}", style="danger", emoji="cross"))
    return kb


def refer_kb(user_id: int):
    kb = types.InlineKeyboardMarkup(row_width=1)
    invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    share_text = f"Join this bot and earn credits! Use my link: {invite_link}"
    share_url = f"https://t.me/share/url?url={invite_link}&text={requests.utils.quote(share_text)}"
    kb.add(url_btn("share referral link", share_url, style="primary", emoji="share"))
    kb.add(btn("back", "back_main", style="danger", emoji="back"))
    return kb


def joinupdates_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(url_btn("join channel", JOIN_UPDATES_LINK, style="success", emoji="join"))
    kb.add(btn("back", "back_main", style="danger", emoji="back"))
    return kb


def dep_action_kb(deposit_id: int):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("approve", f"dep_approve_{deposit_id}", style="success", emoji="verify"),
        btn("reject", f"dep_reject_{deposit_id}", style="danger", emoji="cross"),
    )
    return kb


def gift_action_kb(claim_id: int):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("approve", f"giftclaim_approve_{claim_id}", style="success", emoji="verify"),
        btn("reject", f"giftclaim_reject_{claim_id}", style="danger", emoji="cross"),
    )
    return kb


def admin_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("set upi id", "admin_set_upi", style="primary"),
        btn("set buy rate", "admin_set_rate", style="primary"),
    )
    kb.add(
        btn("set gift price", "admin_set_giftprice", style="primary"),
        btn("set ref reward", "admin_set_refreward", style="primary"),
    )
    kb.add(
        btn("dashboard gif", "admin_set_dashboard_gif", style="primary"),
        btn("clear gif", "admin_clear_dashboard_gif", style="danger"),
    )
    kb.add(
        btn("user sticker", "admin_set_dashboard_sticker", style="primary"),
        btn("remove sticker", "admin_clear_dashboard_sticker", style="danger"),
    )
    kb.add(
        btn("amazon sticker", "admin_set_amazon_sticker", style="primary"),
        btn("remove amazon", "admin_clear_amazon_sticker", style="danger"),
    )
    kb.add(
        btn("add gift codes", "admin_addgiftcodes", style="primary"),
        btn("gift claims", "admin_pending_claims", style="primary"),
    )
    kb.add(
        btn("pending payments", "admin_pending_deposits", style="primary"),
        btn("add/remove credits", "admin_credits_menu", style="primary"),
    )
    kb.add(
        btn("ban user", "admin_ban", style="danger"),
        btn("unban user", "admin_unban", style="success"),
    )
    kb.add(
        btn("stats", "admin_stats", style="primary"),
        btn("broadcast", "admin_broadcast", style="primary"),
    )
    kb.add(
        btn("backup db", "admin_backup", style="success"),
        btn("restore db", "admin_restore", style="danger"),
    )
    return kb


def admin_back_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(btn("back to admin panel", "admin_back", style="danger"))
    return kb


def admin_credits_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("add credits", "admin_addcredit", style="success"),
        btn("remove credits", "admin_removecredit", style="danger"),
    )
    kb.add(btn("back to admin panel", "admin_back", style="danger"))
    return kb


# ════════════════════════════════════════════════
#                   TEXT BUILDERS
# ════════════════════════════════════════════════

def txt_force_join():
    return (
        f"{DIV}\n"
        f"{ce('blocked')} {B(sc('access locked'))}\n"
        f"{DIV2}\n"
        f"{sc('join all the channels below, then tap')} {B(sc('check again'))} {sc('to continue.')}\n"
        f"{sc('your balance stays at 0 until you join everything.')}\n"
        f"{DIV}"
    )


def txt_dashboard(user):
    currency = get_setting("currency_name", "credits")
    balance_text = str(user['balance']) + ' ' + sc(currency)
    return (
        f"{DIV}\n"
        f"{B(sc('balance'))}: {ce('credit')} {C(balance_text)}\n"
        f"{DIV2}\n"
        f"{ce('below')} {sc('choose an option below')}\n"
        f"{DIV}"
    )


def txt_profile(user):
    currency = get_setting("currency_name", "credits")
    username = f"@{user['username']}" if user.get("username") else sc("not set")
    referred_line = ""
    if user.get("referred_by"):
        referrer = get_user(user["referred_by"])
        ref_label = f"@{referrer['username']}" if referrer and referrer.get("username") else sc("a friend")
        referred_line = f"{sc('referred by')}: {C(esc(ref_label))}\n"
    return (
        f"{DIV}\n"
        f"{ce('profile')} {B(sc('your profile'))}\n"
        f"{DIV2}\n"
        f"{sc('name')}: {C(esc(user.get('first_name') or sc('not set')))}\n"
        f"{sc('username')}: {C(esc(username))}\n"
        f"{B(sc('balance'))}: {ce('credit')} {C(str(user['balance']) + ' ' + sc(currency))}\n"
        f"{sc('joined on')}: {C(fmt_dt(user.get('created_at')))}\n"
        f"{referred_line}"
        f"{sc('total referrals')}: {C(str(user.get('referrals_count', 0)))}\n"
        f"{DIV}"
    )


def txt_gift_menu(cost, currency):
    return (
        f"{DIV}\n"
        f"{ce('gift')} {B(sc('gift card'))}\n"
        f"{DIV2}\n"
        f"{sc('redeem your credits for a gift card code.')}\n"
        f"{sc('cost')}: {C(str(cost) + ' ' + sc(currency))}\n"
        f"{sc('once approved, the code is sent here automatically.')}\n"
        f"{DIV}"
    )


def txt_gift_confirm(cost, balance, currency):
    return (
        f"{DIV}\n"
        f"{ce('gift')} {B(sc('confirm gift card purchase'))}\n"
        f"{DIV2}\n"
        f"{sc('cost')}: {C(str(cost) + ' ' + sc(currency))}\n"
        f"{sc('your balance')}: {C(str(balance) + ' ' + sc(currency))}\n"
        f"{DIV}"
    )


def txt_gift_insufficient(cost, currency):
    return (
        f"{DIV}\n"
        f"{ce('cross')} {B(sc('insufficient balance'))}\n"
        f"{DIV2}\n"
        f"{sc('you need')} {C(str(cost) + ' ' + sc(currency))} {sc('to buy a gift card. tap buy credits to top up.')}\n"
        f"{DIV}"
    )


def txt_gift_pending():
    return (
        f"{DIV}\n"
        f"{ce('clock')} {B(sc('request sent'))}\n"
        f"{DIV2}\n"
        f"{sc('your gift card request has been sent to the admin. please wait for approval.')}\n"
        f"{DIV}"
    )


def txt_gift_approved(code):
    return (
        f"{DIV}\n"
        f"{ce('verify')} {B(sc('gift card approved!'))}\n"
        f"{DIV2}\n"
        f"{sc('your code')}:\n{C(esc(code))}\n"
        f"{DIV}"
    )


def txt_gift_rejected(refund, currency):
    return (
        f"{DIV}\n"
        f"{ce('cross')} {B(sc('gift card request rejected'))}\n"
        f"{DIV2}\n"
        f"{C(str(refund) + ' ' + sc(currency))} {sc('has been refunded to your balance.')}\n"
        f"{sc('please try again, or contact support if you have any issue.')}\n"
        f"{DIV}"
    )


def txt_buycredits_prompt(rate_inr, rate_credits, min_credits, currency):
    return (
        f"{DIV}\n"
        f"{ce('credit')} {B(sc('buy credits'))}\n"
        f"{DIV2}\n"
        f"{sc('enter how many credits you want to add:')}\n"
        f"{DIV2}\n"
        f"{C(f'{rate_inr} rs = {rate_credits} {sc(currency)}')}\n"
        f"{sc('minimum')}: {C(str(min_credits) + ' ' + sc(currency))}\n"
        f"{DIV}"
    )


def txt_payment_details(credits, inr_amount, upi_id, currency):
    return (
        f"{DIV}\n"
        f"{ce('credit')} {B(sc('complete your payment'))}\n"
        f"{DIV2}\n"
        f"{sc('amount to pay')}: {C(f'₹{inr_amount}')}\n"
        f"{sc('credits')}: {C(str(credits) + ' ' + sc(currency))}\n"
        f"{DIV2}\n"
        f"{sc('upi id')}:\n{C(esc(upi_id))}\n"
        f"{DIV2}\n"
        f"{sc('scan the qr code or pay to the upi id above, then tap')} {B(sc('paid'))}.\n"
        f"{DIV}"
    )


def txt_awaiting_utr():
    return (
        f"{DIV}\n"
        f"{ce('pin')} {B(sc('enter transaction id'))}\n"
        f"{DIV2}\n"
        f"{sc('please send your utr / transaction id number now.')}\n"
        f"{DIV}"
    )


def txt_deposit_pending():
    return (
        f"{DIV}\n"
        f"{ce('clock')} {B(sc('sent for approval'))}\n"
        f"{DIV2}\n"
        f"{sc('your payment has been sent to the admin. credits will be added once approved.')}\n"
        f"{DIV}"
    )


def txt_deposit_cancelled():
    return f"{DIV}\n{ce('cross')} {sc('payment cancelled.')}\n{DIV}"


def txt_deposit_approved(credits, currency):
    return (
        f"{DIV}\n"
        f"{ce('verify')} {B(sc('payment approved!'))}\n"
        f"{DIV2}\n"
        f"{C(str(credits) + ' ' + sc(currency))} {sc('has been added to your balance.')}\n"
        f"{DIV}"
    )


def txt_deposit_rejected():
    return (
        f"{DIV}\n"
        f"{ce('cross')} {B(sc('payment rejected'))}\n"
        f"{DIV2}\n"
        f"{sc('your payment could not be verified. please try again, or contact support if you have any issue.')}\n"
        f"{DIV}"
    )


def txt_refer(user, reward, currency, invite_link):
    return (
        f"{DIV}\n"
        f"{ce('referral')} {B(sc('refer & earn'))}\n"
        f"{DIV2}\n"
        f"{sc('per refer')}: {C(str(reward) + ' ' + sc(currency))}\n"
        f"{sc('total referrals')}: {C(str(user.get('referrals_count', 0)))}\n"
        f"{DIV2}\n"
        f"{sc('your referral link')}:\n{C(invite_link)}\n"
        f"{DIV2}\n"
        f"{sc('the credit is given only after your friend joins all required channels.')}\n"
        f"{DIV}"
    )


def txt_referral_success(new_name, reward, currency):
    return (
        f"{DIV}\n"
        f"{ce('referral')} {B(sc('referral bonus!'))}\n"
        f"{DIV2}\n"
        f"{C(esc(new_name))} {sc('joined using your link.')}\n"
        f"{C(str(reward) + ' ' + sc(currency))} {sc('has been added to your balance.')}\n"
        f"{DIV}"
    )


def txt_joinupdates():
    return (
        f"{DIV}\n"
        f"{ce('join')} {B(sc('join updates'))}\n"
        f"{DIV2}\n"
        f"{sc('stay updated with the latest news and announcements.')}\n"
        f"{DIV}"
    )


def txt_admin_menu():
    return f"{DIV}\n{ce('crown')} {B(sc('admin panel'))}\n{DIV}"


def txt_admin_prompt(label):
    return f"{DIV}\n{ce('pin')} {sc(label)}\n{DIV}"


def txt_admin_stats(s, currency):
    return (
        f"{DIV}\n"
        f"{ce('idea')} {B(sc('bot stats'))}\n"
        f"{DIV2}\n"
        f"{sc('total users')}: {C(str(s['total_users']))}\n"
        f"{sc('banned users')}: {C(str(s['banned']))}\n"
        f"{sc('total balance in circulation')}: {C(str(s['total_balance']) + ' ' + sc(currency))}\n"
        f"{DIV2}\n"
        f"{sc('gift codes left')}: {C(str(s['codes_left']))}\n"
        f"{sc('gift codes used')}: {C(str(s['codes_used']))}\n"
        f"{sc('pending gift claims')}: {C(str(s['pending_claims']))}\n"
        f"{sc('pending payments')}: {C(str(s['pending_deposits']))}\n"
        f"{DIV}"
    )


def txt_admin_giftcodes_added(added, skipped, remaining):
    return (
        f"{DIV}\n"
        f"{ce('verify')} {B(sc('gift codes added'))}\n"
        f"{DIV2}\n"
        f"{sc('added')}: {C(str(added))}\n"
        f"{sc('skipped (duplicate)')}: {C(str(skipped))}\n"
        f"{sc('total available now')}: {C(str(remaining))}\n"
        f"{DIV}"
    )


def txt_admin_out_of_stock():
    return f"{DIV}\n{ce('blocked')} {B(sc('gift codes finished!'))}\n{DIV2}\n{sc('add more gift codes to keep approving claims.')}\n{DIV}"


def txt_admin_no_stock_alert():
    return sc("no gift codes in stock — add codes first.")


def txt_admin_ban_prompt():
    return txt_admin_prompt("send the user's @username or numeric user id to ban:")


def txt_admin_unban_prompt():
    return txt_admin_prompt("send the user's @username or numeric user id to unban:")


def txt_admin_credit_prompt(action):
    return txt_admin_prompt(f"send: <username or user id> <amount> — to {action} credits")


def txt_admin_user_not_found():
    return f"{DIV}\n{ce('cross')} {sc('user not found.')}\n{DIV}"


def txt_admin_banned(user, banned: bool):
    label = f"@{user['username']}" if user.get("username") else str(user["user_id"])
    verb = sc("banned") if banned else sc("unbanned")
    return f"{DIV}\n{ce('verify')} {C(esc(label))} {sc('has been')} {B(verb)}.\n{DIV}"


def txt_admin_credit_updated(user, delta, new_balance, currency):
    label = f"@{user['username']}" if user.get("username") else str(user["user_id"])
    verb = sc("added to") if delta >= 0 else sc("removed from")
    return (
        f"{DIV}\n{ce('verify')} {B(sc('credits updated'))}\n{DIV}\n"
        f"{C(str(abs(delta)))} {C(currency)} {verb} {C(esc(label))}\n"
        f"{sc('new balance')}: {C(str(new_balance) + ' ' + currency)}\n{DIV}"
    )


def txt_admin_broadcast_prompt():
    return txt_admin_prompt("send the message you want to broadcast to all users now:")


def txt_admin_broadcast_done(sent, failed):
    return f"{DIV}\n{ce('verify')} {B(sc('broadcast finished'))}\n{DIV}\n{sc('sent')}: {C(str(sent))}\n{sc('failed')}: {C(str(failed))}\n{DIV}"


def txt_admin_only_number():
    return f"{DIV}\n{ce('cross')} {sc('send a valid whole number.')}\n{DIV}"


def txt_admin_restore_prompt():
    return f"{DIV}\n{ce('pin')} {sc('upload the .db backup file to restore now.')}\n{DIV}"


def txt_admin_restore_done():
    return f"{DIV}\n{ce('verify')} {sc('database restored successfully.')}\n{DIV}"


# ── admin notification texts ─────────────────────────────────────────────

def txt_admin_new_deposit(dep, user):
    label = f"@{user['username']}" if user.get("username") else str(user["user_id"])
    amount_str = f"₹{dep['inr_amount']}"
    return (
        f"{DIV}\n{ce('credit')} {B(sc('new payment request'))}\n{DIV2}\n"
        f"{sc('user')}: {C(esc(label))} ({C(str(user['user_id']))})\n"
        f"{sc('amount')}: {C(amount_str)}\n"
        f"{sc('credits')}: {C(str(dep['credits']))}\n"
        f"{sc('utr')}: {C(esc(dep['utr'] or ''))}\n{DIV}"
    )


def txt_admin_new_gift_claim(claim, user):
    label = f"@{user['username']}" if user.get("username") else str(user["user_id"])
    return (
        f"{DIV}\n{ce('gift')} {B(sc('new gift card request'))}\n{DIV2}\n"
        f"{sc('user')}: {C(esc(label))} ({C(str(user['user_id']))})\n"
        f"{sc('cost')}: {C(str(claim['cost']))}\n{DIV}"
    )


# ════════════════════════════════════════════════
#              QR CODE GENERATION (UPI)
# ════════════════════════════════════════════════

def generate_upi_qr(upi_id: str, payee_name: str, amount: str, note: str = "Credits Purchase"):
    if not _HAS_QR:
        return None
    payload = (
        f"upi://pay?pa={upi_id}&pn={requests.utils.quote(payee_name)}"
        f"&am={amount}&cu=INR&tn={requests.utils.quote(note)}"
    )
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = io.BytesIO()
    bio.name = "payment_qr.png"
    img.save(bio, "PNG")
    bio.seek(0)
    return bio


# ════════════════════════════════════════════════
#           MEMBERSHIP / FORCE-JOIN GATE
# ════════════════════════════════════════════════

def _is_member_of(chat_id: str, user_id: int) -> bool:
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        log.warning(f"membership check failed for {user_id} in {chat_id}: {e}")
        return False


def missing_channels(user_id: int) -> list[dict]:
    return [ch for ch in FORCE_JOIN_CHANNELS if not _is_member_of(ch["id"], user_id)]


def send_force_join(chat_id: int, missing: list[dict]):
    safe_send(chat_id, txt_force_join(), reply_markup=force_join_kb(missing))


# ════════════════════════════════════════════════
#                     DASHBOARD
# ════════════════════════════════════════════════

def send_dashboard(chat_id: int, user_id: int, edit_message_id: int | None = None):
    user = get_user(user_id)
    if not user:
        return

    dashboard_text = txt_dashboard(user)
    menu = main_menu_kb()
    gif_id = (get_setting("dashboard_gif_file_id", DEFAULT_DASHBOARD_GIF) or "").strip()

    # Same visual language as credkr.py: the gif carries the caption AND the
    # inline keyboard directly (one message, not two) — cleaner and more
    # compact than posting a separate decorative gif plus a separate text
    # message underneath it.
    if gif_id:
        sent = safe_send_animation(chat_id, gif_id, caption=dashboard_text, reply_markup=menu)
        if sent:
            # Once Telegram has fetched an external URL once, cache the
            # file_id it hands back and swap the setting over to it — every
            # dashboard load after that reuses the already-uploaded file and
            # returns almost instantly instead of re-fetching the URL again.
            try:
                if getattr(sent, "animation", None) and gif_id.startswith(("http://", "https://")):
                    current = get_setting("dashboard_gif_file_id", "")
                    if current == gif_id:
                        set_setting("dashboard_gif_file_id", sent.animation.file_id)
            except Exception as e:
                log.warning(f"dashboard gif file_id cache update failed: {e}")

            if edit_message_id:
                try:
                    bot.delete_message(chat_id, edit_message_id)
                except Exception:
                    try:
                        bot.edit_message_reply_markup(chat_id, edit_message_id, reply_markup=None)
                    except Exception:
                        pass
            return

    # no gif configured, or sending it failed — fall back to a plain text
    # dashboard so the buttons are never lost.
    if edit_message_id and safe_edit(chat_id, edit_message_id, dashboard_text, reply_markup=menu):
        return
    safe_send(chat_id, dashboard_text, reply_markup=menu)


def handle_referral_reward(new_user_id: int, new_user_name: str):
    user = get_user(new_user_id)
    if not user or not user.get("referred_by") or user.get("referral_rewarded"):
        return
    referrer_id = user["referred_by"]
    if referrer_id == new_user_id:
        return
    referrer = get_user(referrer_id)
    if not referrer or referrer.get("banned"):
        return
    reward = int(get_setting("referral_reward_credits", "1"))
    add_balance(referrer_id, reward)
    increment_referral_count(referrer_id)
    mark_referral_rewarded(new_user_id)
    currency = get_setting("currency_name", "credits")
    try:
        safe_send(referrer_id, txt_referral_success(new_user_name or f"user {new_user_id}", reward, currency))
    except Exception as e:
        log.warning(f"failed to alert referrer {referrer_id}: {e}")


# ════════════════════════════════════════════════
#                 /start & FORCE JOIN
# ════════════════════════════════════════════════

@bot.message_handler(commands=["start"])
@guarded_message
def handle_start(message: types.Message):
    user_id = message.from_user.id
    clear_state(user_id)

    parts = message.text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    referrer_id = 0
    if payload.startswith("ref_"):
        candidate = payload[4:].strip()
        if candidate.isdigit():
            referrer_id = int(candidate)
    if referrer_id == user_id:
        referrer_id = 0

    user, is_new = get_or_create_user(
        user_id,
        message.from_user.username or "",
        message.from_user.first_name or "",
        referrer_id=referrer_id,
    )

    if user.get("banned"):
        safe_send(message.chat.id, f"{ce('blocked')} {sc('you are')} {B(sc('banned'))}.")
        return

    missing = missing_channels(user_id)
    if missing:
        send_force_join(message.chat.id, missing)
        return

    was_gated = bool(user.get("gate_passed", 0))
    if not was_gated:
        mark_gate_passed(user_id)
        handle_referral_reward(user_id, message.from_user.first_name or message.from_user.username or "")

    send_dashboard(message.chat.id, user_id)


@bot.callback_query_handler(func=lambda c: c.data == "check_join")
@guarded_callback
def cb_check_join(call: types.CallbackQuery):
    user_id = call.from_user.id
    missing = missing_channels(user_id)
    message = _callback_message(call)
    if message is None:
        return
    if missing:
        bot.answer_callback_query(call.id, sc("you haven't joined all channels yet."), show_alert=True)
        safe_edit(message.chat.id, message.message_id, txt_force_join(), reply_markup=force_join_kb(missing))
        return

    user = get_user(user_id)
    if not user:
        bot.answer_callback_query(call.id)
        return

    was_gated = bool(user.get("gate_passed", 0))
    if not was_gated:
        mark_gate_passed(user_id)
        handle_referral_reward(user_id, call.from_user.first_name or call.from_user.username or "")

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)
    send_dashboard(message.chat.id, user_id)


@bot.callback_query_handler(func=lambda c: c.data == "back_main")
@guarded_callback
def cb_back_main(call: types.CallbackQuery):
    clear_state(call.from_user.id)
    message = _callback_message(call)
    if message is None:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(call.id)
    send_dashboard(message.chat.id, call.from_user.id)


def _callback_message(call: types.CallbackQuery):
    message = getattr(call, "message", None)
    if message is None:
        try:
            bot.answer_callback_query(call.id, sc("tap the button again from the bot menu."), show_alert=False)
        except Exception:
            pass
        return None
    return message


def _require_active_user(call: types.CallbackQuery):
    """returns the user dict, or None (and answers the callback) if the
    user is banned or hasn't cleared the force-join gate."""
    user_id = call.from_user.id
    user = get_user(user_id)
    if not user:
        bot.answer_callback_query(call.id)
        return None
    if user.get("banned"):
        bot.answer_callback_query(call.id, sc("you are banned."), show_alert=True)
        return None
    message = _callback_message(call)
    if message is None:
        return None
    missing = missing_channels(user_id)
    if missing:
        bot.answer_callback_query(call.id, sc("join all channels first."), show_alert=True)
        safe_edit(message.chat.id, message.message_id, txt_force_join(), reply_markup=force_join_kb(missing))
        return None
    return user


# ════════════════════════════════════════════════
#                     PROFILE
# ════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data == "menu_profile")
@guarded_callback
def cb_menu_profile(call: types.CallbackQuery):
    user = _require_active_user(call)
    message = _callback_message(call)
    if not user or message is None:
        return
    bot.answer_callback_query(call.id)
    safe_edit(message.chat.id, message.message_id, txt_profile(user), reply_markup=back_kb())


# ════════════════════════════════════════════════
#                     GIFT CARD
# ════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data == "menu_gift")
@guarded_callback
def cb_menu_gift(call: types.CallbackQuery):
    if not _require_active_user(call):
        return
    message = _callback_message(call)
    if message is None:
        return
    cost = int(get_setting("gift_card_cost_credits", "10"))
    currency = get_setting("currency_name", "credits")
    bot.answer_callback_query(call.id)
    safe_edit(message.chat.id, message.message_id, txt_gift_menu(cost, currency), reply_markup=gift_menu_kb())


@bot.callback_query_handler(func=lambda c: c.data == "gift_buy_prompt")
@guarded_callback
def cb_gift_buy_prompt(call: types.CallbackQuery):
    user = _require_active_user(call)
    message = _callback_message(call)
    if not user or message is None:
        return
    cost = int(get_setting("gift_card_cost_credits", "10"))
    currency = get_setting("currency_name", "credits")
    bot.answer_callback_query(call.id)
    safe_edit(message.chat.id, message.message_id, txt_gift_confirm(cost, user["balance"], currency), reply_markup=gift_confirm_kb())


@bot.callback_query_handler(func=lambda c: c.data == "gift_confirm")
@guarded_callback
def cb_gift_confirm(call: types.CallbackQuery):
    user = _require_active_user(call)
    if not user:
        return
    cost = int(get_setting("gift_card_cost_credits", "10"))
    currency = get_setting("currency_name", "credits")

    if not deduct_balance(user["user_id"], cost):
        bot.answer_callback_query(call.id, sc("insufficient balance."), show_alert=True)
        safe_edit(call.message.chat.id, call.message.message_id, txt_gift_insufficient(cost, currency), reply_markup=back_kb(target="menu_gift"))
        return

    claim_id = create_gift_claim(user["user_id"], cost)
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_gift_pending(), reply_markup=back_kb())

    claim = get_gift_claim(claim_id)
    for admin_id in ADMIN_IDS:
        safe_send(admin_id, txt_admin_new_gift_claim(claim, user), reply_markup=gift_action_kb(claim_id))


@bot.callback_query_handler(func=lambda c: c.data.startswith("giftclaim_approve_"))
@guarded_callback
def cb_giftclaim_approve(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    claim_id = int(call.data.split("_")[-1])
    claim = get_gift_claim(claim_id)
    if not claim or claim["status"] != "pending":
        bot.answer_callback_query(call.id, sc("already handled."), show_alert=True)
        return

    code = assign_gift_code(claim["user_id"])
    if code is None:
        bot.answer_callback_query(call.id, txt_admin_no_stock_alert(), show_alert=True)
        return

    set_gift_claim_status(claim_id, "approved", code=code)
    bot.answer_callback_query(call.id, sc("approved."))
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    safe_send(claim["user_id"], txt_gift_approved(code))

    if count_available_gift_codes() == 0:
        for admin_id in ADMIN_IDS:
            safe_send(admin_id, txt_admin_out_of_stock())


@bot.callback_query_handler(func=lambda c: c.data.startswith("giftclaim_reject_"))
@guarded_callback
def cb_giftclaim_reject(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    claim_id = int(call.data.split("_")[-1])
    claim = get_gift_claim(claim_id)
    if not claim or claim["status"] != "pending":
        bot.answer_callback_query(call.id, sc("already handled."), show_alert=True)
        return

    set_gift_claim_status(claim_id, "rejected")
    add_balance(claim["user_id"], claim["cost"])
    currency = get_setting("currency_name", "credits")
    bot.answer_callback_query(call.id, sc("rejected."))
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    safe_send(claim["user_id"], txt_gift_rejected(claim["cost"], currency))


# ════════════════════════════════════════════════
#                   BUY CREDITS
# ════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data == "menu_buycredits")
@guarded_callback
def cb_menu_buycredits(call: types.CallbackQuery):
    if not _require_active_user(call):
        return
    message = _callback_message(call)
    if message is None:
        return
    rate_inr = get_setting("rate_inr", "4")
    rate_credits = get_setting("rate_credits", "10")
    min_credits = get_setting("min_buy_credits", "10")
    currency = get_setting("currency_name", "credits")
    set_state(call.from_user.id, "awaiting_buy_credits_amount")
    bot.answer_callback_query(call.id)
    safe_edit(
        message.chat.id, message.message_id,
        txt_buycredits_prompt(rate_inr, rate_credits, min_credits, currency),
        reply_markup=buy_credits_cancel_kb(),
    )


@bot.message_handler(func=lambda m: get_state(m.from_user.id)["state"] == "awaiting_buy_credits_amount", content_types=["text"])
@guarded_message
def handle_buy_credits_amount(message: types.Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user or user.get("banned"):
        clear_state(user_id)
        return

    text_val = message.text.strip()
    if not text_val.isdigit():
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('please enter a valid whole number of credits.')}\n{DIV}")
        return

    credits = int(text_val)
    min_credits = int(get_setting("min_buy_credits", "10"))
    if credits < min_credits:
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('minimum is')} {C(str(min_credits))} {sc('credits.')}\n{DIV}")
        return

    rate_inr = float(get_setting("rate_inr", "4"))
    rate_credits = float(get_setting("rate_credits", "10"))
    inr_amount = round(credits * rate_inr / rate_credits, 2)
    inr_str = f"{inr_amount:.2f}".rstrip("0").rstrip(".") if "." in f"{inr_amount:.2f}" else f"{inr_amount:.2f}"

    clear_state(user_id)
    deposit_id = create_deposit(user_id, inr_str, credits)

    upi_id = get_setting("admin_upi_id", "8707210511@fam")
    payee_name = get_setting("upi_payee_name", "Credits Bot")
    currency = get_setting("currency_name", "credits")
    caption = txt_payment_details(credits, inr_str, upi_id, currency)
    qr = generate_upi_qr(upi_id, payee_name, inr_str)

    if qr:
        safe_send_photo(message.chat.id, qr, caption=caption, reply_markup=buy_payment_kb(deposit_id))
    else:
        safe_send(message.chat.id, caption, reply_markup=buy_payment_kb(deposit_id))


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_paid_"))
@guarded_callback
def cb_buy_paid(call: types.CallbackQuery):
    deposit_id = int(call.data.split("_")[-1])
    dep = get_deposit(deposit_id)
    if not dep or dep["user_id"] != call.from_user.id or dep["status"] != "awaiting_payment":
        bot.answer_callback_query(call.id, sc("this request is no longer valid."), show_alert=True)
        return
    set_deposit_status(deposit_id, "awaiting_utr")
    set_state(call.from_user.id, "awaiting_utr", {"deposit_id": deposit_id})
    bot.answer_callback_query(call.id)
    safe_send(call.message.chat.id, txt_awaiting_utr(), reply_markup=buy_awaiting_utr_kb(deposit_id))


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_cancel_"))
@guarded_callback
def cb_buy_cancel(call: types.CallbackQuery):
    deposit_id = int(call.data.split("_")[-1])
    dep = get_deposit(deposit_id)
    if not dep or dep["user_id"] != call.from_user.id or dep["status"] in ("approved", "rejected", "cancelled"):
        bot.answer_callback_query(call.id, sc("this request is no longer valid."), show_alert=True)
        return
    set_deposit_status(deposit_id, "cancelled")
    clear_state(call.from_user.id)
    bot.answer_callback_query(call.id)
    try:
        cap_plain, cap_entities = render(txt_deposit_cancelled())
        bot.edit_message_caption(cap_plain, call.message.chat.id, call.message.message_id, caption_entities=cap_entities)
    except Exception:
        safe_send(call.message.chat.id, txt_deposit_cancelled())
    send_dashboard(call.message.chat.id, call.from_user.id)


@bot.message_handler(func=lambda m: get_state(m.from_user.id)["state"] == "awaiting_utr", content_types=["text"])
@guarded_message
def handle_awaiting_utr(message: types.Message):
    user_id = message.from_user.id
    state = get_state(user_id)
    deposit_id = state["data"].get("deposit_id")
    dep = get_deposit(deposit_id) if deposit_id else None
    if not dep or dep["user_id"] != user_id or dep["status"] != "awaiting_utr":
        clear_state(user_id)
        return

    utr = message.text.strip()
    if len(utr) < 4:
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('please send a valid transaction id.')}\n{DIV}")
        return

    set_deposit_utr(deposit_id, utr)
    set_deposit_status(deposit_id, "pending")
    clear_state(user_id)
    safe_send(message.chat.id, txt_deposit_pending())

    dep = get_deposit(deposit_id)
    user = get_user(user_id)
    for admin_id in ADMIN_IDS:
        safe_send(admin_id, txt_admin_new_deposit(dep, user), reply_markup=dep_action_kb(deposit_id))


@bot.callback_query_handler(func=lambda c: c.data.startswith("dep_approve_"))
@guarded_callback
def cb_dep_approve(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    deposit_id = int(call.data.split("_")[-1])
    dep = get_deposit(deposit_id)
    if not dep or dep["status"] != "pending":
        bot.answer_callback_query(call.id, sc("already handled."), show_alert=True)
        return

    add_balance(dep["user_id"], dep["credits"])
    set_deposit_status(deposit_id, "approved")
    currency = get_setting("currency_name", "credits")
    bot.answer_callback_query(call.id, sc("approved."))
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    safe_send(dep["user_id"], txt_deposit_approved(dep["credits"], currency))


@bot.callback_query_handler(func=lambda c: c.data.startswith("dep_reject_"))
@guarded_callback
def cb_dep_reject(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    deposit_id = int(call.data.split("_")[-1])
    dep = get_deposit(deposit_id)
    if not dep or dep["status"] != "pending":
        bot.answer_callback_query(call.id, sc("already handled."), show_alert=True)
        return

    set_deposit_status(deposit_id, "rejected")
    bot.answer_callback_query(call.id, sc("rejected."))
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    safe_send(dep["user_id"], txt_deposit_rejected())


# ════════════════════════════════════════════════
#                   REFER & EARN
# ════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data == "menu_refer")
@guarded_callback
def cb_menu_refer(call: types.CallbackQuery):
    user = _require_active_user(call)
    message = _callback_message(call)
    if not user or message is None:
        return
    reward = get_setting("referral_reward_credits", "1")
    currency = get_setting("currency_name", "credits")
    invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user['user_id']}"
    bot.answer_callback_query(call.id)
    safe_edit(message.chat.id, message.message_id, txt_refer(user, reward, currency, invite_link), reply_markup=refer_kb(user["user_id"]))


# ════════════════════════════════════════════════
#                   JOIN UPDATES
# ════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: c.data == "menu_joinupdates")
@guarded_callback
def cb_menu_joinupdates(call: types.CallbackQuery):
    if not _require_active_user(call):
        return
    message = _callback_message(call)
    if message is None:
        return
    bot.answer_callback_query(call.id)
    safe_edit(message.chat.id, message.message_id, txt_joinupdates(), reply_markup=joinupdates_kb())


# ════════════════════════════════════════════════
#                   ADMIN PANEL
# ════════════════════════════════════════════════

@bot.message_handler(commands=["admin"])
@guarded_message
def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    clear_state(message.from_user.id)
    safe_send(message.chat.id, txt_admin_menu(), reply_markup=admin_menu_kb())


@bot.callback_query_handler(func=lambda c: c.data == "admin_back")
@guarded_callback
def cb_admin_back(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    clear_state(call.from_user.id)
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_menu(), reply_markup=admin_menu_kb())


@bot.callback_query_handler(func=lambda c: c.data == "admin_credits_menu")
@guarded_callback
def cb_admin_credits_menu(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_menu(), reply_markup=admin_credits_menu_kb())


# ── simple text-input settings: upi / rate / gift price / ref reward ────

_ADMIN_SIMPLE_PROMPTS = {
    "admin_set_upi": ("admin_awaiting_upi", "send the new upi id:"),
    "admin_set_giftprice": ("admin_awaiting_giftprice", "send the new gift card price, in credits:"),
    "admin_set_refreward": ("admin_awaiting_refreward", "send the new referral reward, in credits:"),
    "admin_set_dashboard_gif": ("admin_awaiting_dashboard_gif", "send a gif, a direct gif URL, or the word 'remove' to clear it:"),
    "admin_set_dashboard_sticker": ("admin_awaiting_dashboard_sticker", "send the premium user-panel sticker file id:"),
    "admin_set_amazon_sticker": ("admin_awaiting_amazon_sticker", "send the amazon premium sticker file id:"),
}


@bot.callback_query_handler(func=lambda c: c.data in _ADMIN_SIMPLE_PROMPTS)
@guarded_callback
def cb_admin_simple_prompt(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    state, label = _ADMIN_SIMPLE_PROMPTS[call.data]
    set_state(call.from_user.id, state)
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_prompt(label), reply_markup=admin_back_kb())


@bot.callback_query_handler(func=lambda c: c.data == "admin_set_rate")
@guarded_callback
def cb_admin_set_rate(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_state(call.from_user.id, "admin_awaiting_rate")
    bot.answer_callback_query(call.id)
    safe_edit(
        call.message.chat.id, call.message.message_id,
        txt_admin_prompt("send: <rs> <credits> — e.g. 4 10 means 4 rs = 10 credits"),
        reply_markup=admin_back_kb(),
    )


@bot.callback_query_handler(func=lambda c: c.data == "admin_clear_dashboard_gif")
@guarded_callback
def cb_admin_clear_dashboard_gif(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_setting("dashboard_gif_file_id", "")
    bot.answer_callback_query(call.id, sc("dashboard gif removed."), show_alert=True)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_menu(), reply_markup=admin_menu_kb())


@bot.callback_query_handler(func=lambda c: c.data == "admin_clear_dashboard_sticker")
@guarded_callback
def cb_admin_clear_dashboard_sticker(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_setting("dashboard_sticker_file_id", "")
    bot.answer_callback_query(call.id, sc("premium user sticker removed."), show_alert=True)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_menu(), reply_markup=admin_menu_kb())


@bot.callback_query_handler(func=lambda c: c.data == "admin_clear_amazon_sticker")
@guarded_callback
def cb_admin_clear_amazon_sticker(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_setting("amazon_premium_sticker_file_id", "")
    bot.answer_callback_query(call.id, sc("amazon premium sticker removed."), show_alert=True)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_menu(), reply_markup=admin_menu_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_upi", content_types=["text"])
@guarded_message
def handle_admin_set_upi(message: types.Message):
    clear_state(message.from_user.id)
    upi = message.text.strip()
    set_setting("admin_upi_id", upi)
    safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('upi id updated to')} {C(esc(upi))}.\n{DIV}", reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_giftprice", content_types=["text"])
@guarded_message
def handle_admin_set_giftprice(message: types.Message):
    clear_state(message.from_user.id)
    val = message.text.strip()
    if not val.isdigit():
        safe_send(message.chat.id, txt_admin_only_number(), reply_markup=admin_back_kb())
        return
    set_setting("gift_card_cost_credits", val)
    safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('gift card price updated to')} {C(val)}.\n{DIV}", reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_refreward", content_types=["text"])
@guarded_message
def handle_admin_set_refreward(message: types.Message):
    clear_state(message.from_user.id)
    val = message.text.strip()
    if not val.isdigit():
        safe_send(message.chat.id, txt_admin_only_number(), reply_markup=admin_back_kb())
        return
    set_setting("referral_reward_credits", val)
    safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('referral reward updated to')} {C(val)}.\n{DIV}", reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_rate", content_types=["text"])
@guarded_message
def handle_admin_set_rate(message: types.Message):
    clear_state(message.from_user.id)
    parts = message.text.split()
    if len(parts) != 2 or not all(p.replace(".", "", 1).isdigit() for p in parts):
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('send it like: 4 10')}\n{DIV}", reply_markup=admin_back_kb())
        return
    rate_inr, rate_credits = parts
    set_setting("rate_inr", rate_inr)
    set_setting("rate_credits", rate_credits)
    safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('rate updated to')} {C(f'{rate_inr} rs = {rate_credits} credits')}.\n{DIV}", reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_dashboard_gif", content_types=["text", "animation"])
@guarded_message
def handle_admin_dashboard_gif(message: types.Message):
    clear_state(message.from_user.id)
    if message.content_type == "animation" and message.animation:
        set_setting("dashboard_gif_file_id", message.animation.file_id)
        safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('dashboard gif updated.')}\n{DIV}", reply_markup=admin_back_kb())
        return

    txt = (message.text or "").strip()
    if txt.lower() in ("remove", "clear"):
        set_setting("dashboard_gif_file_id", "")
        safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('dashboard gif removed.')}\n{DIV}", reply_markup=admin_back_kb())
        return
    if txt:
        # accept either a pasted https URL or a raw telegram file_id
        set_setting("dashboard_gif_file_id", txt)
        safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('dashboard gif updated.')}\n{DIV}", reply_markup=admin_back_kb())
        return

    safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('send a gif, a direct URL, or the word')} {C('remove')}.\n{DIV}", reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_dashboard_sticker", content_types=["sticker", "text"])
@guarded_message
def handle_admin_dashboard_sticker(message: types.Message):
    clear_state(message.from_user.id)
    value = message.sticker.file_id if getattr(message, "sticker", None) else message.text.strip()
    if not value:
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('send a valid sticker file id.')}\n{DIV}", reply_markup=admin_back_kb())
        return
    set_setting("dashboard_sticker_file_id", value)
    safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('premium user sticker updated.')}\n{DIV}", reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_amazon_sticker", content_types=["sticker", "text"])
@guarded_message
def handle_admin_amazon_sticker(message: types.Message):
    clear_state(message.from_user.id)
    value = message.sticker.file_id if getattr(message, "sticker", None) else message.text.strip()
    if not value:
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('send a valid amazon premium sticker file id.')}\n{DIV}", reply_markup=admin_back_kb())
        return
    set_setting("amazon_premium_sticker_file_id", value)
    safe_send(message.chat.id, f"{DIV}\n{ce('verify')} {sc('amazon premium sticker updated.')}\n{DIV}", reply_markup=admin_back_kb())


# ── gift codes bulk add ──────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "admin_addgiftcodes")
@guarded_callback
def cb_admin_addgiftcodes(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_state(call.from_user.id, "admin_awaiting_giftcodes")
    bot.answer_callback_query(call.id)
    safe_edit(
        call.message.chat.id, call.message.message_id,
        txt_admin_prompt(f"send up to {MAX_GIFT_CODES_PER_BATCH} gift codes, comma separated, e.g:\nAZZZZzzZ,JNJWNJNJ,jnnjsjjidi"),
        reply_markup=admin_back_kb(),
    )


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_giftcodes", content_types=["text"])
@guarded_message
def handle_admin_addgiftcodes(message: types.Message):
    clear_state(message.from_user.id)
    codes = [c.strip() for c in message.text.split(",") if c.strip()]
    if not codes:
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('no codes found. send them comma separated.')}\n{DIV}", reply_markup=admin_back_kb())
        return
    if len(codes) > MAX_GIFT_CODES_PER_BATCH:
        safe_send(
            message.chat.id,
            f"{DIV}\n{ce('cross')} {sc('send at most')} {C(str(MAX_GIFT_CODES_PER_BATCH))} {sc('codes at a time. split them into more messages.')}\n{DIV}",
            reply_markup=admin_back_kb(),
        )
        return
    added, skipped = add_gift_codes(codes)
    remaining = count_available_gift_codes()
    safe_send(message.chat.id, txt_admin_giftcodes_added(added, skipped, remaining), reply_markup=admin_back_kb())


# ── ban / unban ──────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "admin_ban")
@guarded_callback
def cb_admin_ban(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_state(call.from_user.id, "admin_awaiting_ban")
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_ban_prompt(), reply_markup=admin_back_kb())


@bot.callback_query_handler(func=lambda c: c.data == "admin_unban")
@guarded_callback
def cb_admin_unban(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_state(call.from_user.id, "admin_awaiting_unban")
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_unban_prompt(), reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] in ("admin_awaiting_ban", "admin_awaiting_unban"), content_types=["text"])
@guarded_message
def handle_admin_ban_unban(message: types.Message):
    state = get_state(message.from_user.id)["state"]
    clear_state(message.from_user.id)
    user = resolve_user(message.text.strip())
    if not user:
        safe_send(message.chat.id, txt_admin_user_not_found(), reply_markup=admin_back_kb())
        return
    ban_flag = state == "admin_awaiting_ban"
    set_banned(user["user_id"], ban_flag)
    safe_send(message.chat.id, txt_admin_banned(user, ban_flag), reply_markup=admin_back_kb())


# ── add / remove credits ─────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data in ("admin_addcredit", "admin_removecredit"))
@guarded_callback
def cb_admin_credit_prompt(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    action = "add" if call.data == "admin_addcredit" else "remove"
    set_state(call.from_user.id, f"admin_awaiting_{action}credit")
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_credit_prompt(action), reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] in ("admin_awaiting_addcredit", "admin_awaiting_removecredit"), content_types=["text"])
@guarded_message
def handle_admin_credit_change(message: types.Message):
    state = get_state(message.from_user.id)["state"]
    clear_state(message.from_user.id)
    parts = message.text.strip().rsplit(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('send: <username or user id> <amount>')}\n{DIV}", reply_markup=admin_back_kb())
        return
    identifier, amount_str = parts
    amount = int(amount_str)
    user = resolve_user(identifier)
    if not user:
        safe_send(message.chat.id, txt_admin_user_not_found(), reply_markup=admin_back_kb())
        return
    delta = amount if state == "admin_awaiting_addcredit" else -amount
    new_balance = admin_adjust_balance(user["user_id"], delta)
    currency = get_setting("currency_name", "credits")
    safe_send(message.chat.id, txt_admin_credit_updated(user, delta, new_balance, currency), reply_markup=admin_back_kb())
    try:
        if delta > 0:
            safe_send(user["user_id"], f"{DIV}\n{ce('credit')} {C(str(delta) + ' ' + currency)} {sc('has been added to your balance by the admin.')}\n{DIV}")
    except Exception:
        pass


# ── pending queues ────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "admin_pending_claims")
@guarded_callback
def cb_admin_pending_claims(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    claims = list_pending_gift_claims()
    bot.answer_callback_query(call.id)
    if not claims:
        safe_edit(call.message.chat.id, call.message.message_id, f"{DIV}\n{sc('no pending gift claims.')}\n{DIV}", reply_markup=admin_back_kb())
        return
    safe_edit(call.message.chat.id, call.message.message_id, f"{DIV}\n{C(str(len(claims)))} {sc('pending gift claim(s) below:')}\n{DIV}", reply_markup=admin_back_kb())
    for claim in claims:
        user = get_user(claim["user_id"]) or {"user_id": claim["user_id"], "username": ""}
        safe_send(call.message.chat.id, txt_admin_new_gift_claim(claim, user), reply_markup=gift_action_kb(claim["claim_id"]))


@bot.callback_query_handler(func=lambda c: c.data == "admin_pending_deposits")
@guarded_callback
def cb_admin_pending_deposits(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    deps = list_pending_deposits()
    bot.answer_callback_query(call.id)
    if not deps:
        safe_edit(call.message.chat.id, call.message.message_id, f"{DIV}\n{sc('no pending payments.')}\n{DIV}", reply_markup=admin_back_kb())
        return
    safe_edit(call.message.chat.id, call.message.message_id, f"{DIV}\n{C(str(len(deps)))} {sc('pending payment(s) below:')}\n{DIV}", reply_markup=admin_back_kb())
    for dep in deps:
        user = get_user(dep["user_id"]) or {"user_id": dep["user_id"], "username": ""}
        safe_send(call.message.chat.id, txt_admin_new_deposit(dep, user), reply_markup=dep_action_kb(dep["deposit_id"]))


# ── stats ─────────────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
@guarded_callback
def cb_admin_stats(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    currency = get_setting("currency_name", "credits")
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_stats(stats_summary(), currency), reply_markup=admin_back_kb())


# ── broadcast ─────────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "admin_broadcast")
@guarded_callback
def cb_admin_broadcast(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_state(call.from_user.id, "admin_awaiting_broadcast")
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_broadcast_prompt(), reply_markup=admin_back_kb())


@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_broadcast")
@guarded_message
def handle_admin_broadcast(message: types.Message):
    clear_state(message.from_user.id)
    sent, failed = 0, 0
    for uid in all_user_ids():
        try:
            bot.copy_message(uid, message.chat.id, message.message_id)
            sent += 1
        except Exception:
            failed += 1
        time.sleep(0.05)
    safe_send(message.chat.id, txt_admin_broadcast_done(sent, failed), reply_markup=admin_back_kb())


# ── backup / restore ──────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "admin_backup")
@guarded_callback
def cb_admin_backup(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    dest = f"/tmp/backup_{int(time.time())}.db"
    try:
        backup_db(dest)
        with open(dest, "rb") as f:
            bot.send_document(call.message.chat.id, f, caption="database backup")
    except Exception as e:
        safe_send(call.message.chat.id, f"{DIV}\n{ce('cross')} {sc('backup failed')}: {C(esc(str(e)))}\n{DIV}", reply_markup=admin_back_kb())
    finally:
        if os.path.exists(dest):
            os.remove(dest)


@bot.callback_query_handler(func=lambda c: c.data == "admin_restore")
@guarded_callback
def cb_admin_restore(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id)
        return
    set_state(call.from_user.id, "admin_awaiting_restore_file")
    bot.answer_callback_query(call.id)
    safe_edit(call.message.chat.id, call.message.message_id, txt_admin_restore_prompt(), reply_markup=admin_back_kb())


@bot.message_handler(
    content_types=["document"],
    func=lambda m: is_admin(m.from_user.id) and get_state(m.from_user.id)["state"] == "admin_awaiting_restore_file",
)
@guarded_message
def handle_admin_restore_file(message: types.Message):
    clear_state(message.from_user.id)
    tmp_path = f"/tmp/restore_{int(time.time())}.db"
    safety_path = f"/tmp/pre_restore_safety_{int(time.time())}.db"
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        with open(tmp_path, "wb") as f:
            f.write(downloaded)

        if not _is_valid_sqlite_db(tmp_path):
            safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('restore failed — not a valid database. nothing was changed.')}\n{DIV}", reply_markup=admin_back_kb())
            return

        if os.path.exists(DB_PATH):
            backup_db(safety_path)
            try:
                with open(safety_path, "rb") as f:
                    bot.send_document(message.chat.id, f, caption="safety backup (before this restore)")
            except Exception:
                pass

        restore_db(tmp_path)
        safe_send(message.chat.id, txt_admin_restore_done(), reply_markup=admin_back_kb())
    except Exception as e:
        safe_send(message.chat.id, f"{DIV}\n{ce('cross')} {sc('restore failed')}: {C(esc(str(e)))}\n{DIV}", reply_markup=admin_back_kb())
    finally:
        for p in (tmp_path, safety_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ════════════════════════════════════════════════
#                 DEFAULT FALLBACK
# ════════════════════════════════════════════════

@bot.message_handler(func=lambda m: True, content_types=["text"])
@guarded_message
def handle_fallback(message: types.Message):
    user_id = message.from_user.id
    if get_state(user_id)["state"] is not None:
        return
    user = get_user(user_id)
    if not user:
        missing = missing_channels(user_id)
        send_force_join(message.chat.id, missing)
        return
    if user["banned"]:
        safe_send(message.chat.id, f"{ce('blocked')} {sc('you are')} {B(sc('banned'))}.")
        return
    missing = missing_channels(user_id)
    if missing:
        send_force_join(message.chat.id, missing)
        return
    send_dashboard(message.chat.id, user_id)


# ════════════════════════════════════════════════
#                       RUN
# ════════════════════════════════════════════════

def run_bot_forever():
    backoff = 5
    max_backoff = 300
    while True:
        try:
            try:
                bot.remove_webhook()
            except Exception as e:
                log.warning(f"remove_webhook failed (continuing anyway): {e}")
            log.info("gift/credit bot starting polling...")
            bot.infinity_polling(timeout=60, long_polling_timeout=30, allowed_updates=[])
            log.warning("infinity_polling returned unexpectedly — restarting.")
            backoff = 5
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
            log.error(f"network error during polling: {e}. retrying in {backoff}s...")
        except Exception as e:
            log.error(f"unexpected error during polling: {e}. retrying in {backoff}s...")
        time.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


if __name__ == "__main__":
    if not _HAS_QR:
        log.warning("qrcode package not installed — UPI QR images will be skipped. run: pip install qrcode[pil]")
    lock_fd = acquire_single_instance_lock()
    if lock_fd is None:
        log.error("Another bot instance is already running for this token. Exiting to prevent Telegram polling conflicts.")
        raise SystemExit(1)
    try:
        init_db()
        setup_bot_menu()
        log.info("gift/credit bot starting...")
        run_bot_forever()
    finally:
        try:
            os.close(lock_fd)
            if os.path.exists(LOCK_PATH):
                os.remove(LOCK_PATH)
        except Exception:
            pass

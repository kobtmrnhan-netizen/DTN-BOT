# ============================================================
# NGỌC MỸ BOT - PURE PYTHON
# PHẦN 1/15
# KHÔNG AI
# ============================================================

import asyncio
import html
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

OWNER_USERNAME = "DTN_207"
OWNER_DISPLAY = "@DTN_207"

VERSION = "3.0.0"

DATABASE = "bot.db"

API_URL = (
    "https://api.telegram.org/bot"
    + BOT_TOKEN
    + "/"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )
)

logger = logging.getLogger("NGOC_MY")


# ============================================================
# GLOBAL STATE
# ============================================================

START_TIME = time.time()

BOT_RUNNING = True

SPAM_TRACKER = defaultdict(deque)

JOIN_TRACKER = defaultdict(deque)

AFK_CACHE = {}

RUNTIME_STATS = {
    "messages": 0,
    "groups": 0,
    "private": 0,
    "deleted": 0,
    "filter_hits": 0,
    "afk_notifications": 0,
    "joins": 0,
}


GROUP_TYPES = {
    "group",
    "supergroup",
}

PRIVATE_TYPE = "private"

PRIVATE_GROUP_MESSAGE = (
    "sao ngươi lại ngu thế "
    "lệnh này chỉ xài cho nhóm"
)

OWNER_ONLY_MESSAGE = (
    "❌ Lệnh này chỉ dành cho Owner."
)

ADMIN_ONLY_MESSAGE = (
    "❌ Lệnh này chỉ dành cho quản trị viên."
)


# ============================================================
# DATABASE
# ============================================================

DB_LOCK = asyncio.Lock()


def db_connect():
    conn = sqlite3.connect(
        DATABASE,
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    return conn


def db_execute(
    query,
    params=(),
    fetch=False,
    fetchone=False
):
    conn = db_connect()

    try:
        cursor = conn.cursor()

        cursor.execute(
            query,
            params
        )

        if fetch:
            result = cursor.fetchall()

        elif fetchone:
            result = cursor.fetchone()

        else:
            result = None

        conn.commit()

        return result

    finally:
        conn.close()


async def adb_execute(
    query,
    params=(),
    fetch=False,
    fetchone=False
):
    async with DB_LOCK:
        return await asyncio.to_thread(
            db_execute,
            query,
            params,
            fetch,
            fetchone
        )


def init_db():

    conn = db_connect()

    try:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS levels (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                message_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                chat_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY(chat_id, key)
            );

            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                response TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS afk (
                user_id INTEGER PRIMARY KEY,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checkins (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                checkin_date TEXT NOT NULL,
                streak INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(
                    chat_id,
                    user_id,
                    checkin_date
                )
            );

            CREATE TABLE IF NOT EXISTS bot_bans (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS known_profiles (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                display_name TEXT,
                first_seen TEXT NOT NULL,
                PRIMARY KEY(
                    chat_id,
                    user_id
                )
            );
            """
        )

        conn.commit()

    finally:
        conn.close()


# ============================================================
# LEVEL SYSTEM
# ============================================================

LEVEL_REQUIREMENTS = {
    1: 0,
    2: 100,
    3: 300,
    4: 500,
    5: 700,
    6: 900,
    7: 1100,
    8: 1300,
    9: 1500,
    10: 2000,
}


def calculate_level(message_count):

    current_level = 1

    for level, required in LEVEL_REQUIREMENTS.items():

        if message_count >= required:
            current_level = level

    return current_level


def get_level_data(
    chat_id,
    user_id
):

    conn = db_connect()

    row = conn.execute(
        """
        SELECT
            chat_id,
            user_id,
            username,
            first_name,
            message_count,
            level,
            updated_at
        FROM levels
        WHERE chat_id = ?
        AND user_id = ?
        """,
        (
            chat_id,
            user_id
        )
    ).fetchone()

    conn.close()

    return row


def add_level_message(
    chat_id,
    user_id,
    username,
    first_name
):

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = db_connect()

    row = conn.execute(
        """
        SELECT
            message_count,
            level
        FROM levels
        WHERE chat_id = ?
        AND user_id = ?
        """,
        (
            chat_id,
            user_id
        )
    ).fetchone()

    if row:

        message_count = row[0] + 1
        old_level = row[1]

    else:

        message_count = 1
        old_level = 1

    new_level = calculate_level(
        message_count
    )

    conn.execute(
        """
        INSERT INTO levels
        (
            chat_id,
            user_id,
            username,
            first_name,
            message_count,
            level,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            username =
                excluded.username,

            first_name =
                excluded.first_name,

            message_count =
                excluded.message_count,

            level =
                excluded.level,

            updated_at =
                excluded.updated_at
        """,
        (
            chat_id,
            user_id,
            username,
            first_name,
            message_count,
            new_level,
            now
        )
    )

    conn.commit()
    conn.close()

    return (
        message_count,
        old_level,
        new_level
    )


# ============================================================
# TELEGRAM API
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

def telegram_request(
    method,
    data=None,
    timeout=30
):

    if not BOT_TOKEN:

        raise RuntimeError(
            "Bạn chưa cấu hình BOT_TOKEN."
        )

    data = data or {}

    encoded = urlencode(
        {
            key: str(value)
            for key, value in data.items()
            if value is not None
        }
    ).encode()

    request = Request(
        API_URL + method,
        data=encoded,
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        },
        method="POST"
    )

    try:

        with urlopen(
            request,
            timeout=timeout
        ) as response:

            raw = response.read().decode(
                "utf-8"
            )

            result = json.loads(raw)

            if not result.get("ok"):

                logger.warning(
                    "Telegram API error %s: %s",
                    method,
                    result
                )

            return result

    except Exception as e:

        logger.error(
            "Telegram request failed [%s]: %s",
            method,
            e
        )

        return {
            "ok": False,
            "description": str(e)
        }


async def api(
    method,
    data=None,
    timeout=30
):

    return await asyncio.to_thread(
        telegram_request,
        method,
        data,
        timeout
    )


# ============================================================
# TELEGRAM HELPERS
# ============================================================

async def send_message(
    chat_id,
    text,
    reply_to=None,
    parse_mode="HTML"
):

    data = {
        "chat_id": chat_id,
        "text": text,
    }

    if parse_mode:
        data["parse_mode"] = parse_mode

    if reply_to:

        data[
            "reply_to_message_id"
        ] = reply_to

    return await api(
        "sendMessage",
        data
    )


async def delete_message(
    chat_id,
    message_id
):

    return await api(
        "deleteMessage",
        {
            "chat_id": chat_id,
            "message_id": message_id
        }
    )


async def edit_message(
    chat_id,
    message_id,
    text
):

    return await api(
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML"
        }
    )


async def pin_message(
    chat_id,
    message_id,
    disable_notification=False
):

    return await api(
        "pinChatMessage",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification":
                disable_notification
        }
    )


async def unpin_message(
    chat_id,
    message_id
):

    return await api(
        "unpinChatMessage",
        {
            "chat_id": chat_id,
            "message_id": message_id
        }
    )


# ============================================================
# USER HELPERS
# ============================================================

def user_name(user):

    if not user:
        return "Unknown"

    return (
        user.get("first_name")
        or user.get("username")
        or str(
            user.get(
                "id",
                "Unknown"
            )
        )
    )


def user_full_name(user):

    if not user:
        return "Unknown"

    first = user.get(
        "first_name",
        ""
    )

    last = user.get(
        "last_name",
        ""
    )

    return (
        f"{first} {last}"
    ).strip() or "Unknown"


def mention_user(user):

    if not user:
        return "Unknown"

    name = html.escape(
        user_full_name(user)
    )

    user_id = user.get("id")

    return (
        f'<a href="tg://user?id={user_id}">'
        f'{name}'
        f'</a>'
    )


async def save_user(user):

    if not user:
        return

    now = datetime.now(
        timezone.utc
    ).isoformat()

    await adb_execute(
        """
        INSERT INTO users (
            user_id,
            username,
            first_name,
            last_name,
            first_seen,
            last_seen,
            message_count
        )
        VALUES (?, ?, ?, ?, ?, ?, 1)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username =
                excluded.username,

            first_name =
                excluded.first_name,

            last_name =
                excluded.last_name,

            last_seen =
                excluded.last_seen,

            message_count =
                users.message_count + 1
        """,
        (
            user.get("id"),
            user.get("username"),
            user.get("first_name"),
            user.get("last_name"),
            now,
            now
        )
    )


# ============================================================
# CHAT HELPERS
# ============================================================

def is_group(message):

    chat = (
        message or {}
    ).get(
        "chat",
        {}
    )

    return (
        chat.get("type")
        in GROUP_TYPES
    )


def is_private(message):

    chat = (
        message or {}
    ).get(
        "chat",
        {}
    )

    return (
        chat.get("type")
        == PRIVATE_TYPE
    )


def get_chat_id(message):

    return (
        message
        .get("chat", {})
        .get("id")
    )


def get_user(message):

    return (
        message or {}
    ).get(
        "from"
    )


def get_user_id(message):

    user = get_user(message)

    if not user:
        return None

    return user.get("id")


def get_message_id(message):

    return (
        message or {}
    ).get(
        "message_id"
    )


def get_text(message):

    return (
        message or {}
    ).get(
        "text",
        ""
    ) or ""


def parse_command(message):

    text = get_text(
        message
    ).strip()

    if not text.startswith("/"):
        return None, ""

    first, *rest = text.split(
        maxsplit=1
    )

    command = first[1:]

    if "@" in command:

        command = command.split(
            "@",
            1
        )[0]

    command = command.lower()

    args = (
        rest[0]
        if rest
        else ""
    ).strip()

    return command, args

# ============================================================
# GROUP / ADMIN HELPERS
# ============================================================

async def get_chat_member(
    chat_id,
    user_id
):

    result = await api(
        "getChatMember",
        {
            "chat_id": chat_id,
            "user_id": user_id
        }
    )

    if not result.get("ok"):
        return None

    return result.get(
        "result"
    )


async def is_admin(
    chat_id,
    user_id
):

    member = await get_chat_member(
        chat_id,
        user_id
    )

    if not member:
        return False

    return member.get(
        "status"
    ) in {
        "administrator",
        "creator"
    }


async def is_owner(
    user_id
):

    if not user_id:
        return False

    # Cho phép Owner theo ID nếu đã cấu hình
    owner_id = os.getenv(
        "OWNER_ID",
        ""
    ).strip()

    if owner_id:

        try:

            if int(owner_id) == int(
                user_id
            ):
                return True

        except ValueError:
            pass

    return False


async def require_group(
    message
):

    if not is_group(message):

        await send_message(
            get_chat_id(message),
            PRIVATE_GROUP_MESSAGE,
            get_message_id(message)
        )

        return False

    return True


async def require_admin(
    message
):

    if not await require_group(
        message
    ):
        return False

    user_id = get_user_id(
        message
    )

    if await is_owner(
        user_id
    ):
        return True

    if not await is_admin(
        get_chat_id(message),
        user_id
    ):

        await send_message(
            get_chat_id(message),
            ADMIN_ONLY_MESSAGE,
            get_message_id(message)
        )

        return False

    return True


# ============================================================
# BOT PERMISSIONS
# ============================================================

async def get_me():

    result = await api(
        "getMe"
    )

    if not result.get("ok"):
        return {}

    return result.get(
        "result",
        {}
    )


async def get_bot_id():

    me = await get_me()

    return me.get(
        "id"
    )


async def can_delete_messages(
    chat_id
):

    bot_id = await get_bot_id()

    if not bot_id:
        return False

    member = await get_chat_member(
        chat_id,
        bot_id
    )

    if not member:
        return False

    if member.get(
        "status"
    ) == "creator":
        return True

    if member.get(
        "status"
    ) != "administrator":
        return False

    return bool(
        member.get(
            "can_delete_messages",
            False
        )
    )


async def can_restrict_members(
    chat_id
):

    bot_id = await get_bot_id()

    if not bot_id:
        return False

    member = await get_chat_member(
        chat_id,
        bot_id
    )

    if not member:
        return False

    if member.get(
        "status"
    ) == "creator":
        return True

    return (
        member.get("status")
        == "administrator"
        and member.get(
            "can_restrict_members",
            False
        )
    )


# ============================================================
# SETTINGS
# ============================================================

async def get_setting(
    chat_id,
    key,
    default=None
):

    row = await adb_execute(
        """
        SELECT value
        FROM settings
        WHERE chat_id = ?
        AND key = ?
        """,
        (
            chat_id,
            key
        ),
        fetchone=True
    )

    if not row:
        return default

    return row["value"]


async def set_setting(
    chat_id,
    key,
    value
):

    await adb_execute(
        """
        INSERT INTO settings(
            chat_id,
            key,
            value
        )
        VALUES (?, ?, ?)

        ON CONFLICT(chat_id, key)
        DO UPDATE SET
            value =
                excluded.value
        """,
        (
            chat_id,
            key,
            str(value)
        )
    )


async def setting_enabled(
    chat_id,
    key,
    default=False
):

    value = await get_setting(
        chat_id,
        key,
        "1" if default else "0"
    )

    return str(value).lower() in {
        "1",
        "true",
        "yes",
        "on"
    }


# ============================================================
# HELP TEXT
# ============================================================

HELP_TEXT = """
<b>🌸 NGỌC MỸ — TRỢ GIÚP</b>

<b>👮 QUẢN TRỊ NHÓM</b>

/ban — Ban thành viên
/unban — Gỡ ban
/mute — Tắt chat thành viên
/unmute — Gỡ mute
/warn — Cảnh cáo thành viên
/unwarn — Xóa cảnh cáo
/kick — Đuổi thành viên
/promote — Thăng quản trị
/demote — Hạ quản trị
/pin — Ghim tin nhắn
/unpin — Bỏ ghim

<b>🛡️ BẢO VỆ</b>

/antispam — Chống spam
/antilink — Chống link
/antibuff — Chống buff thành viên
/antifake — Chống tài khoản giả mạo

<b>🔧 TIỆN ÍCH</b>

/afk — Bật trạng thái AFK
/filter — Tạo bộ lọc
/filters — Xem bộ lọc
/stopfilter — Xóa bộ lọc
/diemdanh — Điểm danh hằng ngày

<b>🎮 TRÒ CHƠI</b>

/noichu — Nối chữ Việt Nam

<b>📈 LEVEL</b>

/level — Xem hệ thống level
/levelyou — Xem level của bạn
/levelbxh — Bảng xếp hạng level
/leveldanhsach — Điều kiện lên level
/levelnhiemvu — Nhiệm vụ level

<b>❤️ THƠ</b>

/thodoi — Thơ đời
/thotinh — Thơ tình

<b>ℹ️ KHÁC</b>

/help — Hiển thị trợ giúp
/start — Mở menu Ngọc Mỹ

━━━━━━━━━━━━━━
👑 Owner: @DTN_207
"""


# ============================================================
# START MENU
# ============================================================

START_TEXT = """
<b>🌸 Xin chào, mình là Ngọc Mỹ!</b>

Bot quản lý nhóm, tiện ích,
level, điểm danh, trò chơi
và nhiều chức năng khác.

<b>Hãy chọn chức năng bên dưới.</b>
"""


def start_keyboard():

    return json.dumps(
        {
            "inline_keyboard": [
                [
                    {
                        "text": "📖 Hướng dẫn",
                        "callback_data": "help"
                    }
                ],
                [
                    {
                        "text": "🛠 Quản trị",
                        "callback_data":
                            "admin_menu"
                    },
                    {
                        "text": "🛡 Bảo vệ",
                        "callback_data":
                            "protect_menu"
                    }
                ],
                [
                    {
                        "text": "🎮 Trò chơi",
                        "callback_data":
                            "game_menu"
                    },
                    {
                        "text": "📈 Level",
                        "callback_data":
                            "level_menu"
                    }
                ],
                [
                    {
                        "text": "❤️ Thơ",
                        "callback_data":
                            "poem_menu"
                    }
                ]
            ]
        },
        ensure_ascii=False
    )


async def send_start_menu(
    message
):

    chat_id = get_chat_id(
        message
    )

    return await api(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": START_TEXT,
            "parse_mode": "HTML",
            "reply_markup":
                start_keyboard()
        }
    )


# ============================================================
# HELP COMMAND
# ============================================================

async def command_help(
    message
):

    # /help trong nhóm
    if is_group(message):

        await send_message(
            get_chat_id(message),
            "❌ /help chỉ sử dụng trong tin nhắn riêng với bot.",
            get_message_id(message)
        )

        return

    await send_message(
        get_chat_id(message),
        HELP_TEXT,
        get_message_id(message)
    )


async def command_start(
    message
):

    await send_start_menu(
        message
    )


# ============================================================
# OWNER / BASIC COMMANDS
# ============================================================

async def command_id(
    message
):

    user = get_user(
        message
    )

    if not user:
        return

    text = (
        f"🆔 <b>User ID:</b> "
        f"<code>{user.get('id')}</code>\n"
        f"👤 <b>Tên:</b> "
        f"{html.escape(user_full_name(user))}"
    )

    if user.get("username"):

        text += (
            "\n🔗 <b>Username:</b> "
            f"@{html.escape(user['username'])}"
        )

    await send_message(
        get_chat_id(message),
        text,
        get_message_id(message)
    )


async def command_ping(
    message
):

    started = time.perf_counter()

    result = await send_message(
        get_chat_id(message),
        "🏓 Đang kiểm tra...",
        get_message_id(message)
    )

    elapsed = (
        time.perf_counter()
        - started
    ) * 1000

    if result.get("ok"):

        sent = result[
            "result"
        ]

        await edit_message(
            get_chat_id(message),
            sent["message_id"],
            (
                "🏓 <b>Pong!</b>\n"
                f"⚡ {elapsed:.0f} ms"
            )
        )


async def command_stats(
    message
):

    if not await is_owner(
        get_user_id(message)
    ):

        await send_message(
            get_chat_id(message),
            OWNER_ONLY_MESSAGE,
            get_message_id(message)
        )

        return

    uptime = int(
        time.time()
        - START_TIME
    )

    hours = uptime // 3600
    minutes = (
        uptime % 3600
    ) // 60
    seconds = uptime % 60

    text = (
        "<b>📊 NGỌC MỸ STATS</b>\n\n"
        f"💬 Messages: "
        f"{RUNTIME_STATS['messages']}\n"
        f"👥 Groups: "
        f"{RUNTIME_STATS['groups']}\n"
        f"💬 Private: "
        f"{RUNTIME_STATS['private']}\n"
        f"🗑 Deleted: "
        f"{RUNTIME_STATS['deleted']}\n"
        f"🛡 Filter hits: "
        f"{RUNTIME_STATS['filter_hits']}\n"
        f"⏱ Uptime: "
        f"{hours}h {minutes}m {seconds}s"
    )

    await send_message(
        get_chat_id(message),
        text,
        get_message_id(message)
    )


# ============================================================
# SAFE TEXT HELPERS
# ============================================================

def normalize_text(text):

    return re.sub(
        r"\s+",
        " ",
        (text or "").strip().lower()
    )


def contains_link(text):

    if not text:
        return False

    patterns = [
        r"https?://",
        r"www\.",
        r"t\.me/",
        r"telegram\.me/",
        r"bit\.ly/",
        r"tinyurl\.com/"
    ]

    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in patterns
    )


def contains_mention(text):

    if not text:
        return False

    return bool(
        re.search(
            r"@[A-Za-z0-9_]{3,}",
            text
        )
    )


def clean_username(username):

    if not username:
        return ""

    return username.lstrip(
        "@"
    ).strip().lower()


# ============================================================
# MODERATION TARGET
# ============================================================

def get_target_user(
    message,
    args=""
):

    reply = (
        message or {}
    ).get(
        "reply_to_message"
    )

    if reply:

        target = reply.get(
            "from"
        )

        if target:
            return target

    args = (
        args or ""
    ).strip()

    if not args:
        return None

    token = args.split(
        maxsplit=1
    )[0]

    if token.startswith("@"):

        return {
            "username":
                clean_username(token)
        }

    if token.isdigit():

        return {
            "id": int(token)
        }

    return None


async def resolve_target_id(
    message,
    target
):

    if not target:
        return None

    if target.get("id"):

        return int(
            target["id"]
        )

    username = clean_username(
        target.get(
            "username",
            ""
        )
    )

    if not username:
        return None

    # Telegram Bot API không có
    # getUserByUsername trực tiếp.
    # Ưu tiên reply hoặc ID.
    return None

# ============================================================
# PHẦN 3/15 — MODERATION
# ============================================================

def tg_username(user):
    if not user:
        return "người dùng"
    if user.get("username"):
        return "@" + user["username"]
    name = user.get("first_name") or user.get("last_name") or "người dùng"
    return name


def mention_user(user):
    if not user:
        return "người dùng"

    name = (
        user.get("first_name")
        or user.get("last_name")
        or user.get("username")
        or "người dùng"
    )

    uid = user.get("id")
    return f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'


def get_reply_user(message):
    reply = message.get("reply_to_message")
    if reply:
        return reply.get("from")
    return None


def resolve_target(message, args):
    """
    Ưu tiên:
    1. Reply tin nhắn
    2. ID
    3. @username
    """

    reply_user = get_reply_user(message)
    if reply_user:
        return reply_user

    if not args:
        return None

    target = args[0].strip()

    # ID Telegram
    if target.isdigit():
        try:
            uid = int(target)
            return {
                "id": uid,
                "first_name": str(uid),
                "username": None
            }
        except Exception:
            return None

    # @username
    if target.startswith("@"):
        username = target[1:].lower()

        try:
            row = db_fetchone(
                "SELECT user_id, first_name, username "
                "FROM known_profiles WHERE lower(username)=?",
                (username,)
            )

            if row:
                return {
                    "id": row["user_id"],
                    "first_name": row["first_name"] or username,
                    "username": row["username"]
                }
        except Exception:
            pass

        # Telegram Bot API không cho bot tự lấy user theo username
        # nếu chưa từng biết user đó.
        return {
            "id": None,
            "first_name": username,
            "username": username
        }

    return None


def save_known_profile(user):
    if not user or not user.get("id"):
        return

    try:
        db_execute(
            """
            INSERT INTO known_profiles
            (user_id, first_name, username)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                first_name=excluded.first_name,
                username=excluded.username
            """,
            (
                user["id"],
                user.get("first_name"),
                user.get("username")
            )
        )
    except Exception:
        pass


def is_bot_user(user):
    return bool(user and user.get("is_bot"))


def is_self_target(user):
    if not user:
        return False

    try:
        me = tg_call("getMe", {})
        if me.get("ok"):
            return user.get("id") == me["result"].get("id")
    except Exception:
        pass

    return False


def can_target_member(chat_id, target_id):
    if not target_id:
        return False

    try:
        result = tg_call(
            "getChatMember",
            {
                "chat_id": chat_id,
                "user_id": target_id
            }
        )

        if not result.get("ok"):
            return False

        status = result["result"].get("status")

        # Không xử lý owner/admin bằng các lệnh member thường
        if status in ("creator", "administrator"):
            return False

        return status in ("member", "restricted")
    except Exception:
        return False


def target_id_from_args(message, args):
    target = resolve_target(message, args)

    if not target:
        return None

    return target.get("id")


def target_display(target):
    if not target:
        return "người dùng"

    if target.get("username"):
        return "@" + target["username"]

    return html.escape(
        target.get("first_name") or "người dùng"
    )


# ------------------------------------------------------------
# BAN
# ------------------------------------------------------------

def cmd_ban(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "❌ Hãy reply tin nhắn người cần ban hoặc dùng:\n"
            "/ban ID\n"
            "/ban @username"
        )

    uid = target["id"]

    if uid == message["from"]["id"]:
        return send_text(chat_id, "❌ Không thể tự ban chính mình.")

    if not can_target_member(chat_id, uid):
        return send_text(
            chat_id,
            "❌ Không thể ban người này."
        )

    result = tg_call(
        "banChatMember",
        {
            "chat_id": chat_id,
            "user_id": uid
        }
    )

    if result.get("ok"):
        send_text(
            chat_id,
            f"🔨 Đã ban {target_display(target)}.",
            parse_mode="HTML"
        )
    else:
        send_text(
            chat_id,
            "❌ Ban thất bại. Kiểm tra quyền admin của bot."
        )


# ------------------------------------------------------------
# UNBAN
# ------------------------------------------------------------

def cmd_unban(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "❌ Dùng /unban ID hoặc reply tin nhắn."
        )

    result = tg_call(
        "unbanChatMember",
        {
            "chat_id": chat_id,
            "user_id": target["id"],
            "only_if_banned": True
        }
    )

    if result.get("ok"):
        send_text(
            chat_id,
            f"✅ Đã unban {target_display(target)}.",
            parse_mode="HTML"
        )
    else:
        send_text(
            chat_id,
            "❌ Unban thất bại."
        )


# ------------------------------------------------------------
# KICK
# ------------------------------------------------------------

def cmd_kick(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "❌ Reply người cần kick hoặc dùng /kick ID."
        )

    uid = target["id"]

    if not can_target_member(chat_id, uid):
        return send_text(
            chat_id,
            "❌ Không thể kick người này."
        )

    # Kick = ban rồi unban
    result1 = tg_call(
        "banChatMember",
        {
            "chat_id": chat_id,
            "user_id": uid
        }
    )

    if not result1.get("ok"):
        return send_text(
            chat_id,
            "❌ Kick thất bại."
        )

    tg_call(
        "unbanChatMember",
        {
            "chat_id": chat_id,
            "user_id": uid,
            "only_if_banned": True
        }
    )

    send_text(
        chat_id,
        f"👢 Đã kick {target_display(target)}.",
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# MUTE
# ------------------------------------------------------------

def cmd_mute(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "❌ Reply người cần mute hoặc dùng /mute ID."
        )

    uid = target["id"]

    if not can_target_member(chat_id, uid):
        return send_text(
            chat_id,
            "❌ Không thể mute người này."
        )

    result = tg_call(
        "restrictChatMember",
        {
            "chat_id": chat_id,
            "user_id": uid,
            "permissions": {
                "can_send_messages": False,
                "can_send_audios": False,
                "can_send_documents": False,
                "can_send_photos": False,
                "can_send_videos": False,
                "can_send_video_notes": False,
                "can_send_voice_notes": False,
                "can_send_polls": False,
                "can_send_other_messages": False,
                "can_add_web_page_previews": False
            }
        }
    )

    if result.get("ok"):
        send_text(
            chat_id,
            f"🔇 Đã mute {target_display(target)}.",
            parse_mode="HTML"
        )
    else:
        send_text(
            chat_id,
            "❌ Mute thất bại. Bot cần quyền quản trị."
        )


# ------------------------------------------------------------
# UNMUTE
# ------------------------------------------------------------

def cmd_unmute(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "❌ Reply người cần unmute hoặc dùng /unmute ID."
        )

    uid = target["id"]

    result = tg_call(
        "restrictChatMember",
        {
            "chat_id": chat_id,
            "user_id": uid,
            "permissions": {
                "can_send_messages": True,
                "can_send_audios": True,
                "can_send_documents": True,
                "can_send_photos": True,
                "can_send_videos": True,
                "can_send_video_notes": True,
                "can_send_voice_notes": True,
                "can_send_polls": True,
                "can_send_other_messages": True,
                "can_add_web_page_previews": True
            }
        }
    )

    if result.get("ok"):
        send_text(
            chat_id,
            f"🔊 Đã unmute {target_display(target)}.",
            parse_mode="HTML"
        )
    else:
        send_text(
            chat_id,
            "❌ Unmute thất bại."
        )


# ------------------------------------------------------------
# WARN
# ------------------------------------------------------------

def get_warn_count(chat_id, user_id):
    row = db_fetchone(
        "SELECT count FROM warns WHERE chat_id=? AND user_id=?",
        (chat_id, user_id)
    )

    if not row:
        return 0

    return int(row["count"] or 0)


def set_warn_count(chat_id, user_id, count):
    db_execute(
        """
        INSERT INTO warns(chat_id,user_id,count)
        VALUES(?,?,?)
        ON CONFLICT(chat_id,user_id)
        DO UPDATE SET count=excluded.count
        """,
        (chat_id, user_id, count)
    )


def cmd_warn(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "⚠️ Dùng /warn bằng cách reply tin nhắn người cần cảnh cáo."
        )

    uid = target["id"]

    if not can_target_member(chat_id, uid):
        return send_text(
            chat_id,
            "❌ Không thể warn người này."
        )

    count = get_warn_count(chat_id, uid) + 1
    set_warn_count(chat_id, uid, count)

    if count >= 3:
        # Đủ 3 warn -> mute
        tg_call(
            "restrictChatMember",
            {
                "chat_id": chat_id,
                "user_id": uid,
                "permissions": {
                    "can_send_messages": False,
                    "can_send_audios": False,
                    "can_send_documents": False,
                    "can_send_photos": False,
                    "can_send_videos": False,
                    "can_send_video_notes": False,
                    "can_send_voice_notes": False,
                    "can_send_polls": False,
                    "can_send_other_messages": False,
                    "can_add_web_page_previews": False
                }
            }
        )

        send_text(
            chat_id,
            f"⚠️ {target_display(target)} đã nhận {count} cảnh cáo.\n"
            f"🔇 Đã tự động mute vì đủ 3 cảnh cáo.",
            parse_mode="HTML"
        )
        return

    send_text(
        chat_id,
        f"⚠️ {target_display(target)} nhận cảnh cáo.\n"
        f"📌 Warn: {count}/3",
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# UNWARN
# ------------------------------------------------------------

def cmd_unwarn(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "❌ Reply người cần unwarn."
        )

    uid = target["id"]

    count = max(0, get_warn_count(chat_id, uid) - 1)
    set_warn_count(chat_id, uid, count)

    send_text(
        chat_id,
        f"✅ Đã giảm warn cho {target_display(target)}.\n"
        f"📌 Warn hiện tại: {count}/3",
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# PROMOTE
# ------------------------------------------------------------

def cmd_promote(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "❌ Reply người cần promote."
        )

    result = tg_call(
        "promoteChatMember",
        {
            "chat_id": chat_id,
            "user_id": target["id"],
            "can_manage_chat": True,
            "can_delete_messages": True,
            "can_manage_video_chats": True,
            "can_restrict_members": True,
            "can_promote_members": False,
            "can_change_info": True,
            "can_invite_users": True,
            "can_pin_messages": True
        }
    )

    if result.get("ok"):
        send_text(
            chat_id,
            f"👑 Đã promote {target_display(target)}.",
            parse_mode="HTML"
        )
    else:
        send_text(
            chat_id,
            "❌ Promote thất bại."
        )


# ------------------------------------------------------------
# DEMOTE
# ------------------------------------------------------------

def cmd_demote(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    target = resolve_target(message, args)

    if not target or not target.get("id"):
        return send_text(
            chat_id,
            "❌ Reply admin cần hạ quyền."
        )

    result = tg_call(
        "promoteChatMember",
        {
            "chat_id": chat_id,
            "user_id": target["id"],
            "can_manage_chat": False,
            "can_delete_messages": False,
            "can_manage_video_chats": False,
            "can_restrict_members": False,
            "can_promote_members": False,
            "can_change_info": False,
            "can_invite_users": False,
            "can_pin_messages": False
        }
    )

    if result.get("ok"):
        send_text(
            chat_id,
            f"⬇️ Đã demote {target_display(target)}.",
            parse_mode="HTML"
        )
    else:
        send_text(
            chat_id,
            "❌ Demote thất bại."
        )


# ------------------------------------------------------------
# PIN
# ------------------------------------------------------------

def cmd_pin(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    reply = message.get("reply_to_message")

    if not reply:
        return send_text(
            chat_id,
            "📌 Hãy reply tin nhắn cần ghim rồi dùng /pin."
        )

    result = tg_call(
        "pinChatMessage",
        {
            "chat_id": chat_id,
            "message_id": reply["message_id"],
            "disable_notification": False
        }
    )

    if result.get("ok"):
        send_text(chat_id, "📌 Đã ghim tin nhắn.")
    else:
        send_text(
            chat_id,
            "❌ Không thể ghim tin nhắn."
        )


# ------------------------------------------------------------
# UNPIN
# ------------------------------------------------------------

def cmd_unpin(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )

    reply = message.get("reply_to_message")

    if reply:
        result = tg_call(
            "unpinChatMessage",
            {
                "chat_id": chat_id,
                "message_id": reply["message_id"]
            }
        )
    else:
        result = tg_call(
            "unpinChatMessage",
            {
                "chat_id": chat_id
            }
        )

    if result.get("ok"):
        send_text(chat_id, "📍 Đã bỏ ghim tin nhắn.")
    else:
        send_text(
            chat_id,
            "❌ Không thể bỏ ghim."
        )

# ============================================================
# PHẦN 4/15 — BẢO VỆ NHÓM
# ANTISPAM / ANTILINK / ANTIBUFF / ANTIFAKE
# ============================================================

# ------------------------------------------------------------
# BIẾN ANTISPAM
# ------------------------------------------------------------

SPAM_TRACKER = {}

# Số tin nhắn tối đa trong khoảng thời gian
SPAM_LIMIT = 7
SPAM_WINDOW = 8


def check_antispam(chat_id, user_id):
    """
    Trả về True nếu user đang spam.
    """

    now = time.time()

    key = (chat_id, user_id)

    if key not in SPAM_TRACKER:
        SPAM_TRACKER[key] = []

    # Chỉ giữ lại tin nhắn trong khoảng SPAM_WINDOW giây
    SPAM_TRACKER[key] = [
        t for t in SPAM_TRACKER[key]
        if now - t <= SPAM_WINDOW
    ]

    SPAM_TRACKER[key].append(now)

    return len(SPAM_TRACKER[key]) >= SPAM_LIMIT


def clear_spam_user(chat_id, user_id):
    SPAM_TRACKER.pop((chat_id, user_id), None)


# ------------------------------------------------------------
# XÓA TIN NHẮN
# ------------------------------------------------------------

def delete_message(chat_id, message_id):
    try:
        result = tg_call(
            "deleteMessage",
            {
                "chat_id": chat_id,
                "message_id": message_id
            }
        )
        return bool(result.get("ok"))
    except Exception:
        return False


# ------------------------------------------------------------
# ANTISPAM
# ------------------------------------------------------------

def cmd_antispam(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được bật/tắt Antispam."
        )

    action = args[0].lower() if args else ""

    if action in ("on", "bat", "bật", "1"):
        set_setting(chat_id, "antispam", "1")
        return send_text(
            chat_id,
            "🛡️ Antispam đã được BẬT."
        )

    if action in ("off", "tat", "tắt", "0"):
        set_setting(chat_id, "antispam", "0")
        return send_text(
            chat_id,
            "🛡️ Antispam đã được TẮT."
        )

    status = get_setting(chat_id, "antispam", "0")

    send_text(
        chat_id,
        "🛡️ ANTISPAM\n\n"
        f"Trạng thái: {'🟢 BẬT' if status == '1' else '🔴 TẮT'}\n\n"
        "Cách dùng:\n"
        "/antispam on\n"
        "/antispam off"
    )


# ------------------------------------------------------------
# XỬ LÝ ANTISPAM
# ------------------------------------------------------------

def handle_antispam_message(message):
    chat = message.get("chat", {})

    if not is_group_chat(chat):
        return False

    chat_id = chat.get("id")
    user = message.get("from", {})

    if not user:
        return False

    # Admin không bị antispam
    if is_admin(chat_id, user.get("id")):
        return False

    if get_setting(chat_id, "antispam", "0") != "1":
        return False

    if check_antispam(chat_id, user.get("id")):
        delete_message(
            chat_id,
            message.get("message_id")
        )

        clear_spam_user(
            chat_id,
            user.get("id")
        )

        send_text(
            chat_id,
            f"🚫 {mention_user(user)} đang gửi tin nhắn quá nhanh.\n"
            "🛡️ Antispam đã chặn.",
            parse_mode="HTML"
        )

        return True

    return False


# ------------------------------------------------------------
# ANTILINK
# ------------------------------------------------------------

LINK_REGEX = re.compile(
    r"(https?://\S+|www\.\S+|t\.me/\S+|telegram\.me/\S+)",
    re.IGNORECASE
)


def contains_link(text):
    if not text:
        return False

    return bool(LINK_REGEX.search(text))


def cmd_antilink(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được bật/tắt Antilink."
        )

    action = args[0].lower() if args else ""

    if action in ("on", "bat", "bật", "1"):
        set_setting(chat_id, "antilink", "1")
        return send_text(
            chat_id,
            "🔗 Antilink đã được BẬT."
        )

    if action in ("off", "tat", "tắt", "0"):
        set_setting(chat_id, "antilink", "0")
        return send_text(
            chat_id,
            "🔗 Antilink đã được TẮT."
        )

    status = get_setting(chat_id, "antilink", "0")

    send_text(
        chat_id,
        "🔗 ANTILINK\n\n"
        f"Trạng thái: {'🟢 BẬT' if status == '1' else '🔴 TẮT'}\n\n"
        "Cách dùng:\n"
        "/antilink on\n"
        "/antilink off"
    )


def handle_antilink_message(message):
    chat = message.get("chat", {})

    if not is_group_chat(chat):
        return False

    chat_id = chat.get("id")
    user = message.get("from", {})

    if not user:
        return False

    if is_admin(chat_id, user.get("id")):
        return False

    if get_setting(chat_id, "antilink", "0") != "1":
        return False

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    if not contains_link(text):
        return False

    deleted = delete_message(
        chat_id,
        message.get("message_id")
    )

    if deleted:
        send_text(
            chat_id,
            f"🔗 {mention_user(user)}, nhóm đang bật Antilink.\n"
            "❌ Tin nhắn chứa link đã bị xóa.",
            parse_mode="HTML"
        )

    return True


# ------------------------------------------------------------
# ANTIBUFF
# ------------------------------------------------------------

def get_group_member_count(chat_id):
    try:
        result = tg_call(
            "getChatMemberCount",
            {
                "chat_id": chat_id
            }
        )

        if result.get("ok"):
            return int(result["result"])

    except Exception:
        pass

    return 0


def get_recent_joiners(chat_id, hours=24):
    """
    Lấy danh sách user mà bot đã ghi nhận qua các message/service update.
    """

    cutoff = int(time.time()) - hours * 3600

    rows = db_fetchall(
        """
        SELECT user_id, first_name, username
        FROM users
        WHERE chat_id=?
        AND last_seen>=?
        """,
        (chat_id, cutoff)
    )

    return rows


def cmd_antibuff(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được bật/tắt Antibuff."
        )

    action = args[0].lower() if args else ""

    if action in ("on", "bat", "bật", "1"):
        set_setting(chat_id, "antibuff", "1")
        return send_text(
            chat_id,
            "👥 Antibuff đã được BẬT."
        )

    if action in ("off", "tat", "tắt", "0"):
        set_setting(chat_id, "antibuff", "0")
        return send_text(
            chat_id,
            "👥 Antibuff đã được TẮT."
        )

    status = get_setting(chat_id, "antibuff", "0")

    send_text(
        chat_id,
        "👥 ANTIBUFF\n\n"
        f"Trạng thái: {'🟢 BẬT' if status == '1' else '🔴 TẮT'}\n\n"
        "Antibuff giúp theo dõi tài khoản mới xuất hiện trong nhóm "
        "và hạn chế hành vi tăng thành viên bất thường.\n\n"
        "Cách dùng:\n"
        "/antibuff on\n"
        "/antibuff off"
    )


def handle_antibuff_message(message):
    """
    Antibuff không tự động ban hàng loạt.
    Nó chỉ ghi nhận profile để tránh nhận diện sai người dùng thật.
    """

    chat = message.get("chat", {})

    if not is_group_chat(chat):
        return False

    chat_id = chat.get("id")
    user = message.get("from", {})

    if not user or not user.get("id"):
        return False

    if get_setting(chat_id, "antibuff", "0") != "1":
        return False

    save_known_profile(user)

    # Ghi nhận người dùng đã xuất hiện trong nhóm.
    db_execute(
        """
        INSERT INTO users
        (chat_id, user_id, first_name, username, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id,user_id)
        DO UPDATE SET
            first_name=excluded.first_name,
            username=excluded.username,
            last_seen=excluded.last_seen
        """,
        (
            chat_id,
            user["id"],
            user.get("first_name"),
            user.get("username"),
            int(time.time())
        )
    )

    return False


# ------------------------------------------------------------
# ANTIFAKE
# ------------------------------------------------------------

def profile_signature(user):
    """
    Tạo chữ ký đơn giản dựa trên tên + username.
    Không dùng để kết luận người dùng là lừa đảo.
    """

    if not user:
        return ""

    name = (
        user.get("first_name")
        or ""
    ).strip().lower()

    last = (
        user.get("last_name")
        or ""
    ).strip().lower()

    username = (
        user.get("username")
        or ""
    ).strip().lower()

    return f"{name}|{last}|{username}"


def cmd_antifake(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được bật/tắt Antifake."
        )

    action = args[0].lower() if args else ""

    if action in ("on", "bat", "bật", "1"):
        set_setting(chat_id, "antifake", "1")
        return send_text(
            chat_id,
            "🕵️ Antifake đã được BẬT."
        )

    if action in ("off", "tat", "tắt", "0"):
        set_setting(chat_id, "antifake", "0")
        return send_text(
            chat_id,
            "🕵️ Antifake đã được TẮT."
        )

    status = get_setting(chat_id, "antifake", "0")

    send_text(
        chat_id,
        "🕵️ ANTIFAKE\n\n"
        f"Trạng thái: {'🟢 BẬT' if status == '1' else '🔴 TẮT'}\n\n"
        "Bot sẽ lưu profile đã quan sát trong nhóm để phát hiện "
        "những trường hợp có tên hiển thị giống nhau.\n\n"
        "Cách dùng:\n"
        "/antifake on\n"
        "/antifake off"
    )


def handle_antifake_message(message):
    chat = message.get("chat", {})

    if not is_group_chat(chat):
        return False

    chat_id = chat.get("id")
    user = message.get("from", {})

    if not user or not user.get("id"):
        return False

    if get_setting(chat_id, "antifake", "0") != "1":
        return False

    current_name = (
        user.get("first_name")
        or ""
    ).strip().lower()

    current_last = (
        user.get("last_name")
        or ""
    ).strip().lower()

    if not current_name:
        return False

    # Tìm người khác có cùng tên hiển thị.
    rows = db_fetchall(
        """
        SELECT user_id, first_name, last_name, username
        FROM known_profiles
        WHERE user_id != ?
        """,
        (user["id"],)
    )

    possible = []

    for row in rows:
        old_name = (
            row["first_name"]
            or ""
        ).strip().lower()

        old_last = (
            row["last_name"]
            or ""
        ).strip().lower()

        if old_name == current_name and old_last == current_last:
            possible.append(row)

    save_known_profile(user)

    # Chỉ cảnh báo, không tự động ban.
    if possible:
        username = user.get("username")

        # Có username khác nhau thì mới đáng chú ý.
        for row in possible:
            old_username = row["username"]

            if (
                old_username
                and username
                and old_username.lower() != username.lower()
            ):
                send_text(
                    chat_id,
                    "⚠️ <b>CẢNH BÁO ANTIFAKE</b>\n\n"
                    f"Phát hiện tài khoản {mention_user(user)} "
                    "có tên hiển thị giống một tài khoản khác trong "
                    "danh sách đã ghi nhận.\n\n"
                    "🔎 Hãy kiểm tra kỹ @username và ID trước khi "
                    "giao dịch hoặc cung cấp thông tin.",
                    parse_mode="HTML"
                )
                break

    return False


# ------------------------------------------------------------
# TRẠNG THÁI BẢO VỆ
# ------------------------------------------------------------

def cmd_protect(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được xem cấu hình bảo vệ."
        )

    send_text(
        chat_id,
        "🛡️ <b>BẢO VỆ NHÓM</b>\n\n"
        f"🚫 Antispam: "
        f"{'🟢 BẬT' if get_setting(chat_id, 'antispam', '0') == '1' else '🔴 TẮT'}\n"
        f"🔗 Antilink: "
        f"{'🟢 BẬT' if get_setting(chat_id, 'antilink', '0') == '1' else '🔴 TẮT'}\n"
        f"👥 Antibuff: "
        f"{'🟢 BẬT' if get_setting(chat_id, 'antibuff', '0') == '1' else '🔴 TẮT'}\n"
        f"🕵️ Antifake: "
        f"{'🟢 BẬT' if get_setting(chat_id, 'antifake', '0') == '1' else '🔴 TẮT'}",
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# HÀM GỌI TOÀN BỘ BẢO VỆ
# ------------------------------------------------------------

def handle_protection(message):
    """
    Gọi các hệ thống bảo vệ.
    Trả về True nếu tin nhắn đã bị xử lý/xóa.
    """

    if handle_antispam_message(message):
        return True

    if handle_antilink_message(message):
        return True

    handle_antibuff_message(message)
    handle_antifake_message(message)

    return False

# ============================================================
# PHẦN 5/15 — AFK + FILTER
# ============================================================

# ------------------------------------------------------------
# AFK
# ------------------------------------------------------------

def set_afk(chat_id, user_id, reason):
    db_execute(
        """
        INSERT INTO afk(chat_id, user_id, reason, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            reason=excluded.reason,
            created_at=excluded.created_at
        """,
        (
            chat_id,
            user_id,
            reason,
            int(time.time())
        )
    )


def remove_afk(chat_id, user_id):
    db_execute(
        "DELETE FROM afk WHERE chat_id=? AND user_id=?",
        (chat_id, user_id)
    )


def get_afk(chat_id, user_id):
    return db_fetchone(
        """
        SELECT reason, created_at
        FROM afk
        WHERE chat_id=? AND user_id=?
        """,
        (chat_id, user_id)
    )


def cmd_afk(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    user = message.get("from", {})
    user_id = user.get("id")

    reason = " ".join(args).strip()

    if not reason:
        reason = "không có lý do"

    set_afk(
        chat_id,
        user_id,
        reason
    )

    send_text(
        chat_id,
        f"💤 {mention_user(user)} đã bật AFK.\n"
        f"📝 Lý do: {html.escape(reason)}",
        parse_mode="HTML"
    )


def format_duration(seconds):
    seconds = max(0, int(seconds))

    days = seconds // 86400
    seconds %= 86400

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60
    seconds %= 60

    parts = []

    if days:
        parts.append(f"{days} ngày")

    if hours:
        parts.append(f"{hours} giờ")

    if minutes:
        parts.append(f"{minutes} phút")

    if not parts:
        parts.append(f"{seconds} giây")

    return " ".join(parts)


def handle_afk_message(message):
    chat = message.get("chat", {})

    if not is_group_chat(chat):
        return

    chat_id = chat.get("id")
    user = message.get("from", {})

    if not user:
        return

    user_id = user.get("id")

    # --------------------------------------------------------
    # Nếu chính người AFK quay lại -> tắt AFK
    # --------------------------------------------------------

    own_afk = get_afk(
        chat_id,
        user_id
    )

    if own_afk:
        remove_afk(
            chat_id,
            user_id
        )

        duration = format_duration(
            time.time() - own_afk["created_at"]
        )

        send_text(
            chat_id,
            f"👋 {mention_user(user)} đã quay lại.\n"
            f"⏱️ AFK: {duration}",
            parse_mode="HTML"
        )

    # --------------------------------------------------------
    # Nếu reply người đang AFK
    # --------------------------------------------------------

    reply = message.get("reply_to_message")

    if reply:
        target = reply.get("from")

        if target:
            afk = get_afk(
                chat_id,
                target.get("id")
            )

            if afk:
                duration = format_duration(
                    time.time() - afk["created_at"]
                )

                reason = html.escape(
                    afk["reason"] or "không có lý do"
                )

                send_text(
                    chat_id,
                    f"💤 {mention_user(target)} đang AFK.\n"
                    f"📝 Lý do: {reason}\n"
                    f"⏱️ Đã AFK: {duration}",
                    parse_mode="HTML"
                )


# ------------------------------------------------------------
# FILTER
# ------------------------------------------------------------

def normalize_filter_word(text):
    return re.sub(
        r"\s+",
        " ",
        (text or "").strip().lower()
    )


def add_filter(chat_id, word, response):
    word = normalize_filter_word(word)

    if not word:
        return False

    db_execute(
        """
        INSERT INTO filters(chat_id, keyword, response)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id, keyword)
        DO UPDATE SET response=excluded.response
        """,
        (
            chat_id,
            word,
            response
        )
    )

    return True


def remove_filter(chat_id, word):
    word = normalize_filter_word(word)

    result = db_execute(
        """
        DELETE FROM filters
        WHERE chat_id=? AND keyword=?
        """,
        (
            chat_id,
            word
        )
    )

    return result


def get_filters(chat_id):
    return db_fetchall(
        """
        SELECT keyword, response
        FROM filters
        WHERE chat_id=?
        ORDER BY keyword ASC
        """,
        (chat_id,)
    )


def cmd_filter(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được quản lý Filter."
        )

    if len(args) < 2:
        return send_text(
            chat_id,
            "🔎 Cách dùng:\n\n"
            "/filter từ_khóa | nội_dung_trả_lời\n\n"
            "Ví dụ:\n"
            "/filter hello | Xin chào 👋"
        )

    raw = " ".join(args)

    if "|" not in raw:
        return send_text(
            chat_id,
            "❌ Phải có dấu | giữa từ khóa và nội dung."
        )

    keyword, response = raw.split("|", 1)

    keyword = normalize_filter_word(keyword)
    response = response.strip()

    if not keyword:
        return send_text(
            chat_id,
            "❌ Từ khóa không được để trống."
        )

    if not response:
        return send_text(
            chat_id,
            "❌ Nội dung trả lời không được để trống."
        )

    add_filter(
        chat_id,
        keyword,
        response
    )

    send_text(
        chat_id,
        f"✅ Đã thêm filter:\n"
        f"🔎 Từ khóa: <code>{html.escape(keyword)}</code>\n"
        f"💬 Trả lời: {html.escape(response)}",
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# FILTERS — DANH SÁCH
# ------------------------------------------------------------

def cmd_filters(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    rows = get_filters(chat_id)

    if not rows:
        return send_text(
            chat_id,
            "🔎 Nhóm hiện chưa có filter nào."
        )

    lines = [
        "🔎 <b>DANH SÁCH FILTER</b>",
        ""
    ]

    for index, row in enumerate(rows, 1):
        keyword = html.escape(
            row["keyword"]
        )

        response = html.escape(
            row["response"]
        )

        lines.append(
            f"{index}. <code>{keyword}</code> → {response}"
        )

    send_text(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# STOP FILTER
# ------------------------------------------------------------

def cmd_stop_filter(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    if not is_admin(chat_id, message["from"]["id"]):
        return send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được quản lý Filter."
        )

    if not args:
        return send_text(
            chat_id,
            "❌ Dùng:\n/stopfilter từ_khóa"
        )

    keyword = normalize_filter_word(
        " ".join(args)
    )

    existing = db_fetchone(
        """
        SELECT keyword
        FROM filters
        WHERE chat_id=? AND keyword=?
        """,
        (
            chat_id,
            keyword
        )
    )

    if not existing:
        return send_text(
            chat_id,
            f"❌ Không tìm thấy filter: {keyword}"
        )

    remove_filter(
        chat_id,
        keyword
    )

    send_text(
        chat_id,
        f"🗑️ Đã xóa filter: <code>{html.escape(keyword)}</code>",
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# XỬ LÝ FILTER KHI CÓ TIN NHẮN
# ------------------------------------------------------------

def handle_filter_message(message):
    chat = message.get("chat", {})

    if not is_group_chat(chat):
        return False

    chat_id = chat.get("id")

    text = (
        message.get("text")
        or message.get("caption")
        or ""
    )

    if not text:
        return False

    normalized_text = normalize_filter_word(text)

    rows = get_filters(chat_id)

    if not rows:
        return False

    user = message.get("from", {})

    # Admin vẫn có thể kích hoạt filter.
    # Filter là luật của nhóm, không phải quyền người dùng.

    for row in rows:
        keyword = normalize_filter_word(
            row["keyword"]
        )

        if not keyword:
            continue

        # Tìm theo cụm từ
        if keyword in normalized_text:
            response = row["response"]

            send_text(
                chat_id,
                response,
                reply_to=message.get("message_id")
            )

            return True

    return False


# ------------------------------------------------------------
# FILTER TỰ ĐỘNG XÓA
# ------------------------------------------------------------

def handle_filter_delete(message):
    """
    Hàm này chỉ dùng khi filter được cấu hình đặc biệt.
    Hiện tại không tự xóa tin nhắn để tránh xóa nhầm.
    """

    return False


# ------------------------------------------------------------
# XỬ LÝ AFK + FILTER CHUNG
# ------------------------------------------------------------

def handle_extra_message_features(message):
    """
    Chạy AFK và Filter cho mỗi message.
    """

    handle_afk_message(message)

    try:
        handle_filter_message(message)
    except Exception as e:
        logging.exception(
            "Filter error: %s",
            e
        )

# ============================================================
# PHẦN 6/15 — THƠ ĐỜI / THƠ TÌNH / ĐIỂM DANH
# ============================================================

# ------------------------------------------------------------
# 20 CÂU / BÀI THƠ ĐỜI
# ------------------------------------------------------------

THO_DOI = [
    "Đời người như một chuyến xe,\nCó người lên sớm, có người xuống sau.\nGặp nhau chẳng được bao lâu,\nNên xin hãy sống thật sâu nghĩa tình.",

    "Ngoài kia phong ba bão tố,\nBình yên đôi khi chỉ ở trong lòng.\nĐừng mong cuộc sống màu hồng,\nHọc cách mạnh mẽ giữa dòng thế gian.",

    "Có những ngày chẳng muốn cười,\nCó những đêm chẳng muốn người hỏi han.\nNhưng rồi ngày mới lại sang,\nTự mình đứng dậy, bước ngang nỗi buồn.",

    "Tiền nhiều chưa chắc bình yên,\nDanh cao chưa chắc có duyên với đời.\nĐến khi nhắm mắt buông xuôi,\nChỉ mong còn lại một người nhớ ta.",

    "Đường đời lắm lúc chông gai,\nThua hôm nay chẳng có nghĩa thua hoài.\nMiễn còn giữ được tương lai,\nThì còn cơ hội ngày mai làm người.",

    "Người thương ta thật chẳng nhiều,\nNgười vì lợi ích thì điều chẳng hiếm.\nSống sao cho đáng chữ tình,\nĐừng vì một chút lợi mình mà quên.",

    "Có tiền mua được căn nhà,\nNhưng không mua được người nhà yêu thương.\nCó tiền mua được chiếc giường,\nNhưng không mua được giấc thường bình yên.",

    "Đời người ngắn tựa làn mây,\nHôm nay còn đó, mai này đã xa.\nVậy nên đừng sống hơn thua,\nBình an mới chính là quà trời cho.",

    "Người đi để lại câu thề,\nNgười ở ôm lấy bộn bề tháng năm.\nSau cùng mới hiểu âm thầm,\nCó người từng quý mà mình chẳng hay.",

    "Đừng cười khi thấy người đau,\nĐời ai rồi cũng có lúc lao đao.\nHôm nay họ đứng thấp cao,\nNgày mai chưa biết ai nào hơn ai.",

    "Có những bài học trong đời,\nKhông nằm trên sách, chẳng nơi trường nào.\nPhải qua nước mắt lao đao,\nMới hay trưởng thành đổi màu thời gian.",

    "Đời không phải lúc nào vui,\nCó khi phải khóc để rồi trưởng thành.\nSau bao giông tố mong manh,\nTa càng hiểu được chữ lành chữ thương.",

    "Thành công chẳng đến một ngày,\nMà từ những lúc trắng tay đứng nhìn.\nNếu còn giữ được niềm tin,\nThì còn có thể tự mình bước đi.",

    "Đừng vì một phút nóng lòng,\nMà đem cả những tấm lòng đánh rơi.\nLời nói một khi buông rồi,\nMuốn thu lại cũng chẳng đời nào nguyên.",

    "Người khôn biết lúc nên cười,\nBiết khi im lặng, biết người nào nên xa.\nĐời người chẳng rộng bao la,\nĐừng đem thời gian đổi qua hận thù.",

    "Có những người đến rồi đi,\nNhưng đem bài học khắc ghi suốt đời.\nDẫu cho duyên đã xa rồi,\nXin còn cảm tạ một thời gặp nhau.",

    "Mệt thì cứ nghỉ một ngày,\nNhưng đừng bỏ cuộc giữa đầy khó khăn.\nChậm thôi cũng chẳng muộn màng,\nMiễn là đôi bước vẫn đang tiến về.",

    "Đừng nhìn thiên hạ hơn mình,\nMỗi người một cảnh, một tình, một duyên.\nChỉ cần hôm nay tốt hơn,\nHơn mình của chính ngày hôm qua là mừng.",

    "Cuộc đời vốn chẳng công bằng,\nNhưng ta vẫn phải cố gắng mỗi ngày.\nChẳng cần thắng hết cuộc đời,\nChỉ cần không thắng chính mình là thua.",

    "Sau cùng điều quý nhất đời,\nKhông là vật chất, chẳng lời phù hoa.\nLà khi ngoảnh lại đường xa,\nThấy mình đã sống thật thà với nhau."
]


# ------------------------------------------------------------
# 20 CÂU / BÀI THƠ TÌNH
# ------------------------------------------------------------

THO_TINH = [
    "Nếu đời là một bản nhạc,\nAnh mong em là giai điệu cuối cùng.\nDẫu cho thế giới mênh mông,\nChỉ cần có em là lòng bình yên.",

    "Anh không hứa cả đời này,\nSẽ không có lúc đắng cay giữa đường.\nNhưng anh hứa sẽ yêu thương,\nKhi em mỏi mệt, anh thường ở đây.",

    "Em như ánh nắng ban mai,\nSoi vào những tháng năm dài cô đơn.\nTừ ngày em bước vào lòng,\nThế gian bỗng hóa dịu dàng hơn xưa.",

    "Có người hỏi thích điều gì,\nAnh cười chẳng biết nói gì ngoài em.\nBởi vì từ lúc quen em,\nTim anh chẳng muốn gọi tên một người.",

    "Nếu mai trời có mưa bay,\nAnh mong mình vẫn nắm tay cùng người.\nDẫu cho năm tháng đổi dời,\nTình này vẫn giữ một đời chẳng phai.",

    "Yêu em chẳng phải vì xinh,\nMà vì em khiến tim mình bình yên.\nGiữa bao người ở ngoài kia,\nChỉ riêng ánh mắt em làm anh rung.",

    "Anh chẳng cần những lời thề,\nChỉ cần mỗi tối em về bình an.\nNgoài kia dẫu có gian nan,\nVề bên anh nhé, bình an đủ rồi.",

    "Ngày dài rồi cũng sẽ qua,\nChỉ mong người ấy vẫn là người thương.\nDẫu cho đi hết đoạn đường,\nCuối cùng vẫn muốn chung đường với em.",

    "Có em ngày tháng dịu dàng,\nCó em những lúc hoang mang nhẹ lòng.\nTình yêu chẳng cần cầu mong,\nChỉ cần hai đứa thật lòng với nhau.",

    "Anh từng nghĩ chẳng cần ai,\nCho đến khi gặp một người là em.\nTừ ngày ánh mắt chạm nhau,\nTrái tim bỗng chẳng còn đâu bình thường.",

    "Nếu được chọn lại một lần,\nAnh vẫn chọn gặp người cần gặp em.\nDẫu cho phía trước có thêm,\nBao nhiêu thử thách vẫn tìm đến nhau.",

    "Em không phải cả thế gian,\nNhưng em là cả bình an trong lòng.\nNgoài kia vạn vật đổi dòng,\nChỉ mong tình chúng ta không đổi dời.",

    "Thương em chẳng nói thành lời,\nChỉ mong em hiểu những điều anh mong.\nMột đời chẳng cần quá đông,\nChỉ cần một người thật lòng bên nhau.",

    "Nếu tình yêu có hình hài,\nAnh mong nó giống bàn tay của em.\nẤm áp, dịu dàng mỗi đêm,\nĐủ làm tim nhỏ ngủ yên giữa đời.",

    "Anh không biết ngày mai nào,\nNhưng anh biết muốn cùng em đi hoài.\nDẫu cho tóc có bạc màu,\nVẫn mong được gọi tên nhau mỗi ngày.",

    "Em là một chút dịu dàng,\nGiữa bao bộn bề ngổn ngang cuộc đời.\nGặp em anh thấy tuyệt vời,\nVì tim có chỗ để người thương nhau.",

    "Chẳng cần hứa chuyện trăm năm,\nChỉ cần hiện tại âm thầm thương nhau.\nMai sau dẫu có thế nào,\nTừng yêu chân thật là điều đẹp thay.",

    "Anh thích những buổi chiều mưa,\nThích nghe em kể chuyện xưa chuyện đời.\nChẳng cần vật chất xa xôi,\nCó em bên cạnh là rồi đủ vui.",

    "Nếu một ngày em thấy buồn,\nĐừng ngại gọi nhé, anh luôn nghe mà.\nDẫu cho khoảng cách thật xa,\nTấm lòng anh vẫn tìm qua bên người.",

    "Tình yêu đẹp nhất trên đời,\nKhông cần hoàn hảo, chỉ người thật tâm.\nHai người cùng bước âm thầm,\nQua bao giông gió vẫn cầm tay nhau."
]


def cmd_thodoi(message, args):
    chat_id = message.get("chat", {}).get("id")

    poem = random.choice(THO_DOI)

    send_text(
        chat_id,
        "🌿 <b>THƠ ĐỜI</b>\n\n"
        + html.escape(poem),
        parse_mode="HTML"
    )


def cmd_thotinh(message, args):
    chat_id = message.get("chat", {}).get("id")

    poem = random.choice(THO_TINH)

    send_text(
        chat_id,
        "❤️ <b>THƠ TÌNH</b>\n\n"
        + html.escape(poem),
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# ĐIỂM DANH
# ------------------------------------------------------------

def today_string():
    return datetime.datetime.now().strftime("%Y-%m-%d")


def get_checkin(chat_id, user_id):
    return db_fetchone(
        """
        SELECT streak, last_date
        FROM checkins
        WHERE chat_id=? AND user_id=?
        """,
        (
            chat_id,
            user_id
        )
    )


def update_checkin(chat_id, user_id):
    today = today_string()

    row = get_checkin(
        chat_id,
        user_id
    )

    if not row:
        streak = 1

        db_execute(
            """
            INSERT INTO checkins
            (chat_id, user_id, streak, last_date)
            VALUES (?, ?, ?, ?)
            """,
            (
                chat_id,
                user_id,
                streak,
                today
            )
        )

        return streak, True

    last_date = row["last_date"]
    old_streak = int(row["streak"] or 0)

    if last_date == today:
        return old_streak, False

    try:
        last = datetime.datetime.strptime(
            last_date,
            "%Y-%m-%d"
        ).date()

        current = datetime.datetime.strptime(
            today,
            "%Y-%m-%d"
        ).date()

        difference = (
            current - last
        ).days

    except Exception:
        difference = 999

    if difference == 1:
        streak = old_streak + 1
    else:
        streak = 1

    db_execute(
        """
        UPDATE checkins
        SET streak=?, last_date=?
        WHERE chat_id=? AND user_id=?
        """,
        (
            streak,
            today,
            chat_id,
            user_id
        )
    )

    return streak, True


def cmd_diemdanh(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🔥 Điểm danh",
                    "callback_data": "checkin"
                }
            ]
        ]
    }

    send_text(
        chat_id,
        "📋 <b>ĐIỂM DANH HÔM NAY</b>\n\n"
        "Bấm nút bên dưới để điểm danh.\n"
        "🔥 Mỗi ngày điểm danh sẽ duy trì Streak.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


def handle_checkin_callback(callback):
    data = callback.get("data", "")

    if data != "checkin":
        return False

    message = callback.get("message") or {}
    user = callback.get("from") or {}

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    user_id = user.get("id")

    if not chat_id or not user_id:
        return True

    streak, is_new = update_checkin(
        chat_id,
        user_id
    )

    callback_id = callback.get("id")

    if callback_id:
        if is_new:
            tg_call(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": f"🔥 Điểm danh thành công! Streak: {streak} ngày",
                    "show_alert": False
                }
            )

            send_text(
                chat_id,
                f"🔥 {mention_user(user)} điểm danh thành công!\n"
                f"📅 Streak: <b>{streak} ngày</b>",
                parse_mode="HTML"
            )
        else:
            tg_call(
                "answerCallbackQuery",
                {
                    "callback_query_id": callback_id,
                    "text": f"Bạn đã điểm danh hôm nay! Streak: {streak} ngày",
                    "show_alert": True
                }
            )

    return True

# ============================================================
# PHẦN 7/15 — LEVEL SYSTEM
# ============================================================

# ------------------------------------------------------------
# CẤU HÌNH LEVEL
# ------------------------------------------------------------

LEVEL_THRESHOLDS = {
    1: 0,
    2: 100,
    3: 300,
    4: 500,
    5: 700,
    6: 900,
    7: 1200,
    8: 1600,
    9: 2000,
    10: 3000
}


def calculate_level(messages):
    """
    Xác định level dựa trên tổng số tin nhắn.
    """

    messages = int(messages or 0)

    current_level = 1

    for level, required in sorted(
        LEVEL_THRESHOLDS.items()
    ):
        if messages >= required:
            current_level = level
        else:
            break

    return current_level


def get_level_user(chat_id, user_id):
    return db_fetchone(
        """
        SELECT user_id, messages, level
        FROM levels
        WHERE chat_id=? AND user_id=?
        """,
        (
            chat_id,
            user_id
        )
    )


def create_level_user(chat_id, user):
    user_id = user.get("id")

    if not user_id:
        return None

    row = get_level_user(
        chat_id,
        user_id
    )

    if row:
        return row

    db_execute(
        """
        INSERT INTO levels
        (chat_id, user_id, messages, level)
        VALUES (?, ?, ?, ?)
        """,
        (
            chat_id,
            user_id,
            0,
            1
        )
    )

    return get_level_user(
        chat_id,
        user_id
    )


def add_level_message(chat_id, user):
    """
    Cộng 1 tin nhắn cho user.

    Trả về:
        old_level
        new_level
        total_messages
    """

    user_id = user.get("id")

    if not user_id:
        return 1, 1, 0

    row = get_level_user(
        chat_id,
        user_id
    )

    if not row:
        messages = 1
        old_level = 1
        new_level = calculate_level(messages)

        db_execute(
            """
            INSERT INTO levels
            (chat_id, user_id, messages, level)
            VALUES (?, ?, ?, ?)
            """,
            (
                chat_id,
                user_id,
                messages,
                new_level
            )
        )

        return old_level, new_level, messages

    old_level = int(
        row["level"] or 1
    )

    messages = int(
        row["messages"] or 0
    ) + 1

    new_level = calculate_level(
        messages
    )

    db_execute(
        """
        UPDATE levels
        SET messages=?, level=?
        WHERE chat_id=? AND user_id=?
        """,
        (
            messages,
            new_level,
            chat_id,
            user_id
        )
    )

    return old_level, new_level, messages


def level_progress(messages, level):
    """
    Tính tiến độ đến level tiếp theo.
    """

    next_level = level + 1

    if next_level not in LEVEL_THRESHOLDS:
        return None, 100

    current_required = LEVEL_THRESHOLDS[level]
    next_required = LEVEL_THRESHOLDS[next_level]

    if next_required <= current_required:
        return next_level, 100

    progress = (
        (messages - current_required)
        / (next_required - current_required)
    ) * 100

    progress = max(
        0,
        min(100, progress)
    )

    return next_level, int(progress)


# ------------------------------------------------------------
# XỬ LÝ LEVEL KHI CÓ MESSAGE
# ------------------------------------------------------------

def handle_level_message(message):
    chat = message.get("chat", {})

    if not is_group_chat(chat):
        return

    chat_id = chat.get("id")
    user = message.get("from", {})

    if not user:
        return

    # Bot không được tính level
    if user.get("is_bot"):
        return

    old_level, new_level, messages = add_level_message(
        chat_id,
        user
    )

    # --------------------------------------------------------
    # Thông báo khi lên level
    # --------------------------------------------------------

    if new_level > old_level:
        send_text(
            chat_id,
            "🎉 <b>CHÚC MỪNG LEVEL UP!</b>\n\n"
            f"👤 {mention_user(user)}\n"
            f"⬆️ Đã lên <b>Level {new_level}</b>\n"
            f"💬 Tổng tin nhắn: <b>{messages}</b>\n\n"
            "📋 Xem nhiệm vụ tiếp theo:\n"
            "/levelnhiemvu",
            parse_mode="HTML"
        )


# ------------------------------------------------------------
# /LEVEL
# ------------------------------------------------------------

def cmd_level(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    send_text(
        chat_id,
        "⭐ <b>HỆ THỐNG LEVEL NGỌC MỸ</b>\n\n"
        "Level được tăng dựa trên số tin nhắn của thành viên "
        "trong nhóm.\n\n"
        "👤 /levelyou — Xem level của bạn\n"
        "🏆 /levelbxh — Xem bảng xếp hạng\n"
        "📋 /leveldanhsach — Điều kiện từng level\n"
        "🎯 /levelnhiemvu — Xem nhiệm vụ level\n\n"
        "💡 Khi đạt đủ số tin nhắn, bot sẽ tự động thông báo "
        "khi bạn lên level.",
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# /LEVELYOU
# ------------------------------------------------------------

def cmd_levelyou(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    user = message.get("from", {})

    row = get_level_user(
        chat_id,
        user.get("id")
    )

    if not row:
        messages = 0
        level = 1
    else:
        messages = int(
            row["messages"] or 0
        )

        level = int(
            row["level"] or 1
        )

    next_level, progress = level_progress(
        messages,
        level
    )

    text = (
        "⭐ <b>LEVEL CỦA BẠN</b>\n\n"
        f"👤 {mention_user(user)}\n"
        f"🏅 Level hiện tại: <b>{level}</b>\n"
        f"💬 Số tin nhắn: <b>{messages}</b>\n"
    )

    if next_level:
        required = LEVEL_THRESHOLDS[next_level]

        text += (
            f"🎯 Level tiếp theo: <b>{next_level}</b>\n"
            f"📈 Cần đạt: <b>{required}</b> tin nhắn\n"
            f"📊 Tiến độ: <b>{progress}%</b>"
        )
    else:
        text += (
            "🏆 Bạn đã đạt level cao nhất "
            "hiện tại."
        )

    send_text(
        chat_id,
        text,
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# /LEVELBXH
# ------------------------------------------------------------

def cmd_levelbxh(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    rows = db_fetchall(
        """
        SELECT user_id, messages, level
        FROM levels
        WHERE chat_id=?
        AND level >= 2
        ORDER BY level DESC, messages DESC
        LIMIT 50
        """,
        (chat_id,)
    )

    if not rows:
        return send_text(
            chat_id,
            "🏆 Chưa có thành viên nào đạt Level 2."
        )

    lines = [
        "🏆 <b>BẢNG XẾP HẠNG LEVEL</b>",
        ""
    ]

    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉"
    }

    for index, row in enumerate(rows, 1):
        user_id = row["user_id"]
        level = row["level"]
        messages = row["messages"]

        try:
            member = tg_call(
                "getChatMember",
                {
                    "chat_id": chat_id,
                    "user_id": user_id
                }
            )

            if member.get("ok"):
                user = member["result"].get("user", {})
                name = mention_user(user)
            else:
                name = f"<code>{user_id}</code>"

        except Exception:
            name = f"<code>{user_id}</code>"

        prefix = medals.get(
            index,
            f"{index}."
        )

        lines.append(
            f"{prefix} {name} — "
            f"Level <b>{level}</b> "
            f"({messages} tin nhắn)"
        )

    send_text(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# /LEVELDANHSACH
# ------------------------------------------------------------

def cmd_leveldanhsach(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    lines = [
        "📋 <b>DANH SÁCH ĐIỀU KIỆN LÊN LEVEL</b>",
        ""
    ]

    for level, required in sorted(
        LEVEL_THRESHOLDS.items()
    ):
        if level == 1:
            lines.append(
                "⭐ Level 1 — Bắt đầu"
            )
        else:
            lines.append(
                f"⭐ Level {level} — "
                f"{required} tin nhắn"
            )

    send_text(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# /LEVELNHIEMVU
# ------------------------------------------------------------

def cmd_levelnhiemvu(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not is_group_chat(chat):
        return send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )

    user = message.get("from", {})

    row = get_level_user(
        chat_id,
        user.get("id")
    )

    messages = (
        int(row["messages"])
        if row else 0
    )

    level = (
        int(row["level"])
        if row else 1
    )

    lines = [
        "🎯 <b>NHIỆM VỤ LEVEL</b>",
        "",
        f"👤 {mention_user(user)}",
        f"🏅 Level hiện tại: <b>{level}</b>",
        f"💬 Tin nhắn: <b>{messages}</b>",
        ""
    ]

    next_level = level + 1

    if next_level in LEVEL_THRESHOLDS:
        required = LEVEL_THRESHOLDS[next_level]
        remaining = max(
            0,
            required - messages
        )

        lines.extend([
            f"🎯 Mục tiêu Level {next_level}",
            f"📌 Cần: <b>{required}</b> tin nhắn",
            f"📨 Còn thiếu: <b>{remaining}</b> tin nhắn",
            "",
            "💡 Hãy tích cực tham gia trò chuyện "
            "trong nhóm để tăng level."
        ])
    else:
        lines.extend([
            "🏆 Bạn đã đạt level cao nhất "
            "trong hệ thống hiện tại."
        ])

    send_text(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML"
    )


# ------------------------------------------------------------
# XỬ LÝ LEVEL CHO MESSAGE
# ------------------------------------------------------------

def process_level_for_message(message):
    """
    Gọi riêng để process_update sử dụng.
    """

    try:
        handle_level_message(message)
    except Exception as e:
        logging.exception(
            "Level error: %s",
            e
        )

# ============================================================
# PHẦN 8/15 — NỐI CHỮ VIỆT NAM
# ============================================================

import threading

NOICHU_GAMES = {}
NOICHU_LOCK = threading.Lock()


def noichu_clean_text(text):
    """Chuẩn hóa nội dung để kiểm tra nối chữ."""
    if not text:
        return ""

    text = str(text).strip().lower()

    # Bỏ dấu câu cơ bản
    text = re.sub(r"[.,!?;:\"'“”‘’()\[\]{}<>/\\|@#$%^&*_+=~`]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def noichu_words(text):
    """Tách câu thành các từ."""
    text = noichu_clean_text(text)

    if not text:
        return []

    return text.split()


def noichu_last_word(text):
    words = noichu_words(text)

    if not words:
        return ""

    return words[-1]


def noichu_first_word(text):
    words = noichu_words(text)

    if not words:
        return ""

    return words[0]


def noichu_display_name(user):
    if not user:
        return "Người chơi"

    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""

    name = f"{first_name} {last_name}".strip()

    if user.get("username"):
        return f"@{user['username']}"

    return name or "Người chơi"


def noichu_make_join_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🎮 THAM GIA",
                    "callback_data": "noichu_join"
                }
            ]
        ]
    }


def noichu_make_game_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📋 Xem người chơi",
                    "callback_data": "noichu_players"
                }
            ]
        ]
    }


def noichu_get_game(chat_id):
    with NOICHU_LOCK:
        return NOICHU_GAMES.get(int(chat_id))


def noichu_player_exists(game, user_id):
    return any(
        int(player["id"]) == int(user_id)
        for player in game.get("players", [])
    )


def noichu_player_index(game, user_id):
    for index, player in enumerate(game.get("players", [])):
        if int(player["id"]) == int(user_id):
            return index

    return -1


def noichu_player_name_from_game(game, user_id):
    for player in game.get("players", []):
        if int(player["id"]) == int(user_id):
            return player.get("name", "Người chơi")

    return "Người chơi"


def noichu_create_game(chat_id, creator):
    game_id = f"{chat_id}_{int(time.time())}_{random.randint(1000, 9999)}"

    game = {
        "id": game_id,
        "chat_id": int(chat_id),
        "creator_id": int(creator.get("id", 0)),
        "status": "waiting",

        # Danh sách theo đúng thứ tự bấm tham gia
        "players": [],

        # Thứ tự chơi sau khi random
        "order": [],

        "turn_index": 0,

        # Từ hiện tại
        "current_word": "",

        # Thống kê
        "total_turns": 0,
        "correct_turns": 0,

        # Thời gian
        "created_at": time.time(),
        "started_at": None,
        "last_turn_at": None,

        # Thống kê từng người
        "stats": {},

        # Tin nhắn lobby
        "lobby_message_id": None
    }

    with NOICHU_LOCK:
        NOICHU_GAMES[int(chat_id)] = game

    return game


def noichu_add_player(game, user):
    user_id = int(user.get("id", 0))

    if not user_id:
        return False, "Không xác định được người chơi."

    if noichu_player_exists(game, user_id):
        return False, "Bạn đã tham gia trò chơi rồi."

    player = {
        "id": user_id,
        "name": noichu_display_name(user),
        "username": user.get("username") or "",
        "joined_at": time.time()
    }

    game["players"].append(player)

    game["stats"][str(user_id)] = {
        "turns": 0,
        "correct": 0,
        "wrong": 0,
        "response_times": []
    }

    return True, player["name"]


def noichu_remove_player(game, user_id):
    user_id = int(user_id)

    game["players"] = [
        player
        for player in game.get("players", [])
        if int(player["id"]) != user_id
    ]

    game["order"] = [
        player_id
        for player_id in game.get("order", [])
        if int(player_id) != user_id
    ]


def noichu_current_player_id(game):
    order = game.get("order", [])

    if not order:
        return None

    if game["turn_index"] >= len(order):
        game["turn_index"] = 0

    return int(order[game["turn_index"]])


def noichu_next_turn(game):
    if not game.get("order"):
        return

    game["turn_index"] += 1

    if game["turn_index"] >= len(game["order"]):
        game["turn_index"] = 0


def noichu_make_player_list(game):
    players = game.get("players", [])

    if not players:
        return "Chưa có người chơi nào."

    lines = []

    for index, player in enumerate(players, 1):
        player_id = int(player["id"])

        current_mark = ""

        if (
            game.get("status") == "playing"
            and noichu_current_player_id(game) == player_id
        ):
            current_mark = " 🎯"

        lines.append(
            f"{index}. {player.get('name', 'Người chơi')}{current_mark}"
        )

    return "\n".join(lines)


def noichu_send_players(chat_id):
    game = noichu_get_game(chat_id)

    if not game:
        send_text(
            chat_id,
            "❌ Hiện tại nhóm chưa có trò chơi nối chữ."
        )
        return

    if game["status"] == "waiting":
        title = "🎮 DANH SÁCH NGƯỜI ĐĂNG KÝ"
    else:
        title = "🎮 DANH SÁCH NGƯỜI CHƠI"

    text = (
        f"{title}\n\n"
        f"{noichu_make_player_list(game)}\n\n"
        f"👥 Tổng: {len(game.get('players', []))} người"
    )

    send_text(chat_id, text)


def noichu_start_game(chat_id, game_id):
    game = noichu_get_game(chat_id)

    if not game:
        return

    if game.get("id") != game_id:
        return

    if game.get("status") != "waiting":
        return

    players = list(game.get("players", []))

    # Phải có ít nhất 2 người
    if len(players) < 2:
        game["status"] = "ended"

        send_text(
            chat_id,
            "❌ Trò chơi nối chữ đã bị hủy.\n\n"
            "Lý do: cần ít nhất 2 người chơi."
        )

        with NOICHU_LOCK:
            if NOICHU_GAMES.get(int(chat_id)) is game:
                NOICHU_GAMES.pop(int(chat_id), None)

        return

    # Random thứ tự chơi
    random.shuffle(players)

    game["order"] = [
        int(player["id"])
        for player in players
    ]

    game["turn_index"] = 0
    game["current_word"] = ""
    game["status"] = "playing"
    game["started_at"] = time.time()
    game["last_turn_at"] = time.time()

    first_player = noichu_current_player_id(game)
    first_name = noichu_player_name_from_game(game, first_player)

    send_text(
        chat_id,
        "🔥 TRÒ CHƠI NỐI CHỮ VIỆT NAM BẮT ĐẦU!\n\n"
        "🎲 Thứ tự người chơi đã được random.\n"
        f"👑 Người đi đầu tiên: {first_name}\n\n"
        "📌 Luật chơi:\n"
        "• Người đầu tiên được nói bất kỳ từ/cụm từ hợp lệ.\n"
        "• Người tiếp theo phải bắt đầu bằng từ cuối của lượt trước.\n"
        "• Nói sai sẽ bị loại.\n"
        "• Nói khi chưa tới lượt sẽ bị cảnh báo.\n"
        "• Người cuối cùng còn lại là người chiến thắng.\n\n"
        f"🎯 Lượt của: {first_name}"
    )


def noichu_schedule_start(chat_id, game_id):
    def worker():
        try:
            # Chờ đúng 3 phút
            time.sleep(180)

            noichu_start_game(chat_id, game_id)

        except Exception as e:
            logging.exception(
                "Lỗi khởi động game nối chữ: %s",
                e
            )

    thread = threading.Thread(
        target=worker,
        daemon=True
    )

    thread.start()


def cmd_noichu(message, args):
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    # Chỉ cho phép trong nhóm
    if not is_group_chat(message):
        send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    existing = noichu_get_game(chat_id)

    if existing and existing.get("status") in ("waiting", "playing"):
        if existing.get("status") == "waiting":
            send_text(
                chat_id,
                "⚠️ Nhóm đang có một phòng nối chữ đang chờ người chơi.\n\n"
                "Hãy bấm nút 🎮 THAM GIA ở tin nhắn phòng hiện tại."
            )
        else:
            current_id = noichu_current_player_id(existing)
            current_name = noichu_player_name_from_game(
                existing,
                current_id
            )

            send_text(
                chat_id,
                "⚠️ Nhóm đang có một ván nối chữ đang diễn ra.\n\n"
                f"🎯 Hiện tại là lượt của: {current_name}"
            )

        return

    creator = message.get("from", {})

    game = noichu_create_game(
        chat_id,
        creator
    )

    text = (
        "welcome đến với nối chữ Việt Nam vui lòng bấm vào nút "
        "tham gia để vào trò chơi\n\n"
        "🎮 NỐI CHỮ VIỆT NAM\n\n"
        "👥 Người chơi đã tham gia: 0\n"
        "👤 Tối thiểu: 2 người\n\n"
        "⏰ Trò chơi sẽ bắt đầu sau 3 phút.\n"
        "🎲 Thứ tự chơi sẽ được random khi bắt đầu.\n\n"
        "📌 Ai bấm tham gia trước sẽ có số thứ tự đăng ký trước."
    )

    result = send_text(
        chat_id,
        text,
        reply_markup=noichu_make_join_keyboard()
    )

    if isinstance(result, dict):
        game["lobby_message_id"] = (
            result.get("result", {}).get("message_id")
        )

    # Tự động bắt đầu sau 3 phút
    noichu_schedule_start(
        chat_id,
        game["id"]
    )


def handle_noichu_join_callback(callback):
    callback_id = callback.get("id")
    from_user = callback.get("from", {})
    message = callback.get("message", {})

    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not chat_id:
        return

    game = noichu_get_game(chat_id)

    if not game:
        answer_callback_query(
            callback_id,
            "❌ Phòng chơi không còn tồn tại.",
            True
        )
        return

    if game.get("status") != "waiting":
        answer_callback_query(
            callback_id,
            "❌ Trò chơi đã bắt đầu.",
            True
        )
        return

    user_id = int(from_user.get("id", 0))

    if noichu_player_exists(game, user_id):
        answer_callback_query(
            callback_id,
            "⚠️ Bạn đã tham gia rồi!",
            True
        )
        return

    success, result = noichu_add_player(
        game,
        from_user
    )

    if not success:
        answer_callback_query(
            callback_id,
            result,
            True
        )
        return

    position = len(game["players"])

    answer_callback_query(
        callback_id,
        f"🎮 Tham gia thành công! Bạn là người thứ {position}.",
        False
    )

    player_list = noichu_make_player_list(game)

    lobby_text = (
        "welcome đến với nối chữ Việt Nam vui lòng bấm vào nút "
        "tham gia để vào trò chơi\n\n"
        "🎮 NỐI CHỮ VIỆT NAM\n\n"
        f"👥 Người chơi: {len(game['players'])}\n\n"
        f"{player_list}\n\n"
        "⏰ Trò chơi sẽ bắt đầu sau 3 phút.\n"
        "🎲 Thứ tự chơi sẽ được random khi bắt đầu."
    )

    # Cập nhật tin nhắn lobby
    if game.get("lobby_message_id"):
        edit_message_text(
            chat_id,
            game["lobby_message_id"],
            lobby_text,
            reply_markup=noichu_make_join_keyboard()
        )


def handle_noichu_players_callback(callback):
    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if chat_id:
        noichu_send_players(chat_id)

    answer_callback_query(
        callback_id,
        "📋 Đã hiển thị danh sách.",
        False
    )


def noichu_is_valid_move(game, text):
    words = noichu_words(text)

    if not words:
        return False, "Bạn chưa nhập từ."

    current_word = noichu_clean_text(
        game.get("current_word", "")
    )

    # Lượt đầu tiên
    if not current_word:
        return True, ""

    required = noichu_last_word(current_word)

    first = words[0]

    if first != required:
        return (
            False,
            f"❌ Phải bắt đầu bằng từ: {required}"
        )

    return True, ""


def noichu_calculate_achievement(game, user_id):
    stats = game.get("stats", {}).get(str(user_id), {})

    turns = int(stats.get("turns", 0))
    correct = int(stats.get("correct", 0))
    response_times = stats.get("response_times", [])

    if turns <= 0:
        return 0

    accuracy = (
        correct / turns
    ) * 100

    if response_times:
        average_time = sum(response_times) / len(response_times)

        # <= 5 giây và trả lời chính xác toàn bộ
        # được tính 100%
        if correct == turns and average_time <= 5:
            return 100

        speed_score = max(
            0,
            min(
                100,
                100 - int(average_time * 5)
            )
        )
    else:
        speed_score = 0

    achievement = int(
        accuracy * 0.7 +
        speed_score * 0.3
    )

    return max(
        0,
        min(100, achievement)
    )


def noichu_finish_game(chat_id, winner_id=None):
    game = noichu_get_game(chat_id)

    if not game:
        return

    if game.get("status") == "ended":
        return

    game["status"] = "ended"

    players = game.get("players", [])

    if winner_id is None:
        text = (
            "🏁 VÁN NỐI CHỮ ĐÃ KẾT THÚC.\n\n"
            "❌ Không còn người chơi."
        )
    else:
        winner_id = int(winner_id)

        winner_name = noichu_player_name_from_game(
            game,
            winner_id
        )

        achievement = noichu_calculate_achievement(
            game,
            winner_id
        )

        text = (
            "🏆🏆🏆 KẾT THÚC TRÒ CHƠI! 🏆🏆🏆\n\n"
            f"👑 Người chiến thắng: {winner_name}\n"
            f"🎯 Thành tích: {achievement}%\n\n"
        )

        if achievement >= 100:
            text += (
                "🔥 Thành tích 100%!\n"
                "⚡ Nhanh + chính xác + chơi tốt!"
            )
        elif achievement >= 80:
            text += "🔥 Thành tích rất tốt!"
        elif achievement >= 60:
            text += "👍 Thành tích tốt!"
        else:
            text += "💪 Hãy luyện tập để đạt thành tích cao hơn!"

    send_text(chat_id, text)

    with NOICHU_LOCK:
        if NOICHU_GAMES.get(int(chat_id)) is game:
            NOICHU_GAMES.pop(int(chat_id), None)


def handle_noichu_message(message):
    """
    Xử lý tin nhắn thông thường trong khi game đang diễn ra.
    Không yêu cầu bot phải là admin.
    """

    if not is_group_chat(message):
        return False

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return False

    game = noichu_get_game(chat_id)

    if not game:
        return False

    if game.get("status") != "playing":
        return False

    user = message.get("from", {})

    if not user:
        return False

    user_id = int(user.get("id", 0))

    # Chỉ xử lý người đang tham gia
    if not noichu_player_exists(game, user_id):
        return False

    current_id = noichu_current_player_id(game)

    # Người chơi không tới lượt
    if current_id != user_id:
        current_name = noichu_player_name_from_game(
            game,
            current_id
        )

        send_text(
            chat_id,
            f"⏳ Chưa tới lượt của bạn!\n"
            f"🎯 Hiện tại là lượt của: {current_name}"
        )

        return True

    text = message.get("text", "")

    if not text:
        return False

    # Không xử lý command
    if text.startswith("/"):
        return False

    # Kiểm tra từ
    valid, reason = noichu_is_valid_move(
        game,
        text
    )

    player_stats = game["stats"].setdefault(
        str(user_id),
        {
            "turns": 0,
            "correct": 0,
            "wrong": 0,
            "response_times": []
        }
    )

    now = time.time()

    last_turn_at = game.get("last_turn_at")

    if last_turn_at:
        response_time = max(
            0,
            now - float(last_turn_at)
        )
    else:
        response_time = 0

    player_stats["turns"] += 1

    game["total_turns"] += 1

    if not valid:
        player_stats["wrong"] += 1

        noichu_name = noichu_player_name_from_game(
            game,
            user_id
        )

        # Loại người chơi
        noichu_remove_player(
            game,
            user_id
        )

        send_text(
            chat_id,
            f"❌ {noichu_name} đã bị loại!\n\n"
            f"📛 Lý do: {reason}\n"
            "🚫 Trả lời không đúng luật nối chữ."
        )

        # Nếu chỉ còn 1 người
        if len(game.get("players", [])) == 1:
            winner_id = int(
                game["players"][0]["id"]
            )

            noichu_finish_game(
                chat_id,
                winner_id
            )

            return True

        # Nếu không còn ai
        if len(game.get("players", [])) == 0:
            noichu_finish_game(
                chat_id,
                None
            )

            return True

        # Người vừa bị loại có thể đang nằm trong order
        game["order"] = [
            player_id
            for player_id in game["order"]
            if int(player_id) != user_id
        ]

        if game["turn_index"] >= len(game["order"]):
            game["turn_index"] = 0

        game["last_turn_at"] = time.time()

        current_id = noichu_current_player_id(game)

        current_name = noichu_player_name_from_game(
            game,
            current_id
        )

        send_text(
            chat_id,
            f"🎯 Lượt tiếp theo: {current_name}"
        )

        return True

    # Trả lời đúng
    player_stats["correct"] += 1
    player_stats["response_times"].append(
        response_time
    )

    game["correct_turns"] += 1

    game["current_word"] = noichu_clean_text(text)

    # Sang người tiếp theo
    noichu_next_turn(game)

    game["last_turn_at"] = time.time()

    current_id = noichu_current_player_id(game)

    current_name = noichu_player_name_from_game(
        game,
        current_id
    )

    achievement = noichu_calculate_achievement(
        game,
        user_id
    )

    send_text(
        chat_id,
        f"✅ {noichu_display_name(user)} nối đúng!\n\n"
        f"🔗 Từ vừa nói: {text.strip()}\n"
        f"📊 Thành tích hiện tại: {achievement}%\n\n"
        f"🎯 Lượt tiếp theo: {current_name}"
    )

    return True


def handle_noichu_callback(callback):
    data = callback.get("data", "")

    if data == "noichu_join":
        handle_noichu_join_callback(callback)
        return True

    if data == "noichu_players":
        handle_noichu_players_callback(callback)
        return True

    return False


# ============================================================
# KẾT THÚC PHẦN 8/15
# ============================================================

# ============================================================
# PHẦN 9/15 — TIỆN ÍCH + THÔNG TIN NHÓM
# ============================================================

def cmd_id(message, args):
    """
    /id
    Hiển thị ID của người dùng hoặc người được reply.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    target = get_reply_user(message)

    if target:
        user_id = target.get("id")
        name = tg_username(target) or (
            f"{target.get('first_name', '')} "
            f"{target.get('last_name', '')}"
        ).strip()

        send_text(
            chat_id,
            "🆔 THÔNG TIN NGƯỜI DÙNG\n\n"
            f"👤 Người dùng: {name or 'Không có tên'}\n"
            f"🆔 ID: {user_id}"
        )
        return

    user = message.get("from", {})

    send_text(
        chat_id,
        "🆔 THÔNG TIN CỦA BẠN\n\n"
        f"👤 Người dùng: {tg_username(user) or user.get('first_name', 'Không có tên')}\n"
        f"🆔 ID: {user.get('id')}"
    )


def cmd_chatid(message, args):
    """
    /chatid
    Hiển thị ID nhóm/chat hiện tại.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    chat = message.get("chat", {})

    send_text(
        chat_id,
        "💬 THÔNG TIN CHAT\n\n"
        f"🆔 Chat ID: {chat_id}\n"
        f"📌 Loại: {chat.get('type', 'unknown')}\n"
        f"📛 Tên: {chat.get('title') or chat.get('first_name') or 'Không có'}"
    )


def cmd_info(message, args):
    """
    /info
    Hiển thị thông tin người dùng.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    target = get_reply_user(message)

    if not target:
        target = message.get("from", {})

    user_id = target.get("id")
    username = target.get("username")
    first_name = target.get("first_name", "")
    last_name = target.get("last_name", "")

    full_name = (
        f"{first_name} {last_name}"
    ).strip()

    if not full_name:
        full_name = "Không có tên"

    if username:
        username_text = f"@{username}"
    else:
        username_text = "Không có username"

    save_known_profile(target)

    send_text(
        chat_id,
        "👤 THÔNG TIN NGƯỜI DÙNG\n\n"
        f"📛 Tên: {full_name}\n"
        f"🔗 Username: {username_text}\n"
        f"🆔 ID: {user_id}\n"
        f"🤖 Bot: {'Có' if target.get('is_bot') else 'Không'}"
    )


def cmd_groupinfo(message, args):
    """
    /groupinfo
    Thông tin nhóm.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    if not is_group_chat(message):
        send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    chat = message.get("chat", {})

    member_count = get_group_member_count(
        chat_id
    )

    title = chat.get("title") or "Không có tên"

    username = chat.get("username")

    if username:
        username_text = f"@{username}"
    else:
        username_text = "Không có"

    send_text(
        chat_id,
        "🏠 THÔNG TIN NHÓM\n\n"
        f"📛 Tên nhóm: {title}\n"
        f"🆔 ID nhóm: {chat_id}\n"
        f"🔗 Username: {username_text}\n"
        f"👥 Thành viên: {member_count}"
    )


def cmd_members(message, args):
    """
    /members
    Hiển thị số thành viên.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    if not is_group_chat(message):
        send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    count = get_group_member_count(
        chat_id
    )

    send_text(
        chat_id,
        f"👥 Nhóm hiện có khoảng {count} thành viên."
    )


def cmd_rules(message, args):
    """
    /rules
    Hiển thị nội quy cơ bản.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    if not is_group_chat(message):
        send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    rules = get_setting(
        chat_id,
        "group_rules",
        ""
    )

    if not rules:
        rules = (
            "📜 NỘI QUY NHÓM\n\n"
            "1. Tôn trọng mọi người.\n"
            "2. Không spam tin nhắn.\n"
            "3. Không gửi link quảng cáo trái phép.\n"
            "4. Không giả mạo thành viên khác.\n"
            "5. Không sử dụng bot để phá nhóm.\n"
            "6. Tuân thủ hướng dẫn của quản trị viên."
        )

    send_text(
        chat_id,
        rules
    )


def cmd_setrules(message, args):
    """
    /setrules <nội quy>
    Quản trị viên đặt nội quy nhóm.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    if not is_group_chat(message):
        send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    if not is_admin(message):
        send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được sử dụng lệnh này."
        )
        return

    rules = " ".join(args).strip()

    if not rules:
        send_text(
            chat_id,
            "❌ Cách dùng:\n/setrules <nội quy mới>"
        )
        return

    set_setting(
        chat_id,
        "group_rules",
        rules
    )

    send_text(
        chat_id,
        "✅ Đã cập nhật nội quy nhóm."
    )


def cmd_setwelcome(message, args):
    """
    /setwelcome <nội dung>
    Đặt lời chào thành viên mới.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    if not is_group_chat(message):
        send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    if not is_admin(message):
        send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được sử dụng lệnh này."
        )
        return

    welcome = " ".join(args).strip()

    if not welcome:
        send_text(
            chat_id,
            "❌ Cách dùng:\n/setwelcome <nội dung>"
        )
        return

    set_setting(
        chat_id,
        "welcome_text",
        welcome
    )

    send_text(
        chat_id,
        "✅ Đã lưu lời chào thành viên mới."
    )


def cmd_delwelcome(message, args):
    """
    /delwelcome
    Xóa lời chào thành viên mới.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    if not is_group_chat(message):
        send_text(
            chat_id,
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    if not is_admin(message):
        send_text(
            chat_id,
            "❌ Chỉ quản trị viên mới được sử dụng lệnh này."
        )
        return

    set_setting(
        chat_id,
        "welcome_text",
        ""
    )

    send_text(
        chat_id,
        "✅ Đã xóa lời chào thành viên mới."
    )


def handle_new_members(message):
    """
    Tự động chào thành viên mới.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    new_members = message.get(
        "new_chat_members",
        []
    )

    if not new_members:
        return False

    welcome = get_setting(
        chat_id,
        "welcome_text",
        ""
    )

    for user in new_members:
        save_known_profile(user)

    if not welcome:
        return True

    names = []

    for user in new_members:
        names.append(
            mention_user(user)
        )

    names_text = ", ".join(names)

    welcome = welcome.replace(
        "{user}",
        names_text
    )

    send_text(
        chat_id,
        welcome
    )

    return True


def handle_left_member(message):
    """
    Xử lý thành viên rời nhóm.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return False

    left_member = message.get(
        "left_chat_member"
    )

    if not left_member:
        return False

    return True


def cmd_setnick(message, args):
    """
    /setnick <tên>
    Lưu tên hiển thị tùy chỉnh cho người dùng.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    user = message.get("from", {})

    nickname = " ".join(args).strip()

    if not nickname:
        send_text(
            chat_id,
            "❌ Cách dùng:\n/setnick <tên>"
        )
        return

    db_execute(
        """
        INSERT INTO users(
            user_id,
            username,
            first_name,
            last_name,
            messages,
            level,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, 0, 1, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name = excluded.first_name,
            updated_at = excluded.updated_at
        """,
        (
            int(user.get("id", 0)),
            user.get("username"),
            nickname,
            user.get("last_name"),
            int(time.time()),
            int(time.time())
        )
    )

    send_text(
        chat_id,
        f"✅ Đã đặt tên hiển thị của bạn thành: {nickname}"
    )


def cmd_ping(message, args):
    """
    /ping
    Kiểm tra bot còn hoạt động.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    start = time.time()

    result = send_text(
        chat_id,
        "🏓 Pong!"
    )

    elapsed = int(
        (time.time() - start) * 1000
    )

    send_text(
        chat_id,
        f"⚡ Bot đang hoạt động.\n"
        f"⏱ Phản hồi: {elapsed} ms"
    )


def cmd_time(message, args):
    """
    /time
    Hiển thị thời gian hiện tại.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    now = datetime.datetime.now()

    send_text(
        chat_id,
        "🕐 THỜI GIAN HIỆN TẠI\n\n"
        f"📅 Ngày: {now.strftime('%d/%m/%Y')}\n"
        f"⏰ Giờ: {now.strftime('%H:%M:%S')}"
    )


def cmd_uptime(message, args):
    """
    /uptime
    Hiển thị thời gian bot đã chạy.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    current = time.time()

    bot_started = globals().get(
        "BOT_STARTED_AT",
        current
    )

    seconds = max(
        0,
        int(current - bot_started)
    )

    days = seconds // 86400
    seconds %= 86400

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60
    seconds %= 60

    parts = []

    if days:
        parts.append(f"{days} ngày")

    if hours:
        parts.append(f"{hours} giờ")

    if minutes:
        parts.append(f"{minutes} phút")

    parts.append(f"{seconds} giây")

    send_text(
        chat_id,
        "⏱ BOT UPTIME\n\n"
        + " ".join(parts)
    )


def cmd_botinfo(message, args):
    """
    /botinfo
    Thông tin bot Ngọc Mỹ.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    send_text(
        chat_id,
        "🤖 NGỌC MỸ BOT\n\n"
        "✨ Bot quản lý nhóm Telegram\n"
        "🛡 Bảo vệ nhóm\n"
        "🎮 Trò chơi\n"
        "📈 Hệ thống level\n"
        "🔥 Điểm danh\n"
        "💬 Bộ lọc\n"
        "🌙 AFK\n"
        "🌸 Thơ đời / thơ tình\n"
        "🔗 Nối chữ Việt Nam\n\n"
        "👑 Owner: @DTN_207"
    )


def cmd_stats(message, args):
    """
    /stats
    Thống kê tin nhắn của người dùng.
    """

    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    target = get_reply_user(message)

    if not target:
        target = message.get("from", {})

    user_id = int(
        target.get("id", 0)
    )

    row = db_fetchone(
        """
        SELECT messages, level
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    )

    if not row:
        messages = 0
        level = 1
    else:
        messages = int(
            row["messages"] or 0
        )
        level = int(
            row["level"] or 1
        )

    name = tg_username(target)

    if not name:
        name = target.get(
            "first_name",
            "Người dùng"
        )

    send_text(
        chat_id,
        "📊 THỐNG KÊ\n\n"
        f"👤 {name}\n"
        f"💬 Tin nhắn: {messages}\n"
        f"⭐ Level: {level}"
    )


# ============================================================
# KẾT THÚC PHẦN 9/15
# ============================================================

# ============================================================
# PHẦN 10/15 — CALLBACK + MENU + HELP ĐẦY ĐỦ
# ============================================================

def answer_callback_query(callback_id, text="", show_alert=False):
    if not callback_id:
        return

    tg_call(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text or "",
            "show_alert": bool(show_alert)
        }
    )


def edit_message_text(
    chat_id,
    message_id,
    text,
    reply_markup=None
):
    if not chat_id or not message_id:
        return None

    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }

    if reply_markup is not None:
        data["reply_markup"] = reply_markup

    return tg_call(
        "editMessageText",
        data
    )


def build_help_text():
    return (
        "🤖 NGỌC MỸ — DANH SÁCH LỆNH\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "📌 CƠ BẢN\n"
        "/start — Mở menu chính.\n"
        "/help — Xem danh sách lệnh.\n"
        "/ping — Kiểm tra bot.\n"
        "/time — Xem thời gian.\n"
        "/uptime — Xem thời gian bot đã chạy.\n"
        "/botinfo — Thông tin bot.\n"
        "/id — Xem ID người dùng.\n"
        "/chatid — Xem ID chat.\n"
        "/info — Xem thông tin người dùng.\n"
        "/stats — Xem thống kê tin nhắn/level.\n\n"

        "👥 THÔNG TIN NHÓM\n"
        "/groupinfo — Xem thông tin nhóm.\n"
        "/members — Xem số thành viên.\n"
        "/rules — Xem nội quy nhóm.\n"
        "/setrules <nội dung> — Đặt nội quy nhóm.\n"
        "/setwelcome <nội dung> — Đặt lời chào thành viên mới.\n"
        "/delwelcome — Xóa lời chào.\n"
        "/setnick <tên> — Đặt tên hiển thị.\n\n"

        "🛡 QUẢN LÝ NHÓM\n"
        "/ban — Cấm thành viên.\n"
        "Cách dùng: reply tin nhắn người đó + /ban\n\n"
        "/unban <ID> — Gỡ cấm thành viên.\n"
        "/kick — Đuổi thành viên khỏi nhóm.\n"
        "Cách dùng: reply tin nhắn + /kick\n\n"
        "/mute — Tắt quyền nhắn tin.\n"
        "Cách dùng: reply tin nhắn + /mute\n\n"
        "/unmute — Mở quyền nhắn tin.\n"
        "/warn — Cảnh cáo thành viên.\n"
        "/unwarn — Gỡ cảnh cáo.\n"
        "/promote — Thăng quản trị viên.\n"
        "/demote — Hạ quản trị viên.\n"
        "/pin — Ghim tin nhắn.\n"
        "/unpin — Bỏ ghim tin nhắn.\n\n"

        "🛡 BẢO VỆ NHÓM\n"
        "/antispam on — Bật chống spam.\n"
        "/antispam off — Tắt chống spam.\n"
        "/antilink on — Chặn link.\n"
        "/antilink off — Cho phép link.\n"
        "/antibuff on — Chống buff thành viên.\n"
        "/antibuff off — Tắt chống buff.\n"
        "/antifake on — Chống tài khoản giả mạo.\n"
        "/antifake off — Tắt chống fake.\n"
        "/protect on — Bật bảo vệ tổng hợp.\n"
        "/protect off — Tắt bảo vệ tổng hợp.\n\n"

        "🌙 AFK\n"
        "/afk <lý do> — Bật trạng thái AFK.\n"
        "Gửi tin nhắn lại để hủy AFK.\n\n"

        "🔎 FILTER\n"
        "/filter <từ> <nội dung> — Tạo bộ lọc.\n"
        "/filters — Xem bộ lọc.\n"
        "/stopfilter <từ> — Xóa bộ lọc.\n\n"

        "🔥 ĐIỂM DANH\n"
        "/diemdanh — Mở điểm danh hằng ngày.\n"
        "Bấm nút 🔥 Điểm danh để nhận streak.\n\n"

        "⭐ LEVEL\n"
        "/level — Xem hệ thống level.\n"
        "/levelyou — Xem level của bạn.\n"
        "/levelbxh — Xem bảng xếp hạng level.\n"
        "/leveldanhsach — Xem điều kiện lên level.\n"
        "/levelnhiemvu — Xem nhiệm vụ level.\n\n"

        "🎮 TRÒ CHƠI\n"
        "/noichu — Tạo phòng Nối Chữ Việt Nam.\n"
        "Cần ít nhất 2 người chơi.\n"
        "Phòng chờ 3 phút rồi random lượt chơi.\n"
        "Bot không cần quyền admin để chạy trò chơi.\n\n"

        "🌸 THƠ\n"
        "/thodoi — Nhận một bài thơ đời ngẫu nhiên.\n"
        "/thotinh — Nhận một bài thơ tình ngẫu nhiên.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Lệnh quản lý nhóm cần quyền quản trị.\n"
        "🎮 Nối chữ có thể chơi không cần bot admin.\n"
        "🤖 Ngọc Mỹ không sử dụng chức năng AI.\n\n"
        "👑 Owner: @DTN_207"
    )


def cmd_help(message, args):
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    # /help trong nhóm
    if is_group_chat(message):
        send_text(
            chat_id,
            "❌ /help chỉ được sử dụng trong tin nhắn riêng với bot."
        )
        return

    send_text(
        chat_id,
        build_help_text()
    )


def cmd_menu(message, args):
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    if is_group_chat(message):
        send_text(
            chat_id,
            "❌ Menu chỉ được sử dụng trong tin nhắn riêng với bot."
        )
        return

    send_start_menu(
        chat_id,
        message.get("from", {})
    )


def build_main_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📚 HELP",
                    "callback_data": "menu_help"
                },
                {
                    "text": "🛡 BẢO VỆ",
                    "callback_data": "menu_protect"
                }
            ],
            [
                {
                    "text": "👮 QUẢN LÝ",
                    "callback_data": "menu_admin"
                },
                {
                    "text": "🎮 TRÒ CHƠI",
                    "callback_data": "menu_game"
                }
            ],
            [
                {
                    "text": "⭐ LEVEL",
                    "callback_data": "menu_level"
                },
                {
                    "text": "🌸 THƠ",
                    "callback_data": "menu_poem"
                }
            ]
        ]
    }


def send_start_menu(chat_id, user=None):
    name = "bạn"

    if user:
        name = (
            user.get("first_name")
            or user.get("username")
            or "bạn"
        )

    text = (
        f"🤖 Xin chào {name}!\n\n"
        "🌸 Đây là bot Ngọc Mỹ.\n"
        "🛡 Quản lý và bảo vệ nhóm Telegram.\n"
        "🎮 Có trò chơi, level, điểm danh và thơ.\n\n"
        "👇 Chọn chức năng bên dưới:"
    )

    return send_text(
        chat_id,
        text,
        reply_markup=build_main_keyboard()
    )


def callback_menu_help(callback):
    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        answer_callback_query(
            callback_id,
            "Không xác định được chat.",
            True
        )
        return

    # Menu help chủ yếu dùng trong private
    edit_message_text(
        chat_id,
        message.get("message_id"),
        build_help_text(),
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "🔙 MENU",
                        "callback_data": "menu_main"
                    }
                ]
            ]
        }
    )

    answer_callback_query(
        callback_id,
        "📚 Đã mở danh sách lệnh."
    )


def callback_menu_protect(callback):
    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    text = (
        "🛡 BẢO VỆ NHÓM\n\n"
        "/antispam on — Chống spam.\n"
        "/antispam off — Tắt chống spam.\n\n"
        "/antilink on — Chặn link.\n"
        "/antilink off — Tắt chặn link.\n\n"
        "/antibuff on — Chống buff thành viên.\n"
        "/antibuff off — Tắt chống buff.\n\n"
        "/antifake on — Chống tài khoản giả.\n"
        "/antifake off — Tắt chống fake.\n\n"
        "/protect on — Bật bảo vệ tổng hợp.\n"
        "/protect off — Tắt bảo vệ tổng hợp."
    )

    edit_message_text(
        chat_id,
        message.get("message_id"),
        text,
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "🔙 MENU",
                        "callback_data": "menu_main"
                    }
                ]
            ]
        }
    )

    answer_callback_query(
        callback_id,
        "🛡 Bảo vệ"
    )


def callback_menu_admin(callback):
    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    text = (
        "👮 QUẢN LÝ NHÓM\n\n"
        "/ban — Cấm thành viên.\n"
        "/unban <ID> — Gỡ cấm.\n"
        "/kick — Đuổi thành viên.\n"
        "/mute — Khóa chat.\n"
        "/unmute — Mở chat.\n"
        "/warn — Cảnh cáo.\n"
        "/unwarn — Gỡ cảnh cáo.\n"
        "/promote — Thăng quản trị.\n"
        "/demote — Hạ quản trị.\n"
        "/pin — Ghim tin nhắn.\n"
        "/unpin — Bỏ ghim."
    )

    edit_message_text(
        chat_id,
        message.get("message_id"),
        text,
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "🔙 MENU",
                        "callback_data": "menu_main"
                    }
                ]
            ]
        }
    )

    answer_callback_query(
        callback_id,
        "👮 Quản lý"
    )


def callback_menu_game(callback):
    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    text = (
        "🎮 TRÒ CHƠI\n\n"
        "🔗 /noichu\n"
        "Tạo phòng Nối Chữ Việt Nam.\n\n"
        "👥 Tối thiểu 2 người.\n"
        "⏰ Chờ 3 phút.\n"
        "🎲 Random thứ tự.\n"
        "❌ Nói sai bị loại.\n"
        "🏆 Người cuối cùng thắng."
    )

    edit_message_text(
        chat_id,
        message.get("message_id"),
        text,
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "🔙 MENU",
                        "callback_data": "menu_main"
                    }
                ]
            ]
        }
    )

    answer_callback_query(
        callback_id,
        "🎮 Trò chơi"
    )


def callback_menu_level(callback):
    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    text = (
        "⭐ HỆ THỐNG LEVEL\n\n"
        "/level — Thông tin hệ thống.\n"
        "/levelyou — Level của bạn.\n"
        "/levelbxh — Bảng xếp hạng.\n"
        "/leveldanhsach — Điều kiện lên level.\n"
        "/levelnhiemvu — Nhiệm vụ level.\n\n"
        "📈 Level được tăng dựa trên số tin nhắn."
    )

    edit_message_text(
        chat_id,
        message.get("message_id"),
        text,
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "🔙 MENU",
                        "callback_data": "menu_main"
                    }
                ]
            ]
        }
    )

    answer_callback_query(
        callback_id,
        "⭐ Level"
    )


def callback_menu_poem(callback):
    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    text = (
        "🌸 THƠ\n\n"
        "/thodoi — Thơ đời ngẫu nhiên.\n"
        "/thotinh — Thơ tình ngẫu nhiên.\n\n"
        "✨ Mỗi lần dùng lệnh bot sẽ chọn một bài khác."
    )

    edit_message_text(
        chat_id,
        message.get("message_id"),
        text,
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "🔙 MENU",
                        "callback_data": "menu_main"
                    }
                ]
            ]
        }
    )

    answer_callback_query(
        callback_id,
        "🌸 Thơ"
    )


def callback_menu_main(callback):
    callback_id = callback.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    user = callback.get("from", {})

    text = (
        f"🤖 Xin chào {user.get('first_name', 'bạn')}!\n\n"
        "🌸 Ngọc Mỹ Bot\n"
        "👇 Chọn chức năng:"
    )

    edit_message_text(
        chat_id,
        message.get("message_id"),
        text,
        reply_markup=build_main_keyboard()
    )

    answer_callback_query(
        callback_id,
        "🔙 Menu chính"
    )


def handle_menu_callback(callback):
    data = callback.get("data", "")

    if data == "menu_main":
        callback_menu_main(callback)
        return True

    if data == "menu_help":
        callback_menu_help(callback)
        return True

    if data == "menu_protect":
        callback_menu_protect(callback)
        return True

    if data == "menu_admin":
        callback_menu_admin(callback)
        return True

    if data == "menu_game":
        callback_menu_game(callback)
        return True

    if data == "menu_level":
        callback_menu_level(callback)
        return True

    if data == "menu_poem":
        callback_menu_poem(callback)
        return True

    return False


# ============================================================
# KẾT THÚC PHẦN 10/15
# ============================================================

# ============================================================
# PHẦN 11/15 — COMMAND MAP + CALLBACK ROUTER
# ============================================================

# Toàn bộ command của Ngọc Mỹ.
# Không có /ai và không có bất kỳ chức năng AI nào.

def cmd_start(message):
    """
    /start - mở menu chính của Ngọc Mỹ.
    """
    try:
        return send_start_menu(message)
    except Exception:
        logging.exception("cmd_start lỗi")

        try:
            chat_id = message["chat"]["id"]
            send_message(
                chat_id,
                "❌ Không thể mở menu. Vui lòng thử lại."
            )
        except Exception:
            pass

        return False

COMMAND_HANDLERS = {
    # Cơ bản
    "start": cmd_start,
    "help": cmd_help,
    "menu": cmd_menu,
    "ping": cmd_ping,
    "time": cmd_time,
    "uptime": cmd_uptime,
    "botinfo": cmd_botinfo,
    "id": cmd_id,
    "chatid": cmd_chatid,
    "info": cmd_info,
    "stats": cmd_stats,

    # Thông tin nhóm
    "groupinfo": cmd_groupinfo,
    "members": cmd_members,
    "rules": cmd_rules,
    "setrules": cmd_setrules,
    "setwelcome": cmd_setwelcome,
    "delwelcome": cmd_delwelcome,
    "setnick": cmd_setnick,

    # Quản lý
    "ban": cmd_ban,
    "unban": cmd_unban,
    "kick": cmd_kick,
    "mute": cmd_mute,
    "unmute": cmd_unmute,
    "warn": cmd_warn,
    "unwarn": cmd_unwarn,
    "promote": cmd_promote,
    "demote": cmd_demote,
    "pin": cmd_pin,
    "unpin": cmd_unpin,

    # Bảo vệ
    "antispam": cmd_antispam,
    "antilink": cmd_antilink,
    "antibuff": cmd_antibuff,
    "antifake": cmd_antifake,
    "protect": cmd_protect,

    # AFK
    "afk": cmd_afk,

    # Filter
    "filter": cmd_filter,
    "filters": cmd_filters,
    "stopfilter": cmd_stop_filter,

    # Điểm danh
    "diemdanh": cmd_diemdanh,

    # Level
    "level": cmd_level,
    "levelyou": cmd_levelyou,
    "levelbxh": cmd_levelbxh,
    "leveldanhsach": cmd_leveldanhsach,
    "levelnhiemvu": cmd_levelnhiemvu,

    # Trò chơi
    "noichu": cmd_noichu,

    # Thơ
    "thodoi": cmd_thodoi,
    "thotinh": cmd_thotinh,
}


def is_known_command(command):
    if not command:
        return False

    command = command.lower().lstrip("/")

    # Telegram có thể gửi /command@BotUsername
    if "@" in command:
        command = command.split("@", 1)[0]

    return command in COMMAND_HANDLERS


def normalize_command(command):
    if not command:
        return ""

    command = command.lower().strip()

    if command.startswith("/"):
        command = command[1:]

    if "@" in command:
        command = command.split("@", 1)[0]

    return command


def dispatch_command_clean(message):
    """
    Dispatcher duy nhất cho command.
    Không gọi dispatcher cũ.
    """

    command, args = parse_command(message)

    if not command:
        return False

    command = normalize_command(command)

    handler = COMMAND_HANDLERS.get(command)

    if not handler:
        return False

    try:
        handler(
            message,
            args
        )

        return True

    except Exception as e:
        logging.exception(
            "Lỗi command /%s: %s",
            command,
            e
        )

        chat_id = message.get(
            "chat",
            {}
        ).get("id")

        if chat_id:
            send_text(
                chat_id,
                "❌ Đã xảy ra lỗi khi xử lý lệnh.\n"
                "Vui lòng thử lại."
            )

        return True


def dispatch_callback_clean(callback):
    """
    Router callback duy nhất.
    """

    if not callback:
        return False

    data = callback.get("data", "")

    if not data:
        return False

    try:
        # Menu chính
        if handle_menu_callback(callback):
            return True

        # Nối chữ
        if handle_noichu_callback(callback):
            return True

        # Điểm danh
        if data.startswith("checkin_"):
            handle_checkin_callback(callback)
            return True

        return False

    except Exception as e:
        logging.exception(
            "Lỗi callback %s: %s",
            data,
            e
        )

        callback_id = callback.get("id")

        answer_callback_query(
            callback_id,
            "❌ Có lỗi xảy ra.",
            True
        )

        return True


def process_new_members(message):
    try:
        if handle_new_members(message):
            return True
    except Exception as e:
        logging.exception(
            "Lỗi new member: %s",
            e
        )

    return False


def process_left_member(message):
    try:
        if handle_left_member(message):
            return True
    except Exception as e:
        logging.exception(
            "Lỗi left member: %s",
            e
        )

    return False


def process_callback_query(update):
    callback = update.get("callback_query")

    if not callback:
        return False

    return dispatch_callback_clean(
        callback
    )


def process_command_update(update):
    message = update.get("message")

    if not message:
        return False

    text = message.get("text", "")

    if not text:
        return False

    if not text.startswith("/"):
        return False

    return dispatch_command_clean(
        message
    )


def process_game_message(message):
    """
    Xử lý tin nhắn cho Nối Chữ.
    """

    try:
        return handle_noichu_message(
            message
        )
    except Exception as e:
        logging.exception(
            "Lỗi Nối Chữ: %s",
            e
        )

    return False


def process_extra_message(message):
    """
    Xử lý AFK, filter, antispam, antilink,
    antibuff, antifake và level.
    """

    try:
        # Không xử lý command như tin nhắn game/bảo vệ
        text = message.get("text", "")

        if text and text.startswith("/"):
            return False

        # Nối chữ trước
        if process_game_message(message):
            return True

        # AFK
        if handle_afk_message(message):
            return True

        # Filter
        if handle_filter_message(message):
            return True

        # Protection
        if handle_protection(message):
            return True

        # Level
        if process_level_for_message(message):
            return True

        # Các feature phụ
        if handle_extra_message_features(message):
            return True

    except Exception as e:
        logging.exception(
            "Lỗi xử lý message: %s",
            e
        )

    return False


def process_message_update(update):
    message = update.get("message")

    if not message:
        return False

    # Lưu profile người dùng
    user = message.get("from")

    if user:
        try:
            save_known_profile(user)
        except Exception:
            pass

    # Thành viên mới
    if message.get("new_chat_members"):
        process_new_members(message)
        return True

    # Thành viên rời
    if message.get("left_chat_member"):
        process_left_member(message)
        return True

    # Command
    text = message.get("text", "")

    if text and text.startswith("/"):
        return process_command_update(
            update
        )

    # Tin nhắn thông thường
    return process_extra_message(
        message
    )


def process_update_clean(update):
    """
    Bộ xử lý update mới.
    Chỉ xử lý MỘT lần mỗi update.
    """

    if not isinstance(update, dict):
        return False

    try:
        # Callback
        if update.get("callback_query"):
            return process_callback_query(
                update
            )

        # Message
        if update.get("message"):
            return process_message_update(
                update
            )

        return False

    except Exception as e:
        logging.exception(
            "Lỗi process update: %s",
            e
        )

        return False


# ============================================================
# KIỂM TRA COMMAND MAP
# ============================================================

EXPECTED_COMMANDS = [
    "start",
    "help",
    "menu",

    "ping",
    "time",
    "uptime",
    "botinfo",
    "id",
    "chatid",
    "info",
    "stats",

    "groupinfo",
    "members",
    "rules",
    "setrules",
    "setwelcome",
    "delwelcome",
    "setnick",

    "ban",
    "unban",
    "kick",
    "mute",
    "unmute",
    "warn",
    "unwarn",
    "promote",
    "demote",
    "pin",
    "unpin",

    "antispam",
    "antilink",
    "antibuff",
    "antifake",
    "protect",

    "afk",

    "filter",
    "filters",
    "stopfilter",

    "diemdanh",

    "level",
    "levelyou",
    "levelbxh",
    "leveldanhsach",
    "levelnhiemvu",

    "noichu",

    "thodoi",
    "thotinh",
]


def validate_command_map():
    missing = []

    for command in EXPECTED_COMMANDS:
        if command not in COMMAND_HANDLERS:
            missing.append(command)

    # Cố tình kiểm tra AI không được xuất hiện
    forbidden_ai_commands = [
        "ai",
        "askai",
        "chatgpt",
        "openai"
    ]

    ai_found = [
        command
        for command in forbidden_ai_commands
        if command in COMMAND_HANDLERS
    ]

    if missing:
        logging.error(
            "COMMAND BỊ THIẾU: %s",
            ", ".join(missing)
        )

    if ai_found:
        logging.error(
            "PHÁT HIỆN COMMAND AI: %s",
            ", ".join(ai_found)
        )

        for command in ai_found:
            COMMAND_HANDLERS.pop(
                command,
                None
            )

    return (
        len(missing) == 0
        and len(ai_found) == 0
    )


# ============================================================
# KẾT THÚC PHẦN 11/15
# ============================================================

# ============================================================
# PHẦN 12/15 — POLLING TELEGRAM + CHỐNG TRÙNG UPDATE
# ============================================================

BOT_STARTED_AT = time.time()

# Lưu update_id đã xử lý để tránh một update chạy nhiều lần.
PROCESSED_UPDATE_IDS = set()

# Giới hạn số update lưu trong bộ nhớ.
MAX_PROCESSED_UPDATES = 5000

# Lock chống hai luồng xử lý cùng một update.
UPDATE_LOCK = threading.Lock()


def is_update_processed(update_id):
    if update_id is None:
        return False

    try:
        update_id = int(update_id)
    except Exception:
        return False

    with UPDATE_LOCK:
        return update_id in PROCESSED_UPDATE_IDS


def mark_update_processed(update_id):
    if update_id is None:
        return

    try:
        update_id = int(update_id)
    except Exception:
        return

    with UPDATE_LOCK:
        PROCESSED_UPDATE_IDS.add(update_id)

        # Không để bộ nhớ phình vô hạn.
        if len(PROCESSED_UPDATE_IDS) > MAX_PROCESSED_UPDATES:
            remove_count = (
                len(PROCESSED_UPDATE_IDS)
                - MAX_PROCESSED_UPDATES
            )

            # set không có thứ tự nên chỉ cần bỏ một phần tử.
            for _ in range(remove_count):
                try:
                    PROCESSED_UPDATE_IDS.pop()
                except KeyError:
                    break


def get_updates(offset=None, timeout=30):
    """
    Lấy update từ Telegram.
    """

    data = {
        "timeout": int(timeout),
        "allowed_updates": [
            "message",
            "callback_query"
        ]
    }

    if offset is not None:
        data["offset"] = int(offset)

    return tg_call(
        "getUpdates",
        data
    )

def tg_call(method, data=None, timeout=30):
    return telegram_request(
        method,
        data=data,
        timeout=timeout
    )

def delete_webhook():
    """
    Xóa webhook để bot sử dụng polling.
    """

    try:
        result = tg_call(
            "deleteWebhook",
            {
                "drop_pending_updates": False
            }
        )

        return bool(result)

    except Exception as e:
        logging.exception(
            "Không thể xóa webhook: %s",
            e
        )

        return False


def get_bot_information():
    """
    Kiểm tra token và thông tin bot.
    """

    try:
        result = tg_call(
            "getMe",
            {}
        )

        if not result:
            return None

        if isinstance(result, dict):
            return result.get(
                "result"
            )

        return None

    except Exception as e:
        logging.exception(
            "getMe lỗi: %s",
            e
        )

        return None


def process_update_once(update):
    """
    Chỉ xử lý một update đúng một lần.
    """

    if not isinstance(update, dict):
        return False

    update_id = update.get(
        "update_id"
    )

    # Telegram luôn có update_id.
    # Nếu không có thì vẫn xử lý để tránh bỏ update hợp lệ
    # từ những nguồn test nội bộ.
    if update_id is not None:
        if is_update_processed(update_id):
            logging.debug(
                "Bỏ qua update trùng: %s",
                update_id
            )
            return False

        mark_update_processed(
            update_id
        )

    return process_update_clean(
        update
    )


def polling_loop():
    """
    Vòng lặp polling duy nhất.

    Quan trọng:
    - Không gọi process_update cũ.
    - Không gọi _original_process_update.
    - Không gọi wrapper cũ.
    - Chỉ gọi process_update_once().
    """

    if not BOT_TOKEN:
        logging.error(
            "BOT_TOKEN chưa được cấu hình."
        )

        print(
            "❌ LỖI: Chưa có BOT_TOKEN."
        )

        return

    logging.info(
        "Đang kiểm tra bot..."
    )

    bot_info = get_bot_information()

    if not bot_info:
        logging.error(
            "BOT_TOKEN không hợp lệ hoặc Telegram không phản hồi."
        )

        print(
            "❌ Không thể kết nối Telegram."
        )

        return

    bot_username = bot_info.get(
        "username",
        ""
    )

    bot_first_name = bot_info.get(
        "first_name",
        "Ngọc Mỹ"
    )

    logging.info(
        "Bot đã kết nối: %s (@%s)",
        bot_first_name,
        bot_username
    )

    print(
        f"🤖 {bot_first_name}"
        + (
            f" (@{bot_username})"
            if bot_username
            else ""
        )
        + " đang chạy..."
    )

    # Polling không dùng webhook.
    delete_webhook()

    # Offset riêng của polling.
    next_offset = None

    while True:
        try:
            updates = get_updates(
                offset=next_offset,
                timeout=30
            )

            if not updates:
                continue

            # tg_call() thường trả về dict Telegram.
            if isinstance(updates, dict):
                updates_list = updates.get(
                    "result",
                    []
                )
            else:
                updates_list = updates

            if not isinstance(
                updates_list,
                list
            ):
                continue

            for update in updates_list:

                if not isinstance(
                    update,
                    dict
                ):
                    continue

                update_id = update.get(
                    "update_id"
                )

                # Luôn tiến offset lên sau khi Telegram
                # đã trả update.
                if update_id is not None:
                    try:
                        candidate = int(
                            update_id
                        ) + 1

                        if (
                            next_offset is None
                            or candidate > next_offset
                        ):
                            next_offset = candidate

                    except Exception:
                        pass

                try:
                    process_update_once(
                        update
                    )

                except Exception as e:
                    logging.exception(
                        "Lỗi xử lý update %s: %s",
                        update_id,
                        e
                    )

        except KeyboardInterrupt:
            logging.info(
                "Bot đã được dừng bằng bàn phím."
            )

            print(
                "\n🛑 Bot đã dừng."
            )

            break

        except Exception as e:
            logging.exception(
                "Polling error: %s",
                e
            )

            print(
                f"⚠️ Polling lỗi: {e}"
            )

            # Không thoát bot khi mạng chập chờn.
            time.sleep(3)


def run_bot():
    """
    Hàm khởi động chính.
    """

    global BOT_STARTED_AT

    BOT_STARTED_AT = time.time()

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        "🤖 NGỌC MỸ BOT"
    )

    print(
        "🛡 Telegram Group Manager"
    )

    print(
        "🎮 Nối Chữ Việt Nam"
    )

    print(
        "⭐ Level System"
    )

    print(
        "🔥 Điểm Danh"
    )

    print(
        "🌸 Thơ Đời / Thơ Tình"
    )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        "🤖 Chế độ AI: ĐÃ TẮT"
    )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    # Kiểm tra command map.
    if not validate_command_map():
        logging.warning(
            "Command map chưa hoàn chỉnh."
        )

    # Khởi tạo database.
    try:
        init_db()
    except Exception as e:
        logging.exception(
            "Không thể khởi tạo database: %s",
            e
        )

    # Bắt đầu polling.
    polling_loop()


# ============================================================
# KẾT THÚC PHẦN 12/15
# ============================================================

# ============================================================
# PHẦN 13/15
# DATABASE MIGRATION + COMPATIBILITY
# ============================================================

def db_fetchall(sql, params=()):
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(sql, params)
        return cursor.fetchall()
    finally:
        conn.close()

def ensure_db_column(table, column, definition):
    """
    Tự động thêm cột nếu database cũ chưa có.
    Không xóa dữ liệu cũ.
    """
    allowed_tables = {
        "users",
        "known_profiles",
        "levels",
        "settings",
        "warns",
        "filters",
        "afk",
        "checkins",
        "bot_bans",
    }

    if table not in allowed_tables:
        return

    try:
        columns = db_fetchall(f"PRAGMA table_info({table})")

        exists = False
        for row in columns:
            try:
                name = row["name"]
            except Exception:
                name = row[1]

            if name == column:
                exists = True
                break

        if not exists:
            db_execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    except Exception as e:
        logging.exception(
            "Không thể kiểm tra/thêm cột %s.%s: %s",
            table,
            column,
            e
        )


def migrate_database():
    """
    Đồng bộ database cũ với phiên bản bot mới.
    Không xóa dữ liệu.
    """

    # users
    ensure_db_column("users", "last_name", "TEXT")
    ensure_db_column("users", "username", "TEXT")
    ensure_db_column("users", "first_name", "TEXT")
    ensure_db_column("users", "messages", "INTEGER DEFAULT 0")
    ensure_db_column("users", "level", "INTEGER DEFAULT 1")
    ensure_db_column("users", "created_at", "TEXT")
    ensure_db_column("users", "updated_at", "TEXT")

    # known_profiles
    ensure_db_column("known_profiles", "username", "TEXT")
    ensure_db_column("known_profiles", "first_name", "TEXT")
    ensure_db_column("known_profiles", "last_name", "TEXT")
    ensure_db_column("known_profiles", "updated_at", "TEXT")

    # settings
    ensure_db_column("settings", "value", "TEXT")

    # afk
    ensure_db_column("afk", "reason", "TEXT")
    ensure_db_column("afk", "created_at", "TEXT")

    # checkins
    ensure_db_column("checkins", "streak", "INTEGER DEFAULT 0")
    ensure_db_column("checkins", "last_date", "TEXT")

    # filters
    ensure_db_column("filters", "response", "TEXT")

    # warns
    ensure_db_column("warns", "count", "INTEGER DEFAULT 0")

    logging.info("Database migration hoàn tất.")


def initialize_database_safe():
    """
    Khởi tạo database an toàn.
    """

    try:
        init_db()
    except Exception:
        logging.exception("Lỗi init database")
        raise

    try:
        migrate_database()
    except Exception:
        logging.exception("Lỗi migrate database")


# ------------------------------------------------------------
# DATABASE COMPATIBILITY HELPERS
# ------------------------------------------------------------

def db_get_setting_safe(chat_id, key, default=None):
    try:
        value = get_setting(chat_id, key)
        if value is None:
            return default
        return value
    except Exception:
        return default


def db_set_setting_safe(chat_id, key, value):
    try:
        set_setting(chat_id, key, value)
        return True
    except Exception:
        logging.exception(
            "Không thể lưu setting chat=%s key=%s",
            chat_id,
            key
        )
        return False


# ------------------------------------------------------------
# SAFE USER PROFILE
# ------------------------------------------------------------

def safe_update_user_profile(message):
    """
    Lưu thông tin user nhưng không để lỗi profile
    làm hỏng toàn bộ message.
    """

    try:
        user = message.get("from") or {}

        user_id = user.get("id")
        if not user_id:
            return

        username = user.get("username") or ""
        first_name = user.get("first_name") or ""
        last_name = user.get("last_name") or ""

        now = datetime.datetime.now().isoformat()

        db_execute(
            """
            INSERT OR IGNORE INTO users
            (
                user_id,
                username,
                first_name,
                last_name,
                messages,
                level,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 0, 1, ?, ?)
            """,
            (
                user_id,
                username,
                first_name,
                last_name,
                now,
                now,
            )
        )

        db_execute(
            """
            UPDATE users
            SET
                username = ?,
                first_name = ?,
                last_name = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                username,
                first_name,
                last_name,
                now,
                user_id,
            )
        )

    except Exception:
        logging.exception("safe_update_user_profile lỗi")


# ------------------------------------------------------------
# SAFE GROUP CHECK
# ------------------------------------------------------------

def is_group_chat_safe(message):
    try:
        chat = message.get("chat") or {}
        chat_type = chat.get("type")

        return chat_type in (
            "group",
            "supergroup",
        )

    except Exception:
        return False


def require_group_safe(message):
    """
    Kiểm tra command có được dùng trong group hay không.
    """

    if is_group_chat_safe(message):
        return True

    send_message(
        message["chat"]["id"],
        "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
    )

    return False


# ------------------------------------------------------------
# CALLBACK ROUTER BỔ SUNG
# ------------------------------------------------------------

def dispatch_callback_final(callback_query):
    """
    Router callback cuối cùng.
    Hỗ trợ toàn bộ nút của bot.
    """

    try:
        data = callback_query.get("data") or ""

        # Điểm danh
        if data.startswith("checkin"):
            return handle_checkin_callback(callback_query)

        # Nối chữ
        if data.startswith("noichu"):
            return handle_noichu_callback(callback_query)

        # Menu chính
        if data.startswith("menu_"):
            return handle_menu_callback(callback_query)

        # Callback menu cũ
        if data in {
            "help",
            "admin",
            "protect",
            "game",
            "level",
            "poem",
            "start_help",
            "start_admin",
            "start_protect",
            "start_game",
            "start_level",
            "start_poem",
        }:
            return handle_menu_callback(callback_query)

        # Nếu callback không thuộc nhóm trên
        answer_callback_query(
            callback_query.get("id"),
            "❌ Nút này không còn hiệu lực."
        )

        return False

    except Exception:
        logging.exception("dispatch_callback_final lỗi")

        try:
            answer_callback_query(
                callback_query.get("id"),
                "❌ Có lỗi khi xử lý nút."
            )
        except Exception:
            pass

        return False


# ------------------------------------------------------------
# PATCH CALLBACK PROCESSOR
# ------------------------------------------------------------

def process_callback_query_final(callback_query):
    try:
        if not callback_query:
            return False

        callback_id = callback_query.get("id")

        try:
            if callback_id:
                answer_callback_query(callback_id)
        except Exception:
            pass

        return dispatch_callback_final(callback_query)

    except Exception:
        logging.exception("process_callback_query_final lỗi")
        return False


# ------------------------------------------------------------
# PATCH MESSAGE PREPROCESSOR
# ------------------------------------------------------------

def preprocess_message(message):
    """
    Chuẩn hóa message trước khi đưa vào command/game/protection.
    """

    if not isinstance(message, dict):
        return False

    try:
        chat = message.get("chat") or {}
        user = message.get("from") or {}

        if not chat.get("id"):
            return False

        # Lưu profile
        safe_update_user_profile(message)

        # Nếu là group thì lưu profile chống fake
        if chat.get("type") in ("group", "supergroup"):
            try:
                save_known_profile(message)
            except Exception:
                pass

        return True

    except Exception:
        logging.exception("preprocess_message lỗi")
        return False


# ------------------------------------------------------------
# PATCH UPDATE PROCESSOR
# ------------------------------------------------------------

def process_update_final(update):
    """
    Bộ xử lý update cuối cùng.
    Mỗi update chỉ được xử lý một lần.
    """

    if not isinstance(update, dict):
        return False

    update_id = update.get("update_id")

    try:
        # Chặn update trùng
        if update_id is not None:
            if is_update_processed(update_id):
                return False

            mark_update_processed(update_id)

        # Callback
        callback_query = update.get("callback_query")

        if callback_query:
            return process_callback_query_final(callback_query)

        # Message
        message = update.get("message")

        if message:
            preprocess_message(message)

            return process_message_update(message)

        # Edited message
        edited_message = update.get("edited_message")

        if edited_message:
            preprocess_message(edited_message)

            return process_message_update(edited_message)

        return False

    except Exception:
        logging.exception(
            "process_update_final lỗi update_id=%s",
            update_id
        )
        return False


# ------------------------------------------------------------
# FINAL UPDATE ALIAS
# ------------------------------------------------------------

# Chỉ thay reference, không tạo thêm polling loop.
process_update = process_update_final


# ------------------------------------------------------------
# KIỂM TRA COMMAND MAP
# ------------------------------------------------------------

def final_command_check():
    """
    Kiểm tra các command quan trọng đã được đăng ký.
    """

    required_commands = [
        "start",
        "help",

        # moderation
        "ban",
        "unban",
        "kick",
        "mute",
        "unmute",
        "warn",
        "unwarn",
        "promote",
        "demote",
        "pin",
        "unpin",

        # protection
        "antispam",
        "antilink",
        "antibuff",
        "antifake",
        "protect",

        # AFK / filter
        "afk",
        "filter",
        "filters",
        "stopfilter",

        # poetry
        "thodoi",
        "thotinh",

        # checkin
        "diemdanh",

        # level
        "level",
        "levelyou",
        "levelbxh",
        "leveldanhsach",
        "levelnhiemvu",

        # game
        "noichu",

        # utilities
        "id",
        "chatid",
        "info",
        "groupinfo",
        "members",
        "rules",
        "setrules",
        "setwelcome",
        "delwelcome",
        "setnick",
        "ping",
        "time",
        "uptime",
        "botinfo",
        "stats",
    ]

    missing = []

    for command in required_commands:
        if command not in COMMAND_HANDLERS:
            missing.append(command)

    if missing:
        logging.warning(
            "Command chưa đăng ký: %s",
            ", ".join(missing)
        )
        return False

    logging.info(
        "Đã kiểm tra %d command.",
        len(required_commands)
    )

    return True


# ------------------------------------------------------------
# STARTUP DATABASE CHECK
# ------------------------------------------------------------

try:
    initialize_database_safe()
except Exception:
    logging.exception(
        "Không thể khởi tạo database lúc import."
    )


# ------------------------------------------------------------
# STARTUP COMMAND CHECK
# ------------------------------------------------------------

try:
    final_command_check()
except Exception:
    logging.exception(
        "Không thể kiểm tra command map."
    )


print("============================================")
print("        NGỌC MỸ TELEGRAM BOT")
print("        AI: ĐÃ XÓA HOÀN TOÀN")
print("        DATABASE: READY")
print("        COMMANDS: READY")
print("============================================")

# ============================================================
# PHẦN 14/15
# FINAL SAFETY + ERROR HANDLING + HEALTH CHECK
# ============================================================

def safe_send_message(chat_id, text_value, **kwargs):
    """
    Gửi tin nhắn an toàn.
    Nếu Telegram từ chối HTML thì thử gửi text thường.
    """

    if not chat_id:
        return None

    try:
        return send_message(
            chat_id,
            text_value,
            **kwargs
        )

    except Exception as e:
        logging.warning(
            "safe_send_message lỗi: %s",
            e
        )

        try:
            clean_text = re.sub(
                r"<[^>]+>",
                "",
                str(text_value)
            )

            return send_message(
                chat_id,
                clean_text
            )

        except Exception:
            logging.exception(
                "Không thể gửi message"
            )
            return None


def safe_edit_message(chat_id, message_id, text_value, **kwargs):
    """
    Edit message an toàn.
    """

    try:
        return edit_message_text(
            chat_id,
            message_id,
            text_value,
            **kwargs
        )

    except Exception:
        logging.exception(
            "Không thể edit message"
        )
        return None


# ------------------------------------------------------------
# ERROR REPORT
# ------------------------------------------------------------

def report_internal_error(message, error=None):
    """
    Không để lỗi Python lộ ra cho thành viên nhóm.
    """

    try:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if not chat_id:
            return

        safe_send_message(
            chat_id,
            "❌ Đã xảy ra lỗi khi xử lý lệnh."
        )

        if error:
            logging.exception(
                "Internal bot error: %s",
                error
            )

    except Exception:
        logging.exception(
            "report_internal_error lỗi"
        )


# ------------------------------------------------------------
# MESSAGE HANDLER CUỐI
# ------------------------------------------------------------

def process_message_update_final(message):
    """
    Xử lý một message theo đúng thứ tự:

    1. Thành viên mới
    2. Thành viên rời nhóm
    3. Command
    4. Nối chữ
    5. AFK
    6. Filter
    7. Protection
    8. Level
    """

    if not isinstance(message, dict):
        return False

    try:
        chat = message.get("chat") or {}

        if not chat.get("id"):
            return False

        # ----------------------------------------------------
        # NEW MEMBERS
        # ----------------------------------------------------
        if message.get("new_chat_members"):
            try:
                process_new_members(message)
            except Exception:
                logging.exception(
                    "process_new_members lỗi"
                )

            return True

        # ----------------------------------------------------
        # LEFT MEMBER
        # ----------------------------------------------------
        if message.get("left_chat_member"):
            try:
                process_left_member(message)
            except Exception:
                logging.exception(
                    "process_left_member lỗi"
                )

            return True

        # ----------------------------------------------------
        # COMMAND
        # ----------------------------------------------------
        text_value = message.get("text") or ""

        if text_value.startswith("/"):
            try:
                return dispatch_command_clean(message)
            except Exception as e:
                report_internal_error(message, e)
                return False

        # ----------------------------------------------------
        # NỐI CHỮ
        # ----------------------------------------------------
        try:
            if handle_noichu_message(message):
                return True
        except Exception:
            logging.exception(
                "Nối chữ lỗi"
            )

        # ----------------------------------------------------
        # AFK
        # ----------------------------------------------------
        try:
            handle_afk_message(message)
        except Exception:
            logging.exception(
                "AFK handler lỗi"
            )

        # ----------------------------------------------------
        # FILTER
        # ----------------------------------------------------
        try:
            if handle_filter_message(message):
                return True
        except Exception:
            logging.exception(
                "Filter handler lỗi"
            )

        # ----------------------------------------------------
        # PROTECTION
        # ----------------------------------------------------
        try:
            if handle_protection(message):
                return True
        except Exception:
            logging.exception(
                "Protection handler lỗi"
            )

        # ----------------------------------------------------
        # LEVEL
        # ----------------------------------------------------
        try:
            process_level_for_message(message)
        except Exception:
            logging.exception(
                "Level handler lỗi"
            )

        return True

    except Exception as e:
        report_internal_error(message, e)
        return False


# ------------------------------------------------------------
# DÙNG PROCESSOR CUỐI CÙNG
# ------------------------------------------------------------

process_message_update = process_message_update_final


# ------------------------------------------------------------
# UPDATE PROCESSOR CUỐI CÙNG
# ------------------------------------------------------------

def process_update_final_v2(update):
    """
    Processor cuối cùng của bot.
    """

    if not isinstance(update, dict):
        return False

    try:
        update_id = update.get("update_id")

        # Chống update trùng
        if update_id is not None:

            if is_update_processed(update_id):
                return False

            mark_update_processed(update_id)

        # ----------------------------------------------------
        # CALLBACK
        # ----------------------------------------------------
        callback_query = update.get("callback_query")

        if callback_query:
            return process_callback_query_final(
                callback_query
            )

        # ----------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------
        message = update.get("message")

        if message:

            try:
                preprocess_message(message)
            except Exception:
                logging.exception(
                    "preprocess_message lỗi"
                )

            return process_message_update_final(
                message
            )

        # ----------------------------------------------------
        # EDITED MESSAGE
        # ----------------------------------------------------
        edited_message = update.get("edited_message")

        if edited_message:

            try:
                preprocess_message(
                    edited_message
                )
            except Exception:
                logging.exception(
                    "preprocess edited_message lỗi"
                )

            return process_message_update_final(
                edited_message
            )

        # ----------------------------------------------------
        # CHANNEL POST
        # ----------------------------------------------------
        channel_post = update.get("channel_post")

        if channel_post:
            return False

        return False

    except Exception:
        logging.exception(
            "process_update_final_v2 lỗi"
        )
        return False


process_update = process_update_final_v2


# ------------------------------------------------------------
# BOT HEALTH CHECK
# ------------------------------------------------------------

def bot_health_check():
    """
    Kiểm tra Telegram API.
    """

    try:
        me = get_bot_information()

        if not me:
            logging.error(
                "Health check thất bại."
            )
            return False

        username = me.get("username") or "unknown"
        first_name = me.get("first_name") or "Ngọc Mỹ"

        logging.info(
            "Bot online: %s (@%s)",
            first_name,
            username
        )

        return True

    except Exception:
        logging.exception(
            "bot_health_check lỗi"
        )
        return False


# ------------------------------------------------------------
# TOKEN CHECK
# ------------------------------------------------------------

def validate_bot_token():

    if not BOT_TOKEN:
        print("")
        print("============================================")
        print("❌ THIẾU BOT_TOKEN")
        print("")
        print("Hãy đặt biến môi trường:")
        print("BOT_TOKEN=8976236384:AAEpZ_w0uCKliDe4ip8IA-FWX0_8j1UhX5k")
        print("")
        print("Railway:")
        print("Variables → BOT_TOKEN")
        print("============================================")
        print("")

        return False

    if len(BOT_TOKEN) < 20:
        print(
            "⚠️ BOT_TOKEN có vẻ không hợp lệ."
        )
        return False

    return True


# ------------------------------------------------------------
# STARTUP VALIDATION
# ------------------------------------------------------------

def startup_validation():

    print("")
    print("============================================")
    print("       NGỌC MỸ - STARTUP CHECK")
    print("============================================")

    # Token
    if not validate_bot_token():
        return False

    # Database
    try:
        initialize_database_safe()
        print("✅ Database: OK")
    except Exception:
        print("❌ Database: ERROR")
        logging.exception(
            "Database startup error"
        )
        return False

    # Command map
    try:
        if final_command_check():
            print("✅ Commands: OK")
        else:
            print(
                "⚠️ Commands: có command chưa đăng ký"
            )
    except Exception:
        print("⚠️ Không kiểm tra được commands")

    # Telegram
    try:
        if bot_health_check():
            print("✅ Telegram API: OK")
        else:
            print("❌ Telegram API: ERROR")
            return False
    except Exception:
        print("❌ Telegram API: ERROR")
        return False

    print("============================================")
    print("       NGỌC MỸ ĐÃ SẴN SÀNG")
    print("       AI: OFF / REMOVED")
    print("============================================")
    print("")

    return True


# ------------------------------------------------------------
# SIGNAL / SHUTDOWN
# ------------------------------------------------------------

BOT_STOP_REQUESTED = False


def request_bot_stop():
    global BOT_STOP_REQUESTED

    BOT_STOP_REQUESTED = True

    logging.info(
        "Bot nhận yêu cầu dừng."
    )


# ------------------------------------------------------------
# EXCEPTION HANDLER
# ------------------------------------------------------------

def install_exception_handler():

    def handle_exception(exc_type, exc_value, exc_traceback):

        if issubclass(
            exc_type,
            KeyboardInterrupt
        ):
            sys.__excepthook__(
                exc_type,
                exc_value,
                exc_traceback
            )
            return

        logging.error(
            "Unhandled exception",
            exc_info=(
                exc_type,
                exc_value,
                exc_traceback
            )
        )

    sys.excepthook = handle_exception


try:
    install_exception_handler()
except Exception:
    pass

# ============================================================
# PHẦN 15/15
# MAIN + START BOT
# ============================================================

def final_startup():

    print("")
    print("╔════════════════════════════════════════════╗")
    print("║             NGỌC MỸ TELEGRAM BOT          ║")
    print("╠════════════════════════════════════════════╣")
    print("║ AI                  : ĐÃ XÓA               ║")
    print("║ MODERATION          : ON                   ║")
    print("║ PROTECTION          : ON                   ║")
    print("║ AFK / FILTER        : ON                   ║")
    print("║ ĐIỂM DANH           : ON                   ║")
    print("║ LEVEL                : ON                   ║")
    print("║ NỐI CHỮ              : ON                   ║")
    print("║ THƠ ĐỜI / THƠ TÌNH : ON                   ║")
    print("╚════════════════════════════════════════════╝")
    print("")

    try:
        initialize_database_safe()
    except Exception:
        logging.exception(
            "Không thể initialize database."
        )
        return False

    try:
        final_command_check()
    except Exception:
        logging.exception(
            "Không thể kiểm tra command."
        )

    return True


def main():

    global BOT_STOP_REQUESTED

    BOT_STOP_REQUESTED = False

    print("")
    print("============================================")
    print("          KHỞI ĐỘNG NGỌC MỸ")
    print("============================================")

    # --------------------------------------------------------
    # KIỂM TRA TOKEN
    # --------------------------------------------------------

    if not validate_bot_token():
        print("")
        print("❌ BOT KHÔNG THỂ CHẠY.")
        print("❌ Hãy thêm BOT_TOKEN vào biến môi trường.")
        print("")
        return

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    try:
        if not final_startup():
            print(
                "❌ Startup database thất bại."
            )
            return

        print(
            "✅ Database đã sẵn sàng."
        )

    except Exception:
        logging.exception(
            "Startup database lỗi."
        )
        return

    # --------------------------------------------------------
    # TELEGRAM API
    # --------------------------------------------------------

    try:
        delete_webhook()

        print(
            "✅ Webhook đã được xử lý."
        )

    except Exception:
        logging.exception(
            "Không thể xóa webhook."
        )

    # --------------------------------------------------------
    # BOT INFORMATION
    # --------------------------------------------------------

    try:
        bot_info = get_bot_information()

        if bot_info:

            bot_username = (
                bot_info.get("username")
                or "unknown"
            )

            bot_name = (
                bot_info.get("first_name")
                or "Ngọc Mỹ"
            )

            print("")
            print(
                "🤖 Bot:",
                bot_name
            )

            print(
                "👤 Username:",
                "@" + bot_username
            )

        else:
            print(
                "⚠️ Không lấy được thông tin bot."
            )

    except Exception:
        logging.exception(
            "get_bot_information lỗi."
        )

    # --------------------------------------------------------
    # COMMAND CHECK
    # --------------------------------------------------------

    try:
        if final_command_check():
            print(
                "✅ Command map hoàn chỉnh."
            )
        else:
            print(
                "⚠️ Command map có cảnh báo."
            )

    except Exception:
        logging.exception(
            "Command check lỗi."
        )

    # --------------------------------------------------------
    # HEALTH CHECK
    # --------------------------------------------------------

    try:
        if bot_health_check():
            print(
                "✅ Telegram API hoạt động."
            )
        else:
            print(
                "⚠️ Telegram API chưa phản hồi."
            )

    except Exception:
        logging.exception(
            "Health check lỗi."
        )

    # --------------------------------------------------------
    # START POLLING
    # --------------------------------------------------------

    print("")
    print("============================================")
    print("        NGỌC MỸ ĐANG CHẠY")
    print("        AI: ĐÃ XÓA HOÀN TOÀN")
    print("        Đang chờ tin nhắn...")
    print("============================================")
    print("")

    try:

        polling_loop()

    except KeyboardInterrupt:

        print("")
        print(
            "🛑 Ngọc Mỹ đã được dừng."
        )

    except Exception:

        logging.exception(
            "Polling loop bị lỗi."
        )

        print("")
        print(
            "❌ Polling loop đã dừng do lỗi."
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()

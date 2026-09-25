# ============================================================
# THEONE BOT - PURE PYTHON VERSION
# PHẦN 1/10
# KHÔNG AIogram - KHÔNG aiohttp - KHÔNG aiosqlite
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

BOT_TOKEN = "8976236384:AAEpZ_w0uCKliDe4ip8IA-FWX0_8j1UhX5k"

OWNER_USERNAME = "DTN_207"
OWNER_DISPLAY = "@DTN_207"

VERSION = "3.0.0"

DATABASE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "bot.db"
)

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

logger = logging.getLogger("THEONE")


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
    "lệnh này chỉ hoạt động trong nhóm,xin lỗi"
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
            CREATE TABLE IF NOT EXISTS achievements (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                achievement_key TEXT NOT NULL,
                unlocked_at TEXT NOT NULL,
                PRIMARY KEY (
                    chat_id,
                    user_id,
                    achievement_key
                )
            );

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

# ==================== LEVEL SYSTEM ====================

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


def get_level_data(chat_id, user_id):
    conn = db_connect()

    row = conn.execute(
        """
        SELECT chat_id, user_id, username, first_name,
               message_count, level, updated_at
        FROM levels
        WHERE chat_id = ? AND user_id = ?
        """,
        (chat_id, user_id)
    ).fetchone()

    conn.close()
    return row


def add_level_message(chat_id, user_id, username, first_name):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = db_connect()

    row = conn.execute(
        """
        SELECT message_count, level
        FROM levels
        WHERE chat_id = ? AND user_id = ?
        """,
        (chat_id, user_id)
    ).fetchone()

    if row:
        message_count = row[0] + 1
        old_level = row[1]
    else:
        message_count = 1
        old_level = 1

    new_level = calculate_level(message_count)

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
            username = excluded.username,
            first_name = excluded.first_name,
            message_count = excluded.message_count,
            level = excluded.level,
            updated_at = excluded.updated_at
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

    return message_count, old_level, new_level

    logger.info(
        "Database initialized."
    )


# ============================================================
# TELEGRAM API
# ============================================================

def telegram_request(
    method,
    data=None,
    timeout=30
):

    if not BOT_TOKEN or (
        BOT_TOKEN
        == "DÁN_TOKEN_BOT_CỦA_BẠN_VÀO_ĐÂY"
    ):

        raise RuntimeError(
            "Bạn chưa nhập BOT_TOKEN."
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
    parse_mode="HTML",
    reply_markup=None
):

    data = {
        "chat_id": chat_id,
        "text": text,
    }

    if parse_mode:
        data["parse_mode"] = parse_mode

    if reply_to:
        data["reply_to_message_id"] = reply_to

    if reply_markup is not None:
        data["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False
        )

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

# ============================================================
# THĂNG CẤP / PROMOTE
# ============================================================

async def command_thangcap(message, args=""):
    if not is_group(message):
        await send_message(
            chat_id(message),
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    if not await is_admin(message):
        await send_message(
            chat_id(message),
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )
        return

    target_id = None

    reply = message.get("reply_to_message")
    if reply:
        target_id = user_id(reply.get("from"))

    if not target_id and args:
        value = args.split()[0]

        if value.startswith("@"):
            target_id = await resolve_username(value)

        elif value.isdigit():
            target_id = int(value)

    if not target_id:
        await send_message(
            chat_id(message),
            "❌ Hãy reply tin nhắn của người cần thăng cấp hoặc dùng:\n"
            "<code>/thangcap @username</code>\n"
            "<code>/thangcap user_id</code>",
            parse_mode="HTML"
        )
        return

    if target_id == user_id(message):
        await send_message(
            chat_id(message),
            "❌ Bạn không thể tự thăng cấp chính mình."
        )
        return

    target = await get_chat_member(
        chat_id(message),
        target_id
    )

    if not target:
        await send_message(
            chat_id(message),
            "❌ Không tìm thấy thành viên này."
        )
        return

    target_status = target.get("status")

    if target_status == "creator":
        await send_message(
            chat_id(message),
            "❌ Không thể thăng cấp chủ nhóm."
        )
        return

    if target_status == "administrator":
        await send_message(
            chat_id(message),
            "⚠️ Người này đã là quản trị viên."
        )
        return

    result = await api(
        "promoteChatMember",
        {
            "chat_id": chat_id(message),
            "user_id": target_id,

            "can_manage_chat": True,
            "can_delete_messages": True,
            "can_manage_video_chats": True,
            "can_restrict_members": True,
            "can_change_info": True,
            "can_invite_users": True,
            "can_pin_messages": True,
            "can_manage_topics": True,

            "can_promote_members": False
        }
    )

    if not result.get("ok"):
        await send_message(
            chat_id(message),
            "❌ Không thể thăng cấp người này.\n"
            "Hãy kiểm tra quyền của Ngọc Mỹ."
        )
        return

    await send_message(
        chat_id(message),
        f"👑 Đã thăng cấp <code>{target_id}</code> thành quản trị viên.",
        parse_mode="HTML"
    )

# ============================================================
# THÀNH TỰU HIỆN TẠI
# ============================================================

async def command_thanhtuuhientai(message, args=""):
    if not is_group(message):
        await send_message(
            chat_id(message),
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    cid = chat_id(message)
    uid = user_id(message)

    rows = await adb_execute(
        """
        SELECT achievement_key, unlocked_at
        FROM achievements
        WHERE chat_id = ?
          AND user_id = ?
        ORDER BY unlocked_at ASC
        """,
        (cid, uid),
        fetch=True
    )

    unlocked = {
        row["achievement_key"]: row
        for row in rows
    }

    if not unlocked:
        await send_message(
            cid,
            "🏆 <b>THÀNH TỰU HIỆN TẠI</b>\n\n"
            "Bạn chưa mở khóa thành tựu nào.\n"
            "Hãy tiếp tục hoạt động để mở khóa thành tựu! 🔥",
            parse_mode="HTML"
        )
        return

    lines = [
        "🏆 <b>THÀNH TỰU HIỆN TẠI</b>",
        ""
    ]

    for achievement in ACHIEVEMENTS:
        key = achievement["key"]

        if key not in unlocked:
            continue

        name = achievement["name"]
        metric = achievement["metric"]
        value = achievement["value"]

        # Mức độ xịn / khó
        if metric == "level":
            xin = 5
            kho = 5
            progress_text = f"Level {value}"

        elif metric == "messages":
            if value >= 10000:
                xin = 5
                kho = 5
            elif value >= 5000:
                xin = 4
                kho = 4
            else:
                xin = 3
                kho = 3

            progress_text = f"{value:,} messages"

        elif metric == "xu":
            if value >= 100000:
                xin = 5
                kho = 5
            elif value >= 10000:
                xin = 5
                kho = 4
            elif value >= 1000:
                xin = 4
                kho = 3
            else:
                xin = 3
                kho = 2

            progress_text = f"{value:,} Xu"

        else:
            xin = 3
            kho = 3
            progress_text = f"{value}"

        lines.append(
            f"🏅 <b>{name}</b>\n"
            f"⭐ Xịn: {xin}/5 | 🔥 Khó: {kho}/5\n"
            f"📊 {progress_text}\n"
        )

    await send_message(
        cid,
        "\n".join(lines),
        parse_mode="HTML"
    )

def user_name(user):

    if not user:

        return "Unknown"

    return (
        user.get("first_name")
        or user.get("username")
        or str(
            user.get("id", "Unknown")
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

    user_id = user.get(
        "id"
    )

    return (
        f'<a href="tg://user?id={user_id}">'
        f'{name}'
        f'</a>'
    )


async def save_user(user):

    if not user:

        return

    now = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

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

    return (
        message.get("chat", {})
        .get("type")
        in GROUP_TYPES
    )


def is_private(message):

    return (
        message.get("chat", {})
        .get("type")
        == PRIVATE_TYPE
    )

def user_id(message):
    user = from_user(message)

    if not user:
        return None

    return user.get("id")

def chat_id(message):

    return (
        message.get("chat", {})
        .get("id")
    )


def message_id(message):

    return message.get(
        "message_id"
    )


def from_user(message):

    return message.get(
        "from"
    )


# ============================================================
# PERMISSION
# ============================================================

def is_owner(user):

    if not user:

        return False

    username = (
        user.get("username")
        or ""
    ).lower()

    return (
        username
        == OWNER_USERNAME.lower()
    )


async def get_chat_member(
    chat_id_value,
    user_id
):

    result = await api(
        "getChatMember",
        {
            "chat_id": chat_id_value,
            "user_id": user_id
        }
    )

    if not result.get("ok"):

        return None

    return result.get(
        "result"
    )


async def is_admin(
    message
):

    user = from_user(
        message
    )

    if not user:

        return False

    if is_owner(user):

        return True

    if not is_group(message):

        return False

    member = await get_chat_member(
        chat_id(message),
        user.get("id")
    )

    if not member:

        return False

    return member.get(
        "status"
    ) in {
        "administrator",
        "creator"
    }


async def require_group(
    message
):

    if not is_group(message):

        await send_message(
            chat_id(message),
            PRIVATE_GROUP_MESSAGE
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

    if not await is_admin(
        message
    ):

        await send_message(
            chat_id(message),
            ADMIN_ONLY_MESSAGE
        )

        return False

    return True


async def require_owner(
    message
):

    if not is_owner(
        from_user(message)
    ):

        await send_message(
            chat_id(message),
            OWNER_ONLY_MESSAGE
        )

        return False

    return True


# ============================================================
# SETTINGS
# ============================================================

async def get_setting(
    chat_id_value,
    key,
    default=False
):

    row = await adb_execute(
        """
        SELECT value
        FROM settings
        WHERE chat_id = ?
        AND key = ?
        """,
        (
            chat_id_value,
            key
        ),
        fetchone=True
    )

    if not row:

        return default

    return (
        str(row["value"])
        == "1"
    )


async def set_setting(
    chat_id_value,
    key,
    value
):

    await adb_execute(
        """
        INSERT INTO settings (
            chat_id,
            key,
            value
        )
        VALUES (?, ?, ?)

        ON CONFLICT(
            chat_id,
            key
        )
        DO UPDATE SET
            value =
                excluded.value
        """,
        (
            chat_id_value,
            key,
            "1" if value else "0"
        )
    )


# ============================================================
# DURATION
# ============================================================

def parse_duration(text):

    if not text:

        return None

    match = re.fullmatch(
        r"(\d+)\s*(s|m|h|d|w)",
        text.lower()
    )

    if not match:

        return None

    number = int(
        match.group(1)
    )

    unit = match.group(2)

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
        "w": 604800
    }

    return (
        number
        * multipliers[unit]
    )


def format_duration(
    seconds
):

    seconds = int(seconds)

    if seconds < 60:

        return f"{seconds}s"

    if seconds < 3600:

        return (
            f"{seconds // 60}m"
        )

    if seconds < 86400:

        return (
            f"{seconds // 3600}h"
        )

    return (
        f"{seconds // 86400}d"
    )


# ============================================================
# UPTIME
# ============================================================

def get_uptime():

    seconds = int(
        time.time()
        - START_TIME
    )

    days, seconds = divmod(
        seconds,
        86400
    )

    hours, seconds = divmod(
        seconds,
        3600
    )

    minutes, seconds = divmod(
        seconds,
        60
    )

    parts = []

    if days:

        parts.append(
            f"{days}d"
        )

    if hours:

        parts.append(
            f"{hours}h"
        )

    if minutes:

        parts.append(
            f"{minutes}m"
        )

    parts.append(
        f"{seconds}s"
    )

    return " ".join(
        parts
    )


# ============================================================
# BOT BAN
# ============================================================

async def is_bot_banned(
    user_id
):

    row = await adb_execute(
        """
        SELECT user_id
        FROM bot_bans
        WHERE user_id = ?
        """,
        (
            user_id,
        ),
        fetchone=True
    )

    return row is not None


# ============================================================
# STARTUP
# ============================================================

async def startup():

    if (
        not BOT_TOKEN
        or BOT_TOKEN
        == "DÁN_TOKEN_BOT_CỦA_BẠN_VÀO_ĐÂY"
    ):

        raise RuntimeError(
            "Bạn chưa nhập BOT_TOKEN "
            "trong bot.py"
        )

    init_db()

    me = await api(
        "getMe"
    )

    if not me.get("ok"):

        raise RuntimeError(
            "BOT TOKEN không hợp lệ "
            "hoặc Telegram API không phản hồi."
        )

    bot_user = me.get(
        "result",
        {}
    )

    logger.info(
        "=========================================="
    )

    logger.info(
        "Ngọc Mỹ v%s",
        VERSION
    )

    logger.info(
        "Bot: @%s",
        bot_user.get(
            "username",
            "unknown"
        )
    )

    logger.info(
        "Owner: %s",
        OWNER_DISPLAY
    )

    logger.info(
        "Pure Python Telegram API mode"
    )

    logger.info(
        "=========================================="
    )


# ============================================================
# END PHẦN 1/10
# ============================================================

# ============================================================
# NGỌC MỸ - PURE PYTHON VERSION
# PHẦN 2/10
# UPDATE POLLING + COMMAND ROUTER + BASIC COMMANDS
# ============================================================


# ============================================================
# UPDATE STATE
# ============================================================

LAST_UPDATE_ID = 0


# ============================================================
# TEXT / COMMAND HELPERS
# ============================================================

def get_text(message):

    return (
        message.get("text")
        or message.get("caption")
        or ""
    )


def parse_command(message):

    text = get_text(message).strip()

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
        rest[0].strip()
        if rest
        else ""
    )

    return command, args


def command_args(
    args
):

    if not args:

        return []

    return args.split()


# ============================================================
# HELP
# ============================================================

help_text = (
    "🤖 NGỌC MỸ — DANH SÁCH LỆNH\n\n"

    "👤 LỆNH CƠ BẢN\n"
    "/start → Khởi động và xem thông tin bot\n"
    "/help → Xem toàn bộ hướng dẫn sử dụng\n"
    "/id → Xem ID Telegram của bạn\n"
    "/info → Xem thông tin người dùng\n"
    "/ping → Kiểm tra bot có đang hoạt động\n"
    "/time → Xem thời gian hiện tại\n"
    "/stats → Xem thống kê bot\n"
    "/settings → Xem cài đặt nhóm\n\n"

    "🛠 TIỆN ÍCH\n"
    "/echo → Bot nhắc lại nội dung bạn nhập\n"
    "/calc → Tính phép tính nhanh\n"
    "/search → Tìm kiếm thông tin\n"
    "/weather → Xem thời tiết\n"
    "/short → Rút gọn liên kết\n\n"

    "🛡 QUẢN LÝ NHÓM\n"
    "/warn → Cảnh cáo thành viên\n"
    "/warns → Xem số lần cảnh cáo\n"
    "/mute → Khóa chat thành viên\n"
    "/unmute → Mở khóa chat\n"
    "/kick → Đá thành viên khỏi nhóm\n"
    "/ban → Cấm thành viên\n"
    "/unban → Gỡ cấm thành viên\n"
    "/purge → Xóa nhiều tin nhắn\n"
    "/pin → Ghim tin nhắn\n"
    "/unpin → Bỏ ghim tin nhắn\n"
    "/lock → Khóa chat\n"
    "/unlock → Mở khóa chat\n\n"

    "👑 QUẢN TRỊ BOT\n"
    "/admins → Xem quản trị viên\n"
    "/broadcast → Gửi thông báo đến người dùng\n"
    "/users → Xem danh sách người dùng bot\n"
    "/banuser → Cấm người dùng sử dụng bot\n"
    "/unbanuser → Gỡ cấm người dùng bot\n"
    "/restart → Khởi động lại bot\n"
    "/logs → Xem log hoạt động\n\n"

    "⚙️ HỆ THỐNG\n"
    "/database → Kiểm tra database\n"
    "/health → Kiểm tra tình trạng bot\n"
    "/version → Xem phiên bản bot\n\n"

    "🛡 BẢO VỆ\n"
    "/antispam on|off → Bật/tắt chống spam\n"
    "/antilink on|off → Bật/tắt chống link\n"
    "/antibuff on|off → Bật/tắt chống buff thành viên\n"
    "/antifake on|off → Bật/tắt chống giả mạo\n\n"

    "💤 AFK\n"
    "/afk [lý do] → Bật trạng thái AFK\n"
    "→ Bot thông báo khi có người nhắc đến bạn\n\n"

    "🔎 FILTER\n"
    "/filter → Tạo từ khóa tự động trả lời\n"
    "/filters → Xem danh sách filter\n"
    "/stopfilter → Xóa filter\n\n"

    "❤️ THƠ\n"
    "/thodoi → Random một bài thơ đời\n"
    "/thotinh → Random một bài thơ tình\n\n"

    "🔥 ĐIỂM DANH\n"
    "/diemdanh → Mở bảng điểm danh hằng ngày\n"
    "→ Tích điểm và duy trì chuỗi điểm danh\n\n"

    "⭐ LEVEL\n"
    "/level → Xem hệ thống level\n"
    "/levelyou → Xem level hiện tại của bạn\n"
    "/levelbxh → Xem bảng xếp hạng level trong nhóm\n"
    "/leveldanhsach → Xem điều kiện lên từng level\n"
    "/levelnhiemvu → Xem nhiệm vụ tiếp theo\n\n"

    "🎮 TRÒ CHƠI — NỐI CHỮ VIỆT NAM\n"
    "/noichu → Mở game Nối Chữ Việt Nam\n"
    "→ Bấm nút THAM GIA để vào game\n"
    "→ Cần ít nhất 2 người chơi\n"
    "→ Game bắt đầu sau 3 phút\n"
    "→ Người chơi phải nối từ đúng lượt\n"
    "→ Nối sai sẽ bị loại\n"
    "→ Người cuối cùng còn lại là người chiến thắng\n\n"

    "👑 Owner: @DTN_207"
)

# ============================================================
# BASIC COMMANDS
# ============================================================

# ==================== LEVEL COMMANDS ====================

async def command_level(message, args=None):
    if not is_group(message):
        await send_message(
            message["chat"]["id"],
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    chat_id = message["chat"]["id"]
    user = message["from"]

    username = user.get("username")
    first_name = user.get("first_name", "Người dùng")

    count, old_level, new_level = add_level_message(
        chat_id,
        user["id"],
        username,
        first_name
    )

    if new_level > old_level:
        mention = (
            f"@{username}"
            if username
            else f'<a href="tg://user?id={user["id"]}">{html.escape(first_name)}</a>'
        )

        if new_level < 10:
            await send_message(
                chat_id,
                f"🎉 Chúc Mừng {mention} đã lên level {new_level} "
                f"để lên level tiếp theo vui lòng rõ lệnh /levelnhiemvu",
                parse_mode="HTML"
            )
        else:
            await send_message(
                chat_id,
                f"🏆 Chúc Mừng {mention} đã đạt LEVEL 10!\n"
                f"🔥 Bạn đã đạt cấp độ tối đa của hệ thống Level.",
                parse_mode="HTML"
            )
    else:
        await send_message(
            chat_id,
            f"📊 Bạn hiện đang ở level {new_level} với {count} tin nhắn."
        )


async def command_levelyou(message, args=None):
    if not is_group(message):
        await send_message(
            message["chat"]["id"],
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    chat_id = message["chat"]["id"]
    user = message["from"]

    row = get_level_data(chat_id, user["id"])

    if not row:
        count = 0
        level = 1
    else:
        count = row["message_count"]
        level = row["level"]

    username = user.get("username")

    if username:
        name = f"@{username}"
    else:
        name = user.get("first_name", "Bạn")

    await send_message(
        chat_id,
        f"👤 {name}\n"
        f"⭐ Level hiện của bạn là level {level}\n"
        f"💬 Số tin nhắn: {count}"
    )


async def command_leveldanhsach(message, args=None):
    if not is_group(message):
        await send_message(
            message["chat"]["id"],
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    text = (
        "📋 <b>ĐÂY LÀ DANH SÁCH ĐIỀU KIỆN LÊN LEVEL</b>\n\n"
        "⭐ Level 1 → 0 tin nhắn\n"
        "⭐ Level 2 → 100 tin nhắn\n"
        "⭐ Level 3 → 300 tin nhắn\n"
        "⭐ Level 4 → 500 tin nhắn\n"
        "⭐ Level 5 → 700 tin nhắn\n"
        "⭐ Level 6 → 900 tin nhắn\n"
        "⭐ Level 7 → 1100 tin nhắn\n"
        "⭐ Level 8 → 1300 tin nhắn\n"
        "⭐ Level 9 → 1500 tin nhắn\n"
        "🏆 Level 10 → 2000 tin nhắn\n\n"
        "💡 Tin nhắn được cộng dồn liên tục."
    )

    await send_message(
        message["chat"]["id"],
        text,
        parse_mode="HTML"
    )


async def command_levelnhiemvu(message, args=None):
    if not is_group(message):
        await send_message(
            message["chat"]["id"],
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    chat_id = message["chat"]["id"]
    user = message["from"]

    row = get_level_data(chat_id, user["id"])

    if not row:
        count = 0
        level = 1
    else:
        count = row["message_count"]
        level = row["level"]

    username = user.get("username")

    if username:
        name = f"@{username}"
    else:
        name = user.get("first_name", "Bạn")

    if level >= 10:
        await send_message(
            chat_id,
            f"🏆 Nhiệm vụ tiếp theo của {name}:\n"
            f"Bạn đã đạt LEVEL 10 — cấp độ tối đa."
        )
        return

    next_level = level + 1
    required = LEVEL_REQUIREMENTS[next_level]
    remaining = max(0, required - count)

    await send_message(
        chat_id,
        f"🎯 Nhiệm vụ tiếp theo để lên level của bạn {name} là:\n\n"
        f"⭐ Level hiện tại: {level}\n"
        f"💬 Đã có: {count} tin nhắn\n"
        f"🎯 Cần: {required} tin nhắn\n"
        f"🔥 Còn thiếu: {remaining} tin nhắn"
    )


async def command_levelbxh(message, args=None):
    if not is_group(message):
        await send_message(
            message["chat"]["id"],
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    chat_id = message["chat"]["id"]

    conn = db_connect()

    rows = conn.execute(
        """
        SELECT user_id, username, first_name, message_count, level
        FROM levels
        WHERE chat_id = ? AND level >= 2
        ORDER BY level DESC, message_count DESC
        """,
        (chat_id,)
    ).fetchall()

    conn.close()

    if not rows:
        await send_message(
            chat_id,
            "📊 Đây là bản xếp hạng level trong nhóm.\n\n"
            "Hiện chưa có thành viên nào đạt Level 2+."
        )
        return

    lines = [
        "🏆 <b>ĐÂY LÀ BẢN XẾP HẠNG LEVEL TRONG NHÓM</b>",
        ""
    ]

    for index, row in enumerate(rows, 1):
        username = row["username"]

        if username:
            name = f"@{username}"
        else:
            name = row["first_name"] or "Người dùng"

        lines.append(
            f"{index}. {name} — ⭐ Level {row['level']} "
            f"💬 {row['message_count']} tin"
        )

    await send_message(
        chat_id,
        "\n".join(lines),
        parse_mode="HTML"
    )

# ============================================================
# 🎮 NỐI CHỮ VIỆT NAM - GAME STATE
# ============================================================

NOICHU_GAMES = {}
NOICHU_TASKS = {}


def noichu_normalize(text):
    if not text:
        return ""

    return " ".join(
        text.strip().lower().split()
    )


def noichu_first_word(text):
    text = noichu_normalize(text)

    if not text:
        return ""

    return text.split()[0]


def noichu_last_word(text):
    text = noichu_normalize(text)

    if not text:
        return ""

    return text.split()[-1]


def noichu_display_name(user):
    username = user.get("username")

    if username:
        return f"@{username}"

    return user.get(
        "first_name",
        "Người chơi"
    )

def noichu_create_game(chat_id):
    game = {
        "chat_id": chat_id,
        "players": [],
        "active_players": [],
        "turn_order": [],
        "current_player": None,
        "last_phrase": None,
        "last_word": None,
        "started": False,
        "started_at": None,
        "turn_started_at": None,
        "valid_answers": {},
        "invalid_answers": {},
        "response_times": {},
        "total_words": {},
        "rounds": 0,
        "lobby_message_id": None,
    }

    NOICHU_GAMES[chat_id] = game

    return game


def noichu_get_game(chat_id):
    return NOICHU_GAMES.get(chat_id)


def noichu_add_player(game, user):
    user_id = user.get("id")

    if not user_id:
        return False

    for player in game["players"]:
        if player["id"] == user_id:
            return False

    game["players"].append({
        "id": user_id,
        "username": user.get("username"),
        "first_name": user.get(
            "first_name",
            "Người chơi"
        ),
    })

    game["valid_answers"][user_id] = 0
    game["invalid_answers"][user_id] = 0
    game["response_times"][user_id] = []
    game["total_words"][user_id] = 0

    return True


def noichu_remove_player(game, user_id):
    game["active_players"] = [
        player
        for player in game["active_players"]
        if player["id"] != user_id
    ]


def noichu_player_exists(game, user_id):
    return any(
        player["id"] == user_id
        for player in game["players"]
    )


def noichu_get_player(game, user_id):
    for player in game["players"]:
        if player["id"] == user_id:
            return player

    return None


def noichu_player_text(player, number):
    name = noichu_display_name(player)

    return f"{number}. {name}"


def noichu_cancel_task(chat_id):
    task = NOICHU_TASKS.pop(
        chat_id,
        None
    )

    if task:

        try:
            task.cancel()
        except Exception:
            pass

# ============================================================
# 🎮 NỐI CHỮ VIỆT NAM - LOBBY + NÚT THAM GIA
# ============================================================

async def command_noichu(message, args=None):
    if not is_group(message):
        await send_message(
            message["chat"]["id"],
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    chat_id = message["chat"]["id"]

    # Nếu nhóm đang có game
    if chat_id in NOICHU_GAMES:
        old_game = NOICHU_GAMES[chat_id]

        if old_game.get("started"):
            await send_message(
                chat_id,
                "🎮 Nhóm đang có một ván Nối Chữ đang diễn ra."
            )
            return

        if old_game.get("players"):
            await send_message(
                chat_id,
                "🎮 Nhóm đã có phòng Nối Chữ đang chờ người chơi."
            )
            return

        noichu_cancel_task(chat_id)

    game = noichu_create_game(chat_id)

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🎮 THAM GIA",
                    "callback_data": f"noichu_join:{chat_id}"
                }
            ]
        ]
    }

    text = (
        "🎮 <b>WELCOME ĐẾN VỚI NỐI CHỮ VIỆT NAM</b>\n\n"
        "Vui lòng bấm vào nút <b>THAM GIA</b> để vào trò chơi.\n\n"
        "👥 Tối thiểu: 2 người chơi\n"
        "⏱ Thời gian đăng ký: 3 phút\n"
        "🔀 Thứ tự lượt chơi sẽ được xáo ngẫu nhiên.\n\n"
        "⚠️ Khi game bắt đầu, chỉ người đúng lượt mới được trả lời."
    )

    result = await send_message(
        chat_id,
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )

    if isinstance(result, dict):
        sent_message = result.get("result")

        if isinstance(sent_message, dict):
            game["lobby_message_id"] = sent_message.get("message_id")

    # Chờ 3 phút rồi bắt đầu game
    task = asyncio.create_task(
        noichu_start_after_delay(chat_id)
    )

    NOICHU_TASKS[chat_id] = task


async def noichu_start_after_delay(chat_id):
    try:
        await asyncio.sleep(180)

        game = noichu_get_game(chat_id)

        if not game:
            return

        if game.get("started"):
            return

        if len(game.get("players", [])) < 2:
            await send_message(
                chat_id,
                "❌ Nối Chữ đã hết thời gian đăng ký nhưng chưa đủ 2 người chơi.\n"
                "Ván chơi đã bị hủy."
            )

            NOICHU_GAMES.pop(
                chat_id,
                None
            )

            return

        await noichu_start_game(chat_id)

    except asyncio.CancelledError:
        return

    except Exception as e:
        logger.exception(
            "NOICHU START ERROR: %s",
            e
        )

    finally:
        NOICHU_TASKS.pop(
            chat_id,
            None
        )


async def handle_noichu_callback(callback_query):
    data = callback_query.get(
        "data",
        ""
    )

    if not data.startswith("noichu_join:"):
        return False

    try:
        chat_id = int(
            data.split(
                ":",
                1
            )[1]
        )
    except Exception:
        return True

    user = callback_query.get("from")

    if not user:
        return True

    game = noichu_get_game(chat_id)

    if not game:
        await api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query["id"],
                "text": "Phòng chơi không còn tồn tại.",
                "show_alert": True
            }
        )

        return True

    if game.get("started"):
        await api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query["id"],
                "text": "Ván chơi đã bắt đầu.",
                "show_alert": True
            }
        )

        return True

    added = noichu_add_player(
        game,
        user
    )

    if not added:
        await api(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_query["id"],
                "text": "Bạn đã tham gia rồi.",
                "show_alert": True
            }
        )

        return True

    await api(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_query["id"],
            "text": "🎮 Tham gia thành công!"
        }
    )

    lines = [
        "🎮 <b>NỐI CHỮ VIỆT NAM</b>",
        "",
        "👥 <b>Danh sách người chơi:</b>"
    ]

    for index, player in enumerate(
        game["players"],
        1
    ):
        lines.append(
            noichu_player_text(
                player,
                index
            )
        )

    lines.extend([
        "",
        f"👤 Tổng người chơi: <b>{len(game['players'])}</b>",
        "⏱ Game sẽ bắt đầu sau 3 phút kể từ khi tạo phòng.",
        "",
        "Bấm <b>THAM GIA</b> để vào danh sách."
    ])

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🎮 THAM GIA",
                    "callback_data": f"noichu_join:{chat_id}"
                }
            ]
        ]
    }

    message_id = game.get(
        "lobby_message_id"
    )

    if message_id:

        try:
            await api(
                "editMessageText",
                {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": "\n".join(lines),
                    "parse_mode": "HTML",
                    "reply_markup": keyboard
                }
            )
        except Exception:
            pass

    return True

# ============================================================
# 🎮 NỐI CHỮ VIỆT NAM - BẮT ĐẦU GAME + CHIA LƯỢT
# ============================================================

async def noichu_start_game(chat_id):
    game = noichu_get_game(chat_id)

    if not game:
        return

    players = list(game.get("players", []))

    if len(players) < 2:
        await send_message(
            chat_id,
            "❌ Không đủ 2 người chơi để bắt đầu Nối Chữ."
        )

        NOICHU_GAMES.pop(
            chat_id,
            None
        )

        return

    # Xáo ngẫu nhiên thứ tự ban đầu
    random.shuffle(players)

    game["active_players"] = players.copy()
    game["turn_order"] = players.copy()
    game["started"] = True
    game["started_at"] = time.time()
    game["last_phrase"] = None
    game["last_word"] = None
    game["rounds"] = 0

    # Reset dữ liệu thống kê
    for player in players:
        user_id = player["id"]

        game["valid_answers"][user_id] = 0
        game["invalid_answers"][user_id] = 0
        game["response_times"][user_id] = []
        game["total_words"][user_id] = 0

    names = []

    for index, player in enumerate(players, 1):
        names.append(
            f"{index}. {noichu_display_name(player)}"
        )

    await send_message(
        chat_id,
        "🔥 <b>NỐI CHỮ VIỆT NAM CHÍNH THỨC BẮT ĐẦU!</b>\n\n"
        "👥 Người chơi:\n"
        + "\n".join(names)
        + "\n\n"
        "🔀 Thứ tự đã được xáo ngẫu nhiên.\n"
        "⚠️ Chỉ người đúng lượt mới được trả lời.\n"
        "💀 Nối sai sẽ bị loại.\n\n"
        "🎯 Người cuối cùng còn lại sẽ chiến thắng!",
        parse_mode="HTML"
    )

    await noichu_next_turn(
        chat_id
    )


async def noichu_next_turn(chat_id):
    game = noichu_get_game(chat_id)

    if not game or not game.get("started"):
        return

    active_players = game.get(
        "active_players",
        []
    )

    # Chỉ còn 1 người → chiến thắng
    if len(active_players) <= 1:

        if len(active_players) == 1:
            await noichu_finish(
                chat_id,
                active_players[0]["id"]
            )

        else:
            await send_message(
                chat_id,
                "❌ Không còn người chơi. Ván Nối Chữ kết thúc."
            )

            NOICHU_GAMES.pop(
                chat_id,
                None
            )

        return

    previous_player = game.get(
        "current_player"
    )

    # Không chọn lại ngay người vừa chơi nếu còn người khác
    candidates = [
        player
        for player in active_players
        if player["id"] != previous_player
    ]

    if not candidates:
        candidates = active_players

    next_player = random.choice(
        candidates
    )

    game["current_player"] = next_player["id"]
    game["turn_started_at"] = time.time()

    if game.get("last_word"):

        await send_message(
            chat_id,
            f"🎯 Đến lượt "
            f"<a href=\"tg://user?id={next_player['id']}\">"
            f"{html.escape(noichu_display_name(next_player))}"
            f"</a>\n\n"
            f"🔗 Từ trước: <b>{html.escape(game['last_word'])}</b>\n"
            f"👉 Câu của bạn phải bắt đầu bằng từ "
            f"<b>{html.escape(game['last_word'])}</b>.",
            parse_mode="HTML"
        )

    else:

        await send_message(
            chat_id,
            f"🎯 Lượt đầu tiên thuộc về "
            f"<a href=\"tg://user?id={next_player['id']}\">"
            f"{html.escape(noichu_display_name(next_player))}"
            f"</a>!\n\n"
            f"💬 Hãy nói một cụm từ bất kỳ để bắt đầu trò chơi.",
            parse_mode="HTML"
        )

# ============================================================
# 🎮 NỐI CHỮ VIỆT NAM - XỬ LÝ CÂU TRẢ LỜI
# ============================================================

async def noichu_handle_text(message):
    chat = message.get("chat", {})
    user = message.get("from", {})
    text = message.get("text", "")

    if chat.get("type") not in ("group", "supergroup"):
        return False

    if not text or text.startswith("/"):
        return False

    chat_id = chat.get("id")
    user_id = user.get("id")

    game = noichu_get_game(chat_id)

    if not game or not game.get("started"):
        return False

    active_players = game.get("active_players", [])

    # Người không tham gia game nói chuyện
    if not any(p["id"] == user_id for p in active_players):
        return False

    # Chưa đến lượt
    if game.get("current_player") != user_id:
        await send_message(
            chat_id,
            "mày chưa đến lượt bớt tài lanh đi"
        )
        return True

    phrase = noichu_normalize(text)

    if not phrase:
        return True

    first_word = noichu_first_word(phrase)
    last_word = noichu_last_word(phrase)

    # Kiểm tra nối chữ
    if game.get("last_word"):
        required_word = noichu_normalize(
            game["last_word"]
        )

        if first_word != required_word:
            game["invalid_answers"][user_id] = (
                game["invalid_answers"].get(user_id, 0) + 1
            )

            player = noichu_get_player(
                game,
                user_id
            )

            name = (
                noichu_display_name(player)
                if player
                else "Người chơi"
            )

            await send_message(
                chat_id,
                f"❌ {name} đã nối sai!\n"
                f"🔗 Phải bắt đầu bằng: "
                f"<b>{html.escape(required_word)}</b>\n"
                f"💀 {name} đã bị loại khỏi trò chơi.",
                parse_mode="HTML"
            )

            noichu_remove_player(
                game,
                user_id
            )

            game["current_player"] = None

            await noichu_next_turn(
                chat_id
            )

            return True

    # Câu hợp lệ
    started = game.get(
        "turn_started_at"
    ) or time.time()

    response_time = max(
        0.1,
        time.time() - started
    )

    game["valid_answers"][user_id] = (
        game["valid_answers"].get(user_id, 0) + 1
    )

    game["response_times"].setdefault(
        user_id,
        []
    ).append(
        response_time
    )

    game["total_words"][user_id] = (
        game["total_words"].get(user_id, 0)
        + len(phrase.split())
    )

    game["rounds"] = (
        game.get("rounds", 0) + 1
    )

    game["last_phrase"] = phrase
    game["last_word"] = last_word
    game["current_player"] = None

    await send_message(
        chat_id,
        f"✅ <b>Nối đúng!</b>\n"
        f"💬 {html.escape(phrase)}\n"
        f"🔗 Từ tiếp theo phải bắt đầu bằng: "
        f"<b>{html.escape(last_word)}</b>",
        parse_mode="HTML"
    )

    await noichu_next_turn(
        chat_id
    )

    return True

# ============================================================
# 🎮 NỐI CHỮ VIỆT NAM - KẾT THÚC GAME + TÍNH HIỆU SUẤT
# ============================================================

async def noichu_finish(chat_id, winner_id):
    game = noichu_get_game(chat_id)

    if not game:
        return

    winner = noichu_get_player(
        game,
        winner_id
    )

    if not winner:
        NOICHU_GAMES.pop(
            chat_id,
            None
        )
        return

    valid = game["valid_answers"].get(
        winner_id,
        0
    )

    times = game["response_times"].get(
        winner_id,
        []
    )

    total_words = game["total_words"].get(
        winner_id,
        0
    )

    # Điểm tốc độ
    if times:
        average_time = sum(times) / len(times)

        speed_score = max(
            0,
            min(
                1,
                (8 - average_time) / 8
            )
        )
    else:
        average_time = 8
        speed_score = 0

    # Điểm chất lượng câu
    if valid > 0:
        average_words = total_words / valid

        quality_score = max(
            0,
            min(
                1,
                (average_words - 1) / 4
            )
        )
    else:
        quality_score = 0

    # Hiệu suất:
    # 50 điểm nền
    # 30 điểm tốc độ
    # 20 điểm chất lượng câu
    performance = round(
        50
        + speed_score * 30
        + quality_score * 20
    )

    performance = max(
        50,
        min(
            100,
            performance
        )
    )

    name = noichu_display_name(
        winner
    )

    await send_message(
        chat_id,
        (
            "🏆 <b>GAME NỐI CHỮ ĐÃ KẾT THÚC!</b>\n\n"
            f"👑 Người chiến thắng: <b>{html.escape(name)}</b>\n"
            f"🔥 Hiệu suất: <b>{performance}%</b>\n"
            f"✅ Số câu nối đúng: <b>{valid}</b>\n"
            f"⚡ Thời gian trung bình: <b>{average_time:.2f}s</b>\n\n"
            "🎉 Chúc mừng nhà vô địch!"
        ),
        parse_mode="HTML"
    )

    # Xóa game sau khi kết thúc
    NOICHU_GAMES.pop(
        chat_id,
        None
    )

    noichu_cancel_task(
        chat_id
    )

# ============================================================
# START MENU - NGỌC MỸ
# ============================================================

def start_main_keyboard():

    return {
        "inline_keyboard": [

            [
                {
                    "text": "👑 Quản trị",
                    "callback_data": "start_admin"
                }
            ],

            [
                {
                    "text": "🎲 Tài Xỉu Ảo",
                    "callback_data": "start_taixiu"
                }
            ],

            [
                {
                    "text": "🧰 Tiện ích khác",
                    "callback_data": "start_utils"
                }
            ]

        ]
    }

def start_back_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🔙 Quay lại",
                    "callback_data": "start_home"
                }
            ]
        ]
    }


def start_admin_text():
    return (
        "👑 <b>QUẢN TRỊ NHÓM</b>\n\n"

        "⚠️ <b>/warn</b> — Cảnh cáo thành viên.\n"
        "Cách dùng: <code>/warn @username [lý do]</code> hoặc reply.\n\n"

        "📋 <b>/warns</b> — Xem cảnh cáo.\n"
        "Cách dùng: <code>/warns @username</code> hoặc reply.\n\n"

        "🔇 <b>/mute</b> — Khóa thành viên chat.\n"
        "Cách dùng: <code>/mute @username 10m</code> hoặc reply.\n\n"

        "🔊 <b>/unmute</b> — Mở khóa thành viên.\n"
        "Cách dùng: <code>/unmute @username</code> hoặc reply.\n\n"

        "🚪 <b>/kick</b> — Đá thành viên.\n"
        "Cách dùng: <code>/kick @username</code> hoặc reply.\n\n"

        "🚫 <b>/ban</b> — Cấm thành viên.\n"
        "Cách dùng: <code>/ban @username</code> hoặc reply.\n\n"

        "♻️ <b>/unban</b> — Gỡ cấm thành viên.\n"
        "Cách dùng: <code>/unban @username</code> hoặc reply.\n\n"

        "🗑 <b>/purge</b> — Xóa nhiều tin nhắn.\n"
        "Cách dùng: <code>/purge 10</code>.\n\n"

        "📌 <b>/pin</b> — Ghim tin nhắn.\n"
        "Cách dùng: reply tin nhắn rồi dùng <code>/pin</code>.\n\n"

        "📍 <b>/unpin</b> — Bỏ ghim.\n"
        "Cách dùng: <code>/unpin</code>.\n\n"

        "🔒 <b>/lock</b> — Khóa nhóm.\n"
        "Cách dùng: <code>/lock</code>.\n\n"

        "🔓 <b>/unlock</b> — Mở khóa nhóm.\n"
        "Cách dùng: <code>/unlock</code>.\n\n"

        "🛡 <b>BẢO VỆ NHÓM</b>\n"
        "<code>/antispam on|off</code> — Chống spam.\n"
        "<code>/antilink on|off</code> — Chống link.\n"
        "<code>/antibuff on|off</code> — Chống buff thành viên.\n"
        "<code>/antifake on|off</code> — Chống giả mạo."

        "👑 <b>/thangcap</b> – Thăng cấp thành viên thành quản trị viên.\n"
        "Cách dùng: <code>/thangcap @username</code> hoặc reply tin nhắn rồi dùng <code>/thangcap</code>.\n\n"
    )

# ============================================================
# BẢNG XẾP HẠNG CHAT
# ============================================================

async def command_bxhchat(message, args=""):
    if not is_group(message):
        await send_message(
            chat_id(message),
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    rows = await adb_execute(
        """
        SELECT
            user_id,
            username,
            first_name,
            message_count
        FROM levels
        WHERE chat_id = ?
        ORDER BY message_count DESC
        LIMIT 10
        """,
        (
            chat_id(message),
        ),
        fetch=True
    )

    if not rows:
        await send_message(
            chat_id(message),
            "📊 Chưa có dữ liệu xếp hạng chat trong nhóm."
        )
        return

    lines = [
        "🏆 <b>BẢNG XẾP HẠNG CHAT</b>",
        "",
        "📊 Top 10 thành viên gửi nhiều tin nhắn nhất:",
        ""
    ]

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for index, row in enumerate(rows, 1):

        user_id = row["user_id"]
        username = row["username"]
        first_name = row["first_name"] or "Không tên"
        message_count = row["message_count"] or 0

        if username:
            display_name = f"@{username}"
        else:
            display_name = first_name

        prefix = (
            medals[index - 1]
            if index <= 3
            else f"<b>{index}.</b>"
        )

        lines.append(
            f"{prefix} {display_name} — "
            f"<code>{message_count}</code> tin nhắn"
        )

    await send_message(
        chat_id(message),
        "\n".join(lines),
        parse_mode="HTML"
    )

# ============================================================
# BẢNG XẾP HẠNG XU
# ============================================================

async def command_bxhxu(message, args=""):

    if not is_group(message):
        await send_message(
            chat_id(message),
            "sao ngươi lại ngu thế lệnh này chỉ xài cho nhóm"
        )
        return

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                x.user_id,
                x.xu,
                x.admin_mode,
                u.username,
                u.first_name
            FROM xu_accounts x
            LEFT JOIN users u
                ON u.user_id = x.user_id
            ORDER BY
                x.admin_mode DESC,
                x.xu DESC
            LIMIT 10
            """
        ).fetchall()

    finally:
        conn.close()

    if not rows:
        await send_message(
            chat_id(message),
            "🏆 Chưa có dữ liệu xếp hạng Xu."
        )
        return

    lines = [
        "🏆 <b>BẢNG XẾP HẠNG XU</b>",
        "",
        "💰 Top 10 người có nhiều Xu nhất:",
        ""
    ]

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for index, row in enumerate(rows, 1):

        user_id = row["user_id"]
        username = row["username"]
        first_name = row["first_name"] or "Không tên"

        if row["admin_mode"] == 1:
            balance = "∞"
        else:
            balance = f"{float(row['xu']):.2f}"

        if username:
            display_name = f"@{html.escape(username)}"
        else:
            display_name = html.escape(first_name)

        prefix = (
            medals[index - 1]
            if index <= 3
            else f"<b>{index}.</b>"
        )

        lines.append(
            f"{prefix} {display_name} — "
            f"💰 <code>{balance} Xu</code>"
        )

    await send_message(
        chat_id(message),
        "\n".join(lines),
        parse_mode="HTML"
    )

# ============================================================
# ACHIEVEMENT SYSTEM
# ENGLISH + TIẾNG VIỆT
# ============================================================

ACHIEVEMENTS = [

    # ==================== LEVEL ====================

    {
        "key": "legendary",
        "name": "👑 Legendary — Huyền thoại",
        "description": "Reach Level 6 (Max) — Đạt Level 6 (Max)",
        "metric": "level",
        "value": 6,
    },

    # ==================== CHAT ====================

    {
        "key": "chat_100",
        "name": "🌱 Getting Started — Khởi đầu",
        "description": "Send 100 messages — Gửi 100 tin nhắn",
        "metric": "chat_messages",
        "value": 100,
    },

    {
        "key": "chat_1000",
        "name": "🔥 Hard Worker — Chăm chỉ",
        "description": "Send 1,000 messages — Gửi 1.000 tin nhắn",
        "metric": "chat_messages",
        "value": 1000,
    },

    {
        "key": "chat_2000",
        "name": "⚡ Persistent — Bền bỉ",
        "description": "Send 2,000 messages — Gửi 2.000 tin nhắn",
        "metric": "chat_messages",
        "value": 2000,
    },

    {
        "key": "chat_5000",
        "name": "🚀 Chat Master — Cao thủ chat",
        "description": "Send 5,000 messages — Gửi 5.000 tin nhắn",
        "metric": "chat_messages",
        "value": 5000,
    },

    {
        "key": "the_king_chats",
        "name": "💬 The King Chats — Vua chat",
        "description": "Send 10,000 messages — Gửi 10.000 tin nhắn",
        "metric": "chat_messages",
        "value": 10000,
    },

    {
        "key": "chat_20000",
        "name": "🌌 Endless Chatter — Chat bất tận",
        "description": "Send 20,000 messages — Gửi 20.000 tin nhắn",
        "metric": "chat_messages",
        "value": 20000,
    },

    {
        "key": "chat_50000",
        "name": "🛰️ Super Active — Siêu hoạt động",
        "description": "Send 50,000 messages — Gửi 50.000 tin nhắn",
        "metric": "chat_messages",
        "value": 50000,
    },

    {
        "key": "chat_100000",
        "name": "🌠 Chat Universe — Vũ trụ chat",
        "description": "Send 100,000 messages — Gửi 100.000 tin nhắn",
        "metric": "chat_messages",
        "value": 100000,
    },

    # ==================== XU ====================

    {
        "key": "xu_100",
        "name": "🪙 First Coin — Đồng xu đầu tiên",
        "description": "Own 100 Xu — Sở hữu 100 Xu",
        "metric": "xu",
        "value": 100,
    },

    {
        "key": "xu_500",
        "name": "💵 Getting Rich — Có của",
        "description": "Own 500 Xu — Sở hữu 500 Xu",
        "metric": "xu",
        "value": 500,
    },

    {
        "key": "tycoon",
        "name": "💰 Tycoon — Đại gia",
        "description": "Own 1,000 Xu — Sở hữu 1.000 Xu",
        "metric": "xu",
        "value": 1000,
    },

    {
        "key": "xu_5000",
        "name": "🏦 Treasurer — Kho bạc",
        "description": "Own 5,000 Xu — Sở hữu 5.000 Xu",
        "metric": "xu",
        "value": 5000,
    },

    {
        "key": "typhu",
        "name": "💎 Billionaire — Tỉ phú",
        "description": "Own 10,000 Xu — Sở hữu 10.000 Xu",
        "metric": "xu",
        "value": 10000,
    },

    {
        "key": "xu_50000",
        "name": "💰 Treasure Hoard — Kho báu",
        "description": "Own 50,000 Xu — Sở hữu 50.000 Xu",
        "metric": "xu",
        "value": 50000,
    },

    {
        "key": "xu_100000",
        "name": "👑 Grand Treasury — Đại kho bạc",
        "description": "Own 100,000 Xu — Sở hữu 100.000 Xu",
        "metric": "xu",
        "value": 100000,
    },

    # ==================== CHECK-IN ====================

    {
        "key": "checkin_1",
        "name": "🔥 First Check-in — Điểm danh đầu tiên",
        "description": "Check in once — Điểm danh 1 lần",
        "metric": "checkins",
        "value": 1,
    },

    {
        "key": "checkin_7",
        "name": "📅 Weekly Grinder — Tuần chăm chỉ",
        "description": "7 check-ins — Điểm danh 7 lần",
        "metric": "checkins",
        "value": 7,
    },

    {
        "key": "checkin_30",
        "name": "🗓️ Monthly Grinder — Tháng chăm chỉ",
        "description": "30 check-ins — Điểm danh 30 lần",
        "metric": "checkins",
        "value": 30,
    },

    {
        "key": "checkin_100",
        "name": "🏅 Hundred Days — Trăm ngày",
        "description": "100 check-ins — Điểm danh 100 lần",
        "metric": "checkins",
        "value": 100,
    },

    {
        "key": "checkin_365",
        "name": "🏆 One Year — Một năm",
        "description": "365 check-ins — Điểm danh 365 lần",
        "metric": "checkins",
        "value": 365,
    },

    # ==================== STREAK ====================

    {
        "key": "streak_7",
        "name": "🔥 Streak 7 — Chuỗi 7 ngày",
        "description": "7-day streak — Chuỗi 7 ngày",
        "metric": "max_streak",
        "value": 7,
    },

    {
        "key": "streak_30",
        "name": "🔥 Streak 30 — Chuỗi 30 ngày",
        "description": "30-day streak — Chuỗi 30 ngày",
        "metric": "max_streak",
        "value": 30,
    },

    {
        "key": "streak_100",
        "name": "🔥 Streak 100 — Chuỗi 100 ngày",
        "description": "100-day streak — Chuỗi 100 ngày",
        "metric": "max_streak",
        "value": 100,
    },

    {
        "key": "streak_365",
        "name": "🔥 Streak 365 — Chuỗi 365 ngày",
        "description": "365-day streak — Chuỗi 365 ngày",
        "metric": "max_streak",
        "value": 365,
    },

    # ==================== MEMBER ====================

    {
        "key": "member_7d",
        "name": "🌱 7-Day Member — Thành viên 7 ngày",
        "description": "7 days — 7 ngày",
        "metric": "account_days",
        "value": 7,
    },

    {
        "key": "member_30d",
        "name": "🌿 30-Day Member — Thành viên 30 ngày",
        "description": "30 days — 30 ngày",
        "metric": "account_days",
        "value": 30,
    },

    {
        "key": "member_90d",
        "name": "🌳 90-Day Member — Thành viên 90 ngày",
        "description": "90 days — 90 ngày",
        "metric": "account_days",
        "value": 90,
    },

    {
        "key": "member_180d",
        "name": "🏕️ 180-Day Member — Thành viên 180 ngày",
        "description": "180 days — 180 ngày",
        "metric": "account_days",
        "value": 180,
    },

    {
        "key": "member_365d",
        "name": "🏰 1-Year Member — Thành viên 1 năm",
        "description": "365 days — 365 ngày",
        "metric": "account_days",
        "value": 365,
    },

    {
        "key": "member_730d",
        "name": "👑 Veteran Member — Thành viên lâu năm",
        "description": "2 years — 2 năm",
        "metric": "account_days",
        "value": 730,
    },

    # ==================== WARN ====================

    {
        "key": "warn_1",
        "name": "⚠️ First Warning — Cảnh cáo đầu tiên",
        "description": "Receive 1 warning — Nhận 1 cảnh cáo",
        "metric": "warns",
        "value": 1,
    },

    {
        "key": "warn_5",
        "name": "⚠️ Warning Survivor — Kẻ sống sót",
        "description": "Receive 5 warnings — Nhận 5 cảnh cáo",
        "metric": "warns",
        "value": 5,
    },

    {
        "key": "warn_10",
        "name": "🛡️ Warning Veteran — Trùm cảnh cáo",
        "description": "Receive 10 warnings — Nhận 10 cảnh cáo",
        "metric": "warns",
        "value": 10,
    },

    {
        "key": "warn_20",
        "name": "☠️ Warning Boss — Boss cảnh cáo",
        "description": "Receive 20 warnings — Nhận 20 cảnh cáo",
        "metric": "warns",
        "value": 20,
    },

    # ==================== INVITE ====================

    {
        "key": "invite_1",
        "name": "🤝 Connector — Người kết nối",
        "description": "Invite 1 person — Mời 1 người",
        "metric": "people_added",
        "value": 1,
    },

    {
        "key": "invite_5",
        "name": "👥 Guide — Người dẫn đường",
        "description": "Invite 5 people — Mời 5 người",
        "metric": "people_added",
        "value": 5,
    },

    {
        "key": "invite_10",
        "name": "🚪 Team Builder — Mở rộng đội hình",
        "description": "Invite 10 people — Mời 10 người",
        "metric": "people_added",
        "value": 10,
    },

    {
        "key": "invite_25",
        "name": "🌐 Recruiter — Nhà tuyển dụng",
        "description": "Invite 25 people — Mời 25 người",
        "metric": "people_added",
        "value": 25,
    },

    {
        "key": "invite_50",
        "name": "👑 Recruitment Boss — Ông trùm tuyển thành viên",
        "description": "Invite 50 people — Mời 50 người",
        "metric": "people_added",
        "value": 50,
    },

    # ==================== TASK ====================

    {
        "key": "task_100",
        "name": "💬 Task Chatter — Nhiệm vụ chat",
        "description": "100 task messages — 100 tin nhiệm vụ",
        "metric": "task_messages",
        "value": 100,
    },

    {
        "key": "task_500",
        "name": "🔥 Task Grinder — Cày nhiệm vụ",
        "description": "500 task messages — 500 tin nhiệm vụ",
        "metric": "task_messages",
        "value": 500,
    },

    {
        "key": "task_1000",
        "name": "⚡ Task Machine — Máy nhiệm vụ",
        "description": "1,000 task messages — 1.000 tin nhiệm vụ",
        "metric": "task_messages",
        "value": 1000,
    },

    {
        "key": "share_1",
        "name": "📢 Messenger — Người truyền tin",
        "description": "Share the bot once — Chia sẻ bot 1 lần",
        "metric": "bot_shared",
        "value": 1,
    },

    # ==================== LOST XU ====================

    {
        "key": "lost_100",
        "name": "💸 Lost Some Money — Biết mùi mất Xu",
        "description": "Lose 100 Xu — Mất 100 Xu",
        "metric": "xu_lost",
        "value": 100,
    },

    {
        "key": "lost_1000",
        "name": "😭 Broke Wallet — Cháy ví",
        "description": "Lose 1,000 Xu — Mất 1.000 Xu",
        "metric": "xu_lost",
        "value": 1000,
    },

    {
        "key": "lost_5000",
        "name": "💀 Heavy Loss — Đại cháy ví",
        "description": "Lose 5,000 Xu — Mất 5.000 Xu",
        "metric": "xu_lost",
        "value": 5000,
    },

    {
        "key": "lost_10000",
        "name": "☠️ Bankrupt — Phá sản",
        "description": "Lose 10,000 Xu — Mất 10.000 Xu",
        "metric": "xu_lost",
        "value": 10000,
    },

    {
        "key": "lost_50000",
        "name": "💸 Mega Bankruptcy — Đại phá sản",
        "description": "Lose 50,000 Xu — Mất 50.000 Xu",
        "metric": "xu_lost",
        "value": 50000,
    },

    # ==================== GLOBAL CHAT ====================

    {
        "key": "global_1000",
        "name": "🌟 Active Account — Tài khoản hoạt động",
        "description": "1,000 total messages — 1.000 tin nhắn",
        "metric": "global_messages",
        "value": 1000,
    },

    {
        "key": "global_5000",
        "name": "🌟 Active User — Người dùng tích cực",
        "description": "5,000 total messages — 5.000 tin nhắn",
        "metric": "global_messages",
        "value": 5000,
    },

    {
        "key": "global_10000",
        "name": "🌟 Notable User — Người dùng nổi bật",
        "description": "10,000 total messages — 10.000 tin nhắn",
        "metric": "global_messages",
        "value": 10000,
    },

    {
        "key": "global_50000",
        "name": "🌟 Veteran User — Người dùng kỳ cựu",
        "description": "50,000 total messages — 50.000 tin nhắn",
        "metric": "global_messages",
        "value": 50000,
    },

    {
        "key": "global_100000",
        "name": "💥 Super Account — Siêu tài khoản",
        "description": "100,000 total messages — 100.000 tin nhắn",
        "metric": "global_messages",
        "value": 100000,
    },
]

def start_utils_text():
    return (
        "🧰 <b>TIỆN ÍCH KHÁC</b>\n\n"

        "🏆 <b>BẢNG XẾP HẠNG CHAT</b>\n"
        "<code>/bxhchat</code> — Xem Top 10 thành viên chat nhiều nhất trong nhóm.\n\n"

        "🏆 <b>/thanhtuuhientai</b> — Xem các thành tựu đã mở khóa.\n"
        "Cách dùng: <code>/thanhtuuhientai</code>\n\n"

        "⭐ <b>LEVEL</b>\n"
        "<code>/level</code> — Xem hệ thống level.\n"
        "<code>/levelyou</code> — Xem level của bạn.\n"
        "<code>/levelbxh</code> — Xem bảng xếp hạng.\n"
        "<code>/leveldanhsach</code> — Xem điều kiện lên level.\n"
        "<code>/levelnhiemvu</code> — Xem nhiệm vụ tiếp theo.\n\n"

        "🎮 <b>GAME NỐI CHỮ</b>\n"
        "<code>/noichu</code> — Mở game Nối Chữ Việt Nam.\n"
        "Cách dùng: dùng <code>/noichu</code> trong nhóm rồi bấm "
        "<b>THAM GIA</b>.\n"
        "Bot không cần là admin.\n\n"

        "🔥 <b>ĐIỂM DANH</b>\n"
        "<code>/diemdanh</code> — Điểm danh hằng ngày.\n\n"

        "❤️ <b>THƠ</b>\n"
        "<code>/thotinh</code> — Random thơ tình.\n"
        "<code>/thodoi</code> — Random thơ đời.\n\n"

        "💤 <b>AFK</b>\n"
        "<code>/afk [lý do]</code> — Bật trạng thái AFK.\n\n"

        "🔎 <b>FILTER</b>\n"
        "<code>/filter từ khóa | nội dung</code> — Tạo phản hồi tự động.\n"
        "<code>/filters</code> — Xem filter.\n"
        "<code>/stopfilter từ khóa</code> — Xóa filter.\n\n"

        "🛠 <b>TIỆN ÍCH</b>\n"
        "<code>/id</code> — Xem ID.\n"
        "<code>/info</code> — Xem thông tin.\n"
        "<code>/ping</code> — Kiểm tra bot.\n"
        "<code>/time</code> — Xem thời gian.\n"
        "<code>/stats</code> — Xem thống kê.\n"
        "<code>/echo nội dung</code> — Bot lặp lại nội dung.\n"
        "<code>/calc phép_tính</code> — Tính toán.\n"
        "<code>/search từ khóa</code> — Tìm kiếm.\n"
        "<code>/weather địa điểm</code> — Xem thời tiết.\n"
        "<code>/short link</code> — Rút gọn liên kết."
    )


async def send_start_menu(message):

    user = from_user(message) or {}

    username = user.get("username")

    if username:
        greeting = "@" + html.escape(username)
    else:
        greeting = html.escape(
            user.get("first_name", "bạn")
        )

    text = (
        f"👋 <b>Chào {greeting}, tôi là Ngọc Mỹ.</b>\n\n"
        "Tôi có nhiều công cụ hữu ích. "
        "Chạm vào một module bên dưới để xem lệnh.\n\n"
        "Tôi hỗ trợ Tiếng Việt 🇻🇳 và English 🇺🇸"
    )

    await api(
        "sendMessage",
        {
            "chat_id": chat_id(message),
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(
                start_main_keyboard()
            )
        }
    )


async def handle_start_menu_callback(callback):

    data = callback.get("data")
    message = callback.get("message") or {}
    callback_id = callback.get("id")

    if data == "start_home":

        text = (
            "🏠 <b>Chào mừng trở lại với Ngọc Mỹ.</b>\n\n"
            "Tôi có nhiều công cụ hữu ích. "
            "Chạm vào một module bên dưới để xem lệnh.\n\n"
            "Tôi hỗ trợ Tiếng Việt 🇻🇳 và English 🇺🇸"
        )

        keyboard = start_main_keyboard()

    elif data == "start_admin":

        text = start_admin_text()
        keyboard = start_back_keyboard()

    elif data == "start_taixiu":
        user_id = (callback.get("from") or {}).get("id", 0)

        account = get_xu_account(user_id)

        if account and account[4] == 1:
            balance = "∞"
        else:
            balance = f"{get_xu(user_id):.2f}"

        text = (
            "🎲 <b>TÀI XỈU ẢO</b>\n\n"
            f"💰 <b>Xu của bạn:</b> <code>{balance}</code>\n\n"
            "🎲 <b>Tài Xỉu</b>\n"
            "Dùng:\n"
            "<code>/taixiu tai 10</code>\n"
            "<code>/taixiu xiu 10</code>\n\n"
            "🎯 Cược tối thiểu: <b>10 Xu</b>\n"
            "🏆 Thắng: nhận <b>2× tiền cược</b>\n"
            "💸 Thua: mất tiền cược\n\n"
            "🎯 <b>Nhiệm vụ</b>\n"
            "<code>/nhiemvutong</code>\n\n"
            "🏆 <b>Bảng xếp hạng Xu</b>\n"
            "<code>/bxhxu</code>\n\n"
            "💰 <b>Ví Xu</b>\n"
            "<code>/xume</code>\n\n"
            "📉 <b>Xu đã mất</b>\n"
            "<code>/xudamat</code>"
        )

        keyboard = start_back_keyboard()

    elif data == "start_utils":

        text = start_utils_text()
        keyboard = start_back_keyboard()

    else:

        return False

    await api(
        "editMessageText",
        {
            "chat_id": message.get(
                "chat",
                {}
            ).get("id"),

            "message_id":
                message.get("message_id"),

            "text": text,

            "parse_mode": "HTML",

            "reply_markup":
                json.dumps(keyboard)
        }
    )

    await answer_callback(
        callback_id,
        ""
    )

    return True

async def command_start(
    message
):

    user = from_user(
        message
    )

    if user:
        await save_user(
            user
        )

    await send_start_menu(
        message
    )

    message

    message

HELP_TEXT = (
    "🤖 NGỌC MỸ — DANH SÁCH LỆNH\n\n"

    "👤 LỆNH CƠ BẢN\n"
    "/start → Khởi động bot\n"
    "/help → Xem hướng dẫn sử dụng\n"
    "/id → Xem ID Telegram\n"
    "/info → Xem thông tin tài khoản\n"
    "/ping → Kiểm tra bot\n"
    "/time → Xem thời gian\n"
    "/stats → Xem thống kê bot\n"
    "/settings → Xem cài đặt nhóm\n\n"

    "🛠 TIỆN ÍCH\n"
    "/echo → Bot lặp lại nội dung\n"
    "/calc → Tính phép tính\n"
    "/search → Tìm kiếm thông tin\n"
    "/weather → Xem thời tiết\n"
    "/short → Rút gọn liên kết\n\n"

    "🛡 QUẢN LÝ NHÓM\n"
    "/warn → Cảnh cáo thành viên\n"
    "/warns → Xem cảnh cáo\n"
    "/mute → Khóa chat thành viên\n"
    "/unmute → Mở khóa chat\n"
    "/kick → Đá thành viên\n"
    "/ban → Cấm thành viên\n"
    "/unban → Gỡ cấm thành viên\n"
    "/purge → Xóa nhiều tin nhắn\n"
    "/pin → Ghim tin nhắn\n"
    "/unpin → Bỏ ghim\n"
    "/lock → Khóa chat\n"
    "/unlock → Mở khóa chat\n\n"

    "👑 QUẢN TRỊ BOT\n"
    "/admins → Xem quản trị viên\n"
    "/broadcast → Gửi thông báo\n"
    "/users → Xem người dùng\n"
    "/banuser → Cấm người dùng bot\n"
    "/unbanuser → Gỡ cấm người dùng bot\n"
    "/restart → Khởi động lại bot\n"
    "/logs → Xem log\n\n"

    "⚙️ HỆ THỐNG\n"
    "/database → Kiểm tra database\n"
    "/health → Kiểm tra tình trạng bot\n"
    "/version → Xem phiên bản\n\n"

    "🛡 BẢO VỆ\n"
    "/antispam on|off → Chống spam\n"
    "/antilink on|off → Chống link\n"
    "/antibuff on|off → Chống buff\n"
    "/antifake on|off → Chống giả mạo\n\n"

    "💤 AFK\n"
    "/afk [lý do] → Bật trạng thái AFK\n\n"

    "🔎 FILTER\n"
    "/filter → Tạo filter tự động trả lời\n"
    "/filters → Xem các filter\n"
    "/stopfilter → Xóa filter\n\n"

    "❤️ THƠ\n"
    "/thodoi → Random thơ đời\n"
    "/thotinh → Random thơ tình\n\n"

    "🔥 ĐIỂM DANH\n"
    "/diemdanh → Điểm danh hằng ngày\n\n"

    "⭐ LEVEL\n"
    "/level → Hệ thống level\n"
    "/levelyou → Xem level hiện tại\n"
    "/levelbxh → Xem bảng xếp hạng level\n"
    "/leveldanhsach → Xem điều kiện lên level\n"
    "/levelnhiemvu → Xem nhiệm vụ tiếp theo\n\n"

    "\n💰 HỆ THỐNG XU\n"
    "/xume → Xem số Xu và thông tin tài khoản\n"
    "/xudamat → Xem tổng Xu đã mất\n"
    "/nhapcode khoinghieptanthu → Nhận 100 Xu tân thủ\n"
    "/nhiemvutong → Xem tổng 2 nhiệm vụ Xu\n"
    "/nhiemvuthuong → Nhận nhiệm vụ thường, mời 1 người +20 Xu\n"
    "/nhiemvucao → Nhận nhiệm vụ cao, mời 5 người +100 Xu\n"
    "/chiasebot → Chia sẻ bot, không tự cộng Xu nếu chưa nhận nhiệm vụ\n"
    "/taixiu tai 10 → Cược Tài\n"
    "/taixiu xiu 10 → Cược Xỉu\n"
    "/xuadmin MÃ → Kích hoạt phần mềm Admin\n\n"

    "🎮 TRÒ CHƠI — NỐI CHỮ VIỆT NAM\n"
    "/noichu → Mở trò chơi Nối Chữ\n"
    "→ Bấm THAM GIA để vào game\n"
    "→ Cần ít nhất 2 người chơi\n"
    "→ Game bắt đầu sau 3 phút\n"
    "→ Nối sai sẽ bị loại\n"
    "→ Người cuối cùng còn lại thắng\n\n"

    "👑 Owner: @DTN_207"
)

async def command_help(
    message
):

    if is_group(message):

        await send_message(
            chat_id(message),
            (
                "xin lỗi bạn tôi ko hỗ trợ help nhóm"
            )
        )

        return

    await send_message(
        chat_id(message),
        HELP_TEXT
    )


async def command_id(
    message
):

    user = (
        message.get(
            "reply_to_message",
            {}
        ).get("from")
        or from_user(message)
    )

    if not user:

        return

    username = (
        "@"
        + html.escape(
            user["username"]
        )
        if user.get("username")
        else "Không có"
    )

    await send_message(
        chat_id(message),
        (
            "🆔 <b>TELEGRAM ID</b>\n\n"
            f"👤 Tên: "
            f"{html.escape(user_full_name(user))}\n"
            f"🆔 ID: "
            f"<code>{user.get('id')}</code>\n"
            f"🔗 Username: "
            f"{username}"
        )
    )


async def command_info(
    message
):

    user = from_user(
        message
    )

    if not user:

        return

    username = (
        "@"
        + html.escape(
            user["username"]
        )
        if user.get("username")
        else "Không có"
    )

    language = (
        user.get(
            "language_code"
        )
        or "Không xác định"
    )

    await send_message(
        chat_id(message),
        (
            "👤 <b>THÔNG TIN TÀI KHOẢN</b>\n\n"
            f"📛 Tên: "
            f"{html.escape(user_full_name(user))}\n"
            f"🆔 ID: "
            f"<code>{user.get('id')}</code>\n"
            f"🔗 Username: "
            f"{username}\n"
            f"🌐 Ngôn ngữ: "
            f"{html.escape(language)}\n"
            f"🤖 Bot: "
            f"{'Có' if user.get('is_bot') else 'Không'}"
        )
    )


async def command_ping(
    message
):

    start = time.perf_counter()

    result = await send_message(
        chat_id(message),
        "🏓 <b>Pong!</b>\n"
        "⏳ Đang kiểm tra..."
    )

    elapsed = (
        time.perf_counter()
        - start
    ) * 1000

    sent = (
        result.get("result")
        if result.get("ok")
        else None
    )

    if sent:

        await edit_message(
            chat_id(message),
            sent.get(
                "message_id"
            ),
            (
                "🏓 <b>Pong!</b>\n\n"
                f"⚡ Response: "
                f"<code>{elapsed:.2f} ms</code>\n"
                f"🟢 Status Online"
            )
        )


async def command_time(
    message
):

    now = datetime.now()

    await send_message(
        chat_id(message),
        (
            "🕐 <b>THỜI GIAN HIỆN TẠI</b>\n\n"
            f"📅 Ngày: "
            f"<code>"
            f"{now.strftime('%d/%m/%Y')}"
            f"</code>\n"
            f"⏰ Giờ: "
            f"<code>"
            f"{now.strftime('%H:%M:%S')}"
            f"</code>"
        )
    )


async def command_stats(
    message
):

    users = await adb_execute(
        "SELECT COUNT(*) AS c FROM users",
        fetchone=True
    )

    warns = await adb_execute(
        "SELECT COUNT(*) AS c FROM warns",
        fetchone=True
    )

    filters = await adb_execute(
        "SELECT COUNT(*) AS c FROM filters",
        fetchone=True
    )

    checkins = await adb_execute(
        "SELECT COUNT(*) AS c FROM checkins",
        fetchone=True
    )

    await send_message(
        chat_id(message),
        (
            "📊 <b>BOT STATISTICS</b>\n\n"
            f"👥 Users: "
            f"<code>{users['c']}</code>\n"
            f"⚠️ Warns: "
            f"<code>{warns['c']}</code>\n"
            f"🔎 Filters: "
            f"<code>{filters['c']}</code>\n"
            f"🔥 Check-ins: "
            f"<code>{checkins['c']}</code>\n"
            f"📨 Runtime messages: "
            f"<code>"
            f"{RUNTIME_STATS['messages']}"
            f"</code>\n"
            f"🛡 Protection actions: "
            f"<code>"
            f"{RUNTIME_STATS['deleted']}"
            f"</code>\n"
            f"⏱ Uptime: "
            f"<code>{get_uptime()}</code>\n"
            f"📦 Version: "
            f"<code>{VERSION}</code>"
        )
    )


async def command_settings(
    message
):

    if not await require_admin(
        message
    ):

        return

    chat = chat_id(
        message
    )

    antispam = await get_setting(
        chat,
        "antispam"
    )

    antilink = await get_setting(
        chat,
        "antilink"
    )

    antibuff = await get_setting(
        chat,
        "antibuff"
    )

    antifake = await get_setting(
        chat,
        "antifake"
    )

    def status(value):

        return (
            "🟢 ON"
            if value
            else "🔴 OFF"
        )

    await send_message(
        chat,
        (
            "⚙️ <b>GROUP SETTINGS</b>\n\n"
            f"🚫 AntiSpam: "
            f"{status(antispam)}\n"
            f"🔗 AntiLink: "
            f"{status(antilink)}\n"
            f"👥 AntiBuff: "
            f"{status(antibuff)}\n"
            f"🎭 AntiFake: "
            f"{status(antifake)}\n\n"
            f"💡 Dùng:\n"
            f"<code>/antispam on|off</code>\n"
            f"<code>/antilink on|off</code>\n"
            f"<code>/antibuff on|off</code>\n"
            f"<code>/antifake on|off</code>"
        )
    )


# ============================================================
# COMMAND TABLE
# ============================================================

COMMAND_HANDLERS = {

    "thanhtuuhientai": command_thanhtuuhientai,

    "bxhxu": command_bxhxu,

    "bxhchat": command_bxhchat,

    "thangcap": command_thangcap,

    "start":
        command_start,

    "help":
        command_help,

    "id":
        command_id,

    "info":
        command_info,

    "ping":
        command_ping,

    "time":
        command_time,

    "stats":
        command_stats,

    "settings":
        command_settings,

    "level": command_level,
    "levelyou": command_levelyou,
    "levelbxh": command_levelbxh,
    "leveldanhsach": command_leveldanhsach,
    "levelnhiemvu": command_levelnhiemvu,
    "noichu": command_noichu,
}


# ============================================================
# COMMAND DISPATCHER
# ============================================================

async def dispatch_command(
    message
):

    command, args = parse_command(
        message
    )

    if not command:

        return False

    handler = COMMAND_HANDLERS.get(
        command
    )

    if not handler:

        return False

    await handler(
        message
    )

    return True


# ============================================================
# UPDATE PROCESSING
# ============================================================

async def noichu_handle_text(message):
    """
    Xử lý tin nhắn trong game Nối Chữ.
    Trả về True nếu tin nhắn thuộc game, False nếu không.
    """
    chat = message.get("chat", {})
    if chat.get("type") not in ("group", "supergroup"):
        return False

    chat_id = chat["id"]
    game = NOICHU_GAMES.get(chat_id)

    if not game or game.get("status") != "playing":
        return False

    user = message.get("from", {})
    user_id = user.get("id")
    text = (message.get("text") or "").strip()

    if not text or not user_id:
        return False

    # Chỉ người đã tham gia game mới được tính là người chơi
    player_ids = game.get("players", [])

    if user_id not in player_ids:
        return False

    # Chưa đến lượt
    if game.get("current_player") != user_id:
        await send_message(
            chat_id,
            "mày chưa đến lượt bớt tài lanh đi"
        )
        return True

    # Chuẩn hóa câu người chơi nhập
    phrase = noichu_norm(text)

    if not phrase:
        return True

    # Không cho nhập quá dài
    if len(phrase) > 100:
        await send_message(
            chat_id,
            "Câu quá dài, tối đa 100 ký tự."
        )
        return True

    previous_phrase = game.get("last_phrase", "")

    # Nếu đây không phải lượt đầu tiên:
    # từ đầu câu mới phải nối được với từ cuối câu trước
    if previous_phrase:
        required_word = noichu_last_word(previous_phrase)
        first_word = noichu_first_word(phrase)

        if not required_word or not first_word or first_word != required_word:
            # Người chơi nói sai -> bị loại
            game.setdefault("eliminated", set()).add(user_id)

            if user_id in game["players"]:
                game["players"].remove(user_id)

            name = noichu_name(user)

            await send_message(
                chat_id,
                f"❌ {name} đã nối sai và bị loại khỏi trò chơi!"
            )

            # Nếu chỉ còn 1 người
            if len(game["players"]) <= 1:
                await noichu_finish(chat_id)
                return True

            # Chuyển lượt
            game["last_phrase"] = previous_phrase
            game["last_player"] = None

            await noichu_next_turn(chat_id)
            return True

    # ===== NỐI ĐÚNG =====

    now = time.time()

    turn_started = game.get("turn_started_at", now)
    response_time = max(0.1, now - turn_started)

    # Ghi thống kê
    stats = game.setdefault(
        "stats",
        {}
    )

    user_stats = stats.setdefault(
        user_id,
        {
            "valid": 0,
            "invalid": 0,
            "total_time": 0.0,
            "best_time": None,
            "total_length": 0
        }
    )

    user_stats["valid"] += 1
    user_stats["total_time"] += response_time
    user_stats["total_length"] += len(phrase.split())

    if (
        user_stats["best_time"] is None
        or response_time < user_stats["best_time"]
    ):
        user_stats["best_time"] = response_time

    # Lưu câu vừa nói
    game["last_phrase"] = phrase
    game["last_player"] = user_id

    # Lưu thời gian để tính lượt tiếp theo
    game["last_response_time"] = response_time

    # Thông báo câu hợp lệ
    await send_message(
        chat_id,
        f"✅ {noichu_name(user)}: {phrase}"
    )

    # Chuyển lượt tiếp theo
    await noichu_next_turn(chat_id)

    return True

async def process_update(
    update
):

    if not isinstance(
        update,
        dict
    ):

        return

    message = (
        update.get("message")
        or update.get("edited_message")
    )

    if not message:

        return

    user = from_user(
        message
    )

    if user:

        await save_user(
            user
        )

    RUNTIME_STATS[
        "messages"
    ] += 1

    if is_group(message):

        RUNTIME_STATS[
            "groups"
        ] += 1

    elif is_private(message):

        RUNTIME_STATS[
            "private"
        ] += 1

    # Bot ban được xử lý trước command.
    if user:

        if await is_bot_banned(
            user.get("id")
        ):

            if is_owner(user):

                pass

            else:

                return

    await dispatch_command(
        message
    )


# ============================================================
# GET UPDATES
# ============================================================

async def get_updates(
    offset=None,
    timeout=30
):

    data = {
        "timeout": timeout,
        "allowed_updates": json.dumps(
            [
                "message",
                "edited_message",
                "chat_member"
            ]
        )
    }

    if offset is not None:

        data["offset"] = offset

    return await api(
        "getUpdates",
        data,
        timeout=timeout + 10
    )


# ============================================================
# POLLING ENGINE
# ============================================================

async def polling_loop():

    global LAST_UPDATE_ID
    global BOT_RUNNING

    logger.info(
        "Polling started."
    )

    while BOT_RUNNING:

        try:

            offset = (
                LAST_UPDATE_ID + 1
                if LAST_UPDATE_ID
                else None
            )

            result = await get_updates(
                offset=offset,
                timeout=30
            )

            if not result.get("ok"):

                logger.warning(
                    "getUpdates failed: %s",
                    result.get(
                        "description"
                    )
                )

                await asyncio.sleep(
                    3
                )

                continue

            updates = result.get(
                "result",
                []
            )

            for update in updates:

                LAST_UPDATE_ID = max(
                    LAST_UPDATE_ID,
                    update.get(
                        "update_id",
                        0
                    )
                )

                try:

                    await process_update(
                        update
                    )

                except Exception as e:

                    logger.exception(
                        "Update processing error: %s",
                        e
                    )

        except KeyboardInterrupt:

            BOT_RUNNING = False

            break

        except Exception as e:

            logger.exception(
                "Polling error: %s",
                e
            )

            await asyncio.sleep(
                5
            )


# ============================================================
# END PHẦN 2/10
# ============================================================

# ============================================================
# NGỌC MỸ - PURE PYTHON VERSION
# PHẦN 3/10
# UTILITY COMMANDS
# /echo /calc /search /weather /short
# ============================================================


# ============================================================
# ECHO
# ============================================================

async def command_echo(message, args):

    if not args:

        await send_message(
            chat_id(message),
            "❗ Dùng: <code>/echo nội dung</code>"
        )

        return

    await send_message(
        chat_id(message),
        html.escape(args)
    )


# ============================================================
# SAFE CALCULATOR
# ============================================================

CALC_OPERATORS = {
    "add": None,
    "sub": None,
    "mul": None,
    "div": None,
    "mod": None,
    "pow": None,
}


def safe_calculate(expression):

    expression = expression.strip()

    if not expression:

        raise ValueError(
            "Biểu thức trống."
        )

    if len(expression) > 200:

        raise ValueError(
            "Biểu thức quá dài."
        )

    allowed = re.fullmatch(
        r"[0-9+\-*/%().,\s]+",
        expression
    )

    if not allowed:

        raise ValueError(
            "Biểu thức chứa ký tự không hợp lệ."
        )

    expression = expression.replace(
        ",",
        "."
    )

    def evaluate(node):

        if isinstance(
            node,
            __import__("ast").Expression
        ):

            return evaluate(
                node.body
            )

        if isinstance(
            node,
            __import__("ast").Constant
        ):

            value = node.value

            if isinstance(
                value,
                (int, float)
            ):

                if abs(value) > 10**100:

                    raise ValueError(
                        "Số quá lớn."
                    )

                return value

            raise ValueError(
                "Giá trị không hợp lệ."
            )

        if isinstance(
            node,
            __import__("ast").UnaryOp
        ):

            value = evaluate(
                node.operand
            )

            if isinstance(
                node.op,
                __import__("ast").UAdd
            ):

                return +value

            if isinstance(
                node.op,
                __import__("ast").USub
            ):

                return -value

            raise ValueError(
                "Toán tử không hợp lệ."
            )

        if isinstance(
            node,
            __import__("ast").BinOp
        ):

            left = evaluate(
                node.left
            )

            right = evaluate(
                node.right
            )

            ast = __import__(
                "ast"
            )

            if isinstance(
                node.op,
                ast.Add
            ):

                result = left + right

            elif isinstance(
                node.op,
                ast.Sub
            ):

                result = left - right

            elif isinstance(
                node.op,
                ast.Mult
            ):

                result = left * right

            elif isinstance(
                node.op,
                ast.Div
            ):

                if right == 0:

                    raise ValueError(
                        "Không thể chia cho 0."
                    )

                result = left / right

            elif isinstance(
                node.op,
                ast.Mod
            ):

                if right == 0:

                    raise ValueError(
                        "Không thể chia cho 0."
                    )

                result = left % right

            elif isinstance(
                node.op,
                ast.Pow
            ):

                if abs(right) > 100:

                    raise ValueError(
                        "Số mũ quá lớn."
                    )

                result = left ** right

            else:

                raise ValueError(
                    "Toán tử không được hỗ trợ."
                )

            if isinstance(
                result,
                (int, float)
            ) and abs(result) > 10**100:

                raise ValueError(
                    "Kết quả quá lớn."
                )

            return result

        raise ValueError(
            "Biểu thức không hợp lệ."
        )

    import ast

    tree = ast.parse(
        expression,
        mode="eval"
    )

    result = evaluate(tree)

    if isinstance(
        result,
        float
    ):

        if result.is_integer():

            return str(
                int(result)
            )

        return f"{result:12g}"

    return str(result)


async def command_calc(
    message,
    args
):

    if not args:

        await send_message(
            chat_id(message),
            (
                "🧮 Dùng:\n"
                "<code>/calc 2+2</code>\n"
                "<code>/calc (10*5)/2</code>"
            )
        )

        return

    try:

        result = safe_calculate(
            args
        )

        await send_message(
            chat_id(message),
            (
                "🧮 <b>KẾT QUẢ</b>\n\n"
                f"📐 <code>"
                f"{html.escape(args)}"
                f"</code>\n"
                f"🟰 <code>{result}</code>"
            )
        )

    except Exception as e:

        await send_message(
            chat_id(message),
            (
                "❌ <b>Không thể tính.</b>\n"
                f"ℹ️ {html.escape(str(e))}"
            )
        )


# ============================================================
# HTTP GET HELPER
# Không dùng aiohttp / requests
# ============================================================

async def http_get(
    url,
    timeout=15
):

    def fetch():

        request = Request(
            url,
            headers={
                "User-Agent":
                    "THEONE-Bot/3.0"
            }
        )

        with urlopen(
            request,
            timeout=timeout
        ) as response:

            return response.read().decode(
                "utf-8",
                errors="replace"
            )

    return await asyncio.to_thread(
        fetch
    )


# ============================================================
# SEARCH
# DuckDuckGo Instant Answer API
# ============================================================

async def command_search(
    message,
    args
):

    if not args:

        await send_message(
            chat_id(message),
            (
                "🔎 Dùng:\n"
                "<code>/search từ khóa</code>"
            )
        )

        return

    try:

        url = (
            "https://api.duckduckgo.com/?"
            + urlencode(
                {
                    "q": args,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "0"
                }
            )
        )

        raw = await http_get(
            url
        )

        data = json.loads(
            raw
        )

        abstract = data.get("AbstractText", "")

        if abstract:
            result = html.escape(abstract[:3000])
        else:
            result = "Không tìm thấy kết quả phù hợp."

        await send_message(
            chat_id(message),
            result
        )

    except Exception as e:

        logger.warning(
            "Search error: %s",
            e
        )

        await send_message(
            chat_id(message),
            (
                "❌ Không thể tìm kiếm "
                "lúc này."
            )
        )


# ============================================================
# WEATHER
# wttr.in
# ============================================================

async def command_weather(
    message,
    args
):

    if not args:

        await send_message(
            chat_id(message),
            (
                "🌤 Dùng:\n"
                "<code>/weather Cà Mau</code>"
            )
        )

        return

    try:

        city = args.strip()

        url = (
            "https://wttr.in/"
            + __import__(
                "urllib.parse",
                fromlist=["quote"]
            ).quote(
                city
            )
            + "?format=j1"
        )

        raw = await http_get(
            url
        )

        data = json.loads(
            raw
        )

        current = (
            data.get(
                "current_condition",
                [{}]
            )[0]
        )

        temp = current.get(
            "temp_C",
            "?"
        )

        feels = current.get(
            "FeelsLikeC",
            "?"
        )

        humidity = current.get(
            "humidity",
            "?"
        )

        wind = current.get(
            "windspeedKmph",
            "?"
        )

        descriptions = (
            current.get(
                "weatherDesc",
                [{}]
            )
        )

        description = (
            descriptions[0].get(
                "value",
                "Không rõ"
            )
            if descriptions
            else "Không rõ"
        )

        await send_message(
            chat_id(message),
            (
                "🌤 <b>THỜI TIẾT</b>\n\n"
                f"📍 Thành phố: "
                f"<b>{html.escape(city)}</b>\n"
                f"🌡 Nhiệt độ: "
                f"<code>{temp}°C</code>\n"
                f"🤒 Cảm giác: "
                f"<code>{feels}°C</code>\n"
                f"☁️ Trạng thái: "
                f"{html.escape(description)}\n"
                f"💧 Độ ẩm: "
                f"<code>{humidity}%</code>\n"
                f"💨 Gió: "
                f"<code>{wind} km/h</code>"
            )
        )

    except Exception as e:

        logger.warning(
            "Weather error: %s",
            e
        )

        await send_message(
            chat_id(message),
            (
                "❌ Không lấy được "
                "thời tiết.\n"
                "Hãy kiểm tra tên thành phố."
            )
        )


# ============================================================
# URL SHORTENER
# is.gd
# ============================================================

async def command_short(
    message,
    args
):

    if not args:

        await send_message(
            chat_id(message),
            (
                "🔗 Dùng:\n"
                "<code>/short https://example.com</code>"
            )
        )

        return

    url = args.strip()

    if not re.match(
        r"^https?://",
        url,
        re.IGNORECASE
    ):

        await send_message(
            chat_id(message),
            (
                "❌ URL phải bắt đầu bằng "
                "<code>http://</code> hoặc "
                "<code>https://</code>."
            )
        )

        return

    try:

        api_url = (
            "https://is.gd/create.php?"
            + urlencode(
                {
                    "format": "simple",
                    "url": url
                }
            )
        )

        short_url = (
            await http_get(
                api_url
            )
        ).strip()

        if (
            not short_url
            or not short_url.startswith(
                "http"
            )
        ):

            raise ValueError(
                "Invalid short URL"
            )

        await send_message(
            chat_id(message),
            (
                "🔗 <b>LINK ĐÃ RÚT GỌN</b>\n\n"
                f"🌐 URL gốc:\n"
                f"<code>{html.escape(url)}</code>\n\n"
                f"⚡ Link mới:\n"
                f'<a href="{html.escape(short_url)}">'
                f"{html.escape(short_url)}"
                "</a>"
            )
        )

    except Exception as e:

        logger.warning(
            "Short URL error: %s",
            e
        )

        await send_message(
            chat_id(message),
            (
                "❌ Không thể rút gọn "
                "liên kết này."
            )
        )


# ============================================================
# REGISTER UTILITY COMMANDS
# ============================================================

COMMAND_HANDLERS.update({

    "echo":
        lambda message, args:
            command_echo(
                message,
                args
            ),

    "calc":
        lambda message, args:
            command_calc(
                message,
                args
            ),

    "search":
        lambda message, args:
            command_search(
                message,
                args
            ),

    "weather":
        lambda message, args:
            command_weather(
                message,
                args
            ),

    "short":
        lambda message, args:
            command_short(
                message,
                args
            ),
})


# ============================================================
# IMPROVED COMMAND DISPATCHER
# ============================================================

async def dispatch_command(
    message
):

    command, args = parse_command(
        message
    )

    if not command:

        return False

    handler = COMMAND_HANDLERS.get(
        command
    )

    if not handler:

        return False

    try:

        await handler(
            message,
            args
        )

    except TypeError:

        # Các handler cũ không nhận args.
        await handler(
            message
        )

    return True


# ============================================================
# END PHẦN 3/10
# ============================================================

# ============================================================
# THEONE BOT - PURE PYTHON VERSION
# PHẦN 4/10
# GROUP MODERATION
# /warn /warns /mute /unmute /kick /ban /unban
# /purge /pin /unpin /lock /unlock
# ============================================================



# ============================================================
# MUTE
# Telegram restrictChatMember
# ============================================================

async def command_mute(
    message,
    args
):

    if not await require_admin(message):
        return

    if not await bot_is_admin(message):

        await send_message(
            chat_id(message),
            (
                "❌ Bot chưa là admin "
                "hoặc không có quyền hạn chế thành viên."
            )
        )

        return

    target = await resolve_target(
        message,
        args
    )

    if not await ensure_valid_target(
        message,
        target
    ):
        return

    parts = args.split()

    duration = None

    for part in parts:

        parsed = parse_duration(
            part
        )

        if parsed is not None:

            duration = parsed

            break

    if duration is None:

        duration = 3600

    until_date = int(
        time.time()
        + duration
    )

    result = await api(
        "restrictChatMember",
        {
            "chat_id":
                chat_id(message),

            "user_id":
                target.get("id"),

            "permissions":
                json.dumps(
                    {
                        "can_send_messages": False,
                        "can_send_audios": False,
                        "can_send_documents": False,
                        "can_send_photos": False,
                        "can_send_videos": False,
                        "can_send_video_notes": False,
                        "can_send_voice_notes": False,
                        "can_send_polls": False,
                        "can_send_other_messages": False,
                        "can_add_web_page_previews": False,
                        "can_change_info": False,
                        "can_invite_users": False,
                        "can_pin_messages": False,
                        "can_manage_topics": False
                    }
                ),

            "until_date":
                until_date
        }
    )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không thể mute.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        return

    await send_message(
        chat_id(message),
        (
            "🔇 <b>ĐÃ MUTE</b>\n\n"
            f"👤 {mention_user(target)}\n"
            f"⏱ Thời gian: "
            f"<code>{format_duration(duration)}</code>"
        )
    )


# ============================================================
# UNMUTE
# ============================================================

async def command_unmute(
    message,
    args
):

    if not await require_admin(message):
        return

    if not await bot_is_admin(message):

        await send_message(
            chat_id(message),
            "❌ Bot không có quyền quản lý thành viên."
        )

        return

    target = await resolve_target(
        message,
        args
    )

    if not await ensure_valid_target(
        message,
        target
    ):
        return

    result = await api(
        "restrictChatMember",
        {
            "chat_id":
                chat_id(message),

            "user_id":
                target.get("id"),

            "permissions":
                json.dumps(
                    {
                        "can_send_messages": True,
                        "can_send_audios": True,
                        "can_send_documents": True,
                        "can_send_photos": True,
                        "can_send_videos": True,
                        "can_send_video_notes": True,
                        "can_send_voice_notes": True,
                        "can_send_polls": True,
                        "can_send_other_messages": True,
                        "can_add_web_page_previews": True,
                        "can_change_info": False,
                        "can_invite_users": True,
                        "can_pin_messages": False,
                        "can_manage_topics": False
                    }
                )
        }
    )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không thể unmute.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        await send_message(
            chat_id(message),
            "❌ Bot không có quyền ban thành viên."
        )

        return

    target = await resolve_target(
        message,
        args
    )

    if not await ensure_valid_target(
        message,
        target
    ):
        return

    duration = None

    for part in args.split():

        parsed = parse_duration(
            part
        )

        if parsed is not None:

            duration = parsed

            break

    data = {
        "chat_id":
            chat_id(message),

        "user_id":
            target.get("id"),

        "revoke_messages":
            True
    }

    if duration is not None:

        data["until_date"] = int(
            time.time()
            + duration
        )

    result = await api(
        "banChatMember",
        data
    )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không thể ban.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        return

    duration_text = (
        format_duration(duration)
        if duration
        else "Vĩnh viễn"
    )

    await send_message(
        chat_id(message),
        (
            "🔨 <b>ĐÃ BAN</b>\n\n"
            f"👤 {mention_user(target)}\n"
            f"⏱ Thời gian: "
            f"<code>{duration_text}</code>"
        )
    )


# ============================================================
# UNBAN
# ============================================================

async def command_unban(
    message,
    args
):

    if not await require_admin(message):
        return

    if not await bot_is_admin(message):

        await send_message(
            chat_id(message),
            "❌ Bot không có quyền unban."
        )

        return

    target = await resolve_target(
        message,
        args
    )

    if not await ensure_valid_target(
        message,
        target
    ):
        return

    result = await api(
        "unbanChatMember",
        {
            "chat_id":
                chat_id(message),

            "user_id":
                target.get("id"),

            "only_if_banned":
                False
        }
    )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không thể unban.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        return

    await send_message(
        chat_id(message),
        (
            "🔓 <b>ĐÃ UNBAN</b>\n\n"
            f"👤 {mention_user(target)}"
        )
    )


# ============================================================
# PURGE
# ============================================================

async def command_purge(
    message,
    args
):

    if not await require_admin(message):
        return

    if not await bot_is_admin(message):

        await send_message(
            chat_id(message),
            "❌ Bot không có quyền xóa tin nhắn."
        )

        return

    try:

        amount = int(
            args.split()[0]
        )

    except Exception:

        amount = 10

    amount = max(
        1,
        min(
            amount,
            100
        )
    )

    current_id = message_id(
        message
    )

    deleted = 0

    for msg_id in range(
        current_id,
        max(
            0,
            current_id - amount
        ),
        -1
    ):

        result = await delete_message(
            chat_id(message),
            msg_id
        )

        if result.get("ok"):

            deleted += 1

            RUNTIME_STATS[
                "deleted"
            ] += 1

    confirmation = await send_message(
        chat_id(message),
        (
            "🧹 Đã xóa "
            f"<code>{deleted}</code> "
            "tin nhắn."
        )
    )

    if confirmation.get("ok"):

        await asyncio.sleep(
            2
        )

        await delete_message(
            chat_id(message),
            confirmation["result"]["message_id"]
        )

# ============================================================
# PIN
# ============================================================

async def command_pin(
    message,
    args
):

    if not await require_admin(message):
        return

    reply = message.get(
        "reply_to_message"
    )

    if not reply:

        await send_message(
            chat_id(message),
            "❗ Hãy reply tin nhắn cần ghim."
        )

        return

    result = await pin_message(
        chat_id(message),
        reply.get("message_id")
    )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không thể ghim.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        return

    await send_message(
        chat_id(message),
        "📌 Đã ghim tin nhắn."
    )


# ============================================================
# UNPIN
# ============================================================

async def command_unpin(
    message,
    args
):

    if not await require_admin(message):
        return

    reply = message.get(
        "reply_to_message"
    )

    if reply:

        result = await unpin_message(
            chat_id(message),
            reply.get("message_id")
        )

    else:

        result = await api(
            "unpinChatMessage",
            {
                "chat_id":
                    chat_id(message)
            }
        )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không thể bỏ ghim.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        return

    await send_message(
        chat_id(message),
        "📌 Đã bỏ ghim."
    )


# ============================================================
# LOCK
# ============================================================

async def command_lock(
    message,
    args
):

    if not await require_admin(message):
        return

    if not await bot_is_admin(message):

        await send_message(
            chat_id(message),
            "❌ Bot không có quyền khóa nhóm."
        )

        return

    result = await api(
        "setChatPermissions",
        {
            "chat_id":
                chat_id(message),

            "permissions":
                json.dumps(
                    {
                        "can_send_messages": False,
                        "can_send_audios": False,
                        "can_send_documents": False,
                        "can_send_photos": False,
                        "can_send_videos": False,
                        "can_send_video_notes": False,
                        "can_send_voice_notes": False,
                        "can_send_polls": False,
                        "can_send_other_messages": False,
                        "can_add_web_page_previews": False,
                        "can_change_info": False,
                        "can_invite_users": False,
                        "can_pin_messages": False,
                        "can_manage_topics": False
                    }
                )
        }
    )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không thể khóa nhóm.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        return

    await send_message(
        chat_id(message),
        "🔒 <b>ĐÃ KHÓA NHÓM</b>"
    )


# ============================================================
# UNLOCK
# ============================================================

async def command_unlock(
    message,
    args
):

    if not await require_admin(message):
        return

    if not await bot_is_admin(message):

        await send_message(
            chat_id(message),
            "❌ Bot không có quyền mở khóa nhóm."
        )

        return

    result = await api(
        "setChatPermissions",
        {
            "chat_id":
                chat_id(message),

            "permissions":
                json.dumps(
                    {
                        "can_send_messages": True,
                        "can_send_audios": True,
                        "can_send_documents": True,
                        "can_send_photos": True,
                        "can_send_videos": True,
                        "can_send_video_notes": True,
                        "can_send_voice_notes": True,
                        "can_send_polls": True,
                        "can_send_other_messages": True,
                        "can_add_web_page_previews": True,
                        "can_change_info": False,
                        "can_invite_users": True,
                        "can_pin_messages": False,
                        "can_manage_topics": False
                    }
                )
        }
    )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không thể mở khóa nhóm.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        return

    await send_message(
        chat_id(message),
        "🔓 <b>ĐÃ MỞ KHÓA NHÓM</b>"
    )


# ============================================================
# REGISTER MODERATION COMMANDS
# ============================================================

COMMAND_HANDLERS.update({

    "warn":
        lambda message, args:
            command_warn(
                message,
                args
            ),

    "warns":
        lambda message, args:
            command_warns(
                message,
                args
            ),

    "mute":
        lambda message, args:
            command_mute(
                message,
                args
            ),

    "unmute":
        lambda message, args:
            command_unmute(
                message,
                args
            ),

    "kick":
        lambda message, args:
            command_kick(
                message,
                args
            ),

    "ban":
        lambda message, args:
            command_ban(
                message,
                args
            ),

    "unban":
        lambda message, args:
            command_unban(
                message,
                args
            ),

    "purge":
        lambda message, args:
            command_purge(
                message,
                args
            ),

    "pin":
        lambda message, args:
            command_pin(
                message,
                args
            ),

    "unpin":
        lambda message, args:
            command_unpin(
                message,
                args
            ),

    "lock":
        lambda message, args:
            command_lock(
                message,
                args
            ),

    "unlock":
        lambda message, args:
            command_unlock(
                message,
                args
            ),
})


# ============================================================
# END PHẦN 4/10
# ============================================================

# ============================================================
# THEONE BOT - PURE PYTHON VERSION
# PHẦN 5/10
# BOT ADMIN + SYSTEM
# /admins /broadcast /users /banuser /unbanuser
# /restart /logs /database /health /version
# ============================================================


# ============================================================
# ADMIN LIST
# ============================================================

async def command_admins(
    message,
    args
):

    if not await require_group(message):
        return

    result = await api(
        "getChatAdministrators",
        {
            "chat_id":
                chat_id(message)
        }
    )

    if not result.get("ok"):

        await send_message(
            chat_id(message),
            (
                "❌ Không lấy được danh sách admin.\n"
                f"ℹ️ {html.escape(result.get('description', 'Unknown'))}"
            )
        )

        return

    admins = result.get(
        "result",
        []
    )

    lines = [
        "👑 <b>QUẢN TRỊ VIÊN NHÓM</b>\n"
    ]

    for index, member in enumerate(
        admins,
        1
    ):

        user = member.get(
            "user",
            {}
        )

        status = member.get(
            "status",
            ""
        )

        role = (
            "👑 Owner"
            if status == "creator"
            else "🛡 Admin"
        )

        username = (
            "@" + html.escape(
                user.get("username")
            )
            if user.get("username")
            else "Không có username"
        )

        lines.append(
            f"{index}. "
            f"{mention_user(user)}\n"
            f"   {role} | {username}"
        )

    await send_message(
        chat_id(message),
        "\n".join(lines)
    )


# ============================================================
# GET ALL KNOWN USER IDS
# ============================================================

async def get_all_user_ids():

    rows = await adb_execute(
        """
        SELECT user_id
        FROM users
        ORDER BY user_id
        """,
        fetch=True
    )

    return [
        row["user_id"]
        for row in rows
    ]

# ============================================================
# BROADCAST
# ============================================================

async def command_broadcast(
    message,
    args
):

    if not await require_owner(message):
        return

    if not args:

        await send_message(
            chat_id(message),
            (
                "📢 Dùng:\n"
                "<code>/broadcast nội dung</code>"
            )
        )

        return

    users = await get_all_user_ids()

    if not users:

        await send_message(
            chat_id(message),
            "📢 Chưa có user nào trong database."
        )

        return

    success = 0
    failed = 0

    status_message = await send_message(
        chat_id(message),
        (
            "📢 <b>ĐANG BROADCAST</b>\n\n"
            f"👥 Tổng: <code>{len(users)}</code>"
        )
    )

    for user_id in users:

        result = await send_message(
            user_id,
            args
        )

        if result.get("ok"):

            success += 1

        else:

            failed += 1

        # Giảm tốc độ gửi để hạn chế Telegram flood limit.
        await asyncio.sleep(
            0.05
        )

    text = (
        "📢 <b>BROADCAST HOÀN TẤT</b>\n\n"
        f"✅ Thành công: <code>{success}</code>\n"
        f"❌ Thất bại: <code>{failed}</code>\n"
        f"👥 Tổng: <code>{len(users)}</code>"
    )

    if status_message.get("ok"):

        await edit_message(
            chat_id(message),
            status_message["result"]["message_id"],
            text
        )

    else:

        await send_message(
            chat_id(message),
            text
        )


# ============================================================
# USERS
# ============================================================

async def command_users(
    message,
    args
):

    if not await require_owner(message):
        return

    row = await adb_execute(
        """
        SELECT COUNT(*) AS c
        FROM users
        """,
        fetchone=True
    )

    groups = RUNTIME_STATS[
        "groups"
    ]

    private = RUNTIME_STATS[
        "private"
    ]

    await send_message(
        chat_id(message),
        (
            "👥 <b>USER DATABASE</b>\n\n"
            f"👤 Users: <code>{row['c']}</code>\n"
            f"👥 Group messages: <code>{groups}</code>\n"
            f"💬 Private messages: <code>{private}</code>"
        )
    )


# ============================================================
# BAN USER FROM BOT
# ============================================================

async def command_banuser(
    message,
    args
):

    if not await require_owner(message):
        return

    target = await resolve_target(
        message,
        args
    )

    if not target:

        await send_message(
            chat_id(message),
            (
                "❗ Dùng:\n"
                "<code>/banuser ID</code>"
            )
        )

        return

    target_id = target.get(
        "id"
    )

    if not target_id:

        await send_message(
            chat_id(message),
            "❌ ID không hợp lệ."
        )

        return

    if is_owner(
        target
    ):

        await send_message(
            chat_id(message),
            "❌ Không thể ban Owner."
        )

        return

    await adb_execute(
        """
        INSERT INTO bot_bans
        (
            user_id,
            reason,
            created_at
        )
        VALUES (?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            reason = excluded.reason,
            created_at = excluded.created_at
        """,
        (
            target_id,
            args,
            datetime.now(
                timezone.utc
            ).isoformat()
        )
    )

    await send_message(
        chat_id(message),
        (
            "🚫 <b>ĐÃ CẤM USER DÙNG BOT</b>\n\n"
            f"🆔 ID: <code>{target_id}</code>"
        )
    )


# ============================================================
# UNBAN USER FROM BOT
# ============================================================

async def command_unbanuser(
    message,
    args
):

    if not await require_owner(message):
        return

    target = await resolve_target(
        message,
        args
    )

    if not target:

        await send_message(
            chat_id(message),
            (
                "❗ Dùng:\n"
                "<code>/unbanuser ID</code>"
            )
        )

        return

    target_id = target.get(
        "id"
    )

    if not target_id:

        await send_message(
            chat_id(message),
            "❌ ID không hợp lệ."
        )

        return

    await adb_execute(
        """
        DELETE FROM bot_bans
        WHERE user_id = ?
        """,
        (
            target_id,
        )
    )

    await send_message(
        chat_id(message),
        (
            "🔓 <b>ĐÃ GỠ CẤM USER</b>\n\n"
            f"🆔 ID: <code>{target_id}</code>"
        )
    )


# ============================================================
# RESTART
# ============================================================

async def command_restart(
    message,
    args
):

    global BOT_RUNNING

    if not await require_owner(message):
        return

    await send_message(
        chat_id(message),
        "🔄 <b>Đang khởi động lại bot...</b>"
    )

    BOT_RUNNING = False

    # Thoát process để Railway / Termux
    # có thể tự khởi động lại process.
    await asyncio.sleep(
        1
    )

    os._exit(0)


# ============================================================
# LOGS
# ============================================================

async def command_logs(
    message,
    args
):

    if not await require_owner(message):
        return

    rows = await adb_execute(
        """
        SELECT
            user_id,
            username,
            first_name,
            last_seen,
            message_count
        FROM users
        ORDER BY last_seen DESC
        LIMIT 15
        """,
        fetch=True
    )

    lines = [
        "📜 <b>RECENT USER LOGS</b>\n"
    ]

    if not rows:

        lines.append(
            "Chưa có dữ liệu."
        )

    else:

        for row in rows:

            username = (
                "@"
                + row["username"]
                if row["username"]
                else "no_username"
            )

            first_name = (
                row["first_name"]
                or "Unknown"
            )

            lines.append(
                f"👤 "
                f"{html.escape(first_name)} "
                f"({html.escape(username)})\n"
                f"🆔 <code>{row['user_id']}</code>\n"
                f"💬 Messages: "
                f"<code>{row['message_count']}</code>\n"
                f"🕐 Last: "
                f"<code>{html.escape(row['last_seen'])}</code>\n"
            )

    await send_message(
        chat_id(message),
        "\n".join(lines)
    )


# ============================================================
# DATABASE
# ============================================================

async def command_database(
    message,
    args
):

    if not await require_owner(message):
        return

    conn = db_connect()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        )

        tables = [
            row[0]
            for row in cursor.fetchall()
        ]

        try:

            size = os.path.getsize(
                DATABASE
            )

        except Exception:

            size = 0

    finally:

        conn.close()

    size_kb = size / 1024

    await send_message(
        chat_id(message),
        (
            "🗄 <b>DATABASE</b>\n\n"
            f"📦 File: "
            f"<code>{html.escape(DATABASE)}</code>\n"
            f"💾 Size: "
            f"<code>{size_kb:.2f} KB</code>\n"
            f"📚 Tables: "
            f"<code>{len(tables)}</code>\n\n"
            f"🧩 "
            f"{html.escape(', '.join(tables))}"
        )
    )


# ============================================================
# HEALTH
# ============================================================

async def command_health(
    message,
    args
):

    start = time.perf_counter()

    telegram = await api(
        "getMe"
    )

    elapsed = (
        time.perf_counter()
        - start
    ) * 1000

    db_ok = False

    try:

        row = await adb_execute(
            "SELECT 1 AS ok",
            fetchone=True
        )

        db_ok = (
            row
            and row["ok"] == 1
        )

    except Exception:

        db_ok = False

    telegram_status = (
        "🟢 OK"
        if telegram.get("ok")
        else "🔴 ERROR"
    )

    database_status = (
        "🟢 OK"
        if db_ok
        else "🔴 ERROR"
    )

    await send_message(
        chat_id(message),
        (
            "💚 <b>BOT HEALTH</b>\n\n"
            f"🤖 Telegram API: "
            f"{telegram_status}\n"
            f"🗄 Database: "
            f"{database_status}\n"
            f"⚡ API latency: "
            f"<code>{elapsed:.2f} ms</code>\n"
            f"⏱ Uptime: "
            f"<code>{get_uptime()}</code>\n"
            f"📦 Version: "
            f"<code>{VERSION}</code>"
        )
    )


# ============================================================
# VERSION
# ============================================================

async def command_version(
    message,
    args
):

    await send_message(
        chat_id(message),
        (
            "🤖 <b>THEONE BOT</b>\n\n"
            f"📦 Version: "
            f"<code>{VERSION}</code>\n"
            "🐍 Runtime: "
            f"<code>Python {sys.version.split()[0]}</code>\n"
            "🗄 Database: "
            "<code>SQLite3</code>\n"
            "🌐 API: "
            "<code>Telegram Bot API</code>\n"
            "⚙️ Mode: "
            "<code>Pure Python</code>"
        )
    )


# ============================================================
# REGISTER BOT ADMIN + SYSTEM COMMANDS
# ============================================================

COMMAND_HANDLERS.update({

    "admins":
        lambda message, args:
            command_admins(
                message,
                args
            ),

    "broadcast":
        lambda message, args:
            command_broadcast(
                message,
                args
            ),

    "users":
        lambda message, args:
            command_users(
                message,
                args
            ),

    "banuser":
        lambda message, args:
            command_banuser(
                message,
                args
            ),

    "unbanuser":
        lambda message, args:
            command_unbanuser(
                message,
                args
            ),

    "restart":
        lambda message, args:
            command_restart(
                message,
                args
            ),

    "logs":
        lambda message, args:
            command_logs(
                message,
                args
            ),

    "database":
        lambda message, args:
            command_database(
                message,
                args
            ),

    "health":
        lambda message, args:
            command_health(
                message,
                args
            ),

    "version":
        lambda message, args:
            command_version(
                message,
                args
            ),
})


# ============================================================
# END PHẦN 5/10
# ============================================================

# ============================================================
# THEONE BOT - PURE PYTHON VERSION
# PHẦN 6/10
# PROTECTION SYSTEM
# /antispam /antilink /antibuff /antifake
# ============================================================


# ============================================================
# PROTECTION CONFIG
# ============================================================

PROTECTION_KEYS = {
    "antispam",
    "antilink",
    "antibuff",
    "antifake",
}


# ============================================================
# TEXT / LINK HELPERS
# ============================================================

URL_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/)",
    re.IGNORECASE
)

USERNAME_PATTERN = re.compile(
    r"@[A-Za-z0-9_]{4,32}"
)


def message_text(message):

    return (
        message.get("text")
        or message.get("caption")
        or ""
    )


def contains_link(text):

    if not text:
        return False

    return bool(
        URL_PATTERN.search(
            text
        )
    )


# ============================================================
# ANTISPAM
# ============================================================

SPAM_WINDOW = 8
SPAM_LIMIT = 6


async def handle_antispam(
    message
):

    if not is_group(message):
        return False

    chat = chat_id(
        message
    )

    if not await get_setting(
        chat,
        "antispam",
        False
    ):
        return False

    user = from_user(
        message
    )

    if not user:
        return False

    user_id = user.get(
        "id"
    )

    now = time.time()

    key = (
        chat,
        user_id
    )

    queue = SPAM_TRACKER[
        key
    ]

    queue.append(
        now
    )

    while queue and (
        now - queue[0]
        > SPAM_WINDOW
    ):

        queue.popleft()

    if len(queue) < SPAM_LIMIT:
        return False

    # Xóa tin nhắn spam hiện tại.
    deleted = await delete_message(
        chat,
        message_id(message)
    )

    if deleted.get("ok"):

        RUNTIME_STATS[
            "deleted"
        ] += 1

    # Reset để không xóa liên tục
    # mọi tin nhắn sau đó.
    queue.clear()

    await send_message(
        chat,
        (
            "🛡 <b>ANTISPAM</b>\n\n"
            f"👤 {mention_user(user)}\n"
            "⚠️ Phát hiện gửi quá nhiều "
            "tin nhắn trong thời gian ngắn."
        )
    )

    return True


# ============================================================
# ANTILINK
# ============================================================

async def handle_antilink(
    message
):

    if not is_group(message):
        return False

    chat = chat_id(
        message
    )

    if not await get_setting(
        chat,
        "antilink",
        False
    ):
        return False

    text = message_text(
        message
    )

    if not contains_link(
        text
    ):
        return False

    user = from_user(
        message
    )

    # Admin được phép gửi link.
    if await is_admin(
        message
    ):
        return False

    result = await delete_message(
        chat,
        message_id(message)
    )

    if result.get("ok"):

        RUNTIME_STATS[
            "deleted"
        ] += 1

    await send_message(
        chat,
        (
            "🔗 <b>ANTILINK</b>\n\n"
            f"👤 {mention_user(user)}\n"
            "🚫 Link đã bị xóa."
        )
    )

    return True


# ============================================================
# PROFILE NORMALIZATION
# Dùng cho antifake
# ============================================================

UNICODE_CONFUSABLES = str.maketrans({
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "х": "x",
    "у": "y",
    "і": "i",
    "ј": "j",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Χ": "X",
})


def normalize_profile_name(
    text
):

    if not text:
        return ""

    text = str(
        text
    ).translate(
        UNICODE_CONFUSABLES
    )

    text = re.sub(
        r"[\u200b-\u200f\u202a-\u202e\ufeff]",
        "",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip().lower()


def profile_display_name(
    user
):

    return normalize_profile_name(
        user_full_name(user)
    )


# ============================================================
# SAVE / GET KNOWN PROFILE
# ============================================================

async def get_known_profile(
    chat,
    user_id
):

    return await adb_execute(
        """
        SELECT *
        FROM known_profiles
        WHERE chat_id = ?
        AND user_id = ?
        """,
        (
            chat,
            user_id
        ),
        fetchone=True
    )


async def save_known_profile(
    chat,
    user
):

    if not user:
        return

    await adb_execute(
        """
        INSERT INTO known_profiles
        (
            chat_id,
            user_id,
            username,
            display_name,
            first_seen
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            username =
                excluded.username,
            display_name =
                excluded.display_name
        """,
        (
            chat,
            user.get(
                "username"
            ),
            profile_display_name(
                user
            ),
            datetime.now(
                timezone.utc
            ).isoformat()
        )
    )


# ============================================================
# ANTI-FAKE
# ============================================================

async def handle_antifake(
    message
):

    if not is_group(message):
        return False

    chat = chat_id(
        message
    )

    if not await get_setting(
        chat,
        "antifake",
        False
    ):
        return False

    user = from_user(
        message
    )

    if not user:
        return False

    # Bot không xử lý chính nó.
    if user.get(
        "is_bot"
    ):
        return False

    user_id = user.get(
        "id"
    )

    current_name = profile_display_name(
        user
    )

    current_username = (
        user.get(
            "username"
        )
        or ""
    ).lower()

    known = await get_known_profile(
        chat,
        user_id
    )

    if not known:

        await save_known_profile(
            chat,
            user
        )

        return False

    old_name = normalize_profile_name(
        known["display_name"]
        or ""
    )

    old_username = (
        known["username"]
        or ""
    ).lower()

    suspicious = False
    reasons = []

    # Username thay đổi.
    if (
        old_username
        and current_username
        and old_username
        != current_username
    ):

        reasons.append(
            "username thay đổi"
        )

    # Tên hiển thị thay đổi.
    if (
        old_name
        and current_name
        and old_name
        != current_name
    ):

        reasons.append(
            "tên hiển thị thay đổi"
        )

    # Ký tự Unicode bất thường.
    raw_name = user_full_name(
        user
    )

    if re.search(
        r"[\u200b-\u200f\u202a-\u202e\ufeff]",
        raw_name
    ):

        suspicious = True

        reasons.append(
            "ký tự Unicode ẩn"
        )

    # Nếu có thay đổi profile nhưng chưa đủ
    # bằng chứng thì chỉ cảnh báo nhẹ.
    if reasons:

        suspicious = True

    if suspicious:

        # Cập nhật profile mới nhưng không tự động ban.
        await save_known_profile(
            chat,
            user
        )

        await send_message(
            chat,
            (
                "🎭 <b>ANTIFAKE CẢNH BÁO</b>\n\n"
                f"👤 {mention_user(user)}\n"
                "⚠️ Profile có dấu hiệu thay đổi:\n"
                + "\n".join(
                    f"• {html.escape(reason)}"
                    for reason in reasons
                )
                + "\n\n"
                "ℹ️ Bot chỉ cảnh báo vì thay đổi "
                "profile không tự nó chứng minh "
                "tài khoản giả mạo."
            )
        )

        return True

    await save_known_profile(
        chat,
        user
    )

    return False


# ============================================================
# ANTIBUFF
#
# Phát hiện cụm join bất thường.
# Không kết luận tài khoản là fake chỉ từ
# profile; dùng nhiều tín hiệu.
# ============================================================

JOIN_WINDOW = 60
JOIN_LIMIT = 8


def get_chat_member_count_data(
    chat
):

    return None


async def handle_chat_member_update(
    update
):

    chat_member = update.get(
        "chat_member"
    )

    if not chat_member:
        return

    chat = chat_member.get(
        "chat",
        {}
    )

    chat_type = chat.get(
        "type"
    )

    if chat_type not in GROUP_TYPES:
        return

    chat_value = chat.get(
        "id"
    )

    new_member = chat_member.get(
        "new_chat_member",
        {}
    )

    old_member = chat_member.get(
        "old_chat_member",
        {}
    )

    new_status = new_member.get(
        "status"
    )

    old_status = old_member.get(
        "status"
    )

    # Chỉ xử lý user vừa vào / vừa được thêm.
    joined = (
        new_status in {
            "member",
            "administrator",
            "creator"
        }
        and old_status in {
            "left",
            "kicked"
        }
    )

    if not joined:
        return

    user = new_member.get(
        "user",
        {}
    )

    if not user:
        return

    RUNTIME_STATS[
        "joins"
    ] += 1

    if not await get_setting(
        chat_value,
        "antibuff",
        False
    ):
        return

    now = time.time()

    queue = JOIN_TRACKER[
        chat_value
    ]

    queue.append(
        (
            now,
            user.get("id")
        )
    )

    while queue and (
        now - queue[0][0]
        > JOIN_WINDOW
    ):

        queue.popleft()

    join_count = len(
        queue
    )

    # Một cụm join lớn trong thời gian ngắn.
    if join_count >= JOIN_LIMIT:

        recent_users = [
            item[1]
            for item in queue
        ]

        unique_users = len(
            set(
                recent_users
            )
        )

        if unique_users >= JOIN_LIMIT:

            # Chỉ cảnh báo admin.
            # Không tự động ban hàng loạt.
            await send_message(
                chat_value,
                (
                    "👥 <b>ANTIBUFF CẢNH BÁO</b>\n\n"
                    f"⚠️ Phát hiện "
                    f"<code>{unique_users}</code> "
                    "tài khoản tham gia trong "
                    f"<code>{JOIN_WINDOW}s</code>.\n\n"
                    "🔎 Đây là dấu hiệu join bất thường, "
                    "không phải bằng chứng chắc chắn "
                    "rằng các tài khoản là fake/buff.\n\n"
                    "🛡 Hãy kiểm tra danh sách thành viên "
                    "và hoạt động thực tế trước khi xử lý."
                )
            )

            # Reset sau cảnh báo để tránh spam cảnh báo.
            queue.clear()


# ============================================================
# PROTECTION TOGGLE
# ============================================================

async def command_protection_toggle(
    message,
    args,
    protection_name
):

    if not await require_admin(
        message
    ):
        return

    value = args.strip().lower()

    if value not in {
        "on",
        "off"
    }:

        await send_message(
            chat_id(message),
            (
                f"🛡 Dùng:\n"
                f"<code>/{protection_name} on</code>\n"
                f"<code>/{protection_name} off</code>"
            )
        )

        return

    enabled = (
        value == "on"
    )

    await set_setting(
        chat_id(message),
        protection_name,
        enabled
    )

    status = (
        "🟢 ON"
        if enabled
        else "🔴 OFF"
    )

    await send_message(
        chat_id(message),
        (
            "🛡 <b>PROTECTION UPDATED</b>\n\n"
            f"🔧 {html.escape(protection_name)}: "
            f"<b>{status}</b>"
        )
    )


async def command_antispam(
    message,
    args
):

    await command_protection_toggle(
        message,
        args,
        "antispam"
    )


async def command_antilink(
    message,
    args
):

    await command_protection_toggle(
        message,
        args,
        "antilink"
    )


async def command_antibuff(
    message,
    args
):

    await command_protection_toggle(
        message,
        args,
        "antibuff"
    )


async def command_antifake(
    message,
    args
):

    await command_protection_toggle(
        message,
        args,
        "antifake"
    )


# ============================================================
# REGISTER PROTECTION COMMANDS
# ============================================================

COMMAND_HANDLERS.update({

    "antispam":
        lambda message, args:
            command_antispam(
                message,
                args
            ),

    "antilink":
        lambda message, args:
            command_antilink(
                message,
                args
            ),

    "antibuff":
        lambda message, args:
            command_antibuff(
                message,
                args
            ),

    "antifake":
        lambda message, args:
            command_antifake(
                message,
                args
            ),
})


# ============================================================
# PROTECTION PIPELINE
# ============================================================

async def run_message_protection(
    message
):

    if not is_group(
        message
    ):
        return False

    # Owner / admin không bị antispam,
    # antilink xử lý.
    user = from_user(
        message
    )

    if user and await is_admin(
        message
    ):

        # Vẫn cho antifake kiểm tra profile,
        # nhưng không chặn.
        await handle_antifake(
            message
        )

        return False

    # AntiSpam
    if await handle_antispam(
        message
    ):

        return True

    # AntiLink
    if await handle_antilink(
        message
    ):

        return True

    # AntiFake
    if await handle_antifake(
        message
    ):

        # Chỉ cảnh báo, không chặn message.
        return False

    return False


# ============================================================
# UPDATE CHAT MEMBER SUPPORT
# ============================================================

async def process_chat_member_update(
    update
):

    try:

        await handle_chat_member_update(
            update
        )

    except Exception as e:

        logger.exception(
            "Chat member protection error: %s",
            e
        )


# ============================================================
# PATCH PROCESS UPDATE
# để chạy protection trước command
# ============================================================

_original_process_update = process_update


async def process_update(
    update
):

    if not isinstance(
        update,
        dict
    ):
        return

    if update.get(
        "chat_member"
    ):

        await process_chat_member_update(
            update
        )

        return

    message = (
        update.get("message")
        or update.get("edited_message")
    )

    if not message:
        return

    user = from_user(
        message
    )

    if user:
        await save_user(
            user
        )

    RUNTIME_STATS[
        "messages"
    ] += 1

    if is_group(
        message
    ):

        RUNTIME_STATS[
            "groups"
        ] += 1

    elif is_private(
        message
    ):

        RUNTIME_STATS[
            "private"
        ] += 1

    if user and await is_bot_banned(
        user.get("id")
    ):

        if not is_owner(
            user
        ):

            return

    # Protection chạy trước command.
    blocked = await run_message_protection(
        message
    )

    if blocked:
        return

    await dispatch_command(
        message
    )


# ============================================================
# END PHẦN 6/10
# ============================================================

# ============================================================
# THEONE BOT - PURE PYTHON VERSION
# PHẦN 7/10
# AFK + FILTER SYSTEM
# /afk /filter /filters /stopfilter
# ============================================================


# ============================================================
# AFK HELPERS
# ============================================================

async def set_afk(
    user_id,
    reason
):

    if not reason:
        reason = "Không có lý do"

    now = datetime.now(
        timezone.utc
    ).isoformat()

    await adb_execute(
        """
        INSERT INTO afk
        (
            user_id,
            reason,
            created_at
        )
        VALUES (?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            reason = excluded.reason,
            created_at = excluded.created_at
        """,
        (
            user_id,
            reason,
            now
        )
    )

    AFK_CACHE[
        user_id
    ] = {
        "reason": reason,
        "created_at": now
    }


async def get_afk(
    user_id
):

    cached = AFK_CACHE.get(
        user_id
    )

    if cached:
        return cached

    row = await adb_execute(
        """
        SELECT
            user_id,
            reason,
            created_at
        FROM afk
        WHERE user_id = ?
        """,
        (
            user_id,
        ),
        fetchone=True
    )

    if not row:
        return None

    data = {
        "reason": row["reason"],
        "created_at": row["created_at"]
    }

    AFK_CACHE[
        user_id
    ] = data

    return data


async def clear_afk(
    user_id
):

    await adb_execute(
        """
        DELETE FROM afk
        WHERE user_id = ?
        """,
        (
            user_id,
        )
    )

    AFK_CACHE.pop(
        user_id,
        None
    )


def format_afk_time(
    created_at
):

    try:

        created = datetime.fromisoformat(
            created_at
        )

        if created.tzinfo is None:

            created = created.replace(
                tzinfo=timezone.utc
            )

        elapsed = (
            datetime.now(
                timezone.utc
            )
            - created
        ).total_seconds()

        elapsed = max(
            0,
            int(elapsed)
        )

        return format_duration(
            elapsed
        )

    except Exception:

        return "một lúc"


# ============================================================
# /AFK
# ============================================================

async def command_afk(
    message,
    args
):

    user = from_user(
        message
    )

    if not user:
        return

    reason = (
        args.strip()
        if args.strip()
        else "Không có lý do"
    )

    await set_afk(
        user.get("id"),
        reason
    )

    await send_message(
        chat_id(message),
        (
            "💤 <b>ĐÃ BẬT AFK</b>\n\n"
            f"👤 {mention_user(user)}\n"
            f"📝 Lý do: "
            f"{html.escape(reason)}\n\n"
            "💬 Khi bạn gửi tin nhắn mới, "
            "AFK sẽ tự động tắt."
        )
    )


# ============================================================
# EXTRACT MENTIONED USERS
# ============================================================

def mentioned_user_ids(
    message
):

    entities = (
        message.get(
            "entities"
        )
        or []
    )

    text = message.get(
        "text"
        or ""
    )

    result = []

    for entity in entities:

        if entity.get(
            "type"
        ) == "text_mention":

            user = entity.get(
                "user"
            )

            if user and user.get(
                "id"
            ):

                result.append(
                    user.get("id")
                )

    # Telegram có entity "mention" nhưng không
    # cung cấp user ID trực tiếp. Không tự đoán ID.
    return result


async def find_afk_targets(
    message
):

    targets = set()

    reply = message.get(
        "reply_to_message"
    )

    if reply:

        reply_user = reply.get(
            "from"
        )

        if reply_user and reply_user.get(
            "id"
        ):

            targets.add(
                reply_user.get("id")
            )

    for user_id in mentioned_user_ids(
        message
    ):

        targets.add(
            user_id
        )

    return list(
        targets
    )


# ============================================================
# HANDLE AFK NOTIFICATIONS
# ============================================================

async def handle_afk_notification(
    message
):

    targets = await find_afk_targets(
        message
    )

    if not targets:
        return False

    notified = False

    for user_id in targets:

        data = await get_afk(
            user_id
        )

        if not data:
            continue

        row = await adb_execute(
            """
            SELECT
                first_name,
                last_name,
                username
            FROM users
            WHERE user_id = ?
            """,
            (
                user_id,
            ),
            fetchone=True
        )

        if row:

            fake_user = {
                "id":
                    user_id,

                "first_name":
                    row["first_name"]
                    or "User",

                "last_name":
                    row["last_name"]
                    or "",

                "username":
                    row["username"]
            }

        else:

            fake_user = {
                "id":
                    user_id,

                "first_name":
                    "User"
            }

        elapsed = format_afk_time(
            data["created_at"]
        )

        await send_message(
            chat_id(message),
            (
                "💤 <b>NGƯỜI DÙNG ĐANG AFK</b>\n\n"
                f"👤 {mention_user(fake_user)}\n"
                f"📝 Lý do: "
                f"{html.escape(data['reason'])}\n"
                f"⏱ AFK: "
                f"<code>{elapsed}</code>"
            ),
            reply_to=message_id(message)
        )

        RUNTIME_STATS[
            "afk_notifications"
        ] += 1

        notified = True

    return notified


# ============================================================
# CLEAR AFK WHEN USER RETURNS
# ============================================================

async def handle_afk_return(
    message
):

    user = from_user(
        message
    )

    if not user:
        return False

    user_id = user.get(
        "id"
    )

    data = await get_afk(
        user_id
    )

    if not data:
        return False

    elapsed = format_afk_time(
        data["created_at"]
    )

    await clear_afk(
        user_id
    )

    await send_message(
        chat_id(message),
        (
            "👋 <b>CHÀO MỪNG QUAY LẠI</b>\n\n"
            f"👤 {mention_user(user)}\n"
            f"⏱ Bạn đã AFK: "
            f"<code>{elapsed}</code>\n"
            "🟢 AFK đã được tắt."
        )
    )

    return True


# ============================================================
# FILTER HELPERS
# ============================================================

def normalize_filter_keyword(
    keyword
):

    return re.sub(
        r"\s+",
        " ",
        keyword.strip().lower()
    )


async def get_filters(
    chat
):

    return await adb_execute(
        """
        SELECT
            id,
            keyword,
            response
        FROM filters
        WHERE chat_id = ?
        ORDER BY id ASC
        """,
        (
            chat,
        ),
        fetch=True
    )


# ============================================================
# /FILTER
# ============================================================

async def command_filter(
    message,
    args
):

    if not await require_admin(
        message
    ):
        return

    if "|" not in args:

        await send_message(
            chat_id(message),
            (
                "🔎 <b>Cách dùng</b>\n\n"
                "<code>/filter từ khóa | nội dung trả lời</code>\n\n"
                "Ví dụ:\n"
                "<code>/filter hello | Xin chào!</code>"
            )
        )

        return

    keyword, response = args.split(
        "|",
        1
    )

    keyword = normalize_filter_keyword(
        keyword
    )

    response = response.strip()

    if not keyword:

        await send_message(
            chat_id(message),
            "❌ Từ khóa không được để trống."
        )

        return

    if not response:

        await send_message(
            chat_id(message),
            "❌ Nội dung trả lời không được để trống."
        )

        return

    if len(keyword) > 200:

        await send_message(
            chat_id(message),
            "❌ Từ khóa quá dài."
        )

        return

    if len(response) > 3500:

        await send_message(
            chat_id(message),
            "❌ Nội dung trả lời quá dài."
        )

        return

    existing = await adb_execute(
        """
        SELECT id
        FROM filters
        WHERE chat_id = ?
        AND keyword = ?
        """,
        (
            chat_id(message),
            keyword
        ),
        fetchone=True
    )

    if existing:

        await adb_execute(
            """
            UPDATE filters
            SET response = ?
            WHERE id = ?
            """,
            (
                response,
                existing["id"]
            )
        )

        action = "đã cập nhật"

    else:

        await adb_execute(
            """
            INSERT INTO filters
            (
                chat_id,
                keyword,
                response
            )
            VALUES (?, ?, ?)
            """,
            (
                chat_id(message),
                keyword,
                response
            )
        )

        action = "đã tạo"

    await send_message(
        chat_id(message),
        (
            "🔎 <b>FILTER</b>\n\n"
            f"✅ Đã {action}.\n"
            f"🔑 Từ khóa: "
            f"<code>{html.escape(keyword)}</code>\n"
            f"💬 Phản hồi: "
            f"{html.escape(response)}"
        )
    )


# ============================================================
# /FILTERS
# ============================================================

async def command_filters(
    message,
    args
):

    if not await require_group(
        message
    ):
        return

    rows = await get_filters(
        chat_id(message)
    )

    if not rows:

        await send_message(
            chat_id(message),
            "🔎 Nhóm chưa có filter nào."
        )

        return

    lines = [
        "🔎 <b>DANH SÁCH FILTER</b>\n"
    ]

    for index, row in enumerate(
        rows,
        1
    ):

        keyword = html.escape(
            row["keyword"]
        )

        response = html.escape(
            row["response"]
        )

        if len(response) > 150:

            response = (
                response[:150]
                + "..."
            )

        lines.append(
            f"{index}. "
            f"<code>{keyword}</code>\n"
            f"   ↳ {response}"
        )

    await send_message(
        chat_id(message),
        "\n".join(lines)
    )


# ============================================================
# /STOPFILTER
# ============================================================

async def command_stopfilter(
    message,
    args
):

    if not await require_admin(
        message
    ):
        return

    keyword = normalize_filter_keyword(
        args
    )

    if not keyword:

        await send_message(
            chat_id(message),
            (
                "❗ Dùng:\n"
                "<code>/stopfilter từ khóa</code>"
            )
        )

        return

    result = await adb_execute(
        """
        DELETE FROM filters
        WHERE chat_id = ?
        AND keyword = ?
        """,
        (
            chat_id(message),
            keyword
        )
    )

    # sqlite3 rowcount không được trả về từ
    # helper hiện tại nên kiểm tra lại.
    remaining = await adb_execute(
        """
        SELECT id
        FROM filters
        WHERE chat_id = ?
        AND keyword = ?
        """,
        (
            chat_id(message),
            keyword
        ),
        fetchone=True
    )

    if remaining:

        await send_message(
            chat_id(message),
            "❌ Không thể xóa filter."
        )

        return

    await send_message(
        chat_id(message),
        (
            "🗑 <b>FILTER ĐÃ XÓA</b>\n\n"
            f"🔑 Từ khóa: "
            f"<code>{html.escape(keyword)}</code>"
        )
    )


# ============================================================
# FILTER MATCHING
# ============================================================

async def handle_filters(
    message
):

    if not is_group(
        message
    ):
        return False

    text = message_text(
        message
    ).strip()

    if not text:
        return False

    rows = await get_filters(
        chat_id(message)
    )

    if not rows:
        return False

    normalized_text = text.lower()

    for row in rows:

        keyword = (
            row["keyword"]
            or ""
        ).lower()

        if not keyword:
            continue

        # Match theo cụm từ, không cần
        # message phải bằng hoàn toàn keyword.
        if keyword in normalized_text:

            response = row[
                "response"
            ]

            await send_message(
                chat_id(message),
                response,
                reply_to=message_id(message)
            )

            RUNTIME_STATS[
                "filter_hits"
            ] += 1

            return True

    return False


# ============================================================
# REGISTER AFK + FILTER COMMANDS
# ============================================================

COMMAND_HANDLERS.update({

    "afk":
        lambda message, args:
            command_afk(
                message,
                args
            ),

    "filter":
        lambda message, args:
            command_filter(
                message,
                args
            ),

    "filters":
        lambda message, args:
            command_filters(
                message,
                args
            ),

    "stopfilter":
        lambda message, args:
            command_stopfilter(
                message,
                args
            ),
})


# ============================================================
# PATCH MESSAGE PROCESSING
# AFK + FILTER
# ============================================================

_previous_process_update_v6 = process_update


async def process_update(
    update
):

    if not isinstance(
        update,
        dict
    ):
        return

    # chat_member vẫn đi qua protection.
    if update.get(
        "chat_member"
    ):

        await process_chat_member_update(
            update
        )

        return

    message = (
        update.get("message")
        or update.get("edited_message")
    )

    if not message:
        return

    user = from_user(
        message
    )

    if user:
        await save_user(
            user
        )

    RUNTIME_STATS[
        "messages"
    ] += 1

    if is_group(
        message
    ):

        RUNTIME_STATS[
            "groups"
        ] += 1

    elif is_private(
        message
    ):

        RUNTIME_STATS[
            "private"
        ] += 1

    # Bot-ban.
    if (
        user
        and await is_bot_banned(
            user.get("id")
        )
        and not is_owner(user)
    ):

        return

    # Protection.
    blocked = await run_message_protection(
        message
    )

    if blocked:
        return

    # Nếu người đang AFK gửi message,
    # xóa trạng thái AFK trước.
    await handle_afk_return(
        message
    )

    # Nếu message reply/mention người AFK,
    # thông báo trạng thái AFK.
    await handle_afk_notification(
        message
    )

    # Filter.
    await handle_filters(
        message
    )

    # Command.
    await dispatch_command(
        message
    )


# ============================================================
# END PHẦN 7/10
# ============================================================

# ============================================================
# THEONE BOT - PURE PYTHON VERSION
# PHẦN 8/10
# THƠ + ĐIỂM DANH
# /thodoi /thotinh /diemdanh
# ============================================================


# ============================================================
# THƠ ĐỜI
# ============================================================

THO_DOI = [
    "Đời người như một chuyến xe,\nCó người đồng hành, có người xuống xe.",
    "Ngoài kia giông gió đầy trời,\nGiữ lòng bình thản, mỉm cười bước qua.",
    "Có những ngày chẳng muốn nói gì,\nChỉ mong bình yên ở lại bên mình.",
    "Đường đời chẳng phải lúc nào cũng đẹp,\nNhưng mỗi bước đi đều đáng để trưởng thành.",
    "Người đi qua để lại bài học,\nNgười ở lại cho ta một niềm tin.",
    "Có lúc tưởng chẳng còn đường,\nBước thêm một bước lại thường thấy lối ra.",
    "Thành công không đến trong một đêm,\nNó được xây bằng những ngày không bỏ cuộc.",
    "Đời có lúc lên rồi lại xuống,\nQuan trọng là mình vẫn đứng dậy đi tiếp.",
    "Đừng buồn vì chuyện đã qua,\nNgày mai vẫn có một trời bình yên.",
    "Có những thất bại rất đau,\nNhưng chính chúng dạy ta cách mạnh mẽ hơn.",
    "Chậm một chút cũng không sao,\nMiễn là đôi chân vẫn bước về phía trước.",
    "Đừng so mình với người khác,\nMỗi người có một hành trình riêng.",
    "Có tiền chưa chắc mua được bình yên,\nCó bình yên mới biết tiền chẳng phải tất cả.",
    "Người hiểu mình chẳng cần nói nhiều,\nNgười không hiểu giải thích bao nhiêu cũng thừa.",
    "Đôi khi im lặng là cách trả lời,\nKhông phải chuyện gì cũng đáng để tranh cãi.",
    "Hôm nay có thể rất mệt,\nNhưng ngày mai vẫn có thể bắt đầu lại.",
    "Đời ngắn lắm, đừng giữ mãi muộn phiền,\nHãy giữ những người khiến mình thấy bình yên.",
    "Có những cánh cửa đóng lại,\nĐể mở ra một con đường khác tốt hơn cho mình.",
    "Mạnh mẽ không phải không biết đau,\nMà là đau rồi vẫn chọn bước tiếp.",
    "Sau tất cả những ngày giông bão,\nĐiều còn lại quý nhất là một tâm hồn bình yên."
]


async def command_thodoi(
    message,
    args
):

    poem = random.choice(
        THO_DOI
    )

    await send_message(
        chat_id(message),
        (
            "📜 <b>THƠ ĐỜI</b>\n\n"
            f"{html.escape(poem)}"
        )
    )


# ============================================================
# THƠ TÌNH
# ============================================================

THO_TINH = [
    "Nếu ngày mai trời chẳng còn xanh,\nAnh vẫn mong được cạnh em bình yên.",
    "Em như một khoảng trời dịu dàng,\nĐi qua tim anh rồi chẳng muốn rời.",
    "Có những người chỉ gặp một lần,\nNhưng khiến cả đời chẳng thể quên.",
    "Anh chẳng cần một tình yêu hoàn hảo,\nChỉ cần người ở lại lúc anh yếu lòng.",
    "Nếu thương là một điều đơn giản,\nThì anh đã thương em từ rất lâu.",
    "Giữa hàng triệu người ngoài kia,\nAnh vẫn vô thức tìm một người giống em.",
    "Có em, ngày dài bỗng ngắn,\nCó em, bình thường cũng hóa dịu dàng.",
    "Anh không hứa cho em cả thế giới,\nNhưng hứa cùng em đi qua thế giới này.",
    "Tình yêu chẳng cần lời hoa mỹ,\nChỉ cần lúc khó khăn vẫn nắm tay nhau.",
    "Em đến như cơn mưa mùa hạ,\nNhẹ nhàng nhưng làm ướt cả trái tim.",
    "Nếu khoảng cách là điều duy nhất ngăn mình,\nThì nhớ thương sẽ là cây cầu nối lại.",
    "Anh thích những buổi chiều bình thường,\nMiễn là người bên cạnh vẫn là em.",
    "Có những câu yêu chưa từng nói,\nNhưng ánh mắt đã nói thay tất cả rồi.",
    "Thương một người chẳng cần lý do,\nChỉ cần nghĩ đến họ là lòng thấy vui.",
    "Anh chẳng biết ngày mai sẽ thế nào,\nChỉ biết hôm nay anh vẫn thương em.",
    "Nếu được chọn lại giữa muôn người,\nAnh vẫn muốn gặp em thêm một lần nữa.",
    "Tình yêu đẹp nhất không phải lúc bắt đầu,\nMà là khi cả hai vẫn chọn nhau sau giông bão.",
    "Em không phải điều duy nhất trên đời,\nNhưng là điều khiến đời anh trở nên đặc biệt.",
    "Có một người khiến tim anh dịu lại,\nMỗi khi mệt mỏi chỉ cần nhớ đến người.",
    "Nếu thương em là một chuyến đi dài,\nAnh nguyện đi chậm để được bên em lâu hơn."
]


async def command_thotinh(
    message,
    args
):

    poem = random.choice(
        THO_TINH
    )

    await send_message(
        chat_id(message),
        (
            "❤️ <b>THƠ TÌNH</b>\n\n"
            f"{html.escape(poem)}"
        )
    )


# ============================================================
# ĐIỂM DANH - DATE HELPER
# ============================================================

def current_date():

    # Dùng ngày UTC để database có
    # một mốc thống nhất.
    return datetime.now(
        timezone.utc
    ).date()


def previous_date(
    date_value
):

    return date_value - timedelta(
        days=1
    )


# ============================================================
# GET LATEST CHECK-IN
# ============================================================

async def get_latest_checkin(
    chat,
    user_id
):

    return await adb_execute(
        """
        SELECT
            checkin_date,
            streak
        FROM checkins
        WHERE chat_id = ?
        AND user_id = ?
        ORDER BY checkin_date DESC
        LIMIT 1
        """,
        (
            chat,
            user_id
        ),
        fetchone=True
    )


# ============================================================
# CHECK-IN BUTTON
# ============================================================

async def send_checkin_panel(
    message
):

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🔥 Điểm danh",
                    "callback_data":
                        "daily_checkin"
                }
            ]
        ]
    }

    await api(
        "sendMessage",
        {
            "chat_id":
                chat_id(message),

            "text":
                (
                    "🔥 <b>ĐIỂM DANH HẰNG NGÀY</b>\n\n"
                    "Nhấn nút bên dưới để điểm danh.\n"
                    "📅 Mỗi ngày chỉ được điểm danh một lần.\n"
                    "🔥 Điểm danh liên tiếp sẽ tăng streak."
                ),

            "parse_mode":
                "HTML",

            "reply_markup":
                json.dumps(
                    keyboard
                )
        }
    )


# ============================================================
# /DIEMDANH
# ============================================================

async def command_diemdanh(
    message,
    args
):

    if not await require_group(
        message
    ):
        return

    await send_checkin_panel(
        message
    )


# ============================================================
# CALLBACK ANSWER
# ============================================================

async def answer_callback(
    callback_id,
    text,
    show_alert=False
):

    return await api(
        "answerCallbackQuery",
        {
            "callback_query_id":
                callback_id,

            "text":
                text,

            "show_alert":
                show_alert
        }
    )


# ============================================================
# HANDLE DAILY CHECK-IN
# ============================================================

async def handle_daily_checkin(
    callback
):

    callback_id = callback.get(
        "id"
    )

    user = callback.get(
        "from",
        {}
    )

    message = callback.get(
        "message"
    )

    if not message:

        await answer_callback(
            callback_id,
            "❌ Không tìm thấy nhóm.",
            True
        )

        return

    chat = message.get(
        "chat",
        {}
    )

    if chat.get(
        "type"
    ) not in GROUP_TYPES:

        await answer_callback(
            callback_id,
            "❌ Chỉ điểm danh trong nhóm.",
            True
        )

        return

    chat_value = chat.get(
        "id"
    )

    user_id = user.get(
        "id"
    )

    if not user_id:

        await answer_callback(
            callback_id,
            "❌ Không xác định được tài khoản.",
            True
        )

        return

    today = current_date()

    today_text = today.isoformat()

    existing = await adb_execute(
        """
        SELECT
            streak
        FROM checkins
        WHERE chat_id = ?
        AND user_id = ?
        AND checkin_date = ?
        """,
        (
            chat_value,
            user_id,
            today_text
        ),
        fetchone=True
    )

    if existing:

        await answer_callback(
            callback_id,
            (
                "🔥 Bạn đã điểm danh hôm nay rồi!"
                f" Streak: {existing['streak']}"
            ),
            True
        )

        return

    latest = await get_latest_checkin(
        chat_value,
        user_id
    )

    streak = 1

    if latest:

        try:

            latest_date = datetime.strptime(
                latest["checkin_date"],
                "%Y-%m-%d"
            ).date()

            if latest_date == previous_date(
                today
            ):

                streak = (
                    int(
                        latest["streak"]
                    )
                    + 1
                )

        except Exception:

            streak = 1

    await adb_execute(
        """
        INSERT INTO checkins
        (
            chat_id,
            user_id,
            checkin_date,
            streak
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            chat_value,
            user_id,
            today_text,
            streak
        )
    )

    await answer_callback(
        callback_id,
        f"🔥 Điểm danh thành công! Streak {streak}",
        True
    )

    await send_message(
        chat_value,
        (
            "🔥 <b>ĐIỂM DANH THÀNH CÔNG</b>\n\n"
            f"👤 "
            f"{mention_user(user)}\n"
            f"📅 Ngày: "
            f"<code>{today_text}</code>\n"
            f"🔥 Streak: "
            f"<code>{streak}</code> ngày\n\n"
            "💪 Tiếp tục ngày mai nhé!"
        )
    )


# ============================================================
# CALLBACK UPDATE
# ============================================================

async def process_callback_update(
    update
):

    callback = update.get(
        "callback_query"
    )

    if not callback:
        return

    # ==========================================
    # MENU /START
    # ==========================================

    if await handle_start_menu_callback(
        callback
    ):
        return

    data = callback.get(
        "data",
        ""
    )

    # ==========================================
    # ĐIỂM DANH
    # ==========================================

    if data == "daily_checkin":

        await handle_daily_checkin(
            callback
        )

        return

    # ==========================================
    # NỐI CHỮ - THAM GIA
    # ==========================================

    if data.startswith(
        "noichu_join:"
    ):

        try:

            handled = await handle_noichu_callback(
                callback
            )

            if handled:
                return

        except Exception as e:

            logger.exception(
                "NOICHU CALLBACK ERROR: %s",
                e
            )

            await answer_callback(
                callback.get("id"),
                "❌ Lỗi khi tham gia game."
            )

            return

    # ==========================================
    # XU - ADMIN
    # ==========================================

    if data == "xu_admin":

        try:

            await xu_admin_callback(
                callback
            )

        except Exception as e:

            logger.exception(
                "XU ADMIN CALLBACK ERROR: %s",
                e
            )

            await answer_callback(
                callback.get("id"),
                "❌ Lỗi phần mềm Admin."
            )

        return

    # ==========================================
    # XU - CHIA SẺ BOT
    # ==========================================

    if data == "xu_share_done":

        try:

            await xu_share_done_callback(
                callback
            )

        except Exception as e:

            logger.exception(
                "XU SHARE CALLBACK ERROR: %s",
                e
            )

            await answer_callback(
                callback.get("id"),
                "❌ Không thể ghi nhận lượt chia sẻ."
            )

        return

    # ==========================================
    # CALLBACK KHÔNG HỢP LỆ
    # ==========================================

    await answer_callback(
        callback.get("id"),
        "❌ Nút không còn hiệu lực."
    )

# ============================================================
# REGISTER POEM + CHECK-IN
# ============================================================

COMMAND_HANDLERS.update({

    "thodoi":
        lambda message, args:
            command_thodoi(
                message,
                args
            ),

    "thotinh":
        lambda message, args:
            command_thotinh(
                message,
                args
            ),

    "diemdanh":
        lambda message, args:
            command_diemdanh(
                message,
                args
            ),
})


# ============================================================
# PATCH PROCESS UPDATE
# CALLBACK + MESSAGE
# ============================================================

_previous_process_update_v7 = process_update


async def process_update(
    update
):

    if not isinstance(
        update,
        dict
    ):
        return

    # Inline button callback.
    if update.get(
        "callback_query"
    ):

        try:

            await process_callback_update(
                update
            )

        except Exception as e:

            logger.exception(
                "Callback error: %s",
                e
            )

        return

    # Chat member.
    if update.get(
        "chat_member"
    ):

        try:

            await process_chat_member_update(
                update
            )

        except Exception as e:

            logger.exception(
                "Chat member error: %s",
                e
            )

        return

    message = (
        update.get("message")
        or update.get("edited_message")
    )

    if not message:
        return

    user = from_user(
        message
    )

    if user:

        await save_user(
            user
        )

    RUNTIME_STATS[
        "messages"
    ] += 1

    if is_group(
        message
    ):

        RUNTIME_STATS[
            "groups"
        ] += 1

    elif is_private(
        message
    ):

        RUNTIME_STATS[
            "private"
        ] += 1

    # Bot ban.
    if (
        user
        and await is_bot_banned(
            user.get("id")
        )
        and not is_owner(user)
    ):

        return

    # Protection.
    blocked = await run_message_protection(
        message
    )

    if blocked:
        return

    # AFK return.
    await handle_afk_return(
        message
    )

    # AFK notification.
    await handle_afk_notification(
        message
    )

    # Filters.
    await handle_filters(
        message
    )

    # Commands.
    await dispatch_command(
        message
    )


# ============================================================
# UPDATE GETUPDATES
# Thêm callback_query để nút điểm danh hoạt động.
# ============================================================

async def get_updates(
    offset=None,
    timeout=30
):

    data = {
        "timeout":
            timeout,

        "allowed_updates":
            json.dumps(
                [
                    "message",
                    "edited_message",
                    "chat_member",
                    "callback_query"
                ]
            )
    }

    if offset is not None:

        data["offset"] = offset

    return await api(
        "getUpdates",
        data,
        timeout=timeout + 10
    )


# ============================================================
# END PHẦN 8/10
# ============================================================

# ============================================================
# THEONE BOT - PURE PYTHON VERSION
# PHẦN 9/10
# FIX LỖI + ANTIFAKE NÂNG CAO + HOÀN THIỆN BẢO VỆ
# ============================================================


# ============================================================
# FIX PROFILE DATABASE
# Ghi nhớ profile theo từng user trong từng nhóm.
# ============================================================

async def save_known_profile(
    chat,
    user
):

    if not chat or not user:
        return

    user_id = user.get("id")

    if not user_id:
        return

    display_name = user_full_name(
        user
    )

    username = user.get(
        "username"
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    await adb_execute(
        """
        INSERT INTO known_profiles
        (
            chat_id,
            user_id,
            username,
            display_name,
            first_seen
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            username = excluded.username,
            display_name = excluded.display_name
        """,
        (
            chat,
            user_id,
            username,
            display_name,
            now
        )
    )


# ============================================================
# GET KNOWN PROFILE
# ============================================================

async def get_known_profile(
    chat,
    user_id
):

    return await adb_execute(
        """
        SELECT
            chat_id,
            user_id,
            username,
            display_name,
            first_seen
        FROM known_profiles
        WHERE chat_id = ?
        AND user_id = ?
        """,
        (
            chat,
            user_id
        ),
        fetchone=True
    )


# ============================================================
# NORMALIZE TÊN ĐỂ PHÁT HIỆN UNICODE TRICK
# ============================================================

def normalize_identity_text(
    text
):

    if not text:
        return ""

    text = str(
        text
    ).strip().lower()

    # Một số ký tự vô hình thường được
    # dùng để làm tên nhìn giống nhau.
    invisible_chars = (
        "\u200b",
        "\u200c",
        "\u200d",
        "\u2060",
        "\ufeff",
        "\u2061",
        "\u2062",
        "\u2063",
        "\u2064",
    )

    for char in invisible_chars:
        text = text.replace(
            char,
            ""
        )

    # Chuẩn hóa khoảng trắng.
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text


# ============================================================
# XÓA KÝ TỰ ĐẶC BIỆT ĐỂ SO SÁNH TÊN
# ============================================================

def identity_compact(
    text
):

    text = normalize_identity_text(
        text
    )

    return re.sub(
        r"[^a-z0-9\u00c0-\u024f\u1e00-\u9fff]+",
        "",
        text
    )


# ============================================================
# LẤY PROFILE CÁC ADMIN
# ============================================================

async def get_admin_profiles(
    chat
):

    result = await api(
        "getChatAdministrators",
        {
            "chat_id":
                chat
        }
    )

    if not result.get(
        "ok"
    ):

        return []

    return result.get(
        "result",
        []
    )


# ============================================================
# PHÁT HIỆN TÊN GIẢ MẠO ADMIN
# ============================================================

async def detect_admin_impersonation(
    message
):

    if not is_group(
        message
    ):
        return False

    user = from_user(
        message
    )

    if not user:
        return False

    user_id = user.get(
        "id"
    )

    if not user_id:
        return False

    current_name = user_full_name(
        user
    )

    current_compact = identity_compact(
        current_name
    )

    if not current_compact:
        return False

    admins = await get_admin_profiles(
        chat_id(message)
    )

    for admin in admins:

        admin_user = admin.get(
            "user",
            {}
        )

        admin_id = admin_user.get(
            "id"
        )

        if not admin_id:
            continue

        # Bỏ qua chính admin.
        if admin_id == user_id:
            continue

        admin_name = user_full_name(
            admin_user
        )

        admin_compact = identity_compact(
            admin_name
        )

        if not admin_compact:
            continue

        # Trùng hoàn toàn sau normalize.
        if current_compact == admin_compact:

            return True

        # Tên rất giống nhau nhưng có thêm
        # ký tự Unicode / khoảng trắng / ký hiệu.
        if (
            len(current_compact) >= 4
            and len(admin_compact) >= 4
        ):

            if (
                current_compact in admin_compact
                or admin_compact in current_compact
            ):

                return True

    return False


# ============================================================
# PHÁT HIỆN USERNAME GIẢ MẠO ADMIN
# ============================================================

async def detect_username_impersonation(
    message
):

    if not is_group(
        message
    ):
        return False

    user = from_user(
        message
    )

    if not user:
        return False

    username = (
        user.get("username")
        or ""
    )

    username = identity_compact(
        username
    )

    if not username:
        return False

    admins = await get_admin_profiles(
        chat_id(message)
    )

    for admin in admins:

        admin_user = admin.get(
            "user",
            {}
        )

        if admin_user.get(
            "id"
        ) == user.get(
            "id"
        ):
            continue

        admin_username = identity_compact(
            admin_user.get(
                "username",
                ""
            )
        )

        if not admin_username:
            continue

        if username == admin_username:
            return True

        # Chỉ cảnh báo trường hợp gần giống
        # khi tên đủ dài để giảm false positive.
        if (
            len(username) >= 5
            and len(admin_username) >= 5
        ):

            if (
                username in admin_username
                or admin_username in username
            ):
                return True

    return False


# ============================================================
# PROFILE CHANGE WARNING
# ============================================================

async def check_profile_change(
    message
):

    if not is_group(
        message
    ):
        return False

    user = from_user(
        message
    )

    if not user:
        return False

    old = await get_known_profile(
        chat_id(message),
        user.get("id")
    )

    # Chưa từng thấy user.
    if not old:

        await save_known_profile(
            chat_id(message),
            user
        )

        return False

    old_name = old["display_name"] or ""
    new_name = user_full_name(
        user
    )

    old_username = (
        old["username"]
        or ""
    )

    new_username = (
        user.get("username")
        or ""
    )

    changed = (
        normalize_identity_text(
            old_name
        )
        != normalize_identity_text(
            new_name
        )
        or
        normalize_identity_text(
            old_username
        )
        != normalize_identity_text(
            new_username
        )
    )

    await save_known_profile(
        chat_id(message),
        user
    )

    return changed


# ============================================================
# ANTIFAKE MESSAGE
# ============================================================

async def handle_antifake(
    message
):

    if not await get_setting(
        chat_id(message),
        "antifake",
        False
    ):
        return False

    user = from_user(
        message
    )

    if not user:
        return False

    # Owner không bị cảnh báo.
    if is_owner(
        user
    ):
        return False

    admin_name_fake = (
        await detect_admin_impersonation(
            message
        )
    )

    admin_username_fake = (
        await detect_username_impersonation(
            message
        )
    )

    profile_changed = (
        await check_profile_change(
            message
        )
    )

    suspicious = (
        admin_name_fake
        or admin_username_fake
        or profile_changed
    )

    if not suspicious:
        return False

    # Không auto-ban chỉ dựa vào profile.
    # Chỉ gửi cảnh báo cho admin.
    admins = await get_admin_profiles(
        chat_id(message)
    )

    admin_mentions = []

    for item in admins:

        admin_user = item.get(
            "user",
            {}
        )

        if admin_user.get(
            "id"
        ):

            admin_mentions.append(
                mention_user(
                    admin_user
                )
            )

    reason_parts = []

    if admin_name_fake:
        reason_parts.append(
            "tên hiển thị giống admin"
        )

    if admin_username_fake:
        reason_parts.append(
            "username giống admin"
        )

    if profile_changed:
        reason_parts.append(
            "profile đã thay đổi"
        )

    reason = ", ".join(
        reason_parts
    )

    text = (
        "⚠️ <b>CẢNH BÁO ANTIFAKE</b>\n\n"
        f"👤 Người dùng: "
        f"{mention_user(user)}\n"
        f"🔎 Dấu hiệu: "
        f"{html.escape(reason)}\n\n"
        "❗ Đây là cảnh báo tự động, "
        "không khẳng định tài khoản là giả mạo.\n"
        "👮 Admin hãy kiểm tra trước khi xử lý."
    )

    await send_message(
        chat_id(message),
        text,
        reply_to=message_id(message)
    )

    return True


# ============================================================
# ANTIBUFF - JOIN BURST
# ============================================================

async def record_join(
    chat,
    user
):

    now = time.time()

    queue = JOIN_TRACKER[
        chat
    ]

    queue.append(
        now
    )

    # Chỉ giữ 60 giây.
    while queue and (
        now - queue[0] > 60
    ):

        queue.popleft()

    return len(
        queue
    )


async def handle_antibuff(
    message
):

    if not await get_setting(
        chat_id(message),
        "antibuff",
        False
    ):
        return False

    return False


# ============================================================
# PROCESS CHAT MEMBER NÂNG CAO
# ============================================================

async def process_chat_member_update(
    update
):

    data = update.get(
        "chat_member"
    )

    if not data:
        return

    chat = data.get(
        "chat",
        {}
    )

    chat_value = chat.get(
        "id"
    )

    new_member = data.get(
        "new_chat_member",
        {}
    )

    old_member = data.get(
        "old_chat_member",
        {}
    )

    user = new_member.get(
        "user",
        {}
    )

    if not user:
        return

    old_status = old_member.get(
        "status"
    )

    new_status = new_member.get(
        "status"
    )

    was_member = old_status in {
        "member",
        "administrator",
        "creator",
        "restricted"
    }

    is_member_now = new_status in {
        "member",
        "administrator",
        "creator",
        "restricted"
    }

    # Chỉ xử lý join mới.
    if was_member or not is_member_now:
        return

    RUNTIME_STATS[
        "joins"
    ] += 1

    if not await get_setting(
        chat_value,
        "antibuff",
        False
    ):
        return

    count = await record_join(
        chat_value,
        user
    )

    # Ngưỡng join nhanh.
    if count < 8:
        return

    # Cảnh báo admin.
    admins = await get_admin_profiles(
        chat_value
    )

    admin_mentions = []

    for item in admins:

        admin_user = item.get(
            "user",
            {}
        )

        if admin_user.get(
            "id"
        ):

            admin_mentions.append(
                mention_user(
                    admin_user
                )
            )

    await send_message(
        chat_value,
        (
            "🚨 <b>ANTIBUFF CẢNH BÁO</b>\n\n"
            f"👥 Có ít nhất "
            f"<code>{count}</code> tài khoản "
            "vừa tham gia trong khoảng 60 giây.\n\n"
            "⚠️ Đây có thể là dấu hiệu "
            "tăng thành viên bất thường.\n"
            "❗ Bot không khẳng định tất cả "
            "tài khoản đều là fake.\n\n"
            "👮 Admin nên kiểm tra danh sách thành viên."
        )
    )


# ============================================================
# URL + SPAM PROTECTION PATCH
# ============================================================

async def run_message_protection(
    message
):

    if not is_group(
        message
    ):
        return False

    user = from_user(
        message
    )

    if not user:
        return False

    # Owner bỏ qua protection.
    if is_owner(
        user
    ):
        return False

    chat = chat_id(
        message
    )

    # -----------------------------
    # ANTISPAM
    # -----------------------------

    if await get_setting(
        chat,
        "antispam",
        False
    ):

        now = time.time()

        key = (
            chat,
            user.get("id")
        )

        queue = SPAM_TRACKER[
            key
        ]

        queue.append(
            now
        )

        while queue and (
            now - queue[0] > 8
        ):

            queue.popleft()

        if len(queue) >= 6:

            try:

                await delete_message(
                    chat,
                    message_id(message)
                )

                RUNTIME_STATS[
                    "deleted"
                ] += 1

                return True

            except Exception:
                pass

    # -----------------------------
    # ANTILINK
    # -----------------------------

    if await get_setting(
        chat,
        "antilink",
        False
    ):

        text = get_text(
            message
        )

        if contains_link(
            text
        ):

            # Admin được phép gửi link.
            if not await is_admin(
                message
            ):

                try:

                    await delete_message(
                        chat,
                        message_id(message)
                    )

                    RUNTIME_STATS[
                        "deleted"
                    ] += 1

                    return True

                except Exception:
                    pass

    # -----------------------------
    # ANTIFAKE
    # -----------------------------

    if await handle_antifake(
        message
    ):

        # Antifake chỉ cảnh báo,
        # không chặn message.
        pass

    # -----------------------------
    # ANTIBUFF
    # -----------------------------

    await handle_antibuff(
        message
    )

    return False


# ============================================================
# FIX FILTER RESPONSE
# Không cho response của user phá HTML parser.
# ============================================================

async def handle_filters(
    message
):

    if not is_group(
        message
    ):
        return False

    text = get_text(
        message
    ).strip()

    if not text:
        return False

    rows = await get_filters(
        chat_id(message)
    )

    if not rows:
        return False

    normalized_text = text.lower()

    for row in rows:

        keyword = (
            row["keyword"]
            or ""
        ).lower()

        if not keyword:
            continue

        if keyword in normalized_text:

            response = row[
                "response"
            ]

            # Plain text để filter có thể
            # chứa ký tự HTML mà không lỗi.
            result = await api(
                "sendMessage",
                {
                    "chat_id":
                        chat_id(message),

                    "text":
                        str(response),

                    "reply_to_message_id":
                        message_id(message)
                }
            )

            if result.get(
                "ok"
            ):

                RUNTIME_STATS[
                    "filter_hits"
                ] += 1

            return True

    return False


# ============================================================
# FIX MENTION PARSER
# ============================================================

def mentioned_user_ids(
    message
):

    result = []

    text = message.get(
        "text",
        ""
    )

    entities = (
        message.get(
            "entities"
        )
        or []
    )

    for entity in entities:

        entity_type = entity.get(
            "type"
        )

        if entity_type == "text_mention":

            mentioned = entity.get(
                "user"
            )

            if mentioned:

                user_id = mentioned.get(
                    "id"
                )

                if user_id:

                    result.append(
                        user_id
                    )

        elif entity_type == "mention":

            # Telegram chỉ cung cấp username
            # cho entity mention. Không thể dùng
            # getChatMember trực tiếp với username.
            # Username sẽ được tìm trong DB cache.
            offset = entity.get(
                "offset",
                0
            )

            length = entity.get(
                "length",
                0
            )

            username = text[
                offset:
                offset + length
            ]

            username = username.lstrip(
                "@"
            ).lower()

            if username:

                row = awaitable_placeholder = None

    return result


# ============================================================
# CACHE USER PROFILE TỪ MESSAGE
# ============================================================

async def cache_message_profile(
    message
):

    if not is_group(
        message
    ):
        return

    user = from_user(
        message
    )

    if not user:
        return

    await save_known_profile(
        chat_id(message),
        user
    )

# ============================================================
# FIX DISPATCH COMMAND - HỖ TRỢ CẢ 2 KIỂU HANDLER
# ============================================================

async def dispatch_command(message):

    command, args = parse_command(message)

    if not command:
        return

    handler = COMMAND_HANDLERS.get(command)

    if not handler:
        return

    try:
        # Các handler mới:
        # handler(message, args)
        result = handler(message, args)

        if asyncio.iscoroutine(result):
            await result

    except Exception as e:

        logger.exception(
            "Command /%s failed: %s",
            command,
            e
        )

        await send_message(
            chat_id(message),
            (
                "❌ <b>LỖI KHI XỬ LÝ LỆNH</b>\n\n"
                "Bot gặp lỗi nội bộ khi thực hiện lệnh.\n"
                f"<code>{html.escape(str(e))}</code>"
            ),
            parse_mode="HTML"
        )

# ============================================================
# FINAL PROFILE CACHE PATCH
# ============================================================

_previous_process_update_v8 = process_update


async def process_update(
    update
):

    if not isinstance(
        update,
        dict
    ):
        return

    if update.get(
        "callback_query"
    ):

        try:

            await process_callback_update(
                update
            )

        except Exception as e:

            logger.exception(
                "Callback error: %s",
                e
            )

        return

    if update.get(
        "chat_member"
    ):

        try:

            await process_chat_member_update(
                update
            )

        except Exception as e:

            logger.exception(
                "Chat member error: %s",
                e
            )

        return

    message = (
        update.get("message")
        or update.get("edited_message")
    )

    if not message:
        return

    user = from_user(
        message
    )

    if user:

        await save_user(
            user
        )

    if is_group(
        message
    ):

        await cache_message_profile(
            message
        )

    # ==========================================
    # XU - ĐẾM TIN NHẮN NHIỆM VỤ
    # ==========================================

    try:

        await xu_count_message_task(
            message
        )

    except Exception as e:

        logger.exception(
            "XU MESSAGE TASK ERROR: %s",
            e
        )

    # ==========================================
    # XU - ĐẾM THÀNH VIÊN MỚI
    # ==========================================

    try:

        await xu_count_new_member_task(
            message
        )

    except Exception as e:

        logger.exception(
            "XU MEMBER TASK ERROR: %s",
            e
        )

    # ==========================================
    # NỐI CHỮ
    # ==========================================

    try:

        noichu_handled = await noichu_handle_text(
            message
        )

        if noichu_handled:
            return

    except Exception as e:

        logger.exception(
            "NOICHU MESSAGE ERROR: %s",
            e
        )

# ============================================================
# LEVEL - TỰ ĐỘNG ĐẾM TIN NHẮN
# ============================================================

    if (
            is_group(message)
            and user
            and not user.get("is_bot", False)
        ):

        try:

            level_count, old_level, new_level = add_level_message(
                chat_id(message),
                user.get("id"),
                user.get("username"),
                user.get("first_name", "Người dùng")
            )

            # Chỉ thông báo khi vừa lên level
            if new_level > old_level:

                username = user.get("username")

                if username:
                    mention = f"@{username}"
                else:
                    mention = (
                        f'<a href="tg://user?id={user.get("id")}">'
                        f'{html.escape(user.get("first_name", "Người dùng"))}'
                        f'</a>'
                    )

                if new_level < 10:

                    await send_message(
                        chat_id(message),
                        (
                            f"🎉 Chúc Mừng {mention} đã lên level {new_level}\n"
                            f"để lên level tiếp theo vui lòng rõ lệnh /levelnhiemvu"
                        ),
                        parse_mode="HTML"
                    )

                else:

                    await send_message(
                        chat_id(message),
                        (
                            f"🏆 Chúc Mừng {mention} đã đạt LEVEL 10!\n"
                            f"🔥 Bạn đã đạt cấp độ tối đa."
                        ),
                        parse_mode="HTML"
                    )

        except Exception as e:

            logger.exception(
                "LEVEL MESSAGE ERROR: %s",
                e
            )

    RUNTIME_STATS[
        "messages"
    ] += 1

    if is_group(
        message
    ):

        RUNTIME_STATS[
            "groups"
        ] += 1

    elif is_private(
        message
    ):

        RUNTIME_STATS[
            "private"
        ] += 1

    if (
        user
        and await is_bot_banned(
            user.get("id")
        )
        and not is_owner(user)
    ):

        return

    blocked = await run_message_protection(
        message
    )

    if blocked:
        return

    await handle_afk_return(
        message
    )

    await handle_afk_notification(
        message
    )

    await handle_filters(
        message
    )

    await dispatch_command(
        message
    )


# ============================================================
# END PHẦN 9/10
# ============================================================

# ============================================================
# THEONE BOT - PURE PYTHON VERSION
# PHẦN 10/10
# MAIN LOOP + KHỞI ĐỘNG BOT
# ============================================================


# ============================================================
# KIỂM TRA BOT TOKEN
# ============================================================

def validate_token():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN đang trống."
        )

    if BOT_TOKEN == (
        "DÁN_TOKEN_BOT_CỦA_BẠN_VÀO_ĐÂY"
    ):
        raise RuntimeError(
            "Bạn chưa thay BOT_TOKEN "
            "trong bot.py."
        )


# ============================================================
# XÓA WEBHOOK
# ============================================================

async def delete_webhook():

    result = await api(
        "deleteWebhook",
        {
            "drop_pending_updates":
                True
        }
    )

    if result.get(
        "ok"
    ):

        logger.info(
            "Webhook removed."
        )

    else:

        logger.warning(
            "Không thể xóa webhook: %s",
            result.get(
                "description",
                "unknown"
            )
        )


# ============================================================
# BOT COMMANDS MENU
# ============================================================

async def set_bot_commands():

    commands = [

        {
            "command": "start",
            "description": "Khởi động bot"
        },

        {
            "command": "help",
            "description": "Xem danh sách lệnh"
        },

        {
            "command": "id",
            "description": "Xem ID"
        },

        {
            "command": "info",
            "description": "Thông tin người dùng"
        },

        {
            "command": "ping",
            "description": "Kiểm tra bot"
        },

        {
            "command": "time",
            "description": "Xem thời gian"
        },

        {
            "command": "stats",
            "description": "Thống kê bot"
        },

        {
            "command": "settings",
            "description": "Cài đặt nhóm"
        },

        {
            "command": "echo",
            "description": "Lặp lại nội dung"
        },

        {
            "command": "calc",
            "description": "Tính toán"
        },

        {
            "command": "search",
            "description": "Tìm kiếm"
        },

        {
            "command": "weather",
            "description": "Xem thời tiết"
        },

        {
            "command": "short",
            "description": "Rút gọn link"
        },

        {
            "command": "warn",
            "description": "Cảnh cáo"
        },

        {
            "command": "warns",
            "description": "Xem cảnh cáo"
        },

        {
            "command": "mute",
            "description": "Khóa chat"
        },

        {
            "command": "unmute",
            "description": "Mở khóa chat"
        },

        {
            "command": "kick",
            "description": "Kick thành viên"
        },

        {
            "command": "ban",
            "description": "Ban thành viên"
        },

        {
            "command": "unban",
            "description": "Gỡ ban"
        },

        {
            "command": "purge",
            "description": "Xóa nhiều tin nhắn"
        },

        {
            "command": "pin",
            "description": "Ghim tin nhắn"
        },

        {
            "command": "unpin",
            "description": "Bỏ ghim"
        },

        {
            "command": "lock",
            "description": "Khóa nhóm"
        },

        {
            "command": "unlock",
            "description": "Mở khóa nhóm"
        },

        {
            "command": "admins",
            "description": "Danh sách admin"
        },

        {
            "command": "broadcast",
            "description": "Broadcast"
        },

        {
            "command": "users",
            "description": "Danh sách user"
        },

        {
            "command": "banuser",
            "description": "Ban user khỏi bot"
        },

        {
            "command": "unbanuser",
            "description": "Gỡ ban user"
        },

        {
            "command": "restart",
            "description": "Restart bot"
        },

        {
            "command": "logs",
            "description": "Xem logs"
        },

        {
            "command": "database",
            "description": "Thông tin database"
        },

        {
            "command": "health",
            "description": "Kiểm tra hệ thống"
        },

        {
            "command": "version",
            "description": "Xem phiên bản"
        },

        {
            "command": "antispam",
            "description": "Bật/tắt chống spam"
        },

        {
            "command": "antilink",
            "description": "Bật/tắt chống link"
        },

        {
            "command": "antibuff",
            "description": "Bật/tắt chống buff"
        },

        {
            "command": "antifake",
            "description": "Bật/tắt chống giả mạo"
        },

        {
            "command": "afk",
            "description": "Bật trạng thái AFK"
        },

        {
            "command": "filter",
            "description": "Tạo filter"
        },

        {
            "command": "filters",
            "description": "Danh sách filter"
        },

        {
            "command": "stopfilter",
            "description": "Xóa filter"
        },

        {
            "command": "thodoi",
            "description": "Thơ đời"
        },

        {
            "command": "thotinh",
            "description": "Thơ tình"
        },

        {
            "command": "diemdanh",
            "description": "Điểm danh"
        },

        {
            "command": "xume",
            "description": "Xem Xu"
        },

        {
            "command": "xudamat",
            "description": "Xem Xu đã mất"
        },

        {
            "command": "nhapcode",
            "description": "Nhập code tân thủ"
        },

        {
            "command": "nhiemvutong",
            "description": "Xem tổng nhiệm vụ Xu"
        },

        {
            "command": "nhiemvuthuong",
            "description": "Nhận nhiệm vụ thường"
        },

        {
            "command": "nhiemvucao",
            "description": "Nhận nhiệm vụ cao"
        },

        {
            "command": "chiasebot",
            "description": "Chia sẻ bot nhận Xu"
        },

        {
            "command": "taixiu",
            "description": "Chơi Tài Xỉu"
        },

        {
            "command": "xuadmin",
            "description": "Phần mềm Admin Xu"
        }
        ]

    result = await api(
        "setMyCommands",
        {
            "commands":
                json.dumps(
                    commands,
                    ensure_ascii=False
                )
        }
    )

    if result.get(
        "ok"
    ):

        logger.info(
            "Telegram command menu updated."
        )

    else:

        logger.warning(
            "setMyCommands failed: %s",
            result.get(
                "description",
                "unknown"
            )
        )


# ============================================================
# GET BOT INFO
# ============================================================

async def get_bot_info():

    result = await api(
        "getMe"
    )

    if not result.get(
        "ok"
    ):

        raise RuntimeError(
            "Không thể kết nối Telegram Bot API."
        )

    bot = result.get(
        "result",
        {}
    )

    logger.info(
        "Bot username: @%s",
        bot.get(
            "username",
            "unknown"
        )
    )

    logger.info(
        "Bot ID: %s",
        bot.get(
            "id",
            "unknown"
        )
    )

    return bot


# ============================================================
# XỬ LÝ UPDATE AN TOÀN
# ============================================================

async def safe_process_update(
    update
):

    try:

        await process_update(
            update
        )

    except Exception as e:

        logger.exception(
            "Unhandled update error: %s",
            e
        )


# ============================================================
# POLLING LOOP
# ============================================================

async def polling_loop():

    global LAST_UPDATE_ID
    global BOT_RUNNING

    logger.info(
        "Starting long polling..."
    )

    error_delay = 1

    while BOT_RUNNING:

        try:

            offset = None

            if LAST_UPDATE_ID:
                offset = (
                    LAST_UPDATE_ID
                    + 1
                )

            result = await get_updates(
                offset=offset,
                timeout=30
            )

            if not result.get(
                "ok"
            ):

                logger.warning(
                    "getUpdates failed: %s",
                    result.get(
                        "description",
                        "unknown"
                    )
                )

                await asyncio.sleep(
                    error_delay
                )

                error_delay = min(
                    error_delay * 2,
                    30
                )

                continue

            error_delay = 1

            updates = result.get(
                "result",
                []
            )

            if not updates:
                continue

            for update in updates:

                update_id = update.get(
                    "update_id"
                )

                if (
                    update_id is not None
                    and update_id > LAST_UPDATE_ID
                ):

                    LAST_UPDATE_ID = (
                        update_id
                    )

                await safe_process_update(
                    update
                )

        except KeyboardInterrupt:

            BOT_RUNNING = False

            logger.info(
                "KeyboardInterrupt."
            )

            break

        except Exception as e:

            logger.exception(
                "Polling error: %s",
                e
            )

            await asyncio.sleep(
                error_delay
            )

            error_delay = min(
                error_delay * 2,
                30
            )


# ============================================================
# SHUTDOWN
# ============================================================

async def shutdown():

    global BOT_RUNNING

    BOT_RUNNING = False

    logger.info(
        "THEONE BOT shutting down..."
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    validate_token()

    logger.info(
        "=========================================="
    )

    logger.info(
        "THEONE BOT v%s",
        VERSION
    )

    logger.info(
        "Pure Python Telegram Bot API"
    )

    logger.info(
        "Python: %s",
        sys.version.split()[0]
    )

    logger.info(
        "=========================================="
    )

    # Database.
    init_db()

    # Xóa webhook để polling hoạt động.
    await delete_webhook()

    # Kiểm tra token.
    await get_bot_info()

    # Cập nhật menu lệnh Telegram.
    await set_bot_commands()

    # Chạy bot.
    await polling_loop()

    await shutdown()


# ============================================================
# ENTRY POINT
# ============================================================

# ============================================================
# KHỐI 1 - HỆ THỐNG XU / TÀI XỈU
# ============================================================

def init_xu_database():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    # Tài khoản xu
    cur.execute("""
        CREATE TABLE IF NOT EXISTS xu_accounts (
            user_id INTEGER PRIMARY KEY,
            xu REAL NOT NULL DEFAULT 0,
            xu_da_mat REAL NOT NULL DEFAULT 0,
            khoinghieptanthu INTEGER NOT NULL DEFAULT 0,
            admin_mode INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Nhiệm vụ
    cur.execute("""
        CREATE TABLE IF NOT EXISTS xu_tasks (
            user_id INTEGER PRIMARY KEY,
            messages_count INTEGER NOT NULL DEFAULT 0,
            people_added INTEGER NOT NULL DEFAULT 0,
            bot_shared INTEGER NOT NULL DEFAULT 0,
            easy_message_done INTEGER NOT NULL DEFAULT 0,
            easy_add_done INTEGER NOT NULL DEFAULT 0,
            easy_share_done INTEGER NOT NULL DEFAULT 0,
            hard_message_done INTEGER NOT NULL DEFAULT 0,
            hard_add_done INTEGER NOT NULL DEFAULT 0,
            hard_share_done INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Các cột mới cho hệ thống nhận nhiệm vụ
    columns = {
        row[1]
        for row in cur.execute(
            "PRAGMA table_info(xu_tasks)"
        ).fetchall()
    }

    if "active_task" not in columns:
        cur.execute(
            "ALTER TABLE xu_tasks "
            "ADD COLUMN active_task TEXT NOT NULL DEFAULT ''"
        )

    if "active_chat_id" not in columns:
        cur.execute(
            "ALTER TABLE xu_tasks "
            "ADD COLUMN active_chat_id INTEGER NOT NULL DEFAULT 0"
        )

    conn.commit()
    conn.close()


def get_xu_account(user_id):
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id, xu, xu_da_mat, khoinghieptanthu, admin_mode "
        "FROM xu_accounts WHERE user_id = ?",
        (int(user_id),)
    )

    row = cur.fetchone()

    if not row:
        cur.execute(
            """
            INSERT INTO xu_accounts
            (user_id, xu, xu_da_mat, khoinghieptanthu, admin_mode)
            VALUES (?, 0, 0, 0, 0)
            """,
            (int(user_id),)
        )
        conn.commit()

        row = (
            int(user_id),
            0,
            0,
            0,
            0
        )

    conn.close()
    return row


def get_xu(user_id):
    account = get_xu_account(user_id)

    # admin mode = xu vô hạn
    if account[4] == 1:
        return float("inf")

    return float(account[1])


def add_xu(user_id, amount):
    if amount <= 0:
        return

    account = get_xu_account(user_id)

    # Admin không cần cộng xu
    if account[4] == 1:
        return

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE xu_accounts
        SET xu = xu + ?
        WHERE user_id = ?
        """,
        (float(amount), int(user_id))
    )

    conn.commit()
    conn.close()


def remove_xu(user_id, amount):
    if amount <= 0:
        return False

    account = get_xu_account(user_id)

    # Admin vô hạn xu
    if account[4] == 1:
        return True

    current_xu = float(account[1])

    if current_xu < float(amount):
        return False

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE xu_accounts
        SET xu = xu - ?,
            xu_da_mat = xu_da_mat + ?
        WHERE user_id = ?
        """,
        (
            float(amount),
            float(amount),
            int(user_id)
        )
    )

    conn.commit()
    conn.close()

    return True


def add_xu_task_user(user_id):
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute(
        "SELECT user_id FROM xu_tasks WHERE user_id = ?",
        (int(user_id),)
    )

    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO xu_tasks
            (user_id)
            VALUES (?)
            """,
            (int(user_id),)
        )

    conn.commit()
    conn.close()


# Khởi tạo database Xu ngay khi nạp module
try:
    init_xu_database()
except Exception as e:
    print("Lỗi khởi tạo database Xu:", e)

# ============================================================
# KHỐI 2 - /xume
# ============================================================

async def command_xume(message, args=None):
    user = from_user(message)

    if not user:
        return

    user_id = int(user.get("id", 0))
    username = user.get("username") or ""
    first_name = user.get("first_name") or "Không tên"

    account = get_xu_account(user_id)

    xu = account[1]
    xu_da_mat = account[2]
    khoi_nghiep = account[3]
    admin_mode = account[4]

    # ========================================================
    # TRONG NHÓM
    # Chỉ hiện số Xu, không hiện thông tin cá nhân
    # ========================================================
    if is_group(message):

        if admin_mode == 1:
            xu_text = "∞"
        else:
            xu_text = f"{float(xu):.2f}"

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "🛠️ Phần mềm Admin",
                        "callback_data": "xu_admin"
                    }
                ]
            ]
        }

        await send_message(
            chat_id(message),
            f"💰 Xu hiện tại: {xu_text}",
            reply_markup=keyboard
        )

        # Gửi thông tin cá nhân riêng tư
        private_text = (
            "💰 THÔNG TIN XU CÁ NHÂN\n\n"
            f"👤 Tên: {html.escape(first_name)}\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"👤 Username: @{html.escape(username) if username else 'Không có'}\n\n"
            f"💰 Xu hiện tại: "
            f"{'∞' if admin_mode == 1 else f'{float(xu):.2f}'}\n"
            f"📉 Xu đã mất: {float(xu_da_mat):.2f}\n"
            f"🔰 Code tân thủ: "
            f"{'Đã sử dụng' if khoi_nghiep else 'Chưa sử dụng'}\n\n"
            "🔐 Code tân thủ:\n"
            "<code>khoinghieptanthu</code>\n\n"
            "Dùng /nhapcode khoinghieptanthu để nhận 100 Xu."
        )

        try:
            await send_message(
                user_id,
                private_text
            )
        except Exception:
            pass

        return

    # ========================================================
    # TRONG CHAT RIÊNG
    # Hiện đầy đủ thông tin cá nhân
    # ========================================================

    if admin_mode == 1:
        xu_text = "∞"
    else:
        xu_text = f"{float(xu):.2f}"

    text = (
        "💰 THÔNG TIN XU CỦA BẠN\n\n"
        f"👤 Tên: {html.escape(first_name)}\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Username: @{html.escape(username) if username else 'Không có'}\n\n"
        f"💰 Xu hiện tại: {xu_text}\n"
        f"📉 Xu đã mất: {float(xu_da_mat):.2f}\n"
        f"🔰 Code tân thủ: "
        f"{'Đã sử dụng' if khoi_nghiep else 'Chưa sử dụng'}\n\n"
        "🔐 CODE TÂN THỦ\n"
        "<code>khoinghieptanthu</code>\n\n"
        "🎁 Dùng:\n"
        "<code>/nhapcode khoinghieptanthu</code>\n"
        "để nhận 100 Xu."
    )

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🛠️ Phần mềm Admin",
                    "callback_data": "xu_admin"
                }
            ]
        ]
    }

    await send_message(
        chat_id(message),
        text,
        reply_markup=keyboard
    )


# Đăng ký lệnh
COMMAND_HANDLERS["xume"] = command_xume

# ============================================================
# KHỐI 3 - CODE TÂN THỦ
# /nhapcode khoinghieptanthu
# ============================================================

async def command_nhapcode(message, args=None):
    user = from_user(message)

    if not user:
        return

    user_id = int(user.get("id", 0))

    # Kiểm tra đã nhập code chưa
    account = get_xu_account(user_id)

    if account[3] == 1:
        await send_message(
            chat_id(message),
            "❌ Bạn đã sử dụng code tân thủ trước đó rồi."
        )
        return

    # Lấy code
    code = ""

    if args:
        if isinstance(args, list):
            code = " ".join(str(x) for x in args).strip()
        else:
            code = str(args).strip()

    code = code.lower()

    # Sai code
    if code != "khoinghieptanthu":
        await send_message(
            chat_id(message),
            "❌ Code không hợp lệ."
        )
        return

    account = get_xu_account(user_id)

    if account and int(account[3]) == 1:
        await send_message(
            chat_id(message),
            "❌ Code tân thủ này đã được sử dụng trước đó."
        )
        return

    # Cộng 100 Xu và đánh dấu đã dùng
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE xu_accounts
        SET xu = xu + 100,
            khoinghieptanthu = 1
        WHERE user_id = ?
        """,
        (user_id,)
    )

    conn.commit()
    conn.close()

    await send_message(
        chat_id(message),
        "🎉 KÍCH HOẠT CODE THÀNH CÔNG!\n\n"
        "🔰 Code tân thủ: khoinghieptanthu\n"
        "💰 Bạn nhận được: +100 Xu\n\n"
        "💰 Dùng /xume để xem số Xu hiện tại."
    )


COMMAND_HANDLERS["nhapcode"] = command_nhapcode

# ============================================================
# KHỐI 4 - /xudamat
# Xem tổng số Xu đã mất
# Dùng được cả nhóm và chat riêng
# ============================================================

async def command_xudamat(message, args=None):
    user = from_user(message)

    if not user:
        return

    user_id = int(user.get("id", 0))
    account = get_xu_account(user_id)

    xu_da_mat = float(account[2])
    admin_mode = account[4]

    if admin_mode == 1:
        xu_text = "∞"
    else:
        xu_text = f"{xu_da_mat:.2f}"

    await send_message(
        chat_id(message),
        "📉 THỐNG KÊ XU ĐÃ MẤT\n\n"
        f"💸 Tổng Xu đã mất: {xu_text}\n\n"
        "💡 Xu bị trừ khi bạn thua Tài Xỉu "
        "hoặc sử dụng những chức năng yêu cầu Xu."
    )


COMMAND_HANDLERS["xudamat"] = command_xudamat

# ============================================================
# KHỐI 5 - /nhiemvu
# HỆ THỐNG NHIỆM VỤ XU
# Dùng được trong nhóm + chat riêng
# ============================================================

async def command_nhiemvutong(message, args=None):
    if not is_group(message):
        await send_message(
            chat_id(message),
            PRIVATE_GROUP_MESSAGE
        )
        return

    await send_message(
        chat_id(message),
        "🎯 <b>NHIỆM VỤ TỔNG XU</b>\n\n"

        "🟢 <b>NHIỆM VỤ THƯỜNG</b> — +20 Xu\n"
        "Dùng: <code>/nhiemvuthuong</code>\n"
        "→ Mời 1 người vào nhóm.\n\n"

        "🔴 <b>NHIỆM VỤ CAO</b> — +100 Xu\n"
        "Dùng: <code>/nhiemvucao</code>\n"
        "→ Mời 5 người vào nhóm.\n\n"

        "⚠️ Người vào nhóm khi bạn <b>chưa nhận nhiệm vụ</b> "
        "sẽ không được tính."
    )


async def _claim_xu_task(
    message,
    task_type,
    reward,
    target,
    title
):
    if not is_group(message):
        await send_message(
            chat_id(message),
            PRIVATE_GROUP_MESSAGE
        )
        return

    user = from_user(message) or {}

    user_id = int(
        user.get("id", 0)
    )

    group_id = int(
        chat_id(message)
    )

    add_xu_task_user(
        user_id
    )

    conn = sqlite3.connect(
        DATABASE
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            active_task,
            active_chat_id,
            easy_add_done,
            hard_add_done
        FROM xu_tasks
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cur.fetchone()

    if not row:
        conn.close()
        return

    (
        active_task,
        active_chat_id,
        easy_done,
        hard_done
    ) = row

    # Đang có nhiệm vụ khác
    if active_task:
        conn.close()

        await send_message(
            group_id,
            "⚠️ Bạn đang có một nhiệm vụ đang thực hiện.\n"
            "Hãy hoàn thành nhiệm vụ hiện tại trước."
        )

        return

    # Đã hoàn thành nhiệm vụ thường
    if (
        task_type == "easy_add"
        and int(easy_done) == 1
    ):
        conn.close()

        await send_message(
            group_id,
            "✅ Bạn đã hoàn thành nhiệm vụ thường trước đó rồi."
        )

        return

    # Đã hoàn thành nhiệm vụ cao
    if (
        task_type == "hard_add"
        and int(hard_done) == 1
    ):
        conn.close()

        await send_message(
            group_id,
            "✅ Bạn đã hoàn thành nhiệm vụ cao trước đó rồi."
        )

        return

    # Bắt đầu nhiệm vụ từ đầu
    cur.execute(
        """
        UPDATE xu_tasks
        SET
            active_task = ?,
            active_chat_id = ?,
            people_added = 0,
            messages_count = 0
        WHERE user_id = ?
        """,
        (
            task_type,
            group_id,
            user_id
        )
    )

    conn.commit()
    conn.close()

    await send_message(
        group_id,
        f"🎯 <b>{title}</b>\n\n"
        f"👥 Hãy mời <b>{target} người</b> vào nhóm này.\n"
        f"💰 Hoàn thành nhận: <b>+{reward} Xu</b>\n\n"
        "⚠️ Bot chỉ ghi nhận người mới "
        "<b>sau khi bạn nhận nhiệm vụ</b>."
    )


async def command_nhiemvuthuong(
    message,
    args=None
):
    await _claim_xu_task(
        message,
        "easy_add",
        20,
        1,
        "NHIỆM VỤ THƯỜNG"
    )


async def command_nhiemvucao(
    message,
    args=None
):
    await _claim_xu_task(
        message,
        "hard_add",
        100,
        5,
        "NHIỆM VỤ CAO"
    )


COMMAND_HANDLERS[
    "nhiemvutong"
] = command_nhiemvutong

COMMAND_HANDLERS[
    "nhiemvuthuong"
] = command_nhiemvuthuong

COMMAND_HANDLERS[
    "nhiemvucao"
] = command_nhiemvucao

# ============================================================
# KHỐI 6 - TỰ ĐỘNG ĐẾM TIN NHẮN
# 50 tin nhắn = +100 Xu
# ============================================================

async def xu_count_message_task(message):
    # Không tự động tính tin nhắn.
    # Chỉ nhiệm vụ đã nhận mới được phép ghi nhận.
    return

    user = from_user(message)

    if not user:
        return

    user_id = int(user.get("id", 0))

    # Bỏ qua bot
    if user.get("is_bot"):
        return

    add_xu_task_user(user_id)

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    # Tăng số tin nhắn
    cur.execute(
        """
        UPDATE xu_tasks
        SET messages_count = messages_count + 1
        WHERE user_id = ?
        """,
        (user_id,)
    )

    # Lấy thông tin mới
    cur.execute(
        """
        SELECT messages_count, hard_message_done
        FROM xu_tasks
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cur.fetchone()

    conn.commit()
    conn.close()

    if not row:
        return

    messages_count = int(row[0])
    hard_message_done = int(row[1])

    # Đủ 50 tin nhắn
    if messages_count >= 50 and hard_message_done == 0:

        add_xu(user_id, 100)

        conn = sqlite3.connect(DATABASE)
        cur = conn.cursor()

        cur.execute(
            """
            UPDATE xu_tasks
            SET hard_message_done = 1
            WHERE user_id = ?
            """,
            (user_id,)
        )

        conn.commit()
        conn.close()

        await send_message(
            chat_id(message),
            "🎉 NHIỆM VỤ HOÀN THÀNH!\n\n"
            "💬 Bạn đã gửi đủ 50 tin nhắn.\n"
            "💰 Phần thưởng: +100 Xu\n\n"
            "💰 Dùng /xume để xem Xu."
        )

# ============================================================
# KHỐI 7 - NHIỆM VỤ THÊM THÀNH VIÊN
# 1 người = +20 Xu
# 5 người = +100 Xu
# ============================================================

async def xu_count_new_member_task(message):
    if not is_group(message):
        return

    user = from_user(message) or {}

    if not user:
        return

    if user.get("is_bot"):
        return

    user_id = int(
        user.get("id", 0)
    )

    group_id = int(
        chat_id(message)
    )

    new_members = message.get(
        "new_chat_members"
    )

    if not new_members:
        return

    # Không tính bot và không tính trường hợp
    # người dùng tự vào nhóm.
    real_members = [
        member
        for member in new_members
        if not member.get("is_bot", False)
        and int(member.get("id", 0)) != user_id
    ]

    if not real_members:
        return

    add_xu_task_user(
        user_id
    )

    conn = sqlite3.connect(
        DATABASE
    )

    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            active_task,
            active_chat_id,
            easy_add_done,
            hard_add_done,
            people_added
        FROM xu_tasks
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cur.fetchone()

    if not row:
        conn.close()
        return

    (
        active_task,
        active_chat_id,
        easy_done,
        hard_done,
        people_added
    ) = row

    # Không nhận nhiệm vụ -> im lặng hoàn toàn
    if not active_task:
        conn.close()
        return

    # Nhận nhiệm vụ ở nhóm khác -> không tính
    if int(active_chat_id) != group_id:
        conn.close()
        return

    # ==========================================
    # NHIỆM VỤ THƯỜNG
    # ==========================================

    if active_task == "easy_add":

        if int(easy_done) == 1:
            conn.close()
            return

        cur.execute(
            """
            UPDATE xu_tasks
            SET
                easy_add_done = 1,
                active_task = '',
                active_chat_id = 0
            WHERE user_id = ?
            """,
            (user_id,)
        )

        conn.commit()
        conn.close()

        add_xu(
            user_id,
            20
        )

        await send_message(
            group_id,
            "🎉 <b>NHIỆM VỤ THƯỜNG HOÀN THÀNH!</b>\n\n"
            "👥 Bạn đã mời thành công 1 người vào nhóm.\n"
            "💰 Phần thưởng: <b>+20 Xu</b>"
        )

        return

    # ==========================================
    # NHIỆM VỤ CAO
    # ==========================================

    if active_task == "hard_add":

        progress = (
            int(people_added)
            + len(real_members)
        )

        if progress >= 5:

            cur.execute(
                """
                UPDATE xu_tasks
                SET
                    people_added = ?,
                    hard_add_done = 1,
                    active_task = '',
                    active_chat_id = 0
                WHERE user_id = ?
                """,
                (
                    progress,
                    user_id
                )
            )

            conn.commit()
            conn.close()

            add_xu(
                user_id,
                100
            )

            await send_message(
                group_id,
                "🎉 <b>NHIỆM VỤ CAO HOÀN THÀNH!</b>\n\n"
                "👥 Bạn đã mời đủ 5 người vào nhóm.\n"
                "💰 Phần thưởng: <b>+100 Xu</b>"
            )

            return

        cur.execute(
            """
            UPDATE xu_tasks
            SET people_added = ?
            WHERE user_id = ?
            """,
            (
                progress,
                user_id
            )
        )

        conn.commit()
        conn.close()

        await send_message(
            group_id,
            f"📌 Nhiệm vụ cao: "
            f"<b>{progress}/5</b> người."
        )

# ============================================================
# KHỐI 8 - NHIỆM VỤ CHIA SẺ BOT
# 1 lần = +20 Xu
# 5 lần = +100 Xu
# ============================================================

async def command_chiasebot(message, args=None):
    user = from_user(message)

    if not user:
        return

    user_id = int(user.get("id", 0))

    add_xu_task_user(user_id)

    bot_info = await api_request("getMe")

    if not bot_info or not bot_info.get("ok"):
        await send_message(
            chat_id(message),
            "❌ Không lấy được thông tin bot."
        )
        return

    bot_username = bot_info["result"].get("username")

    if not bot_username:
        await send_message(
            chat_id(message),
            "❌ Bot chưa có username."
        )
        return

    share_url = f"https://t.me/{bot_username}"

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🔗 Chia sẻ bot",
                    "url": "https://t.me/share/url?url="
                          + urllib.parse.quote(share_url)
                          + "&text="
                          + urllib.parse.quote(
                              "Mời bạn sử dụng bot Ngọc Mỹ 🤖"
                          )
                }
            ],
            [
                {
                    "text": "✅ Đã chia sẻ",
                    "callback_data": "xu_share_done"
                }
            ]
        ]
    }

    await send_message(
        chat_id(message),
        "🔗 NHIỆM VỤ CHIA SẺ BOT\n\n"
        "Hãy chia sẻ bot cho bạn bè.\n\n"
        "🟢 1 lần chia sẻ → +20 Xu\n"
        "🔴 5 lần chia sẻ → +100 Xu\n\n"
        "Sau khi chia sẻ, bấm nút "
        "「✅ Đã chia sẻ」 để ghi nhận.",
        reply_markup=keyboard
    )

async def xu_share_done_callback(callback_query):
    await answer_callback(
        callback_query.get("id"),
        "❌ Hãy nhận nhiệm vụ bằng /nhiemvutong trước."
    )

COMMAND_HANDLERS["chiasebot"] = command_chiasebot

# ============================================================
# KHỐI 9 - TÀI XỈU
# /taixiu tai 10
# /taixiu xiu 10
# ============================================================

async def command_taixiu(
    message,
    args=None
):
    user = from_user(message)

    if not user:
        return

    user_id = int(
        user.get("id", 0)
    )

    # Dispatcher hiện truyền args dạng chuỗi
    if isinstance(args, str):
        args = args.split()

    if not args or len(args) < 2:
        await send_message(
            chat_id(message),
            "🎲 <b>TÀI XỈU</b>\n\n"
            "Cách dùng:\n"
            "<code>/taixiu tai 10</code>\n"
            "<code>/taixiu xiu 10</code>\n\n"
            "💰 Cược tối thiểu: 10 Xu\n"
            "💰 Cược tối đa: số Xu bạn đang có\n\n"
            "🎯 Chọn Tài → Tài 40% / Xỉu 60%\n"
            "🎯 Chọn Xỉu → Xỉu 40% / Tài 60%\n\n"
            "🏆 Thắng: nhận 2× tiền cược\n"
            "💸 Thua: mất tiền cược"
        )
        return

    choice = str(
        args[0]
    ).lower().strip()

    try:
        bet = float(
            args[1]
        )
    except (
        TypeError,
        ValueError
    ):
        await send_message(
            chat_id(message),
            "❌ Số Xu cược không hợp lệ."
        )
        return

    if choice not in (
        "tai",
        "xiu"
    ):
        await send_message(
            chat_id(message),
            "❌ Bạn phải chọn Tài hoặc Xỉu.\n\n"
            "Ví dụ:\n"
            "/taixiu tai 10\n"
            "/taixiu xiu 10"
        )
        return

    if bet < 10:
        await send_message(
            chat_id(message),
            "❌ Mức cược tối thiểu là 10 Xu."
        )
        return

    account = get_xu_account(
        user_id
    )

    admin_mode = int(
        account[4]
    )

    if admin_mode == 1:
        balance = float("inf")
    else:
        balance = float(
            account[1]
        )

    # Không đủ tiền
    if (
        admin_mode != 1
        and bet > balance
    ):
        await send_message(
            chat_id(message),
            "Bạn Hết Tiền Rồi Hãy Làm Nhiệm Vụ Để Kiếm Thêm Xu,Cảm ơn"
        )
        return

    # ==========================================
    # TỶ LỆ 40% / 60%
    # ==========================================

    # Người chơi chọn bên nào:
    # - Bên được chọn: 40%
    # - Bên đối diện: 60%
    if random.random() < 0.40:
        result = choice
    else:
        result = (
            "xiu"
            if choice == "tai"
            else "tai"
        )

    # ==========================================
    # TẠO 3 XÚC XẮC PHÙ HỢP KẾT QUẢ
    # ==========================================

    while True:

        dice_1 = random.randint(
            1,
            6
        )

        dice_2 = random.randint(
            1,
            6
        )

        dice_3 = random.randint(
            1,
            6
        )

        total = (
            dice_1
            + dice_2
            + dice_3
        )

        # Bỏ bộ ba
        if (
            dice_1
            == dice_2
            == dice_3
        ):
            continue

        actual = (
            "tai"
            if total >= 11
            else "xiu"
        )

        if actual == result:
            break

    # ==========================================
    # TRỪ TIỀN CƯỢC
    # ==========================================

    if admin_mode != 1:

        if not remove_xu(
            user_id,
            bet
        ):
            await send_message(
                chat_id(message),
                "❌ Không thể trừ tiền cược. "
                "Vui lòng thử lại."
            )
            return

    # ==========================================
    # THẮNG / THUA
    # ==========================================

    if result == choice:

        if admin_mode != 1:
            add_xu(
                user_id,
                bet * 2
            )

        result_text = (
            "🎉 BẠN THẮNG!\n"
            f"💰 Nhận: +{bet * 2:.2f} Xu"
        )

    else:

        result_text = (
            "💀 BẠN THUA!\n"
            f"💸 Mất: {bet:.2f} Xu"
        )

    result_name = (
        "🎯 TÀI"
        if result == "tai"
        else "🔵 XỈU"
    )

    balance_text = (
        "∞"
        if admin_mode == 1
        else f"{get_xu(user_id):.2f}"
    )

    await send_message(
        chat_id(message),
        "🎲 <b>KẾT QUẢ TÀI XỈU</b>\n\n"
        f"🎲 Xúc xắc: "
        f"[{dice_1}] [{dice_2}] [{dice_3}]\n"
        f"🔢 Tổng: {total}\n"
        f"📊 Kết quả: {result_name}\n\n"
        f"🎯 Bạn chọn: "
        f"{'TÀI' if choice == 'tai' else 'XỈU'}\n"
        f"💰 Tiền cược: {bet:.2f} Xu\n\n"
        f"{result_text}\n\n"
        f"💰 Số dư: {balance_text}"
    )

COMMAND_HANDLERS["taixiu"] = command_taixiu

# ============================================================
# KHỐI 10 - PHẦN MỀM ADMIN XU
# ============================================================

XU_ADMIN_CODE = "ngocmyvip207"


async def command_xu_admin_code(message, args=None):
    user = from_user(message)

    if not user:
        return

    user_id = int(user.get("id", 0))

    # Chỉ cho nhập mã trong chat riêng
    if not is_private(message):
        await send_message(
            chat_id(message),
            "🔐 Vui lòng mở chat riêng với bot để nhập mã Admin."
        )
        return

    code = ""

    if args:
        if isinstance(args, list):
            code = " ".join(str(x) for x in args).strip()
        else:
            code = str(args).strip()

    if code != XU_ADMIN_CODE:
        await send_message(
            chat_id(message),
            "❌ Code đã sai"
        )
        return

    get_xu_account(user_id)

    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE xu_accounts
        SET admin_mode = 1
        WHERE user_id = ?
        """,
        (user_id,)
    )

    conn.commit()
    conn.close()

    await send_message(
        chat_id(message),
        "👑 KÍCH HOẠT ADMIN THÀNH CÔNG!\n\n"
        "🛠️ Chế độ Admin: BẬT\n"
        "💰 Xu hiện tại: ∞\n"
        "🎲 Có thể sử dụng Tài Xỉu mà không giới hạn Xu."
    )


async def xu_admin_callback(callback_query):
    user = callback_query.get("from") or {}
    user_id = int(user.get("id", 0))

    # Chỉ cho xử lý ở chat riêng
    callback_message = callback_query.get("message") or {}
    callback_chat = callback_message.get("chat") or {}

    if callback_chat.get("type") != "private":
        await answer_callback(
            callback_query.get("id"),
            "🔐 Hãy mở chat riêng với bot để nhập mã Admin."
        )
        return

    await answer_callback(
        callback_query.get("id"),
        "🔐 Mở chat riêng và nhập: /xuadmin <mã>"
    )

    await send_message(
        user_id,
        "🛠️ PHẦN MỀM ADMIN\n\n"
        "Vui lòng nhập mã tài khoản Admin.\n\n"
        "Cú pháp:\n"
        "<code>/xuadmin MÃ_ADMIN</code>\n\n"
        "🔐 Mã được xử lý trong chat riêng."
    )

COMMAND_HANDLERS["xuadmin"] = command_xu_admin_code


# ============================================================
# ĐĂNG KÝ CALLBACK ADMIN
# ============================================================

async def handle_xu_admin_callback(callback_query):
    data = callback_query.get("data", "")

    if data == "xu_admin":
        await xu_admin_callback(callback_query)
        return True

    return False

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\nTHEONE BOT đã dừng."
        )

    except Exception as e:

        logger.exception(
            "Fatal error: %s",
            e
        )

        print(
            "\nBOT DỪNG DO LỖI:"
        )

        print(
            str(e)
        )


# ============================================================
# END PHẦN 10/10
# ============================================================

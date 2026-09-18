# ============================================================
# DTN BOT - FULL VERSION
# Python 3.10+
# pip install -U python-telegram-bot
# ============================================================

import asyncio
import logging
import re
import sqlite3
import time
import random
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import (
    ChatMemberStatus,
    ChatType,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

TOKEN = "8233728594:AAFOTBG8URfrgCfBNwRYttJh1rds6Mvaqm0"

BOT_NAME = "DTN BOT"
OWNER = "@DTN_207"

DB_FILE = "dtn_bot.db"

# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("DTN_BOT")

# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False,
)

db.row_factory = sqlite3.Row

db.execute("PRAGMA journal_mode=WAL")

db.execute("""
CREATE TABLE IF NOT EXISTS settings (
    chat_id INTEGER PRIMARY KEY,
    rules TEXT NOT NULL DEFAULT 'Chưa có nội quy.',
    antilink INTEGER NOT NULL DEFAULT 0,
    antispam INTEGER NOT NULL DEFAULT 0
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS cam_users (
    chat_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS antifake_users (
    chat_id INTEGER,
    user_id INTEGER,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS filters_data (
    chat_id INTEGER,
    trigger TEXT,
    response TEXT,
    PRIMARY KEY(chat_id, trigger)
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    chat_id INTEGER,
    user_id INTEGER,
    last_date TEXT,
    streak INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    PRIMARY KEY(chat_id, user_id)
)
""")

db.commit()

# ============================================================
# CACHE
# ============================================================

spam_cache = defaultdict(lambda: deque(maxlen=20))

afk_users = {}

games = {}
game_tasks = {}

# ============================================================
# DATABASE HELPERS
# ============================================================

def ensure_chat(chat_id):
    db.execute(
        "INSERT OR IGNORE INTO settings(chat_id) VALUES(?)",
        (chat_id,),
    )
    db.commit()


def save_user(chat_id, user):
    if not user:
        return

    db.execute("""
        INSERT INTO users(
            chat_id,
            user_id,
            username,
            first_name,
            last_name
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name
    """, (
        chat_id,
        user.id,
        user.username.lower() if user.username else None,
        user.first_name or "",
        user.last_name or "",
    ))

    db.commit()


def find_saved_user(chat_id, value):
    value = value.strip()

    if value.startswith("@"):
        username = value[1:].lower()

        row = db.execute("""
            SELECT user_id, username, first_name, last_name
            FROM users
            WHERE chat_id=? AND username=?
        """, (
            chat_id,
            username,
        )).fetchone()

    else:
        try:
            user_id = int(value)
        except ValueError:
            return None

        row = db.execute("""
            SELECT user_id, username, first_name, last_name
            FROM users
            WHERE chat_id=? AND user_id=?
        """, (
            chat_id,
            user_id,
        )).fetchone()

    if not row:
        return None

    class SavedUser:
        pass

    user = SavedUser()

    user.id = row["user_id"]
    user.username = row["username"]
    user.first_name = row["first_name"]
    user.last_name = row["last_name"]

    return user


def get_settings(chat_id):
    ensure_chat(chat_id)

    return db.execute("""
        SELECT rules, antilink, antispam
        FROM settings
        WHERE chat_id=?
    """, (chat_id,)).fetchone()

# ============================================================
# TEXT HELPERS
# ============================================================

def display_user(user):
    if getattr(user, "username", None):
        return f"@{user.username}"

    name = getattr(user, "first_name", "") or "User"

    if getattr(user, "last_name", None):
        name += f" {user.last_name}"

    return name


def mention_user(user):
    name = display_user(user)

    return (
        f'<a href="tg://user?id={user.id}">'
        f'{name}</a>'
    )


# ============================================================
# GROUP
# ============================================================

def is_group(update):
    chat = update.effective_chat

    return bool(
        chat
        and chat.type in (
            ChatType.GROUP,
            ChatType.SUPERGROUP,
        )
    )


async def private_group_command(update):
    if not is_group(update):
        await update.message.reply_text(
            "Lệnh Nhóm Mà Ngươi Lại Nhắn Cá Nhân Ngươi Tày Đấy."
        )
        return True

    return False


# ============================================================
# ADMIN
# ============================================================

async def user_is_admin(update, user_id=None):
    if not is_group(update):
        return False

    if user_id is None:
        user_id = update.effective_user.id

    try:
        member = await update.effective_chat.get_member(
            user_id
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception:
        return False


async def bot_is_admin(update, context):
    if not is_group(update):
        return False

    try:
        member = await update.effective_chat.get_member(
            context.bot.id
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception:
        return False


async def admin_required(update):
    if await private_group_command(update):
        return False

    if not await user_is_admin(update):
        await update.message.reply_text(
            "❌ Lệnh này chỉ dành cho quản trị viên."
        )
        return False

    return True


async def bot_admin_required(update, context):
    if not await bot_is_admin(update, context):
        await update.message.reply_text(
            "❌ Bot chưa có quyền quản trị viên."
        )
        return False

    return True


# ============================================================
# TARGET USER
# ============================================================

async def get_target_user(update, context):
    message = update.message
    chat_id = update.effective_chat.id

    # Reply
    if message.reply_to_message:
        user = message.reply_to_message.from_user

        if user:
            save_user(chat_id, user)

        return user

    if not context.args:
        return None

    value = context.args[0].strip()

    # ID
    try:
        user_id = int(value)

        try:
            member = await update.effective_chat.get_member(
                user_id
            )

            save_user(
                chat_id,
                member.user,
            )

            return member.user

        except Exception:
            return find_saved_user(
                chat_id,
                value,
            )

    except ValueError:
        pass

    # Username
    return find_saved_user(
        chat_id,
        value,
    )


# ============================================================
# PARSE TIME
# ============================================================

def parse_duration(value):
    if not value:
        return None

    value = value.strip().lower()

    match = re.fullmatch(
        r"(\d+)(s|m|h|d)?",
        value,
    )

    if not match:
        return None

    number = int(match.group(1))
    unit = match.group(2) or "s"

    multiplier = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }

    seconds = number * multiplier[unit]

    if seconds < 30:
        seconds = 30

    return seconds

# ============================================================
# START
# ============================================================

async def start(update, context):
    await update.message.reply_text(
        "Chào bạn tôi là DTN BOT\n\n"
        "Vui lòng /help để biết thêm về tôi\n\n"
        f"Owner : {OWNER}"
    )


# ============================================================
# HELP
# ============================================================

async def help_command(update, context):

    # GROUP
    if is_group(update):
        await update.message.reply_text(
            "help cái đầu buồi chủ tao chưa làm help group OK"
        )
        return

    # PRIVATE
    text = f"""
💀 ĐỌC ĐI CHO HIỂU LỆNH OK 💀

{BOT_NAME} — DANH SÁCH LỆNH

━━ QUẢN LÝ THÀNH VIÊN ━━

/mute 30s
→ Mute người được reply.

/mute @username 5m
→ Mute theo username.

/mute ID 2h
→ Mute theo ID.

/unmute
→ Mở mute.

/ban
→ Ban thành viên.

/unban ID
→ Gỡ ban.

/kick
→ Đá thành viên khỏi nhóm.

/thangcap
→ Thăng thành quản trị viên.

/thangcapfull
→ Thăng quản trị viên với tối đa quyền bot có thể cấp.

/hacap
→ Hạ quản trị viên.

━━ CẢNH CÁO ━━

/warn
→ Thêm 1 cảnh cáo.

/warnings
→ Xem cảnh cáo.

/clearwarn
→ Xóa cảnh cáo.

━━ TIN NHẮN ━━

/del
→ Xóa tin được reply.

/pin
→ Ghim tin được reply.

/unpin
→ Bỏ ghim.

━━ NHÓM ━━

/lock
→ Khóa thành viên gửi tin.

/unlock
→ Mở khóa.

/rules
→ Xem nội quy.

/setrules Nội dung
→ Đặt nội quy.

━━ BẢO VỆ ━━

/antilink on
→ Bật chống link.

/antilink off
→ Tắt chống link.

/antispam on
→ Bật chống spam.

/antispam off
→ Tắt chống spam.

/cam reply
→ Xóa toàn bộ tin mới của người đó.

/camoff reply
→ Tắt CAM.

/antifake reply
→ Đánh dấu người được bảo vệ.

━━ FILTER ━━

/filter alo alo cái gì
→ Khi có "alo" bot trả lời.

/filters
→ Xem danh sách filter.

/stop alo
→ Xóa filter "alo".

━━ AFK ━━

/afk
→ Bật trạng thái AFK.

/afk đi ngủ
→ Bật AFK kèm lý do.

→ Khi người khác reply/mention người AFK,
bot sẽ báo người đó đang AFK.

━━ GAME ━━

/gamenoichu
→ Mở game nối chữ.

/gameoff
→ Tắt game.

━━ ĐIỂM DANH ━━

/diemdanh
→ Điểm danh hôm nay.

/diemdanh top
→ Xem bảng xếp hạng.

━━ THÔNG TIN ━━

/id
→ Xem ID.

/info
→ Xem thông tin.

/admins
→ Xem admin nhóm.

━━ GIẢI TRÍ ━━

/thodoi
→ Thơ đời.

/thotinh
→ Thơ tình.

/ai(bảo trì)
→ bảo trì không sử dụng.

━━ HỆ THỐNG ━━

/start
→ Khởi động bot.

/help
→ Xem hướng dẫn.

Owner : {OWNER}
"""

    await update.message.reply_text(
        text.strip()
    )


# ============================================================
# MUTE
# ============================================================

async def mute(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    user = None
    duration_arg = None

    # Reply
    if update.message.reply_to_message:

        user = (
            update.message
            .reply_to_message
            .from_user
        )

        save_user(
            update.effective_chat.id,
            user,
        )

        if context.args:
            duration_arg = context.args[0]

    else:

        user = await get_target_user(
            update,
            context,
        )

        if len(context.args) >= 2:
            duration_arg = context.args[1]

    if not user:

        await update.message.reply_text(
            "❌ Dùng:\n"
            "/mute 30s khi reply\n"
            "/mute @username 5m\n"
            "/mute ID 2h"
        )

        return

    seconds = (
        parse_duration(duration_arg)
        if duration_arg
        else 3600
    )

    if duration_arg and seconds is None:

        await update.message.reply_text(
            "❌ Thời gian không hợp lệ.\n"
            "Dùng: 30s, 5m, 2h hoặc 1d."
        )

        return

    try:

        await update.effective_chat.restrict_member(
            user.id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
            until_date=int(time.time()) + seconds,
        )

        await update.message.reply_text(
            f"🔇 Đã mute "
            f"{mention_user(user)} "
            f"trong {seconds} giây.",
            parse_mode="HTML",
        )

    except Exception as e:

        logger.exception(e)

        await update.message.reply_text(
            "❌ Không thể mute thành viên này."
        )


# ============================================================
# UNMUTE
# ============================================================

async def unmute(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        await update.message.reply_text(
            "❌ Reply hoặc nhập ID/@username."
        )
        return

    try:

        await update.effective_chat.restrict_member(
            user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )

        await update.message.reply_text(
            f"🔊 Đã unmute "
            f"{mention_user(user)}.",
            parse_mode="HTML",
        )

    except Exception:
        await update.message.reply_text(
            "❌ Không thể unmute."
        )

# ============================================================
# BAN
# ============================================================

async def ban(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        await update.message.reply_text(
            "❌ Reply hoặc nhập ID/@username."
        )
        return

    try:

        await update.effective_chat.ban_member(
            user.id
        )

        await update.message.reply_text(
            f"🔨 Đã ban {mention_user(user)}.",
            parse_mode="HTML",
        )

    except Exception:
        await update.message.reply_text(
            "❌ Không thể ban thành viên này."
        )


# ============================================================
# UNBAN
# ============================================================

async def unban(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    if not context.args:

        await update.message.reply_text(
            "❌ Dùng: /unban ID"
        )

        return

    try:

        user_id = int(context.args[0])

        await update.effective_chat.unban_member(
            user_id,
            only_if_banned=True,
        )

        await update.message.reply_text(
            f"✅ Đã unban ID {user_id}."
        )

    except Exception:
        await update.message.reply_text(
            "❌ Không thể unban ID này."
        )


# ============================================================
# KICK
# ============================================================

async def kick(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        await update.message.reply_text(
            "❌ Reply hoặc nhập ID/@username."
        )
        return

    try:

        await update.effective_chat.ban_member(
            user.id
        )

        await update.effective_chat.unban_member(
            user.id,
            only_if_banned=True,
        )

        await update.message.reply_text(
            f"👢 Đã kick {mention_user(user)}.",
            parse_mode="HTML",
        )

    except Exception:
        await update.message.reply_text(
            "❌ Không thể kick thành viên này."
        )


# ============================================================
# PROMOTE
# ============================================================

async def promote_user(
    update,
    context,
    full=False,
):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:

        await update.message.reply_text(
            "❌ Reply hoặc nhập ID/@username."
        )

        return

    if user.id == context.bot.id:

        await update.message.reply_text(
            "❌ Không thể thăng cấp chính bot."
        )

        return

    try:

        # Các quyền cơ bản + quyền quản trị.
        # Telegram chỉ cho bot cấp những quyền
        # mà chính bot đang có.

        permissions = {
            "is_anonymous": False,
            "can_manage_chat": True,
            "can_delete_messages": True,
            "can_manage_video_chats": True,
            "can_restrict_members": True,
            "can_promote_members": True,
            "can_change_info": True,
            "can_invite_users": True,
            "can_pin_messages": True,
            "can_manage_topics": True,
        }

        if full:

            # Một số phiên bản Bot API/PTB có thêm
            # các quyền story/tag.
            permissions.update({
                "can_post_stories": True,
                "can_edit_stories": True,
                "can_delete_stories": True,
                "can_manage_tags": True,
            })

        try:

            await context.bot.promote_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user.id,
                **permissions,
            )

        except TypeError:

            # Tương thích với PTB cũ hơn.
            permissions.pop(
                "can_post_stories",
                None,
            )

            permissions.pop(
                "can_edit_stories",
                None,
            )

            permissions.pop(
                "can_delete_stories",
                None,
            )

            permissions.pop(
                "can_manage_tags",
                None,
            )

            await context.bot.promote_chat_member(
                chat_id=update.effective_chat.id,
                user_id=user.id,
                **permissions,
            )

        if full:

            text = (
                f"👑 Đã thăng cấp FULL quyền "
                f"cho {mention_user(user)}.\n\n"
                "⚠️ Telegram chỉ cho phép bot "
                "cấp những quyền mà bot có."
            )

        else:

            text = (
                f"👑 Đã thăng cấp "
                f"{mention_user(user)} "
                "thành quản trị viên."
            )

        await update.message.reply_text(
            text,
            parse_mode="HTML",
        )

    except Exception as e:

        logger.exception(e)

        await update.message.reply_text(
            "❌ Không thể thăng cấp.\n"
            "Kiểm tra bot có quyền "
            "Thêm quản trị viên hay không."
        )


async def thangcap(update, context):
    await promote_user(
        update,
        context,
        full=False,
    )


async def thangcapfull(update, context):
    await promote_user(
        update,
        context,
        full=True,
    )


# ============================================================
# DEMOTE
# ============================================================

async def hacap(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        await update.message.reply_text(
            "❌ Reply hoặc nhập ID/@username."
        )
        return

    try:

        await context.bot.promote_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user.id,
            is_anonymous=False,
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
        )

        await update.message.reply_text(
            f"⬇️ Đã hạ cấp "
            f"{mention_user(user)}.",
            parse_mode="HTML",
        )

    except Exception:
        await update.message.reply_text(
            "❌ Không thể hạ cấp."
        )

# ============================================================
# WARN
# ============================================================

async def warn(update, context):

    if not await admin_required(update):
        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        await update.message.reply_text(
            "❌ Reply hoặc nhập ID/@username."
        )
        return

    chat_id = update.effective_chat.id

    row = db.execute("""
        SELECT count
        FROM warnings
        WHERE chat_id=? AND user_id=?
    """, (
        chat_id,
        user.id,
    )).fetchone()

    count = (row["count"] if row else 0) + 1

    db.execute("""
        INSERT INTO warnings(
            chat_id,
            user_id,
            count
        )
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id,user_id)
        DO UPDATE SET count=excluded.count
    """, (
        chat_id,
        user.id,
        count,
    ))

    db.commit()

    await update.message.reply_text(
        f"⚠️ {mention_user(user)} "
        f"nhận cảnh cáo.\n"
        f"Warning: {count}/3",
        parse_mode="HTML",
    )


# ============================================================
# WARNINGS
# ============================================================

async def warnings(update, context):

    if not is_group(update):
        await update.message.reply_text(
            "Lệnh Nhóm Mà Xài Cá Nhân Coi Bộ Ngươi Tày Đấy."
        )
        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        user = update.effective_user

    row = db.execute("""
        SELECT count
        FROM warnings
        WHERE chat_id=? AND user_id=?
    """, (
        update.effective_chat.id,
        user.id,
    )).fetchone()

    count = row["count"] if row else 0

    await update.message.reply_text(
        f"⚠️ {mention_user(user)}: "
        f"{count} warning.",
        parse_mode="HTML",
    )


# ============================================================
# CLEAR WARN
# ============================================================

async def clearwarn(update, context):

    if not await admin_required(update):
        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        await update.message.reply_text(
            "❌ Reply hoặc nhập ID/@username."
        )
        return

    db.execute("""
        DELETE FROM warnings
        WHERE chat_id=? AND user_id=?
    """, (
        update.effective_chat.id,
        user.id,
    ))

    db.commit()

    await update.message.reply_text(
        "✅ Đã xóa toàn bộ warning."
    )


# ============================================================
# DELETE
# ============================================================

async def delete_message(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    if not update.message.reply_to_message:

        await update.message.reply_text(
            "❌ Reply tin nhắn cần xóa."
        )

        return

    try:

        await update.message.reply_to_message.delete()
        await update.message.delete()

    except Exception:

        await update.message.reply_text(
            "❌ Không thể xóa tin nhắn."
        )


# ============================================================
# PIN
# ============================================================

async def pin(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    if not update.message.reply_to_message:

        await update.message.reply_text(
            "❌ Reply tin nhắn cần ghim."
        )

        return

    try:

        await update.message.reply_to_message.pin(
            disable_notification=False
        )

        await update.message.reply_text(
            "📌 Đã ghim tin nhắn."
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể ghim tin nhắn."
        )


# ============================================================
# UNPIN
# ============================================================

async def unpin(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    try:

        await update.effective_chat.unpin_all_messages()

        await update.message.reply_text(
            "📌 Đã bỏ ghim."
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể bỏ ghim."
        )


# ============================================================
# LOCK
# ============================================================

async def lock(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    try:

        await update.effective_chat.set_permissions(
            ChatPermissions(
                can_send_messages=False
            )
        )

        await update.message.reply_text(
            "🔒 Đã khóa nhóm."
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể khóa nhóm."
        )


# ============================================================
# UNLOCK
# ============================================================

async def unlock(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    try:

        await update.effective_chat.set_permissions(
            ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            )
        )

        await update.message.reply_text(
            "🔓 Đã mở khóa nhóm."
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể mở khóa nhóm."
        )


# ============================================================
# RULES
# ============================================================

async def rules(update, context):

    if not is_group(update):
        await update.message.reply_text(
            "❌ Lệnh này hãy sử dụng trong nhóm."
        )
        return

    settings = get_settings(
        update.effective_chat.id
    )

    await update.message.reply_text(
        f"📜 NỘI QUY NHÓM\n\n"
        f"{settings['rules']}"
    )


async def setrules(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "❌ Dùng: /setrules Nội dung nội quy"
        )

        return

    text = " ".join(context.args)

    ensure_chat(
        update.effective_chat.id
    )

    db.execute("""
        UPDATE settings
        SET rules=?
        WHERE chat_id=?
    """, (
        text,
        update.effective_chat.id,
    ))

    db.commit()

    await update.message.reply_text(
        "✅ Đã cập nhật nội quy."
    )

# ============================================================
# ANTILINK
# ============================================================

async def antilink(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "❌ Dùng /antilink on hoặc /antilink off"
        )

        return

    value = context.args[0].lower()

    if value not in ("on", "off"):

        await update.message.reply_text(
            "❌ Dùng /antilink on hoặc /antilink off"
        )

        return

    ensure_chat(
        update.effective_chat.id
    )

    enabled = 1 if value == "on" else 0

    db.execute("""
        UPDATE settings
        SET antilink=?
        WHERE chat_id=?
    """, (
        enabled,
        update.effective_chat.id,
    ))

    db.commit()

    await update.message.reply_text(
        f"🔗 Anti-link: "
        f"{'BẬT' if enabled else 'TẮT'}"
    )


# ============================================================
# ANTISPAM
# ============================================================

async def antispam(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "❌ Dùng /antispam on hoặc /antispam off"
        )

        return

    value = context.args[0].lower()

    if value not in ("on", "off"):

        await update.message.reply_text(
            "❌ Dùng /antispam on hoặc /antispam off"
        )

        return

    ensure_chat(
        update.effective_chat.id
    )

    enabled = 1 if value == "on" else 0

    db.execute("""
        UPDATE settings
        SET antispam=?
        WHERE chat_id=?
    """, (
        enabled,
        update.effective_chat.id,
    ))

    db.commit()

    await update.message.reply_text(
        f"🛡 Anti-spam: "
        f"{'BẬT' if enabled else 'TẮT'}"
    )


# ============================================================
# CAM
# ============================================================

async def cam(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "❌ Dùng /cam reply hoặc /cam ID hoặc /cam @username"
        )

        return

    chat_id = update.effective_chat.id

    db.execute("""
        INSERT OR IGNORE INTO cam_users(
            chat_id,
            user_id
        )
        VALUES (?, ?)
    """, (
        chat_id,
        target.id,
    ))

    db.commit()

    save_user(
        chat_id,
        target,
    )

    await update.message.reply_text(
        f"🚫 Đã bật CAM cho "
        f"{mention_user(target)}.\n"
        "Tin nhắn mới của người này sẽ bị xóa.",
        parse_mode="HTML",
    )


# ============================================================
# CAM OFF
# ============================================================

async def camoff(update, context):

    if not await admin_required(update):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "❌ Dùng /camoff reply hoặc /camoff ID hoặc /camoff @username"
        )

        return

    db.execute("""
        DELETE FROM cam_users
        WHERE chat_id=? AND user_id=?
    """, (
        update.effective_chat.id,
        target.id,
    ))

    db.commit()

    await update.message.reply_text(
        f"✅ Đã tắt CAM cho "
        f"{mention_user(target)}.",
        parse_mode="HTML",
    )


def cam_enabled(chat_id, user_id):

    row = db.execute("""
        SELECT 1
        FROM cam_users
        WHERE chat_id=? AND user_id=?
    """, (
        chat_id,
        user_id,
    )).fetchone()

    return bool(row)


# ============================================================
# ANTIFAKE
# ============================================================

async def antifake(update, context):

    if not await admin_required(update):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:

        await update.message.reply_text(
            "❌ Dùng /antifake reply hoặc /antifake ID hoặc /antifake @username"
        )

        return

    chat_id = update.effective_chat.id

    db.execute("""
        INSERT OR IGNORE INTO antifake_users(
            chat_id,
            user_id
        )
        VALUES (?, ?)
    """, (
        chat_id,
        target.id,
    ))

    db.commit()

    save_user(
        chat_id,
        target,
    )

    await update.message.reply_text(
        f"🛡 Đã bảo vệ "
        f"{mention_user(target)}.",
        parse_mode="HTML",
    )

# ============================================================
# FILTER
# ============================================================

async def filter_command(update, context):

    if not is_group(update):
        await update.message.reply_text(
            "❌ Lệnh này hãy sử dụng trong nhóm."
        )
        return

    # Chỉ owner/admin có quyền thay đổi filter
    if not await user_is_admin(update):

        await update.message.reply_text(
            "❌ Chỉ admin mới được thêm filter."
        )

        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "❌ Dùng:\n"
            "/filter từ_khóa nội_dung_phản_hồi\n\n"
            "Ví dụ:\n"
            "/filter alo alo cái gì"
        )

        return

    trigger = context.args[0].lower().strip()
    response = " ".join(context.args[1:]).strip()

    if not trigger or not response:
        return

    db.execute("""
        INSERT INTO filters_data(
            chat_id,
            trigger,
            response
        )
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id,trigger)
        DO UPDATE SET response=excluded.response
    """, (
        update.effective_chat.id,
        trigger,
        response,
    ))

    db.commit()

    await update.message.reply_text(
        f"✅ Đã thêm filter:\n"
        f"🔹 Trigger: {trigger}\n"
        f"🔹 Response: {response}"
    )


# ============================================================
# FILTERS
# ============================================================

async def filters_command(update, context):

    if not is_group(update):
        await update.message.reply_text(
            "❌ Lệnh này hãy sử dụng trong nhóm."
        )
        return

    rows = db.execute("""
        SELECT trigger, response
        FROM filters_data
        WHERE chat_id=?
        ORDER BY trigger
    """, (
        update.effective_chat.id,
    )).fetchall()

    if not rows:

        await update.message.reply_text(
            "📭 Nhóm chưa có filter."
        )

        return

    text = "📋 DANH SÁCH FILTER\n\n"

    for row in rows:

        text += (
            f"• {row['trigger']} → "
            f"{row['response']}\n"
        )

    await update.message.reply_text(
        text
    )


# ============================================================
# STOP FILTER
# ============================================================

async def stop_filter(update, context):

    if not is_group(update):
        await update.message.reply_text(
            "❌ Lệnh này hãy sử dụng trong nhóm."
        )
        return

    if not await user_is_admin(update):

        await update.message.reply_text(
            "❌ Chỉ admin mới được xóa filter."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ Dùng: /stop từ_khóa"
        )

        return

    trigger = " ".join(
        context.args
    ).lower().strip()

    db.execute("""
        DELETE FROM filters_data
        WHERE chat_id=? AND trigger=?
    """, (
        update.effective_chat.id,
        trigger,
    ))

    db.commit()

    await update.message.reply_text(
        f"✅ Đã xóa filter: {trigger}"
    )


# ============================================================
# AFK
# ============================================================

async def afk_command(update, context):

    user = update.effective_user

    reason = (
        " ".join(context.args).strip()
        if context.args
        else "Không có lý do"
    )

    afk_users[user.id] = {
        "name": display_user(user),
        "reason": reason,
        "time": time.time(),
    }

    await update.message.reply_text(
        f"💤 {display_user(user)} đã AFK.\n"
        f"📝 Lý do: {reason}"
    )


# ============================================================
# ID
# ============================================================

async def id_command(update, context):

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        user = update.effective_user

    await update.message.reply_text(
        f"👤 {display_user(user)}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Username: "
        f"@{user.username if getattr(user, 'username', None) else 'Không có'}"
    )


# ============================================================
# INFO
# ============================================================

async def info(update, context):

    if not is_group(update):

        await update.message.reply_text(
            "❌ Lệnh này hãy sử dụng trong nhóm."
        )

        return

    user = await get_target_user(
        update,
        context,
    )

    if not user:
        user = update.effective_user

    try:

        member = await update.effective_chat.get_member(
            user.id
        )

        status = member.status

    except Exception:

        status = "unknown"

    await update.message.reply_text(
        f"👤 {display_user(user)}\n"
        f"🆔 ID: {user.id}\n"
        f"🔗 Username: "
        f"@{user.username if getattr(user, 'username', None) else 'Không có'}\n"
        f"📌 Trạng thái: {status}"
    )


# ============================================================
# ADMINS
# ============================================================

async def admins(update, context):

    if not is_group(update):

        await update.message.reply_text(
            "❌ Lệnh này hãy sử dụng trong nhóm."
        )

        return

    try:

        administrators = (
            await update.effective_chat
            .get_administrators()
        )

        text = "👑 DANH SÁCH ADMIN\n\n"

        for member in administrators:

            text += (
                f"• {display_user(member.user)}\n"
                f"  ID: {member.user.id}\n\n"
            )

        await update.message.reply_text(
            text
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể lấy danh sách admin."
        )


# ============================================================
# POEMS
# ============================================================

LIFE_POEMS = [
    "Đời người như bóng câu qua cửa, biết đủ rồi lòng sẽ bình yên.",
    "Có những ngày mưa mới hiểu, bình yên quý giá đến nhường nào.",
    "Đường đời nhiều ngã rẽ, cứ bước rồi sẽ tìm được lối đi.",
    "Đời chẳng hứa bình yên, nên ta học cách mạnh mẽ giữa phong ba.",
    "Có những chuyện hôm nay buồn, ngày mai nhìn lại chỉ còn là kỷ niệm.",
]

LOVE_POEMS = [
    "Thương một người chẳng cần lý do, chỉ cần người ấy bình yên là đủ.",
    "Tình yêu đẹp nhất khi hai người cùng chọn nhau qua những ngày bình thường.",
    "Có người chẳng cần nói nhớ, chỉ cần xuất hiện đã làm một ngày dịu lại.",
    "Giữa bao người xa lạ, gặp được nhau đã là một điều rất đẹp.",
    "Tình yêu không cần quá lớn, chỉ cần đủ thật để ở lại cùng nhau.",
]


async def thodoi(update, context):

    await update.message.reply_text(
        random.choice(LIFE_POEMS)
    )


async def thotinh(update, context):

    await update.message.reply_text(
        random.choice(LOVE_POEMS)
    )


# ============================================================
# AI
# ============================================================

async def ai_command(update, context):

    if not context.args:

        await update.message.reply_text(
            "🤖 AI DTN BOT\n\n"
            "Hãy nhập câu hỏi sau /ai\n\n"
            "Ví dụ:\n"
            "/ai xin chào"
        )

        return

    question = " ".join(context.args)

    await update.message.reply_text(
        f"🤖 Bạn vừa hỏi:\n{question}\n\n"
        "DTN BOT đã nhận câu hỏi."
    )

# ============================================================
# GAME NỐI CHỮ
# ============================================================

START_WORDS = [
    "mặt trời",
    "bầu trời",
    "hoa hồng",
    "học sinh",
    "trường học",
    "con đường",
    "quê hương",
    "bình minh",
    "mưa rơi",
    "nụ cười",
    "ước mơ",
    "gia đình",
]


def clean_words(text):

    text = re.sub(
        r"[^\wÀ-ỹ ]+",
        "",
        text.lower(),
        flags=re.UNICODE,
    )

    return text.strip().split()


def first_word(text):

    words = clean_words(text)

    return words[0] if words else ""


def last_word(text):

    words = clean_words(text)

    return words[-1] if words else ""


async def gamenoichu(update, context):

    if not await admin_required(update):
        return

    if not await bot_admin_required(update, context):
        return

    chat_id = update.effective_chat.id

    old_task = game_tasks.get(chat_id)

    if old_task and not old_task.done():
        old_task.cancel()

    games[chat_id] = {
        "phase": "join",
        "players": [],
        "turn": 0,
        "current_word": None,
        "started_at": time.time(),
        "used": set(),
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎮 THAM GIA",
                callback_data="dtn_join_game",
            )
        ]
    ])

    await update.message.reply_text(
        "🎮 GAME NỐI CHỮ\n\n"
        "Bấm nút THAM GIA để vào game.\n"
        "⏳ Thời gian tham gia: 5 phút.\n"
        "👥 Cần ít nhất 2 người.\n\n"
        "Sau 5 phút game bắt đầu.",
        reply_markup=keyboard,
    )

    game_tasks[chat_id] = asyncio.create_task(
        game_countdown(
            context,
            chat_id,
        )
    )


# ============================================================
# GAME JOIN
# ============================================================

async def game_join_callback(update, context):

    query = update.callback_query

    await query.answer()

    chat = query.message.chat
    user = query.from_user

    state = games.get(chat.id)

    if not state or state.get("phase") != "join":

        await query.answer(
            "Game đã kết thúc.",
            show_alert=True,
        )

        return

    if time.time() - state["started_at"] >= 300:

        await query.answer(
            "Đã hết thời gian tham gia.",
            show_alert=True,
        )

        return

    if any(
        player["id"] == user.id
        for player in state["players"]
    ):

        await query.answer(
            "Bạn đã tham gia rồi 😄",
            show_alert=True,
        )

        return

    state["players"].append({
        "id": user.id,
        "user": user,
        "alive": True,
    })

    save_user(
        chat.id,
        user,
    )

    number = len(state["players"])

    await query.answer(
        f"Đã tham gia! Bạn là người số {number}.",
        show_alert=True,
    )

    try:

        await query.message.reply_text(
            f"🎮 {mention_user(user)} "
            f"đã tham gia — số {number}.",
            parse_mode="HTML",
        )

    except Exception:
        pass


# ============================================================
# GAME START
# ============================================================

async def game_start_now(context, chat_id):

    state = games.get(chat_id)

    if not state or state.get("phase") != "join":
        return

    if len(state["players"]) < 2:

        try:

            await context.bot.send_message(
                chat_id,
                "❌ Game chưa đủ 2 người nên đã hủy.",
            )

        except Exception:
            pass

        games.pop(chat_id, None)

        return

    state["phase"] = "playing"
    state["turn"] = 0

    state["current_word"] = random.choice(
        START_WORDS
    )

    state["used"] = {
        state["current_word"]
    }

    player = state["players"][0]

    await context.bot.send_message(
        chat_id,
        "🔥 GAME NỐI CHỮ BẮT ĐẦU!\n\n"
        f"👤 Đến lượt "
        f"{mention_user(player['user'])}\n"
        f"🔤 Từ đầu tiên: "
        f"<b>{state['current_word']}</b>\n"
        f"👉 Từ tiếp theo phải bắt đầu bằng: "
        f"<b>{last_word(state['current_word'])}</b>",
        parse_mode="HTML",
    )


async def game_countdown(context, chat_id):

    try:

        await asyncio.sleep(300)

        await game_start_now(
            context,
            chat_id,
        )

    except asyncio.CancelledError:
        pass

    finally:

        game_tasks.pop(
            chat_id,
            None,
        )


# ============================================================
# GAME MESSAGE
# ============================================================

async def game_message(update, context):

    message = update.message

    if (
        not message
        or not is_group(update)
        or not message.from_user
    ):
        return False

    state = games.get(
        update.effective_chat.id
    )

    if not state or state.get("phase") != "playing":
        return False

    user_id = message.from_user.id

    players = state["players"]

    alive = [
        player
        for player in players
        if player["alive"]
    ]

    if len(alive) <= 1:

        games.pop(
            update.effective_chat.id,
            None,
        )

        return True

    current = alive[
        state["turn"] % len(alive)
    ]

    # Không phải lượt thì bỏ qua.
    if user_id != current["id"]:
        return True

    text = (
        message.text or ""
    ).strip()

    if not text:
        return True

    answer = " ".join(
        clean_words(text)
    )

    needed = last_word(
        state["current_word"]
    )

    # Sai hoặc trùng từ
    if (
        first_word(answer) != needed
        or answer in state["used"]
    ):

        current["alive"] = False

        try:

            await message.reply_text(
                f"❌ {mention_user(message.from_user)} "
                "nối sai nên bị loại!",
                parse_mode="HTML",
            )

        except Exception:
            pass

    else:

        state["current_word"] = answer

        state["used"].add(
            answer
        )

    alive = [
        player
        for player in players
        if player["alive"]
    ]

    if len(alive) == 1:

        winner = alive[0]

        await message.reply_text(
            f"👑 NHÀ VUA: "
            f"{mention_user(winner['user'])}\n"
            "🎉 Chúc mừng người chiến thắng!",
            parse_mode="HTML",
        )

        games.pop(
            update.effective_chat.id,
            None,
        )

        return True

    state["turn"] += 1

    alive = [
        player
        for player in players
        if player["alive"]
    ]

    next_player = alive[
        state["turn"] % len(alive)
    ]

    await message.reply_text(
        f"🎯 Đến lượt "
        f"{mention_user(next_player['user'])}\n"
        f"🔤 Từ hiện tại: "
        f"<b>{state['current_word']}</b>\n"
        f"👉 Nối bằng từ: "
        f"<b>{last_word(state['current_word'])}</b>",
        parse_mode="HTML",
    )

    return True


# ============================================================
# GAME OFF
# ============================================================

async def gameoff(update, context):

    if not await admin_required(update):
        return

    chat_id = update.effective_chat.id

    task = game_tasks.pop(
        chat_id,
        None,
    )

    if task and not task.done():
        task.cancel()

    games.pop(
        chat_id,
        None,
    )

    await update.message.reply_text(
        "🛑 Đã tắt game."
    )

# ============================================================
# VIETNAM DATE
# ============================================================

def vietnam_date():

    return (
        datetime.now(
            timezone.utc
        ) + timedelta(hours=7)
    ).date()


# ============================================================
# DIEM DANH
# ============================================================

async def diemdanh(update, context):

    if not is_group(update):

        await update.message.reply_text(
            "❌ Lệnh này hãy sử dụng trong nhóm."
        )

        return

    chat_id = update.effective_chat.id

    # TOP
    if context.args and context.args[0].lower() == "top":

        rows = db.execute("""
            SELECT user_id, streak, total
            FROM attendance
            WHERE chat_id=?
            ORDER BY streak DESC, total DESC
            LIMIT 10
        """, (
            chat_id,
        )).fetchall()

        if not rows:

            await update.message.reply_text(
                "📭 Chưa có dữ liệu điểm danh."
            )

            return

        text = "🏆 BẢNG XẾP HẠNG ĐIỂM DANH\n\n"

        for index, row in enumerate(rows, 1):

            user = find_saved_user(
                chat_id,
                str(row["user_id"]),
            )

            name = (
                display_user(user)
                if user
                else str(row["user_id"])
            )

            text += (
                f"{index}. {name}\n"
                f"🔥 Streak: {row['streak']}\n"
                f"📅 Tổng: {row['total']}\n\n"
            )

        await update.message.reply_text(
            text
        )

        return

    user = update.effective_user

    today = str(
        vietnam_date()
    )

    row = db.execute("""
        SELECT last_date, streak, total
        FROM attendance
        WHERE chat_id=? AND user_id=?
    """, (
        chat_id,
        user.id,
    )).fetchone()

    if row and row["last_date"] == today:

        await update.message.reply_text(
            "✅ Hôm nay bạn đã điểm danh rồi."
        )

        return

    if row:

        last = datetime.strptime(
            row["last_date"],
            "%Y-%m-%d",
        ).date()

        yesterday = (
            vietnam_date()
            - timedelta(days=1)
        )

        if last == yesterday:
            streak = row["streak"] + 1
        else:
            streak = 1

        total = row["total"] + 1

        db.execute("""
            UPDATE attendance
            SET last_date=?,
                streak=?,
                total=?
            WHERE chat_id=? AND user_id=?
        """, (
            today,
            streak,
            total,
            chat_id,
            user.id,
        ))

    else:

        streak = 1
        total = 1

        db.execute("""
            INSERT INTO attendance(
                chat_id,
                user_id,
                last_date,
                streak,
                total
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            chat_id,
            user.id,
            today,
            streak,
            total,
        ))

    db.commit()

    save_user(
        chat_id,
        user,
    )

    await update.message.reply_text(
        f"✅ {mention_user(user)} "
        "điểm danh thành công!\n\n"
        f"🔥 Streak: {streak} ngày\n"
        f"📅 Tổng điểm danh: {total} lần",
        parse_mode="HTML",
    )


# ============================================================
# WELCOME
# ============================================================

async def welcome(update, context):

    event = update.chat_member

    if not event:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    was_out = old_status in (
        ChatMemberStatus.LEFT,
        ChatMemberStatus.KICKED,
    )

    is_member = new_status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    )

    if not (
        is_member
        and was_out
    ):
        return

    user = event.new_chat_member.user

    save_user(
        update.effective_chat.id,
        user,
    )

    try:

        await context.bot.send_message(
            update.effective_chat.id,
            f"👋 Chào mừng "
            f"{mention_user(user)} "
            "đến với nhóm!",
            parse_mode="HTML",
        )

    except Exception:
        pass


# ============================================================
# PROTECTION
# ============================================================

async def protection_handler(update, context):

    message = update.message

    if (
        not message
        or not message.from_user
        or not is_group(update)
    ):
        return

    user = message.from_user

    if user.is_bot:
        return

    chat_id = update.effective_chat.id

    save_user(
        chat_id,
        user,
    )

    # --------------------------------------------------------
    # GAME
    # --------------------------------------------------------

    if await game_message(
        update,
        context,
    ):
        return

    # --------------------------------------------------------
    # AFK - người gửi tin đã trở lại
    # --------------------------------------------------------

    if user.id in afk_users:

        afk = afk_users.pop(
            user.id,
            None,
        )

        if afk:

            try:

                await message.reply_text(
                    f"👋 {mention_user(user)} "
                    "đã trở lại, AFK đã tắt.",
                    parse_mode="HTML",
                )

            except Exception:
                pass

    # --------------------------------------------------------
    # CAM
    # --------------------------------------------------------

    if cam_enabled(
        chat_id,
        user.id,
    ):

        try:
            await message.delete()
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # ADMIN CHECK
    # --------------------------------------------------------

    try:

        is_admin = await user_is_admin(
            update,
            user.id,
        )

    except Exception:

        is_admin = False

    # --------------------------------------------------------
    # TEXT + CAPTION
    # --------------------------------------------------------

    text_parts = []

    if message.text:
        text_parts.append(
            message.text
        )

    if message.caption:
        text_parts.append(
            message.caption
        )

    text = "\n".join(
        text_parts
    )

    # --------------------------------------------------------
    # ANTILINK
    # --------------------------------------------------------

    settings = get_settings(
        chat_id
    )

    antilink_enabled = bool(
        settings["antilink"]
    )

    antispam_enabled = bool(
        settings["antispam"]
    )

    if (
        antilink_enabled
        and not is_admin
        and text
    ):

        link_pattern = (
            r"(https?://"
            r"|www\."
            r"|t\.me/"
            r"|telegram\.me/"
            r"|telegram\.dog/"
            r"|discord\.gg/"
            r"|discord\.com/invite/)"
        )

        has_link = re.search(
            link_pattern,
            text,
            re.IGNORECASE,
        )

        # Bắt cả URL được Telegram đánh dấu entity.
        entities = (
            list(message.entities or [])
            + list(message.caption_entities or [])
        )

        has_url_entity = any(
            entity.type in (
                "url",
                "text_link",
            )
            for entity in entities
        )

        if has_link or has_url_entity:

            try:
                await message.delete()
            except Exception:
                pass

            return

    # --------------------------------------------------------
    # ANTISPAM
    # --------------------------------------------------------

    if (
        antispam_enabled
        and not is_admin
    ):

        key = (
            chat_id,
            user.id,
        )

        now = time.time()

        spam_cache[key].append(
            now
        )

        recent = [
            timestamp
            for timestamp in spam_cache[key]
            if now - timestamp <= 5
        ]

        spam_cache[key].clear()

        for timestamp in recent:
            spam_cache[key].append(
                timestamp
            )

        # 5 tin trong 5 giây.
        if len(recent) >= 5:

            spam_cache[key].clear()

            try:
                await message.delete()
            except Exception:
                pass

            try:

                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user.id,
                    permissions=ChatPermissions(
                        can_send_messages=False
                    ),
                    until_date=(
                        datetime.now(timezone.utc)
                        + timedelta(seconds=30)
                    ),
                )

                await context.bot.send_message(
                    chat_id,
                    f"🛡 {mention_user(user)} "
                    "bị mute 30 giây do spam.",
                    parse_mode="HTML",
                )

            except Exception as e:

                logger.warning(
                    "Antispam restriction failed: %s",
                    e,
                )

            return

    # --------------------------------------------------------
    # FILTER
    # --------------------------------------------------------

    if text:

        rows = db.execute("""
            SELECT trigger, response
            FROM filters_data
            WHERE chat_id=?
        """, (
            chat_id,
        )).fetchall()

        lower_text = text.lower()

        for row in rows:

            trigger = row["trigger"].lower()

            if trigger in lower_text:

                try:

                    await message.reply_text(
                        row["response"]
                    )

                except Exception:
                    pass

                break

    # --------------------------------------------------------
    # AFK MENTION / REPLY
    # --------------------------------------------------------

    target_user = None

    if message.reply_to_message:

        target_user = (
            message
            .reply_to_message
            .from_user
        )

    if not target_user and message.entities:

        for entity in message.entities:

            if entity.type == "mention":

                try:

                    username = text[
                        entity.offset + 1:
                        entity.offset + entity.length
                    ].lower()

                    row = db.execute("""
                        SELECT user_id
                        FROM users
                        WHERE chat_id=? AND username=?
                    """, (
                        chat_id,
                        username,
                    )).fetchone()

                    if row:

                        target_user = (
                            await update
                            .effective_chat
                            .get_member(
                                row["user_id"]
                            )
                        )

                        target_user = (
                            target_user.user
                        )

                        break

                except Exception:
                    pass

    if target_user and target_user.id in afk_users:

        afk = afk_users[
            target_user.id
        ]

        await message.reply_text(
            f"💤 {mention_user(target_user)} "
            "đang AFK.\n"
            f"📝 Lý do: {afk['reason']}",
            parse_mode="HTML",
        )

# ============================================================
# ERROR
# ============================================================

async def error_handler(update, context):

    logger.error(
        "Unhandled exception:",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if TOKEN == "DAN_TOKEN_MOI_VAO_DAY":

        print(
            "❌ Hãy mở bot.py và nhập token vào TOKEN."
        )

        return

    app = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # ========================================================
    # SYSTEM
    # ========================================================

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    # ========================================================
    # MEMBER MANAGEMENT
    # ========================================================

    app.add_handler(
        CommandHandler(
            "mute",
            mute,
        )
    )

    app.add_handler(
        CommandHandler(
            "unmute",
            unmute,
        )
    )

    app.add_handler(
        CommandHandler(
            "ban",
            ban,
        )
    )

    app.add_handler(
        CommandHandler(
            "unban",
            unban,
        )
    )

    app.add_handler(
        CommandHandler(
            "kick",
            kick,
        )
    )

    app.add_handler(
        CommandHandler(
            "thangcap",
            thangcap,
        )
    )

    app.add_handler(
        CommandHandler(
            "thangcapfull",
            thangcapfull,
        )
    )

    app.add_handler(
        CommandHandler(
            "hacap",
            hacap,
        )
    )

    # ========================================================
    # WARN
    # ========================================================

    app.add_handler(
        CommandHandler(
            "warn",
            warn,
        )
    )

    app.add_handler(
        CommandHandler(
            "warnings",
            warnings,
        )
    )

    app.add_handler(
        CommandHandler(
            "clearwarn",
            clearwarn,
        )
    )

    # ========================================================
    # MESSAGE
    # ========================================================

    app.add_handler(
        CommandHandler(
            "del",
            delete_message,
        )
    )

    app.add_handler(
        CommandHandler(
            "pin",
            pin,
        )
    )

    app.add_handler(
        CommandHandler(
            "unpin",
            unpin,
        )
    )

    # ========================================================
    # GROUP
    # ========================================================

    app.add_handler(
        CommandHandler(
            "lock",
            lock,
        )
    )

    app.add_handler(
        CommandHandler(
            "unlock",
            unlock,
        )
    )

    # ========================================================
    # RULES
    # ========================================================

    app.add_handler(
        CommandHandler(
            "rules",
            rules,
        )
    )

    app.add_handler(
        CommandHandler(
            "setrules",
            setrules,
        )
    )

    # ========================================================
    # SECURITY
    # ========================================================

    app.add_handler(
        CommandHandler(
            "antilink",
            antilink,
        )
    )

    app.add_handler(
        CommandHandler(
            "antispam",
            antispam,
        )
    )

    app.add_handler(
        CommandHandler(
            "antifake",
            antifake,
        )
    )

    app.add_handler(
        CommandHandler(
            "cam",
            cam,
        )
    )

    app.add_handler(
        CommandHandler(
            "camoff",
            camoff,
        )
    )

    # ========================================================
    # FILTER
    # ========================================================

    app.add_handler(
        CommandHandler(
            "filter",
            filter_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "filters",
            filters_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "stop",
            stop_filter,
        )
    )

    # ========================================================
    # INFO
    # ========================================================

    app.add_handler(
        CommandHandler(
            "id",
            id_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "info",
            info,
        )
    )

    app.add_handler(
        CommandHandler(
            "admins",
            admins,
        )
    )

    # ========================================================
    # POEMS / AI
    # ========================================================

    app.add_handler(
        CommandHandler(
            "thodoi",
            thodoi,
        )
    )

    app.add_handler(
        CommandHandler(
            "thotinh",
            thotinh,
        )
    )

    app.add_handler(
        CommandHandler(
            "ai",
            ai_command,
        )
    )

    app.add_handler(
        CommandHandler(
            "afk",
            afk_command,
        )
    )

    # ========================================================
    # GAME
    # ========================================================

    app.add_handler(
        CommandHandler(
            "gamenoichu",
            gamenoichu,
        )
    )

    app.add_handler(
        CommandHandler(
            "gameoff",
            gameoff,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            game_join_callback,
            pattern="^dtn_join_game$",
        )
    )

    # ========================================================
    # ATTENDANCE
    # ========================================================

    app.add_handler(
        CommandHandler(
            "diemdanh",
            diemdanh,
        )
    )

    # ========================================================
    # WELCOME
    # ========================================================

    app.add_handler(
        ChatMemberHandler(
            welcome,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    # ========================================================
    # NORMAL MESSAGES
    # ========================================================

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            protection_handler,
        )
    )

    # ========================================================
    # ERROR
    # ========================================================

    app.add_error_handler(
        error_handler
    )

    # ========================================================
    # START
    # ========================================================

    print(
        f"👑 {BOT_NAME} đang chạy..."
    )

    print(
        f"👑 Owner : {OWNER}"
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()

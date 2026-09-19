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
from collections import defaultdict, deque, Counter
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

spam_cache = defaultdict(
    lambda: deque(maxlen=20)
)

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

    return {
        "id": row["user_id"],
        "username": row["username"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
    }


def get_settings(chat_id):
    ensure_chat(chat_id)

    row = db.execute("""
        SELECT *
        FROM settings
        WHERE chat_id=?
    """, (
        chat_id,
    )).fetchone()

    return row


def display_user(user):
    if not user:
        return "Không rõ"

    if user.username:
        return f"@{user.username}"

    return user.full_name


def mention_user(user):
    if not user:
        return "Không rõ"

    name = (
        user.full_name
        or user.first_name
        or "Người dùng"
    )

    return (
        f'<a href="tg://user?id={user.id}">'
        f'{name}'
        f'</a>'
    )


def is_group(update):
    if not update.effective_chat:
        return False

    return update.effective_chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    )


# ============================================================
# PRIVATE / GROUP
# ============================================================

async def private_group_command(update, text):
    if not update.message:
        return

    if is_group(update):
        return

    await update.message.reply_text(
        text
    )


# ============================================================
# ADMIN CHECK
# ============================================================

async def user_is_admin(update, user_id=None):

    if not update.effective_chat:
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

    if not update.effective_chat:
        return False

    try:

        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            context.bot.id,
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except Exception:

        return False


async def admin_required(update):

    if not is_group(update):
        await update.message.reply_text(
            "❌ Lệnh này chỉ dùng trong nhóm."
        )
        return False

    if not await user_is_admin(update):
        await update.message.reply_text(
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )
        return False

    return True


async def bot_admin_required(update, context):

    if not await bot_is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ Bot phải là quản trị viên."
        )
        return False

    return True


# ============================================================
# GET TARGET USER
# ============================================================

async def get_target_user(update, context):

    if not update.message:
        return None

    # Reply
    if update.message.reply_to_message:

        return (
            update.message
            .reply_to_message
            .from_user
        )

    # @username / ID
    if context.args:

        value = context.args[0]

        saved = find_saved_user(
            update.effective_chat.id,
            value,
        )

        if saved:

            try:

                member = await update.effective_chat.get_member(
                    saved["id"]
                )

                return member.user

            except Exception:

                return None

    return None


# ============================================================
# DURATION
# ============================================================

def parse_duration(value):

    if not value:
        return 3600

    value = value.lower().strip()

    match = re.fullmatch(
        r"(\d+)(s|m|h|d)",
        value,
    )

    if not match:
        return None

    number = int(
        match.group(1)
    )

    unit = match.group(2)

    if unit == "s":
        return number

    if unit == "m":
        return number * 60

    if unit == "h":
        return number * 3600

    if unit == "d":
        return number * 86400

    return None


# ============================================================
# START
# ============================================================

async def start(update, context):

    if not update.message:
        return

    await update.message.reply_text(
        "Chào bạn tôi là DTN BOT\n\n"
        "Vui lòng /help để biết thêm về tôi\n\n"
        "Owner : {@DTN_207}"
    )


# ============================================================
# HELP
# ============================================================

async def help_command(update, context):

    if is_group(update):

        await update.message.reply_text(
            "help cái đầu buồi chủ tao chưa làm help group OK"
        )

        return

    text = f"""

{DTN BOT} — DANH SÁCH LỆNH

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

/masoi
→ Mở trò chơi Ma Sói.

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

Owner : {@DTN_207}
"""

    await update.message.reply_text(
        text.strip()
    )

# ============================================================
# MUTE
# ============================================================

async def mute(update, context):

    if not update.message:
        return

    if not is_group(update):
        return

    if not await user_is_admin(update):
        await update.message.reply_text(
            "❌ Chỉ admin mới dùng được lệnh này."
        )
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Hãy reply tin nhắn người cần mute "
            "hoặc dùng /mute @username 5m"
        )
        return

    duration = 3600

    if context.args:
        last = context.args[-1]
        parsed = parse_duration(last)

        if parsed is not None:
            duration = parsed

    until_date = datetime.now(
        timezone.utc
    ) + timedelta(
        seconds=duration
    )

    try:

        await update.effective_chat.restrict_member(
            target.id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
            until_date=until_date,
        )

        await update.message.reply_text(
            f"🔇 Đã mute {mention_user(target)} "
            f"trong {duration} giây.",
            parse_mode="HTML",
        )

    except Exception as e:

        logger.exception(e)

        await update.message.reply_text(
            "❌ Không thể mute người này."
        )


# ============================================================
# UNMUTE
# ============================================================

async def unmute(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Reply người cần unmute."
        )
        return

    try:

        await update.effective_chat.restrict_member(
            target.id,
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
            f"🔊 Đã unmute {mention_user(target)}",
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

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Reply người cần ban "
            "hoặc dùng /ban @username."
        )
        return

    try:

        await update.effective_chat.ban_member(
            target.id
        )

        await update.message.reply_text(
            f"🚫 Đã ban {mention_user(target)}",
            parse_mode="HTML",
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể ban người này."
        )


# ============================================================
# UNBAN
# ============================================================

async def unban(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Reply người cần unban "
            "hoặc dùng /unban ID."
        )
        return

    try:

        await update.effective_chat.unban_member(
            target.id,
            only_if_banned=True,
        )

        await update.message.reply_text(
            f"✅ Đã unban {mention_user(target)}",
            parse_mode="HTML",
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể unban."
        )


# ============================================================
# KICK
# ============================================================

async def kick(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Reply người cần kick."
        )
        return

    try:

        await update.effective_chat.ban_member(
            target.id
        )

        await asyncio.sleep(1)

        await update.effective_chat.unban_member(
            target.id
        )

        await update.message.reply_text(
            f"👢 Đã kick {mention_user(target)}",
            parse_mode="HTML",
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể kick người này."
        )


# ============================================================
# WARN
# ============================================================

async def warn(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Reply người cần cảnh cáo."
        )
        return

    chat_id = update.effective_chat.id

    db.execute("""
        INSERT INTO warnings(
            chat_id,
            user_id,
            count
        )
        VALUES (?, ?, 1)

        ON CONFLICT(chat_id, user_id)
        DO UPDATE SET
            count = count + 1
    """, (
        chat_id,
        target.id,
    ))

    db.commit()

    row = db.execute("""
        SELECT count
        FROM warnings
        WHERE chat_id=? AND user_id=?
    """, (
        chat_id,
        target.id,
    )).fetchone()

    count = row["count"] if row else 1

    await update.message.reply_text(
        f"⚠️ {mention_user(target)} "
        f"đã nhận cảnh cáo thứ {count}.",
        parse_mode="HTML",
    )


# ============================================================
# WARNINGS
# ============================================================

async def warnings(update, context):

    if not update.message:
        return

    if not is_group(update):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        target = update.effective_user

    row = db.execute("""
        SELECT count
        FROM warnings
        WHERE chat_id=? AND user_id=?
    """, (
        update.effective_chat.id,
        target.id,
    )).fetchone()

    count = row["count"] if row else 0

    await update.message.reply_text(
        f"⚠️ {mention_user(target)} có "
        f"{count} cảnh cáo.",
        parse_mode="HTML",
    )


# ============================================================
# CLEAR WARN
# ============================================================

async def clearwarn(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Reply người cần xóa cảnh cáo."
        )
        return

    db.execute("""
        DELETE FROM warnings
        WHERE chat_id=? AND user_id=?
    """, (
        update.effective_chat.id,
        target.id,
    ))

    db.commit()

    await update.message.reply_text(
        f"✅ Đã xóa toàn bộ cảnh cáo của "
        f"{mention_user(target)}.",
        parse_mode="HTML",
    )


# ============================================================
# DELETE MESSAGE
# ============================================================

async def delete_message(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ Hãy reply tin nhắn cần xóa."
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

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ Hãy reply tin cần ghim."
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
            "❌ Không thể ghim."
        )


# ============================================================
# UNPIN
# ============================================================

async def unpin(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    try:

        if update.message.reply_to_message:

            await update.message.reply_to_message.unpin()

        else:

            await update.effective_chat.unpin_all_forum_topic_messages()

        await update.message.reply_text(
            "📌 Đã bỏ ghim."
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể bỏ ghim."
        )

# ============================================================
# THĂNG CẤP ADMIN
# ============================================================

async def promote(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Hãy reply người cần thăng cấp."
        )
        return

    try:

        await context.bot.promote_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_topics=True,
        )

        await update.message.reply_text(
            f"👑 Đã thăng cấp {mention_user(target)} "
            f"thành quản trị viên.",
            parse_mode="HTML",
        )

    except Exception as e:

        logger.exception(e)

        await update.message.reply_text(
            "❌ Không thể thăng cấp người này."
        )


# ============================================================
# THĂNG CẤP FULL
# ============================================================

async def promote_full(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Hãy reply người cần thăng cấp."
        )
        return

    try:

        await context.bot.promote_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,

            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_topics=True,
            can_post_messages=True,
            can_edit_messages=True,
            can_manage_direct_messages=True,
        )

        await update.message.reply_text(
            f"👑 Đã thăng cấp FULL cho "
            f"{mention_user(target)}.",
            parse_mode="HTML",
        )

    except Exception as e:

        logger.exception(e)

        await update.message.reply_text(
            "❌ Không thể thăng cấp FULL."
        )


# ============================================================
# HẠ CẤP ADMIN
# ============================================================

async def demote(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Hãy reply admin cần hạ cấp."
        )
        return

    try:

        await context.bot.promote_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,

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
            f"🔻 Đã hạ cấp {mention_user(target)}.",
            parse_mode="HTML",
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể hạ cấp người này."
        )


# ============================================================
# LOCK GROUP
# ============================================================

async def lock_group(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    try:

        await context.bot.set_chat_permissions(
            update.effective_chat.id,
            ChatPermissions(
                can_send_messages=False
            ),
        )

        await update.message.reply_text(
            "🔒 Đã khóa nhóm."
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể khóa nhóm."
        )


# ============================================================
# UNLOCK GROUP
# ============================================================

async def unlock_group(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not await bot_admin_required(
        update,
        context,
    ):
        return

    try:

        await context.bot.set_chat_permissions(
            update.effective_chat.id,
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
            ),
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

    if not update.message:
        return

    if not is_group(update):
        return

    settings = get_settings(
        update.effective_chat.id
    )

    await update.message.reply_text(
        "📜 NỘI QUY NHÓM\n\n"
        + settings["rules"]
    )


# ============================================================
# SET RULES
# ============================================================

async def setrules(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Dùng:\n/setrules Nội dung nội quy"
        )
        return

    text = " ".join(
        context.args
    )

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
# ID
# ============================================================

async def id_command(update, context):

    if not update.message:
        return

    target = None

    if update.message.reply_to_message:
        target = (
            update.message
            .reply_to_message
            .from_user
        )

    if target:

        await update.message.reply_text(
            f"🆔 ID: {target.id}\n"
            f"👤 Tên: {target.full_name}"
        )

    else:

        await update.message.reply_text(
            f"🆔 ID của bạn: "
            f"{update.effective_user.id}"
        )


# ============================================================
# INFO
# ============================================================

async def info(update, context):

    if not update.message:
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        target = update.effective_user

    username = (
        f"@{target.username}"
        if target.username
        else "Không có"
    )

    text = (
        "👤 THÔNG TIN\n\n"
        f"Tên: {target.full_name}\n"
        f"Username: {username}\n"
        f"ID: {target.id}"
    )

    await update.message.reply_text(
        text
    )


# ============================================================
# ADMINS
# ============================================================

async def admins(update, context):

    if not update.message:
        return

    if not is_group(update):
        return

    try:

        members = await context.bot.get_chat_administrators(
            update.effective_chat.id
        )

        lines = [
            "👑 DANH SÁCH ADMIN\n"
        ]

        for member in members:

            user = member.user

            username = (
                f"@{user.username}"
                if user.username
                else user.full_name
            )

            lines.append(
                f"• {username} — `{user.id}`"
            )

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
        )

    except Exception:

        await update.message.reply_text(
            "❌ Không thể lấy danh sách admin."
        )

# ============================================================
# ANTILINK
# ============================================================

async def antilink(update, context):

    if not update.message:
        return

    if not is_group(update):
        return

    if not context.args:
        settings = get_settings(
            update.effective_chat.id
        )

        status = (
            "🟢 BẬT"
            if settings["antilink"]
            else "🔴 TẮT"
        )

        await update.message.reply_text(
            f"🔗 Antilink: {status}\n\n"
            "Dùng:\n"
            "/antilink on\n"
            "/antilink off"
        )
        return

    if not await admin_required(update):
        return

    value = context.args[0].lower()

    if value not in ("on", "off"):
        await update.message.reply_text(
            "❌ Dùng /antilink on hoặc /antilink off"
        )
        return

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
        "🔗 Antilink đã "
        + ("🟢 BẬT." if enabled else "🔴 TẮT.")
    )


# ============================================================
# ANTISPAM
# ============================================================

async def antispam(update, context):

    if not update.message:
        return

    if not is_group(update):
        return

    if not context.args:
        settings = get_settings(
            update.effective_chat.id
        )

        status = (
            "🟢 BẬT"
            if settings["antispam"]
            else "🔴 TẮT"
        )

        await update.message.reply_text(
            f"🚫 Antispam: {status}\n\n"
            "Dùng:\n"
            "/antispam on\n"
            "/antispam off"
        )
        return

    if not await admin_required(update):
        return

    value = context.args[0].lower()

    if value not in ("on", "off"):
        await update.message.reply_text(
            "❌ Dùng /antispam on hoặc /antispam off"
        )
        return

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
        "🚫 Antispam đã "
        + ("🟢 BẬT." if enabled else "🔴 TẮT.")
    )


# ============================================================
# AFK
# ============================================================

async def afk(update, context):

    if not update.message:
        return

    user = update.effective_user

    reason = (
        " ".join(context.args)
        if context.args
        else "Không có lý do."
    )

    afk_users[user.id] = {
        "name": user.full_name,
        "reason": reason,
        "time": time.time(),
    }

    await update.message.reply_text(
        f"💤 {mention_user(user)} đã AFK.\n"
        f"📝 Lý do: {reason}",
        parse_mode="HTML",
    )


# ============================================================
# FILTER
# ============================================================

async def filter_command(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Dùng:\n"
            "/filter từ_khóa nội_dung_trả_lời"
        )
        return

    trigger = context.args[0].lower()
    response = " ".join(context.args[1:])

    db.execute("""
        INSERT INTO filters_data(
            chat_id,
            trigger,
            response
        )
        VALUES (?, ?, ?)

        ON CONFLICT(chat_id, trigger)
        DO UPDATE SET response=excluded.response
    """, (
        update.effective_chat.id,
        trigger,
        response,
    ))

    db.commit()

    await update.message.reply_text(
        f"✅ Đã tạo filter cho: {trigger}"
    )


# ============================================================
# FILTERS LIST
# ============================================================

async def filters_command(update, context):

    if not update.message:
        return

    if not is_group(update):
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

    lines = [
        "📋 DANH SÁCH FILTER",
        ""
    ]

    for row in rows:
        lines.append(
            f"• {row['trigger']} → {row['response']}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# STOP FILTER
# ============================================================

async def stop_filter(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not context.args:
        await update.message.reply_text(
            "❌ Dùng /stop từ_khóa"
        )
        return

    trigger = context.args[0].lower()

    cursor = db.execute("""
        DELETE FROM filters_data
        WHERE chat_id=? AND trigger=?
    """, (
        update.effective_chat.id,
        trigger,
    ))

    db.commit()

    if cursor.rowcount:
        await update.message.reply_text(
            f"✅ Đã xóa filter: {trigger}"
        )
    else:
        await update.message.reply_text(
            "❌ Không tìm thấy filter."
        )


# ============================================================
# THƠ ĐỜI
# ============================================================

LIFE_POEMS = [
    (
        "Đời người có lúc lên cao,\n"
        "Có khi mệt mỏi, lao đao giữa đường.\n"
        "Dẫu cho phía trước vô thường,\n"
        "Cứ đi từng bước, rồi đường sẽ thông."
    ),
    (
        "Cuộc đời chẳng phải màu hồng,\n"
        "Có vui có buồn, có lúc long đong.\n"
        "Quan trọng giữ được trong lòng,\n"
        "Một niềm hy vọng để không bỏ mình."
    ),
    (
        "Ngoài kia mưa nắng đổi thay,\n"
        "Người đi người ở, tháng ngày vẫn trôi.\n"
        "Dẫu đời có lúc chơi vơi,\n"
        "Bình tâm bước tiếp, ngày mai sẽ lành."
    ),
]


async def thodoi(update, context):

    if not update.message:
        return

    await update.message.reply_text(
        random.choice(LIFE_POEMS)
    )


# ============================================================
# THƠ TÌNH
# ============================================================

LOVE_POEMS = [
    (
        "Có người chẳng nói thành câu,\n"
        "Nhưng trong ánh mắt giấu bao dịu dàng.\n"
        "Nếu mai hai đứa lỡ làng,\n"
        "Thì xin giữ lại một trang kỷ niệm."
    ),
    (
        "Tình yêu chẳng cần lời hoa,\n"
        "Chỉ cần chân thật đi qua tháng ngày.\n"
        "Dẫu cho thế giới đổi thay,\n"
        "Một người vẫn nhớ một người là vui."
    ),
    (
        "Có khi chẳng ở cạnh nhau,\n"
        "Nhưng lòng vẫn nhớ những câu hôm nào.\n"
        "Thời gian dẫu có qua mau,\n"
        "Kỷ niệm đẹp vẫn ngọt ngào trong tim."
    ),
]


async def thotinh(update, context):

    if not update.message:
        return

    await update.message.reply_text(
        random.choice(LOVE_POEMS)
    )


# ============================================================
# ĐIỂM DANH
# ============================================================

async def diemdanh(update, context):

    if not update.message:
        return

    if not is_group(update):
        await update.message.reply_text(
            "❌ /diemdanh chỉ dùng trong nhóm."
        )
        return

    chat_id = update.effective_chat.id

    if context.args and context.args[0].lower() == "top":

        rows = db.execute("""
            SELECT
                user_id,
                total,
                streak
            FROM attendance
            WHERE chat_id=?
            ORDER BY total DESC, streak DESC
            LIMIT 20
        """, (
            chat_id,
        )).fetchall()

        if not rows:
            await update.message.reply_text(
                "📭 Chưa có ai điểm danh."
            )
            return

        lines = [
            "🏆 BẢNG XẾP HẠNG ĐIỂM DANH",
            ""
        ]

        for index, row in enumerate(rows, 1):

            user = await context.bot.get_chat_member(
                chat_id,
                row["user_id"],
            )

            name = user.user.full_name

            lines.append(
                f"{index}. {name} — "
                f"{row['total']} lần — "
                f"🔥 {row['streak']}"
            )

        await update.message.reply_text(
            "\n".join(lines)
        )

        return

    keyboard = [
        [
            InlineKeyboardButton(
                "🔥 ĐIỂM DANH",
                callback_data=(
                    f"attendance|{chat_id}"
                ),
            )
        ]
    ]

    await update.message.reply_text(
        "📢 ĐIỂM DANH HÔM NAY\n\n"
        "Bấm nút bên dưới để điểm danh.",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# ĐIỂM DANH CALLBACK
# ============================================================

async def attendance_callback(update, context):

    query = update.callback_query

    try:
        await query.answer()
    except Exception:
        pass

    if not query.message:
        return

    chat_id = query.message.chat.id
    user = query.from_user

    today = datetime.now(
        timezone.utc
    ).astimezone().strftime(
        "%Y-%m-%d"
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

        await query.answer(
            "Bạn đã điểm danh hôm nay rồi 😂",
            show_alert=True,
        )

        return

    if row:

        old_date = row["last_date"]

        try:

            old = datetime.strptime(
                old_date,
                "%Y-%m-%d",
            ).date()

            current = datetime.strptime(
                today,
                "%Y-%m-%d",
            ).date()

            if (current - old).days == 1:
                streak = row["streak"] + 1
            else:
                streak = 1

        except Exception:

            streak = 1

        total = row["total"] + 1

        db.execute("""
            UPDATE attendance
            SET
                last_date=?,
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

    try:

        await query.message.delete()

    except Exception:

        pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "🔥 ĐIỂM DANH THÀNH CÔNG!\n\n"
            f"👤 {user.full_name}\n"
            f"🔥 Chuỗi: {streak}\n"
            f"📅 Tổng số lần: {total}"
        ),
    )

# ============================================================
# GAME NỐI CHỮ
# ============================================================

async def gamenoichu(update, context):

    if not update.message:
        return

    if not is_group(update):
        await update.message.reply_text(
            "❌ Game chỉ chơi trong nhóm."
        )
        return

    chat_id = update.effective_chat.id

    if chat_id in games:
        await update.message.reply_text(
            "🎮 Nhóm đang có một game."
        )
        return

    games[chat_id] = {
        "phase": "join",
        "players": [],
        "current": None,
        "turn": 0,
        "started": False,
    }

    keyboard = [
        [
            InlineKeyboardButton(
                "🎮 THAM GIA",
                callback_data=f"wordgame|join|{chat_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ HỦY GAME",
                callback_data=f"wordgame|cancel|{chat_id}",
            )
        ],
    ]

    await update.message.reply_text(
        "🎮 GAME NỐI CHỮ\n\n"
        "Bấm nút để tham gia.\n"
        "⏰ Thời gian tham gia: 5 phút.\n"
        "👥 Có thể tham gia không giới hạn.",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )

    game_tasks[chat_id] = asyncio.create_task(
        wordgame_lobby_timer(
            chat_id,
            context,
        )
    )


async def wordgame_lobby_timer(chat_id, context):

    await asyncio.sleep(300)

    state = games.get(chat_id)

    if not state:
        return

    if state.get("phase") != "join":
        return

    players = state.get("players", [])

    if len(players) < 2:

        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ Game nối chữ bị hủy "
                    "vì chưa đủ người chơi."
                ),
            )
        except Exception:
            pass

        games.pop(chat_id, None)
        game_tasks.pop(chat_id, None)
        return

    state["phase"] = "playing"
    state["started"] = True
    state["turn"] = 0

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "🎮 GAME NỐI CHỮ BẮT ĐẦU!\n\n"
            f"👥 Người chơi: {len(players)}\n\n"
            "Bot sẽ đưa ra từ đầu tiên."
        ),
    )

    words = [
        "con mèo",
        "mặt trời",
        "học sinh",
        "trái cây",
        "bầu trời",
        "điện thoại",
        "cà phê",
        "Việt Nam",
    ]

    word = random.choice(words)

    state["current"] = word

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🔤 Từ hiện tại: **{word}**\n\n"
            "👉 Người chơi đầu tiên hãy nối "
            "bằng từ bắt đầu bằng chữ cuối."
        ),
        parse_mode="Markdown",
    )


async def wordgame_callback(update, context):

    query = update.callback_query

    try:
        await query.answer()
    except Exception:
        pass

    data = query.data.split("|")

    if len(data) < 3:
        return

    action = data[1]

    try:
        chat_id = int(data[2])
    except Exception:
        return

    state = games.get(chat_id)

    if not state:
        await query.answer(
            "Game không còn tồn tại.",
            show_alert=True,
        )
        return

    user = query.from_user

    if action == "join":

        if state["phase"] != "join":
            await query.answer(
                "Game đã bắt đầu.",
                show_alert=True,
            )
            return

        if any(
            p["id"] == user.id
            for p in state["players"]
        ):
            await query.answer(
                "Bạn đã tham gia rồi 😂",
                show_alert=True,
            )
            return

        state["players"].append({
            "id": user.id,
            "name": user.full_name,
        })

        names = []

        for i, player in enumerate(
            state["players"],
            1,
        ):
            names.append(
                f"{i}. {player['name']}"
            )

        text = (
            "🎮 GAME NỐI CHỮ\n\n"
            "Bấm nút để tham gia.\n"
            "⏰ Còn thời gian tham gia.\n\n"
            "👥 DANH SÁCH:\n"
            + "\n".join(names)
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "🎮 THAM GIA",
                    callback_data=(
                        f"wordgame|join|{chat_id}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ HỦY GAME",
                    callback_data=(
                        f"wordgame|cancel|{chat_id}"
                    ),
                )
            ],
        ]

        try:
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(
                    keyboard
                ),
            )
        except Exception:
            pass

        return

    if action == "cancel":

        if state["phase"] != "join":
            await query.answer(
                "Game đã bắt đầu.",
                show_alert=True,
            )
            return

        if not await user_is_admin(update, user.id):
            await query.answer(
                "❌ Chỉ admin mới được hủy.",
                show_alert=True,
            )
            return

        task = game_tasks.pop(
            chat_id,
            None,
        )

        if task:
            task.cancel()

        games.pop(
            chat_id,
            None,
        )

        try:
            await query.edit_message_text(
                "❌ Game nối chữ đã bị hủy."
            )
        except Exception:
            pass


async def gameoff(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    chat_id = update.effective_chat.id

    state = games.pop(
        chat_id,
        None,
    )

    task = game_tasks.pop(
        chat_id,
        None,
    )

    if task:
        try:
            task.cancel()
        except Exception:
            pass

    if state:
        await update.message.reply_text(
            "❌ Đã tắt game."
        )
    else:
        await update.message.reply_text(
            "❌ Nhóm hiện không có game."
        )


# ============================================================
# XỬ LÝ TỪ NỐI CHỮ
# ============================================================

async def wordgame_message(update, context):

    if not update.message:
        return False

    if not is_group(update):
        return False

    chat_id = update.effective_chat.id
    state = games.get(chat_id)

    if not state:
        return False

    if state.get("phase") != "playing":
        return False

    text = update.message.text

    if not text:
        return True

    user_id = update.effective_user.id

    players = state.get("players", [])

    if not any(
        p["id"] == user_id
        for p in players
    ):
        return True

    current_index = state.get(
        "turn",
        0,
    )

    if not players:
        return True

    current_player = players[
        current_index % len(players)
    ]

    if current_player["id"] != user_id:
        try:
            await update.message.delete()
        except Exception:
            pass

        return True

    current_word = (
        state.get("current")
        or ""
    ).strip()

    answer = text.strip()

    if not answer:
        return True

    if answer.lower() == current_word.lower():

        try:
            await update.message.delete()
        except Exception:
            pass

        return True

    last_char = current_word[-1].lower()

    first_char = answer[0].lower()

    if first_char != last_char:

        try:
            await update.message.reply_text(
                f"❌ Sai rồi!\n"
                f"Từ trước kết thúc bằng chữ "
                f"**{last_char}**.",
                parse_mode="Markdown",
            )
        except Exception:
            pass

        try:
            await update.message.delete()
        except Exception:
            pass

        return True

    state["current"] = answer

    state["turn"] = (
        current_index + 1
    )

    next_index = (
        state["turn"] % len(players)
    )

    next_player = players[next_index]

    try:
        await update.message.reply_text(
            f"✅ {answer}\n\n"
            f"👉 Lượt của "
            f"{next_player['name']}\n"
            f"Nối bằng chữ **{answer[-1]}**.",
            parse_mode="Markdown",
        )
    except Exception:
        pass

    return True

# ============================================================
# CAM - XÓA TIN NHẮN NGƯỜI ĐƯỢC ĐÁNH DẤU
# ============================================================

async def cam_command(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Hãy reply người cần CAM."
        )
        return

    db.execute("""
        INSERT OR IGNORE INTO cam_users(
            chat_id,
            user_id
        )
        VALUES (?, ?)
    """, (
        update.effective_chat.id,
        target.id,
    ))

    db.commit()

    await update.message.reply_text(
        f"🔴 Đã bật CAM cho {mention_user(target)}",
        parse_mode="HTML",
    )


# ============================================================
# CAM OFF
# ============================================================

async def camoff_command(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Hãy reply người cần tắt CAM."
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
        f"🟢 Đã tắt CAM cho {mention_user(target)}",
        parse_mode="HTML",
    )


# ============================================================
# ANTIFAKE
# ============================================================

async def antifake(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    target = await get_target_user(
        update,
        context,
    )

    if not target:
        await update.message.reply_text(
            "❌ Hãy reply người cần antifake."
        )
        return

    db.execute("""
        INSERT OR IGNORE INTO antifake_users(
            chat_id,
            user_id
        )
        VALUES (?, ?)
    """, (
        update.effective_chat.id,
        target.id,
    ))

    db.commit()

    await update.message.reply_text(
        f"🛡️ Đã thêm {mention_user(target)} "
        "vào danh sách bảo vệ.",
        parse_mode="HTML",
    )


# ============================================================
# AFK CHECK
# ============================================================

async def check_afk(update, context):

    if not update.message:
        return False

    if not update.message.reply_to_message:
        return False

    target = (
        update.message
        .reply_to_message
        .from_user
    )

    if not target:
        return False

    info = afk_users.get(
        target.id
    )

    if not info:
        return False

    elapsed = int(
        time.time() - info["time"]
    )

    minutes = elapsed // 60
    seconds = elapsed % 60

    await update.message.reply_text(
        f"💤 {mention_user(target)} đang AFK.\n"
        f"📝 Lý do: {info['reason']}\n"
        f"⏰ Đã AFK: {minutes} phút "
        f"{seconds} giây.",
        parse_mode="HTML",
    )

    return True


# ============================================================
# TỰ XÓA AFK KHI NGƯỜI DÙNG QUAY LẠI
# ============================================================

async def remove_afk(update, context):

    if not update.message:
        return

    user = update.effective_user

    if user.id not in afk_users:
        return

    info = afk_users.pop(
        user.id
    )

    elapsed = int(
        time.time() - info["time"]
    )

    minutes = elapsed // 60

    await update.message.reply_text(
        f"👋 {mention_user(user)} đã quay lại!\n"
        f"💤 AFK trong khoảng {minutes} phút.",
        parse_mode="HTML",
    )


# ============================================================
# LINK DETECTION
# ============================================================

LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|"
    r"discord\.gg/|discord\.com/invite/)",
    re.IGNORECASE,
)


async def handle_antilink(update, context):

    if not update.message:
        return False

    if not is_group(update):
        return False

    settings = get_settings(
        update.effective_chat.id
    )

    if not settings["antilink"]:
        return False

    text = (
        update.message.text
        or update.message.caption
        or ""
    )

    if not LINK_PATTERN.search(text):
        return False

    user = update.effective_user

    # Admin được phép gửi link
    if await user_is_admin(
        update,
        user.id,
    ):
        return False

    try:
        await update.message.delete()
    except Exception:
        pass

    try:
        warning = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"🚫 {mention_user(user)}, "
                "nhóm đang bật chống link."
            ),
            parse_mode="HTML",
        )

        await asyncio.sleep(3)

        await warning.delete()

    except Exception:
        pass

    return True


# ============================================================
# ANTISPAM
# ============================================================

async def handle_antispam(update, context):

    if not update.message:
        return False

    if not is_group(update):
        return False

    settings = get_settings(
        update.effective_chat.id
    )

    if not settings["antispam"]:
        return False

    user = update.effective_user

    if await user_is_admin(
        update,
        user.id,
    ):
        return False

    chat_id = update.effective_chat.id

    key = (
        chat_id,
        user.id,
    )

    now = time.time()

    cache = spam_cache[key]

    cache.append(now)

    # Xóa timestamp quá cũ
    while cache and now - cache[0] > 5:
        cache.popleft()

    # 5 tin trong 5 giây
    if len(cache) < 5:
        return False

    cache.clear()

    try:
        await update.message.delete()
    except Exception:
        pass

    try:

        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
            until_date=datetime.now(
                timezone.utc
            ) + timedelta(
                seconds=30
            ),
        )

        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚫 {mention_user(user)} "
                "đã spam quá nhiều.\n"
                "🔇 Bị mute 30 giây."
            ),
            parse_mode="HTML",
        )

        await asyncio.sleep(3)

        try:
            await msg.delete()
        except Exception:
            pass

    except Exception:
        pass

    return True


# ============================================================
# CAM CHECK
# ============================================================

async def handle_cam(update, context):

    if not update.message:
        return False

    if not is_group(update):
        return False

    user = update.effective_user

    row = db.execute("""
        SELECT 1
        FROM cam_users
        WHERE chat_id=? AND user_id=?
    """, (
        update.effective_chat.id,
        user.id,
    )).fetchone()

    if not row:
        return False

    # Admin không bị CAM
    if await user_is_admin(
        update,
        user.id,
    ):
        return False

    try:
        await update.message.delete()
    except Exception:
        pass

    return True


# ============================================================
# FILTER MESSAGE CHECK
# ============================================================

async def handle_filters(update, context):

    if not update.message:
        return False

    if not is_group(update):
        return False

    text = (
        update.message.text
        or ""
    ).strip().lower()

    if not text:
        return False

    rows = db.execute("""
        SELECT trigger, response
        FROM filters_data
        WHERE chat_id=?
    """, (
        update.effective_chat.id,
    )).fetchall()

    for row in rows:

        trigger = row["trigger"].lower()

        if trigger in text:

            await update.message.reply_text(
                row["response"]
            )

            return False

    return False


# ============================================================
# SAVE USER
# ============================================================

async def save_current_user(update, context):

    if not update.effective_user:
        return

    if not update.effective_chat:
        return

    save_user(
        update.effective_chat.id,
        update.effective_user,
    )

# ============================================================
# AFK COMMAND
# ============================================================

async def afk_command(update, context):

    if not update.message:
        return

    user = update.effective_user

    reason = "Không có lý do"

    if context.args:
        reason = " ".join(context.args)

    afk_users[user.id] = {
        "time": time.time(),
        "reason": reason,
    }

    await update.message.reply_text(
        f"💤 {mention_user(user)} đã AFK.\n"
        f"📝 Lý do: {reason}",
        parse_mode="HTML",
    )


# ============================================================
# SET ANTILINK
# ============================================================

async def antilink_command(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Dùng:\n"
            "/antilink on\n"
            "/antilink off"
        )
        return

    value = context.args[0].lower()

    if value not in ("on", "off"):
        await update.message.reply_text(
            "❌ Chỉ dùng on hoặc off."
        )
        return

    enabled = 1 if value == "on" else 0

    ensure_chat(
        update.effective_chat.id
    )

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
        "🔗 Antilink: "
        + ("BẬT ✅" if enabled else "TẮT ❌")
    )


# ============================================================
# SET ANTISPAM
# ============================================================

async def antispam_command(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Dùng:\n"
            "/antispam on\n"
            "/antispam off"
        )
        return

    value = context.args[0].lower()

    if value not in ("on", "off"):
        await update.message.reply_text(
            "❌ Chỉ dùng on hoặc off."
        )
        return

    enabled = 1 if value == "on" else 0

    ensure_chat(
        update.effective_chat.id
    )

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
        "🛡️ Antispam: "
        + ("BẬT ✅" if enabled else "TẮT ❌")
    )


# ============================================================
# SET WELCOME
# ============================================================

async def welcome_command(update, context):

    if not update.message:
        return

    if not await admin_required(update):
        return

    if not context.args:
        await update.message.reply_text(
            "Dùng:\n"
            "/welcome on\n"
            "/welcome off"
        )
        return

    value = context.args[0].lower()

    if value not in ("on", "off"):
        await update.message.reply_text(
            "❌ Chỉ dùng on hoặc off."
        )
        return

    enabled = 1 if value == "on" else 0

    ensure_chat(
        update.effective_chat.id
    )

    db.execute("""
        UPDATE settings
        SET welcome=?
        WHERE chat_id=?
    """, (
        enabled,
        update.effective_chat.id,
    ))

    db.commit()

    await update.message.reply_text(
        "👋 Welcome: "
        + ("BẬT ✅" if enabled else "TẮT ❌")
    )


# ============================================================
# NEW MEMBER WELCOME
# ============================================================

async def welcome_new_member(
    update,
    context
):

    if not update.message:
        return

    if not update.message.new_chat_members:
        return

    chat_id = update.effective_chat.id

    settings = get_settings(chat_id)

    if not settings["welcome"]:
        return

    for user in update.message.new_chat_members:

        if user.is_bot:
            continue

        save_user(
            chat_id,
            user,
        )

        await update.message.reply_text(
            f"👋 Chào mừng {mention_user(user)} "
            "đã tham gia nhóm!\n\n"
            "📌 Hãy đọc /rules để biết nội quy.",
            parse_mode="HTML",
        )


# ============================================================
# MEMBER LEFT
# ============================================================

async def member_left(
    update,
    context
):

    if not update.message:
        return

    if not update.message.left_chat_member:
        return

    user = update.message.left_chat_member

    if user.is_bot:
        return

    try:
        await update.message.delete()
    except Exception:
        pass


# ============================================================
# BOT ADDED TO GROUP
# ============================================================

async def bot_added(
    update,
    context
):

    if not update.my_chat_member:
        return

    new_status = (
        update.my_chat_member
        .new_chat_member
        .status
    )

    old_status = (
        update.my_chat_member
        .old_chat_member
        .status
    )

    if new_status not in (
        "member",
        "administrator",
    ):
        return

    if old_status in (
        "member",
        "administrator",
    ):
        return

    chat_id = update.effective_chat.id

    ensure_chat(chat_id)

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🤖 <b>DTN BOT đã tham gia nhóm!</b>\n\n"
                "📚 Dùng /help để xem toàn bộ lệnh.\n"
                "🛡️ Hãy cấp quyền quản trị cho bot "
                "nếu muốn sử dụng các chức năng quản lý."
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ============================================================
# DELETE SERVICE MESSAGE
# ============================================================

async def delete_service_message(
    update,
    context
):

    if not update.message:
        return

    # Những tin hệ thống Telegram
    if (
        update.message.new_chat_title
        or update.message.new_chat_photo
        or update.message.delete_chat_photo
        or update.message.group_chat_created
        or update.message.supergroup_chat_created
        or update.message.migrate_to_chat_id
        or update.message.migrate_from_chat_id
    ):
        try:
            await update.message.delete()
        except Exception:
            pass


# ============================================================
# GROUP MESSAGE LOGGER
# ============================================================

async def group_user_tracker(
    update,
    context
):

    if not update.message:
        return

    if not update.effective_user:
        return

    if not update.effective_chat:
        return

    if not is_group(update):
        return

    save_user(
        update.effective_chat.id,
        update.effective_user,
    )


# ============================================================
# WARN LIMIT CHECK
# ============================================================

async def check_warning_limit(
    update,
    context
):

    if not update.message:
        return False

    if not is_group(update):
        return False

    user = update.effective_user

    row = db.execute("""
        SELECT COUNT(*) AS total
        FROM warnings
        WHERE chat_id=? AND user_id=?
    """, (
        update.effective_chat.id,
        user.id,
    )).fetchone()

    total = row["total"]

    if total < 3:
        return False

    # Reset cảnh cáo sau khi xử lý
    db.execute("""
        DELETE FROM warnings
        WHERE chat_id=? AND user_id=?
    """, (
        update.effective_chat.id,
        user.id,
    ))

    db.commit()

    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
            until_date=datetime.now(
                timezone.utc
            ) + timedelta(
                minutes=5
            ),
        )

        msg = await update.message.reply_text(
            f"🔇 {mention_user(user)} "
            "đã nhận đủ 3 cảnh cáo.\n"
            "⏰ Bị mute 5 phút.",
            parse_mode="HTML",
        )

        await asyncio.sleep(4)

        try:
            await msg.delete()
        except Exception:
            pass

    except Exception:
        pass

    return False


# ============================================================
# CLEAN OLD SPAM CACHE
# ============================================================

async def cleanup_spam_cache():

    while True:

        try:

            now = time.time()

            remove_keys = []

            for key, values in spam_cache.items():

                while values and (
                    now - values[0] > 10
                ):
                    values.popleft()

                if not values:
                    remove_keys.append(key)

            for key in remove_keys:
                spam_cache.pop(
                    key,
                    None,
                )

        except Exception:
            pass

        await asyncio.sleep(30)


# ============================================================
# CLEAN OLD GAME DATA
# ============================================================

async def cleanup_game_data():

    while True:

        try:

            now = time.time()

            remove_games = []

            for chat_id, game in list(
                word_games.items()
            ):

                created = game.get(
                    "created",
                    now,
                )

                if now - created > 3600:
                    remove_games.append(chat_id)

            for chat_id in remove_games:
                word_games.pop(
                    chat_id,
                    None,
                )

        except Exception:
            pass

        await asyncio.sleep(60)

# ============================================================
# MA SÓI - CẤU TRÚC GAME
# ============================================================

werewolf_games = {}
werewolf_tasks = {}


ROLE_VILLAGER = "Dân làng"
ROLE_WOLF = "Sói"
ROLE_SEER = "Tiên tri"
ROLE_GUARD = "Bảo vệ"
ROLE_WITCH = "Phù thủy"
ROLE_HUNTER = "Thợ săn"
ROLE_ZOMBIE = "Zombie"


ROLE_DESCRIPTIONS = {
    ROLE_VILLAGER:
        "Bạn là Dân làng. "
        "Ban ngày hãy thảo luận và tìm Sói.",

    ROLE_WOLF:
        "Bạn là Sói. "
        "Ban đêm cùng phe Sói chọn một người để cắn.",

    ROLE_SEER:
        "Bạn là Tiên tri. "
        "Mỗi đêm kiểm tra một người để biết "
        "người đó có phải Sói hay không.",

    ROLE_GUARD:
        "Bạn là Bảo vệ. "
        "Mỗi đêm bảo vệ một người khỏi Sói. "
        "Đêm lẻ có thể tự bảo vệ, đêm chẵn không được "
        "tự bảo vệ.",

    ROLE_WITCH:
        "Bạn là Phù thủy. "
        "Mỗi đêm biết người bị Sói cắn. "
        "Bạn có 1 lần cứu và 1 lần độc.",

    ROLE_HUNTER:
        "Bạn là Thợ săn. "
        "Mỗi đêm chọn một người để bắn.",

    ROLE_ZOMBIE:
        "Bạn là Zombie. "
        "Mỗi đêm chọn một người để đánh dấu. "
        "Đủ 3 lần trên cùng một người thì người đó chết.",
}


# ============================================================
# BỘ ROLE THEO SỐ NGƯỜI
# ============================================================

WEREWOLF_ROLE_DECKS = {
    4: [
        ROLE_WOLF,
        ROLE_VILLAGER,
        ROLE_SEER,
        ROLE_GUARD,
    ],

    5: [
        ROLE_WOLF,
        ROLE_VILLAGER,
        ROLE_SEER,
        ROLE_GUARD,
        ROLE_WITCH,
    ],

    6: [
        ROLE_WOLF,
        ROLE_WOLF,
        ROLE_VILLAGER,
        ROLE_SEER,
        ROLE_GUARD,
        ROLE_WITCH,
    ],

    7: [
        ROLE_WOLF,
        ROLE_WOLF,
        ROLE_VILLAGER,
        ROLE_SEER,
        ROLE_GUARD,
        ROLE_WITCH,
        ROLE_HUNTER,
    ],

    8: [
        ROLE_WOLF,
        ROLE_WOLF,
        ROLE_VILLAGER,
        ROLE_SEER,
        ROLE_GUARD,
        ROLE_WITCH,
        ROLE_HUNTER,
        ROLE_ZOMBIE,
    ],

    9: [
        ROLE_WOLF,
        ROLE_WOLF,
        ROLE_VILLAGER,
        ROLE_VILLAGER,
        ROLE_SEER,
        ROLE_GUARD,
        ROLE_WITCH,
        ROLE_HUNTER,
        ROLE_ZOMBIE,
    ],
}


# ============================================================
# TẠO GAME MA SÓI
# ============================================================

def create_werewolf_game(chat_id):

    return {
        "chat_id": chat_id,

        "phase": "lobby",

        "players": {},

        "roles": {},

        "alive": set(),

        "dead": set(),

        "votes": {},

        "night": 0,

        "night_actions": {},

        "wolf_target": None,

        "guard_target": None,

        "witch_save": None,

        "witch_poison": None,

        "hunter_target": None,

        "zombie_targets": {},

        "zombie_marks": {},

        "watching": {},

        "role_messages": {},

        "join_message_id": None,

        "join_task": None,

        "night_task": None,

        "vote_message_id": None,

        "created": time.time(),
    }


# ============================================================
# KIỂM TRA GAME
# ============================================================

def get_werewolf_game(chat_id):

    return werewolf_games.get(chat_id)


def werewolf_has_game(chat_id):

    return chat_id in werewolf_games


# ============================================================
# LẤY ROLE
# ============================================================

def get_role(chat_id, user_id):

    game = werewolf_games.get(chat_id)

    if not game:
        return None

    return game["roles"].get(user_id)


# ============================================================
# NGƯỜI CÒN SỐNG
# ============================================================

def alive_players(game):

    return [
        user_id
        for user_id in game["players"]
        if user_id in game["alive"]
    ]


# ============================================================
# NGƯỜI ĐÃ CHẾT
# ============================================================

def dead_players(game):

    return [
        user_id
        for user_id in game["players"]
        if user_id in game["dead"]
    ]


# ============================================================
# TÌM USER
# ============================================================

def get_game_user(game, user_id):

    return game["players"].get(user_id)


# ============================================================
# FORMAT DANH SÁCH NGƯỜI CHƠI
# ============================================================

def werewolf_player_list(game):

    lines = []

    index = 1

    for user_id, user in game["players"].items():

        status = "🟢"

        if user_id in game["dead"]:
            status = "💀"

        name = (
            user.full_name
            or user.username
            or str(user_id)
        )

        lines.append(
            f"{status} {index}. {name}"
        )

        index += 1

    return "\n".join(lines)


# ============================================================
# BUTTON THAM GIA
# ============================================================

def werewolf_join_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🐺 Tham gia trò chơi",
                callback_data="ww_join",
            )
        ]
    ])


# ============================================================
# TẠO BUTTON CHỌN NGƯỜI
# ============================================================

def werewolf_target_keyboard(
    game,
    prefix,
    include_dead=False,
):

    buttons = []

    index = 1

    for user_id, user in game["players"].items():

        if not include_dead:
            if user_id not in game["alive"]:
                continue

        name = (
            user.first_name
            or user.username
            or str(user_id)
        )

        name = name[:20]

        buttons.append([
            InlineKeyboardButton(
                f"{index}. {name}",
                callback_data=f"{prefix}:{user_id}",
            )
        ])

        index += 1

    return InlineKeyboardMarkup(buttons)


# ============================================================
# KIỂM TRA THẮNG THUA
# ============================================================

def werewolf_winner(game):

    wolves = 0
    others = 0

    for user_id in game["alive"]:

        role = game["roles"].get(user_id)

        if role == ROLE_WOLF:
            wolves += 1
        else:
            others += 1

    if wolves == 0:
        return "village"

    if wolves >= others:
        return "wolves"

    return None


# ============================================================
# TẠO PHASE MESSAGE
# ============================================================

async def werewolf_announce(
    context,
    chat_id,
    text,
):

    try:
        return await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
        )
    except Exception:
        return None


# ============================================================
# KIỂM TRA BOT CÓ QUYỀN XÓA
# ============================================================

async def werewolf_bot_can_delete(
    update,
    context,
):

    try:

        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            context.bot.id,
        )

        return (
            member.status == "administrator"
            and bool(
                getattr(
                    member,
                    "can_delete_messages",
                    False,
                )
            )
        )

    except Exception:
        return False


# ============================================================
# KIỂM TRA BOT ADMIN
# ============================================================

async def werewolf_bot_is_admin(
    update,
    context,
):

    try:

        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            context.bot.id,
        )

        return member.status in (
            "administrator",
            "creator",
        )

    except Exception:
        return False


# ============================================================
# XÓA TASK CŨ
# ============================================================

def cancel_werewolf_task(chat_id):

    task = werewolf_tasks.pop(
        chat_id,
        None,
    )

    if task:

        try:
            task.cancel()
        except Exception:
            pass


# ============================================================
# HỦY GAME
# ============================================================

def delete_werewolf_game(chat_id):

    cancel_werewolf_task(chat_id)

    werewolf_games.pop(
        chat_id,
        None,
    )


# ============================================================
# KIỂM TRA USER ĐANG CHƠI
# ============================================================

def user_in_werewolf_game(
    chat_id,
    user_id,
):

    game = werewolf_games.get(chat_id)

    if not game:
        return False

    return user_id in game["players"]


# ============================================================
# KIỂM TRA USER CÒN SỐNG
# ============================================================

def user_alive_in_werewolf(
    chat_id,
    user_id,
):

    game = werewolf_games.get(chat_id)

    if not game:
        return False

    return user_id in game["alive"]


# ============================================================
# TẠO ROLE CARD
# ============================================================

def build_role_card(role):

    return (
        "🎴 <b>VAI TRÒ MA SÓI</b>\n\n"
        f"🐺 <b>Vai trò:</b> {role}\n\n"
        f"📖 <b>Nhiệm vụ:</b>\n"
        f"{ROLE_DESCRIPTIONS.get(role, '')}\n\n"
        "⚠️ Đây là vai trò bí mật. "
        "Không được cho người khác biết."
    )


# ============================================================
# LẤY DANH SÁCH SÓI
# ============================================================

def werewolf_users(game):

    return [
        user_id
        for user_id in game["alive"]
        if game["roles"].get(user_id) == ROLE_WOLF
    ]


# ============================================================
# LẤY NGƯỜI CÓ ROLE
# ============================================================

def users_with_role(
    game,
    role,
):

    return [
        user_id
        for user_id in game["alive"]
        if game["roles"].get(user_id) == role
    ]


# ============================================================
# RANDOM ROLE
# ============================================================

def assign_werewolf_roles(game):

    player_ids = list(
        game["players"].keys()
    )

    count = len(player_ids)

    deck = WEREWOLF_ROLE_DECKS.get(
        count
    )

    if not deck:
        return False

    deck = deck.copy()

    random.shuffle(deck)

    random.shuffle(player_ids)

    game["roles"] = {}

    for user_id, role in zip(
        player_ids,
        deck,
    ):
        game["roles"][user_id] = role

    game["alive"] = set(
        player_ids
    )

    game["dead"] = set()

    return True

# ============================================================
# MA SÓI - LỆNH /MASOI
# ============================================================

async def masoi_command(update, context):

    if not update.message:
        return

    if not is_group(update):
        await update.message.reply_text(
            "❌ Trò chơi Ma Sói chỉ chơi trong nhóm."
        )
        return

    chat_id = update.effective_chat.id

    # Đã có game
    if chat_id in werewolf_games:

        game = werewolf_games[chat_id]

        if game["phase"] == "lobby":
            await update.message.reply_text(
                "🐺 Trò chơi Ma Sói đang mở phòng!\n\n"
                f"👥 Người chơi hiện tại: "
                f"{len(game['players'])}/9\n\n"
                "Bấm nút bên dưới để tham gia."
                ,
                reply_markup=werewolf_join_keyboard(),
            )
            return

        await update.message.reply_text(
            "⚠️ Nhóm đang có một ván Ma Sói."
        )
        return

    # Bot phải là admin
    if not await werewolf_bot_is_admin(
        update,
        context,
    ):

        await update.message.reply_text(
            "❌ Bot phải là quản trị viên "
            "của nhóm để chơi Ma Sói."
        )
        return

    # Bot cần quyền xóa tin
    if not await werewolf_bot_can_delete(
        update,
        context,
    ):

        await update.message.reply_text(
            "❌ Bot cần quyền <b>Xóa tin nhắn</b> "
            "để điều khiển trò chơi.",
            parse_mode="HTML",
        )
        return

    game = create_werewolf_game(
        chat_id
    )

    werewolf_games[chat_id] = game

    text = (
        "🐺 <b>TRÒ CHƠI MA SÓI</b>\n\n"

        "📖 <b>Luật chơi:</b>\n"
        "• Có từ 4 đến 9 người chơi.\n"
        "• Mỗi người nhận một vai trò bí mật.\n"
        "• Ban đêm các vai trò đặc biệt hành động.\n"
        "• Ban ngày mọi người thảo luận và bỏ phiếu.\n"
        "• Dân làng phải tìm ra phe Sói.\n"
        "• Sói phải loại bỏ phe Dân.\n\n"

        "⏰ Thời gian tham gia: <b>3 phút</b>\n"
        "👥 Tối đa: <b>9 người</b>\n"
        "⚠️ Cần ít nhất <b>4 người</b> để bắt đầu.\n\n"

        "👇 <b>Bấm nút để tham gia!</b>"
    )

    msg = await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=werewolf_join_keyboard(),
    )

    game["join_message_id"] = msg.message_id

    task = asyncio.create_task(
        werewolf_lobby_timer(
            context,
            chat_id,
        )
    )

    game["join_task"] = task
    werewolf_tasks[chat_id] = task


# ============================================================
# THỜI GIAN CHỜ THAM GIA
# ============================================================

async def werewolf_lobby_timer(
    context,
    chat_id,
):

    try:

        await asyncio.sleep(180)

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

        if game["phase"] != "lobby":
            return

        count = len(
            game["players"]
        )

        if count < 4:

            await werewolf_announce(
                context,
                chat_id,
                (
                    "🐺 <b>MA SÓI ĐÃ HỦY</b>\n\n"
                    f"👥 Chỉ có {count} người tham gia.\n"
                    "❌ Cần ít nhất 4 người để bắt đầu."
                ),
            )

            delete_werewolf_game(
                chat_id
            )

            return

        await werewolf_start_game(
            context,
            chat_id,
        )

    except asyncio.CancelledError:
        return

    except Exception as e:

        print(
            "werewolf_lobby_timer error:",
            e,
        )


# ============================================================
# CALLBACK THAM GIA GAME
# ============================================================

async def werewolf_join_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    chat_id = query.message.chat.id

    user = query.from_user

    game = werewolf_games.get(
        chat_id
    )

    if not game:

        await query.answer(
            "❌ Ván chơi không còn tồn tại.",
            show_alert=True,
        )
        return

    if game["phase"] != "lobby":

        await query.answer(
            "⚠️ Đã hết thời gian tham gia.",
            show_alert=True,
        )
        return

    # Đã tham gia
    if user.id in game["players"]:

        await query.answer(
            "✅ Bạn đã tham gia rồi!",
            show_alert=True,
        )
        return

    # Tối đa 9 người
    if len(game["players"]) >= 9:

        await query.answer(
            "❌ Ván này đã đủ 9 người.",
            show_alert=True,
        )
        return

    # Lưu người chơi
    game["players"][user.id] = user

    save_user(
        chat_id,
        user,
    )

    count = len(
        game["players"]
    )

    text = (
        "🐺 <b>TRÒ CHƠI MA SÓI</b>\n\n"

        "📖 Thời gian tham gia: <b>3 phút</b>\n"
        f"👥 Người chơi: <b>{count}/9</b>\n\n"

        "<b>Danh sách người chơi:</b>\n"
        f"{werewolf_player_list(game)}\n\n"

        "👇 Bấm nút bên dưới để tham gia."
    )

    try:

        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=werewolf_join_keyboard(),
        )

    except Exception:
        pass

    await query.answer(
        f"✅ Đã tham gia! ({count}/9)"
    )


# ============================================================
# RỜI GAME TRONG LOBBY
# ============================================================

async def werewolf_leave_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    chat_id = query.message.chat.id

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    user_id = query.from_user.id

    if game["phase"] != "lobby":
        return

    if user_id not in game["players"]:

        await query.answer(
            "Bạn chưa tham gia.",
            show_alert=True,
        )
        return

    game["players"].pop(
        user_id,
        None,
    )

    count = len(
        game["players"]
    )

    text = (
        "🐺 <b>TRÒ CHƠI MA SÓI</b>\n\n"
        f"👥 Người chơi: <b>{count}/9</b>\n\n"
        "<b>Danh sách:</b>\n"
        f"{werewolf_player_list(game)}\n\n"
        "👇 Bấm nút để tham gia."
    )

    try:
        await query.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=werewolf_join_keyboard(),
        )
    except Exception:
        pass


# ============================================================
# HỦY GAME
# ============================================================

async def werewolf_cancel_command(
    update,
    context,
):

    if not update.message:
        return

    if not is_group(update):
        return

    chat_id = update.effective_chat.id

    game = werewolf_games.get(
        chat_id
    )

    if not game:

        await update.message.reply_text(
            "❌ Nhóm không có ván Ma Sói."
        )
        return

    if not await user_is_admin(
        update,
        update.effective_user.id,
    ):

        await update.message.reply_text(
            "❌ Chỉ quản trị viên mới có thể "
            "hủy ván Ma Sói."
        )
        return

    delete_werewolf_game(
        chat_id
    )

    await update.message.reply_text(
        "🛑 Đã hủy ván Ma Sói."
    )


# ============================================================
# KIỂM TRA USER CÓ THỂ BẮT ĐẦU GAME
# ============================================================

async def werewolf_preflight(
    context,
    game,
):

    failed = []

    for user_id, user in game["players"].items():

        try:

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🐺 <b>Kiểm tra kết nối Ma Sói</b>\n\n"
                    "Bạn đã sẵn sàng nhận vai trò."
                ),
                parse_mode="HTML",
            )

        except Exception:

            failed.append(
                user_id
            )

    return failed

# ============================================================
# MA SÓI - BẮT ĐẦU VÁN
# ============================================================

async def werewolf_start_game(
    context,
    chat_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["phase"] != "lobby":
        return

    player_count = len(
        game["players"]
    )

    if player_count < 4:

        await werewolf_announce(
            context,
            chat_id,
            (
                "❌ Không đủ người chơi.\n"
                f"Hiện có {player_count}/4 người."
            ),
        )

        delete_werewolf_game(
            chat_id
        )

        return

    if player_count > 9:

        await werewolf_announce(
            context,
            chat_id,
            "❌ Ván chơi tối đa 9 người.",
        )

        delete_werewolf_game(
            chat_id
        )

        return

    # Kiểm tra DM trước khi phát role
    failed = await werewolf_preflight(
        context,
        game,
    )

    if failed:

        names = []

        for user_id in failed:

            user = game["players"].get(
                user_id
            )

            if user:
                names.append(
                    user.full_name
                    or str(user_id)
                )

        await werewolf_announce(
            context,
            chat_id,
            (
                "❌ Không thể bắt đầu ván.\n\n"
                "Một số người chơi chưa mở chat "
                "với bot nên bot không thể gửi "
                "vai trò bí mật.\n\n"
                "👤 Người cần mở chat với bot:\n"
                + "\n".join(
                    f"• {name}"
                    for name in names
                )
            ),
        )

        delete_werewolf_game(
            chat_id
        )

        return

    # Phân vai
    if not assign_werewolf_roles(
        game
    ):

        await werewolf_announce(
            context,
            chat_id,
            "❌ Không thể phân vai.",
        )

        delete_werewolf_game(
            chat_id
        )

        return

    game["phase"] = "role"

    await werewolf_announce(
        context,
        chat_id,
        (
            "🎴 <b>ĐÃ CHIA VAI!</b>\n\n"
            f"👥 Có {player_count} người tham gia.\n\n"
            "📩 Bot đang gửi vai trò bí mật "
            "cho từng người chơi.\n"
            "⚠️ Kiểm tra tin nhắn riêng với bot."
        ),
    )

    await werewolf_send_role_cards(
        context,
        chat_id,
    )


# ============================================================
# GỬI ROLE CARD
# ============================================================

async def werewolf_send_role_cards(
    context,
    chat_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    for user_id in list(
        game["players"].keys()
    ):

        role = game["roles"].get(
            user_id
        )

        if not role:
            continue

        text = build_role_card(
            role
        )

        try:

            msg = await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="HTML",
            )

            game["role_messages"][
                user_id
            ] = msg.message_id

        except Exception as e:

            print(
                "send role card error:",
                e,
            )

    # Cho người chơi 1 phút xem role
    task = asyncio.create_task(
        werewolf_role_card_timer(
            context,
            chat_id,
        )
    )

    game["night_task"] = task

    werewolf_tasks[chat_id] = task


# ============================================================
# TỰ XÓA ROLE CARD SAU 1 PHÚT
# ============================================================

async def werewolf_role_card_timer(
    context,
    chat_id,
):

    try:

        await asyncio.sleep(60)

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

        for user_id, message_id in list(
            game["role_messages"].items()
        ):

            try:

                await context.bot.delete_message(
                    chat_id=user_id,
                    message_id=message_id,
                )

            except Exception:
                pass

        game["role_messages"].clear()

        await werewolf_announce(
            context,
            chat_id,
            (
                "🌙 <b>ĐÊM ĐÃ XUỐNG</b>\n\n"
                "Mọi người hãy nhắm mắt.\n"
                "🤫 Không được nói chuyện.\n\n"
                "🐺 Các vai trò ban đêm "
                "sẽ lần lượt được gọi."
            ),
        )

        await asyncio.sleep(2)

        await werewolf_start_night(
            context,
            chat_id,
        )

    except asyncio.CancelledError:
        return

    except Exception as e:

        print(
            "role card timer error:",
            e,
        )


# ============================================================
# KHỞI TẠO ĐÊM
# ============================================================

def reset_night_actions(game):

    game["night_actions"] = {}

    game["wolf_target"] = None

    game["guard_target"] = None

    game["witch_save"] = None

    game["witch_poison"] = None

    game["hunter_target"] = None

    game["zombie_targets"] = {}


# ============================================================
# BẮT ĐẦU ĐÊM
# ============================================================

async def werewolf_start_night(
    context,
    chat_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    game["phase"] = "night"

    game["night"] += 1

    reset_night_actions(
        game
    )

    night = game["night"]

    await werewolf_announce(
        context,
        chat_id,
        (
            f"🌙 <b>ĐÊM {night}</b>\n\n"
            "🤫 Tất cả người chơi im lặng.\n"
            "📩 Bot sẽ gọi từng vai trò."
        ),
    )

    await asyncio.sleep(2)

    await werewolf_run_night_roles(
        context,
        chat_id,
    )


# ============================================================
# KIỂM TRA ROLE CÓ HÀNH ĐỘNG BAN ĐÊM
# ============================================================

def night_roles():

    return [
        ROLE_WOLF,
        ROLE_SEER,
        ROLE_GUARD,
        ROLE_WITCH,
        ROLE_HUNTER,
        ROLE_ZOMBIE,
    ]


# ============================================================
# CHẠY TỪNG ROLE BAN ĐÊM
# ============================================================

async def werewolf_run_night_roles(
    context,
    chat_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["phase"] != "night":
        return

    # Sói
    wolves = users_with_role(
        game,
        ROLE_WOLF,
    )

    if wolves:

        await werewolf_wolf_action(
            context,
            chat_id,
        )

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

    # Tiên tri
    seers = users_with_role(
        game,
        ROLE_SEER,
    )

    if seers:

        await werewolf_seer_action(
            context,
            chat_id,
            seers[0],
        )

    # Bảo vệ
    guards = users_with_role(
        game,
        ROLE_GUARD,
    )

    if guards:

        await werewolf_guard_action(
            context,
            chat_id,
            guards[0],
        )

    # Phù thủy
    witches = users_with_role(
        game,
        ROLE_WITCH,
    )

    if witches:

        await werewolf_witch_action(
            context,
            chat_id,
            witches[0],
        )

    # Thợ săn
    hunters = users_with_role(
        game,
        ROLE_HUNTER,
    )

    if hunters:

        await werewolf_hunter_action(
            context,
            chat_id,
            hunters[0],
        )

    # Zombie
    zombies = users_with_role(
        game,
        ROLE_ZOMBIE,
    )

    if zombies:

        await werewolf_zombie_action(
            context,
            chat_id,
            zombies[0],
        )

    # Sau khi tất cả role xong
    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    await werewolf_resolve_night(
        context,
        chat_id,
    )


# ============================================================
# HÀM CHỜ HÀNH ĐỘNG
# ============================================================

async def werewolf_wait_for_action(
    context,
    chat_id,
    user_id,
    seconds=60,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return None

    game["night_actions"][
        user_id
    ] = {
        "done": False,
        "target": None,
    }

    started = time.time()

    while time.time() - started < seconds:

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return None

        action = game[
            "night_actions"
        ].get(user_id)

        if action and action.get(
            "done"
        ):
            return action.get(
                "target"
            )

        await asyncio.sleep(1)

    action = game[
        "night_actions"
    ].get(user_id)

    if action:
        action["done"] = True
        action["target"] = None

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "⏰ Hết 1 phút.\n"
                "😂 Bạn suy nghĩ hơi lâu nên "
                "lượt này bị bỏ qua."
            ),
        )

    except Exception:
        pass

    return None


# ============================================================
# HÀM GHI NHẬN TARGET
# ============================================================

def set_night_action(
    game,
    user_id,
    target_id,
):

    action = game[
        "night_actions"
    ].get(user_id)

    if not action:
        return False

    action["target"] = target_id
    action["done"] = True

    return True

# ============================================================
# MA SÓI - HÀNH ĐỘNG CỦA SÓI
# ============================================================

async def werewolf_wolf_action(
    context,
    chat_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    wolves = users_with_role(
        game,
        ROLE_WOLF,
    )

    if not wolves:
        return

    # Tạo danh sách mục tiêu
    keyboard = werewolf_target_keyboard(
        game,
        "ww_wolf",
    )

    text = (
        "🐺 <b>SÓI THỨC DẬY</b>\n\n"
        "Các Sói hãy chọn người muốn cắn.\n"
        "⏰ Bạn có 1 phút để lựa chọn."
    )

    # Gửi cho từng Sói
    for wolf_id in wolves:

        try:

            await context.bot.send_message(
                chat_id=wolf_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

        except Exception as e:

            print(
                "wolf dm error:",
                e,
            )

    # Chờ Sói
    # Nếu có nhiều Sói, chỉ cần một lựa chọn
    chosen = None

    started = time.time()

    while time.time() - started < 60:

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

        target = game.get(
            "wolf_target"
        )

        if target is not None:

            chosen = target
            break

        await asyncio.sleep(1)

    if chosen is None:

        try:

            for wolf_id in wolves:

                await context.bot.send_message(
                    chat_id=wolf_id,
                    text=(
                        "⏰ Hết giờ!\n"
                        "😂 Sói suy nghĩ hơi lâu nên "
                        "đêm nay không cắn ai."
                    ),
                )

        except Exception:
            pass

    else:

        game["wolf_target"] = chosen

        target_user = game["players"].get(
            chosen
        )

        if target_user:

            for wolf_id in wolves:

                try:

                    await context.bot.send_message(
                        chat_id=wolf_id,
                        text=(
                            "🐺 Đã chọn mục tiêu:\n"
                            f"🎯 {target_user.full_name}"
                        ),
                    )

                except Exception:
                    pass


# ============================================================
# TIÊN TRI
# ============================================================

async def werewolf_seer_action(
    context,
    chat_id,
    seer_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if seer_id not in game["alive"]:
        return

    keyboard = werewolf_target_keyboard(
        game,
        "ww_seer",
    )

    try:

        await context.bot.send_message(
            chat_id=seer_id,
            text=(
                "🔮 <b>TIÊN TRI THỨC DẬY</b>\n\n"
                "Chọn một người để kiểm tra.\n"
                "⏰ Bạn có 1 phút."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    except Exception:
        return

    game["night_actions"][
        seer_id
    ] = {
        "done": False,
        "target": None,
    }

    started = time.time()

    while time.time() - started < 60:

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

        action = game[
            "night_actions"
        ].get(seer_id)

        if action and action.get(
            "done"
        ):

            target = action.get(
                "target"
            )

            if target is None:
                return

            target_role = game[
                "roles"
            ].get(target)

            is_wolf = (
                target_role == ROLE_WOLF
            )

            target_user = game[
                "players"
            ].get(target)

            name = (
                target_user.full_name
                if target_user
                else str(target)
            )

            result = (
                "🐺 CÓ, người này là Sói."
                if is_wolf
                else "🙂 KHÔNG, người này không phải Sói."
            )

            try:

                await context.bot.send_message(
                    chat_id=seer_id,
                    text=(
                        "🔮 <b>KẾT QUẢ TIÊN TRI</b>\n\n"
                        f"👤 {name}\n"
                        f"➡️ {result}"
                    ),
                    parse_mode="HTML",
                )

            except Exception:
                pass

            return

        await asyncio.sleep(1)

    try:

        await context.bot.send_message(
            chat_id=seer_id,
            text=(
                "⏰ Hết 1 phút.\n"
                "😂 Tiên tri suy nghĩ hơi lâu "
                "nên lượt này bỏ qua."
            ),
        )

    except Exception:
        pass


# ============================================================
# CALLBACK SÓI
# ============================================================

async def werewolf_wolf_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    # Tìm game mà user đang tham gia
    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:

        await query.answer(
            "❌ Bạn không ở trong ván Ma Sói.",
            show_alert=True,
        )
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["phase"] != "night":

        await query.answer(
            "❌ Hiện không phải lượt ban đêm.",
            show_alert=True,
        )
        return

    if game["roles"].get(user_id) != ROLE_WOLF:

        await query.answer(
            "❌ Bạn không phải Sói.",
            show_alert=True,
        )
        return

    try:

        target_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "❌ Mục tiêu không hợp lệ.",
            show_alert=True,
        )
        return

    if target_id not in game["alive"]:

        await query.answer(
            "❌ Người này đã chết.",
            show_alert=True,
        )
        return

    if game["roles"].get(
        target_id
    ) == ROLE_WOLF:

        await query.answer(
            "❌ Sói không được cắn Sói.",
            show_alert=True,
        )
        return

    game["wolf_target"] = target_id

    target_user = game["players"].get(
        target_id
    )

    target_name = (
        target_user.full_name
        if target_user
        else str(target_id)
    )

    try:

        await query.edit_message_text(
            (
                "🐺 <b>ĐÃ CHỌN MỤC TIÊU</b>\n\n"
                f"🎯 {target_name}\n\n"
                "Hãy chờ các Sói khác."
            ),
            parse_mode="HTML",
        )

    except Exception:
        pass


# ============================================================
# CALLBACK TIÊN TRI
# ============================================================

async def werewolf_seer_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["roles"].get(user_id) != ROLE_SEER:

        await query.answer(
            "❌ Bạn không phải Tiên tri.",
            show_alert=True,
        )
        return

    try:

        target_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "❌ Mục tiêu không hợp lệ.",
            show_alert=True,
        )
        return

    if target_id not in game["alive"]:

        await query.answer(
            "❌ Người này đã chết.",
            show_alert=True,
        )
        return

    set_night_action(
        game,
        user_id,
        target_id,
    )

    try:

        await query.edit_message_text(
            "🔮 Đã ghi nhận lựa chọn của bạn.",
        )

    except Exception:
        pass


# ============================================================
# KIỂM TRA GAME SAU HÀNH ĐỘNG
# ============================================================

async def werewolf_check_game_after_action(
    context,
    chat_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return True

    winner = werewolf_winner(
        game
    )

    if not winner:
        return False

    await werewolf_end_game(
        context,
        chat_id,
        winner,
    )

    return True

# ============================================================
# MA SÓI - BẢO VỆ
# ============================================================

async def werewolf_guard_action(
    context,
    chat_id,
    guard_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if guard_id not in game["alive"]:
        return

    keyboard = werewolf_target_keyboard(
        game,
        "ww_guard",
    )

    night = game["night"]

    # Đêm lẻ được tự bảo vệ
    allow_self = (
        night % 2 == 1
    )

    text = (
        "🛡️ <b>BẢO VỆ THỨC DẬY</b>\n\n"
        "Chọn một người để bảo vệ.\n"
    )

    if allow_self:
        text += (
            "✅ Đêm này bạn được phép tự bảo vệ.\n"
        )
    else:
        text += (
            "❌ Đêm này bạn không được tự bảo vệ.\n"
        )

    text += "⏰ Bạn có 1 phút."

    try:

        await context.bot.send_message(
            chat_id=guard_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    except Exception:
        return

    game["night_actions"][
        guard_id
    ] = {
        "done": False,
        "target": None,
    }

    started = time.time()

    while time.time() - started < 60:

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

        action = game[
            "night_actions"
        ].get(guard_id)

        if action and action.get("done"):

            target = action.get(
                "target"
            )

            if target is not None:
                game["guard_target"] = target

            return

        await asyncio.sleep(1)

    try:

        await context.bot.send_message(
            chat_id=guard_id,
            text=(
                "⏰ Hết 1 phút.\n"
                "😂 Bảo vệ suy nghĩ hơi lâu "
                "nên lượt này bỏ qua."
            ),
        )

    except Exception:
        pass


# ============================================================
# CALLBACK BẢO VỆ
# ============================================================

async def werewolf_guard_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["phase"] != "night":

        await query.answer(
            "❌ Không phải ban đêm.",
            show_alert=True,
        )
        return

    if game["roles"].get(
        user_id
    ) != ROLE_GUARD:

        await query.answer(
            "❌ Bạn không phải Bảo vệ.",
            show_alert=True,
        )
        return

    try:

        target_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "❌ Mục tiêu không hợp lệ.",
            show_alert=True,
        )
        return

    if target_id not in game["alive"]:

        await query.answer(
            "❌ Người này đã chết.",
            show_alert=True,
        )
        return

    # Kiểm tra tự bảo vệ
    if target_id == user_id:

        if game["night"] % 2 == 0:

            await query.answer(
                "❌ Đêm chẵn không được tự bảo vệ.",
                show_alert=True,
            )
            return

    game["guard_target"] = target_id

    set_night_action(
        game,
        user_id,
        target_id,
    )

    try:

        await query.edit_message_text(
            "🛡️ Đã ghi nhận người được bảo vệ.",
        )

    except Exception:
        pass


# ============================================================
# PHÙ THỦY
# ============================================================

async def werewolf_witch_action(
    context,
    chat_id,
    witch_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if witch_id not in game["alive"]:
        return

    bitten = game.get(
        "wolf_target"
    )

    bitten_user = None

    if bitten is not None:
        bitten_user = game[
            "players"
        ].get(bitten)

    text = (
        "🧙 <b>PHÙ THỦY THỨC DẬY</b>\n\n"
    )

    if bitten_user:

        text += (
            f"🐺 Sói đã cắn: "
            f"<b>{bitten_user.full_name}</b>\n\n"
        )

    else:

        text += (
            "🐺 Đêm nay Sói không chọn ai.\n\n"
        )

    text += (
        "❤️ Bạn có thể dùng bình cứu 1 lần.\n"
        "☠️ Bạn cũng có thể dùng độc 1 lần.\n\n"
        "⏰ Bạn có 1 phút."
    )

    buttons = []

    # Cứu
    if (
        bitten is not None
        and not game.get(
            "witch_save_used",
            False,
        )
    ):

        buttons.append([
            InlineKeyboardButton(
                "❤️ CỨU",
                callback_data="ww_witch_save",
            )
        ])

    # Bỏ qua cứu
    buttons.append([
        InlineKeyboardButton(
            "➡️ KHÔNG CỨU",
            callback_data="ww_witch_no_save",
        )
    ])

    # Độc
    if not game.get(
        "witch_poison_used",
        False,
    ):

        buttons.append([
            InlineKeyboardButton(
                "☠️ DÙNG ĐỘC",
                callback_data="ww_witch_poison_menu",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⏭️ BỎ QUA",
            callback_data="ww_witch_skip",
        )
    ])

    keyboard = InlineKeyboardMarkup(
        buttons
    )

    try:

        await context.bot.send_message(
            chat_id=witch_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    except Exception:
        return

    game["witch_action"] = {
        "done": False,
        "save": None,
        "poison": None,
    }

    started = time.time()

    while time.time() - started < 60:

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

        action = game.get(
            "witch_action"
        )

        if action and action.get(
            "done"
        ):

            game["witch_save"] = action.get(
                "save"
            )

            game["witch_poison"] = action.get(
                "poison"
            )

            return

        await asyncio.sleep(1)

    try:

        await context.bot.send_message(
            chat_id=witch_id,
            text=(
                "⏰ Hết 1 phút.\n"
                "😂 Phù thủy suy nghĩ hơi lâu "
                "nên lượt này bỏ qua."
            ),
        )

    except Exception:
        pass


# ============================================================
# CALLBACK PHÙ THỦY - CỨU
# ============================================================

async def werewolf_witch_save_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["roles"].get(
        user_id
    ) != ROLE_WITCH:

        await query.answer(
            "❌ Bạn không phải Phù thủy.",
            show_alert=True,
        )
        return

    if game.get(
        "witch_save_used",
        False,
    ):

        await query.answer(
            "❌ Bạn đã dùng bình cứu rồi.",
            show_alert=True,
        )
        return

    bitten = game.get(
        "wolf_target"
    )

    if bitten is None:

        await query.answer(
            "❌ Đêm nay không có ai bị cắn.",
            show_alert=True,
        )
        return

    # Đánh dấu đã dùng bình
    game["witch_save_used"] = True

    action = game.get(
        "witch_action"
    )

    if not action:
        return

    action["save"] = bitten
    action["done"] = True

    try:

        await query.edit_message_text(
            "❤️ Đã dùng bình cứu.",
        )

    except Exception:
        pass


# ============================================================
# PHÙ THỦY KHÔNG CỨU
# ============================================================

async def werewolf_witch_no_save_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["roles"].get(
        user_id
    ) != ROLE_WITCH:
        return

    action = game.get(
        "witch_action"
    )

    if not action:
        return

    action["save"] = None

    # Nếu chưa chọn độc thì vẫn hoàn tất lượt
    action["done"] = True

    try:

        await query.edit_message_text(
            "➡️ Bạn không dùng bình cứu.",
        )

    except Exception:
        pass


# ============================================================
# PHÙ THỦY BỎ QUA
# ============================================================

async def werewolf_witch_skip_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["roles"].get(
        user_id
    ) != ROLE_WITCH:
        return

    action = game.get(
        "witch_action"
    )

    if not action:
        return

    action["save"] = None
    action["poison"] = None
    action["done"] = True

    try:

        await query.edit_message_text(
            "⏭️ Phù thủy bỏ qua lượt.",
        )

    except Exception:
        pass

# ============================================================
# MA SÓI - PHÙ THỦY DÙNG ĐỘC
# ============================================================

async def werewolf_witch_poison_menu(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["roles"].get(
        user_id
    ) != ROLE_WITCH:

        await query.answer(
            "❌ Bạn không phải Phù thủy.",
            show_alert=True,
        )
        return

    if game.get(
        "witch_poison_used",
        False,
    ):

        await query.answer(
            "❌ Bạn đã dùng thuốc độc.",
            show_alert=True,
        )
        return

    keyboard = werewolf_target_keyboard(
        game,
        "ww_poison",
    )

    try:

        await query.edit_message_text(
            (
                "☠️ <b>THUỐC ĐỘC</b>\n\n"
                "Chọn một người để sử dụng thuốc độc.\n"
                "⏰ Lựa chọn của bạn sẽ được ghi nhận."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    except Exception:
        pass


# ============================================================
# CALLBACK DÙNG ĐỘC
# ============================================================

async def werewolf_witch_poison_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["roles"].get(
        user_id
    ) != ROLE_WITCH:

        await query.answer(
            "❌ Bạn không phải Phù thủy.",
            show_alert=True,
        )
        return

    if game.get(
        "witch_poison_used",
        False,
    ):

        await query.answer(
            "❌ Thuốc độc đã được sử dụng.",
            show_alert=True,
        )
        return

    try:

        target_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "❌ Mục tiêu không hợp lệ.",
            show_alert=True,
        )
        return

    if target_id not in game["alive"]:

        await query.answer(
            "❌ Người này đã chết.",
            show_alert=True,
        )
        return

    if target_id == user_id:

        await query.answer(
            "❌ Không thể dùng độc lên chính mình.",
            show_alert=True,
        )
        return

    game["witch_poison_used"] = True

    action = game.get(
        "witch_action"
    )

    if not action:
        return

    action["poison"] = target_id
    action["done"] = True

    target_user = game["players"].get(
        target_id
    )

    name = (
        target_user.full_name
        if target_user
        else str(target_id)
    )

    try:

        await query.edit_message_text(
            f"☠️ Đã dùng thuốc độc lên <b>{name}</b>.",
            parse_mode="HTML",
        )

    except Exception:
        pass


# ============================================================
# MA SÓI - THỢ SĂN
# ============================================================

async def werewolf_hunter_action(
    context,
    chat_id,
    hunter_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if hunter_id not in game["alive"]:
        return

    keyboard = werewolf_target_keyboard(
        game,
        "ww_hunter",
    )

    try:

        await context.bot.send_message(
            chat_id=hunter_id,
            text=(
                "🏹 <b>THỢ SĂN THỨC DẬY</b>\n\n"
                "Chọn một người để bắn.\n"
                "⏰ Bạn có 1 phút."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    except Exception:
        return

    game["night_actions"][
        hunter_id
    ] = {
        "done": False,
        "target": None,
    }

    started = time.time()

    while time.time() - started < 60:

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

        action = game[
            "night_actions"
        ].get(hunter_id)

        if action and action.get(
            "done"
        ):

            target = action.get(
                "target"
            )

            if target is not None:
                game["hunter_target"] = target

            return

        await asyncio.sleep(1)

    try:

        await context.bot.send_message(
            chat_id=hunter_id,
            text=(
                "⏰ Hết 1 phút.\n"
                "😂 Thợ săn ngắm hơi lâu nên "
                "đêm nay không bắn."
            ),
        )

    except Exception:
        pass


# ============================================================
# CALLBACK THỢ SĂN
# ============================================================

async def werewolf_hunter_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["roles"].get(
        user_id
    ) != ROLE_HUNTER:

        await query.answer(
            "❌ Bạn không phải Thợ săn.",
            show_alert=True,
        )
        return

    try:

        target_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "❌ Mục tiêu không hợp lệ.",
            show_alert=True,
        )
        return

    if target_id not in game["alive"]:

        await query.answer(
            "❌ Người này đã chết.",
            show_alert=True,
        )
        return

    if target_id == user_id:

        await query.answer(
            "❌ Không thể tự bắn mình.",
            show_alert=True,
        )
        return

    game["hunter_target"] = target_id

    set_night_action(
        game,
        user_id,
        target_id,
    )

    target_user = game["players"].get(
        target_id
    )

    name = (
        target_user.full_name
        if target_user
        else str(target_id)
    )

    try:

        await query.edit_message_text(
            f"🏹 Đã chọn mục tiêu: <b>{name}</b>",
            parse_mode="HTML",
        )

    except Exception:
        pass


# ============================================================
# MA SÓI - ZOMBIE
# ============================================================

async def werewolf_zombie_action(
    context,
    chat_id,
    zombie_id,
):

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if zombie_id not in game["alive"]:
        return

    keyboard = werewolf_target_keyboard(
        game,
        "ww_zombie",
    )

    try:

        await context.bot.send_message(
            chat_id=zombie_id,
            text=(
                "🧟 <b>ZOMBIE THỨC DẬY</b>\n\n"
                "Chọn một người để ăn não.\n"
                "🎯 Nếu cùng một người bị đánh dấu "
                "3 lần, người đó sẽ chết.\n\n"
                "⏰ Bạn có 1 phút."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    except Exception:
        return

    game["night_actions"][
        zombie_id
    ] = {
        "done": False,
        "target": None,
    }

    started = time.time()

    while time.time() - started < 60:

        game = werewolf_games.get(
            chat_id
        )

        if not game:
            return

        action = game[
            "night_actions"
        ].get(zombie_id)

        if action and action.get(
            "done"
        ):

            target = action.get(
                "target"
            )

            if target is not None:

                game[
                    "zombie_targets"
                ][zombie_id] = target

                old_marks = game[
                    "zombie_marks"
                ].get(
                    target,
                    0,
                )

                game[
                    "zombie_marks"
                ][target] = old_marks + 1

            return

        await asyncio.sleep(1)

    try:

        await context.bot.send_message(
            chat_id=zombie_id,
            text=(
                "⏰ Hết 1 phút.\n"
                "😂 Zombie suy nghĩ hơi lâu "
                "nên đêm nay không ăn não."
            ),
        )

    except Exception:
        pass


# ============================================================
# CALLBACK ZOMBIE
# ============================================================

async def werewolf_zombie_callback(
    update,
    context,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    chat_id = None

    for cid, game in werewolf_games.items():

        if user_id in game["players"]:
            chat_id = cid
            break

    if chat_id is None:
        return

    game = werewolf_games.get(
        chat_id
    )

    if not game:
        return

    if game["roles"].get(
        user_id
    ) != ROLE_ZOMBIE:

        await query.answer(
            "❌ Bạn không phải Zombie.",
            show_alert=True,
        )
        return

    try:

        target_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "❌ Mục tiêu không hợp lệ.",
            show_alert=True,
        )
        return

    if target_id not in game["alive"]:

        await query.answer(
            "❌ Người này đã chết.",
            show_alert=True,
        )
        return

    if target_id == user_id:

        await query.answer(
            "❌ Không thể tự ăn não mình.",
            show_alert=True,
        )
        return

    set_night_action(
        game,
        user_id,
        target_id,
    )

    game[
        "zombie_targets"
    ][user_id] = target_id

    target_user = game["players"].get(
        target_id
    )

    name = (
        target_user.full_name
        if target_user
        else str(target_id)
    )

    try:

        await query.edit_message_text(
            (
                f"🧟 Đã đánh dấu "
                f"<b>{name}</b>."
            ),
            parse_mode="HTML",
        )

    except Exception:
        pass

# =========================
# PHẦN 14/20 — MA SÓI
# XỬ LÝ BAN ĐÊM + NGƯỜI CHẾT + BUỔI SÁNG
# =========================

async def werewolf_resolve_night(game):
    chat_id = game["chat_id"]

    alive = game["alive"]
    roles = game["roles"]
    actions = game["night_actions"]

    deaths = set()

    # -------------------------
    # 1. XỬ LÝ SÓI CẮN
    # -------------------------
    wolf_target = actions.get("wolf_target")

    protected = actions.get("guard_target")
    saved = actions.get("witch_saved")

    if wolf_target:
        if wolf_target not in protected and wolf_target not in saved:
            deaths.add(wolf_target)

    # -------------------------
    # 2. THUỐC ĐỘC PHÙ THỦY
    # -------------------------
    poison_target = actions.get("witch_poison")

    if poison_target:
        if poison_target in alive:
            deaths.add(poison_target)

    # -------------------------
    # 3. THỢ SĂN
    # -------------------------
    hunter_target = actions.get("hunter_target")

    if hunter_target:
        if hunter_target in alive:
            deaths.add(hunter_target)

    # -------------------------
    # 4. ZOMBIE
    # -------------------------
    zombie_target = actions.get("zombie_target")

    if zombie_target and zombie_target in alive:
        marks = game["zombie_marks"]

        marks[zombie_target] = marks.get(zombie_target, 0) + 1

        if marks[zombie_target] >= 3:
            deaths.add(zombie_target)

    # -------------------------
    # 5. XÓA NGƯỜI CHẾT KHỎI ALIVE
    # -------------------------
    for uid in deaths:
        if uid in alive:
            alive.remove(uid)

    # -------------------------
    # 6. LƯU DANH SÁCH NGƯỜI CHẾT
    # -------------------------
    game["dead"].update(deaths)

    # -------------------------
    # 7. GỬI THÔNG BÁO BUỔI SÁNG
    # -------------------------
    if not deaths:
        await context_bot_send(
            game,
            "🌅 *TRỜI SÁNG!*\n\n"
            "Đêm qua không có ai bị loại. 😮"
        )
    else:
        lines = [
            "🌅 *TRỜI SÁNG!*",
            "",
            "Đêm qua đã có người bị loại:"
        ]

        for uid in deaths:
            name = display_user(uid)
            role = roles.get(uid, "Không rõ")

            lines.append(
                f"💀 {name} — *{role}*"
            )

        await context_bot_send(
            game,
            "\n".join(lines)
        )

    # -------------------------
    # 8. KIỂM TRA THẮNG THUA
    # -------------------------
    winner = werewolf_check_winner(game)

    if winner:
        await werewolf_finish_game(game, winner)
        return

    # -------------------------
    # 9. NGƯỜI CHẾT CHỌN XEM / RỜI
    # -------------------------
    game["phase"] = "dead_choice"
    game["dead_choices"] = {}

    if deaths:
        await werewolf_dead_choice(game)
    else:
        await werewolf_start_vote(game)


async def context_bot_send(game, text):
    """
    Gửi tin nhắn vào group.
    Hàm này dùng context.bot được lưu trong game.
    """
    bot = game.get("bot")

    if bot:
        try:
            await bot.send_message(
                chat_id=game["chat_id"],
                text=text,
                parse_mode="Markdown"
            )
        except Exception:
            try:
                await bot.send_message(
                    chat_id=game["chat_id"],
                    text=text
                )
            except Exception:
                pass


async def werewolf_dead_choice(game):
    """
    Người chết được chọn:
    👁 Xem tiếp
    🚪 Rời trò chơi
    """

    bot = game.get("bot")

    if not bot:
        return

    dead_players = list(game["dead"])

    for uid in dead_players:

        # Chỉ gửi cho người vừa chết / đang tham gia game
        try:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "👁 Xem tiếp",
                        callback_data=f"ww_watch:{game['chat_id']}:{uid}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🚪 Rời trò chơi",
                        callback_data=f"ww_leave:{game['chat_id']}:{uid}"
                    )
                ]
            ])

            await bot.send_message(
                chat_id=uid,
                text=(
                    "💀 Bạn đã bị loại khỏi trò chơi Ma Sói.\n\n"
                    "Bạn muốn làm gì?"
                ),
                reply_markup=keyboard
            )

        except Exception:
            # Không DM được thì bỏ qua
            game["dead_choices"][uid] = "watch"


async def werewolf_dead_choice_timeout(game):
    """
    Sau một khoảng thời gian nếu người chết
    không chọn thì mặc định là xem.
    """

    await asyncio.sleep(30)

    if game.get("phase") != "dead_choice":
        return

    for uid in game["dead"]:
        if uid not in game["dead_choices"]:
            game["dead_choices"][uid] = "watch"

    await werewolf_start_vote(game)


async def werewolf_dead_callback(update, context):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not (
        data.startswith("ww_watch:")
        or data.startswith("ww_leave:")
    ):
        return

    try:
        _, chat_id, uid = data.split(":", 2)

        chat_id = int(chat_id)
        uid = int(uid)

    except Exception:
        await query.answer()
        return

    # Chỉ chính người chết mới được bấm
    if query.from_user.id != uid:
        await query.answer(
            "❌ Đây không phải lựa chọn của bạn!",
            show_alert=True
        )
        return

    game = werewolf_games.get(chat_id)

    if not game:
        await query.answer(
            "❌ Trò chơi không còn tồn tại.",
            show_alert=True
        )
        return

    if uid not in game["dead"]:
        await query.answer(
            "❌ Bạn không phải người đã chết.",
            show_alert=True
        )
        return

    if data.startswith("ww_watch:"):
        game["dead_choices"][uid] = "watch"

        await query.answer("👁 Bạn sẽ xem tiếp.")

        try:
            await query.edit_message_text(
                "👁 Bạn đã chọn *xem tiếp*.\n\n"
                "Bạn không thể tham gia bỏ phiếu hoặc hành động."
            )
        except Exception:
            pass

    elif data.startswith("ww_leave:"):
        game["dead_choices"][uid] = "leave"

        await query.answer("🚪 Bạn đã rời khỏi trò chơi.")

        try:
            await query.edit_message_text(
                "🚪 Bạn đã chọn rời khỏi trò chơi.\n\n"
                "Bạn không còn được tính là người chơi."
            )
        except Exception:
            pass

    # Kiểm tra đủ lựa chọn
    if all(
        dead_uid in game["dead_choices"]
        for dead_uid in game["dead"]
    ):
        await werewolf_start_vote(game)


async def werewolf_start_vote(game):
    """
    Bắt đầu giai đoạn bỏ phiếu công khai.
    """

    if game.get("phase") == "finished":
        return

    game["phase"] = "vote"
    game["votes"] = {}

    bot = game.get("bot")

    if not bot:
        return

    alive = [
        uid for uid in game["players"]
        if uid in game["alive"]
    ]

    if len(alive) <= 0:
        await werewolf_finish_game(
            game,
            "draw"
        )
        return

    keyboard_rows = []

    for uid in alive:
        name = display_user(uid)

        keyboard_rows.append([
            InlineKeyboardButton(
                f"🗳 {name}",
                callback_data=f"ww_vote:{game['chat_id']}:{uid}"
            )
        ])

    keyboard = InlineKeyboardMarkup(
        keyboard_rows
    )

    try:
        await bot.send_message(
            chat_id=game["chat_id"],
            text=(
                "☀️ *BUỔI SÁNG*\n\n"
                "Mọi người hãy thảo luận và bỏ phiếu "
                "cho người mà bạn nghi là Sói.\n\n"
                "🗳 Mỗi người chỉ được bỏ phiếu 1 lần.\n"
                "⏳ Thời gian bỏ phiếu: 60 giây."
            ),
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    except Exception:
        pass

    asyncio.create_task(
        werewolf_vote_timeout(
            game,
            60
        )
    )


async def werewolf_vote_timeout(game, seconds=60):
    await asyncio.sleep(seconds)

    if game.get("phase") != "vote":
        return

    await werewolf_resolve_vote(game)


async def werewolf_vote_callback(update, context):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith("ww_vote:"):
        return

    try:
        _, chat_id, target = data.split(":", 2)

        chat_id = int(chat_id)
        target = int(target)

    except Exception:
        await query.answer()
        return

    game = werewolf_games.get(chat_id)

    if not game:
        await query.answer(
            "❌ Game không tồn tại.",
            show_alert=True
        )
        return

    voter = query.from_user.id

    # -------------------------
    # CHỈ NGƯỜI CÒN SỐNG ĐƯỢC BỎ PHIẾU
    # -------------------------
    if voter not in game["alive"]:
        await query.answer(
            "💀 Người đã chết không được bỏ phiếu!",
            show_alert=True
        )
        return

    # -------------------------
    # KIỂM TRA TARGET
    # -------------------------
    if target not in game["alive"]:
        await query.answer(
            "❌ Người này đã chết hoặc không còn trong game.",
            show_alert=True
        )
        return

    # -------------------------
    # MỖI NGƯỜI 1 PHIẾU
    # -------------------------
    if voter in game["votes"]:
        await query.answer(
            "⚠️ Bạn đã bỏ phiếu rồi!",
            show_alert=True
        )
        return

    game["votes"][voter] = target

    await query.answer(
        f"🗳 Bạn đã bỏ phiếu cho {display_user(target)}"
    )

    # -------------------------
    # ĐỦ PHIẾU THÌ KẾT THÚC SỚM
    # -------------------------
    alive_count = len(game["alive"])

    if len(game["votes"]) >= alive_count:
        await werewolf_resolve_vote(game)


async def werewolf_resolve_vote(game):
    """
    Tính kết quả bỏ phiếu.
    """

    if game.get("phase") != "vote":
        return

    game["phase"] = "resolving_vote"

    votes = game.get("votes", {})
    roles = game.get("roles", {})

    if not votes:
        await context_bot_send(
            game,
            "🗳 Không có ai bỏ phiếu.\n\n"
            "Không ai bị loại hôm nay."
        )

        await werewolf_next_night(game)
        return

    count = {}

    for target in votes.values():
        count[target] = count.get(target, 0) + 1

    max_votes = max(count.values())

    winners = [
        uid
        for uid, amount in count.items()
        if amount == max_votes
    ]

    # -------------------------
    # HÒA PHIẾU
    # -------------------------
    if len(winners) > 1:

        names = [
            display_user(uid)
            for uid in winners
        ]

        await context_bot_send(
            game,
            "⚖️ *HÒA PHIẾU!*\n\n"
            "Những người có số phiếu cao nhất:\n"
            + "\n".join(
                f"• {name}"
                for name in names
            )
            + "\n\nKhông ai bị loại."
        )

        await werewolf_next_night(game)
        return

    target = winners[0]

    # -------------------------
    # LOẠI NGƯỜI BỊ BỎ PHIẾU
    # -------------------------
    if target in game["alive"]:
        game["alive"].remove(target)

    game["dead"].add(target)

    role = roles.get(
        target,
        "Không rõ"
    )

    await context_bot_send(
        game,
        (
            "🗳 *KẾT QUẢ BỎ PHIẾU*\n\n"
            f"❌ {display_user(target)} "
            f"đã bị dân làng loại.\n\n"
            f"🎭 Vai trò: *{role}*"
        )
    )

    # -------------------------
    # KIỂM TRA THẮNG
    # -------------------------
    winner = werewolf_check_winner(game)

    if winner:
        await werewolf_finish_game(
            game,
            winner
        )
        return

    # -------------------------
    # CHUYỂN SANG ĐÊM
    # -------------------------
    await asyncio.sleep(2)

    await werewolf_next_night(game)


async def werewolf_next_night(game):
    """
    Bắt đầu đêm tiếp theo.
    """

    if game.get("phase") == "finished":
        return

    game["night"] = game.get("night", 1) + 1

    game["phase"] = "night"

    game["night_actions"] = {}

    await context_bot_send(
        game,
        (
            f"🌙 *ĐÊM {game['night']}*\n\n"
            "Mọi người hãy nhắm mắt lại.\n"
            "Bot sẽ lần lượt gọi từng vai trò."
        )
    )

    await asyncio.sleep(2)

    await werewolf_run_night_roles(game)

# =========================
# PHẦN 15/20 — MA SÓI
# KẾT THÚC GAME + KIỂM TRA THẮNG + CHẶN CHAT BAN ĐÊM
# =========================

async def werewolf_finish_game(game, winner):
    """
    Kết thúc trò chơi Ma Sói.
    winner:
        wolf  = phe Sói thắng
        village = phe Dân làng thắng
        draw = hòa
    """

    if game.get("phase") == "finished":
        return

    game["phase"] = "finished"

    chat_id = game["chat_id"]
    roles = game.get("roles", {})
    players = game.get("players", [])

    bot = game.get("bot")

    if winner == "wolf":
        title = "🐺 *PHE SÓI WIN!*"
        reason = "Số Sói đã áp đảo phe Dân làng."

    elif winner == "village":
        title = "🏘 *PHE DÂN LÀNG WIN!*"
        reason = "Tất cả Sói đã bị loại."

    else:
        title = "⚖️ *TRÒ CHƠI HÒA!*"
        reason = "Không phe nào đạt điều kiện chiến thắng."

    # -------------------------
    # HIỂN THỊ KẾT QUẢ
    # -------------------------

    lines = [
        title,
        "",
        reason,
        "",
        "🎭 *DANH SÁCH VAI TRÒ:*"
    ]

    for uid in players:
        name = display_user(uid)
        role = roles.get(uid, "Không rõ")

        if uid in game.get("alive", []):
            status = "🟢 Còn sống"
        else:
            status = "💀 Đã chết"

        lines.append(
            f"• {name} — {role} — {status}"
        )

    lines.extend([
        "",
        "🎮 Trò chơi đã kết thúc.",
        "Dùng /masoi để mở ván mới."
    ])

    try:
        if bot:
            await bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines),
                parse_mode="Markdown"
            )
    except Exception:
        pass

    # -------------------------
    # XÓA GAME KHỎI BỘ NHỚ
    # -------------------------

    await asyncio.sleep(5)

    try:
        if chat_id in werewolf_games:
            del werewolf_games[chat_id]
    except Exception:
        pass


def werewolf_check_winner(game):
    """
    Kiểm tra điều kiện thắng.
    """

    alive = game.get("alive", [])
    roles = game.get("roles", {})

    wolves = [
        uid
        for uid in alive
        if roles.get(uid) == "🐺 Sói"
    ]

    villagers = [
        uid
        for uid in alive
        if roles.get(uid) != "🐺 Sói"
    ]

    # Không còn Sói
    if len(wolves) == 0:
        return "village"

    # Sói bằng hoặc nhiều hơn phe còn lại
    if len(wolves) >= len(villagers):
        return "wolf"

    return None


def werewolf_is_running(chat_id):
    """
    Kiểm tra group có game Ma Sói hay không.
    """

    game = werewolf_games.get(chat_id)

    if not game:
        return False

    return game.get("phase") != "finished"


def werewolf_can_chat(game):
    """
    Những phase được phép chat bình thường:
    - morning
    - vote
    - resolving_vote

    Ban đêm / role action sẽ xóa tin nhắn người chơi.
    """

    phase = game.get("phase")

    return phase in (
        "morning",
        "vote",
        "resolving_vote",
        "dead_choice"
    )


def werewolf_should_delete_message(game, user_id):
    """
    Quyết định có xóa tin nhắn của người chơi hay không.
    """

    if not game:
        return False

    phase = game.get("phase")

    # Không xóa khi đang bàn luận / bỏ phiếu
    if werewolf_can_chat(game):
        return False

    # Lobby cho phép chat
    if phase == "lobby":
        return False

    # Game đã kết thúc
    if phase == "finished":
        return False

    # Tin nhắn của người không tham gia
    if user_id not in game.get("players", []):
        return False

    # Trong đêm / role action → xóa
    if phase in (
        "night",
        "role",
        "night_action"
    ):
        return True

    return False


async def werewolf_protect_group_message(
    update,
    context
):
    """
    Xóa tin nhắn người chơi khi game đang ở
    giai đoạn ban đêm.
    """

    if not update.message:
        return False

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return False

    if chat.type not in (
        "group",
        "supergroup"
    ):
        return False

    game = werewolf_games.get(chat.id)

    if not game:
        return False

    if not werewolf_should_delete_message(
        game,
        user.id
    ):
        return False

    # Admin vẫn được phép điều khiển group
    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user.id
        )

        if member.status in (
            "administrator",
            "creator"
        ):
            return False

    except Exception:
        pass

    try:
        await update.message.delete()
        return True

    except Exception:
        return False


async def werewolf_force_night_mode(game):
    """
    Chuyển game sang chế độ ban đêm.
    """

    game["phase"] = "night"

    game["night_actions"] = {}

    game["current_role"] = None

    await context_bot_send(
        game,
        (
            "🌙 *MỌI NGƯỜI NHẮM MẮT!*\n\n"
            "🤫 Không được nhắn tin trong group.\n"
            "Bot sẽ lần lượt gọi các vai trò."
        )
    )


async def werewolf_day_message(game):
    """
    Thông báo bắt đầu ban ngày.
    """

    game["phase"] = "morning"

    await context_bot_send(
        game,
        (
            "☀️ *BUỔI SÁNG BẮT ĐẦU!*\n\n"
            "Mọi người có thể thảo luận trong group."
        )
    )


async def werewolf_cleanup_old_messages(
    update,
    context
):
    """
    Xóa tin nhắn cũ của game nếu bot có quyền.
    Hàm này chỉ dùng khi Telegram cho phép bot xóa.
    """

    if not update.message:
        return

    chat = update.effective_chat

    if not chat:
        return

    game = werewolf_games.get(chat.id)

    if not game:
        return

    if game.get("phase") not in (
        "night",
        "role",
        "night_action"
    ):
        return

    await werewolf_protect_group_message(
        update,
        context
    )


async def werewolf_cancel_if_not_enough(
    game
):
    """
    Kiểm tra lobby.
    Nếu hết 3 phút mà dưới 4 người
    thì hủy game.
    """

    if game.get("phase") != "lobby":
        return

    players = game.get("players", [])

    if len(players) >= 4:
        return

    await context_bot_send(
        game,
        (
            "❌ *KHÔNG ĐỦ NGƯỜI CHƠI!*\n\n"
            f"Hiện chỉ có {len(players)} người tham gia.\n"
            "Cần ít nhất 4 người để bắt đầu Ma Sói."
        )
    )

    game["phase"] = "finished"

    chat_id = game["chat_id"]

    if chat_id in werewolf_games:
        del werewolf_games[chat_id]


async def werewolf_admin_cancel(
    update,
    context
):
    """
    Admin có thể dùng:
    /huyma
    để hủy game hiện tại.
    """

    if not update.message:
        return

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in (
        "group",
        "supergroup"
    ):
        return

    if not await is_admin(
        context.bot,
        chat.id,
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ Chỉ quản trị viên mới được hủy game."
        )
        return

    game = werewolf_games.get(chat.id)

    if not game:
        await update.message.reply_text(
            "❌ Group hiện không có game Ma Sói."
        )
        return

    game["phase"] = "finished"

    del werewolf_games[chat.id]

    await update.message.reply_text(
        "🛑 *Đã hủy trò chơi Ma Sói.*",
        parse_mode="Markdown"
    )


async def werewolf_status(
    update,
    context
):
    """
    /masoistatus
    Hiển thị trạng thái game.
    """

    if not update.message:
        return

    chat = update.effective_chat

    if not chat:
        return

    game = werewolf_games.get(chat.id)

    if not game:
        await update.message.reply_text(
            "❌ Hiện không có game Ma Sói."
        )
        return

    phase = game.get("phase", "unknown")
    players = game.get("players", [])
    alive = game.get("alive", [])

    await update.message.reply_text(
        "🐺 *MA SÓI STATUS*\n\n"
        f"🎮 Trạng thái: `{phase}`\n"
        f"👥 Người chơi: {len(players)}\n"
        f"❤️ Còn sống: {len(alive)}",
        parse_mode="Markdown"
    )

# =========================
# PHẦN 16/20
# PROTECTION HANDLER + TÍCH HỢP MA SÓI
# =========================

async def protection_handler(update, context):
    """
    Handler tin nhắn chính của group.

    Thứ tự:
    1. Lưu user
    2. Kiểm tra game Ma Sói
    3. Xóa chat ban đêm của người chơi
    4. AFK
    5. CAM
    6. Antilink
    7. Antispam
    8. Filter
    9. Game nối chữ
    """

    if not update.message:
        return

    message = update.message
    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    # Chỉ xử lý group
    if chat.type not in (
        "group",
        "supergroup"
    ):
        return

    # -------------------------
    # LƯU USER
    # -------------------------

    try:
        save_user(
            user.id,
            user.username,
            user.first_name
        )
    except Exception:
        pass

    try:
        ensure_chat(chat.id)
    except Exception:
        pass

    # =====================================================
    # MA SÓI — PHẢI KIỂM TRA TRƯỚC
    # =====================================================

    ww_game = werewolf_games.get(chat.id)

    if ww_game:

        # Tin nhắn của người chơi trong ban đêm
        # sẽ bị xóa.
        deleted = await werewolf_protect_group_message(
            update,
            context
        )

        if deleted:
            return

    # =====================================================
    # GAME NỐI CHỮ
    # =====================================================

    try:
        if chat.id in word_games:

            # Không để hệ thống bảo vệ can thiệp
            # vào tin nhắn đang chơi nối chữ.
            await wordgame_message(
                update,
                context
            )

            return

    except Exception:
        pass

    # =====================================================
    # AFK
    # =====================================================

    try:
        await remove_afk(
            update,
            context
        )
    except Exception:
        pass

    try:
        await check_afk(
            update,
            context
        )
    except Exception:
        pass

    # =====================================================
    # CAM / ANTIFAKE
    # =====================================================

    try:
        blocked = await handle_cam(
            update,
            context
        )

        if blocked:
            return

    except Exception:
        pass

    # =====================================================
    # ANTILINK
    # =====================================================

    try:
        blocked = await handle_antilink(
            update,
            context
        )

        if blocked:
            return

    except Exception:
        pass

    # =====================================================
    # ANTISPAM
    # =====================================================

    try:
        blocked = await handle_antispam(
            update,
            context
        )

        if blocked:
            return

    except Exception:
        pass

    # =====================================================
    # FILTER
    # =====================================================

    try:
        blocked = await handle_filters(
            update,
            context
        )

        if blocked:
            return

    except Exception:
        pass


# =========================================================
# MA SÓI — XỬ LÝ TIN NHẮN RIÊNG
# =========================================================

async def werewolf_private_message(
    update,
    context
):
    """
    Xử lý tin nhắn riêng của người chơi Ma Sói.

    Các callback button xử lý phần lớn hành động.
    Hàm này dùng để trả lời những trường hợp người chơi
    nhắn chữ thay vì bấm nút.
    """

    if not update.message:
        return

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type != "private":
        return

    # Tìm game có người chơi này
    game = None

    for g in werewolf_games.values():

        if user.id in g.get("players", []):
            game = g
            break

    if not game:
        return

    phase = game.get("phase")

    # -------------------------
    # ĐANG CHỜ HÀNH ĐỘNG
    # -------------------------

    action = game.get("current_action")

    if not action:
        await update.message.reply_text(
            "🤫 Hiện tại bạn chưa được gọi hành động."
        )
        return

    if action.get("user_id") != user.id:
        return

    await update.message.reply_text(
        "🎮 Hãy sử dụng các nút mà bot gửi cho bạn "
        "để chọn hành động."
    )


# =========================================================
# MA SÓI — KIỂM TRA BOT CÓ QUYỀN XÓA TIN
# =========================================================

async def werewolf_check_bot_permission(
    update,
    context
):
    """
    Kiểm tra bot có quyền Delete Messages hay không.
    """

    chat = update.effective_chat

    if not chat:
        return False

    try:
        me = await context.bot.get_me()

        member = await context.bot.get_chat_member(
            chat.id,
            me.id
        )

        if member.status == "creator":
            return True

        if member.status != "administrator":
            return False

        permissions = getattr(
            member,
            "can_delete_messages",
            False
        )

        return bool(permissions)

    except Exception:
        return False


# =========================================================
# MA SÓI — NHẮC QUYỀN BOT
# =========================================================

async def werewolf_permission_warning(
    update,
    context
):
    """
    Dùng khi /masoi được gọi nhưng bot không có
    quyền xóa tin nhắn.
    """

    try:
        await update.message.reply_text(
            "❌ Bot chưa có quyền *Xóa tin nhắn*.\n\n"
            "Hãy cấp quyền quản trị cho bot và bật:\n"
            "• 🗑 Xóa tin nhắn\n\n"
            "Sau đó dùng lại /masoi.",
            parse_mode="Markdown"
        )
    except Exception:
        pass


# =========================================================
# MA SÓI — DỌN GAME CŨ
# =========================================================

async def werewolf_cleanup_games():
    """
    Dọn những game bị treo quá lâu.

    Chạy định kỳ từ main().
    """

    now = time.time()

    remove_ids = []

    for chat_id, game in list(
        werewolf_games.items()
    ):

        created = game.get(
            "created_at",
            now
        )

        # Game tồn tại quá 2 giờ
        if now - created > 7200:

            remove_ids.append(
                chat_id
            )

    for chat_id in remove_ids:

        try:
            del werewolf_games[chat_id]
        except Exception:
            pass


# =========================================================
# MA SÓI — XÓA MESSAGE LỖI / GAME
# =========================================================

async def werewolf_safe_delete(
    bot,
    chat_id,
    message_id
):
    try:
        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
        return True

    except Exception:
        return False


# =========================================================
# MA SÓI — THÔNG BÁO PHASE
# =========================================================

async def werewolf_phase_message(
    game,
    phase
):
    """
    Gửi thông báo phase.
    """

    if phase == "night":
        text = (
            "🌙 *BAN ĐÊM*\n\n"
            "🤫 Mọi người giữ im lặng.\n"
            "Bot đang gọi các vai trò."
        )

    elif phase == "morning":
        text = (
            "☀️ *BUỔI SÁNG*\n\n"
            "Mọi người có thể nói chuyện và "
            "thảo luận trong group."
        )

    elif phase == "vote":
        text = (
            "🗳 *BỎ PHIẾU*\n\n"
            "Mọi người hãy chọn người mà bạn nghi "
            "là Sói."
        )

    else:
        return

    await context_bot_send(
        game,
        text
    )


# =========================================================
# MA SÓI — KIỂM TRA NGƯỜI CHƠI CÒN SỐNG
# =========================================================

def werewolf_is_alive(
    game,
    user_id
):
    return user_id in game.get(
        "alive",
        []
    )


# =========================================================
# MA SÓI — KIỂM TRA NGƯỜI CHƠI
# =========================================================

def werewolf_is_player(
    game,
    user_id
):
    return user_id in game.get(
        "players",
        []
    )


# =========================================================
# MA SÓI — LẤY VAI TRÒ
# =========================================================

def werewolf_role(
    game,
    user_id
):
    return game.get(
        "roles",
        {}
    ).get(
        user_id
    )


# =========================================================
# MA SÓI — LẤY GAME CỦA USER
# =========================================================

def werewolf_find_game_by_user(
    user_id
):
    for game in werewolf_games.values():

        if user_id in game.get(
            "players",
            []
        ):
            return game

    return None


# =========================================================
# MA SÓI — LẤY GAME THEO CHAT
# =========================================================

def werewolf_get_game(
    chat_id
):
    return werewolf_games.get(
        chat_id
    )

# =========================
# PHẦN 17/20
# MA SÓI — CALLBACK ROUTER
# =========================

async def werewolf_callback_router(update, context):
    """
    Router tổng cho toàn bộ nút Ma Sói.

    Callback được chia theo tiền tố:
      ww_join
      ww_leave
      ww_cancel
      ww_wolf
      ww_seer
      ww_guard
      ww_witch
      ww_hunter
      ww_zombie
      ww_vote
      ww_watch
    """

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    # =====================================================
    # LOBBY
    # =====================================================

    if data.startswith("ww_join:"):
        await werewolf_join_callback(
            update,
            context
        )
        return

    if data.startswith("ww_leave:"):
        # Có 2 loại ww_leave:
        # - người chơi lobby
        # - người chết chọn rời
        #
        # Kiểm tra game trước.
        try:
            parts = data.split(":")

            if len(parts) == 3:
                await werewolf_dead_callback(
                    update,
                    context
                )
            else:
                await werewolf_leave_callback(
                    update,
                    context
                )

        except Exception:
            await query.answer()

        return

    # =====================================================
    # NGƯỜI CHẾT
    # =====================================================

    if data.startswith("ww_watch:"):
        await werewolf_dead_callback(
            update,
            context
        )
        return

    # =====================================================
    # SÓI
    # =====================================================

    if data.startswith("ww_wolf:"):
        await werewolf_wolf_callback(
            update,
            context
        )
        return

    # =====================================================
    # TIÊN TRI
    # =====================================================

    if data.startswith("ww_seer:"):
        await werewolf_seer_callback(
            update,
            context
        )
        return

    # =====================================================
    # BẢO VỆ
    # =====================================================

    if data.startswith("ww_guard:"):
        await werewolf_guard_callback(
            update,
            context
        )
        return

    # =====================================================
    # PHÙ THỦY — CỨU
    # =====================================================

    if data.startswith("ww_save:"):
        await werewolf_witch_save_callback(
            update,
            context
        )
        return

    if data.startswith("ww_nosave:"):
        await werewolf_witch_no_save_callback(
            update,
            context
        )
        return

    if data.startswith("ww_skip:"):
        await werewolf_witch_skip_callback(
            update,
            context
        )
        return

    # =====================================================
    # PHÙ THỦY — ĐỘC
    # =====================================================

    if data.startswith("ww_poison_menu:"):
        await werewolf_witch_poison_menu(
            update,
            context
        )
        return

    if data.startswith("ww_poison:"):
        await werewolf_witch_poison_callback(
            update,
            context
        )
        return

    # =====================================================
    # THỢ SĂN
    # =====================================================

    if data.startswith("ww_hunter:"):
        await werewolf_hunter_callback(
            update,
            context
        )
        return

    # =====================================================
    # ZOMBIE
    # =====================================================

    if data.startswith("ww_zombie:"):
        await werewolf_zombie_callback(
            update,
            context
        )
        return

    # =====================================================
    # BỎ PHIẾU
    # =====================================================

    if data.startswith("ww_vote:"):
        await werewolf_vote_callback(
            update,
            context
        )
        return

    # =====================================================
    # KHÔNG NHẬN DIỆN
    # =====================================================

    try:
        await query.answer(
            "⚠️ Nút này không còn hoạt động."
        )
    except Exception:
        pass


# =========================================================
# CALLBACK AN TOÀN
# =========================================================

async def werewolf_answer(
    query,
    text=None,
    alert=False
):
    """
    Tránh lỗi khi callback đã được answer trước đó.
    """

    try:
        if text is None:
            await query.answer()
        else:
            await query.answer(
                text,
                show_alert=alert
            )
    except Exception:
        pass


# =========================================================
# KIỂM TRA CALLBACK CÓ ĐÚNG GAME KHÔNG
# =========================================================

def werewolf_validate_callback(
    game,
    user_id
):
    if not game:
        return False

    if user_id not in game.get(
        "players",
        []
    ):
        return False

    if user_id not in game.get(
        "alive",
        []
    ):
        return False

    return True


# =========================================================
# HỦY GAME KHI GROUP BỊ XÓA / BOT MẤT QUYỀN
# =========================================================

async def werewolf_check_games(
    context
):
    """
    Kiểm tra các game đang chạy.

    Nếu group không còn tồn tại hoặc bot không truy cập được,
    game sẽ được dọn khỏi bộ nhớ.
    """

    remove_games = []

    for chat_id, game in list(
        werewolf_games.items()
    ):

        try:
            await context.bot.get_chat(
                chat_id
            )

        except Exception:
            remove_games.append(
                chat_id
            )

    for chat_id in remove_games:

        try:
            del werewolf_games[
                chat_id
            ]
        except Exception:
            pass


# =========================================================
# TIMER DỌN GAME
# =========================================================

async def werewolf_background_loop(
    application
):
    """
    Background loop.

    Chạy mỗi 60 giây để:
    - dọn game bị treo
    - kiểm tra game cũ
    """

    while True:

        try:
            await werewolf_cleanup_games()

            class DummyContext:
                pass

            dummy = DummyContext()
            dummy.bot = application.bot

            await werewolf_check_games(
                dummy
            )

        except asyncio.CancelledError:
            break

        except Exception:
            pass

        await asyncio.sleep(60)


# =========================================================
# TẠO TASK BACKGROUND
# =========================================================

async def start_background_tasks(
    application
):
    """
    Tạo các task chạy nền.
    """

    if not hasattr(
        application,
        "_dtn_background_tasks"
    ):
        application._dtn_background_tasks = []

    task = asyncio.create_task(
        werewolf_background_loop(
            application
        )
    )

    application._dtn_background_tasks.append(
        task
    )


# =========================================================
# DỪNG TASK BACKGROUND
# =========================================================

async def stop_background_tasks(
    application
):
    tasks = getattr(
        application,
        "_dtn_background_tasks",
        []
    )

    for task in tasks:

        try:
            task.cancel()
        except Exception:
            pass

    if tasks:

        try:
            await asyncio.gather(
                *tasks,
                return_exceptions=True
            )
        except Exception:
            pass

    application._dtn_background_tasks = []


# =========================================================
# CALLBACK ERROR HANDLER
# =========================================================

async def callback_error_handler(
    update,
    context
):
    """
    Không để lỗi callback làm chết bot.
    """

    try:
        error = context.error

        print(
            "CALLBACK ERROR:",
            repr(error)
        )

    except Exception:
        pass

# =========================
# PHẦN 18/20
# HANDLER PHỤ + ERROR HANDLER
# =========================


async def bot_error_handler(update, context):
    """
    Error handler tổng.
    Không để một lỗi Telegram làm bot dừng.
    """

    try:
        print(
            "BOT ERROR:",
            repr(context.error)
        )
    except Exception:
        pass


# =========================================================
# KIỂM TRA BOT CÓ PHẢI ADMIN
# =========================================================

async def check_bot_admin(
    update,
    context
):
    """
    Kiểm tra bot có quyền admin trong group.
    """

    chat = update.effective_chat

    if not chat:
        return False

    try:
        me = await context.bot.get_me()

        member = await context.bot.get_chat_member(
            chat.id,
            me.id
        )

        return member.status in (
            "administrator",
            "creator"
        )

    except Exception:
        return False


# =========================================================
# LỆNH /masoistatus
# =========================================================

async def masoistatus_command(
    update,
    context
):
    if not update.message:
        return

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in (
        "group",
        "supergroup"
    ):
        await update.message.reply_text(
            "🐺 Lệnh này chỉ dùng trong group."
        )
        return

    game = werewolf_games.get(chat.id)

    if not game:
        await update.message.reply_text(
            "❌ Hiện tại group chưa có game Ma Sói."
        )
        return

    phase = game.get(
        "phase",
        "unknown"
    )

    players = game.get(
        "players",
        []
    )

    alive = game.get(
        "alive",
        []
    )

    dead = game.get(
        "dead",
        []
    )

    await update.message.reply_text(
        "🐺 *TRẠNG THÁI MA SÓI*\n\n"
        f"🎮 Giai đoạn: `{phase}`\n"
        f"👥 Người chơi: {len(players)}\n"
        f"❤️ Còn sống: {len(alive)}\n"
        f"💀 Đã chết: {len(dead)}",
        parse_mode="Markdown"
    )


# =========================================================
# LỆNH /huyma
# =========================================================

async def huyma_command(
    update,
    context
):
    if not update.message:
        return

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in (
        "group",
        "supergroup"
    ):
        await update.message.reply_text(
            "❌ Lệnh này chỉ dùng trong group."
        )
        return

    user = update.effective_user

    if not user:
        return

    if not await is_admin(
        context.bot,
        chat.id,
        user.id
    ):
        await update.message.reply_text(
            "❌ Chỉ quản trị viên mới được dùng lệnh này."
        )
        return

    game = werewolf_games.get(
        chat.id
    )

    if not game:
        await update.message.reply_text(
            "❌ Không có game Ma Sói đang chạy."
        )
        return

    game["phase"] = "finished"

    try:
        del werewolf_games[
            chat.id
        ]
    except Exception:
        pass

    await update.message.reply_text(
        "🛑 *Đã hủy game Ma Sói.*",
        parse_mode="Markdown"
    )


# =========================================================
# /masoi — KIỂM TRA TRƯỚC KHI CHƠI
# =========================================================

async def masoi_precheck(
    update,
    context
):
    """
    Hàm kiểm tra trước khi tạo game.
    """

    if not update.message:
        return False

    chat = update.effective_chat

    if not chat:
        return False

    if chat.type not in (
        "group",
        "supergroup"
    ):
        return False

    # Bot phải là admin
    if not await check_bot_admin(
        update,
        context
    ):
        await update.message.reply_text(
            "❌ Bot phải là quản trị viên của group."
        )
        return False

    # Bot phải có quyền xóa tin nhắn
    if not await werewolf_check_bot_permission(
        update,
        context
    ):
        await werewolf_permission_warning(
            update,
            context
        )
        return False

    # Đã có game
    if chat.id in werewolf_games:

        game = werewolf_games[
            chat.id
        ]

        phase = game.get(
            "phase",
            "unknown"
        )

        await update.message.reply_text(
            "🐺 Group đang có một game Ma Sói.\n\n"
            f"🎮 Trạng thái: {phase}\n\n"
            "Hãy chờ game kết thúc hoặc dùng "
            "/huyma nếu bạn là admin."
        )

        return False

    return True


# =========================================================
# WRAPPER /masoi
# =========================================================

async def masoi_command(
    update,
    context
):
    """
    Wrapper an toàn cho lệnh /masoi.

    Hàm werewolf_command ở PHẦN 9 sẽ xử lý
    phần tạo lobby.
    """

    allowed = await masoi_precheck(
        update,
        context
    )

    if not allowed:
        return

    try:
        await werewolf_command(
            update,
            context
        )

    except Exception as e:

        print(
            "MASOI ERROR:",
            repr(e)
        )

        try:
            await update.message.reply_text(
                "❌ Không thể khởi động Ma Sói.\n"
                "Kiểm tra quyền bot và thử lại."
            )
        except Exception:
            pass


# =========================================================
# DM ERROR
# =========================================================

async def werewolf_dm_error(
    bot,
    user_id,
    text
):
    """
    Gửi DM an toàn.
    """

    try:
        await bot.send_message(
            chat_id=user_id,
            text=text
        )

        return True

    except Exception as e:

        print(
            "DM ERROR:",
            user_id,
            repr(e)
        )

        return False


# =========================================================
# THÔNG BÁO USER CHƯA MỞ CHAT BOT
# =========================================================

async def werewolf_dm_required(
    update,
    context
):
    """
    Dùng khi người chơi chưa từng mở chat riêng
    với bot.
    """

    if not update.callback_query:
        return

    query = update.callback_query

    await query.answer(
        "❌ Bạn chưa mở chat riêng với bot.",
        show_alert=True
    )

    try:
        await query.message.reply_text(
            "⚠️ Người chơi cần mở chat riêng với bot "
            "và nhấn /start trước khi tham gia."
        )
    except Exception:
        pass


# =========================================================
# /ww
# =========================================================

async def ww_command(
    update,
    context
):
    """
    Alias cho /masoi.
    """

    await masoi_command(
        update,
        context
    )


# =========================================================
# LỆNH KIỂM TRA QUYỀN BOT
# =========================================================

async def botpermission_command(
    update,
    context
):
    if not update.message:
        return

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in (
        "group",
        "supergroup"
    ):
        await update.message.reply_text(
            "❌ Lệnh này chỉ dùng trong group."
        )
        return

    try:
        me = await context.bot.get_me()

        member = await context.bot.get_chat_member(
            chat.id,
            me.id
        )

        if member.status not in (
            "administrator",
            "creator"
        ):
            await update.message.reply_text(
                "❌ Bot chưa phải admin."
            )
            return

        can_delete = getattr(
            member,
            "can_delete_messages",
            False
        )

        if can_delete:
            await update.message.reply_text(
                "✅ Bot là admin và có quyền xóa tin nhắn."
            )
        else:
            await update.message.reply_text(
                "⚠️ Bot là admin nhưng chưa có quyền "
                "xóa tin nhắn."
            )

    except Exception as e:

        print(
            "PERMISSION ERROR:",
            repr(e)
        )

        await update.message.reply_text(
            "❌ Không thể kiểm tra quyền bot."
        )


# =========================================================
# DEBUG GAME
# =========================================================

async def debug_masoi_command(
    update,
    context
):
    """
    Lệnh debug chỉ dành cho admin.
    """

    if not update.message:
        return

    chat = update.effective_chat

    if not chat:
        return

    user = update.effective_user

    if not user:
        return

    if not await is_admin(
        context.bot,
        chat.id,
        user.id
    ):
        return

    game = werewolf_games.get(
        chat.id
    )

    if not game:
        await update.message.reply_text(
            "DEBUG: Không có game."
        )
        return

    text = (
        "DEBUG MA SÓI\n\n"
        f"phase = {game.get('phase')}\n"
        f"night = {game.get('night')}\n"
        f"players = {game.get('players')}\n"
        f"alive = {game.get('alive')}\n"
        f"dead = {game.get('dead')}\n"
        f"roles = {game.get('roles')}\n"
        f"actions = {game.get('night_actions')}"
    )

    await update.message.reply_text(
        text
    )

# =========================
# PHẦN 19/20
# MAIN — ĐĂNG KÝ TOÀN BỘ HANDLER
# =========================


async def post_init(application):
    """
    Chạy sau khi bot khởi động.
    """

    print("================================")
    print("        DTN BOT STARTING")
    print("================================")

    try:
        await start_background_tasks(
            application
        )
    except Exception as e:
        print(
            "BACKGROUND TASK ERROR:",
            repr(e)
        )

    print("DTN BOT: ONLINE")


async def post_shutdown(application):
    """
    Dừng các task nền khi bot shutdown.
    """

    try:
        await stop_background_tasks(
            application
        )
    except Exception as e:
        print(
            "SHUTDOWN ERROR:",
            repr(e)
        )

    print("DTN BOT: OFFLINE")


def build_application():
    """
    Tạo Telegram Application.
    """

    application = (
        Application
        .builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # =====================================================
    # COMMANDS CƠ BẢN
    # =====================================================

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    # =====================================================
    # QUẢN LÝ THÀNH VIÊN
    # =====================================================

    application.add_handler(
        CommandHandler(
            "mute",
            mute_command
        )
    )

    application.add_handler(
        CommandHandler(
            "unmute",
            unmute_command
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            ban_command
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            unban_command
        )
    )

    application.add_handler(
        CommandHandler(
            "kick",
            kick_command
        )
    )

    application.add_handler(
        CommandHandler(
            "warn",
            warn_command
        )
    )

    application.add_handler(
        CommandHandler(
            "warnings",
            warnings_command
        )
    )

    application.add_handler(
        CommandHandler(
            "clearwarn",
            clearwarn_command
        )
    )

    # =====================================================
    # ADMIN
    # =====================================================

    application.add_handler(
        CommandHandler(
            "promote",
            promote_command
        )
    )

    application.add_handler(
        CommandHandler(
            "promotefull",
            promote_full_command
        )
    )

    application.add_handler(
        CommandHandler(
            "demote",
            demote_command
        )
    )

    application.add_handler(
        CommandHandler(
            "lock",
            lock_group_command
        )
    )

    application.add_handler(
        CommandHandler(
            "unlock",
            unlock_group_command
        )
    )

    application.add_handler(
        CommandHandler(
            "rules",
            rules_command
        )
    )

    application.add_handler(
        CommandHandler(
            "setrules",
            setrules_command
        )
    )

    application.add_handler(
        CommandHandler(
            "id",
            id_command
        )
    )

    application.add_handler(
        CommandHandler(
            "info",
            info_command
        )
    )

    application.add_handler(
        CommandHandler(
            "admins",
            admins_command
        )
    )

    # =====================================================
    # BẢO VỆ GROUP
    # =====================================================

    application.add_handler(
        CommandHandler(
            "antilink",
            antilink_command
        )
    )

    application.add_handler(
        CommandHandler(
            "antispam",
            antispam_command
        )
    )

    application.add_handler(
        CommandHandler(
            "afk",
            afk_command
        )
    )

    # =====================================================
    # FILTER
    # =====================================================

    application.add_handler(
        CommandHandler(
            "filter",
            filter_command
        )
    )

    application.add_handler(
        CommandHandler(
            "filters",
            filters_command
        )
    )

    application.add_handler(
        CommandHandler(
            "stop",
            stop_filter
        )
    )

    # =====================================================
    # GIẢI TRÍ
    # =====================================================

    application.add_handler(
        CommandHandler(
            "thodoi",
            thodoi_command
        )
    )

    application.add_handler(
        CommandHandler(
            "thotinh",
            thotinh_command
        )
    )

    application.add_handler(
        CommandHandler(
            "diemdanh",
            diemdanh_command
        )
    )

    # =====================================================
    # GAME NỐI CHỮ
    # =====================================================

    application.add_handler(
        CommandHandler(
            "gamenoichu",
            gamenoichu_command
        )
    )

    application.add_handler(
        CommandHandler(
            "gameoff",
            gameoff_command
        )
    )

    # =====================================================
    # MA SÓI
    # =====================================================

    application.add_handler(
        CommandHandler(
            "masoi",
            masoi_command
        )
    )

    application.add_handler(
        CommandHandler(
            "ww",
            ww_command
        )
    )

    application.add_handler(
        CommandHandler(
            "huyma",
            huyma_command
        )
    )

    application.add_handler(
        CommandHandler(
            "masoistatus",
            masoistatus_command
        )
    )

    application.add_handler(
        CommandHandler(
            "botpermission",
            botpermission_command
        )
    )

    application.add_handler(
        CommandHandler(
            "debugmasoi",
            debug_masoi_command
        )
    )

    # =====================================================
    # CALLBACK MA SÓI
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            werewolf_callback_router,
            pattern=r"^ww_"
        )
    )

    # =====================================================
    # ĐIỂM DANH CALLBACK
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            attendance_callback,
            pattern=r"^attendance:"
        )
    )

    # =====================================================
    # GAME NỐI CHỮ CALLBACK
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            wordgame_callback,
            pattern=r"^wordgame:"
        )
    )

    # =====================================================
    # TIN NHẮN PRIVATE
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.TEXT
            & ~filters.COMMAND,
            werewolf_private_message
        )
    )

    # =====================================================
    # TIN NHẮN GROUP
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & ~filters.COMMAND,
            protection_handler
        )
    )

    # =====================================================
    # NEW MEMBER
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            new_member_handler
        )
    )

    # =====================================================
    # MEMBER RỜI GROUP
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            left_member_handler
        )
    )

    # =====================================================
    # BOT ĐƯỢC THÊM VÀO GROUP
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            bot_added_handler
        )
    )

    # =====================================================
    # SERVICE MESSAGE CLEANUP
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.ALL,
            delete_service_message
        )
    )

    # =====================================================
    # ERROR HANDLER
    # =====================================================

    application.add_error_handler(
        bot_error_handler
    )

    return application


# =========================================================
# MAIN
# =========================================================

def main():

    application = build_application()

    print("")
    print("================================")
    print("          DTN BOT")
    print("================================")
    print("Bot đang chạy...")
    print("Nhấn CTRL+C để dừng.")
    print("================================")
    print("")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


# =========================================================
# START
# =========================================================

# =========================================================
# PHẦN 20/20 — FINAL
# KIỂM TRA + KHỞI ĐỘNG DTN BOT
# =========================================================


def final_check():
    """
    Kiểm tra một số thành phần quan trọng trước khi chạy.
    """

    required_names = [
        "TOKEN",
        "Application",
        "CommandHandler",
        "MessageHandler",
        "CallbackQueryHandler",

        # Ma Sói
        "werewolf_games",
        "werewolf_command",
        "werewolf_join_callback",
        "werewolf_run_night_roles",
        "werewolf_wolf_callback",
        "werewolf_seer_callback",
        "werewolf_guard_callback",
        "werewolf_witch_save_callback",
        "werewolf_witch_no_save_callback",
        "werewolf_witch_skip_callback",
        "werewolf_witch_poison_callback",
        "werewolf_hunter_callback",
        "werewolf_zombie_callback",
        "werewolf_vote_callback",

        # Game khác
        "word_games",
        "protection_handler",
    ]

    missing = []

    for name in required_names:

        if name not in globals():
            missing.append(name)

    if missing:

        print("")
        print("================================")
        print("        ❌ DTN BOT ERROR")
        print("================================")

        print(
            "Thiếu các thành phần:"
        )

        for name in missing:
            print(
                " -",
                name
            )

        print("================================")
        print("")

        return False

    return True


def check_token():

    if not TOKEN:
        print(
            "❌ TOKEN đang trống."
        )
        return False

    if TOKEN == "DAN_TOKEN_MOI_VAO_DAY":
        print("")
        print("⚠️ TOKEN CHƯA ĐƯỢC ĐIỀN!")
        print(
            "Hãy thay DAN_TOKEN_MOI_VAO_DAY "
            "bằng token bot mới của bạn."
        )
        print("")
        return False

    return True


def final_start():

    print("")
    print("========================================")
    print("             DTN BOT")
    print("========================================")

    # -------------------------
    # KIỂM TRA TOKEN
    # -------------------------

    if not check_token():

        print(
            "❌ Bot chưa thể khởi động."
        )

        return

    # -------------------------
    # KIỂM TRA CODE
    # -------------------------

    if not final_check():

        print(
            "❌ Kiểm tra code thất bại."
        )

        return

    # -------------------------
    # CHẠY BOT
    # -------------------------

    try:

        main()

    except KeyboardInterrupt:

        print("")
        print(
            "🛑 DTN BOT đã được dừng."
        )
        print("")

    except Exception as e:

        print("")
        print("================================")
        print("       ❌ BOT CRASH")
        print("================================")
        print(
            repr(e)
        )
        print("================================")
        print("")


# =========================================================
# CHẠY CHƯƠNG TRÌNH
# =========================================================

if __name__ == "__main__":
    final_start()

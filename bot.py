# ============================================================
# DTN BOT
# PHẦN 1/25
# ============================================================

import os
import re
import json
import time
import random
import asyncio
import unicodedata

from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)

from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError, BadRequest

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CẤU HÌNH
# ============================================================

TOKEN = "8233728594:AAFOTBG8URfrgCfBNwRYttJh1rds6Mvaqm0"

BOT_NAME = "DTN BOT"

# OWNER CỦA BOT
OWNER_USERNAME = "@DTN_207"

# ID sẽ được nhận diện tự động khi Owner sử dụng bot
OWNER_USER_ID = None

# Múi giờ Việt Nam
VN_TZ = timezone(timedelta(hours=7))

# Database
DB_FILE = "dtn_bot_data.json"


# ============================================================
# DATABASE MẶC ĐỊNH
# ============================================================

DEFAULT_DB = {
    "rules": {},
    "warns": {},
    "filters": {},
    "settings": {},
    "attendance": {},
}


# ============================================================
# LOAD DATABASE
# ============================================================

def load_db():

    if not os.path.exists(DB_FILE):
        return DEFAULT_DB.copy()

    try:
        with open(
            DB_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        for key, value in DEFAULT_DB.items():

            if key not in data:
                data[key] = value

        return data

    except Exception as e:

        print(
            f"[DB] Lỗi đọc database: {e}"
        )

        return DEFAULT_DB.copy()


db = load_db()


# ============================================================
# SAVE DATABASE
# ============================================================

def save_db():

    try:

        with open(
            DB_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                db,
                file,
                ensure_ascii=False,
                indent=2
            )

    except Exception as e:

        print(
            f"[DB] Lỗi lưu database: {e}"
        )


db_lock = asyncio.Lock()


async def save_db_async():

    async with db_lock:
        save_db()


# ============================================================
# TRẠNG THÁI BOT
# ============================================================

# Chống link
antilink_enabled = defaultdict(bool)

# Chống spam
antispam_enabled = defaultdict(bool)

# Cache spam
spam_cache = defaultdict(
    lambda: defaultdict(deque)
)

# AFK
afk_users = {}

# Cache người dùng
user_cache = {}

# Game nối chữ
word_games = {}

# Ma Sói
werewolf_games = {}

# Các task nền
background_tasks = set()


# ============================================================
# TẠO BACKGROUND TASK
# ============================================================

def create_background_task(coro):

    task = asyncio.create_task(coro)

    background_tasks.add(task)

    def remove_task(done_task):
        background_tasks.discard(done_task)

    task.add_done_callback(remove_task)

    return task


# ============================================================
# THỜI GIAN
# ============================================================

def now_vn():

    return datetime.now(VN_TZ)


def today_key():

    return now_vn().strftime("%Y-%m-%d")


# ============================================================
# CHUẨN HÓA TEXT
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = text.strip().lower()

    text = unicodedata.normalize(
        "NFD",
        text
    )

    text = "".join(
        char
        for char in text
        if unicodedata.category(char) != "Mn"
    )

    return text


# ============================================================
# LẤY TÊN USER
# ============================================================

def user_display_name(user):

    if not user:
        return "Không rõ"

    if user.full_name:
        return user.full_name

    if user.username:
        return f"@{user.username}"

    return str(user.id)


# ============================================================
# MENTION USER
# ============================================================

def mention_user(user):

    if not user:
        return "Không rõ"

    name = user_display_name(user)

    name = (
        name
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    return (
        f'<a href="tg://user?id={user.id}">'
        f'{name}'
        f'</a>'
    )


# ============================================================
# CACHE USER
# ============================================================

def cache_user(user):

    if not user:
        return

    user_cache[user.id] = {
        "id": user.id,
        "username": user.username,
        "name": user_display_name(user),
    }


# ============================================================
# KIỂM TRA GROUP
# ============================================================

def is_group(update):

    if not update.effective_chat:
        return False

    return update.effective_chat.type in (
        "group",
        "supergroup",
    )


# ============================================================
# KIỂM TRA OWNER
# ============================================================

def is_owner(user):

    if not user:
        return False

    if OWNER_USER_ID is not None:

        if user.id == OWNER_USER_ID:
            return True

    if user.username:

        return (
            user.username.lower()
            == OWNER_USERNAME
            .replace("@", "")
            .lower()
        )

    return False


# ============================================================
# NHẬN DIỆN OWNER
# ============================================================

def log_event(text):
    print(
        f"[{now_vn().strftime('%Y-%m-%d %H:%M:%S')}] {text}"
    )

def register_owner(user):

    global OWNER_USER_ID

    if not user:
        return

    if not user.username:
        return

    if (
        user.username.lower()
        == OWNER_USERNAME
        .replace("@", "")
        .lower()
    ):

        OWNER_USER_ID = user.id

        log_event(
            f"Đã nhận diện Owner "
            f"{OWNER_USERNAME} "
            f"(ID: {user.id})"
        )


# ============================================================
# LẤY BOT MEMBER
# ============================================================

async def get_bot_member(
    context,
    chat_id
):

    try:

        me = await context.bot.get_me()

        return await context.bot.get_chat_member(
            chat_id,
            me.id
        )

    except TelegramError:

        return None


# ============================================================
# KIỂM TRA ADMIN
# ============================================================

async def is_admin(
    context,
    chat_id,
    user_id
):

    if OWNER_USER_ID is not None:

        if user_id == OWNER_USER_ID:
            return True

    try:

        member = await context.bot.get_chat_member(
            chat_id,
            user_id
        )

        return member.status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )

    except TelegramError:

        return False


# ============================================================
# BOT CÓ QUYỀN RESTRICT
# ============================================================

async def bot_can_restrict(
    context,
    chat_id
):

    member = await get_bot_member(
        context,
        chat_id
    )

    if not member:
        return False

    if member.status == ChatMemberStatus.OWNER:
        return True

    return bool(
        getattr(
            member,
            "can_restrict_members",
            False
        )
    )


# ============================================================
# BOT CÓ QUYỀN DELETE
# ============================================================

async def bot_can_delete(
    context,
    chat_id
):

    member = await get_bot_member(
        context,
        chat_id
    )

    if not member:
        return False

    if member.status == ChatMemberStatus.OWNER:
        return True

    return bool(
        getattr(
            member,
            "can_delete_messages",
            False
        )
    )


# ============================================================
# BOT CÓ QUYỀN PIN
# ============================================================

async def bot_can_pin(
    context,
    chat_id
):

    member = await get_bot_member(
        context,
        chat_id
    )

    if not member:
        return False

    if member.status == ChatMemberStatus.OWNER:
        return True

    return bool(
        getattr(
            member,
            "can_pin_messages",
            False
        )
    )

# ============================================================
# DTN BOT
# PHẦN 2/25
# CÁC HÀM TIỆN ÍCH + KIỂM TRA QUYỀN
# ============================================================


# ============================================================
# LẤY USER TỪ REPLY
# ============================================================

def get_replied_user(update):

    message = update.effective_message

    if not message:
        return None

    if not message.reply_to_message:
        return None

    return message.reply_to_message.from_user


# ============================================================
# LẤY USER TỪ ARGUMENT
# Hỗ trợ:
# /mute 123456789
# /mute @username
# /mute (reply tin nhắn)
# ============================================================

async def resolve_target_user(
    update,
    context
):

    message = update.effective_message

    if not message:
        return None

    # ----------------------------------------
    # 1. Nếu reply tin nhắn
    # ----------------------------------------

    replied_user = get_replied_user(update)

    if replied_user:
        cache_user(replied_user)
        register_owner(replied_user)

        return replied_user

    # ----------------------------------------
    # 2. Lấy argument
    # ----------------------------------------

    args = get_args(update)

    if not args:
        return None

    target = args[0].strip()

    # ----------------------------------------
    # 3. ID số
    # ----------------------------------------

    if re.fullmatch(r"-?\d+", target):

        try:

            user_id = int(target)

            # Telegram không cho get_chat_member
            # theo username nhưng có thể lấy theo ID
            member = await context.bot.get_chat_member(
                update.effective_chat.id,
                user_id
            )

            cache_user(member.user)
            register_owner(member.user)

            return member.user

        except TelegramError:

            # Nếu từng cache user này
            if user_id in user_cache:

                cached = user_cache[user_id]

                class CachedUser:
                    pass

                user = CachedUser()
                user.id = cached["id"]
                user.username = cached["username"]
                user.full_name = cached["name"]

                return user

            return None

    # ----------------------------------------
    # 4. Username
    # ----------------------------------------

    username = target.lstrip("@")

    if username:

        # Tìm trong cache trước
        for cached_id, cached in user_cache.items():

            if not cached.get("username"):
                continue

            if (
                cached["username"].lower()
                == username.lower()
            ):

                try:

                    member = await context.bot.get_chat_member(
                        update.effective_chat.id,
                        cached_id
                    )

                    cache_user(member.user)
                    register_owner(member.user)

                    return member.user

                except TelegramError:
                    pass

        # Nếu không có trong cache,
        # thử tìm qua administrators
        try:

            admins = await context.bot.get_chat_administrators(
                update.effective_chat.id
            )

            for admin in admins:

                if not admin.user.username:
                    continue

                if (
                    admin.user.username.lower()
                    == username.lower()
                ):

                    cache_user(admin.user)
                    register_owner(admin.user)

                    return admin.user

        except TelegramError:
            pass

    return None


# ============================================================
# KIỂM TRA TARGET CÓ PHẢI BOT KHÔNG
# ============================================================

async def is_target_bot(
    context,
    target_user
):

    if not target_user:
        return False

    try:

        me = await context.bot.get_me()

        return target_user.id == me.id

    except TelegramError:

        return False


# ============================================================
# KIỂM TRA TARGET CÓ PHẢI ADMIN KHÔNG
# ============================================================

async def is_target_admin(
    context,
    chat_id,
    target_user
):

    if not target_user:
        return False

    return await is_admin(
        context,
        chat_id,
        target_user.id
    )


# ============================================================
# KIỂM TRA NGƯỜI DÙNG CÓ THỂ QUẢN LÝ TARGET
# ============================================================

async def can_manage_target(
    update,
    context,
    target_user
):

    if not target_user:
        return False, "Không tìm thấy thành viên."

    user = update.effective_user

    if not user:
        return False, "Không xác định được người sử dụng lệnh."

    chat_id = update.effective_chat.id

    # Owner có quyền cao nhất
    if is_owner(user):
        return True, None

    # Phải là admin
    if not await is_admin(
        context,
        chat_id,
        user.id
    ):
        return (
            False,
            "❌ Bạn phải là admin để sử dụng lệnh này."
        )

    # Không được quản lý bot
    if await is_target_bot(
        context,
        target_user
    ):
        return (
            False,
            "❌ Không thể quản lý chính bot."
        )

    # Không được quản lý Owner
    if is_owner(target_user):
        return (
            False,
            "❌ Không thể quản lý Owner."
        )

    # Admin thường không nên quản lý admin khác
    if await is_target_admin(
        context,
        chat_id,
        target_user
    ):
        return (
            False,
            "❌ Không thể quản lý admin khác."
        )

    return True, None


# ============================================================
# KIỂM TRA QUYỀN ADMIN VÀ TRẢ MESSAGE
# ============================================================

async def require_admin(
    update,
    context
):

    if not is_group(update):

        await update.effective_message.reply_text(
            "❌ Lệnh này chỉ sử dụng được trong nhóm."
        )

        return False

    user = update.effective_user

    if not user:

        return False

    register_owner(user)

    if is_owner(user):
        return True

    if await is_admin(
        context,
        update.effective_chat.id,
        user.id
    ):
        return True

    await update.effective_message.reply_text(
        "❌ Bạn cần là admin để sử dụng lệnh này."
    )

    return False


# ============================================================
# KIỂM TRA QUYỀN OWNER
# ============================================================

async def require_owner(
    update,
    context
):

    user = update.effective_user

    if not user:
        return False

    register_owner(user)

    if is_owner(user):
        return True

    await update.effective_message.reply_text(
        "❌ Chỉ Owner @DTN_207 mới có thể sử dụng lệnh này."
    )

    return False


# ============================================================
# KIỂM TRA BOT CÓ ĐỦ QUYỀN
# ============================================================

async def require_bot_permission(
    update,
    context,
    permission
):

    chat_id = update.effective_chat.id

    member = await get_bot_member(
        context,
        chat_id
    )

    if not member:

        await update.effective_message.reply_text(
            "❌ Không thể kiểm tra quyền của bot."
        )

        return False

    if member.status == ChatMemberStatus.OWNER:
        return True

    allowed = bool(
        getattr(
            member,
            permission,
            False
        )
    )

    if allowed:
        return True

    await update.effective_message.reply_text(
        "❌ Bot chưa có quyền cần thiết.\n\n"
        "Hãy cấp quyền phù hợp cho DTN BOT "
        "trong phần quản trị nhóm."
    )

    return False


# ============================================================
# XÓA MESSAGE AN TOÀN
# ============================================================

async def safe_delete_message(
    context,
    chat_id,
    message_id
):

    try:

        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )

        return True

    except (
        TelegramError,
        BadRequest
    ):

        return False


# ============================================================
# GỬI MESSAGE AN TOÀN
# ============================================================

async def safe_send_message(
    context,
    chat_id,
    text,
    **kwargs
):

    try:

        return await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            **kwargs
        )

    except TelegramError as e:

        log_event(
            f"Lỗi gửi message: {e}"
        )

        return None


# ============================================================
# TRẢ LỜI AN TOÀN
# ============================================================

async def safe_reply(
    update,
    text,
    **kwargs
):

    message = update.effective_message

    if not message:
        return None

    try:

        return await message.reply_text(
            text,
            **kwargs
        )

    except TelegramError as e:

        log_event(
            f"Lỗi reply: {e}"
        )

        return None


# ============================================================
# KIỂM TRA MESSAGE CÓ TEXT
# ============================================================

def get_message_text(update):

    message = update.effective_message

    if not message:
        return ""

    return message.text or message.caption or ""


# ============================================================
# LẤY ID USER
# ============================================================

def get_user_id(update):

    user = update.effective_user

    if not user:
        return None

    return user.id


# ============================================================
# LẤY CHAT ID
# ============================================================

def get_chat_id(update):

    chat = update.effective_chat

    if not chat:
        return None

    return chat.id


# ============================================================
# TẠO KEY CHO USER TRONG GROUP
# ============================================================

def user_key(
    chat_id,
    user_id
):

    return f"{chat_id}:{user_id}"


# ============================================================
# TẠO KEY CHO WARN
# ============================================================

def warn_key(
    chat_id,
    user_id
):

    return f"{chat_id}:{user_id}"


# ============================================================
# LẤY SỐ WARN
# ============================================================

def get_warn_count(
    chat_id,
    user_id
):

    key = warn_key(
        chat_id,
        user_id
    )

    return len(
        db["warns"].get(
            key,
            []
        )
    )


# ============================================================
# LẤY DANH SÁCH WARN
# ============================================================

def get_warns(
    chat_id,
    user_id
):

    key = warn_key(
        chat_id,
        user_id
    )

    return db["warns"].get(
        key,
        []
    )


# ============================================================
# THÊM WARN
# ============================================================

def add_warn(
    chat_id,
    user_id,
    reason,
    admin_id
):

    key = warn_key(
        chat_id,
        user_id
    )

    if key not in db["warns"]:
        db["warns"][key] = []

    db["warns"][key].append({
        "reason": reason,
        "admin_id": admin_id,
        "time": now_vn().isoformat(),
    })


# ============================================================
# XÓA WARN
# ============================================================

def clear_warns(
    chat_id,
    user_id
):

    key = warn_key(
        chat_id,
        user_id
    )

    db["warns"].pop(
        key,
        None
    )


# ============================================================
# LẤY RULES
# ============================================================

def get_rules(chat_id):

    return db["rules"].get(
        str(chat_id),
        ""
    )


# ============================================================
# SET RULES
# ============================================================

def set_rules(
    chat_id,
    text
):

    db["rules"][str(chat_id)] = text


# ============================================================
# LẤY SETTINGS
# ============================================================

def get_chat_settings(chat_id):

    key = str(chat_id)

    if key not in db["settings"]:
        db["settings"][key] = {}

    return db["settings"][key]

async def require_group(update):
    if is_group(update):
        return True

    await update.effective_message.reply_text(
        "ngươi bớt ngu đi chức năng nhóm ngươi lại riêng tư"
    )
    return False

# ============================================================
# KẾT THÚC PHẦN 2/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 3/25
# LỆNH CƠ BẢN
# /START /HELP /ID /INFO /ADMINS
# ============================================================


# ============================================================
# /START
# ============================================================

def owner_footer():
    return "\n\n👑 Owner : @DTN_207"

async def start_command(
    update,
    context
):

    user = update.effective_user

    if user:
        cache_user(user)
        register_owner(user)

    text = (
        "🤖 Chào bạn! Tôi là DTN BOT\n"
        "Vui lòng /help để biết thêm về tôi."
        + owner_footer()
    )

    await safe_reply(
        update,
        text
    )


# ============================================================
# NỘI DUNG HELP
# ============================================================

HELP_TEXT = (
    "🤖 DTN BOT — DANH SÁCH LỆNH\n"
    "\n"
    "🏠 CƠ BẢN\n"
    "/start — Khởi động bot\n"
    "/help — Xem danh sách lệnh\n"
    "/id — Xem ID người dùng / nhóm\n"
    "/info — Xem thông tin người dùng\n"
    "/admins — Xem danh sách quản trị viên\n"
    "/rules — Xem nội quy nhóm\n"
    "/setrules — Đặt nội quy nhóm\n"
    "\n"
    "👮 QUẢN LÝ\n"
    "/mute — Khóa chat thành viên\n"
    "/unmute — Mở khóa chat\n"
    "/ban — Cấm thành viên\n"
    "/unban — Gỡ cấm\n"
    "/kick — Đuổi thành viên\n"
    "/warn — Cảnh cáo thành viên\n"
    "/warnings — Xem số cảnh cáo\n"
    "/clearwarn — Xóa cảnh cáo\n"
    "\n"
    "👑 ADMIN\n"
    "/promote — Thăng thành viên\n"
    "/promotefull — Thăng với đầy đủ quyền\n"
    "/demote — Hạ quyền admin\n"
    "/lock — Khóa chat nhóm\n"
    "/unlock — Mở khóa chat nhóm\n"
    "\n"
    "🛡️ BẢO VỆ\n"
    "/antilink — Bật/tắt chống link\n"
    "/antispam — Bật/tắt chống spam\n"
    "/filter — Tạo bộ lọc từ khóa\n"
    "/filters — Xem bộ lọc\n"
    "/stopfilter — Xóa bộ lọc\n"
    "/afk — Bật trạng thái AFK\n"
    "\n"
    "🗑️ TIN NHẮN\n"
    "/del — Xóa tin nhắn\n"
    "/pin — Ghim tin nhắn\n"
    "/unpin — Bỏ ghim tin nhắn\n"
    "\n"
    "😂 THƠ\n"
    "/thodoi — Bot gửi một bài thơ đời ý nghĩa\n"
    "/thotinh — Bot gửi một bài thơ tình ý nghĩa\n"
    "\n"
    "🎮 GIẢI TRÍ\n"
    "/diemdanh — Điểm danh nhận streak\n"
    "/gamenoichu — Bắt đầu game nối chữ\n"
    "/gameoff — Dừng game nối chữ\n"
    "\n"
    "🐺 MA SÓI\n"
    "/masoi — Tạo phòng Ma Sói\n"
    "/masoistatus — Xem trạng thái trận\n"
    "/huyma — Hủy trận Ma Sói\n"
    "/ww — Hướng dẫn Ma Sói\n"
    "/botpermission — Kiểm tra quyền bot\n"
    "/debugmasoi — Kiểm tra dữ liệu Ma Sói\n"
    "\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "👑 Owner : @DTN_207\n"
    "🤖 DTN BOT"
)


# ============================================================
# /HELP
# ============================================================

async def help_command(update, context):

    if is_group(update):
        await update.effective_message.reply_text(
            "help cái đầu buồi chủ tao chưa ra help group OK"
        )
        return

    user = update.effective_user

    if user:
        cache_user(user)
        register_owner(user)

    # Trong nhóm
    if is_group(update):

        await safe_reply(
            update,
            HELP_TEXT
        )

        return

    # Trong tin nhắn riêng
    text = (
        "🤖 DTN BOT\n\n"
        "Các tính năng quản lý nhóm "
        "chỉ hoạt động trong group.\n\n"
        "👉 Hãy thêm bot vào nhóm và sử dụng "
        "/help tại đó."
        + owner_footer()
    )

    await safe_reply(
        update,
        text
    )


# ============================================================
# /ID
# ============================================================

async def id_command(
    update,
    context
):

    user = update.effective_user
    chat = update.effective_chat

    if user:
        cache_user(user)
        register_owner(user)

    if not user or not chat:
        return

    text = (
        "🆔 THÔNG TIN ID\n\n"
        f"👤 User ID: {user.id}\n"
        f"💬 Chat ID: {chat.id}\n"
        f"🏷️ Chat type: {chat.type}"
    )

    if chat.title:
        text += (
            f"\n📌 Tên nhóm: {chat.title}"
        )

    await safe_reply(
        update,
        text
    )


# ============================================================
# /INFO
# ============================================================

async def info_command(
    update,
    context
):

    user = await resolve_target_user(
        update,
        context
    )

    # Nếu không có target thì lấy người dùng lệnh
    if not user:
        user = update.effective_user

    if not user:
        return

    cache_user(user)
    register_owner(user)

    name = escape_html(
        user_display_name(user)
    )

    username = (
        f"@{escape_html(user.username)}"
        if user.username
        else "Không có"
    )

    owner_status = (
        "👑 Owner"
        if is_owner(user)
        else "👤 Thành viên"
    )

    admin_status = "Không xác định"

    if is_group(update):

        if await is_admin(
            context,
            update.effective_chat.id,
            user.id
        ):
            admin_status = "👮 Admin"
        else:
            admin_status = "👤 Thành viên"

    text = (
        "ℹ️ THÔNG TIN NGƯỜI DÙNG\n\n"
        f"👤 Tên: {name}\n"
        f"🔹 Username: {username}\n"
        f"🆔 ID: {user.id}\n"
        f"📌 Trạng thái: {owner_status}\n"
        f"👮 Quyền nhóm: {admin_status}"
    )

    await safe_reply(
        update,
        text,
        parse_mode="HTML"
    )


# ============================================================
# /ADMINS
# ============================================================

async def admins_command(
    update,
    context
):

    if not is_group(update):

        await safe_reply(
            update,
            "❌ Lệnh này chỉ sử dụng được trong nhóm."
        )

        return

    try:

        admins = await context.bot.get_chat_administrators(
            update.effective_chat.id
        )

    except TelegramError as e:

        log_event(
            f"Lỗi lấy danh sách admin: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể lấy danh sách quản trị viên."
        )

        return

    lines = [
        "👑 DANH SÁCH QUẢN TRỊ VIÊN",
        ""
    ]

    for index, admin in enumerate(
        admins,
        start=1
    ):

        user = admin.user

        cache_user(user)
        register_owner(user)

        name = escape_html(
            user_display_name(user)
        )

        if admin.status == ChatMemberStatus.OWNER:

            role = "👑 Chủ nhóm"

        else:

            role = "🛡️ Admin"

        lines.append(
            f"{index}. {name} — {role}"
        )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("👑 Owner : @DTN_207")

    await safe_reply(
        update,
        "\n".join(lines),
        parse_mode="HTML"
    )


# ============================================================
# KẾT THÚC PHẦN 3/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 4/25
# NỘI QUY NHÓM
# /RULES /SETRULES
# ============================================================


# ============================================================
# /RULES
# ============================================================

async def rules_command(
    update,
    context
):

    if not is_group(update):

        await safe_reply(
            update,
            "❌ Lệnh này chỉ sử dụng được trong nhóm."
        )

        return

    chat_id = update.effective_chat.id

    rules = get_rules(chat_id)

    if not rules:

        text = (
            "📜 NỘI QUY NHÓM\n\n"
            "⚠️ Nhóm chưa thiết lập nội quy.\n\n"
            "👑 Admin có thể dùng:\n"
            "/setrules <nội quy>"
        )

    else:

        text = (
            "📜 NỘI QUY NHÓM\n\n"
            f"{rules}"
        )

    text += owner_footer()

    await safe_reply(
        update,
        text
    )


# ============================================================
# /SETRULES
# ============================================================

async def setrules_command(
    update,
    context
):

    if not await require_admin(
        update,
        context
    ):
        return

    args = get_args(update)

    if not args:

        await safe_reply(
            update,
            "❌ Cách dùng:\n"
            "/setrules <nội quy mới>\n\n"
            "Ví dụ:\n"
            "/setrules Không spam, không quảng cáo, "
            "tôn trọng mọi người."
        )

        return

    rules_text = " ".join(args).strip()

    if len(rules_text) > 4000:

        await safe_reply(
            update,
            "❌ Nội quy quá dài.\n"
            "Vui lòng giữ nội quy dưới 4000 ký tự."
        )

        return

    chat_id = update.effective_chat.id

    set_rules(
        chat_id,
        rules_text
    )

    await save_db_async()

    await safe_reply(
        update,
        "✅ Đã cập nhật nội quy nhóm.\n\n"
        f"📜 Nội quy mới:\n{rules_text}"
        + owner_footer()
    )


# ============================================================
# HỖ TRỢ SETRULES BẰNG REPLY
# ============================================================

async def setrules_reply_command(
    update,
    context
):

    if not await require_admin(
        update,
        context
    ):
        return

    message = update.effective_message

    if not message:
        return

    replied = message.reply_to_message

    if not replied:
        return

    text = (
        replied.text
        or replied.caption
        or ""
    ).strip()

    if not text:

        await safe_reply(
            update,
            "❌ Tin nhắn được reply không có nội dung."
        )

        return

    if len(text) > 4000:

        await safe_reply(
            update,
            "❌ Nội quy quá dài.\n"
            "Vui lòng giữ dưới 4000 ký tự."
        )

        return

    chat_id = update.effective_chat.id

    set_rules(
        chat_id,
        text
    )

    await save_db_async()

    await safe_reply(
        update,
        "✅ Đã lấy nội dung tin nhắn làm nội quy nhóm."
        + owner_footer()
    )


# ============================================================
# HỖ TRỢ HIỂN THỊ NỘI QUY KHI NHÓM CHƯA CÓ
# ============================================================

def default_rules_text():

    return (
        "📜 NỘI QUY GỢI Ý\n\n"
        "1️⃣ Không spam tin nhắn.\n"
        "2️⃣ Không gửi link quảng cáo trái phép.\n"
        "3️⃣ Không xúc phạm hoặc gây mất đoàn kết.\n"
        "4️⃣ Không gửi nội dung làm ảnh hưởng đến nhóm.\n"
        "5️⃣ Tôn trọng thành viên và quản trị viên.\n"
        "6️⃣ Tuân thủ quyết định của admin.\n\n"
        "👑 Owner : @DTN_207"
    )


# ============================================================
# KẾT THÚC PHẦN 4/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 5/25
# MUTE / UNMUTE
# ============================================================


# ============================================================
# HÀM TẠO QUYỀN MUTE
# ============================================================

def muted_permissions():

    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


# ============================================================
# HÀM TẠO QUYỀN UNMUTE
# ============================================================

def normal_permissions():

    return ChatPermissions(
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
        can_invite_users=True,
        can_pin_messages=False,
        can_manage_topics=True,
    )


# ============================================================
# /MUTE
#
# Cách dùng:
# /mute @username 10m
# /mute 123456789 30m
# Reply tin nhắn rồi:
# /mute 10m
# ============================================================

async def mute_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy thành viên.\n\n"
            "Cách dùng:\n"
            "• Reply tin nhắn rồi /mute 10m\n"
            "• /mute @username 10m\n"
            "• /mute ID 10m"
        )

        return

    allowed, reason = await can_manage_target(
        update,
        context,
        target
    )

    if not allowed:

        await safe_reply(
            update,
            f"❌ {reason}"
        )

        return

    args = get_args(update)

    duration = None

    # Nếu reply: argument đầu tiên là thời gian
    if get_replied_user(update):

        if args:
            duration = parse_duration(
                args[0]
            )

    # Nếu không reply:
    # argument thứ hai là thời gian
    else:

        if len(args) >= 2:
            duration = parse_duration(
                args[1]
            )

    if duration is None:

        await safe_reply(
            update,
            "❌ Bạn chưa nhập thời gian mute hợp lệ.\n\n"
            "Ví dụ:\n"
            "/mute @username 10m\n"
            "/mute 123456789 1h\n\n"
            "Đơn vị:\n"
            "s = giây\n"
            "m = phút\n"
            "h = giờ\n"
            "d = ngày"
        )

        return

    if duration > 366 * 86400:

        await safe_reply(
            update,
            "❌ Thời gian mute tối đa là 366 ngày."
        )

        return

    chat_id = update.effective_chat.id

    if not await bot_can_restrict(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền hạn chế thành viên."
        )

        return

    until_date = datetime.now(
        timezone.utc
    ) + timedelta(
        seconds=duration
    )

    try:

        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target.id,
            permissions=muted_permissions(),
            until_date=until_date
        )

    except TelegramError as e:

        log_event(
            f"Lỗi mute {target.id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể mute thành viên này.\n"
            "Có thể bot chưa đủ quyền hoặc thành viên "
            "có quyền cao hơn bot."
        )

        return

    await safe_reply(
        update,
        "🔇 ĐÃ MUTE THÀNH VIÊN\n\n"
        f"👤 Thành viên: {user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n"
        f"⏱️ Thời gian: {format_duration(duration)}\n"
        f"👮 Người thực hiện: "
        f"{user_display_name(update.effective_user)}"
        + owner_footer()
    )


# ============================================================
# /UNMUTE
#
# Cách dùng:
# Reply tin nhắn:
# /unmute
#
# Hoặc:
# /unmute @username
# /unmute ID
# ============================================================

async def unmute_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy thành viên.\n\n"
            "Cách dùng:\n"
            "• Reply tin nhắn rồi /unmute\n"
            "• /unmute @username\n"
            "• /unmute ID"
        )

        return

    allowed, reason = await can_manage_target(
        update,
        context,
        target
    )

    if not allowed:

        await safe_reply(
            update,
            f"❌ {reason}"
        )

        return

    chat_id = update.effective_chat.id

    if not await bot_can_restrict(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền hạn chế thành viên."
        )

        return

    try:

        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target.id,
            permissions=normal_permissions()
        )

    except TelegramError as e:

        log_event(
            f"Lỗi unmute {target.id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể mở khóa thành viên này."
        )

        return

    await safe_reply(
        update,
        "🔊 ĐÃ UNMUTE THÀNH VIÊN\n\n"
        f"👤 Thành viên: {user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n"
        f"👮 Người thực hiện: "
        f"{user_display_name(update.effective_user)}"
        + owner_footer()
    )


# ============================================================
# TỰ ĐỘNG GỠ MUTE KHI HẾT THỜI GIAN
# ============================================================

async def auto_unmute_after(
    context,
    chat_id,
    user_id,
    duration
):

    try:

        await asyncio.sleep(duration)

        try:

            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=normal_permissions()
            )

            log_event(
                f"Đã tự động unmute "
                f"{user_id} tại {chat_id}"
            )

        except TelegramError as e:

            log_event(
                f"Lỗi auto unmute "
                f"{user_id}: {e}"
            )

    except asyncio.CancelledError:

        return


# ============================================================
# KẾT THÚC PHẦN 5/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 6/25
# BAN / UNBAN / KICK
# ============================================================


# ============================================================
# /BAN
#
# Cách dùng:
# Reply tin nhắn:
# /ban
#
# Hoặc:
# /ban @username
# /ban 123456789
# ============================================================

async def ban_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy thành viên.\n\n"
            "Cách dùng:\n"
            "• Reply tin nhắn rồi /ban\n"
            "• /ban @username\n"
            "• /ban ID"
        )

        return

    allowed, reason = await can_manage_target(
        update,
        context,
        target
    )

    if not allowed:

        await safe_reply(
            update,
            f"❌ {reason}"
        )

        return

    chat_id = update.effective_chat.id

    if not await bot_can_restrict(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền cấm thành viên."
        )

        return

    try:

        await context.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target.id
        )

    except TelegramError as e:

        log_event(
            f"Lỗi ban {target.id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể cấm thành viên này.\n"
            "Có thể bot chưa đủ quyền hoặc thành viên "
            "có quyền cao hơn bot."
        )

        return

    await safe_reply(
        update,
        "🔨 ĐÃ BAN THÀNH VIÊN\n\n"
        f"👤 Thành viên: {user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n"
        f"👮 Người thực hiện: "
        f"{user_display_name(update.effective_user)}"
        + owner_footer()
    )


# ============================================================
# /UNBAN
#
# Cách dùng:
# /unban 123456789
# /unban @username
# ============================================================

async def unban_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    args = get_args(update)

    target = await resolve_target_user(
        update,
        context
    )

    # Với user đã bị ban, resolve qua get_chat_member
    # có thể không lấy được nên hỗ trợ ID trực tiếp.
    target_id = None
    target_name = None

    if target:

        target_id = target.id
        target_name = user_display_name(target)

    elif args:

        raw = args[0].strip()

        if re.fullmatch(
            r"-?\d+",
            raw
        ):

            target_id = int(raw)
            target_name = str(target_id)

        else:

            username = raw.lstrip("@")

            # Tìm trong cache
            for cached_id, cached in user_cache.items():

                cached_username = cached.get(
                    "username"
                )

                if (
                    cached_username
                    and cached_username.lower()
                    == username.lower()
                ):

                    target_id = cached_id
                    target_name = cached.get(
                        "name",
                        str(cached_id)
                    )

                    break

    if target_id is None:

        await safe_reply(
            update,
            "❌ Không tìm thấy ID thành viên.\n\n"
            "Cách dùng:\n"
            "/unban 123456789\n"
            "hoặc /unban @username"
        )

        return

    chat_id = update.effective_chat.id

    if not await bot_can_restrict(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền gỡ cấm."
        )

        return

    try:

        await context.bot.unban_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            only_if_banned=True
        )

    except TelegramError as e:

        log_event(
            f"Lỗi unban {target_id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể gỡ cấm thành viên này."
        )

        return

    await safe_reply(
        update,
        "✅ ĐÃ GỠ BAN\n\n"
        f"👤 Thành viên: {target_name}\n"
        f"🆔 ID: {target_id}\n"
        f"👮 Người thực hiện: "
        f"{user_display_name(update.effective_user)}"
        + owner_footer()
    )


# ============================================================
# /KICK
#
# Kick = cấm rồi gỡ cấm ngay.
# Thành viên có thể tham gia lại nhóm nếu có link/quyền vào.
# ============================================================

async def kick_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy thành viên.\n\n"
            "Cách dùng:\n"
            "• Reply tin nhắn rồi /kick\n"
            "• /kick @username\n"
            "• /kick ID"
        )

        return

    allowed, reason = await can_manage_target(
        update,
        context,
        target
    )

    if not allowed:

        await safe_reply(
            update,
            f"❌ {reason}"
        )

        return

    chat_id = update.effective_chat.id

    if not await bot_can_restrict(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền đuổi thành viên."
        )

        return

    try:

        await context.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target.id
        )

        await context.bot.unban_chat_member(
            chat_id=chat_id,
            user_id=target.id
        )

    except TelegramError as e:

        log_event(
            f"Lỗi kick {target.id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể đuổi thành viên này."
        )

        return

    await safe_reply(
        update,
        "👢 ĐÃ KICK THÀNH VIÊN\n\n"
        f"👤 Thành viên: {user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n"
        f"👮 Người thực hiện: "
        f"{user_display_name(update.effective_user)}\n\n"
        "ℹ️ Thành viên đã bị đuổi khỏi nhóm."
        + owner_footer()
    )


# ============================================================
# KIỂM TRA THÀNH VIÊN CÓ ĐANG BỊ BAN
# ============================================================

async def is_user_banned(
    context,
    chat_id,
    user_id
):

    try:

        member = await context.bot.get_chat_member(
            chat_id,
            user_id
        )

        return (
            member.status
            == ChatMemberStatus.BANNED
        )

    except TelegramError:

        return False


# ============================================================
# KẾT THÚC PHẦN 6/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 7/25
# WARN / WARNINGS / CLEARWARN
# ============================================================


# ============================================================
# /WARN
#
# Cách dùng:
# Reply:
# /warn
# /warn spam
#
# Hoặc:
# /warn @username spam
# /warn 123456789 spam
# ============================================================

async def warn_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy thành viên.\n\n"
            "Cách dùng:\n"
            "• Reply tin nhắn rồi /warn\n"
            "• /warn @username spam\n"
            "• /warn ID spam"
        )

        return

    allowed, reason = await can_manage_target(
        update,
        context,
        target
    )

    if not allowed:

        await safe_reply(
            update,
            f"❌ {reason}"
        )

        return

    args = get_args(update)

    reason_text = "Không có lý do"

    # Reply: toàn bộ args là lý do
    if get_replied_user(update):

        if args:
            reason_text = " ".join(args)

    # Không reply:
    # arg 0 = target
    # arg còn lại = lý do
    else:

        if len(args) > 1:
            reason_text = " ".join(args[1:])

    chat_id = update.effective_chat.id
    admin = update.effective_user

    add_warn(
        chat_id=chat_id,
        user_id=target.id,
        reason=reason_text,
        admin_id=admin.id
    )

    await save_db_async()

    count = get_warn_count(
        chat_id,
        target.id
    )

    # --------------------------------------------------------
    # ĐỦ 3 WARN -> MUTE 30 PHÚT
    # --------------------------------------------------------

    if count >= 3:

        if await bot_can_restrict(
            context,
            chat_id
        ):

            try:

                until_date = (
                    datetime.now(timezone.utc)
                    + timedelta(minutes=30)
                )

                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=target.id,
                    permissions=muted_permissions(),
                    until_date=until_date
                )

                clear_warns(
                    chat_id,
                    target.id
                )

                await save_db_async()

                await safe_reply(
                    update,
                    "⚠️ THÀNH VIÊN ĐÃ ĐỦ 3 WARN\n\n"
                    f"👤 Thành viên: "
                    f"{user_display_name(target)}\n"
                    f"📝 Lý do cuối: {reason_text}\n"
                    "🔇 Hình phạt: Mute 30 phút\n"
                    "♻️ Số warn đã được đặt lại về 0."
                    + owner_footer()
                )

                return

            except TelegramError as e:

                log_event(
                    f"Lỗi tự mute sau warn: {e}"
                )

    await safe_reply(
        update,
        "⚠️ ĐÃ CẢNH CÁO\n\n"
        f"👤 Thành viên: {user_display_name(target)}\n"
        f"📝 Lý do: {reason_text}\n"
        f"⚠️ Số warn: {count}/3\n\n"
        "ℹ️ Đủ 3 warn sẽ bị mute 30 phút."
        + owner_footer()
    )


# ============================================================
# /WARNINGS
#
# Reply:
# /warnings
#
# Hoặc:
# /warnings @username
# /warnings ID
# ============================================================

async def warnings_command(
    update,
    context
):

    if not await require_group(update):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:
        target = update.effective_user

    if not target:
        return

    chat_id = update.effective_chat.id

    count = get_warn_count(
        chat_id,
        target.id
    )

    warnings = get_warns(
        chat_id,
        target.id
    )

    text = (
        "⚠️ LỊCH SỬ CẢNH CÁO\n\n"
        f"👤 Thành viên: "
        f"{user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n"
        f"⚠️ Tổng warn: {count}"
    )

    if not warnings:

        text += (
            "\n\n✅ Thành viên hiện không có cảnh cáo."
        )

    else:

        text += "\n\n📋 Chi tiết:\n"

        for index, item in enumerate(
            warnings,
            start=1
        ):

            reason = item.get(
                "reason",
                "Không có lý do"
            )

            warn_time = item.get(
                "time",
                ""
            )

            text += (
                f"\n{index}. {reason}"
            )

            if warn_time:

                try:

                    dt = datetime.fromisoformat(
                        warn_time
                    )

                    formatted = dt.strftime(
                        "%d/%m/%Y %H:%M"
                    )

                    text += (
                        f" — {formatted}"
                    )

                except Exception:
                    pass

    text += owner_footer()

    await safe_reply(
        update,
        text
    )


# ============================================================
# /CLEARWARN
#
# Admin mới được xóa warn.
#
# Reply:
# /clearwarn
#
# Hoặc:
# /clearwarn @username
# /clearwarn ID
# ============================================================

async def clearwarn_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy thành viên."
        )

        return

    allowed, reason = await can_manage_target(
        update,
        context,
        target
    )

    if not allowed:

        await safe_reply(
            update,
            f"❌ {reason}"
        )

        return

    chat_id = update.effective_chat.id

    old_count = get_warn_count(
        chat_id,
        target.id
    )

    clear_warns(
        chat_id,
        target.id
    )

    await save_db_async()

    await safe_reply(
        update,
        "✅ ĐÃ XÓA CẢNH CÁO\n\n"
        f"👤 Thành viên: "
        f"{user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n"
        f"🗑️ Đã xóa: {old_count} warn"
        + owner_footer()
    )


# ============================================================
# TỰ ĐỘNG CẢNH BÁO KHI SPAM
# ============================================================

async def auto_warn_spam(
    update,
    context,
    user
):

    if not user:
        return

    chat_id = update.effective_chat.id

    # Không tự warn admin/owner
    if is_owner(user):
        return

    if await is_admin(
        context,
        chat_id,
        user.id
    ):
        return

    add_warn(
        chat_id=chat_id,
        user_id=user.id,
        reason="Spam tin nhắn",
        admin_id=0
    )

    await save_db_async()

    count = get_warn_count(
        chat_id,
        user.id
    )

    return count


# ============================================================
# LẤY THÔNG TIN WARN AN TOÀN
# ============================================================

def warning_summary(
    chat_id,
    user_id
):

    count = get_warn_count(
        chat_id,
        user_id
    )

    if count <= 0:

        return "Không có cảnh cáo."

    return f"{count}/3 cảnh cáo."


# ============================================================
# KẾT THÚC PHẦN 7/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 8/25
# PROMOTE / PROMOTEFULL / DEMOTE
# ============================================================


# ============================================================
# LẤY QUYỀN ADMIN HIỆN TẠI CỦA USER
# ============================================================

async def get_admin_rights(
    context,
    chat_id,
    user_id
):

    try:

        member = await context.bot.get_chat_member(
            chat_id,
            user_id
        )

        return {
            "can_manage_chat": getattr(
                member,
                "can_manage_chat",
                False
            ),
            "can_delete_messages": getattr(
                member,
                "can_delete_messages",
                False
            ),
            "can_manage_video_chats": getattr(
                member,
                "can_manage_video_chats",
                False
            ),
            "can_restrict_members": getattr(
                member,
                "can_restrict_members",
                False
            ),
            "can_promote_members": getattr(
                member,
                "can_promote_members",
                False
            ),
            "can_change_info": getattr(
                member,
                "can_change_info",
                False
            ),
            "can_invite_users": getattr(
                member,
                "can_invite_users",
                False
            ),
            "can_pin_messages": getattr(
                member,
                "can_pin_messages",
                False
            ),
            "can_manage_topics": getattr(
                member,
                "can_manage_topics",
                False
            ),
        }

    except TelegramError:

        return {}


# ============================================================
# KIỂM TRA BOT CÓ QUYỀN PROMOTE
# ============================================================

async def require_promote_permission(
    update,
    context
):

    if not await require_admin(
        update,
        context
    ):
        return False

    chat_id = update.effective_chat.id

    if not await bot_can_promote(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền thêm quản trị viên."
        )

        return False

    return True


# ============================================================
# /PROMOTE
#
# Cách dùng:
# Reply:
# /promote
#
# Hoặc:
# /promote @username
# /promote ID
# ============================================================

async def promote_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_promote_permission(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy thành viên.\n\n"
            "Cách dùng:\n"
            "• Reply tin nhắn rồi /promote\n"
            "• /promote @username\n"
            "• /promote ID"
        )

        return

    allowed, reason = await can_manage_target(
        update,
        context,
        target
    )

    if not allowed:

        await safe_reply(
            update,
            f"❌ {reason}"
        )

        return

    chat_id = update.effective_chat.id

    try:

        await context.bot.promote_chat_member(
            chat_id=chat_id,
            user_id=target.id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
            can_manage_topics=False
        )

    except TelegramError as e:

        log_event(
            f"Lỗi promote {target.id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể thăng chức thành viên.\n"
            "Hãy kiểm tra quyền của DTN BOT."
        )

        return

    await safe_reply(
        update,
        "👑 ĐÃ PROMOTE\n\n"
        f"👤 Thành viên: {user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n"
        "🛡️ Quyền: Admin cơ bản"
        + owner_footer()
    )


# ============================================================
# /PROMOTEFULL
#
# Thăng admin với nhiều quyền quản lý.
# ============================================================

async def promotefull_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_promote_permission(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy thành viên.\n\n"
            "Cách dùng:\n"
            "• Reply tin nhắn rồi /promotefull\n"
            "• /promotefull @username\n"
            "• /promotefull ID"
        )

        return

    allowed, reason = await can_manage_target(
        update,
        context,
        target
    )

    if not allowed:

        await safe_reply(
            update,
            f"❌ {reason}"
        )

        return

    chat_id = update.effective_chat.id

    try:

        await context.bot.promote_chat_member(
            chat_id=chat_id,
            user_id=target.id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_topics=True
        )

    except TelegramError as e:

        log_event(
            f"Lỗi promotefull {target.id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể cấp đầy đủ quyền admin.\n"
            "Có thể DTN BOT chưa có đủ quyền."
        )

        return

    await safe_reply(
        update,
        "👑 ĐÃ PROMOTEFULL\n\n"
        f"👤 Thành viên: {user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n\n"
        "🛡️ Đã cấp các quyền quản lý chính."
        + owner_footer()
    )


# ============================================================
# /DEMOTE
#
# Cách dùng:
# Reply:
# /demote
#
# Hoặc:
# /demote @username
# /demote ID
# ============================================================

async def demote_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    target = await resolve_target_user(
        update,
        context
    )

    if not target:

        await safe_reply(
            update,
            "❌ Không tìm thấy admin.\n\n"
            "Cách dùng:\n"
            "• Reply tin nhắn rồi /demote\n"
            "• /demote @username\n"
            "• /demote ID"
        )

        return

    # Không thể hạ Owner
    if is_owner(target):

        await safe_reply(
            update,
            "❌ Không thể hạ quyền Owner."
        )

        return

    # Không thể hạ chủ nhóm
    try:

        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            target.id
        )

        if member.status == ChatMemberStatus.OWNER:

            await safe_reply(
                update,
                "❌ Không thể hạ quyền chủ nhóm."
            )

            return

    except TelegramError:

        pass

    chat_id = update.effective_chat.id

    # Người thực hiện phải có quyền promote
    if not await bot_can_promote(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền hạ quyền admin."
        )

        return

    try:

        await context.bot.promote_chat_member(
            chat_id=chat_id,
            user_id=target.id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_manage_video_chats=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False
        )

    except TelegramError as e:

        log_event(
            f"Lỗi demote {target.id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể hạ quyền admin."
        )

        return

    await safe_reply(
        update,
        "⬇️ ĐÃ DEMOTE\n\n"
        f"👤 Thành viên: {user_display_name(target)}\n"
        f"🆔 ID: {target.id}\n"
        "👤 Đã trở về quyền thành viên."
        + owner_footer()
    )


# ============================================================
# KIỂM TRA ADMIN CÓ QUYỀN THĂNG NGƯỜI KHÁC
# ============================================================

async def can_promote_target(
    context,
    chat_id,
    user_id
):

    try:

        member = await context.bot.get_chat_member(
            chat_id,
            user_id
        )

        if member.status == ChatMemberStatus.OWNER:
            return True

        return bool(
            getattr(
                member,
                "can_promote_members",
                False
            )
        )

    except TelegramError:

        return False


# ============================================================
# KẾT THÚC PHẦN 8/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 9/25
# DEL / PIN / UNPIN / LOCK / UNLOCK
# ============================================================


# ============================================================
# /DEL
#
# Cách dùng:
# Reply tin nhắn rồi:
# /del
# ============================================================

async def del_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    message = update.effective_message

    if not message:
        return

    replied = message.reply_to_message

    if not replied:

        await safe_reply(
            update,
            "❌ Hãy reply vào tin nhắn cần xóa rồi dùng /del."
        )

        return

    chat_id = update.effective_chat.id

    if not await bot_can_delete(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền xóa tin nhắn."
        )

        return

    target_message_id = replied.message_id

    deleted_target = await safe_delete_message(
        context,
        chat_id,
        target_message_id
    )

    # Xóa luôn lệnh /del
    await safe_delete_message(
        context,
        chat_id,
        message.message_id
    )

    if not deleted_target:

        await safe_send_message(
            context,
            chat_id,
            "❌ Không thể xóa tin nhắn đó."
        )


# ============================================================
# /PIN
#
# Cách dùng:
# Reply tin nhắn rồi:
# /pin
# ============================================================

async def pin_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    message = update.effective_message

    if not message:
        return

    replied = message.reply_to_message

    if not replied:

        await safe_reply(
            update,
            "❌ Hãy reply vào tin nhắn cần ghim rồi dùng /pin."
        )

        return

    chat_id = update.effective_chat.id

    if not await bot_can_pin(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền ghim tin nhắn."
        )

        return

    try:

        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=replied.message_id,
            disable_notification=False
        )

    except TelegramError as e:

        log_event(
            f"Lỗi pin: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể ghim tin nhắn."
        )

        return

    await safe_reply(
        update,
        "📌 Đã ghim tin nhắn thành công."
        + owner_footer()
    )


# ============================================================
# /UNPIN
#
# Cách dùng:
# Reply tin nhắn đã ghim rồi:
# /unpin
#
# Không reply:
# /unpin
# -> bỏ ghim tin nhắn ghim hiện tại
# ============================================================

async def unpin_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    chat_id = update.effective_chat.id

    if not await bot_can_pin(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền bỏ ghim."
        )

        return

    message = update.effective_message

    try:

        if (
            message
            and message.reply_to_message
        ):

            await context.bot.unpin_chat_message(
                chat_id=chat_id,
                message_id=(
                    message
                    .reply_to_message
                    .message_id
                )
            )

        else:

            await context.bot.unpin_chat_message(
                chat_id=chat_id
            )

    except TelegramError as e:

        log_event(
            f"Lỗi unpin: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể bỏ ghim tin nhắn."
        )

        return

    await safe_reply(
        update,
        "📌 Đã bỏ ghim tin nhắn."
        + owner_footer()
    )


# ============================================================
# TẠO QUYỀN LOCK
# ============================================================

def locked_permissions():

    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


# ============================================================
# /LOCK
#
# Khóa toàn bộ thành viên thường.
# Admin vẫn có thể chat.
# ============================================================

async def lock_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    chat_id = update.effective_chat.id

    if not await bot_can_restrict(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền khóa chat."
        )

        return

    try:

        await context.bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=locked_permissions()
        )

    except TelegramError as e:

        log_event(
            f"Lỗi lock {chat_id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể khóa chat nhóm."
        )

        return

    settings = get_chat_settings(
        chat_id
    )

    settings["locked"] = True

    await save_db_async()

    await safe_reply(
        update,
        "🔒 ĐÃ KHÓA CHAT\n\n"
        "🚫 Thành viên thường không thể gửi tin nhắn.\n"
        "👮 Admin vẫn có thể quản lý nhóm."
        + owner_footer()
    )


# ============================================================
# /UNLOCK
#
# Mở lại quyền chat cho thành viên.
# ============================================================

async def unlock_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    chat_id = update.effective_chat.id

    if not await bot_can_restrict(
        context,
        chat_id
    ):

        await safe_reply(
            update,
            "❌ DTN BOT chưa có quyền mở khóa chat."
        )

        return

    try:

        await context.bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=normal_permissions()
        )

    except TelegramError as e:

        log_event(
            f"Lỗi unlock {chat_id}: {e}"
        )

        await safe_reply(
            update,
            "❌ Không thể mở khóa chat nhóm."
        )

        return

    settings = get_chat_settings(
        chat_id
    )

    settings["locked"] = False

    await save_db_async()

    await safe_reply(
        update,
        "🔓 ĐÃ MỞ KHÓA CHAT\n\n"
        "✅ Thành viên có thể gửi tin nhắn trở lại."
        + owner_footer()
    )


# ============================================================
# KIỂM TRA TRẠNG THÁI LOCK
# ============================================================

def is_chat_locked(chat_id):

    settings = get_chat_settings(
        chat_id
    )

    return bool(
        settings.get(
            "locked",
            False
        )
    )


# ============================================================
# KẾT THÚC PHẦN 9/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 10/25
# ANTILINK / ANTISPAM
# ============================================================


# ============================================================
# /ANTILINK
#
# /antilink on
# /antilink off
# ============================================================

async def antilink_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    chat_id = update.effective_chat.id
    args = get_args(update)

    if not args:

        status = (
            "🟢 ĐANG BẬT"
            if antilink_enabled[chat_id]
            else "🔴 ĐANG TẮT"
        )

        await safe_reply(
            update,
            "🛡️ ANTILINK\n\n"
            f"Trạng thái: {status}\n\n"
            "Cách dùng:\n"
            "/antilink on\n"
            "/antilink off"
        )

        return

    mode = args[0].lower()

    if mode in (
        "on",
        "1",
        "true",
        "bat",
        "bật"
    ):

        antilink_enabled[chat_id] = True

        settings = get_chat_settings(
            chat_id
        )

        settings["antilink"] = True

        await save_db_async()

        await safe_reply(
            update,
            "🛡️ ĐÃ BẬT ANTILINK\n\n"
            "🚫 Link gửi bởi thành viên thường "
            "sẽ bị xóa."
            + owner_footer()
        )

        return

    if mode in (
        "off",
        "0",
        "false",
        "tat",
        "tắt"
    ):

        antilink_enabled[chat_id] = False

        settings = get_chat_settings(
            chat_id
        )

        settings["antilink"] = False

        await save_db_async()

        await safe_reply(
            update,
            "🛡️ ĐÃ TẮT ANTILINK."
            + owner_footer()
        )

        return

    await safe_reply(
        update,
        "❌ Giá trị không hợp lệ.\n\n"
        "Dùng:\n"
        "/antilink on\n"
        "/antilink off"
    )


# ============================================================
# /ANTISPAM
#
# /antispam on
# /antispam off
# ============================================================

async def antispam_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    chat_id = update.effective_chat.id
    args = get_args(update)

    if not args:

        status = (
            "🟢 ĐANG BẬT"
            if antispam_enabled[chat_id]
            else "🔴 ĐANG TẮT"
        )

        await safe_reply(
            update,
            "🛡️ ANTISPAM\n\n"
            f"Trạng thái: {status}\n\n"
            "Cách dùng:\n"
            "/antispam on\n"
            "/antispam off"
        )

        return

    mode = args[0].lower()

    if mode in (
        "on",
        "1",
        "true",
        "bat",
        "bật"
    ):

        antispam_enabled[chat_id] = True

        settings = get_chat_settings(
            chat_id
        )

        settings["antispam"] = True

        await save_db_async()

        await safe_reply(
            update,
            "🛡️ ĐÃ BẬT ANTISPAM\n\n"
            "⚡ DTN BOT sẽ phát hiện thành viên "
            "gửi quá nhiều tin nhắn liên tiếp."
            + owner_footer()
        )

        return

    if mode in (
        "off",
        "0",
        "false",
        "tat",
        "tắt"
    ):

        antispam_enabled[chat_id] = False

        settings = get_chat_settings(
            chat_id
        )

        settings["antispam"] = False

        await save_db_async()

        await safe_reply(
            update,
            "🛡️ ĐÃ TẮT ANTISPAM."
            + owner_footer()
        )

        return

    await safe_reply(
        update,
        "❌ Giá trị không hợp lệ.\n\n"
        "Dùng:\n"
        "/antispam on\n"
        "/antispam off"
    )


# ============================================================
# LẤY TRẠNG THÁI ANTILINK
# ============================================================

def get_antilink_status(chat_id):

    settings = get_chat_settings(
        chat_id
    )

    if "antilink" in settings:

        return bool(
            settings["antilink"]
        )

    return bool(
        antilink_enabled[chat_id]
    )


# ============================================================
# LẤY TRẠNG THÁI ANTISPAM
# ============================================================

def get_antispam_status(chat_id):

    settings = get_chat_settings(
        chat_id
    )

    if "antispam" in settings:

        return bool(
            settings["antispam"]
        )

    return bool(
        antispam_enabled[chat_id]
    )


# ============================================================
# KIỂM TRA TIN NHẮN CÓ PHẢI COMMAND KHÔNG
# ============================================================

def is_command_message(message):

    if not message:
        return False

    text = message.text or ""

    return text.startswith("/")


# ============================================================
# KIỂM TRA NGƯỜI GỬI CÓ ĐƯỢC MIỄN ANTILINK KHÔNG
# ============================================================

async def is_exempt_from_antilink(
    update,
    context
):

    user = update.effective_user

    if not user:
        return True

    if is_owner(user):
        return True

    return await is_admin(
        context,
        update.effective_chat.id,
        user.id
    )


# ============================================================
# XỬ LÝ ANTILINK
# ============================================================

async def process_antilink(
    update,
    context
):

    if not is_group(update):
        return False

    message = update.effective_message

    if not message:
        return False

    if not get_antilink_status(
        update.effective_chat.id
    ):
        return False

    text = (
        message.text
        or message.caption
        or ""
    )

    if not contains_link(text):
        return False

    if await is_exempt_from_antilink(
        update,
        context
    ):
        return False

    if not await bot_can_delete(
        context,
        update.effective_chat.id
    ):
        return False

    deleted = await safe_delete_message(
        context,
        update.effective_chat.id,
        message.message_id
    )

    if deleted:

        warning = await safe_send_message(
            context,
            update.effective_chat.id,
            "🚫 Tin nhắn chứa link đã bị xóa."
        )

        if warning:

            create_background_task(
                delete_later(
                    context,
                    warning.chat_id,
                    warning.message_id,
                    5
                )
            )

    return deleted


# ============================================================
# XÓA MESSAGE SAU MỘT KHOẢNG THỜI GIAN
# ============================================================

async def delete_later(
    context,
    chat_id,
    message_id,
    seconds
):

    try:

        await asyncio.sleep(
            seconds
        )

        await safe_delete_message(
            context,
            chat_id,
            message_id
        )

    except asyncio.CancelledError:

        return

    except Exception as e:

        log_event(
            f"Lỗi delete_later: {e}"
        )


# ============================================================
# GHI NHẬN TIN NHẮN SPAM
# ============================================================

def record_spam_message(
    chat_id,
    user_id
):

    current_time = time.monotonic()

    queue = spam_cache[
        chat_id
    ][
        user_id
    ]

    queue.append(
        current_time
    )

    # Chỉ giữ tin nhắn trong 5 giây
    while queue:

        if (
            current_time
            - queue[0]
            > 5
        ):

            queue.popleft()

        else:

            break

    return len(queue)


# ============================================================
# RESET CACHE SPAM
# ============================================================

def reset_spam_user(
    chat_id,
    user_id
):

    try:

        spam_cache[
            chat_id
        ].pop(
            user_id,
            None
        )

    except Exception:

        pass


# ============================================================
# XỬ LÝ ANTISPAM
#
# 5 tin nhắn trong 5 giây:
# -> Xóa các tin nhắn có thể xóa
# -> Mute 30 giây
# ============================================================

async def process_antispam(
    update,
    context
):

    if not is_group(update):
        return False

    message = update.effective_message

    user = update.effective_user

    if not message or not user:
        return False

    chat_id = update.effective_chat.id

    if not get_antispam_status(
        chat_id
    ):
        return False

    if is_owner(user):
        return False

    if await is_admin(
        context,
        chat_id,
        user.id
    ):
        return False

    count = record_spam_message(
        chat_id,
        user.id
    )

    # Chưa đạt ngưỡng
    if count < 5:
        return False

    # Reset ngay để không kích hoạt liên tục
    reset_spam_user(
        chat_id,
        user.id
    )

    # Bot cần quyền restrict
    can_restrict = await bot_can_restrict(
        context,
        chat_id
    )

    can_delete = await bot_can_delete(
        context,
        chat_id
    )

    if can_delete:

        # Xóa tin nhắn spam hiện tại
        await safe_delete_message(
            context,
            chat_id,
            message.message_id
        )

    if can_restrict:

        try:

            until_date = (
                datetime.now(timezone.utc)
                + timedelta(seconds=30)
            )

            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user.id,
                permissions=muted_permissions(),
                until_date=until_date
            )

            notice = await safe_send_message(
                context,
                chat_id,
                "🛑 PHÁT HIỆN SPAM\n\n"
                f"👤 {user_display_name(user)}\n"
                "🔇 Đã bị mute 30 giây."
            )

            if notice:

                create_background_task(
                    delete_later(
                        context,
                        chat_id,
                        notice.message_id,
                        8
                    )
                )

            return True

        except TelegramError as e:

            log_event(
                f"Lỗi antispam mute {user.id}: {e}"
            )

    return False


# ============================================================
# KẾT THÚC PHẦN 10/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 11/25
# FILTER — BỘ LỌC TỪ KHÓA
# ============================================================

def get_filters(chat_id):

    key = str(chat_id)

    if key not in db["filters"]:
        db["filters"][key] = {}

    return db["filters"][key]


def normalize_filter_word(text):

    if not text:
        return ""

    return normalize_text(
        text.strip()
    )


def filter_matches(text, keyword):

    if not text:
        return False

    if not keyword:
        return False

    normalized_text = normalize_text(text)
    normalized_keyword = normalize_filter_word(keyword)

    if not normalized_keyword:
        return False

    return normalized_keyword in normalized_text


# ============================================================
# /filter
# Cú pháp:
# /filter từ_khóa
# /filter từ_khóa nội_dung_trả_lời
# ============================================================

async def filter_command(update, context):

    if not await require_group(update):
        return

    if not await require_admin(update, context):
        return

    if not await require_group(update):
        return

    args = get_args(update)

    if not args:

        await safe_reply(
            update,
            "❌ Cú pháp:\n"
            "/filter từ_khóa\n\n"
            "Hoặc:\n"
            "/filter từ_khóa nội_dung_trả_lời\n\n"
            "Ví dụ:\n"
            "/filter spam\n"
            "/filter quảng cáo Không được quảng cáo trong nhóm."
        )

        return

    keyword = args[0].strip()

    if len(keyword) > 100:

        await safe_reply(
            update,
            "❌ Từ khóa quá dài."
        )

        return

    filters_data = get_filters(
        update.effective_chat.id
    )

    normalized_keyword = normalize_filter_word(
        keyword
    )

    response = ""

    if len(args) > 1:

        response = " ".join(args[1:]).strip()

        if len(response) > 1000:

            await safe_reply(
                update,
                "❌ Nội dung trả lời quá dài."
            )

            return

    filters_data[normalized_keyword] = {
        "keyword": keyword,
        "response": response,
        "admin_id": update.effective_user.id,
        "created_at": now_vn().isoformat(),
    }

    await save_db_async()

    if response:

        await safe_reply(
            update,
            "✅ Đã tạo bộ lọc.\n\n"
            f"🔎 Từ khóa: {keyword}\n"
            f"💬 Phản hồi: {response}"
        )

    else:

        await safe_reply(
            update,
            "✅ Đã tạo bộ lọc.\n\n"
            f"🔎 Từ khóa: {keyword}\n"
            "🗑️ Tin nhắn chứa từ khóa sẽ bị xóa."
        )


# ============================================================
# /filters
# Xem danh sách bộ lọc
# ============================================================

async def filters_command(update, context):

    if not await require_group(update):
        return

    if not await require_admin(update, context):
        return

    if not await require_group(update):
        return

    filters_data = get_filters(
        update.effective_chat.id
    )

    if not filters_data:

        await safe_reply(
            update,
            "📭 Nhóm chưa có bộ lọc nào."
        )

        return

    lines = [
        "🛡️ DANH SÁCH BỘ LỌC",
        ""
    ]

    index = 1

    for data in filters_data.values():

        keyword = data.get(
            "keyword",
            ""
        )

        response = data.get(
            "response",
            ""
        )

        if response:

            lines.append(
                f"{index}. 🔎 {keyword}"
                f" → {response}"
            )

        else:

            lines.append(
                f"{index}. 🔎 {keyword}"
                " → 🗑️ Xóa tin nhắn"
            )

        index += 1

    await safe_reply(
        update,
        "\n".join(lines)
    )


# ============================================================
# /stopfilter
# Cú pháp:
# /stopfilter từ_khóa
# ============================================================

async def stopfilter_command(update, context):

    if not await require_group(update):
        return

    if not await require_admin(update, context):
        return

    if not await require_group(update):
        return

    args = get_args(update)

    if not args:

        await safe_reply(
            update,
            "❌ Cú pháp:\n"
            "/stopfilter từ_khóa\n\n"
            "Ví dụ:\n"
            "/stopfilter spam"
        )

        return

    keyword = normalize_filter_word(
        args[0]
    )

    filters_data = get_filters(
        update.effective_chat.id
    )

    if keyword not in filters_data:

        await safe_reply(
            update,
            "❌ Không tìm thấy bộ lọc này."
        )

        return

    original_keyword = filters_data[
        keyword
    ].get(
        "keyword",
        args[0]
    )

    del filters_data[keyword]

    await save_db_async()

    await safe_reply(
        update,
        "✅ Đã xóa bộ lọc:\n"
        f"🔎 {original_keyword}"
    )


# ============================================================
# XỬ LÝ FILTER KHI CÓ TIN NHẮN
# ============================================================

async def process_filter(update, context):

    if not is_group(update):
        return

    message = update.effective_message

    if not message:
        return

    text = get_message_text(update)

    if not text:
        return

    chat_id = update.effective_chat.id

    filters_data = get_filters(chat_id)

    if not filters_data:
        return

    user = update.effective_user

    if not user:
        return

    # Admin và Owner được miễn filter
    if is_owner(user):
        return

    if await is_admin(
        context,
        chat_id,
        user.id
    ):
        return

    matched_filter = None

    for normalized_keyword, data in filters_data.items():

        if filter_matches(
            text,
            normalized_keyword
        ):

            matched_filter = data
            break

    if not matched_filter:
        return

    # Xóa tin nhắn vi phạm
    deleted = await safe_delete_message(
        context,
        chat_id,
        message.message_id
    )

    response = matched_filter.get(
        "response",
        ""
    )

    if response:

        sent = await safe_send_message(
            context,
            chat_id,
            response
        )

        if sent:

            create_background_task(
                delete_later(
                    context,
                    chat_id,
                    sent.message_id,
                    8
                )
            )

    elif deleted:

        sent = await safe_send_message(
            context,
            chat_id,
            "⚠️ Tin nhắn của bạn chứa "
            "từ khóa bị cấm."
        )

        if sent:

            create_background_task(
                delete_later(
                    context,
                    chat_id,
                    sent.message_id,
                    5
                )
            )


# ============================================================
# KẾT THÚC PHẦN 11/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 12/25
# AFK + MENTION + QUAY LẠI
# ============================================================

# ============================================================
# /afk
# Cú pháp:
# /afk
# /afk lý do
# ============================================================

async def afk_command(update, context):

    if not await require_group(update):
        return

    if not await require_group(update):
        return

    user = update.effective_user

    if not user:
        return

    chat_id = update.effective_chat.id

    reason = "Không có lý do."

    args = get_args(update)

    if args:
        reason = " ".join(args).strip()

    afk_key = user_key(
        chat_id,
        user.id
    )

    afk_users[afk_key] = {
        "user_id": user.id,
        "name": user_display_name(user),
        "reason": reason,
        "time": time.time(),
    }

    cache_user(user)
    register_owner(user)

    await safe_reply(
        update,
        "💤 Đã bật trạng thái AFK.\n\n"
        f"👤 {user_display_name(user)}\n"
        f"📝 Lý do: {reason}"
    )


# ============================================================
# XÓA AFK
# ============================================================

def remove_afk(chat_id, user_id):

    key = user_key(
        chat_id,
        user_id
    )

    return afk_users.pop(
        key,
        None
    )


# ============================================================
# FORMAT THỜI GIAN AFK
# ============================================================

def format_afk_time(start_time):

    elapsed = int(
        max(
            0,
            time.time() - start_time
        )
    )

    if elapsed < 60:
        return f"{elapsed} giây"

    if elapsed < 3600:
        return f"{elapsed // 60} phút"

    if elapsed < 86400:
        return f"{elapsed // 3600} giờ"

    return f"{elapsed // 86400} ngày"


# ============================================================
# KIỂM TRA MENTION
# ============================================================

async def process_afk_mentions(
    update,
    context
):

    if not is_group(update):
        return

    message = update.effective_message

    if not message:
        return

    text = get_message_text(update)

    if not text:
        return

    chat_id = update.effective_chat.id

    # --------------------------------------------------------
    # 1. Kiểm tra người gửi có đang AFK không
    # --------------------------------------------------------

    sender = update.effective_user

    if sender:

        sender_key = user_key(
            chat_id,
            sender.id
        )

        if sender_key in afk_users:

            data = remove_afk(
                chat_id,
                sender.id
            )

            if data:

                duration = format_afk_time(
                    data.get(
                        "time",
                        time.time()
                    )
                )

                await safe_send_message(
                    context,
                    chat_id,
                    "👋 Chào mừng bạn quay lại!\n\n"
                    f"👤 {user_display_name(sender)}\n"
                    f"⏱️ AFK: {duration}\n"
                    "✅ Trạng thái AFK đã được tắt."
                )

    # --------------------------------------------------------
    # 2. Kiểm tra reply vào người đang AFK
    # --------------------------------------------------------

    replied_user = None

    if message.reply_to_message:

        replied_user = (
            message.reply_to_message.from_user
        )

    if replied_user:

        afk_key = user_key(
            chat_id,
            replied_user.id
        )

        data = afk_users.get(
            afk_key
        )

        if data:

            duration = format_afk_time(
                data.get(
                    "time",
                    time.time()
                )
            )

            reason = data.get(
                "reason",
                "Không có lý do."
            )

            await safe_send_message(
                context,
                chat_id,
                "💤 Người này đang AFK.\n\n"
                f"👤 {data.get('name', 'Không rõ')}\n"
                f"📝 Lý do: {reason}\n"
                f"⏱️ Đã AFK: {duration}"
            )

            return

    # --------------------------------------------------------
    # 3. Kiểm tra @username
    # --------------------------------------------------------

    mentioned_usernames = re.findall(
        r"@([A-Za-z0-9_]{5,32})",
        text
    )

    if not mentioned_usernames:
        return

    mentioned_usernames = {
        username.lower()
        for username in mentioned_usernames
    }

    notified = set()

    for afk_key, data in list(
        afk_users.items()
    ):

        try:

            key_chat, key_user = (
                afk_key.split(":", 1)
            )

            if int(key_chat) != chat_id:
                continue

            username = None

            cached = user_cache.get(
                int(key_user)
            )

            if cached:
                username = cached.get(
                    "username"
                )

            if not username:
                continue

            if username.lower() not in mentioned_usernames:
                continue

            user_id = int(key_user)

            if user_id in notified:
                continue

            notified.add(user_id)

            duration = format_afk_time(
                data.get(
                    "time",
                    time.time()
                )
            )

            reason = data.get(
                "reason",
                "Không có lý do."
            )

            await safe_send_message(
                context,
                chat_id,
                "💤 Người này đang AFK.\n\n"
                f"👤 {data.get('name', 'Không rõ')}\n"
                f"📝 Lý do: {reason}\n"
                f"⏱️ Đã AFK: {duration}"
            )

        except Exception as e:

            log_event(
                f"Lỗi xử lý AFK mention: {e}"
            )


# ============================================================
# CACHE USER TỪ MESSAGE
# ============================================================

async def cache_message_user(
    update,
    context
):

    user = update.effective_user

    if not user:
        return

    cache_user(user)
    register_owner(user)


# ============================================================
# XỬ LÝ NGƯỜI DÙNG QUAY LẠI
# ============================================================

async def process_afk_return(
    update,
    context
):

    if not is_group(update):
        return

    user = update.effective_user

    if not user:
        return

    chat_id = update.effective_chat.id

    key = user_key(
        chat_id,
        user.id
    )

    if key not in afk_users:
        return

    data = remove_afk(
        chat_id,
        user.id
    )

    if not data:
        return

    duration = format_afk_time(
        data.get(
            "time",
            time.time()
        )
    )

    await safe_send_message(
        context,
        chat_id,
        "👋 Chào mừng quay lại!\n"
        f"👤 {user_display_name(user)}\n"
        f"⏱️ AFK: {duration}"
    )


# ============================================================
# KẾT THÚC PHẦN 12/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 13/25
# WELCOME / LEAVE + XỬ LÝ TIN NHẮN CHUNG
# ============================================================

# ============================================================
# CÀI ĐẶT WELCOME
# ============================================================

def get_welcome_setting(chat_id):

    settings = get_chat_settings(chat_id)

    if "welcome" not in settings:
        settings["welcome"] = True

    return settings["welcome"]


def get_leave_setting(chat_id):

    settings = get_chat_settings(chat_id)

    if "leave" not in settings:
        settings["leave"] = True

    return settings["leave"]


# ============================================================
# TẠO NỘI DUNG WELCOME
# ============================================================

def build_welcome_text(user):

    return (
        "🎉 Chào mừng thành viên mới!\n\n"
        f"👤 {user_display_name(user)}\n"
        "🤖 Chúc bạn có những giây phút vui vẻ "
        "trong nhóm DTN BOT!"
    )


# ============================================================
# TẠO NỘI DUNG LEAVE
# ============================================================

def build_leave_text(user):

    return (
        "👋 Thành viên đã rời nhóm.\n\n"
        f"👤 {user_display_name(user)}"
    )


# ============================================================
# XỬ LÝ THÀNH VIÊN MỚI
# ============================================================

async def new_member_handler(
    update,
    context
):

    if not is_group(update):
        return

    message = update.effective_message

    if not message:
        return

    chat_id = update.effective_chat.id

    if not get_welcome_setting(chat_id):
        return

    new_members = (
        message.new_chat_members
        or []
    )

    if not new_members:
        return

    for user in new_members:

        cache_user(user)
        register_owner(user)

        # Nếu chính bot được thêm vào nhóm
        try:

            me = await context.bot.get_me()

            if user.id == me.id:

                await safe_reply(
                    update,
                    "🤖 DTN BOT đã được thêm vào nhóm!\n\n"
                    "Hãy cấp quyền quản trị cần thiết "
                    "để bot có thể thực hiện các chức năng "
                    "quản lý và bảo vệ nhóm."
                )

                continue

        except TelegramError:
            pass

        await safe_send_message(
            context,
            chat_id,
            build_welcome_text(user)
        )


# ============================================================
# XỬ LÝ THÀNH VIÊN RỜI NHÓM
# ============================================================

async def left_member_handler(
    update,
    context
):

    if not is_group(update):
        return

    message = update.effective_message

    if not message:
        return

    chat_id = update.effective_chat.id

    if not get_leave_setting(chat_id):
        return

    left_user = (
        message.left_chat_member
    )

    if not left_user:
        return

    cache_user(left_user)

    # Xóa AFK nếu người dùng rời nhóm
    remove_afk(
        chat_id,
        left_user.id
    )

    await safe_send_message(
        context,
        chat_id,
        build_leave_text(left_user)
    )


# ============================================================
# KIỂM TRA TIN NHẮN TEXT CHUNG
# ============================================================

async def general_message_handler(
    update,
    context
):

    if not is_group(update):
        return

    message = update.effective_message

    if not message:
        return

    user = update.effective_user

    if not user:
        return

    cache_user(user)
    register_owner(user)

    # --------------------------------------------------------
    # AFK
    # --------------------------------------------------------

    await process_afk_mentions(
        update,
        context
    )

    # --------------------------------------------------------
    # FILTER
    # --------------------------------------------------------

    await process_filter(
        update,
        context
    )

    # --------------------------------------------------------
    # ANTILINK
    # --------------------------------------------------------

    await process_antilink(
        update,
        context
    )

    # --------------------------------------------------------
    # ANTISPAM
    # --------------------------------------------------------

    await process_antispam(
        update,
        context
    )


# ============================================================
# XỬ LÝ ẢNH / VIDEO / FILE / MEDIA
# ============================================================

async def media_message_handler(
    update,
    context
):

    if not is_group(update):
        return

    user = update.effective_user

    if user:
        cache_user(user)
        register_owner(user)

    # Các chức năng bảo vệ vẫn được xử lý
    # dựa trên caption nếu có.

    await process_filter(
        update,
        context
    )

    await process_antilink(
        update,
        context
    )

    await process_antispam(
        update,
        context
    )


# ============================================================
# XỬ LÝ MESSAGE BỊ XÓA / KHÔNG CẦN PHẢN HỒI
# ============================================================

async def ignored_message_handler(
    update,
    context
):

    return


# ============================================================
# KẾT THÚC PHẦN 13/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 14/25
# THƠ ĐỜI — 20 BÀI
# ============================================================

THO_DOI_LIST = [

    (
        "🌿 THƠ ĐỜI\n\n"
        "Đời người chẳng có bao lâu,\n"
        "Hôm nay còn gặp, mai sau xa rồi.\n"
        "Đừng vì hơn thua một lời,\n"
        "Mà quên trân trọng những người bên ta."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Có khi mệt mỏi giữa đời,\n"
        "Chẳng cần ai cứu, chỉ cần bình yên.\n"
        "Ngoài kia sóng gió triền miên,\n"
        "Giữ lòng vững bước, ưu phiền sẽ qua."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Người đi để lại đôi câu,\n"
        "Người còn ở lại bạc đầu chờ mong.\n"
        "Cuộc đời như nước xuôi dòng,\n"
        "Biết đâu bến đợi, biết không ngày về."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Đường đời có lúc chông gai,\n"
        "Có khi tưởng đã chẳng còn ngày mai.\n"
        "Nhưng rồi nắng lại ban mai,\n"
        "Sau cơn mưa lớn trời dài bình yên."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Đừng buồn vì chuyện đã qua,\n"
        "Đừng đau vì những người xa khỏi mình.\n"
        "Đời còn phía trước bình minh,\n"
        "Ngày mai vẫn có hành trình để đi."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Tiền tài rồi cũng như mây,\n"
        "Danh vọng một thoáng hao gầy tháng năm.\n"
        "Điều còn ở lại âm thầm,\n"
        "Là người bên cạnh những lần khó khăn."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Có người gặp gỡ một lần,\n"
        "Mà trong ký ức muôn phần chẳng phai.\n"
        "Có người bên cạnh tháng ngày,\n"
        "Đến khi xa cách mới hay quý người."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Đời không phải lúc nào vui,\n"
        "Có ngày nước mắt ngậm ngùi trong tim.\n"
        "Chỉ cần còn giữ niềm tin,\n"
        "Thì còn một lối bình minh phía ngoài."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Thành công chẳng đến tức thì,\n"
        "Muốn đi xa phải bước đi từng ngày.\n"
        "Dẫu cho thất bại đắng cay,\n"
        "Đứng lên bước tiếp, có ngày thành công."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Lòng người như nước mùa thu,\n"
        "Khi trong khi đục, khi mù khi trong.\n"
        "Đừng đem tất cả tấm lòng,\n"
        "Trao nhầm một chỗ rồi mong quay về."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Có tiền chưa chắc có vui,\n"
        "Có danh chưa chắc ngọt bùi quanh ta.\n"
        "Bình yên đôi lúc thật xa,\n"
        "Lại nằm trong một mái nhà có nhau."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Ngày dài rồi cũng sẽ qua,\n"
        "Nỗi buồn rồi cũng nhạt nhòa theo năm.\n"
        "Điều quan trọng nhất âm thầm,\n"
        "Là mình vẫn bước dù nằm giữa đau."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Đừng nhìn người khác mà ghen,\n"
        "Mỗi người một cuộc, một phen thăng trầm.\n"
        "Có người rực rỡ âm thầm,\n"
        "Có người chậm bước nhưng bền đường đi."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Một đời được mấy lần vui,\n"
        "Sao không giữ lấy nụ cười hôm nay?\n"
        "Ngày mai chưa biết thế nào,\n"
        "Nên đừng bỏ phí phút giây hiện giờ."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Người khôn biết giữ chữ tình,\n"
        "Người hay biết giữ lòng mình trước sau.\n"
        "Dẫu cho cuộc sống đổi màu,\n"
        "Đừng quên tử tế từ đầu đến sau."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Có những ngày chẳng muốn cười,\n"
        "Chỉ mong nằm xuống cho đời lặng im.\n"
        "Rồi mai thức giấc bình minh,\n"
        "Lại thêm một bước hành trình phía xa."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Đời người quý nhất chữ tâm,\n"
        "Không mua bằng bạc, chẳng cầm bằng tay.\n"
        "Sống sao cho đến một ngày,\n"
        "Nhìn về quá khứ chẳng cay trong lòng."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Có khi chẳng được như mong,\n"
        "Có khi cố gắng vẫn không thành rồi.\n"
        "Nhưng đừng vì thế buông xuôi,\n"
        "Vì sau thất bại còn người tiến lên."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Thời gian chẳng đợi một ai,\n"
        "Thanh xuân chẳng thể quay lại lần hai.\n"
        "Việc gì có thể làm ngay,\n"
        "Đừng chờ đến lúc tháng ngày trôi xa."
    ),

    (
        "🌿 THƠ ĐỜI\n\n"
        "Sau cùng chẳng giữ được gì,\n"
        "Ngoài bao kỷ niệm mình ghi trong lòng.\n"
        "Đời như một chuyến đò dòng,\n"
        "Đến nơi rồi cũng xuôi dòng mà đi."
    ),
]


# ============================================================
# /thodoi
# ============================================================

async def thodoi_command(update, context):

    if not await require_group(update):
        return

    poem = random.choice(
        THO_DOI_LIST
    )

    await safe_reply(
        update,
        poem
    )


# ============================================================
# KẾT THÚC PHẦN 14/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 15/25
# THƠ TÌNH — 20 BÀI
# ============================================================

THO_TINH_LIST = [

    (
        "❤️ THƠ TÌNH\n\n"
        "Nếu mai này chẳng cạnh nhau,\n"
        "Xin đừng quên những ngày đầu gặp nhau.\n"
        "Có người đi đến về sau,\n"
        "Có người chỉ đến một câu rồi rời."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Thương ai chẳng nói thành lời,\n"
        "Chỉ mong người ấy một đời bình an.\n"
        "Dẫu cho duyên phận hợp tan,\n"
        "Tấm lòng từng có vẫn mang trong lòng."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Gặp nhau giữa chốn đông người,\n"
        "Vậy mà ánh mắt chỉ cười với nhau.\n"
        "Chẳng cần hứa hẹn dài lâu,\n"
        "Chỉ cần chân thật bên nhau mỗi ngày."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Có người chẳng nói lời yêu,\n"
        "Nhưng luôn xuất hiện mỗi chiều hỏi han.\n"
        "Chẳng cần những thứ cao sang,\n"
        "Một câu quan tâm cũng làm lòng vui."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Tình yêu chẳng phải lời thề,\n"
        "Mà là ở cạnh những khi khó lòng.\n"
        "Ngoài kia dẫu có bão giông,\n"
        "Vẫn còn một người thật lòng ở bên."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Nếu thương thì hãy thật lòng,\n"
        "Đừng đem lời hứa chất chồng rồi quên.\n"
        "Tình yêu chẳng cần gọi tên,\n"
        "Chỉ cần hai phía giữ niềm tin nhau."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Một người đứng giữa chiều mưa,\n"
        "Chờ tin nhắn đến dù chưa nói gì.\n"
        "Đôi khi thương nhớ lạ kỳ,\n"
        "Chỉ vì một chữ người kia gửi về."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Ngày mai nếu bước xa nhau,\n"
        "Xin đừng biến những ngọt ngào thành đau.\n"
        "Từng thương thì hãy trước sau,\n"
        "Giữ cho kỷ niệm bạc màu cũng vui."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Chẳng cần người hứa trăm năm,\n"
        "Chỉ mong hôm nay thật tâm với mình.\n"
        "Tình yêu đẹp nhất khi bình,\n"
        "Không cần phô diễn, chỉ tình thật thôi."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Có người ở tận phương xa,\n"
        "Mà sao cảm giác như là cạnh bên.\n"
        "Một câu hỏi nhỏ mỗi đêm,\n"
        "Đủ làm khoảng cách dịu mềm hơn đi."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Thương nhau chẳng phải vì tiền,\n"
        "Cũng không vì những lời khen ngọt ngào.\n"
        "Thương là lúc chẳng đẹp nào,\n"
        "Vẫn còn ở cạnh, chẳng sao bỏ người."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Nếu một ngày chẳng còn yêu,\n"
        "Xin đừng trách móc những điều đã qua.\n"
        "Từng vui, từng nhớ, từng xa,\n"
        "Cũng từng là một mái nhà trong tim."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Có duyên thì gặp giữa đời,\n"
        "Có thương thì giữ một người thật tâm.\n"
        "Đừng vì một phút âm thầm,\n"
        "Mà đem đánh mất tháng năm bên người."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Em không cần những xa hoa,\n"
        "Chỉ cần người vẫn thật thà với em.\n"
        "Một câu hỏi lúc về đêm,\n"
        "Một lời nhắc nhỏ cũng mềm lòng nhau."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Anh không hứa chuyện mai sau,\n"
        "Chỉ mong hôm nay bên nhau thật lòng.\n"
        "Nếu đời có lúc long đong,\n"
        "Ta cùng cố gắng vượt dòng thời gian."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Tình yêu chẳng phải phép màu,\n"
        "Mà là hai phía cùng nhau vun bồi.\n"
        "Một người bước, một người thôi,\n"
        "Thì con đường ấy khó rồi đi xa."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Có khi chẳng nói một câu,\n"
        "Mà trong ánh mắt đã đầy nhớ thương.\n"
        "Tình yêu chẳng phải con đường,\n"
        "Mà là hai trái tim cùng hướng về."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Nếu thương xin chớ hững hờ,\n"
        "Đừng để người đợi bên bờ thời gian.\n"
        "Tình yêu quý nhất bình an,\n"
        "Không phải những thứ ngập tràn lời hoa."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Ngày nào còn có thể thương,\n"
        "Hãy trao tử tế trên đường gặp nhau.\n"
        "Đừng để đến lúc mất nhau,\n"
        "Mới hay một người từng sâu trong lòng."
    ),

    (
        "❤️ THƠ TÌNH\n\n"
        "Tình yêu nếu thật chân thành,\n"
        "Chẳng cần nói lớn vẫn dành cho nhau.\n"
        "Dẫu cho năm tháng đổi màu,\n"
        "Một lòng tử tế trước sau vẫn còn."
    ),
]


# ============================================================
# /thotinh
# ============================================================

async def thotinh_command(update, context):

    if not await require_group(update):
        return

    poem = random.choice(
        THO_TINH_LIST
    )

    await safe_reply(
        update,
        poem
    )


# ============================================================
# KẾT THÚC PHẦN 15/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 16/25
# ĐIỂM DANH — DỮ LIỆU + LỆNH
# ============================================================

# ============================================================
# LẤY DỮ LIỆU ĐIỂM DANH CỦA NHÓM
# ============================================================

def get_attendance_chat(chat_id):

    key = str(chat_id)

    if key not in db["attendance"]:
        db["attendance"][key] = {}

    return db["attendance"][key]


# ============================================================
# LẤY DỮ LIỆU USER
# ============================================================

def get_attendance_user(
    chat_id,
    user_id
):

    chat_data = get_attendance_chat(
        chat_id
    )

    key = str(user_id)

    if key not in chat_data:

        chat_data[key] = {
            "user_id": user_id,
            "name": "",
            "username": "",
            "streak": 0,
            "last_checkin": "",
            "total": 0,
        }

    return chat_data[key]


# ============================================================
# KIỂM TRA ĐÃ ĐIỂM DANH HÔM NAY
# ============================================================

def already_checked_in(
    chat_id,
    user_id
):

    data = get_attendance_user(
        chat_id,
        user_id
    )

    return (
        data.get("last_checkin")
        == today_key()
    )


# ============================================================
# TÍNH STREAK
# ============================================================

def calculate_attendance_streak(
    data
):

    last_checkin = data.get(
        "last_checkin",
        ""
    )

    if not last_checkin:
        return 1

    try:

        last_date = datetime.strptime(
            last_checkin,
            "%Y-%m-%d"
        ).date()

        today = now_vn().date()

        difference = (
            today - last_date
        ).days

        if difference == 1:
            return int(
                data.get(
                    "streak",
                    0
                )
            ) + 1

        if difference == 0:
            return int(
                data.get(
                    "streak",
                    0
                )
            )

        return 1

    except Exception:

        return 1


# ============================================================
# TẠO BẢNG XẾP HẠNG
# ============================================================

def build_attendance_leaderboard(
    chat_id
):

    chat_data = get_attendance_chat(
        chat_id
    )

    checked_users = []

    for data in chat_data.values():

        if not data.get(
            "last_checkin"
        ):
            continue

        if not data.get(
            "total",
            0
        ):
            continue

        checked_users.append(data)

    checked_users.sort(
        key=lambda item: (
            int(
                item.get(
                    "streak",
                    0
                )
            ),
            int(
                item.get(
                    "total",
                    0
                )
            )
        ),
        reverse=True
    )

    lines = [
        "🏆 BẢNG XẾP HẠNG ĐIỂM DANH",
        ""
    ]

    if not checked_users:

        lines.append(
            "📭 Chưa có ai điểm danh."
        )

        return "\n".join(lines)

    for index, data in enumerate(
        checked_users,
        start=1
    ):

        name = data.get(
            "name",
            "Không rõ"
        )

        streak = int(
            data.get(
                "streak",
                0
            )
        )

        total = int(
            data.get(
                "total",
                0
            )
        )

        lines.append(
            f"{index}. {name} — "
            f"🔥 {streak} ngày — "
            f"📅 {total} lần"
        )

    return "\n".join(lines)


# ============================================================
# TẠO NÚT ĐIỂM DANH
# ============================================================

def attendance_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔥 Điểm danh",
                callback_data="attendance_checkin"
            )
        ]
    ])


# ============================================================
# /diemdanh
# ============================================================

async def diemdanh_command(
    update,
    context
):

    if not await require_group(update):
        return

    chat_id = update.effective_chat.id

    await safe_send_message(
        context,
        chat_id,
        "🔥 ĐIỂM DANH HÔM NAY\n\n"
        "Bấm nút bên dưới để điểm danh.\n"
        "Mỗi ngày chỉ được điểm danh một lần.",
        reply_markup=attendance_keyboard()
    )


# ============================================================
# THÔNG TIN ĐIỂM DANH CÁ NHÂN
# ============================================================

async def attendance_info_command(
    update,
    context
):

    if not await require_group(update):
        return

    user = update.effective_user

    if not user:
        return

    chat_id = update.effective_chat.id

    data = get_attendance_user(
        chat_id,
        user.id
    )

    streak = int(
        data.get(
            "streak",
            0
        )
    )

    total = int(
        data.get(
            "total",
            0
        )
    )

    last_checkin = data.get(
        "last_checkin",
        "Chưa có"
    )

    await safe_reply(
        update,
        "📊 THÔNG TIN ĐIỂM DANH\n\n"
        f"👤 {user_display_name(user)}\n"
        f"🔥 Streak: {streak} ngày\n"
        f"📅 Tổng số lần: {total}\n"
        f"🗓️ Lần gần nhất: {last_checkin}"
    )


# ============================================================
# /diemdanhinfo
# ============================================================

async def attendance_leaderboard_command(
    update,
    context
):

    if not await require_group(update):
        return

    chat_id = update.effective_chat.id

    await safe_reply(
        update,
        build_attendance_leaderboard(
            chat_id
        )
    )


# ============================================================
# KẾT THÚC PHẦN 16/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 17/25
# CALLBACK ĐIỂM DANH + LEADERBOARD
# ============================================================

async def attendance_callback(update, context):

    query = update.callback_query

    if not query:
        return

    if not query.message:
        return

    chat_id = query.message.chat.id
    user = query.from_user

    if not user:
        return

    # --------------------------------------------------------
    # Chỉ cho phép trong nhóm
    # --------------------------------------------------------

    if query.message.chat.type not in (
        "group",
        "supergroup",
    ):

        try:
            await query.answer(
                "Chức năng này chỉ dùng trong nhóm.",
                show_alert=True
            )
        except Exception:
            pass

        return

    cache_user(user)
    register_owner(user)

    # --------------------------------------------------------
    # Kiểm tra đã điểm danh chưa
    # --------------------------------------------------------

    if already_checked_in(
        chat_id,
        user.id
    ):

        try:
            await query.answer(
                "✅ Bạn đã điểm danh hôm nay rồi!",
                show_alert=True
            )
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # Lấy dữ liệu
    # --------------------------------------------------------

    data = get_attendance_user(
        chat_id,
        user.id
    )

    # --------------------------------------------------------
    # Tính streak
    # --------------------------------------------------------

    streak = calculate_attendance_streak(
        data
    )

    data["user_id"] = user.id
    data["name"] = user_display_name(user)
    data["username"] = (
        user.username or ""
    )
    data["streak"] = streak
    data["last_checkin"] = today_key()
    data["total"] = int(
        data.get(
            "total",
            0
        )
    ) + 1

    await save_db_async()

    # --------------------------------------------------------
    # Popup xác nhận
    # --------------------------------------------------------

    try:
        await query.answer(
            f"✅ ĐIỂM DANH THÀNH CÔNG!\n"
            f"🔥 Streak: {streak} ngày",
            show_alert=True
        )
    except Exception:
        pass

    # --------------------------------------------------------
    # Xóa message cũ
    # --------------------------------------------------------

    try:
        await query.message.delete()

    except TelegramError:
        pass

    # --------------------------------------------------------
    # Tạo message mới
    # --------------------------------------------------------

    leaderboard = build_attendance_leaderboard(
        chat_id
    )

    await safe_send_message(
        context,
        chat_id,
        "🔥 ĐIỂM DANH HÔM NAY\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"✅ {user_display_name(user)} ĐÃ ĐIỂM DANH!\n\n"
        f"🔥 Streak: {streak} ngày\n"
        f"📅 Tổng số lần: {data['total']}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{leaderboard}\n\n"
        "👆 Bấm nút bên dưới để kiểm tra điểm danh.",
        reply_markup=attendance_keyboard()
    )

# ============================================================
# CALLBACK LEADERBOARD
# ============================================================

async def attendance_leaderboard_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    try:
        await query.answer()
    except Exception:
        pass

    if not query.message:
        return

    chat_id = query.message.chat.id

    leaderboard = build_attendance_leaderboard(
        chat_id
    )

    try:

        await query.message.edit_text(
            leaderboard,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔥 Điểm danh",
                        callback_data="attendance_checkin"
                    )
                ]
            ])
        )

    except TelegramError:
        pass


# ============================================================
# KIỂM TRA CALLBACK ĐIỂM DANH
# ============================================================

async def attendance_callback_router(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    callback_data = (
        query.data
        or ""
    )

    if callback_data == "attendance_checkin":

        await attendance_callback(
            update,
            context
        )

        return

    if callback_data == "attendance_leaderboard":

        await attendance_leaderboard_callback(
            update,
            context
        )

        return


# ============================================================
# KẾT THÚC PHẦN 17/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 18/25
# GAME NỐI CHỮ — DỮ LIỆU + HÀM HỖ TRỢ
# ============================================================

# ============================================================
# DANH SÁCH TỪ KHỞI ĐẦU
# ============================================================

WORD_START_LIST = [
    "con mèo",
    "bầu trời",
    "mặt trời",
    "hoa hồng",
    "học sinh",
    "gia đình",
    "quê hương",
    "bình minh",
    "ánh sáng",
    "cây xanh",
    "dòng sông",
    "biển cả",
    "mùa hè",
    "trường học",
    "bạn bè",
    "niềm vui",
    "ước mơ",
    "cuộc sống",
    "tình bạn",
    "thế giới",
]


# ============================================================
# LẤY GAME THEO NHÓM
# ============================================================

def get_word_game(chat_id):

    return word_games.get(
        chat_id
    )


# ============================================================
# TẠO GAME MỚI
# ============================================================

def create_word_game(chat_id):

    game = {
        "chat_id": chat_id,
        "status": "joining",
        "players": {},
        "player_order": [],
        "current_index": 0,
        "current_word": None,
        "used_words": [],
        "join_message_id": None,
        "join_task": None,
        "turn_message_id": None,
        "created_at": time.time(),
    }

    word_games[chat_id] = game

    return game


# ============================================================
# LẤY / TẠO PLAYER
# ============================================================

def add_word_player(
    game,
    user
):

    if not user:
        return False

    user_id = user.id

    if user_id in game["players"]:
        return False

    if len(game["players"]) >= 20:
        return False

    game["players"][user_id] = {
        "id": user.id,
        "name": user_display_name(user),
        "username": user.username or "",
    }

    game["player_order"].append(
        user_id
    )

    cache_user(user)

    return True


# ============================================================
# XÓA PLAYER
# ============================================================

def remove_word_player(
    game,
    user_id
):

    if user_id not in game["players"]:
        return False

    del game["players"][user_id]

    if user_id in game["player_order"]:
        game["player_order"].remove(
            user_id
        )

    if game["current_index"] >= len(
        game["player_order"]
    ):
        game["current_index"] = 0

    return True


# ============================================================
# LẤY PLAYER HIỆN TẠI
# ============================================================

def get_current_word_player(game):

    players = game.get(
        "player_order",
        []
    )

    if not players:
        return None

    index = game.get(
        "current_index",
        0
    )

    if index >= len(players):
        index = 0
        game["current_index"] = 0

    return players[index]


# ============================================================
# LẤY TÊN PLAYER
# ============================================================

def get_word_player_name(
    game,
    user_id
):

    player = game.get(
        "players",
        {}
    ).get(
        user_id
    )

    if not player:
        return "Không rõ"

    return player.get(
        "name",
        "Không rõ"
    )


# ============================================================
# CHUYỂN LƯỢT
# ============================================================

def next_word_turn(game):

    players = game.get(
        "player_order",
        []
    )

    if not players:
        game["current_index"] = 0
        return

    game["current_index"] = (
        game.get(
            "current_index",
            0
        ) + 1
    ) % len(players)


# ============================================================
# LẤY TỪ CUỐI CÙNG
# ============================================================

def get_last_word_part(word):

    if not word:
        return ""

    normalized = normalize_text(
        word
    )

    parts = normalized.split()

    if not parts:
        return ""

    return parts[-1]


# ============================================================
# KIỂM TRA TỪ HỢP LỆ
# ============================================================

def is_valid_chain_word(
    current_word,
    new_word
):

    if not current_word:
        return True

    if not new_word:
        return False

    current_last = get_last_word_part(
        current_word
    )

    new_first = (
        normalize_text(new_word)
        .split()[0]
        if normalize_text(new_word).split()
        else ""
    )

    if not current_last:
        return False

    if not new_first:
        return False

    return (
        new_first
        == current_last
    )


# ============================================================
# KIỂM TRA TỪ ĐÃ DÙNG
# ============================================================

def is_word_used(
    game,
    word
):

    normalized = normalize_text(
        word
    )

    for used in game.get(
        "used_words",
        []
    ):

        if normalize_text(used) == normalized:
            return True

    return False


# ============================================================
# THÊM TỪ ĐÃ DÙNG
# ============================================================

def add_used_word(
    game,
    word
):

    game.setdefault(
        "used_words",
        []
    ).append(
        word
    )


# ============================================================
# TẠO DANH SÁCH PLAYER
# ============================================================

def build_word_player_list(game):

    lines = [
        "👥 DANH SÁCH NGƯỜI CHƠI",
        ""
    ]

    players = game.get(
        "player_order",
        []
    )

    if not players:

        lines.append(
            "📭 Chưa có người chơi."
        )

        return "\n".join(lines)

    for index, user_id in enumerate(
        players,
        start=1
    ):

        name = get_word_player_name(
            game,
            user_id
        )

        lines.append(
            f"{index}. {name}"
        )

    return "\n".join(lines)


# ============================================================
# BẢNG NÚT THAM GIA
# ============================================================

def word_join_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎮 Tham gia",
                callback_data="word_join"
            )
        ]
    ])


# ============================================================
# BẢNG NÚT KHI GAME ĐANG CHƠI
# ============================================================

def word_game_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 Người chơi",
                callback_data="word_players"
            )
        ]
    ])


# ============================================================
# CHỌN TỪ KHỞI ĐẦU
# ============================================================

def choose_start_word():

    return random.choice(
        WORD_START_LIST
    )


# ============================================================
# TẠO NỘI DUNG PHÒNG CHỜ
# ============================================================

def build_word_join_text(game):

    players = game.get(
        "players",
        {}
    )

    return (
        "🎮 GAME NỐI CHỮ\n\n"
        "⏳ Thời gian tham gia: 5 phút\n"
        f"👥 Người chơi: {len(players)}/20\n\n"
        f"{build_word_player_list(game)}\n\n"
        "Bấm nút bên dưới để tham gia."
    )


# ============================================================
# TẠO NỘI DUNG GAME
# ============================================================

def build_word_turn_text(game):

    current_word = game.get(
        "current_word"
    )

    current_user_id = (
        get_current_word_player(game)
    )

    current_name = get_word_player_name(
        game,
        current_user_id
    )

    players_count = len(
        game.get(
            "player_order",
            []
        )
    )

    return (
        "🎮 GAME NỐI CHỮ ĐANG DIỄN RA\n\n"
        f"👥 Người chơi: {players_count}\n"
        f"🔤 Từ hiện tại: {current_word}\n\n"
        f"👉 Đến lượt: {current_name}\n\n"
        "Hãy gửi một từ bắt đầu bằng "
        "từ cuối của từ hiện tại."
    )


# ============================================================
# KẾT THÚC PHẦN 18/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 19/25
# GAME NỐI CHỮ — TẠO PHÒNG + THAM GIA
# ============================================================

# ============================================================
# /gamenoichu
# ============================================================

async def gamenoichu_command(
    update,
    context
):

    if not await require_group(update):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    if not user:
        return

    existing_game = get_word_game(
        chat_id
    )

    if existing_game:

        status = existing_game.get(
            "status"
        )

        if status == "joining":

            await safe_reply(
                update,
                "🎮 Nhóm đang có một phòng "
                "nối chữ đang chờ người chơi."
            )

            return

        if status == "playing":

            await safe_reply(
                update,
                "🎮 Game nối chữ đang diễn ra rồi."
            )

            return

    # --------------------------------------------------------
    # Tạo phòng
    # --------------------------------------------------------

    game = create_word_game(
        chat_id
    )

    # Người dùng tạo phòng tự động tham gia
    add_word_player(
        game,
        user
    )

    # --------------------------------------------------------
    # Gửi phòng chờ
    # --------------------------------------------------------

    sent = await safe_send_message(
        context,
        chat_id,
        build_word_join_text(game),
        reply_markup=word_join_keyboard()
    )

    if not sent:
        word_games.pop(
            chat_id,
            None
        )
        return

    game["join_message_id"] = (
        sent.message_id
    )

    # --------------------------------------------------------
    # Tạo countdown 5 phút
    # --------------------------------------------------------

    game["join_task"] = create_background_task(
        word_join_countdown(
            context,
            chat_id
        )
    )


# ============================================================
# COUNTDOWN PHÒNG CHỜ
# ============================================================

async def word_join_countdown(
    context,
    chat_id
):
    try:
        await asyncio.sleep(300)

        game = get_word_game(chat_id)

        if not game:
            return

        if game.get("status") != "joining":
            return

        join_message_id = game.get("join_message_id")

        # Xóa tin nhắn phòng chờ cũ
        if join_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=join_message_id
                )
            except TelegramError:
                pass

        players = game.get(
            "player_order",
            []
        )

        # Không đủ người
        if len(players) < 2:

            await safe_send_message(
                context,
                chat_id,
                "❌ GAME NỐI CHỮ ĐÃ HỦY\n\n"
                "⏰ Đã hết 5 phút chờ người chơi.\n"
                "👥 Cần ít nhất 2 người để bắt đầu."
            )

            word_games.pop(
                chat_id,
                None
            )

            return

        # Đủ người → bắt đầu game
        game["status"] = "playing"
        game["current_index"] = 0

        start_word = choose_start_word()

        game["current_word"] = start_word
        game["used_words"] = [
            start_word
        ]

        await safe_send_message(
            context,
            chat_id,
            "🎮 GAME NỐI CHỮ BẮT ĐẦU!\n\n"
            f"{build_word_player_list(game)}\n\n"
            f"🔤 Từ khởi đầu: {start_word}\n\n"
            f"{build_word_turn_text(game)}",
            reply_markup=word_game_keyboard()
        )

    except asyncio.CancelledError:
        return

    except Exception as e:
        log_event(
            f"Lỗi countdown game nối chữ: {e}"
        )

# ============================================================
# CALLBACK THAM GIA
# ============================================================

async def word_join_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    try:
        await query.answer()
    except Exception:
        pass

    if not query.message:
        return

    chat_id = query.message.chat.id
    user = query.from_user

    if not user:
        return

    game = get_word_game(
        chat_id
    )

    if not game:

        try:
            await query.answer(
                "Phòng chơi không còn tồn tại.",
                show_alert=True
            )
        except Exception:
            pass

        return

    if game.get(
        "status"
    ) != "joining":

        try:
            await query.answer(
                "Game đã bắt đầu.",
                show_alert=True
            )
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # Đã tham gia
    # --------------------------------------------------------

    if user.id in game.get(
        "players",
        {}
    ):

        try:
            await query.answer(
                "Bạn đã tham gia rồi!",
                show_alert=True
            )
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # Giới hạn 20 người
    # --------------------------------------------------------

    if len(
        game.get(
            "players",
            {}
        )
    ) >= 20:

        try:
            await query.answer(
                "Phòng đã đủ 20 người.",
                show_alert=True
            )
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # Thêm người chơi
    # --------------------------------------------------------

    add_word_player(
        game,
        user
    )

    try:

        await query.answer(
            "🎮 Bạn đã tham gia game!"
        )

    except Exception:
        pass

    # --------------------------------------------------------
    # Cập nhật message phòng chờ
    # --------------------------------------------------------

    try:

        await query.message.edit_text(
            build_word_join_text(game),
            reply_markup=word_join_keyboard()
        )

    except TelegramError:
        pass


# ============================================================
# CALLBACK XEM DANH SÁCH NGƯỜI CHƠI
# ============================================================

async def word_players_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    try:
        await query.answer()
    except Exception:
        pass

    if not query.message:
        return

    chat_id = query.message.chat.id

    game = get_word_game(
        chat_id
    )

    if not game:

        try:
            await query.answer(
                "Game không còn tồn tại.",
                show_alert=True
            )
        except Exception:
            pass

        return

    try:

        await query.message.reply_text(
            build_word_player_list(game)
        )

    except TelegramError:
        pass


# ============================================================
# ROUTER CALLBACK GAME NỐI CHỮ
# ============================================================

async def word_callback_router(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    callback_data = (
        query.data
        or ""
    )

    if callback_data == "word_join":

        await word_join_callback(
            update,
            context
        )

        return

    if callback_data == "word_players":

        await word_players_callback(
            update,
            context
        )

        return


# ============================================================
# KẾT THÚC PHẦN 19/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 20/25
# GAME NỐI CHỮ — XỬ LÝ LƯỢT + GAMEOFF
# ============================================================

async def process_word_game(update, context):

    if not is_group(update):
        return

    message = update.effective_message

    if not message:
        return

    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    # Không xử lý command
    if text.startswith("/"):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    if not user:
        return

    game = get_word_game(chat_id)

    if not game:
        return

    if game.get("status") != "playing":
        return

    # --------------------------------------------------------
    # Kiểm tra người chơi
    # --------------------------------------------------------

    if user.id not in game.get(
        "players",
        {}
    ):

        return

    current_user_id = (
        get_current_word_player(game)
    )

    # Không phải lượt người này
    if user.id != current_user_id:

        try:

            await message.reply_text(
                "⏳ Chưa tới lượt bạn.\n"
                f"👉 Lượt hiện tại: "
                f"{get_word_player_name(game, current_user_id)}"
            )

        except TelegramError:
            pass

        return

    # --------------------------------------------------------
    # Chỉ lấy một cụm từ vừa phải
    # --------------------------------------------------------

    if len(text) > 100:

        await safe_reply(
            update,
            "❌ Từ/cụm từ quá dài."
        )

        return

    # --------------------------------------------------------
    # Không cho dùng lại từ
    # --------------------------------------------------------

    if is_word_used(
        game,
        text
    ):

        await safe_reply(
            update,
            "❌ Từ này đã được sử dụng."
        )

        return

    # --------------------------------------------------------
    # Kiểm tra nối chữ
    # --------------------------------------------------------

    current_word = game.get(
        "current_word"
    )

    if not is_valid_chain_word(
        current_word,
        text
    ):

        last_part = get_last_word_part(
            current_word
        )

        await safe_reply(
            update,
            "❌ Không hợp lệ!\n\n"
            f"🔤 Từ hiện tại kết thúc bằng: "
            f"**{last_part}**\n"
            f"👉 Hãy gửi từ bắt đầu bằng "
            f"**{last_part}**.",
            parse_mode="Markdown"
        )

        return

    # --------------------------------------------------------
    # Lưu từ mới
    # --------------------------------------------------------

    add_used_word(
        game,
        text
    )

    game["current_word"] = text

    # --------------------------------------------------------
    # Chuyển lượt
    # --------------------------------------------------------

    next_word_turn(game)

    next_user_id = (
        get_current_word_player(game)
    )

    next_name = get_word_player_name(
        game,
        next_user_id
    )

    await safe_send_message(
        context,
        chat_id,
        "✅ Hợp lệ!\n\n"
        f"🔤 Từ mới: {text}\n"
        f"👉 Lượt tiếp theo: {next_name}"
    )


# ============================================================
# /gameoff
# ============================================================

async def gameoff_command(
    update,
    context
):

    if not await require_group(update):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    if not user:
        return

    game = get_word_game(
        chat_id
    )

    if not game:

        await safe_reply(
            update,
            "❌ Nhóm hiện không có game nối chữ."
        )

        return

    # Chỉ admin / Owner được dừng game
    if not is_owner(user):

        if not await is_admin(
            context,
            chat_id,
            user.id
        ):

            await safe_reply(
                update,
                "❌ Chỉ admin hoặc Owner "
                "mới có thể dừng game."
            )

            return

    # Hủy task countdown nếu còn
    join_task = game.get(
        "join_task"
    )

    if join_task:

        try:

            if not join_task.done():
                join_task.cancel()

        except Exception:
            pass

    word_games.pop(
        chat_id,
        None
    )

    await safe_reply(
        update,
        "🛑 Đã dừng game nối chữ."
    )


# ============================================================
# HỦY GAME KHI CÓ LỖI
# ============================================================

async def cleanup_word_game(
    chat_id
):

    game = word_games.pop(
        chat_id,
        None
    )

    if not game:
        return

    task = game.get(
        "join_task"
    )

    if task:

        try:

            if not task.done():
                task.cancel()

        except Exception:
            pass


# ============================================================
# KIỂM TRA GAME CÒN HOẠT ĐỘNG
# ============================================================

def is_word_game_active(
    chat_id
):

    game = get_word_game(
        chat_id
    )

    if not game:
        return False

    return game.get(
        "status"
    ) in (
        "joining",
        "playing",
    )


# ============================================================
# KẾT THÚC PHẦN 20/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 21/25
# MA SÓI — DỮ LIỆU + VAI TRÒ
# ============================================================

# ============================================================
# CẤU HÌNH MA SÓI
# ============================================================

WEREWOLF_MIN_PLAYERS = 4
WEREWOLF_MAX_PLAYERS = 9
WEREWOLF_JOIN_TIME = 180


# ============================================================
# VAI TRÒ
# ============================================================

WEREWOLF_ROLES = {
    "wolf": {
        "name": "🐺 Sói",
        "team": "wolf",
    },
    "villager": {
        "name": "👨 Dân làng",
        "team": "village",
    },
    "seer": {
        "name": "🔮 Tiên tri",
        "team": "village",
    },
    "protector": {
        "name": "🛡️ Bảo vệ",
        "team": "village",
    },
    "witch": {
        "name": "🧙 Phù thủy",
        "team": "village",
    },
    "hunter": {
        "name": "🔫 Thợ săn",
        "team": "village",
    },
    "zombie": {
        "name": "🧟 Zombie",
        "team": "zombie",
    },
}


# ============================================================
# TẠO DANH SÁCH VAI TRÒ THEO SỐ NGƯỜI
# ============================================================

def build_werewolf_roles(player_count):

    if player_count < 4:
        return []

    if player_count == 4:

        roles = [
            "wolf",
            "villager",
            "seer",
            "protector",
        ]

    elif player_count == 5:

        roles = [
            "wolf",
            "wolf",
            "villager",
            "seer",
            "protector",
        ]

    elif player_count == 6:

        roles = [
            "wolf",
            "wolf",
            "villager",
            "seer",
            "protector",
            "witch",
        ]

    elif player_count == 7:

        roles = [
            "wolf",
            "wolf",
            "villager",
            "villager",
            "seer",
            "protector",
            "witch",
        ]

    elif player_count == 8:

        roles = [
            "wolf",
            "wolf",
            "villager",
            "villager",
            "seer",
            "protector",
            "witch",
            "hunter",
        ]

    else:

        roles = [
            "wolf",
            "wolf",
            "villager",
            "villager",
            "seer",
            "protector",
            "witch",
            "hunter",
            "zombie",
        ]

    random.shuffle(roles)

    return roles


# ============================================================
# TẠO PHÒNG MA SÓI
# ============================================================

def create_werewolf_game(chat_id):

    game = {
        "chat_id": chat_id,
        "status": "joining",

        "players": {},

        "phase": "join",

        "round": 0,

        "join_message_id": None,

        "join_task": None,

        "phase_task": None,

        "night_actions": {},

        "votes": {},

        "deaths": [],

        "protected": None,

        "witch_heal_used": False,

        "witch_poison_used": False,

        "witch_heal_target": None,

        "witch_poison_target": None,

        "hunter_target": None,

        "zombie_marks": {},

        "last_protected": None,

        "last_protected_round": -1,

        "created_at": time.time(),

        "winner": None,
    }

    werewolf_games[chat_id] = game

    return game


# ============================================================
# LẤY GAME
# ============================================================

def get_werewolf_game(chat_id):

    return werewolf_games.get(
        chat_id
    )


# ============================================================
# THÊM NGƯỜI CHƠI
# ============================================================

def add_werewolf_player(
    game,
    user
):

    if not user:
        return False

    user_id = user.id

    if user_id in game["players"]:
        return False

    if len(
        game["players"]
    ) >= WEREWOLF_MAX_PLAYERS:

        return False

    game["players"][user_id] = {
        "id": user.id,
        "name": user_display_name(user),
        "username": user.username or "",
        "alive": True,
        "role": None,
        "role_sent": False,
        "wolf_target": None,
        "seer_target": None,
        "protected": False,
        "hunter_alive": False,
        "zombie_marks": 0,
    }

    cache_user(user)

    return True


# ============================================================
# XÓA NGƯỜI CHƠI
# ============================================================

def remove_werewolf_player(
    game,
    user_id
):

    if user_id not in game["players"]:
        return False

    del game["players"][user_id]

    return True


# ============================================================
# LẤY PLAYER
# ============================================================

def get_werewolf_player(
    game,
    user_id
):

    return game.get(
        "players",
        {}
    ).get(
        user_id
    )


# ============================================================
# LẤY PLAYER CÒN SỐNG
# ============================================================

def get_alive_players(game):

    return [
        player
        for player in game.get(
            "players",
            {}
        ).values()
        if player.get(
            "alive",
            False
        )
    ]


# ============================================================
# LẤY PLAYER THEO ROLE
# ============================================================

def get_players_by_role(
    game,
    role
):

    return [
        player
        for player in game.get(
            "players",
            {}
        ).values()
        if player.get(
            "role"
        ) == role
        and player.get(
            "alive",
            False
        )
    ]


# ============================================================
# KIỂM TRA PLAYER CÒN SỐNG
# ============================================================

def is_werewolf_alive(
    game,
    user_id
):

    player = get_werewolf_player(
        game,
        user_id
    )

    if not player:
        return False

    return bool(
        player.get(
            "alive",
            False
        )
    )


# ============================================================
# LẤY TÊN PLAYER
# ============================================================

def werewolf_player_name(
    game,
    user_id
):

    player = get_werewolf_player(
        game,
        user_id
    )

    if not player:
        return "Không rõ"

    return player.get(
        "name",
        "Không rõ"
    )


# ============================================================
# DANH SÁCH NGƯỜI CHƠI
# ============================================================

def build_werewolf_player_list(
    game,
    show_roles=False
):

    lines = [
        "🐺 DANH SÁCH MA SÓI",
        ""
    ]

    players = list(
        game.get(
            "players",
            {}
        ).values()
    )

    for index, player in enumerate(
        players,
        start=1
    ):

        name = player.get(
            "name",
            "Không rõ"
        )

        if player.get(
            "alive",
            False
        ):

            status = "🟢"

        else:

            status = "💀"

        line = (
            f"{index}. {status} {name}"
        )

        if show_roles:

            role = player.get(
                "role"
            )

            role_name = WEREWOLF_ROLES.get(
                role,
                {}
            ).get(
                "name",
                "❓"
            )

            line += (
                f" — {role_name}"
            )

        lines.append(line)

    return "\n".join(lines)


# ============================================================
# NÚT THAM GIA MA SÓI
# ============================================================

def werewolf_join_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🐺 Tham gia",
                callback_data="ww_join"
            )
        ]
    ])


# ============================================================
# NỘI DUNG PHÒNG CHỜ
# ============================================================

def build_werewolf_join_text(game):

    count = len(
        game.get(
            "players",
            {}
        )
    )

    return (
        "🐺 PHÒNG MA SÓI\n\n"
        f"⏳ Thời gian tham gia: "
        f"{WEREWOLF_JOIN_TIME // 60} phút\n"
        f"👥 Người chơi: "
        f"{count}/{WEREWOLF_MAX_PLAYERS}\n"
        f"📌 Tối thiểu: "
        f"{WEREWOLF_MIN_PLAYERS} người\n\n"
        f"{build_werewolf_player_list(game)}\n\n"
        "Bấm nút bên dưới để tham gia."
    )


# ============================================================
# KẾT THÚC PHẦN 21/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 22/25
# MA SÓI — TẠO PHÒNG / THAM GIA / TRẠNG THÁI / HỦY
# ============================================================

# ============================================================
# /masoi
# ============================================================

async def masoi_command(update, context):

    if not await require_group(update):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    if not user:
        return

    existing = get_werewolf_game(chat_id)

    if existing:
        await safe_reply(
            update,
            "🐺 Nhóm đang có một phòng Ma Sói."
        )
        return

    game = create_werewolf_game(chat_id)

    add_werewolf_player(
        game,
        user
    )

    sent = await safe_send_message(
        context,
        chat_id,
        build_werewolf_join_text(game),
        reply_markup=werewolf_join_keyboard()
    )

    if not sent:
        werewolf_games.pop(
            chat_id,
            None
        )
        return

    game["join_message_id"] = (
        sent.message_id
    )

    game["join_task"] = create_background_task(
        werewolf_join_countdown(
            context,
            chat_id
        )
    )


# ============================================================
# COUNTDOWN 3 PHÚT
# ============================================================

async def werewolf_join_countdown(
    context,
    chat_id
):
    try:
        await asyncio.sleep(
            WEREWOLF_JOIN_TIME
        )

        game = get_werewolf_game(
            chat_id
        )

        if not game:
            return

        if game.get("status") != "joining":
            return

        join_message_id = game.get(
            "join_message_id"
        )

        # Xóa tin nhắn phòng chờ
        if join_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=join_message_id
                )
            except TelegramError:
                pass

        player_count = len(
            game.get(
                "players",
                {}
            )
        )

        # Không đủ người
        if player_count < WEREWOLF_MIN_PLAYERS:

            await safe_send_message(
                context,
                chat_id,
                "❌ PHÒNG MA SÓI ĐÃ HỦY\n\n"
                "⏰ Đã hết 3 phút chờ người chơi.\n"
                f"👥 Chỉ có {player_count} người tham gia.\n"
                f"🐺 Cần ít nhất "
                f"{WEREWOLF_MIN_PLAYERS} người."
            )

            werewolf_games.pop(
                chat_id,
                None
            )

            return

        # Đủ người → bắt đầu
        await safe_send_message(
            context,
            chat_id,
            "🐺 HẾT THỜI GIAN THAM GIA!\n\n"
            f"👥 Có {player_count} người chơi.\n"
            "🎮 Trận Ma Sói bắt đầu!"
        )

        await start_werewolf_game(
            context,
            chat_id
        )

    except asyncio.CancelledError:
        return

    except Exception as e:
        log_event(
            f"Lỗi countdown Ma Sói: {e}"
        )

# ============================================================
# CALLBACK THAM GIA
# ============================================================

async def werewolf_join_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    try:
        await query.answer()
    except Exception:
        pass

    if not query.message:
        return

    chat_id = query.message.chat.id
    user = query.from_user

    if not user:
        return

    game = get_werewolf_game(
        chat_id
    )

    if not game:

        try:
            await query.answer(
                "Phòng không còn tồn tại.",
                show_alert=True
            )
        except Exception:
            pass

        return

    if game.get("status") != "joining":

        try:
            await query.answer(
                "Trận đấu đã bắt đầu.",
                show_alert=True
            )
        except Exception:
            pass

        return

    if user.id in game.get(
        "players",
        {}
    ):

        try:
            await query.answer(
                "Bạn đã tham gia rồi!",
                show_alert=True
            )
        except Exception:
            pass

        return

    if len(
        game.get(
            "players",
            {}
        )
    ) >= WEREWOLF_MAX_PLAYERS:

        try:
            await query.answer(
                "Phòng đã đủ người.",
                show_alert=True
            )
        except Exception:
            pass

        return

    add_werewolf_player(
        game,
        user
    )

    try:
        await query.answer(
            "🐺 Đã tham gia phòng!"
        )
    except Exception:
        pass

    try:

        await query.message.edit_text(
            build_werewolf_join_text(game),
            reply_markup=werewolf_join_keyboard()
        )

    except TelegramError:
        pass


# ============================================================
# /masoistatus
# ============================================================

async def masoistatus_command(
    update,
    context
):

    if not await require_group(update):
        return

    chat_id = update.effective_chat.id

    game = get_werewolf_game(
        chat_id
    )

    if not game:

        await safe_reply(
            update,
            "🐺 Nhóm hiện không có trận Ma Sói."
        )

        return

    status = game.get(
        "status",
        "unknown"
    )

    phase = game.get(
        "phase",
        "unknown"
    )

    player_count = len(
        game.get(
            "players",
            {}
        )
    )

    alive_count = len(
        get_alive_players(game)
    )

    if status == "joining":

        status_text = "⏳ Đang chờ người chơi"

    elif status == "playing":

        status_text = "🎮 Đang chơi"

    elif status == "finished":

        status_text = "🏁 Đã kết thúc"

    else:

        status_text = status

    phase_names = {
        "join": "Phòng chờ",
        "night": "🌙 Ban đêm",
        "morning": "🌅 Buổi sáng",
        "vote": "🗳️ Bỏ phiếu",
        "finished": "🏁 Kết thúc",
    }

    phase_text = phase_names.get(
        phase,
        phase
    )

    await safe_reply(
        update,
        "🐺 TRẠNG THÁI MA SÓI\n\n"
        f"📌 Trạng thái: {status_text}\n"
        f"🌙 Giai đoạn: {phase_text}\n"
        f"👥 Người chơi: {player_count}\n"
        f"❤️ Còn sống: {alive_count}"
    )


# ============================================================
# /huyma
# ============================================================

async def huyma_command(
    update,
    context
):

    if not await require_group(update):
        return

    chat_id = update.effective_chat.id
    user = update.effective_user

    if not user:
        return

    game = get_werewolf_game(
        chat_id
    )

    if not game:

        await safe_reply(
            update,
            "❌ Không có trận Ma Sói để hủy."
        )

        return

    if not is_owner(user):

        if not await is_admin(
            context,
            chat_id,
            user.id
        ):

            await safe_reply(
                update,
                "❌ Chỉ admin hoặc Owner "
                "mới có thể hủy trận."
            )

            return

    # Hủy các task nền
    for task_name in (
        "join_task",
        "phase_task",
    ):

        task = game.get(
            task_name
        )

        if task:

            try:

                if not task.done():
                    task.cancel()

            except Exception:
                pass

    werewolf_games.pop(
        chat_id,
        None
    )

    await safe_reply(
        update,
        "🛑 Đã hủy trận Ma Sói."
    )


# ============================================================
# /ww — HƯỚNG DẪN
# ============================================================

async def ww_command(
    update,
    context
):

    if not await require_group(update):
        return

    text = (
        "🐺 HƯỚNG DẪN MA SÓI\n\n"
        "/masoi — Tạo phòng Ma Sói\n"
        "/masoistatus — Xem trạng thái trận\n"
        "/huyma — Hủy trận\n"
        "/ww — Xem hướng dẫn\n\n"
        "👥 Phòng có từ 4 đến 9 người.\n"
        "⏳ Thời gian tham gia: 3 phút.\n\n"
        "🌙 Ban đêm các vai trò đặc biệt "
        "sẽ lần lượt hành động.\n"
        "🌅 Ban ngày người chơi thảo luận "
        "và bỏ phiếu."
    )

    await safe_reply(
        update,
        text
    )


# ============================================================
# ROUTER CALLBACK MA SÓI
# ============================================================

async def werewolf_callback_router(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    callback_data = (
        query.data
        or ""
    )

    if callback_data == "ww_join":

        await werewolf_join_callback(
            update,
            context
        )

        return


# ============================================================
# KẾT THÚC PHẦN 22/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 23/25
# MA SÓI — CHIA VAI + GỬI ROLE RIÊNG
# ============================================================

# ============================================================
# BẮT ĐẦU TRẬN MA SÓI
# ============================================================

async def start_werewolf_game(
    context,
    chat_id
):

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return

    players = list(
        game.get(
            "players",
            {}
        ).values()
    )

    if len(players) < WEREWOLF_MIN_PLAYERS:

        await safe_send_message(
            context,
            chat_id,
            "❌ Không đủ người để bắt đầu Ma Sói."
        )

        werewolf_games.pop(
            chat_id,
            None
        )

        return

    if len(players) > WEREWOLF_MAX_PLAYERS:

        players = players[
            :WEREWOLF_MAX_PLAYERS
        ]

        game["players"] = {
            player["id"]: player
            for player in players
        }

    roles = build_werewolf_roles(
        len(players)
    )

    if not roles:

        werewolf_games.pop(
            chat_id,
            None
        )

        return

    # --------------------------------------------------------
    # Gán vai
    # --------------------------------------------------------

    random.shuffle(players)

    for index, player in enumerate(players):

        role = roles[index]

        player["role"] = role
        player["alive"] = True
        player["role_sent"] = False

    game["status"] = "playing"
    game["phase"] = "night"
    game["round"] = 1

    game["night_actions"] = {}
    game["votes"] = {}
    game["deaths"] = []
    game["protected"] = None

    # --------------------------------------------------------
    # Gửi vai riêng
    # --------------------------------------------------------

    await send_werewolf_roles(
        context,
        chat_id
    )

    # --------------------------------------------------------
    # Thông báo bắt đầu
    # --------------------------------------------------------

    await safe_send_message(
        context,
        chat_id,
        "🐺 MA SÓI BẮT ĐẦU!\n\n"
        f"👥 Người chơi: {len(players)}\n"
        "🌙 Đêm 1 bắt đầu.\n\n"
        "📩 Hãy kiểm tra tin nhắn riêng "
        "với DTN BOT để xem vai trò của bạn."
    )

    await start_werewolf_night(
        context,
        chat_id
    )


# ============================================================
# THẺ VAI TRÒ
# ============================================================

def build_role_card(
    game,
    player
):

    role = player.get(
        "role"
    )

    role_data = WEREWOLF_ROLES.get(
        role,
        {}
    )

    role_name = role_data.get(
        "name",
        "❓ Không rõ"
    )

    team = role_data.get(
        "team",
        "unknown"
    )

    if team == "wolf":

        team_text = (
            "🐺 Phe Sói"
        )

    elif team == "zombie":

        team_text = (
            "🧟 Phe Zombie"
        )

    else:

        team_text = (
            "🏘️ Phe Dân làng"
        )

    descriptions = {

        "wolf":
            "Ban đêm chọn một người để phe Sói tấn công.",

        "villager":
            "Không có kỹ năng đặc biệt. "
            "Hãy quan sát và bỏ phiếu tìm Sói.",

        "seer":
            "Mỗi đêm có thể kiểm tra vai trò "
            "của một người.",

        "protector":
            "Mỗi đêm bảo vệ một người khỏi "
            "bị Sói tấn công.",

        "witch":
            "Có bình cứu một người và bình độc "
            "để loại một người.",

        "hunter":
            "Khi bị loại, có thể chọn một người "
            "để bắn.",

        "zombie":
            "Có khả năng đánh dấu mục tiêu. "
            "Mục tiêu bị đánh dấu nhiều lần "
            "có thể bị Zombie loại."
    }

    description = descriptions.get(
        role,
        "Không có mô tả."
    )

    return (
        "🐺 THẺ VAI TRÒ MA SÓI\n\n"
        f"🎭 Vai trò: {role_name}\n"
        f"⚔️ Phe: {team_text}\n\n"
        f"📖 Kỹ năng:\n"
        f"{description}\n\n"
        "⚠️ Không tiết lộ vai trò của bạn "
        "cho người khác."
    )


# ============================================================
# GỬI ROLE RIÊNG
# ============================================================

async def send_werewolf_roles(
    context,
    chat_id
):

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return

    for player in game.get(
        "players",
        {}
    ).values():

        user_id = player.get(
            "id"
        )

        if not user_id:
            continue

        try:

            sent = await context.bot.send_message(
                chat_id=user_id,
                text=build_role_card(
                    game,
                    player
                )
            )

            player["role_sent"] = True

            # Lưu ID message để có thể xóa sau
            player["role_message_id"] = (
                sent.message_id
            )

            create_background_task(
                delete_role_card_later(
                    context,
                    user_id,
                    sent.message_id
                )
            )

        except TelegramError as e:

            log_event(
                "Không thể gửi role riêng "
                f"cho {user_id}: {e}"
            )

            player["role_sent"] = False

            try:

                await safe_send_message(
                    context,
                    chat_id,
                    "⚠️ Một người chơi chưa mở "
                    "tin nhắn riêng với DTN BOT."
                )

            except Exception:
                pass


# ============================================================
# XÓA THẺ ROLE SAU KHOẢNG 1 PHÚT
# ============================================================

async def delete_role_card_later(
    context,
    user_id,
    message_id
):

    try:

        await asyncio.sleep(
            60
        )

        try:

            await context.bot.delete_message(
                chat_id=user_id,
                message_id=message_id
            )

        except TelegramError:
            pass

    except asyncio.CancelledError:
        pass

    except Exception as e:

        log_event(
            f"Lỗi xóa role card: {e}"
        )


# ============================================================
# LẤY ROLE CỦA PLAYER
# ============================================================

def get_werewolf_role(
    game,
    user_id
):

    player = get_werewolf_player(
        game,
        user_id
    )

    if not player:
        return None

    return player.get(
        "role"
    )


# ============================================================
# KIỂM TRA CÓ ROLE NÀY CÒN SỐNG
# ============================================================

def has_alive_role(
    game,
    role
):

    players = get_players_by_role(
        game,
        role
    )

    return len(players) > 0


# ============================================================
# LẤY NGƯỜI CHƠI THEO ROLE
# ============================================================

def get_first_alive_role(
    game,
    role
):

    players = get_players_by_role(
        game,
        role
    )

    if not players:
        return None

    return players[0]


# ============================================================
# ĐÁNH DẤU PLAYER CHẾT
# ============================================================

def kill_werewolf_player(
    game,
    user_id,
    reason="unknown"
):

    player = get_werewolf_player(
        game,
        user_id
    )

    if not player:
        return False

    if not player.get(
        "alive",
        False
    ):
        return False

    player["alive"] = False

    game.setdefault(
        "deaths",
        []
    ).append({
        "user_id": user_id,
        "reason": reason,
        "round": game.get(
            "round",
            0
        ),
    })

    return True


# ============================================================
# RESET DỮ LIỆU BAN ĐÊM
# ============================================================

def reset_werewolf_night(
    game
):

    game["night_actions"] = {}

    game["protected"] = None

    game["witch_heal_target"] = None

    game["witch_poison_target"] = None

    game["hunter_target"] = None

    for player in game.get(
        "players",
        {}
    ).values():

        player["wolf_target"] = None
        player["seer_target"] = None
        player["protected"] = False


# ============================================================
# KẾT THÚC PHẦN 23/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 24/25
# MA SÓI — BAN ĐÊM / KỸ NĂNG / BỎ PHIẾU
# ============================================================

# ============================================================
# NÚT CHỌN MỤC TIÊU
# ============================================================

def werewolf_target_keyboard(
    game,
    prefix,
    only_alive=True,
    exclude_user_id=None
):

    buttons = []

    for player in game.get(
        "players",
        {}
    ).values():

        user_id = player.get("id")

        if not user_id:
            continue

        if only_alive and not player.get(
            "alive",
            False
        ):
            continue

        if exclude_user_id is not None:
            if user_id == exclude_user_id:
                continue

        name = player.get(
            "name",
            "Không rõ"
        )

        buttons.append([
            InlineKeyboardButton(
                name[:30],
                callback_data=f"{prefix}:{user_id}"
            )
        ])

    return InlineKeyboardMarkup(
        buttons
    )


# ============================================================
# BẮT ĐẦU BAN ĐÊM
# ============================================================

async def start_werewolf_night(
    context,
    chat_id
):

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return

    if game.get(
        "status"
    ) != "playing":
        return

    game["phase"] = "night"

    reset_werewolf_night(
        game
    )

    round_number = game.get(
        "round",
        1
    )

    await safe_send_message(
        context,
        chat_id,
        "🌙 ĐÊM "
        f"{round_number}"
        "\n\n"
        "🤫 Mọi người hãy giữ im lặng.\n"
        "📩 Các vai trò đặc biệt hãy kiểm tra "
        "tin nhắn riêng với DTN BOT."
    )

    # --------------------------------------------------------
    # Gửi nút cho Sói
    # --------------------------------------------------------

    wolves = get_players_by_role(
        game,
        "wolf"
    )

    for wolf in wolves:

        keyboard = werewolf_target_keyboard(
            game,
            "ww_wolf",
            only_alive=True,
            exclude_user_id=wolf["id"]
        )

        try:

            await context.bot.send_message(
                chat_id=wolf["id"],
                text=(
                    "🐺 LƯỢT SÓI\n\n"
                    "Chọn người bạn muốn "
                    "phe Sói tấn công:"
                ),
                reply_markup=keyboard
            )

        except TelegramError:
            pass

    # --------------------------------------------------------
    # Tiên tri
    # --------------------------------------------------------

    seer = get_first_alive_role(
        game,
        "seer"
    )

    if seer:

        keyboard = werewolf_target_keyboard(
            game,
            "ww_seer",
            only_alive=True,
            exclude_user_id=seer["id"]
        )

        try:

            await context.bot.send_message(
                chat_id=seer["id"],
                text=(
                    "🔮 LƯỢT TIÊN TRI\n\n"
                    "Chọn một người để kiểm tra:"
                ),
                reply_markup=keyboard
            )

        except TelegramError:
            pass

    # --------------------------------------------------------
    # Bảo vệ
    # --------------------------------------------------------

    protector = get_first_alive_role(
        game,
        "protector"
    )

    if protector:

        keyboard = werewolf_target_keyboard(
            game,
            "ww_protect",
            only_alive=True
        )

        try:

            await context.bot.send_message(
                chat_id=protector["id"],
                text=(
                    "🛡️ LƯỢT BẢO VỆ\n\n"
                    "Chọn một người để bảo vệ đêm nay:"
                ),
                reply_markup=keyboard
            )

        except TelegramError:
            pass

    # --------------------------------------------------------
    # Phù thủy
    # --------------------------------------------------------

    witch = get_first_alive_role(
        game,
        "witch"
    )

    if witch:

        keyboard_buttons = []

        # Bình cứu
        if not game.get(
            "witch_heal_used",
            False
        ):

            keyboard_buttons.append([
                InlineKeyboardButton(
                    "❤️ Cứu người bị Sói",
                    callback_data="ww_witch_heal"
                )
            ])

        # Bình độc
        if not game.get(
            "witch_poison_used",
            False
        ):

            keyboard_buttons.append([
                InlineKeyboardButton(
                    "☠️ Dùng bình độc",
                    callback_data="ww_witch_poison"
                )
            ])

        keyboard_buttons.append([
            InlineKeyboardButton(
                "⏭️ Bỏ qua",
                callback_data="ww_witch_skip"
            )
        ])

        try:

            await context.bot.send_message(
                chat_id=witch["id"],
                text=(
                    "🧙 LƯỢT PHÙ THỦY\n\n"
                    "Bạn có thể sử dụng bình cứu "
                    "hoặc bình độc."
                ),
                reply_markup=InlineKeyboardMarkup(
                    keyboard_buttons
                )
            )

        except TelegramError:
            pass

    # --------------------------------------------------------
    # Zombie
    # --------------------------------------------------------

    zombie = get_first_alive_role(
        game,
        "zombie"
    )

    if zombie:

        keyboard = werewolf_target_keyboard(
            game,
            "ww_zombie",
            only_alive=True,
            exclude_user_id=zombie["id"]
        )

        try:

            await context.bot.send_message(
                chat_id=zombie["id"],
                text=(
                    "🧟 LƯỢT ZOMBIE\n\n"
                    "Chọn người muốn đánh dấu:"
                ),
                reply_markup=keyboard
            )

        except TelegramError:
            pass

    # --------------------------------------------------------
    # Tự động xử lý ban đêm sau thời gian chờ
    # --------------------------------------------------------

    game["phase_task"] = create_background_task(
        werewolf_night_timeout(
            context,
            chat_id
        )
    )


# ============================================================
# TIMEOUT BAN ĐÊM
# ============================================================

async def werewolf_night_timeout(
    context,
    chat_id
):

    try:

        await asyncio.sleep(
            60
        )

        game = get_werewolf_game(
            chat_id
        )

        if not game:
            return

        if game.get(
            "phase"
        ) != "night":
            return

        await resolve_werewolf_night(
            context,
            chat_id
        )

    except asyncio.CancelledError:
        return

    except Exception as e:

        log_event(
            f"Lỗi timeout Ma Sói: {e}"
        )


# ============================================================
# CALLBACK CHỌN MỤC TIÊU BAN ĐÊM
# ============================================================

async def werewolf_night_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    user = query.from_user

    if not user:
        return

    data = query.data or ""

    if ":" not in data:
        return

    prefix, target_text = data.split(
        ":",
        1
    )

    try:
        target_id = int(target_text)
    except ValueError:
        return

    chat_id = (
        query.message.chat.id
        if query.message
        else None
    )

    if not chat_id:
        return

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        await query.answer(
            "Trận đấu không còn tồn tại.",
            show_alert=True
        )
        return

    if game.get(
        "phase"
    ) != "night":

        await query.answer(
            "Hiện không phải ban đêm.",
            show_alert=True
        )
        return

    player = get_werewolf_player(
        game,
        user.id
    )

    target = get_werewolf_player(
        game,
        target_id
    )

    if not player or not player.get(
        "alive",
        False
    ):

        await query.answer(
            "Bạn đã bị loại.",
            show_alert=True
        )
        return

    if not target or not target.get(
        "alive",
        False
    ):

        await query.answer(
            "Mục tiêu không hợp lệ.",
            show_alert=True
        )
        return

    # --------------------------------------------------------
    # SÓI
    # --------------------------------------------------------

    if prefix == "ww_wolf":

        if player.get(
            "role"
        ) != "wolf":

            await query.answer(
                "Bạn không phải Sói.",
                show_alert=True
            )
            return

        wolves = get_players_by_role(
            game,
            "wolf"
        )

        selected_targets = []

        for wolf in wolves:

            action = game[
                "night_actions"
            ].get(
                str(wolf["id"])
            )

            if action:
                selected_targets.append(
                    action
                )

        game[
            "night_actions"
        ][str(user.id)] = target_id

        await query.answer(
            "🐺 Đã chọn mục tiêu."
        )

        # Khi tất cả Sói đã chọn
        alive_wolves = len(
            wolves
        )

        selected_count = 0

        for wolf in wolves:

            if str(wolf["id"]) in game[
                "night_actions"
            ]:

                selected_count += 1

        if selected_count >= alive_wolves:

            # Hủy timeout cũ
            task = game.get(
                "phase_task"
            )

            if task:

                try:

                    if not task.done():
                        task.cancel()

                except Exception:
                    pass

            await resolve_werewolf_night(
                context,
                chat_id
            )

        return

    # --------------------------------------------------------
    # TIÊN TRI
    # --------------------------------------------------------

    if prefix == "ww_seer":

        if player.get(
            "role"
        ) != "seer":

            await query.answer(
                "Bạn không phải Tiên tri.",
                show_alert=True
            )
            return

        role = target.get(
            "role"
        )

        role_name = WEREWOLF_ROLES.get(
            role,
            {}
        ).get(
            "name",
            "❓"
        )

        game[
            "night_actions"
        ][str(user.id)] = target_id

        await query.answer(
            "🔮 Đã kiểm tra."
        )

        try:

            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    "🔮 KẾT QUẢ TIÊN TRI\n\n"
                    f"👤 {target.get('name')}\n"
                    f"🎭 Vai trò: {role_name}"
                )
            )

        except TelegramError:
            pass

        return

    # --------------------------------------------------------
    # BẢO VỆ
    # --------------------------------------------------------

    if prefix == "ww_protect":

        if player.get(
            "role"
        ) != "protector":

            await query.answer(
                "Bạn không phải Bảo vệ.",
                show_alert=True
            )
            return

        last_protected = game.get(
            "last_protected"
        )

        if (
            target_id == last_protected
            and game.get("round", 0)
            > 1
        ):

            await query.answer(
                "Không thể bảo vệ cùng một "
                "người liên tiếp.",
                show_alert=True
            )
            return

        game["protected"] = target_id
        game["last_protected"] = target_id

        game[
            "night_actions"
        ][str(user.id)] = target_id

        await query.answer(
            "🛡️ Đã bảo vệ mục tiêu."
        )

        return

    # --------------------------------------------------------
    # ZOMBIE
    # --------------------------------------------------------

    if prefix == "ww_zombie":

        if player.get(
            "role"
        ) != "zombie":

            await query.answer(
                "Bạn không phải Zombie.",
                show_alert=True
            )
            return

        marks = game.setdefault(
            "zombie_marks",
            {}
        )

        key = str(target_id)

        marks[key] = marks.get(
            key,
            0
        ) + 1

        game[
            "night_actions"
        ][str(user.id)] = target_id

        target["zombie_marks"] = marks[key]

        await query.answer(
            f"🧟 Đã đánh dấu "
            f"{marks[key]}/3."
        )

        return


# ============================================================
# GIẢI QUYẾT BAN ĐÊM
# ============================================================

async def resolve_werewolf_night(
    context,
    chat_id
):

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return

    if game.get(
        "phase"
    ) != "night":
        return

    game["phase"] = "morning"

    # --------------------------------------------------------
    # Hủy timeout
    # --------------------------------------------------------

    task = game.get(
        "phase_task"
    )

    if task:

        try:

            if not task.done():
                task.cancel()

        except Exception:
            pass

    # --------------------------------------------------------
    # Mục tiêu Sói
    # --------------------------------------------------------

    wolves = get_players_by_role(
        game,
        "wolf"
    )

    wolf_targets = []

    for wolf in wolves:

        target_id = game[
            "night_actions"
        ].get(
            str(wolf["id"])
        )

        if target_id:
            wolf_targets.append(
                target_id
            )

    wolf_target = None

    if wolf_targets:

        counts = {}

        for target_id in wolf_targets:

            counts[target_id] = (
                counts.get(
                    target_id,
                    0
                ) + 1
            )

        wolf_target = max(
            counts,
            key=counts.get
        )

    # --------------------------------------------------------
    # Bảo vệ
    # --------------------------------------------------------

    protected = game.get(
        "protected"
    )

    # --------------------------------------------------------
    # Phù thủy cứu
    # --------------------------------------------------------

    witch_heal = game.get(
        "witch_heal_target"
    )

    if (
        wolf_target
        and protected == wolf_target
    ):

        wolf_target = None

    if (
        wolf_target
        and witch_heal == wolf_target
    ):

        wolf_target = None

    # --------------------------------------------------------
    # Người chết trong đêm
    # --------------------------------------------------------

    night_deaths = []

    if wolf_target:

        if kill_werewolf_player(
            game,
            wolf_target,
            "wolf"
        ):

            night_deaths.append(
                wolf_target
            )

    # --------------------------------------------------------
    # Bình độc
    # --------------------------------------------------------

    poison_target = game.get(
        "witch_poison_target"
    )

    if poison_target:

        if poison_target not in night_deaths:

            if kill_werewolf_player(
                game,
                poison_target,
                "witch"
            ):

                night_deaths.append(
                    poison_target
                )

    # --------------------------------------------------------
    # Zombie
    # --------------------------------------------------------

    zombie_marks = game.get(
        "zombie_marks",
        {}
    )

    zombie_kills = []

    for target_text, count in zombie_marks.items():

        if count < 3:
            continue

        try:
            target_id = int(
                target_text
            )
        except ValueError:
            continue

        if target_id in night_deaths:
            continue

        if kill_werewolf_player(
            game,
            target_id,
            "zombie"
        ):

            zombie_kills.append(
                target_id
            )

    night_deaths.extend(
        zombie_kills
    )

    # --------------------------------------------------------
    # Thông báo sáng
    # --------------------------------------------------------

    if night_deaths:

        lines = [
            "🌅 TRỜI SÁNG!",
            ""
        ]

        for user_id in night_deaths:

            lines.append(
                f"💀 {werewolf_player_name(game, user_id)} "
                "đã bị loại."
            )

        await safe_send_message(
            context,
            chat_id,
            "\n".join(lines)
        )

    else:

        await safe_send_message(
            context,
            chat_id,
            "🌅 TRỜI SÁNG!\n\n"
            "✨ Đêm qua không có ai bị loại."
        )

    # --------------------------------------------------------
    # Kiểm tra thắng
    # --------------------------------------------------------

    if await check_werewolf_win(
        context,
        chat_id
    ):

        return

    # --------------------------------------------------------
    # Sang bỏ phiếu
    # --------------------------------------------------------

    await start_werewolf_vote(
        context,
        chat_id
    )


# ============================================================
# BẮT ĐẦU BỎ PHIẾU
# ============================================================

async def start_werewolf_vote(
    context,
    chat_id
):

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return

    game["phase"] = "vote"
    game["votes"] = {}

    keyboard = werewolf_target_keyboard(
        game,
        "ww_vote",
        only_alive=True
    )

    await safe_send_message(
        context,
        chat_id,
        "🗳️ BỎ PHIẾU\n\n"
        "Hãy chọn người bạn nghi là Sói.\n"
        "⏳ Thời gian bỏ phiếu: 60 giây.",
        reply_markup=keyboard
    )

    game["phase_task"] = create_background_task(
        werewolf_vote_timeout(
            context,
            chat_id
        )
    )


# ============================================================
# TIMEOUT BỎ PHIẾU
# ============================================================

async def werewolf_vote_timeout(
    context,
    chat_id
):

    try:

        await asyncio.sleep(
            60
        )

        game = get_werewolf_game(
            chat_id
        )

        if not game:
            return

        if game.get(
            "phase"
        ) != "vote":
            return

        await resolve_werewolf_vote(
            context,
            chat_id
        )

    except asyncio.CancelledError:
        return

    except Exception as e:

        log_event(
            f"Lỗi vote timeout Ma Sói: {e}"
        )


# ============================================================
# CALLBACK BỎ PHIẾU
# ============================================================

async def werewolf_vote_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    user = query.from_user

    if not user:
        return

    data = query.data or ""

    if not data.startswith(
        "ww_vote:"
    ):
        return

    try:

        target_id = int(
            data.split(
                ":",
                1
            )[1]
        )

    except (ValueError, IndexError):

        await query.answer(
            "Mục tiêu không hợp lệ.",
            show_alert=True
        )

        return

    chat_id = (
        query.message.chat.id
        if query.message
        else None
    )

    if not chat_id:
        return

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        await query.answer(
            "Trận đấu không còn tồn tại.",
            show_alert=True
        )
        return

    if game.get(
        "phase"
    ) != "vote":

        await query.answer(
            "Hiện không phải lúc bỏ phiếu.",
            show_alert=True
        )
        return

    player = get_werewolf_player(
        game,
        user.id
    )

    target = get_werewolf_player(
        game,
        target_id
    )

    if not player or not player.get(
        "alive",
        False
    ):

        await query.answer(
            "Bạn đã bị loại.",
            show_alert=True
        )
        return

    if not target or not target.get(
        "alive",
        False
    ):

        await query.answer(
            "Người được chọn không hợp lệ.",
            show_alert=True
        )
        return

    game["votes"][
        str(user.id)
    ] = target_id

    await query.answer(
        "🗳️ Đã ghi nhận phiếu."
    )

    alive_players = len(
        get_alive_players(game)
    )

    if len(
        game["votes"]
    ) >= alive_players:

        task = game.get(
            "phase_task"
        )

        if task:

            try:

                if not task.done():
                    task.cancel()

            except Exception:
                pass

        await resolve_werewolf_vote(
            context,
            chat_id
        )


# ============================================================
# GIẢI QUYẾT BỎ PHIẾU
# ============================================================

async def resolve_werewolf_vote(
    context,
    chat_id
):

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return

    if game.get(
        "phase"
    ) != "vote":
        return

    game["phase"] = "morning"

    votes = game.get(
        "votes",
        {}
    )

    counts = {}

    for target_id in votes.values():

        counts[target_id] = (
            counts.get(
                target_id,
                0
            ) + 1
        )

    if not counts:

        await safe_send_message(
            context,
            chat_id,
            "🗳️ Không có đủ phiếu.\n\n"
            "🌙 Đêm mới bắt đầu."
        )

        game["round"] = (
            game.get(
                "round",
                1
            ) + 1
        )

        await start_werewolf_night(
            context,
            chat_id
        )

        return

    max_votes = max(
        counts.values()
    )

    candidates = [
        user_id
        for user_id, count
        in counts.items()
        if count == max_votes
    ]

    # Hòa phiếu -> không ai bị loại
    if len(candidates) != 1:

        await safe_send_message(
            context,
            chat_id,
            "🗳️ Kết quả bỏ phiếu bị hòa.\n\n"
            "Không ai bị loại."
        )

    else:

        target_id = candidates[0]

        if kill_werewolf_player(
            game,
            target_id,
            "vote"
        ):

            target = get_werewolf_player(
                game,
                target_id
            )

            role = target.get(
                "role"
            ) if target else None

            role_name = WEREWOLF_ROLES.get(
                role,
                {}
            ).get(
                "name",
                "❓"
            )

            await safe_send_message(
                context,
                chat_id,
                "🗳️ KẾT QUẢ BỎ PHIẾU\n\n"
                f"💀 {werewolf_player_name(game, target_id)} "
                "đã bị loại.\n"
                f"🎭 Vai trò: {role_name}"
            )

    # --------------------------------------------------------
    # Kiểm tra thắng
    # --------------------------------------------------------

    if await check_werewolf_win(
        context,
        chat_id
    ):

        return

    # --------------------------------------------------------
    # Sang đêm tiếp theo
    # --------------------------------------------------------

    game["round"] = (
        game.get(
            "round",
            1
        ) + 1
    )

    await start_werewolf_night(
        context,
        chat_id
    )


# ============================================================
# KẾT THÚC PHẦN 24/25
# ============================================================

# ============================================================
# DTN BOT
# PHẦN 25/25
# MA SÓI — KẾT THÚC + CALLBACK + MAIN
# ============================================================


# ============================================================
# HÀM BẮT BUỘC PHẢI Ở TRONG NHÓM
# ============================================================

async def require_group(update):

    if is_group(update):
        return True

    message = update.effective_message

    if message:

        await message.reply_text(
            "ngươi bớt ngu đi chức năng nhóm ngươi lại riêng tư"
        )

    return False


# ============================================================
# GHI ĐÈ require_admin
# ĐỂ CHỨC NĂNG NHÓM TRONG PRIVATE CHAT TRẢ ĐÚNG CÂU
# ============================================================

async def require_admin(update, context):

    if not is_group(update):

        message = update.effective_message

        if message:

            await message.reply_text(
                "ngươi bớt ngu đi chức năng nhóm ngươi lại riêng tư"
            )

        return False

    user = update.effective_user

    if not user:
        return False

    register_owner(user)

    if is_owner(user):
        return True

    if await is_admin(
        context,
        update.effective_chat.id,
        user.id
    ):

        return True

    await update.effective_message.reply_text(
        "❌ Bạn cần là admin để sử dụng lệnh này."
    )

    return False


# ============================================================
# GHI ĐÈ /help
# ============================================================

async def help_command(update, context):

    if is_group(update):

        await safe_reply(
            update,
            "help cái đầu buồi chủ tao chưa ra help group OK"
        )

        return

    await safe_reply(
        update,
        HELP_TEXT
    )


# ============================================================
# MA SÓI — PHÙ THỦY
# ============================================================

async def werewolf_witch_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    user = query.from_user

    if not user:
        return

    data = query.data or ""

    if not data.startswith(
        "ww_witch_"
    ):
        return

    chat_id = None

    if query.message:
        chat_id = query.message.chat.id

    if not chat_id:
        return

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        await query.answer(
            "Trận đấu không còn tồn tại.",
            show_alert=True
        )
        return

    if game.get("phase") != "night":

        await query.answer(
            "Hiện không phải ban đêm.",
            show_alert=True
        )

        return

    player = get_werewolf_player(
        game,
        user.id
    )

    if not player:

        await query.answer(
            "Bạn không ở trong trận.",
            show_alert=True
        )

        return

    if not player.get("alive", False):

        await query.answer(
            "Bạn đã bị loại.",
            show_alert=True
        )

        return

    if player.get("role") != "witch":

        await query.answer(
            "Bạn không phải Phù thủy.",
            show_alert=True
        )

        return

    # --------------------------------------------------------
    # BÌNH CỨU
    # --------------------------------------------------------

    if data == "ww_witch_heal":

        if game.get(
            "witch_heal_used",
            False
        ):

            await query.answer(
                "Bạn đã dùng bình cứu rồi.",
                show_alert=True
            )

            return

        wolf_target = None

        wolves = get_players_by_role(
            game,
            "wolf"
        )

        targets = []

        for wolf in wolves:

            target_id = game[
                "night_actions"
            ].get(
                str(wolf["id"])
            )

            if target_id:
                targets.append(
                    target_id
                )

        if targets:

            counts = {}

            for target_id in targets:

                counts[target_id] = (
                    counts.get(
                        target_id,
                        0
                    ) + 1
                )

            wolf_target = max(
                counts,
                key=counts.get
            )

        if not wolf_target:

            await query.answer(
                "Đêm nay chưa có mục tiêu Sói.",
                show_alert=True
            )

            return

        game[
            "witch_heal_used"
        ] = True

        game[
            "witch_heal_target"
        ] = wolf_target

        await query.answer(
            "❤️ Đã dùng bình cứu."
        )

        return

    # --------------------------------------------------------
    # BÌNH ĐỘC
    # --------------------------------------------------------

    if data == "ww_witch_poison":

        if game.get(
            "witch_poison_used",
            False
        ):

            await query.answer(
                "Bạn đã dùng bình độc rồi.",
                show_alert=True
            )

            return

        keyboard = werewolf_target_keyboard(
            game,
            "ww_witch_poison_target",
            only_alive=True,
            exclude_user_id=user.id
        )

        try:

            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    "🧙 BÌNH ĐỘC\n\n"
                    "Chọn người bạn muốn dùng "
                    "bình độc:"
                ),
                reply_markup=keyboard
            )

        except TelegramError:
            pass

        await query.answer(
            "☠️ Hãy chọn mục tiêu."
        )

        return

    # --------------------------------------------------------
    # BỎ QUA
    # --------------------------------------------------------

    if data == "ww_witch_skip":

        game[
            "night_actions"
        ][str(user.id)] = "skip"

        await query.answer(
            "⏭️ Đã bỏ qua."
        )

        return


# ============================================================
# CALLBACK MỤC TIÊU BÌNH ĐỘC
# ============================================================

async def werewolf_witch_poison_target_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(
        "ww_witch_poison_target:"
    ):
        return

    user = query.from_user

    if not user:
        return

    try:

        target_id = int(
            data.split(
                ":",
                1
            )[1]
        )

    except (ValueError, IndexError):

        await query.answer(
            "Mục tiêu không hợp lệ.",
            show_alert=True
        )

        return

    chat_id = (
        query.message.chat.id
        if query.message
        else None
    )

    if not chat_id:
        return

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return

    player = get_werewolf_player(
        game,
        user.id
    )

    target = get_werewolf_player(
        game,
        target_id
    )

    if not player or player.get(
        "role"
    ) != "witch":

        await query.answer(
            "Bạn không phải Phù thủy.",
            show_alert=True
        )

        return

    if game.get(
        "witch_poison_used",
        False
    ):

        await query.answer(
            "Bình độc đã được sử dụng.",
            show_alert=True
        )

        return

    if not target or not target.get(
        "alive",
        False
    ):

        await query.answer(
            "Mục tiêu không hợp lệ.",
            show_alert=True
        )

        return

    game[
        "witch_poison_used"
    ] = True

    game[
        "witch_poison_target"
    ] = target_id

    await query.answer(
        "☠️ Đã chọn mục tiêu."
    )


# ============================================================
# MA SÓI — THỢ SĂN
# ============================================================

async def werewolf_hunter_check(
    context,
    chat_id,
    dead_user_id
):

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return False

    dead_player = get_werewolf_player(
        game,
        dead_user_id
    )

    if not dead_player:
        return False

    if dead_player.get(
        "role"
    ) != "hunter":

        return False

    await safe_send_message(
        context,
        chat_id,
        "🔫 THỢ SĂN ĐÃ BỊ LOẠI!\n\n"
        "Thợ săn có thể chọn một người để bắn."
    )

    try:

        keyboard = werewolf_target_keyboard(
            game,
            "ww_hunter",
            only_alive=True
        )

        await context.bot.send_message(
            chat_id=dead_user_id,
            text=(
                "🔫 Bạn là Thợ săn.\n\n"
                "Chọn một người để bắn:"
            ),
            reply_markup=keyboard
        )

    except TelegramError:
        pass

    return True


# ============================================================
# CALLBACK THỢ SĂN
# ============================================================

async def werewolf_hunter_callback(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if not data.startswith(
        "ww_hunter:"
    ):
        return

    user = query.from_user

    if not user:
        return

    try:

        target_id = int(
            data.split(
                ":",
                1
            )[1]
        )

    except (ValueError, IndexError):

        await query.answer(
            "Mục tiêu không hợp lệ.",
            show_alert=True
        )

        return

    chat_id = (
        query.message.chat.id
        if query.message
        else None
    )

    if not chat_id:
        return

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return

    player = get_werewolf_player(
        game,
        user.id
    )

    target = get_werewolf_player(
        game,
        target_id
    )

    if not player:
        return

    if player.get(
        "role"
    ) != "hunter":

        await query.answer(
            "Bạn không phải Thợ săn.",
            show_alert=True
        )

        return

    if not target or not target.get(
        "alive",
        False
    ):

        await query.answer(
            "Mục tiêu không hợp lệ.",
            show_alert=True
        )

        return

    if not game.get(
        "hunter_alive",
        True
    ):
        pass

    kill_werewolf_player(
        game,
        target_id,
        "hunter"
    )

    await query.answer(
        "🔫 Đã bắn."
    )

    await safe_send_message(
        context,
        chat_id,
        "🔫 Thợ săn đã sử dụng phát bắn cuối cùng.\n\n"
        f"💀 {werewolf_player_name(game, target_id)} "
        "đã bị loại."
    )

    await check_werewolf_win(
        context,
        chat_id
    )


# ============================================================
# KIỂM TRA THẮNG MA SÓI
# ============================================================

async def check_werewolf_win(
    context,
    chat_id
):

    game = get_werewolf_game(
        chat_id
    )

    if not game:
        return False

    if game.get(
        "status"
    ) != "playing":

        return False

    alive_players = get_alive_players(
        game
    )

    wolves = [
        player
        for player in alive_players
        if player.get("role") == "wolf"
    ]

    zombies = [
        player
        for player in alive_players
        if player.get("role") == "zombie"
    ]

    village = [
        player
        for player in alive_players
        if player.get("role")
        in (
            "villager",
            "seer",
            "protector",
            "witch",
            "hunter",
        )
    ]

    winner = None

    # Zombie thắng nếu Zombie là phe cuối cùng
    if zombies and not wolves and not village:

        winner = "zombie"

    # Sói thắng nếu số Sói >= số người phe làng
    elif wolves and len(wolves) >= len(
        village
    ) + len(zombies):

        winner = "wolf"

    # Dân thắng khi toàn bộ Sói và Zombie bị loại
    elif not wolves and not zombies:

        winner = "village"

    if not winner:
        return False

    game["winner"] = winner
    game["status"] = "finished"
    game["phase"] = "finished"

    winner_text = {
        "wolf": "🐺 PHE SÓI THẮNG!",
        "village": "🏘️ PHE DÂN LÀNG THẮNG!",
        "zombie": "🧟 PHE ZOMBIE THẮNG!",
    }.get(
        winner,
        "🏁 TRẬN ĐẤU KẾT THÚC!"
    )

    await safe_send_message(
        context,
        chat_id,
        winner_text
        + "\n\n"
        + build_werewolf_player_list(
            game,
            show_roles=True
        )
    )

    # Không xóa ngay để /masoistatus vẫn xem được
    return True


# ============================================================
# ROUTER CALLBACK MA SÓI — BẢN ĐẦY ĐỦ
# ============================================================

async def werewolf_callback_router(
    update,
    context
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data == "ww_join":

        await werewolf_join_callback(
            update,
            context
        )

        return

    if data.startswith(
        "ww_wolf:"
    ):

        await werewolf_night_callback(
            update,
            context
        )

        return

    if data.startswith(
        "ww_seer:"
    ):

        await werewolf_night_callback(
            update,
            context
        )

        return

    if data.startswith(
        "ww_protect:"
    ):

        await werewolf_night_callback(
            update,
            context
        )

        return

    if data.startswith(
        "ww_zombie:"
    ):

        await werewolf_night_callback(
            update,
            context
        )

        return

    if data.startswith(
        "ww_witch_poison_target:"
    ):

        await werewolf_witch_poison_target_callback(
            update,
            context
        )

        return

    if data.startswith(
        "ww_witch_"
    ):

        await werewolf_witch_callback(
            update,
            context
        )

        return

    if data.startswith(
        "ww_hunter:"
    ):

        await werewolf_hunter_callback(
            update,
            context
        )

        return

    if data.startswith(
        "ww_vote:"
    ):

        await werewolf_vote_callback(
            update,
            context
        )

        return


# ============================================================
# /botpermission
# ============================================================

async def botpermission_command(
    update,
    context
):

    if not await require_group(update):
        return

    chat_id = update.effective_chat.id

    member = await get_bot_member(
        context,
        chat_id
    )

    if not member:

        await safe_reply(
            update,
            "❌ Không lấy được thông tin quyền của bot."
        )

        return

    if member.status == ChatMemberStatus.OWNER:

        await safe_reply(
            update,
            "🤖 QUYỀN DTN BOT\n\n"
            "👑 Bot đang là Owner của nhóm."
        )

        return

    permissions = [
        (
            "Xóa tin nhắn",
            "can_delete_messages"
        ),
        (
            "Khóa/mở khóa thành viên",
            "can_restrict_members"
        ),
        (
            "Ghim tin nhắn",
            "can_pin_messages"
        ),
        (
            "Thăng/hạ admin",
            "can_promote_members"
        ),
        (
            "Quản lý nhóm",
            "can_manage_chat"
        ),
    ]

    lines = [
        "🤖 QUYỀN CỦA DTN BOT",
        ""
    ]

    for name, attribute in permissions:

        allowed = bool(
            getattr(
                member,
                attribute,
                False
            )
        )

        icon = "✅" if allowed else "❌"

        lines.append(
            f"{icon} {name}"
        )

    await safe_reply(
        update,
        "\n".join(lines)
    )


# ============================================================
# /debugmasoi
# ============================================================

async def debugmasoi_command(
    update,
    context
):

    if not await require_group(update):
        return

    if not await require_admin(
        update,
        context
    ):
        return

    chat_id = update.effective_chat.id

    game = get_werewolf_game(
        chat_id
    )

    if not game:

        await safe_reply(
            update,
            "🐺 Không có dữ liệu Ma Sói."
        )

        return

    lines = [
        "🔧 DEBUG MA SÓI",
        "",
        f"status: {game.get('status')}",
        f"phase: {game.get('phase')}",
        f"round: {game.get('round')}",
        f"players: {len(game.get('players', {}))}",
        f"votes: {len(game.get('votes', {}))}",
        f"deaths: {len(game.get('deaths', []))}",
    ]

    await safe_reply(
        update,
        "\n".join(lines)
    )


# ============================================================
# CALLBACK CALLBACK ĐIỂM DANH
# ============================================================

# attendance_callback_router đã được định nghĩa ở PHẦN 17.


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context
):

    error = context.error

    log_event(
        f"Telegram error: {error}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if (
        not TOKEN
        or TOKEN == "PASTE_BOT_TOKEN_HERE"
    ):

        print(
            "=================================================="
        )

        print(
            "❌ CHƯA NHẬP BOT TOKEN"
        )

        print(
            "Hãy sửa biến TOKEN ở đầu file bot.py."
        )

        print(
            "=================================================="
        )

        return

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # ========================================================
    # COMMAND — CƠ BẢN
    # ========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
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

    # ========================================================
    # RULES
    # ========================================================

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

    # ========================================================
    # MODERATION
    # ========================================================

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

    # ========================================================
    # ADMIN
    # ========================================================

    application.add_handler(
        CommandHandler(
            "promote",
            promote_command
        )
    )

    application.add_handler(
        CommandHandler(
            "promotefull",
            promotefull_command
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
            lock_command
        )
    )

    application.add_handler(
        CommandHandler(
            "unlock",
            unlock_command
        )
    )

    # ========================================================
    # MESSAGE TOOLS
    # ========================================================

    application.add_handler(
        CommandHandler(
            "del",
            del_command
        )
    )

    application.add_handler(
        CommandHandler(
            "pin",
            pin_command
        )
    )

    application.add_handler(
        CommandHandler(
            "unpin",
            unpin_command
        )
    )

    # ========================================================
    # PROTECTION
    # ========================================================

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
            "stopfilter",
            stopfilter_command
        )
    )

    application.add_handler(
        CommandHandler(
            "afk",
            afk_command
        )
    )

    # ========================================================
    # THƠ
    # ========================================================

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

    # ========================================================
    # ĐIỂM DANH
    # ========================================================

    application.add_handler(
        CommandHandler(
            "diemdanh",
            diemdanh_command
        )
    )

    application.add_handler(
        CommandHandler(
            "attendance",
            attendance_info_command
        )
    )

    application.add_handler(
        CommandHandler(
            "topdiemdanh",
            attendance_leaderboard_command
        )
    )

    # ========================================================
    # GAME NỐI CHỮ
    # ========================================================

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

    # ========================================================
    # MA SÓI
    # ========================================================

    application.add_handler(
        CommandHandler(
            "masoi",
            masoi_command
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
            "huyma",
            huyma_command
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
            "botpermission",
            botpermission_command
        )
    )

    application.add_handler(
        CommandHandler(
            "debugmasoi",
            debugmasoi_command
        )
    )

    # ========================================================
    # CALLBACK — ĐIỂM DANH
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            attendance_callback_router,
            pattern=r"^attendance_"
        )
    )

    # ========================================================
    # CALLBACK — GAME NỐI CHỮ
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            word_callback_router,
            pattern=r"^word_"
        )
    )

    # ========================================================
    # CALLBACK — MA SÓI
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            werewolf_callback_router,
            pattern=r"^ww_"
        )
    )

    # ========================================================
    # TIN NHẮN GAME NỐI CHỮ
    #
    # Đặt trước handler bảo vệ để xử lý lượt chơi.
    # Handler bảo vệ vẫn được chạy ở group khác.
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            process_word_game
        ),
        group=0
    )

    # ========================================================
    # TIN NHẮN MEDIA
    # ========================================================

    application.add_handler(
        MessageHandler(
            (
                filters.PHOTO
                | filters.VIDEO
                | filters.Document.ALL
                | filters.AUDIO
                | filters.VOICE
                | filters.VIDEO_NOTE
            ),
            media_message_handler
        ),
        group=1
    )

    # ========================================================
    # THÀNH VIÊN MỚI / RỜI NHÓM
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            new_member_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.LEFT_CHAT_MEMBER,
            left_member_handler
        )
    )

    # ========================================================
    # REPLY SETRULES
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.REPLY
            & filters.TEXT
            & ~filters.COMMAND,
            setrules_reply_command
        ),
        group=2
    )

    # ========================================================
    # ERROR
    # ========================================================

    application.add_error_handler(
        error_handler
    )

    # ========================================================
    # KHỞI ĐỘNG
    # ========================================================

    print(
        "=================================================="
    )

    print(
        "🤖 DTN BOT đang khởi động..."
    )

    print(
        "👑 Owner : @DTN_207"
    )

    print(
        "=================================================="
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# CHẠY BOT
# ============================================================

if __name__ == "__main__":
    main()


# ============================================================
# HẾT TOÀN BỘ 25/25
# ============================================================

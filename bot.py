"""
BOT QUẢN LÝ NHÓM TELEGRAM - OSAKA
==================================
Bot quản lý nhóm Telegram với tên lệnh tiếng Việt, phản hồi song ngữ Việt/Anh.

DANH SÁCH LỆNH (xem chi tiết trong /help của bot):
  /start, /help
  /cammom (mute), /mocammom (unmute)
  /sut (ban), /mosut (unban), /da (kick)
  /khoa (lock nhóm), /mokhoa (unlock nhóm)
  /canhcao (warn), /xoacanhcao (reset warn)
  /ghim (pin), /boghim (unpin)
  /thangchuc (promote), /giangchuc (demote)
  /thongtin (user info)
  /noiquy (xem/đặt nội quy)
  /xoa (xóa tin nhắn)

Cách chọn "mục tiêu" (target) cho hầu hết lệnh quản trị:
  - Reply vào tin nhắn của người đó, HOẶC
  - /lenh <user_id>, HOẶC
  - /lenh @username  (chỉ hoạt động nếu username đó là công khai)

Yêu cầu: bot phải được thêm làm ADMIN trong nhóm với đủ quyền
(xóa tin nhắn, cấm/hạn chế thành viên, ghim tin nhắn, thăng chức...).
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import Chat, ChatPermissions, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============================================================
# DÁN TOKEN BOT VÀO ĐÂY (lấy từ @BotFather trên Telegram)
BOT_TOKEN = "8801642678:AAHmBSWsG2s7mj1mbtm9b1Yld0CwwVhH7jo"
# ============================================================

BOT_NAME = "Osaka"
DATA_FILE = Path(__file__).parent / "data.json"

# Quyền chat "mở" đầy đủ (dùng cho unmute / unlock)
FULL_PERMISSIONS = ChatPermissions(
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

# Quyền chat "đóng" (dùng cho mute / lock)
MUTED_PERMISSIONS = ChatPermissions(
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
)

DURATION_RE = re.compile(
    r"^(\d+)\s*(s|gy|giay|giây|p|ph|phut|phút|m|min|h|g|gio|giờ|d|ng|ngay|ngày)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Lưu trữ dữ liệu đơn giản bằng file JSON (số lần cảnh cáo, nội quy nhóm)
# ---------------------------------------------------------------------------

def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("data.json bị lỗi định dạng, tạo dữ liệu mới.")
            return {}
    return {}


def save_data(data: dict) -> None:
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Hàm hỗ trợ
# ---------------------------------------------------------------------------

def parse_duration(text: str):
    """Chuyển '5p', '1h', '2d'... thành timedelta. Trả None nếu không hợp lệ."""
    if not text:
        return None
    match = DURATION_RE.match(text.strip().lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit in ("s", "gy", "giay", "giây"):
        return timedelta(seconds=value)
    if unit in ("p", "ph", "phut", "phút", "m", "min"):
        return timedelta(minutes=value)
    if unit in ("h", "g", "gio", "giờ"):
        return timedelta(hours=value)
    if unit in ("d", "ng", "ngay", "ngày"):
        return timedelta(days=value)
    return None


async def ensure_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Kiểm tra: đang ở trong nhóm VÀ người gọi lệnh là admin/creator."""
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.effective_message.reply_text(
            "⚠️ Lệnh này chỉ dùng được trong nhóm.\n"
            "⚠️ This command only works inside a group."
        )
        return False

    member = await context.bot.get_chat_member(chat.id, user.id)
    if member.status not in ("administrator", "creator"):
        await update.effective_message.reply_text(
            "⛔ Bạn cần là admin của nhóm để dùng lệnh này.\n"
            "⛔ You must be a group admin to use this command."
        )
        return False
    return True


async def get_target_and_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Xác định người dùng mục tiêu theo thứ tự ưu tiên:
    reply tin nhắn > @username > user_id
    Trả về (user_id, tên_hiển_thị_html, phần_args_còn_lại)
    Nếu không tìm thấy: (None, None, args)
    """
    message = update.effective_message
    args = list(context.args or [])

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        return target_user.id, target_user.mention_html(), args

    if args:
        first = args[0]
        if first.startswith("@"):
            username = first[1:]
            try:
                chat = await context.bot.get_chat(f"@{username}")
                return chat.id, f"@{username}", args[1:]
            except Exception:
                return None, None, args
        if first.lstrip("-").isdigit():
            user_id = int(first)
            display = f"ID <code>{user_id}</code>"
            try:
                member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
                display = member.user.mention_html()
            except Exception:
                pass
            return user_id, display, args[1:]

    return None, None, args


# ---------------------------------------------------------------------------
# /start và /help
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("Vui Lòng Bạn Bấm /help để xem lệnh ạ")


HELP_TEXT = f"""🌸 <b>Chào mừng đến với {BOT_NAME}!</b>

<b>Cách chọn mục tiêu / How to target a user:</b>
Reply tin nhắn, hoặc <code>&lt;user_id&gt;</code>, hoặc <code>@username</code>.

👮 <b>Quản trị (chỉ admin) / Admin only</b>

<code>/cammom [thời gian]</code>
 Cấm chat thành viên. VD: <code>/cammom 5p</code> = câm 5 phút. Không nhập = vĩnh viễn.
 Mute a member. e.g. <code>/cammom 5p</code> = mute for 5 min. No duration = permanent.

<code>/mocammom</code>
 Bỏ câm mồm (unmute).

<code>/sut</code>
 Đuổi vĩnh viễn khỏi nhóm (ban).

<code>/mosut &lt;id/@username&gt;</code>
 Gỡ sút, cho phép vào lại nhóm (unban).

<code>/da</code>
 Đá khỏi nhóm nhưng có thể vào lại (kick).

<code>/khoa</code>
 Khóa nhóm, chỉ admin được nhắn (lock chat).

<code>/mokhoa</code>
 Mở khóa nhóm (unlock chat).

<code>/canhcao</code>
 Cảnh cáo thành viên, đủ 3 lần sẽ tự động bị sút (warn, auto-ban at 3).

<code>/xoacanhcao</code>
 Xóa hết cảnh cáo của thành viên (reset warns).

<code>/ghim</code>
 Ghim tin nhắn đang reply (pin message).

<code>/boghim</code>
 Bỏ ghim tin nhắn (unpin message).

<code>/thangchuc</code>
 Thăng thành viên làm phó nhóm/admin (promote to admin).

<code>/giangchuc</code>
 Giáng chức admin xuống thành viên thường (demote admin).

<code>/xoa</code>
 Xóa tin nhắn đang reply (delete message).

<code>/noiquy [nội dung]</code>
 Xem nội quy, hoặc admin đặt nội quy mới (view/set group rules).

ℹ️ <b>Khác / Other</b>

<code>/thongtin</code>
 Xem thông tin thành viên: ID, tên, username (user info).

<code>/start</code> · <code>/help</code>
 Giới thiệu bot · Xem lại danh sách lệnh này.

⏱ <b>Định dạng thời gian / Duration format:</b>
<code>&lt;số&gt;&lt;đơn vị&gt;</code> — s (giây/seconds), p hoặc m (phút/minutes),
h (giờ/hours), d (ngày/days). VD: <code>30s</code>, <code>5p</code>, <code>2h</code>, <code>1d</code>.
"""


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_html(HELP_TEXT)


# ---------------------------------------------------------------------------
# Câm mồm / Mở câm mồm (mute / unmute)
# ---------------------------------------------------------------------------

async def cammom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, rest = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Reply tin nhắn hoặc dùng /cammom <id/@username> [thời gian].\n"
            "⚠️ Reply to a message, or use /cammom <id/@username> [duration]."
        )
        return

    until_date = None
    duration_label = "vĩnh viễn / permanent"
    if rest:
        duration = parse_duration(rest[0])
        if duration is None:
            await update.effective_message.reply_text(
                "⚠️ Thời gian không hợp lệ. VD: 5p, 1h, 2d.\n"
                "⚠️ Invalid duration. e.g. 5p, 1h, 2d."
            )
            return
        until_date = datetime.now(timezone.utc) + duration
        duration_label = rest[0]

    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=MUTED_PERMISSIONS,
            until_date=until_date,
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return

    await update.effective_message.reply_html(
        f"🔇 Đã câm mồm {display} ({duration_label}).\n"
        f"🔇 Muted {display} ({duration_label})."
    )


async def mocammom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, _ = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Reply tin nhắn hoặc dùng /mocammom <id/@username>.\n"
            "⚠️ Reply to a message, or use /mocammom <id/@username>."
        )
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=FULL_PERMISSIONS,
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return

    await update.effective_message.reply_html(
        f"🔊 Đã bỏ câm mồm cho {display}.\n🔊 Unmuted {display}."
    )


# ---------------------------------------------------------------------------
# Sút / Gỡ sút / Đá (ban / unban / kick)
# ---------------------------------------------------------------------------

async def sut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, _ = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Reply tin nhắn hoặc dùng /sut <id/@username>.\n"
            "⚠️ Reply to a message, or use /sut <id/@username>."
        )
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return

    await update.effective_message.reply_html(
        f"🚫 Đã sút {display} khỏi nhóm vĩnh viễn.\n🚫 Banned {display} from the group."
    )


async def mosut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, _ = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Dùng /mosut <id/@username> (thành viên đã rời nhóm nên khó reply được).\n"
            "⚠️ Use /mosut <id/@username> (they've left, so replying won't work)."
        )
        return

    try:
        await context.bot.unban_chat_member(update.effective_chat.id, user_id, only_if_banned=True)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return

    await update.effective_message.reply_html(
        f"✅ Đã gỡ sút cho {display}, có thể vào lại nhóm.\n✅ Unbanned {display}, they can rejoin."
    )


async def da_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, _ = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Reply tin nhắn hoặc dùng /da <id/@username>.\n"
            "⚠️ Reply to a message, or use /da <id/@username>."
        )
        return

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await context.bot.unban_chat_member(update.effective_chat.id, user_id, only_if_banned=True)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return

    await update.effective_message.reply_html(
        f"👢 Đã đá {display} khỏi nhóm (có thể vào lại).\n👢 Kicked {display} (can rejoin)."
    )


# ---------------------------------------------------------------------------
# Khóa / Mở khóa nhóm (lock / unlock toàn nhóm)
# ---------------------------------------------------------------------------

async def khoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, MUTED_PERMISSIONS)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return
    await update.effective_message.reply_text(
        "🔒 Đã khóa nhóm, chỉ admin được nhắn.\n🔒 Group locked, only admins can chat."
    )


async def mokhoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    try:
        await context.bot.set_chat_permissions(update.effective_chat.id, FULL_PERMISSIONS)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return
    await update.effective_message.reply_text(
        "🔓 Đã mở khóa nhóm.\n🔓 Group unlocked."
    )


# ---------------------------------------------------------------------------
# Cảnh cáo / Xóa cảnh cáo (warn / reset warn)
# ---------------------------------------------------------------------------

async def canhcao_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, _ = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Reply tin nhắn hoặc dùng /canhcao <id/@username>.\n"
            "⚠️ Reply to a message, or use /canhcao <id/@username>."
        )
        return

    data = load_data()
    chat_key = str(update.effective_chat.id)
    warns = data.setdefault("warns", {}).setdefault(chat_key, {})
    count = warns.get(str(user_id), 0) + 1
    warns[str(user_id)] = count
    save_data(data)

    if count >= 3:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Lỗi khi sút / Error banning: {e}")
            return
        warns[str(user_id)] = 0
        save_data(data)
        await update.effective_message.reply_html(
            f"🚫 {display} đã bị cảnh cáo đủ 3 lần và bị SÚT khỏi nhóm!\n"
            f"🚫 {display} reached 3 warnings and was banned!"
        )
    else:
        await update.effective_message.reply_html(
            f"⚠️ Đã cảnh cáo {display} ({count}/3).\n⚠️ Warned {display} ({count}/3)."
        )


async def xoacanhcao_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, _ = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Reply tin nhắn hoặc dùng /xoacanhcao <id/@username>.\n"
            "⚠️ Reply to a message, or use /xoacanhcao <id/@username>."
        )
        return

    data = load_data()
    chat_key = str(update.effective_chat.id)
    warns = data.setdefault("warns", {}).setdefault(chat_key, {})
    warns[str(user_id)] = 0
    save_data(data)

    await update.effective_message.reply_html(
        f"✅ Đã xóa cảnh cáo của {display}.\n✅ Cleared warnings for {display}."
    )


# ---------------------------------------------------------------------------
# Ghim / Bỏ ghim (pin / unpin)
# ---------------------------------------------------------------------------

async def ghim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text(
            "⚠️ Hãy reply tin nhắn cần ghim.\n⚠️ Reply to the message you want to pin."
        )
        return
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, message.reply_to_message.message_id)
    except Exception as e:
        await message.reply_text(f"❌ Lỗi / Error: {e}")
        return
    await message.reply_text("📌 Đã ghim tin nhắn.\n📌 Message pinned.")


async def boghim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    message = update.effective_message
    try:
        if message.reply_to_message:
            await context.bot.unpin_chat_message(update.effective_chat.id, message.reply_to_message.message_id)
        else:
            await context.bot.unpin_chat_message(update.effective_chat.id)
    except Exception as e:
        await message.reply_text(f"❌ Lỗi / Error: {e}")
        return
    await message.reply_text("📌 Đã bỏ ghim.\n📌 Message unpinned.")


# ---------------------------------------------------------------------------
# Thăng chức / Giáng chức (promote / demote)
# ---------------------------------------------------------------------------

async def thangchuc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, _ = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Reply tin nhắn hoặc dùng /thangchuc <id/@username>.\n"
            "⚠️ Reply to a message, or use /thangchuc <id/@username>."
        )
        return
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id,
            user_id,
            can_manage_chat=True,
            can_change_info=True,
            can_delete_messages=True,
            can_invite_users=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_manage_video_chats=True,
            can_promote_members=False,
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return
    await update.effective_message.reply_html(
        f"⭐ Đã thăng chức {display} làm phó nhóm.\n⭐ Promoted {display} to admin."
    )


async def giangchuc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    user_id, display, _ = await get_target_and_args(update, context)
    if user_id is None:
        await update.effective_message.reply_text(
            "⚠️ Reply tin nhắn hoặc dùng /giangchuc <id/@username>.\n"
            "⚠️ Reply to a message, or use /giangchuc <id/@username>."
        )
        return
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id,
            user_id,
            can_manage_chat=False,
            can_change_info=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_manage_video_chats=False,
            can_promote_members=False,
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi / Error: {e}")
        return
    await update.effective_message.reply_html(
        f"⬇️ Đã giáng chức {display} xuống thành viên thường.\n⬇️ Demoted {display} to member."
    )


# ---------------------------------------------------------------------------
# Thông tin thành viên (user info)
# ---------------------------------------------------------------------------

async def thongtin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, _display, _ = await get_target_and_args(update, context)

    if user_id is None:
        target = update.effective_user
    else:
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
            target = member.user
        except Exception:
            await update.effective_message.reply_text(
                "❌ Không tìm thấy thành viên.\n❌ Member not found."
            )
            return

    username_line = f"@{target.username}" if target.username else "Không có / None"
    text = (
        f"👤 <b>Thông tin thành viên / User info</b>\n"
        f"ID: <code>{target.id}</code>\n"
        f"Tên / Name: {target.full_name}\n"
        f"Username: {username_line}"
    )
    await update.effective_message.reply_html(text)


# ---------------------------------------------------------------------------
# Nội quy nhóm (group rules)
# ---------------------------------------------------------------------------

async def noiquy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    chat_key = str(update.effective_chat.id)

    if context.args:
        if not await ensure_group_admin(update, context):
            return
        rules_text = " ".join(context.args)
        data.setdefault("rules", {})[chat_key] = rules_text
        save_data(data)
        await update.effective_message.reply_text(
            "✅ Đã cập nhật nội quy nhóm.\n✅ Group rules updated."
        )
        return

    rules_text = data.get("rules", {}).get(chat_key)
    if rules_text:
        await update.effective_message.reply_text(f"📜 Nội quy nhóm / Group rules:\n\n{rules_text}")
    else:
        await update.effective_message.reply_text(
            "📜 Nhóm chưa có nội quy. Admin dùng /noiquy <nội dung> để đặt.\n"
            "📜 No rules set yet. Admin: /noiquy <text> to set rules."
        )


# ---------------------------------------------------------------------------
# Xóa tin nhắn (delete message)
# ---------------------------------------------------------------------------

async def xoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    message = update.effective_message
    if not message.reply_to_message:
        await message.reply_text(
            "⚠️ Hãy reply tin nhắn cần xóa.\n⚠️ Reply to the message you want to delete."
        )
        return
    try:
        await context.bot.delete_message(update.effective_chat.id, message.reply_to_message.message_id)
        await message.delete()
    except Exception as e:
        await message.reply_text(f"❌ Lỗi / Error: {e}")


# ---------------------------------------------------------------------------
# Chào mừng thành viên mới
# ---------------------------------------------------------------------------

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.effective_message.new_chat_members:
        if member.id == context.bot.id:
            continue
        await update.effective_chat.send_message(
            f"👋 Chào mừng {member.mention_html()} đến với nhóm!\n"
            f"👋 Welcome {member.mention_html()} to the group!",
            parse_mode=ParseMode.HTML,
        )


# ---------------------------------------------------------------------------
# Xử lý lỗi chung
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Lỗi khi xử lý update %s: %s", update, context.error)


# ---------------------------------------------------------------------------
# Khởi chạy bot
# ---------------------------------------------------------------------------

def main():
    token = BOT_TOKEN
    if not token or token == "PASTE_YOUR_TOKEN_HERE":
        raise SystemExit(
            "❌ Chưa dán BOT_TOKEN! Mở bot.py, tìm dòng BOT_TOKEN ở gần đầu file và dán token vào."
        )

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cammom", cammom_command))
    app.add_handler(CommandHandler("mocammom", mocammom_command))
    app.add_handler(CommandHandler("sut", sut_command))
    app.add_handler(CommandHandler("mosut", mosut_command))
    app.add_handler(CommandHandler("da", da_command))
    app.add_handler(CommandHandler("khoa", khoa_command))
    app.add_handler(CommandHandler("mokhoa", mokhoa_command))
    app.add_handler(CommandHandler("canhcao", canhcao_command))
    app.add_handler(CommandHandler("xoacanhcao", xoacanhcao_command))
    app.add_handler(CommandHandler("ghim", ghim_command))
    app.add_handler(CommandHandler("boghim", boghim_command))
    app.add_handler(CommandHandler("thangchuc", thangchuc_command))
    app.add_handler(CommandHandler("giangchuc", giangchuc_command))
    app.add_handler(CommandHandler("thongtin", thongtin_command))
    app.add_handler(CommandHandler("noiquy", noiquy_command))
    app.add_handler(CommandHandler("xoa", xoa_command))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_error_handler(error_handler)

    logger.info("🤖 %s đang chạy...", BOT_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()


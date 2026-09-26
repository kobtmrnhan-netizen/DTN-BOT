"""
BOT QUẢN LÝ NHÓM TELEGRAM - OSAKA
==================================
Bot quản lý nhóm Telegram với tên lệnh tiếng Việt, phản hồi song ngữ Việt/Anh.

DANH SÁCH LỆNH (xem chi tiết trong /help riêng tư của bot):
  /start, /help (help chỉ hoạt động khi nhắn riêng cho bot)
  /cammom (mute), /mocammom (unmute)
  /sut (ban), /mosut (unban), /da (kick)
  /khoa (lock nhóm), /mokhoa (unlock nhóm)
  /canhcao (warn), /xoacanhcao (reset warn)
  /ghim (pin), /boghim (unpin)
  /thangchuc (promote), /giangchuc (demote)
  /thongtin (user info)
  /noiquy (xem/đặt nội quy)
  /xoa (xóa tin nhắn)
  /antilink, /antispam, /antibuff, /antifake (chống phá nhóm, bật/tắt on|off)
  /diemdanh (điểm danh hằng ngày, giữ streak)

LƯU Ý: KHÔNG có lệnh giả danh người khác (/fake) — tính năng này không được
xây dựng vì có thể bị lợi dụng để lừa đảo/giả mạo người thật trong nhóm.
"anti-fake" ở đây là bảo vệ: cảnh báo khi có người vào nhóm với tên trùng
y hệt admin (nghi giả mạo để lừa đảo), không phải công cụ để giả người khác.

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

from telegram import Chat, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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

# Múi giờ Việt Nam (UTC+7), dùng cho tính năng điểm danh theo ngày
VN_TZ = timezone(timedelta(hours=7))

# --- Cấu hình chống phá nhóm (anti-abuse) — chỉnh số ở đây nếu muốn ---
LINK_RE = re.compile(r"(https?://|t\.me/|telegram\.me/|www\.)\S+", re.IGNORECASE)
FLOOD_WINDOW_SECONDS = 10     # antibuff: cửa sổ thời gian theo dõi
FLOOD_MAX_MESSAGES = 5        # antibuff: quá số này trong cửa sổ trên -> bị câm
FLOOD_MUTE_MINUTES = 5        # antibuff: thời gian câm khi bị bắt nhồi tin
SPAM_REPEAT_THRESHOLD = 3     # antispam: lặp lại đúng nội dung bấy nhiêu lần -> xóa
SPAM_WINDOW_SECONDS = 60      # antispam: cửa sổ thời gian tính lặp lại
CANHCAO_AUTO_SUT = 3          # /canhcao: đủ số lần này thì tự động /sut

# Cài đặt chống phá nhóm mặc định cho mỗi nhóm (có thể bật/tắt bằng lệnh)
DEFAULT_SETTINGS = {
    "antilink": False,
    "antispam": False,
    "antiflood": False,
    "antifake": True,
}

# Bộ nhớ tạm (không lưu file) để theo dõi tần suất tin nhắn mỗi người — phục vụ
# antispam / antibuff. Mất khi bot restart, không sao vì đây chỉ là dữ liệu tức thời.
_recent_messages: dict = {}


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


def get_settings(chat_id) -> dict:
    """Lấy cài đặt antilink/antispam/antiflood/antifake của 1 nhóm (có giá trị mặc định)."""
    data = load_data()
    chat_settings = data.get("settings", {}).get(str(chat_id), {})
    merged = dict(DEFAULT_SETTINGS)
    merged.update(chat_settings)
    return merged


def set_setting(chat_id, key: str, value: bool) -> None:
    data = load_data()
    data.setdefault("settings", {}).setdefault(str(chat_id), {})[key] = value
    save_data(data)


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
        await update.effective_message.reply_text("Lệnh chỉ xài trong nhóm, xin lỗi")
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
Thêm bot vào nhóm và cấp quyền <b>Admin</b> để dùng đầy đủ tính năng.

🎯 <b>Cách chọn mục tiêu (target):</b> reply tin nhắn, hoặc <code>id</code>, hoặc <code>@username</code>.

━━━━━━━━━━━━━━━
🔇 <b>CÂM MỒM</b>
<code>/cammom [thời gian]</code> · <code>/mocammom</code>
VD: <code>/cammom 5p</code> = câm 5 phút. Không nhập = vĩnh viễn.

🚫 <b>ĐUỔI / SÚT</b>
<code>/sut</code> (ban) · <code>/mosut id/@user</code> (unban) · <code>/da</code> (kick, vào lại được)

🔒 <b>KHÓA NHÓM</b>
<code>/khoa</code> · <code>/mokhoa</code>

⚠️ <b>CẢNH CÁO</b>
<code>/canhcao</code> (đủ {CANHCAO_AUTO_SUT} lần tự động sút) · <code>/xoacanhcao</code>

📌 <b>GHIM TIN NHẮN</b>
<code>/ghim</code> · <code>/boghim</code>

👑 <b>CHỨC VỤ</b>
<code>/thangchuc</code> (lên admin) · <code>/giangchuc</code> (xuống thành viên)

━━━━━━━━━━━━━━━
🛡️ <b>CHỐNG PHÁ NHÓM</b> (admin bật/tắt bằng <code>on</code>/<code>off</code>)
<code>/antilink</code> — tự xóa tin nhắn chứa link
<code>/antispam</code> — tự xóa tin nhắn spam lặp đi lặp lại
<code>/antibuff</code> — tự câm mồm khi nhồi tin nhắn liên tục
<code>/antifake</code> — cảnh báo nếu có người vào nhóm giả tên admin (mặc định BẬT)

━━━━━━━━━━━━━━━
📋 <b>KHÁC</b>
<code>/thongtin</code> — xem thông tin thành viên
<code>/noiquy [nội dung]</code> — xem / đặt nội quy nhóm
<code>/xoa</code> — xóa tin nhắn đang reply
<code>/diemdanh</code> — điểm danh hằng ngày, giữ chuỗi (streak), quên 1 ngày là mất chuỗi
<code>/start</code> · <code>/help</code>

⏱ <b>Định dạng thời gian:</b> <code>&lt;số&gt;&lt;đơn vị&gt;</code> — s (giây), p/m (phút), h (giờ), d (ngày).
VD: <code>30s</code>, <code>5p</code>, <code>2h</code>, <code>1d</code>.

<i>Ghi chú: các lệnh quản trị ở trên chỉ dùng được trong nhóm và cần bạn là admin.</i>
"""


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == Chat.PRIVATE:
        await update.effective_message.reply_html(HELP_TEXT)
    else:
        await update.effective_message.reply_text("xin lỗi bạn tôi chưa có help group,xin lỗi")


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

    if count >= CANHCAO_AUTO_SUT:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Lỗi khi sút / Error banning: {e}")
            return
        warns[str(user_id)] = 0
        save_data(data)
        await update.effective_message.reply_html(
            f"🚫 {display} đã bị cảnh cáo đủ {CANHCAO_AUTO_SUT} lần và bị SÚT khỏi nhóm!\n"
            f"🚫 {display} reached {CANHCAO_AUTO_SUT} warnings and was banned!"
        )
    else:
        await update.effective_message.reply_html(
            f"⚠️ Đã cảnh cáo {display} ({count}/{CANHCAO_AUTO_SUT}).\n"
            f"⚠️ Warned {display} ({count}/{CANHCAO_AUTO_SUT})."
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
# Chống phá nhóm: antilink / antispam / antibuff / antifake (bật/tắt)
# ---------------------------------------------------------------------------

async def _toggle_command(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, ten_lenh: str, mo_ta: str):
    if not await ensure_group_admin(update, context):
        return
    args = context.args
    chat_id = update.effective_chat.id

    if not args or args[0].lower() not in ("on", "off"):
        state = get_settings(chat_id).get(key, False)
        await update.effective_message.reply_text(
            f"ℹ️ {mo_ta} hiện đang {'BẬT ✅' if state else 'TẮT ❌'}.\n"
            f"Dùng /{ten_lenh} on hoặc /{ten_lenh} off để bật/tắt."
        )
        return

    new_state = args[0].lower() == "on"
    set_setting(chat_id, key, new_state)
    await update.effective_message.reply_text(
        f"{mo_ta}: đã chuyển sang {'BẬT ✅' if new_state else 'TẮT ❌'}."
    )


async def antilink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_command(update, context, "antilink", "antilink", "🔗 Antilink (tự xóa tin nhắn chứa link)")


async def antispam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_command(update, context, "antispam", "antispam", "🧹 Antispam (tự xóa tin nhắn spam lặp lại)")


async def antibuff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_command(update, context, "antiflood", "antibuff", "🚨 Antibuff (tự câm mồm khi nhồi tin nhắn liên tục)")


async def antifake_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _toggle_command(update, context, "antifake", "antifake", "🕵️ Antifake (cảnh báo nếu có người giả tên admin)")


async def group_message_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chạy trên mọi tin nhắn văn bản (không phải lệnh) trong nhóm để lọc link/spam/flood."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not message or not message.text or not user or user.is_bot:
        return

    settings = get_settings(chat.id)
    if not (settings.get("antilink") or settings.get("antispam") or settings.get("antiflood")):
        return  # không có gì bật, khỏi tốn công kiểm tra

    # Admin thì bỏ qua, không áp dụng anti-abuse
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass

    now = datetime.now(timezone.utc).timestamp()
    key = (chat.id, user.id)
    history = _recent_messages.setdefault(key, [])
    history.append((now, message.text))
    cutoff = now - max(FLOOD_WINDOW_SECONDS, SPAM_WINDOW_SECONDS)
    while history and history[0][0] < cutoff:
        history.pop(0)

    # --- antilink ---
    if settings.get("antilink") and LINK_RE.search(message.text):
        try:
            await message.delete()
            await chat.send_message(
                f"🔗 Đã xóa tin nhắn chứa link của {user.mention_html()} (antilink).\n"
                f"🔗 Removed a link message from {user.mention_html()} (antilink).",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # --- antispam (nội dung lặp lại) ---
    if settings.get("antispam"):
        repeats = [t for t, txt in history if now - t <= SPAM_WINDOW_SECONDS and txt == message.text]
        if len(repeats) >= SPAM_REPEAT_THRESHOLD:
            try:
                await message.delete()
                await chat.send_message(
                    f"🧹 Đã xóa tin nhắn lặp lại của {user.mention_html()} (antispam).\n"
                    f"🧹 Removed a repeated message from {user.mention_html()} (antispam).",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

    # --- antibuff / antiflood (nhồi tin nhắn liên tục) ---
    if settings.get("antiflood"):
        flood_count = sum(1 for t, _ in history if now - t <= FLOOD_WINDOW_SECONDS)
        if flood_count >= FLOOD_MAX_MESSAGES:
            try:
                until_date = datetime.now(timezone.utc) + timedelta(minutes=FLOOD_MUTE_MINUTES)
                await context.bot.restrict_chat_member(
                    chat.id, user.id, permissions=MUTED_PERMISSIONS, until_date=until_date
                )
                await chat.send_message(
                    f"🚨 {user.mention_html()} gửi tin quá nhanh, đã bị câm mồm {FLOOD_MUTE_MINUTES} phút (antibuff).\n"
                    f"🚨 {user.mention_html()} was flooding messages, muted for {FLOOD_MUTE_MINUTES} min (antibuff).",
                    parse_mode=ParseMode.HTML,
                )
                history.clear()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Điểm danh hằng ngày (daily check-in streak)
# ---------------------------------------------------------------------------

def _today_str() -> str:
    return datetime.now(VN_TZ).strftime("%Y-%m-%d")


async def diemdanh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Điểm danh", callback_data=f"diemdanh:{user.id}")]]
    )
    await update.effective_message.reply_html(
        f"📋 Chào {user.mention_html()}, vui lòng nhấn nút điểm danh để hệ thống xác nhận.\n"
        f"📋 Hi {user.mention_html()}, please tap the check-in button below to confirm.",
        reply_markup=keyboard,
    )


async def diemdanh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, owner_id_str = query.data.split(":", 1)
        owner_id = int(owner_id_str)
    except (ValueError, AttributeError):
        await query.answer()
        return

    if query.from_user.id != owner_id:
        await query.answer(
            "⚠️ Đây là nút điểm danh của người khác, không phải của bạn.\n"
            "⚠️ This check-in button belongs to someone else.",
            show_alert=True,
        )
        return

    data = load_data()
    chat_key = str(update.effective_chat.id)
    checkins = data.setdefault("checkins", {}).setdefault(chat_key, {})
    record = checkins.get(str(owner_id), {"streak": 0, "last_date": None})

    today = _today_str()
    if record["last_date"] == today:
        await query.answer(
            f"✅ Bạn đã điểm danh hôm nay rồi! Chuỗi hiện tại: {record['streak']} ngày.",
            show_alert=True,
        )
        return

    yesterday = (datetime.now(VN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    if record["last_date"] == yesterday:
        record["streak"] += 1
    else:
        record["streak"] = 1  # bỏ lỡ ngày trước đó -> tính lại từ đầu
    record["last_date"] = today
    checkins[str(owner_id)] = record
    save_data(data)

    await query.answer(
        f"🎉 Điểm danh thành công! Chuỗi hiện tại: {record['streak']} ngày.", show_alert=True
    )
    try:
        await query.edit_message_text(
            f"📋 {query.from_user.mention_html()} đã điểm danh hôm nay ✅\n"
            f"🔥 Chuỗi điểm danh / Streak: <b>{record['streak']}</b> ngày (days)",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Chào mừng thành viên mới + phát hiện giả danh admin (antifake)
# ---------------------------------------------------------------------------

async def _check_new_member_impersonation(update: Update, context: ContextTypes.DEFAULT_TYPE, member):
    """Nếu thành viên mới có tên trùng y hệt một admin -> nghi giả mạo, cảnh báo + tạm câm."""
    chat = update.effective_chat
    if not get_settings(chat.id).get("antifake", True):
        return
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
    except Exception:
        return

    new_name = (member.full_name or "").strip().lower()
    if not new_name:
        return

    for admin in admins:
        if admin.user.id == member.id:
            continue
        admin_name = (admin.user.full_name or "").strip().lower()
        if admin_name and admin_name == new_name:
            try:
                await context.bot.restrict_chat_member(chat.id, member.id, permissions=MUTED_PERMISSIONS)
            except Exception:
                pass
            await chat.send_message(
                f"🕵️ CẢNH BÁO: {member.mention_html()} có tên trùng với admin "
                f"{admin.user.mention_html()} — nghi giả mạo, đã tạm câm mồm để admin kiểm tra (antifake).\n"
                f"🕵️ WARNING: {member.mention_html()} has the same name as admin "
                f"{admin.user.mention_html()} — possible impersonation, muted pending review (antifake).",
                parse_mode=ParseMode.HTML,
            )
            return


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.effective_message.new_chat_members:
        if member.id == context.bot.id:
            continue
        await update.effective_chat.send_message(
            f"👋 Chào mừng {member.mention_html()} đến với nhóm!\n"
            f"👋 Welcome {member.mention_html()} to the group!",
            parse_mode=ParseMode.HTML,
        )
        await _check_new_member_impersonation(update, context, member)


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
    app.add_handler(CommandHandler("antilink", antilink_command))
    app.add_handler(CommandHandler("antispam", antispam_command))
    app.add_handler(CommandHandler("antibuff", antibuff_command))
    app.add_handler(CommandHandler("antifake", antifake_command))
    app.add_handler(CommandHandler("diemdanh", diemdanh_command))
    app.add_handler(CallbackQueryHandler(diemdanh_callback, pattern=r"^diemdanh:"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, group_message_guard))
    app.add_error_handler(error_handler)

    logger.info("🤖 %s đang chạy...", BOT_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

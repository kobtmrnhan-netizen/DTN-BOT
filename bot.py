"""
BOT QUẢN LÝ NHÓM & NHÀ CÁI TELEGRAM - OSAKA v2
================================================
Bot quản lý nhóm Telegram + hệ thống nhà cái Osaka
Tính năng: Quản lý nhóm, Tiện ích, Casino, XU system

DANH SÁCH LỆNH CHÍNH:
  /help (help chỉ hoạt động khi nhắn riêng cho bot)
  /cammom, /mocammom, /sut, /mosut, /da, /khoa, /mokhoa
  /canhcao, /xoacanhcao, /ghim, /boghim, /thangchuc, /giangchuc
  /thongtin, /noiquy, /xoa, /antilink, /antispam, /antibuff, /antifake
  /diemdanh, /filter, /filters, /stop
  
CASINO (Nhà Cái Osaka):
  /menuXu - Vào nhà cái Osaka
  /xume - Kiểm tra số XU hiện có
  /xumat - Kiểm tra số XU đã thua
  /taixiu <số_xu> <tài/xỉu> - Chơi tài xỉu
  /vaytien <số_tiền> - Vay tiền chơi
  /nhapma <code> - Nhập mã admin
  /nhapcode <code> - Nhập code newbie
"""

import json
import logging
import re
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

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
# BOT CONFIG
BOT_TOKEN = "8801642678:AAHmBSWsG2s7mj1mbtm9b1Yld0CwwVhH7jo"
# ============================================================

BOT_NAME = "Osaka"
DATA_FILE = Path(__file__).parent / "data.json"

# Permissions
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

LINK_RE = re.compile(r"(https?://|t\.me/|telegram\.me/|www\.)\S+", re.IGNORECASE)

# Flood/Spam config
FLOOD_WINDOW_SECONDS = 10
FLOOD_MAX_MESSAGES = 5
FLOOD_MUTE_MINUTES = 5
SPAM_REPEAT_THRESHOLD = 3
SPAM_WINDOW_SECONDS = 60
CANHCAO_AUTO_SUT = 3

DEFAULT_SETTINGS = {
    "antilink": False,
    "antispam": False,
    "antiflood": False,
    "antifake": True,
}

# Múi giờ Việt Nam
VN_TZ = timezone(timedelta(hours=7))

# Casino settings
TAIXIU_TAI_PERCENTAGE = 40  # Tài có 40% thắng, 60% thua
TAIXIU_XIU_PERCENTAGE = 40  # Xỉu có 40% thắng, 60% thua
LOAN_MAX = 500000
LOAN_TIME_HOURS = 5

# Memory
_recent_messages: dict = {}

# ============================================================
# DATA MANAGEMENT
# ============================================================

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
    data = load_data()
    chat_settings = data.get("settings", {}).get(str(chat_id), {})
    merged = dict(DEFAULT_SETTINGS)
    merged.update(chat_settings)
    return merged


def set_setting(chat_id, key: str, value: bool) -> None:
    data = load_data()
    data.setdefault("settings", {}).setdefault(str(chat_id), {})[key] = value
    save_data(data)


# ============================================================
# XU SYSTEM (Currency)
# ============================================================

def get_user_xu(user_id: int) -> int:
    """Lấy số XU của người dùng (mặc định 10000 XU)"""
    data = load_data()
    users = data.setdefault("users", {})
    
    # Khởi tạo user nếu chưa tồn tại
    if str(user_id) not in users:
        users[str(user_id)] = {
            "xu": 10000,
            "xu_lost": 0,
            "loans": [],
            "is_admin": False,
            "codes_used": []
        }
        save_data(data)
    
    user_record = users[str(user_id)]
    return user_record.get("xu", 10000)


def set_user_xu(user_id: int, amount: int) -> None:
    """Cập nhật số XU của người dùng"""
    data = load_data()
    users = data.setdefault("users", {})
    if str(user_id) not in users:
        users[str(user_id)] = {
            "xu": 10000,
            "xu_lost": 0,
            "loans": [],
            "is_admin": False,
            "codes_used": []
        }
    users[str(user_id)]["xu"] = max(0, amount)
    save_data(data)


def add_user_xu(user_id: int, amount: int) -> None:
    """Thêm XU cho người dùng"""
    current = get_user_xu(user_id)  # Đảm bảo user tồn tại
    set_user_xu(user_id, current + amount)


def get_user_xu_lost(user_id: int) -> int:
    """Lấy số XU đã thua"""
    data = load_data()
    users = data.setdefault("users", {})
    if str(user_id) not in users:
        users[str(user_id)] = {
            "xu": 10000,
            "xu_lost": 0,
            "loans": [],
            "is_admin": False,
            "codes_used": []
        }
        save_data(data)
    user_record = users[str(user_id)]
    return user_record.get("xu_lost", 0)


def add_xu_lost(user_id: int, amount: int) -> None:
    """Cập nhật số XU đã thua"""
    data = load_data()
    users = data.setdefault("users", {})
    if str(user_id) not in users:
        users[str(user_id)] = {
            "xu": 10000,
            "xu_lost": 0,
            "loans": [],
            "is_admin": False,
            "codes_used": []
        }
    users[str(user_id)]["xu_lost"] = users[str(user_id)].get("xu_lost", 0) + amount
    save_data(data)


def get_user_loans(user_id: int) -> list:
    """Lấy danh sách vay nợ của người dùng"""
    data = load_data()
    users = data.setdefault("users", {})
    user_record = users.get(str(user_id), {"xu": 10000, "xu_lost": 0, "loans": [], "is_admin": False, "codes_used": []})
    return user_record.get("loans", [])


def is_user_admin(user_id: int) -> bool:
    """Kiểm tra xem người dùng là admin trong hệ thống"""
    data = load_data()
    users = data.setdefault("users", {})
    user_record = users.get(str(user_id), {"xu": 10000, "xu_lost": 0, "loans": [], "is_admin": False, "codes_used": []})
    return user_record.get("is_admin", False)


def set_user_admin(user_id: int, is_admin: bool) -> None:
    """Đặt người dùng làm admin hệ thống"""
    data = load_data()
    users = data.setdefault("users", {})
    if str(user_id) not in users:
        users[str(user_id)] = {"xu": 10000, "xu_lost": 0, "loans": [], "is_admin": False, "codes_used": []}
    users[str(user_id)]["is_admin"] = is_admin
    save_data(data)


def get_codes_used(user_id: int) -> list:
    """Lấy danh sách code đã dùng của người dùng"""
    data = load_data()
    users = data.setdefault("users", {})
    user_record = users.get(str(user_id), {"xu": 10000, "xu_lost": 0, "loans": [], "is_admin": False, "codes_used": []})
    return user_record.get("codes_used", [])


def add_code_used(user_id: int, code_type: str) -> None:
    """Thêm code vào danh sách đã dùng"""
    data = load_data()
    users = data.setdefault("users", {})
    if str(user_id) not in users:
        users[str(user_id)] = {"xu": 10000, "xu_lost": 0, "loans": [], "is_admin": False, "codes_used": []}
    users[str(user_id)].setdefault("codes_used", []).append(code_type)
    save_data(data)


def add_loan(user_id: int, amount: int) -> None:
    """Thêm khoản vay mới"""
    data = load_data()
    users = data.setdefault("users", {})
    if str(user_id) not in users:
        users[str(user_id)] = {
            "xu": 10000,
            "xu_lost": 0,
            "loans": [],
            "is_admin": False,
            "codes_used": []
        }
    
    users[str(user_id)].setdefault("loans", []).append({
        "amount": amount,
        "created_at": datetime.now(VN_TZ).isoformat(),
    })
    users[str(user_id)]["xu"] += amount
    save_data(data)


def clear_loans(user_id: int) -> None:
    """Xóa toàn bộ khoản vay"""
    data = load_data()
    users = data.setdefault("users", {})
    if str(user_id) in users:
        users[str(user_id)]["loans"] = []
    save_data(data)


def is_loan_overdue(user_id: int) -> bool:
    """Kiểm tra xem có khoản vay quá hạn không"""
    loans = get_user_loans(user_id)
    if not loans:
        return False
    
    for loan in loans:
        created = datetime.fromisoformat(loan["created_at"])
        elapsed = datetime.now(VN_TZ) - created
        if elapsed > timedelta(hours=LOAN_TIME_HOURS):
            return True
    return False


# ============================================================
# FILTER SYSTEM
# ============================================================

def get_filters(chat_id: int) -> dict:
    """Lấy danh sách filter của nhóm"""
    data = load_data()
    filters_data = data.get("filters", {}).get(str(chat_id), {})
    return filters_data


def add_filter(chat_id: int, trigger: str, response: str) -> None:
    """Thêm filter mới"""
    data = load_data()
    data.setdefault("filters", {}).setdefault(str(chat_id), {})[trigger.lower()] = response
    save_data(data)


def remove_filter(chat_id: int, trigger: str) -> None:
    """Xóa filter"""
    data = load_data()
    if str(chat_id) in data.get("filters", {}):
        data["filters"][str(chat_id)].pop(trigger.lower(), None)
    save_data(data)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def parse_duration(text: str):
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
    """Kiểm tra xem người gọi lệnh có là admin trong nhóm"""
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
    Xác định người dùng mục tiêu theo thứ tự:
    reply > @username > user_id
    """
    message = update.effective_message
    args = list(context.args or [])

    # Priority 1: reply
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        return target_user.id, target_user.mention_html(), args

    # Priority 2: @username hoặc user_id từ args
    if args:
        first_arg = args[0]
        if first_arg.startswith("@"):
            username = first_arg[1:]
            try:
                member = await context.bot.get_chat_member(update.effective_chat.id, f"@{username}")
                return member.user.id, member.user.mention_html(), args[1:]
            except Exception:
                await message.reply_text(f"❌ Không tìm thấy @{username}")
                return None, None, args
        else:
            try:
                user_id = int(first_arg)
                member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
                return member.user.id, member.user.mention_html(), args[1:]
            except ValueError:
                await message.reply_text(f"❌ User ID không hợp lệ: {first_arg}")
                return None, None, args
            except Exception:
                await message.reply_text(f"❌ Không tìm thấy user với ID: {first_arg}")
                return None, None, args

    await message.reply_text("❌ Vui lòng reply tin nhắn hoặc cung cấp @username/user_id")
    return None, None, args


def _today_str() -> str:
    return datetime.now(VN_TZ).strftime("%Y-%m-%d")


# ============================================================
# HELP MENU & NAVIGATION
# ============================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị menu help chính với 3 nút lớn - nằm ngang"""
    user = update.effective_user
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛡️ Quản Trị", callback_data="help_admin"),
            InlineKeyboardButton("🛠️ Tiện Ích", callback_data="help_utility"),
            InlineKeyboardButton("🎰 Nhà Cái", callback_data="help_casino"),
        ]
    ])
    
    text = (
        f"👋 Chào {user.mention_html()}, tôi là {BOT_NAME}.\n\n"
        f"🌟 Tôi có nhiều công cụ hữu ích. Chạm vào một module bên dưới để xem lệnh 💝\n\n"
        f"🌍 Tôi hỗ trợ Tiếng Việt 🇻🇳 và English 🇺🇸"
    )
    
    # Nếu từ callback thì edit, nếu từ command thì reply
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await update.effective_message.reply_html(text, reply_markup=keyboard)


async def help_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu quản trị"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Xóa tin", callback_data="admin_xoa"),
            InlineKeyboardButton("🔇 Câm/Uncam", callback_data="admin_cammom"),
            InlineKeyboardButton("🚫 Cấm/Hỏi cấm", callback_data="admin_sut"),
        ],
        [
            InlineKeyboardButton("🦶 Kick", callback_data="admin_da"),
            InlineKeyboardButton("🔒 Khóa/Mở", callback_data="admin_khoa"),
            InlineKeyboardButton("⚠️ Cảnh cáo", callback_data="admin_canhcao"),
        ],
        [
            InlineKeyboardButton("📌 Ghim/Bỏ ghim", callback_data="admin_ghim"),
            InlineKeyboardButton("👑 Thăng/Giáng", callback_data="admin_chuc"),
        ],
        [
            InlineKeyboardButton("🔙 Quay lại", callback_data="help"),
        ]
    ])
    
    text = (
        "🛡️ <b>LỆNH QUẢN TRỊ NHÓM</b>\n\n"
        "✅ <b>/xoa</b> - Xóa tin nhắn\n"
        "✅ <b>/cammom</b> &lt;@user|id&gt; [thời gian] - Câm người dùng\n"
        "✅ <b>/mocammom</b> &lt;@user|id&gt; - Uncam\n"
        "✅ <b>/sut</b> &lt;@user|id&gt; [thời gian] - Cấm người dùng\n"
        "✅ <b>/mosut</b> &lt;@user|id&gt; - Hỏi cấm\n"
        "✅ <b>/da</b> &lt;@user|id&gt; - Kick người dùng\n"
        "✅ <b>/khoa</b> - Khóa nhóm (chỉ admin nói được)\n"
        "✅ <b>/mokhoa</b> - Mở nhóm\n"
        "✅ <b>/canhcao</b> &lt;@user|id&gt; [lý do] - Cảnh cáo\n"
        "✅ <b>/xoacanhcao</b> &lt;@user|id&gt; - Reset cảnh cáo\n"
        "✅ <b>/ghim</b> &lt;message_id&gt; - Ghim tin nhắn\n"
        "✅ <b>/boghim</b> &lt;message_id&gt; - Bỏ ghim\n"
        "✅ <b>/thangchuc</b> &lt;@user|id&gt; - Thăng chức admin\n"
        "✅ <b>/giangchuc</b> &lt;@user|id&gt; - Giáng chức\n"
        "✅ <b>/thongtin</b> &lt;@user|id&gt; - Xem info người dùng\n"
        "✅ <b>/noiquy</b> - Xem/đặt nội quy nhóm\n"
        "✅ <b>/antilink</b> [on|off] - Chặn link\n"
        "✅ <b>/antispam</b> [on|off] - Chặn spam\n"
        "✅ <b>/antibuff</b> [on|off] - Chặn nhồi tin\n"
        "✅ <b>/antifake</b> [on|off] - Chặn giả danh\n\n"
        "💡 <i>Sử dụng:</i> Reply tin nhắn hoặc <code>/lệnh @username</code> hoặc <code>/lệnh [user_id]</code>"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def help_utility_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu tiện ích"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Điểm danh", callback_data="util_diemdanh"),
            InlineKeyboardButton("🔍 Filter", callback_data="util_filter"),
            InlineKeyboardButton("ℹ️ Thông tin", callback_data="util_info"),
        ],
        [
            InlineKeyboardButton("🔙 Quay lại", callback_data="help"),
        ]
    ])
    
    text = (
        "🛠️ <b>LỆNH TIỆN ÍCH</b>\n\n"
        "✅ <b>/diemdanh</b> - Điểm danh hằng ngày, giữ streak\n"
        "✅ <b>/filter</b> &lt;từ_khóa&gt; &lt;phản_hồi&gt; - Thêm filter tự động\n"
        "✅ <b>/filters</b> - Xem tất cả filter\n"
        "✅ <b>/stop</b> &lt;từ_khóa&gt; - Xóa filter\n"
        "✅ <b>/thongtin</b> &lt;@user|id&gt; - Xem thông tin người dùng\n\n"
        "💡 <b>Ví dụ:</b>\n"
        "<code>/filter xin hello</code> - Khi ai nhắn 'xin', bot trả lời 'hello'\n"
        "<code>/filters</code> - Xem tất cả\n"
        "<code>/stop xin</code> - Xóa filter 'xin'"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def help_casino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu nhà cái"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Số XU", callback_data="casino_xu"),
            InlineKeyboardButton("🎲 Tài Xỉu", callback_data="casino_taixiu"),
            InlineKeyboardButton("💳 Vay tiền", callback_data="casino_vaytien"),
        ],
        [
            InlineKeyboardButton("🔙 Quay lại", callback_data="help"),
        ]
    ])
    
    text = (
        "🎰 <b>NHÀ CÁI OSAKA</b>\n\n"
        "🎮 Chơi tài xỉu, kiếm &amp; mất XU!\n\n"
        "✅ <b>/xume</b> - Kiểm tra số XU hiện có\n"
        "✅ <b>/xumat</b> - Xem số XU đã thua\n"
        "✅ <b>/taixiu</b> &lt;số_xu&gt; &lt;tài|xỉu&gt; - Chơi tài xỉu\n"
        "✅ <b>/vaytien</b> &lt;số_tiền&gt; - Vay tiền chơi (tối đa 500,000 XU)\n"
        "✅ <b>/nhapma</b> &lt;code&gt; - Nhập mã admin\n"
        "✅ <b>/nhapcode</b> &lt;code&gt; - Nhập code newbie\n\n"
        "⚠️ <b>Quy tắc:</b>\n"
        "• Tài/Xỉu thắng: x2 tiền cược\n"
        "• Tài thắng 40%, Xỉu thắng 40% (50% hòa)\n"
        "• Vay tiền tối đa: 500,000 XU\n"
        "• Thời hạn trả nợ: 5 giờ\n"
        "• Quá hạn không trả = Khóa chơi"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def back_to_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quay lại menu chính - Edit message cũ"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛡️ Quản Trị", callback_data="help_admin"),
            InlineKeyboardButton("🛠️ Tiện Ích", callback_data="help_utility"),
            InlineKeyboardButton("🎰 Nhà Cái", callback_data="help_casino"),
        ]
    ])
    
    text = (
        f"👋 Chào {user.mention_html()}, tôi là {BOT_NAME}.\n\n"
        f"🌟 Tôi có nhiều công cụ hữu ích. Chạm vào một module bên dưới để xem lệnh 💝\n\n"
        f"🌍 Tôi hỗ trợ Tiếng Việt 🇻🇳 và English 🇺🇸"
    )
    
    # Nếu từ callback thì edit, nếu từ command thì reply
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await update.effective_message.reply_html(text, reply_markup=keyboard)


async def help_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu quản trị"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Xóa tin", callback_data="admin_xoa"),
            InlineKeyboardButton("🔇 Câm/Uncam", callback_data="admin_cammom"),
            InlineKeyboardButton("🚫 Cấm/Hỏi cấm", callback_data="admin_sut"),
        ],
        [
            InlineKeyboardButton("🦶 Kick", callback_data="admin_da"),
            InlineKeyboardButton("🔒 Khóa/Mở", callback_data="admin_khoa"),
            InlineKeyboardButton("⚠️ Cảnh cáo", callback_data="admin_canhcao"),
        ],
        [
            InlineKeyboardButton("📌 Ghim/Bỏ ghim", callback_data="admin_ghim"),
            InlineKeyboardButton("👑 Thăng/Giáng", callback_data="admin_chuc"),
        ],
        [
            InlineKeyboardButton("🔙 Quay lại", callback_data="help"),
        ]
    ])
    
    text = (
        "🛡️ <b>LỆNH QUẢN TRỊ NHÓM</b>\n\n"
        "✅ <b>/xoa</b> - Xóa tin nhắn\n"
        "✅ <b>/cammom</b> &lt;@user|id&gt; [thời gian] - Câm người dùng\n"
        "✅ <b>/mocammom</b> &lt;@user|id&gt; - Uncam\n"
        "✅ <b>/sut</b> &lt;@user|id&gt; [thời gian] - Cấm người dùng\n"
        "✅ <b>/mosut</b> &lt;@user|id&gt; - Hỏi cấm\n"
        "✅ <b>/da</b> &lt;@user|id&gt; - Kick người dùng\n"
        "✅ <b>/khoa</b> - Khóa nhóm (chỉ admin nói được)\n"
        "✅ <b>/mokhoa</b> - Mở nhóm\n"
        "✅ <b>/canhcao</b> &lt;@user|id&gt; [lý do] - Cảnh cáo\n"
        "✅ <b>/xoacanhcao</b> &lt;@user|id&gt; - Reset cảnh cáo\n"
        "✅ <b>/ghim</b> &lt;message_id&gt; - Ghim tin nhắn\n"
        "✅ <b>/boghim</b> &lt;message_id&gt; - Bỏ ghim\n"
        "✅ <b>/thangchuc</b> &lt;@user|id&gt; - Thăng chức admin\n"
        "✅ <b>/giangchuc</b> &lt;@user|id&gt; - Giáng chức\n"
        "✅ <b>/thongtin</b> &lt;@user|id&gt; - Xem info người dùng\n"
        "✅ <b>/noiquy</b> - Xem/đặt nội quy nhóm\n"
        "✅ <b>/antilink</b> [on|off] - Chặn link\n"
        "✅ <b>/antispam</b> [on|off] - Chặn spam\n"
        "✅ <b>/antibuff</b> [on|off] - Chặn nhồi tin\n"
        "✅ <b>/antifake</b> [on|off] - Chặn giả danh\n\n"
        "💡 <i>Sử dụng:</i> Reply tin nhắn hoặc <code>/lệnh @username</code> hoặc <code>/lệnh [user_id]</code>"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def help_utility_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu tiện ích"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Điểm danh", callback_data="util_diemdanh"),
            InlineKeyboardButton("🔍 Filter", callback_data="util_filter"),
            InlineKeyboardButton("ℹ️ Thông tin", callback_data="util_info"),
        ],
        [
            InlineKeyboardButton("🔙 Quay lại", callback_data="help"),
        ]
    ])
    
    text = (
        "🛠️ <b>LỆNH TIỆN ÍCH</b>\n\n"
        "✅ <b>/diemdanh</b> - Điểm danh hằng ngày, giữ streak\n"
        "✅ <b>/filter</b> &lt;từ_khóa&gt; &lt;phản_hồi&gt; - Thêm filter tự động\n"
        "✅ <b>/filters</b> - Xem tất cả filter\n"
        "✅ <b>/stop</b> &lt;từ_khóa&gt; - Xóa filter\n"
        "✅ <b>/thongtin</b> &lt;@user|id&gt; - Xem thông tin người dùng\n\n"
        "💡 <b>Ví dụ:</b>\n"
        "<code>/filter xin hello</code> - Khi ai nhắn 'xin', bot trả lời 'hello'\n"
        "<code>/filters</code> - Xem tất cả\n"
        "<code>/stop xin</code> - Xóa filter 'xin'"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def help_casino_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu nhà cái"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Số XU", callback_data="casino_xu"),
            InlineKeyboardButton("🎲 Tài Xỉu", callback_data="casino_taixiu"),
            InlineKeyboardButton("💳 Vay tiền", callback_data="casino_vaytien"),
        ],
        [
            InlineKeyboardButton("🔙 Quay lại", callback_data="help"),
        ]
    ])
    
    text = (
        "🎰 <b>NHÀ CÁI OSAKA</b>\n\n"
        "🎮 Chơi tài xỉu, kiếm &amp; mất XU!\n\n"
        "✅ <b>/xume</b> - Kiểm tra số XU hiện có\n"
        "✅ <b>/xumat</b> - Xem số XU đã thua\n"
        "✅ <b>/taixiu</b> &lt;số_xu&gt; &lt;tài|xỉu&gt; - Chơi tài xỉu\n"
        "✅ <b>/vaytien</b> &lt;số_tiền&gt; - Vay tiền chơi (tối đa 500,000 XU)\n"
        "✅ <b>/nhapma</b> &lt;code&gt; - Nhập mã admin\n"
        "✅ <b>/nhapcode</b> &lt;code&gt; - Nhập code newbie\n\n"
        "⚠️ <b>Quy tắc:</b>\n"
        "• Tài/Xỉu thắng: x2 tiền cược\n"
        "• Tài thắng 40%, Xỉu thắng 40% (50% hòa)\n"
        "• Vay tiền tối đa: 500,000 XU\n"
        "• Thời hạn trả nợ: 5 giờ\n"
        "• Quá hạn không trả = Khóa chơi"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def back_to_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quay lại menu chính - Edit message cũ"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛡️ Quản Trị", callback_data="help_admin"),
            InlineKeyboardButton("🛠️ Tiện Ích", callback_data="help_utility"),
            InlineKeyboardButton("🎰 Nhà Cái", callback_data="help_casino"),
        ]
    ])
    
    text = (
        f"👋 Chào {user.mention_html()}, tôi là {BOT_NAME}.\n\n"
        f"🌟 Tôi có nhiều công cụ hữu ích. Chạm vào một module bên dưới để xem lệnh 💝\n\n"
        f"🌍 Tôi hỗ trợ Tiếng Việt 🇻🇳 và English 🇺🇸"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


# ============================================================
# CASINO COMMANDS
# ============================================================

async def menuXu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /menuXu - Vào nhà cái"""
    user = update.effective_user
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Phần mềm admin", callback_data="casino_admin_menu"),
            InlineKeyboardButton("🆕 Code tân thủ", callback_data="casino_newbie_menu"),
        ]
    ])
    
    text = (
        f"🎰 Chào mừng {user.mention_html()} đã đến với nhà cái Osaka!\n\n"
        f"🎮 Nhà cái này giúp bạn giải trí và test vận may.\n\n"
        f"📊 Lệnh cần biết:\n"
        f"  • /xume - Kiểm tra số XU của bạn\n"
        f"  • /xumat - Kiểm tra số XU đã thua\n"
        f"  • /taixiu <xu> <tài/xỉu> - Chơi tài xỉu\n"
        f"  • /vaytien <tiền> - Vay tiền chơi\n\n"
        f"💳 *Vay tiền:* Tối đa 500,000 XU | Thời hạn: 5 giờ\n"
        f"   Nếu quá hạn không trả → Khóa trò chơi\n\n"
        f"📞 Muốn chơi lại sau khi bị khóa? Liên hệ admin: @DTN_207\n\n"
        f"🙏 Cảm ơn bạn!"
    )
    
    await update.effective_message.reply_html(text, reply_markup=keyboard)


async def casino_admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu nhập mã admin"""
    query = update.callback_query
    await query.answer()
    
    text = (
        "🔐 **PHẦN MỀM ADMIN**\n\n"
        "👤 Nhập mã đề vào trạng thái admin\n\n"
        "Cách nhập: `/nhapma [code]`\n\n"
        "⚠️ Mã admin không được chia sẻ công khai!"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)


async def casino_newbie_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu nhập code newbie"""
    query = update.callback_query
    await query.answer()
    
    text = (
        "🆕 **CODE TÂN THỦ**\n\n"
        "Chào bạn đến chỗ nhập code!\n\n"
        "Cách nhập: `/nhapcode [code]`\n\n"
        "💝 Code tân thủ có thể được chia sẻ cho mọi người!"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)


async def xume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kiểm tra số XU hiện có"""
    user = update.effective_user
    xu = get_user_xu(user.id)
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Phần mềm admin", callback_data="casino_admin_menu"),
            InlineKeyboardButton("🆕 Code tân thủ", callback_data="casino_newbie_menu"),
        ]
    ])
    
    text = (
        f"💰 **XU HIỆN CÓ**\n\n"
        f"👤 Người dùng: {user.mention_html()}\n"
        f"💎 XU: <b>{xu:,}</b>\n\n"
        f"🎮 Sẵn sàng chơi? Gõ `/taixiu [xu] [tài/xỉu]`"
    )
    
    await update.effective_message.reply_html(text, reply_markup=keyboard)


async def xumat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kiểm tra số XU đã thua"""
    user = update.effective_user
    xu_lost = get_user_xu_lost(user.id)
    
    text = (
        f"📉 **XU ĐÃ THUA**\n\n"
        f"👤 Người dùng: {user.mention_html()}\n"
        f"🔴 Tổng XU thua: <b>{xu_lost:,}</b>\n\n"
        f"💪 Cố lên! Hãy thắng lại!"
    )
    
    await update.effective_message.reply_html(text)


async def taixiu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chơi tài xỉu"""
    user = update.effective_user
    
    if len(context.args) < 2:
        await update.effective_message.reply_text(
            "❌ Cách dùng: `/taixiu <số_xu> <tài|xỉu>`\n"
            "Ví dụ: `/taixiu 100 tài` hoặc `/taixiu 100 xỉu`"
        )
        return
    
    # Parse arguments
    try:
        bet_amount = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Số XU không hợp lệ!")
        return
    
    choice = context.args[1].lower()
    if choice not in ("tài", "xỉu"):
        await update.effective_message.reply_text("❌ Lựa chọn không hợp lệ! Dùng 'tài' hoặc 'xỉu'")
        return
    
    # Check balance & loans
    if is_loan_overdue(user.id):
        await update.effective_message.reply_text(
            "🔒 **KHÓA TRỪNG PHẠT**\n\n"
            "⏰ Bạn có khoản vay quá hạn 5 giờ mà chưa trả!\n"
            "Không thể chơi tiếp. Liên hệ admin: @DTN_207"
        )
        return
    
    current_xu = get_user_xu(user.id)
    if current_xu < bet_amount:
        await update.effective_message.reply_html(
            f"❌ <b>Xin lỗi!</b> Bạn không đủ XU để cược.\n\n"
            f"💰 XU hiện có: <b>{current_xu:,}</b>\n"
            f"💎 XU cần: <b>{bet_amount:,}</b>\n\n"
            f"Gõ `/vaytien [số_tiền]` để vay tiền chơi tiếp!"
        )
        return
    
    if bet_amount <= 0:
        await update.effective_message.reply_text("❌ Số XU cược phải > 0")
        return
    
    # Roll dice (1-100)
    result = random.randint(1, 100)
    is_tai = result <= 50  # 50% tài, 50% xỉu
    
    win = False
    if choice == "tài" and is_tai:
        win = True
        win_amount = bet_amount * 2
    elif choice == "xỉu" and not is_tai:
        win = True
        win_amount = bet_amount * 2
    
    if win:
        add_user_xu(user.id, win_amount)
        emoji = "🎉" if choice == "tài" else "🎊"
        result_text = "TÀI" if is_tai else "XỈU"
        text = (
            f"{emoji} **THẮNG RỒI!**\n\n"
            f"🎲 Kết quả: <b>{result_text}</b>\n"
            f"💎 Cược: <b>{bet_amount:,}</b> XU\n"
            f"🏆 Thắng: <b>{win_amount:,}</b> XU\n\n"
            f"💰 XU hiện tại: <b>{get_user_xu(user.id):,}</b>"
        )
    else:
        set_user_xu(user.id, current_xu - bet_amount)
        add_xu_lost(user.id, bet_amount)
        result_text = "TÀI" if is_tai else "XỈU"
        text = (
            f"💔 **THUA RỒI!**\n\n"
            f"🎲 Kết quả: <b>{result_text}</b>\n"
            f"💎 Cược: <b>{bet_amount:,}</b> XU\n"
            f"❌ Mất: <b>{bet_amount:,}</b> XU\n\n"
            f"💰 XU hiện tại: <b>{get_user_xu(user.id):,}</b>"
        )
    
    await update.effective_message.reply_html(text)


async def vaytien_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vay tiền chơi"""
    user = update.effective_user
    
    if not context.args:
        await update.effective_message.reply_text(
            "❌ Cách dùng: `/vaytien <số_tiền>`\n"
            "Ví dụ: `/vaytien 100000`"
        )
        return
    
    try:
        loan_amount = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Số tiền không hợp lệ!")
        return
    
    if loan_amount <= 0:
        await update.effective_message.reply_text("❌ Số tiền vay phải > 0")
        return
    
    if loan_amount > LOAN_MAX:
        await update.effective_message.reply_html(
            f"❌ <b>Tối đa vay:</b> {LOAN_MAX:,} XU\n"
            f"<b>Bạn yêu cầu:</b> {loan_amount:,} XU"
        )
        return
    
    total_loans = sum(l["amount"] for l in get_user_loans(user.id))
    if total_loans + loan_amount > LOAN_MAX:
        remaining = LOAN_MAX - total_loans
        await update.effective_message.reply_html(
            f"❌ <b>Hạn mức vay còn lại:</b> {remaining:,} XU"
        )
        return
    
    add_loan(user.id, loan_amount)
    
    text = (
        f"✅ **VAY TIỀN THÀNH CÔNG**\n\n"
        f"💳 Số tiền vay: <b>{loan_amount:,}</b> XU\n"
        f"⏰ Thời hạn trả: <b>5 giờ</b>\n"
        f"💰 XU hiện tại: <b>{get_user_xu(user.id):,}</b>\n\n"
        f"⚠️ <b>Lưu ý:</b> Nếu quá hạn không trả, bạn sẽ bị khóa trò chơi!\n"
        f"📞 Liên hệ admin: @DTN_207"
    )
    
    await update.effective_message.reply_html(text)


async def nhapma_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhập mã admin - Nhận vô hạn xu (riêng tư)"""
    user = update.effective_user
    
    # Nếu gõ trong nhóm, chuyển hướng sang riêng tư
    if update.effective_chat.type in (Chat.GROUP, Chat.SUPERGROUP):
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    "🔐 <b>PHẦN MỀM ADMIN</b>\n\n"
                    "Bạn đã gõ /nhapma trong nhóm!\n\n"
                    "⚠️ Vui lòng gõ lại `/nhapma [mã]` <b>trong DM này</b> để nhập mã admin.\n\n"
                    "💡 Để bảo mật, mã admin chỉ được xử lý trong tin nhắn riêng tư."
                ),
                parse_mode=ParseMode.HTML
            )
            await update.effective_message.reply_html(
                f"📨 {user.mention_html()}, mình đã gửi tin nhắn riêng tư cho bạn!\n"
                f"Vui lòng kiểm tra DM và nhập mã trong đó."
            )
        except Exception as e:
            await update.effective_message.reply_text(
                "❌ Không thể gửi DM! Vui lòng mở tin nhắn riêng tư với bot trước."
            )
        return
    
    # Xử lý trong DM (chat riêng)
    if not context.args:
        await update.effective_message.reply_text("❌ Cách dùng: `/nhapma [mã]`")
        return
    
    code = " ".join(context.args)
    admin_code = "Thiện Đẹp Trai"
    
    if code == admin_code:
        set_user_admin(user.id, True)
        set_user_xu(user.id, 999999999)  # Vô hạn xu
        
        await update.effective_message.reply_html(
            f"✅ <b>CHÍNH XÁC!</b>\n\n"
            f"🔓 Bạn đã trở thành <b>ADMIN</b>!\n"
            f"💎 Nhận được: <b>999,999,999 XU</b> (Vô hạn)\n"
            f"👑 Bạn giờ có quyền tối cao!\n\n"
            f"🌟 Quay lại nhóm để sử dụng quyền admin của bạn!"
        )
    else:
        await update.effective_message.reply_html(
            f"❌ <b>Bạn Nhập Sai!</b>\n\n"
            f"Hãy vào Nhóm Telegram để có Code\n"
            f"Nhập kiếm XU Nhóm ở Tiểu Sử BOT"
        )


async def nhapcode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhập code newbie - Nhận 100.000 xu (hiện công khai)"""
    user = update.effective_user
    
    if not context.args:
        # Nếu không có args, hiển thị code công khai
        if update.effective_chat.type in (Chat.GROUP, Chat.SUPERGROUP):
            await update.effective_message.reply_html(
                f"🆕 <b>CODE TÂN THỦ</b>\n\n"
                f"📢 <b>Code công khai cho mọi người:</b>\n\n"
                f"<code>tanthunewbie</code>\n\n"
                f"💝 Nhận: <b>+100,000 XU</b>\n"
                f"✅ Dùng lệnh: <code>/nhapcode tanthunewbie</code>"
            )
        else:
            await update.effective_message.reply_text(
                "❌ Cách dùng: `/nhapcode [code]`\n"
                "Hoặc gõ `/nhapcode` để xem code tân thủ"
            )
        return
    
    code = " ".join(context.args)
    newbie_code = "tanthunewbie"
    codes_used = get_codes_used(user.id)
    
    if code == newbie_code:
        # Kiểm tra xem đã dùng code newbie trước đó chưa
        if "newbie" in codes_used:
            await update.effective_message.reply_html(
                f"⚠️ <b>Lỗi!</b>\n\n"
                f"Bạn đã nhập code tân thủ rồi!\n"
                f"💡 Mỗi người chỉ được nhập <b>1 lần</b>.\n\n"
                f"Gõ `/taixiu` để chơi và kiếm thêm XU!"
            )
            return
        
        # Cấp 100.000 xu
        current_xu = get_user_xu(user.id)
        new_xu = current_xu + 100000
        set_user_xu(user.id, new_xu)
        add_code_used(user.id, "newbie")
        
        # Hiển thị công khai trong nhóm hoặc riêng tư trong DM
        if update.effective_chat.type in (Chat.GROUP, Chat.SUPERGROUP):
            await update.effective_message.reply_html(
                f"✅ <b>CHÍNH XÁC!</b>\n\n"
                f"🎉 {user.mention_html()} nhập code tân thủ thành công!\n"
                f"💝 Nhận được: <b>+100,000 XU</b>\n"
                f"💰 XU hiện tại: <b>{new_xu:,}</b>\n\n"
                f"🎮 Sẵn sàng chơi? Gõ `/taixiu [xu] [tài/xỉu]`"
            )
        else:
            await update.effective_message.reply_html(
                f"✅ <b>CHÍNH XÁC!</b>\n\n"
                f"🎉 {user.mention_html()} nhập code tân thủ thành công!\n"
                f"💝 Nhận được: <b>+100,000 XU</b>\n"
                f"💰 XU hiện tại: <b>{new_xu:,}</b>\n\n"
                f"🎮 Sẵn sàng chơi? Gõ `/taixiu [xu] [tài/xỉu]`"
            )
    else:
        await update.effective_message.reply_html(
            f"❌ <b>Bạn Nhập Sai!</b>\n\n"
            f"Hãy vào Nhóm Telegram để có Code\n"
            f"Nhập kiếm XU Nhóm ở Tiểu Sử BOT"
        )


# ============================================================
# FILTER COMMANDS
# ============================================================

async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Thêm filter"""
    if not await ensure_group_admin(update, context):
        return
    
    if len(context.args) < 2:
        await update.effective_message.reply_text(
            "❌ Cách dùng: `/filter <từ_khóa> <phản_hồi>`\n"
            "Ví dụ: `/filter hello hi`"
        )
        return
    
    trigger = context.args[0]
    response = " ".join(context.args[1:])
    
    add_filter(update.effective_chat.id, trigger, response)
    
    await update.effective_message.reply_html(
        f"✅ Thêm filter thành công!\n\n"
        f"🔑 Từ khóa: <b>{trigger}</b>\n"
        f"💬 Phản hồi: <b>{response}</b>"
    )


async def filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem tất cả filter"""
    if not await ensure_group_admin(update, context):
        return
    
    filters_dict = get_filters(update.effective_chat.id)
    
    if not filters_dict:
        await update.effective_message.reply_text("❌ Nhóm này chưa có filter nào")
        return
    
    text = "📖 **DANH SÁCH FILTER**\n\n"
    for trigger, response in filters_dict.items():
        text += f"🔑 <b>{trigger}</b> → {response}\n"
    
    await update.effective_message.reply_html(text)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xóa filter"""
    if not await ensure_group_admin(update, context):
        return
    
    if not context.args:
        await update.effective_message.reply_text("❌ Cách dùng: `/stop <từ_khóa>`")
        return
    
    trigger = context.args[0]
    remove_filter(update.effective_chat.id, trigger)
    
    await update.effective_message.reply_html(
        f"✅ Xóa filter <b>{trigger}</b> thành công!"
    )


# ============================================================
# AUTO FILTER RESPONSE
# ============================================================

async def handle_filter_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tự động trả lời theo filter"""
    if update.effective_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        return
    
    filters_dict = get_filters(update.effective_chat.id)
    message_text = (update.effective_message.text or "").lower()
    
    for trigger, response in filters_dict.items():
        if trigger.lower() in message_text:
            await update.effective_message.reply_text(response)
            return


# ============================================================
# PLACEHOLDER ADMIN COMMANDS (từ file cũ)
# ============================================================

async def cammom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("🔇 Lệnh /cammom đang được phát triển")


async def mocammom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("🔊 Lệnh /mocammom đang được phát triển")


async def sut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("🚫 Lệnh /sut đang được phát triển")


async def mosut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("✅ Lệnh /mosut đang được phát triển")


async def da_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("🦶 Lệnh /da đang được phát triển")


async def khoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("🔒 Lệnh /khoa đang được phát triển")


async def mokhoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("🔓 Lệnh /mokhoa đang được phát triển")


async def canhcao_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("⚠️ Lệnh /canhcao đang được phát triển")


async def xoacanhcao_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("🧹 Lệnh /xoacanhcao đang được phát triển")


async def ghim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("📌 Lệnh /ghim đang được phát triển")


async def boghim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("📌 Lệnh /boghim đang được phát triển")


async def thangchuc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("👑 Lệnh /thangchuc đang được phát triển")


async def giangchuc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("👤 Lệnh /giangchuc đang được phát triển")


async def thongtin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("ℹ️ Lệnh /thongtin đang được phát triển")


async def noiquy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in (Chat.GROUP, Chat.SUPERGROUP):
        if not await ensure_group_admin(update, context):
            return
    await update.effective_message.reply_text("📝 Lệnh /noiquy đang được phát triển")


async def xoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("❌ Lệnh /xoa đang được phát triển")


async def antilink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("⛓️ Lệnh /antilink đang được phát triển")


async def antispam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("📝 Lệnh /antispam đang được phát triển")


async def antibuff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("💬 Lệnh /antibuff đang được phát triển")


async def antifake_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_group_admin(update, context):
        return
    await update.effective_message.reply_text("🕵️ Lệnh /antifake đang được phát triển")


async def diemdanh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Điểm danh", callback_data=f"diemdanh:{user.id}")]]
    )
    await update.effective_message.reply_html(
        f"📋 Chào {user.mention_html()}, vui lòng nhấn nút điểm danh để xác nhận.\n"
        f"📋 Hi {user.mention_html()}, please tap the check-in button below.",
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
            "⚠️ Đây là nút điểm danh của người khác, không phải của bạn.",
            show_alert=True,
        )
        return

    data = load_data()
    chat_key = str(update.effective_chat.id)
    checkins = data.setdefault("checkins", {}).setdefault(chat_key, {})
    record = checkins.get(str(owner_id), {"streak": 0, "last_date": None})

    today = _today_str()
    if record["last_date"] == today:
        await query.answer(f"✅ Bạn đã điểm danh hôm nay! Streak: {record['streak']} 🔥", show_alert=True)
        return

    yesterday = (datetime.now(VN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    if record["last_date"] == yesterday:
        record["streak"] += 1
    else:
        record["streak"] = 1

    record["last_date"] = today
    checkins[str(owner_id)] = record
    save_data(data)

    await query.answer(f"🎉 Điểm danh thành công! Streak: {record['streak']} 🔥", show_alert=True)
    try:
        await query.edit_message_text(
            f"📋 {query.from_user.mention_html()} đã điểm danh ✅\n🔥 Streak: <b>{record['streak']}</b> ngày",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Lỗi khi xử lý update %s: %s", update, context.error)


# ============================================================
# MAIN
# ============================================================

def main():
    token = BOT_TOKEN
    if not token or token == "PASTE_YOUR_TOKEN_HERE":
        raise SystemExit("❌ Chưa dán BOT_TOKEN!")

    app = Application.builder().token(token).build()

    # Help & Casino commands
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menuXu", menuXu_command))
    app.add_handler(CommandHandler("xume", xume_command))
    app.add_handler(CommandHandler("xumat", xumat_command))
    app.add_handler(CommandHandler("taixiu", taixiu_command))
    app.add_handler(CommandHandler("vaytien", vaytien_command))
    app.add_handler(CommandHandler("nhapma", nhapma_command))
    app.add_handler(CommandHandler("nhapcode", nhapcode_command))

    # Filter commands
    app.add_handler(CommandHandler("filter", filter_command))
    app.add_handler(CommandHandler("filters", filters_command))
    app.add_handler(CommandHandler("stop", stop_command))

    # Admin commands
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

    # Callbacks
    app.add_handler(CallbackQueryHandler(help_admin_callback, pattern="^help_admin$"))
    app.add_handler(CallbackQueryHandler(help_utility_callback, pattern="^help_utility$"))
    app.add_handler(CallbackQueryHandler(help_casino_callback, pattern="^help_casino$"))
    app.add_handler(CallbackQueryHandler(back_to_help_callback, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(casino_admin_menu_callback, pattern="^casino_admin_menu$"))
    app.add_handler(CallbackQueryHandler(casino_newbie_menu_callback, pattern="^casino_newbie_menu$"))
    app.add_handler(CallbackQueryHandler(diemdanh_callback, pattern=r"^diemdanh:"))

    # Message handler for filters
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_filter_response
    ))

    app.add_error_handler(error_handler)

    logger.info("🤖 %s v2 đang chạy...", BOT_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()


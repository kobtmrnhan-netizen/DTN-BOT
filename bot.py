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

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /start - Hướng dẫn dùng /help"""
    await update.effective_message.reply_text(
        "Tôi Chỉ Hoạt Động khi bạn rõ lệnh /help"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hiển thị menu chính với 4 nút"""
    user = update.effective_user
    
    text = (
        f"👋 Chào {user.mention_html()}, tôi là {BOT_NAME}.\n\n"
        f"🌟 Tôi có nhiều công cụ hữu ích. Chạm vào một module bên dưới để xem lệnh 💝\n\n"
        f"🌍 Tôi hỗ trợ Tiếng Việt 🇻🇳 và English 🇺🇸"
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛡️ Quản Trị", callback_data="help_admin"),
            InlineKeyboardButton("🛠️ Tiện Ích", callback_data="help_utility"),
        ],
        [
            InlineKeyboardButton("📊 Thống Kê", callback_data="help_stats"),
            InlineKeyboardButton("🎰 Nhà Cái", callback_data="help_casino"),
        ]
    ])
    
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
            InlineKeyboardButton("☰ Menu", callback_data="help"),
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
        "🆕 <b>LỆNH MỚI:</b>\n"
        "✅ <b>/ghostban</b> &lt;@user|id&gt; - Cấm lặng lẽ (họ ko biết)\n"
        "✅ <b>/welcome</b> [text] - Chào mừng member mới\n"
        "✅ <b>/goodbye</b> [text] - Tạm biệt member rời\n"
        "✅ <b>/wordfilter</b> add/remove/list &lt;từ&gt; - Quản lý từ cấm\n"
        "✅ <b>/muteall</b> - Câm tất cả member\n"
        "✅ <b>/unmuteall</b> - Mở câm tất cả\n"
        "✅ <b>/ticket</b> [vấn đề] - Tạo ticket hỗ trợ\n\n"
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
            InlineKeyboardButton("☰ Menu", callback_data="help"),
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
        "🆕 <b>LỆNH MỚI:</b>\n"
        "✅ <b>/translate</b> &lt;text&gt; [ngôn_ngữ] - Dịch tin nhắn\n"
        "✅ <b>/report</b> @user [lý do] - Báo cáo vi phạm\n"
        "✅ <b>/faq</b> [add/list] - Câu hỏi thường gặp\n"
        "✅ <b>/kb</b> [add/list] - Knowledge Base\n"
        "✅ <b>/links</b> [add/list] - Quick Links\n\n"
        "💡 <b>Ví dụ:</b>\n"
        "<code>/filter xin hello</code> - Khi ai nhắn 'xin', bot trả lời 'hello'\n"
        "<code>/translate hello vi</code> - Dịch từ ENG → VI\n"
        "<code>/faq add Giá bao nhiêu Giá 50k</code>"
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
            InlineKeyboardButton("☰ Menu", callback_data="help"),
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
        "✅ <b>/tratien</b> &lt;số_tiền&gt; - Trả nợ\n"
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


async def help_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menu thống kê"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data="stats_view"),
            InlineKeyboardButton("📈 Growth", callback_data="growth_view"),
            InlineKeyboardButton("💬 Analytics", callback_data="analytics_view"),
        ],
        [
            InlineKeyboardButton("⏰ Peak Hours", callback_data="peak_view"),
        ],
        [
            InlineKeyboardButton("☰ Menu", callback_data="help"),
            InlineKeyboardButton("🔙 Quay lại", callback_data="help"),
        ]
    ])
    
    text = (
        "📊 <b>LỆNH THỐNG KÊ</b>\n\n"
        "✅ <b>/stats</b> - Xem thống kê hoạt động\n"
        "✅ <b>/growth</b> - Xem biểu đồ tăng trưởng\n"
        "✅ <b>/analytics</b> - Phân tích tin nhắn\n"
        "✅ <b>/peakhours</b> - Xem giờ hoạt động nhất\n\n"
        "📈 Các lệnh này sẽ giúp bạn:\n"
        "• Theo dõi hoạt động của nhóm\n"
        "• Xem ai active nhất\n"
        "• Phân tích thời gian peak\n"
        "• Theo dõi tăng trưởng member"
    )
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
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


async def tratien_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trả tiền nợ"""
    user = update.effective_user
    
    if not context.args:
        await update.effective_message.reply_text("❌ Cách dùng: `/tratien <số_tiền>`\nVí dụ: `/tratien 50000`")
        return
    
    try:
        payment = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Số tiền không hợp lệ!")
        return
    
    if payment <= 0:
        await update.effective_message.reply_text("❌ Số tiền trả phải > 0")
        return
    
    # Lấy thông tin nợ
    loans = get_user_loans(user.id)
    if not loans:
        await update.effective_message.reply_html(
            f"✅ <b>Bạn không có nợ!</b>\n\n"
            f"💰 Hiện tại XU của bạn: <b>{get_user_xu(user.id):,}</b>"
        )
        return
    
    # Tính tổng nợ
    total_debt = sum(loan["amount"] for loan in loans)
    current_xu = get_user_xu(user.id)
    
    if current_xu < payment:
        await update.effective_message.reply_html(
            f"❌ <b>Bạn không đủ XU để trả!</b>\n\n"
            f"💰 XU hiện có: <b>{current_xu:,}</b>\n"
            f"💎 Muốn trả: <b>{payment:,}</b>"
        )
        return
    
    # Trả tiền
    set_user_xu(user.id, current_xu - payment)
    remaining_debt = total_debt - payment
    
    if remaining_debt <= 0:
        # Hết nợ
        clear_loans(user.id)
        await update.effective_message.reply_html(
            f"✅ <b>TRẢ NỢ THÀNH CÔNG!</b>\n\n"
            f"💳 Số tiền trả: <b>{payment:,}</b> XU\n"
            f"🎉 Bạn đã <b>THANH TOÁN HẾT NỢ</b>!\n\n"
            f"💰 XU hiện tại: <b>{get_user_xu(user.id):,}</b>"
        )
    else:
        # Còn nợ
        # Cập nhật lại loans (trừ đi số tiền đã trả)
        data = load_data()
        users = data.setdefault("users", {})
        
        # Tính lại danh sách loans sau khi trả
        remaining = payment
        for i, loan in enumerate(users[str(user.id)]["loans"]):
            if remaining <= 0:
                break
            if remaining >= loan["amount"]:
                remaining -= loan["amount"]
                users[str(user.id)]["loans"][i] = None
            else:
                users[str(user.id)]["loans"][i]["amount"] -= remaining
                remaining = 0
        
        # Xóa loans đã trả (None)
        users[str(user.id)]["loans"] = [l for l in users[str(user.id)]["loans"] if l is not None]
        save_data(data)
        
        await update.effective_message.reply_html(
            f"✅ <b>TRẢ NỢ THÀNH CÔNG!</b>\n\n"
            f"💳 Số tiền trả: <b>{payment:,}</b> XU\n"
            f"⚠️ Còn nợ: <b>{remaining_debt:,}</b> XU\n\n"
            f"💰 XU hiện tại: <b>{get_user_xu(user.id):,}</b>\n"
            f"📝 Hãy trả nợ trước khi <b>quá hạn 5 giờ</b>!"
        )


async def ghostban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cấm lặng lẽ - người không biết mình bị cấm"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await update.effective_message.reply_html(
            f"👻 {user_html} đã bị cấm lặng lẽ!\n"
            f"(Họ không biết mình bị cấm)"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def welcome_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Đặt tin chào mừng member mới"""
    if update.effective_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.effective_message.reply_text("Lệnh chỉ xài trong nhóm")
        return
    
    if not await ensure_group_admin(update, context):
        return
    
    if not context.args:
        data = load_data()
        welcome_msg = data.get("welcome_msg", {}).get(str(update.effective_chat.id))
        if welcome_msg:
            await update.effective_message.reply_html(
                f"👋 <b>WELCOME MESSAGE HIỆN TẠI:</b>\n\n{welcome_msg}"
            )
        else:
            await update.effective_message.reply_text("❌ Nhóm này chưa có welcome message!")
        return
    
    welcome_text = " ".join(context.args)
    data = load_data()
    data.setdefault("welcome_msg", {})[str(update.effective_chat.id)] = welcome_text
    save_data(data)
    
    await update.effective_message.reply_html(
        f"✅ Welcome message đã được cập nhật:\n\n{welcome_text}"
    )


async def goodbye_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Đặt tin tạm biệt member rời"""
    if update.effective_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.effective_message.reply_text("Lệnh chỉ xài trong nhóm")
        return
    
    if not await ensure_group_admin(update, context):
        return
    
    if not context.args:
        data = load_data()
        goodbye_msg = data.get("goodbye_msg", {}).get(str(update.effective_chat.id))
        if goodbye_msg:
            await update.effective_message.reply_html(
                f"👋 <b>GOODBYE MESSAGE HIỆN TẠI:</b>\n\n{goodbye_msg}"
            )
        else:
            await update.effective_message.reply_text("❌ Nhóm này chưa có goodbye message!")
        return
    
    goodbye_text = " ".join(context.args)
    data = load_data()
    data.setdefault("goodbye_msg", {})[str(update.effective_chat.id)] = goodbye_text
    save_data(data)
    
    await update.effective_message.reply_html(
        f"✅ Goodbye message đã được cập nhật:\n\n{goodbye_text}"
    )


async def wordfilter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quản lý từ cấm"""
    if not await ensure_group_admin(update, context):
        return
    
    if not context.args:
        await update.effective_message.reply_text(
            "❌ Cách dùng:\n"
            "/wordfilter add <từ> - Thêm từ cấm\n"
            "/wordfilter remove <từ> - Xóa từ cấm\n"
            "/wordfilter list - Xem danh sách từ cấm"
        )
        return
    
    action = context.args[0].lower()
    
    if action == "add":
        if len(context.args) < 2:
            await update.effective_message.reply_text("❌ Cách dùng: /wordfilter add <từ>")
            return
        word = context.args[1].lower()
        data = load_data()
        data.setdefault("banned_words", {}).setdefault(str(update.effective_chat.id), []).append(word)
        save_data(data)
        await update.effective_message.reply_html(f"✅ Đã thêm từ cấm: <b>{word}</b>")
    
    elif action == "remove":
        if len(context.args) < 2:
            await update.effective_message.reply_text("❌ Cách dùng: /wordfilter remove <từ>")
            return
        word = context.args[1].lower()
        data = load_data()
        if str(update.effective_chat.id) in data.get("banned_words", {}):
            data["banned_words"][str(update.effective_chat.id)].remove(word)
            save_data(data)
            await update.effective_message.reply_html(f"✅ Đã xóa từ cấm: <b>{word}</b>")
        else:
            await update.effective_message.reply_text("❌ Từ này không có trong danh sách!")
    
    elif action == "list":
        data = load_data()
        banned_words = data.get("banned_words", {}).get(str(update.effective_chat.id), [])
        if banned_words:
            text = "📝 <b>DANH SÁCH TỪ CẤM:</b>\n\n"
            for word in banned_words:
                text += f"• {word}\n"
            await update.effective_message.reply_html(text)
        else:
            await update.effective_message.reply_text("❌ Nhóm này chưa có từ cấm nào!")
    else:
        await update.effective_message.reply_text("❌ Action không hợp lệ: add/remove/list")


async def muteall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Câm tất cả member"""
    if not await ensure_group_admin(update, context):
        return
    
    try:
        await context.bot.set_chat_permissions(
            update.effective_chat.id, permissions=MUTED_PERMISSIONS
        )
        await update.effective_message.reply_html(
            "🔇 <b>TẤT CẢ MEMBER ĐÃ BỊ CÂM!</b>\n\n"
            "Chỉ admin có thể nói chuyện."
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def unmuteall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mở câm tất cả member"""
    if not await ensure_group_admin(update, context):
        return
    
    try:
        await context.bot.set_chat_permissions(
            update.effective_chat.id, permissions=FULL_PERMISSIONS
        )
        await update.effective_message.reply_html(
            "🔊 <b>NHÓM ĐÃ ĐƯỢC MỞ!</b>\n\n"
            "Tất cả member có thể nói chuyện bình thường."
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tạo ticket hỗ trợ"""
    user = update.effective_user
    
    if not context.args:
        await update.effective_message.reply_text(
            "❌ Cách dùng: `/ticket [mô tả vấn đề]`\n"
            "Ví dụ: `/ticket Bị lỗi khi chơi tài xỉu`"
        )
        return
    
    issue = " ".join(context.args)
    data = load_data()
    tickets = data.setdefault("tickets", {})
    ticket_id = len(tickets) + 1
    
    tickets[str(ticket_id)] = {
        "user_id": user.id,
        "username": user.username or user.first_name,
        "issue": issue,
        "status": "open",
        "created_at": datetime.now(VN_TZ).isoformat()
    }
    save_data(data)
    
    await update.effective_message.reply_html(
        f"✅ <b>TICKET ĐÃ TẠO!</b>\n\n"
        f"🆔 Ticket ID: <b>#{ticket_id}</b>\n"
        f"👤 Người báo cáo: {user.mention_html()}\n"
        f"📝 Vấn đề: {issue}\n"
        f"⏰ Trạng thái: <b>Đang xử lý</b>\n\n"
        f"Admin sẽ xem xét sớm nhất có thể!"
    )

    """Trả tiền nợ"""
    user = update.effective_user
    
    if not context.args:
        await update.effective_message.reply_text("❌ Cách dùng: `/tratien <số_tiền>`\nVí dụ: `/tratien 50000`")
        return
    
    try:
        payment = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("❌ Số tiền không hợp lệ!")
        return
    
    if payment <= 0:
        await update.effective_message.reply_text("❌ Số tiền trả phải > 0")
        return
    
    # Lấy thông tin nợ
    loans = get_user_loans(user.id)
    if not loans:
        await update.effective_message.reply_html(
            f"✅ <b>Bạn không có nợ!</b>\n\n"
            f"💰 Hiện tại XU của bạn: <b>{get_user_xu(user.id):,}</b>"
        )
        return
    
    # Tính tổng nợ
    total_debt = sum(loan["amount"] for loan in loans)
    current_xu = get_user_xu(user.id)
    
    if current_xu < payment:
        await update.effective_message.reply_html(
            f"❌ <b>Bạn không đủ XU để trả!</b>\n\n"
            f"💰 XU hiện có: <b>{current_xu:,}</b>\n"
            f"💎 Muốn trả: <b>{payment:,}</b>"
        )
        return
    
    # Trả tiền
    set_user_xu(user.id, current_xu - payment)
    remaining_debt = total_debt - payment
    
    if remaining_debt <= 0:
        # Hết nợ
        clear_loans(user.id)
        await update.effective_message.reply_html(
            f"✅ <b>TRẢ NỢ THÀNH CÔNG!</b>\n\n"
            f"💳 Số tiền trả: <b>{payment:,}</b> XU\n"
            f"🎉 Bạn đã <b>THANH TOÁN HẾT NỢ</b>!\n\n"
            f"💰 XU hiện tại: <b>{get_user_xu(user.id):,}</b>"
        )
    else:
        # Còn nợ
        # Cập nhật lại loans (trừ đi số tiền đã trả)
        data = load_data()
        users = data.setdefault("users", {})
        
        # Tính lại danh sách loans sau khi trả
        remaining = payment
        for i, loan in enumerate(users[str(user.id)]["loans"]):
            if remaining <= 0:
                break
            if remaining >= loan["amount"]:
                remaining -= loan["amount"]
                users[str(user.id)]["loans"][i] = None
            else:
                users[str(user.id)]["loans"][i]["amount"] -= remaining
                remaining = 0
        
        # Xóa loans đã trả (None)
        users[str(user.id)]["loans"] = [l for l in users[str(user.id)]["loans"] if l is not None]
        save_data(data)
        
        await update.effective_message.reply_html(
            f"✅ <b>TRẢ NỢ THÀNH CÔNG!</b>\n\n"
            f"💳 Số tiền trả: <b>{payment:,}</b> XU\n"
            f"⚠️ Còn nợ: <b>{remaining_debt:,}</b> XU\n\n"
            f"💰 XU hiện tại: <b>{get_user_xu(user.id):,}</b>\n"
            f"📝 Hãy trả nợ trước khi <b>quá hạn 5 giờ</b>!"
        )
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
    """Câm người dùng"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    duration = None
    if args:
        duration = parse_duration(args[0])
    
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user_id, permissions=MUTED_PERMISSIONS, until_date=duration
        )
        time_str = f"trong {args[0]}" if args else "vĩnh viễn"
        await update.effective_message.reply_html(
            f"🔇 {user_html} đã bị câm {time_str}!"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def mocammom_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uncam người dùng"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user_id, permissions=FULL_PERMISSIONS
        )
        await update.effective_message.reply_html(
            f"🔊 {user_html} đã được uncam!"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def sut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cấm người dùng"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    duration = None
    if args:
        duration = parse_duration(args[0])
    
    try:
        await context.bot.ban_chat_member(
            update.effective_chat.id, user_id, until_date=duration
        )
        time_str = f"trong {args[0]}" if args else "vĩnh viễn"
        await update.effective_message.reply_html(
            f"🚫 {user_html} đã bị cấm {time_str}!"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def mosut_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hỏi cấm người dùng"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, user_id)
        await update.effective_message.reply_html(
            f"✅ {user_html} đã được hỏi cấm!"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def da_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kick người dùng"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await context.bot.unban_chat_member(update.effective_chat.id, user_id)
        await update.effective_message.reply_html(
            f"🦶 {user_html} đã bị kick khỏi nhóm!"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def khoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Khóa nhóm - chỉ admin nói được"""
    if not await ensure_group_admin(update, context):
        return
    
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            update.effective_user.id,
            permissions=FULL_PERMISSIONS
        )
        await context.bot.set_chat_permissions(
            update.effective_chat.id, permissions=MUTED_PERMISSIONS
        )
        await update.effective_message.reply_html(
            "🔒 Nhóm đã bị khóa! Chỉ admin có thể nói chuyện."
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def mokhoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mở khóa nhóm"""
    if not await ensure_group_admin(update, context):
        return
    
    try:
        await context.bot.set_chat_permissions(
            update.effective_chat.id, permissions=FULL_PERMISSIONS
        )
        await update.effective_message.reply_html(
            "🔓 Nhóm đã được mở khóa! Mọi người có thể nói chuyện bình thường."
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def canhcao_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cảnh cáo người dùng"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    reason = " ".join(args) if args else "Không nêu lý do"
    
    data = load_data()
    warns = data.setdefault("warns", {}).setdefault(str(update.effective_chat.id), {})
    warn_count = warns.get(str(user_id), 0) + 1
    warns[str(user_id)] = warn_count
    save_data(data)
    
    await update.effective_message.reply_html(
        f"⚠️ {user_html} đã nhận cảnh cáo!\n\n"
        f"Lý do: {reason}\n"
        f"Cảnh cáo: {warn_count}/{CANHCAO_AUTO_SUT}"
    )
    
    if warn_count >= CANHCAO_AUTO_SUT:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, user_id)
            await update.effective_message.reply_html(
                f"🚫 {user_html} đã bị cấm vì nhận đủ {CANHCAO_AUTO_SUT} cảnh cáo!"
            )
        except Exception:
            pass


async def xoacanhcao_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset cảnh cáo"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    data = load_data()
    warns = data.setdefault("warns", {}).setdefault(str(update.effective_chat.id), {})
    warns[str(user_id)] = 0
    save_data(data)
    
    await update.effective_message.reply_html(
        f"🧹 Cảnh cáo của {user_html} đã được xóa!"
    )


async def ghim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ghim tin nhắn"""
    if not await ensure_group_admin(update, context):
        return
    
    if update.effective_message.reply_to_message:
        try:
            await context.bot.pin_chat_message(
                update.effective_chat.id,
                update.effective_message.reply_to_message.message_id,
                disable_notification=True
            )
            await update.effective_message.reply_html("📌 Tin nhắn đã được ghim!")
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")
    else:
        await update.effective_message.reply_text("❌ Vui lòng reply tin nhắn cần ghim")


async def boghim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bỏ ghim tin nhắn"""
    if not await ensure_group_admin(update, context):
        return
    
    if update.effective_message.reply_to_message:
        try:
            await context.bot.unpin_chat_message(
                update.effective_chat.id,
                update.effective_message.reply_to_message.message_id
            )
            await update.effective_message.reply_html("📌 Tin nhắn đã được bỏ ghim!")
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")
    else:
        await update.effective_message.reply_text("❌ Vui lòng reply tin nhắn cần bỏ ghim")


async def thangchuc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Thăng chức admin"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id, user_id,
            can_delete_messages=True,
            can_restrict_members=True,
            can_promote_members=True,
            can_manage_chat=True
        )
        await update.effective_message.reply_html(
            f"👑 {user_html} đã được thăng chức admin!"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def giangchuc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Giáng chức admin"""
    if not await ensure_group_admin(update, context):
        return
    
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id, user_id,
            can_delete_messages=False,
            can_restrict_members=False,
            can_promote_members=False,
            can_manage_chat=False
        )
        await update.effective_message.reply_html(
            f"👤 {user_html} đã bị giáng chức!"
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def thongtin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem thông tin người dùng"""
    user_id, user_html, args = await get_target_and_args(update, context)
    if not user_id:
        return
    
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        user = member.user
        
        status_map = {
            "creator": "👑 Chủ nhóm",
            "administrator": "🛡️ Admin",
            "member": "👤 Thành viên",
            "restricted": "⛔ Bị hạn chế",
            "left": "➡️ Rời nhóm",
            "kicked": "🚫 Bị kick"
        }
        
        status = status_map.get(member.status, "❓ Không xác định")
        
        text = (
            f"ℹ️ <b>THÔNG TIN NGƯỜI DÙNG</b>\n\n"
            f"👤 <b>Tên:</b> {user_html}\n"
            f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
            f"📱 <b>Username:</b> @{user.username if user.username else 'Không có'}\n"
            f"<b>Trạng thái:</b> {status}\n"
            f"🤖 <b>Bot:</b> {'✅ Có' if user.is_bot else '❌ Không'}"
        )
        
        await update.effective_message.reply_html(text)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def noiquy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem/đặt nội quy nhóm"""
    if update.effective_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.effective_message.reply_text("Lệnh chỉ xài trong nhóm")
        return
    
    chat = update.effective_chat
    
    if context.args:
        # Đặt nội quy
        if not await ensure_group_admin(update, context):
            return
        
        rules = " ".join(context.args)
        data = load_data()
        data.setdefault("rules", {})[str(chat.id)] = rules
        save_data(data)
        
        await update.effective_message.reply_html(
            f"✅ Nội quy nhóm đã được cập nhật:\n\n{rules}"
        )
    else:
        # Xem nội quy
        data = load_data()
        rules = data.get("rules", {}).get(str(chat.id))
        
        if rules:
            await update.effective_message.reply_html(
                f"📝 <b>NỘI QUY NHÓM</b>\n\n{rules}"
            )
        else:
            await update.effective_message.reply_text(
                "❌ Nhóm này chưa có nội quy! Admin vui lòng đặt bằng:\n"
                "/noiquy [nội quy của bạn]"
            )


async def xoa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xóa tin nhắn"""
    if not await ensure_group_admin(update, context):
        return
    
    if update.effective_message.reply_to_message:
        try:
            await update.effective_message.reply_to_message.delete()
            await update.effective_message.delete()
        except Exception as e:
            await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")
    else:
        await update.effective_message.reply_text("❌ Vui lòng reply tin nhắn cần xóa")


async def antilink_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bật/tắt chặn link"""
    if not await ensure_group_admin(update, context):
        return
    
    if not context.args or context.args[0].lower() not in ("on", "off"):
        current = get_settings(update.effective_chat.id).get("antilink")
        await update.effective_message.reply_text(
            f"⛓️ Antilink hiện: {'✅ BẬT' if current else '❌ TẮT'}\n"
            f"Dùng: /antilink on hoặc /antilink off"
        )
        return
    
    status = context.args[0].lower() == "on"
    set_setting(update.effective_chat.id, "antilink", status)
    
    await update.effective_message.reply_html(
        f"⛓️ Antilink đã {'✅ BẬT' if status else '❌ TẮT'}"
    )


async def antispam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bật/tắt chặn spam"""
    if not await ensure_group_admin(update, context):
        return
    
    if not context.args or context.args[0].lower() not in ("on", "off"):
        current = get_settings(update.effective_chat.id).get("antispam")
        await update.effective_message.reply_text(
            f"📝 Antispam hiện: {'✅ BẬT' if current else '❌ TẮT'}\n"
            f"Dùng: /antispam on hoặc /antispam off"
        )
        return
    
    status = context.args[0].lower() == "on"
    set_setting(update.effective_chat.id, "antispam", status)
    
    await update.effective_message.reply_html(
        f"📝 Antispam đã {'✅ BẬT' if status else '❌ TẮT'}"
    )


async def antibuff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bật/tắt chặn nhồi tin"""
    if not await ensure_group_admin(update, context):
        return
    
    if not context.args or context.args[0].lower() not in ("on", "off"):
        current = get_settings(update.effective_chat.id).get("antiflood")
        await update.effective_message.reply_text(
            f"💬 Antibuff hiện: {'✅ BẬT' if current else '❌ TẮT'}\n"
            f"Dùng: /antibuff on hoặc /antibuff off"
        )
        return
    
    status = context.args[0].lower() == "on"
    set_setting(update.effective_chat.id, "antiflood", status)
    
    await update.effective_message.reply_html(
        f"💬 Antibuff đã {'✅ BẬT' if status else '❌ TẮT'}"
    )


async def antifake_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bật/tắt chặn giả danh"""
    if not await ensure_group_admin(update, context):
        return
    
    if not context.args or context.args[0].lower() not in ("on", "off"):
        current = get_settings(update.effective_chat.id).get("antifake")
        await update.effective_message.reply_text(
            f"🕵️ Antifake hiện: {'✅ BẬT' if current else '❌ TẮT'}\n"
            f"Dùng: /antifake on hoặc /antifake off"
        )
        return
    
    status = context.args[0].lower() == "on"
    set_setting(update.effective_chat.id, "antifake", status)
    
    await update.effective_message.reply_html(
        f"🕵️ Antifake đã {'✅ BẬT' if status else '❌ TẮT'}"
    )


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dịch tin nhắn (giả lập - chỉ hiển thị hướng dẫn)"""
    if not context.args:
        await update.effective_message.reply_text(
            "❌ Cách dùng: `/translate <text> [ngôn_ngữ]`\n\n"
            "Ví dụ:\n"
            "`/translate hello vi` - Dịch từ ENG → VI\n"
            "`/translate xin chào en` - Dịch từ VI → EN"
        )
        return
    
    text_to_translate = " ".join(context.args[:-1]) if len(context.args) > 1 else context.args[0]
    target_lang = context.args[-1].lower() if len(context.args) > 1 else "vi"
    
    # Giả lập dịch (vì không có thư viện nặng)
    lang_names = {"vi": "Tiếng Việt", "en": "English", "ja": "日本語", "zh": "中文"}
    
    await update.effective_message.reply_html(
        f"🌐 <b>DỊCH THUẬT</b>\n\n"
        f"📝 Văn bản gốc: <i>{text_to_translate}</i>\n"
        f"🌍 Ngôn ngữ: <b>{lang_names.get(target_lang, 'Không xác định')}</b>\n\n"
        f"💡 <i>Chức năng dịch đầy đủ sẽ được thêm sau khi upgrade server!</i>"
    )


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Báo cáo vi phạm"""
    user = update.effective_user
    
    if len(context.args) < 2:
        await update.effective_message.reply_text(
            "❌ Cách dùng: `/report @user [lý do]`\n"
            "Ví dụ: `/report @spammer Spam link`"
        )
        return
    
    target = context.args[0]
    reason = " ".join(context.args[1:])
    
    data = load_data()
    reports = data.setdefault("reports", {})
    report_id = len(reports) + 1
    
    reports[str(report_id)] = {
        "reporter_id": user.id,
        "reporter": user.mention_html(),
        "target": target,
        "reason": reason,
        "status": "pending",
        "created_at": datetime.now(VN_TZ).isoformat()
    }
    save_data(data)
    
    await update.effective_message.reply_html(
        f"✅ <b>BÁO CÁO ĐÃ GỬI!</b>\n\n"
        f"🆔 Report ID: <b>#{report_id}</b>\n"
        f"👤 Người báo cáo: {user.mention_html()}\n"
        f"⚠️ Đối tượng: <b>{target}</b>\n"
        f"📝 Lý do: {reason}\n\n"
        f"Admin sẽ kiểm tra và xử lý soonest!"
    )


async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quản lý FAQ"""
    if not context.args:
        data = load_data()
        faq_data = data.get("faq", {}).get(str(update.effective_chat.id), {})
        
        if not faq_data:
            await update.effective_message.reply_text("❌ Nhóm này chưa có FAQ nào!")
            return
        
        text = "❓ <b>FREQUENTLY ASKED QUESTIONS</b>\n\n"
        for q, a in faq_data.items():
            text += f"<b>Q:</b> {q}\n"
            text += f"<b>A:</b> {a}\n\n"
        await update.effective_message.reply_html(text)
        return
    
    if not await ensure_group_admin(update, context):
        return
    
    if context.args[0].lower() == "add":
        if len(context.args) < 3:
            await update.effective_message.reply_text(
                "❌ Cách dùng: `/faq add <câu_hỏi> <câu_trả_lời>`"
            )
            return
        
        question = context.args[1]
        answer = " ".join(context.args[2:])
        
        data = load_data()
        data.setdefault("faq", {}).setdefault(str(update.effective_chat.id), {})[question] = answer
        save_data(data)
        
        await update.effective_message.reply_html(
            f"✅ Đã thêm FAQ:\n"
            f"<b>Q:</b> {question}\n"
            f"<b>A:</b> {answer}"
        )


async def kb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Knowledge Base"""
    if not context.args:
        data = load_data()
        kb_data = data.get("knowledge_base", {}).get(str(update.effective_chat.id), {})
        
        if not kb_data:
            await update.effective_message.reply_text("❌ Chưa có kiến thức nào trong Knowledge Base!")
            return
        
        text = "📚 <b>KNOWLEDGE BASE</b>\n\n"
        for topic, content in kb_data.items():
            text += f"📌 <b>{topic}</b>\n{content}\n\n"
        await update.effective_message.reply_html(text)
        return
    
    if not await ensure_group_admin(update, context):
        return
    
    if context.args[0].lower() == "add":
        if len(context.args) < 3:
            await update.effective_message.reply_text(
                "❌ Cách dùng: `/kb add <chủ_đề> <nội_dung>`"
            )
            return
        
        topic = context.args[1]
        content = " ".join(context.args[2:])
        
        data = load_data()
        data.setdefault("knowledge_base", {}).setdefault(str(update.effective_chat.id), {})[topic] = content
        save_data(data)
        
        await update.effective_message.reply_html(
            f"✅ Đã thêm vào Knowledge Base:\n"
            f"<b>Chủ đề:</b> {topic}\n"
            f"<b>Nội dung:</b> {content}"
        )


async def links_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quản lý Quick Links"""
    if not context.args:
        data = load_data()
        links_data = data.get("quick_links", {}).get(str(update.effective_chat.id), {})
        
        if not links_data:
            await update.effective_message.reply_text("❌ Nhóm này chưa có Quick Links nào!")
            return
        
        text = "🔗 <b>QUICK LINKS</b>\n\n"
        for name, url in links_data.items():
            text += f"📌 <b>{name}:</b> {url}\n"
        await update.effective_message.reply_html(text)
        return
    
    if not await ensure_group_admin(update, context):
        return
    
    if context.args[0].lower() == "add":
        if len(context.args) < 3:
            await update.effective_message.reply_text(
                "❌ Cách dùng: `/links add <tên> <url>`"
            )
            return
        
        name = context.args[1]
        url = " ".join(context.args[2:])
        
        data = load_data()
        data.setdefault("quick_links", {}).setdefault(str(update.effective_chat.id), {})[name] = url
        save_data(data)
        
        await update.effective_message.reply_html(
            f"✅ Đã thêm Quick Link:\n"
            f"<b>Tên:</b> {name}\n"
            f"<b>URL:</b> {url}"
        )

    user = update.effective_user
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Điểm danh", callback_data=f"diemdanh:{user.id}")]]
    )
    await update.effective_message.reply_html(
        f"📋 Chào {user.mention_html()}, vui lòng nhấn nút điểm danh để xác nhận.\n"
        f"📋 Hi {user.mention_html()}, please tap the check-in button below.",
        reply_markup=keyboard,
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem thống kê hoạt động nhóm"""
    if update.effective_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.effective_message.reply_text("Lệnh chỉ xài trong nhóm")
        return
    
    data = load_data()
    message_count = data.get("message_count", {}).get(str(update.effective_chat.id), {})
    
    if not message_count:
        await update.effective_message.reply_text("❌ Chưa có dữ liệu thống kê!")
        return
    
    sorted_users = sorted(message_count.items(), key=lambda x: x[1], reverse=True)[:10]
    
    text = f"📊 <b>THỐNG KÊ HOẠT ĐỘNG NHÓM</b>\n\n"
    text += f"🔥 <b>TOP 10 ACTIVE MEMBERS:</b>\n\n"
    
    for i, (user_id, count) in enumerate(sorted_users, 1):
        text += f"{i}. <b>User {user_id}:</b> {count} tin nhắn\n"
    
    await update.effective_message.reply_html(text)


async def growth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem biểu đồ tăng trưởng member"""
    if update.effective_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.effective_message.reply_text("Lệnh chỉ xài trong nhóm")
        return
    
    try:
        chat = await context.bot.get_chat(update.effective_chat.id)
        member_count = await context.bot.get_chat_member_count(update.effective_chat.id)
        
        text = (
            f"📈 <b>BIỂU ĐỒ TĂNG TRƯỞNG NHÓM</b>\n\n"
            f"👥 <b>Tổng thành viên:</b> {member_count}\n"
            f"📝 <b>Tên nhóm:</b> {chat.title}\n"
            f"📅 <b>Ngày kiểm tra:</b> {datetime.now(VN_TZ).strftime('%d/%m/%Y %H:%M')}\n\n"
            f"💡 <i>Biểu đồ chi tiết sẽ được cập nhật khi có thêm dữ liệu lịch sử!</i>"
        )
        
        await update.effective_message.reply_html(text)
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lỗi: {str(e)}")


async def analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phân tích tin nhắn"""
    if update.effective_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.effective_message.reply_text("Lệnh chỉ xài trong nhóm")
        return
    
    data = load_data()
    message_count = data.get("message_count", {}).get(str(update.effective_chat.id), {})
    
    if not message_count:
        await update.effective_message.reply_text("❌ Chưa có dữ liệu phân tích!")
        return
    
    total_messages = sum(message_count.values())
    avg_messages = total_messages // len(message_count) if message_count else 0
    
    text = (
        f"📊 <b>PHÂN TÍCH TIN NHẮN</b>\n\n"
        f"📈 <b>Tổng tin nhắn:</b> {total_messages}\n"
        f"👥 <b>Số người nói:</b> {len(message_count)}\n"
        f"⏱️ <b>Trung bình/người:</b> {avg_messages} tin\n\n"
        f"🔝 <b>Top 3 người chat nhiều nhất:</b>\n"
    )
    
    sorted_users = sorted(message_count.items(), key=lambda x: x[1], reverse=True)[:3]
    for i, (user_id, count) in enumerate(sorted_users, 1):
        percentage = (count / total_messages * 100) if total_messages > 0 else 0
        text += f"{i}. User {user_id}: {count} tin ({percentage:.1f}%)\n"
    
    await update.effective_message.reply_html(text)


async def peakhours_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xem giờ hoạt động nhất"""
    if update.effective_chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await update.effective_message.reply_text("Lệnh chỉ xài trong nhóm")
        return
    
    data = load_data()
    peak_data = data.get("peak_hours", {}).get(str(update.effective_chat.id), {})
    
    if not peak_data:
        current_hour = datetime.now(VN_TZ).hour
        await update.effective_message.reply_html(
            f"⏰ <b>GIỜ HOẠT ĐỘNG NHẤT</b>\n\n"
            f"🕐 <b>Giờ hiện tại:</b> {current_hour}:00\n\n"
            f"💡 <i>Dữ liệu sẽ được cập nhật khi nhóm hoạt động!</i>"
        )
        return
    
    sorted_hours = sorted(peak_data.items(), key=lambda x: x[1], reverse=True)[:5]
    
    text = f"⏰ <b>GIỜ HOẠT ĐỘNG NHẤT</b>\n\n"
    text += f"🔥 <b>Top 5 giờ peak:</b>\n\n"
    
    for hour, count in sorted_hours:
        text += f"🕐 <b>{hour}:00</b> - {count} tin nhắn\n"
    
    await update.effective_message.reply_html(text)

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


async def nhapcode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Nhập code newbie - Nhận 100.000 xu"""
    user = update.effective_user
    
    if not context.args:
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
                "❌ Cách dùng: `/nhapcode [code]`"
            )
        return
    
    code = " ".join(context.args)
    newbie_code = "tanthunewbie"
    codes_used = get_codes_used(user.id)
    
    if code == newbie_code:
        if "newbie" in codes_used:
            await update.effective_message.reply_html(
                f"⚠️ <b>Lỗi!</b>\n\nBạn đã nhập code tân thủ rồi!"
            )
            return
        
        current_xu = get_user_xu(user.id)
        new_xu = current_xu + 100000
        set_user_xu(user.id, new_xu)
        add_code_used(user.id, "newbie")
        
        await update.effective_message.reply_html(
            f"✅ <b>CHÍNH XÁC!</b>\n\n"
            f"🎉 {user.mention_html()} nhập code thành công!\n"
            f"💝 Nhận: <b>+100,000 XU</b>\n"
            f"💰 XU hiện tại: <b>{new_xu:,}</b>"
        )
    else:
        await update.effective_message.reply_html(
            f"❌ <b>Bạn Nhập Sai!</b>\n\n"
            f"Hãy vào Nhóm Telegram để có Code"
        )


async def diemdanh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Điểm danh hằng ngày"""
    user = update.effective_user
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Điểm danh", callback_data=f"diemdanh:{user.id}")]]
    )
    await update.effective_message.reply_html(
        f"📋 Chào {user.mention_html()}, vui lòng nhấn nút điểm danh để xác nhận.",
        reply_markup=keyboard,
    )




async def back_to_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quay lại menu help"""
    await help_command(update, context)


async def diemdanh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý điểm danh"""
    query = update.callback_query
    try:
        _, owner_id_str = query.data.split(":", 1)
        owner_id = int(owner_id_str)
    except (ValueError, AttributeError):
        await query.answer()
        return

    if query.from_user.id != owner_id:
        await query.answer(
            "⚠️ Đây là nút điểm danh của người khác!",
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

    # Help & Start commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("menuXu", menuXu_command))
    app.add_handler(CommandHandler("xume", xume_command))
    app.add_handler(CommandHandler("xumat", xumat_command))
    app.add_handler(CommandHandler("taixiu", taixiu_command))
    app.add_handler(CommandHandler("vaytien", vaytien_command))
    app.add_handler(CommandHandler("tratien", tratien_command))
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
    
    # New admin commands
    app.add_handler(CommandHandler("ghostban", ghostban_command))
    app.add_handler(CommandHandler("welcome", welcome_command))
    app.add_handler(CommandHandler("goodbye", goodbye_command))
    app.add_handler(CommandHandler("wordfilter", wordfilter_command))
    app.add_handler(CommandHandler("muteall", muteall_command))
    app.add_handler(CommandHandler("unmuteall", unmuteall_command))
    app.add_handler(CommandHandler("ticket", ticket_command))
    
    # Utility commands
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("faq", faq_command))
    app.add_handler(CommandHandler("kb", kb_command))
    app.add_handler(CommandHandler("links", links_command))
    
    # Statistics commands
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("growth", growth_command))
    app.add_handler(CommandHandler("analytics", analytics_command))
    app.add_handler(CommandHandler("peakhours", peakhours_command))
    
    app.add_handler(CommandHandler("diemdanh", diemdanh_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(help_admin_callback, pattern="^help_admin$"))
    app.add_handler(CallbackQueryHandler(help_utility_callback, pattern="^help_utility$"))
    app.add_handler(CallbackQueryHandler(help_stats_callback, pattern="^help_stats$"))
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


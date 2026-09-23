import asyncio
import logging
import sqlite3
import sys
import os
import random
from os import getenv
from aiohttp import web

from aiogram import Bot, Dispatcher, F, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- SOZLAMALAR ---
TOKEN = getenv("BOT_TOKEN", "8829743983:AAG4AjKrVc_xmeIvo7fHMARqNNCPdwBpthM")
ADMIN_ID = int(getenv("ADMIN_ID", "8923173548")) 

dp = Dispatcher()

# --- FSM (ADMIN PANEL UCHUN HOLATLAR) ---
class AddAnimeState(StatesGroup):
    waiting_for_code = State()
    waiting_for_title = State()
    waiting_for_video = State()

class AddVipAnimeState(StatesGroup):
    waiting_for_code = State()
    waiting_for_title = State()
    waiting_for_video = State()

class AddShortsState(StatesGroup):
    waiting_for_title = State()
    waiting_for_video = State()

class ChannelState(StatesGroup):
    waiting_for_channel = State()

# --- MA'LUMOTLAR BAZASI (SQLITE) ---
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # Animelar jadvali (is_vip ustuni bilan)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS animes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            title TEXT,
            file_id TEXT,
            is_vip INTEGER DEFAULT 0
        )
    """)
    
    # Shorts jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shorts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            file_id TEXT
        )
    """)
    
    # Foydalanuvchilar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            is_vip INTEGER DEFAULT 0
        )
    """)

    # Sozlamalar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    conn.commit()
    conn.close()

def add_user(user_id: int, full_name: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, full_name) VALUES (?, ?)", (user_id, full_name))
    conn.commit()
    conn.close()

def add_anime(code: str, title: str, file_id: str, is_vip: int = 0) -> bool:
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO animes (code, title, file_id, is_vip) VALUES (?, ?, ?, ?)", (code, title, file_id, is_vip))
        conn.commit()
        res = True
    except sqlite3.IntegrityError:
        res = False
    conn.close()
    return res

def add_shorts(title: str, file_id: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO shorts (title, file_id) VALUES (?, ?)", (title, file_id))
    conn.commit()
    conn.close()

def get_random_shorts():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT title, file_id FROM shorts ORDER BY RANDOM() LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return result

def get_anime_by_code(code: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT title, file_id, is_vip FROM animes WHERE code = ?", (code,))
    result = cursor.fetchone()
    conn.close()
    return result

def get_stats():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM animes WHERE is_vip = 0")
    anime_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM animes WHERE is_vip = 1")
    vip_anime_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM shorts")
    shorts_count = cursor.fetchone()[0]
    conn.close()
    return users_count, anime_count, vip_anime_count, shorts_count

def set_setting(key: str, value: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_setting(key: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

# --- MAJBURIY OBUNANI TEKSHIRISH ---
async def check_subscription(bot: Bot, user_id: int) -> bool:
    channel = get_setting("required_channel")
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            return True
        return False
    except Exception as e:
        logging.error(f"Obuna tekshirishda xatolik: {e}")
        return True

def get_sub_keyboard(channel: str):
    channel_link = channel.replace("@", "https://t.me/") if channel.startswith("@") else channel
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=channel_link)],
            [InlineKeyboardButton(text="✅ Obunani tekshirish", callback_data="check_sub")]
        ]
    )

# --- QISMLAR UCHUN RAQAMLI TUGMALAR ---
def get_anime_episodes_keyboard(total_episodes: int = 12):
    """Qismlarni 1, 2, 3, 4, 5... ko'rinishida tartib bilan chiqarish"""
    buttons = []
    row = []
    
    for ep in range(1, total_episodes + 1):
        row.append(InlineKeyboardButton(text=f"▶️ {ep}", callback_data=f"ep_{ep}"))
        if len(row) == 5:  # Bitta qatorda 5 ta raqam joylashadi
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
        
    buttons.append([
        InlineKeyboardButton(text="📥 Yuklab olish", callback_data="download_video"),
        InlineKeyboardButton(text="⭐ Saqlab qo'yish", callback_data="save_anime")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- KEYBOARDS ---
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Anime Izlash")],
        [KeyboardButton(text="👑 VIP Animelar"), KeyboardButton(text="💎 VIP Obuna")],
        [KeyboardButton(text="⚙️ Kabinet"), KeyboardButton(text="▶️ Shorts")],
        [KeyboardButton(text="📑 Qo'llanma"), KeyboardButton(text="📢 Reklama")]
    ],
    resize_keyboard=True
)

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Oddiy Anime Qo'shish"), KeyboardButton(text="👑 VIP Anime Qo'shish")],
        [KeyboardButton(text="🎬 Shorts Qo'shish"), KeyboardButton(text="⚙️ Majburiy obuna sozlamalari")],
        [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="🔙 Asosiy Menyu")]
    ],
    resize_keyboard=True
)

channel_setting_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Kanal ulash / O'zgartirish")],
        [KeyboardButton(text="❌ Obunani o'chirish")],
        [KeyboardButton(text="⬅️ Admin Menyu")]
    ],
    resize_keyboard=True
)

# --- HANDLERS ---

@dp.message(CommandStart())
async def command_start_handler(message: Message, bot: Bot) -> None:
    add_user(message.from_user.id, message.from_user.full_name)
    if not await check_subscription(bot, message.from_user.id):
        channel = get_setting("required_channel")
        await message.answer("⚠️ Botdan foydalanish uchun kanalga obuna bo'ling:", reply_markup=get_sub_keyboard(channel))
        return

    await message.answer(
        f"Assalomu alaykum, {html.bold(message.from_user.full_name)}!\n\n"
        f"AniOlam botiga xush kelibsiz! Anime kodini yuboring yoki menyudan foydalaning:",
        reply_markup=main_keyboard
    )

@dp.callback_query(F.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery, bot: Bot):
    if await check_subscription(bot, callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer("✅ Obuna tasdiqlandi!", reply_markup=main_keyboard)
    else:
        await callback.answer("❌ Siz hali kanalga obuna bo'lmadingiz!", show_alert=True)

# --- ADMIN PANEL ---

@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("🛠 Admin panelga xush kelibsiz!", reply_markup=admin_keyboard)
    else:
        await message.answer("❌ Siz admin emassiz!")

@dp.message(F.text == "🔙 Asosiy Menyu")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Asosiy menyuga qaytdingiz:", reply_markup=main_keyboard)

@dp.message(F.text == "⬅️ Admin Menyu")
async def back_to_admin(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Admin menyuga qaytdingiz:", reply_markup=admin_keyboard)

@dp.message(F.text == "📊 Statistika")
async def stats_handler(message: Message):
    if message.from_user.id == ADMIN_ID:
        users, animes, vips, shorts = get_stats()
        channel = get_setting("required_channel") or "Ulanmagan"
        await message.answer(
            f"📊 **Bot Statistikasi:**\n\n"
            f"👤 Foydalanuvchilar: {users} ta\n"
            f"🎬 Oddiy animelar: {animes} ta\n"
            f"👑 VIP animelar: {vips} ta\n"
            f"▶️ Shorts videolar: {shorts} ta\n"
            f"📢 Majburiy kanal: {channel}"
        )

# --- ODDIY ANIME QO'SHISH ---
@dp.message(F.text == "➕ Oddiy Anime Qo'shish")
async def start_add_anime(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await state.set_state(AddAnimeState.waiting_for_code)
        await message.answer("Yangi anime uchun **KOD** kiriting (masalan: `101`):", reply_markup=ReplyKeyboardRemove())

@dp.message(AddAnimeState.waiting_for_code)
async def process_code(message: Message, state: FSMContext):
    await state.update_data(code=message.text.strip())
    await state.set_state(AddAnimeState.waiting_for_title)
    await message.answer("Anime **NOMINI** kiriting:")

@dp.message(AddAnimeState.waiting_for_title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddAnimeState.waiting_for_video)
    await message.answer("Anime **VIDEO FAYLINI** yuboring:")

@dp.message(AddAnimeState.waiting_for_video, F.video)
async def process_video(message: Message, state: FSMContext):
    data = await state.get_data()
    if add_anime(data['code'], data['title'], message.video.file_id, is_vip=0):
        await message.answer(f"✅ Oddiy anime saqlandi!\n\n🔑 Kod: {data['code']}\n🎬 Nomi: {data['title']}", reply_markup=admin_keyboard)
    else:
        await message.answer("❌ Xatolik: Bu kod allaqachon mavjud!", reply_markup=admin_keyboard)
    await state.clear()

# --- VIP ANIME QO'SHISH ---
@dp.message(F.text == "👑 VIP Anime Qo'shish")
async def start_add_vip_anime(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await state.set_state(AddVipAnimeState.waiting_for_code)
        await message.answer("VIP anime uchun **KOD** kiriting (masalan: `vip1`):", reply_markup=ReplyKeyboardRemove())

@dp.message(AddVipAnimeState.waiting_for_code)
async def process_vip_code(message: Message, state: FSMContext):
    await state.update_data(code=message.text.strip())
    await state.set_state(AddVipAnimeState.waiting_for_title)
    await message.answer("VIP Anime **NOMINI** kiriting:")

@dp.message(AddVipAnimeState.waiting_for_title)
async def process_vip_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddVipAnimeState.waiting_for_video)
    await message.answer("VIP Anime **VIDEO FAYLINI** yuboring:")

@dp.message(AddVipAnimeState.waiting_for_video, F.video)
async def process_vip_video(message: Message, state: FSMContext):
    data = await state.get_data()
    if add_anime(data['code'], data['title'], message.video.file_id, is_vip=1):
        await message.answer(f"👑 VIP Anime saqlandi!\n\n🔑 Kod: {data['code']}\n🎬 Nomi: {data['title']}", reply_markup=admin_keyboard)
    else:
        await message.answer("❌ Xatolik: Bu kod allaqachon mavjud!", reply_markup=admin_keyboard)
    await state.clear()

# --- SHORTS QO'SHISH ---
@dp.message(F.text == "🎬 Shorts Qo'shish")
async def start_add_shorts(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await state.set_state(AddShortsState.waiting_for_title)
        await message.answer("Shorts uchun sarlavha kiriting:", reply_markup=ReplyKeyboardRemove())

@dp.message(AddShortsState.waiting_for_title)
async def process_shorts_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddShortsState.waiting_for_video)
    await message.answer("Shorts **VIDEO FAYLINI** yuboring:")

@dp.message(AddShortsState.waiting_for_video, F.video)
async def process_shorts_video(message: Message, state: FSMContext):
    data = await state.get_data()
    add_shorts(data['title'], message.video.file_id)
    await message.answer("✅ Shorts muvaffaqiyatli saqlandi!", reply_markup=admin_keyboard)
    await state.clear()

# --- MAJBURIY OBUNA SOZLAMALARI ---
@dp.message(F.text == "⚙️ Majburiy obuna sozlamalari")
async def sub_settings_handler(message: Message):
    if message.from_user.id == ADMIN_ID:
        channel = get_setting("required_channel")
        status = f"Hozirgi kanal: {channel}" if channel else "Hozircha majburiy obuna kanali o'rnatilmagan."
        await message.answer(f"⚙️ **Majburiy obuna sozlamalari**\n\n{status}", reply_markup=channel_setting_keyboard)

@dp.message(F.text == "➕ Kanal ulash / O'zgartirish")
async def add_channel_start(message: Message, state: FSMContext):
    if message.from_user.id == ADMIN_ID:
        await state.set_state(ChannelState.waiting_for_channel)
        await message.answer("📢 Kanal username-ini kiriting (`@kanalim_uz`):", reply_markup=ReplyKeyboardRemove())

@dp.message(ChannelState.waiting_for_channel)
async def process_channel_input(message: Message, state: FSMContext):
    channel = message.text.strip()
    if not channel.startswith("@"):
        await message.answer("❌ Kanal username-i `@` belgisi bilan boshlanishi kerak!")
        return
    set_setting("required_channel", channel)
    await state.clear()
    await message.answer(f"✅ Kanal `{channel}` ga o'zgartirildi!", reply_markup=channel_setting_keyboard)

@dp.message(F.text == "❌ Obunani o'chirish")
async def remove_channel_handler(message: Message):
    if message.from_user.id == ADMIN_ID:
        set_setting("required_channel", "")
        await message.answer("✅ Majburiy obuna o'chirildi!", reply_markup=channel_setting_keyboard)

# --- FOYDALANUVCHI BO'LIMLARI ---

@dp.message(F.text == "▶️ Shorts")
async def user_shorts_handler(message: Message, bot: Bot):
    if not await check_subscription(bot, message.from_user.id):
        channel = get_setting("required_channel")
        await message.answer("⚠️ Botdan foydalanish uchun kanalga obuna bo'ling:", reply_markup=get_sub_keyboard(channel))
        return
    
    shorts = get_random_shorts()
    if shorts:
        title, file_id = shorts
        await message.answer_video(video=file_id, caption=f"🎬 <b>{title}</b>\n\nYana ko'rish uchun ▶️ Shorts tugmasini bosing!")
    else:
        await message.answer("🎬 Hozircha hech qanday Shorts video qo'shilmagan.")

@dp.message(F.text == "🔍 Anime Izlash")
async def anime_search_handler(message: Message, bot: Bot):
    if not await check_subscription(bot, message.from_user.id):
        channel = get_setting("required_channel")
        await message.answer("⚠️ Botdan foydalanish uchun kanalga obuna bo'ling:", reply_markup=get_sub_keyboard(channel))
        return
    await message.answer("🔎 Anime kodini kiriting (Masalan: `101`):")

@dp.message(F.text == "👑 VIP Animelar")
async def vip_anime_info(message: Message):
    await message.answer("👑 VIP Animelarni tomosha qilish uchun VIP kodingiz bo'lishi kerak. VIP obunani sotib olish uchun '💎 VIP Obuna' bo'limiga o'ting.")

@dp.message(F.text == "💎 VIP Obuna")
async def vip_sub_handler(message: Message):
    await message.answer("💳 VIP obuna xarid qilish uchun adminga murojaat qiling:\n\n👨‍💻 Admin: @admin_username")

@dp.message(F.text == "⚙️ Kabinet")
async def cabinet_handler(message: Message):
    await message.answer(f"👤 **Shaxsiy Kabinet:**\n\n🆔 ID: `{message.from_user.id}`\n👤 Ism: {message.from_user.full_name}\n💎 VIP status: Faol emas")

@dp.message(F.text == "📑 Qo'llanma")
async def guide_handler(message: Message):
    await message.answer("📖 Botdan foydalanish usuli:\n\n1. Anime kodini botga yuboring.\n2. Pastida chiqqan 1, 2, 3... raqamli tugmalarni bosib kerakli qismni ko'ring.")

@dp.message(F.text == "📢 Reklama")
async def ad_handler(message: Message):
    await message.answer("📢 Reklama va hamkorlik uchun adminga bog'laning.")

# --- INLINE TUGMALAR ISHLOVCHI (QISMLAR UCHUN) ---
@dp.callback_query(F.data.startswith("ep_"))
async def episode_callback_handler(callback: CallbackQuery):
    ep = callback.data.split("_")[1]
    await callback.answer(f"Siz {ep}-qismni tanladingiz!")

@dp.callback_query(F.data == "download_video")
async def download_callback_handler(callback: CallbackQuery):
    await callback.answer("Video yuklab olish havolasi tayyorlanmoqda...", show_alert=True)

@dp.callback_query(F.data == "save_anime")
async def save_callback_handler(callback: CallbackQuery):
    await callback.answer("Anime tanlanganlarga saqlandi! ⭐", show_alert=True)

# --- KOD BO'YICHA QIDIRUV ---
@dp.message()
async def search_anime_handler(message: Message, bot: Bot):
    if not await check_subscription(bot, message.from_user.id):
        channel = get_setting("required_channel")
        await message.answer("⚠️ Botdan foydalanish uchun kanalga obuna bo'ling:", reply_markup=get_sub_keyboard(channel))
        return

    code = message.text.strip()
    anime = get_anime_by_code(code)
    
    if anime:
        title, file_id, is_vip = anime
        if is_vip and message.from_user.id != ADMIN_ID:
            await message.answer("👑 Ushbu anime **VIP** kontent hisoblanadi! Tomosha qilish uchun **VIP Obuna** xarid qiling.")
            return

        caption = f"🎬 <b>{title}</b>\n\n🔑 Kod: <code>{code}</code>\n\n👇 <i>Kerakli qismni tanlang:</i>"
        if file_id:
            await message.answer_video(video=file_id, caption=caption, reply_markup=get_anime_episodes_keyboard(12))
        else:
            await message.answer(caption, reply_markup=get_anime_episodes_keyboard(12))
    else:
        await message.answer("❌ **Afsuski, bu kod bilan hech narsa topilmadi.**")

# --- RENDER UCHUN SOXTA VEB-SERVER FUNKSIYASI ---
async def handle(request):
    return web.Response(text="Bot muvaffaqiyatli ishlayapti!")

# --- ISHGA TUSHIRISH ---
async def main() -> None:
    init_db()
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    # Render portini tinglash
    port = int(os.environ.get("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
    
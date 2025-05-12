# StudyShareBot: Толық жұмыс істейтін нұсқа
import asyncio
import logging
import logging.config
import os
import re
import json
import sys
import configparser
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
    InlineKeyboardButton
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.utils.markdown import hlink, hbold, hcode
from aiogram.client.default import DefaultBotProperties

# Google Drive интеграциясы
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2 import service_account

    GOOGLE_DRIVE_ENABLED = True
except ImportError:
    GOOGLE_DRIVE_ENABLED = False
    logging.warning("Google Drive модульдері табылмады. Drive функциялары ажыратылған.")

# Logging конфигурациясы
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'},
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.FileHandler',
            'filename': 'bot.log',
            'encoding': 'utf8'
        },
        'console': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
        }
    },
    'loggers': {
        '': {
            'handlers': ['default', 'console'],
            'level': 'INFO',
            'propagate': True
        }
    }
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# Базалық директориялар
BASE_DIR = Path(__file__).parent
FILES_DIR = BASE_DIR / "files"
CONFIG_FILE = BASE_DIR / "config.ini"
STATS_FILE = BASE_DIR / "user_stats.json"


# Конфигурацияны жүктеу
def load_config():
    config_parser = configparser.ConfigParser()  # config -> config_parser

    if not CONFIG_FILE.exists():
        config_parser['Bot'] = {
            'TOKEN': os.getenv('TELEGRAM_BOT_TOKEN', "7973575924:AAEZ9gb6o8qk8NfpqVfoaTomDnaEBo6oAr0"),
            # Токенді осы жерге қойыңыз
            'ADMIN_IDS': '123456789'  # Администратор ID
        }
        config_parser['Files'] = {
            'MAX_FILE_SIZE': '52428800',  # 50MB
            'ALLOWED_EXTENSIONS': '.pdf,.docx,.jpg,.jpeg,.png,.txt,.zip,.rar,.pptx,.xls,.xlsx'
        }
        config_parser['General'] = {
            'UNIVERSITY_SITE': 'https://htu.edu.kz',
            'CATEGORIES': 'Математика,Физика,Бағдарламалау,Диплом жұмыстары,Информатика,IT,Ағылшын тілі,Тарих'
        }
        config_parser['Webhook'] = {  # Егер webhook қолдансаңыз
            'HOST': '',  # Мысалы: https://yourdomain.com
            'PORT': '8443',
            'LISTEN': '0.0.0.0'
        }

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            config_parser.write(f)
        logger.info(f"Жаңа конфигурация файлы жасалды: {CONFIG_FILE}")
    else:
        config_parser.read(CONFIG_FILE, encoding='utf-8')

    # Конфигурациядан оқу кезінде қателерді болдырмау үшін get fallback мәндерін қолдану
    return {
        'token': config_parser.get('Bot', 'TOKEN', fallback="YOUR_TELEGRAM_BOT_TOKEN"),
        'admin_ids': list(map(int, config_parser.get('Bot', 'ADMIN_IDS', fallback="").split(','))) if config_parser.get(
            'Bot', 'ADMIN_IDS', fallback="") else [],
        'max_file_size': config_parser.getint('Files', 'MAX_FILE_SIZE', fallback=52428800),
        'allowed_extensions': config_parser.get('Files', 'ALLOWED_EXTENSIONS', fallback='.pdf,.docx').split(','),
        'university_site': config_parser.get('General', 'UNIVERSITY_SITE', fallback=""),
        'categories': [cat.strip() for cat in config_parser.get('General', 'CATEGORIES', fallback="Жалпы").split(',') if
                       cat.strip()],
        'webhook_host': config_parser.get('Webhook', 'HOST', fallback=""),
        'webhook_port': config_parser.getint('Webhook', 'PORT', fallback=8443),
        'webhook_listen': config_parser.get('Webhook', 'LISTEN', fallback="0.0.0.0")
    }


# Глобалды айнымалылар
config = load_config()
TOKEN = config['token']
UNIVERSITY_SITE = config['university_site']
CATEGORIES = config['categories']
ADMIN_IDS = config['admin_ids']
MAX_FILE_SIZE = config['max_file_size']
ALLOWED_EXTENSIONS = config['allowed_extensions']
# AUTHORIZED_USERS тізімін конфигурациядан немесе басқа жолмен басқаруға болады
AUTHORIZED_USERS = ADMIN_IDS[:]  # Мысалы, бастапқыда тек админдер рұқсат етілген


# FSM Күйлері
class UploadState(StatesGroup):
    choosing_category = State()
    waiting_for_file = State()


class SearchState(StatesGroup):
    waiting_for_query = State()


class AddCategoryState(StatesGroup):
    waiting_for_name = State()


# Bot және Dispatcher
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# Пайдаланушы авторизациясы
def is_authorized(user_id: int) -> bool:
    return user_id in AUTHORIZED_USERS or user_id in ADMIN_IDS


# Google Drive функциялары (өзгеріссіз)
def get_drive_service():
    if not GOOGLE_DRIVE_ENABLED:
        return None
    credentials_file = BASE_DIR / 'service_account.json'
    if not credentials_file.exists():
        logger.warning(f"Google Drive credentials файлы табылмады: {credentials_file}")
        return None
    try:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=['https://www.googleapis.com/auth/drive'])
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        logger.error(f"Google Drive қызметін қосу кезінде қате: {e}")
        return None


def upload_to_drive(file_path: str, category: str) -> Optional[str]:
    service = get_drive_service()
    if not service: return None
    try:
        results = service.files().list(q=f"name='{category}' and mimeType='application/vnd.google-apps.folder'",
                                       spaces='drive').execute()
        if not results.get('files'):
            folder_metadata = {'name': category, 'mimeType': 'application/vnd.google-apps.folder'}
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder.get('id')
        else:
            folder_id = results.get('files')[0].get('id')
        file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
        media = MediaFileUpload(file_path)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        logger.error(f"Google Drive-ға жүктеу қатесі: {e}")
        return None


# Статистика функциялары (өзгеріссіз)
def load_stats() -> Dict[str, Dict[str, Any]]:
    try:
        if not STATS_FILE.exists(): return defaultdict(
            lambda: {"username": "", "files_uploaded": 0, "last_activity": ""})
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return defaultdict(lambda: {"username": "", "files_uploaded": 0, "last_activity": ""}, json.load(f))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Статистиканы жүктеу қатесі: {e}")
        return defaultdict(lambda: {"username": "", "files_uploaded": 0, "last_activity": ""})


def save_stats(stats: Dict[str, Dict[str, Any]]):
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Статистиканы сақтау қатесі: {e}")


def update_user_stats(user: types.User):
    stats = load_stats()
    user_id_str = str(user.id)
    current_uploads = stats.get(user_id_str, {}).get("files_uploaded", 0)
    stats[user_id_str] = {
        "username": user.username or f"User_{user.id}",
        "files_uploaded": current_uploads + 1,
        "last_activity": datetime.now().isoformat()
    }
    save_stats(stats)


# Батырмалар Менюсі
def main_menu_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📤 Файл жүктеу"), KeyboardButton(text="📋 Файлдар тізімі"))
    builder.row(KeyboardButton(text="🔍 Файлдарды іздеу"), KeyboardButton(text="📊 Статистика"))
    builder.row(KeyboardButton(text="ℹ️ Көмек"))
    return builder.as_markup(resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="❌ Болдырмау"))
    return builder.as_markup(resize_keyboard=True)


def get_pagination_keyboard(category_idx: int, current_page: int, total_pages: int, files_on_page: List[Path],
                            callback_action_prefix: str = "page_list") -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    for i, file in enumerate(files_on_page):
        # МАҢЫЗДЫ: file.name тым ұзын болса, callback_data шектен асуы мүмкін.
        # Қажет болса, файл атын қысқарту немесе файлдың индексін қолдану керек.
        file_display_name = file.name[:30] + '...' if len(file.name) > 30 else file.name
        builder.button(
            text=f"⬇️ {file_display_name}",
            callback_data=f"download_{category_idx}_{file.name}"  # file.name тікелей қолданылады
        )
    builder.adjust(1)  # Әр файлды бір қатарға

    pagination_row = []
    if current_page > 1:
        pagination_row.append(InlineKeyboardButton(text="⬅️",
                                                   callback_data=f"{callback_action_prefix}_{category_idx}_{current_page - 1}"))
    pagination_row.append(
        InlineKeyboardButton(text=f"{current_page}/{total_pages}", callback_data="noop"))  # no operation
    if current_page < total_pages:
        pagination_row.append(InlineKeyboardButton(text="➡️",
                                                   callback_data=f"{callback_action_prefix}_{category_idx}_{current_page + 1}"))

    if pagination_row:  # Егер пагинация батырмалары болса ғана қосу
        builder.row(*pagination_row)

    builder.row(InlineKeyboardButton(text="🔙 Категорияларға оралу", callback_data="show_categories_list"))
    return builder


# Старт хендлері
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        await message.answer("Кешіріңіз, сіз бұл ботты қолдану құқығына ие емессіз.")
        return
    await state.clear()
    site_link_text = f"\n🏫 Университет сайты: {hlink('ХТУ', UNIVERSITY_SITE)}" if UNIVERSITY_SITE else ""
    await message.answer(
        f"📚 {hbold('StudyShareBot-қа қош келдіңіз!')}\n"
        f"Төмендегі батырмалар арқылы қажетті әрекетті таңдаңыз:{site_link_text}",
        reply_markup=main_menu_keyboard()
    )


# Негізгі мәзірге оралу хэндлері
@dp.callback_query(F.data == "back_to_main_menu")
async def handle_back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # Күйді тазалау маңызды
    site_link_text = f"\n🏫 Университет сайты: {hlink('ХТУ', UNIVERSITY_SITE)}" if UNIVERSITY_SITE else ""
    await callback.message.edit_text(  # edit_text немесе answer (егер алдыңғы reply_markup болмаса)
        f"📚 {hbold('StudyShareBot-қа қош келдіңіз!')}\n"
        f"Төмендегі батырмалар арқылы қажетті әрекетті таңдаңыз:{site_link_text}",
        reply_markup=main_menu_keyboard()
        # Бұл жерде reply_markup-ты edit_text-ке беру мүмкін емес, жаңа хабарлама жіберу керек немесе inline keyboard-ты өзгерту керек.
        # Қарапайымдылық үшін, егер inline батырмадан шақырылса, мәтінді өзгертіп, reply_markup-сыз қалдырамыз.
        # Немесе жаңа хабарлама жібереміз.
    )
    # edit_text reply_markup-ты өзгерте алмайды, сондықтан жаңа хабарлама жіберген дұрыс:
    await callback.message.answer(
        "Негізгі мәзірге оралдыңыз.",
        reply_markup=main_menu_keyboard()
    )
    if callback.message.from_user.id == bot.id:  # Check if the message to edit is from the bot
        await callback.message.delete()  # Optionally delete the inline keyboard message
    await callback.answer()


# Файл жүктеу процесі
@dp.message(F.text == "📤 Файл жүктеу")
@dp.message(Command("upload"))
async def upload_start_cmd(message: Message, state: FSMContext):  # upload_start -> upload_start_cmd
    if not is_authorized(message.from_user.id): return
    builder = InlineKeyboardBuilder()
    for i, cat_name in enumerate(CATEGORIES):
        builder.button(text=cat_name, callback_data=f"category_idx_{i}")
    builder.adjust(2)
    await message.answer("📂 Файлды қай категорияға жүктегіңіз келеді?", reply_markup=builder.as_markup())
    await state.set_state(UploadState.choosing_category)


@dp.callback_query(UploadState.choosing_category, F.data.startswith("category_idx_"))
async def category_chosen(callback: CallbackQuery, state: FSMContext):
    try:
        category_index = int(callback.data.split("_", 2)[2])
        if not (0 <= category_index < len(CATEGORIES)):
            await callback.answer("⚠️ Жарамсыз категория индексі!", show_alert=True)
            return
        selected_category = CATEGORIES[category_index]
    except (IndexError, ValueError):
        await callback.answer("⚠️ Категорияны таңдауда қате!", show_alert=True)
        return

    await state.update_data(chosen_category_name=selected_category, chosen_category_idx=category_index)
    await callback.message.edit_text(
        f"📁 <b>{selected_category}</b> категориясы таңдалды.\n"
        f"Енді осы категорияға тиісті файлды жіберіңіз ({', '.join(ALLOWED_EXTENSIONS)})."
    )
    # Файлды күту туралы хабарламаны бөлек жібереміз, cancel_keyboard-мен бірге
    await callback.message.answer("Файлды күтудемін:", reply_markup=cancel_keyboard())
    await callback.answer()
    await state.set_state(UploadState.waiting_for_file)


@dp.message(UploadState.waiting_for_file, F.document | F.photo)
async def handle_file(message: Message, state: FSMContext):
    user_data = await state.get_data()
    category_name = user_data.get('chosen_category_name')
    category_idx = user_data.get('chosen_category_idx')

    if category_name is None or category_idx is None:
        await message.reply("⚠️ Қателік: Категория анықталмады. /upload командасын қайталаңыз",
                            reply_markup=main_menu_keyboard())
        await state.clear()
        return

    file_info = message.document or message.photo[-1]
    file_name_original = message.document.file_name if message.document else f"photo_{file_info.file_unique_id}.jpg"
    file_name = re.sub(r'[^\w\.\-\[\]\(\)]+', '_', file_name_original)  # Рұқсат етілген символдарды кеңейту

    if file_info.file_size > MAX_FILE_SIZE:
        await message.reply(f"❌ Файл өлшемі тым үлкен (максимум {MAX_FILE_SIZE // 1024 // 1024}MB)",
                            reply_markup=main_menu_keyboard())
        await state.clear()
        return

    file_ext = os.path.splitext(file_name)[1].lower()
    if not ALLOWED_EXTENSIONS or (
            file_ext not in ALLOWED_EXTENSIONS and ALLOWED_EXTENSIONS[0] != '*'):  # '*' барлығын рұқсат етеді
        await message.reply(
            f"❌ Рұқсат етілмеген файл түрі: {file_ext}. Рұқсат етілгендер: {', '.join(ALLOWED_EXTENSIONS)}",
            reply_markup=main_menu_keyboard())
        await state.clear()
        return

    save_dir = FILES_DIR / category_name
    save_dir.mkdir(exist_ok=True, parents=True)
    file_path = save_dir / file_name

    counter = 0
    temp_file_name = file_name
    while file_path.exists():  # Егер файл аты бұрыннан бар болса, _1, _2 қосу
        counter += 1
        name, ext = os.path.splitext(file_name)
        temp_file_name = f"{name}_{counter}{ext}"
        file_path = save_dir / temp_file_name
    file_name = temp_file_name  # Жаңартылған файл атын қолдану

    try:
        await bot.download(file_info, destination=str(file_path))
        drive_file_id = None
        if GOOGLE_DRIVE_ENABLED:
            drive_file_id = upload_to_drive(str(file_path), category_name)

        success_msg = f"✅ Файл <code>{file_name}</code> <b>{category_name}</b> категориясына жүктелді!"
        if drive_file_id:
            success_msg += f"\n✅ Google Drive-ға сақталды (ID: {drive_file_id})"

        update_user_stats(message.from_user)
        await message.reply(success_msg, reply_markup=main_menu_keyboard())
    except Exception as e:
        logger.error(f"Файлды сақтау қатесі ({file_name}): {e}")
        await message.reply(f"❌ Файлды сақтау кезінде қате пайда болды: {str(e)}", reply_markup=main_menu_keyboard())
    finally:
        await state.clear()


# Файлдар тізімін көрсету
@dp.message(F.text == "📋 Файлдар тізімі")
@dp.message(Command("list"))
async def show_categories_for_listing(message: Message):  # show_categories -> show_categories_for_listing
    if not is_authorized(message.from_user.id): return
    builder = InlineKeyboardBuilder()
    if not CATEGORIES:
        await message.answer("ℹ️ Категориялар әлі қосылмаған.")
        return
    for i, cat_name in enumerate(CATEGORIES):
        builder.button(text=cat_name, callback_data=f"list_idx_{i}")
    builder.adjust(2)
    await message.answer("📁 Қай категориядағы файлдарды көргіңіз келеді?", reply_markup=builder.as_markup())


@dp.callback_query(F.data == "show_categories_list")  # "Категорияларға оралу" батырмасы үшін
async def handle_back_to_categories_list(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    if not CATEGORIES:
        await callback.message.edit_text("ℹ️ Категориялар әлі қосылмаған.")
        await callback.answer()
        return
    for i, cat_name in enumerate(CATEGORIES):
        builder.button(text=cat_name, callback_data=f"list_idx_{i}")
    builder.adjust(2)
    await callback.message.edit_text("📁 Қай категориядағы файлдарды көргіңіз келеді?", reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("list_idx_"))
async def list_files_in_category(callback: CallbackQuery):  # list_files -> list_files_in_category
    try:
        category_idx = int(callback.data.split("_", 2)[2])
        if not (0 <= category_idx < len(CATEGORIES)):
            await callback.answer("⚠️ Жарамсыз категория!", show_alert=True)
            return
        category_name = CATEGORIES[category_idx]
    except (IndexError, ValueError):
        await callback.answer("⚠️ Категорияны таңдауда қате!", show_alert=True)
        return

    category_dir = FILES_DIR / category_name
    if not category_dir.exists() or not any(category_dir.iterdir()):
        await callback.message.edit_text(f"📂 <b>{category_name}</b> категориясы бос немесе файлдар жоқ.")
        await callback.answer()
        return

    files_in_dir = sorted([f for f in category_dir.iterdir() if f.is_file()])
    if not files_in_dir:
        await callback.message.edit_text(f"📂 <b>{category_name}</b> категориясында файлдар жоқ.")
        await callback.answer()
        return

    PAGE_SIZE = 5
    total_pages = (len(files_in_dir) + PAGE_SIZE - 1) // PAGE_SIZE
    current_page_files = files_in_dir[:PAGE_SIZE]

    files_text = "\n".join([f"{i + 1}. <code>{file.name}</code>" for i, file in enumerate(current_page_files)])
    await callback.message.edit_text(
        f"📂 <b>{category_name}</b> ({1}/{total_pages}):\n{files_text}",
        reply_markup=get_pagination_keyboard(category_idx, 1, total_pages, current_page_files).as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("page_list_"))
async def show_page_files(callback: CallbackQuery):  # show_page -> show_page_files
    try:
        parts = callback.data.split("_")  # page_list_CATEGORYIDX_PAGE
        category_idx = int(parts[2])
        page = int(parts[3])
        if not (0 <= category_idx < len(CATEGORIES)):
            await callback.answer("⚠️ Жарамсыз категория!", show_alert=True)
            return
        category_name = CATEGORIES[category_idx]
    except (IndexError, ValueError):
        await callback.answer("⚠️ Бет нөмірінде немесе категорияда қате!", show_alert=True)
        return

    category_dir = FILES_DIR / category_name
    if not category_dir.exists():  # Бұл тексеру қажет болмауы мүмкін, егер алдыңғы шақыруда болса
        await callback.answer(f"❌ {category_name} категориясы табылмады.", show_alert=True)
        return

    files_in_dir = sorted([f for f in category_dir.iterdir() if f.is_file()])
    PAGE_SIZE = 5
    total_pages = (len(files_in_dir) + PAGE_SIZE - 1) // PAGE_SIZE

    if not (1 <= page <= total_pages):
        await callback.answer("⚠️ Жарамсыз бет нөмірі.", show_alert=True)
        return

    start_idx = (page - 1) * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, len(files_in_dir))
    current_page_files = files_in_dir[start_idx:end_idx]

    files_text = "\n".join(
        [f"{i + 1 + start_idx}. <code>{file.name}</code>" for i, file in enumerate(current_page_files)])
    await callback.message.edit_text(
        f"📂 <b>{category_name}</b> ({page}/{total_pages}):\n{files_text}",
        reply_markup=get_pagination_keyboard(category_idx, page, total_pages, current_page_files).as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("download_"))
async def download_file_cmd(callback: CallbackQuery):  # download_file -> download_file_cmd
    try:
        # download_CATEGORYIDX_FILENAME
        parts = callback.data.split("_", 2)
        category_idx = int(parts[1])
        file_name = parts[2]  # Файл атында '_' болуы мүмкін, сондықтан қалғанының бәрі файл аты

        if not (0 <= category_idx < len(CATEGORIES)):
            await callback.answer("⚠️ Жарамсыз категория!", show_alert=True)
            return
        category_name = CATEGORIES[category_idx]
    except (IndexError, ValueError) as e:
        logger.error(f"Download callback_data parsing error: {callback.data}, error: {e}")
        await callback.answer("❌ Файл идентификаторы дұрыс емес форматта.", show_alert=True)
        return

    file_path = FILES_DIR / category_name / file_name
    if not file_path.exists() or not file_path.is_file():
        logger.warning(f"Download attempt for non-existent file: {file_path}")
        await callback.answer("❌ Файл табылмады.", show_alert=True)
        return

    try:
        await callback.message.answer_document(
            FSInputFile(file_path),
            caption=f"📁 Категория: {category_name}\n📄 Файл: {file_name}"
        )
    except Exception as e:
        logger.error(f"Файлды жіберу қатесі ({file_path}): {e}")
        await callback.message.answer(
            "❌ Файлды жіберу кезінде қате пайда болды. Файл тым үлкен немесе басқа мәселе болуы мүмкін.")
    finally:
        await callback.answer()


# Файлдарды іздеу
@dp.message(F.text == "🔍 Файлдарды іздеу")
@dp.message(Command("search"))
async def search_start_cmd(message: Message, state: FSMContext):  # search_start -> search_start_cmd
    if not is_authorized(message.from_user.id): return
    await message.answer("🔍 Іздеу сөзін енгізіңіз:", reply_markup=cancel_keyboard())
    await state.set_state(SearchState.waiting_for_query)


@dp.message(SearchState.waiting_for_query, F.text)
async def perform_search_cmd(message: Message, state: FSMContext):  # perform_search -> perform_search_cmd
    query = message.text.lower().strip()
    await state.clear()

    if len(query) < 3:
        await message.answer("⚠️ Іздеу үшін кем дегенде 3 таңба енгізіңіз.", reply_markup=main_menu_keyboard())
        return

    results = []  # [(category_idx, category_name, file_name), ...]
    for idx, cat_name in enumerate(CATEGORIES):
        category_dir = FILES_DIR / cat_name
        if category_dir.exists() and category_dir.is_dir():
            for file_path_obj in category_dir.iterdir():
                if file_path_obj.is_file():
                    # Іздеу логикасын жақсартуға болады (мысалы, сөздер бойынша)
                    if query in file_path_obj.name.lower() or query in cat_name.lower():
                        results.append((idx, cat_name, file_path_obj.name))

    if not results:
        await message.answer(f"🔍 '{query}' бойынша нәтиже табылмады.", reply_markup=main_menu_keyboard())
        return

    # TODO: Іздеу нәтижелерін беттерге бөлу (pagination)
    results_to_show = results[:10]  # Алғашқы 10 нәтиже

    builder = InlineKeyboardBuilder()
    text_parts = [f"🔍 '{query}' бойынша табылған нәтижелер ({len(results)}). Көрсетілгені: {len(results_to_show)}:"]

    for i, (cat_idx, cat_name_res, file_name_res) in enumerate(results_to_show):
        text_parts.append(f"{i + 1}. <b>{cat_name_res}</b>: <code>{file_name_res}</code>")
        # callback_data ұзындығын тексеру маңызды!
        callback_data_str = f"download_{cat_idx}_{file_name_res}"
        if len(callback_data_str.encode('utf-8')) < 64:
            builder.button(text=f"⬇️ {i + 1}. {file_name_res[:20]}", callback_data=callback_data_str)
        else:
            logger.warning(f"Search result callback_data too long, skipping button: {callback_data_str}")
            # Тым ұзын болса батырманы қоспауға болады немесе басқа әрекет
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Негізгі мәзір", callback_data="back_to_main_menu"))

    await message.answer("\n".join(text_parts), reply_markup=builder.as_markup())


# Статистика
@dp.message(F.text == "📊 Статистика")
@dp.message(Command("stats"))
async def show_stats_cmd(message: Message):  # show_stats -> show_stats_cmd
    if not is_authorized(message.from_user.id): return
    stats = load_stats()
    user_id_str = str(message.from_user.id)
    if user_id_str in stats and stats[user_id_str].get("files_uploaded", 0) > 0:
        user_s = stats[user_id_str]
        await message.answer(
            f"📊 <b>Жеке статистика:</b>\n"
            f"👤 Пайдаланушы: {user_s.get('username', 'N/A')}\n"
            f"📤 Жүктелген файлдар: {user_s.get('files_uploaded', 0)}\n"
            f"📅 Соңғы белсенділік: {user_s.get('last_activity', 'N/A')}"
        )
    else:
        await message.answer("📊 Сіз әлі файл жүктемегенсіз немесе статистикаңыз жоқ.")


@dp.message(Command("allstats"))  # Әкімшілер үшін
async def show_all_stats_cmd(message: Message):  # show_all_stats -> show_all_stats_cmd
    if message.from_user.id not in ADMIN_IDS: return
    stats = load_stats()
    if not stats:
        await message.answer("📊 Статистика әлі жиналмаған.")
        return

    # Файл жүктеген пайдаланушыларды ғана сұрыптау
    valid_stats = {uid: udata for uid, udata in stats.items() if udata.get("files_uploaded", 0) > 0}
    if not valid_stats:
        await message.answer("📊 Файл жүктеген пайдаланушылар әлі жоқ.")
        return

    sorted_stats = sorted(valid_stats.items(), key=lambda x: x[1].get('files_uploaded', 0), reverse=True)[:10]
    reply_text = "📊 <b>Жалпы статистика (Топ-10 белсенді):</b>\n\n"
    for i, (user_id, user_s) in enumerate(sorted_stats, 1):
        reply_text += (
            f"{i}. 👤 {user_s.get('username', f'User_{user_id}')}\n"
            f"   📤 Жүктелген файлдар: {user_s.get('files_uploaded', 0)}\n"
            f"   📅 Соңғы белсенділік: {user_s.get('last_activity', 'N/A')}\n\n"
        )
    total_users_with_uploads = len(valid_stats)
    total_uploads = sum(user.get('files_uploaded', 0) for user in valid_stats.values())
    reply_text += (
        f"👥 <b>Файл жүктеген пайдаланушылар:</b> {total_users_with_uploads}\n"
        f"📦 <b>Жалпы жүктемелер:</b> {total_uploads}"
    )
    await message.answer(reply_text)


# Файлды жою (әкімшілер үшін)
@dp.message(Command("delete"))
async def delete_file_cmd(message: Message):  # delete_file -> delete_file_cmd
    if message.from_user.id not in ADMIN_IDS: return
    try:
        # /delete "Категория аты" "файл_аты.pdf"
        # немесе /delete Индекс_категория "файл_аты.pdf"
        command_parts = message.text.split(maxsplit=1)
        if len(command_parts) < 2:
            await message.reply(
                "⚠️ Формат: /delete \"Категория аты\" \"файл_аты.pdf\" немесе /delete КатегорияИндексі \"файл_аты.pdf\"")
            return

        args_str = command_parts[1]
        # Тырмақшадағы аргументтерді бөліп алу
        match = re.match(r"(\d+)\s+\"(.+)\"|\"(.+?)\"\s+\"(.+)\"", args_str)
        if not match:
            await message.reply(
                "⚠️ Аргументтерді дұрыс форматта енгізіңіз. Мысалы: /delete \"Математика\" \"лекция.pdf\"")
            return

        category_input, file_name = "", ""
        if match.group(1):  # Индекспен берілсе
            category_idx = int(match.group(1))
            file_name = match.group(2)
            if not (0 <= category_idx < len(CATEGORIES)):
                await message.reply(f"❌ Жарамсыз категория индексі: {category_idx}")
                return
            category_name = CATEGORIES[category_idx]
        elif match.group(3):  # Атаумен берілсе
            category_name = match.group(3)
            file_name = match.group(4)
            if category_name not in CATEGORIES:
                await message.reply(f"❌ Категория табылмады: {category_name}")
                return
        else:  # Бұл жағдайға жетпеуі керек
            await message.reply("❌ Аргументтерді анықтау мүмкін болмады.")
            return


    except ValueError:
        await message.reply("⚠️ Категория индексі сан болуы керек.")
        return
    except Exception as e:
        logger.error(f"Delete command parsing error: {e}")
        await message.reply("⚠️ Команданы талдау кезінде қате.")
        return

    file_path = FILES_DIR / category_name / file_name
    if not file_path.exists() or not file_path.is_file():
        await message.reply(f"❌ Файл табылмады: {category_name}/{file_name}")
        return
    try:
        file_path.unlink()
        # TODO: Google Drive-тан жою функциясын қосу керек, егер GOOGLE_DRIVE_ENABLED болса
        # delete_from_drive(str(file_path), category_name, file_name)
        await message.reply(f"✅ Файл <code>{file_name}</code> ({category_name}) жойылды.")
    except Exception as e:
        logger.error(f"Файлды жою қатесі ({file_path}): {e}")
        await message.reply(f"❌ Файлды жою кезінде қате: {str(e)}")


# Категория қосу (әкімшілер үшін)
@dp.message(Command("addcategory"))
async def add_category_cmd_start(message: Message, state: FSMContext):  # add_category_command -> add_category_cmd_start
    if message.from_user.id not in ADMIN_IDS: return
    args = message.text.split(maxsplit=1)
    if len(args) == 2:
        await process_add_category(message, args[1].strip())
    else:
        await message.reply("📝 Жаңа категория атын енгізіңіз:", reply_markup=cancel_keyboard())
        await state.set_state(AddCategoryState.waiting_for_name)


@dp.message(AddCategoryState.waiting_for_name, F.text)
async def process_category_name_input(message: Message,
                                      state: FSMContext):  # process_category_name -> process_category_name_input
    category_name = message.text.strip()
    await state.clear()
    await process_add_category(message, category_name)


async def process_add_category(message: Message, category_name: str):  # add_category -> process_add_category
    global CATEGORIES
    if not category_name:
        await message.reply("⚠️ Категория аты бос болмауы керек.", reply_markup=main_menu_keyboard())
        return
    if category_name in CATEGORIES:
        await message.reply(f"⚠️ '{category_name}' категориясы бұрыннан бар.", reply_markup=main_menu_keyboard())
        return
    try:
        CATEGORIES.append(category_name)
        (FILES_DIR / category_name).mkdir(exist_ok=True, parents=True)

        # Конфигурация файлын жаңарту
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE, encoding='utf-8')
        if 'General' not in cfg: cfg['General'] = {}
        cfg['General']['CATEGORIES'] = ','.join(CATEGORIES)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            cfg.write(f)

        await message.reply(f"✅ <b>{category_name}</b> категориясы қосылды.", reply_markup=main_menu_keyboard())
    except Exception as e:
        logger.error(f"Категория қосу қатесі ({category_name}): {e}")
        # Қате болса, тізімнен алып тастауға тырысу (егер қосылып үлгерсе)
        if category_name in CATEGORIES: CATEGORIES.remove(category_name)
        await message.reply(f"❌ Категорияны қосу кезінде қате: {str(e)}", reply_markup=main_menu_keyboard())


# Көмек
@dp.message(F.text == "ℹ️ Көмек")
@dp.message(Command("help"))
async def show_help_cmd(message: Message):  # show_help -> show_help_cmd
    admin_help = ""
    if message.from_user.id in ADMIN_IDS:
        admin_help = (
            f"\n\n{hbold('👨‍💻 Әкімші командалары:')}\n"
            f"/allstats - Барлық статистика\n"
            f"/addcategory [аты] - Жаңа категория қосу\n"
            f"/delete \"Кат. аты\" \"Файл аты\" - Файлды жою\n"
            f"/delete Кат.Индексі \"Файл аты\" - Файлды жою\n"
        )
    help_text = (
        f"📚 {hbold('StudyShareBot Көмек')}\n\n"
        f"📤 Файл жүктеу - Оқу материалдарын жүктеу\n"
        f"📋 Файлдар тізімі - Категориялар бойынша файлдарды көру\n"
        f"🔍 Іздеу - Файлдарды аты бойынша іздеу\n"
        f"📊 Статистика - Жеке статистиканы көру\n"
        f"ℹ️ Көмек - Осы хабарлама"
        f"{admin_help}"
    )
    await message.answer(help_text, reply_markup=main_menu_keyboard())


# Болдырмау
@dp.message(F.text == "❌ Болдырмау")
@dp.message(Command("cancel"))
async def cancel_action_cmd(message: Message, state: FSMContext):  # cancel_action -> cancel_action_cmd
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        await message.answer("✅ Әрекет болдырмады.", reply_markup=main_menu_keyboard())
    else:
        await message.answer("ℹ️ Болдыратын белсенді әрекет жоқ.", reply_markup=main_menu_keyboard())


# Белгісіз командалар/хабарламалар
@dp.message()
async def handle_unknown_cmd(message: Message):  # handle_unknown -> handle_unknown_cmd
    if not is_authorized(message.from_user.id):
        await message.reply("Кешіріңіз, сізге бұл ботты пайдалануға рұқсат жоқ.")
        return
    await message.reply(
        "Түсінбедім. Қолжетімді командалар үшін /help теріңіз немесе төмендегі мәзірді пайдаланыңыз.",
        reply_markup=main_menu_keyboard()
    )


# Ботты іске қосу функциялары
async def on_startup_polling(dispatcher: Dispatcher):
    FILES_DIR.mkdir(exist_ok=True, parents=True)
    for category in CATEGORIES:
        (FILES_DIR / category).mkdir(exist_ok=True, parents=True)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot polling режимінде іске қосылды")
    logger.info(f"Категориялар: {CATEGORIES}")
    logger.info(f"Админ ID: {ADMIN_IDS}")


async def on_startup_webhook(dispatcher: Dispatcher):
    FILES_DIR.mkdir(exist_ok=True, parents=True)
    for category in CATEGORIES:
        (FILES_DIR / category).mkdir(exist_ok=True, parents=True)
    webhook_url = f"{config['webhook_host']}/webhook/{TOKEN}"
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True, allowed_updates=dp.resolve_used_update_types())
    logger.info(f"Bot webhook режимінде іске қосылды: {webhook_url}")
    logger.info(f"Категориялар: {CATEGORIES}")
    logger.info(f"Админ ID: {ADMIN_IDS}")


async def main():
    # dp.startup.register(on_startup_polling) # Polling үшін
    # await dp.start_polling(bot)

    # Webhook үшін (егер config.ini-да webhook_host көрсетілсе)
    if config['webhook_host']:
        from aiohttp import web
        dp.startup.register(on_startup_webhook)

        app = web.Application()
        # Маршрутты TOKEN арқылы емес, басқа жолмен қорғауға болады, мысалы /
        # Бірақ TOKEN-мен маршрут қарапайымдау
        webhook_path = f"/webhook/{TOKEN}"

        async def telegram_webhook_handler(request: web.Request):
            update = types.Update(**await request.json())
            await dp.feed_update(bot=bot, update=update)
            return web.Response()

        app.router.add_post(webhook_path, telegram_webhook_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=config['webhook_listen'], port=config['webhook_port'])
        await site.start()
        logger.info(f"AIOHTTP сервері іске қосылды: {config['webhook_listen']}:{config['webhook_port']}")
        await asyncio.Event().wait()  # Сервердің тоқтауын күту
    else:  # Polling режимі
        dp.startup.register(on_startup_polling)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("Telegram бот токені config.ini файлында немесе жүйелік айнымалыда көрсетілмеген!")
        sys.exit("Токен қатесі")
    if not ADMIN_IDS:
        logger.warning("Әкімші ID-лары config.ini файлында көрсетілмеген! Кейбір функциялар жұмыс істемеуі мүмкін.")

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot тоқтатылды.")
    except Exception as e:
        logger.critical(f"Күтпеген қате: {e}", exc_info=True)

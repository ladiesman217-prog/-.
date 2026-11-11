import asyncio
import ctypes
import hashlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from documents import extract_docx_text

from app import generate_topics, generation_error_message, normalize_generation_data


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
with (ROOT / "static" / "catalog.json").open(encoding="utf-8") as catalog_file:
    CATALOG = json.load(catalog_file)

PROGRAMS = CATALOG["programs"]
SUBJECT_EXAMPLES = CATALOG["studyExamples"]
PROGRAMS_PER_PAGE = 10
SUBJECTS_PER_PAGE = 7
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("topic-generator-bot")
_single_instance_lock = None


def acquire_single_instance(token: str) -> bool:
    """Prevent duplicate polling processes for the same Telegram bot token."""
    global _single_instance_lock
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:20]
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        create_mutex.restype = ctypes.c_void_p
        ctypes.set_last_error(0)
        handle = create_mutex(None, 1, f"Local\\topic-generator-bot-{fingerprint}")
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        _single_instance_lock = (kernel32, handle)
        return True

    lock_path = Path(tempfile.gettempdir()) / f"topic-generator-bot-{fingerprint}.lock"
    lock_file = lock_path.open("a+")
    try:
        import fcntl
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        lock_file.close()
        return False
    _single_instance_lock = lock_file
    return True


def program_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    start = page * PROGRAMS_PER_PAGE
    rows = []
    for index in range(start, min(start + PROGRAMS_PER_PAGE, len(PROGRAMS))):
        institute, code, name, _family = PROGRAMS[index]
        label = f"{code} — {name}"
        if len(label) > 62:
            label = label[:59].rstrip() + "…"
        rows.append([InlineKeyboardButton(label, callback_data=f"program:{index}")])

    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton("← Назад", callback_data=f"page:{page - 1}"))
    if start + PROGRAMS_PER_PAGE < len(PROGRAMS):
        navigation.append(InlineKeyboardButton("Ещё →", callback_data=f"page:{page + 1}"))
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(rows)


def level_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Курсовая работа", callback_data="level:course")],
        [InlineKeyboardButton("Дипломная работа", callback_data="level:diploma")],
        [InlineKeyboardButton("← К выбору специальности", callback_data="back:program")],
    ])


def year_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{year} курс", callback_data=f"year:{year}") for year in range(1, 5)],
        [InlineKeyboardButton("← Тип работы", callback_data="back:level")],
    ])


def subject_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    subjects = SUBJECT_EXAMPLES.get(context.user_data.get("family", ""), [])
    selected = set(context.user_data.get("selected_subjects", []))
    rows = []
    for index, subject in enumerate(subjects[:SUBJECTS_PER_PAGE]):
        prefix = "✅ " if index in selected else "＋ "
        label = prefix + subject
        if len(label) > 64:
            label = label[:61].rstrip() + "…"
        rows.append([InlineKeyboardButton(label, callback_data=f"subject:{index}")])
    rows.append([InlineKeyboardButton("Продолжить →", callback_data="subjects:done")])
    rows.append([InlineKeyboardButton("← К выбору курса", callback_data="back:year")])
    return InlineKeyboardMarkup(rows)


def topic_options_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    count = context.user_data.get("generation_count", 5)
    language = context.user_data.get("language", "ru")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(("✓ Русский" if language == "ru" else "Русский"), callback_data="language:ru"), InlineKeyboardButton(("✓ Қазақша" if language == "kk" else "Қазақша"), callback_data="language:kk")],
        [InlineKeyboardButton(("✓ " if n == count else "") + (f"{n} идей" if language == "ru" else f"{n} тақырып"), callback_data=f"count:{n}") for n in (3, 5, 8)],
        [InlineKeyboardButton("Сгенерировать по выбранным предметам", callback_data="generate")],
        [InlineKeyboardButton("Добавить свои темы", callback_data="custom")],
        [InlineKeyboardButton("← Изменить предметы", callback_data="back:subjects")],
    ])


def ready_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    count = context.user_data.get("generation_count", 5)
    language = context.user_data.get("language", "ru")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✓ Русский" if language == "ru" else "Русский", callback_data="language:ru"), InlineKeyboardButton("✓ Қазақша" if language == "kk" else "Қазақша", callback_data="language:kk")],
        [InlineKeyboardButton(("✓ " if n == count else "") + (f"{n} идей" if language == "ru" else f"{n} тақырып"), callback_data=f"count:{n}") for n in (3, 5, 8)],
        [InlineKeyboardButton("✨ Подобрать темы", callback_data="generate")],
        [InlineKeyboardButton("Изменить список тем", callback_data="custom")],
    ])


def topic_message(topic: dict, index: int, language: str = "ru") -> str:
    title = str(topic.get("title", "Тема без названия"))
    why = str(topic.get("why", ""))
    goal = str(topic.get("goal", ""))
    result = str(topic.get("result", ""))
    tasks = topic.get("tasks", [])
    if not isinstance(tasks, list):
        tasks = []
    tasks_text = "\n".join(f"• {str(task)}" for task in tasks[:5])
    if language == "kk":
        content = f"{index}. {title}\n\n{why}\n\nМақсаты: {goal}\n\nМіндеттер:\n{tasks_text}\n\nКүтілетін нәтиже: {result}"
    else:
        content = f"{index}. {title}\n\n{why}\n\nЦель: {goal}\n\nЗадачи:\n{tasks_text}\n\nОжидаемый результат: {result}"
    return content[:3900]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    context.user_data["stage"] = "program"
    await update.effective_message.reply_text(
        "Привет! Я помогу подобрать темы учебного проекта по программе и пройденным предметам.\n\n"
        "Сначала выбери специальность Жангир хана:",
        reply_markup=program_keyboard(),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.effective_message.reply_text("Выбор сброшен. Начни заново командой /start.")


async def show_programs(query, context: ContextTypes.DEFAULT_TYPE, page: int = 0) -> None:
    context.user_data["stage"] = "program"
    await query.edit_message_text(
        "Выбери специальность / образовательную программу:",
        reply_markup=program_keyboard(page),
    )


async def show_levels(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    program = context.user_data.get("program")
    if not program:
        await show_programs(query, context)
        return
    context.user_data["stage"] = "level"
    await query.edit_message_text(
        f"Выбрана программа: {program[1]} — {program[2]}\n\nТеперь укажи тип работы:",
        reply_markup=level_keyboard(),
    )


async def show_years(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["stage"] = "year"
    label = "курсовой" if context.user_data.get("level") == "course" else "дипломной"
    await query.edit_message_text(
        f"Тип работы: {label}.\n\nНа каком ты курсе?",
        reply_markup=year_keyboard(),
    )


async def show_subjects(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["stage"] = "subjects"
    chosen = context.user_data.get("selected_subjects", [])
    selected_text = "\n\nВыбрано: " + ", ".join(chosen) if chosen else ""
    await query.edit_message_text(
        "Отметь предметы и темы, которые уже проходил. Нажми на предмет, чтобы добавить или убрать его."
        + selected_text,
        reply_markup=subject_keyboard(context),
    )


async def generate_for_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    selected = context.user_data.get("selected_subjects", [])
    custom = context.user_data.get("custom_topics", "").strip()
    studied = "\n".join([*selected, custom]).strip()
    program = context.user_data.get("program")
    if not program or not context.user_data.get("level"):
        await update.effective_chat.send_message("Пройди выбор специальности и типа работы заново командой /start.")
        return
    if not studied:
        context.user_data["stage"] = "awaiting_topics"
        await update.effective_chat.send_message(
            "Напиши одним сообщением предметы или темы, которые ты уже проходил."
        )
        return

    label = "курсовая" if context.user_data["level"] == "course" else "дипломная"
    await update.effective_chat.send_message("⏳ Подбираю темы с учётом специальности и выбранного типа работы…")
    try:
        data = normalize_generation_data({
            "major": program[2],
            "studied": studied,
            "level": context.user_data["level"],
            "year": context.user_data.get("year", ""),
            "count": context.user_data.get("generation_count", 5),
            "language": context.user_data.get("language", "ru"),
        })
        topics, mode = await asyncio.to_thread(generate_topics, data)
    except Exception as exc:
        logger.warning("Topic generation failed (%s)", type(exc).__name__)
        await update.effective_chat.send_message(generation_error_message(exc))
        return

    language = context.user_data.get("language", "ru")
    mode_note = "" if mode == "ai" else ("\nҚазір дайын мысалдар көрсетілді." if language == "kk" else "\nСейчас показаны готовые примеры.")
    done_text = f"Дайын: {len(topics)} жұмыс тақырыбы ұсынылды.{mode_note}" if language == "kk" else f"Готово: {len(topics)} идей для работы на тему «{label}».{mode_note}"
    await update.effective_chat.send_message(done_text)
    for index, topic in enumerate(topics, 1):
        await update.effective_chat.send_message(topic_message(topic, index, language))
    await update.effective_chat.send_message(
        "Басқа нұсқа алу үшін /start бас." if language == "kk" else "Чтобы подобрать другой вариант, нажми /start.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Қайта бастау" if language == "kk" else "Начать заново", callback_data="restart")]]),
    )
    context.user_data["stage"] = "finished"


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    payload = query.data or ""

    if payload == "restart":
        await start(update, context)
    elif payload.startswith("page:"):
        await show_programs(query, context, int(payload.split(":", 1)[1]))
    elif payload.startswith("program:"):
        index = int(payload.split(":", 1)[1])
        if not 0 <= index < len(PROGRAMS):
            await show_programs(query, context)
            return
        context.user_data.clear()
        program = PROGRAMS[index]
        context.user_data.update(program=program, family=program[3], selected_subjects=[], generation_count=5, language="ru")
        await show_levels(query, context)
    elif payload.startswith("level:"):
        level = payload.split(":", 1)[1]
        if level not in {"course", "diploma"}:
            await show_levels(query, context)
            return
        context.user_data["level"] = level
        await show_years(query, context)
    elif payload.startswith("year:"):
        year = payload.split(":", 1)[1]
        if year not in {"1", "2", "3", "4"}:
            await show_years(query, context)
            return
        context.user_data["year"] = year
        await show_subjects(query, context)
    elif payload.startswith("subject:"):
        index = int(payload.split(":", 1)[1])
        subjects = SUBJECT_EXAMPLES.get(context.user_data.get("family", ""), [])
        if 0 <= index < min(len(subjects), SUBJECTS_PER_PAGE):
            selected = context.user_data.setdefault("selected_subjects", [])
            subject = subjects[index]
            if subject in selected:
                selected.remove(subject)
            else:
                selected.append(subject)
            await show_subjects(query, context)
    elif payload == "subjects:done":
        context.user_data["stage"] = "topic_options"
        await query.edit_message_text(
            "Список предметов готов. Можно сразу сгенерировать темы или добавить свои пройденные темы.",
            reply_markup=topic_options_keyboard(context),
        )
    elif payload == "custom":
        context.user_data["stage"] = "awaiting_topics"
        await query.edit_message_text(
            "Отправь одним сообщением свои пройденные предметы и темы. Я добавлю их к выбранным выше."
        )
    elif payload.startswith("count:"):
        count = payload.split(":", 1)[1]
        if count in {"3", "5", "8"}:
            context.user_data["generation_count"] = int(count)
        keyboard = ready_keyboard(context) if context.user_data.get("stage") == "ready" else topic_options_keyboard(context)
        await query.edit_message_reply_markup(reply_markup=keyboard)
    elif payload.startswith("language:"):
        language = payload.split(":", 1)[1]
        if language in {"ru", "kk"}:
            context.user_data["language"] = language
        keyboard = ready_keyboard(context) if context.user_data.get("stage") == "ready" else topic_options_keyboard(context)
        await query.edit_message_reply_markup(reply_markup=keyboard)
    elif payload == "generate":
        await generate_for_chat(update, context)
    elif payload == "back:program":
        await show_programs(query, context)
    elif payload == "back:level":
        await show_levels(query, context)
    elif payload == "back:year":
        await show_years(query, context)
    elif payload == "back:subjects":
        await show_subjects(query, context)


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("stage") != "awaiting_topics":
        await update.effective_message.reply_text("Чтобы начать или изменить выбор, нажми /start.")
        return
    text = (update.effective_message.text or "").strip()
    if not text:
        await update.effective_message.reply_text("Напиши названия предметов или пройденных тем.")
        return
    context.user_data["custom_topics"] = text[:3000]
    context.user_data["stage"] = "ready"
    await update.effective_message.reply_text(
        "Добавил твои темы. Можно запускать генерацию:",
        reply_markup=ready_keyboard(context),
    )


async def receive_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    document = message.document
    if not document or not document.file_name or Path(document.file_name).suffix.lower() != ".docx":
        await message.reply_text("Пришли документ Word в формате .docx.")
        return
    if document.file_size and document.file_size > 5 * 1024 * 1024:
        await message.reply_text("Файл слишком большой. Максимальный размер — 5 МБ.")
        return
    try:
        remote = await document.get_file()
        payload = await remote.download_as_bytearray()
        extracted = extract_docx_text(payload)[:3000]
        if not extracted:
            await message.reply_text("В файле не найден текст. Добавь темы или уроки в документ.")
            return
        previous = context.user_data.get("custom_topics", "").strip()
        context.user_data["custom_topics"] = f"{previous}\n{extracted}".strip()[:3000]
        context.user_data["stage"] = "ready"
        await message.reply_text("Материалы из Word-документа добавлены. Можно генерировать темы:", reply_markup=ready_keyboard(context))
    except Exception:
        logger.exception("Could not read uploaded DOCX")
        await message.reply_text("Не удалось открыть файл. Проверь, что это корректный документ .docx.")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "вставьте_токен_от_BotFather":
        print("Не найден TELEGRAM_BOT_TOKEN. Создай бота у @BotFather и добавь токен в .env.")
        sys.exit(1)

    if not acquire_single_instance(token):
        print("Этот Telegram-бот уже запущен в другом окне. Второй экземпляр не стартовал.")
        sys.exit(0)

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))
    application.add_handler(MessageHandler(filters.Document.ALL, receive_document))
    logger.info("Бот запущен. Останови его сочетанием Ctrl+C.")
    application.run_polling()


if __name__ == "__main__":
    main()

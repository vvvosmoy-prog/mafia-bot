import os
import re
import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==== ФЕЙКОВЫЙ ВЕБ-СЕРВЕР ====
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot is alive"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


# ==== НАСТРОЙКИ ====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DEFAULT_THRESHOLD = 10
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]


def build_keyboard(closed: bool = False) -> InlineKeyboardMarkup:
    if closed:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("Сбор завершён", callback_data="noop")]]
        )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Я в деле ✅", callback_data="join"),
                InlineKeyboardButton("Отмена ❌", callback_data="leave"),
            ]
        ]
    )


def render_text(names: list, threshold: int, closed: bool = False) -> str:
    lines = [
        "🕵️‍♂️ СБОР НА МАФИЮ 🔪",
        "",
        f"Нужно игроков: {threshold}",
        f"Собралось: {len(names)}/{threshold}",
        "",
    ]
    if names:
        lines.append("Участники:")
        lines.extend(f"• {n}" for n in names)
    else:
        lines.append("Пока никого. Жми кнопку ниже 👇")

    if closed:
        lines.insert(0, "✅ СБОР СОСТОЯЛСЯ! Все готовы, стартуем!")
        lines.insert(1, "")

    return "\n".join(lines)


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    msg = update.effective_message
    if not msg:
        return False

    if update.effective_chat and update.effective_chat.type == "channel":
        return True

    if msg.sender_chat or msg.is_automatic_forward:
        return True

    user = update.effective_user
    if not user:
        return True

    if user.id in (1087968824, 777000):
        return True

    if ADMIN_IDS and user.id in ADMIN_IDS:
        return True

    if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
        try:
            member = await context.bot.get_chat_member(
                update.effective_chat.id, user.id
            )
            if member.status in ("administrator", "creator"):
                return True
        except Exception as e:
            logger.error(f"Ошибка проверки прав: {e}")

    if ADMIN_IDS:
        return False

    return True


async def handle_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    if msg.is_automatic_forward:
        return

    if not await is_admin(update, context):
        if update.message:
            await update.message.reply_text("Эта команда только для админов.")
        return

    parts = msg.text.strip().split()
    threshold = DEFAULT_THRESHOLD
    if len(parts) > 1:
        try:
            threshold = int(parts[1])
        except ValueError:
            pass

    text = render_text(names=[], threshold=threshold)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=build_keyboard(),
    )

    try:
        await msg.delete()
    except Exception as e:
        logger.warning(f"Не удалось удалить текст команды: {e}")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            "Привет! Я бот для сбора игроков в мафию.\n\n"
            "Команда /newgame — запустить новый сбор (по умолчанию 10 человек).\n"
            "Пример: /newgame 8 — запустить сбор на 8 человек."
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.message:
        return

    if query.data == "noop":
        await query.answer("Этот сбор уже завершён.", show_alert=True)
        return

    current_text = query.message.text or ""

    threshold_match = re.search(r"Нужно игроков:\s*(\d+)", current_text)
    threshold = int(threshold_match.group(1)) if threshold_match else DEFAULT_THRESHOLD

    names = []
    for line in current_text.split("\n"):
        line = line.strip()
        if line.startswith("• "):
            names.append(line[2:].strip())

    user = query.from_user
    display = f"@{user.username}" if user.username else user.first_name

    # Обработка нажатия "Я в деле ✅"
    if query.data == "join":
        if display in names:
            await query.answer("Ты уже записан на этот сбор!", show_alert=True)
            return
        names.append(display)
        await query.answer("Записал тебя!")

    # Обработка нажатия "Отмена ❌"
    elif query.data == "leave":
        if display not in names:
            await query.answer("Тебя нет в списке этого сбора.", show_alert=True)
            return
        names.remove(display)
        await query.answer("Ты вышел из сбора.")

    closed = len(names) >= threshold
    new_text = render_text(names=names, threshold=threshold, closed=closed)

    await query.edit_message_text(
        text=new_text,
        reply_markup=build_keyboard(closed=closed),
    )

    if closed:
        mentions = ", ".join(names)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🚨 Собралось {threshold} человек! Го в лобби: {mentions}",
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения")

    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.Regex(r"^/start"), handle_start))
    app.add_handler(MessageHandler(filters.Regex(r"^/newgame"), handle_newgame))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

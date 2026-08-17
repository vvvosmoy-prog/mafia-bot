import os
import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==== ФЕЙКОВЫЙ ВЕБ-СЕРВЕР ====
# Render бесплатно держит только "веб-сервисы", которые отвечают на HTTP-запросы.
# Этот мини-сервер существует только чтобы Render считал бота "сайтом" и не убивал процесс,
# а внешний пингер (UptimeRobot) будет стучаться сюда каждые 5 минут, чтобы Render не усыплял его.
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot is alive"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# ==== НАСТРОЙКИ ====
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # токен подставляется через переменную окружения
DEFAULT_THRESHOLD = 10  # сколько человек нужно для старта сбора
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

# Хранилище активных сборов: {message_id: {"chat_id":.., "players": {}, "threshold":.., "closed": bool}}
active_sessions = {}


def build_keyboard(closed: bool = False) -> InlineKeyboardMarkup:
    if closed:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Сбор завершён", callback_data="noop")]])
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Я в деле ✅", callback_data="join")]]
    )


def render_text(players: dict, threshold: int, closed: bool = False) -> str:
    names = [p["display"] for p in players.values()]
    lines = [
        "🕵️‍♂️ СБОР НА МАФИЮ 🔪",
        "",
        f"Нужно игроков: {threshold}",
        f"Собралось: {len(players)}/{threshold}",
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
    # сообщения, опубликованные от имени канала (а не от личного аккаунта),
    # не содержат данных об отправителе - но постить в канал может только админ,
    # поэтому такие сообщения считаем доверенными
    if update.effective_user is None:
        return True
    user_id = update.effective_user.id
    if ADMIN_IDS:
        return user_id in ADMIN_IDS
    # если список админов не задан - разрешаем всем (упрощённый режим)
    return True


async def newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /newgame [число] - запускает новый сбор. Использовать в канале как админ-пост,
    либо в группе - командой от админа."""
    if not await is_admin(update, context):
        await update.message.reply_text("Эта команда только для админов.")
        return

    threshold = DEFAULT_THRESHOLD
    if context.args:
        try:
            threshold = int(context.args[0])
        except ValueError:
            pass

    players = {}
    text = render_text(players, threshold)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=build_keyboard(),
    )
    active_sessions[msg.message_id] = {
        "chat_id": msg.chat_id,
        "players": players,
        "threshold": threshold,
        "closed": False,
    }


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    msg_id = query.message.message_id
    session = active_sessions.get(msg_id)

    if not session or session["closed"]:
        await query.answer("Этот сбор уже закрыт или не найден.", show_alert=True)
        return

    user = query.from_user
    display = f"@{user.username}" if user.username else user.first_name

    if user.id in session["players"]:
        # повторное нажатие - выходит из списка
        del session["players"][user.id]
        await query.answer("Ты вышел из сбора.")
    else:
        session["players"][user.id] = {"display": display}
        await query.answer("Записал тебя!")

    closed = len(session["players"]) >= session["threshold"]
    session["closed"] = closed

    text = render_text(session["players"], session["threshold"], closed)
    await context.bot.edit_message_text(
        chat_id=session["chat_id"],
        message_id=msg_id,
        text=text,
        reply_markup=build_keyboard(closed=closed),
    )

    if closed:
        mentions = ", ".join(p["display"] for p in session["players"].values())
        await context.bot.send_message(
            chat_id=session["chat_id"],
            text=f"🚨 Собралось {session['threshold']} человек! Го в лобби: {mentions}",
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для сбора игроков в мафию.\n\n"
        "Команда /newgame — запустить новый сбор (по умолчанию порог 10 человек).\n"
        "Пример: /newgame 8 — запустить сбор на 8 человек."
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения")

    # запускаем фейковый веб-сервер в отдельном потоке, чтобы Render видел "живой сайт"
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newgame", newgame))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()

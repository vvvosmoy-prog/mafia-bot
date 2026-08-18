import os
import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ContextTypes,
    TypeHandler,
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

# Хранилище активных сборов
active_sessions = {}


def build_keyboard(closed: bool = False) -> InlineKeyboardMarkup:
    if closed:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("Сбор завершён", callback_data="noop")]]
        )
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


async def button_handler(query):
    msg_id = query.message.message_id
    session = active_sessions.get(msg_id)

    if not session or session["closed"]:
        await query.answer("Этот сбор уже закрыт или не найден.", show_alert=True)
        return

    user = query.from_user
    display = f"@{user.username}" if user.username else user.first_name

    if user.id in session["players"]:
        del session["players"][user.id]
        await query.answer("Ты вышел из сбора.")
    else:
        session["players"][user.id] = {"display": display}
        await query.answer("Записал тебя!")

    closed = len(session["players"]) >= session["threshold"]
    session["closed"] = closed

    text = render_text(session["players"], session["threshold"], closed)
    await query.bot.edit_message_text(
        chat_id=session["chat_id"],
        message_id=msg_id,
        text=text,
        reply_markup=build_keyboard(closed=closed),
    )

    if closed:
        mentions = ", ".join(p["display"] for p in session["players"].values())
        await query.bot.send_message(
            chat_id=session["chat_id"],
            text=f"🚨 Собралось {session['threshold']} человек! Го в лобби: {mentions}",
        )


async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Нажатие на кнопки
    if update.callback_query:
        await button_handler(update.callback_query)
        return

    # 2. Перехватываем сообщение из группы или публикацию из канала
    msg = update.channel_post or update.message
    if not msg or not msg.text:
        return

    # Игнорируем авто-дубликат поста, который Telegram шлёт в чат
    if msg.is_automatic_forward:
        return

    text = msg.text.strip()

    # Команда /start
    if text.startswith("/start"):
        await context.bot.send_message(
            chat_id=msg.chat_id,
            text="Привет! Я бот для сбора игроков в мафию.\n\n"
                 "Команда /newgame — запустить новый сбор (по умолчанию 10 человек).\n"
                 "Пример: /newgame 8 — запустить сбор на 8 человек.",
        )
        return

    # Команда /newgame
    if text.startswith("/newgame"):
        parts = text.split()
        threshold = DEFAULT_THRESHOLD
        if len(parts) > 1:
            try:
                threshold = int(parts[1])
            except ValueError:
                pass

        players = {}
        rendered_text = render_text(players, threshold)

        try:
            # Публикуем интерактивную карточку в Канал
            sent_msg = await context.bot.send_message(
                chat_id=msg.chat_id,
                text=rendered_text,
                reply_markup=build_keyboard(),
            )
            active_sessions[sent_msg.message_id] = {
                "chat_id": sent_msg.chat_id,
                "players": players,
                "threshold": threshold,
                "closed": False,
            }

            # Если команда отправлена в канале — сразу удаляем текст /newgame
            if msg.chat.type == "channel":
                try:
                    await msg.delete()
                except Exception as e:
                    logger.warning(f"Не удалось удалить команду из канала: {e}")

        except Exception as e:
            logger.error(f"Ошибка при обработке /newgame: {e}")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения")

    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # Перехватчик всех типов сообщений и постов каналов без потерь
    app.add_handler(TypeHandler(Update, handle_update))

    logger.info("Бот запущен")
    app.run_polling(allowed_updates=["message", "channel_post", "callback_query"])


if __name__ == "__main__":
    main()

import logging
import os
import sqlite3
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

# Используем общий логгер
logger = logging.getLogger('bot')

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'loyobot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return conn, cursor

def get_user_position(telegram_id):
    logger.info(f"Получаем должность пользователя с Telegram ID: {telegram_id}")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("SELECT position FROM team WHERE telegramId = ?", (telegram_id,))
        positions = [row[0] for row in cursor.fetchall() if row[0]]
        logger.info(f"Должности пользователя: {positions}")
        return positions
    except Exception as e:
        logger.error(f"Ошибка при получении должности пользователя: {e}")
        return []
    finally:
        conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    positions = get_user_position(telegram_id)
    positions = [position.lower() for position in positions if position]  # Приводим позиции к нижнему регистру

    # Базовые команды, доступные всем
    commands = [
        "🔄 /cancel - Рестарт бота",
        "📝 /request - Подать заявку на расход",
        "💰 /deposit - Подать заявку на возврат депозита",
        "💸 /comission - Подать заявку на выплату комиссии агенству"
        "📌 /submitchecks - Прикрепить чеки к своим оплаченных заявкам"
    ]

    # Добавляем команды в зависимости от должности
    if 'head' in positions:
        commands.extend([
            "👥 /department_requests - Посмотреть заявки отдела",
            "📊 /report - Получить историю заявок"
        ])

    if 'cfo' in positions:
        commands.append("💼 /cfo - Посмотреть согласованные заявки")

    if 'payer' in positions:
        commands.append("💳 /payer_requests - Посмотреть заявки на оплату")

    # Формируем сообщение
    message = "🤖 <b>Доступные команды:</b>\n\n" + "\n".join(commands)

    await update.message.reply_text(message, parse_mode='HTML')

def register_handlers(application):
    application.add_handler(CommandHandler('start', start))

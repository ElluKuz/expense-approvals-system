import logging
import os
import datetime
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

# Используем общий логгер
logger = logging.getLogger('bot')

# Стейты для ConversationHandler
NAME, CLIENT_NAME, PROJECT_NAME, UNIT_NUMBER, AGENT, REASON, DETAILS, AMOUNT = range(8)

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'loyobot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return conn, cursor

# Функция для проверки наличия пользователя в таблице 'team'
def check_user_in_team(telegram_id):
    logger.info(f"Проверяем наличие пользователя с Telegram ID: {telegram_id} в таблице 'team'")
    conn, cursor = get_db_connection()
    cursor.execute("SELECT * FROM team WHERE telegramId = ?", (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        logger.info("Пользователь найден в таблице 'team'")
        return True
    else:
        logger.info("Пользователь не найден в таблице 'team'")
        return False

# Функция для получения имени пользователя из таблицы 'team'
def get_requester_name(telegram_id):
    logger.info(f"Получаем имя пользователя с Telegram ID: {telegram_id}")
    conn, cursor = get_db_connection()
    cursor.execute("SELECT name FROM team WHERE telegramId = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        name = row[0]
        logger.info(f"Имя пользователя: {name}")
        return name
    else:
        logger.error("Не удалось найти пользователя в таблице 'team'")
        return None

# Функция для добавления нового пользователя в таблицу 'team'
def add_user_to_team(telegram_id, telegram_nickname, name):
    logger.info(f"Добавляем нового пользователя с Telegram ID: {telegram_id}")
    conn, cursor = get_db_connection()
    cursor.execute("""
        INSERT INTO team (telegramId, telegramNickname, name)
        VALUES (?, ?, ?)
    """, (telegram_id, telegram_nickname, name))
    conn.commit()
    conn.close()
    logger.info("Пользователь успешно добавлен в таблицу 'team'")

# Обработчик команды /deposit
async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Обработка команды /deposit")
    telegram_id = update.effective_user.id
    logger.info(f"Telegram ID пользователя: {telegram_id}")

    user_exists = check_user_in_team(telegram_id)
    if not user_exists:
        logger.info("Пользователь не найден, запрашиваем имя")
        await update.message.reply_text(
            "👤 Please enter your <b>name</b>:",
            parse_mode='HTML'
        )
        return NAME
    else:
        logger.info("Пользователь найден, переходим к запросу имени клиента")
        await request_client_name(update, context)
        return CLIENT_NAME

# Обработчик для получения имени пользователя
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    context.user_data['name'] = name
    logger.info(f"Получено имя пользователя: {name}")
    telegram_id = update.effective_user.id
    telegram_nickname = update.effective_user.username or ''
    logger.info(f"Telegram ID: {telegram_id}, Никнейм: {telegram_nickname}")

    add_user_to_team(telegram_id, telegram_nickname, name)
    logger.info("Переходим к запросу имени клиента")

    # Удаляем предыдущее сообщение пользователя
    await update.message.delete()

    await request_client_name(update, context)
    return CLIENT_NAME

async def request_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Запрос имени клиента")
    message = await update.message.reply_text(
        "👤 Please enter the <b>client's name</b>:",
        parse_mode='HTML'
    )
    # Сохраняем ID сообщения бота
    context.user_data['bot_message_id'] = message.message_id
    context.user_data['bot_chat_id'] = message.chat_id

async def get_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client_name = update.message.text
    context.user_data['client_name'] = client_name
    logger.info(f"Получено имя клиента: {client_name}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота
    bot_message_id = context.user_data['bot_message_id']
    bot_chat_id = context.user_data['bot_chat_id']
    text = f"👤 Сlient's name: <b>{client_name}</b>\n\n" \
           "🏗️ Please enter the <b>project name</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return PROJECT_NAME

async def get_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_name = update.message.text
    context.user_data['project_name'] = project_name
    logger.info(f"Получено наименование проекта: {project_name}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота
    bot_message_id = context.user_data['bot_message_id']
    bot_chat_id = context.user_data['bot_chat_id']
    client_name = context.user_data['client_name']
    text = f"👤 Сlient's name: <b>{client_name}</b>\n" \
           f"🏗️ Project name: <b>{project_name}</b>\n\n" \
           "🏢  Please enter the <b>unit number</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return UNIT_NUMBER

async def get_unit_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    unit_number = update.message.text
    context.user_data['unit_number'] = unit_number
    logger.info(f"Получен номер юнита: {unit_number}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота
    bot_message_id = context.user_data['bot_message_id']
    bot_chat_id = context.user_data['bot_chat_id']
    client_name = context.user_data['client_name']
    project_name = context.user_data['project_name']
    text = f"👤 Сlient's name: <b>{client_name}</b>\n" \
           f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n\n" \
           "🧑‍💼 Please enter the <b>agent's name</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return AGENT

async def get_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = update.message.text
    context.user_data['agent'] = agent
    logger.info(f"Получено имя агента: {agent}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота
    bot_message_id = context.user_data['bot_message_id']
    bot_chat_id = context.user_data['bot_chat_id']
    client_name = context.user_data['client_name']
    project_name = context.user_data['project_name']
    unit_number = context.user_data['unit_number']
    text = f"👤 Сlient's name: <b>{client_name}</b>\n" \
           f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n\n" \
           f"🧑‍💼 Agent's name: <b>{agent}</b>\n\n" \
           "❓ Please enter the <b>reason for rejection</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return REASON

async def get_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text
    context.user_data['reason'] = reason
    logger.info(f"Получена причина отказа: {reason}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота
    bot_message_id = context.user_data['bot_message_id']
    bot_chat_id = context.user_data['bot_chat_id']
    client_name = context.user_data['client_name']
    project_name = context.user_data['project_name']
    unit_number = context.user_data['unit_number']
    agent = context.user_data['agent']
    text = f"👤 Сlient's name: <b>{client_name}</b>\n" \
           f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n\n" \
           f"🧑‍💼 Agent's name: <b>{agent}</b>\n\n" \
           f"❓ Reason for rejection <b>{reason}</b>\n\n" \
           "💳 Please enter the <b>USDT TRC-20 wallet number</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return DETAILS
async def get_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    details = update.message.text
    context.user_data['details'] = details
    logger.info(f"Получен номер кошелька: {details}")
    # Удаляем сообщение пользователя
    await update.message.delete()
    
    # Извлекаем данные из context.user_data, используя get() с значением по умолчанию
    client_name = context.user_data.get('client_name', 'не указано')
    project_name = context.user_data.get('project_name', 'не указано')
    unit_number = context.user_data.get('unit_number', 'не указано')
    agent = context.user_data.get('agent', 'не указано')
    reason = context.user_data.get('reason', 'не указано')
    
    # Обновляем сообщение бота
    bot_message_id = context.user_data['bot_message_id']
    bot_chat_id = context.user_data['bot_chat_id']
    text = (
        f"👤 Сlient's name: <b>{client_name}</b>\n"
        f"🏗️ Project name: <b>{project_name}</b>\n"
        f"🏢 Unit number: <b>{unit_number}</b>\n"
        f"🧑‍💼 Agent's name: <b>{agent}</b>\n"
        f"❓ Reason for rejection: <b>{reason}</b>\n"
        f"💳 USDT TRC-20 wallet number: <b>{details}</b>\n\n"
        "💰 Please enter the <b>amount</b>:"
    )
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = update.message.text
    context.user_data['amount'] = amount
    logger.info(f"Получена сумма: {amount}")

    # Удаляем сообщение пользователя
    await update.message.delete()

    # Изменяем сообщение бота на "Ожидайте, заявка в обработке"
    bot_message_id = context.user_data['bot_message_id']
    bot_chat_id = context.user_data['bot_chat_id']
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text="⌛ Please wait, the request is being processed...",
        parse_mode='HTML'
    )

    # Сохраняем заявку
    await save_request(update, context)

    # После сохранения заявки показываем подтверждение
    client_name = context.user_data['client_name']
    project_name = context.user_data['project_name']
    unit_number = context.user_data['unit_number']
    agent = context.user_data['agent']
    reason = context.user_data['reason']
    details = context.user_data['details']
    amount = context.user_data['amount']
    text = f"👤 Сlient's name: <b>{client_name}</b>\n" \
           f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n\n" \
           f"🧑‍💼 Agent's name: <b>{agent}</b>\n\n" \
           f"❓ Reason for rejection <b>{reason}</b>\n\n" \
           f"💳 USDT TRC-20 wallet number: <b>{details}</b>\n" \
           f"💰 Amount:  <b>{amount}</b>\n\n" \
           "✅ The request has been submitted, the department head has been notified."
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )

    # Clear user data before ending the conversation
    context.user_data.clear()
    return ConversationHandler.END

# Функция для сохранения заявки
async def save_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Начинаем сохранение запроса")
    data = context.user_data
    user = update.effective_user

    status = 'Ожидает решения руководителя'
    dateTime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    department = 'Операционный отдел'
    amount = data['amount']

    combined_description = (
        "ВОЗВРАТ ДЕПОЗИТА\n"
        f"👤 Сlient's name: {data['client_name']}\n"
        f"🏗️ Project name: {data['project_name']}\n"
        f"🏢 Unit number:  {data['unit_number']}\n"
        f"🧑‍💼 Agent's name: {data['agent']}\n"
        f"❓ Reason for rejection: {data['reason']}"
    )
    logger.info(f"Объединённое описание: {combined_description}")

    requesterTelegramId = user.id
    requesterTelegramNickname = user.username or ''
    requesterName = get_requester_name(user.id)

    # Вставляем запись в базу данных
    conn, cursor = get_db_connection()
    cursor.execute("""
        INSERT INTO requests (status, dateTime, department, amount, description, details,
                              requesterTelegramId, requesterTelegramNickname, requesterName)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        status, dateTime, department, amount, combined_description, data['details'],
        requesterTelegramId, requesterTelegramNickname, requesterName
    ))
    conn.commit()
    conn.close()
    logger.info("Новая заявка успешно добавлена в таблицу 'requests'")

    # Уведомляем руководителей отдела "Операционный отдел"
    logger.info("Получаем Telegram ID глав отдела 'Операционный отдел'")
    department_heads = get_department_heads('Операционный отдел')

    notification_text = (
        f"📢 <b>Новая заявка от {requesterName} (@{requesterTelegramNickname})</b>\n"
        f"🆔 <b>Статус:</b> {status}\n"
        f"📅 <b>Дата и время:</b> {dateTime}\n"
        f"{combined_description}\n"
        f"<b>______________________________</b>\n"
        f"🆕 <b>Введите /department_requests,</b> чтобы принять решение по заявке\n"
    )
    logger.info("Отправляем уведомления главам отдела 'Операционный отдел'")

    for head_id in department_heads:
        try:
            await context.bot.send_message(chat_id=head_id, text=notification_text, parse_mode='HTML')
            logger.info(f"Уведомление отправлено пользователю с ID: {head_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {head_id}: {e}")

# Функция для получения ID руководителей отдела
def get_department_heads(department):
    logger.info(f"Получаем Telegram ID глав отдела: {department}")
    conn, cursor = get_db_connection()
    cursor.execute("""
        SELECT telegramId FROM team WHERE department = ? AND position = 'head'
    """, (department,))
    head_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    if head_ids:
        logger.info(f"Найдены главы отдела: {head_ids}")
    else:
        logger.info("Главы отдела не найдены")
    return head_ids

# Функция отмены диалога
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Пользователь отменил диалог")
    # Очищаем данные пользователя
    context.user_data.clear()
    await update.message.reply_text(
        "🚫 Диалог был отменён.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

# Регистрация обработчиков
def register_handlers(application: Application):
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('deposit', deposit_command)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            CLIENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_client_name)],
            PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_project_name)],
            UNIT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_unit_number)],
            AGENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_agent)],
            REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_reason)],
            DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_details)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(conv_handler)

    # Добавляем глобальный обработчик /cancel
    application.add_handler(CommandHandler('cancel', cancel))

def get_departments():
    logger.info("Получаем список отделов из базы данных")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("SELECT name FROM departments")
        departments = [row[0] for row in cursor.fetchall()]
        logger.info(f"Список отделов из базы данных: {departments}")
        return departments
    except Exception as e:
        logger.error(f"Ошибка при получении списка отделов: {e}")
        return []
    finally:
        conn.close()

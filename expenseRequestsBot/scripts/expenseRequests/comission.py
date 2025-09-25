import logging
import datetime
import sqlite3
import os
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, filters
)

# Используем общий логгер
logger = logging.getLogger('bot')

# Обновленные стейты для ConversationHandler
NAME, PROJECT_NAME, CLIENT_NAME, UNIT_NUMBER, PRICE, MANAGER_CONTACT, AGENCY_NAME, AGENCY_COMMISSION_PERCENT, AMOUNT, AGENT_NAME, INTERNAL_MANAGER_NAME, DETAILS, DESCRIPTION = range(13)

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

# Обработчик команды /comission
async def comission_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Обработка команды /comission")
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
        logger.info("Пользователь найден, переходим к запросу наименования проекта")
        await request_project_name(update, context)
        return PROJECT_NAME

# Обработчик для получения имени пользователя
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    context.user_data['name'] = name
    logger.info(f"Получено имя пользователя: {name}")
    telegram_id = update.effective_user.id
    telegram_nickname = update.effective_user.username or ''
    logger.info(f"Telegram ID: {telegram_id}, Никнейм: {telegram_nickname}")

    add_user_to_team(telegram_id, telegram_nickname, name)
    logger.info("Переходим к запросу наименования проекта")

    # Удаляем предыдущее сообщение пользователя
    await update.message.delete()

    await request_project_name(update, context)
    return PROJECT_NAME

async def request_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Запрос наименования проекта")
    message = await update.message.reply_text(
        "🏗️ Please enter the <b>project name</b>:",
        parse_mode='HTML'
    )
    # Сохраняем ID сообщения бота
    context.user_data['bot_message_id'] = message.message_id
    context.user_data['bot_chat_id'] = message.chat_id

async def get_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    project_name = update.message.text
    context.user_data['project_name'] = project_name
    logger.info(f"Получено наименование проекта: {project_name}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    text = f"🏗️ Project name: <b>{project_name}</b>\n\n" \
           "👤 Please enter the <b>client's name</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return CLIENT_NAME

async def get_client_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client_name = update.message.text
    context.user_data['client_name'] = client_name
    logger.info(f"Получено имя клиента: {client_name}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    project_name = context.user_data['project_name']
    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n\n" \
           "🏢 Please enter the <b>unit number</b>:"
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
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n\n" \
           "💰 Please enter the <b>price</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return PRICE

async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = update.message.text
    context.user_data['price'] = price
    logger.info(f"Получена цена: {price}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота и переходим сразу к запросу контакта руководителя
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    unit_number = context.user_data['unit_number']
    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n" \
           f"💰 Price: <b>{price}</b>\n\n" \
           "📞 Please enter the <b>manager's contact</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return MANAGER_CONTACT

async def get_manager_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager_contact = update.message.text
    context.user_data['manager_contact'] = manager_contact
    logger.info(f"Получен контакт руководителя: {manager_contact}")
    # Удаляем сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота и переходим к запросу названия агентства
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')

    # Получаем все предыдущие данные
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    unit_number = context.user_data['unit_number']
    price = context.user_data['price']

    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n" \
           f"💰 Price: <b>{price}</b>\n" \
           f"📞 Manager's contact: <b>{manager_contact}</b>\n\n" \
           "💳 Please enter the <b>agency name</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return AGENCY_NAME

async def get_agency_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agency_name = update.message.text
    context.user_data['agency_name'] = agency_name
    logger.info(f"Получено название агентства: {agency_name}")
    await update.message.delete()

    # Обновляем сообщение бота и переходим к запросу комиссии агентства (процент)
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')

    # Получаем все предыдущие данные
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    unit_number = context.user_data['unit_number']
    price = context.user_data['price']
    manager_contact = context.user_data['manager_contact']

    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n" \
           f"💰 Price: <b>{price}</b>\n" \
           f"📞 Manager's contact: <b>{manager_contact}</b>\n\n" \
           f"🏢 Agency name: <b>{agency_name}</b>\n\n" \
           "💼 Please enter the <b>agency commission (%)</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return AGENCY_COMMISSION_PERCENT

async def get_agency_commission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agency_commission_percent = update.message.text
    context.user_data['agency_commission_percent'] = agency_commission_percent
    logger.info(f"Получена комиссия агентства (процент): {agency_commission_percent}")
    await update.message.delete()

    # Обновляем сообщение бота и переходим к запросу суммы комиссии
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')

    # Получаем все предыдущие данные
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    unit_number = context.user_data['unit_number']
    price = context.user_data['price']
    manager_contact = context.user_data['manager_contact']
    agency_name = context.user_data['agency_name']

    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n" \
           f"💰 Price: <b>{price}</b>\n" \
           f"📞 Manager's contact: <b>{manager_contact}</b>\n\n" \
           f"🏢 Agency name: <b>{agency_name}</b>\n\n" \
           f"💼 Agency commission: <b>{agency_commission_percent}%</b>\n\n" \
           "💰 Please enter the <b>commission amount</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Валидация: только целое число суммы
    try:
        amount_int = int(text)
    except ValueError:
        await update.message.reply_text(
            "⚠️ Пожалуйста, введите сумму комиссии целым числом (только цифры, без точек и запятых)."
        )
        return AMOUNT
    
    warning_id = context.user_data.pop('warning_msg_id', None)
    if warning_id:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=warning_id
            )
        except:
            pass
    context.user_data['amount'] = amount_int
    logger.info(f"Получена сумма комиссии: {amount_int}")
    await update.message.delete()

    # Обновляем сообщение бота и переходим к запросу имени агента
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')

    # Получаем все предыдущие данные
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    unit_number = context.user_data['unit_number']
    price = context.user_data['price']
    manager_contact = context.user_data['manager_contact']
    agency_name = context.user_data['agency_name']
    agency_commission_percent = context.user_data['agency_commission_percent']

    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n" \
           f"💰 Price: <b>{price}</b>\n" \
           f"📞 Manager's contact: <b>{manager_contact}</b>\n\n" \
           f"🏢 Agency name: <b>{agency_name}</b>\n\n" \
           f"💼 Agency commission: <b>{agency_commission_percent}%</b>\n\n" \
           f"💰 Commission amount: <b>{amount_int}</b>\n\n" \
           "👤 Please enter the <b>agent's name</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return AGENT_NAME

async def get_agent_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent_name = update.message.text
    context.user_data['agent_name'] = agent_name
    logger.info(f"Получено имя агента: {agent_name}")
    await update.message.delete()

    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')

    # Получаем все предыдущие данные, включая сумму комиссии
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    unit_number = context.user_data['unit_number']
    price = context.user_data['price']
    manager_contact = context.user_data['manager_contact']
    agency_name = context.user_data['agency_name']
    agency_commission_percent = context.user_data['agency_commission_percent']
    amount = context.user_data['amount']

    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n" \
           f"💰 Price: <b>{price}</b>\n" \
           f"📞 Manager's contact: <b>{manager_contact}</b>\n\n" \
           f"🏢 Agency name: <b>{agency_name}</b>\n\n" \
           f"💼 Agency commission: <b>{agency_commission_percent}%</b>\n\n" \
           f"💰 Commission amount: <b>{amount}</b>\n\n" \
           f"👤 Agent's name: <b>{agent_name}</b>\n\n" \
           "👤 Please enter the <b>internal manager's name</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return INTERNAL_MANAGER_NAME

async def get_internal_manager_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    internal_manager_name = update.message.text
    context.user_data['internal_manager_name'] = internal_manager_name
    logger.info(f"Получено имя внутреннего менеджера: {internal_manager_name}")
    await update.message.delete()

    # Обновляем сообщение бота и переходим к запросу номера кошелька
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')

    # Получаем все предыдущие данные, включая сумму комиссии
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    unit_number = context.user_data['unit_number']
    price = context.user_data['price']
    manager_contact = context.user_data['manager_contact']
    agency_name = context.user_data['agency_name']
    agency_commission_percent = context.user_data['agency_commission_percent']
    amount = context.user_data['amount']
    agent_name = context.user_data['agent_name']

    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n" \
           f"💰 Price: <b>{price}</b>\n" \
           f"📞 Manager's contact: <b>{manager_contact}</b>\n\n" \
           f"🏢 Agency name: <b>{agency_name}</b>\n\n" \
           f"💼 Agency commission: <b>{agency_commission_percent}%</b>\n\n" \
           f"💰 Commission amount: <b>{amount}</b>\n\n" \
           f"👤 Agent's name: <b>{agent_name}</b>\n\n" \
           f"👤 Internal manager's name: <b>{internal_manager_name}</b>\n\n" \
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
    logger.info(f"Получены детали (номер кошелька): {details}")
    await update.message.delete()

    # Обновляем сообщение бота и переходим к запросу описания
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')

    # Получаем все предыдущие данные
    project_name = context.user_data['project_name']
    client_name = context.user_data['client_name']
    unit_number = context.user_data['unit_number']
    price = context.user_data['price']
    manager_contact = context.user_data['manager_contact']
    agency_name = context.user_data['agency_name']
    agency_commission_percent = context.user_data['agency_commission_percent']
    amount = context.user_data['amount']
    agent_name = context.user_data['agent_name']
    internal_manager_name = context.user_data['internal_manager_name']
    details = context.user_data['details']

    # Формируем новое сообщение с учетом всех данных
    text = f"🏗️ Project name: <b>{project_name}</b>\n" \
           f"👤 Client's name: <b>{client_name}</b>\n" \
           f"🏢 Unit number: <b>{unit_number}</b>\n" \
           f"💰 Price: <b>{price}</b>\n" \
           f"📞 Manager's contact: <b>{manager_contact}</b>\n\n" \
           f"🏢 Agency name: <b>{agency_name}</b>\n\n" \
           f"💼 Agency commission: <b>{agency_commission_percent}%</b>\n\n" \
           f"💰 Commission amount: <b>{amount}</b>\n\n" \
           f"👤 Agent's name: <b>{agent_name}</b>\n\n" \
           f"👤 Internal manager's name: <b>{internal_manager_name}</b>\n\n" \
           f"💳 Wallet number: <b>{details}</b>\n\n" \
           "📝 Please enter <b>description</b>:"

    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )
    return DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text
    context.user_data['description'] = description
    logger.info(f"Получено описание: {description}")

    # Удаляем сообщение пользователя
    await update.message.delete()

    # Изменяем сообщение бота на "Ожидайте, заявка в обработке"
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text="⌛ Ожидайте, заявка в обработке...",
        parse_mode='HTML'
    )

    # Сохраняем заявку
    await save_request(update, context)

    # После сохранения заявки показываем подтверждение
    data = context.user_data
    text = f"🏗️ Project name: <b>{data['project_name']}</b>\n" \
           f"👤 Client name: <b>{data['client_name']}</b>\n" \
           f"🏢 Unit number: <b>{data['unit_number']}</b>\n" \
           f"💰 Price: <b>{data['price']}</b>\n" \
           f"📞 Manager's contact: <b>{data['manager_contact']}</b>\n" \
           f"🏢 Agency name: <b>{data['agency_name']}</b>\n" \
           f"💼 Agency commission: <b>{data['agency_commission_percent']}%</b>\n" \
           f"💰 Commission amount: <b>{data['amount']}</b>\n" \
           f"👤 Agent's name: <b>{data['agent_name']}</b>\n" \
           f"👤 Internal manager's name: <b>{data['internal_manager_name']}</b>\n" \
           f"💳 Wallet number: <b>{data['details']}</b>\n" \
           f"📝 Description: <b>{data['description']}</b>\n\n" \
           "✅ Application submitted, notification sent to the department manager."
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )

    # Очищаем кэш пользователя после сохранения заявки
    context.user_data.clear()
    logger.info("Кэш пользователя очищен после подачи заявки.")

    return ConversationHandler.END

# Функция для сохранения заявки
async def save_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Начинаем сохранение запроса")
    data = context.user_data
    user = update.effective_user

    status = 'Ожидает решения руководителя'
    dateTime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    department = 'Отдел продажКОМИССИИ'

    combined_description = (
        f"🏗️ Project name: {data['project_name']}\n"
        f"👤 Client name:  {data['client_name']}\n"
        f"🏢 Unit number: {data['unit_number']}\n"
        f"💰 Price: {data['price']}\n"
        f"📞 Manager's contact: {data['manager_contact']}\n"
        f"💳 Agency name:  {data['agency_name']}\n"
        f"💼 Agency commission:  {data['agency_commission_percent']}%\n"
        f"💰 Commission amount: {data['amount']}\n"
        f"👤 Agent's name: {data['agent_name']}\n"
        f"👤 Internal manager's name: {data['internal_manager_name']}\n"
        f"💳 Wallet number: {data['details']}\n"
        f"📝 Description: {data['description']}"
    )
    logger.info(f"Объединённое описание: {combined_description}")

    requesterTelegramId = user.id
    requesterTelegramNickname = user.username or ''
    requesterName = get_requester_name(user.id)

    # Вставляем запись в базу данных с полем amount
    conn, cursor = get_db_connection()
    cursor.execute("""
        INSERT INTO requests (status, dateTime, department, amount, description, details,
                              requesterTelegramId, requesterTelegramNickname, requesterName)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        status, dateTime, department, data['amount'], combined_description, data['details'],
        requesterTelegramId, requesterTelegramNickname, requesterName
    ))
    conn.commit()
    conn.close()
    logger.info("Новая заявка успешно добавлена в таблицу 'requests'")

    # Уведомляем руководителей отдела "Отдел продаж"
    logger.info("Получаем Telegram ID глав отдела 'Отдел продажКОМИССИИ'")
    department_heads = get_department_heads('Отдел продажКОМИССИИ')

    notification_text = (
        f"📢 <b>Новая заявка от {requesterName} (@{requesterTelegramNickname})</b>\n"
        f"🆔 <b>Статус:</b> {status}\n"
        f"📅 <b>Дата и время:</b> {dateTime}\n"
        f"{combined_description}\n"
        f"<b>______________________________</b>\n"
        f"🆕 <b>Введите /department_requests,</b> чтобы принять решение по заявке\n"
    )
    logger.info("Отправляем уведомления главам отдела 'Отдел продажКОМИССИИ'")

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
    # Получаем данные перед очисткой
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    # Очищаем данные пользователя
    context.user_data.clear()
    # Очищаем данные чата
    context.chat_data.clear()
    # Удаляем сообщение бота, если нужно
    if bot_message_id and bot_chat_id:
        await context.bot.delete_message(chat_id=bot_chat_id, message_id=bot_message_id)
    # Уведомляем пользователя об отмене
    await update.message.reply_text(
        "🚫 Диалог был отменён.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

# Регистрация обработчиков
def register_handlers(application: Application):
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('comission', comission_command)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            PROJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_project_name)],
            CLIENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_client_name)],
            UNIT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_unit_number)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_price)],
            MANAGER_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_manager_contact)],
            AGENCY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_agency_name)],
            AGENCY_COMMISSION_PERCENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_agency_commission)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            AGENT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_agent_name)],
            INTERNAL_MANAGER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_internal_manager_name)],
            DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_details)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True,
    )
    application.add_handler(conv_handler)

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
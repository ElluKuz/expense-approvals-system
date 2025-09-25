# Standard library imports
import datetime
import sqlite3
import logging
import asyncio
import os

# Third-party imports
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, Document, PhotoSize
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
import validators
import telegram.error

# Используем общий логгер
logger = logging.getLogger('bot')

# Стейты для ConversationHandler
NAME, DEPARTMENT, AMOUNT, DETAILS, DESCRIPTION, ATTACHMENT = range(6)

# Изменим подключение к базе данных, добавив проверку существования таблицы
def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'loyobot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return conn, cursor

# Функция для проверки наличия пользователя в таблице 'team'
def check_user_in_team(telegram_id):
    conn, cursor = get_db_connection()
    logger.info(f"Проверяем наличие пользователя с Telegram ID: {telegram_id} в таблице 'team'")
    
    # Проверим существование таблицы
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='team'")
    if not cursor.fetchone():
        logger.error("Таблица 'team' не существует в базе данных")
        return False
    
    # Выведем содержимое таблицы для отладки
    cursor.execute("SELECT * FROM team")
    all_users = cursor.fetchall()
    logger.info(f"Все пользователи в таблице team: {all_users}")
    
    # Проверим конкретного пользователя
    cursor.execute("SELECT * FROM team WHERE telegramId = ?", (telegram_id,))
    result = cursor.fetchone() is not None
    
    if result:
        logger.info(f"Пользователь найден в таблице 'team': {cursor.fetchone()}")
    else:
        logger.info("Пользователь не найден в таблице 'team'")
    
    conn.close()
    return result

# Функция для получения имени пользователя из таблицы 'team'
def get_requester_name(telegram_id):
    logger.info(f"Получам имя пользователя с Telegram ID: {telegram_id}")
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
    # Получаем соединение и курсор
    conn, cursor = get_db_connection()
    
    cursor.execute('''
        INSERT INTO team (telegramId, telegramNickname, name, position, department)
        VALUES (?, ?, ?, ?, ?)
    ''', (telegram_id, telegram_nickname, name, None, None))
    conn.commit()
    conn.close()  # Закрываем соединение
    
    logger.info("Пользователь успешно добавлен в таблицу 'team'")

# Функция для получения списка отделов
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

# Функция для обрботки команды /request
async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Обработка команды /request")
    telegram_id = update.effective_user.id
    logger.info(f"Telegram ID пользователя: {telegram_id}")

    user_exists = check_user_in_team(telegram_id)
    if not user_exists:
        logger.info("Пользователь не найден, запрашиваем имя")
        await update.message.reply_text(
            "👤 Пожалуйста, введите ваше <b>имя</b>:",
            parse_mode='HTML'
        )
        return NAME
    else:
        logger.info("Пользователь найден, переходим к выбору отдела")
        await choose_department(update, context)
        return DEPARTMENT

# Обработчик для получения имени пользователя
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text
    logger.info(f"Получено имя пользователя: {name}")
    telegram_id = update.effective_user.id
    telegram_nickname = update.effective_user.username or ''
    logger.info(f"Telegram ID: {telegram_id}, Никнейм: {telegram_nickname}")

    add_user_to_team(telegram_id, telegram_nickname, name)
    logger.info("Переходим к выбору отдела")

    # Удаляем предыдущее сообщение пользователя
    await update.message.delete()

    # Отправляем сообщение с выбором отдела и сохраняем его для последующего редактирования
    departments_keyboard = get_departments_keyboard()
    message = await update.message.reply_text(
        "🏢 Пожалуйста, выберите <b>отдел</b>:",
        reply_markup=InlineKeyboardMarkup(departments_keyboard),
        parse_mode='HTML'
    )
    context.user_data['bot_message_id'] = message.message_id
    context.user_data['bot_chat_id'] = message.chat_id

    return DEPARTMENT

# Функция для отображения клавиатуры отделов
def get_departments_keyboard():
    departments = get_departments()
    keyboard = []
    # Формируем двухколоночную клавиатуру
    for i in range(0, len(departments), 2):
        row = []
        row.append(InlineKeyboardButton(departments[i], callback_data=departments[i]))
        if i + 1 < len(departments):
            row.append(InlineKeyboardButton(departments[i + 1], callback_data=departments[i + 1]))
        keyboard.append(row)
    return keyboard

# Функция обработки выбора отдела
async def department_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    department = query.data
    context.user_data['department'] = department
    logger.info(f"Пользователь выбрал отдел: {department}")

    # Удаляем предыдущее сообщение пользователя
    await query.message.delete()

    # Обновляем сообщение бота, добавляя выбранный отдел
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    text = f"🏢 Отдел: <b>{department}</b>\n\n" \
           "💰 Пожалуйста, введите <b>сумму запроса</b> (<b>только ЦЕЛОЕ ЧИСЛО в USD</b>):"
    message = await context.bot.send_message(
        chat_id=bot_chat_id,
        text=text,
        parse_mode='HTML'
    )
    context.user_data['bot_message_id'] = message.message_id

    return AMOUNT

# Обработчик для получения суммы
async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Валидация: только целое число
    try:
        amount_int = int(text)
    except ValueError:
        await update.message.reply_text(
            "⚠️ Пожалуйста, введите сумму целым числом (только цифры, без точек и запятых)."
        )
        return AMOUNT

    # Сохраняем как int
    context.user_data['amount'] = amount_int
    logger.info(f"Пользователь ввел сумму: {amount_int}")


    # Удаляем предыдущее сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота, добавляя введенную сумму
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    department = context.user_data['department']
    amount = context.user_data['amount']
    text = f"🏢 Отдел: <b>{department}</b>\n" \
           f"💰 Сумма: <b>{amount}</b>\n\n" \
           "💳 Пожалуйста, введите <b>адрес кошелька USDT TRC-20</b>"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )

    return DETAILS

# Обработчик для получения деталей
async def get_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    details = update.message.text
    context.user_data['details'] = details
    logger.info(f"Пользователь ввел детали: {details}")

    # Удаляем предыдущее сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение б��та, добавляя детали
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    department = context.user_data['department']
    amount = context.user_data['amount']
    text = f"🏢 Отдел: <b>{department}</b>\n" \
           f"💰 Сумма: <b>{amount}</b>\n" \
           f"💳 Детали: <b>{details}</b>\n\n" \
           "📝 Пожалуйста, введите <b>описание</b>:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )

    return DESCRIPTION

# Обработчик для получения описания
async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text
    context.user_data['description'] = description
    logger.info(f"Пользователь ввел описание: {description}")

    # Удаляем предыдущее сообщение пользователя
    await update.message.delete()

    # Обновляем сообщение бота, добавляя описание
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    department = context.user_data['department']
    amount = context.user_data['amount']
    details = context.user_data['details']
    text = f"🏢 Отдел: <b>{department}</b>\n" \
           f"💰 Сумма: <b>{amount}</b>\n" \
           f"💳 Детали: <b>{details}</b>\n" \
           f"📝 Описание: <b>{description}</b>\n\n" \
           "📎 Пожалуйста, отправьте <b>вложения</b> (до 5 файлов) или введите <b>/done</b>, чтобы завершить:"
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )

    return ATTACHMENT

# Обработчик для получения вложений
async def get_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'files' not in context.user_data:
        context.user_data['files'] = []
        context.user_data['file_messages'] = []
        logger.info("Инициализируем список файлов пользователя")
    if 'links' not in context.user_data:
        context.user_data['links'] = []
        logger.info("Инициализируем список ссылок пользователя")

    message = update.message

    # Проверяем тип сообще��ия и обрабатываем вложения
    if message.document or message.photo:
        if message.document:
            file = message.document
            file_id = file.file_id
            file_name = file.file_name
        elif message.photo:
            file = message.photo[-1]
            file_id = file.file_id
            file_name = f"{file_id}.jpg"

        # Скачиваем файл
        new_file = await context.bot.get_file(file_id)

        # Путь к каталогу для вложений
        attachments_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'attachments')

        # Убедимся, что каталог существует
        os.makedirs(attachments_dir, exist_ok=True)

        # Путь для сохранения файла
        file_path = os.path.join(attachments_dir, file_name)

        # Сохраняем файл
        await new_file.download_to_drive(file_path)
        logger.info(f"Файл сохранен: {file_path}")

        # Сохраняем путь к файлу в контексте пользователя
        context.user_data['files'].append(file_path)

        # Удаляем сообщение пользователя с файло
        await message.delete()

        # Сообщаем пользов��телю о получении файла
        if len(context.user_data['files']) == 1:
            reply_text = "📎 Файл получен и сохранен. Вы можете отправить ещё файлы или ссылки или ввести <b>/done</b>, чтобы завершить."
        else:
            reply_text = "📎 Файлы получены и сохранены. Вы можете отправить ещё файлы или ссылки или ввести <b>/done</b>, чтобы завершить."
        
        file_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=reply_text,
            parse_mode='HTML'
        )
        
        # Сохраняем идентификатор сообщения для последующего удаления
        context.user_data['file_messages'].append(file_message.message_id)

        return ATTACHMENT
    elif message.text:
        # Проверяем, является ли сообщение ссылкой
        if validators.url(message.text):
            context.user_data['links'].append(message.text)
            logger.info(f"Пользователь отправил ссылку: {message.text}")

            # Удаляем сообщение пользователя
            await message.delete()

            # Отправляем уведомление пользователю
            link_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text='🔗 <b>Ссылка получена.</b> Вы можете отправить ещё файлы или ссылки или ввести <b>/done</b>, чтобы завершить.',
                parse_mode='HTML'
            )
            # Сохраняе идентификатор сообщения для последующего удаления
            context.user_data['file_messages'].append(link_message.message_id)
            return ATTACHMENT
        elif message.text in ['/skip', '/done']:
            return await process_request(update, context)
        else:
            logger.info("Пользователь отправил неподдерживаемый тип сообщения")
            await message.reply_text(
                '⚠️ Пожалуйста, отправьте документ или фото.',
                parse_mode='HTML'
            )
            return ATTACHMENT
    else:
        logger.info("Пользователь отправил неподдерживаемый тип сообщения")
        await message.reply_text(
            '⚠️ Пожалуйста, отправьте документ, фото или сылку на документ или введите <b>/done</b>, чтобы завершить.',
            parse_mode='HTML'
        )
        return ATTACHMENT

# Обновляем функцию для сохранения запроса
async def save_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Начинаем сохранение запроса")
    data = context.user_data
    user = update.effective_user

    conn, cursor = get_db_connection()

    status = 'Ожидает решения руководителя'
    dateTime = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    department = data['department']
    amount = data['amount']
    description = data['description']
    details = data['details']
    files = data.get('files', [])
    links = data.get('links', [])

    # Объединяем пути к файлам и ссылки
    attachments = files + links
    attachments_links = ', '.join(attachments)

    requesterTelegramId = user.id
    requesterTelegramNickname = user.username or ''
    requesterName = get_requester_name(user.id)

    # Получаем ID руководителя отдела
    logger.info("Получаем Telegram ID глав отдела")
    department_heads = get_department_heads(department)
    department_head_id = department_heads[0] if department_heads else None


    # Добавлем запись в таблицу 'requests' без указания requestId
    cursor.execute('''
        INSERT INTO requests (
            status, dateTime, department, amount, description, details,
            attachment, requesterTelegramId, requesterTelegramNickname, requesterName,
            departmentHeadTelegramId
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        status, dateTime, department, amount, description, details,
        attachments_links, requesterTelegramId, requesterTelegramNickname, requesterName,
        department_head_id
    ))

    conn.commit()
    conn.close()
    logger.info("Новая заявка успешно добавлена в таблицу 'requests'")

    # Уведомляем руководителей отде��а
    logger.info("Получаем Telegram ID глав отдела")
    department_heads = get_department_heads(department)

    # Формируем текст уведомления без ссылок на вложения
    notification_text = (
        f"📢 <b>Новая заявка от {requesterName} (@{requesterTelegramNickname})</b>\n"
        f"🆔 <b>Статус:</b> {status}\n"
        f"📅 <b>Дата и время:</b> {dateTime}\n"
        f"🏢 <b>Отдел:</b> {department}\n"
        f"💰 <b>Сумма:</b> {amount}\n"
        f"📝 <b>Описание:</b> {description}\n"
        f"💳 <b>Детали:</b> {details}\n"
        f"📎 <b>Вложения:</b> {attachments_links}\n"
        f"<b>______________________________</b>\n"
        f"🆕 <b>Введите /department_requests,</b> чтобы принять решение по заявке\n"
    )

    # Отправляем уведомления и вложения руководителям отдела
    logger.info("Отправляем уведомления и вложения главам отдела")
    for head_id in department_heads:
        try:
            # Отправляем уведомление
            await context.bot.send_message(chat_id=head_id, text=notification_text, parse_mode='HTML')
            logger.info(f"Уведомление отправлено пользователю с ID: {head_id}")

            # Отправляем вложения (файлы)
            for file_path in files:
                with open(file_path, 'rb') as file:
                    await context.bot.send_document(chat_id=head_id, document=file)
                logger.info(f"Вложение {file_path} отправлено пользователю с ID: {head_id}")

            # Отправляем ссылки, если они есть
            if links:
                links_text = "\n".join(links)
                await context.bot.send_message(chat_id=head_id, text=f"🔗 <b>Ссылки:</b>\n{links_text}", parse_mode='HTML')
                logger.info(f"Ссылки отправлены пользователю с ID: {head_id}")

        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {head_id}: {e}")

# Функция для получения Telegram ID глав отдела
def get_department_heads(department):
    logger.info(f"Получаем Telegram ID глав отдела: {department}")
    conn, cursor = get_db_connection()
    cursor.execute('''
        SELECT telegramId FROM team WHERE department = ? AND position = 'head'
    ''', (department,))
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

    if update.message:
        await update.message.reply_text(
            "🚫 Диалог был отменён.",
            parse_mode='HTML'
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "🚫 Диалог был отменён.",
            parse_mode='HTML'
        )
    return ConversationHandler.END

# Добавьте это определение функции после других функций или в подходящее место в вашем коде

# Функция для отображения списка отделов
async def choose_department(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Отправляем список отделов для выбора")
    departments_keyboard = get_departments_keyboard()

    # Отправляем сообщение с выбором отдела и сохраняем его для дальнейшего редактирования
    message = await update.message.reply_text(
        "🏢 Пожалуйста, выберите <b>отдел</b>:",
        reply_markup=InlineKeyboardMarkup(departments_keyboard),
        parse_mode='HTML'
    )
    context.user_data['bot_message_id'] = message.message_id
    context.user_data['bot_chat_id'] = message.chat_id

# Регистрация обработчиков
def register_handlers(application: Application):
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('request', request_command)],
        states={
            NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_name),
                CommandHandler('cancel', cancel)
            ],
            DEPARTMENT: [
                CallbackQueryHandler(department_chosen),
                CommandHandler('cancel', cancel)
            ],
            AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount),
                CommandHandler('cancel', cancel)
            ],
            DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_details),
                CommandHandler('cancel', cancel)
            ],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_description),
                CommandHandler('cancel', cancel)
            ],
            ATTACHMENT: [
                MessageHandler(
                    filters.Document.ALL | filters.PHOTO | filters.TEXT & ~filters.COMMAND,
                    get_attachment
                ),
                CommandHandler('cancel', cancel),
                CommandHandler('skip', process_request),
                CommandHandler('done', process_request)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )
    application.add_handler(conv_handler)

async def process_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Пользователь завершил отправку вложений")

    # Удаляем сообщение пользователя с командой /done
    try:
        await update.message.delete()
    except telegram.error.BadRequest as e:
        logger.warning(f"Не удалось удалить сообщение пользователя: {e}")

    # Удаляем сообщения с уведомлениями о получении файлов и ссылок
    for msg_id in context.user_data.get('file_messages', []):
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            logger.info(f"Сообщение {msg_id} успешно удалено")
        except telegram.error.BadRequest as e:
            logger.warning(f"Не удалось удалить сообщение {msg_id}: {e}")
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения {msg_id}: {e}", exc_info=True)

    # Изменяем сообщение бота на "Ожидайте, заявка в обработке"
    bot_message_id = context.user_data.get('bot_message_id')
    bot_chat_id = context.user_data.get('bot_chat_id')
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text="Ожидайте, заявка в обработке...",
        parse_mode='HTML'
    )

    # Сохраняем заявку
    await save_request(update, context)

    # **Получаем необходимые данные перед очисткой**
    department = context.user_data['department']
    amount = context.user_data['amount']
    details = context.user_data['details']
    description = context.user_data['description']

    # **Теперь можно очистить данные пользователя**
    context.user_data.clear()

    # После очистки данных сообщаем пользователю о результате
    text = (
        f"🏢 Отдел: <b>{department}</b>\n"
        f"💰 Сумма: <b>{amount}</b>\n"
        f"💳 Детали: <b>{details}</b>\n"
        f"📝 Описание: <b>{description}</b>\n\n"
        "✅ Заявка подана, уведомление руководителю отдела отправлено."
    )
    await context.bot.edit_message_text(
        chat_id=bot_chat_id,
        message_id=bot_message_id,
        text=text,
        parse_mode='HTML'
    )

    return ConversationHandler.END

import sys
print("Начало выполнения скрипта:", sys.executable)
print("Скрипт выполнен успешно.")









from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
import sqlite3
import logging
import datetime
import os
from google_sync import sync_request
logger = logging.getLogger('bot')

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'loyobot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return conn, cursor

# Функция проверки прав доступа пользователя (CFO)
def check_user_access(telegram_id):
    logger.info(f"Проверяем права доступа пользователя с Telegram ID: {telegram_id}")
    conn, cursor = get_db_connection()
    cursor.execute("SELECT position FROM team WHERE telegramId = ?", (telegram_id,))
    results = cursor.fetchall()
    conn.close()

    # безопасно приводим к нижнему регистру и отбрасываем None
    positions = [(row[0] or "").lower() for row in results] if results else []
    if "cfo" in positions:
        logger.info("Пользователь CFO, доступ разрешён")
        return True
    else:
        logger.info("У пользователя нет прав CFO")
        return False

# Функция получения заявок для CFO
def get_cfo_requests():
    logger.info("Получаем заявки, ожидающие решения CFO")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("""
            SELECT * FROM requests
            WHERE status = 'Одобрено руководителем отдела, ожидает решения финансового отдела'
        """)

        requests = cursor.fetchall()
        logger.info(f"Найдено {len(requests)} заявок для CFO")
        return requests
    except Exception as e:
        logger.error(f"Ошибка при получении заявок: {e}")
        return []
    finally:
        conn.close()

# Состояния для ConversationHandler
REQUEST_NAVIGATION, REASON, CORRECTION_REASON = range(3)

# Обработчик команды /cfo
async def cfo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    telegram_nickname = update.effective_user.username
    logger.info(f"Пользователь {telegram_nickname} ({telegram_id}) ввёл команду /cfo")

    # Проверяем права доступа
    if not check_user_access(telegram_id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END

    # Получаем заявки, ожидающие решения CFO
    requests = get_cfo_requests()
    if not requests:
        await update.message.reply_text("Нет заявок, ожидающих вашего решения.")
        return ConversationHandler.END

    # Сохраняем заявки в user_data
    context.user_data['requests'] = requests
    context.user_data['current_request_index'] = 0
    context.user_data['attachment_messages'] = []

    # Отображаем первую заявку
    await show_request(update, context)
    return REQUEST_NAVIGATION

# Обработчик нажатия на кнопки
async def decision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'next_request':
        # Переходим к следующей заявке
        context.user_data['current_request_index'] += 1
        if context.user_data['current_request_index'] >= len(context.user_data['requests']):
            context.user_data['current_request_index'] = 0
        await show_request(update, context)
        return REQUEST_NAVIGATION

    elif data == 'prev_request':
        # Переходим к предыдущей заявке
        context.user_data['current_request_index'] -= 1
        if context.user_data['current_request_index'] < 0:
            context.user_data['current_request_index'] = len(context.user_data['requests']) - 1
        await show_request(update, context)
        return REQUEST_NAVIGATION

    elif data.startswith('cfo_approve_') or data.startswith('cfo_reject_'):
        # Логика одобрения / отклонения
        requestId = int(data.split('_')[-1])
        telegram_id = update.effective_user.id
        telegram_nickname = update.effective_user.username
        user_name = get_user_name_by_telegram_id(telegram_id)

        if data.startswith('cfo_approve_'):
            # Обработка одобрения
            await query.edit_message_text("Пожалуйста, ожидайте, заявка одобряется.")

            conn, cursor = get_db_connection()
            status = 'Одобрено финансовым отделом, передано на оплату'
            decision = 'Одобрено'
            decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            try:
                logger.info("Обновляем статус заявки в базе данных (CFO approve)")
                cursor.execute("""
                    UPDATE requests
                    SET status = ?,
                        CFOTelegramId = ?,
                        CFOTelegramNickname = ?,
                        CFOName = ?,
                        CFODecision = ?,
                        CFODecisionDateTime = ?
                    WHERE requestId = ?
                """, (status, telegram_id, telegram_nickname, user_name, decision, decision_date, requestId))
                conn.commit()
            except Exception as e:
                logger.error(f"Ошибка при обновлении заявки: {e}")
                await query.edit_message_text("Произошла ошибка при обновлении заявки.")
                return ConversationHandler.END
            finally:
                conn.close()
                try:
                    sync_request(requestId)
                except Exception as e:
                    logger.error(f"sync_request failed for {requestId}: {e}")

            # Уведомляем заявителя и руководителя отдела
            try:
                conn, cursor = get_db_connection()
                cursor.execute("SELECT * FROM requests WHERE requestId = ?", (requestId,))
                request = cursor.fetchone()
                conn.close()

                if request:
                    requester_id = request[8]
                    department_head_id = request[11]
                    dateTime = request[2]
                    department = request[3]
                    amount = request[4]
                    description = request[5]
                    details = request[6]
                    requesterName = request[10]
                    requesterTelegramNickname = request[9]

                    notification_text = (
                        f"Вашу заявку рассмотрели.\n"
                        f"📄 <b>Номер заявки:</b> {requestId}\n"
                        f"🆔 <b>Статус:</b> {status}\n"
                        f"📅 <b>Дата и время:</b> {dateTime}\n"
                        f"🏢 <b>Отдел:</b> {department}\n"
                        f"💰 <b>Сумма:</b> {amount}\n"
                        f"📝 <b>Описание:</b> {description}\n"
                        f"💳 <b>Кошелек:</b> {details}\n"
                        f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
                        f"👤 <b>CFO:</b> {user_name} (@{telegram_nickname})\n"
                        f"📅 <b>Дата решения:</b> {decision_date}\n"
                        f"📝 <b>Решение:</b> {decision}"
                    )
                    await context.bot.send_message(chat_id=requester_id, text=notification_text, parse_mode='HTML')
                    await context.bot.send_message(chat_id=department_head_id, text=notification_text, parse_mode='HTML')
                else:
                    logger.error("Не удалось найти заявку в базе данных")
                    await query.edit_message_text("Не удалось найти заявку в базе данных.")
                    return ConversationHandler.END

            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления: {e}")

            # Удаляем заявку из списка
            current_index = context.user_data['current_request_index']
            context.user_data['requests'].pop(current_index)

            if context.user_data['requests']:
                if current_index >= len(context.user_data['requests']):
                    context.user_data['current_request_index'] = 0
                await show_request(update, context)
                return REQUEST_NAVIGATION
            else:
                await query.edit_message_text("Все заявки обработаны.")
                context.user_data.clear()
                return ConversationHandler.END

        elif data.startswith('cfo_reject_'):
            # Обработка отклонения
            context.user_data['request_id'] = requestId
            context.user_data['telegram_id'] = telegram_id
            context.user_data['telegram_nickname'] = telegram_nickname
            context.user_data['user_name'] = user_name

            await query.edit_message_text("Пожалуйста, укажите причину отклонения заявки.")
            return REASON

    elif data.startswith('cfo_correction_'):
        # Обработка отправки заявки "На исправление"
        requestId = int(data.split('_')[-1])
        telegram_id = update.effective_user.id
        telegram_nickname = update.effective_user.username
        user_name = get_user_name_by_telegram_id(telegram_id)

        context.user_data['request_id'] = requestId
        context.user_data['telegram_id'] = telegram_id
        context.user_data['telegram_nickname'] = telegram_nickname
        context.user_data['user_name'] = user_name

        await query.edit_message_text("Пожалуйста, введите комментарий для заявителя, что нужно исправить или уточнить.")
        return CORRECTION_REASON

    else:
        await query.edit_message_text("Неизвестное действие.")
        return ConversationHandler.END

# Обработчик для ввода причины (комментария) при кнопке «На исправление»
async def correction_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    telegram_id = context.user_data['telegram_id']
    telegram_nickname = context.user_data['telegram_nickname']
    user_name = context.user_data['user_name']
    request_id = context.user_data['request_id']

    logger.info(f"CFO {telegram_nickname} указал комментарий для исправления: {comment}")

    # Устанавливаем статус "Требует корректировки", сохраняем комментарий
    conn, cursor = get_db_connection()
    status = 'Требует корректировки'
    decision = 'На исправление'
    decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        logger.info("Обновляем статус заявки на 'Требует корректировки'")
        cursor.execute("""
            UPDATE requests
            SET status = ?,
                CFOTelegramId = NULL,
                CFOTelegramNickname = NULL,
                CFOName = NULL,
                CFODecision = NULL,
                CFODecisionDateTime = NULL,
                comment = ?
            WHERE requestId = ?
        """, (status, comment, request_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении заявки: {e}")
        await update.message.reply_text("Произошла ошибка при обновлении заявки.")
        return ConversationHandler.END
    finally:
        conn.close()
        try:
            sync_request(request_id)
        except Exception as e:
            logger.error(f"sync_request failed for {request_id}: {e}")

    # Уведомляем заявителя (и по желанию – руководителя)
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM requests WHERE requestId = ?", (request_id,))
        request = cursor.fetchone()
        conn.close()

        if request:
            logger.info(f"Данные заявки: {request}")
            requester_id = request[8]
            dateTime = request[2]
            department = request[3]
            amount = request[4]
            description = request[5]
            details = request[6]
            requesterTelegramNickname = request[9]
            requesterName = request[10]

            notification_text = (
                f"Ваша заявка (ID: {request_id}) требует корректировки.\n\n"
                f"Комментарий:\n<b>{comment}</b>\n\n"
                "Чтобы внести изменения, введите команду /fix_request."
            )
            await context.bot.send_message(chat_id=requester_id, text=notification_text, parse_mode='HTML')
            logger.info(f"Уведомление отправлено заявителю {requester_id}")
        else:
            logger.error(f"Заявка с ID {request_id} не найдена")
            await update.message.reply_text("Не удалось найти заявку в базе данных.")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления заявителю: {e}")

    # Удаляем заявку из списка (статус больше не «Ожидает решения финансового отдела»)
    current_index = context.user_data['current_request_index']
    context.user_data['requests'].pop(current_index)

    # Удаляем сообщение с запросом комментария
    await update.message.delete()
# Функция проверки прав доступа пользователя (CFO)
    # Переходим к следующей заявке (если есть)
    if context.user_data['requests']:
        if current_index >= len(context.user_data['requests']):
            context.user_data['current_request_index'] = 0
        await show_request(update, context)
        return REQUEST_NAVIGATION
    else:
        await update.message.reply_text("Все заявки обработаны.")
        return ConversationHandler.END

# Обработчик для получения причины отклонения
async def reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text
    telegram_id = context.user_data['telegram_id']
    telegram_nickname = context.user_data['telegram_nickname']
    user_name = context.user_data['user_name']
    request_id = context.user_data['request_id']

    logger.info(f"Пользователь {telegram_nickname} указал причину отклонения: {reason}")

    conn, cursor = get_db_connection()
    status = 'Отклонено финансовым отделом'
    decision = 'Отклонено'
    decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        logger.info("Обновляем статус заявки (CFO reject) с причиной")
        cursor.execute("""
            UPDATE requests
            SET status = ?,
                CFOTelegramId = ?,
                CFOTelegramNickname = ?,
                CFOName = ?,
                CFODecision = ?,
                CFODecisionDateTime = ?,
                comment = ?
            WHERE requestId = ?
        """, (status, telegram_id, telegram_nickname, user_name, decision, decision_date, reason, request_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении заявки: {e}")
        await update.message.reply_text("Произошла ошибка при обновлении заявки.")
        return ConversationHandler.END
    finally:
        conn.close()
        try:
            sync_request(request_id)
        except Exception as e:
            logger.error(f"sync_request failed for {request_id}: {e}")

    # Уведомляем заявителя и руководителя отдела
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM requests WHERE requestId = ?", (request_id,))
        request = cursor.fetchone()
        conn.close()

        if request:
            requester_id = request[8]
            department_head_id = request[11]
            dateTime = request[2]
            department = request[3]
            amount = request[4]
            description = request[5]
            details = request[6]
            requesterName = request[10]
            requesterTelegramNickname = request[9]

            notification_text = (
                f"Вашу заявку отклонили.\n"
                f"📄 <b>Номер заявки:</b> {request_id}\n"
                f"🆔 <b>Статус:</b> {status}\n"
                f"📅 <b>Дата и время:</b> {dateTime}\n"
                f"🏢 <b>Отдел:</b> {department}\n"
                f"💰 <b>Сумма:</b> {amount}\n"
                f"📝 <b>Описание:</b> {description}\n"
                f"💳 <b>Детали:</b> {details}\n"
                f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
                f"👤 <b>CFO:</b> {user_name} (@{telegram_nickname})\n"
                f"📅 <b>Дата решения:</b> {decision_date}\n"
                f"📝 <b>Решение:</b> {decision}\n"
                f"📝 <b>Причина отклонения:</b> {reason}"
            )
            await context.bot.send_message(chat_id=requester_id, text=notification_text, parse_mode='HTML')
            await context.bot.send_message(chat_id=department_head_id, text=notification_text, parse_mode='HTML')
            logger.info(f"Уведомления отправлены заявителю {requester_id} и руководителю {department_head_id}")
        else:
            logger.error("Не удалось найти заявку в базе данных")
            await update.message.reply_text("Не удалось найти заявку в базе данных.")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления: {e}")

    # Удаляем заявку из списка
    current_index = context.user_data['current_request_index']
    context.user_data['requests'].pop(current_index)

    # Удаляем сообщение с запросом причины
    await update.message.delete()

    # Проверяем, остались ли заявки
    if context.user_data['requests']:
        if current_index >= len(context.user_data['requests']):
            context.user_data['current_request_index'] = 0
        await show_request(update, context)
        return REQUEST_NAVIGATION
    else:
        await context.bot.send_message(chat_id=telegram_id, text="Все заявки обработаны.")
        return ConversationHandler.END

def get_user_name_by_telegram_id(telegram_id):
    logger.info(f"Получаем имя пользователя с Telegram ID: {telegram_id}")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("SELECT name FROM team WHERE telegramId = ?", (telegram_id,))
        row = cursor.fetchone()
        if row:
            user_name = row[0]
            logger.info(f"Имя пользователя: {user_name}")
            return user_name
        else:
            logger.info("Имя пользователя не найдено")
            return None
    except Exception as e:
        logger.error(f"Ошибка при получении имени пользователя: {e}")
        return None
    finally:
        conn.close()

async def show_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показываем текущую заявку CFO, добавляем кнопки:
      - Одобрить
      - Отклонить
      - На исправление
      - Стрелки навигации
    """
    for msg_id in context.user_data.get('attachment_messages', []):
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения с вложением: {e}")
    context.user_data['attachment_messages'] = []

    requests = context.user_data['requests']
    index = context.user_data['current_request_index']
    request = requests[index]

    requestId = request[0]
    dateTime = request[2]
    amount = request[4]
    description = request[5]
    details = request[6]
    attachment = request[7]
    requesterTelegramId = request[8]
    requesterTelegramNickname = request[9]
    requesterName = request[10]

    message_text = (
        f"🔎 <b>Заявка {index + 1} из {len(requests)}</b>\n"
        f"📄 <b>Номер заявки:</b> {requestId}\n"
        f"📅 <b>Дата и время:</b> {dateTime}\n"
        f"💰 <b>Сумма:</b> {amount}\n"
        f"📝 <b>Описание:</b> {description}\n"
        f"💳 <b>Детали:</b> {details}\n"
        f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text=message_text, parse_mode='HTML')
        message_to_reply = update.callback_query.message
    else:
        sent_message = await update.message.reply_text(text=message_text, parse_mode='HTML')
        message_to_reply = sent_message

    # Прикрепляем вложения (файлы или ссылки)
    if attachment:
        attachments = attachment.split(', ')
        for file_path in attachments:
            if file_path.startswith('http'):
                attachment_text = f"🔗 <a href='{file_path}'>{file_path}</a>"
                sent_links = await context.bot.send_message(
                    chat_id=update.effective_chat.id, text=attachment_text,
                    parse_mode='HTML', disable_web_page_preview=True
                )
                context.user_data['attachment_messages'].append(sent_links.message_id)
            else:
                try:
                    with open(file_path, 'rb') as file:
                        sent_file = await context.bot.send_document(chat_id=update.effective_chat.id, document=file)
                        context.user_data['attachment_messages'].append(sent_file.message_id)
                        logger.info(f"Вложение {file_path} отправлено")
                except Exception as e:
                    logger.error(f"Не удалось отправить вложение {file_path}: {e}")

    # Третья кнопка "На исправление"
    keyboard_buttons = [
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f"cfo_approve_{requestId}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"cfo_reject_{requestId}"),
            InlineKeyboardButton("✏️ На исправление", callback_data=f"cfo_correction_{requestId}")
        ],
        [
            InlineKeyboardButton("⬅️", callback_data='prev_request'),
            InlineKeyboardButton("➡️", callback_data='next_request')
        ]
    ]
    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    await message_to_reply.edit_reply_markup(reply_markup=keyboard)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Пользователь отменил диалог CFO")
    context.user_data.clear()
    if update.message:
        await update.message.reply_text("🚫 Действие отменено.", parse_mode='HTML')
    else:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🚫 Действие отменено.", parse_mode='HTML')
    return ConversationHandler.END

def register_handlers(application):
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('cfo', cfo_handler)],
        states={
            REQUEST_NAVIGATION: [CallbackQueryHandler(decision_handler)],
            REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reason_handler),
                CommandHandler('cancel', cancel)
            ],
            CORRECTION_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, correction_reason_handler),
                CommandHandler('cancel', cancel)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
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
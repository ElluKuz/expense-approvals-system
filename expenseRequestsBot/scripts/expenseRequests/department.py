# /home/loyo/projects/loyoTelegramBot/expenseRequestsBot/scripts/expenseRequests/department.py

import logging
import os
import datetime
import sqlite3
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from google_sync import sync_request
logger = logging.getLogger('bot')

# Состояния для ConversationHandler
REQUEST_NAVIGATION, REASON = range(2)
# Добавляем новый стейт для комментария при отправке «На исправление»
CORRECTION_REASON = 3

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'loyobot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return conn, cursor

# Функция проверки прав доступа пользователя
def check_user_access(telegram_id):
    logger.info(f"Проверяем права доступа пользователя с Telegram ID: {telegram_id}")
    departments = get_user_departments(telegram_id)
    if departments:
        logger.info("Пользователь имеет права доступа")
        return True
    else:
        logger.info("У пользователя нет прав доступа")
        return False

# Функция получения отделов пользователя
def get_user_departments(telegram_id):
    logger.info(f"Получаем отделы пользователя с Telegram ID: {telegram_id}")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("""
            SELECT department FROM team
            WHERE telegramId = ? AND position = 'head'
        """, (telegram_id,))
        departments = [row[0] for row in cursor.fetchall() if row[0]]
        logger.info(f"Отделы пользователя: {departments}")
        return departments
    except Exception as e:
        logger.error(f"Ошибка при получении отделов пользователя: {e}")
        return []
    finally:
        conn.close()

# Функция получения заявок отделов
def get_department_requests(departments):
    logger.info(f"Получаем заявки отделов: {departments}")
    conn, cursor = get_db_connection()
    try:
        placeholders = ','.join('?' * len(departments))
        query = f"""
            SELECT * FROM requests
            WHERE department IN ({placeholders})
            AND status = 'Ожидает решения руководителя'
        """
        cursor.execute(query, departments)
        requests = cursor.fetchall()
        logger.info(f"Найдено {len(requests)} заявок")
        return requests
    except Exception as e:
        logger.error(f"Ошибка при получении заявок отделов: {e}")
        return []
    finally:
        conn.close()

# Обработчик команды /department_requests
async def department_requests_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    telegram_nickname = update.effective_user.username
    logger.info(f"Пользователь {telegram_nickname} ({telegram_id}) запросил список заявок")

    # Проверяем права доступа
    if not check_user_access(telegram_id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END

    # Получаем отделы пользователя
    departments = get_user_departments(telegram_id)
    if not departments:
        await update.message.reply_text("Не удалось определить ваши отделы.")
        return ConversationHandler.END

    # Сохраняем отделы в user_data
    context.user_data['departments'] = departments

    # Store 'department' key if expected elsewhere
    if departments:
        context.user_data['department'] = departments[0]  # Assuming the first department
    else:
        await update.message.reply_text("У вас не закреплено ни одного отдела.")
        return ConversationHandler.END

    # Получаем заявки по всем отделам пользователя
    requests = get_department_requests(departments)
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

# Функция для отображения заявки
async def show_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Удаляем старые сообщения с вложениями, если они есть
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
        f"🆔 <b>Номер заявки:</b> {requestId}\n"
        f"📅 <b>Дата и время:</b> {dateTime}\n"
        f"💰 <b>Сумма:</b> {amount}\n"
        f"📝 <b>Описание:</b> {description}\n"
        f"💳 <b>Детали:</b> {details}\n"
        f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
    )

    # Кнопки управления
    keyboard_buttons = [
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f"department_approve_{requestId}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"department_reject_{requestId}"),
            InlineKeyboardButton("✏️ На исправление", callback_data=f"department_correction_{requestId}")
        ],
        [
            InlineKeyboardButton("⬅️", callback_data='prev_request'),
            InlineKeyboardButton("➡️", callback_data='next_request')
        ]
    ]

    # Если пользователь является руководителем 'Отдел продаж', добавляем кнопку 'Оплачено'
    # Только для заявок комиссии добавляем кнопку 'Оплачено'
    # request[3] — это поле department из БД
    current_dept = request[3]
    if current_dept == 'Отдел продажКОМИССИИ' and 'Отдел продажКОМИССИИ' in context.user_data.get('departments', []):
        keyboard_buttons.append([
            InlineKeyboardButton("💵 Оплачено", callback_data=f"department_paid_{requestId}")
        ])

    keyboard = InlineKeyboardMarkup(keyboard_buttons)

    if update.callback_query:
        await update.callback_query.edit_message_text(text=message_text, parse_mode='HTML')
        await update.callback_query.edit_message_reply_markup(reply_markup=keyboard)
    else:
        await update.message.reply_text(text=message_text, parse_mode='HTML', reply_markup=keyboard)


    # Отправляем вложения, если они есть
    if attachment:
        attachments = attachment.split(', ')
        attachment_text = "📎 <b>Вложения:</b>\n"
        for file_path in attachments:
            if file_path.startswith('http'):
                # Это ссылка
                attachment_text += f"🔗 <a href='{file_path}'>{file_path}</a>\n"
            else:
                # Это файл
                try:
                    with open(file_path, 'rb') as file:
                        sent_file = await context.bot.send_document(chat_id=update.effective_chat.id, document=file)
                        context.user_data['attachment_messages'].append(sent_file.message_id)
                        logger.info(f"Вложение {file_path} отправлено")
                except Exception as e:
                    logger.error(f"Не удалось отправить вложение {file_path}: {e}")
        # Отправляем текст с ссылками (если были)
        if '🔗' in attachment_text:
            sent_links = await context.bot.send_message(chat_id=update.effective_chat.id, text=attachment_text, parse_mode='HTML', disable_web_page_preview=True)
            context.user_data['attachment_messages'].append(sent_links.message_id)



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

    elif data.startswith('department_approve_') or data.startswith('department_reject_'):
        requestId = int(data.split('_')[-1])
        telegram_id = update.effective_user.id
        telegram_nickname = update.effective_user.username
        user_name = get_user_name_by_telegram_id(telegram_id)

        if data.startswith('department_approve_'):
            # Обработка одобрения
            await query.edit_message_text("Пожалуйста, ожидайте, заявка одобряется.")

            conn, cursor = get_db_connection()
            status = 'Одобрено руководителем отдела, ожидает решения финансового отдела'
            decision = 'Одобрено'
            decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            try:
                logger.info("Обновляем статус заявки в базе данных")
                cursor.execute("""
                    UPDATE requests
                    SET status = ?,
                        departmentHeadTelegramId = ?,
                        departmentHeadTelegramNickname = ?,
                        departmentHeadName = ?,
                        departmentHeadDecision = ?,
                        departmentHeadDecisionDateTime = ?
                    WHERE requestId = ?
                """, (status, telegram_id, telegram_nickname, user_name, decision, decision_date, requestId))
                conn.commit()
                logger.info("Заявка успешно обновлена")
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

            # Уведомляем заявителя
            try:
                conn, cursor = get_db_connection()
                cursor.execute("SELECT * FROM requests WHERE requestId = ?", (requestId,))
                request = cursor.fetchone()
                conn.close()

                if request:
                    logger.info(f"Данные заявки: {request}")
                    
                    requester_id = request[8]
                    if requester_id is None:
                        logger.error(f"requesterTelegramId is None for requestId {requestId}")
                        return
                    
                    status = request[1]
                    dateTime = request[2]
                    department = request[3]
                    amount = request[4]
                    description = request[5]
                    details = request[6]
                    requesterTelegramNickname = request[9]
                    requesterName = request[10]

                    notification_text = (
                        f"Вашу заявку рассмотрели.\n"
                        f"🆔 <b>Статус:</b> {status}\n"
                        f"📅 <b>Дата и время:</b> {dateTime}\n"
                        f"🏢 <b>Отдел:</b> {department}\n"
                        f"💰 <b>Сумма:</b> {amount}\n"
                        f"📝 <b>Описание:</b> {description}\n"
                        f"💳 <b>Детали:</b> {details}\n"
                        f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
                        f"👤 <b>Руководитель отдела:</b> {user_name} (@{telegram_nickname})\n"
                        f"📅 <b>Дата решения:</b> {decision_date}\n"
                        f"📝 <b>Решение:</b> {decision}"
                    )

                    await context.bot.send_message(chat_id=requester_id, text=notification_text, parse_mode='HTML')
                    logger.info(f"Уведомление отправлено заявителю {requester_id}")

                    # Уведомляем CFO
                    cfo_ids = get_cfo_ids()
                    cfo_notification_text = (
                        f"Есть новая заявка, ожидающая вашего решения.\n"
                        f"🆔 <b>Статус:</b> {status}\n"
                        f"📅 <b>Дата и время:</b> {dateTime}\n"
                        f"🏢 <b>Отдел:</b> {department}\n"
                        f"💰 <b>Сумма:</b> {amount}\n"
                        f"📝 <b>Описание:</b> {description}\n"
                        f"<b>______________________________</b>\n"
                        f"🆕 <b>Введите /cfo,</b> чтобы принять решение по заявке\n"
                    )
                    for cfo_id in cfo_ids:
                        await context.bot.send_message(chat_id=cfo_id, text=cfo_notification_text, parse_mode='HTML')
                        logger.info(f"Уведомление отправлено CFO {cfo_id}")
                else:
                    logger.error(f"Заявка с ID {requestId} не найдена")
                    await query.edit_message_text("Не удалось найти заявку в базе данных.")
                    return ConversationHandler.END

            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления: {e}")

            # Удаляем заявку из списка
            current_index = context.user_data['current_request_index']
            context.user_data['requests'].pop(current_index)

            # Удаляем вложения текущей заявки
            for msg_id in context.user_data.get('attachment_messages', []):
                try:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
                except Exception as e:
                    logger.error(f"Ошибка при удалении сообщения с вложением: {e}")
            context.user_data['attachment_messages'] = []

            # Переходим к следующей
            if context.user_data['requests']:
                if current_index >= len(context.user_data['requests']):
                    context.user_data['current_request_index'] = 0
                await show_request(update, context)
                return REQUEST_NAVIGATION
            else:
                await query.edit_message_text("Все заявки обработаны.")
                return ConversationHandler.END

        elif data.startswith('department_reject_'):
            # Обработка отклонения
            context.user_data['request_id'] = requestId
            context.user_data['telegram_id'] = telegram_id
            context.user_data['telegram_nickname'] = telegram_nickname
            context.user_data['user_name'] = user_name

            await query.edit_message_text("Пожалуйста, укажите причину отклонения заявки.")
            return REASON

    elif data.startswith('department_paid_'):
        requestId = int(data.split('_')[-1])
        telegram_id = update.effective_user.id
        telegram_nickname = update.effective_user.username
        user_name = get_user_name_by_telegram_id(telegram_id)

        # Обработка отметки оплаты
        await query.edit_message_text("Пожалуйста, ожидайте, заявка отмечается как оплаченная.")

        conn, cursor = get_db_connection()
        status = 'Оплачено'
        decision = 'Оплачено'
        decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            logger.info("Обновляем статус заявки в базе данных на 'Оплачено'")
            cursor.execute("""
                UPDATE requests
                SET status = ?,
                    departmentHeadTelegramId = ?,
                    departmentHeadTelegramNickname = ?,
                    departmentHeadName = ?,
                    departmentHeadDecision = ?,
                    departmentHeadDecisionDateTime = ?
                WHERE requestId = ?
            """, (status, telegram_id, telegram_nickname, user_name, decision, decision_date, requestId))
            conn.commit()
            logger.info("Заявка успешно обновлена как 'Оплачено'")
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

        # Уведомляем заявителя
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM requests WHERE requestId = ?", (requestId,))
            request = cursor.fetchone()
            conn.close()

            if request:
                logger.info(f"Данные заявки: {request}")
                
                requester_id = request[8]
                if requester_id is None:
                    logger.error(f"requesterTelegramId is None for requestId {requestId}")
                    return
                
                status = request[1]
                dateTime = request[2]
                department = request[3]
                amount = request[4]
                description = request[5]
                details = request[6]
                requesterTelegramNickname = request[9]
                requesterName = request[10]

                notification_text = (
                    f"Ваша заявка отмечена как оплаченная.\n"
                    f"🆔 <b>Статус:</b> {status}\n"
                    f"📅 <b>Дата и время:</b> {dateTime}\n"
                    f"🏢 <b>Отдел:</b> {department}\n"
                    f"💰 <b>Сумма:</b> {amount}\n"
                    f"📝 <b>Описание:</b> {description}\n"
                    f"💳 <b>Детали:</b> {details}\n"
                    f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
                    f"👤 <b>Руководитель отдела:</b> {user_name} (@{telegram_nickname})\n"
                    f"📅 <b>Дата отметки:</b> {decision_date}\n"
                    f"📝 <b>Статус:</b> {decision}"
                )

                await context.bot.send_message(chat_id=requester_id, text=notification_text, parse_mode='HTML')
                logger.info(f"Уведомление отправлено заявителю {requester_id}")
            else:
                logger.error(f"Заявка с ID {requestId} не найдена")
                await query.edit_message_text("Не удалось найти заявку в базе данных.")
                return ConversationHandler.END

        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления: {e}")

        # Удаляем заявку из списка
        current_index = context.user_data['current_request_index']
        context.user_data['requests'].pop(current_index)

        # Удаляем вложения
        for msg_id in context.user_data.get('attachment_messages', []):
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения с вложением: {e}")
        context.user_data['attachment_messages'] = []

        # Переходим к следующей
        if context.user_data['requests']:
            if current_index >= len(context.user_data['requests']):
                context.user_data['current_request_index'] = 0
            await show_request(update, context)
            return REQUEST_NAVIGATION
        else:
            await query.edit_message_text("Все заявки обработаны.")
            return ConversationHandler.END

    elif data.startswith('department_correction_'):
        # Обработка отправки заявки "На исправление"
        requestId = int(data.split('_')[-1])
        telegram_id = update.effective_user.id
        telegram_nickname = update.effective_user.username
        user_name = get_user_name_by_telegram_id(telegram_id)

        # Запоминаем данные в user_data
        context.user_data['request_id'] = requestId
        context.user_data['telegram_id'] = telegram_id
        context.user_data['telegram_nickname'] = telegram_nickname
        context.user_data['user_name'] = user_name

        await query.edit_message_text("Пожалуйста, введите комментарий для заявителя, что нужно исправить или уточнить.")
        return CORRECTION_REASON

    else:
        await query.edit_message_text("Неизвестное действие.")
        return ConversationHandler.END

# Обработчик для получения причины (комментария) при отправке "На исправление"
async def correction_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    telegram_id = context.user_data['telegram_id']
    telegram_nickname = context.user_data['telegram_nickname']
    user_name = context.user_data['user_name']
    request_id = context.user_data['request_id']

    logger.info(f"Пользователь {telegram_nickname} указал комментарий для исправления: {comment}")

    # Устанавливаем статус "Требует корректировки", сохраняем комментарий
    conn, cursor = get_db_connection()
    status = 'Требует корректировки'
    decision = 'На исправление'
    decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        logger.info("Обновляем статус заявки в базе данных - Требует корректировки")
        cursor.execute("""
            UPDATE requests
            SET status = ?,
                departmentHeadTelegramId = ?,
                departmentHeadTelegramNickname = ?,
                departmentHeadName = ?,
                departmentHeadDecision = ?,
                departmentHeadDecisionDateTime = ?,
                comment = ?
            WHERE requestId = ?
        """, (status, telegram_id, telegram_nickname, user_name, decision, decision_date, comment, request_id))
        conn.commit()
        logger.info("Заявка успешно обновлена: Требует корректировки")
    except Exception as e:
        logger.error(f"Ошибка при обновлении заявки: {e}")
        await update.message.reply_text("Произошла ошибка при обновлении заявки.")
        return ConversationHandler.END
    finally:
        conn.close()
        # → push to Sheets
        try:
            sync_request(request_id)
        except Exception as e:
            logger.error(f"sync_request failed for {request_id}: {e}")

    # Уведомляем заявителя
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM requests WHERE requestId = ?", (request_id,))
        request = cursor.fetchone()
        conn.close()

        if request:
            logger.info(f"Данные заявки: {request}")

            requester_id = request[8]
            if requester_id is None:
                logger.error(f"requesterTelegramId is None for requestId {request_id}")
                return

            # Отправляем сообщение пользователю
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

    # Удаляем заявку из списка (так как статус больше не "Ожидает решения руководителя")
    current_index = context.user_data['current_request_index']
    context.user_data['requests'].pop(current_index)

    # Удаляем сообщение с запросом комментария
    await update.message.delete()

    # Очищаем вложения
    for msg_id in context.user_data.get('attachment_messages', []):
        try:
            await update.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения с вложением: {e}")
    context.user_data['attachment_messages'] = []

    # Переходим к следующей заявке
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

    # Обновляем данные в базе данных
    conn, cursor = get_db_connection()
    status = 'Отклонено руководителем отдела'
    decision = 'Отклонено'
    decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        logger.info("Обновляем статус заявки в базе данных с причиной отклонения")
        cursor.execute("""
            UPDATE requests
            SET status = ?,
                departmentHeadTelegramId = ?,
                departmentHeadTelegramNickname = ?,
                departmentHeadName = ?,
                departmentHeadDecision = ?,
                departmentHeadDecisionDateTime = ?,
                comment = ?
            WHERE requestId = ?
        """, (status, telegram_id, telegram_nickname, user_name, decision, decision_date, reason, request_id))
        conn.commit()
        logger.info("Заявка успешно обновлена с причиной отклонения")
    except Exception as e:
        logger.error(f"Ошибка при обновлении заявки: {e}")
        await update.message.reply_text("Произошла ошибка при обновлении заявки.")
        return ConversationHandler.END
    finally:
        conn.close()
        # → push to Sheets
        try:
            sync_request(request_id)
        except Exception as e:
            logger.error(f"sync_request failed for {request_id}: {e}")

    # Уведомляем заявителя
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM requests WHERE requestId = ?", (request_id,))
        request = cursor.fetchone()
        conn.close()

        if request:
            requester_id = request[8]
            dateTime = request[2]
            department = request[3]
            amount = request[4]
            description = request[5]
            details = request[6]
            requesterName = request[10]
            requesterTelegramNickname = request[9]

            notification_text = (
                f"Вашу заявку отклонили.\n"
                f"🆔 <b>Статус:</b> {status}\n"
                f"📅 <b>Дата и время:</b> {dateTime}\n"
                f"🏢 <b>Отдел:</b> {department}\n"
                f"💰 <b>Сумма:</b> {amount}\n"
                f"📝 <b>Описание:</b> {description}\n"
                f"💳 <b>Детали:</b> {details}\n"
                f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
                f"👤 <b>Руководитель отдела:</b> {user_name} (@{telegram_nickname})\n"
                f"📅 <b>Дата решения:</b> {decision_date}\n"
                f"📝 <b>Решение:</b> {decision}\n"
                f"📝 <b>Причина отклонения:</b> {reason}"
            )

            await context.bot.send_message(chat_id=requester_id, text=notification_text, parse_mode='HTML')
            logger.info(f"Уведомление отправлено заявителю {requester_id}")
        else:
            logger.error(f"Заявка с ID {request_id} не найдена")
            await update.message.reply_text("Не удалось найти заявку в базе данных.")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления заявителю: {e}")

    # Удаляем заявку из списка
    current_index = context.user_data['current_request_index']
    context.user_data['requests'].pop(current_index)

    # Удаляем сообщение с запросом причины
    await update.message.delete()

    # Очищаем данные из context.user_data
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

def get_cfo_ids():
    logger.info("Получаем Telegram ID CFO")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("SELECT telegramId FROM team WHERE position = 'CFO'")
        cfo_ids = [row[0] for row in cursor.fetchall()]
        if cfo_ids:
            logger.info(f"Найдены CFO с Telegram ID: {cfo_ids}")
            return cfo_ids
        else:
            logger.info("CFO не найдены")
            return []
    except Exception as e:
        logger.error(f"Ошибка при получении CFO: {e}")
        return []
    finally:
        conn.close()

# Функция отмены диалога
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Пользователь отменил диалог")
    context.user_data.clear()
    await update.message.reply_text(
        "🚫 Действие отменено.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

# Регистрация обработчиков
def register_handlers(application):
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('department_requests', department_requests_handler),
        ],
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

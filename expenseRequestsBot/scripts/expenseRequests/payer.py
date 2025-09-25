import os
import logging
import datetime
import sqlite3
import os
import requests
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from google_sync import sync_request
from expenseRequests.async_tasks import (
    _upload_attachments as upload_attachments_to_drive,
    notify_tron_and_users,
)
import asyncio
from expenseRequests.databasehelper import get_db_connection

# Используем общий логгер
logger = logging.getLogger('bot')

# >>> Добавляем две константы для TRON:
API_KEY = 'REMOVED_TRON_API_KEY'
CONTRACT_ADDRESS = 'TYKC3tKUjLsNDPXM52QcLcLVxN94qbMRfp'

# Состояния для ConversationHandler
REQUEST_NAVIGATION, REASON, CORRECTION_REASON = range(3)



def clean_amount(amount):
    """
    Очищает строковое представление суммы:
    - Удаляет символ '$' и лишние пробелы.
    - Если в строке присутствует запятая, предполагается, что запятая — десятичный разделитель,
      а точки — разделители тысяч. Все точки удаляются, а запятая заменяется на точку.
    - Если запятой нет и число имеет формат "X.Y", где Y состоит ровно из 3 цифр, 
      считается, что точка — разделитель тысяч, и она удаляется.
    """
    if isinstance(amount, str):
        s = amount.replace('$', '').strip()
        if ',' in s:
            s = s.replace('.', '')
            s = s.replace(',', '.')
        else:
            parts = s.split('.')
            if len(parts) == 2 and len(parts[1]) == 3:
                s = parts[0] + parts[1]
        return s
    return str(amount)

# Функция отправки webhook в Zapier
def send_webhook(request_data):
    webhook_url = "os.getenv('EXPENSE_STATUS_WEBHOOK','https://example.com/status')"
    payload = {
        "requestId": request_data[0],
        "status": "Paid by Payer",
        "amount": request_data[4],
        "description": request_data[5],
        "dateTime": request_data[2],
        "details": request_data[6],
        "requesterName": request_data[10]
    }
    try:
        logger.info(f"Sending webhook to {webhook_url} with payload: {payload}")
        response = requests.post(webhook_url, json=payload)
        logger.info(f"Webhook response: {response.status_code} - {response.text}")
        if response.status_code == 200:
            logger.info("Webhook sent successfully.")
        else:
            logger.warning(f"Webhook sent, but received unexpected status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Ошибка отправки webhook: {e}")

# >>> Функция поиска транзакции в сети Tron
def find_tron_transaction_in_last_day(amount, to_address):
    """
    Ищет в сети Tron (по контракту USDT) транзакцию за последние 24 часа,
    совпадающую по адресу назначения и сумме.
    Возвращает ссылку вида https://tronscan.org/#/transaction/<TxHash>,
    либо None, если транзакция не найдена или произошла ошибка.
    """
    try:
        # Очищаем сумму от символов валюты и разделителей тысяч, если это необходимо
        clean_amt = clean_amount(amount)
        raw_amount = float(clean_amt)
        trc20_amount = int(raw_amount * 1_000_000)

        now_ms = int(datetime.datetime.now().timestamp() * 1000)
        day_ago_ms = now_ms - 24 * 60 * 60 * 1000

        to_address = to_address.strip()

        url = f"https://api.trongrid.io/v1/accounts/{to_address}/transactions/trc20"
        params = {
            "limit": 200,
            "contract_address": CONTRACT_ADDRESS,
            "min_timestamp": day_ago_ms
        }
        headers = {
            "accept": "application/json",
            "TRON-PRO-API-KEY": API_KEY
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        if "data" not in data:
            return None

        for tx in data["data"]:
            if "value" not in tx or "to" not in tx:
                continue
            if tx["to"] != to_address:
                continue

            value_in_tx = int(tx["value"])
            if value_in_tx == trc20_amount:
                txn_hash = tx["transaction_id"]
                return f"https://tronscan.org/#/transaction/{txn_hash}"

        return None

    except Exception as e:
        logger.error(f"Ошибка в find_tron_transaction_in_last_day: {e}")
        return None

# Функция проверки прав доступа пользователя
def check_user_access(telegram_id):
    logger.info(f"Проверяем права доступа пользователя с Telegram ID: {telegram_id}")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("""
            SELECT position 
            FROM team 
            WHERE telegramId = ?
        """, (telegram_id,))
        positions = cursor.fetchall()
        for position in positions:
            if position[0] == 'payer':
                logger.info("Пользователь имеет права доступа (роль: payer)")
                return True
        logger.info("У пользователя нет прав доступа")
        return False
    except Exception as e:
        logger.error(f"Ошибка при проверке прав доступа: {e}")
        return False
    finally:
        conn.close()

# Функция получения заявок для плательщика
def get_payer_requests():
    logger.info("Получаем заявки, ожидающие оплаты")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("""
            SELECT * FROM requests
            WHERE status IN (
                'Одобрено финансовым отделом, передано на оплату'
            )
        """)
        requests = cursor.fetchall()
        logger.info(f"Найдено {len(requests)} заявок")
        return requests
    except Exception as e:
        logger.error(f"Ошибка при получении заявок: {e}")
        return []
    finally:
        conn.close()

# Функция получения имени пользователя по его Telegram ID
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

# Обработчик команды /payer_requests
async def payer_requests_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    telegram_nickname = update.effective_user.username
    logger.info(f"Пользователь {telegram_nickname} ({telegram_id}) запросил список заявок для оплаты")

    # Проверяем права доступа
    if not check_user_access(telegram_id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END

    # Получаем заявки, ожидающие оплаты
    requests = get_payer_requests()
    if not requests:
        await update.message.reply_text("Нет заявок, ожидающих оплаты.")
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
        f"💳 <b>Детали:</b> {details}\n"
        f"📝 <b>Описание:</b> {description}\n"
        f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text=message_text, parse_mode='HTML')
        message_to_reply = update.callback_query.message
    else:
        sent_message = await update.message.reply_text(text=message_text, parse_mode='HTML')
        message_to_reply = sent_message

    # Отправляем вложения, если они есть
    if attachment:
        attachments = attachment.split(', ')
        for file_path in attachments:
            if file_path.startswith('http'):
                # Это ссылка
                attachment_text = f"🔗 <a href='{file_path}'>{file_path}</a>"
                sent_links = await context.bot.send_message(chat_id=update.effective_chat.id, text=attachment_text, parse_mode='HTML', disable_web_page_preview=True)
                context.user_data['attachment_messages'].append(sent_links.message_id)
            else:
                # Это файл
                try:
                    with open(file_path, 'rb') as file:
                        sent_file = await context.bot.send_document(chat_id=update.effective_chat.id, document=file)
                        context.user_data['attachment_messages'].append(sent_file.message_id)
                        logger.info(f"Вложение {file_path} отправлено")
                except Exception as e:
                    logger.error(f"Не удалось отправить вложение {file_path}: {e}")

    # Третья кнопка: "✏️ На исправление"
    keyboard_buttons = [
        [
            InlineKeyboardButton("💸 Оплачено", callback_data=f"payer_paid_{requestId}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"payer_reject_{requestId}"),
            InlineKeyboardButton("✏️ На исправление", callback_data=f"payer_correction_{requestId}")
        ],
        [
            InlineKeyboardButton("⬅️", callback_data='payer_prev'),
            InlineKeyboardButton("➡️", callback_data='payer_next')
        ]
    ]
    keyboard = InlineKeyboardMarkup(keyboard_buttons)

    # Добавляем кнопки к сообщению с заявкой
    await message_to_reply.edit_reply_markup(reply_markup=keyboard)

# Обработчик нажатия на кнопки
async def decision_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == 'payer_next':
        context.user_data['current_request_index'] += 1
        if context.user_data['current_request_index'] >= len(context.user_data['requests']):
            context.user_data['current_request_index'] = 0
        await show_request(update, context)
        return REQUEST_NAVIGATION

    elif data == 'payer_prev':
        context.user_data['current_request_index'] -= 1
        if context.user_data['current_request_index'] < 0:
            context.user_data['current_request_index'] = len(context.user_data['requests']) - 1
        await show_request(update, context)
        return REQUEST_NAVIGATION

    elif data.startswith('payer_paid_') or data.startswith('payer_reject_'):
        requestId = int(data.split('_')[-1])
        telegram_id = update.effective_user.id
        telegram_nickname = update.effective_user.username
        user_name = get_user_name_by_telegram_id(telegram_id)

        if data.startswith('payer_paid_'):

            conn0, cur0 = get_db_connection()
            cur0.execute("SELECT * FROM requests WHERE requestId = ?", (requestId,))
            request_data = cur0.fetchone()
            conn0.close()
            # Обработка оплаты
            await query.edit_message_text("Пожалуйста, ожидайте, заявка отмечается как оплаченная.")

            conn, cursor = get_db_connection()
            status = 'Оплачено'
            decision = 'Оплачено'
            decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            try:
                logger.info("Обновляем статус заявки в базе данных (payer_paid)")
                cursor.execute("""
                    UPDATE requests
                    SET status = ?,
                        payerTelegramId = ?,
                        payerTelegramNickname = ?,
                        payerName = ?,
                        payerDecision = ?,
                        payerDecisionDateTime = ?
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

            if request_data[7]:  # Проверяем наличие вложений
                asyncio.create_task(upload_attachments_to_drive(request_data[0], request_data[7]))
            else:
                logger.info(f"No attachments to upload for request {request_data[0]}")
            asyncio.create_task(notify_tron_and_users(request_data, context.bot))
            # ===== Новый блок: уведомление группы финансистов =====
            requester_id              = request_data[8]
            department_head_id        = request_data[11]
            dateTime                  = request_data[2]
            amount                    = request_data[4]
            description               = request_data[5]
            details                   = request_data[6]
            requesterName             = request_data[10]
            requesterTelegramNickname = request_data[9]
            if description.strip().startswith("🏗️ Project name:") or description.strip().startswith("ВОЗВРАТ ДЕПОЗИТА"):
                financier_bot_token = "REMOVED_TG_TOKEN"
                financier_chat_id = "-1002316341562"  # Замените на реальный ID группы "Loyo finance"
                finance_notification = (
                    f"✅ <b>Оплачено:</b> заявка {requestId}\n"
                    f"📅 <b>Дата оплаты:</b> {decision_date}\n"
                    f"💰 <b>Сумма:</b> {amount}\n"
                    f"📝 <b>Описание:</b> {description}"
                )
                try:
                    response = requests.get(
                        f"https://api.telegram.org/bot{financier_bot_token}/sendMessage",
                        params={"chat_id": financier_chat_id, "text": finance_notification, "parse_mode": "HTML"},
                        timeout=10
                    )
                    logger.info(f"Уведомление в группу финансистов отправлено, статус: {response.status_code}")
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления в группу финансистов: {e}")
            # ===== Конец нового блока =====
                         # webhook, MySQL, SFTP, Drive
            
            
            

            # 2) синхронная рассылка «заявителю» и «руководителю отдела» сразу без ожидания Tron
            requester_id              = request_data[8]
            department_head_id        = request_data[11]
            dateTime                  = request_data[2]
            amount                    = request_data[4]
            description               = request_data[5]
            details                   = request_data[6]
            requesterName             = request_data[10]
            requesterTelegramNickname = request_data[9]
            notification_text = (
                f"Ваша заявка оплачена.\n"
                f"🆔 <b>Статус:</b> {status}\n"
                f"📅 <b>Дата и время:</b> {dateTime}\n"
                f"💰 <b>Сумма:</b> {amount}\n"
                f"💳 <b>Детали:</b> {details}\n"
                f"📝 <b>Описание:</b> {description}\n"
                f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
                f"👤 <b>Плательщик:</b> {user_name} (@{telegram_nickname})\n"
                f"📅 <b>Дата оплаты:</b> {decision_date}\n"
            )
            # используем context.bot
            await context.bot.send_message(chat_id=requester_id, text=notification_text, parse_mode='HTML')
            await context.bot.send_message(chat_id=department_head_id, text=notification_text, parse_mode='HTML')

            # 3) мгновенный ответ плательщику и выход из диалога
            await query.edit_message_text(
                "✅ Заявка отмечена как оплаченная. "
                "Заявитель и руководитель уже уведомлены, а ссылка на папку/транзакцию придёт чуть позже."
            )
            # Удаляем заявку из списка
            current_index = context.user_data['current_request_index']
            context.user_data['requests'].pop(current_index)

            if context.user_data['requests']:
                if current_index >= len(context.user_data['requests']):
                    context.user_data['current_request_index'] = 0
                await show_request(update, context)
                return REQUEST_NAVIGATION
            else:
                await context.bot.send_message(chat_id=telegram_id, text="Все заявки обработаны.")
                context.user_data.clear()
                return ConversationHandler.END
                

            

        elif data.startswith('payer_reject_'):
            # Отклонение
            context.user_data['request_id'] = requestId
            context.user_data['telegram_id'] = telegram_id
            context.user_data['telegram_nickname'] = telegram_nickname
            context.user_data['user_name'] = user_name

            await query.edit_message_text("Пожалуйста, укажите причину отклонения заявки.")
            return REASON

    elif data.startswith('payer_correction_'):
        # Отправка "На исправление"
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

async def reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик ввода причины при нажатии '❌ Отклонить'.
    """
    reason = update.message.text
    telegram_id = context.user_data['telegram_id']
    telegram_nickname = context.user_data['telegram_nickname']
    user_name = context.user_data['user_name']
    request_id = context.user_data['request_id']

    logger.info(f"Пользователь {telegram_nickname} указал причину отклонения: {reason}")

    conn, cursor = get_db_connection()
    status = 'Отклонено плательщиком'
    decision = 'Отклонено'
    decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        logger.info("Обновляем статус заявки (payer_reject)")
        cursor.execute("""
            UPDATE requests
            SET status = ?,
                payerTelegramId = ?,
                payerTelegramNickname = ?,
                payerName = ?,
                payerDecision = ?,
                payerDecisionDateTime = ?,
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
            amount = request[4]
            description = request[5]
            details = request[6]
            requesterName = request[10]
            requesterTelegramNickname = request[9]

            notification_text = (
                f"Ваша заявка отклонена плательщиком.\n"
                f"🆔 <b>Статус:</b> {status}\n"
                f"📅 <b>Дата и время:</b> {dateTime}\n"
                f"💰 <b>Сумма:</b> {amount}\n"
                f"💳 <b>Детали:</b> {details}\n"
                f"📝 <b>Описание:</b> {description}\n"
                f"👤 <b>Заявитель:</b> {requesterName} (@{requesterTelegramNickname})\n"
                f"👤 <b>Плательщик:</b> {user_name} (@{telegram_nickname})\n"
                f"📅 <b>Дата решения:</b> {decision_date}\n"
                f"📝 <b>Причина отклонения:</b> {reason}"
            )

            await context.bot.send_message(chat_id=requester_id, text=notification_text, parse_mode='HTML')
            await context.bot.send_message(chat_id=department_head_id, text=notification_text, parse_mode='HTML')
        else:
            logger.error("Не удалось найти заявку в базе данных")
            await update.message.reply_text("Не удалось найти заявку в базе данных.")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления: {e}")

    # Удаляем заявку из списка
    current_index = context.user_data['current_request_index']
    context.user_data['requests'].pop(current_index)

    await update.message.delete()

    if context.user_data['requests']:
        if current_index >= len(context.user_data['requests']):
            context.user_data['current_request_index'] = 0
        await show_request(update, context)
        return REQUEST_NAVIGATION
    else:
        await context.bot.send_message(chat_id=telegram_id, text="Все заявки обработаны.")
        return ConversationHandler.END

# Обработчик комментария при кнопке «На исправление»
async def correction_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    telegram_id = context.user_data['telegram_id']
    telegram_nickname = context.user_data['telegram_nickname']
    user_name = context.user_data['user_name']
    request_id = context.user_data['request_id']

    logger.info(f"Плательщик {telegram_nickname} указал комментарий (на исправление): {comment}")

    conn, cursor = get_db_connection()
    status = 'Требует корректировки'
    decision = 'На исправление'
    decision_date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        logger.info("Обновляем статус заявки (payer_correction) на 'Требует корректировки'")
        cursor.execute("""
            UPDATE requests
            SET status = ?,
                payerTelegramId = ?,
                payerTelegramNickname = ?,
                payerName = ?,
                payerDecision = ?,
                payerDecisionDateTime = ?,
                comment = ?
            WHERE requestId = ?
        """, (status, telegram_id, telegram_nickname, user_name, decision, decision_date, comment, request_id))
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении заявки (payer_correction): {e}")
        await update.message.reply_text("Произошла ошибка при обновлении заявки.")
        return ConversationHandler.END
    finally:
        conn.close()
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
        logger.error(f"Ошибка при уведомлении заявителя: {e}")

    # Удаляем заявку из списка
    current_index = context.user_data['current_request_index']
    context.user_data['requests'].pop(current_index)

    # Удаляем сообщение с запросом комментария
    await update.message.delete()

    if context.user_data['requests']:
        if current_index >= len(context.user_data['requests']):
            context.user_data['current_request_index'] = 0
        await show_request(update, context)
        return REQUEST_NAVIGATION
    else:
        await context.bot.send_message(chat_id=telegram_id, text="Все заявки обработаны.")
        return ConversationHandler.END

# Функция отмены диалога
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Пользователь отменил диалог")
    # Очищаем данные пользователя
    context.user_data.clear()
    if update.message:
        await update.message.reply_text(
            "🚫 Действие отменено.",
            parse_mode='HTML'
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "🚫 Действие отменено.",
            parse_mode='HTML'
        )
    return ConversationHandler.END

# Регстрация обработчиков
def register_handlers(application):
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('payer_requests', payer_requests_handler),
        ],
        states={
            REQUEST_NAVIGATION: [CallbackQueryHandler(decision_handler, pattern=r'^(?:payer_prev|payer_next|payer_paid_\d+|payer_reject_\d+|payer_correction_\d+)$')],
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

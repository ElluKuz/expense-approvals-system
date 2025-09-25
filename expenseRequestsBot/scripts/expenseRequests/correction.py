import logging
import sqlite3
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)

logger = logging.getLogger('bot')

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'loyobot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return conn, cursor

# Состояния для диалога, когда заявитель исправляет заявку
CORRECTION_CHOICE, CORRECTION_VALUE = range(2)

def register_correction_handlers(application):
    """
    Регистрируем хендлеры для логики, когда заявитель исправляет заявку /fix_request.
    """
    fix_request_conversation = ConversationHandler(
        entry_points=[CommandHandler('fix_request', start_request_fix)],
        states={
            CORRECTION_CHOICE: [MessageHandler(filters.Regex('^[0-9]+$'), handle_choice)],
            CORRECTION_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_value)],
        },
        fallbacks=[],
        allow_reentry=True
    )

    application.add_handler(fix_request_conversation)

# =========================================================
# 1. ЛОГИКА ИСПРАВЛЕНИЯ ЗАЯВКИ ПОЛЬЗОВАТЕЛЕМ (/fix_request)
# =========================================================

async def start_request_fix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает команду /fix_request.
    Находит заявку со статусом "Требует корректировки" и отправляет пользователю список пунктов для исправления.
    """
    user_id = update.effective_user.id
    logger.info(f"Looking for a request for user with ID {user_id}")

    request_id = find_user_correction_request(user_id)
    if not request_id:
        await update.message.reply_text("You don't have any requests that require correction.")
        return ConversationHandler.END

    logger.info(f"Request found for user {user_id}, request ID: {request_id}")
    context.user_data['fix_request_id'] = request_id

    data = get_request_data(request_id)
    description = data.get('description', '')
    
    if description.startswith("🏗️ Project name:"):
        formatted_description = format_description_with_numbers_for_commission(data)
        number_of_items = 12  # 12 items для комиссионной заявки
        context.user_data['request_type'] = 'commission'
    elif description.startswith("ВОЗВРАТ ДЕПОЗИТА"):
        formatted_description = format_description_with_numbers_for_deposit_return(data)
        number_of_items = 5   # 5 items для заявки на возврат депозита
        context.user_data['request_type'] = 'deposit'
    else:
        formatted_description = format_description_with_numbers_for_expenses(data)
        number_of_items = 4   # 4 items для заявки на расход
        context.user_data['request_type'] = 'expenses'
    
    # Сохраняем количество пунктов для последующей проверки в handle_choice
    context.user_data['number_of_items'] = number_of_items

    text = (
        f"Your request (ID: {request_id}) requires correction.\n\n"
        "Please enter the number of the item you would like to correct:\n\n"
        f"{formatted_description}\n\n"
        f"Send a number (1-{number_of_items})."
    )
    await update.message.reply_text(text, parse_mode='HTML')
    return CORRECTION_CHOICE

def format_description_with_numbers_for_expenses(data):
    """
    Форматирует описание для заявки на расход.
    """
    amount = data.get('amount', '')
    description = data.get('description', '')
    details = data.get('details', '')
    attachments = data.get('attachments_links', '')

    return (
        f"1 - <b>Amount:</b> {amount}\n"
        f"2 - <b>Description:</b> {description}\n"
        f"3 - <b>Details:</b> {details}\n"
        f"4 - <b>Attachments:</b> {attachments}\n"
    )

def format_description_with_numbers_for_commission(data):
    """
    Форматирует описание для комиссионной заявки.
    """
    description = data.get('description', '')
    lines = description.split("\n")
    formatted_lines = []
    for i, line in enumerate(lines, start=1):
        formatted_lines.append(f"{i} - {line}")
    return "\n".join(formatted_lines)

def format_description_with_numbers_for_deposit_return(data):
    """
    Форматирует описание для заявки на возврат депозита.
    """
    description = data.get('description', '')
    lines = description.split("\n")
    formatted_lines = []
    index = 1
    for line in lines:
        if line.startswith("ВОЗВРАТ ДЕПОЗИТА"):
            continue
        formatted_lines.append(f"{index} - {line}")
        index += 1
    return "\n".join(formatted_lines)

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор пункта для исправления.
    """
    choice_str = update.message.text
    if not choice_str.isdigit():
        await update.message.reply_text("Please enter a number from 1 to 12.")
        return CORRECTION_CHOICE

    choice = int(choice_str)
    number_of_items = context.user_data.get('number_of_items', 12)
    if choice < 1 or choice > number_of_items:
        await update.message.reply_text(f"Please enter a number from 1 to {number_of_items}.")
        return CORRECTION_CHOICE

    context.user_data['fix_field_choice'] = choice
    request_type = context.user_data.get('request_type', 'commission')
    field_label = map_choice_to_label(choice, request_type)

    await update.message.reply_text(f"Please enter the new value for: {field_label}")
    return CORRECTION_VALUE

async def handle_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает новое значение выбранного поля и обновляет заявку в БД.
    Для заявок типа 'expenses' обновляем отдельные колонки,
    а для типов 'commission' и 'deposit' обновляем поле description,
    и дополнительно для commission при выборе Commission Amount (8)
    обновляем поле amount, а при выборе Wallet Number (11) – поле details.
    """
    new_value = update.message.text
    choice = context.user_data['fix_field_choice']
    request_id = context.user_data['fix_request_id']
    request_type = context.user_data.get('request_type', 'commission')

    if request_type == 'expenses':
        # Для расходов обновляем конкретное поле
        field_mapping = {
            1: "amount",
            2: "description",
            3: "details",
            4: "attachment"  # или 'attachments_links', если так хранится
        }
        field = field_mapping.get(choice)
        if field:
            update_specific_field(request_id, field, new_value)
        else:
            await update.message.reply_text("Invalid field choice.")
            return CORRECTION_CHOICE
    else:
        # Для заявок типа commission и deposit обновляем многострочное поле description
        request_data = get_request_data(request_id)
        description = request_data.get('description', '')
        lines = description.split("\n")
        if 1 <= choice <= len(lines):
            lines[choice - 1] = f"{lines[choice - 1].split(':')[0]}: {new_value}"
        new_description = "\n".join(lines)
        update_request_field(request_id, new_description)
        
        # Дополнительно, для заявок типа commission обновляем и отдельные колонки:
        if request_type == 'commission':
            # Если пользователь меняет Commission Amount (номер 8), обновляем поле amount
            # Если меняется Wallet Number (номер 11), обновляем поле details
            commission_extra_fields = {
                8: "amount",
                11: "details"
            }
            extra_field = commission_extra_fields.get(choice)
            if extra_field:
                update_specific_field(request_id, extra_field, new_value)
        # Аналогично можно добавить логику для deposit, если требуется

    set_request_status(request_id, "Одобрено руководителем отдела, ожидает решения финансового отдела")
    updated_data = get_request_data(request_id)
    logger.info(f"После обновления в БД: {updated_data}")

    combined_description = build_combined_description(updated_data)
    department_heads = get_department_heads(updated_data["department"])

    notification_text = (
        f"📢 <b>Исправленная заявка</b>\n"
        f"ID: {request_id}\n"
        f"Статус: Ожидает решения\n\n"
        "------------------------------------\n"
        "Введите /department_requests (или другую команду), чтобы просмотреть."
    )
    for head_id in department_heads:
        try:
            await context.bot.send_message(chat_id=head_id, text=notification_text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Ошибка при уведомлении руководителя {head_id}: {e}")

    context.user_data.clear()
    await update.message.reply_text("Изменения сохранены! Заявка отправлена на повторное согласование.")
    return ConversationHandler.END


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def update_specific_field(request_id: int, field: str, new_value: str):
    conn, cursor = get_db_connection()
    try:
        sql = f"UPDATE requests SET {field} = ? WHERE requestId = ?"
        cursor.execute(sql, (new_value, request_id))
        conn.commit()
        logger.info(f"Заявка {request_id} обновлена: поле {field} изменено на {new_value}")
    except Exception as e:
        logger.error(f"Ошибка при обновлении поля {field} для заявки {request_id}: {e}")
    finally:
        conn.close()


def find_user_correction_request(user_id: int):
    """
    Находит заявку со статусом 'Требует корректировки' для пользователя.
    """
    conn, cursor = get_db_connection()
    try:
        cursor.execute("""
            SELECT requestId FROM requests
            WHERE requesterTelegramId = ? AND status = 'Требует корректировки'
            ORDER BY requestId DESC LIMIT 1
        """, (user_id,))
        result = cursor.fetchone()
        if result:
            logger.info(f"Заявка найдена для пользователя {user_id}: ID {result[0]}")
        else:
            logger.info(f"Заявка не найдена для пользователя {user_id}")
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Ошибка при поиске заявки для пользователя {user_id}: {e}")
        return None
    finally:
        conn.close()

def get_request_data(request_id: int) -> dict:
    """
    Достаёт из БД данные заявки в виде словаря.
    """
    conn, cursor = get_db_connection()
    try:
        cursor.execute("SELECT * FROM requests WHERE requestId = ?", (request_id,))
        row = cursor.fetchone()
        if row:
            return dict(zip([column[0] for column in cursor.description], row))
        return {}
    except Exception as e:
        logger.error(f"Ошибка при получении данных заявки {request_id}: {e}")
        return {}
    finally:
        conn.close()

def set_request_status(request_id: int, status: str):
    """
    Обновляет статус заявки.
    """
    conn, cursor = get_db_connection()
    try:
        cursor.execute("UPDATE requests SET status = ? WHERE requestId = ?", (status, request_id))
        conn.commit()
        logger.info(f"Статус заявки {request_id} изменён на {status}")
    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса заявки {request_id}: {e}")
    finally:
        conn.close()

def update_request_field(request_id: int, new_description: str):
    """
    Обновляет поле description заявки.
    """
    conn, cursor = get_db_connection()
    try:
        cursor.execute("UPDATE requests SET description = ? WHERE requestId = ?", (new_description, request_id))
        conn.commit()
        logger.info(f"Заявка {request_id} обновлена: описание")
    except Exception as e:
        logger.error(f"Ошибка при обновлении описания для заявки {request_id}: {e}")
    finally:
        conn.close()

def map_choice_to_label(choice: int, request_type: str) -> str:
    """
    Возвращает название поля для выбранного пункта в зависимости от типа заявки.
    """
    if request_type == 'expenses':
        labels = {
            1: "Amount",
            2: "Description",
            3: "Details",
            4: "Attachments"
        }
    else:  # для 'commission' и 'deposit'
        labels = {
            1: "Project name",
            2: "Сlient's name",
            3: "Unit Number",
            4: "Price",
            5: "Manager Contact",
            6: "Agency Name",
            7: "Agency Commission (%)",
            8: "Commission Amount",
            9: "Agent Name",
            10: "Internal Manager Name",
            11: "Wallet Number",
            12: "Description"
        }
    return labels.get(choice, "Неизвестное поле")

def build_combined_description(request_data: dict) -> str:
    """
    Формирует текст для уведомлений о заявке.
    """
    text = (
        f"🏗️ Project Name: {request_data.get('project_name', '')}\n"
        f"👤 Client Name: {request_data.get('client_name', '')}\n"
        f"🏢 Unit Number: {request_data.get('unit_number', '')}\n"
        f"💰 Price: {request_data.get('price', '')}\n"
        f"📞 Manager Contact: {request_data.get('manager_contact', '')}\n"
        f"🏢 Agency Commission (%): {request_data.get('agency_name', '')}\n"
        f"💼 Commission Amount: {request_data.get('agency_commission_percent', '')}%\n"
        f"💰 Сумма комиссии: {request_data.get('amount', '')}\n"
        f"👤 Agent Name: {request_data.get('agent_name', '')}\n"
        f"👤 Internal Manager Name: {request_data.get('internal_manager_name', '')}\n"
        f"💳 Wallet Number: {request_data.get('details', '')}\n"
        f"📝 Description: {request_data.get('description', '')}"
    )
    return text

def get_department_heads(department: str) -> list:
    conn, cursor = get_db_connection()
    try:
        cursor.execute("""
            SELECT telegramId FROM team
            WHERE position = 'head' AND department = ?
        """, (department,))
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Ошибка при получении главы отдела {department}: {e}")
        return []
    finally:
        conn.close()

import logging
import datetime
import csv
import io
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, ConversationHandler, MessageHandler, filters
import sqlite3
import calendar

# Используем общий логгер
logger = logging.getLogger('bot')

# Состояния для ConversationHandler
CHOOSING_MONTH = range(1)

# Функция для подключения к базе данных (путь теперь относительный)
def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'loyobot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return conn, cursor

def get_all_departments():
    logger.info("Получаем список всех отделов из базы данных")
    conn, cursor = get_db_connection()
    try:
        cursor.execute("SELECT name FROM departments")
        departments = [row[0] for row in cursor.fetchall()]
        logger.info(f"Все отделы: {departments}")
        return departments
    except Exception as e:
        logger.error(f"Ошибка при получении всех отделов: {e}")
        return []
    finally:
        conn.close()

# Функция проверки прав доступа пользователя с учетом приоритетов ролей
def check_user_access(telegram_id):
    """Проверка прав доступа пользователя с учетом приоритетов ролей"""
    logger.info(f"Проверяем права доступа пользователя с Telegram ID: {telegram_id}")
    conn, cursor = get_db_connection()
    try:
        # Получаем все позиции пользователя
        cursor.execute(
            """
            SELECT position FROM team WHERE telegramId = ?
            """,
            (telegram_id,)
        )
        positions = [row[0] for row in cursor.fetchall()]
        
        if not positions:
            logger.info("У пользователя нет позиций в системе")
            return [], None
        
        # Определяем приоритет ролей
        role_priority = ['CFO', 'payer', 'head']
        user_role = None
        
        for role in role_priority:
            if role in positions:
                user_role = role
                break  # Прерываем цикл при нахождении роли с наивысшим приоритетом
        
        if user_role in ('CFO', 'payer'):
            # Пользователь имеет доступ ко всем отделам
            departments = get_all_departments()
            logger.info(f"Пользователь {user_role} имеет доступ ко всем отделам: {departments}")
            return departments, user_role
        elif user_role == 'head':
            # Пользователь - руководитель отдела
            cursor.execute(
                """
                SELECT department FROM team WHERE telegramId = ? AND position = 'head'
                """,
                (telegram_id,)
            )
            departments = [row[0] for row in cursor.fetchall()]
            if departments:
                logger.info(f"Пользователь {user_role} имеет доступ к отделам: {departments}")
                return departments, user_role
        
        logger.info("У пользователя нет прав доступа")
        return [], None
    except Exception as e:
        logger.error(f"Ошибка при проверке прав доступа: {e}")
        return [], None
    finally:
        conn.close()

def get_date_range(month_type):
    """Получение диапазона дат для фильтрации"""
    now = datetime.datetime.now()

    if month_type == 'current':
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    else:  # previous
        if now.month == 1:
            prev_month = 12
            prev_year = now.year - 1
        else:
            prev_month = now.month - 1
            prev_year = now.year

        # Начало предыдущего месяца
        start_date = datetime.datetime(prev_year, prev_month, 1,
                                       hour=0, minute=0, second=0, microsecond=0)
        # Конец предыдущего месяца
        last_day = calendar.monthrange(prev_year, prev_month)[1]
        end_date = datetime.datetime(prev_year, prev_month, last_day,
                                     hour=23, minute=59, second=59, microsecond=999999)

    return start_date, end_date

def filter_requests(departments, start_date, end_date):
    """Фильтрация заявок по отделам и датам из базы данных"""
    logger.info(f"Фильтруем заявки для отделов {departments} с {start_date} по {end_date}")
    conn, cursor = get_db_connection()
    try:
        # Формируем список плейсхолдеров для запросов с IN
        placeholders = ', '.join('?' * len(departments))
        query = f"""
            SELECT requestId, status, dateTime, department, amount, description, details,
                   requesterTelegramId, requesterTelegramNickname, requesterName,
                   departmentHeadTelegramId, departmentHeadTelegramNickname, departmentHeadName,
                   departmentHeadDecision, departmentHeadDecisionDateTime,
                   CFOTelegramId, CFOTelegramNickname, CFOName, CFODecision, CFODecisionDateTime,
                   payerTelegramId, payerTelegramNickname, payerName, payerDecision,
                   payerDecisionDateTime, comment
            FROM requests
            WHERE department IN ({placeholders})
            AND dateTime BETWEEN ? AND ?
        """
        params = departments + [
            start_date.strftime('%Y-%m-%d %H:%M:%S'),
            end_date.strftime('%Y-%m-%d %H:%M:%S')
        ]
        cursor.execute(query, params)
        records = cursor.fetchall()
        logger.info(f"Найдено {len(records)} записей после фильтрации для отделов {departments}")
        # Получаем названия полей из описания курсора
        column_names = [description[0] for description in cursor.description]
        # Конвертируем записи в список словарей
        filtered_records = []
        for record in records:
            record_dict = dict(zip(column_names, record))

            # Обработка поля amount: чистим и переводим в float
            raw_amount = str(record_dict.get("amount", "")).replace(',', '.')
            try:
                # Оставляем только цифры, точку и минус
                cleaned = ''.join(c for c in raw_amount if c.isdigit() or c in ['.', '-'])
                amt = float(cleaned) if cleaned else 0.0
                # Если число целое, храним как int (100.0 → 100),
                # иначе как float (12.50 → 12.5, 12.34 → 12.34)
                record_dict["amount"] = int(amt) if amt.is_integer() else amt
            except Exception as e:
                logger.warning(f"Не удалось привести amount к числу: '{raw_amount}' → {e}")
                record_dict["amount"] = 0

            filtered_records.append(record_dict)
        return filtered_records
    except Exception as e:
        logger.error(f"Ошибка при выполнении запроса: {e}")
        return []
    finally:
        conn.close()

def create_csv(records):
    """Создание CSV файла из отфильтрованных записей"""
    output = io.StringIO()
    if records:
        fieldnames = records[0].keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=';')
        writer.writeheader()
        writer.writerows(records)
    return output.getvalue()

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /report"""
    telegram_id = update.effective_user.id
    logger.info(f"Получена команда /report от пользователя {telegram_id}")

    departments, position = check_user_access(telegram_id)
    logger.info(f"Результат проверки прав доступа: отделы = {departments}, позиция = {position}")

    if not departments:
        logger.warning(f"Отказано в доступе пользователю {telegram_id}")
        await update.message.reply_text(
            "<b>У вас нет прав для выполнения этой команды.</b>",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    context.user_data['departments'] = departments
    context.user_data['position'] = position
    logger.info(f"Сохранены данные в context.user_data: отделы={departments}, позиция={position}")

    logger.info(f"Отправляем клавиатуру выбора периода пользователю {telegram_id}")
    keyboard = [
        [
            InlineKeyboardButton("Текущий месяц", callback_data="current"),
            InlineKeyboardButton("Прошлый месяц", callback_data="previous")
        ]
    ]

    await update.message.reply_text(
        "<b>Выберите период для отчета:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

    return CHOOSING_MONTH

async def month_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора месяца"""
    query = update.callback_query
    await query.answer()

    month_type = query.data
    departments = context.user_data['departments']
    position = context.user_data['position']
    logger.info(f"Пользователь ({position}) выбрал период: {month_type} для отделов {departments}")

    await query.edit_message_text(
        "<b>⌛ Подготавливаем отчет(ы)...</b>",
        parse_mode='HTML'
    )

    start_date, end_date = get_date_range(month_type)
    logger.info(f"Определен диапазон дат: с {start_date} по {end_date}")

    filtered_records = filter_requests(departments, start_date, end_date)
    logger.info(f"Получено {len(filtered_records)} записей после фильтрации")

    if filtered_records:
        csv_data = create_csv(filtered_records)
        logger.info("CSV файл создан успешно")

        # Формируем красивое имя файла
        period_name = "текущий" if month_type == "current" else "прошлый"
        month_name = start_date.strftime('%B_%Y')  # Название месяца и год
        
        if position in ('CFO', 'payer'):
            filename = f"Отчет_все_отделы_{month_name}.csv"
            caption = f"<b>Сводный отчет по всем отделам за {period_name} месяц</b>"
        else:
            dept_names = '_'.join(departments)
            filename = f"Отчет_{dept_names}_{month_name}.csv"
            caption = f"<b>Отчет по отделу{'ам' if len(departments) > 1 else ''} {', '.join(departments)} за {period_name} месяц</b>"

        logger.info(f"Подготовлен файл: {filename}")

        try:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=io.BytesIO(csv_data.encode('utf-8-sig')),
                filename=filename,
                caption=caption,
                parse_mode='HTML'
            )
            logger.info(f"Файл {filename} успешно отправлен")
            
            await query.edit_message_text(
                f"<b>✅ Отчет успешно сформирован и отправлен.</b>",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке файла: {e}")
            await query.edit_message_text(
                "<b>Произошла ошибка при отправке отчета.</b>",
                parse_mode='HTML'
            )
            return ConversationHandler.END
    else:
        await query.edit_message_text(
            "<b>За выбранный период заявок не найдено.</b>",
            parse_mode='HTML'
        )

    logger.info("Обработка запроса завершена успешно")
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Function to handle user cancellation."""
    logger.info("User canceled the conversation.")
    # Clear user data
    context.user_data.clear()
    await update.message.reply_text(
        "🚫 Отчет отменен.",
        parse_mode='HTML'
    )
    return ConversationHandler.END

# Регстрация обработчиков
def register_handlers(application: Application):
    """Регистрация обработчиков"""
    # Регистрируем команду /cancel как глобальный обработчик
    application.add_handler(CommandHandler('cancel', cancel), group=0)
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('report', report_command)],
        states={
            CHOOSING_MONTH: [
                CallbackQueryHandler(month_chosen, pattern='^(current|previous)$'),
                CommandHandler('report', report_command)  # Добавляем обработку повторного ввода /report
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(conv_handler, group=1)
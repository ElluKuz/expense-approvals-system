import os
import datetime
import sqlite3
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, CallbackQueryHandler,
    MessageHandler, CommandHandler, ConversationHandler, filters
)

logger = logging.getLogger('bot')

# состояния
SHOWING, ATTACHING = range(2)

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'loyobot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return conn, cursor

async def submit_checks_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler для /submitchecks"""
    user_id = update.effective_user.id
    # запросим заявки со статусом 'Оплачено' и датой today+
    today = datetime.datetime.now().strftime('%Y-%m-%d 00:00:00')
    conn, cur = get_db_connection()
    cur.execute("""
        SELECT requestId, dateTime, department, amount, description 
        FROM requests
        WHERE requesterTelegramId = ?
          AND status = 'Оплачено'
          AND dateTime >= ?
        ORDER BY dateTime ASC
    """, (user_id, today))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Нет оплаченных заявок за сегодня.")
        return ConversationHandler.END

    context.user_data['checks_rows'] = rows
    context.user_data['idx'] = 0
    return await _show_one(update, context)

async def _show_one(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать одну заявку с кнопками"""
    rows = context.user_data['checks_rows']
    i = context.user_data['idx']
    rid, dt, dept, amt, desc = rows[i]

    text = (
        f"🔎 <b>Заявка {i+1} из {len(rows)}</b>\n"
        f"🆔 <b>ID:</b> {rid}\n"
        f"📅 <b>Дата:</b> {dt}\n"
        f"🏢 <b>Отдел:</b> {dept}\n"
        f"💰 <b>Сумма:</b> {amt}\n"
        f"📝 <b>Описание:</b> {desc}\n\n"
        "📎 Прикрепите чек или нажмите «Отмена»."
    )
    kb = [
        [
            InlineKeyboardButton("⬅️", callback_data="checks_prev"),
            InlineKeyboardButton("➡️", callback_data="checks_next")
        ],
        [ InlineKeyboardButton("Прикрепить чек", callback_data="checks_attach") ],
        [ InlineKeyboardButton("Отмена", callback_data="checks_cancel") ],
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='HTML',
                                                     reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode='HTML',
                                        reply_markup=InlineKeyboardMarkup(kb))
    return SHOWING

async def checks_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка стрелок и Attach"""
    q = update.callback_query
    data = q.data
    if data == 'checks_prev':
        context.user_data['idx'] = (context.user_data['idx'] - 1) % len(context.user_data['checks_rows'])
        return await _show_one(update, context)
    if data == 'checks_next':
        context.user_data['idx'] = (context.user_data['idx'] + 1) % len(context.user_data['checks_rows'])
        return await _show_one(update, context)
    if data == 'checks_attach':
        await q.edit_message_text("📎 Пожалуйста, отправьте <b>чеки</b> (до 5 файлов).", parse_mode='HTML')
        context.user_data['files'] = []
        return ATTACHING
    if data == 'checks_cancel':
        await q.edit_message_text("Операция отменена.")
        return ConversationHandler.END

async def checks_save_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прием файлов-чеков"""
    msg = update.message
    if msg.document or msg.photo:
        # аналогично applyRequest: сохранить в data/attachments
        attachments_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'attachments')
        os.makedirs(attachments_dir, exist_ok=True)
        f = msg.document or msg.photo[-1]
        file_id = f.file_id
        file_name = getattr(f, 'file_name', f"{file_id}.jpg")
        new_file = await context.bot.get_file(file_id)
        path = os.path.join(attachments_dir, file_name)
        await new_file.download_to_drive(path)
        context.user_data['files'].append(path)

        await msg.reply_text(f"Файл сохранён ({len(context.user_data['files'])}/5).")
        if len(context.user_data['files']) < 5:
            return ATTACHING

    # либо текст-команда /done
    # когда файлов достаточно или пользователь завершил
    # обновляем БД: допишем в checks, поменяем статус
    rows = context.user_data['checks_rows']
    i = context.user_data['idx']
    rid = rows[i][0]
    files = context.user_data['files']
    files_str = ', '.join(files)

    conn, cur = get_db_connection()
    # достаём старый checks, добавляем
    cur.execute("SELECT checks FROM requests WHERE requestId = ?", (rid,))
    old = cur.fetchone()[0] or ''
    new_checks = ', '.join(filter(None, [old, files_str]))
    cur.execute("""
        UPDATE requests
        SET checks = ?, status = 'Оплачено и чек прикреплен'
        WHERE requestId = ?
    """, (new_checks, rid))
    conn.commit()
    conn.close()

    await update.message.reply_text("Чеки успешно прикреплены.")
    return ConversationHandler.END

async def checks_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

def register_handlers(application):
    conv = ConversationHandler(
        entry_points=[CommandHandler('submitchecks', submit_checks_start)],
        states={
            SHOWING: [CallbackQueryHandler(checks_navigation)],
            ATTACHING: [
                MessageHandler(filters.Document.ALL | filters.PHOTO, checks_save_file),
                MessageHandler(filters.TEXT & filters.Regex('^/done$'), checks_save_file),
                CommandHandler('cancel', checks_cancel)
            ]
        },
        fallbacks=[CommandHandler('cancel', checks_cancel)],
        allow_reentry=True
    )
    application.add_handler(conv)

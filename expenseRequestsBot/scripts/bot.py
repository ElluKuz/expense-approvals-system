import os
import logging
import os
import sys
import fcntl
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, ConversationHandler
from expenseRequests.applyRequest import register_handlers as register_request_handlers
from expenseRequests.department import register_handlers as register_department_handlers
from expenseRequests.cfo import register_handlers as register_cfo_handlers
from expenseRequests.payer import register_handlers as register_payer_handlers
from expenseRequests.comission import register_handlers as register_comission_handlers
from expenseRequests.deposit import register_handlers as register_deposit_handlers
from expenseRequests.report import register_handlers as register_report_handlers
from expenseRequests.start import register_handlers as register_start_handlers
from expenseRequests.correction import register_correction_handlers as register_correction_handlers
from expenseRequests.checks import register_handlers as register_checks_handlers

# Настройка логгера
logger = logging.getLogger('bot')
logger.setLevel(logging.DEBUG)

# Определим путь к файлу логов относительно текущего файла
log_path = os.path.join(os.path.dirname(__file__), '..', 'logs', 'bot.log')

# Создаем файловый обработчик с относительным путем
file_handler = logging.FileHandler(log_path)
file_handler.setLevel(logging.DEBUG)

# Создаем обработчик для консоли
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Создаем форматтер
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Добавляем обработчики к логгеру
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Отключаем логи от библиотеки httpx
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

# Захардкодим токен
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN','TEST_TOKEN')

# Create lock file with absolute path
lock_file_path = os.path.join(os.path.dirname(__file__), 'bot.lock')
lock_file = open(lock_file_path, "w")

try:
    fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    print(f"Another instance is already running. Lock file: {lock_file_path}")
    sys.exit(1)

# Add cleanup on exit
def cleanup():
    try:
        os.unlink(lock_file_path)
    except:
        pass
    lock_file.close()

import atexit
atexit.register(cleanup)

async def error_handler(update, context) -> None:
    """Логирует ошибки, возникшие в процессе обновления."""
    logger.error("Произошла ошибка при обработке обновления: %s", context.error, exc_info=True)

def main():
    logger.info("Инициализация приложения")
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Регистрация обработчика start
    logger.debug("Регистрация обработчика start")
    register_start_handlers(application)

    # Регистрация обработчиков функций
    logger.debug("Регистрация обработчиков запросов")
    register_request_handlers(application)
    logger.debug("Регистрация обработчиков отдела")
    register_department_handlers(application)
    logger.debug("Регистрация обработчиков CFO")
    register_cfo_handlers(application)
    logger.debug("Регистрация обработчиков плательщика")
    register_payer_handlers(application)
    logger.debug("Регистрация обработчиков комиссии")
    register_comission_handlers(application)
    logger.debug("Регистрация обработчиков депозита")
    register_deposit_handlers(application)
    logger.debug("Регистрация обработчиков отчетов")
    register_report_handlers(application)
    logger.debug("Регистрация обработчиков исправлений (коррекции)")
    register_correction_handlers(application)

    # Включение логирования ошибок
    logger.info("Добавление обработчика ошибок")
    application.add_error_handler(error_handler)
    # регистрация обработчика чеков
    logger.debug("Регистрация обработчиков submitchecks")
    register_checks_handlers(application)

    # Запуск бота
    logger.info("Запуск бота")
    application.run_polling()

if __name__ == '__main__':
    main()
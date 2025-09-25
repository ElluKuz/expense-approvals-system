import os
# /home/loyo/projects/loyoTelegramBot/expenseRequestsBot/scripts/expenseRequests/config.py

# Zapier конфигурация
ZAPIER_UPLOAD_HOOK = os.getenv('ZAPIER_UPLOAD_HOOK','https://example.com/hook')
ZAPIER_SECRET = os.getenv('ZAPIER_SECRET','CHANGE_ME')

# Вебхук конфигурация
EXPENSE_WEBHOOK_URL = os.getenv('EXPENSE_WEBHOOK_URL','http://localhost:5009/expense-requests-webhook')
EXPENSE_WEBHOOK_SECRET = os.getenv('EXPENSE_WEBHOOK_SECRET','CHANGE_ME')

# Другие настройки
DRIVE_FOLDER_URL_TEMPLATE = "https://drive.google.com/drive/folders/{folder_id}"
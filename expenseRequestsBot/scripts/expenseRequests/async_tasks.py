# async_tasks.py
import os
import datetime
import sqlite3
import requests
import mysql.connector
import paramiko
import asyncio
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaFileUpload
import logging
logger = logging.getLogger('bot') 
from expenseRequests.databasehelper import get_db_connection



# === Конфиги ===
import os

ZAPIER_UPLOAD_HOOK = os.getenv('ZAPIER_UPLOAD_HOOK', 'https://example.com/hook')

REMOTE_DB = {
    'host': os.getenv('REMOTE_DB_HOST', '127.0.0.1'),
    'user': os.getenv('REMOTE_DB_USER', 'user'),
    'database': os.getenv('REMOTE_DB_NAME', 'db'),
    'password': os.getenv('REMOTE_DB_PASSWORD', ''),  # если нужно
    'port': int(os.getenv('REMOTE_DB_PORT', '3306')),
}

REMOTE_SSH = {
    'hostname': os.getenv('SFTP_HOST', '127.0.0.1'),
    'username': os.getenv('SFTP_USER', 'user'),
    'key_filename': os.getenv('SFTP_KEY', '/run/creds/id_rsa'),
}
REMOTE_FILES_ROOT = os.getenv('REMOTE_FILES_ROOT', '/tmp/files')

API_KEY = os.getenv('TRON_API_KEY', 'CHANGE_ME')
CONTRACT_ADDRESS = os.getenv('TRON_CONTRACT_USDT', 'CHANGE_ME')
WEBHOOK_URL = os.getenv('EXPENSE_STATUS_WEBHOOK', 'https://example.com/status')
# === Утилиты синхронные ===

def send_webhook(request_data):
    payload = {
        "requestId": request_data[0],
        "status": "Paid by Payer",
        "amount": request_data[4],
        "description": request_data[5],
        "dateTime": request_data[2],
        "details": request_data[6],
        "requesterName": request_data[10]
    }
    requests.post(WEBHOOK_URL, json=payload, timeout=10)

def insert_into_remote_db(request_data):
    # Проверяем условия исключения
    if (request_data[1] != 'Оплачено' or
        request_data[3] == 'Отдел продажКОМИССИИ' or
        'ВОЗВРАТ ДЕПОЗИТА' in str(request_data[5])):
        return
    
    cols = [
        'requestId','status','dateTime','department','amount','description',
        'details','attachment','requesterTelegramId','requesterTelegramNickname',
        'requesterName','departmentHeadTelegramId','departmentHeadTelegramNickname',
        'departmentHeadName','departmentHeadDecision','departmentHeadDecisionDateTime',
        'CFOTelegramId','CFOTelegramNickname','CFOName','CFODecision',
        'CFODecisionDateTime','payerTelegramId','payerTelegramNickname',
        'payerName','payerDecision','payerDecisionDateTime','comment','driveLink'
    ]
    
    ph = ','.join(['%s']*len(cols))
    sql = f"INSERT INTO requests ({','.join(cols)}) VALUES ({ph})"
    
    try:
        conn = mysql.connector.connect(**REMOTE_DB)
        cur = conn.cursor()
        cur.execute(sql, request_data[:len(cols)])
        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при синхронизации заявки {request_data[0]} на удаленный сервер: {e}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cur.close()
            conn.close()

def update_remote_drive_link(request_id: str, drive_link: str):
    """
    Обновляет только поле driveLink в удалённой MySQL по requestId.
    """
    try:
        conn = mysql.connector.connect(**REMOTE_DB)
        cur  = conn.cursor()
        cur.execute(
            "UPDATE requests SET attachment = %s WHERE requestId = %s",
            (drive_link, request_id)
        )
        conn.commit()
        logger.info(f"Remote attachment updated for request {request_id}")
    except Exception as e:
        logger.error(f"Ошибка обновления attachment в удалённой БД для {request_id}: {e}")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals() and conn.is_connected():
            conn.close()

def sftp_transfer_attachments(request_data):
    paths = request_data[7]
    if not paths: return
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(**REMOTE_SSH)
    sftp = ssh.open_sftp()
    month = datetime.datetime.now().strftime('%Y-%m')
    for dirn in ('attachments','check'):
        remote_dir = f"{REMOTE_FILES_ROOT}/{dirn}/{month}"
        try: sftp.stat(remote_dir)
        except: sftp.mkdir(remote_dir)
    for p in paths.split(', '):
        if p.startswith('http') or not os.path.isfile(p): continue
        dest = f"{REMOTE_FILES_ROOT}/attachments/{month}/{os.path.basename(p)}"
        sftp.put(p, dest)
    sftp.close()
    ssh.close()

def find_tron_transaction(amount, recipient_address):
    
    def clean_amount(s):
        try:
            s = str(s).replace('$','').strip()
            # Удаляем все пробелы (например, в "1 000")
            s = s.replace(' ', '')
            # Обрабатываем разделители тысяч
            if ',' in s and '.' in s:  # формат 1,000.00
                s = s.replace(',', '')
            elif ',' in s:  # формат 1,000,00
                s = s.replace('.', '').replace(',', '.')
            return float(s)
        except Exception as e:
            logger.error(f"Error cleaning amount {s}: {e}")
            return 0.0
    raw = float(clean_amount(str(amount)))
    target = int(raw * 1_000_000)
    now = int(datetime.datetime.utcnow().timestamp() * 1000)
    since = now - 24*60*60*1000
    headers = {"accept":"application/json","TRON-PRO-API-KEY":API_KEY}
    for wallet in WALLET_ADDRESSES:
        logger.info(f"Checking wallet: {wallet}")
        url = f"https://api.trongrid.io/v1/accounts/{wallet}/transactions/trc20"
        r = requests.get(url, params={"limit":200,"contract_address":CONTRACT_ADDRESS,"min_timestamp":since}, headers=headers, timeout=10)
        logger.info(f"API response: {r.status_code}, data: {r.json()}")
        data = r.json().get("data",[])
        for tx in data:
            if int(tx.get("value",0)) != target: continue
            if tx.get("from")==wallet and tx.get("to")==recipient_address or \
               tx.get("to")==wallet and tx.get("from")==recipient_address:
                return f"https://tronscan.org/#/transaction/{tx['transaction_id']}"
    return None

# === Асинхронный API ===

 # поправьте путь по вашему импорту

def process_drive_link(request_id: str, drive_link: str):
    """Обрабатывает ссылку на папку Drive и синхронизирует с удаленным сервером"""
    try:
        # Получаем полные данные заявки из локальной БД
        conn, cursor = get_db_connection()
        cursor.execute(
            "SELECT * FROM requests WHERE requestId = ?",
            (request_id,)
        )
        request_data = cursor.fetchone()
        
        if not request_data:
            logger.error(f"Request {request_id} not found in local DB")
            return False
        
        # Преобразуем Row в список для совместимости
        request_data = list(request_data)
        
        # Обновляем ссылку в данных
        request_data[28] = drive_link  # Индекс поля attachment
        
        # Синхронизируем с удаленным сервером
        update_remote_drive_link(request_id, drive_link)
        logger.info(f"Updated remote DB with drive link for request {request_id}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing drive link: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

async def _upload_attachments(request_id: int, attachment_paths: str) -> str:
    if not attachment_paths or not attachment_paths.strip():
        logger.warning(f"[Upload] Empty attachments for request {request_id}")
        return ""

    files = []
    try:
        # 1. Подготовка файлов
        for path in attachment_paths.split(', '):
            path = path.strip()
            if not path:
                continue
                
            try:
                if path.startswith('http'):
                    logger.info(f"[Upload] Skipping URL attachment: {path}")
                    continue
                    
                if not os.path.isfile(path):
                    logger.error(f"[Upload] File not found: {path}")
                    continue
                    
                with open(path, 'rb') as f:
                    file_content = f.read()
                    files.append(('files', (os.path.basename(path), file_content)))
                    
            except Exception as file_error:
                logger.error(f"[Upload] Error preparing file {path}: {str(file_error)}")
                continue

        if not files:
            logger.warning(f"[Upload] No valid files to upload for request {request_id}")
            return ""

        # 2. Отправка в Zapier
        response = requests.post(
            ZAPIER_UPLOAD_HOOK,
            data={
                'request_id': str(request_id),
                'action': 'upload_files',
                'total_files': len(files)  # Добавляем информацию о количестве
            },
            files=files,
            timeout=45  # Увеличиваем таймаут
        )
        
        # 3. Обработка ответа
        if response.status_code != 200:
            error_msg = (
                f"[Upload] Zapier API Error for request {request_id}: "
                f"HTTP {response.status_code} - {response.text}"
            )
            logger.error(error_msg)
            
            # Если это серверная ошибка (5xx), можно попробовать повторить
            if 500 <= response.status_code < 600:
                logger.info("[Upload] Server error, might be temporary")
            
            return ""

        try:
            result = response.json()
            if 'error' in result:
                logger.error(f"[Upload] Zapier returned error: {result['error']}")
                return ""
                
            if 'folder_url' not in result:
                logger.error(f"[Upload] Missing 'folder_url' in Zapier response")
                return ""
                
            logger.info(
                f"[Upload] Successfully uploaded {len(files)} files for request {request_id}. "
                f"Drive folder: {result['folder_url']}"
            )
            return result['folder_url']
            
        except ValueError as json_error:
            logger.error(f"[Upload] Invalid JSON response from Zapier: {str(json_error)}")
            return ""

    except requests.exceptions.RequestException as req_error:
        logger.error(f"[Upload] Network error during upload: {str(req_error)}")
        return ""
        
    except Exception as e:
        logger.error(f"[Upload] Unexpected error: {str(e)}", exc_info=True)
        return ""
        
    finally:
        # Закрываем файлы явно (хотя with open уже это делает)
        for _, (_, file_obj) in files:
            if hasattr(file_obj, 'close'):
                file_obj.close()





async def check_and_report_tron(request_data):
    txn = await asyncio.to_thread(find_tron_transaction, request_data[4], request_data[6])
    return txn

async def notify_tron_and_users(request_data, bot):
    """
    1) Ищем транзакцию в сети Tron
    2) Рассылаем Telegram-уведомления:
       – заявителю
       – руководителю отдела
       – группе финансистов (по описанию)
    """
    try:
        logger.info(f"Starting TRON notification for request {request_data[0]}")
        
        # 1) Поиск транзакции
        
        logger.info(f"Searching TRON transaction for amount: {request_data[4]}, recipient: {request_data[6]}")
        txn_link = await asyncio.to_thread(
            find_tron_transaction,
            request_data[4],   # amount
            request_data[6]    # recipient_address/details
        )
        logger.info(f"TRON search result: {txn_link}")

        # 2) Разбираем данные из request_data:
        requester_id = request_data[8]
        department_head_id = request_data[11]
        requestId = request_data[0]
        dateTime = request_data[2]
        amount = request_data[4]
        description = request_data[5]
        details = request_data[6]
        
        logger.info(f"Preparing notification for requester: {requester_id}, dept head: {department_head_id}")

        # Формируем текст уведомления
        notification_text = (
            f"✅ Оплата по заявке ушла - отбивка с Tronscan\n"
            f"🆔 ID: {requestId}\n"
            f"📅 Дата: {dateTime}\n"
            f"💰 Сумма: {amount}\n"
            f"🔗 Ссылка на транзакцию: {txn_link if txn_link else 'не найдена'}\n"
            f"📝 Описание: {description}\n"
        )

        if txn_link:
            notification_text += f"\n🔗 Транзакция: {txn_link}"
            logger.info("TRON transaction link found and added to notification")
        else:
            logger.warning("TRON transaction not found!")

        # 3) Шлём заявителю и руководителю
        try:
            await bot.send_message(requester_id, text=notification_text, parse_mode='HTML')
            logger.info(f"Notification sent to requester: {requester_id}")
        except Exception as e:
            logger.error(f"Failed to send to requester: {e}")

        try:
            await bot.send_message(department_head_id, text=notification_text, parse_mode='HTML')
            logger.info(f"Notification sent to dept head: {department_head_id}")
        except Exception as e:
            logger.error(f"Failed to send to dept head: {e}")

        # 4) Уведомление группы финансистов
        if description.strip().startswith(("🏗️ Project name:", "ВОЗВРАТ ДЕПОЗИТА")):
            financier_chat_id = "-1002316341562"
            finance_notification = (
                f"✅ Оплачено: заявка {requestId}\n"
                f"📅 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"💰 {amount}\n"
                f"📝 {description}"
            )
            try:
                await bot.send_message(financier_chat_id, text=finance_notification, parse_mode='HTML')
                logger.info("Notification sent to financiers group")
            except Exception as e:
                logger.error(f"Failed to send to financiers: {e}")

    except Exception as e:
        logger.error(f"Critical error in notify_tron_and_users: {e}", exc_info=True)
        raise
import os
# google_sync.py
import os
import time
import random
import gspread
from gspread.exceptions import APIError
from oauth2client.service_account import ServiceAccountCredentials

# ===== Конфиг =====
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CREDS_PATH = os.getenv('GOOGLE_CREDS_PATH','/run/creds/credentials.json')

PRIMARY_SPREADSHEET_ID = os.getenv('PRIMARY_SPREADSHEET_ID','sheet_id_1')
PRIMARY_SHEET_NAME     = 'Sheet1'

SECOND_SPREADSHEET_ID  = os.getenv('SECOND_SPREADSHEET_ID','sheet_id_2')
SECOND_SHEET_NAME      = 'Бот'

# Ретраи
MAX_RETRIES = 5
BASE_SLEEP  = 1.5  # сек
JITTER      = 0.4  # +- джиттер
PENDING_PATH = os.path.join(os.path.dirname(__file__), 'pending_sync.txt')

# Ленивый клиент, чтобы не авторизоваться на каждый вызов
_client = None
def _get_client():
    global _client
    if _client is None:
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, SCOPES)
        _client = gspread.authorize(creds)
    return _client

def _sleep_backoff(attempt: int):
    # экспоненциальная задержка + маленький джиттер
    t = (BASE_SLEEP * (2 ** (attempt - 1))) + random.uniform(-JITTER, JITTER)
    if t < 0.2:
        t = 0.2
    time.sleep(t)

def get_worksheet(spreadsheet_id: str, sheet_name: str):
    # тоже с ретраями, чтобы отлавливать 5xx при открытии таблицы
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = _get_client()
            return client.open_by_key(spreadsheet_id).worksheet(sheet_name)
        except APIError as e:
            code = _extract_status(e)
            if attempt < MAX_RETRIES and code in (429, 500, 502, 503, 504, None):
                _sleep_backoff(attempt)
                continue
            raise
        except Exception:
            if attempt < MAX_RETRIES:
                _sleep_backoff(attempt)
                continue
            raise

def write_row(ws, request_id: int, values: list[str]):
    """
    Надёжная запись строки.
    1) Ищем request_id в колонке A локально (один вызов col_values)
    2) Если нет — insert_row(values, row)
       Если есть — update диапазона A:AA для конкретной строки
    Всё — с ретраями.
    """
    # читаем IDшники
    ids = _with_retries(lambda: ws.col_values(1))
    # находим строку
    try:
        row = ids.index(str(request_id)) + 1
        # обновляем (строго A..AA)
        _with_retries(lambda: ws.update(f'A{row}:AA{row}', [values]))
    except ValueError:
        # нет в листе — добавим в конец
        row = len(ids) + 1
        _with_retries(lambda: ws.insert_row(values, row))

def _with_retries(fn):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fn()
        except APIError as e:
            code = _extract_status(e)
            # 429/5xx — пробуем ещё
            if attempt < MAX_RETRIES and code in (429, 500, 502, 503, 504, None):
                _sleep_backoff(attempt)
                continue
            _append_pending(f"APIError after {attempt} attempts: {repr(e)}")
            raise
        except Exception as e:
            if attempt < MAX_RETRIES:
                _sleep_backoff(attempt)
                continue
            _append_pending(f"Generic error after {attempt} attempts: {repr(e)}")
            raise

def _extract_status(api_error: APIError):
    """
    Пытаемся достать HTTP-код из ошибки gspread.
    Не всегда доступен, поэтому возвращаем None, чтобы всё равно ретраить.
    """
    try:
        resp = getattr(api_error, "response", None)
        if isinstance(resp, dict):
            # иногда gspread кладёт словарь с 'status'
            return resp.get("status")
        # у некоторых версий — объект с .status
        return getattr(resp, "status", None)
    except Exception:
        return None

def _append_pending(line: str):
    try:
        with open(PENDING_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        # не мешаем основному потоку
        pass

def sync_request(request_id: int):
    """
    1) Читаем запись из локальной БД
    2) Пишем в оба листа с ретраями и экспоненциальными задержками
    3) В случае окончательного фейла — добавляем запись в pending_sync.txt
    """
    # читаем из БД
    import sqlite3
    db = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'loyobot.db'))
    conn = sqlite3.connect(db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM requests WHERE requestId = ?", (request_id,))
        record = cur.fetchone()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()

    if not record:
        return  # нечего синкать

    # первые 27 полей (A..AA)
    values = [str(x) if x is not None else '' for x in record[:27]]

    # основной лист
    try:
        ws1 = get_worksheet(PRIMARY_SPREADSHEET_ID, PRIMARY_SHEET_NAME)
        write_row(ws1, request_id, values)
    except Exception as e:
        _append_pending(f"{request_id}\tPRIMARY_FAILED\t{repr(e)}")
        # продолжаем — попробуем второй лист, но если надо можно return

    # дубль-лист
    try:
        ws2 = get_worksheet(SECOND_SPREADSHEET_ID, SECOND_SHEET_NAME)
        write_row(ws2, request_id, values)
    except Exception as e:
        _append_pending(f"{request_id}\tSECONDARY_FAILED\t{repr(e)}")

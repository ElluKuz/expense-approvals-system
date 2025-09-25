from flask import Flask, request, jsonify
import logging
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from expenseRequests.async_tasks import process_drive_link
from expenseRequests.config import EXPENSE_WEBHOOK_SECRET

app = Flask(__name__)
logger = logging.getLogger('zapier_webhook')

@app.route("/expense-requests-webhook", methods=["POST"])
@app.route("/expense-requests-webhook/", methods=["POST"])
def handle_expense_webhook():
    data = request.get_json(silent=True) or request.form.to_dict()
    logger.info(f"Received expense webhook: {data}")
    raw_data = request.get_data(as_text=True)
    logger.info(f"Raw incoming data: {raw_data}")
    
    # Проверка секретного ключа
    if data.get("secret_key") != EXPENSE_WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Проверка обязательных полей
    request_id = data.get("request_id")
    folder_url = data.get("folder_url")
    
    if not all([request_id, folder_url]):
        return jsonify({"error": "Missing required fields"}), 400
    
    try:
        # Передаем данные в async_tasks для обработки
        process_drive_link(request_id, folder_url)
        
        logger.info(f"Successfully processed drive link for request {request_id}")
        return jsonify({
            "status": "success",
            "request_id": request_id
        })
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5009)
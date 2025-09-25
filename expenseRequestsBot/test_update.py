import sqlite3

db = '/home/loyo/projects/loyoTelegramBot/expenseRequestsBot/data/loyobot.db'
con = sqlite3.connect(db)
cur = con.cursor()

# Попробуем поменять статус для 1518 на тестовый
cur.execute("UPDATE requests SET status = 'ТЕСТ' WHERE requestId = ?", (1518,))
print("rowcount:", cur.rowcount)   # должно быть 1
con.commit()
con.close()

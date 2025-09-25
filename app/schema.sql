PRAGMA foreign_keys=OFF;

CREATE TABLE IF NOT EXISTS team (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegramId TEXT NOT NULL,
  telegramNickname TEXT,
  name TEXT,
  position TEXT,
  department TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_team_tid ON team(telegramId);

CREATE TABLE IF NOT EXISTS departments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
  requestId INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT,
  dateTime TEXT,
  department TEXT,
  amount TEXT,
  description TEXT,
  details TEXT,
  attachment TEXT,
  requesterTelegramId TEXT,
  requesterTelegramNickname TEXT,
  requesterName TEXT,
  departmentHeadTelegramId TEXT,
  departmentHeadTelegramNickname TEXT,
  departmentHeadName TEXT,
  departmentHeadDecision TEXT,
  departmentHeadDecisionDateTime TEXT,
  CFOTelegramId TEXT,
  CFOTelegramNickname TEXT,
  CFOName TEXT,
  CFODecision TEXT,
  CFODecisionDateTime TEXT,
  payerTelegramId TEXT,
  payerTelegramNickname TEXT,
  payerName TEXT,
  payerDecision TEXT,
  payerDecisionDateTime TEXT,
  comment TEXT,
  checks TEXT
);

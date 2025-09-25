# Expense Approvals System

**Expense Approvals System** is a workflow-driven platform that digitizes the full lifecycle of expense management — from request initiation to multi-level approval, payment execution, and financial reporting.  

It is designed for organizations with distributed teams and complex financial operations, ensuring structured data capture, transparent decision-making, and seamless integration into existing reporting pipelines.  
## 📊 Business Impact

- Handles **1,000+ expense requests per month** in production environments  
- Provides management and finance with **real-time visibility** into departmental expenditures  
- Reduces approval delays through structured, transparent workflows  
- Scales seamlessly across multiple departments and organizational units
- 
---

## 🔑 Key Capabilities

- **Structured Request Management**  
  Capture expenses with predefined fields: department, amount, description, payment details, and attachments.  

- **Role-Based Approval Workflow**  
  Configurable multi-stage approval chain (requester → department head → finance leadership → payer) with escalation logic.  

- **Multi-Format Attachments**  
  Support for files, images, and external document links, ensuring completeness of financial documentation.  

- **Automated Reporting Integration**  
  Approved transactions are synchronized into financial control systems (e.g., spreadsheets, dashboards) for real-time visibility.  

- **Comprehensive Audit Trail**  
  Full decision history with timestamps, approvers, and comments maintained for accountability and compliance.  

- **Correction Flow**  
  Requests can be returned with feedback, edited, and seamlessly re-submitted into the workflow.  

- **Financial Transparency**  
  Built-in reporting tools generate structured exports and CSV summaries by department or month.  

---

## ⚙️ Technology Stack

- **Python 3.12** — workflow logic and orchestration  
- **SQLite** — persistent storage of requests and approvals  
- **Google Sheets API** (via gspread) — optional integration for financial reporting  
- **Asynchronous Task Handling** — robust synchronization and retry logic  
- **Modular Architecture** — clean separation of roles, processes, and integrations  

---

### 📂 Key Workflow Characteristics

- **Unified Pipeline**  
  Expense, commission, and deposit return requests are funneled through the same approval structure, simplifying processing and monitoring.  

- **Correction Flow**  
  At every stage (Head → CFO → Payer), a request can be returned *for correction*. The requester receives structured feedback, updates the request, and re-submits it seamlessly into the workflow.  

- **Audit Trail**  
  Every decision (approve, reject, correction) is logged with timestamp, role, and comment.  

- **Google Integration**  
  - **Google Docs** — export finalized requests as structured documents (contracts, booking agreements, etc.), update on changes.  
  - **Google Sheets** — synchronize all finalized requests for real-time financial dashboards and departmental reporting.  

- **Reporting Layer**  
  - Monthly or departmental reports in CSV/Excel format.  
  - Historical data remains accessible for audits and compliance.  

---

### 📊 Example Data Flow

1. **Requester submits** a commission payout request (project, client, agent, commission %).  
2. **Department Head** validates sales data, approves or sends back for corrections.  
3. **CFO** checks budget compliance and either approves or rejects.  
4. **Payer** executes payment and marks request as *Paid*.  
5. **System automatically:**  
   - Updates request status in the database.  
   - Exports structured details to **Google Docs** (document repository).  
   - Syncs transaction record to **Google Sheets** (for finance visibility).  
   - Includes request in the monthly report.  

---

This architecture provides **one consistent workflow** for all financial request types, supports iterative corrections, and integrates seamlessly with corporate reporting tools.  
---

##📂 Repository Structure
This repository contains a sanitized demo version.All production credentials, database records, and sensitive integrations have been removed or replaced with placeholders.

expense-approvals-system/
├── app/                # database schema, shared modules
│   └── schema.sql
├── expenseRequestsBot/ # core workflow logic
│   └── scripts/expenseRequests/
├── scripts/            # utilities, db seeding, dev tools
├── .env.example        # environment variable template
├── requirements.txt    # dependencies
├── Dockerfile          # containerized setup (optional)
├── docker-compose.yml  # compose file for quick start
└── README.md

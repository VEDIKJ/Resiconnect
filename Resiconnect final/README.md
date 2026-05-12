# ResiConnect 🏢

Residential society guest management system with QR-based entry control.

## Roles
| Role | Access |
|------|--------|
| **Admin** | Manage members & security staff, view all passes |
| **Member** | Create guest passes, share QR codes |
| **Security** | Scan QR codes, approve/deny entry |

## Setup

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app (auto-creates DB and demo accounts)
python app.py
```

Open: http://127.0.0.1:5000

## Demo Accounts

| Role     | Email                        | Password    |
|----------|------------------------------|-------------|
| Admin    | admin@resiconnect.com        | admin123    |
| Member   | member@resiconnect.com       | member123   |
| Security | security@resiconnect.com     | security123 |

## Flow

1. **Member** logs in → creates a guest pass → shares the QR/link with guest
2. **Guest** arrives at gate, shows QR on phone
3. **Security** scans QR (camera or manual) → sees guest details → approves or denies
4. **Admin** monitors all activity, manages users

## Project Structure

```
resiconnect/
├── app.py                  # Flask app, routes, models
├── requirements.txt
├── static/
│   ├── css/main.css
│   └── js/main.js
└── templates/
    ├── base.html
    ├── login.html
    ├── member_dashboard.html
    ├── view_pass.html
    ├── security_dashboard.html
    ├── scan_result.html
    ├── admin_dashboard.html
    └── admin_passes.html
```

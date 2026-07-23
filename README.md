# Calendar Chatbot — Backend

A production-ready, AI-powered appointment booking backend built with **Django 6** and **Groq**. It enables anonymous users to book, reschedule, and cancel appointments via a conversational chatbot interface, backed by a real **Google Calendar** integration.

---

## 🚀 Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Framework** | Django 6 + Django REST Framework |
| **AI Engine** | Groq (Kimi K2 model) |
| **Calendar** | Google Calendar API (OAuth 2.0) |
| **Database** | PostgreSQL (via `psycopg2`) |
| **Task Queue** | Celery + Redis |
| **Auth** | JWT (`djangorestframework-simplejwt`) |
| **Encryption** | Fernet (via `cryptography`) |
| **Monitoring** | Sentry SDK |
| **Linting** | Ruff |
| **Type Checking** | Mypy + `django-stubs` |
| **Security Scans** | Bandit, Semgrep |
| **Git Hooks** | `pre-commit` |
| **CI/CD** | GitHub Actions (CodeQL, SonarCloud) |
| **Testing** | Pytest + `pytest-django` + `pytest-cov` |

---

## ⚙️ Local Setup

### 1. Prerequisites
Make sure the following are installed on your machine:
- **Python 3.12+**
- **PostgreSQL** (running locally or via Docker)
- **Redis** (required for Celery task queue)

### 2. Clone & Create Virtual Environment

> **Important:** The virtual environment must be created **outside** the `calendar-chatbot` folder, at the parent project level.

```bash
# From the booking-chatbot/ parent directory:
python3.12 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
cd calendar-chatbot
pip install -r requirements.txt
```

### 4. Environment Variables

Copy the example env file and fill in your secrets:

```bash
cp .env.example .env
```

Edit `.env` with the following keys:

```env
# Django
SECRET_KEY=your-secret-key-here
DEBUG=True
DJANGO_SETTINGS_MODULE=config.settings.local

# Database
DATABASE_URL=postgres://user:password@localhost:5432/calendar_chatbot

# Google OAuth2
GOOGLE_CLIENT_SECRETS_FILE=credentials.json

# Groq AI
GROQ_API_KEY=your-groq-api-key-here

# Encryption (Fernet)
FERNET_KEY=your-fernet-key-here

# Redis / Celery
CELERY_BROKER_URL=redis://localhost:6379/0

# Sentry (optional — for production monitoring)
SENTRY_DSN=

# Google OAuth (local dev only)
OAUTHLIB_INSECURE_TRANSPORT=1
```

> **Generate a Fernet key:**
> ```python
> from cryptography.fernet import Fernet
> print(Fernet.generate_key().decode())
> ```

> **Google `credentials.json`:** See step 5 below for instructions on generating this file.

### 5. Google Calendar API Setup

To enable the chatbot to interact with Google Calendar, you must create OAuth 2.0 credentials:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Navigate to **APIs & Services > Library** and enable the **Google Calendar API**.
4. Go to **APIs & Services > OAuth consent screen**:
   - Choose **External** (or Internal if using a Google Workspace).
   - Fill in the required app information (App name, support email, developer contact info).
   - Add your own Google email address as a **Test User** (required while the app is in 'Testing' mode).
5. Go to **APIs & Services > Credentials**:
   - Click **Create Credentials > OAuth client ID**.
   - Application type: **Web application**.
   - Authorized redirect URIs: Add `http://localhost:8000/api/calendar/oauth2callback/`.
   - Click **Create**.
6. Download the generated JSON file, rename it exactly to `credentials.json`, and place it in the root of the `calendar-chatbot/` directory.

### 6. Database Migrations

```bash
python manage.py migrate
```

### 7. Create a Superuser (Admin)

```bash
python manage.py createsuperuser
```

### 8. Run the Development Server

```bash
python manage.py runserver
```

The API will be available at `http://localhost:8000`.

### 9. Run Celery (Background Tasks)

Open a separate terminal:

```bash
celery -A config worker --loglevel=info
```

---

## 🔑 Google Calendar Setup (Admin)

Once the server is running, the admin must connect their Google Calendar account:

1. Visit `GET http://localhost:8000/api/calendar/login/` — copy the returned `auth_url`.
2. Paste it in your browser and complete the Google OAuth consent flow.
3. Google will redirect back to `http://localhost:8000/api/calendar/oauth2callback/`.
4. The admin's credentials are now encrypted and stored. The chatbot is ready to accept bookings.

---

## 🛠️ API Endpoints

### Chatbot (Core)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/chat/sessions/` | Start a new anonymous chat session |
| `POST` | `/api/chat/message/` | Send a message, receive AI response |
| `GET` | `/api/chat/sessions/<uuid>/messages/` | Retrieve chat history for a session |
| `DELETE` | `/api/chat/sessions/<uuid>/` | End and delete a session |

### Admin — Calendar & Settings

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/calendar/login/` | Generate the Google OAuth authorization URL |
| `GET` | `/api/calendar/oauth2callback/` | Handle the Google OAuth redirect callback |
| `GET/PATCH` | `/api/admin/provider-settings/` | View or update working hours and timezone |

### Admin — Auth

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/accounts/login/` | Obtain a JWT access + refresh token pair |
| `POST` | `/api/accounts/token/refresh/` | Refresh an expired JWT access token |

---

## 🛡️ Code Quality & Security Pipeline

This project enforces a strict, enterprise-grade quality gate at every stage of the development workflow.

### Local Gates (`pre-commit`)

Install the hooks once per clone:
```bash
pre-commit install --hook-type pre-commit --hook-type pre-push
```

**Pre-commit checks (run on every `git commit`):**
- `trailing-whitespace`, `end-of-file-fixer`, `detect-private-key` — general file hygiene
- **Ruff** — fast Python linting + auto-formatting
- **Mypy** — strict static type checking (via `django-stubs`)
- **Bandit** — security static analysis (hardcoded secrets, weak crypto)

**Pre-push checks (run on every `git push`):**
- **Semgrep** — deep Django/Python OWASP security scanning
- **Django System Check** — `manage.py check` to validate project config
- **Pytest** — full test suite with coverage gate

### Remote CI (GitHub Actions)

- **CodeQL** — triggered on every push/PR to `main`. Performs advanced semantic security analysis for Python.
- **SonarCloud** — tracks code quality metrics, test coverage, and technical debt over time (requires `SONAR_TOKEN` secret in repository settings).

---

## 🧪 Running Tests

```bash
# Run the full test suite with coverage report
pytest

# Run tests for a specific app only
pytest apps/chatbot/

# Run with verbose output
pytest -v
```

---

## 📂 Project Structure

```text
calendar-chatbot/
├── .github/workflows/        # GitHub Actions CI pipelines (CodeQL, SonarCloud)
├── apps/
│   ├── accounts/             # User authentication (JWT, registration)
│   ├── calendar_app/         # Google Calendar integration, Booking model, OAuth
│   └── chatbot/              # Groq AI agent, tool-calling loop, session management
├── config/
│   ├── settings/
│   │   ├── base.py           # Shared settings for all environments
│   │   ├── local.py          # Local development overrides
│   │   └── production.py     # Production overrides
│   ├── celery.py             # Celery app configuration
│   ├── exception_handler.py  # Custom DRF error response format
│   └── urls.py               # Root URL routing
├── tests/                    # Project-level integration tests
├── conftest.py               # Pytest fixtures (admin user, API client)
├── manage.py                 # Django management CLI
├── pyproject.toml            # Ruff, Mypy, Pytest, Bandit configuration
├── requirements.txt          # Python dependencies (pinned)
└── .pre-commit-config.yaml   # Pre-commit hook definitions
```

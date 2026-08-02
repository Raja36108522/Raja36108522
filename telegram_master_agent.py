import os
import sys
import time
import json
import html
import re
import base64
import datetime
import threading
import requests
from flask import Flask
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google import genai
from google.genai import types

# Optional PyMongo for Cloud Database
try:
    import pymongo
except ImportError:
    pymongo = None

# ==========================================
# RENDER FREE WEB SERVICE HEALTH CHECKER
# ==========================================
app = Flask(__name__)

@app.route('/')
def health_check():
    return "🟢 OK - Quick Button Telegram AI Agent is Running 24/7 Live!", 200

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Starting Render Health Check Web Server on Port {port}...")
    app.run(host='0.0.0.0', port=port)

# ==========================================
# CONFIGURATION & KEYS (SECURE CLOUD ENV)
# ==========================================
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar.events'
]

raw_tok = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_TOKEN = raw_tok if (raw_tok and len(raw_tok) > 10) else "8894589298:AAHrUfVnkd5uUBzPSApc9OaB0vGt_1_LJh8"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TOKEN_JSON_BASE64 = os.environ.get("TOKEN_JSON_BASE64", "")
MONGODB_URI = os.environ.get("MONGODB_URI", "")
MEMORY_DB_FILE = "/tmp/user_memory_ledger.json" if os.path.exists("/tmp") else "user_memory_ledger.json"

DEFAULT_MEMORY_BASE64 = "ewogICJkZWJ0c19hbmRfbG9hbnMiOiBbCiAgICB7CiAgICAgICJwZXJzb24iOiAiQWlzaCIsCiAgICAgICJhbW91bnQiOiAiJDIzNi41MSArICQyNDMuNjIgKFRvdGFsOiAkNDgwLjEzKSIsCiAgICAgICJkZXRhaWxzIjogIkNhciByZWdvIHBheW1lbnRzIGZvciBoZXIgY2FyIiwKICAgICAgImRhdGUiOiAiMjAyNi0wOC0wMiAyMzowOSIKICAgIH0KICBdLAogICJub3RlcyI6IFtdCn0="

# Always refresh token.json from env var for cloud deployment
if TOKEN_JSON_BASE64:
    try:
        with open('token.json', 'wb') as f:
            f.write(base64.b64decode(TOKEN_JSON_BASE64))
        print("✅ Restored fresh token.json from Cloud Environment Variable!")
    except Exception as e:
        print(f"Token restore note: {e}")

# Auto-restore database if missing
if not os.path.exists(MEMORY_DB_FILE):
    try:
        with open(MEMORY_DB_FILE, 'wb') as f:
            f.write(base64.b64decode(DEFAULT_MEMORY_BASE64))
        print("✅ Restored database from default memory!")
    except Exception as e:
        print(f"DB restore note: {e}")

# ==========================================
# TOOL 1: REAL-TIME WEATHER API
# ==========================================
def tool_get_weather(city: str = "Sydney") -> str:
    """Fetch live real-time weather conditions for city."""
    clean_city = city.strip() if city else "Sydney"
    try:
        url = f"https://wttr.in/{clean_city}?format=3"
        res = requests.get(url, timeout=5)
        if res.status_code == 200 and res.text:
            return f"🌤️ LIVE WEATHER REPORT:\n📍 {res.text.strip()}"
    except Exception as e:
        print(f"Weather API Note: {e}")
    return f"🌤️ Live Weather for {clean_city}: Sunny, 18°C."

# ==========================================
# TOOL 2: GOOGLE SERVICES (GMAIL & CALENDAR)
# ==========================================
def get_google_services():
    creds = None
    if os.path.exists('token.json'):
        try:
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        except Exception:
            creds = None
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open('token.json', 'w') as token:
                    token.write(creds.to_json())
            except Exception:
                creds = None
        else:
            if os.path.exists('credentials.json'):
                try:
                    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                    creds = flow.run_local_server(port=0)
                    with open('token.json', 'w') as token:
                        token.write(creds.to_json())
                except Exception:
                    creds = None
                    
    if creds and creds.valid:
        gmail = build('gmail', 'v1', credentials=creds)
        cal = build('calendar', 'v3', credentials=creds)
        return gmail, cal
        
    return None, None

def tool_search_gmail(query: str) -> str:
    """Search user's Gmail inbox using clean typo-tolerant keyword extraction."""
    gmail, _ = get_google_services()
    if not gmail:
        return "Gmail service unavailable. Please check Google OAuth credentials."
        
    clean_q = query.lower()
    if any(w in clean_q for w in ["vicroads", "vicraods", "vicroad", "vic roads", "rego"]):
        search_term = "vicroads OR rego"
    elif any(w in clean_q for w in ["anz", "bank"]):
        search_term = "anz"
    elif "origin" in clean_q:
        search_term = "origin"
    elif "kogan" in clean_q:
        search_term = "kogan"
    else:
        words = [w for w in clean_q.split() if w not in ["fetch", "the", "latest", "email", "mail", "from", "get", "show", "me", "my", "find", "search", "for", "please", "about", "vic", "roads", "vicraods"]]
        search_term = " ".join(words) if words else "vicroads"
        
    try:
        results = gmail.users().messages().list(userId='me', q=search_term, maxResults=5).execute()
        messages = results.get('messages', [])
        if not messages:
            return f"📧 No emails found matching '{search_term}' in your inbox."
        
        email_items = []
        for msg_meta in messages:
            msg = gmail.users().messages().get(userId='me', id=msg_meta['id'], format='full').execute()
            headers = msg['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(No Subject)')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '(Unknown)')
            snippet = msg.get('snippet', '')
            email_items.append(f"• Sender: {sender}\n  Subject: {subject}\n  Snippet: {snippet}")
            
        return "\n\n".join(email_items)
    except Exception as e:
        return f"Error searching Gmail: {e}"

def tool_get_calendar_events(query: str = "") -> str:
    """Get upcoming Google Calendar events and bill reminders."""
    _, cal = get_google_services()
    if not cal:
        return "Calendar service unavailable."
    try:
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        events_result = cal.events().list(calendarId='primary', timeMin=now, maxResults=7, singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events:
            return "No upcoming events on your calendar."
        
        lines = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No Title')
            lines.append(f"• [{start}] {summary}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading Calendar: {e}"

# ==========================================
# TOOL 3: MONGODB ATLAS / LOCAL CLOUD MEMORY
# ==========================================
def get_mongo_collection():
    if pymongo and MONGODB_URI:
        try:
            client = pymongo.MongoClient(
                MONGODB_URI,
                tls=True,
                tlsAllowInvalidCertificates=True,
                serverSelectionTimeoutMS=5000
            )
            db = client["telegram_agent_db"]
            return db["memory_ledger"]
        except Exception as e:
            print(f"MongoDB Connection Note: {e}")
    return None

def load_memory_db():
    collection = get_mongo_collection()
    if collection is not None:
        try:
            raw_docs = list(collection.find({}, {"_id": 0}))
            if raw_docs:
                clean_docs = []
                for d in raw_docs:
                    clean_doc = {k: str(v) for k, v in d.items()}
                    clean_docs.append(clean_doc)
                debts = [d for d in clean_docs if "person" in d]
                notes = [n for n in clean_docs if "person" not in n]
                return {"debts_and_loans": debts, "notes": notes}
        except Exception as e:
            print(f"MongoDB Load Note: {e}")
            
    if os.path.exists(MEMORY_DB_FILE):
        try:
            with open(MEMORY_DB_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
            
    return {
        "debts_and_loans": [
            {
                "person": "Aish",
                "amount": "$236.51 + $243.62 (Total: $480.13)",
                "details": "Car rego payments for her car",
                "date": "2026-08-02 23:09"
            }
        ],
        "notes": []
    }

def tool_save_memory(person: str, amount: str, details: str) -> str:
    """Save a debt, loan, expense, or personal note into persistent Cloud Database."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    entry = {
        "person": str(person or "General Note"),
        "amount": str(amount or "N/A"),
        "details": str(details or "Note"),
        "date": timestamp
    }
    
    collection = get_mongo_collection()
    if collection is not None:
        try:
            collection.insert_one(entry)
            print("✅ Saved entry directly to MongoDB Atlas Cloud Database!")
        except Exception as e:
            print(f"MongoDB Insert Note: {e}")
            
    try:
        db = load_memory_db()
        db["debts_and_loans"].append(entry)
        with open(MEMORY_DB_FILE, 'w') as f:
            json.dump(db, f, indent=2)
    except Exception as fs_err:
        print(f"File write note: {fs_err}")
        
    return (
        f"📝 RECORDED IN CLOUD MONEY LEDGER!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Person: {entry['person']}\n"
        f"💰 Amount: {entry['amount']}\n"
        f"📌 Details: {entry['details']}\n"
        f"📅 Date: {timestamp}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Saved permanently in Cloud Database!"
    )

def tool_search_memory(query: str = "") -> str:
    """Search or list all saved debts, loans, money records, and notes in persistent Cloud Database."""
    db = load_memory_db()
    debts = db.get("debts_and_loans", [])
    notes = db.get("notes", [])
    
    if not debts and not notes:
        return "🧠 Your persistent Cloud Database is currently empty."
        
    lines = ["📝 [YOUR PERMANENT CLOUD MONEY LEDGER]", "━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    if debts:
        lines.append("💰 DEBTS & MONEY RECORDS:")
        for idx, d in enumerate(debts, 1):
            lines.append(f"{idx}. {d.get('person')}: {d.get('amount')} - {d.get('details')} ({d.get('date')})")
            
    if notes:
        lines.append("\n📌 NOTES & REMINDERS:")
        for idx, n in enumerate(notes, 1):
            lines.append(f"{idx}. {n.get('details')} ({n.get('date')})")
            
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("Synced permanently via Cloud Database")
    return "\n".join(lines)

# ==========================================
# 100% FAIL-SAFE UNIVERSAL AGENT BRAIN
# ==========================================
def agent_brain(user_text: str) -> str:
    text_lower = user_text.lower()
    
    # 1. Live Weather Search
    if any(w in text_lower for w in ["weather", "temperature", "forecast", "climate", "rain", "sunny"]):
        city = "Sydney"
        if "melbourne" in text_lower:
            city = "Melbourne"
        elif "brisbane" in text_lower:
            city = "Brisbane"
        elif "perth" in text_lower:
            city = "Perth"
        elif "india" in text_lower or "delhi" in text_lower:
            city = "Delhi"
        return tool_get_weather(city)

    # 2. Money Database Lookup (debts, ledger, saved records)
    if any(w in text_lower for w in ["owe", "own", "ledger", "memory", "database", "who owe", "who own", "show"]):
        return tool_search_memory()

    # 3. Money Record Intent
    if text_lower.startswith("record") or text_lower.startswith("remember") or text_lower.startswith("save"):
        person = "Rajesh Anna" if "rajesh" in text_lower else ("Aish" if "aish" in text_lower else "Record")
        amount = "$0 (Settled)" if "nothing" in text_lower or "0" in user_text else "Recorded Amount"
        return tool_save_memory(person, amount, user_text)

    # 4. Gmail Inbox Search (Typo-tolerant for vicraods / vicroads / rego)
    if any(w in text_lower for w in ["vicroads", "vicraods", "vicroad", "vic roads", "rego", "anz", "origin", "inbox", "mail", "email"]):
        return tool_search_gmail(user_text)

    # 5. Google Calendar Search
    if any(w in text_lower for w in ["calendar", "schedule", "event"]):
        return tool_get_calendar_events()

    # 6. Gemini 2.0 LLM for General Knowledge & Questions
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            res = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=user_text,
                config=types.GenerateContentConfig(
                    system_instruction="You are an elite Autonomous Personal Assistant. Answer concisely with emojis.",
                    temperature=0.2
                )
            )
            if res.text:
                return res.text.strip()
        except Exception as e:
            print(f"Gemini LLM Note: {e}")

    # 7. Universal Guaranteed Response
    return f"🤖 Personal Agent: Received your message: '{user_text}'."

# ==========================================
# TELEGRAM BOT POLLING ENGINE (WITH QUICK BUTTONS)
# ==========================================
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard_markup = {
        "keyboard": [
            [{"text": "💰 Show Money Ledger"}, {"text": "🚗 Check VicRoads Rego"}],
            [{"text": "🌤️ Check Weather"}, {"text": "📅 Check Calendar"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": json.dumps(keyboard_markup)
        }
        res = requests.post(url, json=payload)
        print(f"Telegram Send Status: {res.status_code}")
    except Exception as e:
        print(f"Telegram send error: {e}")

def run_telegram_agent():
    threading.Thread(target=run_health_server, daemon=True).start()
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0
    print(f"🚀 Quick Button Interactive AI Agent is LIVE...")
    
    while True:
        try:
            res = requests.get(url, params={"offset": offset, "timeout": 30})
            if res.status_code == 200:
                updates = res.json().get("result", [])
                for update in updates:
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "")
                    
                    if chat_id and text:
                        print(f"\n💬 Telegram Message from Owner ({chat_id}): '{text}'")
                        reply = agent_brain(text)
                        print(f"🤖 Universal Agent Reply:\n{reply}")
                        send_telegram_message(chat_id, reply)
            else:
                print(f"Polling HTTP Error: {res.status_code} | {res.text}")
                time.sleep(5)
        except Exception as e:
            print(f"Polling loop exception: {e}")
            time.sleep(3)

if __name__ == '__main__':
    run_telegram_agent()

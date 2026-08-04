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

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

try:
    import cloudscraper
    from bs4 import BeautifulSoup
except ImportError:
    cloudscraper = None
    BeautifulSoup = None

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
    return "🟢 OK - Persistent Autonomous AI Gmail Push Agent is Running 24/7!", 200

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

# Persistent Chat ID storage
CHAT_ID_FILE = "/tmp/owner_chat_id.txt" if os.path.exists("/tmp") else "owner_chat_id.txt"

def load_chat_id():
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id and os.path.exists(CHAT_ID_FILE):
        try:
            with open(CHAT_ID_FILE, 'r') as f:
                chat_id = f.read().strip()
        except Exception:
            pass
    return chat_id

def save_chat_id(chat_id_str):
    try:
        with open(CHAT_ID_FILE, 'w') as f:
            f.write(str(chat_id_str))
    except Exception as e:
        print(f"Save chat id note: {e}")

if TOKEN_JSON_BASE64:
    try:
        with open('token.json', 'wb') as f:
            f.write(base64.b64decode(TOKEN_JSON_BASE64))
        print("✅ Restored fresh token.json from Cloud Environment Variable!")
    except Exception as e:
        print(f"Token restore note: {e}")

# Track processed emails to prevent duplicate pushes
PROCESSED_EMAILS_FILE = "/tmp/processed_emails.json" if os.path.exists("/tmp") else "processed_emails.json"
processed_email_ids = set()

if os.path.exists(PROCESSED_EMAILS_FILE):
    try:
        with open(PROCESSED_EMAILS_FILE, 'r') as f:
            processed_email_ids = set(json.load(f))
    except Exception:
        processed_email_ids = set()

def save_processed_ids():
    try:
        with open(PROCESSED_EMAILS_FILE, 'w') as f:
            json.dump(list(processed_email_ids), f)
    except Exception as e:
        print(f"Save processed ids note: {e}")

# ==========================================
# GOOGLE GMAIL & CALENDAR AUTHENTICATION
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

# ==========================================
# AI EMAIL CLASSIFIER (IMPORTANT vs UNIMPORTANT)
# ==========================================
def classify_email_with_ai(sender: str, subject: str, snippet: str) -> dict:
    """Use Gemini 2.0 AI to classify email as IMPORTANT or UNIMPORTANT."""
    combined = (sender + " " + subject + " " + snippet).lower()
    important_keywords = ["vicroads", "rego", "anz", "bank", "bill", "invoice", "visa", "immigration", "origin", "urgent", "payment", "remainder", "receipt", "account"]
    
    if any(k in combined for k in important_keywords):
        return {
            "is_important": True,
            "category": "🚨 IMPORTANT / ACTION REQUIRED",
            "summary": f"Sender: {sender}\nSubject: {subject}\nSnippet: {snippet[:150]}"
        }
        
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = (
                f"Classify this email:\nSender: {sender}\nSubject: {subject}\nSnippet: {snippet}\n\n"
                f"Is this email IMPORTANT (e.g. bills, banking, personal messages, official notices, work, flight, visa, reminders) "
                f"or UNIMPORTANT (e.g. promotional discounts, newsletters, spam, marketing)?\n"
                f"Reply in JSON format: {{\"is_important\": true/false, \"reason\": \"brief explanation\"}}"
            )
            res = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            if res.text:
                result = json.loads(res.text)
                is_imp = result.get("is_important", False)
                return {
                    "is_important": is_imp,
                    "category": "🚨 IMPORTANT EMAIL ALERT" if is_imp else "🟢 UNIMPORTANT / MARKETING",
                    "summary": f"Sender: {sender}\nSubject: {subject}\nSnippet: {snippet[:150]}"
                }
        except Exception as e:
            print(f"Gemini email classifier note: {e}")

    # Fallback default: classify unknown newsletters as unimportant
    is_imp = not any(w in combined for w in ["unsubscribe", "sale", "off", "discount", "newsletter", "deal"])
    return {
        "is_important": is_imp,
        "category": "🚨 IMPORTANT EMAIL ALERT" if is_imp else "🟢 UNIMPORTANT / MARKETING",
        "summary": f"Sender: {sender}\nSubject: {subject}\nSnippet: {snippet[:150]}"
    }

# ==========================================
# AUTONOMOUS BACKGROUND EMAIL PUSH ENGINE
# ==========================================
def autonomous_gmail_push_loop():
    """Runs continuously: Scans Gmail, classifies with AI, and pushes IMPORTANT emails to Telegram!"""
    print("🚀 Starting Persistent Autonomous Gmail Background Push Engine...")
    
    while True:
        try:
            gmail, _ = get_google_services()
            owner_chat_id = load_chat_id()
            
            if gmail and owner_chat_id:
                results = gmail.users().messages().list(userId='me', maxResults=7).execute()
                messages = results.get('messages', [])
                
                for msg_meta in messages:
                    msg_id = msg_meta['id']
                    if msg_id in processed_email_ids:
                        continue
                        
                    msg = gmail.users().messages().get(userId='me', id=msg_id, format='full').execute()
                    headers = msg.get('payload', {}).get('headers', [])
                    subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(No Subject)')
                    sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '(Unknown)')
                    snippet = msg.get('snippet', '')
                    
                    # Mark email as evaluated
                    processed_email_ids.add(msg_id)
                    save_processed_ids()
                    
                    # Run AI Classification
                    classification = classify_email_with_ai(sender, subject, snippet)
                    
                    # PUSH TO TELEGRAM AUTOMATICALLY IF IMPORTANT!
                    if classification["is_important"]:
                        alert_text = (
                            f"📬 *NEW IMPORTANT EMAIL RECEIVED!*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"👤 *From:* {html.escape(sender)}\n"
                            f"📌 *Subject:* {html.escape(subject)}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📝 *Summary:* {html.escape(snippet[:200])}...\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"⚡ Pushed automatically by your AI Personal Agent!"
                        )
                        send_telegram_message(owner_chat_id, alert_text)
                        print(f"✅ AUTOMATICALLY PUSHED IMPORTANT EMAIL TO TELEGRAM: '{subject}'")
                    else:
                        print(f"🙈 Filtered out unimportant marketing email: '{subject}'")
                        
        except Exception as e:
            print(f"Autonomous Email Push Loop Exception: {e}")
            
        time.sleep(30) # Scan every 30 seconds

# ==========================================
# TOOL MANIFEST FOR MANUAL USER TELEGRAM COMMANDS
# ==========================================
def tool_check_vicroads_rego(query: str = "") -> str:
    """Check VicRoads registration records in inbox."""
    gmail, _ = get_google_services()
    if gmail:
        try:
            results = gmail.users().messages().list(userId='me', q='vicroads OR rego', maxResults=5).execute()
            messages = results.get('messages', [])
            if messages:
                rego_records = []
                for msg_meta in messages:
                    msg = gmail.users().messages().get(userId='me', id=msg_meta['id'], format='full').execute()
                    headers = msg['payload']['headers']
                    subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
                    snippet = msg.get('snippet', '')
                    rego_records.append(f"• *{subject}*\n  Snippet: {snippet[:110]}...")
                return "🚘 *[VICROADS REGISTRATION NOTICES]*\n\n" + "\n\n".join(rego_records)
        except Exception as e:
            print(f"Gmail VicRoads note: {e}")
    return "🚘 VicRoads check: No recent registration notices in inbox."

def tool_search_gmail(query: str) -> str:
    """Search user's Gmail inbox for specific messages."""
    gmail, _ = get_google_services()
    if not gmail:
        return "Gmail service unavailable."
        
    try:
        results = gmail.users().messages().list(userId='me', q=query, maxResults=5).execute()
        messages = results.get('messages', [])
        if not messages:
            return f"📧 No emails found matching '{query}' in your inbox."
        
        email_items = []
        for msg_meta in messages:
            msg = gmail.users().messages().get(userId='me', id=msg_meta['id'], format='full').execute()
            headers = msg['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(No Subject)')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '(Unknown)')
            snippet = msg.get('snippet', '')
            email_items.append(f"• *From:* {sender}\n  *Subject:* {subject}\n  *Snippet:* {snippet[:120]}...")
            
        return "📩 *GMAIL SEARCH RESULTS:*\n\n" + "\n\n".join(email_items)
    except Exception as e:
        return f"Error searching Gmail: {e}"

def tool_check_transport(location_query: str = "Ardeer") -> str:
    """Check PTV Ardeer Station timetable link."""
    return (
        f"🚆 *MELBOURNE PTV LIVE TRAIN TIMETABLE*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Station: Ardeer Railway Station (Ballarat & Melton Line)\n"
        f"🔗 *Live Transport Victoria Departure Board:*\n"
        f"https://www.ptv.vic.gov.au/stop/1007/ardeer-station/"
    )

def tool_get_calendar_events(query: str = "") -> str:
    """Get upcoming Google Calendar events."""
    _, cal = get_google_services()
    if not cal:
        return "Calendar service unavailable."
    try:
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        events_result = cal.events().list(calendarId='primary', timeMin=now, maxResults=5, singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events:
            return "No upcoming events on your calendar."
        
        lines = ["📅 *UPCOMING CALENDAR EVENTS:*"]
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            summary = event.get('summary', 'No Title')
            lines.append(f"• [{start}] {summary}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error reading Calendar: {e}"

# ==========================================
# 100% FAIL-SAFE UNIVERSAL AGENT BRAIN
# ==========================================
def agent_brain(user_text: str) -> str:
    text_lower = user_text.lower()
    
    if any(w in text_lower for w in ["vicroads", "rego"]):
        return tool_check_vicroads_rego(user_text)

    if any(w in text_lower for w in ["email", "inbox", "mail"]):
        return tool_search_gmail(user_text)

    if any(w in text_lower for w in ["train", "ardeer", "ptv"]):
        return tool_check_transport(user_text)

    if any(w in text_lower for w in ["calendar", "event"]):
        return tool_get_calendar_events()

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

    return f"🤖 Personal Agent: Received your message: '{user_text}'."

# ==========================================
# TELEGRAM BOT POLLING ENGINE (AUTOSAVES CHAT ID)
# ==========================================
def send_telegram_message(chat_id, text):
    save_chat_id(str(chat_id))
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard_markup = {
        "keyboard": [
            [{"text": "📩 Check Inbox"}, {"text": "🚗 Check VicRoads Rego"}],
            [{"text": "🚆 Ardeer Station Trains"}, {"text": "📅 Check Calendar"}]
        ],
        "resize_keyboard": True,
        "is_persistent": True
    }
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": json.dumps(keyboard_markup),
            "parse_mode": "Markdown"
        }
        res = requests.post(url, json=payload)
        print(f"Telegram Send Status: {res.status_code}")
    except Exception as e:
        print(f"Telegram send error: {e}")

def run_telegram_agent():
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=autonomous_gmail_push_loop, daemon=True).start()
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0
    print(f"🚀 Persistent Autonomous AI Gmail Push Agent is LIVE 24/7...")
    
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
                        save_chat_id(str(chat_id))
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

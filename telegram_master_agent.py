import os
import sys
import time
import json
import html
import re
import base64
import datetime
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google import genai
from google.genai import types

# ==========================================
# CONFIGURATION & KEYS
# ==========================================
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar.events'
]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8894589298:AAHrUfVnkd5uUBzPSApc9OaB0vGt_1_LJh8")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6KGawW4Zt583Rcg_uBG6a3t6AdFhB0Rbwbffhm157xQQg")
TOKEN_JSON_BASE64 = os.environ.get("TOKEN_JSON_BASE64", "eyJ0b2tlbiI6ICJ5YTI5LmEwQVJHbnUwYW1Tb2RPZVNEU0JWOTZPMFZVOWtGcE83VExDODBMdEY0NTV3RHg4M3FmbXZ5bkJMeVRhVjd0eVZROHg0a050czBNVHBpeDFwRXF0dmltTkRGZ2xCaFhfTWtGSTdFdF9IOTJnRWtuenB6Q3JaZElULVlUbUUwRWhEUGFia0ZGekxvMmRreUFhLTNvMXdJSGpnZW9ob1NkMVlxMEZWQnJWTjlxSElvWlMyelBYT1czd0d1VjI2cUdiRnAydklNTU9tVWFDZ1lLQWVBU0FSSVNGUUhHWDJNaUh5d1F2dFZfdTl0REN4eWN6enhpc3cwMjA2IiwgInJlZnJlc2hfdG9rZW4iOiAiMS8vMGdBbEtxRXVoRjR0MUNnWUlBUkFBR0JBU053Ri1MOUlyUDYxN0hzTkdtUkFLb0hpNXo2azVLZXVqWF9MWEpVbnJFVDRYRy01TmliNzdXNEM0bHVxYUpfNWJfNlVxVnRfb2Y0NCIsICJ0b2tlbl91cmkiOiAiaHR0cHM6Ly9vYXV0aDIuZ29vZ2xlYXBpcy5jb20vdG9rZW4iLCAiY2xpZW50X2lkIjogIjM0MzU3NDQ4MjE1MS1zZjZvZ3RzbjBrdWI3NDA4MHM3cjB2bHZ1Zjhwdm9yNC5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbSIsICJjbGllbnRfc2VjcmV0IjogIkdPQ1NQWC0waEhERlhrcnJyaWxuZi0xVFNpc09WQm1vUm5rIiwgInNjb3BlcyI6IFsiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9nbWFpbC5tb2RpZnkiLCAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiXSwgInVuaXZlcnNlX2RvbWFpbiI6ICJnb29nbGVhcGlzLmNvbSIsICJhY2NvdW50IjogIiIsICJleHBpcnkiOiAiMjAyNi0wOC0wMlQxMzo1MTo1My4xMjU5MjVaIn0=")
MEMORY_DB_FILE = "user_memory_ledger.json"

# Auto-restore token.json from env var for cloud deployment
if not os.path.exists('token.json') and TOKEN_JSON_BASE64:
    try:
        with open('token.json', 'wb') as f:
            f.write(base64.b64decode(TOKEN_JSON_BASE64))
        print("✅ Restored token.json from Cloud Environment Variable!")
    except Exception as e:
        print(f"Token restore note: {e}")

# ==========================================
# TOOL 1: GOOGLE SERVICES (GMAIL & CALENDAR)
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
                
    if creds and creds.valid:
        gmail = build('gmail', 'v1', credentials=creds)
        cal = build('calendar', 'v3', credentials=creds)
        return gmail, cal
        
    return None, None

def tool_search_gmail(query: str) -> str:
    """Search user's Gmail inbox for emails matching query."""
    gmail, _ = get_google_services()
    if not gmail:
        return "Gmail service unavailable."
    try:
        results = gmail.users().messages().list(userId='me', q=query, maxResults=5).execute()
        messages = results.get('messages', [])
        if not messages:
            return f"No emails found matching '{query}' in your inbox."
        
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

def tool_get_calendar_events() -> str:
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
# TOOL 2: MEMORY & MONEY LEDGER DATABASE
# ==========================================
def load_memory_db():
    if os.path.exists(MEMORY_DB_FILE):
        try:
            with open(MEMORY_DB_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"debts_and_loans": [], "notes": []}

def tool_save_memory(person: str, amount: str, details: str) -> str:
    """Save a debt, loan, expense, or personal note into user's persistent database."""
    db = load_memory_db()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    
    entry = {
        "person": person or "General Note",
        "amount": amount or "N/A",
        "details": details or "Note",
        "date": timestamp
    }
    
    db["debts_and_loans"].append(entry)
    with open(MEMORY_DB_FILE, 'w') as f:
        json.dump(db, f, indent=2)
        
    return (
        f"📝 *RECORDED IN MONEY LEDGER!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Person:* {entry['person']}\n"
        f"💰 *Amount:* {entry['amount']}\n"
        f"📌 *Details:* {entry['details']}\n"
        f"📅 *Date:* {timestamp}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Saved to your persistent AI database!_"
    )

def tool_search_memory(query: str = "") -> str:
    """Search or list all saved debts, loans, money records, and notes in persistent database."""
    db = load_memory_db()
    debts = db.get("debts_and_loans", [])
    notes = db.get("notes", [])
    
    if not debts and not notes:
        return "🧠 Your persistent database is currently empty."
        
    lines = ["📝 *[YOUR SAVED MEMORY & MONEY LEDGER]*", "━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    if debts:
        lines.append("💰 *DEBTS & MONEY RECORDS:*")
        for idx, d in enumerate(debts, 1):
            lines.append(f"{idx}. *{d.get('person')}*: {d.get('amount')} - {d.get('details')} _({d.get('date')})_")
            
    if notes:
        lines.append("\n📌 *NOTES & REMINDERS:*")
        for idx, n in enumerate(notes, 1):
            lines.append(f"{idx}. {n.get('details')} _({n.get('date')})_")
            
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Saved in your persistent database_")
    return "\n".join(lines)

# ==========================================
# GEMINI RETRY WRAPPER
# ==========================================
def call_gemini_with_retry(client, prompt, system_instruction=None):
    for attempt in range(2):
        try:
            config = types.GenerateContentConfig(temperature=0.2)
            if system_instruction:
                config.system_instruction = system_instruction
            res = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config=config
            )
            return res.text.strip()
        except Exception as e:
            if "429" in str(e) and attempt < 1:
                print(f"Rate limited. Retrying in 2 seconds...")
                time.sleep(2)
            else:
                raise e

# ==========================================
# UNIVERSAL AUTONOMOUS LLM BRAIN (GEMINI 2.0)
# ==========================================
def agent_brain(user_text: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    text_lower = user_text.lower()
    
    system_instruction = """
    You are an elite, highly intelligent Autonomous Personal AI Assistant for the user.
    You communicate directly over Telegram.
    Format all output neatly using Telegram Markdown with clear headings, bullet points, and clean emojis.
    Be warm, professional, concise, and executive.
    """
    
    is_ledger_query = (
        any(w in text_lower for w in ["owe", "own", "who", "how much", "ledger", "memory", "saved", "database", "notes", "aish", "john"]) and
        any(w in text_lower for w in ["show", "list", "who", "how", "what", "tell", "get", "my"])
    ) or text_lower.strip() in ["show", "ledger", "memory", "list"]
    
    if is_ledger_query:
        return tool_search_memory()
        
    is_recording = (
        any(w in text_lower for w in ["remember", "record", "save", "paid", "spent", "lent", "borrowed"]) or 
        (("$" in user_text or re.search(r'\d+\.\d+|\d+', user_text)) and ("pay" in text_lower or "rego" in text_lower or "cost" in text_lower))
    )
    
    if is_recording and not is_ledger_query:
        person = "Aish" if "aish" in text_lower else ("John" if "john" in text_lower else "Record")
        return tool_save_memory(person, "Extracted from message", user_text)

    if any(w in text_lower for w in ["email", "mail", "inbox", "vicroads", "anz", "origin", "kogan", "powershop"]):
        q = "vicroads" if "vicroads" in text_lower or "rego" in text_lower else ("is:unread" if "unread" in text_lower else text_lower)
        tool_result = tool_search_gmail(q)
        try:
            return call_gemini_with_retry(client, f"User asked: {user_text}\nEmail results:\n{tool_result}", system_instruction)
        except Exception:
            return tool_result

    if any(w in text_lower for w in ["calendar", "schedule", "event", "upcoming bills"]):
        tool_result = tool_get_calendar_events()
        try:
            return call_gemini_with_retry(client, f"User asked: {user_text}\nCalendar results:\n{tool_result}", system_instruction)
        except Exception:
            return tool_result

    try:
        return call_gemini_with_retry(client, user_text, system_instruction)
    except Exception as e:
        print(f"Fallback note: {e}")
        return f"🤖 Personal Agent: Received your request '{user_text}'."

# ==========================================
# TELEGRAM BOT POLLING ENGINE
# ==========================================
def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram send error: {e}")

def run_telegram_agent():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0
    print("🚀 Universal Autonomous Personal AI Agent is LIVE & Cloud Ready...")
    
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
        except Exception as e:
            print(f"Polling loop note: {e}")
            time.sleep(2)

if __name__ == '__main__':
    run_telegram_agent()

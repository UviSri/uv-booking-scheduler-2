#!/usr/bin/env python3
"""
Final scheduler.py — uses JSON body + Postman-style headers.
Sends one minimal Telegram message and writes a minimal booking_log.txt.
"""

import os
import time
import json
import requests
from datetime import datetime, timedelta
import pytz
import traceback

IST = pytz.timezone("Asia/Kolkata")
CONFIG_PATH = "booking_config.json"
LOG_FILE = "booking_log.txt"

# Env secrets (set in GitHub repo secrets)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
COOKIE = os.getenv("COOKIE")  # full cookie string from browser

# Attempts
ATTEMPTS_PER_SLOT = 3
GAP_BETWEEN_ATTEMPTS = 0.05  # 50 ms

# Postman-like headers (keys lowercased for requests)
POSTMAN_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://in.adda.io",
    "referer": "https://in.adda.io/",
    # good UA value — keep same style as Postman/Chrome
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest"
}

def now_ist():
    return datetime.now(IST)

def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def send_telegram_single(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        # can't send; just return False
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False

def write_minimal_log_line(line):
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def make_booking_json(api_url, booking_date, facility_id, flat_id, slot):
    payload = {
        "facilityId": facility_id,
        "bookDate": booking_date,
        "slot": slot,
        "flatId": flat_id
    }
    # Use JSON body exactly like Postman
    headers = POSTMAN_HEADERS.copy()
    if COOKIE:
        headers["cookie"] = COOKIE
    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=10)
        text = r.text or ""
        # try parse json to extract message
        msg = None
        try:
            j = r.json()
            if isinstance(j, dict):
                msg = j.get("message", None)
        except Exception:
            msg = None
        if msg is None:
            msg = text.strip()
        return r.status_code, msg, text
    except Exception as e:
        return None, f"Exception: {e}", None

def wait_until_6_or_run_now():
    now = now_ist()
    target = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now >= target:
        return
    # Sleep until 2 seconds before target
    while True:
        now = now_ist()
        diff = (target - now).total_seconds()
        if diff <= 2.0:
            break
        time.sleep(1)
    # Busy wait final microseconds
    while now_ist() < target:
        pass

def main():
    try:
        cfg = load_config()
    except Exception as e:
        send_telegram_single(f"🔥 Config load error: {e}")
        return

    facility_id = cfg.get("facilityId")
    flat_id = cfg.get("flatId")
    api_url = cfg.get("api_url")
    slots = cfg.get("slots")

    missing = []
    if not facility_id: missing.append("facilityId")
    if not flat_id: missing.append("flatId")
    if not api_url: missing.append("api_url")
    if not slots or not isinstance(slots, list): missing.append("slots")
    if missing:
        send_telegram_single(f"🔥 Config error: missing {', '.join(missing)}")
        return

    if not COOKIE:
        send_telegram_single("🔒 SECRET ERROR: COOKIE missing. Add COOKIE in repo secrets.")
        return

    # booking date = today + 2 days (IST)
    booking_date = (now_ist() + timedelta(days=2)).strftime("%d-%m-%Y")

    # Wait until 6 or run now
    try:
        wait_until_6_or_run_now()
    except Exception:
        pass  # on any wait error, proceed

    confirmed_line = None
    # try each slot
    for slot in slots:
        last_msg = None
        for attempt in range(1, ATTEMPTS_PER_SLOT + 1):
            status, msg, raw = make_booking_json(api_url, booking_date, facility_id, flat_id, slot)
            last_msg = msg or "(no message)"
            # exact success check
            if last_msg == "Amenity has been Reserved":
                confirmed_line = f"Slot: {slot} → {last_msg}"
                break
            # very short gap
            time.sleep(GAP_BETWEEN_ATTEMPTS)
        if confirmed_line:
            break

    # Prepare telegram minimal text and minimal log
    if confirmed_line:
        telegram_text = f"Booking Date from 2: {booking_date}\n\n{confirmed_line}"
        write_minimal_log_line(confirmed_line)
    else:
        telegram_text = f"Booking Date from 2: {booking_date}\n\nNo slots available"
        write_minimal_log_line("No slots available")

    # Trim to safe length
    if len(telegram_text) > 3800:
        telegram_text = telegram_text[:3800]

    send_telegram_single(telegram_text)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Best-effort notify
        try:
            send_telegram_single("🔥 Scheduler crashed unexpectedly.")
        except:
            pass

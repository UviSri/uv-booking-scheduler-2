#!/usr/bin/env python3
"""
Final Scheduler
- Waits until 06:00 IST if started early
- Weekday flat pairing
- Independent cookies per flat
- Today + 2 days booking
- Parallel 30-min slot booking
- facUserId in Telegram
- Booking Alert prefix for ALL Telegram messages
"""

import os
import json
import time
import threading
import requests
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
CONFIG_PATH = "booking_config.json"
LOG_FILE = "booking_log.txt"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

POSTMAN_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://in.adda.io",
    "referer": "https://in.adda.io/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "x-requested-with": "XMLHttpRequest"
}

# Flat configuration
FLATS = {
    "Flat_Y":  {"flat_id": "1711676", "display": "Yuvi"},
    "Flat_D":  {"flat_id": "1711772", "display": "Dev"},
    "Flat_SD": {"flat_id": "1711056", "display": "Sadu"},
    "Flat_M":  {"flat_id": "1711888", "display": "Manoj"},
    "Flat_SY": {"flat_id": "1711289", "display": "Sanjay"}
}

def now_ist():
    return datetime.now(IST)

# 🔐 Wait logic (from your reference code)
def wait_until_6_or_run_now():
    now = now_ist()
    target = now.replace(hour=6, minute=0, second=0, microsecond=0)

    if now >= target:
        return

    while True:
        diff = (target - now_ist()).total_seconds()
        if diff <= 2:
            break
        time.sleep(1)

    while now_ist() < target:
        pass

# 📩 Telegram sender (always Booking Alert)
def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    final_msg = f"🚨 Booking Alert 🚨\n\n{message}"
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": final_msg},
            timeout=10
        )
    except Exception:
        pass

def get_cookie(flat):
    cookie = os.getenv(flat.upper())
    if not cookie:
        raise Exception(f"Cookie missing for {FLATS[flat]['display']}")
    return cookie

def book_slot(api_url, booking_date, flat, slot, result, key):
    headers = POSTMAN_HEADERS.copy()
    headers["cookie"] = get_cookie(flat)

    payload = {
        "facilityId": FACILITY_ID,
        "bookDate": booking_date,
        "slot": slot,
        "flatId": FLATS[flat]["flat_id"]
    }

    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=10)
        data = r.json()
        result[key] = {
            "success": data.get("message") == "Amenity has been Reserved",
            "slot": slot,
            "flat": flat,
            "facUserId": data.get("data", {}).get("facUserId")
        }
    except Exception as e:
        result[key] = {
            "success": False,
            "slot": slot,
            "flat": flat,
            "facUserId": None,
            "error": str(e)
        }

def try_parallel_slots(api_url, booking_date, flats, slots):
    result = {}
    t1 = threading.Thread(target=book_slot, args=(api_url, booking_date, flats[0], slots[0], result, 1))
    t2 = threading.Thread(target=book_slot, args=(api_url, booking_date, flats[1], slots[1], result, 2))
    t1.start(); t2.start()
    t1.join(); t2.join()
    return result

def main():
    cfg = json.load(open(CONFIG_PATH))

    global FACILITY_ID
    FACILITY_ID = cfg["facilityId"]
    api_url = cfg["api_url"]

    today = now_ist().strftime("%A")
    booking_date = (now_ist() + timedelta(days=2)).strftime("%d-%m-%Y")

    # ⏳ Wait until 6 AM IST
    wait_until_6_or_run_now()

    flats_pair = cfg["weekday_flat_map"].get(today)
    if not flats_pair:
        send_telegram(f"No flat mapping configured for {today}")
        return

    for f in flats_pair:
        get_cookie(f)

    slots = cfg["slots"]

    if today in ("Saturday", "Sunday"):
        result = try_parallel_slots(api_url, booking_date, flats_pair, slots["night"])
    else:
        result = try_parallel_slots(api_url, booking_date, flats_pair, slots["morning"])
        if not (result[1]["success"] and result[2]["success"]):
            result = try_parallel_slots(api_url, booking_date, flats_pair, slots["night"])

    success, failed = [], []

    for r in result.values():
        name = FLATS[r["flat"]]["display"]
        if r["success"]:
            success.append(f"{r['slot']} → {name} → facUserId: {r['facUserId']}")
        else:
            failed.append(f"{r['slot']} → {name} → FAILED")

    msg = f"Date: {booking_date}\nDay: {today}\n\n"
    if success:
        msg += "✅ Booked:\n" + "\n".join(success) + "\n\n"
    if failed:
        msg += "❌ Failed:\n" + "\n".join(failed)

    send_telegram(msg.strip())
    open(LOG_FILE, "w").write(msg)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_telegram(f"Scheduler crashed:\n{e}")

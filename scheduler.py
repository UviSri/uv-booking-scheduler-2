#!/usr/bin/env python3
"""
Final Scheduler:
- 5 flats (each with own cookie + flatId)
- Booking date = Today + 2 (IST)
- Weekday/weekend logic based on BOOKING DATE
- 30-min paired slot booking
- Simultaneous API hits
- facUserId included
- Telegram message for SUCCESS + FAILURE
"""

import os
import json
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
    "user-agent": "Mozilla/5.0",
    "x-requested-with": "XMLHttpRequest"
}

# ---------------- FLAT DEFINITIONS ----------------

FLATS = {
    "Flat_Y":  {"flatId": "1711676", "env": "FLAT_Y",  "name": "Yuvi"},
    "Flat_D":  {"flatId": "1711772", "env": "FLAT_D",  "name": "Dev"},
    "Flat_SD": {"flatId": "1711056", "env": "FLAT_SD", "name": "Sadu"},
    "Flat_SY": {"flatId": "1711289", "env": "FLAT_SY", "name": "Sanjay"},
    "Flat_M":  {"flatId": "1711300", "env": "FLAT_M",  "name": "Manoj"},
}

# Booking plan based on BOOKING DATE weekday
WEEKDAY_FLAT_MAP = {
    "Monday":    ["Flat_SY", "Flat_SD"],
    "Tuesday":   ["Flat_Y",  "Flat_D"],
    "Wednesday": ["Flat_Y",  "Flat_SY"],
    "Thursday":  ["Flat_M",  "Flat_SD"],
    "Friday":    ["Flat_D",  "Flat_M"],
    "Saturday":  ["Flat_Y",  "Flat_D"],
    "Sunday":    ["Flat_Y",  "Flat_D"],
}

# Slot definitions
MORNING_SLOTS = [
    "07:00:00,07:30:00,0.00,0",
    "07:30:00,08:00:00,0.00,0"
]

NIGHT_SLOTS = [
    "20:00:00,20:30:00,0.00,0",
    "20:30:00,21:00:00,0.00,0"
]

# -------------------------------------------------

def now_ist():
    return datetime.now(IST)

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception:
        pass

def get_cookie(flat):
    cookie = os.getenv(FLATS[flat]["env"])
    if not cookie:
        raise Exception(f"Cookie missing for {FLATS[flat]['name']}")
    return cookie

def book_slot(api_url, facility_id, booking_date, flat, slot, result, key):
    headers = POSTMAN_HEADERS.copy()
    headers["cookie"] = get_cookie(flat)

    payload = {
        "facilityId": facility_id,
        "bookDate": booking_date,
        "slot": slot,
        "flatId": FLATS[flat]["flatId"]
    }

    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=10)
        j = r.json()
        result[key] = {
            "success": j.get("message") == "Amenity has been Reserved",
            "facUserId": j.get("data", {}).get("facUserId")
        }
    except Exception:
        result[key] = {"success": False, "facUserId": None}

def try_pair(api_url, facility_id, booking_date, flats, slots):
    result = {}

    t1 = threading.Thread(target=book_slot,
                          args=(api_url, facility_id, booking_date, flats[0], slots[0], result, 1))
    t2 = threading.Thread(target=book_slot,
                          args=(api_url, facility_id, booking_date, flats[1], slots[1], result, 2))

    t1.start(); t2.start()
    t1.join(); t2.join()

    return result

def main():
    cfg = json.load(open(CONFIG_PATH))
    facility_id = cfg["facilityId"]
    api_url = cfg["api_url"]

    booking_date_dt = now_ist() + timedelta(days=2)
    booking_date = booking_date_dt.strftime("%d-%m-%Y")
    booking_day = booking_date_dt.strftime("%A")

    flats = WEEKDAY_FLAT_MAP[booking_day]

    # Validate cookies early
    for f in flats:
        get_cookie(f)

    success_info = []
    failure_info = []

    # Weekend → night only
    slot_sets = [NIGHT_SLOTS] if booking_day in ("Saturday", "Sunday") else [MORNING_SLOTS, NIGHT_SLOTS]

    for slots in slot_sets:
        result = try_pair(api_url, facility_id, booking_date, flats, slots)

        if result.get(1, {}).get("success") and result.get(2, {}).get("success"):
            success_info = [
                (slots[0], flats[0], result[1]["facUserId"]),
                (slots[1], flats[1], result[2]["facUserId"]),
            ]
            break
        else:
            failure_info.append((slots, result))

    msg = f"Booking Date: {booking_date} ({booking_day})\n\n"

    if success_info:
        msg += "✅ SUCCESS\n"
        for slot, flat, fac in success_info:
            msg += f"{slot} → {FLATS[flat]['name']} → facUserId: {fac}\n"
    else:
        msg += "❌ FAILED\n"
        for slots, res in failure_info:
            msg += f"\nAttempted Slots:\n"
            for i, flat in enumerate(flats, start=1):
                msg += f"{slots[i-1]} → {FLATS[flat]['name']} → ❌\n"

    send_telegram(msg.strip())
    open(LOG_FILE, "w").write(msg)

if __name__ == "__main__":
    main()

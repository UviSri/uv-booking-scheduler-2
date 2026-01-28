#!/usr/bin/env python3
"""
Scheduler.py — Weekday booking with morning/evening fallback.
Sends Telegram alerts with Booking Alert header and writes log.
"""

import os
import time
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

# Postman-like headers
POSTMAN_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://in.adda.io",
    "referer": "https://in.adda.io/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest"
}

# Flats info
flats_info = {
    "Flat_Y": {"flat_number": "1711676", "cookie_env": "Flat_Y", "display": "Yuvi"},
    "Flat_D": {"flat_number": "1711772", "cookie_env": "Flat_D", "display": "Dev"},
    "Flat_SD": {"flat_number": "1711056", "cookie_env": "Flat_SD", "display": "Sadu"},
    # "Flat_M": {"flat_number": "1711056", "cookie_env": "Flat_SD", "display": "Manoj"},  # alias
    "Flat_M": {"flat_number": "1711289", "cookie_env": "Flat_SY", "display": "Manoj (Sanjay)"}  # now own cookie
    "Flat_SY": {"flat_number": "1711289", "cookie_env": "Flat_SY", "display": "Sanjay"}  # now own cookie
}

# Weekday flat pairs
WEEKDAY_FLAT_PAIRS = {
    "Monday": ["Flat_SY", "Flat_SD"],
    "Tuesday": ["Flat_Y", "Flat_D"],
    "Wednesday": ["Flat_Y", "Flat_SY"],
    "Thursday": ["Flat_M", "Flat_SD"],
    "Friday": ["Flat_D", "Flat_M"]
}

# Slot pairs
MORNING_SLOTS = ["07:00:00,07:30:00,0.00,0", "07:30:00,08:00:00,0.00,0"]
EVENING_SLOTS = ["20:00:00,20:30:00,0.00,0", "20:30:00,21:00:00,0.00,0"]

# Attempts
ATTEMPTS_PER_SLOT = 3
GAP_BETWEEN_ATTEMPTS = 0.05  # 50ms

def now_ist():
    return datetime.now(IST)

def wait_until_6_am():
    target = now_ist().replace(hour=6, minute=0, second=0, microsecond=0)
    while now_ist() < target:
        time.sleep(1)

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": f"🚨 Booking Alert 🚨\n\n{msg}"},
            timeout=10
        )
    except:
        pass

def get_cookie(flat):
    cookie = os.getenv(flats_info[flat]["cookie_env"])
    if not cookie:
        raise Exception(f"Cookie missing for {flats_info[flat]['display']}")
    return cookie

def book_slot(flat, slot, api_url, facility_id, booking_date):
    cookie = get_cookie(flat)
    payload = {
        "facilityId": facility_id,
        "bookDate": booking_date,
        "slot": slot,
        "flatId": flats_info[flat]["flat_number"]
    }
    headers = POSTMAN_HEADERS.copy()
    headers["cookie"] = cookie

    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=10)
        data = r.json()
        success = data.get("message") == "Amenity has been Reserved"
        facUserId = data.get("data", {}).get("facUserId")
        return success, facUserId
    except:
        return False, None

def attempt_slot(flat, slot, api_url, facility_id, booking_date):
    for _ in range(ATTEMPTS_PER_SLOT):
        success, facUserId = book_slot(flat, slot, api_url, facility_id, booking_date)
        if success:
            return True, facUserId
        time.sleep(GAP_BETWEEN_ATTEMPTS)
    return False, None

def book_consecutive_slots(flat_pair, slots_pair, api_url, facility_id, booking_date):
    results = []
    for i in range(2):
        success, facUserId = attempt_slot(flat_pair[i], slots_pair[i], api_url, facility_id, booking_date)
        results.append((slots_pair[i], flat_pair[i], facUserId, success))
    return results

def main():
    try:
        cfg = json.load(open(CONFIG_PATH))
    except Exception as e:
        send_telegram(f"🔥 Config load error: {e}")
        return

    facility_id = cfg.get("facilityId")
    api_url = cfg.get("api_url")

    booking_date = (now_ist() + timedelta(days=2)).strftime("%d-%m-%Y")
    day_of_booking = (now_ist() + timedelta(days=2)).strftime("%A")

    # Only book on weekdays
    if day_of_booking not in WEEKDAY_FLAT_PAIRS:
        send_telegram(f"Date: {booking_date}\nDay: {day_of_booking}\nNo booking for weekends.")
        return

    flats_pair = WEEKDAY_FLAT_PAIRS[day_of_booking]

    # Check cookies
    for flat in flats_pair:
        try:
            get_cookie(flat)
        except Exception as e:
            send_telegram(str(e))
            return

    # Wait until 6 AM IST
    wait_until_6_am()

    # First try morning slots
    booked_info = book_consecutive_slots(flats_pair, MORNING_SLOTS, api_url, facility_id, booking_date)

    # If any failed, try evening slots
    if not all([b[3] for b in booked_info]):
        booked_info = book_consecutive_slots(flats_pair, EVENING_SLOTS, api_url, facility_id, booking_date)

    # Prepare Telegram message
    msg_lines = [f"Date: {booking_date}", f"Day: {day_of_booking}", ""]
    failed_lines = []

    for slot, flat, facUserId, success in booked_info:
        if success:
            msg_lines.append(f"{slot} → {flats_info[flat]['display']} → facUserId: {facUserId}")
        else:
            failed_lines.append(f"{slot} → {flats_info[flat]['display']} → FAILED")

    if failed_lines:
        msg_lines.append("\n❌ Failed:")
        msg_lines.extend(failed_lines)

    send_telegram("\n".join(msg_lines))

    # Write log
    open(LOG_FILE, "w").write("\n".join(msg_lines))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_telegram(f"🔥 Booking Alert Exception: {e}")

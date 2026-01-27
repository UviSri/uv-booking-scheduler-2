#!/usr/bin/env python3
"""
Scheduler with:
- fixed weekday flat pairing
- cookie name == flat name
- 30-min paired booking
- simultaneous API hits
- weekday-based slot strategy
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

POSTMAN_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
    "origin": "https://in.adda.io",
    "referer": "https://in.adda.io/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest"
}

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

def make_booking(api_url, facility_id, booking_date, flat, slot, result, key):
    payload = {
        "facilityId": facility_id,
        "bookDate": booking_date,
        "slot": slot,
        "flatId": flat
    }

    headers = POSTMAN_HEADERS.copy()
    headers["cookie"] = os.getenv(flat)

    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=10)
        msg = r.json().get("message", "") if r.headers.get("content-type","").startswith("application/json") else r.text
        result[key] = msg
    except Exception as e:
        result[key] = f"Exception: {e}"

def try_slot_pair(api_url, facility_id, booking_date, flats, slots):
    results = {}

    t1 = threading.Thread(target=make_booking,
        args=(api_url, facility_id, booking_date, flats[0], slots[0], results, 1))
    t2 = threading.Thread(target=make_booking,
        args=(api_url, facility_id, booking_date, flats[1], slots[1], results, 2))

    t1.start(); t2.start()
    t1.join(); t2.join()

    return (
        results.get(1) == "Amenity has been Reserved" and
        results.get(2) == "Amenity has been Reserved"
    ), results

def main():
    cfg = json.load(open(CONFIG_PATH))

    today = now_ist().strftime("%A")
    booking_date = (now_ist() + timedelta(days=2)).strftime("%d-%m-%Y")

    flats = cfg["weekday_flat_map"].get(today)
    if not flats:
        send_telegram(f"❌ No flat mapping for {today}")
        return

    for f in flats:
        if not os.getenv(f):
            send_telegram(f"🔒 COOKIE missing for {f}")
            return

    facility_id = cfg["facilityId"]
    api_url = cfg["api_url"]
    slots = cfg["slots"]

    booked_slots = []

    # Weekend logic
    if today in ("Saturday", "Sunday"):
        success, _ = try_slot_pair(
            api_url, facility_id, booking_date, flats, slots["night"]
        )
        if success:
            booked_slots.extend(slots["night"])
    else:
        # Weekday: try morning first
        success, _ = try_slot_pair(
            api_url, facility_id, booking_date, flats, slots["morning"]
        )
        if success:
            booked_slots.extend(slots["morning"])
        else:
            success, _ = try_slot_pair(
                api_url, facility_id, booking_date, flats, slots["night"]
            )
            if success:
                booked_slots.extend(slots["night"])

    if booked_slots:
        msg = f"Booking Date: {booking_date}\nFlats: {flats[0]} & {flats[1]}\n\n"
        msg += "\n".join(booked_slots)
        send_telegram(msg)
        open(LOG_FILE, "w").write(msg)
    else:
        send_telegram(f"Booking Date: {booking_date}\nNo slots available")
        open(LOG_FILE, "w").write("No slots available")

if __name__ == "__main__":
    main()

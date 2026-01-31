#!/usr/bin/env python3
"""
Scheduler.py — weekday booking with 2 consecutive 30-min slots
Retries evening slots if morning fails.
Sends Booking Alert via Telegram with facUserId and FAILED info.
"""

import os
import json
import threading
import requests
from datetime import datetime, timedelta
import pytz
import time

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

# Flats info — flat_number, cookie env variable, display name
flats_info = {
    "Flat_Y": {"flat_number": "1711676", "cookie_env": "FLAT_Y", "display": "Yuvi"},
    "Flat_D": {"flat_number": "1711772", "cookie_env": "FLAT_D", "display": "Dev"},
    "Flat_SD": {"flat_number": "1711056", "cookie_env": "FLAT_SD", "display": "Sadu"},
    "Flat_M": {"flat_number": "1711772", "cookie_env": "FLAT_M", "display": "Manoj"},
    "Flat_SY": {"flat_number": "1711289", "cookie_env": "FLAT_SY", "display": "Sanjay"}
}

# Attempts per slot
ATTEMPTS_PER_SLOT = 3
GAP_BETWEEN_ATTEMPTS = 0.05  # 50ms gap

def now_ist():
    return datetime.now(IST)

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

def write_log(msg):
    try:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write(msg)
    except:
        pass

def make_booking(api_url, booking_date, flat_ref, slot, result, key):
    flat_number = flats_info[flat_ref]["flat_number"]
    cookie = os.getenv(flats_info[flat_ref]["cookie_env"])
    if not cookie:
        result[key] = {"success": False, "facUserId": None}
        return

    payload = {
        "facilityId": facility_id,
        "bookDate": booking_date,
        "slot": slot,
        "flatId": flat_number
    }

    headers = POSTMAN_HEADERS.copy()
    headers["cookie"] = cookie

    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=10)
        data = r.json()
        success = data.get("message") == "Amenity has been Reserved"
        fac_id = data.get("data", {}).get("facUserId") if success else None
        result[key] = {"success": success, "facUserId": fac_id}
    except:
        result[key] = {"success": False, "facUserId": None}

def try_slot_pair(api_url, booking_date, flats_pair, slots_pair):
    result = {}
    threads = []

    for idx, (flat, slot) in enumerate(zip(flats_pair, slots_pair), 1):
        t = threading.Thread(target=make_booking,
                             args=(api_url, booking_date, flat, slot, result, idx))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return result

def wait_until_6am_or_run_now():
    now = now_ist()
    target = now.replace(hour=6, minute=0, second=2, microsecond=0)

    # If already past 6 AM IST, proceed immediately
    if now >= target:
        return

    # Sleep until ~2 seconds before 6:00 AM
    while True:
        now = now_ist()
        diff = (target - now).total_seconds()
        if diff <= 2.0:
            break
        time.sleep(0.5)

    # High-precision wait for final milliseconds
    while now_ist() < target:
        time.sleep(0.001)


def now_ist():
    return datetime.now(IST)

def main():
    try:
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    except Exception as e:
        send_telegram(f"🔥 Config load error: {e}")
        return

    global facility_id
    facility_id = cfg.get("facilityId")
    api_url = cfg.get("api_url")
    weekday_flat_map = cfg.get("weekday_flat_map")
    slots_cfg = cfg.get("slots")

    # Booking date is today + 2 days
    booking_date_obj = now_ist() + timedelta(days=2)
    booking_date = booking_date_obj.strftime("%d-%m-%Y")
    booking_day = booking_date_obj.strftime("%A")

    # Only weekdays (Mon-Fri)
    if booking_day not in weekday_flat_map:
        send_telegram(f"Date: {booking_date}\nNo booking scheduled for {booking_day}.")
        return

    flats_pair = weekday_flat_map[booking_day]

    # Check cookies
    for flat in flats_pair:
        if not os.getenv(flats_info[flat]["cookie_env"]):
            send_telegram(f"Date: {booking_date}\n❌ COOKIE missing for {flats_info[flat]['display']}")
            return

    booked_info = []
    wait_until_6am_or_run_now()
    # Try morning slots first (2 consecutive 30-min slots)
    result = try_slot_pair(api_url, booking_date, flats_pair, slots_cfg["morning"])
    for idx, flat in enumerate(flats_pair, 1):
        r = result[idx]
        if r["success"]:
            booked_info.append((slots_cfg["morning"][idx-1], flat, r["facUserId"]))
        else:
            booked_info.append((slots_cfg["morning"][idx-1], flat, "FAILED"))

    # Retry evening slots for any failed flat
    evening_slots = slots_cfg.get("evening")
    if evening_slots:
        for i, (slot, flat, fac_id) in enumerate(booked_info):
            if fac_id == "FAILED":
                res_evening = try_slot_pair(api_url, booking_date, [flat], [evening_slots[i]])
                r2 = res_evening[1]
                if r2["success"]:
                    booked_info[i] = (evening_slots[i], flat, r2["facUserId"])

    # Prepare Telegram message
    msg_lines = [f"Date: {booking_date}"]
    success_lines, fail_lines = [], []

    for slot, flat, fac_id in booked_info:
        line = f"{slot} → {flats_info[flat]['display']} → facUserId: {fac_id}" if fac_id != "FAILED" else f"{slot} → {flats_info[flat]['display']} → FAILED"
        if fac_id != "FAILED":
            success_lines.append(line)
        else:
            fail_lines.append(line)

    if success_lines:
        msg_lines.append("\n✅ Booked:")
        msg_lines.extend(success_lines)
    if fail_lines:
        msg_lines.append("\n❌ Failed:")
        msg_lines.extend(fail_lines)

    final_msg = "\n".join(msg_lines)
    send_telegram(final_msg)
    write_log(final_msg)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        send_telegram(f"🔥 Booking Alert: Scheduler crashed unexpectedly.\n{e}")

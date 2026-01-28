#!/usr/bin/env python3
"""
Weekday Booking Scheduler — 2 consecutive 30-min slots per flat.
Sends Telegram alert for success/failure and writes minimal log.
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
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest"
}

ATTEMPTS_PER_SLOT = 3
GAP_BETWEEN_ATTEMPTS = 0.05  # 50 ms

def now_ist():
    return datetime.now(IST)

def wait_until_6am():
    target = now_ist().replace(hour=6, minute=0, second=0, microsecond=0)
    if now_ist() >= target:
        return
    while (diff := (target - now_ist()).total_seconds()) > 2:
        time.sleep(1)
    while now_ist() < target:
        pass

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

def make_booking(api_url, booking_date, flat_number, cookie, slot, result, key):
    headers = POSTMAN_HEADERS.copy()
    headers["cookie"] = cookie
    payload = {
        "facilityId": facility_id,
        "bookDate": booking_date,
        "slot": slot,
        "flatId": flat_number
    }
    try:
        for _ in range(ATTEMPTS_PER_SLOT):
            r = requests.post(api_url, json=payload, headers=headers, timeout=10)
            data = r.json()
            if data.get("message") == "Amenity has been Reserved":
                result[key] = {
                    "success": True,
                    "facUserId": data.get("data", {}).get("facUserId")
                }
                return
    except:
        pass
    result[key] = {"success": False, "facUserId": None}

def try_slot_pair(api_url, booking_date, flats_pair, slots_pair):
    result = {}
    t1 = threading.Thread(target=make_booking, args=(api_url, booking_date,
                                                     flats_info[flats_pair[0]]["flat_number"],
                                                     os.getenv(flats_info[flats_pair[0]]["cookie_env"]),
                                                     slots_pair[0], result, 1))
    t2 = threading.Thread(target=make_booking, args=(api_url, booking_date,
                                                     flats_info[flats_pair[1]]["flat_number"],
                                                     os.getenv(flats_info[flats_pair[1]]["cookie_env"]),
                                                     slots_pair[1], result, 2))
    t1.start(); t2.start()
    t1.join(); t2.join()
    return result

def main():
    try:
        cfg = json.load(open(CONFIG_PATH, encoding="utf-8"))
    except Exception as e:
        send_telegram(f"Failed to load config: {e}")
        return

    global facility_id
    facility_id = cfg.get("facilityId")
    api_url = cfg.get("api_url")
    weekday_map = cfg.get("weekday_flat_map")
    slots_cfg = cfg.get("slots")
    global flats_info
    flats_info = cfg.get("flats_info")

    today_weekday = now_ist().strftime("%A")
    booking_date = (now_ist() + timedelta(days=2)).strftime("%d-%m-%Y")

    # Only book on weekdays
    if today_weekday not in weekday_map:
        send_telegram(f"Today is {today_weekday}. No booking scheduled for weekends.")
        return

    flats_pair = weekday_map[today_weekday]

    # Check cookies exist
    for flat in flats_pair:
        cookie_env = flats_info[flat]["cookie_env"]
        if not os.getenv(cookie_env):
            send_telegram(f"Cookie missing for {flats_info[flat]['display']} ({cookie_env})")
            return

    # Wait until 6AM IST
    wait_until_6am()

    # Try morning slots first
    booked_info = []
    result = try_slot_pair(api_url, booking_date, flats_pair, slots_cfg["morning"])
    for idx, flat in enumerate(flats_pair, 1):
        if result[idx]["success"]:
            booked_info.append((slots_cfg["morning"][idx-1], flat, result[idx]["facUserId"]))
        else:
            booked_info.append((slots_cfg["morning"][idx-1], flat, "FAILED"))

    # If any slot failed, try evening slots
    if any(r["facUserId"] is None for r in result.values()):
        result_evening = try_slot_pair(api_url, booking_date, flats_pair, slots_cfg["evening"])
        for idx, flat in enumerate(flats_pair, 1):
            if result[idx]["facUserId"] is None and result_evening[idx]["success"]:
                booked_info[idx-1] = (slots_cfg["evening"][idx-1], flat, result_evening[idx]["facUserId"])

    # Prepare Telegram message
    msg = f"Date: {booking_date}\nDay: {today_weekday}\n\n"
    success_lines = []
    fail_lines = []
    for slot, flat, fac_id in booked_info:
        if fac_id == "FAILED":
            fail_lines.append(f"{slot} → {flats_info[flat]['display']} → FAILED")
        else:
            success_lines.append(f"{slot} → {flats_info[flat]['display']} → facUserId: {fac_id}")

    if success_lines:
        msg += "✅ Success:\n" + "\n".join(success_lines) + "\n"
    if fail_lines:
        msg += "❌ Failed:\n" + "\n".join(fail_lines)

    send_telegram(msg)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(msg)

if __name__ == "__main__":
    main()

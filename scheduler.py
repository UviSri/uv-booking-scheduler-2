#!/usr/bin/env python3
"""
Scheduler with:
- weekday flat pairing
- flat reference mapping
- cookies + flat number
- paired 30-min booking
- simultaneous API hits
- facUserId in Telegram
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
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest"
}

# Flats mapping
# flats_info = {
#     "Flat_SY": {"flat_number": "1711772", "cookie_env": "Flat_SY", "display": "Sanjay"},
#     "Flat_SD": {"flat_number": "1711888", "cookie_env": "Flat_SD", "display": "Sadu"},
#     "Flat_Y": {"flat_number": "1711999", "cookie_env": "Flat_Y", "display": "Yuvi"},
#     "Flat_D": {"flat_number": "1712001", "cookie_env": "Flat_D", "display": "Dev"},
#     "Flat_M": {"flat_number": "1712050", "cookie_env": "Flat_M", "display": "Manoj"},
# }

############### Temporary ##################################
flats_info = {
    "Flat_Y": {"flat_number": "1711676", "cookie_env": "Flat_Y", "display": "Yuvi"},
    "Flat_D": {"flat_number": "1711772", "cookie_env": "Flat_D", "display": "Dev"},
    "Flat_SD": {"flat_number": "1711056", "cookie_env": "Flat_SD", "display": "Sadu"},
    "Flat_M": {"flat_number": "1711056", "cookie_env": "Flat_SD", "display": "(Sadu) Manoj"},  # alias Flat_SD
    "Flat_SY": {"flat_number": "1711772", "cookie_env": "Flat_D", "display": "(Dev) Sanjay"}  # alias Flat_D
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

def make_booking(api_url, booking_date, flat_ref, slot, result, key):
    flat_number = flats_info[flat_ref]["flat_number"]
    cookie = os.getenv(flats_info[flat_ref]["cookie_env"])

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
        result[key] = {
            "success": data.get("message") == "Amenity has been Reserved",
            "facUserId": data.get("data", {}).get("facUserId")
        }
    except Exception as e:
        result[key] = {
            "success": False,
            "facUserId": None
        }

def try_slot_pair(api_url, booking_date, flats_pair, slots_pair):
    result = {}

    t1 = threading.Thread(target=make_booking,
                          args=(api_url, booking_date, flats_pair[0], slots_pair[0], result, 1))
    t2 = threading.Thread(target=make_booking,
                          args=(api_url, booking_date, flats_pair[1], slots_pair[1], result, 2))

    t1.start(); t2.start()
    t1.join(); t2.join()

    if result.get(1, {}).get("success") and result.get(2, {}).get("success"):
        return True, result
    return False, result

def main():
    cfg = json.load(open(CONFIG_PATH))

    today = now_ist().strftime("%A")
    booking_date = (now_ist() + timedelta(days=2)).strftime("%d-%m-%Y")

    flats_pair = cfg["weekday_flat_map"].get(today)
    if not flats_pair:
        send_telegram(f"❌ No flat mapping for {today}")
        return

    for f in flats_pair:
        if not os.getenv(flats_info[f]["cookie_env"]):
            send_telegram(f"🔒 COOKIE missing for {flats_info[f]['display']}")
            return

    global facility_id
    facility_id = cfg["facilityId"]
    api_url = cfg["api_url"]
    slots = cfg["slots"]

    booked_info = []

    # Weekend logic
    if today in ("Saturday", "Sunday"):
        success, res = try_slot_pair(api_url, booking_date, flats_pair, slots["night"])
        if success:
            booked_info = [
                (slots["night"][0], flats_pair[0], res[1]["facUserId"]),
                (slots["night"][1], flats_pair[1], res[2]["facUserId"])
            ]
    else:
        # Weekday → morning first
        success, res = try_slot_pair(api_url, booking_date, flats_pair, slots["morning"])
        if success:
            booked_info = [
                (slots["morning"][0], flats_pair[0], res[1]["facUserId"]),
                (slots["morning"][1], flats_pair[1], res[2]["facUserId"])
            ]
        else:
            success, res = try_slot_pair(api_url, booking_date, flats_pair, slots["night"])
            if success:
                booked_info = [
                    (slots["night"][0], flats_pair[0], res[1]["facUserId"]),
                    (slots["night"][1], flats_pair[1], res[2]["facUserId"])
                ]

    if booked_info:
        msg = f"Booking Date: {booking_date}\nFlats: {flats_info[flats_pair[0]]['display']} & {flats_info[flats_pair[1]]['display']}\n\n"
        for slot, flat_ref, fac_id in booked_info:
            msg += f"{slot} → {flats_info[flat_ref]['display']} → facUserId: {fac_id}\n"

        send_telegram(msg.strip())
        open(LOG_FILE, "w").write(msg)
    else:
        send_telegram(f"Booking Date: {booking_date}\nNo slots available")
        open(LOG_FILE, "w").write("No slots available")

if __name__ == "__main__":
    main()

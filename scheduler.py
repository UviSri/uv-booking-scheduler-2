import os
import sys
import json
import requests
from datetime import datetime

# =========================
# CONFIG
# =========================

BOOKING_URL = "https://<YOUR_BOOKING_API_ENDPOINT>"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# =========================
# FLAT → PERSON MAPPING
# =========================

FLAT_NAME_MAP = {
    "Flat_SY": "Sanjay",
    "Flat_SD": "Sadu",
    "Flat_Y":  "Yuvi",
    "Flat_D":  "Dev",
    "Flat_M":  "Manoj"
}

# =========================
# FLAT → FLAT ID MAPPING
# =========================

FLAT_ID_MAP = {
    "Flat_Y": 1711676,
    "Flat_D": 1711772,
    "Flat_SD": 1711056,
    "Flat_M": 1711056,   # temp reuse
    "Flat_SY": 1711289   # Sanjay has his own now
}

# =========================
# DAY → FLAT MAPPING
# =========================

# DAY_FLAT_MAP = {
#     "Monday":    ["Flat_SY", "Flat_SD"],
#     "Tuesday":   ["Flat_Y",  "Flat_D"],
#     "Wednesday": ["Flat_Y",  "Flat_SY"],
#     "Thursday":  ["Flat_M",  "Flat_SD"],
#     "Friday":    ["Flat_D",  "Flat_M"],
#     "Saturday":  ["Flat_Y",  "Flat_D"],
#     "Sunday":    ["Flat_Y",  "Flat_D"]
# }

# SY:3 , SD:3, D:4, Y:4

DAY_FLAT_MAP = {
    "Monday":    ["Flat_SY", "Flat_SD"],
    "Tuesday":   ["Flat_Y",  "Flat_D"],
    "Wednesday": ["Flat_Y",  "Flat_D"],
    "Thursday":  ["Flat_SY",  "Flat_SD"],
    "Friday":    ["Flat_Y",  "Flat_D"],
    "Saturday":  ["Flat_Y",  "Flat_SY"],
    "Sunday":    ["Flat_SD",  "Flat_D"]
}

# =========================
# SLOT DEFINITIONS
# =========================

MORNING_SLOTS = [
    ("07:00:00", "07:30:00", "0.00", "0"),
    ("07:30:00", "08:00:00", "0.00", "0")
]

EVENING_SLOTS = [
    ("20:00:00", "20:30:00", "0.00", "0"),
    ("20:30:00", "21:00:00", "0.00", "0")
]

# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)


def telegram_success(flat, slot, fac_user_id):
    msg = (
        f"✅ *Booking Successful*\n"
        f"👤 {FLAT_NAME_MAP[flat]} ({flat})\n"
        f"🕒 {slot[0]} - {slot[1]}\n"
        f"🆔 facUserId: `{fac_user_id}`"
    )
    send_telegram(msg)


def telegram_failure(flat, slot, reason):
    msg = (
        f"❌ *Booking Failed*\n"
        f"👤 {FLAT_NAME_MAP[flat]} ({flat})\n"
        f"🕒 {slot[0]} - {slot[1]}\n"
        f"⚠️ Reason: {reason}"
    )
    send_telegram(msg)

# =========================
# DISPLAY PLAN
# =========================

def display_booking_plan(day, flats, slots):
    print("\n=== BOOKING PLAN ===")
    print(f"Day: {day}\n")
    print(f"{'Flat':<10} | {'Person':<10} | Slots")
    print("-" * 55)
    for flat in flats:
        slot_str = ", ".join([f"{s[0]}-{s[1]}" for s in slots])
        print(f"{flat:<10} | {FLAT_NAME_MAP[flat]:<10} | {slot_str}")
    print("-" * 55)

# =========================
# BOOKING CORE
# =========================

def get_cookie(flat):
    # IMPORTANT FIX:
    # Secret is stored as FLAT_Y, FLAT_SD, etc.
    key = flat.upper()
    cookie = os.getenv(key)
    if not cookie:
        raise Exception(f"Cookie missing for {FLAT_NAME_MAP[flat]}")
    return cookie


def book_slot(flat, slot):
    flat_id = FLAT_ID_MAP[flat]
    cookie = get_cookie(flat)

    headers = {
        "Content-Type": "application/json",
        "Cookie": cookie
    }

    payload = {
        "flat_id": flat_id,
        "from_time": slot[0],
        "to_time": slot[1],
        "amount": slot[2],
        "guest_count": slot[3]
    }

    try:
        response = requests.post(BOOKING_URL, headers=headers, json=payload, timeout=15)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def attempt_slot(flat, slot):
    response = book_slot(flat, slot)

    if response.get("status") == "success":
        fac_user_id = response["data"]["facUserId"]
        telegram_success(flat, slot, fac_user_id)
        return True
    else:
        telegram_failure(flat, slot, response.get("message", "Unknown error"))
        return False


def book_consecutive_slots(flat, slots):
    for slot in slots:
        if not attempt_slot(flat, slot):
            return False
    return True

# =========================
# DAY EXECUTION
# =========================

def run_day(day):
    flats = DAY_FLAT_MAP[day]

    if day in ["Saturday", "Sunday"]:
        display_booking_plan(day, flats, EVENING_SLOTS)
        for flat in flats:
            book_consecutive_slots(flat, EVENING_SLOTS)
    else:
        display_booking_plan(day, flats, MORNING_SLOTS)
        for flat in flats:
            if not book_consecutive_slots(flat, MORNING_SLOTS):
                display_booking_plan(day, [flat], EVENING_SLOTS)
                book_consecutive_slots(flat, EVENING_SLOTS)

# =========================
# MAIN
# =========================

def main():
    today = datetime.now().strftime("%A")
    print(f"\nRunning scheduler for: {today}")
    run_day(today)

if __name__ == "__main__":
    main()

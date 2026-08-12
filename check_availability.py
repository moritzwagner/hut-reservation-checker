import os
import json
import requests
from datetime import datetime, timedelta
from time import sleep

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
HUTS = os.environ.get("HUTS", "")  # e.g. "150,603"
DATES_JSON = os.environ.get("DATES", "[]")  # e.g. '[{"arrivalDate":"11.07.2025","departureDate":"12.07.2025"}]'
FREE_BEDS = os.environ.get("FREE_BEDS", "3")

BASE_URL = "https://www.hut-reservation.org/api/v1"
DATE_FORMAT = "%d.%m.%Y"

# Parse input
selected_hut_ids = [int(h.strip()) for h in HUTS.split(",") if h.strip().isdigit()]
dates = json.loads(DATES_JSON)

def expand_date_ranges(input_dates):
    expanded_dates = []

    for date_range in input_dates:
        arrival = date_range.get("arrivalDate")
        departure = date_range.get("departureDate")

        if not arrival or not departure:
            print(f"Skipping invalid date range: {date_range}")
            continue

        try:
            arrival_dt = datetime.strptime(arrival, DATE_FORMAT)
            departure_dt = datetime.strptime(departure, DATE_FORMAT)
        except ValueError:
            print(f"Skipping invalid date format in range: {date_range}")
            continue

        if departure_dt <= arrival_dt:
            print(f"Skipping date range where departure is not after arrival: {date_range}")
            continue

        current_arrival = arrival_dt
        while current_arrival < departure_dt:
            current_departure = current_arrival + timedelta(days=1)
            expanded_dates.append({
                "arrivalDate": current_arrival.strftime(DATE_FORMAT),
                "departureDate": current_departure.strftime(DATE_FORMAT)
            })
            current_arrival = current_departure

    return expanded_dates

def get_hut_info(hut_id):
    url = f"{BASE_URL}/reservation/hutInfo/{hut_id}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Failed to fetch hut info for {hut_id}: {e}")
        return None

def check_availability(hut_id, hut_name, categories, arrival, departure):

    url = f"{BASE_URL}/reservation/checkAvailability/{hut_id}"

    category_ids = [c["categoryID"] for c in categories]
    peoplePerCategory = []
    for index, category_id in enumerate(category_ids):
        peoplePerCategory.append({
            "categoryId": category_id,
            "people": 1 if index == 0 else 0
        })

    payload = {
        "arrivalDate": arrival,
        "departureDate": departure,
        "numberOfPeople": 1,
        "nextPossibleReservations": False,
        "peoplePerCategory": peoplePerCategory,
        "isWaitingListAccepted": False,
        "reservationPublicId": ""
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.hut-reservation.org",
        "Referer": "https://www.hut-reservation.org/reservation"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        availabilityPerDayDTOs = data.get("availabilityPerDayDTOs", [{}])
        categories = availabilityPerDayDTOs[0].get("bedCategoriesData", [])

        for category in categories:
            label_data = category.get("hutBedCategoryLanguagesData", [])
            category_label = next((l["label"] for l in label_data if l["language"] == "EN"), "Unknown Category")
          
            total_beds = category.get("totalPlaces", 0)
            free_beds = category.get("totalFreePlaces", 0)

            if free_beds > int(FREE_BEDS):
                print(category)
                send_discord_notification(hut_name, arrival, departure, category_label , free_beds)
            elif free_beds == 0:
                print(f"{arrival}–{departure} | {hut_name} ({category_label}): No beds availble — no notification.")
            else:
                print(f"{arrival}–{departure} | {hut_name} ({category_label}): Only {free_beds} beds availble — no notification.")

    except requests.RequestException as e:
        print(f"Error checking availability for {hut_name} {arrival}–{departure}: {e}")

def send_discord_notification(hut_name, arrival, departure, category_label, free_places):
    message = {
        "content": f"🛌 **{free_places} beds** available in **{category_label}** at **{hut_name}** from {arrival} to {departure}!\n👉 https://www.hut-reservation.org"
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=message)
        response.raise_for_status()
        print(f"✅ Notification sent for {hut_name} ({category_label}) from {arrival} to {departure}.")
    except requests.RequestException as e:
        print(f"❌ Failed to send Discord message: {e}")

if __name__ == "__main__":

    if not selected_hut_ids:
        print("No valid hut IDs provided.")

    expanded_dates = expand_date_ranges(dates)

    if not expanded_dates:
        print("No valid date ranges provided.")


    for hut_id in selected_hut_ids:
        hut_info = get_hut_info(hut_id)

        if not hut_info:
            continue

        hut_name = hut_info.get("hutName", f"Hut {hut_id}")

        categories = [
            c for c in hut_info.get("hutBedCategories", [])
            if c.get("isVisible", False)
        ]

        if not categories:
            print(f"No visible categories found for {hut_name}")
            continue

        for date in expanded_dates:
            check_availability(
                hut_id=hut_id,
                hut_name=hut_name,
                categories=categories,
                arrival=date["arrivalDate"],
                departure=date["departureDate"]
            )

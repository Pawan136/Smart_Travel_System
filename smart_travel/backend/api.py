"""
Mock API -
Simulates flight and hotel search backends.
Returns realistic structured data.
"""
from __future__ import annotations
import copy, random, string
from datetime import datetime, timedelta


def _ref(prefix: str) -> str:
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


# ── FLIGHT DATA 
FLIGHTS = [
    {
        "id": "F001",
        "airline": "IndiGo",
        "airline_code": "6E",
        "flight_no": "6E-205",
        "departure": "06:00",
        "arrival": "08:05",
        "duration": "2h 05m",
        "stops": 0,
        "stops_label": "Non-stop",
        "fare": {"base": 3200, "taxes": 640, "total": 3840},
        "currency": "INR",
        "class": "Economy",
        "refundable": False,
        "cancellation_policy": "Non-refundable. Change fee ₹2,000 applies.",
        "baggage": "15 kg check-in · 7 kg cabin",
        "seats_left": 8,
        "rating": 3.9,
    },
    {
        "id": "F002",
        "airline": "Air India",
        "airline_code": "AI",
        "flight_no": "AI-665",
        "departure": "09:30",
        "arrival": "11:45",
        "duration": "2h 15m",
        "stops": 0,
        "stops_label": "Non-stop",
        "fare": {"base": 4100, "taxes": 820, "total": 4920},
        "currency": "INR",
        "class": "Economy",
        "refundable": True,
        "cancellation_policy": "Fully refundable up to 24h before departure. No change fee.",
        "baggage": "25 kg check-in · 8 kg cabin",
        "seats_left": 15,
        "rating": 4.1,
    },
    {
        "id": "F003",
        "airline": "Vistara",
        "airline_code": "UK",
        "flight_no": "UK-985",
        "departure": "14:15",
        "arrival": "16:20",
        "duration": "2h 05m",
        "stops": 0,
        "stops_label": "Non-stop",
        "fare": {"base": 5500, "taxes": 1100, "total": 6600},
        "currency": "INR",
        "class": "Business",
        "refundable": True,
        "cancellation_policy": "Fully refundable anytime. No fees.",
        "baggage": "35 kg check-in · 12 kg cabin",
        "seats_left": 4,
        "rating": 4.6,
    },
]

HOTELS = [
    {
        "id": "H001",
        "name": "The Leela Palace",
        "stars": 5,
        "location": "Chanakyapuri, Central Delhi",
        "room_type": "Deluxe Room",
        "price_per_night": 15000,
        "currency": "INR",
        "amenities": [
            "Outdoor swimming pool",
            "World-class spa",
            "4 signature restaurants",
            "Free high-speed Wi-Fi",
            "Airport limousine service",
            "24h butler service",
            "Business center",
            "Fitness center",
        ],
        "cancellation_policy": "Free cancellation up to 48h before check-in.",
        "rating": 4.8,
        "reviews": 2841,
        "breakfast_included": True,
        "highlights": ["Luxury", "City view", "Award-winning spa"],
    },
    {
        "id": "H002",
        "name": "Taj Hotel & Convention Centre",
        "stars": 5,
        "location": "Diplomatic Enclave",
        "room_type": "Superior Room",
        "price_per_night": 11500,
        "currency": "INR",
        "amenities": [
            "3 swimming pools",
            "Beach-style pool",
            "Spa & wellness center",
            "3 restaurants + bar",
            "Free Wi-Fi",
            "Gym",
            "Kids club",
            "Concierge",
        ],
        "cancellation_policy": "Free cancellation up to 72h. One night charge after.",
        "rating": 4.5,
        "reviews": 1923,
        "breakfast_included": True,
        "highlights": ["Heritage", "Central location", "Great dining"],
    },
    {
        "id": "H003",
        "name": "Novotel New Delhi",
        "stars": 4,
        "location": "Aerocity, Near IGI Airport",
        "room_type": "Standard Room",
        "price_per_night": 6200,
        "currency": "INR",
        "amenities": [
            "Rooftop pool",
            "Restaurant & bar",
            "Free Wi-Fi",
            "Gym",
            "24h reception",
            "Airport shuttle",
        ],
        "cancellation_policy": "Non-refundable rate. No changes allowed.",
        "rating": 4.1,
        "reviews": 4102,
        "breakfast_included": False,
        "highlights": ["Budget-friendly", "Near airport", "Modern"],
    },
]


def search_flights(origin: str, destination: str, date: str, passengers: int) -> list[dict]:
    """Search flights and return enriched results."""
    results = copy.deepcopy(FLIGHTS)
    for f in results:
        f["date"]        = date
        f["passengers"]  = passengers
        f["origin"]      = origin
        f["destination"] = destination
        # Scale total by passenger count
        base  = f["fare"]["base"]
        taxes = f["fare"]["taxes"]
        f["fare"]["total"] = (base + taxes) * passengers
        f["fare"]["per_person"] = base + taxes
    return results


def confirm_flight_booking(offer: dict, passenger: dict) -> dict:
    return {
        "booking_ref": _ref("FL"),
        "pnr":         _ref(""),
        "status":      "CONFIRMED",
        "flight_no":   offer["flight_no"],
        "airline":     offer["airline"],
        "route":       f"{offer['origin']} → {offer['destination']}",
        "date":        offer["date"],
        "departure":   offer["departure"],
        "arrival":     offer["arrival"],
        "class":       offer["class"],
        "passengers":  offer["passengers"],
        "passenger_name":  passenger["name"],
        "passenger_email": passenger["email"],
        "passenger_phone": passenger["phone"],
        "amount_paid": f"₹{offer['fare']['total']:,}",
        "baggage":     offer["baggage"],
        "confirmed_at": datetime.now().strftime("%d %b %Y, %H:%M"),
    }


def search_hotels(city: str, checkin: str, checkout: str, guests: int) -> list[dict]:
    """Search hotels and return enriched results."""
    from datetime import datetime as dt
    try:
        ci = dt.strptime(checkin, "%Y-%m-%d")
        co = dt.strptime(checkout, "%Y-%m-%d")
        nights = max(1, (co - ci).days)
    except Exception:
        nights = 1

    results = copy.deepcopy(HOTELS)
    for h in results:
        h["city"]         = city
        h["checkin"]      = checkin
        h["checkout"]     = checkout
        h["nights"]       = nights
        h["guests"]       = guests
        h["total_price"]  = h["price_per_night"] * nights
    return results


def confirm_hotel_booking(offer: dict, guest: dict) -> dict:
    return {
        "booking_ref": _ref("HT"),
        "status":      "CONFIRMED",
        "hotel":       offer["name"],
        "room_type":   offer["room_type"],
        "city":        offer["city"],
        "checkin":     offer["checkin"],
        "checkout":    offer["checkout"],
        "nights":      offer["nights"],
        "guests":      offer["guests"],
        "guest_name":  guest["name"],
        "guest_email": guest["email"],
        "guest_phone": guest["phone"],
        "amount_paid": f"₹{offer['total_price']:,}",
        "confirmed_at": datetime.now().strftime("%d %b %Y, %H:%M"),
    }

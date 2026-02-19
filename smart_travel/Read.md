# Smart Travel Companion
## AI Intelligence Layer — Complete Rebuild

A fully working, context-aware AI assistant for booking flights and hotels.
Includes a **beautiful web UI** + clean backend engine.

---

## Application Screenshot

![Smart Travel Companion Screenshot](https://drive.google.com/file/d/1VShILxRtvuo6_VSpmZRaJic5cSOkrArs/view?usp=sharing)

## Setup & Run

### 1. No extra dependencies needed!
The server works with **zero pip installs** using Python's stdlib HTTP server.
Flask is optional (auto-detected if installed).

```bash
cd smart_travel
python server.py
```

Open **http://localhost:5000** in your browser.

### 2. Optional: Install Flask for production serving
```bash
pip install flask
python server.py
```

---

## Key Bugs Fixed From Previous Version

| Bug | Fix |
|-----|-----|
| Bare number "4" not recognized as passenger count | Added `awaiting_slot` context to classifier — knows what we're collecting |
| Unknown cities (Bhopal, Varanasi) not recognized | Added 30+ Indian cities to CITY_MAP |
| "Rahul Verma" not parsed as name | Detects bare multi-word text as name when `awaiting_slot="name"` |
| Loop on passenger slot | Engine tracks what slot it last asked for and routes bare values correctly |
| State machine broken after slot collection | Fixed COLLECTING_PAX routing — no longer falls through to search |

---

## Required Scenarios — All Working

### Scenario 1: Full Flight Booking (3 steps)
```
"Book a flight from Delhi to Mumbai on 2026-03-20 for 2 passengers"
→ Shows 3 structured flight results with fares

"Option 1"
→ Shows full details: fare breakdown, refundability, cancellation policy, baggage

"yes" → "Rahul Sharma" → "rahul@gmail.com" → "+91 9876543210" → "yes"
→ Booking confirmed with PNR + booking reference
```

### Scenario 2: Mid-Flow Context Switch
```
"I want to fly from Delhi to Mumbai"  [collects date + passengers]
→ Flight results shown

"Also check hotels in Mumbai"
→ ⚠ Switching to hotel. Flight progress SAVED.
→ Collects hotel params, shows hotel results

"What amenities does option 2 include?"
→ Answers from STORED CONTEXT — no re-search

"Go back to my flight booking"
→ Resumes at RESULTS step with same flights
→ Continue booking from where you left off
```

### Scenario 3: Parameter Update + Invalidation
```
"Book a flight from Delhi to Goa on 2026-03-15 for 1 passenger"
→ Results shown for March 15

"Actually change the date to 2026-03-22"
→ ⚠ WARNING: date changed — clearing results
→ New results auto-shown for March 22

→ Full booking completes normally
```

---

## Architecture

```
smart_travel/
├── server.py              # HTTP server (Flask or stdlib)
├── frontend/
│   └── index.html         # Full web UI (single file)
└── backend/
    ├── __init__.py
    ├── engine.py          # Orchestrator + service handlers (returns JSON)
    ├── intent.py          # Intent classifier with awaiting_slot context
    ├── models.py          # SessionMemory, FlightContext, HotelContext, Slot
    └── api.py             # Mock flight/hotel search APIs
```

### Memory Design
- `SessionMemory` → `FlightContext` + `HotelContext` (fully isolated)
- Each data point stored in a `Slot(value, status, filled_at)`
- Status lifecycle: `EMPTY → FILLED → CONFIRMED / STALE`
- Context switch: `active_service ↔ previous_service` swap

### State Machine
```
IDLE → COLLECTING → SEARCHING → RESULTS → VERIFYING → COLLECTING_PAX → CONFIRMING → BOOKED
```

### Intent Classifier Fix
The classifier now accepts `awaiting_slot` — what we last asked for:
- Awaiting "passengers" + input "4" → fills passengers
- Awaiting "name" + input "Rahul Verma" → fills name
- Awaiting "travel_date" + input "2026-03-20" → fills date

---

## Web UI Features
- Dark luxury aesthetic with gold accents
- Rich flight cards (route display, fare breakdown, refundability badge)
- Hotel cards (star rating, amenities, breakfast badge)
- Live memory panel (sidebar showing all slots in real-time)
- Clickable quick-start chips
- Typing indicator
- Context bar showing active service + flow step
- Responsive (mobile-friendly)

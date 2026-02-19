"""
Travel AI Engine-

Central orchestrator that processes user messages and returns
structured JSON responses consumed by the web UI.

All responses are dicts with:
  {
    "type": "message" | "flight_results" | "hotel_results" |
            "flight_details" | "hotel_details" |
            "booking_confirm" | "memory_snapshot" | "asking",
    "text": str,           # human-readable text
    "data": dict | None,   # structured payload for UI rendering
    "meta": dict,          # session metadata
  }
"""
from __future__ import annotations
from typing import Optional
import uuid

from .models import (
    SessionMemory, ServiceType, FlowStep,
    FlightContext, HotelContext,
)
from .intent import classify, IntentResult
from .api import (
    search_flights, confirm_flight_booking,
    search_hotels,  confirm_hotel_booking,
)


class TravelEngine:
    def __init__(self):
        self.memory = SessionMemory(session_id=str(uuid.uuid4())[:8])
        self._awaiting_slot: Optional[str] = None  # what we last asked for

    # ── Public API ────────────────────────────────────────────

    def process(self, user_input: str) -> list[dict]:
        """Process one user turn. Returns list of response messages."""
        if not user_input.strip():
            return []

        intent = classify(user_input, self._awaiting_slot)
        self.memory.log("user", user_input, {"intent": intent.intent, "slots": intent.slots})

        responses = self._route(intent)

        for r in responses:
            self.memory.log("assistant", r.get("text", ""), {"type": r.get("type")})

        return responses

    def get_memory_snapshot(self) -> dict:
        return self.memory.to_dict()

    # ── Routing ───────────────────────────────────────────────

    def _route(self, intent: IntentResult) -> list[dict]:
        # Global commands
        if intent.intent == "help":
            self._awaiting_slot = None
            return [self._help()]
        if intent.intent == "status":
            return [self._status()]
        if intent.intent == "resume":
            return self._handle_resume(intent)
        if intent.intent == "cancel":
            return self._handle_cancel()

        # Service switching
        new_svc = self._detect_service(intent)
        if new_svc and new_svc != self.memory.active_service:
            return self._switch_service(new_svc, intent)

        # No active service
        if self.memory.active_service == ServiceType.NONE:
            return [self._msg(
                "I can help you book flights or hotels — which would you like?\n"
                "Try: *\"Book a flight from Delhi to Mumbai\"* or *\"Find hotels in Goa\"*"
            )]

        # Delegate to active service
        svc = self.memory.active_service
        if svc == ServiceType.FLIGHT:
            return self._flight_handle(intent)
        if svc == ServiceType.HOTEL:
            return self._hotel_handle(intent)

        return [self._msg("I'm not sure what you need. Type *help* for options.")]

    # ── Service detection ─────────────────────────────────────

    def _detect_service(self, intent: IntentResult) -> Optional[ServiceType]:
        if intent.service == "flight" or intent.intent == "search_flight":
            return ServiceType.FLIGHT
        if intent.service == "hotel" or intent.intent == "search_hotel":
            return ServiceType.HOTEL
        return None

    def _switch_service(self, target: ServiceType, intent: IntentResult) -> list[dict]:
        prev = self.memory.active_service
        self.memory.switch_service(target)
        responses = []
        if prev != ServiceType.NONE:
            responses.append(self._msg(
                f"Switching to **{target.value}** booking. "
                f"Your {prev.value} progress is saved — say *\"resume {prev.value}\"* to return.",
                msg_type="switch_notice"
            ))

        if target == ServiceType.FLIGHT:
            responses += self._flight_handle(intent)
        else:
            responses += self._hotel_handle(intent)
        return responses

    # ── Flight handlers ───────────────────────────────────────

    def _flight_handle(self, intent: IntentResult) -> list[dict]:
        ctx = self.memory.flight
        changed = self._apply_flight_slots(ctx, intent.slots)

        # Invalidation
        search_keys = {"origin", "destination", "travel_date", "passengers"}
        if changed and set(changed) & search_keys and ctx.step not in (FlowStep.IDLE, FlowStep.COLLECTING):
            ctx.invalidate_results()
            return [
                self._msg(f"⚠ {', '.join(changed)} changed — clearing previous results and re-searching.", "warning"),
            ] + self._flight_collect(ctx)

        if intent.intent in ("search_flight", "provide_info", "update_param"):
            if ctx.step == FlowStep.COLLECTING_PAX:
                return self._flight_collect_pax(ctx)
            return self._flight_collect(ctx)

        if intent.intent == "select_offer":
            return self._flight_select(ctx, intent.slots.get("index"))

        if intent.intent == "query_offer":
            return self._flight_query(ctx, intent)

        if intent.intent == "confirm":
            return self._flight_confirm(ctx)

        if intent.intent == "cancel":
            return self._flight_cancel(ctx)

        # Unknown — continue flow
        if ctx.step == FlowStep.COLLECTING_PAX:
            return self._flight_collect_pax(ctx)
        return self._flight_collect(ctx)

    def _apply_flight_slots(self, ctx: FlightContext, slots: dict) -> list[str]:
        changed = []
        sp = ctx.search_params
        pd = ctx.passenger_details
        mapping = {
            "origin": sp.origin, "destination": sp.destination,
            "travel_date": sp.travel_date, "passengers": sp.passengers,
            "name": pd.name, "email": pd.email, "phone": pd.phone,
        }
        for key, slot in mapping.items():
            if key in slots and slots[key]:
                v = str(slots[key])
                if slot.is_ready and slot.value != v:
                    changed.append(key)
                slot.fill(v)
        return changed

    def _flight_collect(self, ctx: FlightContext) -> list[dict]:
        """Collect slots, then search when all ready."""
        sp = ctx.search_params
        missing = sp.missing()

        if missing:
            ctx.step = FlowStep.COLLECTING
            slot = missing[0]
            self._awaiting_slot = slot
            prompts = {
                "origin":      ("🛫 Where are you flying **from**?", "City name or airport code (e.g. Delhi, BOM)"),
                "destination": ("🛬 Where are you flying **to**?", "City name or airport code (e.g. Goa, BLR)"),
                "travel_date": ("📅 What's your **travel date**?", "Format: YYYY-MM-DD (e.g. 2026-03-15)"),
                "passengers":  ("👤 How many **passengers**?", "Enter a number (e.g. 2)"),
            }
            title, hint = prompts[slot]
            return [{"type": "asking", "text": title, "data": {"hint": hint, "slot": slot}, "meta": self._meta()}]

        # All slots filled — run search
        ctx.step = FlowStep.SEARCHING
        self._awaiting_slot = None
        results = search_flights(
            sp.origin.value, sp.destination.value,
            sp.travel_date.value, int(sp.passengers.value)
        )
        ctx.search_results = results
        ctx.step = FlowStep.RESULTS

        return [
            self._msg(f"Found **{len(results)} flights** from {sp.origin.value} → {sp.destination.value} on {sp.travel_date.value} for {sp.passengers.value} passenger(s):"),
            {
                "type": "flight_results",
                "text": "Select a flight to continue.",
                "data": {"flights": results, "origin": sp.origin.value, "destination": sp.destination.value},
                "meta": self._meta(),
            },
            self._msg("Reply with **Option 1**, **Option 2**, or **Option 3** to select a flight, or ask me anything about them."),
        ]

    def _flight_select(self, ctx: FlightContext, index: Optional[int]) -> list[dict]:
        if not ctx.search_results:
            return self._flight_collect(ctx)

        if not index or index > len(ctx.search_results):
            return [self._msg(f"Please choose Option 1, 2, or 3.")]

        ctx.selected_offer = ctx.search_results[index - 1]
        ctx.step = FlowStep.VERIFYING
        self._awaiting_slot = None

        return [
            self._msg(f"Great choice! Here are the full details for **{ctx.selected_offer['airline']} {ctx.selected_offer['flight_no']}**:"),
            {
                "type": "flight_details",
                "text": "Flight details",
                "data": {"flight": ctx.selected_offer},
                "meta": self._meta(),
            },
            {"type": "asking", "text": "Would you like to **book this flight**?",
             "data": {"hint": "Reply yes to proceed, no to choose another", "slot": "confirm"},
             "meta": self._meta()},
        ]

    def _flight_query(self, ctx: FlightContext, intent: IntentResult) -> list[dict]:
        results = ctx.search_results
        if not results:
            return self._flight_collect(ctx)

        idx  = intent.slots.get("index")
        offer = ctx.selected_offer
        if idx and 1 <= idx <= len(results):
            offer = results[idx - 1]
        elif not offer and results:
            offer = results[0]

        text = intent.raw.lower()
        name = f"{offer['airline']} {offer['flight_no']}" if offer else "that flight"

        if any(k in text for k in ("refund", "cancel", "policy")):
            resp = f"**Cancellation policy** for {name}:\n\n{offer['cancellation_policy']}\n\nThis fare is **{'refundable' if offer['refundable'] else 'non-refundable'}**."
        elif any(k in text for k in ("baggage", "luggage", "bag")):
            resp = f"**Baggage allowance** for {name}:\n\n{offer['baggage']}"
        elif any(k in text for k in ("fare", "price", "cost", "total")):
            f = offer["fare"]
            resp = (f"**Fare breakdown** for {name}:\n\n"
                    f"Base fare: ₹{f['base']:,} × {offer['passengers']} = ₹{f['base']*offer['passengers']:,}\n"
                    f"Taxes: ₹{f['taxes']*offer['passengers']:,}\n"
                    f"**Total: ₹{f['total']:,}**")
        else:
            return [{
                "type": "flight_details",
                "text": f"Details for {name}",
                "data": {"flight": offer},
                "meta": self._meta(),
            }]

        return [self._msg(resp)]

    def _flight_collect_pax(self, ctx: FlightContext) -> list[dict]:
        pd = ctx.passenger_details
        missing = pd.missing()
        if not missing:
            return self._flight_do_book(ctx)

        slot = missing[0]
        self._awaiting_slot = slot
        prompts = {
            "name":  ("👤 Passenger's **full name**?", "As it appears on your ID"),
            "email": ("📧 Passenger's **email address**?", "For booking confirmation"),
            "phone": ("📱 Passenger's **phone number**?", "Including country code"),
        }
        title, hint = prompts[slot]
        return [{"type": "asking", "text": title, "data": {"hint": hint, "slot": slot}, "meta": self._meta()}]

    def _flight_confirm(self, ctx: FlightContext) -> list[dict]:
        if ctx.step == FlowStep.VERIFYING:
            ctx.step = FlowStep.COLLECTING_PAX
            return self._flight_collect_pax(ctx)

        if ctx.step == FlowStep.COLLECTING_PAX:
            pd = ctx.passenger_details
            if not pd.all_filled():
                return self._flight_collect_pax(ctx)
            return self._flight_do_book(ctx)

        if ctx.step == FlowStep.CONFIRMING:
            return self._flight_do_book(ctx)

        return [self._msg("Nothing to confirm right now. What would you like to do?")]

    def _flight_do_book(self, ctx: FlightContext) -> list[dict]:
        pd = ctx.passenger_details
        if not pd.all_filled():
            return self._flight_collect_pax(ctx)

        passenger = {k: getattr(pd, k).value for k in pd.REQUIRED}

        if ctx.step == FlowStep.COLLECTING_PAX:
            # Show summary first
            ctx.step = FlowStep.CONFIRMING
            self._awaiting_slot = "confirm"
            offer = ctx.selected_offer
            return [
                self._msg("Here's your **booking summary**:"),
                {
                    "type": "booking_summary",
                    "text": "Booking summary",
                    "data": {
                        "flight": offer,
                        "passenger": passenger,
                    },
                    "meta": self._meta(),
                },
                {"type": "asking", "text": "Confirm booking and **process payment**?",
                 "data": {"hint": "Reply yes to confirm and pay", "slot": "confirm"},
                 "meta": self._meta()},
            ]

        # Actually book
        ctx.step = FlowStep.BOOKED
        self._awaiting_slot = None
        booking = confirm_flight_booking(ctx.selected_offer, passenger)
        ctx.booking_ref = booking["booking_ref"]

        return [{
            "type": "booking_confirm",
            "text": "Flight booked successfully!",
            "data": {"booking": booking, "service": "flight"},
            "meta": self._meta(),
        }]

    def _flight_cancel(self, ctx: FlightContext) -> list[dict]:
        self._awaiting_slot = None
        if ctx.step == FlowStep.VERIFYING:
            ctx.selected_offer = None
            ctx.step = FlowStep.RESULTS
            return [
                self._msg("No problem. Here are the flights again — which would you prefer?"),
                {
                    "type": "flight_results",
                    "text": "",
                    "data": {"flights": ctx.search_results},
                    "meta": self._meta(),
                }
            ]
        return [self._msg("Cancelled. What would you like to do?")]

    # ── Hotel handlers ────────────────────────────────────────

    def _hotel_handle(self, intent: IntentResult) -> list[dict]:
        ctx = self.memory.hotel
        changed = self._apply_hotel_slots(ctx, intent.slots)

        search_keys = {"city", "checkin_date", "checkout_date", "guests"}
        if changed and set(changed) & search_keys and ctx.step not in (FlowStep.IDLE, FlowStep.COLLECTING):
            ctx.invalidate_results()
            return [
                self._msg(f"⚠ {', '.join(changed)} changed — clearing previous results and re-searching.", "warning"),
            ] + self._hotel_collect(ctx)

        if intent.intent in ("search_hotel", "provide_info", "update_param"):
            if ctx.step == FlowStep.COLLECTING_PAX:
                return self._hotel_collect_guest(ctx)
            return self._hotel_collect(ctx)

        if intent.intent == "select_offer":
            return self._hotel_select(ctx, intent.slots.get("index"))

        if intent.intent == "query_offer":
            return self._hotel_query(ctx, intent)

        if intent.intent == "confirm":
            return self._hotel_confirm(ctx)

        if intent.intent == "cancel":
            return self._hotel_cancel(ctx)

        if ctx.step == FlowStep.COLLECTING_PAX:
            return self._hotel_collect_guest(ctx)
        return self._hotel_collect(ctx)

    def _apply_hotel_slots(self, ctx: HotelContext, slots: dict) -> list[str]:
        changed = []
        sp = ctx.search_params
        gd = ctx.guest_details
        mapping = {
            "city": sp.city, "checkin_date": sp.checkin_date,
            "checkout_date": sp.checkout_date, "guests": sp.guests,
            "name": gd.name, "email": gd.email, "phone": gd.phone,
        }
        for key, slot in mapping.items():
            if key in slots and slots[key]:
                v = str(slots[key])
                if slot.is_ready and slot.value != v:
                    changed.append(key)
                slot.fill(v)
        return changed

    def _hotel_collect(self, ctx: HotelContext) -> list[dict]:
        sp = ctx.search_params
        missing = sp.missing()

        if missing:
            ctx.step = FlowStep.COLLECTING
            slot = missing[0]
            self._awaiting_slot = slot
            prompts = {
                "city":          ("🏙 Which **city** are you looking for hotels in?", "e.g. Mumbai, Goa, Delhi"),
                "checkin_date":  ("📅 What's your **check-in date**?", "Format: YYYY-MM-DD (e.g. 2026-03-15)"),
                "checkout_date": ("📅 What's your **check-out date**?", "Format: YYYY-MM-DD (e.g. 2026-03-18)"),
                "guests":        ("👥 How many **guests**?", "Enter a number (e.g. 2)"),
            }
            title, hint = prompts[slot]
            return [{"type": "asking", "text": title, "data": {"hint": hint, "slot": slot}, "meta": self._meta()}]

        ctx.step = FlowStep.SEARCHING
        self._awaiting_slot = None
        results = search_hotels(
            sp.city.value, sp.checkin_date.value,
            sp.checkout_date.value, int(sp.guests.value)
        )
        ctx.search_results = results
        ctx.step = FlowStep.RESULTS

        return [
            self._msg(f"Found **{len(results)} hotels** in {sp.city.value} for {sp.guests.value} guest(s) · {sp.checkin_date.value} to {sp.checkout_date.value}:"),
            {
                "type": "hotel_results",
                "text": "Select a hotel to continue.",
                "data": {"hotels": results, "city": sp.city.value},
                "meta": self._meta(),
            },
            self._msg("Reply with **Option 1**, **Option 2**, or **Option 3** — or ask about any hotel's amenities, policy, or pricing."),
        ]

    def _hotel_select(self, ctx: HotelContext, index: Optional[int]) -> list[dict]:
        if not ctx.search_results:
            return self._hotel_collect(ctx)
        if not index or index > len(ctx.search_results):
            return [self._msg("Please choose Option 1, 2, or 3.")]

        ctx.selected_offer = ctx.search_results[index - 1]
        ctx.step = FlowStep.VERIFYING
        self._awaiting_slot = None

        return [
            self._msg(f"Great! Here are the full details for **{ctx.selected_offer['name']}**:"),
            {
                "type": "hotel_details",
                "text": "Hotel details",
                "data": {"hotel": ctx.selected_offer},
                "meta": self._meta(),
            },
            {"type": "asking", "text": "Would you like to **book this hotel**?",
             "data": {"hint": "Reply yes to proceed, no to choose another", "slot": "confirm"},
             "meta": self._meta()},
        ]

    def _hotel_query(self, ctx: HotelContext, intent: IntentResult) -> list[dict]:
        results = ctx.search_results
        if not results:
            return self._hotel_collect(ctx)

        idx   = intent.slots.get("index")
        offer = ctx.selected_offer
        if idx and 1 <= idx <= len(results):
            offer = results[idx - 1]
        elif not offer and results:
            offer = results[0]

        text = intent.raw.lower()
        name = offer["name"] if offer else "that hotel"

        if any(k in text for k in ("ameniti", "facilities", "include", "feature")):
            items = "\n".join(f"• {a}" for a in offer["amenities"])
            bfast = "✅ **Breakfast included**" if offer["breakfast_included"] else "❌ Breakfast not included"
            resp  = f"**Amenities at {name}:**\n\n{items}\n\n{bfast}"
        elif any(k in text for k in ("cancel", "refund", "policy")):
            resp = f"**Cancellation policy** for {name}:\n\n{offer['cancellation_policy']}"
        elif any(k in text for k in ("price", "cost", "rate", "night", "total")):
            resp = (f"**Pricing for {name}:**\n\n"
                    f"₹{offer['price_per_night']:,} per night × {offer.get('nights', '?')} nights\n"
                    f"**Total: ₹{offer.get('total_price', '?'):,}**")
        elif any(k in text for k in ("breakfast", "meal", "food")):
            bfast = "**Breakfast is included** in the room rate." if offer["breakfast_included"] else "**Breakfast is not included.** It can be added at the property."
            resp  = f"{name}: {bfast}"
        else:
            return [{
                "type": "hotel_details",
                "text": f"Details for {name}",
                "data": {"hotel": offer},
                "meta": self._meta(),
            }]

        return [self._msg(resp)]

    def _hotel_collect_guest(self, ctx: HotelContext) -> list[dict]:
        gd = ctx.guest_details
        missing = gd.missing()
        if not missing:
            return self._hotel_do_book(ctx)

        slot = missing[0]
        self._awaiting_slot = slot
        prompts = {
            "name":  ("👤 Primary guest's **full name**?", "As it appears on your ID"),
            "email": ("📧 Guest's **email address**?", "For booking confirmation"),
            "phone": ("📱 Guest's **phone number**?", "Including country code"),
        }
        title, hint = prompts[slot]
        return [{"type": "asking", "text": title, "data": {"hint": hint, "slot": slot}, "meta": self._meta()}]

    def _hotel_confirm(self, ctx: HotelContext) -> list[dict]:
        if ctx.step == FlowStep.VERIFYING:
            ctx.step = FlowStep.COLLECTING_PAX
            return self._hotel_collect_guest(ctx)
        if ctx.step == FlowStep.COLLECTING_PAX:
            if not ctx.guest_details.all_filled():
                return self._hotel_collect_guest(ctx)
            return self._hotel_do_book(ctx)
        if ctx.step == FlowStep.CONFIRMING:
            return self._hotel_do_book(ctx)
        return [self._msg("Nothing to confirm right now.")]

    def _hotel_do_book(self, ctx: HotelContext) -> list[dict]:
        gd = ctx.guest_details
        if not gd.all_filled():
            return self._hotel_collect_guest(ctx)

        guest = {k: getattr(gd, k).value for k in gd.REQUIRED}

        if ctx.step == FlowStep.COLLECTING_PAX:
            ctx.step = FlowStep.CONFIRMING
            self._awaiting_slot = "confirm"
            return [
                self._msg("Here's your **hotel booking summary**:"),
                {
                    "type": "hotel_booking_summary",
                    "text": "Hotel booking summary",
                    "data": {
                        "hotel": ctx.selected_offer,
                        "guest": guest,
                    },
                    "meta": self._meta(),
                },
                {"type": "asking", "text": "Confirm booking and **process payment**?",
                 "data": {"hint": "Reply yes to confirm and pay", "slot": "confirm"},
                 "meta": self._meta()},
            ]

        ctx.step = FlowStep.BOOKED
        self._awaiting_slot = None
        booking = confirm_hotel_booking(ctx.selected_offer, guest)
        ctx.booking_ref = booking["booking_ref"]

        return [{
            "type": "booking_confirm",
            "text": "Hotel booked successfully!",
            "data": {"booking": booking, "service": "hotel"},
            "meta": self._meta(),
        }]

    def _hotel_cancel(self, ctx: HotelContext) -> list[dict]:
        self._awaiting_slot = None
        if ctx.step == FlowStep.VERIFYING:
            ctx.selected_offer = None
            ctx.step = FlowStep.RESULTS
            return [
                self._msg("No problem. Here are the hotels again:"),
                {
                    "type": "hotel_results",
                    "text": "",
                    "data": {"hotels": ctx.search_results},
                    "meta": self._meta(),
                }
            ]
        return [self._msg("Cancelled. What would you like to do?")]

    # ── Resume / cancel ───────────────────────────────────────

    def _handle_resume(self, intent: IntentResult) -> list[dict]:
        target = None
        if intent.service:
            target = ServiceType(intent.service)
        elif self.memory.previous_service != ServiceType.NONE:
            target = self.memory.previous_service

        if not target:
            return [self._msg("No previous service to resume. What would you like to book?")]

        self.memory.switch_service(target)
        ctx = self.memory.active_context()
        self._awaiting_slot = None

        responses = [self._msg(
            f"Resuming your **{target.value} booking** — {ctx.summary() if ctx else ''}",
            "resume_notice"
        )]

        if target == ServiceType.FLIGHT:
            responses += self._flight_collect(self.memory.flight) if self.memory.flight.step in (
                FlowStep.IDLE, FlowStep.COLLECTING
            ) else self._show_flight_state(self.memory.flight)
        else:
            responses += self._hotel_collect(self.memory.hotel) if self.memory.hotel.step in (
                FlowStep.IDLE, FlowStep.COLLECTING
            ) else self._show_hotel_state(self.memory.hotel)

        return responses

    def _show_flight_state(self, ctx: FlightContext) -> list[dict]:
        if ctx.search_results and ctx.step == FlowStep.RESULTS:
            return [{
                "type": "flight_results",
                "text": "Here are your flight options:",
                "data": {"flights": ctx.search_results},
                "meta": self._meta(),
            }]
        return self._flight_collect(ctx)

    def _show_hotel_state(self, ctx: HotelContext) -> list[dict]:
        if ctx.search_results and ctx.step == FlowStep.RESULTS:
            return [{
                "type": "hotel_results",
                "text": "Here are your hotel options:",
                "data": {"hotels": ctx.search_results},
                "meta": self._meta(),
            }]
        return self._hotel_collect(ctx)

    def _handle_cancel(self) -> list[dict]:
        self._awaiting_slot = None
        svc = self.memory.active_service
        if svc == ServiceType.FLIGHT:
            return self._flight_cancel(self.memory.flight)
        if svc == ServiceType.HOTEL:
            return self._hotel_cancel(self.memory.hotel)
        return [self._msg("Nothing active to cancel.")]

    # ── Helpers ───────────────────────────────────────────────

    def _meta(self) -> dict:
        return {
            "session_id":    self.memory.session_id,
            "active":        self.memory.active_service.value,
            "previous":      self.memory.previous_service.value,
            "flight_step":   self.memory.flight.step.value,
            "hotel_step":    self.memory.hotel.step.value,
        }

    def _msg(self, text: str, msg_type: str = "message") -> dict:
        return {"type": msg_type, "text": text, "data": None, "meta": self._meta()}

    def _help(self) -> dict:
        text = (
            "**What I can help with:**\n\n"
            "✈ **Flight booking** — *\"Book a flight from Delhi to Mumbai on 2026-03-15 for 2 passengers\"*\n"
            "🏨 **Hotel booking** — *\"Find hotels in Goa, check-in 2026-03-15, check-out 2026-03-18\"*\n\n"
            "**During any flow:**\n"
            "• Select options: *\"Option 1\"*, *\"Choose the second one\"*\n"
            "• Ask questions: *\"What amenities does option 2 have?\"*\n"
            "• Change a detail: *\"Actually change the date to March 20\"*\n"
            "• Switch services: *\"Also look for hotels\"* (flight progress saved)\n"
            "• Resume: *\"Go back to my flight booking\"*\n"
            "• Memory: *\"status\"*"
        )
        return {"type": "help", "text": text, "data": None, "meta": self._meta()}

    def _status(self) -> dict:
        return {
            "type": "memory_snapshot",
            "text": "Session memory snapshot",
            "data": self.memory.to_dict(),
            "meta": self._meta(),
        }

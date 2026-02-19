"""
Memory Models-

Typed data containers for the Smart Travel Companion.
All state is explicit, typed, and owned here.
Nothing lives in raw chat history.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid


class ServiceType(str, Enum):
    FLIGHT = "flight"
    HOTEL  = "hotel"
    NONE   = "none"


class FlowStep(str, Enum):
    IDLE          = "idle"
    COLLECTING    = "collecting"
    SEARCHING     = "searching"
    RESULTS       = "results"
    VERIFYING     = "verifying"
    COLLECTING_PAX = "collecting_pax"
    CONFIRMING    = "confirming"
    BOOKED        = "booked"


class SlotStatus(str, Enum):
    EMPTY     = "empty"
    FILLED    = "filled"
    CONFIRMED = "confirmed"
    STALE     = "stale"


@dataclass
class Slot:
    name:     str
    value:    Optional[Any]  = None
    status:   SlotStatus     = SlotStatus.EMPTY
    filled_at: Optional[str] = None

    def fill(self, value: Any) -> None:
        self.value     = value
        self.status    = SlotStatus.FILLED
        self.filled_at = datetime.now().isoformat()

    def invalidate(self) -> None:
        if self.status in (SlotStatus.FILLED, SlotStatus.CONFIRMED):
            self.status = SlotStatus.STALE

    def clear(self) -> None:
        self.value  = None
        self.status = SlotStatus.EMPTY

    @property
    def is_ready(self) -> bool:
        return self.status in (SlotStatus.FILLED, SlotStatus.CONFIRMED)

    def to_dict(self) -> dict:
        return {"value": self.value, "status": self.status.value}


@dataclass
class FlightSearchParams:
    origin:      Slot = field(default_factory=lambda: Slot("origin"))
    destination: Slot = field(default_factory=lambda: Slot("destination"))
    travel_date: Slot = field(default_factory=lambda: Slot("travel_date"))
    passengers:  Slot = field(default_factory=lambda: Slot("passengers"))

    REQUIRED = ("origin", "destination", "travel_date", "passengers")

    def all_filled(self) -> bool:
        return all(getattr(self, k).is_ready for k in self.REQUIRED)

    def missing(self) -> list[str]:
        return [k for k in self.REQUIRED if not getattr(self, k).is_ready]


@dataclass
class PassengerDetails:
    name:  Slot = field(default_factory=lambda: Slot("name"))
    email: Slot = field(default_factory=lambda: Slot("email"))
    phone: Slot = field(default_factory=lambda: Slot("phone"))

    REQUIRED = ("name", "email", "phone")

    def all_filled(self) -> bool:
        return all(getattr(self, k).is_ready for k in self.REQUIRED)

    def missing(self) -> list[str]:
        return [k for k in self.REQUIRED if not getattr(self, k).is_ready]


@dataclass
class FlightContext:
    step:              FlowStep           = FlowStep.IDLE
    search_params:     FlightSearchParams = field(default_factory=FlightSearchParams)
    search_results:    list               = field(default_factory=list)
    selected_offer:    Optional[dict]     = None
    passenger_details: PassengerDetails   = field(default_factory=PassengerDetails)
    booking_ref:       Optional[str]      = None

    def invalidate_results(self) -> None:
        self.search_results = []
        self.selected_offer = None
        if self.step in (FlowStep.RESULTS, FlowStep.VERIFYING,
                         FlowStep.COLLECTING_PAX, FlowStep.CONFIRMING):
            self.step = FlowStep.COLLECTING

    def summary(self) -> str:
        p = self.search_params
        parts = []
        if p.origin.is_ready:      parts.append(f"from {p.origin.value}")
        if p.destination.is_ready: parts.append(f"to {p.destination.value}")
        if p.travel_date.is_ready: parts.append(f"on {p.travel_date.value}")
        if p.passengers.is_ready:  parts.append(f"({p.passengers.value} pax)")
        return "Flight [" + self.step.value + "]: " + (" ".join(parts) or "no params")

    def to_dict(self) -> dict:
        sp = self.search_params
        return {
            "step": self.step.value,
            "origin":       sp.origin.to_dict(),
            "destination":  sp.destination.to_dict(),
            "travel_date":  sp.travel_date.to_dict(),
            "passengers":   sp.passengers.to_dict(),
            "results_count": len(self.search_results),
            "selected": self.selected_offer.get("flight_no") if self.selected_offer else None,
            "booking_ref": self.booking_ref,
        }


@dataclass
class HotelSearchParams:
    city:          Slot = field(default_factory=lambda: Slot("city"))
    checkin_date:  Slot = field(default_factory=lambda: Slot("checkin_date"))
    checkout_date: Slot = field(default_factory=lambda: Slot("checkout_date"))
    guests:        Slot = field(default_factory=lambda: Slot("guests"))

    REQUIRED = ("city", "checkin_date", "checkout_date", "guests")

    def all_filled(self) -> bool:
        return all(getattr(self, k).is_ready for k in self.REQUIRED)

    def missing(self) -> list[str]:
        return [k for k in self.REQUIRED if not getattr(self, k).is_ready]


@dataclass
class GuestDetails:
    name:  Slot = field(default_factory=lambda: Slot("name"))
    email: Slot = field(default_factory=lambda: Slot("email"))
    phone: Slot = field(default_factory=lambda: Slot("phone"))

    REQUIRED = ("name", "email", "phone")

    def all_filled(self) -> bool:
        return all(getattr(self, k).is_ready for k in self.REQUIRED)

    def missing(self) -> list[str]:
        return [k for k in self.REQUIRED if not getattr(self, k).is_ready]


@dataclass
class HotelContext:
    step:           FlowStep         = FlowStep.IDLE
    search_params:  HotelSearchParams = field(default_factory=HotelSearchParams)
    search_results: list             = field(default_factory=list)
    selected_offer: Optional[dict]   = None
    guest_details:  GuestDetails     = field(default_factory=GuestDetails)
    booking_ref:    Optional[str]    = None

    def invalidate_results(self) -> None:
        self.search_results = []
        self.selected_offer = None
        if self.step in (FlowStep.RESULTS, FlowStep.VERIFYING,
                         FlowStep.COLLECTING_PAX, FlowStep.CONFIRMING):
            self.step = FlowStep.COLLECTING

    def summary(self) -> str:
        p = self.search_params
        parts = []
        if p.city.is_ready:          parts.append(f"in {p.city.value}")
        if p.checkin_date.is_ready:  parts.append(f"check-in {p.checkin_date.value}")
        if p.checkout_date.is_ready: parts.append(f"check-out {p.checkout_date.value}")
        if p.guests.is_ready:        parts.append(f"({p.guests.value} guests)")
        return "Hotel [" + self.step.value + "]: " + (" ".join(parts) or "no params")

    def to_dict(self) -> dict:
        sp = self.search_params
        return {
            "step": self.step.value,
            "city":          sp.city.to_dict(),
            "checkin_date":  sp.checkin_date.to_dict(),
            "checkout_date": sp.checkout_date.to_dict(),
            "guests":        sp.guests.to_dict(),
            "results_count": len(self.search_results),
            "selected": self.selected_offer.get("name") if self.selected_offer else None,
            "booking_ref": self.booking_ref,
        }


@dataclass
class SessionMemory:
    session_id:       str
    active_service:   ServiceType   = ServiceType.NONE
    previous_service: ServiceType   = ServiceType.NONE
    flight:           FlightContext = field(default_factory=FlightContext)
    hotel:            HotelContext  = field(default_factory=HotelContext)
    conversation:     list          = field(default_factory=list)
    global_facts:     dict          = field(default_factory=dict)
    created_at:       str           = field(default_factory=lambda: datetime.now().isoformat())

    def switch_service(self, new_service: ServiceType) -> None:
        if self.active_service != new_service:
            self.previous_service = self.active_service
            self.active_service   = new_service

    def resume_previous(self) -> bool:
        if self.previous_service != ServiceType.NONE:
            self.active_service, self.previous_service = (
                self.previous_service, self.active_service
            )
            return True
        return False

    def active_context(self):
        if self.active_service == ServiceType.FLIGHT: return self.flight
        if self.active_service == ServiceType.HOTEL:  return self.hotel
        return None

    def log(self, role: str, content: str, meta: dict = None) -> None:
        self.conversation.append({
            "role":    role,
            "content": content,
            "meta":    meta or {},
            "time":    datetime.now().isoformat(),
            "service": self.active_service.value,
        })

    def to_dict(self) -> dict:
        return {
            "session_id":       self.session_id,
            "active_service":   self.active_service.value,
            "previous_service": self.previous_service.value,
            "flight":           self.flight.to_dict(),
            "hotel":            self.hotel.to_dict(),
            "turns":            len(self.conversation),
        }

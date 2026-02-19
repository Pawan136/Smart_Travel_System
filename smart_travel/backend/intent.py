"""
Intent Classifier — v2

Key fix: when user is in a COLLECTING step, a bare number IS the answer
to the current question. The classifier itself can't know which step we're
in, so the orchestrator passes `awaiting_slot` to guide interpretation.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IntentResult:
    intent:   str
    service:  Optional[str] = None
    slots:    dict          = field(default_factory=dict)
    raw:      str           = ""


# ── Keyword sets ──────────────────────────────────────────────
FLIGHT_KW = {"flight","fly","flights","airline","air ticket","plane","airfare","ticket","flying"}
HOTEL_KW  = {"hotel","hotels","stay","room","accommodation","lodge","resort","inn","check-in","checkin"}
RESUME_KW = {"go back","resume","continue","return to","back to","switch back","previous"}
CONFIRM_KW = {"yes","yeah","yep","confirm","correct","ok","okay","proceed","book it","sure","absolutely","done","ready"}
CANCEL_KW  = {"no","nope","cancel","stop","exit","nevermind","never mind","abort","dont","don't"}
HELP_KW    = {"help","what can you do","commands"}
STATUS_KW  = {"status","show memory","show context","debug","snapshot","where am i"}
UPDATE_KW  = {"change","update","modify","actually","instead","wrong","correction"}
QUERY_KW   = {"ameniti","facilities","include","tell me about","cancellation","policy","refund",
               "baggage","breakfast","luggage","what does","does it have","does option","does the",
               "what amenities","what's included"}
SELECT_KW  = {"select","choose","pick","option","go with","take","i'll take","i want the",
               "the first","the second","the third","book option"}

NUMBER_MAP = {
    "one":"1","two":"2","three":"3","four":"4","five":"5",
    "six":"6","seven":"7","eight":"8","nine":"9","ten":"10",
    "first":"1","second":"2","third":"3",
    "1st":"1","2nd":"2","3rd":"3",
}
DATE_RE = re.compile(r'\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b', re.I)
EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.\w+')
PHONE_RE = re.compile(r'\+?[\d\s\-\(\)]{10,16}')
NAME_RE  = re.compile(r'(?:my name is|name is|i am|i\'m|name)\s+([A-Za-z]+(?: [A-Za-z]+)+)', re.I)

CITY_MAP = {
    "new delhi":"DEL","delhi":"DEL","del":"DEL",
    "mumbai":"BOM","bombay":"BOM","bom":"BOM",
    "bangalore":"BLR","bengaluru":"BLR","blr":"BLR",
    "hyderabad":"HYD","hyd":"HYD",
    "chennai":"MAA","madras":"MAA","maa":"MAA",
    "kolkata":"CCU","calcutta":"CCU","ccu":"CCU",
    "goa":"GOA","panaji":"GOA","goa city":"GOA",
    "pune":"PNQ","pnq":"PNQ",
    "ahmedabad":"AMD","amd":"AMD",
    "jaipur":"JAI","jai":"JAI",
    "kochi":"COK","cochin":"COK","cok":"COK",
    "lucknow":"LKO","lko":"LKO",
    "bhopal":"BHO","bho":"BHO",
    "varanasi":"VNS","vns":"VNS","banaras":"VNS",
    "indore":"IDR","idr":"IDR",
    "nagpur":"NAG","nag":"NAG",
    "coimbatore":"CJB","cjb":"CJB",
    "amritsar":"ATQ","atq":"ATQ",
    "agra":"AGR","agr":"AGR",
    "chandigarh":"IXC","ixc":"IXC",
    "guwahati":"GAU","gau":"GAU",
    "bhubaneswar":"BBI","bbi":"BBI",
    "patna":"PAT","pat":"PAT",
    "raipur":"RPR","rpr":"RPR",
    "trichy":"TRZ","tiruchirappalli":"TRZ",
    "visakhapatnam":"VTZ","vizag":"VTZ",
}


def _norm(text: str) -> str:
    t = text.lower().strip()
    for w, n in NUMBER_MAP.items():
        t = re.sub(rf'\b{w}\b', n, t)
    return t


def _city(text: str) -> Optional[str]:
    t = text.lower()
    for name in sorted(CITY_MAP, key=len, reverse=True):
        if name in t:
            return CITY_MAP[name]
    m = re.search(r'\b([A-Z]{3})\b', text)
    return m.group(1) if m else None


def _city_pair(text: str) -> tuple[Optional[str], Optional[str]]:
    t = text.lower()
    # "from X to Y on ..."
    m = re.search(r'from\s+(.+?)\s+to\s+(.+?)(?:\s+on|\s+for|\s+\d|,|$)', t)
    if m:
        o, d = _city(m.group(1)), _city(m.group(2))
        if o and d: return o, d
    # "X to Y"
    m2 = re.search(r'(\w[\w\s]{1,20}?)\s+to\s+(\w[\w\s]{1,20})', t)
    if m2:
        o, d = _city(m2.group(1)), _city(m2.group(2))
        if o and d: return o, d
    return None, None


def _extract_int(text: str) -> Optional[int]:
    """Extract a bare integer from text (for slot filling)."""
    t = _norm(text)
    # Look for standalone integer
    m = re.search(r'\b(\d{1,2})\b', t)
    if m:
        v = int(m.group(1))
        # Reject if it looks like a year
        if v < 1 or v > 99:
            return None
        # Reject if part of a date
        dates = DATE_RE.findall(text)
        date_str = " ".join(dates)
        if m.group(1) in date_str:
            return None
        return v
    return None


def _extract_dates(text: str) -> list[str]:
    return DATE_RE.findall(text)


def _option_index(text: str) -> Optional[int]:
    t = _norm(text)
    patterns = [
        r'option\s+(\d)',
        r'(?:choose|select|pick|go with|take|book)\s+(?:option\s+)?(\d)',
        r'(?:the\s+)?(\d)(?:st|nd|rd|th)?\s+(?:one|option|flight|hotel)',
        r'\b(\d)\b',
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            idx = int(m.group(1))
            if 1 <= idx <= 9:
                return idx
    return None


def _flight_slots(text: str) -> dict:
    slots = {}
    o, d = _city_pair(text)
    if o: slots["origin"] = o
    if d: slots["destination"] = d
    dates = _extract_dates(text)
    if dates: slots["travel_date"] = dates[0]
    # Passengers: explicit word OR bare number (only if no city/date context)
    pax_m = re.search(r'(\d+)\s*(?:passenger|pax|person|people|travell?er|adult)', text, re.I)
    if pax_m:
        slots["passengers"] = pax_m.group(1)
    return slots


def _hotel_slots(text: str) -> dict:
    slots = {}
    t = text.lower()
    has_checkin  = bool(re.search(r'check.?in|arriving|arrival', t))
    has_checkout = bool(re.search(r'check.?out|departing|departure|till|until|leaving', t))

    city_val = _city(text)
    if city_val: slots["city"] = city_val

    dates = _extract_dates(text)
    if len(dates) >= 2:
        slots["checkin_date"]  = dates[0]
        slots["checkout_date"] = dates[1]
    elif len(dates) == 1:
        if has_checkout and not has_checkin:
            slots["checkout_date"] = dates[0]
        else:
            slots["checkin_date"] = dates[0]

    guests_m = re.search(r'(\d+)\s*(?:guest|person|people|adult|pax)', text, re.I)
    if guests_m: slots["guests"] = guests_m.group(1)

    return slots


def _personal_slots(text: str) -> dict:
    slots = {}
    em = EMAIL_RE.search(text)
    if em: slots["email"] = em.group(0)
    nm = NAME_RE.search(text)
    if nm: slots["name"] = nm.group(1).strip()
    ph = PHONE_RE.search(text)
    if ph:
        candidate = ph.group(0).strip()
        digits = re.sub(r'\D', '', candidate)
        if len(digits) >= 10:
            slots["phone"] = candidate
    return slots


# ── Main classifier ───────────────────────────────────────────

def classify(text: str, awaiting_slot: Optional[str] = None) -> IntentResult:
    """
    Classify user input into a structured intent.
    
    awaiting_slot: If set, we are mid-collection and a bare value
                   should be interpreted as filling this slot.
                   e.g. awaiting_slot="passengers" → "4" fills passengers
    """
    t = _norm(text)
    raw = text

    # ── Hard commands ─────────────────────────────────────────
    if any(k in t for k in HELP_KW) and len(t.split()) <= 3:
        return IntentResult("help", raw=raw)
    if any(k in t for k in STATUS_KW):
        return IntentResult("status", raw=raw)

    # ── Resume ────────────────────────────────────────────────
    if any(k in t for k in RESUME_KW):
        svc = None
        if any(k in t for k in FLIGHT_KW): svc = "flight"
        if any(k in t for k in HOTEL_KW):  svc = "hotel"
        return IntentResult("resume", service=svc, raw=raw)

    # ── Cancel ────────────────────────────────────────────────
    if any(k in t for k in CANCEL_KW) and len(t.split()) <= 4:
        return IntentResult("cancel", raw=raw)

    # ── Confirm ───────────────────────────────────────────────
    if any(k in t for k in CONFIRM_KW) and len(t.split()) <= 5:
        return IntentResult("confirm", raw=raw)

    # ── Query about offer details ─────────────────────────────
    if any(k in t for k in QUERY_KW):
        idx = _option_index(raw)
        return IntentResult("query_offer", slots={"index": idx}, raw=raw)

    # ── Service detection ─────────────────────────────────────
    is_flight = any(k in t for k in FLIGHT_KW)
    is_hotel  = any(k in t for k in HOTEL_KW)

    # ── CONTEXT-AWARE SLOT FILL ───────────────────────────────
    # If we're awaiting a specific slot, treat bare values as that slot
    if awaiting_slot:
        slots = {}

        # Personal details slots
        personal = _personal_slots(raw)
        if personal:
            return IntentResult("provide_info", slots=personal, raw=raw)

        # Bare number → fill the awaiting numeric slot
        num = _extract_int(text)
        if num is not None and awaiting_slot in ("passengers", "guests"):
            return IntentResult("provide_info",
                                slots={awaiting_slot: str(num)}, raw=raw)

        # Date → fill date slot
        dates = _extract_dates(text)
        if dates and awaiting_slot in ("travel_date", "checkin_date", "checkout_date"):
            return IntentResult("provide_info",
                                slots={awaiting_slot: dates[0]}, raw=raw)

        # City → fill city slot
        city = _city(text)
        if city and awaiting_slot in ("origin", "destination", "city"):
            return IntentResult("provide_info",
                                slots={awaiting_slot: city}, raw=raw)

        # Also try raw text as city name for unknown cities
        if awaiting_slot in ("origin", "destination", "city"):
            # Could be an unknown city name
            if re.match(r'^[A-Za-z\s]{2,30}$', raw.strip()):
                return IntentResult("provide_info",
                                    slots={awaiting_slot: raw.strip().title()}, raw=raw)

        # Bare name → fill name slot
        if awaiting_slot == "name":
            # If it looks like a person name (2+ words, letters only)
            if re.match(r'^[A-Za-z]+(?: [A-Za-z]+)+$', raw.strip()):
                return IntentResult("provide_info",
                                    slots={"name": raw.strip()}, raw=raw)
            # Also: name might have "is" - handle "Rahul Verma" directly
            if re.match(r'^[A-Za-z]+$', raw.strip()):  # single word name
                return IntentResult("provide_info",
                                    slots={"name": raw.strip()}, raw=raw)

        # Bare email
        if awaiting_slot == "email":
            em = EMAIL_RE.search(raw)
            if em:
                return IntentResult("provide_info", slots={"email": em.group(0)}, raw=raw)

        # Bare phone
        if awaiting_slot == "phone":
            ph = PHONE_RE.search(raw)
            if ph:
                digits = re.sub(r'\D', '', ph.group(0))
                if len(digits) >= 10:
                    return IntentResult("provide_info", slots={"phone": ph.group(0).strip()}, raw=raw)

    # ── Update / change param ─────────────────────────────────
    if any(k in t for k in UPDATE_KW):
        slots: dict = {}
        if is_flight or not is_hotel:
            slots.update(_flight_slots(raw))
        if is_hotel or not is_flight:
            for k, v in _hotel_slots(raw).items():
                if k not in slots: slots[k] = v
        slots.update(_personal_slots(raw))
        svc = "flight" if is_flight else ("hotel" if is_hotel else None)
        return IntentResult("update_param", service=svc, slots=slots, raw=raw)

    # ── Option selection ──────────────────────────────────────
    has_pax = bool(re.search(r'passenger|pax|guest|person|people|travell', t, re.I))
    idx = _option_index(raw)
    if idx and not has_pax and not is_flight and not is_hotel:
        if any(k in t for k in SELECT_KW | {"option"}):
            return IntentResult("select_offer", slots={"index": idx}, raw=raw)
        if len(t.split()) <= 2:
            return IntentResult("select_offer", slots={"index": idx}, raw=raw)

    # ── Flight search intent ──────────────────────────────────
    if is_flight and not is_hotel:
        slots = _flight_slots(raw)
        slots.update(_personal_slots(raw))
        return IntentResult("search_flight", service="flight", slots=slots, raw=raw)

    # ── Hotel search intent ───────────────────────────────────
    if is_hotel and not is_flight:
        slots = _hotel_slots(raw)
        slots.update(_personal_slots(raw))
        return IntentResult("search_hotel", service="hotel", slots=slots, raw=raw)

    # ── General info provision ────────────────────────────────
    slots = {}
    slots.update(_flight_slots(raw))
    for k, v in _hotel_slots(raw).items():
        if k not in slots: slots[k] = v
    slots.update(_personal_slots(raw))
    if slots:
        return IntentResult("provide_info", slots=slots, raw=raw)

    return IntentResult("unknown", raw=raw)

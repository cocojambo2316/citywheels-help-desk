"""Tools for the CityWheels help desk agent.

Plain Python, no LLM here: every function can be tested without a network or an API key.
Every tool returns a dict, so the agent can send it to the model as JSON.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
BOOKINGS_FILE = DATA_DIR / "bookings.json"
POLICIES_DIR = DATA_DIR / "policies"

# The fixed "current date" from README.md: 2026-06-10 09:00, Europe/Warsaw (UTC+02:00).
# A fixed offset instead of ZoneInfo("Europe/Warsaw"): no tzdata needed on Windows,
# and all bookings use +02:00 anyway.
WARSAW = timezone(timedelta(hours=2))
NOW = datetime(2026, 6, 10, 9, 0, tzinfo=WARSAW)

CANCELLABLE_STATUS = "confirmed"


# ---------- get_booking ----------

def load_bookings(path: Path = BOOKINGS_FILE) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_booking_id(booking_id: str) -> str:
    """'cw 1002', ' CW-1002 ', 'cw1002' -> 'CW-1002'."""
    cleaned = booking_id.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("CW"):
        cleaned = "CW-" + cleaned[2:]
    return cleaned


def get_booking(booking_id: str) -> dict:
    """Return one booking, or a clear 'not found' result. Never raises for a bad id."""
    wanted = normalize_booking_id(booking_id)
    for booking in load_bookings():
        if booking["id"] == wanted:
            return {"found": True, "booking": booking}
    return {
        "found": False,
        "booking_id": booking_id,
        "message": f"Booking {booking_id} was not found.",
    }


# ---------- calculate_refund ----------

def refund_percent(hours_before_start: float) -> int:
    """Rule from cancellations.md. Boundaries: exactly 48 h -> 100%, exactly 24 h -> 50%."""
    if hours_before_start >= 48:
        return 100
    if hours_before_start >= 24:
        return 50
    return 0


def parse_cancel_time(cancel_at: str | None) -> datetime:
    """None -> NOW. A time without a zone is treated as Warsaw time."""
    if cancel_at is None:
        return NOW
    moment = datetime.fromisoformat(cancel_at)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=WARSAW)
    return moment


def calculate_refund(booking_id: str, cancel_at: str | None = None) -> dict:
    """How much the customer gets back if the booking is cancelled at `cancel_at` (default: now)."""
    result = get_booking(booking_id)
    if not result["found"]:
        return result
    booking = result["booking"]

    try:
        moment = parse_cancel_time(cancel_at)
    except ValueError:
        return {"found": True, "error": f"Invalid date: {cancel_at}. Use ISO format, e.g. 2026-06-11T09:00."}

    start = datetime.fromisoformat(booking["start"])
    hours_before_start = (start - moment).total_seconds() / 3600

    base = {
        "found": True,
        "booking_id": booking["id"],
        "status": booking["status"],
        "cancel_at": moment.isoformat(),
        "hours_before_start": round(hours_before_start, 2),
    }

    if booking["status"] != CANCELLABLE_STATUS:
        return base | {
            "can_cancel": False,
            "reason": (
                f"Bookings with status '{booking['status']}' cannot be cancelled, so nothing is refunded "
                "by a cancellation. (For a rental in progress, the deposit is handled when the bike is returned.)"
            ),
            "total_refund_eur": 0.0,
        }

    # Our decision: the JSON may still say 'confirmed' after the start time
    # (the data is a snapshot). A rental that has already started is not cancellable.
    if hours_before_start <= 0:
        return base | {
            "can_cancel": False,
            "reason": "The rental has already started at this time, so it cannot be cancelled.",
            "total_refund_eur": 0.0,
        }

    percent = refund_percent(hours_before_start)
    rental_refund = round(booking["rental_price_eur"] * percent / 100, 2)
    deposit_refund = booking["deposit_eur"]  # always refunded in full on cancellation
    total = round(rental_refund + deposit_refund, 2)

    if booking["paid_with"] == "voucher":
        method = "As a new voucher of the same value, never as money."
    else:
        method = "To the same card within 5 working days."

    return base | {
        "can_cancel": True,
        "rental_price_eur": booking["rental_price_eur"],
        "refund_percent": percent,
        "rental_refund_eur": rental_refund,
        "deposit_refund_eur": deposit_refund,
        "booking_fee_refund_eur": 0.0,  # the booking fee is never refunded
        "booking_fee_kept_eur": booking["booking_fee_eur"],
        "total_refund_eur": total,
        "refund_method": method,
    }


# ---------- search_policies ----------
# Approach: split every Markdown file into sections at "## " headings, then score each
# section by how many words of the query it contains (words in the heading count double).
# Simple keyword search is enough for 3 short files; no embeddings, no extra services.

STOP_WORDS = {
    "a", "an", "the", "and", "or", "is", "are", "do", "does", "can", "i", "you", "we",
    "my", "your", "to", "of", "in", "on", "for", "with", "what", "how", "when", "much",
    "it", "be", "if", "at", "there", "any", "me", "get", "need",
}
MAX_RESULTS = 3


def stem(word: str) -> str:
    """Very small stemmer: 'opening' -> 'open', 'prices' -> 'price', 'cancelled' -> 'cancel'."""
    for suffix in ("ing", "led", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {stem(w) for w in words if w not in STOP_WORDS}


def load_sections(policies_dir: Path = POLICIES_DIR) -> list[dict]:
    """Every '## ' section of every policy file, with the file name and the heading."""
    sections = []
    for path in sorted(policies_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        # parts[0] is the document title ("# Prices" + intro), the rest start with a heading
        parts = re.split(r"^## ", text, flags=re.MULTILINE)
        title = parts[0].strip().lstrip("# ").splitlines()[0]
        for part in parts[1:]:
            heading, _, body = part.partition("\n")
            sections.append({
                "source": path.name,
                "title": title,
                "heading": heading.strip(),
                "text": body.strip(),
            })
    return sections


def search_policies(query: str) -> dict:
    """Return the policy sections most relevant to the query, best first."""
    query_words = keywords(query)
    scored = []
    for section in load_sections():
        heading_words = keywords(section["title"] + " " + section["heading"])
        body_words = keywords(section["text"])
        score = 2 * len(query_words & heading_words) + len(query_words & body_words)
        if score > 0:
            scored.append((score, section))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    results = [section for _, section in scored[:MAX_RESULTS]]
    if not results:
        return {"results": [], "message": "No relevant policy sections found."}
    return {"results": results}
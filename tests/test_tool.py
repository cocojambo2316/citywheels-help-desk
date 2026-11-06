from tools import calculate_refund, get_booking, search_policies


# ---------- calculate_refund: refund rules ----------

def test_cw1001_48h_or_more_full_refund():
    # 73 h before start -> 100% of rental (40) + deposit (50)
    result = calculate_refund("CW-1001")
    assert result["refund_percent"] == 100
    assert result["total_refund_eur"] == 90.0


def test_cw1002_between_24_and_48h_half_refund():
    # 33 h before start -> 50% of rental (80 * 0.5 = 40) + deposit (300)
    result = calculate_refund("CW-1002")
    assert result["refund_percent"] == 50
    assert result["total_refund_eur"] == 340.0


def test_cw1003_less_than_24h_only_deposit():
    # 6 h before start -> 0% of rental, deposit (50) still comes back
    result = calculate_refund("CW-1003")
    assert result["rental_refund_eur"] == 0.0
    assert result["total_refund_eur"] == 50.0


def test_cw1007_exactly_48h_is_full_refund():
    # boundary: exactly 48 h counts as "48 hours or more"
    result = calculate_refund("CW-1007")
    assert result["hours_before_start"] == 48
    assert result["refund_percent"] == 100
    assert result["total_refund_eur"] == 186.0


def test_cw1010_exactly_24h_is_half_refund():
    # boundary: exactly 24 h counts as "24 hours or more"
    result = calculate_refund("CW-1010")
    assert result["hours_before_start"] == 24
    assert result["refund_percent"] == 50
    assert result["total_refund_eur"] == 170.0


def test_booking_fee_is_never_refunded():
    result = calculate_refund("CW-1001")
    assert result["booking_fee_refund_eur"] == 0.0


def test_cw1004_voucher_refunded_as_voucher():
    # 240 h before start -> 100% of rental (23) + deposit (50), paid with voucher
    result = calculate_refund("CW-1004")
    assert result["total_refund_eur"] == 73.0
    assert "voucher" in result["refund_method"]


def test_cw1009_long_rental_full_refund():
    # 121 h before start -> 100% of rental (119, already with the 7-day discount) + deposit (50)
    result = calculate_refund("CW-1009")
    assert result["refund_percent"] == 100
    assert result["total_refund_eur"] == 169.0


def test_cancelled_booking_cannot_be_cancelled():
    result = calculate_refund("CW-1005")
    assert result["can_cancel"] is False
    assert result["total_refund_eur"] == 0.0


def test_completed_booking_cannot_be_cancelled():
    result = calculate_refund("CW-1006")
    assert result["can_cancel"] is False
    assert result["total_refund_eur"] == 0.0


def test_in_progress_booking_cannot_be_cancelled():
    result = calculate_refund("CW-1008")
    assert result["can_cancel"] is False
    assert result["total_refund_eur"] == 0.0


def test_cancel_at_another_time():
    # "what if I cancel tomorrow?" CW-1002 starts 2026-06-11 18:00 -> from 06-11 09:00 only 9 h left
    result = calculate_refund("CW-1002", cancel_at="2026-06-11T09:00")
    assert result["refund_percent"] == 0
    assert result["total_refund_eur"] == 300.0


def test_cancel_after_start_is_not_possible():
    # CW-1003 starts 2026-06-10 15:00; on 06-11 it has already started
    result = calculate_refund("CW-1003", cancel_at="2026-06-11T09:00")
    assert result["can_cancel"] is False


def test_refund_unknown_booking():
    result = calculate_refund("CW-9999")
    assert result["found"] is False


# ---------- get_booking ----------

def test_get_booking_found():
    result = get_booking("CW-1002")
    assert result["found"] is True
    assert result["booking"]["bike_type"] == "e-bike"


def test_get_booking_not_found():
    result = get_booking("CW-9999")
    assert result["found"] is False
    assert "not found" in result["message"]


def test_get_booking_normalizes_id():
    assert get_booking("cw-1002")["found"] is True
    assert get_booking(" CW 1002 ")["found"] is True
    assert get_booking("cw1002")["found"] is True
    assert get_booking("cw_1002")["found"] is True


# ---------- search_policies ----------

def test_search_opening_hours():
    results = search_policies("opening hours Saturday")["results"]
    assert results[0]["heading"] == "When are you open?"


def test_search_prices():
    results = search_policies("e-bike price per day")["results"]
    assert results[0]["source"] == "prices.md"
    assert "40 EUR" in results[0]["text"]


def test_search_age_limits():
    results = search_policies("age limit e-bike")["results"]
    assert results[0]["heading"] == "Are there age limits?"


def test_search_unrelated_question_finds_nothing():
    result = search_policies("capital of Australia")
    assert result["results"] == []
    assert "No relevant" in result["message"]
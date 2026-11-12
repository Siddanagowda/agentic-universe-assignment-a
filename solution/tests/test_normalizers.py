import pytest
from src.normalizers import (
    normalize_phone,
    parse_date,
    parse_decimal,
    parse_timestamp,
    ist_date,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("(+91) 98765-43210", "+919876543210"),
    ],
)
def test_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["1234567890", "5876543210", "123", ""])
def test_bad_phone(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


@pytest.mark.parametrize(
    "raw", ["2026-12-01", "01/12/2026", "01-12-2026", "01-Dec-2026"]
)
def test_dates(raw):
    assert parse_date(raw) == "2026-12-01"


def test_impossible_date():
    with pytest.raises(ValueError):
        parse_date("31/02/2026")


@pytest.mark.parametrize(
    "raw,expected",
    [("₹12,345", "12345.00"), ("Rs. 100.5", "100.50"), ("INR 1,000.999", "1001.00")],
)
def test_decimal(raw, expected):
    assert parse_decimal(raw) == expected


def test_negative_decimal():
    with pytest.raises(ValueError):
        parse_decimal("-1")


def test_naive_timestamp_means_ist():
    ts = parse_timestamp("2026-10-03 10:01:00")
    assert ist_date(ts) == "2026-10-03"

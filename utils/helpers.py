import re
from datetime import datetime


def is_valid_address(address):
    return bool(re.match(r"^0x[a-fA-F0-9]{40}$", address))


def format_usd(value):
    if value >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value/1_000:.2f}K"
    return f"${value:.2f}"


def format_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_str


def risk_color(risk):
    colors = {"low": "green", "medium": "yellow", "high": "red"}
    return colors.get(risk, "white")


def truncate(s, max_len=10):
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

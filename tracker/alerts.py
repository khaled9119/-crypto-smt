import json
import os
import requests
from datetime import datetime

from config import ALERTS


def send_telegram(message):
    token = ALERTS.get("telegram_bot_token", "")
    chat_id = ALERTS.get("telegram_chat_id", "")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=5)
    except Exception:
        pass


class AlertEngine:
    def __init__(self):
        self.history = []

    def fire(self, event_type, title, detail, data=None):
        entry = {
            "type": event_type,
            "title": title,
            "detail": detail,
            "data": data or {},
            "timestamp": datetime.now().isoformat(),
        }
        self.history.append(entry)
        msg = f"<b>[{event_type.upper()}]</b> {title}\n{detail}"
        send_telegram(msg)
        return entry

    def get_history(self, limit=20):
        return self.history[-limit:]

    def get_stats(self):
        counts = {}
        for h in self.history:
            t = h["type"]
            counts[t] = counts.get(t, 0) + 1
        return counts

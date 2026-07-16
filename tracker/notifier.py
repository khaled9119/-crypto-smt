import requests, json, os
from config import ALERTS

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.py")

def load_config():
    return ALERTS.get("telegram_bot_token", ""), ALERTS.get("telegram_chat_id", "")

def save_config(bot_token, chat_id):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    import re
    content = re.sub(
        r'("telegram_bot_token":\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{bot_token}"',
        content
    )
    content = re.sub(
        r'("telegram_chat_id":\s*)"[^"]*"',
        lambda m: f'{m.group(1)}"{chat_id}"',
        content
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def send(chain, symbol, value, usd_value, from_addr, to_addr, tx_hash, explorer_url=""):
    token, chat_id = load_config()
    if not token or not chat_id:
        return
    explorer_link = ""
    if chain == "Ethereum":
        explorer_link = f"https://etherscan.io/tx/{tx_hash}"
    elif chain == "BSC":
        explorer_link = f"https://bscscan.com/tx/{tx_hash}"
    elif chain == "Base":
        explorer_link = f"https://basescan.org/tx/{tx_hash}"
    msg = (
        f"\U0001F40B *Whale Alert!*\n"
        f"Chain: {chain}\n"
        f"Amount: {value:.4f} {symbol}\n"
        f"USD: ${usd_value:,.2f}\n"
        f"From: `{from_addr[:10]}...{from_addr[-4:]}`\n"
        f"To: `{to_addr[:10]}...{to_addr[-4:]}`\n"
        f"[View TX]({explorer_link})"
    )
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=8
        )
        return resp.json()
    except Exception:
        return None

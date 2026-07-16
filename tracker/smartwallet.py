import time
import requests
from datetime import datetime
from threading import Thread, Event

from tracker.blockchain import CHAINS, get_explorer_txns, get_token_txns
from database.db import Database
from config import SMART_WALLET_MIN_PROFIT, SMART_WALLET_MIN_TRADES, SMART_WALLET_WIN_RATE


class SmartWalletTracker:
    def __init__(self):
        self.db = Database()
        self.running = Event()
        self.preset_wallets = [
            "0x2faf487a4414fe77e2327f0bf4ae2a264a776ad2",
            "0x7a58c0b8c2ad9c0b3b4c4f5f6a7b8c9d0e1f2a3b",
        ]

    def start(self):
        self.running.set()
        Thread(target=self._scan_loop, daemon=True).start()

    def stop(self):
        self.running.clear()

    def _scan_loop(self):
        while self.running.is_set():
            for chain_id in ["ethereum", "bsc"]:
                if CHAINS[chain_id]["api_key"]:
                    for wallet in self.preset_wallets:
                        self._analyze_wallet(wallet, chain_id)
            time.sleep(300)

    def _analyze_wallet(self, wallet, chain_id):
        cfg = CHAINS[chain_id]
        txns = get_token_txns(wallet, chain_id, cfg["api_key"], offset=100)
        if not txns:
            return
        self.process_wallet_trades(wallet, chain_id, txns)

    def process_wallet_trades(self, wallet, chain_id, txns):
        trades = []
        for tx in txns:
            try:
                if tx.get("to").lower() == wallet.lower():
                    trades.append({
                        "hash": tx.get("hash"),
                        "token": tx.get("contractAddress"),
                        "token_symbol": tx.get("tokenSymbol"),
                        "token_name": tx.get("tokenName"),
                        "value": float(tx.get("value", 0)) / 10 ** int(tx.get("tokenDecimal", 18)),
                        "usd_value": float(tx.get("usdValue", 0) or 0),
                        "from": tx.get("from"),
                        "to": tx.get("to"),
                        "timestamp": datetime.fromtimestamp(int(tx.get("timeStamp", 0))).isoformat() if tx.get("timeStamp") else datetime.now().isoformat(),
                        "chain": CHAINS[chain_id]["name"],
                    })
            except Exception:
                continue

        if not trades:
            return

        profit = self._estimate_profit(trades)
        win_rate = self._estimate_win_rate(trades)
        result = {
            "wallet": wallet,
            "chain": CHAINS[chain_id]["name"],
            "total_trades": len(trades),
            "estimated_profit_usd": round(profit, 2),
            "win_rate": round(win_rate, 2),
            "last_active": trades[0]["timestamp"] if trades else datetime.now().isoformat(),
            "tokens_traded": list(set(t["token_symbol"] for t in trades if t["token_symbol"])),
            "timestamp": datetime.now().isoformat(),
        }
        self.db.save_smart_wallet(result)

    def _estimate_profit(self, trades):
        buys = [t for t in trades if t.get("from", "").lower() != t.get("to", "").lower()]
        sells = [t for t in trades if t.get("from", "").lower() == t.get("to", "").lower()]
        total_buy = sum(t.get("usd_value", 0) for t in buys)
        total_sell = sum(t.get("usd_value", 0) for t in sells)
        return total_sell - total_buy

    def _estimate_win_rate(self, trades):
        winning = [t for t in trades if t.get("usd_value", 0) > 0]
        if not trades:
            return 0
        return len(winning) / len(trades)

    def add_wallet(self, address):
        if address not in self.preset_wallets:
            self.preset_wallets.append(address.lower())
            return True
        return False

    def remove_wallet(self, address):
        if address in self.preset_wallets:
            self.preset_wallets.remove(address)
            return True
        return False

    def get_tracked_wallets(self):
        return self.preset_wallets

    def get_smart_wallets(self, min_win_rate=0.6):
        return self.db.get_smart_wallets(min_win_rate)

    def find_potential_smart_wallets(self, chain_id="ethereum", min_trades=20):
        cfg = CHAINS[chain_id]
        if not cfg["api_key"]:
            return []
        wallets = {}
        try:
            from tracker.blockchain import get_token_txns
            sample_tokens = [
                "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            ]
            for token in sample_tokens:
                for page in range(1, 4):
                    txns = get_token_txns(token, chain_id, cfg["api_key"], page=page, offset=100)
                    for tx in txns:
                        addr = tx.get("from", "").lower()
                        if addr not in wallets:
                            wallets[addr] = {"count": 0, "txns": []}
                        wallets[addr]["count"] += 1
                        wallets[addr]["txns"].append(tx)
        except Exception:
            pass
        candidates = []
        for addr, data in wallets.items():
            if data["count"] >= min_trades:
                self._analyze_wallet(addr, chain_id)
                candidates.append(addr)
        return candidates

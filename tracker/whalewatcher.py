import time
from datetime import datetime
from threading import Thread, Event
from colorama import Fore, Style

from tracker.blockchain import Web3Client, explore_tx, get_usd_price, CHAINS
from database.db import Database
from config import WHALE_THRESHOLD_USD, REFRESH_INTERVAL


class WhaleWatcher:
    def __init__(self):
        self.client = Web3Client()
        self.db = Database()
        self.running = Event()
        self.last_blocks = {}
        self.whale_txns = []

    def start(self):
        self.running.set()
        eth_price = get_usd_price("ethereum")
        Thread(target=self._monitor_chain, args=("ethereum", eth_price), daemon=True).start()
        bnb_price = get_usd_price("binancecoin")
        Thread(target=self._monitor_chain, args=("bsc", bnb_price), daemon=True).start()
        Thread(target=self._monitor_chain, args=("base", eth_price), daemon=True).start()

    def stop(self):
        self.running.clear()

    def _monitor_chain(self, chain_id, native_usd):
        w3 = self.client.get_w3(chain_id)
        if not w3:
            return
        self.last_blocks[chain_id] = w3.eth.block_number
        while self.running.is_set():
            try:
                current = w3.eth.block_number
                for block_num in range(self.last_blocks[chain_id] + 1, current + 1):
                    txns = self.client.get_block_transactions(chain_id, block_num)
                    for tx in txns:
                        self._analyze_tx(tx, chain_id, native_usd)
                self.last_blocks[chain_id] = max(self.last_blocks[chain_id], current)
            except Exception:
                pass
            time.sleep(REFRESH_INTERVAL)

    def _analyze_tx(self, tx, chain_id, native_usd):
        try:
            tx_data = explore_tx(tx, chain_id, self.client.get_w3(chain_id))
            if not tx_data or not tx_data.get("to"):
                return
            usd_value = tx_data["value"] * native_usd
            if usd_value >= WHALE_THRESHOLD_USD:
                tx_data["usd_value"] = round(usd_value, 2)
                symbol = CHAINS[chain_id]["symbol"]
                status = f"{Fore.YELLOW}WHALE{Style.RESET_ALL}"
                print(
                    f"  {status} {tx_data['chain']} | "
                    f"{tx_data['value']} {symbol} (${tx_data['usd_value']:,}) | "
                    f"{tx_data['from'][:8]}... -> {tx_data['to'][:8]}..."
                )
                self.whale_txns.append(tx_data)
                self.db.save_whale_tx({
                    "hash": tx_data["hash"],
                    "chain": tx_data["chain"],
                    "from_addr": tx_data["from"],
                    "to_addr": tx_data["to"],
                    "value": tx_data["value"],
                    "usd_value": tx_data["usd_value"],
                    "symbol": symbol,
                    "timestamp": datetime.now().isoformat(),
                })
        except Exception:
            pass

    def get_history(self, limit=20):
        return self.db.get_whale_txns(limit)

    def get_stats(self):
        txns = self.db.get_whale_txns(1000)
        total = len(txns)
        total_usd = sum(t.get("usd_value", 0) or 0 for t in txns)
        chains = {}
        for t in txns:
            c = t.get("chain", "unknown")
            chains[c] = chains.get(c, 0) + 1
        return {"total": total, "total_usd": round(total_usd, 2), "chains": chains}

import sqlite3
import os
import json
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "crypto_tracker.db")


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS whale_txns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE,
                chain TEXT,
                from_addr TEXT,
                to_addr TEXT,
                value REAL,
                usd_value REAL,
                symbol TEXT,
                timestamp TEXT
            );
            CREATE TABLE IF NOT EXISTS token_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_key TEXT UNIQUE,
                address TEXT,
                chain_id TEXT,
                name TEXT,
                symbol TEXT,
                risk TEXT,
                score INTEGER,
                details TEXT,
                timestamp TEXT
            );
            CREATE TABLE IF NOT EXISTS smart_wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet TEXT,
                chain TEXT,
                total_trades INTEGER,
                estimated_profit_usd REAL,
                win_rate REAL,
                last_active TEXT,
                tokens_traded TEXT,
                timestamp TEXT
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                title TEXT,
                detail TEXT,
                data TEXT,
                timestamp TEXT
            );
        """)
        conn.commit()
        conn.close()

    def save_whale_tx(self, data):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO whale_txns (hash, chain, from_addr, to_addr, value, usd_value, symbol, timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (data["hash"], data["chain"], data["from_addr"], data["to_addr"], data["value"], data["usd_value"], data["symbol"], data["timestamp"])
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def get_whale_txns(self, limit=20):
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM whale_txns ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def save_token_analysis(self, token_key, data):
        conn = self._get_conn()
        details = {k: v for k, v in data.items() if k not in ("address", "chain_id", "name", "symbol", "risk", "score", "timestamp")}
        try:
            conn.execute(
                "INSERT OR REPLACE INTO token_analysis (token_key, address, chain_id, name, symbol, risk, score, details, timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
                (token_key, data.get("address", ""), data.get("chain_id", ""), data.get("name", ""), data.get("symbol", ""), data.get("risk", ""), data.get("score", 0), json.dumps(details), data.get("timestamp", datetime.now().isoformat()))
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def get_token_analysis(self, token_key):
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM token_analysis WHERE token_key = ?", (token_key,)).fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["details"] = json.loads(d.get("details", "{}"))
            return d
        return None

    def save_smart_wallet(self, data):
        conn = self._get_conn()
        tokens_str = ",".join(data.get("tokens_traded", []))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO smart_wallets (wallet, chain, total_trades, estimated_profit_usd, win_rate, last_active, tokens_traded, timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (data["wallet"], data["chain"], data["total_trades"], data["estimated_profit_usd"], data["win_rate"], data["last_active"], tokens_str, data["timestamp"])
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def get_smart_wallets(self, min_win_rate=0.0):
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM smart_wallets WHERE win_rate >= ? ORDER BY estimated_profit_usd DESC LIMIT 50",
            (min_win_rate,)
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            d["tokens_traded"] = d.get("tokens_traded", "").split(",") if d.get("tokens_traded") else []
            results.append(d)
        return results

    def save_alert(self, alert_type, title, detail, data=None):
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO alerts (type, title, detail, data, timestamp) VALUES (?,?,?,?,?)",
                (alert_type, title, detail, json.dumps(data or {}), datetime.now().isoformat())
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    def get_alerts(self, limit=20):
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

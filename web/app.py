import sys, os, json, time, threading
from datetime import datetime, timedelta
from collections import deque
from flask import Flask, render_template, jsonify, request, Response
try:
    from waitress import serve as wsgi_serve
    HAS_WAITRESS = True
except ImportError:
    HAS_WAITRESS = False
    wsgi_serve = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tracker.blockchain import Web3Client, get_usd_price, CHAINS
from tracker.tokenanalyzer import TokenAnalyzer
from tracker.whalewatcher import WhaleWatcher
from tracker.smartwallet import SmartWalletTracker
from tracker.notifier import load_config as load_tg_config, save_config as save_tg_config, send as test_tg
from database.db import Database
from utils.helpers import is_valid_address, format_usd
from config import ALERTS, ETHERSCAN_API_KEY, BSCSCAN_API_KEY

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(16).hex()

client = Web3Client()
token_analyzer = TokenAnalyzer()
whale_watcher = WhaleWatcher()
smart_wallet = SmartWalletTracker()
db = Database()

whale_watcher.start()
smart_wallet.start()

price_history = {"ethereum": deque(maxlen=120), "binancecoin": deque(maxlen=120)}
whale_volume_history = deque(maxlen=120)
whale_count_history = deque(maxlen=120)

def _record_snapshot():
    while True:
        time.sleep(30)
        try:
            for coin in ["ethereum", "binancecoin"]:
                p = get_usd_price(coin)
                if p: price_history[coin].append(p)
            stats = whale_watcher.get_stats()
            whales = whale_watcher.get_history(10)
            recent_vol = sum(w.get("usd_value", 0) or 0 for w in whales)
            whale_volume_history.append(recent_vol)
            whale_count_history.append(len(whales))
        except: pass

threading.Thread(target=_record_snapshot, daemon=True).start()

def get_chain_status():
    return {c: client.is_connected(c) for c in ["ethereum", "bsc", "base"]}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    chains = get_chain_status()
    prices = {}
    for coin in ["ethereum", "binancecoin"]:
        p = get_usd_price(coin)
        if p: prices[coin] = p
    stats = whale_watcher.get_stats()
    wallets = smart_wallet.get_smart_wallets(0.0)
    vol_list = list(whale_volume_history)
    count_list = list(whale_count_history)
    price_eth = list(price_history["ethereum"])
    price_bnb = list(price_history["binancecoin"])
    return jsonify({
        "chains": chains,
        "prices": prices,
        "whales": stats["total"],
        "volume": stats["total_usd"],
        "wallets": len(wallets),
        "chains_breakdown": stats.get("chains", {}),
        "chart": {
            "volume": vol_list[-60:] if vol_list else [],
            "counts": count_list[-60:] if count_list else [],
            "price_eth": price_eth[-60:] if price_eth else [],
            "price_bnb": price_bnb[-60:] if price_bnb else [],
        },
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "api_keys": {
            "etherscan": bool(ETHERSCAN_API_KEY),
            "bscscan": bool(BSCSCAN_API_KEY),
        },
    })

@app.route("/api/whales")
def api_whales():
    limit = request.args.get("limit", 50, type=int)
    whales = whale_watcher.get_history(limit)
    return jsonify([dict(w) for w in whales])

@app.route("/api/events")
def api_events():
    def stream():
        last_count = 0
        while True:
            stats = whale_watcher.get_stats()
            if stats["total"] > last_count:
                whales = whale_watcher.get_history(3)
                for w in whales:
                    yield f"data: {json.dumps({'type':'whale', 'data': w})}\n\n"
                last_count = stats["total"]
            yield f"data: {json.dumps({'type':'ping'})}\n\n"
            time.sleep(3)
    return Response(stream(), mimetype="text/event-stream")

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data = request.get_json()
    addr = data.get("address", "").strip()
    chain = data.get("chain", "ethereum")
    if not addr or not is_valid_address(addr):
        return jsonify({"error": "Invalid address format"}), 400
    try:
        result = token_analyzer.analyze_token(addr, chain)
        if not result: return jsonify({"error": "Analysis returned no data"}), 500
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/wallets")
def api_wallets():
    wallets = smart_wallet.get_smart_wallets(0.0)
    return jsonify([dict(w) for w in wallets])

@app.route("/api/wallet/track", methods=["POST"])
def api_track_wallet():
    data = request.get_json()
    addr = data.get("address", "").strip()
    if not addr or not is_valid_address(addr):
        return jsonify({"error": "Invalid address"}), 400
    smart_wallet.add_wallet(addr)
    threading.Thread(target=_fetch_wallet_data, args=(addr,), daemon=True).start()
    return jsonify({"status": "ok", "message": "Wallet added, syncing data..."})

def _fetch_wallet_data(addr):
    from tracker.blockchain import get_token_txns, get_explorer_txns, get_usd_price as gup
    for chain_id in ["ethereum", "bsc"]:
        cfg = CHAINS[chain_id]
        txns = get_token_txns(addr, chain_id, cfg["api_key"], offset=100)
        if txns:
            smart_wallet.process_wallet_trades(addr, chain_id, txns)
        native = get_explorer_txns(addr, chain_id, cfg["api_key"], offset=50)
        if native and not txns:
            price = gup(chain_id)
            total_out = sum(float(t.get("value", 0)) / 1e18 for t in native if t.get("from","").lower() == addr.lower())
            total_in = sum(float(t.get("value", 0)) / 1e18 for t in native if t.get("to","").lower() == addr.lower())
            if total_out or total_in:
                dummy = [{
                    "hash": n.get("hash",""),
                    "contractAddress": "",
                    "tokenSymbol": cfg["symbol"],
                    "tokenName": cfg["name"],
                    "value": str(int(n.get("value", 0))),
                    "tokenDecimal": str(cfg["decimals"]),
                    "usdValue": str(float(n.get("value", 0)) / 1e18 * price),
                    "from": n.get("from",""),
                    "to": n.get("to",""),
                    "timeStamp": n.get("timeStamp", str(int(time.time()))),
                } for n in native if float(n.get("value", 0)) > 0]
                if dummy:
                    smart_wallet.process_wallet_trades(addr, chain_id, dummy)

@app.route("/api/whales/clear", methods=["POST"])
def api_clear_whales():
    conn = db._get_conn()
    conn.execute("DELETE FROM whale_txns")
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/tokens/recent")
def api_recent_tokens():
    conn = db._get_conn()
    rows = conn.execute("SELECT * FROM token_analysis ORDER BY id DESC LIMIT 30").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/export/whales")
def api_export_whales():
    whales = whale_watcher.get_history(500)
    import csv, io
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Time", "Chain", "From", "To", "Amount", "Symbol", "USD Value", "Tx Hash"])
    for w in whales:
        cw.writerow([w.get("timestamp",""), w.get("chain",""), w.get("from_addr",""), w.get("to_addr",""),
                     w.get("value",0), w.get("symbol",""), w.get("usd_value",0), w.get("hash","")])
    return Response(si.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=whales.csv"})

@app.route("/api/export/wallets")
def api_export_wallets():
    wallets = smart_wallet.get_smart_wallets(0.0)
    import csv, io
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Wallet", "Chain", "Trades", "Profit USD", "Win Rate", "Tokens", "Last Active"])
    for w in wallets:
        cw.writerow([w.get("wallet",""), w.get("chain",""), w.get("total_trades",0),
                     w.get("estimated_profit_usd",0), w.get("win_rate",0),
                     ",".join(w.get("tokens_traded",[])), w.get("last_active","")])
    return Response(si.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=smart_wallets.csv"})

# ===== TELEGRAM NOTIFICATIONS =====

@ app.route("/api/telegram/config")
def api_tg_config():
    token, chat_id = load_tg_config()
    return jsonify({"bot_token": token, "chat_id": chat_id, "enabled": bool(token and chat_id)})

@ app.route("/api/telegram/config", methods=["POST"])
def api_tg_save():
    data = request.get_json()
    token = data.get("bot_token", "").strip()
    chat_id = data.get("chat_id", "").strip()
    save_tg_config(token, chat_id)
    return jsonify({"status": "ok", "enabled": bool(token and chat_id)})

@ app.route("/api/telegram/test", methods=["POST"])
def api_tg_test():
    token, chat_id = load_tg_config()
    if not token or not chat_id:
        result = test_tg("Test", "TEST", 1, 1, "0x0000000000000000000000000000000000000000", "0x0000000000000000000000000000000000000000", "0x0000000000000000000000000000000000000000")
        return jsonify({"status": "error", "message": "Telegram not configured"}), 400
    try:
        import requests as r
        resp = r.post(f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": "✅ *Crypto Tracker*\nTest notification works!\nChain: Ethereum\nValue: 100 ETH\nUSD: $192,000", "parse_mode": "Markdown"}, timeout=8)
        if resp.status_code == 200:
            return jsonify({"status": "ok", "message": "Test sent successfully!"})
        return jsonify({"status": "error", "message": resp.json().get("description", "Failed")}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ===== ENHANCED TOKEN ANALYSIS =====

@ app.route("/api/token/advanced", methods=["POST"])
def api_token_advanced():
    data = request.get_json()
    addr = data.get("address", "").strip()
    chain = data.get("chain", "ethereum")
    if not addr or not is_valid_address(addr):
        return jsonify({"error": "Invalid address"}), 400
    try:
        w3 = client.get_w3(chain)
        if not w3:
            return jsonify({"error": "Chain not connected"}), 503
        checksum = w3.to_checksum_address(addr)
        token = w3.eth.contract(address=checksum, abi=[
            {"constant": True, "inputs": [], "name": "name", "outputs": [{"name":"","type":"string"}], "type":"function"},
            {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name":"","type":"string"}], "type":"function"},
            {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name":"","type":"uint8"}], "type":"function"},
            {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name":"","type":"uint256"}], "type":"function"},
        ])
        name = token.functions.name().call()[:40]
        symbol = token.functions.symbol().call()[:20]
        decimals = token.functions.decimals().call()
        total_supply = token.functions.totalSupply().call() / 10 ** decimals
        chain_name = {"ethereum": "Ethereum", "bsc": "BSC", "base": "Base"}.get(chain, chain)

        # Get recent transfers (last 20)
        from_block = max(0, w3.eth.block_number - 50000)
        transfer_sig = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        logs = []
        try:
            logs = w3.eth.get_logs({"address": checksum, "fromBlock": from_block, "topics": [transfer_sig]}, timeout=10)[:20]
        except Exception:
            pass

        recent_txns = []
        for log in logs:
            from_h = "0x" + log["topics"][1].hex()[-40:]
            to_h = "0x" + log["topics"][2].hex()[-40:]
            val = int.from_bytes(log["data"], "big") / 10 ** decimals if log["data"] else 0
            recent_txns.append({
                "from": from_h, "to": to_h, "value": round(val, 4), "hash": log["transactionHash"].hex(),
                "block": log["blockNumber"]
            })

        # Price and liquidity
        price = 0
        liquidity = 0
        try:
            from tracker.blockchain import get_token_price
            price = get_token_price(addr, chain)
        except Exception:
            pass

        return jsonify({
            "name": name, "symbol": symbol, "decimals": decimals,
            "total_supply": total_supply, "chain": chain_name,
            "price_usd": price, "recent_txns": recent_txns[:10],
            "address": checksum
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===== GAS PRICES =====

GAS_CACHE = {}
GAS_CACHE_TIME = 0

@ app.route("/api/gas")
def api_gas():
    global GAS_CACHE, GAS_CACHE_TIME
    now = time.time()
    if now - GAS_CACHE_TIME < 15 and GAS_CACHE:
        return jsonify(GAS_CACHE)
    result = {}
    for chain_id in ["ethereum", "bsc", "base"]:
        w3 = client.get_w3(chain_id)
        if not w3:
            result[chain_id] = None
            continue
        try:
            fee = w3.eth.fee_history(1, "latest")
            base_fee = fee.get("baseFeePerGas", [0])[0] if fee.get("baseFeePerGas") else 0
            # Get priority fees
            pending = w3.eth.get_block("pending")
            tx_count = len(pending.get("transactions", []))
            result[chain_id] = {
                "base_fee_gwei": round(base_fee / 1e9, 2),
                "pending_tx": tx_count,
                "gas_price_gwei": round(w3.eth.gas_price / 1e9, 2),
            }
        except Exception:
            try:
                gp = w3.eth.gas_price
                result[chain_id] = {
                    "base_fee_gwei": round(gp / 1e9, 2),
                    "pending_tx": 0,
                    "gas_price_gwei": round(gp / 1e9, 2),
                }
            except Exception:
                result[chain_id] = None
    GAS_CACHE = result
    GAS_CACHE_TIME = now
    return jsonify(result)

# ===== BALANCE CHECKER =====

@ app.route("/api/balance", methods=["POST"])
def api_balance():
    data = request.get_json()
    addr = data.get("address", "").strip()
    if not addr or not is_valid_address(addr):
        return jsonify({"error": "Invalid address"}), 400
    result = {}
    for chain_id in ["ethereum", "bsc", "base"]:
        w3 = client.get_w3(chain_id)
        if not w3:
            result[chain_id] = None
            continue
        try:
            bal = w3.eth.get_balance(w3.to_checksum_address(addr))
            native = bal / 1e18
            price = get_usd_price(CHAINS[chain_id]["native_usd"])
            result[chain_id] = {
                "balance": round(native, 6),
                "usd": round(native * price, 2) if price else 0,
                "symbol": CHAINS[chain_id]["symbol"],
            }
        except Exception:
            try:
                bal = w3.eth.get_balance(addr)
                native = bal / 1e18
                price = get_usd_price(CHAINS[chain_id]["native_usd"])
                result[chain_id] = {
                    "balance": round(native, 6),
                    "usd": round(native * price, 2) if price else 0,
                    "symbol": CHAINS[chain_id]["symbol"],
                }
            except Exception:
                result[chain_id] = None
    return jsonify(result)


def main():
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    host = "0.0.0.0"
    port = 5000
    print(f"  {'='*52}")
    print(f"  [Crypto Smart Money Tracker Pro - Web UI]")
    print(f"  {'='*52}")
    print(f"  [OK] Server: http://localhost:{port}")
    print(f"  [OK] Monitoring: Ethereum | BSC | Base")
    print(f"  [OK] Server: waitress" if HAS_WAITRESS else f"  [OK] Server: flask (dev)")
    print(f"  {'='*52}")
    if HAS_WAITRESS:
        wsgi_serve(app, host=host, port=port, threads=8)
    else:
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

if __name__ == "__main__":
    main()

import time
import requests
from web3 import Web3
from concurrent.futures import ThreadPoolExecutor

from config import ETH_RPC, BSC_RPC, BASE_RPC, ETHERSCAN_API_KEY, BSCSCAN_API_KEY as _BSCSCAN

CHAINS = {
    "ethereum": {
        "rpc": ETH_RPC,
        "name": "Ethereum",
        "symbol": "ETH",
        "decimals": 18,
        "explorer": "https://api.etherscan.io/api",
        "api_key": ETHERSCAN_API_KEY,
        "native_usd": "ethereum",
        "chain_id": 1,
    },
    "bsc": {
        "rpc": BSC_RPC,
        "name": "BSC",
        "symbol": "BNB",
        "decimals": 18,
        "explorer": "https://api.bscscan.com/api" if _BSCSCAN else "https://api.etherscan.io/v2/api",
        "api_key": _BSCSCAN if _BSCSCAN else ETHERSCAN_API_KEY,
        "native_usd": "binancecoin",
        "chain_id": 56,
    },
    "base": {
        "rpc": BASE_RPC,
        "name": "Base",
        "symbol": "ETH",
        "decimals": 18,
        "explorer": "https://api.etherscan.io/v2/api" if ETHERSCAN_API_KEY else None,
        "api_key": ETHERSCAN_API_KEY if ETHERSCAN_API_KEY else None,
        "native_usd": "ethereum",
        "chain_id": 8453,
    },
}

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]

_price_cache = {"usd": {}, "timestamp": 0}
COINGECKO_API = "https://api.coingecko.com/api/v3"


class Web3Client:
    def __init__(self):
        self.connections = {}
        self._init_connections()

    def _init_connections(self):
        for chain_id, cfg in CHAINS.items():
            try:
                w3 = Web3(Web3.HTTPProvider(cfg["rpc"], request_kwargs={"timeout": 10}))
                if w3.is_connected():
                    self.connections[chain_id] = w3
            except Exception:
                pass

    def get_w3(self, chain_id):
        return self.connections.get(chain_id)

    def is_connected(self, chain_id):
        w3 = self.get_w3(chain_id)
        return w3 is not None and w3.is_connected()

    def get_latest_block(self, chain_id):
        w3 = self.get_w3(chain_id)
        if not w3:
            return None
        return w3.eth.block_number

    def get_block_transactions(self, chain_id, block_number):
        w3 = self.get_w3(chain_id)
        if not w3:
            return []
        block = w3.eth.get_block(block_number, full_transactions=True)
        return block.get("transactions", [])

    def get_balance(self, chain_id, address):
        w3 = self.get_w3(chain_id)
        if not w3 or not Web3.is_address(address):
            return 0
        try:
            checksum = Web3.to_checksum_address(address)
            bal = w3.eth.get_balance(checksum)
            return bal / 10 ** CHAINS[chain_id]["decimals"]
        except Exception:
            return 0

    def get_token_balance(self, chain_id, token_address, wallet_address):
        w3 = self.get_w3(chain_id)
        if not w3:
            return 0
        try:
            token = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
            decimals = token.functions.decimals().call()
            bal = token.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
            return bal / 10 ** decimals
        except Exception:
            return 0

    def is_contract(self, chain_id, address):
        w3 = self.get_w3(chain_id)
        if not w3:
            return False
        try:
            code = w3.eth.get_code(Web3.to_checksum_address(address))
            return code != b""
        except Exception:
            return False


def explore_tx(tx, chain_id, w3):
    cfg = CHAINS[chain_id]
    value_eth = tx.get("value", 0)
    if isinstance(value_eth, int):
        value_eth = value_eth / 1e18
    else:
        value_eth = 0
    gas_price = tx.get("gasPrice", 0)
    gas = tx.get("gas", 0)
    tx_hash = tx.get("hash", b"").hex() if isinstance(tx.get("hash"), bytes) else str(tx.get("hash", ""))
    return {
        "hash": tx_hash,
        "from": tx.get("from", ""),
        "to": tx.get("to", ""),
        "value": round(value_eth, 6),
        "gas_price_gwei": round(gas_price / 1e9, 2) if gas_price else 0,
        "gas": gas,
        "input": tx.get("input", ""),
        "chain": cfg["name"],
        "chain_id": chain_id,
    }


def get_usd_price(coin_id):
    now = time.time()
    if now - _price_cache["timestamp"] < 60 and coin_id in _price_cache["usd"]:
        return _price_cache["usd"][coin_id]
    try:
        resp = requests.get(f"{COINGECKO_API}/simple/price?ids={coin_id}&vs_currencies=usd", timeout=5)
        if resp.status_code == 200:
            price = resp.json().get(coin_id, {}).get("usd", 0)
            _price_cache["usd"][coin_id] = price
            _price_cache["timestamp"] = now
            return price
    except Exception:
        pass
    return _price_cache["usd"].get(coin_id, 0)


def get_token_price(token_address, chain_id):
    chain_map = {"ethereum": "etherscan", "bsc": "bsc"}
    platform = chain_map.get(chain_id)
    if not platform:
        return 0
    try:
        url = f"{COINGECKO_API}/coins/{platform}/contract/{token_address}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("market_data", {}).get("current_price", {}).get("usd", 0)
    except Exception:
        pass
    return 0


def _explorer_params(cfg, api_key, extra=None):
    p = {"apikey": api_key}
    if cfg.get("explorer", "") and "/v2/" in cfg["explorer"]:
        p["chainid"] = cfg.get("chain_id", 1)
    if extra:
        p.update(extra)
    return p

def _explorer_get(url, params, fallback_func, address, chain_id, offset=50):
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1":
            return data.get("result", [])
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return fallback_func(address, chain_id, offset)

def get_explorer_txns(address, chain_id, api_key, page=1, offset=50):
    cfg = CHAINS[chain_id]
    if not api_key or not cfg["explorer"]:
        return _rpc_native_txns(address, chain_id, offset)
    url = cfg["explorer"]
    params = _explorer_params(cfg, api_key, {
        "module": "account", "action": "txlist",
        "address": address, "startblock": 0, "endblock": 99999999,
        "page": page, "offset": offset, "sort": "desc",
    })
    return _explorer_get(url, params, _rpc_native_txns, address, chain_id, offset)

def get_token_txns(address, chain_id, api_key, page=1, offset=50):
    cfg = CHAINS[chain_id]
    if not api_key or not cfg["explorer"]:
        return _rpc_token_txns(address, chain_id, offset)
    url = cfg["explorer"]
    params = _explorer_params(cfg, api_key, {
        "module": "account", "action": "tokentx",
        "address": address, "startblock": 0, "endblock": 99999999,
        "page": page, "offset": offset, "sort": "desc",
    })
    return _explorer_get(url, params, _rpc_token_txns, address, chain_id, offset)


def _rpc_native_txns(address, chain_id, limit=50):
    """Fallback: scan recent blocks via RPC for native coin txns involving address"""
    w3 = Web3Client().get_w3(chain_id)
    if not w3:
        return []
    addr = address.lower()
    results = []
    try:
        latest = w3.eth.block_number
        start = max(0, latest - 2000)
        for bn in range(latest, start, -1):
            if len(results) >= limit:
                break
            try:
                block = w3.eth.get_block(bn, full_transactions=True)
                for tx in block.get("transactions", []):
                    tx_from = tx.get("from", "").lower() if tx.get("from") else ""
                    tx_to = tx.get("to", "").lower() if tx.get("to") else ""
                    if tx_from == addr or tx_to == addr:
                        val = tx.get("value", 0)
                        if isinstance(val, int) and val > 0:
                            results.append({
                                "hash": tx.get("hash", b"").hex() if isinstance(tx.get("hash"), bytes) else str(tx.get("hash", "")),
                                "contractAddress": "",
                                "tokenSymbol": CHAINS[chain_id]["symbol"],
                                "tokenName": CHAINS[chain_id]["name"],
                                "value": str(val),
                                "tokenDecimal": str(CHAINS[chain_id]["decimals"]),
                                "from": tx.get("from", ""),
                                "to": tx.get("to", ""),
                                "timeStamp": str(block.get("timestamp", 0)),
                            })
            except Exception:
                continue
    except Exception:
        pass
    return results


def _rpc_token_txns(address, chain_id, limit=50):
    """Fallback: scan ERC-20 Transfer events via RPC for token txns involving address"""
    _client = Web3Client()
    w3 = _client.get_w3(chain_id)
    if not w3:
        return []
    transfer_sig = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    results = []
    try:
        latest = w3.eth.block_number
        start = max(0, latest - 5000)
        try:
            logs = w3.eth.get_logs({
                "fromBlock": start,
                "address": None,
                "topics": [transfer_sig, None, None],
            }, timeout=15)
        except Exception:
            logs = []
        for log in logs:
            if len(results) >= limit:
                break
            topic_from = "0x" + log["topics"][1].hex()[-40:]
            topic_to = "0x" + log["topics"][2].hex()[-40:]
            if topic_from.lower() != address.lower() and topic_to.lower() != address.lower():
                continue
            val = int.from_bytes(log["data"], "big") if len(log["data"]) > 0 else 0
            token_addr = log["address"]
            try:
                token = w3.eth.contract(address=token_addr, abi=[
                    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name":"","type":"string"}], "type":"function"},
                    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name":"","type":"uint8"}], "type":"function"},
                ])
                t_symbol = token.functions.symbol().call()[:15]
                t_decimals = token.functions.decimals().call()
            except Exception:
                t_symbol = "TOKEN"
                t_decimals = 18
            results.append({
                "hash": log["transactionHash"].hex(),
                "contractAddress": token_addr,
                "tokenSymbol": t_symbol,
                "tokenName": t_symbol,
                "value": str(val),
                "tokenDecimal": str(t_decimals),
                "from": topic_from,
                "to": topic_to,
                "timeStamp": str(log.get("blockNumber", 0)),
            })
    except Exception:
        pass
    return results

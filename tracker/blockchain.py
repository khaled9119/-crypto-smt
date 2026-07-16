import time
import requests
from web3 import Web3
from concurrent.futures import ThreadPoolExecutor

from config import ETH_RPC, BSC_RPC, BASE_RPC, ETHERSCAN_API_KEY, BSCSCAN_API_KEY

CHAINS = {
    "ethereum": {
        "rpc": ETH_RPC,
        "name": "Ethereum",
        "symbol": "ETH",
        "decimals": 18,
        "explorer": "https://api.etherscan.io/api",
        "api_key": ETHERSCAN_API_KEY,
        "native_usd": "ethereum",
    },
    "bsc": {
        "rpc": BSC_RPC,
        "name": "BSC",
        "symbol": "BNB",
        "decimals": 18,
        "explorer": "https://api.bscscan.com/api",
        "api_key": BSCSCAN_API_KEY,
        "native_usd": "binancecoin",
    },
    "base": {
        "rpc": BASE_RPC,
        "name": "Base",
        "symbol": "ETH",
        "decimals": 18,
        "explorer": None,
        "api_key": None,
        "native_usd": "ethereum",
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


def get_explorer_txns(address, chain_id, api_key, page=1, offset=50):
    if not api_key:
        return []
    cfg = CHAINS[chain_id]
    url = f"{cfg['explorer']}"
    params = {
        "module": "account",
        "action": "txlist",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "page": page,
        "offset": offset,
        "sort": "desc",
        "apikey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1":
            return data.get("result", [])
    except Exception:
        pass
    return []


def get_token_txns(address, chain_id, api_key, page=1, offset=50):
    if not api_key:
        return []
    cfg = CHAINS[chain_id]
    url = f"{cfg['explorer']}"
    params = {
        "module": "account",
        "action": "tokentx",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "page": page,
        "offset": offset,
        "sort": "desc",
        "apikey": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "1":
            return data.get("result", [])
    except Exception:
        pass
    return []

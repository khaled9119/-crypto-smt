import time
import requests
from datetime import datetime

from tracker.blockchain import Web3Client, CHAINS, ERC20_ABI, get_token_price, get_explorer_txns
from database.db import Database
from config import RUG_CHECK


class TokenAnalyzer:
    def __init__(self):
        self.client = Web3Client()
        self.db = Database()
        self.checked_tokens = set()

    def analyze_token(self, token_address, chain_id="ethereum"):
        w3 = self.client.get_w3(chain_id)
        if not w3:
            return None
        try:
            checksum = w3.to_checksum_address(token_address)
        except Exception:
            return None
        token_key = f"{chain_id}:{checksum.lower()}"
        if token_key in self.checked_tokens:
            return self.db.get_token_analysis(token_key)
        self.checked_tokens.add(token_key)

        if not self.client.is_contract(chain_id, checksum):
            return {"risk": "high", "reason": "Not a contract address"}

        token = w3.eth.contract(address=checksum, abi=ERC20_ABI)
        try:
            name = token.functions.name().call()[:30]
            symbol = token.functions.symbol().call()[:15]
            decimals = token.functions.decimals().call()
            total_supply = token.functions.totalSupply().call() / 10 ** decimals
        except Exception:
            return {"risk": "high", "reason": "Cannot read basic token info"}

        result = {
            "address": checksum,
            "chain_id": chain_id,
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "total_supply": total_supply,
            "risk": "unknown",
            "issues": [],
            "score": 50,
        }
        cr = self._check_renounced(chain_id, checksum)
        result["ownership_renounced"] = cr
        if cr:
            result["score"] += 15
        else:
            result["issues"].append("Ownership not renounced")
            result["score"] -= 20

        liquidity = self._check_liquidity(chain_id, checksum)
        result["liquidity_usd"] = liquidity
        if liquidity < RUG_CHECK["min_liquidity_usd"]:
            result["issues"].append(f"Low liquidity (${liquidity:.0f})")
            result["score"] -= 25

        holders = self._get_holder_concentration(chain_id, checksum)
        result["top_holder_pct"] = holders
        if holders > RUG_CHECK["max_holder_concentration"]:
            result["issues"].append(f"Top holder has {holders:.1%} supply")
            result["score"] -= 30

        is_honeypot = self._check_honeypot(chain_id, checksum)
        result["honeypot"] = is_honeypot
        if is_honeypot:
            result["issues"].append("Potential honeypot (cannot sell)")
            result["score"] -= 40

        if result["score"] >= 70:
            result["risk"] = "low"
        elif result["score"] >= 40:
            result["risk"] = "medium"
        else:
            result["risk"] = "high"

        result["timestamp"] = datetime.now().isoformat()
        self.db.save_token_analysis(token_key, result)
        return result

    def _check_renounced(self, chain_id, address):
        w3 = self.client.get_w3(chain_id)
        if not w3:
            return False
        owner_sig = w3.keccak(text="owner()").hex()[:10]
        renounce_sig = w3.keccak(text="renounceOwnership()").hex()[:10]
        try:
            code = w3.eth.get_code(address).hex()
            if owner_sig[2:] in code:
                try:
                    contract = w3.eth.contract(address=address, abi=ERC20_ABI + [
                        {"constant": True, "inputs": [], "name": "owner", "outputs": [{"name": "", "type": "address"}], "type": "function"}
                    ])
                    owner = contract.functions.owner().call()
                    return owner == "0x0000000000000000000000000000000000000000"
                except Exception:
                    return False
            return True
        except Exception:
            return False

    def _check_liquidity(self, chain_id, address):
        dex_factories = {
            "ethereum": ["0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"],
            "bsc": ["0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"],
        }
        factories = dex_factories.get(chain_id, [])
        w3 = self.client.get_w3(chain_id)
        if not w3:
            return 0
        pair_abi = [{"constant": True, "inputs": [], "name": "getReserves", "outputs": [{"name": "_reserve0", "type": "uint112"}, {"name": "_reserve1", "type": "uint112"}], "type": "function"}]
        factory_abi = [{"constant": True, "inputs": [{"name": "", "type": "address"}, {"name": "", "type": "address"}], "name": "getPair", "outputs": [{"name": "", "type": "address"}], "type": "function"}]
        weth = {"ethereum": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "bsc": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"}
        weth_addr = weth.get(chain_id)
        if not weth_addr:
            return 0
        for factory_addr in factories:
            try:
                factory = w3.eth.contract(address=w3.to_checksum_address(factory_addr), abi=factory_abi)
                pair = factory.functions.getPair(w3.to_checksum_address(address), w3.to_checksum_address(weth_addr)).call()
                if pair and pair != "0x0000000000000000000000000000000000000000":
                    pair_c = w3.eth.contract(address=pair, abi=pair_abi)
                    reserves = pair_c.functions.getReserves().call()
                    price = get_token_price(address, chain_id)
                    if price > 0:
                        return reserves[1] / 1e18 * price if chain_id == "ethereum" else reserves[0] / 1e18 * get_usd_price("binancecoin")
                    token_price = get_token_price(weth_addr, chain_id)
                    if token_price > 0:
                        return reserves[1] / 1e18 * token_price * 2 if chain_id == "ethereum" else reserves[0] / 1e18 * token_price * 2
            except Exception:
                continue
        return 0

    def _get_holder_concentration(self, chain_id, address):
        cfg = CHAINS[chain_id]
        if not cfg["api_key"]:
            return 0
        url = f"{cfg['explorer']}"
        params = {
            "module": "token",
            "action": "tokenholderlist",
            "contractaddress": address,
            "page": 1,
            "offset": 10,
            "apikey": cfg["api_key"],
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("status") == "1" and data.get("result"):
                holders = data["result"]
                total = sum(float(h.get("tokenHolderQuantity", 0)) for h in holders)
                if total > 0:
                    top = float(holders[0].get("tokenHolderQuantity", 0))
                    return top / total
        except Exception:
            pass
        return 0

    def _check_honeypot(self, chain_id, address):
        return False

    def scan_new_tokens(self, chain_id="ethereum", hours=24):
        cfg = CHAINS[chain_id]
        if not cfg["api_key"]:
            return []
        since = int(time.time()) - hours * 3600
        url = f"{cfg['explorer']}"
        params = {
            "module": "contract",
            "action": "getsourcecode",
            "address": "0x0000000000000000000000000000000000000000",
            "apikey": cfg["api_key"],
        }
        new_tokens = []
        try:
            resp = requests.get(f"https://api.coingecko.com/api/v3/coins/list?include_platform=true", timeout=10)
            if resp.status_code == 200:
                coins = resp.json()
                platform = {"ethereum": "ethereum", "bsc": "binance-smart-chain"}.get(chain_id, chain_id)
                chain_coins = [c for c in coins if platform in c.get("platforms", {})]
                for coin in chain_coins[:50]:
                    addr = coin["platforms"][platform]
                    if addr and self.client.is_contract(chain_id, addr):
                        new_tokens.append(addr)
        except Exception:
            pass
        return new_tokens[:50]


def get_usd_price(coin_id):
    from tracker.blockchain import get_usd_price as gup
    return gup(coin_id)

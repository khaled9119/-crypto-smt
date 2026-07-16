ETH_RPC = "https://eth.drpc.org"
BSC_RPC = "https://bsc-dataseed1.binance.org"
BASE_RPC = "https://mainnet.base.org"

ETHERSCAN_API_KEY = "IYZKU9UZJIMZDGQS4A47SJGGIN172JRR4I"
BSCSCAN_API_KEY = ""

WHALE_THRESHOLD_USD = 100000
TRACKED_CHAINS = ["ethereum", "bsc", "base"]
REFRESH_INTERVAL = 15
MAX_TX_HISTORY = 1000

RUG_CHECK = {
    "min_liquidity_usd": 5000,
    "max_holder_concentration": 0.5,
    "min_holders": 50,
    "honeypot_check": True,
}

ALERTS = {
    "sound": False,
    "desktop": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
}

SMART_WALLET_MIN_PROFIT = 50.0
SMART_WALLET_MIN_TRADES = 10
SMART_WALLET_WIN_RATE = 0.6

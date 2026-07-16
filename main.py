import sys
import time
import signal
from threading import Event
from datetime import datetime

from colorama import init, Fore, Style
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text

from config import WHALE_THRESHOLD_USD, REFRESH_INTERVAL
from tracker.whalewatcher import WhaleWatcher
from tracker.tokenanalyzer import TokenAnalyzer
from tracker.smartwallet import SmartWalletTracker
from tracker.alerts import AlertEngine
from database.db import Database
from utils.helpers import is_valid_address, format_usd, format_time, risk_color

init(autoreset=True)
console = Console()

running = Event()
running.set()

whale = WhaleWatcher()
token_analyzer = TokenAnalyzer()
smart_wallet = SmartWalletTracker()
alerts = AlertEngine()
db = Database()


def print_header():
    console.print(Panel.fit(
        "[bold cyan]🐋 Crypto Smart Money Tracker[/bold cyan]\n"
        "[dim]Ethereum | BSC | Base — Whale Watching · Token Analysis · Smart Wallet Tracking[/dim]",
        border_style="cyan"
    ))


def print_menu():
    menu = Table.grid(padding=(0, 2))
    menu.add_column(style="bold yellow", width=4)
    menu.add_column(style="white")
    menu.add_row("1.", "🐋  Start Whale Watcher (live monitoring)")
    menu.add_row("2.", "🔍  Analyze Token (check for rug pulls)")
    menu.add_row("3.", "👛  Smart Wallet Tracker")
    menu.add_row("4.", "📊  Dashboard / Reports")
    menu.add_row("5.", "⚙️   Settings")
    menu.add_row("6.", "👁️   Track Custom Wallet")
    menu.add_row("0.", "❌  Exit")
    console.print(Panel(menu, title="[bold]MENU[/bold]", border_style="blue"))
    console.print()


def start_whale_watcher():
    console.print(f"\n[bold yellow]🐋 Start Whale Watcher[/bold yellow]")
    console.print(f"  Threshold: ${WHALE_THRESHOLD_USD:,}")
    console.print(f"  Chains: Ethereum, BSC, Base\n")

    whale.start()
    smart_wallet.start()
    console.print("[green]✓ Monitoring started. Press Ctrl+C to stop.\n[/green]")

    try:
        while running.is_set():
            time.sleep(REFRESH_INTERVAL)
            stats = whale.get_stats()
            smart = smart_wallet.get_smart_wallets(0.5)
            console.print(
                f"  [dim]{datetime.now().strftime('%H:%M:%S')}[/dim] "
                f"Whales: [yellow]{stats['total']}[/yellow] | "
                f"Volume: [green]${stats['total_usd']:,.0f}[/green] | "
                f"Smart Wallets: [cyan]{len(smart)}[/cyan]"
            )
    except KeyboardInterrupt:
        pass
    finally:
        whale.stop()
        smart_wallet.stop()
        console.print("\n[dim]Monitoring stopped.[/dim]\n")


def analyze_token_menu():
    console.print(f"\n[bold yellow]🔍 Analyze Token[/bold yellow]")
    addr = input("  Token address: ").strip()
    if not addr or not is_valid_address(addr):
        console.print("[red]Invalid address[/red]")
        return

    console.print(f"\n  Chain: 1=Ethereum  2=BSC  3=Base")
    ch = input("  Choice (1-3): ").strip()
    chain_map = {"1": "ethereum", "2": "bsc", "3": "base"}
    chain = chain_map.get(ch, "ethereum")

    console.print(f"\n[dim]Analyzing {chain}...[/dim]\n")
    result = token_analyzer.analyze_token(addr, chain)
    if not result:
        console.print("[red]Analysis failed[/red]")
        return

    risk = result.get("risk", "unknown")
    score = result.get("score", 0)
    issues = result.get("issues", [])

    risk_display = {
        "low": f"[bold green]{risk.upper()}[/bold green]",
        "medium": f"[bold yellow]{risk.upper()}[/bold yellow]",
        "high": f"[bold red]{risk.upper()}[/bold red]",
    }.get(risk, f"[bold]{risk.upper()}[/bold]")

    table = Table(box=None)
    table.add_column("Property", style="cyan", width=18)
    table.add_column("Value", style="white")
    table.add_row("Token", f"{result.get('name', '?')} ({result.get('symbol', '?')})")
    table.add_row("Address", f"[dim]{result.get('address', '')[:20]}...[/dim]")
    table.add_row("Risk Level", risk_display)
    table.add_row("Safety Score", f"{score}/100")
    table.add_row("Ownership Renounced", f"{'✅ Yes' if result.get('ownership_renounced') else '❌ No'}")

    if result.get("liquidity_usd"):
        table.add_row("Liquidity", format_usd(result["liquidity_usd"]))

    if result.get("top_holder_pct"):
        table.add_row("Top Holder", f"{result['top_holder_pct']:.1%}")

    if result.get("honeypot"):
        table.add_row("Honeypot Check", "⚠️ Warning")

    console.print(table)

    if issues:
        console.print(f"\n[bold red]Issues Found:[/bold red]")
        for issue in issues:
            console.print(f"  • [red]{issue}[/red]")

    console.print()


def smart_wallet_menu():
    console.print(f"\n[bold yellow]👛 Smart Wallet Tracker[/bold yellow]")
    wallets = smart_wallet.get_tracked_wallets()
    console.print(f"\n[dim]Tracked wallets: {len(wallets)}[/dim]")

    result = smart_wallet.get_smart_wallets(0.5)
    if result:
        table = Table(title="Smart Wallets", box=None)
        table.add_column("Wallet", style="cyan", width=22)
        table.add_column("Chain", width=10)
        table.add_column("Trades", justify="right")
        table.add_column("Profit", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Tokens")
        for w in result:
            table.add_row(
                f"{w['wallet'][:10]}...{w['wallet'][-6:]}",
                w.get("chain", ""),
                str(w.get("total_trades", 0)),
                f"${w.get('estimated_profit_usd', 0):,.0f}",
                f"{w.get('win_rate', 0)*100:.0f}%",
                ", ".join(w.get("tokens_traded", [])[:3])
            )
        console.print(table)
    else:
        console.print("\n[yellow]No smart wallets found yet. Start the whale watcher first to collect data.[/yellow]")

    console.print()
    console.print("  a=Add wallet  r=Remove  s=Scan for new  b=Back")
    action = input("  Action: ").strip().lower()
    if action == "a":
        addr = input("  Wallet address: ").strip()
        if is_valid_address(addr):
            smart_wallet.add_wallet(addr)
            console.print("[green]✓ Added[/green]")
    elif action == "r":
        addr = input("  Wallet address: ").strip()
        if is_valid_address(addr):
            smart_wallet.remove_wallet(addr)
            console.print("[green]✓ Removed[/green]")
    elif action == "s":
        chain_id = "ethereum"
        ch = input("  Chain (1=eth, 2=bsc): ").strip()
        if ch == "2":
            chain_id = "bsc"
        console.print("[dim]Scanning for active wallets...[/dim]")
        candidates = smart_wallet.find_potential_smart_wallets(chain_id, min_trades=20)
        console.print(f"[green]Found {len(candidates)} potential smart wallets[/green]")


def dashboard():
    console.print(f"\n[bold yellow]📊 Dashboard[/bold yellow]\n")

    whale_stats = whale.get_stats()
    smart_wallets = smart_wallet.get_smart_wallets(0.0)
    alert_stats = alerts.get_stats()
    recent_alerts = alerts.get_history(5)
    recent_whales = whale.get_history(10)

    layout = Layout()
    layout.split_column(
        Layout(name="top", size=6),
        Layout(name="bottom"),
    )
    layout["top"].split_row(
        Layout(name="stats"),
        Layout(name="top_alerts"),
    )
    layout["bottom"].split_row(
        Layout(name="whales"),
        Layout(name="wallets"),
    )

    stats_table = Table(title="📈 Summary", box=None)
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="white")
    stats_table.add_row("Total Whale Txns", str(whale_stats["total"]))
    stats_table.add_row("Total Whale Volume", f"${whale_stats['total_usd']:,.0f}")
    stats_table.add_row("Smart Wallets Tracked", str(len(smart_wallets)))
    for chain, count in whale_stats.get("chains", {}).items():
        stats_table.add_row(f"  {chain} Txns", str(count))
    stats_table.add_row("Alerts Fired", str(alert_stats.get("whale", 0)))

    top_alerts_table = Table(title="🔔 Recent Alerts", box=None)
    top_alerts_table.add_column("Time", width=16)
    top_alerts_table.add_column("Event")
    for a in recent_alerts:
        top_alerts_table.add_row(
            format_time(a["timestamp"]),
            f"[yellow]{a['type']}[/yellow]: {a['title'][:30]}",
        )

    whale_table = Table(title="🐋 Recent Whale Transactions", box=None)
    whale_table.add_column("Time", width=16)
    whale_table.add_column("Chain", width=10)
    whale_table.add_column("Value", justify="right", width=14)
    whale_table.add_column("From", width=14)
    whale_table.add_column("To", width=14)
    for t in recent_whales:
        whale_table.add_row(
            format_time(t.get("timestamp", "")),
            t.get("chain", ""),
            f"{t.get('value', 0)} {t.get('symbol', '')}",
            f"{str(t.get('from_addr', ''))[:8]}...",
            f"{str(t.get('to_addr', ''))[:8]}...",
        )

    wallet_table = Table(title="👛 Smart Wallets", box=None)
    wallet_table.add_column("Wallet", width=18)
    wallet_table.add_column("Profit", justify="right")
    wallet_table.add_column("Win Rate", justify="right")
    wallet_table.add_column("Trades", justify="right")
    for w in smart_wallets[:8]:
        wallet_table.add_row(
            f"{w['wallet'][:8]}...",
            f"${w.get('estimated_profit_usd', 0):,.0f}",
            f"{w.get('win_rate', 0)*100:.0f}%",
            str(w.get("total_trades", 0)),
        )

    console.print(stats_table)
    console.print()
    console.print(top_alerts_table)
    console.print()
    console.print(whale_table)
    console.print()
    console.print(wallet_table)
    console.print()


def settings_menu():
    console.print(f"\n[bold yellow]⚙️  Settings[/bold yellow]\n")
    table = Table(box=None)
    table.add_column("Setting", style="cyan", width=30)
    table.add_column("Value")
    table.add_row("Whale Threshold", f"${WHALE_THRESHOLD_USD:,}")
    table.add_row("Refresh Interval", f"{REFRESH_INTERVAL}s")
    table.add_row("Tracked Chains", ", ".join(["Ethereum", "BSC", "Base"]))
    table.add_row("Min Liquidity (Rug Check)", f"${RUG_CHECK['min_liquidity_usd']:,}")
    table.add_row("Max Holder Conc. (Rug Check)", f"{RUG_CHECK['max_holder_concentration']:.0%}")
    console.print(table)

    console.print(f"\n[dim]Edit config.py to change settings[/dim]")
    console.print()


def track_custom_wallet():
    console.print(f"\n[bold yellow]👁️  Track Custom Wallet[/bold yellow]")
    addr = input("  Wallet address: ").strip()
    if not addr or not is_valid_address(addr):
        console.print("[red]Invalid address[/red]")
        return

    console.print(f"\n  Chain: 1=Ethereum  2=BSC")
    ch = input("  Choice (1-2): ").strip()
    chain_id = "ethereum" if ch != "2" else "bsc"

    cfg = {"ethereum": "etherscan", "bsc": "bsc"}
    helpers = {k: v for k, v in cfg.items()}

    wallet = SmartWalletTracker()
    wallet.add_wallet(addr)

    console.print(f"\n[dim]Fetching transactions for {addr[:10]}... on {chain_id}...[/dim]")
    txns = get_token_txns(addr, chain_id, CHAINS[chain_id]["api_key"], offset=100)
    if not txns:
        eth_txns = get_explorer_txns(addr, chain_id, CHAINS[chain_id]["api_key"], offset=100)
        if eth_txns:
            console.print(f"  [green]Found {len(eth_txns)} ETH transactions[/green]")
            total_in = sum(float(t.get("value", 0)) / 1e18 for t in eth_txns if t.get("to", "").lower() == addr.lower())
            total_out = sum(float(t.get("value", 0)) / 1e18 for t in eth_txns if t.get("from", "").lower() == addr.lower())
            native_price = get_usd_price(chain_id)
            balance = total_in - total_out
            table = Table(box=None)
            table.add_column("Metric", style="cyan", width=18)
            table.add_column("Value")
            table.add_row("Wallet", addr[:20] + "...")
            table.add_row("Chain", CHAINS[chain_id]["name"])
            table.add_row("Total TX", str(len(eth_txns)))
            table.add_row("Net Balance", f"{balance:.4f} {CHAINS[chain_id]['symbol']} (${balance * native_price:,.2f})")
            table.add_row("Total Received", f"{total_in:.4f} {CHAINS[chain_id]['symbol']}")
            table.add_row("Total Sent", f"{total_out:.4f} {CHAINS[chain_id]['symbol']}")
            console.print(table)
        else:
            console.print("[yellow]No transactions found or API key missing[/yellow]")
    else:
        console.print(f"  [green]Found {len(txns)} token transactions[/green]")
        wallet.process_wallet_trades(addr, chain_id, txns)
        smart_wallets = db.get_smart_wallets(0.0)
        w_data = [w for w in smart_wallets if w["wallet"].lower() == addr.lower()]
        if w_data:
            w = w_data[0]
            table = Table(box=None)
            table.add_column("Metric", style="cyan", width=18)
            table.add_column("Value")
            table.add_row("Wallet", addr[:20] + "...")
            table.add_row("Chain", w.get("chain", ""))
            table.add_row("Total Trades", str(w.get("total_trades", 0)))
            table.add_row("Est. Profit", f"${w.get('estimated_profit_usd', 0):,.2f}")
            table.add_row("Win Rate", f"{w.get('win_rate', 0)*100:.0f}%")
            table.add_row("Tokens", ", ".join(w.get("tokens_traded", [])[:5]))
            console.print(table)

    console.print()


from tracker.blockchain import get_token_txns, get_explorer_txns, get_usd_price, CHAINS


def main():
    signal.signal(signal.SIGINT, lambda s, f: running.clear())
    print_header()

    while running.is_set():
        print_menu()
        try:
            choice = input("  Choice: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == "1":
            start_whale_watcher()
        elif choice == "2":
            analyze_token_menu()
        elif choice == "3":
            smart_wallet_menu()
        elif choice == "4":
            dashboard()
        elif choice == "5":
            settings_menu()
        elif choice == "6":
            track_custom_wallet()
        elif choice == "0":
            break
        else:
            console.print("[red]Invalid choice[/red]")

    whale.stop()
    smart_wallet.stop()
    console.print("\n[bold cyan]👋 Goodbye![/bold cyan]\n")


if __name__ == "__main__":
    main()

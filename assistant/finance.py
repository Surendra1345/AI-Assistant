"""Live market data and calculator tools: calculate, stock_quote, market_movers, investment_scenario, news_search.
Prices come from Yahoo Finance's public chart endpoint (no key). Everything is data, not advice."""
import ast
import math
import operator
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .tools import tool

DISCLAIMER = "Data only, not financial advice: past moves don't guarantee future returns and you can lose money."

# ---------------------------------------------------------------- calculator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
          "sin": math.sin, "cos": math.cos, "tan": math.tan, "abs": abs, "round": round, "min": min, "max": max,
          "floor": math.floor, "ceil": math.ceil, "factorial": math.factorial}
_CONST = {"pi": math.pi, "e": math.e}


def _eval(n):
    if isinstance(n, ast.Expression):
        return _eval(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return n.value
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        a, b = _eval(n.left), _eval(n.right)
        if isinstance(n.op, ast.Pow) and (abs(b) > 1000 or abs(a) > 1e12):
            raise ValueError("That power is too large.")
        return _BIN[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
        return _UN[type(n.op)](_eval(n.operand))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
        args = [_eval(a) for a in n.args]
        if n.func.id == "factorial" and args and args[0] > 500:
            raise ValueError("Too large.")
        return _FUNCS[n.func.id](*args)
    raise ValueError("Unsupported expression.")


def safe_calc(expr: str):
    expr = expr.replace(",", "").replace("^", "**").replace("×", "*").replace("÷", "/")
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"(\1/100)*", expr, flags=re.I)   # "15% of 2000"
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expr)
    return _eval(ast.parse(expr.strip(), mode="eval"))


@tool("calculate", "Exact calculator. Pass a math expression such as '15% of 2400', '(1+0.08)**10 * 50000', 'sqrt(144)'. "
                   "Always use this for arithmetic instead of computing in your head.",
      {"expression": {"type": "string"}}, ["expression"])
def calculate(expression: str) -> str:
    try:
        v = safe_calc(expression)
    except ZeroDivisionError:
        return "Can't divide by zero."
    except (ValueError, SyntaxError, TypeError, OverflowError) as e:
        return f"ERROR: couldn't evaluate that ({e}). Rewrite it as a plain math expression."
    if isinstance(v, float):
        v = round(v, 6)
        if v == int(v) and abs(v) < 1e15:
            v = int(v)
    return f"{expression} = {v:,}" if isinstance(v, (int, float)) else f"{expression} = {v}"


# ---------------------------------------------------------------- market data

_HDR = {"User-Agent": "Mozilla/5.0 (personal-assistant)"}
US_WATCH = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "AMD", "NFLX", "JPM", "V", "WMT",
            "XOM", "LLY", "ORCL", "CRM", "INTC", "ADBE", "DIS", "BA", "PYPL", "UBER", "PLTR"]
INDIA_WATCH = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS",
               "LT.NS", "KOTAKBANK.NS", "AXISBANK.NS", "WIPRO.NS", "TATAMOTORS.NS", "ADANIENT.NS", "MARUTI.NS",
               "SUNPHARMA.NS", "HCLTECH.NS", "BAJFINANCE.NS", "TATASTEEL.NS", "ZOMATO.NS"]
_RANGES = {"1d": ("5d", "1d"), "1w": ("1mo", "1d"), "1m": ("1mo", "1d"), "3m": ("3mo", "1d"), "6m": ("6mo", "1d"),
           "1y": ("1y", "1d"), "5y": ("5y", "1wk")}


def _get_json(url: str, params: Optional[dict] = None) -> dict:
    import httpx
    r = httpx.get(url, params=params, headers=_HDR, timeout=15)
    r.raise_for_status()
    return r.json()


def _resolve(name: str) -> str:
    """'tesla' -> 'TSLA'. Tickers (AAPL, RELIANCE.NS) pass straight through."""
    name = name.strip()
    if re.fullmatch(r"[A-Z0-9.\-^=]{1,12}", name):
        return name
    quotes = _get_json("https://query1.finance.yahoo.com/v1/finance/search", {"q": name, "quotesCount": 5}).get("quotes", [])
    for q in quotes:
        if q.get("quoteType") in ("EQUITY", "ETF", "INDEX", "CRYPTOCURRENCY") and q.get("symbol"):
            return q["symbol"]
    raise ValueError(f"No stock found for '{name}'.")


def _history(symbol: str, rng: str = "3mo", interval: str = "1d") -> dict:
    j = _get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", {"range": rng, "interval": interval})
    res = (j.get("chart", {}).get("result") or [None])[0]
    if not res:
        raise ValueError(f"No market data for {symbol}.")
    closes = [c for c in res["indicators"]["quote"][0].get("close", []) if c is not None]
    if len(closes) < 2:
        raise ValueError(f"Not enough price history for {symbol}.")
    m = res.get("meta", {})
    return {"symbol": m.get("symbol", symbol), "name": m.get("shortName") or m.get("longName") or symbol,
            "currency": m.get("currency", ""), "price": m.get("regularMarketPrice") or closes[-1], "closes": closes}


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100


def _summary(h: dict) -> dict:
    c, p = h["closes"], h["price"]
    prev = c[-2] if abs(c[-1] - p) < 1e-9 or len(c) < 2 else c[-1]
    ma20 = sum(c[-20:]) / len(c[-20:])
    return {"symbol": h["symbol"], "name": h["name"], "cur": h["currency"], "price": p,
            "day": _pct(p, prev), "week": _pct(p, c[-6]) if len(c) > 5 else None,
            "month": _pct(p, c[-21]) if len(c) > 20 else _pct(p, c[0]), "above_ma20": p > ma20}


def _line(s: dict) -> str:
    wk = f", 1w {s['week']:+.1f}%" if s["week"] is not None else ""
    trend = "above" if s["above_ma20"] else "below"
    return f"{s['name']} ({s['symbol']}): {s['price']:,.2f} {s['cur']}, today {s['day']:+.1f}%{wk}, 1m {s['month']:+.1f}%, {trend} 20-day average"


def _safe(sym: str):
    try:
        return _summary(_history(sym, "3mo"))
    except Exception:
        return None


@tool("stock_quote", "Live price and recent trend for companies, by ticker or name (e.g. 'AAPL', 'Tesla', 'RELIANCE.NS'). "
                     "Gives today's move, 1-week and 1-month change. Pass several, comma separated.",
      {"symbols": {"type": "string", "description": "tickers or company names, comma separated"}}, ["symbols"])
def stock_quote(symbols: str) -> str:
    out = []
    for raw in [s for s in symbols.split(",") if s.strip()][:6]:
        try:
            out.append(_line(_summary(_history(_resolve(raw), "3mo"))))
        except Exception as e:
            out.append(f"{raw.strip()}: {e}")
    return "\n".join(out) + f"\n{DISCLAIMER}"


@tool("market_movers", "Which big companies are rising or falling most right now. market is 'us' or 'india'. "
                       "Use for 'which company is going up/high today'.",
      {"market": {"type": "string", "enum": ["us", "india"]}, "period": {"type": "string", "enum": ["today", "month"]}})
def market_movers(market: str = "us", period: str = "today") -> str:
    syms = INDIA_WATCH if market.lower().startswith("in") else US_WATCH
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(_safe, syms) if r]
    if not rows:
        return "ERROR: couldn't reach market data right now."
    key = "month" if period == "month" else "day"
    rows.sort(key=lambda r: r[key], reverse=True)
    label = "past month" if key == "month" else "today"
    top, bottom = rows[:5], rows[-3:][::-1]
    return (f"Top risers {label} among {len(rows)} large {market.upper()} companies:\n" + "\n".join(_line(r) for r in top) +
            f"\n\nBiggest fallers {label}:\n" + "\n".join(_line(r) for r in bottom) +
            f"\n(Only a watchlist of large companies is scanned, not the whole market.)\n{DISCLAIMER}")


@tool("investment_scenario", "What an investment would have done: 'if I put 50000 in Tesla, what would it be now / over 1y'. "
                             "Uses real price history. Gives value, gain/loss, worst drop and risk. Cannot predict the future.",
      {"amount": {"type": "number"}, "company": {"type": "string", "description": "ticker or name"},
       "period": {"type": "string", "enum": ["1m", "3m", "6m", "1y", "5y"], "description": "default 1y"}}, ["amount", "company"])
def investment_scenario(amount: float, company: str, period: str = "1y") -> str:
    rng, interval = _RANGES.get(period, _RANGES["1y"])
    h = _history(_resolve(company), rng, interval)
    c, now = h["closes"], h["price"]
    value = amount * now / c[0]
    peak, worst = c[0], 0.0
    for x in c:
        peak = max(peak, x)
        worst = min(worst, _pct(x, peak))
    rets = [_pct(c[i], c[i - 1]) for i in range(1, len(c))]
    mean = sum(rets) / len(rets)
    vol = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
    return (f"{h['name']} ({h['symbol']}) over the last {period}: {amount:,.0f} {h['currency']} invested at the start would now be "
            f"{value:,.0f} ({_pct(now, c[0]):+.1f}%). Biggest drop from a peak along the way: {worst:.1f}%. "
            f"Typical daily swing: about {vol:.1f}%, so it is {'high' if vol > 2.5 else 'moderate' if vol > 1.2 else 'low'} risk. "
            f"This is history only; the price could just as easily fall from here. {DISCLAIMER}")


# ---------------------------------------------------------------- fresh news

@tool("news_search", "Latest news headlines from the last day/week/month with dates and sources. Use for 'what's the update on X today', "
                     "'latest in AI/technology', or anything time-sensitive. Prefer this over memory.",
      {"query": {"type": "string"}, "when": {"type": "string", "enum": ["day", "week", "month"], "description": "default day"},
       "max_results": {"type": "integer", "description": "1-10, default 6"}}, ["query"])
def news_search(query: str, when: str = "day", max_results: int = 6) -> str:
    from ddgs import DDGS
    tl = {"day": "d", "week": "w", "month": "m"}.get(when, "d")
    n = max(1, min(int(max_results), 10))
    res = DDGS().news(query, max_results=n, timelimit=tl)
    if not res and tl == "d":      # quiet day: widen to the week rather than return nothing
        res = DDGS().news(query, max_results=n, timelimit="w")
    if not res:
        return "No recent news found."
    return "\n\n".join(f"{r.get('title')} ({r.get('source')}, {str(r.get('date', ''))[:10]})\n{r.get('url')}\n{r.get('body')}" for r in res)

from assistant import finance, tools


def _chart(symbol, closes, price=None):
    return {"chart": {"result": [{"meta": {"symbol": symbol, "shortName": symbol + " Inc", "currency": "USD",
                                           "regularMarketPrice": price or closes[-1]},
                                  "indicators": {"quote": [{"close": closes}]}}]}}


def _fake(monkeypatch, table):
    def get(url, params=None):
        sym = url.rsplit("/", 1)[-1]
        if "search" in url:
            return {"quotes": [{"symbol": "TSLA", "quoteType": "EQUITY"}]}
        return _chart(sym, table[sym])
    monkeypatch.setattr(finance, "_get_json", get)


def test_calculator():
    assert finance.calculate("15% of 2400").endswith("= 360")
    assert finance.calculate("(1+0.08)**10 * 50000").endswith("107,946.249864")
    assert "ERROR" in finance.calculate("__import__('os').system('x')")
    assert "ERROR" in finance.calculate("9**9**9")
    assert "zero" in finance.calculate("1/0")


def test_stock_quote_resolves_names_and_reports_moves(monkeypatch):
    _fake(monkeypatch, {"TSLA": [100.0] * 20 + [110.0, 121.0]})
    out = finance.stock_quote("tesla")
    assert "TSLA" in out and "+10.0%" in out and "not financial advice" in out


def test_market_movers_ranks_by_day_change(monkeypatch):
    table = {s: [100.0] * 25 + [100.0, 101.0] for s in finance.US_WATCH}
    table["NVDA"] = [100.0] * 25 + [100.0, 110.0]
    table["INTC"] = [100.0] * 25 + [100.0, 90.0]
    _fake(monkeypatch, table)
    out = finance.market_movers("us")
    assert out.index("NVDA") < out.index("Biggest fallers") < out.index("INTC")


def test_market_movers_includes_the_index_for_context(monkeypatch):
    """A broad 'where should I invest' question needs the overall index, not just individual companies."""
    table = {s: [100.0] * 25 + [100.0, 101.0] for s in finance.US_WATCH}
    for sym in finance.US_INDEX:
        table[sym] = [100.0] * 25 + [100.0, 102.0]
    _fake(monkeypatch, table)
    out = finance.market_movers("us")
    assert out.startswith("Index today:") and "+2.0%" in out.split("Top risers")[0]


def test_investment_scenario_works_on_an_index_name(monkeypatch):
    def get(url, params=None):
        if "search" in url:
            return {"quotes": [{"symbol": "^GSPC", "quoteType": "INDEX"}]}
        return _chart("^GSPC", [4000.0, 4400.0])
    monkeypatch.setattr(finance, "_get_json", get)
    out = finance.investment_scenario(10000, "S&P 500", "5y")
    assert "+10.0%" in out and "could just as easily fall" in out


def test_investment_scenario(monkeypatch):
    _fake(monkeypatch, {"AAPL": [100.0, 120.0, 90.0, 150.0]})
    out = finance.investment_scenario(1000, "AAPL", "1y")
    assert "1,500" in out and "+50.0%" in out and "-25.0%" in out and "could just as easily fall" in out


def test_market_data_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(finance, "_get_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403 Forbidden")))
    assert "403" in finance.stock_quote("AAPL")
    assert "ERROR" in finance.market_movers("us")


def test_tools_registered_and_news_is_current():
    for n in ("calculate", "stock_quote", "market_movers", "investment_scenario", "news_search"):
        assert n in tools.TOOLS
    from assistant.brain import SYSTEM
    assert "ALWAYS call news_search" in SYSTEM

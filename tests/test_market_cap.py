from src.scanner import market_cap_bucket


def test_market_cap_bucket_ranges():
    assert market_cap_bucket(250_000_000_000) == "Mega Cap"
    assert market_cap_bucket(25_000_000_000) == "Large Cap"
    assert market_cap_bucket(3_000_000_000) == "Mid Cap"
    assert market_cap_bucket(500_000_000) == "Small Cap"

from vnstock import Vnstock
import pandas as pd

try:
    print("Fetching VNINDEX...")
    stock = Vnstock().stock(symbol="VNINDEX", source="VCI")
    df = stock.quote.history(start="2024-01-01", end="2024-01-10", interval="1D")
    print(df.head())
    
    print("\nMarket Top...")
    # try to get top movers
    market = Vnstock().market
    # There is something like top_movers or similar, let's just print available methods
    print(dir(market))
except Exception as e:
    print(e)

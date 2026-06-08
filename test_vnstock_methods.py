from vnstock import Vnstock
import sys

try:
    v = Vnstock()
    # Let's explore available sub-modules
    print("Vnstock methods:", dir(v))
    # Check if there is a 'trading' or 'quote' module
    if hasattr(v, 'quote'):
        print("quote methods:", dir(v.quote))
    if hasattr(v, 'trading'):
        print("trading methods:", dir(v.trading))
    if hasattr(v, 'screener'):
        print("screener methods:", dir(v.screener))
except Exception as e:
    print(e)

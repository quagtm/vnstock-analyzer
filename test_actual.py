import pandas as pd
import json

from data_pipeline.fetch_and_analyze import fetch_ssi_daily_data, calculate_technical_indicators, compute_tas_history_fast, process_symbol

def test():
    # Process symbol directly
    res = process_symbol('VNINDEX')
    if res:
        print("Root TAS:", res['tas']['score'])
        print("History TAS last 5:", [x['score'] for x in res['tas']['history'][-5:]])
    else:
        print("Failed to process")

if __name__ == '__main__':
    test()

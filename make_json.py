import ast
import json
import re

with open('data_pipeline/fetch_and_analyze.py', 'r', encoding='utf-8') as f:
    code = f.read()
    
match = re.search(r'SECTOR_MAP_FALLBACK\s*=\s*(\{[\s\S]*?\n\})', code)
if match:
    dict_str = match.group(1)
    d = ast.literal_eval(dict_str)
    with open('custom_sectors.json', 'w', encoding='utf-8') as out:
        json.dump(d, out, ensure_ascii=False, indent=4)
    print("Success")

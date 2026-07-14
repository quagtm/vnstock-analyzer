import urllib.request, json
req = urllib.request.Request("https://api.github.com/repos/quagtm/vnstock-analyzer/actions/runs?per_page=5")
req.add_header('User-Agent', 'Mozilla/5.0')
try:
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read())
    for r in data.get('workflow_runs', []):
        print(f"{r.get('created_at')} | {r.get('name')} | {r.get('event')} | status={r.get('status')} | conc={r.get('conclusion')}")
except Exception as e:
    print(e)

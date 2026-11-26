"""Kiểm tra nhanh bộ rule nhận định: python data_pipeline/test_market_rules.py"""
import itertools
import market_rules as mr


def snap(close=100, ma=(98, 97, 95, 93, 90), tas=40, adx=28, cmf=0.1, roc=(3, 5),
         rsi=60, n_up=20, n_down=8, smc_trend=1, vol_diff=0, change_pc=0.5):
    names = ("MA10", "MA20", "MA50", "MA100", "MA200")
    return {
        "symbol": "TEST", "close": close, "prev_close": close / (1 + change_pc / 100),
        "change_pc": change_pc, "high": close * 1.01, "low": close * 0.99,
        "volume": 5e8, "vol_diff": vol_diff, "ma": dict(zip(names, ma)),
        "roc10": roc[0], "roc20": roc[1], "rsi14": rsi, "adx": adx, "atr": close * 0.02,
        "keltner_h": close * 1.03, "keltner_l": close * 0.97, "cmf": cmf, "vwap": close * 0.99,
        "obv": 1e9, "obv_change_10": 1e7, "tas_score": tas, "tas_label": "",
        "smc": {"trend": smc_trend, "choch_level": close * 0.94, "last_event": None},
        "breadth": {"n_up": n_up, "n_down": n_down}, "sector_perf": [("A", 1.0), ("B", 0.5), ("C", -0.2)],
        "sr_zones": [{"level": close * 0.97}, {"level": close * 1.04}, {"level": close * 0.92}],
    }


def test_strong_up():
    v = mr.build_verdict(snap())
    assert v["regime_key"] == "strong_up" and v["action"] == "Tăng tỷ trọng"


def test_strong_down():
    v = mr.build_verdict(snap(ma=(102, 103, 105, 107, 110), tas=-50, cmf=-0.1, roc=(-3, -5),
                              n_up=5, n_down=20, smc_trend=-1))
    assert v["regime_key"] == "strong_down" and v["action"] == "Đứng ngoài"


def test_downgrade_only_one_level():
    v = mr.build_verdict(snap(cmf=-0.2, n_up=2, n_down=20))
    assert mr.ACTIONS.index(v["base_action"]) - mr.ACTIONS.index(v["action"]) == 1


def test_grid_consistency():
    """Mọi tổ hợp: luôn có đúng 1 trạng thái, hành động chung xuất hiện ở mọi tab,
    lý do và rủi ro không chứa cùng một tín hiệu."""
    grid = itertools.product(
        [(98, 97, 95, 93, 90), (102, 103, 105, 107, 110), (99, 101, 97, 104, 106), (101, 99, 103, 97, 95)],
        [-60, -10, 0, 10, 60], [12, 22, 30], [-0.1, 0, 0.1], [(-3, -5), (0, 0), (3, 5)],
        [(20, 5), (12, 12), (3, 20)], [1, -1])
    for ma, tas, adx, cmf, roc, (u, d), t in grid:
        s = snap(ma=ma, tas=tas, adx=adx, cmf=cmf, roc=roc, n_up=u, n_down=d, smc_trend=t)
        out = mr.build_commentary(s)
        v = out["_v"]
        assert v["regime_key"] in mr.REGIMES
        assert v["action"] in mr.ACTIONS
        for k in ("general_markdown", "volume_markdown", "trend_markdown"):
            assert f"**{v['action']}**" in out[k], (k, v["regime"])
        assert not set(id(x) for x in v["reasons"]) & set(id(x) for x in v["risks"])
        if v["bias"]:
            assert all(x["dir"] == v["bias"] for x in v["reasons"])
            assert all(x["dir"] == -v["bias"] for x in v["risks"])
        assert mr.ACTIONS.index(v["base_action"]) - mr.ACTIONS.index(v["action"]) in (0, 1)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)

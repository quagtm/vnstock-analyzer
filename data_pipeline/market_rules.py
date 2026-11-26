"""
Bộ rule luận giải nhận định thị trường (rules v1).

Nguyên tắc:
  1. Mỗi chỉ số mỗi ngày chỉ có MỘT trạng thái (7 trạng thái, xét rule theo thứ tự,
     khớp rule nào trước thì dừng) và MỘT hành động (5 mức cố định).
  2. Hành động gốc lấy từ trạng thái; các điều chỉnh chỉ được HẠ tối đa 1 bậc.
  3. "Lý do" chỉ chứa tín hiệu cùng chiều với trạng thái, tín hiệu ngược chiều
     luôn nằm ở "Rủi ro".
  4. Một kết luận (verdict) dùng lại nguyên văn ở mọi tab.
  5. Mốc giá dùng chung một nguồn: vùng S/R gần nhất và mốc CHoCH của SMC.

Mọi ngưỡng nằm trong CONFIG để chỉnh mà không phải sửa logic.
"""

RULES_VERSION = "rules v1"

CONFIG = {
    # Động lượng
    "roc10_pos": 1.5, "roc10_neg": -1.5,
    "roc20_pos": 2.0, "roc20_neg": -2.0,
    # Quá mua / quá bán
    "rsi_overbought": 70, "rsi_oversold": 30,
    # Sức mạnh xu hướng (ADX)
    "adx_weak": 20, "adx_strong": 25, "adx_very_flat": 15,
    # Dòng tiền
    "cmf_in": 0.05, "cmf_out": -0.05,
    "vol_spike_pct": 20,          # KL so với TB20 (%)
    "session_move_pct": 1.0,      # % thay đổi phiên để tính phiên phân phối / cầu chủ động
    # Độ rộng (A/D)
    "ad_broad_up": 2.0, "ad_lean_up": 1.2, "ad_lean_down": 0.8, "ad_broad_down": 0.5,
    # Ngành (% số ngành tăng)
    "sector_up_pct": 70, "sector_down_pct": 30,
    # TAS
    "tas_strong": 34,
    # Biến động (ATR / giá, %)
    "atr_low_pct": 1.5, "atr_high_pct": 3.0,
    # Độ tin cậy (% nhóm cùng chiều)
    "conf_high": 75, "conf_mid": 50,
}

# ── Từ điển cố định ────────────────────────────────────────────────
ACTIONS = [  # từ thấp đến cao
    "Đứng ngoài",
    "Giảm tỷ trọng",
    "Thăm dò tỷ trọng nhỏ",
    "Nắm giữ",
    "Tăng tỷ trọng",
]

# regime key → (nhãn, bias, hành động gốc, kịch bản chính)
REGIMES = {
    "strong_up":   ("Tăng mạnh", 1, "Tăng tỷ trọng", "positive"),
    "strong_down": ("Giảm mạnh", -1, "Đứng ngoài", "negative"),
    "sideway":     ("Đi ngang", 0, "Thăm dò tỷ trọng nhỏ", "neutral"),
    "up":          ("Tăng", 1, "Nắm giữ", "positive"),
    "pullback":    ("Điều chỉnh trong xu hướng tăng", 1, "Nắm giữ", "neutral"),
    "rebound":     ("Hồi phục kỹ thuật", 1, "Thăm dò tỷ trọng nhỏ", "neutral"),
    "down":        ("Giảm", -1, "Giảm tỷ trọng", "negative"),
}

SCENARIO_LABEL = {"positive": "Tích cực", "neutral": "Trung tính", "negative": "Tiêu cực"}
DIR_MARK = {1: "+", 0: "0", -1: "−"}
EMOJI = {1: "🟢", 0: "🟡", -1: "🔴"}

FOOTER = (f"\n\n---\n*Nhận định sinh tự động theo bộ rule cố định ({RULES_VERSION}) từ dữ liệu kỹ thuật. "
          "Không phải khuyến nghị đầu tư.*")


# ── Tiện ích ───────────────────────────────────────────────────────
def _p(x):
    return f"{x:,.2f}" if x is not None else "N/A"


def _pct(x, digits=2):
    return f"{x:+.{digits}f}%"


def _ma(snap, name):
    v = snap["ma"].get(name) or 0
    return v if v > 0 else None


def _long_ma(snap):
    """MA200, thiếu thì dùng MA100."""
    if _ma(snap, "MA200"):
        return "MA200", _ma(snap, "MA200")
    if _ma(snap, "MA100"):
        return "MA100", _ma(snap, "MA100")
    return None, None


# ── Bước 1: quy từng nhóm tín hiệu về trạng thái + chiều ────────────
def classify_factors(snap):
    c = CONFIG
    close = snap["close"]
    f = {}

    # Cấu trúc MA
    horizons = {}
    for key, names in (("Ngắn hạn", ("MA10", "MA20")), ("Trung hạn", ("MA50",)), ("Dài hạn", ("MA100", "MA200"))):
        vals = [_ma(snap, n) for n in names if _ma(snap, n)]
        if not vals:
            horizons[key] = None
        elif all(close >= v for v in vals):
            horizons[key] = 1
        elif all(close < v for v in vals):
            horizons[key] = -1
        else:
            horizons[key] = 0
    key_mas = [(n, _ma(snap, n)) for n in ("MA20", "MA50") if _ma(snap, n)]
    ln, lv = _long_ma(snap)
    if lv:
        key_mas.append((ln, lv))
    above = sum(1 for _, v in key_mas if close >= v)
    if key_mas and above == len(key_mas):
        ma_dir = 1
    elif key_mas and above == 0:
        ma_dir = -1
    else:
        ma_dir = 0
    hz_word = {1: "tăng", -1: "giảm", 0: "hỗn hợp", None: "không đủ dữ liệu"}
    ma_detail = ", ".join(f"{'trên' if close >= v else 'dưới'} {n} ({_p(v)})" for n, v in key_mas)
    def _join(names):
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " và " + names[-1]
    ab = [n for n, v in key_mas if close >= v]
    be = [n for n, v in key_mas if close < v]
    ma_short = ", ".join(x for x in (f"trên {_join(ab)}" if ab else "", f"dưới {_join(be)}" if be else "") if x)
    f["ma"] = {
        "short": f"giá {ma_short}" if key_mas else "không đủ dữ liệu MA",
        "group": "Cấu trúc MA",
        "dir": ma_dir,
        "state": "; ".join(f"{k.lower()} {hz_word[v]}" for k, v in horizons.items()).capitalize(),
        "fact": f"Giá {ma_detail}" if key_mas else "Không đủ dữ liệu MA",
        "horizons": horizons,
    }

    # Động lượng
    r10, r20 = snap["roc10"], snap["roc20"]
    if r10 > c["roc10_pos"] and r20 > c["roc20_pos"]:
        m_dir, m_state = 1, "Tích cực"
    elif r10 < c["roc10_neg"] and r20 < c["roc20_neg"]:
        m_dir, m_state = -1, "Tiêu cực"
    else:
        m_dir, m_state = 0, "Trung tính"
    f["momentum"] = {
        "group": "Động lượng", "dir": m_dir, "state": m_state,
        "short": f"động lượng {m_state.lower()} (ROC20 {_pct(r20)})",
        "fact": f"ROC10 {_pct(r10)}, ROC20 {_pct(r20)}: động lượng {m_state.lower()}",
    }

    # Dòng tiền
    cmf, vd, chg = snap["cmf"], snap["vol_diff"], snap["change_pc"]
    if cmf > c["cmf_in"]:
        fl_dir, fl_state = 1, "Vào"
    elif cmf < c["cmf_out"]:
        fl_dir, fl_state = -1, "Ra"
    else:
        fl_dir, fl_state = 0, "Trung tính"
    distribution = chg < -c["session_move_pct"] and vd > c["vol_spike_pct"]
    demand = chg > c["session_move_pct"] and vd > c["vol_spike_pct"]
    if fl_dir == 1 and demand:
        fl_state = "Vào mạnh"
    elif fl_dir == -1 and distribution:
        fl_state = "Ra mạnh"
    session_note = ""
    if distribution:
        session_note = f"; phiên phân phối (giảm {abs(chg):.2f}% với KL {_pct(vd, 0)} so với TB20)"
    elif demand:
        session_note = f"; phiên cầu chủ động (tăng {chg:.2f}% với KL {_pct(vd, 0)} so với TB20)"
    f["flow"] = {
        "group": "Dòng tiền", "dir": fl_dir, "state": fl_state,
        "short": f"dòng tiền {fl_state.lower()} (CMF {cmf:+.3f})",
        "fact": f"CMF {cmf:+.3f}: dòng tiền {fl_state.lower()}{session_note}",
        "distribution": distribution, "demand": demand,
    }

    # Độ rộng
    b = snap.get("breadth")
    if b and (b.get("n_up", 0) + b.get("n_down", 0)) > 0:
        ratio = b["n_up"] / max(b["n_down"], 1)
        if ratio >= c["ad_broad_up"]:
            br_dir, br_state = 1, "Lan tỏa tăng"
        elif ratio >= c["ad_lean_up"]:
            br_dir, br_state = 1, "Nghiêng tăng"
        elif ratio > c["ad_lean_down"]:
            br_dir, br_state = 0, "Phân hóa"
        elif ratio >= c["ad_broad_down"]:
            br_dir, br_state = -1, "Nghiêng giảm"
        else:
            br_dir, br_state = -1, "Lan tỏa giảm"
        f["breadth"] = {
            "group": "Độ rộng", "dir": br_dir, "state": br_state, "ratio": ratio,
            "short": f"độ rộng {br_state.lower()} (A/D {ratio:.2f})",
            "fact": f"A/D {ratio:.2f} ({b['n_up']} tăng / {b['n_down']} giảm): {br_state.lower()}",
        }
    else:
        f["breadth"] = {"group": "Độ rộng", "dir": 0, "state": "Không đủ dữ liệu", "ratio": None,
                        "fact": "Không đủ dữ liệu độ rộng", "missing": True}

    # Ngành
    sp = [(n, v) for n, v in (snap.get("sector_perf") or []) if n != "Khác"]
    if sp:
        n_up = sum(1 for _, v in sp if v > 0)
        share = n_up / len(sp) * 100
        if share >= c["sector_up_pct"]:
            s_dir, s_state = 1, "Đồng thuận tăng"
        elif share <= c["sector_down_pct"]:
            s_dir, s_state = -1, "Đồng thuận giảm"
        else:
            s_dir, s_state = 0, "Phân hóa"
        srt = sorted(sp, key=lambda x: x[1], reverse=True)
        k = min(3, len(srt) // 2)
        lead = ", ".join(f"{n} ({_pct(v)})" for n, v in srt[:k]) if k else ""
        lag = ", ".join(f"{n} ({_pct(v)})" for n, v in srt[::-1][:k]) if k else ""
        f["sector"] = {
            "group": "Ngành", "dir": s_dir, "state": s_state,
            "short": f"nhóm ngành {s_state.lower()} ({n_up}/{len(sp)} ngành tăng)",
            "fact": f"{n_up}/{len(sp)} ngành tăng: {s_state.lower()}",
            "lead": lead, "lag": lag,
        }
    else:
        f["sector"] = {"group": "Ngành", "dir": 0, "state": "Không đủ dữ liệu",
                       "fact": "Không đủ dữ liệu ngành", "missing": True}

    # Cấu trúc SMC
    smc = snap.get("smc") or {}
    t = smc.get("trend")
    if t in (1, -1):
        ev = smc.get("last_event") or {}
        ev_txt = ""
        if ev.get("txt"):
            ev_txt = f", sự kiện gần nhất {ev['txt']} {'tăng' if ev.get('dir') == 'bull' else 'giảm'} tại {_p(ev.get('y'))}"
        f["smc"] = {
            "group": "Cấu trúc SMC", "dir": t, "state": "Tăng" if t == 1 else "Giảm",
            "short": f"cấu trúc SMC {'tăng' if t == 1 else 'giảm'}",
            "fact": f"Cấu trúc SMC {'tăng' if t == 1 else 'giảm'}{ev_txt}",
        }
    else:
        f["smc"] = {"group": "Cấu trúc SMC", "dir": 0, "state": "Không đủ dữ liệu",
                    "fact": "Không đủ dữ liệu SMC", "missing": True}

    # Cảnh báo (không có chiều)
    rsi, kh, kl = snap["rsi14"], snap["keltner_h"], snap["keltner_l"]
    ob_reasons, os_reasons = [], []
    if rsi > c["rsi_overbought"]:
        ob_reasons.append(f"RSI14 {rsi:.1f}")
    if kh and close > kh:
        ob_reasons.append(f"giá trên Keltner trên ({_p(kh)})")
    if 0 < rsi < c["rsi_oversold"]:
        os_reasons.append(f"RSI14 {rsi:.1f}")
    if kl and close < kl:
        os_reasons.append(f"giá dưới Keltner dưới ({_p(kl)})")
    f["overbought"] = ob_reasons
    f["oversold"] = os_reasons

    # Sức mạnh xu hướng
    adx = snap["adx"]
    if adx < c["adx_weak"]:
        adx_state = "yếu hoặc đi ngang"
    elif adx < c["adx_strong"]:
        adx_state = "đang hình thành"
    else:
        adx_state = "mạnh"
    f["adx_state"] = adx_state

    # Biến động
    atr_pct = snap["atr"] / close * 100 if close > 0 else 0
    if atr_pct < c["atr_low_pct"]:
        vol_state = "thấp"
    elif atr_pct <= c["atr_high_pct"]:
        vol_state = "bình thường"
    else:
        vol_state = "cao"
    f["atr_pct"] = atr_pct
    f["volatility_state"] = vol_state
    return f


DIRECTIONAL = ("ma", "momentum", "flow", "breadth", "sector", "smc")


# ── Bước 2: xác định trạng thái ────────────────────────────────────
def determine_regime(snap, f):
    c = CONFIG
    close, tas, adx = snap["close"], snap["tas_score"], snap["adx"]
    ma20, ma50 = _ma(snap, "MA20"), _ma(snap, "MA50")
    _, long_v = _long_ma(snap)
    smc_dir = f["smc"]["dir"]
    ratio = f["breadth"].get("ratio")

    def above(v):
        return v is not None and close >= v

    def below(v):
        return v is not None and close < v

    if (tas >= c["tas_strong"] and above(ma20) and above(ma50) and above(long_v)
            and smc_dir == 1 and ratio is not None and ratio >= c["ad_lean_up"]):
        return "strong_up", 1
    if (tas <= -c["tas_strong"] and below(ma20) and below(ma50) and below(long_v)
            and smc_dir == -1 and ratio is not None and ratio <= c["ad_lean_down"]):
        return "strong_down", 2
    if (adx < c["adx_weak"] and -(c["tas_strong"] - 1) <= tas <= (c["tas_strong"] - 1)
            and f["ma"]["dir"] == 0):
        return "sideway", 3
    ref = long_v if long_v is not None else ma50
    if above(ma50) and above(long_v) and tas > 0:
        return "up", 4
    if above(ref):
        return "pullback", 5
    if tas > 0:
        return "rebound", 6
    return "down", 7


# ── Bước 3: mốc giá ────────────────────────────────────────────────
def key_levels(snap):
    close = snap["close"]
    zones = snap.get("sr_zones") or []
    sup = sorted([z["level"] for z in zones if z["level"] < close], reverse=True)
    res = sorted([z["level"] for z in zones if z["level"] > close])
    # bổ sung MA làm mốc khi thiếu vùng S/R
    ma_vals = [v for v in (snap["ma"].get(n) for n in ("MA20", "MA50", "MA100", "MA200")) if v and v > 0]
    if not sup:
        sup = sorted([v for v in ma_vals if v < close], reverse=True)
    if not res:
        res = sorted([v for v in ma_vals if v > close])
    return sup, res


def invalidation_level(snap, bias, sup, res):
    """Ngưỡng vô hiệu nhận định: ưu tiên mốc CHoCH của SMC, sau đó S/R, cuối cùng MA50."""
    close = snap["close"]
    choch = (snap.get("smc") or {}).get("choch_level")
    ma50 = _ma(snap, "MA50")
    if bias > 0:
        if choch is not None and choch < close:
            return choch, "mốc CHoCH"
        if sup:
            return sup[0], "hỗ trợ gần nhất"
        if ma50 and ma50 < close:
            return ma50, "MA50"
    elif bias < 0:
        if choch is not None and choch > close:
            return choch, "mốc CHoCH"
        if res:
            return res[0], "kháng cự gần nhất"
        if ma50 and ma50 > close:
            return ma50, "MA50"
    return None, None


# ── Bước 4: tổng hợp kết luận ──────────────────────────────────────
def build_verdict(snap):
    c = CONFIG
    f = classify_factors(snap)
    key, rule_no = determine_regime(snap, f)
    label, bias, base_action, main_scenario = REGIMES[key]

    # Hành động: chỉ được hạ, tối đa 1 bậc
    idx = ACTIONS.index(base_action)
    downgrade_reasons = []
    if bias >= 0:
        if f["flow"]["distribution"]:
            downgrade_reasons.append("có phiên phân phối")
        elif snap["cmf"] < c["cmf_out"]:
            downgrade_reasons.append(f"dòng tiền ra (CMF {snap['cmf']:+.3f})")
        ratio = f["breadth"].get("ratio")
        if ratio is not None and ratio < c["ad_broad_down"]:
            downgrade_reasons.append(f"độ rộng lan tỏa giảm (A/D {ratio:.2f})")
    if downgrade_reasons and idx > 0:
        idx -= 1
    action = ACTIONS[idx]

    # Lý do / rủi ro
    reasons, risks = [], []
    for k in DIRECTIONAL:
        fac = f[k]
        if fac.get("missing"):
            continue
        if bias == 0:
            (reasons if fac["dir"] == 0 else risks).append(fac)
        elif fac["dir"] == bias:
            reasons.append(fac)
        elif fac["dir"] == -bias:
            risks.append(fac)

    # Độ tin cậy
    if bias == 0:
        confidence = "Cao" if snap["adx"] < c["adx_very_flat"] else "Trung bình"
    else:
        nonneutral = [f[k] for k in DIRECTIONAL if not f[k].get("missing") and f[k]["dir"] != 0]
        agree = sum(1 for x in nonneutral if x["dir"] == bias)
        share = agree / len(nonneutral) * 100 if nonneutral else 0
        confidence = "Cao" if share >= c["conf_high"] else ("Trung bình" if share >= c["conf_mid"] else "Thấp")

    sup, res = key_levels(snap)
    inv, inv_src = invalidation_level(snap, bias, sup, res)

    return {
        "regime_key": key, "regime": label, "rule_no": rule_no, "bias": bias,
        "base_action": base_action, "action": action, "downgrade_reasons": downgrade_reasons,
        "confidence": confidence, "main_scenario": main_scenario,
        "factors": f, "reasons": reasons, "risks": risks,
        "support": sup, "resistance": res, "invalidation": inv, "invalidation_src": inv_src,
    }


# ── Câu hành động ──────────────────────────────────────────────────
def action_sentence(v):
    s = _p(v["support"][0]) if v["support"] else None
    r = _p(v["resistance"][0]) if v["resistance"] else None
    inv = _p(v["invalidation"]) if v["invalidation"] is not None else None
    a = v["action"]
    parts = []
    if a == "Tăng tỷ trọng":
        parts.append(f"Tăng tỷ trọng ở các nhịp điều chỉnh về hỗ trợ {s}" if s else "Tăng tỷ trọng ở các nhịp điều chỉnh")
    elif a == "Nắm giữ":
        parts.append(f"Nắm giữ vị thế hiện có, chỉ mua thêm khi giá giữ được hỗ trợ {s}" if s else "Nắm giữ vị thế hiện có, chưa mua thêm")
    elif a == "Thăm dò tỷ trọng nhỏ":
        p = f"Chỉ mua thăm dò tỷ trọng nhỏ quanh hỗ trợ {s}" if s else "Chỉ mua thăm dò tỷ trọng nhỏ"
        if r:
            p += f", chỉ nâng tỷ trọng khi đóng cửa vượt kháng cự {r}"
        parts.append(p)
    elif a == "Giảm tỷ trọng":
        parts.append(f"Giảm tỷ trọng khi giá hồi lên kháng cự {r}, chưa mua mới" if r else "Giảm tỷ trọng, chưa mua mới")
    else:
        parts.append("Đứng ngoài, chưa bắt đáy")
    if v["bias"] == 0 and v["support"] and v["resistance"]:
        parts.append(f"trạng thái đi ngang kết thúc khi đóng cửa ngoài vùng {s} – {r}")
    elif inv:
        if v["bias"] > 0:
            parts.append(f"hạ một bậc hành động nếu đóng cửa dưới {inv} ({v['invalidation_src']})")
        else:
            parts.append(f"chỉ xem xét lại khi đóng cửa trên {inv} ({v['invalidation_src']})")
    sent = "; ".join(parts) + "."
    f = v["factors"]
    if v["bias"] >= 0 and f["overbought"]:
        sent += f" Không mua đuổi vì đang quá mua ({', '.join(f['overbought'])})."
    if v["bias"] < 0 and f["oversold"]:
        sent += f" Theo dõi tín hiệu tạo đáy vì đang quá bán ({', '.join(f['oversold'])})."
    return sent


def summary_sentence(snap, v):
    """Một câu nhận định tổng quan: trạng thái → lý do chính → điểm cần lưu ý → hành động."""
    f = v["factors"]
    if v["bias"] == 0:
        why = f"chưa có xu hướng rõ (ADX {snap['adx']:.1f}, TAS {snap['tas_score']:+d})"
    elif v["reasons"]:
        why = ", ".join(x["short"] for x in v["reasons"][:2])
    else:
        why = f"TAS {snap['tas_score']:+d}, {f['ma']['short']}"
    watch = None
    if v["downgrade_reasons"]:
        watch = ", ".join(v["downgrade_reasons"])
    elif v["bias"] >= 0 and f["overbought"]:
        watch = "đang quá mua (" + ", ".join(f["overbought"]) + ")"
    elif v["bias"] < 0 and f["oversold"]:
        watch = "đang quá bán (" + ", ".join(f["oversold"]) + "), có thể có nhịp hồi ngắn"
    elif v["risks"]:
        watch = v["risks"][0]["short"]
    out = (f"{snap['symbol']} đang ở trạng thái **{v['regime']}** (độ tin cậy {v['confidence']}): {why}")
    if watch:
        out += f"; cần lưu ý {watch}"
    out += f". Hành động: **{v['action']}**"
    if v["bias"] == 0 and v["support"] and v["resistance"]:
        out += f", chờ đóng cửa ra khỏi vùng {_p(v['support'][0])} – {_p(v['resistance'][0])}"
    elif v["invalidation"] is not None:
        side = "dưới" if v["bias"] > 0 else "trên"
        out += f", nhận định đổi nếu đóng cửa {side} {_p(v['invalidation'])}"
    return out + "."


def verdict_line(v):
    return f"{EMOJI[v['bias']]} **{v['regime']}** → **{v['action']}** (độ tin cậy {v['confidence']})"


# ── Khối nhận định 5 mục ───────────────────────────────────────────
def build_assessment_md(snap, v):
    f = v["factors"]
    out = []
    out.append(f"**Trạng thái:** {EMOJI[v['bias']]} **{v['regime']}** "
               f"(TAS {snap['tas_score']:+d}/100, ADX {snap['adx']:.1f} — xu hướng {f['adx_state']}, "
               f"độ tin cậy **{v['confidence']}**)")
    out.append("")
    out.append("**Tín hiệu:**\n")
    out.append("| Nhóm | Trạng thái | Chiều | Số liệu |")
    out.append("|---|---|---|---|")
    for k in DIRECTIONAL:
        fac = f[k]
        out.append(f"| {fac['group']} | {fac['state']} | {DIR_MARK[fac['dir']]} | {fac['fact']} |")
    out.append("")

    out.append("**Lý do:**")
    if v["bias"] == 0:
        out.append(f"- ADX {snap['adx']:.1f} < {CONFIG['adx_weak']} và TAS {snap['tas_score']:+d} nằm giữa "
                   f"−{CONFIG['tas_strong'] - 1} và +{CONFIG['tas_strong'] - 1}: chưa có xu hướng rõ")
    if v["reasons"]:
        for fac in v["reasons"]:
            out.append(f"- {fac['fact']}")
    elif v["bias"] != 0:
        out.append(f"- Trạng thái xác định chủ yếu từ vị trí giá so với MA dài hạn và TAS {snap['tas_score']:+d}")
    out.append("")

    out.append("**Rủi ro:**")
    if v["bias"] == 0:
        risk_lines = [f"- Nghiêng {'tăng' if fac['dir'] > 0 else 'giảm'}: {fac['fact']}" for fac in v["risks"]]
    else:
        risk_lines = [f"- {fac['fact']}" for fac in v["risks"]]
    if v["bias"] >= 0 and f["overbought"]:
        risk_lines.append(f"- Quá mua: {', '.join(f['overbought'])}")
    if v["bias"] == 0 and f["oversold"]:
        risk_lines.append(f"- Quá bán: {', '.join(f['oversold'])}")
    if v["bias"] < 0 and f["oversold"]:
        risk_lines.append(f"- Quá bán ({', '.join(f['oversold'])}) có thể tạo nhịp hồi kỹ thuật ngắn")
    if f["volatility_state"] == "cao":
        risk_lines.append(f"- Biến động cao: ATR {f['atr_pct']:.2f}% giá mỗi phiên")
    if v["bias"] == 0 and v["support"] and v["resistance"]:
        risk_lines.append(f"- Trạng thái đi ngang kết thúc nếu đóng cửa ngoài vùng {_p(v['support'][0])} – {_p(v['resistance'][0])}")
    elif v["invalidation"] is not None:
        if v["bias"] > 0:
            risk_lines.append(f"- Nhận định mất hiệu lực nếu đóng cửa dưới {_p(v['invalidation'])} ({v['invalidation_src']})")
        else:
            risk_lines.append(f"- Nhận định mất hiệu lực nếu đóng cửa trên {_p(v['invalidation'])} ({v['invalidation_src']})")
    out.extend(risk_lines or ["- Không có tín hiệu ngược chiều đáng kể"])
    out.append("")

    act = f"**Hành động:** ➡️ **{v['action']}**"
    if v["action"] != v["base_action"]:
        act += f" (hạ một bậc từ {v['base_action']} vì {', '.join(v['downgrade_reasons'])})"
    out.append(act + f". {action_sentence(v)}")
    return "\n".join(out)


def build_general_md(snap, v, market_stats_md="", breadth_md=""):
    chg = snap["close"] - snap["prev_close"]
    chg_pc = snap["change_pc"]
    word = "tăng" if chg > 0 else ("giảm" if chg < 0 else "đứng giá")
    em = "🟢" if chg > 0 else ("🔴" if chg < 0 else "🟡")
    vd = snap["vol_diff"]
    vol_word = f"cao hơn {vd:.2f}%" if vd >= 0 else f"thấp hơn {abs(vd):.2f}%"
    md = [
        f"{EMOJI[v['bias']]} **Nhận định tổng quan:** {summary_sentence(snap, v)}",
        "",
        "### 1. Diễn biến phiên giao dịch",
        f"{em} **{snap['symbol']}** đóng cửa tại **{_p(snap['close'])}** điểm, **{word} {abs(chg):,.2f} điểm "
        f"({_pct(chg_pc)})** so với phiên trước ({_p(snap['prev_close'])}). "
        f"Biên độ phiên {_p(snap['low'])} – {_p(snap['high'])}.",
        "",
        f"Khối lượng: **{snap['volume'] / 1_000_000:,.2f} triệu CP**, {vol_word} so với TB 20 phiên.",
        "",
        "### 2. Nhận định tổng hợp",
        build_assessment_md(snap, v),
    ]
    f = v["factors"]
    if market_stats_md or f["sector"].get("lead"):
        md += ["", "### 3. Thống kê Cổ phiếu & Nhóm ngành"]
        if f["sector"].get("lead"):
            md.append(f"**Ngành mạnh nhất:** {f['sector']['lead']}  \n**Ngành yếu nhất:** {f['sector']['lag']}")
            md.append("")
        if market_stats_md:
            md.append(market_stats_md)
    if breadth_md:
        md += ["", "### 4. Độ rộng thị trường", breadth_md]
    return "\n".join(md) + FOOTER


def build_volume_md(snap, v):
    f = v["factors"]
    close, vwap = snap["close"], snap["vwap"]
    obv_chg = snap.get("obv_change_10")
    if obv_chg is None:
        obv_note = "Không đủ dữ liệu"
    elif obv_chg > 0:
        obv_note = "Tăng trong 10 phiên: khối lượng ngày tăng áp đảo"
    elif obv_chg < 0:
        obv_note = "Giảm trong 10 phiên: khối lượng ngày giảm áp đảo"
    else:
        obv_note = "Đi ngang trong 10 phiên"
    vwap_note = ("Giá trên VWAP: bên mua chiếm ưu thế" if vwap and close > vwap
                 else ("Giá dưới VWAP: bên bán chiếm ưu thế" if vwap else "Không đủ dữ liệu"))
    vd = snap["vol_diff"]
    if vd > CONFIG["vol_spike_pct"]:
        vol_note = "đột biến"
    elif vd < -CONFIG["vol_spike_pct"]:
        vol_note = "thấp, dòng tiền thận trọng"
    else:
        vol_note = "bình thường"
    fl = f["flow"]
    md = [
        "### 1. Thống kê Chỉ báo Khối lượng",
        "| Chỉ báo | Giá trị | Nhận định |",
        "|---|---|---|",
        f"| **CMF** | `{snap['cmf']:+.4f}` | Dòng tiền {fl['state'].lower()} |",
        f"| **VWAP (14 phiên)** | `{_p(vwap)}` | {vwap_note} |",
        f"| **OBV** | `{snap['obv']:,.0f}` | {obv_note} |",
        f"| **KL phiên** | `{snap['volume'] / 1_000_000:,.2f} triệu CP` | {_pct(vd)} so với TB20: {vol_note} |",
        "",
        "### 2. Nhận định Dòng tiền",
        f"**Trạng thái dòng tiền:** {EMOJI[fl['dir']]} **{fl['state']}** — {fl['fact']}.",
        "",
    ]
    if fl["distribution"]:
        md.append("⚠️ Phiên giảm kèm khối lượng lớn là dấu hiệu phân phối; hành động chung đã được hạ một bậc nếu đang ở trạng thái tăng hoặc đi ngang.")
        md.append("")
    md.append(f"**Nhận định chung:** {verdict_line(v)}. {action_sentence(v)}")
    return "\n".join(md) + FOOTER


def build_trend_md(snap, v):
    f = v["factors"]
    close = snap["close"]
    rows = []
    for n in ("MA10", "MA20", "MA50", "MA100", "MA200"):
        val = _ma(snap, n)
        if val:
            d = (close - val) / val * 100
            rows.append(f"| **{n}** | `{_p(val)}` | {_pct(d)} | {'Hỗ trợ' if d >= 0 else 'Kháng cự'} |")
    kh, kl = snap["keltner_h"], snap["keltner_l"]
    if kh and close > kh:
        kpos = "Trên Keltner trên: quá mua ngắn hạn"
    elif kl and close < kl:
        kpos = "Dưới Keltner dưới: quá bán ngắn hạn, áp lực bán còn mạnh"
    else:
        kpos = "Trong kênh Keltner"
    hz = f["ma"]["horizons"]
    hz_word = {1: "Tăng", -1: "Giảm", 0: "Hỗn hợp", None: "Không đủ dữ liệu"}
    md = [
        "### 1. Thống kê Xu hướng & Động lượng",
        "| MA | Giá trị | Khoảng cách | Vai trò |",
        "|---|---|---|---|",
        *rows,
        "",
        "| Chỉ báo | Giá trị | Nhận định |",
        "|---|---|---|",
        f"| **ADX** | `{snap['adx']:.2f}` | Xu hướng {f['adx_state']} |",
        f"| **ATR** | `{snap['atr']:.2f}` ({f['atr_pct']:.2f}% giá) | Biến động {f['volatility_state']} |",
        f"| **ROC10 / ROC20** | `{_pct(snap['roc10'])}` / `{_pct(snap['roc20'])}` | Động lượng {f['momentum']['state'].lower()} |",
        f"| **Keltner** | `{_p(kl)} – {_p(kh)}` | {kpos} |",
        "",
        "### 2. Xu hướng theo khung thời gian",
        f"- **Ngắn hạn** (MA10, MA20): {hz_word[hz['Ngắn hạn']]}",
        f"- **Trung hạn** (MA50): {hz_word[hz['Trung hạn']]}",
        f"- **Dài hạn** (MA100, MA200): {hz_word[hz['Dài hạn']]}",
        "",
        "**Ngưỡng giá then chốt:**",
    ]
    if v["support"]:
        md.append(f"- Hỗ trợ: {', '.join(_p(x) for x in v['support'][:2])}")
    if v["resistance"]:
        md.append(f"- Kháng cự: {', '.join(_p(x) for x in v['resistance'][:2])}")
    if v["invalidation"] is not None:
        md.append(f"- Ngưỡng vô hiệu nhận định: {_p(v['invalidation'])} ({v['invalidation_src']})")
    md += ["", f"**Nhận định chung:** {verdict_line(v)}. {action_sentence(v)}"]
    return "\n".join(md) + FOOTER


def build_scenario_md(snap, v, volatility_value=None):
    sup, res = v["support"], v["resistance"]
    s1 = sup[0] if sup else None
    s2 = sup[1] if len(sup) > 1 else None
    r1 = res[0] if res else None
    r2 = res[1] if len(res) > 1 else None
    idx = ACTIONS.index(v["action"])
    up_action = ACTIONS[min(idx + 1, len(ACTIONS) - 1)]
    down_action = ACTIONS[max(idx - 1, 0)]
    main = v["main_scenario"]

    def title(n, key, extra=""):
        tag = " — Kịch bản chính" if key == main else ""
        return f"### {n}. Kịch bản {SCENARIO_LABEL[key].upper()}{extra}{tag}"

    md = [
        f"**Kịch bản chính:** {SCENARIO_LABEL[main]} (theo trạng thái {v['regime']}, độ tin cậy {v['confidence']}). "
        "Tầm nhìn 5–15 phiên.",
        "",
        title(1, "positive"),
        f"- **Điều kiện:** đóng cửa vượt kháng cự {_p(r1)} với KL trên TB20 và A/D ≥ {CONFIG['ad_lean_up']}."
        if r1 else f"- **Điều kiện:** giữ trên mọi MA với KL trên TB20 và A/D ≥ {CONFIG['ad_lean_up']}.",
        f"- **Mục tiêu:** {_p(r2)}." if r2 else "- **Mục tiêu:** chưa có kháng cự kế tiếp trong vùng 52 tuần.",
        f"- **Hành động khi xảy ra:** nâng lên {up_action}.",
        "",
        title(2, "neutral", f" (dao động {_p(s1)} – {_p(r1)})" if s1 and r1 else ""),
        f"- **Điều kiện:** giá đóng cửa trong vùng {_p(s1)} – {_p(r1)}, ADX dưới {CONFIG['adx_strong']}."
        if s1 and r1 else f"- **Điều kiện:** giá đi ngang, ADX dưới {CONFIG['adx_strong']}.",
        f"- **Hành động khi xảy ra:** giữ {v['action']}.",
        "",
        title(3, "negative"),
        f"- **Điều kiện:** đóng cửa thủng hỗ trợ {_p(s1)} với KL trên TB20 và A/D ≤ {CONFIG['ad_lean_down']}."
        if s1 else f"- **Điều kiện:** tiếp tục đóng cửa dưới các MA với KL trên TB20 và A/D ≤ {CONFIG['ad_lean_down']}.",
        f"- **Mục tiêu:** {_p(s2)}." if s2 else "- **Mục tiêu:** chưa có hỗ trợ kế tiếp trong vùng 52 tuần.",
        f"- **Hành động khi xảy ra:** hạ xuống {down_action}.",
        "",
        "### Dẫn chứng",
        f"- **TAS:** {snap['tas_score']:+d}/100 ({snap.get('tas_label', '')}).",
        f"- **Sức mạnh xu hướng:** ADX {snap['adx']:.1f}, xu hướng {v['factors']['adx_state']}.",
        f"- **Biến động:** ATR {v['factors']['atr_pct']:.2f}% giá/phiên ({v['factors']['volatility_state']})"
        + (f"; biên độ 20 phiên {volatility_value:.2f}% giá." if volatility_value is not None else "."),
    ]
    if s1 and r1:
        ds = (snap["close"] - s1) / snap["close"] * 100
        dr = (r1 - snap["close"]) / snap["close"] * 100
        md.append(f"- **Khoảng đệm:** cách hỗ trợ {ds:.2f}%, cách kháng cự {dr:.2f}%.")
    return "\n".join(md) + FOOTER


def build_smc_strategy_md(snap, v):
    """Thay mục 5 của luận giải SMC để hành động khớp với nhận định chung."""
    smc = snap.get("smc") or {}
    lines = ["### 5. Luận giải & Chiến lược Hành động",
             f"**Nhận định chung:** {verdict_line(v)}. {action_sentence(v)}", ""]
    bull = (smc.get("bull_obs") or [None])[0]
    bear = (smc.get("bear_obs") or [None])[0]
    if v["bias"] >= 0 and bull:
        lines.append(f"- **Vùng canh mua theo SMC:** Bullish OB `{_p(bull['btm'])} – {_p(bull['top'])}` "
                     f"(mid-line `{_p(bull['avg'])}`).")
    if v["bias"] <= 0 and bear:
        lines.append(f"- **Vùng hạ tỷ trọng theo SMC:** Bearish OB `{_p(bear['btm'])} – {_p(bear['top'])}` "
                     f"(mid-line `{_p(bear['avg'])}`).")
    t = smc.get("trend")
    if t in (1, -1) and v["bias"] != 0 and t != v["bias"]:
        lines.append(f"- ⚠️ Cấu trúc SMC đang **{'tăng' if t == 1 else 'giảm'}**, ngược với nhận định chung: "
                     "xem là rủi ro, không đổi hành động.")
    choch = smc.get("choch_level")
    if choch is not None:
        lines.append(f"- **Mốc CHoCH:** `{_p(choch)}` — đóng cửa {'dưới' if t == 1 else 'trên'} mốc này "
                     f"là đảo chiều cấu trúc sang {'giảm' if t == 1 else 'tăng'}.")
    return "\n".join(lines)


def replace_smc_strategy(interpretation_md, snap, v):
    if not interpretation_md:
        return interpretation_md
    head = interpretation_md.split("\n### 5.")[0]
    return head + "\n\n" + build_smc_strategy_md(snap, v)


def build_commentary(snap, market_stats_md="", breadth_md="", volatility_value=None):
    """Điểm vào duy nhất: trả về verdict và markdown cho mọi tab."""
    v = build_verdict(snap)
    return {
        "verdict": {
            "regime": v["regime"], "regime_key": v["regime_key"], "rule_no": v["rule_no"],
            "action": v["action"], "base_action": v["base_action"], "confidence": v["confidence"],
            "main_scenario": SCENARIO_LABEL[v["main_scenario"]],
            "invalidation": v["invalidation"], "version": RULES_VERSION,
            "summary": summary_sentence(snap, v),
        },
        "general_markdown": build_general_md(snap, v, market_stats_md, breadth_md),
        "scenario_markdown": build_scenario_md(snap, v, volatility_value),
        "volume_markdown": build_volume_md(snap, v),
        "trend_markdown": build_trend_md(snap, v),
        "_v": v,
    }

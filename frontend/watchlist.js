/* ═══════════════════════════════════════════════════
   watchlist.js — Danh sách Khuyến nghị (MUA / BÁN)
   Lưu trữ: localStorage key "vn_watchlist"
   ═══════════════════════════════════════════════════ */

(function () {
    const LS_KEY = "vn_watchlist";

    function loadList() {
        try { return JSON.parse(localStorage.getItem(LS_KEY) || "[]"); }
        catch { return []; }
    }
    function saveList(list) { localStorage.setItem(LS_KEY, JSON.stringify(list)); }
    function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
    
    function fmt(n) {
        if (n == null || isNaN(n) || n === "") return "—";
        return Number(n).toLocaleString("en-US");
    }
    function fmtPct(n) {
        if (n == null || isNaN(n)) return "—";
        return (n > 0 ? "+" : "") + Number(n).toFixed(2) + "%";
    }

    // Giá tự động từ bảng giá thị trường
    function getAutoMarketPrice(ticker) {
        try {
            const g = window.appData && window.appData["__global__"];
            if (!g) return null;
            const s = (g.raw_stocks || {})[ticker.toUpperCase()];
            if (!s) return null;
            return s.match_price || s.close || s.ref || null;
        } catch { return null; }
    }

    // Giá hiệu lực (ưu tiên giá nhập tay custom_price, nếu không có thì lấy giá thị trường)
    function getEffectiveCurrentPrice(item) {
        if (item.custom_price != null && !isNaN(item.custom_price) && item.custom_price > 0) {
            return parseFloat(item.custom_price);
        }
        return getAutoMarketPrice(item.ticker);
    }

    function render() {
        const list  = loadList();
        const tbody = document.getElementById("watchlist-tbody");
        const empty = document.getElementById("wl-empty");
        if (!tbody) return;
        if (list.length === 0) {
            tbody.innerHTML = "";
            if (empty) empty.style.display = "block";
            return;
        }
        if (empty) empty.style.display = "none";

        tbody.innerHTML = list.map(item => {
            const isSell  = (item.type === "SELL");
            const type    = isSell ? "SELL" : "BUY";
            const autoCur = getAutoMarketPrice(item.ticker);
            const cur     = getEffectiveCurrentPrice(item);
            const rec     = parseFloat(item.rec_price);
            const sl      = parseFloat(item.sl_price) || 0;

            // Tính Lãi/Lỗ:
            // BUY:  Lãi = Giá HT - Giá KN
            // SELL: Lãi = Giá KN - Giá HT
            let pnlAbs = null;
            let pnlPct = null;
            if (cur != null && rec > 0) {
                pnlAbs = isSell ? (rec - cur) : (cur - rec);
                pnlPct = (pnlAbs / rec) * 100;
            }

            const pColor = pnlPct == null ? "#94a3b8" : (pnlPct > 0 ? "#10e89a" : (pnlPct < 0 ? "#ff4d6d" : "#94a3b8"));

            // Check Stoploss hit:
            // BUY:  cur <= sl
            // SELL: cur >= sl (nếu sl > 0)
            let slHit = false;
            if (cur != null && sl > 0) {
                slHit = isSell ? (cur >= sl) : (cur <= sl);
            }
            const slStyle = slHit ? "color:#ff4d6d;font-weight:700;" : "";

            // Badge MUA / BÁN
            const badgeHtml = isSell 
                ? `<span class="wl-badge wl-badge-sell">🔴 BÁN</span>`
                : `<span class="wl-badge wl-badge-buy">🟢 MUA</span>`;

            // Ô nhập giá hiện tại (editable inline)
            const inputVal = item.custom_price != null ? item.custom_price : (autoCur != null ? autoCur : "");
            const isManual = item.custom_price != null && item.custom_price !== "";

            const curPriceCell = `
                <td>
                    <div style="display:flex;align-items:center;gap:4px">
                        <input type="number" class="wl-price-edit" data-id="${item.id}" value="${inputVal}" placeholder="${autoCur != null ? autoCur : 'Tự nhập'}" title="${isManual ? 'Giá do bạn tự nhập (xóa để dùng giá thị trường)' : 'Giá thị trường (gõ vào để đổi)'}" />
                        ${isManual ? `<button class="btn-icon btn-reset-price" data-id="${item.id}" title="Khôi phục giá thị trường" style="color:#f59e0b;font-size:0.75rem;padding:2px"><i class='bx bx-reset'></i></button>` : ''}
                    </div>
                </td>
            `;

            // Ô Lãi / Lỗ
            const pnlCell = pnlPct == null
                ? `<td style="color:#64748b">—</td>`
                : `<td style="color:${pColor};font-weight:600;">${fmtPct(pnlPct)}<br><small style="font-weight:400;font-size:0.75rem">${pnlAbs > 0 ? "+" : ""}${fmt(Math.round(pnlAbs))}đ</small></td>`;

            return `<tr class="wl-row${slHit ? ' wl-sl-hit' : ''}">
                <td>${badgeHtml}</td>
                <td><span class="wl-ticker">${item.ticker}</span></td>
                <td style="color:#94a3b8;font-size:0.82rem">${item.date || '—'}</td>
                <td>${fmt(rec)}</td>
                ${curPriceCell}
                <td style="${slStyle}">${sl > 0 ? fmt(sl) : '—'}${slHit ? ' ⚠️' : ''}</td>
                ${pnlCell}
                <td><button class="btn-wl-del btn-icon" data-id="${item.id}" title="Xóa"><i class='bx bx-trash' style="color:#ff4d6d"></i></button></td>
            </tr>`;
        }).join("");

        // Gắn sự kiện sửa giá trực tiếp trong ô table
        tbody.querySelectorAll(".wl-price-edit").forEach(input => {
            input.addEventListener("change", (e) => {
                const id = e.target.dataset.id;
                const val = e.target.value.trim();
                const list2 = loadList();
                const item = list2.find(x => x.id === id);
                if (item) {
                    if (val !== "" && !isNaN(val) && parseFloat(val) > 0) {
                        item.custom_price = parseFloat(val);
                    } else {
                        delete item.custom_price;
                    }
                    saveList(list2);
                    render();
                }
            });
        });

        // Gắn sự kiện reset giá về giá thị trường
        tbody.querySelectorAll(".btn-reset-price").forEach(btn => {
            btn.addEventListener("click", () => {
                const id = btn.dataset.id;
                const list2 = loadList();
                const item = list2.find(x => x.id === id);
                if (item) {
                    delete item.custom_price;
                    saveList(list2);
                    render();
                }
            });
        });

        // Gắn sự kiện xóa
        tbody.querySelectorAll(".btn-wl-del").forEach(btn => {
            btn.addEventListener("click", () => {
                saveList(loadList().filter(x => x.id !== btn.dataset.id));
                render();
            });
        });
    }

    function openPanel() {
        const panel = document.getElementById("watchlist-panel");
        const ov    = document.getElementById("watchlist-overlay");
        if (panel) { panel.style.display = "flex"; panel.classList.add("open"); }
        if (ov)    { ov.style.display = "block"; }
        render();
        const d = document.getElementById("wl-date");
        if (d && !d.value) d.value = new Date().toISOString().slice(0, 10);
    }
    function closePanel() {
        const panel = document.getElementById("watchlist-panel");
        const ov    = document.getElementById("watchlist-overlay");
        if (panel) { panel.classList.remove("open"); panel.style.display = "none"; }
        if (ov)    { ov.style.display = "none"; }
    }

    function addEntry() {
        const type     = document.getElementById("wl-type")?.value || "BUY";
        const ticker   = (document.getElementById("wl-ticker")?.value || "").trim().toUpperCase();
        const rec      = parseFloat(document.getElementById("wl-rec-price")?.value);
        const curInput = parseFloat(document.getElementById("wl-cur-price")?.value);
        const sl       = parseFloat(document.getElementById("wl-sl-price")?.value) || 0;
        const date     = document.getElementById("wl-date")?.value || new Date().toISOString().slice(0, 10);

        if (!ticker) { alert("Vui lòng nhập mã CP!"); return; }
        if (!rec || rec <= 0) { alert("Vui lòng nhập giá khuyến nghị!"); return; }

        const list = loadList();
        const newItem = { id: uid(), type, ticker, rec_price: rec, sl_price: sl, date };
        if (!isNaN(curInput) && curInput > 0) {
            newItem.custom_price = curInput;
        }

        list.unshift(newItem);
        saveList(list);

        ["wl-ticker","wl-rec-price","wl-cur-price","wl-sl-price"].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = "";
        });
        render();
    }

    window.addWatchlistFromSwing = function(ticker, recPrice, slPrice) {
        if (!ticker) return;
        const list = loadList();
        const exists = list.some(x => x.ticker === ticker.toUpperCase());
        if (!exists) {
            list.unshift({
                id: uid(),
                type: "BUY",
                ticker: ticker.toUpperCase(),
                rec_price: parseFloat(recPrice) || 0,
                sl_price: parseFloat(slPrice) || 0,
                date: new Date().toISOString().slice(0, 10)
            });
            saveList(list);
        }
        openPanel();
    };

    function init() {
        document.getElementById("btn-open-watchlist")?.addEventListener("click", openPanel);
        document.getElementById("btn-close-watchlist")?.addEventListener("click", closePanel);
        document.getElementById("watchlist-overlay")?.addEventListener("click", closePanel);
        document.getElementById("btn-wl-add")?.addEventListener("click", addEntry);
        
        ["wl-ticker","wl-rec-price","wl-cur-price","wl-sl-price","wl-date"].forEach(id => {
            document.getElementById(id)?.addEventListener("keydown", e => { if (e.key === "Enter") addEntry(); });
        });

        // Auto-fill price and stoploss when typing ticker in add form
        document.getElementById("wl-ticker")?.addEventListener("input", e => {
            const sym = (e.target.value || "").trim().toUpperCase();
            if (sym.length >= 3) {
                const curPrice = getAutoMarketPrice(sym);
                const recIn = document.getElementById("wl-rec-price");
                const curIn = document.getElementById("wl-cur-price");
                const slIn = document.getElementById("wl-sl-price");
                if (curPrice && recIn && !recIn.value) {
                    recIn.value = curPrice;
                }
                if (curPrice && curIn && !curIn.value) {
                    curIn.value = curPrice;
                }
                const g = window.appData && window.appData["__global__"];
                const stock = (g?.raw_stocks || {})[sym];
                if (stock && stock.swing_tsl && slIn && !slIn.value) {
                    slIn.value = stock.swing_tsl;
                }
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else { init(); }
})();

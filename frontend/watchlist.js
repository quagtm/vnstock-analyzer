/* ═══════════════════════════════════════════════════
   watchlist.js — Danh sách Khuyến nghị
   Lưu trữ: localStorage key "vn_watchlist"
   Giá hiện tại: lấy từ window.appData.__global__.raw_stocks
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
        if (n == null || isNaN(n)) return "—";
        return Number(n).toLocaleString("en-US");
    }
    function fmtPct(n) {
        if (n == null || isNaN(n)) return "—";
        return (n > 0 ? "+" : "") + n.toFixed(2) + "%";
    }

    function getCurrentPrice(ticker) {
        try {
            const g = window.appData && window.appData["__global__"];
            if (!g) return null;
            const s = (g.raw_stocks || {})[ticker.toUpperCase()];
            if (!s) return null;
            return s.match_price || s.close || s.ref || null;
        } catch { return null; }
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
            const cur     = getCurrentPrice(item.ticker);
            const rec     = parseFloat(item.rec_price);
            const sl      = parseFloat(item.sl_price);
            const pnlAbs  = (cur != null && rec) ? (cur - rec) : null;
            const pnlPct  = (cur != null && rec) ? ((cur - rec) / rec * 100) : null;
            const pColor  = pnlPct == null ? "#94a3b8" : (pnlPct > 0 ? "#4ade80" : (pnlPct < 0 ? "#f87171" : "#94a3b8"));
            const slHit   = (cur != null && sl) ? cur <= sl : false;
            const slStyle = slHit ? "color:#f87171;font-weight:700;" : "";
            const pnlCell = pnlPct == null
                ? "<td style=\"color:#64748b\">—</td>"
                : "<td style=\"color:" + pColor + ";font-weight:600;\">" + fmtPct(pnlPct) + "<br><small style=\"font-weight:400;font-size:0.75rem\">" + (pnlAbs > 0 ? "+" : "") + fmt(Math.round(pnlAbs)) + "đ</small></td>";
            return "<tr class=\"wl-row" + (slHit ? " wl-sl-hit" : "") + "\">" +
                "<td><span class=\"wl-ticker\">" + item.ticker + "</span></td>" +
                "<td style=\"color:#94a3b8;font-size:0.82rem\">" + (item.date || "—") + "</td>" +
                "<td>" + fmt(rec) + "</td>" +
                "<td style=\"font-weight:600\">" + (cur != null ? fmt(cur) : "<span style=\"color:#64748b\">—</span>") + "</td>" +
                "<td style=\"" + slStyle + "\">" + fmt(sl) + (slHit ? " 🔴" : "") + "</td>" +
                pnlCell +
                "<td><button class=\"btn-wl-del btn-icon\" data-id=\"" + item.id + "\" title=\"Xóa\"><i class=\"bx bx-trash\" style=\"color:#f87171\"></i></button></td>" +
                "</tr>";
        }).join("");

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
        const ticker = (document.getElementById("wl-ticker")?.value || "").trim().toUpperCase();
        const rec    = parseFloat(document.getElementById("wl-rec-price")?.value);
        const sl     = parseFloat(document.getElementById("wl-sl-price")?.value) || 0;
        const date   = document.getElementById("wl-date")?.value || new Date().toISOString().slice(0, 10);
        if (!ticker) { alert("Vui lòng nhập mã CP!"); return; }
        if (!rec || rec <= 0) { alert("Vui lòng nhập giá khuyến nghị!"); return; }
        const list = loadList();
        list.unshift({ id: uid(), ticker, rec_price: rec, sl_price: sl, date });
        saveList(list);
        ["wl-ticker","wl-rec-price","wl-sl-price"].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = "";
        });
        render();
    }

    function init() {
        document.getElementById("btn-open-watchlist")?.addEventListener("click", openPanel);
        document.getElementById("btn-close-watchlist")?.addEventListener("click", closePanel);
        document.getElementById("watchlist-overlay")?.addEventListener("click", closePanel);
        document.getElementById("btn-wl-add")?.addEventListener("click", addEntry);
        ["wl-ticker","wl-rec-price","wl-sl-price","wl-date"].forEach(id => {
            document.getElementById(id)?.addEventListener("keydown", e => { if (e.key === "Enter") addEntry(); });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else { init(); }
})();

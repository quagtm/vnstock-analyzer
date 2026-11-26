// ─── Định giá ngành từ SSI (public/ssi_sectors.json) ─────────────
// File JSON được làm mới bởi một phiên Claude gọi SSI MCP
// (xem data_pipeline/ssi_mcp/README.md). Script này chỉ đọc và hiển thị.
(function () {
    const EX_LABEL = { VNINDEX: 'VN-Index', HOHAUP: 'HOSE', HNXINDEX: 'HNX' };
    let ssiData = null;
    let currentEx = 'VNINDEX';
    let sortKey = 'market_cap';
    let sortDir = -1;

    const esc = s => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const num = (v, d = 1) => (v == null || !isFinite(v) || v === 0) ? '—' : v.toFixed(d);
    const pct = v => (v == null || !isFinite(v) || v === 0) ? '—' : (v * 100).toFixed(1) + '%';
    const capTn = v => (v == null || !v) ? '—' : Math.round(v / 1e12).toLocaleString('vi-VN');

    const COLS = [
        { key: 'name',              label: 'Ngành',        fmt: null },
        { key: 'pe',                label: 'P/E',          fmt: v => num(v, 1) },
        { key: 'pb',                label: 'P/B',          fmt: v => num(v, 2) },
        { key: 'roe',               label: 'ROE',          fmt: pct },
        { key: 'net_profit_margin', label: 'Biên LN ròng', fmt: pct },
        { key: 'sale_growth_rate',  label: 'Tăng trưởng DT', fmt: pct },
        { key: 'market_cap',        label: 'Vốn hóa (nghìn tỷ)', fmt: capTn },
    ];

    function metricsFor(s) {
        return (s.metrics || {})[currentEx] || null;
    }

    function render() {
        const box = document.getElementById('ssi-sector-panel');
        if (!box || !ssiData) return;
        const sectors = (ssiData.sectors || []).filter(s => metricsFor(s));

        sectors.sort((a, b) => {
            if (sortKey === 'name') return sortDir * a.name.localeCompare(b.name, 'vi');
            const va = (metricsFor(a) || {})[sortKey] ?? -Infinity;
            const vb = (metricsFor(b) || {})[sortKey] ?? -Infinity;
            return sortDir * (va - vb);
        });

        const asOf = ssiData.as_of ? new Date(ssiData.as_of) : null;
        const asOfTxt = asOf && !isNaN(asOf)
            ? asOf.toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'short', timeStyle: 'short' })
            : '';

        const exBtns = (ssiData.exchanges || []).map(e =>
            `<button class="ssi-ex-btn${e === currentEx ? ' active' : ''}" data-ex="${esc(e)}">${esc(EX_LABEL[e] || e)}</button>`
        ).join('');

        const head = COLS.map(c => {
            const arrow = c.key === sortKey ? (sortDir > 0 ? ' ▲' : ' ▼') : '';
            return `<th data-sort="${c.key}">${c.label}${arrow}</th>`;
        }).join('');

        const rows = sectors.map(s => {
            const m = metricsFor(s);
            const cells = COLS.slice(1).map(c => `<td>${c.fmt(m[c.key])}</td>`).join('');
            const a = s.assessment;
            const icon = a ? `<i class='bx bx-chevron-down ssi-toggle'></i>` : '';
            const main = `<tr class="ssi-row${a ? ' has-note' : ''}" data-code="${esc(s.icb_code)}">
                <td class="ssi-name">${icon}${esc(s.name)}</td>${cells}</tr>`;
            const note = a ? `<tr class="ssi-note" data-note="${esc(s.icb_code)}" style="display:none"><td colspan="${COLS.length}">
                <div class="ssi-note-title">Nhận định SSI Research · ${esc(a.title)}</div>
                <div class="ssi-note-text">${esc(a.text).replace(/\n/g, '<br>')}</div></td></tr>` : '';
            return main + note;
        }).join('');

        box.innerHTML = `
            <div class="ssi-head">
                <label><i class='bx bx-bar-chart-square'></i> Định giá ngành (SSI)</label>
                <div class="ssi-ex">${exBtns}</div>
            </div>
            <div class="ssi-table-wrap">
                <table class="ssi-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>
            </div>
            <div class="ssi-foot">Nguồn: SSI (ICB cấp 2, bình quân theo rổ ${esc(EX_LABEL[currentEx] || currentEx)})${asOfTxt ? ' · cập nhật ' + esc(asOfTxt) : ''}. Bấm vào ngành để xem nhận định SSI Research.</div>`;

        box.querySelectorAll('.ssi-ex-btn').forEach(b => b.onclick = () => { currentEx = b.dataset.ex; render(); });
        box.querySelectorAll('th[data-sort]').forEach(th => th.onclick = () => {
            const k = th.dataset.sort;
            if (k === sortKey) sortDir = -sortDir; else { sortKey = k; sortDir = k === 'name' ? 1 : -1; }
            render();
        });
        box.querySelectorAll('tr.ssi-row.has-note').forEach(tr => tr.onclick = () => {
            const note = box.querySelector(`tr.ssi-note[data-note="${tr.dataset.code}"]`);
            if (!note) return;
            const open = note.style.display === 'none';
            note.style.display = open ? '' : 'none';
            tr.classList.toggle('open', open);
        });
    }

    // #ssi-sector-panel nằm trong <template id="dashboard-template">, được app.js
    // clone lại mỗi lần đổi mã/tab. Theo dõi DOM để vẽ lại khi panel mới xuất hiện.
    function renderIfEmpty() {
        const box = document.getElementById('ssi-sector-panel');
        if (box && ssiData && !box.hasChildNodes()) render();
    }

    async function load() {
        try {
            const res = await fetch(`public/ssi_sectors.json?v=${Date.now()}`);
            if (!res.ok) throw new Error(res.status);
            ssiData = await res.json();
            if (!(ssiData.exchanges || []).includes(currentEx)) currentEx = (ssiData.exchanges || [])[0];
        } catch (e) {
            console.warn('[SSI sectors] không tải được ssi_sectors.json:', e);
            return;
        }
        renderIfEmpty();
        const root = document.getElementById('dashboard-content') || document.body;
        new MutationObserver(renderIfEmpty).observe(root, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
})();

// ─── Top tăng / giảm / cổ phiếu hot từ SSI (public/ssi_top_stocks.json) ───
// File JSON được làm mới bởi một phiên Claude gọi SSI MCP
// (xem data_pipeline/ssi_mcp/README.md). Script này chỉ đọc và hiển thị.
(function () {
    let data = null;
    let currentEx = 'HOSE';

    const esc = s => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const bn = v => (v / 1e9).toLocaleString('vi-VN', { maximumFractionDigits: 1 });
    const vol = v => v >= 1e6 ? (v / 1e6).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + 'tr'
        : v >= 1e3 ? Math.round(v / 1e3).toLocaleString('vi-VN') + 'k' : Math.round(v).toLocaleString('vi-VN');

    function pctCell(p) {
        const cls = p > 0 ? 'up' : p < 0 ? 'down' : 'ref';
        return `<span class="ssi-mv-pct ${cls}">${p > 0 ? '+' : ''}${p.toFixed(2)}%</span>`;
    }

    function list(title, icon, rows, extra) {
        const body = rows.length
            ? rows.map((r, i) => `<li><span class="ssi-mv-rank">${i + 1}</span><span class="ssi-mv-sym">${esc(r.symbol)}</span>${pctCell(r.change_pct)}<span class="ssi-mv-extra">${extra(r)}</span></li>`).join('')
            : '<li class="ssi-mv-empty">Chưa có dữ liệu</li>';
        return `<div class="ssi-mv-col"><div class="ssi-mv-title">${icon} ${title}</div><ol>${body}</ol></div>`;
    }

    function render() {
        const box = document.getElementById('ssi-top-stocks');
        if (!box || !data) return;
        const ex = (data.exchanges || {})[currentEx] || {};
        const exBtns = Object.keys(data.exchanges || {}).map(e =>
            `<button class="ssi-ex-btn${e === currentEx ? ' active' : ''}" data-ex="${esc(e)}">${esc(e)}</button>`).join('');
        const period = data.to_date ? `phiên ${esc(data.to_date)} và phiên trước` : '2 phiên gần nhất';

        box.innerHTML = `
            <div class="ssi-head">
                <label><i class='bx bx-trophy'></i> Top cổ phiếu (SSI)</label>
                <div class="ssi-ex">${exBtns}</div>
            </div>
            <div class="ssi-mv-grid">
                ${list('Tăng mạnh nhất', "<i class='bx bx-trending-up' style='color:var(--positive)'></i>", ex.gainers || [], r => vol(r.avg_volume) + ' CP')}
                ${list('Giảm mạnh nhất', "<i class='bx bx-trending-down' style='color:var(--negative)'></i>", ex.losers || [], r => vol(r.avg_volume) + ' CP')}
                ${list('Hot nhất (GTGD)', "<i class='bx bxs-hot' style='color:#ff9f43'></i>", ex.hot || [], r => bn(r.avg_value) + ' tỷ')}
            </div>
            <div class="ssi-foot">Nguồn: SSI · thay đổi giá gộp ${period}; khối lượng và giá trị giao dịch là bình quân mỗi phiên.</div>`;

        box.querySelectorAll('.ssi-ex-btn').forEach(b => b.onclick = () => { currentEx = b.dataset.ex; render(); });
    }

    async function load() {
        const box = document.getElementById('ssi-top-stocks');
        if (!box) return;
        try {
            const res = await fetch(`public/ssi_top_stocks.json?v=${Date.now()}`);
            if (!res.ok) throw new Error(res.status);
            data = await res.json();
            const exs = Object.keys(data.exchanges || {});
            if (!exs.includes(currentEx)) currentEx = exs[0];
            box.style.display = '';
            render();
        } catch (e) {
            console.warn('[SSI top] không tải được ssi_top_stocks.json:', e);
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load);
    else load();
})();

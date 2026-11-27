/* ═══════════════════════════════════════════════════
   portfolio.js — Danh mục cổ phiếu đang nắm giữ
   Dữ liệu: public/portfolio.json (pipeline đêm sinh ra từ portfolio.json ở gốc repo)
   Mỗi mã: ngày mua, luận điểm mua, mô tả kỹ thuật, ATR và SMC.
   ═══════════════════════════════════════════════════ */

(function () {
    let pfData = null;
    let loading = null;

    const esc = s => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const fmtP = n => (n == null || isNaN(n)) ? '—' : Math.round(n).toLocaleString('en-US');
    const fmtPct = n => (n == null || isNaN(n)) ? '—' : (n > 0 ? '+' : '') + Number(n).toFixed(2) + '%';
    const pnlCls = n => n > 0.001 ? 'pf-pos' : (n < -0.001 ? 'pf-neg' : 'pf-flat');

    function mdToHtml(md) {
        let html = window.marked ? marked.parse(md || '') : `<pre>${esc(md)}</pre>`;
        html = html.replace(/\b(Bullish|TĂNG|NẮM GIỮ|Vùng Cầu)\b/g, '<span class="pf-txt-bull">$1</span>');
        html = html.replace(/\b(Bearish|GIẢM|Vùng Cung|THOÁT)\b/g, '<span class="pf-txt-bear">$1</span>');
        return html;
    }

    async function loadPortfolio() {
        if (pfData) return pfData;
        if (loading) return loading;
        loading = (async () => {
            for (const url of ['public/portfolio.json', 'portfolio.json']) {
                try {
                    const r = await fetch(url, { cache: 'no-cache' });
                    if (r.ok) { pfData = await r.json(); return pfData; }
                } catch (e) { /* thử đường dẫn tiếp theo */ }
            }
            throw new Error('Chưa có file portfolio.json — pipeline sẽ tạo sau lần chạy kế tiếp.');
        })();
        try { return await loading; } finally { loading = null; }
    }

    // ── Thang mức giá: stop → giá mua → giá hiện tại → mục tiêu ──
    function ladderHtml(h) {
        const a = h.atr || {}, s = h.smc_levels || {};
        const marks = [];
        if (a.trailing_stop) marks.push({ p: a.trailing_stop, label: 'Trailing stop', cls: 'stop' });
        if (a.initial_stop && Math.abs(a.initial_stop - a.trailing_stop) > 1) marks.push({ p: a.initial_stop, label: 'Stop ban đầu', cls: 'stop dim' });
        if (s.smc_stop) marks.push({ p: s.smc_stop, label: 'Stop SMC', cls: 'smc' });
        marks.push({ p: h.buy_price, label: 'Giá mua', cls: 'buy' });
        (a.targets || []).forEach(t => marks.push({ p: t.price, label: t.label + (t.hit ? ' ✓' : ''), cls: 'target' + (t.hit ? ' hit' : '') }));
        (s.targets || []).slice(0, 2).forEach(t => marks.push({ p: t.price, label: t.label, cls: 'smc-tg' }));
        if (a.user_target) marks.push({ p: a.user_target, label: 'Mục tiêu', cls: 'target' });
        const prices = marks.map(m => m.p).concat([h.close]).filter(x => x != null);
        let lo = Math.min(...prices), hi = Math.max(...prices);
        const pad = (hi - lo) * 0.06 || hi * 0.02;
        lo -= pad; hi += pad;
        const x = p => ((p - lo) / (hi - lo) * 100).toFixed(2);
        marks.sort((m1, m2) => m1.p - m2.p);
        const items = marks.map((m, i) => `
            <div class="pf-mark ${m.cls} ${i % 2 ? 'down' : 'up'}" style="left:${x(m.p)}%" title="${esc(m.label)}: ${fmtP(m.p)}">
                <span class="pf-mark-lbl">${esc(m.label)}<b>${fmtP(m.p)}</b></span>
            </div>`).join('');
        const rows = marks.concat([{ p: h.close, label: 'Giá hiện tại', cls: 'now' }])
            .sort((m1, m2) => m2.p - m1.p)
            .map(m => `<div class="pf-levels-row ${m.cls}"><span><i></i>${esc(m.label)}</span><span>${fmtP(m.p)}</span></div>`).join('');
        const inRisk = h.close < h.buy_price;
        const zoneL = x(Math.min(h.buy_price, h.close)), zoneR = x(Math.max(h.buy_price, h.close));
        return `
            <div class="pf-ladder">
                <div class="pf-ladder-track">
                    <div class="pf-ladder-zone ${inRisk ? 'neg' : 'pos'}" style="left:${zoneL}%;width:${(zoneR - zoneL).toFixed(2)}%"></div>
                    ${items}
                    <div class="pf-mark now" style="left:${x(h.close)}%" title="Giá hiện tại: ${fmtP(h.close)}">
                        <span class="pf-mark-lbl">Giá HT<b>${fmtP(h.close)}</b></span>
                    </div>
                </div>
            </div>
            <div class="pf-levels">${rows}</div>`;
    }

    function kpi(label, val, sub, cls) {
        return `<div class="pf-kpi"><span class="pf-kpi-lbl">${label}</span><strong class="${cls || ''}">${val}</strong><span class="pf-kpi-sub">${sub || ''}</span></div>`;
    }

    function cardHtml(h, idx) {
        const a = h.atr || {}, t = h.technical || {}, smc = h.smc || {};
        const trend = smc.trend === 1 ? ['Bullish', 'pf-pos'] : smc.trend === -1 ? ['Bearish', 'pf-neg'] : ['Neutral', 'pf-flat'];
        const qty = h.quantity ? `${Number(h.quantity).toLocaleString('en-US')} cp` : '';
        const pnlVal = h.pnl_value != null ? ` · ${h.pnl_value > 0 ? '+' : ''}${fmtP(h.pnl_value)} đ` : '';
        return `
        <article class="pf-card glass" data-idx="${idx}">
            <header class="pf-card-head">
                <div class="pf-head-left">
                    <span class="pf-ticker">${esc(h.symbol)}</span>
                    <span class="pf-verdict ${esc(h.verdict_tone)}">${esc(h.verdict)}</span>
                </div>
                <div class="pf-head-right">
                    <span class="pf-close">${fmtP(h.close)}</span>
                    <span class="pf-pnl ${pnlCls(h.pnl_pct)}">${fmtPct(h.pnl_pct)}${pnlVal}</span>
                </div>
            </header>
            <div class="pf-meta">
                <span><i class='bx bx-calendar'></i> Mua ${esc(h.buy_date)} · ${h.sessions_held} phiên (${h.days_held} ngày)</span>
                <span><i class='bx bx-purchase-tag'></i> Giá mua ${fmtP(h.buy_price)}${qty ? ' · ' + qty : ''}</span>
                <span><i class='bx bx-time-five'></i> Dữ liệu ${esc(h.last_date)}</span>
            </div>
            <div class="pf-thesis">
                <div class="pf-sec-title"><i class='bx bx-bulb'></i> Luận điểm mua</div>
                <p>${h.thesis ? esc(h.thesis) : '<em>Chưa ghi luận điểm — thêm trường "thesis" trong portfolio.json.</em>'}</p>
                ${h.note ? `<p class="pf-note">${esc(h.note)}</p>` : ''}
            </div>
            <div class="pf-summary">${mdToHtml(h.summary)}</div>
            ${ladderHtml(h)}
            <div class="pf-kpis">
                ${kpi('ATR(14)', `${fmtP(a.atr)} <small>(${a.atr_pct != null ? a.atr_pct.toFixed(2) : '—'}%)</small>`, `Biến động ${esc(a.regime || '')}`)}
                ${kpi('Trailing stop', fmtP(a.trailing_stop), `Cách giá ${a.dist_trailing_atr != null ? a.dist_trailing_atr.toFixed(1) : '—'} ATR`, a.dist_trailing_atr < 1 ? 'pf-neg' : '')}
                ${kpi('Vị thế (R)', `${a.r_multiple > 0 ? '+' : ''}${a.r_multiple != null ? a.r_multiple.toFixed(2) : '—'}R`, `1R = ${fmtP(a.risk_r)} đ`, pnlCls(a.r_multiple))}
                ${kpi('Cấu trúc SMC', trend[0], smc.choch_level ? `CHoCH ${fmtP(smc.choch_level)}` : '', trend[1])}
                ${kpi('RSI / ADX', `${t.rsi ?? '—'} / ${t.adx ?? '—'}`, esc((t.ma_state || '').split('(')[0]))}
            </div>
            <div class="pf-tabs">
                <button class="pf-tab active" data-tab="desc">📋 Mô tả chi tiết</button>
                <button class="pf-tab" data-tab="chart">🕯️ Biểu đồ SMC</button>
                <button class="pf-tab" data-tab="smc">🧠 Luận giải SMC đầy đủ</button>
            </div>
            <div class="pf-tab-panel markdown-body" data-panel="desc">${mdToHtml(h.description_markdown)}</div>
            <div class="pf-tab-panel" data-panel="chart" style="display:none">
                <div class="pf-chart-wrap"><canvas></canvas></div>
                <p class="pf-chart-note">80 phiên gần nhất · Order Block, FVG, BOS/CHoCH tính theo BigBeluga SMC.</p>
            </div>
            <div class="pf-tab-panel markdown-body" data-panel="smc" style="display:none">${mdToHtml(smc.interpretation_markdown || 'Chưa có dữ liệu SMC.')}</div>
        </article>`;
    }

    function render() {
        const body = document.getElementById('pf-body');
        const meta = document.getElementById('pf-meta-line');
        if (!body) return;
        const d = pfData || {};
        const list = d.holdings || [];
        const tot = d.totals || {};
        if (meta) {
            const parts = [`${list.length} mã`];
            if (tot.value) parts.push(`Giá trị ${fmtP(tot.value)} đ`);
            if (tot.pnl_pct != null) parts.push(`<span class="${pnlCls(tot.pnl_pct)}">Lãi/Lỗ ${fmtPct(tot.pnl_pct)}</span>`);
            if (d.generated_at) parts.push(`Cập nhật ${esc(d.generated_at)}`);
            meta.innerHTML = parts.join(' · ');
        }
        const errs = (d.errors || []).map(e => `<li><b>${esc(e.symbol)}</b>: ${esc(e.error)}</li>`).join('');
        if (!list.length) {
            body.innerHTML = `<div class="pf-empty glass">
                <i class='bx bx-briefcase-alt-2'></i>
                <h3>Danh mục trống</h3>
                <p>Thêm mã vào file <code>portfolio.json</code> ở gốc repo (symbol, buy_date, buy_price, thesis). Pipeline đêm sẽ tự tính ATR & SMC.</p>
                ${errs ? `<ul class="pf-errors">${errs}</ul>` : ''}
            </div>`;
            return;
        }
        body.innerHTML = list.map(cardHtml).join('') + (errs ? `<div class="pf-empty glass"><p>Không phân tích được:</p><ul class="pf-errors">${errs}</ul></div>` : '');
    }

    function drawChart(card) {
        const h = (pfData.holdings || [])[+card.dataset.idx];
        const canvas = card.querySelector('[data-panel="chart"] canvas');
        if (!h || !h.smc || !canvas) return;
        if (typeof window.drawSMCChart === 'function') {
            window.drawSMCChart(canvas, h.smc, { showOB: true, showFVG: true, showMS: true });
        } else {
            canvas.parentElement.innerHTML = '<p class="pf-chart-note">Không tải được bộ vẽ biểu đồ SMC.</p>';
        }
    }

    function onBodyClick(e) {
        const tab = e.target.closest('.pf-tab');
        if (!tab) return;
        const card = tab.closest('.pf-card');
        card.querySelectorAll('.pf-tab').forEach(b => b.classList.toggle('active', b === tab));
        card.querySelectorAll('.pf-tab-panel').forEach(p => { p.style.display = p.dataset.panel === tab.dataset.tab ? '' : 'none'; });
        if (tab.dataset.tab === 'chart') requestAnimationFrame(() => drawChart(card));
    }

    async function open() {
        document.getElementById('portfolio-overlay').style.display = 'block';
        document.getElementById('portfolio-panel').style.display = 'flex';
        const body = document.getElementById('pf-body');
        if (!pfData) body.innerHTML = '<div class="pf-empty"><i class="bx bx-loader-alt bx-spin"></i><p>Đang tải danh mục…</p></div>';
        try {
            await loadPortfolio();
            render();
        } catch (err) {
            body.innerHTML = `<div class="pf-empty glass"><i class='bx bx-error-circle'></i><p>${esc(err.message)}</p></div>`;
        }
    }

    function close() {
        document.getElementById('portfolio-overlay').style.display = 'none';
        document.getElementById('portfolio-panel').style.display = 'none';
    }

    function init() {
        const btn = document.getElementById('btn-open-portfolio');
        if (!btn) return;
        btn.addEventListener('click', open);
        document.getElementById('btn-close-portfolio').addEventListener('click', close);
        document.getElementById('portfolio-overlay').addEventListener('click', close);
        document.getElementById('pf-body').addEventListener('click', onBodyClick);
        document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
        let rT;
        window.addEventListener('resize', () => {
            clearTimeout(rT);
            rT = setTimeout(() => document.querySelectorAll('.pf-card').forEach(c => {
                const p = c.querySelector('[data-panel="chart"]');
                if (p && p.style.display !== 'none') drawChart(c);
            }), 200);
        });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();

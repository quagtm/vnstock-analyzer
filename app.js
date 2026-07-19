document.addEventListener('DOMContentLoaded', () => {
    let appData = null;
    let currentSymbol = 'VNINDEX';
    let currentMiniTab = 'general';
    let tasChartInstance = null;

    const dashboardContent = document.getElementById('dashboard-content');
    const pageTitle = document.getElementById('page-title');
    const updateDate = document.getElementById('update-date');

    // Setup Markdown Options
    if (window.marked) {
        marked.setOptions({
            breaks: true,
            gfm: true
        });
    }

    // Fetch Data với cache-busting để luôn lấy dữ liệu mới nhất
    async function fetchData() {
        const ts = Date.now(); // timestamp để bypass browser cache
        try {
            const response = await fetch(`public/data.json?v=${ts}`);
            if (!response.ok) {
                const fallbackResponse = await fetch(`data.json?v=${ts}`);
                if (!fallbackResponse.ok) throw new Error("Data not found");
                appData = await fallbackResponse.json();
            } else {
                appData = await response.json();
            }
            if (!appData) throw new Error("Dữ liệu trống");
            initSectorModal(appData);
            renderDashboard();
        } catch (error) {
            console.error('Error fetching data:', error);
            dashboardContent.innerHTML = `
                <div class="glass" style="padding: 32px; text-align: center; color: var(--negative);">
                    <i class='bx bx-error-circle' style="font-size: 48px; margin-bottom: 16px;"></i>
                    <h3>Lỗi tải dữ liệu</h3>
                    <p>Không thể kết nối đến máy chủ hoặc dữ liệu chưa được cập nhật.</p>
                    <p style="font-size: 12px; opacity: 0.7; margin-top: 10px;">Chi tiết lỗi: ${error.message}</p>
                </div>
            `;
        }
    }

    // Tự động reload data mỗi 5 phút (300.000ms)
    setInterval(() => {
        console.log('[Auto-refresh] Reloading data...');
        fetchData();
    }, 5 * 60 * 1000);

    // ─── Candle Pattern Badges ────────────────────────────────────
    function renderCandleBadges(patterns) {
        const el = document.getElementById('candle-badges');
        if (!el) return;
        if (!patterns || patterns.length === 0) { el.style.display = 'none'; return; }
        el.style.display = 'flex';
        el.innerHTML = patterns.map(p => {
            const cls = p.type === 'bullish' ? 'badge-bull' : p.type === 'bearish' ? 'badge-bear' : 'badge-neutral';
            return `<div class="candle-badge ${cls}">
                <span class="badge-name">${p.name}</span>
                <span class="badge-desc">${p.desc}</span>
            </div>`;
        }).join('');
    }

    // ─── S/R Zones Strip ─────────────────────────────────────────
    function renderSRZones(zones) {
        const el = document.getElementById('sr-zones');
        if (!el) return;
        if (!zones || zones.length === 0) { el.style.display = 'none'; return; }
        el.style.display = 'flex';
        const items = zones.map(z => {
            const isNear = z.near;
            const cls  = z.type === 'resistance' ? 'sr-resist' : 'sr-support';
            const nearBadge = isNear ? '<span class="sr-near">⚠️ Gần</span>' : '';
            const sign = z.dist_pct >= 0 ? '+' : '';
            return `<div class="sr-zone ${cls} ${isNear ? 'sr-zone-near' : ''}">
                <span class="sr-type">${z.type === 'resistance' ? '🔴 KC' : '🟢 HT'}</span>
                <span class="sr-level">${z.level.toFixed(2)}</span>
                <span class="sr-dist">${sign}${z.dist_pct.toFixed(1)}%</span>
                ${nearBadge}
            </div>`;
        }).join('');
        el.innerHTML = `<div class="sr-label"><i class='bx bx-layer'></i> Hỗ trợ / Kháng cự (52 tuần)</div><div class="sr-zones-list">${items}</div>`;
    }

    // ─── Sector Heatmap ───────────────────────────────────────────
    function renderSectorHeatmap(sectors) {
        const el = document.getElementById('sector-heatmap');
        if (!el) return;
        if (!sectors || sectors.length === 0) { el.innerHTML = '<span style="color:var(--text-secondary);font-size:.8rem;padding:8px">Chưa có dữ liệu ngành</span>'; return; }
        el.innerHTML = sectors.map(s => {
            const v   = s.avg_change;
            const abs = Math.abs(v);
            // Color intensity: capped at 3%
            const intensity = Math.min(abs / 3, 1);
            const r = v < 0 ? Math.round(255 * intensity) : 0;
            const g = v > 0 ? Math.round(180 * intensity) : 0;
            const alpha = 0.08 + intensity * 0.35;
            const bg  = v > 0 ? `rgba(16,232,154,${alpha})` : v < 0 ? `rgba(255,77,109,${alpha})` : 'rgba(255,255,255,0.05)';
            const clr = v > 0 ? '#10e89a' : v < 0 ? '#ff4d6d' : '#94a3b8';
            const sign = v >= 0 ? '+' : '';
            return `<div class="sector-cell" style="background:${bg};border-color:${clr}22;">
                <span class="sector-name">${s.sector}</span>
                <span class="sector-chg" style="color:${clr}">${sign}${v.toFixed(2)}%</span>
                <span class="sector-cnt">${s.count} CP</span>
            </div>`;
        }).join('');
    }

    // ─── TAS Multi-chart (50 phiên) ───────────────────────────────
    const _tasCharts = {};

    window.switchTASTab = function(tab) {
        ['score','price','macd','stoch'].forEach(t => {
            const panel = document.getElementById(`tas-chart-${t}`);
            const btn   = document.getElementById(`tab-tas-${t}`);
            if (panel) panel.style.display = t === tab ? 'block' : 'none';
            if (btn)   btn.classList.toggle('active', t === tab);
        });
        // Trigger Chart.js resize after display
        const c = _tasCharts[tab];
        if (c) c.resize();
    };

    function _destroyTASCharts() {
        Object.values(_tasCharts).forEach(c => { try { c.destroy(); } catch(e) {} });
        Object.keys(_tasCharts).forEach(k => delete _tasCharts[k]);
    }

    function _chartDefaults(title) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 400 },
            plugins: {
                legend: { display: true, labels: { color: 'rgba(255,255,255,0.7)', boxWidth: 12, font: { size: 11 } } },
                tooltip: { mode: 'index', intersect: false,
                    titleColor: '#fff', bodyColor: 'rgba(255,255,255,0.85)',
                    backgroundColor: 'rgba(15,23,42,0.95)' }
            },
            scales: {
                x: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: 'rgba(255,255,255,0.5)', maxTicksLimit: 12, font: { size: 10 } } },
                y: { grid: { color: 'rgba(255,255,255,0.07)' }, ticks: { color: 'rgba(255,255,255,0.55)', font: { size: 10 } } }
            }
        };
    }

    function renderTASChart(history) {  // kept for compatibility — calls renderTASCharts
        renderTASCharts(history);
    }

    function renderTASCharts(history) {
        _destroyTASCharts();
        if (!history || history.length < 2) return;

        const fmt = d => {
            if (!d || d.startsWith('D')) return d;
            const p = d.split('-');
            return p.length >= 3 ? p[2] + '/' + p[1] : d;
        };
        const labels = history.map(h => fmt(h.date));
        const N = history.length;

        // ── Chart 1: TAS Score ──────────────────────────────────────
        const cvScore = document.getElementById('tas-history-chart');
        if (cvScore) {
            const scores = history.map(h => h.score);
            _tasCharts['score'] = new Chart(cvScore, {
                type: 'line',
                data: {
                    labels,
                    datasets: [{
                        label: 'TAS Score',
                        data: scores,
                        borderColor: '#4f8ef7',
                        backgroundColor: 'rgba(79,142,247,0.08)',
                        borderWidth: 2,
                        pointBackgroundColor: scores.map(s =>
                            s >= 34 ? '#4ade80' : s >= 1 ? '#a3e635' : s >= -33 ? '#fb923c' : '#f87171'),
                        pointRadius: N <= 30 ? 4 : 2,
                        fill: true, tension: 0.35
                    }]
                },
                options: { ..._chartDefaults('TAS Score'),
                    plugins: { ..._chartDefaults().plugins, legend: { display: false },
                        annotation: undefined },
                    scales: {
                        x: _chartDefaults().scales.x,
                        y: { ..._chartDefaults().scales.y, min: -100, max: 100,
                            ticks: { color: 'rgba(255,255,255,0.55)', font: { size: 10 },
                                callback: v => v + '%' } }
                    }
                }
            });
        }

        // ── Chart 2: Giá + MA20/MA50 + Bollinger Bands ─────────────
        const cvPrice = document.getElementById('tas-price-chart');
        if (cvPrice) {
            const closes   = history.map(h => h.close   || null);
            const ma20arr  = history.map(h => h.ma20    || null);
            const ma50arr  = history.map(h => h.ma50    || null);
            const bbUpper  = history.map(h => h.bb_upper || null);
            const bbLower  = history.map(h => h.bb_lower || null);
            _tasCharts['price'] = new Chart(cvPrice, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        { label: 'BB Upper', data: bbUpper, borderColor: 'rgba(148,163,184,0.3)',
                          borderWidth: 1, borderDash: [4,3], pointRadius: 0, fill: '+1',
                          backgroundColor: 'rgba(148,163,184,0.05)', tension: 0.2 },
                        { label: 'BB Lower', data: bbLower, borderColor: 'rgba(148,163,184,0.3)',
                          borderWidth: 1, borderDash: [4,3], pointRadius: 0, fill: false, tension: 0.2 },
                        { label: 'Giá đóng', data: closes, borderColor: '#f8fafc',
                          borderWidth: 2, pointRadius: 0, fill: false, tension: 0.2 },
                        { label: 'MA20', data: ma20arr, borderColor: '#fbbf24',
                          borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.2 },
                        { label: 'MA50', data: ma50arr, borderColor: '#60a5fa',
                          borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.2 },
                    ]
                },
                options: _chartDefaults('Giá + BB')
            });
        }

        // ── Chart 3: MACD ────────────────────────────────────────────
        const cvMACD = document.getElementById('tas-macd-chart');
        if (cvMACD) {
            const macdLine = history.map(h => h.macd        || null);
            const sigLine  = history.map(h => h.macd_signal || null);
            const hist     = history.map(h => h.macd_diff   || null);
            _tasCharts['macd'] = new Chart(cvMACD, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        { label: 'Histogram', data: hist, type: 'bar',
                          backgroundColor: hist.map(v => v >= 0 ? 'rgba(74,222,128,0.5)' : 'rgba(248,113,113,0.5)'),
                          yAxisID: 'y' },
                        { label: 'MACD', data: macdLine, type: 'line',
                          borderColor: '#4f8ef7', borderWidth: 1.5, pointRadius: 0,
                          fill: false, tension: 0.3, yAxisID: 'y' },
                        { label: 'Signal', data: sigLine, type: 'line',
                          borderColor: '#fb923c', borderWidth: 1.5, pointRadius: 0,
                          fill: false, tension: 0.3, yAxisID: 'y' },
                    ]
                },
                options: _chartDefaults('MACD')
            });
        }

        // ── Chart 4: Stochastic %K/%D ────────────────────────────────
        const cvStoch = document.getElementById('tas-stoch-chart');
        if (cvStoch) {
            const kLine = history.map(h => h.stoch_k || null);
            const dLine = history.map(h => h.stoch_d || null);
            _tasCharts['stoch'] = new Chart(cvStoch, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        { label: '%K', data: kLine, borderColor: '#a78bfa', borderWidth: 1.5,
                          pointRadius: 0, fill: false, tension: 0.3 },
                        { label: '%D', data: dLine, borderColor: '#f472b6', borderWidth: 1.5,
                          pointRadius: 0, fill: false, tension: 0.3, borderDash: [4,3] },
                    ]
                },
                options: {
                    ..._chartDefaults('Stochastic'),
                    scales: {
                        x: _chartDefaults().scales.x,
                        y: { ..._chartDefaults().scales.y, min: 0, max: 100,
                            ticks: { color: 'rgba(255,255,255,0.55)', font: { size: 10 } } }
                    },
                    plugins: {
                        ..._chartDefaults().plugins,
                        annotation: {
                            annotations: {
                                ob: { type: 'line', yMin: 80, yMax: 80, borderColor: 'rgba(248,113,113,0.4)', borderWidth: 1, borderDash: [4,3], label: { content: 'Overbought 80', display: true, color: 'rgba(248,113,113,0.7)', font: { size: 9 } } },
                                os: { type: 'line', yMin: 20, yMax: 20, borderColor: 'rgba(74,222,128,0.4)', borderWidth: 1, borderDash: [4,3], label: { content: 'Oversold 20', display: true, color: 'rgba(74,222,128,0.7)', font: { size: 9 } } }
                            }
                        }
                    }
                }
            });
        }
    }


    function renderSectorTable(sectors) {
        const tbody = document.getElementById('sector-table-body');
        if (!tbody) return;
        tbody.innerHTML = '';
        
        if (!sectors || sectors.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4">Không có dữ liệu ngành</td></tr>';
            return;
        }

        sectors.forEach(s => {
            const tr = document.createElement('tr');
            
            // Name & Tickers
            const tdName = document.createElement('td');
            const nameDiv = document.createElement('div');
            nameDiv.textContent = s.sector;
            tdName.appendChild(nameDiv);
            
            if (s.tickers && s.tickers.length > 0) {
                const tickDiv = document.createElement('div');
                tickDiv.style.fontSize = '0.75rem';
                tickDiv.style.color = 'var(--text-secondary)';
                tickDiv.style.marginTop = '4px';
                tickDiv.style.maxWidth = '250px';
                tickDiv.style.whiteSpace = 'normal';
                tickDiv.style.lineHeight = '1.4';
                // Show up to 15 tickers, then append ... if more
                const displayTickers = s.tickers.length > 15 ? s.tickers.slice(0, 15).join(', ') + '...' : s.tickers.join(', ');
                tickDiv.textContent = displayTickers;
                tdName.appendChild(tickDiv);
            }
            
            // Change
            const tdChange = document.createElement('td');
            const chg = (s.avg_change || 0);
            const isPos = chg > 0;
            const isNeg = chg < 0;
            tdChange.textContent = (isPos ? '+' : '') + chg.toFixed(2) + '%';
            tdChange.style.color = isPos ? 'var(--positive)' : (isNeg ? 'var(--negative)' : 'var(--text-secondary)');
            
            // Value
            const tdVal = document.createElement('td');
            tdVal.textContent = (s.total_val || 0).toLocaleString('vi-VN', {maximumFractionDigits: 2});
            
            // Money Flow Bar
            const tdFlow = document.createElement('td');
            const capUp = s.cap_up || 0;
            const capDown = s.cap_down || 0;
            const capRef = s.cap_ref || 0;
            const totalCap = capUp + capDown + capRef;
            
            let pctUp = 0, pctDown = 0, pctRef = 0;
            if (totalCap > 0) {
                pctUp = (capUp / totalCap) * 100;
                pctDown = (capDown / totalCap) * 100;
                pctRef = (capRef / totalCap) * 100;
            }
            
            const barWrap = document.createElement('div');
            barWrap.className = 'money-flow-bar';
            
            if (pctUp > 0) {
                const bUp = document.createElement('div');
                bUp.className = 'flow-up';
                bUp.style.width = pctUp + '%';
                barWrap.appendChild(bUp);
            }
            if (pctRef > 0) {
                const bRef = document.createElement('div');
                bRef.className = 'flow-ref';
                bRef.style.width = pctRef + '%';
                barWrap.appendChild(bRef);
            }
            if (pctDown > 0) {
                const bDown = document.createElement('div');
                bDown.className = 'flow-down';
                bDown.style.width = pctDown + '%';
                barWrap.appendChild(bDown);
            }
            
            tdFlow.appendChild(barWrap);
            
            tr.appendChild(tdName);
            tr.appendChild(tdChange);
            tr.appendChild(tdVal);
            tr.appendChild(tdFlow);
            
            tbody.appendChild(tr);
        });
    }

    function renderTASChart(history) {
        const canvas = document.getElementById('tas-history-chart');
        if (!canvas || !history || history.length < 2) return;

        if (tasChartInstance) {
            tasChartInstance.destroy();
        }

        const labels = history.map(h => {
            const dateStr = h.date;
            if(dateStr.startsWith('D')) return dateStr;
            const parts = dateStr.split('-');
            if(parts.length >= 3) return parts[2] + '/' + parts[1];
            return dateStr;
        });
        const scores = history.map(h => h.score);

        tasChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'TAS Score',
                    data: scores,
                    borderColor: '#4f8ef7',
                    backgroundColor: 'rgba(79, 142, 247, 0.1)',
                    borderWidth: 2,
                    pointBackgroundColor: scores.map(s => s >= 34 ? '#4ade80' : s >= 0 ? '#a3e635' : s >= -33 ? '#fb923c' : '#f87171'),
                    pointRadius: 4,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `Score: ${context.parsed.y}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: 'rgba(255,255,255,0.6)' }
                    },
                    y: {
                        min: -100,
                        max: 100,
                        grid: { color: 'rgba(255,255,255,0.1)' },
                        ticks: { color: 'rgba(255,255,255,0.6)' }
                    }
                }
            }
        });
    }

    // ─── TAS Renderer ────────────────────────────────────────────────
    function renderTAS(tas) {
        if (!tas) return;

        const score  = tas.score;   // -100 → +100
        const label  = tas.label;
        const indics = tas.indicators || [];

        // Score text — hiển thị dương 0–100%, càng cao càng tốt (không dấu âm)
        const pctEl  = document.getElementById('tas-pct');
        const lblEl  = document.getElementById('tas-label');
        if (pctEl)  pctEl.textContent  = (score > 0 ? '+' : '') + score + '%';
        if (lblEl) {
            lblEl.textContent = label;
            lblEl.className   = 'tas-label ' + (
                label.includes('STRONG BULL') ? 'lbl-sbull' :
                label.includes('BULL')        ? 'lbl-bull'  :
                label.includes('STRONG BEAR') ? 'lbl-sbear' :
                label.includes('BEAR')        ? 'lbl-bear'  : 'lbl-neutral'
            );
        }

        // Gauge arc — arc total length ≈ 251px for a 80r semicircle
        const arcFill   = document.getElementById('tas-arc-fill');
        const needle    = document.getElementById('tas-needle');
        if (arcFill && needle) {
            const ARC_LEN  = 251;
            const pct01    = (score + 100) / 200;  // 0 → 1
            const offset   = ARC_LEN * (1 - pct01);
            arcFill.style.strokeDashoffset = offset;

            // Color by zone
            const color = score >= 34 ? '#4ade80' : score >= 1 ? '#a3e635' :
                          score === 0 ? '#94a3b8' : score >= -33 ? '#fb923c' : '#f87171';
            arcFill.style.stroke = color;

            // Needle: 0% = -90deg (left), 100% = +90deg (right)
            const deg = (pct01 * 180) - 90;
            needle.setAttribute('transform', `rotate(${deg}, 100, 100)`);
        }

        // Agreement Grid
        const tbody = document.getElementById('tas-grid-body');
        const tfoot = document.getElementById('tas-grid-foot');
        if (!tbody) return;
        tbody.innerHTML = '';
        let prevGroup = '';
        indics.forEach(ind => {
            const tr = document.createElement('tr');
            const dotClass = ind.status === 'Bullish' ? 'dot-bull' :
                             ind.status === 'Bearish' ? 'dot-bear' : 'dot-neutral';
            const scoreStr = ind.score > 0 ? `+${ind.score}` : `${ind.score}`;
            const groupCell = ind.group !== prevGroup
                ? `<td class="tas-group-cell" rowspan="1">${ind.group}</td>`
                : '<td class="tas-group-hidden"></td>';
            prevGroup = ind.group;
            tr.innerHTML = `
                ${groupCell}
                <td class="tas-name-cell">${ind.name}</td>
                <td><span class="tas-dot ${dotClass}"></span> <span class="tas-status">${ind.status}</span></td>
                <td class="tas-score-cell ${ind.score > 0 ? 'pos' : ind.score < 0 ? 'neg' : ''}">${scoreStr}</td>
            `;
            tbody.appendChild(tr);
        });

        // Footer total — dùng score với dấu +/-
        if (tfoot) {
            const scoreStr = (score > 0 ? '+' : '') + score + '%';
            tfoot.innerHTML = `
                <tr class="tas-total-row">
                    <td colspan="2"><strong>T\u1ed4NG \u0110I\u1ec2M</strong></td>
                    <td><strong>${label}</strong></td>
                    <td class="tas-score-cell ${score > 0 ? 'pos' : score < 0 ? 'neg' : ''}"><strong>${scoreStr}</strong></td>
                </tr>`;
        }
    }

    function renderDashboard() {

        if (!appData || !appData[currentSymbol]) {
            dashboardContent.innerHTML = `
                <div class="glass" style="padding: 32px; text-align: center;">
                    <p>Dữ liệu cho ${currentSymbol} đang được xử lý hoặc không có sẵn.</p>
                </div>
            `;
            return;
        }

        const data = appData[currentSymbol];
        
        // Update Titles
        pageTitle.textContent = `${currentSymbol} Dashboard`;
        updateDate.textContent = data.date || "N/A";

        // Use Template
        const template = document.getElementById('dashboard-template');
        const clone = template.content.cloneNode(true);

        // Format numbers
        const formatNum = (num) => new Intl.NumberFormat('vi-VN').format(num);
        
        const closeSpan = clone.getElementById('val-close');
        const changeSpan = clone.getElementById('val-change');
        const scoreCard = clone.getElementById('score-card');
        
        if (closeSpan && data.change_pc !== undefined) {
            const isPositive = data.change_pc > 0;
            const isNegative = data.change_pc < 0;
            const sign = isPositive ? '+' : '';
            
            let color = 'var(--flat)';
            let bgGlow = 'rgba(251, 191, 36, 0.05)';
            if (isPositive) { color = 'var(--positive)'; bgGlow = 'var(--positive-glow)'; }
            else if (isNegative) { color = 'var(--negative)'; bgGlow = 'var(--negative-glow)'; }
            
            closeSpan.textContent = formatNum(data.close);
            closeSpan.style.color = color;
            
            if (changeSpan) {
                const changeAbs = (data.change > 0 ? '+' : '') + (data.change || 0).toFixed(2);
                const changePc = sign + data.change_pc.toFixed(2) + '%';
                changeSpan.textContent = `(${changeAbs}  ${changePc})`;
                changeSpan.style.color = color;
            }
            
            if (scoreCard) {
                scoreCard.style.borderColor = color;
                scoreCard.style.boxShadow = `0 0 15px ${bgGlow}`;
            }
        } else if (closeSpan) {
            closeSpan.textContent = formatNum(data.close);
        }

        clone.getElementById('val-volume').textContent = formatNum(data.volume);
        clone.getElementById('val-pivot').textContent = data.technical.pivot ? formatNum(data.technical.pivot) : 'N/A';
        clone.getElementById('val-ma20').textContent = data.technical.ma20 ? formatNum(data.technical.ma20) : 'N/A';

        // Add to DOM first so we can attach events
        dashboardContent.innerHTML = '';
        dashboardContent.appendChild(clone);

        const markdownContainer = document.getElementById('markdown-content');
        const analysisTitle = document.getElementById('analysis-title');

        // Set Title & Content
        let markdownText = "";
        let titleText = "";
        if (currentMiniTab === 'general') {
            titleText = "Phân tích Tổng quan";
            markdownText = data.general_markdown || data.analysis_markdown || "Không có dữ liệu.";
        } else if (currentMiniTab === 'scenario') {
            titleText = "Kịch bản Thị trường";
            markdownText = data.scenario_markdown || "Không có dữ liệu kịch bản.";
        } else if (currentMiniTab === 'volume') {
            titleText = "Phân tích Dòng tiền (Khối lượng)";
            markdownText = data.volume_markdown || "Không có dữ liệu.";
        } else if (currentMiniTab === 'trend') {
            titleText = "Phân tích Xu hướng (Biến động)";
            markdownText = data.trend_markdown || "Không có dữ liệu.";
        }

        if (analysisTitle) {
            analysisTitle.textContent = titleText;
        }

        if (markdownContainer) {
            let html = "";
            if (window.marked) {
                html = marked.parse(markdownText);
            } else {
                html = "<p>" + markdownText + "</p>";
            }
            
            // Auto-highlight logic
            html = html.replace(/\b(giảm)\s*([\d.,]+)?(\s*%|\s*điểm|\s*CP)?/gi, '<span style="color: var(--negative); font-weight: 600;">$&</span>');
            html = html.replace(/\b(tăng)\s*([\d.,]+)?(\s*%|\s*điểm|\s*CP)?/gi, '<span style="color: var(--positive); font-weight: 600;">$&</span>');
            html = html.replace(/\b(thấp hơn)\s*([\d.,]+)?(\s*%|\s*điểm|\s*CP)?/gi, '<span style="color: var(--negative); font-weight: 600;">$&</span>');
            html = html.replace(/\b(cao hơn)\s*([\d.,]+)?(\s*%|\s*điểm|\s*CP)?/gi, '<span style="color: var(--positive); font-weight: 600;">$&</span>');
            html = html.replace(/\b(Hỗ trợ|tích cực)\b/gi, '<span style="color: var(--positive); font-weight: 600;">$&</span>');
            html = html.replace(/\b(Kháng cự|tiêu cực)\b/gi, '<span style="color: var(--negative); font-weight: 600;">$&</span>');

            markdownContainer.innerHTML = html;

            // ── Outsidebox highlight: scan tables sau khi inject HTML ──
            markdownContainer.querySelectorAll('table').forEach(table => {
                const rows = Array.from(table.querySelectorAll('tbody tr'));
                // Tô màu tất cả cell chứa % (dương/âm)
                rows.forEach(row => {
                    row.querySelectorAll('td').forEach(td => {
                        const txt = td.textContent.trim();
                        const match = txt.match(/([+-]?\d+\.?\d*)\s*%/);
                        if (match) {
                            const val = parseFloat(match[1]);
                            if (val > 0) td.classList.add('cell-positive');
                            else if (val < 0) td.classList.add('cell-negative');
                        }
                    });
                });
                // Highlight hàng đầu (top tăng) và hàng cuối (top giảm) — outsidebox style
                if (rows.length >= 2) {
                    rows[0].classList.add('row-top-gain');
                    rows[rows.length - 1].classList.add('row-top-loss');
                }
            });
        }

        // Render TAS + sparkline + narrative
        const tas = data.tas;
        if (tas) {
            renderTAS(tas);
            renderTASChart(tas.history || []);
        }

        // Render candle pattern badges
        renderCandleBadges(data.candle_patterns || []);

        // Render S/R zones strip
        renderSRZones(data.sr_zones || []);

        // Render sector heatmap
        let sectorData = data.sector_heatmap || [];
        if (typeof customSectors !== 'undefined' && customSectors && appData['__global__'] && appData['__global__'].raw_stocks) {
            sectorData = computeCustomSectors(appData['__global__'].raw_stocks) || sectorData;
        }

        renderSectorHeatmap(sectorData);
        renderSectorTable(sectorData);
        
        if (window.bindEditSectorButton) window.bindEditSectorButton();
    }

    // Expose for sectors.js
    window.renderDashboard = renderDashboard;

    // Navigation setup
    const containers = document.querySelectorAll('.nav-item-container');
    const subNavItems = document.querySelectorAll('.sub-nav-item');

    // Handle clicking main symbols (accordion)
    containers.forEach(container => {
        const navItem = container.querySelector('.nav-item');
        navItem.addEventListener('click', () => {
            // If already active, don't collapse (or you can toggle it)
            if(!container.classList.contains('active')) {
                // Collapse all others
                containers.forEach(c => c.classList.remove('active'));
                container.classList.add('active');
                
                // Select first sub-tab automatically
                currentSymbol = container.getAttribute('data-symbol');
                currentMiniTab = 'general';
                
                // Update active state of sub-tabs
                const allSubTabs = document.querySelectorAll('.sub-nav-item');
                allSubTabs.forEach(t => t.classList.remove('active'));
                const firstTab = container.querySelector('.sub-nav-item[data-tab="general"]');
                if(firstTab) firstTab.classList.add('active');

                if (appData) renderDashboard();
            }
        });
    });

    // Handle clicking sub-tabs
    subNavItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.stopPropagation(); // prevent triggering parent
            
            // Update active state of sub-tabs globally
            document.querySelectorAll('.sub-nav-item').forEach(t => t.classList.remove('active'));
            item.classList.add('active');

            const parentContainer = item.closest('.nav-item-container');
            
            currentSymbol = parentContainer.getAttribute('data-symbol');
            currentMiniTab = item.getAttribute('data-tab');

            // Ensure parent is active
            document.querySelectorAll('.nav-item-container').forEach(c => c.classList.remove('active'));
            parentContainer.classList.add('active');

            if (appData) renderDashboard();
        });
    });

    // Init
    fetchData();
});

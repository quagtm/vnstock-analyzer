/**
 * Smart Screener Module
 * Bộ Lọc Cổ Phiếu Thông Minh Đa Tiêu Chí
 */

(function () {
    let currentRawStocks = {};
    let activePreset = 'all';

    // State của các bộ lọc
    const filters = {
        keyword: '',
        sector: 'all',
        signal: 'all',
        priceChange: 'all',
        volume: 'all',
        sortBy: 'chg_desc'
    };

    function initScreener() {
        const btnOpen = document.getElementById('btn-open-screener');
        const btnClose = document.getElementById('btn-close-screener');
        const overlay = document.getElementById('screener-overlay');
        const panel = document.getElementById('screener-panel');

        if (btnOpen) {
            btnOpen.addEventListener('click', openScreener);
        }
        if (btnClose) {
            btnClose.addEventListener('click', closeScreener);
        }
        if (overlay) {
            overlay.addEventListener('click', closeScreener);
        }

        // Setup filter input listeners
        setupFilterListeners();
    }

    function openScreener() {
        const overlay = document.getElementById('screener-overlay');
        const panel = document.getElementById('screener-panel');
        if (overlay) overlay.style.display = 'block';
        if (panel) panel.style.display = 'flex';

        // Load sector dropdown options if needed
        populateSectorDropdown();

        // Load data from global appData
        loadDataAndRender();
    }

    function closeScreener() {
        const overlay = document.getElementById('screener-overlay');
        const panel = document.getElementById('screener-panel');
        if (overlay) overlay.style.display = 'none';
        if (panel) panel.style.display = 'none';
    }

    function populateSectorDropdown() {
        const select = document.getElementById('scr-sector');
        if (!select || select.options.length > 1) return;

        const globalData = window.appData && window.appData.__global__;
        const raw = (globalData && globalData.raw_stocks) || {};
        const sectors = new Set();

        Object.values(raw).forEach(s => {
            if (s.sector && s.sector !== 'Tất cả HOSE' && s.sector !== 'Khác') {
                sectors.add(s.sector);
            }
        });

        Array.from(sectors).sort().forEach(sec => {
            const opt = document.createElement('option');
            opt.value = sec;
            opt.textContent = sec;
            select.appendChild(opt);
        });
    }

    function setupFilterListeners() {
        const kw = document.getElementById('scr-keyword');
        const sec = document.getElementById('scr-sector');
        const sig = document.getElementById('scr-signal');
        const chg = document.getElementById('scr-change');
        const vol = document.getElementById('scr-volume');
        const sort = document.getElementById('scr-sort');
        const btnReset = document.getElementById('btn-scr-reset');

        if (kw) {
            kw.addEventListener('input', (e) => {
                filters.keyword = e.target.value.trim().toUpperCase();
                activePreset = null;
                updatePresetButtonsUI();
                renderFilteredStocks();
            });
        }
        if (sec) {
            sec.addEventListener('change', (e) => {
                filters.sector = e.target.value;
                activePreset = null;
                updatePresetButtonsUI();
                renderFilteredStocks();
            });
        }
        if (sig) {
            sig.addEventListener('change', (e) => {
                filters.signal = e.target.value;
                activePreset = null;
                updatePresetButtonsUI();
                renderFilteredStocks();
            });
        }
        if (chg) {
            chg.addEventListener('change', (e) => {
                filters.priceChange = e.target.value;
                activePreset = null;
                updatePresetButtonsUI();
                renderFilteredStocks();
            });
        }
        if (vol) {
            vol.addEventListener('change', (e) => {
                filters.volume = e.target.value;
                activePreset = null;
                updatePresetButtonsUI();
                renderFilteredStocks();
            });
        }
        if (sort) {
            sort.addEventListener('change', (e) => {
                filters.sortBy = e.target.value;
                renderFilteredStocks();
            });
        }
        if (btnReset) {
            btnReset.addEventListener('click', () => {
                applyPreset('all');
            });
        }

        // Preset buttons
        document.querySelectorAll('.scr-preset-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const preset = btn.getAttribute('data-preset');
                applyPreset(preset);
            });
        });
    }

    function applyPreset(presetName) {
        activePreset = presetName;
        updatePresetButtonsUI();

        // Reset default inputs
        const kw = document.getElementById('scr-keyword');
        const sec = document.getElementById('scr-sector');
        const sig = document.getElementById('scr-signal');
        const chg = document.getElementById('scr-change');
        const vol = document.getElementById('scr-volume');
        const sort = document.getElementById('scr-sort');

        filters.keyword = '';
        filters.sector = 'all';
        filters.signal = 'all';
        filters.priceChange = 'all';
        filters.volume = 'all';
        filters.sortBy = 'chg_desc';

        if (kw) kw.value = '';
        if (sec) sec.value = 'all';

        switch (presetName) {
            case 'swing_buy':
                filters.signal = 'swing_buy';
                if (sig) sig.value = 'swing_buy';
                break;
            case 'strong_leader':
                filters.signal = 'is_strong';
                filters.volume = 'val_20b';
                if (sig) sig.value = 'is_strong';
                if (vol) vol.value = 'val_20b';
                break;
            case 'vol_breakout':
                filters.volume = 'vol_15x';
                filters.priceChange = 'up_2';
                if (vol) vol.value = 'vol_15x';
                if (chg) chg.value = 'up_2';
                break;
            case 'new_high_52w':
                filters.signal = 'new_high_52w';
                if (sig) sig.value = 'new_high_52w';
                break;
            case 'uptrend_gain':
                filters.signal = 'uptrend';
                filters.priceChange = 'up_3';
                if (sig) sig.value = 'uptrend';
                if (chg) chg.value = 'up_3';
                break;
            case 'swing_sell':
                filters.signal = 'swing_sell';
                if (sig) sig.value = 'swing_sell';
                break;
            case 'all':
            default:
                if (sig) sig.value = 'all';
                if (chg) chg.value = 'all';
                if (vol) vol.value = 'all';
                break;
        }

        if (sort) sort.value = filters.sortBy;
        renderFilteredStocks();
    }

    function updatePresetButtonsUI() {
        document.querySelectorAll('.scr-preset-btn').forEach(btn => {
            const preset = btn.getAttribute('data-preset');
            if (preset === activePreset) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    function loadDataAndRender() {
        const globalData = window.appData && window.appData.__global__;
        if (!globalData || !globalData.raw_stocks) {
            console.warn('[SmartScreener] Chưa có raw_stocks data');
            return;
        }
        currentRawStocks = globalData.raw_stocks;
        renderFilteredStocks();
    }

    function renderFilteredStocks() {
        const tbody = document.getElementById('scr-tbody');
        const countSpan = document.getElementById('scr-count');
        const totalSpan = document.getElementById('scr-total');
        if (!tbody) return;

        const allStocks = Object.values(currentRawStocks);
        if (totalSpan) totalSpan.textContent = allStocks.length;

        // Apply filters
        let results = allStocks.filter(s => {
            // Keyword
            if (filters.keyword && !s.symbol.includes(filters.keyword)) {
                return false;
            }

            // Sector
            if (filters.sector !== 'all' && s.sector !== filters.sector) {
                return false;
            }

            // Signal
            if (filters.signal === 'swing_buy' && !s.swing_buy) return false;
            if (filters.signal === 'swing_sell' && !s.swing_sell) return false;
            if (filters.signal === 'uptrend' && s.swing_trend !== 'BUY') return false;
            if (filters.signal === 'is_strong' && !s.is_strong) return false;
            if (filters.signal === 'is_uptrend' && !s.is_uptrend) return false;
            if (filters.signal === 'new_high_52w' && !s.is_new_high_52w) return false;

            // Price Change
            const chg = parseFloat(s.change_pc) || 0;
            if (filters.priceChange === 'up' && chg <= 0) return false;
            if (filters.priceChange === 'up_2' && chg < 2.0) return false;
            if (filters.priceChange === 'up_3' && chg < 3.0) return false;
            if (filters.priceChange === 'ceil' && chg < 6.7) return false;
            if (filters.priceChange === 'down' && chg >= 0) return false;

            // Volume & Value
            const vol = s.volume || 0;
            const valB = s.accumulated_value || 0;
            if (filters.volume === 'vol_sma5' && !s.is_vol_breakout_5) return false;
            if (filters.volume === 'vol_15x' && !s.is_vol_breakout_20) return false;
            if (filters.volume === 'vol_500k' && vol < 500000) return false;
            if (filters.volume === 'vol_1m' && vol < 1000000) return false;
            if (filters.volume === 'val_10b' && valB < 10) return false;
            if (filters.volume === 'val_20b' && valB < 20) return false;
            if (filters.volume === 'val_50b' && valB < 50) return false;

            return true;
        });

        // Sorting
        results.sort((a, b) => {
            const chgA = parseFloat(a.change_pc) || 0;
            const chgB = parseFloat(b.change_pc) || 0;
            const valA = parseFloat(a.accumulated_value) || 0;
            const valB = parseFloat(b.accumulated_value) || 0;
            const volA = parseFloat(a.volume) || 0;
            const volB = parseFloat(b.volume) || 0;

            switch (filters.sortBy) {
                case 'chg_desc': return chgB - chgA;
                case 'chg_asc': return chgA - chgB;
                case 'val_desc': return valB - valA;
                case 'vol_desc': return volB - volA;
                case 'ticker_asc': return a.symbol.localeCompare(b.symbol);
                default: return chgB - chgA;
            }
        });

        if (countSpan) countSpan.textContent = results.length;

        if (results.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" style="text-align:center;padding:40px 20px;color:#64748b;">
                        <i class='bx bx-search-alt' style="font-size:2rem;margin-bottom:8px;display:block;"></i>
                        Không tìm thấy cổ phiếu nào thỏa mãn các tiêu chí lọc. Thử đổi bộ lọc khác!
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = results.map(s => {
            const chg = parseFloat(s.change_pc) || 0;
            const chgColor = chg > 0 ? '#10e89a' : (chg < 0 ? '#ff4d6d' : '#94a3b8');
            const chgSign = chg > 0 ? '+' : '';
            const price = s.match_price || 0;
            const valB = s.accumulated_value || 0;
            const vol = s.volume || 0;
            const tsl = s.swing_tsl || 0;

            // Badges
            let tagsHtml = '';
            if (s.swing_buy) {
                tagsHtml += `<span class="scr-tag scr-tag-buy">🟢 MUA QW</span>`;
            } else if (s.swing_sell) {
                tagsHtml += `<span class="scr-tag scr-tag-sell">🔴 BÁN QW</span>`;
            } else if (s.swing_trend === 'BUY') {
                tagsHtml += `<span class="scr-tag scr-tag-trend">🚀 Uptrend</span>`;
            }

            if (s.is_strong) {
                tagsHtml += `<span class="scr-tag scr-tag-strong" title="Giá > MA20 > MA50 > MA200">💪 Siêu Khỏe</span>`;
            }
            if (s.is_vol_breakout_20) {
                tagsHtml += `<span class="scr-tag scr-tag-vol" title="Vol >= 1.5x TB 20 phiên">⚡ Vol x${s.vol_ratio_20 || 1.5}</span>`;
            }
            if (s.is_new_high_52w) {
                tagsHtml += `<span class="scr-tag scr-tag-high" title="Vượt đỉnh 52 tuần">🏆 Đỉnh 52W</span>`;
            }

            if (!tagsHtml) {
                tagsHtml = `<span style="color:#64748b;font-size:0.75rem">—</span>`;
            }

            return `
                <tr class="scr-row">
                    <td>
                        <span class="scr-ticker">${s.symbol}</span>
                    </td>
                    <td style="color:#cbd5e1;font-size:0.82rem;">${s.sector || 'Tất cả HOSE'}</td>
                    <td style="font-weight:700;font-size:0.9rem;color:#f8fafc;">${formatNumber(price)}</td>
                    <td style="font-weight:700;font-size:0.9rem;color:${chgColor};">${chgSign}${chg.toFixed(2)}%</td>
                    <td style="color:#94a3b8;font-size:0.82rem;">${vol > 0 ? formatNumber(vol) : '—'}</td>
                    <td style="font-weight:600;font-size:0.85rem;color:#e2e8f0;">${valB > 0 ? formatNumber(Math.round(valB)) + ' tỷ' : '—'}</td>
                    <td>
                        <div class="scr-tags-wrap">${tagsHtml}</div>
                    </td>
                    <td style="color:#f59e0b;font-weight:600;font-size:0.85rem;">${tsl > 0 ? formatNumber(tsl) : '—'}</td>
                    <td style="text-align:center;">
                        <button class="btn-add-screener-quick" onclick="window.addWatchlistFromScreener('${s.symbol}', ${price}, ${tsl})" title="Thêm vào Danh sách Khuyến nghị">
                            <i class='bx bx-plus'></i> KN
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    }

    function formatNumber(num) {
        if (num == null || isNaN(num)) return '—';
        return Number(num).toLocaleString('vi-VN');
    }

    // Quick add to Watchlist handler
    window.addWatchlistFromScreener = function (ticker, price, tsl) {
        if (window.addWatchlistFromSwing) {
            window.addWatchlistFromSwing(ticker, price, tsl);
        } else {
            alert(`Đã chọn mã ${ticker}. Mở bảng Khuyến nghị để kiểm tra!`);
        }
    };

    // Public API
    window.SmartScreener = {
        init: initScreener,
        open: openScreener,
        close: closeScreener,
        refresh: loadDataAndRender
    };

    // Auto init when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initScreener);
    } else {
        initScreener();
    }
})();

/* ═══════════════════════════════════════════════════
   data-store.js — Quản lý dữ liệu dùng chung
   - data.json: dữ liệu dashboard (tải ngay khi mở trang)
   - raw_stocks.json: dữ liệu toàn bộ mã HOSE, chỉ tải khi cần
     (screener, watchlist, sửa nhóm ngành, nhóm ngành tùy chỉnh)
   Sau khi tải, raw_stocks được gắn vào appData.__global__.raw_stocks
   nên các đoạn code cũ đọc window.appData vẫn dùng được.
   ═══════════════════════════════════════════════════ */

(function () {
    let mainData = null;
    let basePath = 'public/';
    let rawStocks = null;      // cache raw_stocks đã tải
    let rawVersion = null;     // phiên bản dữ liệu ứng với cache
    let rawPromise = null;     // request đang chạy

    function globalOf(data) {
        return (data && data.__global__) || {};
    }

    function versionOf(data) {
        const g = globalOf(data);
        return g.generated_at || (data && data.VNINDEX && data.VNINDEX.date) || '';
    }

    function attach() {
        if (mainData && rawStocks) {
            mainData.__global__ = mainData.__global__ || {};
            mainData.__global__.raw_stocks = rawStocks;
        }
    }

    // Gọi sau mỗi lần tải data.json (kể cả auto-refresh)
    function setMain(data, base) {
        mainData = data;
        window.appData = data;
        if (base !== undefined) basePath = base;

        const g = globalOf(data);
        // Định dạng cũ: raw_stocks nằm sẵn trong data.json
        if (g.raw_stocks) {
            rawStocks = g.raw_stocks;
            rawVersion = versionOf(data);
            return;
        }
        if (rawStocks && rawVersion === versionOf(data)) {
            attach();
        } else if (rawStocks) {
            // Dữ liệu mới → tải lại raw_stocks ở nền vì đã có phần giao diện đang dùng
            rawStocks = null;
            rawPromise = null;
            loadRawStocks();
        }
    }

    function getRawStocks() {
        return rawStocks;
    }

    function loadRawStocks() {
        if (rawStocks) return Promise.resolve(rawStocks);
        if (rawPromise) return rawPromise;
        if (!mainData) return Promise.resolve(null);

        const g = globalOf(mainData);
        const file = g.raw_stocks_file || 'raw_stocks.json';
        const version = versionOf(mainData);
        const url = `${basePath}${file}?v=${encodeURIComponent(version)}`;

        rawPromise = fetch(url)
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then(json => {
                if (version !== versionOf(mainData)) {
                    // data.json đã đổi trong lúc tải → tải lại bản mới
                    rawPromise = null;
                    return loadRawStocks();
                }
                rawStocks = json || {};
                rawVersion = version;
                attach();
                document.dispatchEvent(new CustomEvent('vndata:raw-stocks', { detail: rawStocks }));
                return rawStocks;
            })
            .catch(err => {
                console.error('[DataStore] Không tải được raw_stocks:', err);
                rawPromise = null;
                return null;
            });
        return rawPromise;
    }

    window.VNData = { setMain, getRawStocks, loadRawStocks };
})();

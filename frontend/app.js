document.addEventListener('DOMContentLoaded', () => {
    let appData = null;
    let currentSymbol = 'VNINDEX';
    let currentMiniTab = 'general';

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
            renderDashboard();
        } catch (error) {
            console.error('Error fetching data:', error);
            dashboardContent.innerHTML = `
                <div class="glass" style="padding: 32px; text-align: center; color: var(--negative);">
                    <i class='bx bx-error-circle' style="font-size: 48px; margin-bottom: 16px;"></i>
                    <h3>Lỗi tải dữ liệu</h3>
                    <p>Không thể kết nối đến máy chủ hoặc dữ liệu chưa được cập nhật.</p>
                </div>
            `;
        }
    }

    // Tự động reload data mỗi 5 phút (300.000ms)
    setInterval(() => {
        console.log('[Auto-refresh] Reloading data...');
        fetchData();
    }, 5 * 60 * 1000);

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
        
        clone.getElementById('val-close').textContent = formatNum(data.close);
        
        const changeSpan = clone.getElementById('val-change');
        if (changeSpan && data.change_pc !== undefined) {
            const isPositive = data.change_pc >= 0;
            const sign = isPositive ? '+' : '';
            const color = isPositive ? 'var(--positive)' : 'var(--negative)';
            changeSpan.style.color = color;
            changeSpan.textContent = `(${sign}${data.change_pc.toFixed(2)}%)`;
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
        }
    }

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

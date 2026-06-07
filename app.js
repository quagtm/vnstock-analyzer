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

    // Fetch Data
    async function fetchData() {
        try {
            const response = await fetch('public/data.json');
            if (!response.ok) {
                const fallbackResponse = await fetch('data.json');
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
        if (currentMiniTab === 'general') {
            analysisTitle.textContent = "Phân tích Tổng quan";
            markdownText = data.general_markdown || data.analysis_markdown || "Không có dữ liệu.";
        } else if (currentMiniTab === 'volume') {
            analysisTitle.textContent = "Phân tích Dòng tiền (Khối lượng)";
            markdownText = data.volume_markdown || "Không có dữ liệu.";
        } else if (currentMiniTab === 'trend') {
            analysisTitle.textContent = "Phân tích Xu hướng (Biến động)";
            markdownText = data.trend_markdown || "Không có dữ liệu.";
        }

        if (window.marked) {
            markdownContainer.innerHTML = marked.parse(markdownText);
        } else {
            markdownContainer.innerHTML = "<p>" + markdownText + "</p>";
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

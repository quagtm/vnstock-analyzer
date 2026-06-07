document.addEventListener('DOMContentLoaded', () => {
    let appData = null;
    let currentSymbol = 'VNINDEX';
    let currentMiniTab = 'general';

    const dashboardContent = document.getElementById('dashboard-content');
    const pageTitle = document.getElementById('page-title');
    const updateDate = document.getElementById('update-date');
    const navItems = document.querySelectorAll('.nav-item');

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

        // Attach Mini-tab Events
        const miniTabBtns = document.querySelectorAll('.mini-tab-btn');
        const markdownContainer = document.getElementById('markdown-content');
        const analysisTitle = document.getElementById('analysis-title');

        function renderTabContent(tabName) {
            currentMiniTab = tabName;
            
            // Update UI buttons
            miniTabBtns.forEach(btn => {
                if (btn.getAttribute('data-tab') === tabName) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });

            // Set Title & Content
            let markdownText = "";
            if (tabName === 'general') {
                analysisTitle.textContent = "Phân tích Tổng quan";
                // Fallback cho data cũ (analysis_markdown)
                markdownText = data.general_markdown || data.analysis_markdown || "Không có dữ liệu.";
            } else if (tabName === 'volume') {
                analysisTitle.textContent = "Phân tích Dòng tiền (Khối lượng)";
                markdownText = data.volume_markdown || "Không có dữ liệu.";
            } else if (tabName === 'trend') {
                analysisTitle.textContent = "Phân tích Xu hướng (Biến động)";
                markdownText = data.trend_markdown || "Không có dữ liệu.";
            }

            if (window.marked) {
                markdownContainer.innerHTML = marked.parse(markdownText);
            } else {
                markdownContainer.innerHTML = "<p>" + markdownText + "</p>";
            }
        }

        miniTabBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const tab = e.target.closest('button').getAttribute('data-tab');
                renderTabContent(tab);
            });
        });

        // Init default tab
        renderTabContent(currentMiniTab);
    }

    // Navigation setup
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            navItems.forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            currentSymbol = item.getAttribute('data-target');
            // Reset to general tab when switching symbol
            currentMiniTab = 'general';
            if (appData) {
                renderDashboard();
            }
        });
    });

    // Init
    fetchData();
});

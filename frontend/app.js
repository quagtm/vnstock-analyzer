document.addEventListener('DOMContentLoaded', () => {
    let appData = null;
    let currentSymbol = 'VNINDEX';

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
            // Because we are on GH Pages or Local, we fetch from public/data.json
            const response = await fetch('public/data.json');
            if (!response.ok) {
                // If public/data.json not found, try data.json in same dir (useful for GH pages)
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

        // Render Markdown
        const markdownContainer = clone.getElementById('markdown-content');
        if (data.analysis_markdown && window.marked) {
            markdownContainer.innerHTML = marked.parse(data.analysis_markdown);
        } else {
            markdownContainer.innerHTML = "<p>Không có bài phân tích nào được tạo.</p>";
        }

        // Add to DOM
        dashboardContent.innerHTML = '';
        dashboardContent.appendChild(clone);
    }

    // Navigation setup
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            // Remove active class
            navItems.forEach(n => n.classList.remove('active'));
            // Add active class
            item.classList.add('active');
            
            // Switch symbol
            currentSymbol = item.getAttribute('data-target');
            
            // Render
            if (appData) {
                renderDashboard();
            }
        });
    });

    // Init
    fetchData();
});

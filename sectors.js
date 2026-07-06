// Custom Sectors Logic

let customSectors = null;

function loadCustomSectors() {
    try {
        const saved = localStorage.getItem('custom_sectors');
        if (saved) customSectors = JSON.parse(saved);
    } catch(e) {}
}

function computeCustomSectors(rawStocks) {
    if (!customSectors || !rawStocks) return null;
    
    let results = [];
    for (const [sectorName, tickers] of Object.entries(customSectors)) {
        let grp = tickers.map(t => rawStocks[t]).filter(x => x);
        if (grp.length === 0) {
            // Hiển thị ngành trống với dữ liệu bằng 0 thay vì bỏ qua
            results.push({
                sector: sectorName,
                avg_change: 0,
                count: 0,
                total_val: 0,
                cap_up: 0,
                cap_down: 0,
                cap_ref: 0
            });
            continue;
        }
        
        let avgChg = grp.reduce((acc, s) => acc + (s.change_pc || 0), 0) / grp.length;
        let totalVal = grp.reduce((acc, s) => acc + (s.accumulated_value || 0), 0) / 1000;
        let capUp = 0, capDown = 0, capRef = 0;
        
        grp.forEach(s => {
            let mc = (s.listed_share || 0) * (s.match_price || 0) / 1e9;
            if ((s.change_pc || 0) > 0) capUp += mc;
            else if ((s.change_pc || 0) < 0) capDown += mc;
            else capRef += mc;
        });
        
        results.push({
            sector: sectorName,
            avg_change: avgChg,
            count: grp.length,
            total_val: totalVal,
            cap_up: capUp,
            cap_down: capDown,
            cap_ref: capRef
        });
    }
    results.sort((a,b) => b.avg_change - a.avg_change);
    return results;
}

function initSectorModal(appData) {
    const modal = document.getElementById('sector-modal');
    const btnClose = document.getElementById('btn-close-modal');
    const editor = document.getElementById('sector-list-editor');
    const btnAddSector = document.getElementById('btn-add-sector');
    const btnReset = document.getElementById('btn-reset-sectors');
    const btnSave = document.getElementById('btn-save-sectors');
    
    if (!modal) return;
    
    let workingSectors = {};

    function extractDefaultSectors() {
        const rawStocks = (appData['__global__'] && appData['__global__'].raw_stocks) || {};
        let defaults = {};
        for (const [sym, data] of Object.entries(rawStocks)) {
            let sec = data.sector;
            if (!sec) continue;
            if (!defaults[sec]) defaults[sec] = [];
            defaults[sec].push(sym);
        }
        return defaults;
    }

    function renderEditor() {
        editor.innerHTML = '';
        for (const [sectorName, tickers] of Object.entries(workingSectors)) {
            const card = document.createElement('div');
            card.className = 'sector-edit-card';
            
            const header = document.createElement('div');
            header.className = 'sector-edit-header';
            header.innerHTML = `<div class="sector-edit-title">${sectorName} (${tickers.length})</div>`;
            
            const btnDelSector = document.createElement('button');
            btnDelSector.className = 'btn-icon';
            btnDelSector.innerHTML = `<i class='bx bx-trash' style="color:var(--negative)"></i>`;
            btnDelSector.onclick = () => {
                delete workingSectors[sectorName];
                renderEditor();
            };
            header.appendChild(btnDelSector);
            card.appendChild(header);
            
            const chips = document.createElement('div');
            chips.className = 'sector-edit-chips';
            
            tickers.forEach(t => {
                const chip = document.createElement('div');
                chip.className = 'sector-chip';
                chip.innerHTML = `${t} <i class='bx bx-x'></i>`;
                chip.querySelector('.bx-x').onclick = () => {
                    workingSectors[sectorName] = workingSectors[sectorName].filter(x => x !== t);
                    renderEditor();
                };
                chips.appendChild(chip);
            });
            
            const input = document.createElement('input');
            input.className = 'sector-add-input';
            input.placeholder = '+ Mã CP';
            input.onkeypress = (e) => {
                if (e.key === 'Enter') {
                    let val = input.value.trim().toUpperCase();
                    if (val && !workingSectors[sectorName].includes(val)) {
                        workingSectors[sectorName].push(val);
                        renderEditor();
                    }
                }
            };
            input.onblur = () => {
                let val = input.value.trim().toUpperCase();
                if (val && !workingSectors[sectorName].includes(val)) {
                    workingSectors[sectorName].push(val);
                    renderEditor();
                }
            };
            chips.appendChild(input);
            
            card.appendChild(chips);
            editor.appendChild(card);
        }
    }

    window.bindEditSectorButton = () => {
        const btnEdit = document.getElementById('btn-edit-sectors');
        if (btnEdit) {
            btnEdit.onclick = () => {
                if (customSectors) {
                    workingSectors = JSON.parse(JSON.stringify(customSectors));
                } else {
                    workingSectors = extractDefaultSectors();
                }
                renderEditor();
                modal.style.display = 'flex';
            };
        }
    };

    btnClose.onclick = () => {
        modal.style.display = 'none';
    };

    btnAddSector.onclick = () => {
        let name = prompt("Nhập tên Nhóm Ngành mới:");
        if (name && name.trim()) {
            name = name.trim();
            if (!workingSectors[name]) {
                workingSectors[name] = [];
                renderEditor();
            }
        }
    };

    btnReset.onclick = () => {
        if (confirm("Khôi phục về danh sách ngành mặc định của thị trường?")) {
            localStorage.removeItem('custom_sectors');
            customSectors = null;
            modal.style.display = 'none';
            if (window.renderDashboard) window.renderDashboard();
        }
    };

    btnSave.onclick = () => {
        // Collect pending inputs before saving (handled by onblur)
        
        if (Object.keys(workingSectors).length === 0) {
            alert("Bạn đã xóa hết tất cả các nhóm ngành! Vui lòng thêm nhóm mới hoặc khôi phục mặc định.");
            return;
        }

        customSectors = workingSectors;
        localStorage.setItem('custom_sectors', JSON.stringify(customSectors));
        modal.style.display = 'none';
        if (window.renderDashboard) window.renderDashboard();
    };
}

loadCustomSectors();

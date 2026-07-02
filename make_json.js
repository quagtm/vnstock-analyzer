const fs = require('fs');
const code = fs.readFileSync('data_pipeline/fetch_and_analyze.py', 'utf8');
const match = code.match(/SECTOR_MAP_FALLBACK\s*=\s*(\{[\s\S]*?\n\})/);
if (match) {
    let dictStr = match[1];
    dictStr = dictStr.replace(/'/g, '"');
    fs.writeFileSync('custom_sectors.json', dictStr);
    console.log('Created custom_sectors.json');
} else {
    console.log('Not found');
}

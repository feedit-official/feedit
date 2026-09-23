/* ══════════════════════════════════════════════════════
   금주의 리포트 — 내려받기(.xlsx) · 링크 공유 (2026-09-23)

   요구사항 정의서에 '리포트를 파일로 저장하고 링크로 공유한다'로 적어 두고
   화면에는 없던 기능이다. 오른쪽 위 버튼 두 개가 이 파일을 부른다.

   · 엑셀은 바깥 라이브러리 없이 만든다. .xlsx 는 XML 몇 장을 담은 zip 이라,
     압축하지 않는(store) zip 을 직접 쓰면 그것으로 충분하다.
     CSV 로 내리지 않는 이유 — 표가 여러 장이고, 한글 CSV 는 엑셀에서 깨지기 쉽다.
   · 값은 화면에 이미 떠 있는 것만 넣는다. 없는 값은 빈칸으로 두고 지어내지 않는다.
   ══════════════════════════════════════════════════════ */

/* ── 최소 zip(store) ── */
const CRC = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++){
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c;
  }
  return t;
})();
function crc32(bytes){
  let c = -1;
  for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ -1) >>> 0;
}
const utf8 = s => new TextEncoder().encode(s);

/* files: [{name, data(Uint8Array)}] → .xlsx 한 덩어리 */
function zipStore(files){
  const chunks = [], central = [];
  let offset = 0;
  files.forEach(f => {
    const name = utf8(f.name), crc = crc32(f.data), n = f.data.length;
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);  /* 이름은 UTF-8 */
    local.setUint16(8, 0, true);                                      /* 압축 안 함 */
    local.setUint32(14, crc, true);
    local.setUint32(18, n, true); local.setUint32(22, n, true);
    local.setUint16(26, name.length, true);
    chunks.push(new Uint8Array(local.buffer), name, f.data);

    const cen = new DataView(new ArrayBuffer(46));
    cen.setUint32(0, 0x02014b50, true);
    cen.setUint16(4, 20, true); cen.setUint16(6, 20, true); cen.setUint16(8, 0x0800, true);
    cen.setUint16(10, 0, true);
    cen.setUint32(16, crc, true);
    cen.setUint32(20, n, true); cen.setUint32(24, n, true);
    cen.setUint16(28, name.length, true);
    cen.setUint32(42, offset, true);
    central.push(new Uint8Array(cen.buffer), name);
    offset += 30 + name.length + n;
  });
  const cenSize = central.reduce((a, b) => a + b.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, cenSize, true); end.setUint32(16, offset, true);
  const all = chunks.concat(central, [new Uint8Array(end.buffer)]);
  const total = all.reduce((a, b) => a + b.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  all.forEach(b => { out.set(b, at); at += b.length });
  return out;
}

/* ── 시트 XML ── */
const xmlEsc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const colName = i => {
  let s = '', n = i + 1;
  while (n > 0){ const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = ((n - r) / 26) | 0 }
  return s;
};
/* 숫자로 넣을 값만 숫자 칸(t 없음)으로, 나머지는 인라인 문자열로 쓴다.
   숫자를 문자로 넣으면 엑셀에서 합계가 안 잡히고, 문자를 숫자로 넣으면 깨진다. */
function sheetXML(rows, widths){
  const body = rows.map((row, r) =>
    '<row r="' + (r + 1) + '">' + row.map((v, c) => {
      const ref = colName(c) + (r + 1);
      const isNum = typeof v === 'number' && isFinite(v);
      return isNum
        ? '<c r="' + ref + '"><v>' + v + '</v></c>'
        : (v == null || v === '' ? '<c r="' + ref + '"/>'
          : '<c r="' + ref + '" t="inlineStr"><is><t xml:space="preserve">' + xmlEsc(v) + '</t></is></c>');
    }).join('') + '</row>').join('');
  /* 칸 너비 — 없으면 기본 8자라 '내려받은 시각' 같은 말머리가 잘려 보인다 */
  const cols = (widths && widths.length)
    ? '<cols>' + widths.map((w, i) =>
        '<col min="' + (i + 1) + '" max="' + (i + 1) + '" width="' + w + '" customWidth="1"/>').join('') + '</cols>'
    : '';
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    cols + '<sheetData>' + body + '</sheetData></worksheet>';
}

/* sheets: [{name, rows, widths}] → .xlsx Blob */
export function buildXlsx(sheets){
  const files = [
    { name:'[Content_Types].xml', data:utf8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      sheets.map((_, i) => '<Override PartName="/xl/worksheets/sheet' + (i + 1) + '.xml" ' +
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>').join('') +
      '<Override PartName="/xl/workbook.xml" ' +
      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '</Types>') },
    { name:'_rels/.rels', data:utf8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Target="xl/workbook.xml" ' +
      'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>' +
      '</Relationships>') },
    { name:'xl/workbook.xml', data:utf8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
      sheets.map((s, i) => '<sheet name="' + xmlEsc(s.name) + '" sheetId="' + (i + 1) +
        '" r:id="rId' + (i + 1) + '"/>').join('') +
      '</sheets></workbook>') },
    { name:'xl/_rels/workbook.xml.rels', data:utf8(
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      sheets.map((_, i) => '<Relationship Id="rId' + (i + 1) + '" Target="worksheets/sheet' + (i + 1) + '.xml" ' +
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>').join('') +
      '</Relationships>') },
  ].concat(sheets.map((s, i) => ({ name:'xl/worksheets/sheet' + (i + 1) + '.xml',
    data:utf8(sheetXML(s.rows, s.widths)) })));
  return new Blob([zipStore(files)], {
    type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
}

export function saveBlob(blob, filename){
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/* ── 공유 링크 ──
   받는 사람이 열었을 때 금주의 리포트가 곧바로 서도록 주소에 화면과 탭을 적는다.
   (app_shell/static/js/router.js 의 resumeNav 가 이 두 값을 읽는다)
   기준 주와 키워드도 같이 적어, 다음 주에 열어도 무엇을 보던 링크였는지 남는다. */
export function reportShareUrl({ keyword = '', week = '' } = {}){
  const u = new URL(location.href);
  u.hash = '';
  u.searchParams.set('view', 'trend');
  u.searchParams.set('tr', 'report');
  if (keyword) u.searchParams.set('kw', keyword);
  if (week) u.searchParams.set('week', week);
  return u.toString();
}

/* 공유 — 모바일은 기본 공유 시트, PC 는 클립보드. 둘 다 막히면 주소를 그대로 보여 준다. */
export async function shareLink(url, title){
  if (navigator.share){
    try{ await navigator.share({ title, url }); return '공유 창을 열었습니다.' }
    catch(e){ if (e && e.name === 'AbortError') return '' }   /* 사용자가 닫은 것 — 조용히 */
  }
  try{
    await navigator.clipboard.writeText(url);
    return '리포트 링크를 복사했습니다.';
  }catch(e){
    window.prompt('아래 링크를 복사해 주세요.', url);
    return '';
  }
}

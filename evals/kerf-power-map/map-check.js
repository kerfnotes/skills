// Power Map 地圖驗收檢查。用法見同資料夾 README.md：預覽時以 inline <script> 附在 </body> 前，交付版不含此 script。
// 輸出：每項一行 PASS/FAIL 與原因，最後一行總結。
(function () {
  // shortcut: 以 id 排除 html_preview 注入的主題樣式（它替 html 設了背景），換預覽工具時要改這裡
  var THEME_ID = 't3-theme';
  var MAX_FOCAL = 2;
  var root = document.documentElement;
  var vw = root.clientWidth;
  var notCode = function (el) { return !/^(script|style|template)$/i.test(el.tagName); };
  var all = Array.from(document.body.querySelectorAll('*')).filter(notCode);
  var results = []; // 每項檢查一筆 { no, ok }，總數取它的長度

  function describe(el) {
    var cls = (el.getAttribute('class') || '').trim();
    var text = el === root || el === document.body ? '' : (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 20);
    return '<' + el.tagName.toLowerCase() + (cls ? '.' + cls.split(/\s+/).join('.') : '') + '>' + (text ? '「' + text + '」' : '');
  }

  function report(no, label, problems) {
    var shown = problems.slice(0, 5).join('；') + (problems.length > 5 ? '；…共 ' + problems.length + ' 處' : '');
    console.log((problems.length ? 'FAIL ' : 'PASS ') + no + ' ' + label + (problems.length ? '：' + shown : ''));
    results.push({ no: no, ok: !problems.length });
  }

  // 1. 水平溢出：整頁不能比視窗寬，任何元素也不能超出視窗左右緣（只報最外層的那個）
  var overflowIssues = [];
  if (root.scrollWidth > vw) overflowIssues.push('頁面寬 ' + root.scrollWidth + 'px > 視窗 ' + vw + 'px');
  var over = new Set();
  all.forEach(function (el) {
    var r = el.getBoundingClientRect();
    if (!r.width || (r.right <= vw + 1 && r.left >= -1)) return;
    if (!over.has(el.parentElement)) overflowIssues.push(describe(el) + ' 佔 ' + Math.round(r.left) + '～' + Math.round(r.right) + 'px');
    over.add(el);
  });
  report(1, '寬 ' + vw + ' 無水平溢出', overflowIssues);

  // 2. 文字截斷：overflow 裁切且內容比框大；SVG 的 scrollWidth 量不到，改看 <text> 有沒有超出畫布
  var clipIssues = [];
  all.forEach(function (el) {
    if (el instanceof SVGElement) return;
    var cs = getComputedStyle(el);
    if (cs.display === 'inline' || cs.display === 'none') return;
    var clipX = /hidden|clip/.test(cs.overflowX) && el.scrollWidth > el.clientWidth + 1;
    var clipY = /hidden|clip/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 1;
    if (clipX || clipY) clipIssues.push(describe(el) + (clipX ? ' 橫向' : ' 縱向') + '被裁切');
  });
  document.querySelectorAll('svg').forEach(function (svg) {
    var box = svg.getBoundingClientRect();
    svg.querySelectorAll('text').forEach(function (t) {
      var r = t.getBoundingClientRect();
      if (r.left < box.left - 1 || r.right > box.right + 1 || r.top < box.top - 1 || r.bottom > box.bottom + 1) clipIssues.push('SVG ' + describe(t) + ' 超出畫布');
    });
  });
  report(2, '文字未被截斷', clipIssues);

  // 3. 強調元素（data-focal）最多 2 個
  var focal = Array.from(document.querySelectorAll('[data-focal]'));
  report(3, '強調元素不超過 ' + MAX_FOCAL + ' 個', focal.length > MAX_FOCAL ? ['共 ' + focal.length + ' 個：' + focal.map(describe).join('、')] : []);

  // 4. SVG 無障礙：role="img"、aria-labelledby 指向自己內部非空的 <title> 與 <desc>、<title> 是第一個子元素
  var svgIssues = [];
  document.querySelectorAll('svg').forEach(function (svg, i) {
    var id = '第 ' + (i + 1) + ' 個 <svg>';
    if (svg.getAttribute('role') !== 'img') svgIssues.push(id + ' 缺 role="img"');
    var refs = (svg.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).map(function (x) {
      var el = document.getElementById(x);
      return el && svg.contains(el) && el.textContent.trim() ? el.tagName.toLowerCase() : null;
    });
    if (refs.indexOf(null) >= 0) svgIssues.push(id + ' aria-labelledby 指向不存在或空白的元素');
    if (refs.indexOf('title') < 0 || refs.indexOf('desc') < 0) svgIssues.push(id + ' aria-labelledby 沒有同時指向 <title> 與 <desc>');
    var first = svg.firstElementChild;
    if (!first || first.tagName.toLowerCase() !== 'title') svgIssues.push(id + ' 第一個子元素不是 <title>');
  });
  report(4, 'SVG 有標題與描述', svgIssues);

  // 5. 外部資源：資源屬性不可指向 http(s) 或 //；<style> 與 style 屬性不可有網址或 @import（<a> 連結不算資源）
  var externalIssues = [];
  var extUrl = /(^|,)\s*(https?:)?\/\//i;
  document.querySelectorAll('*').forEach(function (el) {
    var tag = el.tagName.toLowerCase();
    if (el.id === THEME_ID || tag === 'a') return;
    ['src', 'srcset', 'href', 'xlink:href', 'data', 'poster'].forEach(function (a) {
      var v = el.getAttribute(a);
      if (v && extUrl.test(v)) externalIssues.push('<' + tag + ' ' + a + '="' + v.trim().slice(0, 60) + '">');
    });
    var css = (tag === 'style' ? el.textContent : '') + ' ' + (el.getAttribute('style') || '');
    if (/@import|https?:\/\/|url\(\s*['"]?\/\//i.test(css)) externalIssues.push('<' + tag + '> 的樣式含外部網址或 @import');
  });
  report(5, '沒有外部資源', externalIssues);

  // 6. html、body 與 body 的最外層容器不設背景（掃作者樣式規則與 style 屬性，不看計算值）
  var backgroundIssues = [];
  var targets = [root, document.body].concat(Array.from(document.body.children).filter(notCode));
  var setsBg = function (style) {
    return ['background-color', 'background-image'].some(function (prop) {
      var v = style.getPropertyValue(prop).trim();
      return v && !/^(transparent|initial|unset|none|rgba\(0, 0, 0, 0\))$/i.test(v);
    });
  };
  var scan = function (rules) {
    Array.from(rules).forEach(function (rule) {
      if (rule.cssRules) scan(rule.cssRules); // @media、@supports 裡的規則
      if (!rule.selectorText || !setsBg(rule.style)) return;
      targets.forEach(function (el) {
        try { if (el.matches(rule.selectorText)) backgroundIssues.push(describe(el) + ' 被「' + rule.selectorText + '」設了背景'); } catch (e) { /* 偽元素等無法 matches 的選擇器 */ }
      });
    });
  };
  Array.from(document.styleSheets).forEach(function (sheet) {
    if (sheet.ownerNode && sheet.ownerNode.id === THEME_ID) return;
    try { scan(sheet.cssRules); } catch (e) { /* 外部樣式表讀不到規則，已由第 5 項抓 */ }
  });
  targets.forEach(function (el) { if (setsBg(el.style)) backgroundIssues.push(describe(el) + ' 的 style 屬性設了背景'); });
  report(6, 'html、body、最外層容器不設背景', backgroundIssues);

  // 7. 證據標籤 .tag 都要有文字
  var emptyTagIssues = [];
  document.querySelectorAll('.tag').forEach(function (t, i) { if (!t.textContent.trim()) emptyTagIssues.push('第 ' + (i + 1) + ' 個 .tag 是空的'); });
  report(7, '證據標籤都有文字', emptyTagIssues);

  var failed = results.filter(function (r) { return !r.ok; }).map(function (r) { return r.no; });
  console.log('map-check ' + (failed.length ? 'FAIL（第 ' + failed.join('、') + ' 項）' : 'PASS') + '：' + (results.length - failed.length) + '/' + results.length + ' 通過，視窗寬 ' + vw + 'px');
})();

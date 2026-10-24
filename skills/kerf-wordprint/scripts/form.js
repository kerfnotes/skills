'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const choice = (name) => document.querySelector(`input[name=${name}]:checked`)?.value;
  const MAX_FILE = 1024 ** 3;
  const AUDIO = /\.(wav|m4a|mp3|aac|flac|ogg|opus|aif|aiff|mp4|wma|qta)$/i;
  let initial;
  try { initial = JSON.parse($('initial-state').textContent); }
  catch (_) {
    $('error').textContent = '無法讀取表單設定，請回到 agent 重新開啟表單。';
    $('form').querySelectorAll('button, input, textarea').forEach((el) => { el.disabled = true; });
    return;
  }
  let serial = 0;
  let sources = (initial.sources || []).map((source) => ({
    key: `source-${++serial}`, payload: source, title: source.title, detail: source.path,
  }));
  let memos = initial.memos || [];
  const checkedMemos = new Set();
  let operation = null, uploading = false, submitted = false;
  let submissionUncertain = false;
  let rejectedSourceKey = null;
  const locked = () => Boolean(operation || uploading || submitted);
  const fatal = (message) => { $('error').textContent = message; $('error').focus(); };
  const element = (tag, className, text) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const announce = (message) => { $('source-status').textContent = message; };
  const bytes = (n) => !Number.isFinite(n) ? '' : n < 1024 ? `${n} B` :
    n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KiB` : `${(n / 1024 ** 2).toFixed(1)} MiB`;
  const titleFromPath = (path) => path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path;
  const matchesMemo = (source, memo) => source.payload?.memo_id === memo.id ||
    (source.payload?.kind === 'voice_memo' && source.payload.path === memo.path);
  const memoAdded = (id) => sources.some((source) => source.payload?.memo_id === id ||
    memos.some((memo) => memo.id === id && matchesMemo(source, memo)));
  const memoUnavailable = (source) => memos.some((memo) => matchesMemo(source, memo) && memo.availability !== 'local');
  const pending = () => sources.some((source) => source.upload && source.upload.status !== 'done');
  const settings = initial.settings || {};
  for (const name of ['engine', 'summary']) {
    document.querySelectorAll(`input[name=${name}]`).forEach((el) => {
      if (settings[name] !== undefined) el.checked = el.value === settings[name];
    });
  }
  for (const name of ['merge', 'mail']) {
    if (typeof settings[name] === 'boolean') $(name).checked = settings[name];
  }
  if (typeof settings.summary_custom === 'string') $('summary_custom').value = settings.summary_custom;
  if (Array.isArray(settings.roster)) {
    $('roster').value = settings.roster.join('、');
    $('roster').defaultValue = $('roster').value;
    $('roster').dataset.values = JSON.stringify(settings.roster);
  }
  if (Array.isArray(settings.recipients)) $('recipients').value = settings.recipients.join(', ');

  // This tab and token only. Never serialize File objects or audio bytes.
  let storage, draftKey, submissionKey, reselectKey = null, pathErrorReason = null, restoredDraft = false;
  const draftSettings = () => ({engine: choice('engine'), summary: choice('summary'),
    merge: $('merge').checked, mail: $('mail').checked,
    summary_custom: $('summary_custom').value, roster: $('roster').value,
    recipients: $('recipients').value, paths: $('paths').value});
  const record = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
  const string = (value) => typeof value === 'string' && value.length <= 65536 && !value.includes('\0');
  const identifier = (value) => string(value) && value.length > 0 && value.length <= 512;
  function validPayload(payload) {
    if (!record(payload)) return false;
    const keys = Object.keys(payload);
    if (keys.length === 1 && (identifier(payload.upload_id) || identifier(payload.memo_id))) return true;
    return keys.every((key) => ['kind', 'path', 'title'].includes(key)) &&
      ['path', 'voice_memo'].includes(payload.kind) && string(payload.path) && Boolean(payload.path.trim()) && string(payload.title);
  }
  function saveDraft() {
    if (!storage || submitted) return;
    try {
      storage.setItem(draftKey, JSON.stringify({version: 1, settings: draftSettings(), sources: sources.map((source) => ({
        title: source.title, detail: source.detail || '',
        ...(source.payload ? {payload: source.payload} : {needs_selection: true}),
      }))}));
    } catch (_) { restoredDraft = false; $('draft-status').textContent = '此分頁無法暫存設定；重新整理前請先完成送出。'; }
  }
  try {
    if (typeof window !== 'undefined') {
      draftKey = `wordprint:draft:v1:${window.location.origin}${window.location.pathname}${window.location.search}`;
      submissionKey = `${draftKey}:submission`;
      storage = window.sessionStorage;
      submissionUncertain = storage.getItem(submissionKey) === 'pending';
      const raw = storage.getItem(draftKey);
      if (raw !== null) {
        if (raw.length > 1024 ** 2) throw new Error('draft');
        const draft = JSON.parse(raw), saved = draft?.settings;
        if (!record(draft) || draft.version !== 1 || !record(saved) || !Array.isArray(draft.sources) || draft.sources.length > 1000 ||
            !['merge', 'mail'].every((key) => typeof saved[key] === 'boolean') ||
            !['summary_custom', 'roster', 'recipients', 'paths'].every((key) => string(saved[key])) ||
            !['engine', 'summary'].every((name) => [...document.querySelectorAll(`input[name=${name}]`)].some((el) => el.value === saved[name])) ||
            !draft.sources.every((source) => record(source) && string(source.title) && string(source.detail) &&
              Object.keys(source).every((key) => ['title', 'detail', 'payload', 'needs_selection'].includes(key)) &&
              (source.needs_selection === true ? !('payload' in source) : !('needs_selection' in source) && validPayload(source.payload)))) throw new Error('draft');
        sources = draft.sources.map((source) => ({key: `source-${++serial}`, title: source.title, detail: source.detail,
          ...(source.needs_selection ? {upload: {status: 'needs-selection', file: null,
            message: '重新整理前尚未完成上傳，請重新選取檔案或移除。'}} : {payload: source.payload})}));
        for (const name of ['engine', 'summary']) document.querySelectorAll(`input[name=${name}]`).forEach((el) => { el.checked = el.value === saved[name]; });
        for (const name of ['merge', 'mail']) $(name).checked = saved[name];
        for (const name of ['summary_custom', 'roster', 'recipients', 'paths']) $(name).value = saved[name];
        if (saved.paths) $('more-sources').open = true;
        restoredDraft = true;
      }
    }
  } catch (_) {
    $('draft-status').textContent = '無法恢復暫存設定，已保留表單原始內容；請確認錄音清單。';
    try { storage?.removeItem(draftKey); } catch (_) { /* Storage may be blocked. */ }
  }
  const recipients = () => $('recipients').value.split(/[\s,;，；]+/).filter(Boolean);
  const validRecipients = () => recipients().every((address) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address));
  function fieldError(id, field, message) {
    $(id).textContent = message; $(field).setAttribute('aria-invalid', String(Boolean(message)));
  }
  function clearResolvedErrors() {
    if (rejectedSourceKey && !sources.some((source) => source.key === rejectedSourceKey)) rejectedSourceKey = null;
    if (!rejectedSourceKey && sources.length && !pending() && !sources.some(memoUnavailable)) fieldError('sources-error', 'source-list', '');
    if (choice('summary') !== 'custom' || $('summary_custom').value.trim()) fieldError('custom-error', 'summary_custom', '');
    if (validRecipients()) fieldError('recipients-error', 'recipients', '');
    if ((pathErrorReason === 'empty' && $('paths').value.trim()) ||
        (pathErrorReason !== 'empty' && !$('paths').value.trim())) {
      fieldError('paths-error', 'paths', ''); pathErrorReason = null;
    }
  }
  if (typeof window !== 'undefined') window.addEventListener('beforeunload', (event) => {
    saveDraft();
    if (uploading || operation === 'submit' || sources.some((source) => source.upload?.file)) {
      event.preventDefault(); event.returnValue = '';
    }
  });

  function sync() {
    $('selected-sources').hidden = sources.length === 0;
    $('output-settings').hidden = sources.length === 0;
    const summaryLabels = {meeting: '會議摘要', interview: '訪談摘要', lecture: '演講／課程摘要', custom: '自訂摘要'};
    $('current-output').textContent = choice('summary') === 'none' ? '逐字稿' : `逐字稿＋${summaryLabels[choice('summary')] || '會議摘要'}`;
    $('submit').textContent = initial.mode === 'run' ? (choice('engine') === 'colab' ? '準備 Colab' : '開始整理') : '送出設定';
    if (restoredDraft) $('draft-status').textContent = sources.some((source) => source.upload?.status === 'needs-selection') ?
      '已恢復此分頁的設定與順序；未完成上傳的檔案須重新選取。' : '已恢復此分頁的錄音來源、順序與設定。';
    clearResolvedErrors(); saveDraft();
    $('form').setAttribute('aria-busy', String(locked()));
    $('drop-zone').setAttribute('aria-disabled', String(locked()));
    document.querySelectorAll('[data-lock=source]').forEach((el) => { el.disabled = locked(); });
    $('files').disabled = locked(); $('paths').disabled = locked();
    $('submit').disabled = locked() || submissionUncertain || pending() || sources.some(memoUnavailable);
    document.querySelectorAll('input[name=engine], input[name=summary], #merge, #summary_custom, #roster, #recipients, #mail').forEach((el) => {
      el.disabled = operation === 'submit' || submitted;
    });
    document.querySelectorAll('[data-memo-id]').forEach((el) => {
      el.disabled = locked() || el.dataset.unavailable === 'true' || memoAdded(el.dataset.memoId);
    });
    $('add-memos').disabled = locked() || !memos.some((memo) =>
      checkedMemos.has(memo.id) && memo.availability === 'local' && !memoAdded(memo.id));
    document.querySelectorAll('[data-source-action]').forEach((el) => {
      const source = sources.find((item) => item.key === el.dataset.key);
      const index = sources.indexOf(source), action = el.dataset.sourceAction;
      el.disabled = operation === 'submit' || submitted ||
        (action === 'up' && index === 0) || (action === 'down' && index === sources.length - 1) ||
        (action === 'remove' && source?.upload?.status === 'uploading') ||
        (['retry', 'reselect'].includes(action) && Boolean(operation)) || (action === 'reselect' && uploading);
    });
    $('merge-row').hidden = sources.length < 2 && !sources.some((source) => source.payload?.kind === 'path');
    const custom = choice('summary') === 'custom';
    $('custom-row').hidden = !custom; $('summary_custom').required = custom;
  }
  function actionButton(text, action, source) {
    const button = element('button', '', text);
    button.type = 'button'; button.dataset.sourceAction = action; button.dataset.key = source.key;
    button.setAttribute('aria-label', `${text}：${source.title}`);
    return button;
  }
  function restoreSourceFocus(key, action) {
    const target = [...document.querySelectorAll('[data-source-action]')].find((el) =>
      el.dataset.key === key && el.dataset.sourceAction === action && !el.disabled);
    (target || (sources.length ? $('selected-heading') : $('choose-files'))).focus();
  }
  function renderSources() {
    const list = $('source-list'), active = document.activeElement;
    const focusedKey = active?.dataset?.key, focusedAction = active?.dataset?.sourceAction;
    list.replaceChildren();
    sources.forEach((source, index) => {
      const row = element('li', 'source-row'); row.dataset.status = source.upload?.status || 'ready';
      const content = element('div', 'item-content');
      content.append(element('span', 'item-title', `${index + 1}. ${source.title}`));
      content.append(element('span', 'meta', source.detail || ''));
      if (memoUnavailable(source)) content.append(element('span', 'error', '這份語音備忘錄目前無法讀取，請重新整理或移除。'));
      if (source.upload) {
        const upload = source.upload, status = element('span', 'meta upload-detail', upload.message);
        status.id = `${source.key}-status`; content.append(status);
        if (upload.status === 'uploading' || upload.status === 'queued') {
          const progress = element('progress'); progress.id = `${source.key}-progress`;
          progress.max = 100; progress.value = upload.percent || 0;
          progress.setAttribute('aria-label', `${source.title} 上傳進度`); content.append(progress);
        }
      }
      const actions = element('div', 'item-actions');
      actions.append(actionButton('上移', 'up', source), actionButton('下移', 'down', source));
      if (source.upload?.status === 'failed') actions.append(actionButton('重試', 'retry', source));
      if (source.upload?.status === 'needs-selection') actions.append(actionButton('重新選取', 'reselect', source));
      actions.append(actionButton('移除', 'remove', source)); row.append(content, actions); list.append(row);
    });
    $('source-count').textContent = sources.length ? String(sources.length) : '';
    sync(); if (focusedKey) restoreSourceFocus(focusedKey, focusedAction);
  }
  function renderMemos() {
    $('memo-list').replaceChildren();
    $('memo-hint').hidden = !memos.some((memo) => memo.availability !== 'local');
    memos.forEach((memo) => {
      const row = element('div', 'memo-row'), label = element('label', 'choice'), box = element('input');
      box.type = 'checkbox'; box.dataset.memoId = memo.id;
      box.dataset.unavailable = String(memo.availability !== 'local');
      box.checked = checkedMemos.has(memo.id) || memoAdded(memo.id);
      box.addEventListener('change', () => {
        if (box.checked) checkedMemos.add(memo.id); else checkedMemos.delete(memo.id); sync();
      });
      const content = element('span', 'item-content', memo.title);
      const duration = Math.max(0, Math.round(Number(memo.duration) || 0));
      const when = String(memo.recorded_at || '').slice(0, 16).replace('T', ' ');
      const availability = memo.availability === 'missing' ? '不在這台 Mac' :
        memo.availability === 'unreadable' ? '無法讀取' : memoAdded(memo.id) ? '已加入' : '';
      content.append(element('span', 'meta', [when, `${Math.floor(duration / 60)}:${String(duration % 60).padStart(2, '0')}`, availability].filter(Boolean).join(' · ')));
      label.append(box, content);
      const button = element('button', '', memoAdded(memo.id) ? '已加入' : '加入');
      button.type = 'button'; button.dataset.memoId = memo.id;
      button.dataset.unavailable = String(memo.availability !== 'local');
      button.setAttribute('aria-label', `加入：${memo.title}`);
      button.addEventListener('click', () => addMemos([memo.id]));
      row.append(label, button); $('memo-list').append(row);
    }); sync();
  }
  function addMemos(ids) {
    if (locked()) return;
    let count = 0;
    memos.forEach((memo) => {
      if (!ids.includes(memo.id) || memo.availability !== 'local' || memoAdded(memo.id)) return;
      sources.push({key: `source-${++serial}`, payload: {memo_id: memo.id}, title: memo.title, detail: '語音備忘錄'});
      checkedMemos.delete(memo.id); count++;
    });
    renderSources(); renderMemos(); announce(`已加入 ${count} 份語音備忘錄。`); $('selected-heading').focus();
  }
  function addPaths(paths) {
    let count = 0;
    paths.forEach((path) => {
      if (sources.some((source) => source.payload?.path === path)) return;
      sources.push({key: `source-${++serial}`, title: titleFromPath(path), detail: path,
        payload: {kind: 'path', path, title: titleFromPath(path)}}); count++;
    }); renderSources(); announce(`已加入 ${count} 個路徑。`); return count;
  }
  async function request(endpoint, body) {
    const response = await fetch(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error('服務未回傳有效資料，請回到 agent 確認表單仍開啟。'); }
    if (!response.ok) {
      const error = new Error(result.error || '操作失敗，請重試。');
      error.status = response.status; error.result = result; throw error;
    }
    return result;
  }
  $('read-memos').addEventListener('click', async () => {
    if (locked()) return;
    operation = 'memos'; sync(); $('memo-panel').hidden = false;
    $('memo-error').textContent = ''; $('memo-status').textContent = '正在讀取語音備忘錄…';
    try {
      const result = await request('memos', {});
      if (!Array.isArray(result.memos) || result.memos.some((memo) => typeof memo.id !== 'string')) throw new Error('語音備忘錄清單格式錯誤。');
      memos = result.memos; $('read-memos').textContent = '重新整理語音備忘錄';
      $('memo-status').textContent = memos.length ? `顯示最近 ${memos.length} 份，共 ${result.total ?? memos.length} 份。` : '沒有可列出的語音備忘錄，可改用「加入錄音」。';
      renderMemos(); renderSources();
    } catch (error) {
      $('memo-status').textContent = ''; $('memo-error').textContent = `讀取失敗，原有選擇仍保留。${error.message}`;
    } finally { operation = null; sync(); }
  });
  $('add-memos').addEventListener('click', () => addMemos([...checkedMemos]));
  document.querySelectorAll('[data-browse]').forEach((button) => button.addEventListener('click', async () => {
    if (locked()) return;
    operation = 'browse'; sync(); $('browse-error').textContent = '';
    $('browse-status').textContent = '請在系統選擇器選擇，或取消返回。';
    try {
      const {paths} = await request('browse', {kind: button.dataset.browse});
      if (!Array.isArray(paths) || paths.some((path) => typeof path !== 'string' || !path.trim())) throw new Error('選擇器回傳格式錯誤。');
      const count = addPaths(paths);
      $('browse-status').textContent = paths.length ? `已加入 ${count} 個路徑，可在清單調整順序。` : '已取消選擇。';
    } catch (error) {
      $('browse-status').textContent = ''; $('browse-error').textContent = `無法開啟選擇器，可改填本機路徑。${error.message}`;
    } finally { operation = null; sync(); }
  }));
  $('add-paths').addEventListener('click', () => {
    if (locked()) return;
    const paths = $('paths').value.split('\n').map((path) => path.trim()).filter(Boolean);
    pathErrorReason = paths.length ? null : 'empty';
    fieldError('paths-error', 'paths', paths.length ? '' : '請先填入本機路徑。');
    if (!paths.length) { $('paths').focus(); return; }
    addPaths(paths); $('paths').value = ''; sync(); $('selected-heading').focus();
  });
  function uploadFile(source) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest(); xhr.open('POST', 'upload'); xhr.timeout = 30 * 60 * 1000;
      xhr.setRequestHeader('Content-Type', 'application/octet-stream');
      xhr.setRequestHeader('X-File-Name', encodeURIComponent(source.upload.file.name));
      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        const percent = Math.min(100, Math.round(event.loaded / event.total * 100)); source.upload.percent = percent;
        source.upload.message = percent === 100 ? '已傳送，正在確認檔案…' : `上傳中 ${percent}%`;
        const progress = $(`${source.key}-progress`), status = $(`${source.key}-status`);
        if (progress) progress.value = percent; if (status) status.textContent = source.upload.message;
      };
      xhr.onload = () => {
        try {
          const result = JSON.parse(xhr.responseText);
          if (xhr.status < 200 || xhr.status >= 300) throw new Error(result.error || '上傳失敗。');
          if (typeof result.id !== 'string' || !result.id || typeof result.title !== 'string' ||
              !Number.isFinite(result.byte_count) || typeof result.sha256 !== 'string') throw new Error('上傳回覆不完整。');
          resolve(result);
        } catch (error) { reject(error); }
      };
      xhr.onerror = () => reject(new Error('連線中斷，請確認本機表單仍開啟後重試。'));
      xhr.ontimeout = () => reject(new Error('上傳逾時，可重試或移除。'));
      xhr.onabort = () => reject(new Error('上傳已中止，可重試或移除。'));
      xhr.send(source.upload.file);
    });
  }
  async function runUploads() {
    if (uploading || operation || submitted) return;
    uploading = true; sync();
    try {
      let source;
      while ((source = sources.find((item) => item.upload?.status === 'queued'))) {
        source.upload.status = 'uploading'; source.upload.message = '上傳中 0%';
        $('upload-status').textContent = `正在上傳：${source.title}`; renderSources();
        try {
          const result = await uploadFile(source);
          source.payload = {upload_id: result.id}; source.title = result.title; source.detail = bytes(result.byte_count);
          source.upload.status = 'done'; source.upload.message = '已加入本機表單'; source.upload.file = null;
        } catch (error) {
          source.upload.status = 'failed'; source.upload.message = `上傳失敗：${error.message} 檔案仍保留，可重試或移除。`;
        } renderSources();
      }
    } finally {
      uploading = false; sync();
      $('upload-status').textContent = pending() ?
        '仍有未完成的檔案，已完成的項目會保留。請重試、重新選取或移除後繼續。' : '錄音檔已加入，可調整順序後繼續。';
    }
  }
  function queueFiles(files) {
    if (locked()) return;
    const errors = [];
    let needsNativePicker = false;
    for (const file of Array.from(files || [])) {
      if (!(file instanceof File)) { errors.push('只接受錄音檔案。'); continue; }
      if (!AUDIO.test(file.name)) { errors.push(`${file.name}：不支援此副檔名，請選擇 WAV、M4A、MP3、AAC、FLAC、OGG、OPUS、AIF、AIFF、MP4、WMA 或 QTA。`); continue; }
      if (file.size > MAX_FILE) {
        errors.push(`${file.name}：超過 1 GiB，請改用「其他匯入方式 → 選擇本機檔案」，或填入本機路徑。`);
        needsNativePicker = true; continue;
      }
      if (file.size === 0) { errors.push(`${file.name}：檔案不可為空。`); continue; }
      const source = {key: `source-${++serial}`, title: file.name, detail: bytes(file.size),
        upload: {file, status: 'queued', percent: 0, message: '等待上傳'}};
      const replace = sources.findIndex((item) => item.key === reselectKey && item.upload?.status === 'needs-selection');
      if (replace >= 0) { sources[replace] = source; reselectKey = null; } else sources.push(source);
    }
    reselectKey = null;
    $('upload-error').textContent = errors.join('\n'); renderSources();
    if (needsNativePicker) {
      $('more-sources').open = true;
      document.querySelector('[data-browse=file]').focus();
    }
    if (sources.some((source) => source.upload?.status === 'queued')) runUploads();
  }
  $('choose-files').addEventListener('click', () => { if (!locked()) { reselectKey = null; $('files').click(); } });
  $('files').addEventListener('cancel', () => { reselectKey = null; });
  $('files').addEventListener('change', () => { queueFiles($('files').files); $('files').value = ''; });
  ['dragenter', 'dragover'].forEach((name) => $('drop-zone').addEventListener(name, (event) => {
    event.preventDefault(); if (!locked()) $('drop-zone').classList.add('drag-over');
  }));
  $('drop-zone').addEventListener('dragleave', () => $('drop-zone').classList.remove('drag-over'));
  $('drop-zone').addEventListener('drop', (event) => {
    event.preventDefault(); $('drop-zone').classList.remove('drag-over'); if (locked()) return;
    const transfer = event.dataTransfer;
    if ([...(transfer?.items || [])].some((item) => item.webkitGetAsEntry?.()?.isDirectory)) {
      $('upload-error').textContent = '資料夾請用「其他匯入方式 → 選擇本機資料夾」。'; return;
    }
    if (!transfer?.files?.length) {
      $('upload-error').textContent = '未收到可上傳的錄音檔。請先將語音備忘錄匯出成檔案，再拖入或選取。'; return;
    } queueFiles(transfer.files);
  });
  document.addEventListener('dragover', (event) => { event.preventDefault(); });
  document.addEventListener('drop', (event) => { event.preventDefault(); });
  $('source-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-source-action]');
    if (!button || button.disabled || operation === 'submit' || submitted) return;
    const index = sources.findIndex((source) => source.key === button.dataset.key); if (index < 0) return;
    const source = sources[index], action = button.dataset.sourceAction;
    if (action === 'reselect') {
      if (locked() || source.upload?.status !== 'needs-selection') return;
      reselectKey = source.key; $('files').click(); return;
    }
    if (action === 'retry') {
      if (source.upload?.status !== 'failed' || operation) return;
      source.upload.status = 'queued'; source.upload.message = '等待重試'; source.upload.percent = 0;
      renderSources(); $('selected-heading').focus(); runUploads(); return;
    }
    if (action === 'remove') {
      if (source.upload?.status === 'uploading') return;
      sources.splice(index, 1); if (source.payload?.memo_id) checkedMemos.delete(source.payload.memo_id);
      if (source.upload && !uploading) {
        $('upload-status').textContent = pending() ? '仍有未完成的檔案，請重試、重新選取或移除。' : '';
      }
      announce(`已移除 ${source.title}。`);
    } else {
      const next = index + (action === 'up' ? -1 : 1); if (next < 0 || next >= sources.length) return;
      [sources[index], sources[next]] = [sources[next], sources[index]]; announce(`${source.title} 已移至第 ${next + 1} 位。`);
    }
    renderSources(); renderMemos();
    restoreSourceFocus(action === 'remove' ? sources[Math.min(index, sources.length - 1)]?.key : source.key, action);
  });
  document.addEventListener('change', sync);
  document.addEventListener('input', () => { clearResolvedErrors(); saveDraft(); });
  $('form').addEventListener('submit', async (event) => {
    event.preventDefault(); if (locked() || submissionUncertain) return;
    $('error').textContent = '';
    pathErrorReason = null; rejectedSourceKey = null;
    for (const [id, field] of [['sources-error', 'source-list'], ['custom-error', 'summary_custom'], ['recipients-error', 'recipients'], ['paths-error', 'paths']]) fieldError(id, field, '');
    if ($('paths').value.trim()) {
      pathErrorReason = 'unadded';
      $('more-sources').open = true; fieldError('paths-error', 'paths', '請先按「加入路徑」，確認清單順序後再繼續。'); $('paths').focus(); return;
    }
    if (!sources.length || pending() || sources.some(memoUnavailable)) {
      fieldError('sources-error', 'source-list', !sources.length ? '請至少加入一份錄音。' : '請先重試失敗項目、重新選取未完成檔案、重新整理語音備忘錄，或移除無法讀取的項目。');
      $('selected-heading').focus(); return;
    }
    const summary = choice('summary'), engine = choice('engine');
    if (!engine || !summary) { fatal('請選擇轉錄方式與摘要。'); return; }
    if (summary === 'custom' && !$('summary_custom').value.trim()) {
      fieldError('custom-error', 'summary_custom', '請填寫自訂摘要需求。'); $('summary_custom').focus(); return;
    }
    if (!validRecipients()) {
      $('optional-settings').open = true; fieldError('recipients-error', 'recipients', '請確認 email 地址，並以逗號分隔。'); $('recipients').focus(); return;
    }
    const answers = {
      sources: sources.map((source) => source.payload), merge: !$('merge-row').hidden && $('merge').checked,
      engine, summary, summary_custom: $('summary_custom').value,
      roster: $('roster').value === $('roster').defaultValue ? JSON.parse($('roster').dataset.values || '[]') : $('roster').value,
      recipients: recipients(), mail: $('mail').checked,
    };
    // Keep this guard separate from the v1 draft: a reload must not enable a duplicate task.
    submissionUncertain = true;
    try { storage?.setItem(submissionKey, 'pending'); } catch (_) { /* The in-page guard still applies. */ }
    operation = 'submit'; sync(); $('submit-status').textContent = '正在交付設定…';
    try {
      const result = await request('submit', answers);
      if (result?.ok !== true) throw new Error('服務未確認設定已儲存。');
      submitted = true; $('form').hidden = true; $('success').hidden = false; $('success').focus();
      try { storage?.removeItem(draftKey); storage?.removeItem(submissionKey); } catch (_) { /* Submission already succeeded. */ }
    } catch (error) {
      if (error.status === 400 && error.result?.code === 'invalid_source' && error.result.saved === false) {
        submissionUncertain = false;
        try { storage?.removeItem(submissionKey); } catch (_) { /* Safe retry is confirmed by the server. */ }
        rejectedSourceKey = sources[error.result.source_index]?.key || null;
        $('submit-status').textContent = '設定尚未儲存，請修正來源後再送出；清單、設定與已完成上傳均已保留。';
        fieldError('sources-error', 'source-list', error.message); $('selected-heading').focus();
      } else {
        $('submit-status').textContent = '尚未確認送出，內容仍保留。請先核對任務狀態，勿重複送出；需要重開表單時請回到對話。';
        fatal(`無法確認設定是否儲存，請先查看 agent 視窗。${error.message}`);
      }
    } finally {
      operation = null; sync();
      if (rejectedSourceKey) restoreSourceFocus(rejectedSourceKey, 'remove');
    }
  });
  if (memos.length) {
    $('memo-panel').hidden = false; $('read-memos').textContent = '重新整理語音備忘錄';
    $('memo-status').textContent = `顯示最近 ${memos.length} 份。`;
  }
  if (submissionUncertain) {
    $('submit-status').textContent = '尚未確認送出，內容仍保留。請先核對任務狀態，勿重複送出；需要重開表單時請回到對話。';
  }
  renderSources(); renderMemos();
})();

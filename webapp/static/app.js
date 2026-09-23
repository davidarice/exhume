'use strict';

(() => {
  const POLL_MS = 1000;
  const MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024; // 2 GiB, matches the server limit

  const $ = (id) => document.getElementById(id);

  const el = {
    status: $('status'),
    sections: {
      idle: $('state-idle'),
      uploading: $('state-uploading'),
      parsing: $('state-parsing'),
      ready: $('state-ready'),
      converting: $('state-converting'),
      done: $('state-done'),
      error: $('state-error'),
    },
    dropzone: $('dropzone'),
    fileInput: $('file-input'),
    uploadFilename: $('upload-filename'),
    uploadProgress: $('upload-progress'),
    uploadBar: $('upload-bar'),
    uploadPct: $('upload-pct'),
    uploadNote: $('upload-note'),
    parsingFilename: $('parsing-filename'),
    parsingElapsed: $('parsing-elapsed'),
    projectSummary: $('project-summary'),
    selectAll: $('select-all'),
    seqTbody: $('seq-tbody'),
    convertBtn: $('convert-btn'),
    convertProgress: $('convert-progress'),
    convertBar: $('convert-bar'),
    convertLabel: $('convert-label'),
    doneSummary: $('done-summary'),
    downloadAll: $('download-all'),
    doneFiles: $('done-files'),
    backBtn: $('back-btn'),
    resetBtn: $('reset-btn'),
    errorMessage: $('error-message'),
    retryBtn: $('retry-btn'),
    quitBtn: $('quit-btn'),
  };

  const state = {
    view: 'idle',
    filename: '',
    jobId: null,
    project: null, // payload of a "ready" job
    selected: new Set(),
    convertId: null,
    parseStart: 0,
  };

  // Bumping the generation cancels every scheduled poll/tick from older views.
  let generation = 0;
  let shutdownToken = null;

  function schedule(fn, ms) {
    const gen = generation;
    setTimeout(() => {
      if (gen === generation) fn();
    }, ms);
  }

  function show(view) {
    generation += 1;
    state.view = view;
    for (const [name, section] of Object.entries(el.sections)) {
      section.hidden = name !== view;
    }
  }

  function announce(text) {
    el.status.textContent = text;
  }

  // ---------- helpers ----------

  function plural(n, word) {
    return n.toLocaleString() + ' ' + word + (n === 1 ? '' : 's');
  }

  function humanSize(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) return '—';
    if (bytes < 1024) return bytes.toLocaleString() + ' B';
    const units = ['KB', 'MB', 'GB', 'TB'];
    let value = bytes / 1024;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return value.toFixed(1) + ' ' + units[unit];
  }

  async function readJson(res) {
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      // non-JSON body; handled below
    }
    if (!res.ok) {
      throw new Error((data && data.error) || 'Server error (HTTP ' + res.status + ').');
    }
    if (data === null || typeof data !== 'object') {
      throw new Error('Unexpected response from the server.');
    }
    return data;
  }

  function errorMessage(err) {
    if (err instanceof TypeError) return 'Network error — could not reach the server.';
    return (err && err.message) || 'Something went wrong.';
  }

  async function loadSession() {
    try {
      const data = await readJson(await fetch('/api/session'));
      shutdownToken = typeof data.shutdown_token === 'string' ? data.shutdown_token : null;
    } catch (_) {
      shutdownToken = null;
    }
  }

  async function quitApp() {
    if (!shutdownToken) {
      await loadSession();
    }
    if (!shutdownToken || !window.confirm('Quit FCP7 Export Tool? Any active conversion will be stopped.')) {
      return;
    }
    el.quitBtn.disabled = true;
    try {
      await readJson(await fetch('/api/shutdown', {
        method: 'POST',
        headers: {'X-FCP': '1', 'X-FCP-Shutdown': shutdownToken},
      }));
      document.querySelector('main').innerHTML =
        '<section class="state panel"><h2 class="state-title">FCP7 Export Tool has stopped</h2>' +
        '<p class="muted">You can close this browser tab.</p></section>';
      el.quitBtn.hidden = true;
    } catch (err) {
      el.quitBtn.disabled = false;
      window.alert(errorMessage(err));
    }
  }

  // ---------- 1. idle ----------

  function toIdle() {
    state.filename = '';
    state.jobId = null;
    state.project = null;
    state.selected = new Set();
    state.convertId = null;
    el.fileInput.value = '';
    show('idle');
    announce('Ready. Drop a .fcp file to begin.');
  }

  function handleChosenFile(file) {
    if (!file) return;
    if (file.size === 0) {
      toError('"' + file.name + '" is empty (0 bytes).');
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      toError('"' + file.name + '" is larger than the 2 GiB upload limit.');
      return;
    }
    startUpload(file);
  }

  // ---------- 2. uploading ----------

  function setUploadProgress(fraction) {
    const pct = Math.max(0, Math.min(100, Math.round(fraction * 100)));
    el.uploadBar.style.width = pct + '%';
    el.uploadPct.textContent = pct + '%';
    el.uploadProgress.setAttribute('aria-valuenow', String(pct));
  }

  function startUpload(file) {
    state.filename = file.name;
    el.uploadFilename.textContent = file.name;
    const looksFcp = /\.fcp$/i.test(file.name);
    el.uploadNote.hidden = looksFcp;
    if (!looksFcp) {
      // Client-side heads-up only; the server is the judge.
      el.uploadNote.textContent =
        '"' + file.name + '" doesn’t end in .fcp — uploading anyway.';
    }
    setUploadProgress(0);
    show('uploading');
    announce('Uploading ' + file.name);

    const gen = generation;
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload?name=' + encodeURIComponent(file.name));
    xhr.setRequestHeader('X-FCP', '1'); // CSRF guard: cross-origin no-cors can't set this
    xhr.upload.onprogress = (e) => {
      if (gen === generation && e.lengthComputable && e.total > 0) {
        setUploadProgress(e.loaded / e.total);
      }
    };
    xhr.onload = () => {
      if (gen !== generation) return;
      let data = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch (_) {
        // handled below
      }
      if (xhr.status === 200 && data && typeof data.job === 'string') {
        state.jobId = data.job;
        toParsing();
      } else {
        toError((data && data.error) || 'Upload failed (HTTP ' + xhr.status + ').');
      }
    };
    xhr.onerror = () => {
      if (gen === generation) toError('Network error during upload.');
    };
    xhr.send(file); // raw bytes, not FormData
  }

  // ---------- 3. parsing ----------

  function toParsing() {
    state.parseStart = Date.now();
    el.parsingFilename.textContent = state.filename;
    el.parsingElapsed.textContent = '0';
    show('parsing');
    announce('Cracking open ' + state.filename);
    schedule(tickElapsed, 500);
    schedule(pollJob, POLL_MS);
  }

  function tickElapsed() {
    el.parsingElapsed.textContent = String(Math.floor((Date.now() - state.parseStart) / 1000));
    schedule(tickElapsed, 500);
  }

  async function pollJob() {
    let data;
    try {
      data = await readJson(await fetch('/api/job/' + state.jobId));
    } catch (err) {
      toError(errorMessage(err));
      return;
    }
    if (data.status === 'ready') {
      toReady(data);
    } else if (data.status === 'error') {
      toError(data.error || 'Parsing failed.');
    } else {
      schedule(pollJob, POLL_MS);
    }
  }

  // ---------- 4. ready ----------

  function toReady(project) {
    state.project = project;
    // Pre-select everything that has content; empty sequences stay unticked.
    state.selected = new Set(
      project.sequences.filter((s) => s.clips > 0).map((s) => s.index)
    );
    el.projectSummary.textContent =
      project.filename + ' — ' + humanSize(project.size) + ' — ' +
      plural(project.sequences.length, 'sequence');
    renderTable(project.sequences);
    show('ready');
    syncSelection();
    announce(project.filename + ' parsed. ' + plural(project.sequences.length, 'sequence') + ' found.');
  }

  function renderTable(sequences) {
    el.seqTbody.textContent = '';
    for (const seq of sequences) {
      const tr = document.createElement('tr');
      if (seq.clips === 0) tr.classList.add('is-empty');

      const tdCheck = document.createElement('td');
      tdCheck.className = 'col-check';
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.dataset.index = String(seq.index);
      box.setAttribute('aria-label', 'Select ' + seq.name);
      tdCheck.appendChild(box);
      tr.appendChild(tdCheck);

      const cells = [
        ['cell-name', seq.name],
        ['cell-num', String(seq.fps)],
        ['cell-num', seq.width + '×' + seq.height],
        ['cell-num', seq.duration_tc],
      ];
      for (const [className, text] of cells) {
        const td = document.createElement('td');
        td.className = className;
        td.textContent = text;
        tr.appendChild(td);
      }

      box.addEventListener('change', () => {
        toggleIndex(seq.index, box.checked);
      });
      tr.addEventListener('click', (e) => {
        if (e.target === box) return; // the change handler already ran
        toggleIndex(seq.index, !state.selected.has(seq.index));
      });

      el.seqTbody.appendChild(tr);
    }
  }

  function toggleIndex(index, on) {
    if (on) state.selected.add(index);
    else state.selected.delete(index);
    syncSelection();
  }

  function syncSelection() {
    const boxes = el.seqTbody.querySelectorAll('input[type="checkbox"]');
    for (const box of boxes) {
      const checked = state.selected.has(Number(box.dataset.index));
      box.checked = checked;
      box.closest('tr').classList.toggle('is-selected', checked);
    }
    // Select-all tracks the non-empty sequences (matching the initial preselect).
    const selectable = state.project
      ? state.project.sequences.filter((s) => s.clips > 0)
      : [];
    const picked = state.selected.size;
    const allPicked =
      selectable.length > 0 && selectable.every((s) => state.selected.has(s.index));
    el.selectAll.checked = allPicked;
    el.selectAll.indeterminate = !allPicked && picked > 0;
    el.convertBtn.disabled = picked === 0;
    el.convertBtn.textContent = picked === 0
      ? 'Select sequences to convert'
      : 'Convert ' + plural(picked, 'sequence') + ' to XML';
  }

  // ---------- 5. converting ----------

  function setConvertProgress(done, total) {
    el.convertLabel.textContent =
      done.toLocaleString() + ' of ' + total.toLocaleString() + ' converted';
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;
    el.convertBar.style.width = pct + '%';
    el.convertProgress.setAttribute('aria-valuenow', String(pct));
  }

  async function startConvert() {
    const indices = [...state.selected].sort((a, b) => a - b);
    setConvertProgress(0, indices.length);
    show('converting');
    announce('Converting ' + plural(indices.length, 'sequence') + ' to XML.');
    let data;
    try {
      const res = await fetch('/api/convert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-FCP': '1' },
        body: JSON.stringify({ job: state.jobId, indices }),
      });
      data = await readJson(res);
    } catch (err) {
      toError(errorMessage(err));
      return;
    }
    if (typeof data.convert !== 'string') {
      toError('Unexpected response from the server.');
      return;
    }
    state.convertId = data.convert;
    schedule(pollConvert, POLL_MS);
  }

  async function pollConvert() {
    let data;
    try {
      data = await readJson(await fetch('/api/convert/' + state.convertId));
    } catch (err) {
      toError(errorMessage(err));
      return;
    }
    if (data.status === 'done') {
      toDone(Array.isArray(data.files) ? data.files : []);
    } else if (data.status === 'error') {
      toError(data.error || 'Conversion failed.');
    } else {
      setConvertProgress(Number(data.done) || 0, Number(data.total) || 0);
      schedule(pollConvert, POLL_MS);
    }
  }

  // ---------- 6. done ----------

  function toDone(files) {
    el.doneSummary.textContent =
      plural(files.length, 'XML file') + ' ready, from ' + state.filename + '.';
    el.downloadAll.textContent = files.length === 1 ? 'Download XML' : 'Download all (.zip)';
    el.downloadAll.href = '/api/download/' + state.convertId;
    el.doneFiles.textContent = '';
    for (const file of files) {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = '/api/download/' + state.convertId + '/' + file.index;
      a.textContent = file.name;
      const size = document.createElement('span');
      size.className = 'file-size';
      size.textContent = humanSize(file.bytes);
      li.appendChild(a);
      li.appendChild(size);
      el.doneFiles.appendChild(li);
    }
    el.doneFiles.hidden = files.length === 0;
    show('done');
    announce('Conversion complete. ' + plural(files.length, 'file') + ' ready to download.');
  }

  // ---------- 7. error ----------

  function toError(message) {
    el.errorMessage.textContent = message || 'Something went wrong.';
    el.retryBtn.textContent = state.project ? 'Back to sequences' : 'Try again';
    show('error');
    announce('Error: ' + (message || 'Something went wrong.'));
  }

  function retry() {
    if (state.project) {
      // The job is still parsed server-side; go back to the sequence list.
      show('ready');
      syncSelection();
      announce('Back to sequence list.');
    } else {
      toIdle();
    }
  }

  // ---------- wiring ----------

  el.fileInput.addEventListener('change', () => {
    handleChosenFile(el.fileInput.files[0]);
  });

  for (const type of ['dragenter', 'dragover']) {
    el.dropzone.addEventListener(type, (e) => {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
      el.dropzone.classList.add('is-dragover');
    });
  }
  el.dropzone.addEventListener('dragleave', (e) => {
    if (!el.dropzone.contains(e.relatedTarget)) {
      el.dropzone.classList.remove('is-dragover');
    }
  });
  el.dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    el.dropzone.classList.remove('is-dragover');
    if (state.view !== 'idle') return;
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    handleChosenFile(file);
  });

  // A drop that misses the zone must not navigate away from the app.
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => e.preventDefault());

  el.selectAll.addEventListener('change', () => {
    if (!state.project) return;
    state.selected = el.selectAll.checked
      ? new Set(state.project.sequences.filter((s) => s.clips > 0).map((s) => s.index))
      : new Set();
    syncSelection();
  });

  el.convertBtn.addEventListener('click', startConvert);
  el.backBtn.addEventListener('click', () => {
    show('ready');
    syncSelection();
    announce('Back to sequence list.');
  });
  el.resetBtn.addEventListener('click', toIdle);
  el.retryBtn.addEventListener('click', retry);
  el.quitBtn.addEventListener('click', quitApp);

  loadSession();
  toIdle();
})();

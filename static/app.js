const API = '/api';
let currentBots = [];
let editingBot = null;
let logInterval = null;

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    loadBots();
    loadSystem();
    setInterval(loadSystem, 5000);
    setInterval(loadBots, 8000);
});

// --- API helpers ---
async function api(path, opts = {}) {
    const res = await fetch(API + path, {
        headers: { 'Content-Type': 'application/json', ...opts.headers },
        ...opts,
    });
    return res.json();
}

function toast(msg, type = 'success') {
    const container = document.getElementById('toasts');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}

// --- System stats ---
async function loadSystem() {
    try {
        const s = await api('/system');
        document.getElementById('stat-cpu').textContent = s.cpu + '%';
        document.getElementById('stat-mem').textContent = s.mem_percent + '%';
        document.getElementById('stat-disk').textContent = s.disk_percent + '%';
        const tempEl = document.getElementById('stat-temp');
        if (s.temp !== null) {
            tempEl.textContent = Math.round(s.temp) + '°C';
            tempEl.closest('.stat').style.display = '';
        } else {
            tempEl.closest('.stat').style.display = 'none';
        }
    } catch (e) { /* retry next interval */ }
}

// --- Bots ---
async function loadBots() {
    try {
        currentBots = await api('/bots');
        renderBots();
    } catch (e) { /* retry next interval */ }
}

function renderBots() {
    const grid = document.getElementById('bot-grid');
    const count = document.getElementById('bot-count');
    const running = currentBots.filter(b => b.status === 'active').length;
    count.textContent = `${currentBots.length} services • ${running} actief`;

    if (currentBots.length === 0) {
        grid.innerHTML = `
            <div class="empty-state" style="grid-column:1/-1">
                <h3>Geen bots gevonden</h3>
                <p>Voeg je eerste bot of service toe om te beginnen.</p>
                <button class="btn btn-primary" onclick="openAddModal()">+ Toevoegen</button>
            </div>`;
        return;
    }

    grid.innerHTML = currentBots.map(bot => `
        <div class="bot-card" data-name="${bot.name}">
            <div class="bot-card-header">
                <div class="bot-name">
                    <span class="status-dot ${bot.status}"></span>
                    ${esc(bot.name)}
                </div>
                <span class="bot-status-text">${bot.status}</span>
            </div>
            <div class="bot-desc">${esc(bot.description) || '<em style="opacity:0.4">Geen beschrijving</em>'}</div>
            <div class="bot-command">${esc(bot.command) || '(geen commando)'}</div>
            <div class="bot-actions">
                ${bot.status === 'active'
                    ? `<button class="btn btn-sm" onclick="botAction('${bot.name}','stop')">Stop</button>
                       <button class="btn btn-sm" onclick="botAction('${bot.name}','restart')">Herstart</button>`
                    : `<button class="btn btn-sm btn-primary" onclick="botAction('${bot.name}','start')">Start</button>`}
                <button class="btn btn-sm" onclick="showLogs('${bot.name}')">Logs</button>
                ${bot.git_url ? `<button class="btn btn-sm" onclick="gitPull('${bot.name}')">Pull</button>` : ''}
                <button class="btn btn-sm" onclick="openEditModal('${bot.name}')">Bewerk</button>
                <button class="btn btn-sm btn-danger" onclick="deleteBot('${bot.name}')">Verwijder</button>
            </div>
        </div>
    `).join('');
}

function esc(s) {
    if (!s) return '';
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// --- Bot actions ---
async function botAction(name, action) {
    const labels = { start: 'Starten', stop: 'Stoppen', restart: 'Herstarten' };
    toast(`${labels[action]}...`, 'success');
    const res = await api(`/bots/${name}/${action}`, { method: 'POST' });
    if (res.status === 'ok') {
        toast(`${name} ${action === 'start' ? 'gestart' : action === 'stop' ? 'gestopt' : 'herstart'}`);
    } else {
        toast(`Fout: ${res.output}`, 'error');
    }
    setTimeout(loadBots, 1000);
}

async function gitPull(name) {
    toast('Git pull bezig...');
    const res = await api(`/bots/${name}/pull`, { method: 'POST' });
    if (res.status === 'ok') {
        toast(`Pull voltooid: ${res.output.substring(0, 100)}`);
    } else {
        toast(`Pull mislukt: ${res.output}`, 'error');
    }
}

async function deleteBot(name) {
    if (!confirm(`Weet je zeker dat je "${name}" wilt verwijderen? Dit verwijdert ook alle bestanden.`)) return;
    const res = await api(`/bots/${name}`, { method: 'DELETE' });
    if (res.status === 'ok') {
        toast(`${name} verwijderd`);
        loadBots();
    } else {
        toast(`Fout: ${res.error}`, 'error');
    }
}

// --- Logs ---
async function showLogs(name) {
    const viewer = document.getElementById('log-viewer');
    const title = document.getElementById('log-title');
    const content = document.getElementById('log-content');

    title.textContent = `Logs: ${name}`;
    viewer.classList.add('active');

    if (logInterval) clearInterval(logInterval);

    async function fetchLogs() {
        const res = await api(`/bots/${name}/logs`);
        content.textContent = res.logs || '(geen logs)';
        content.scrollTop = content.scrollHeight;
    }

    await fetchLogs();
    logInterval = setInterval(fetchLogs, 3000);
}

function closeLogs() {
    document.getElementById('log-viewer').classList.remove('active');
    if (logInterval) { clearInterval(logInterval); logInterval = null; }
}

// --- Add / Edit modal ---
function openAddModal() {
    editingBot = null;
    document.getElementById('modal-title').textContent = 'Bot toevoegen';
    document.getElementById('bot-form').reset();
    document.getElementById('env-list').innerHTML = '';
    document.getElementById('source-git').classList.add('active');
    document.getElementById('source-upload').classList.remove('active');
    document.getElementById('git-source').style.display = '';
    document.getElementById('upload-source').style.display = 'none';
    document.getElementById('upload-filename').textContent = '';
    addEnvRow();
    openModal('add-modal');
}

function openEditModal(name) {
    const bot = currentBots.find(b => b.name === name);
    if (!bot) return;
    editingBot = bot;

    document.getElementById('modal-title').textContent = `${name} bewerken`;
    document.getElementById('f-name').value = bot.name;
    document.getElementById('f-name').disabled = true;
    document.getElementById('f-desc').value = bot.description;
    document.getElementById('f-git').value = bot.git_url;
    document.getElementById('f-command').value = bot.command;
    document.getElementById('f-autorestart').checked = bot.auto_restart;
    document.getElementById('f-autostart').checked = bot.auto_start;

    const envList = document.getElementById('env-list');
    envList.innerHTML = '';
    const entries = Object.entries(bot.env || {});
    if (entries.length === 0) {
        addEnvRow();
    } else {
        entries.forEach(([k, v]) => addEnvRow(k, v));
    }

    openModal('add-modal');
}

function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
    document.getElementById('f-name').disabled = false;
}

// --- Source tabs ---
function setSource(type) {
    document.getElementById('source-git').classList.toggle('active', type === 'git');
    document.getElementById('source-upload').classList.toggle('active', type === 'upload');
    document.getElementById('git-source').style.display = type === 'git' ? '' : 'none';
    document.getElementById('upload-source').style.display = type === 'upload' ? '' : 'none';
}

// --- File upload ---
function setupUpload() {
    const area = document.getElementById('upload-area');
    const input = document.getElementById('upload-file');

    area.addEventListener('click', () => input.click());
    area.addEventListener('dragover', e => { e.preventDefault(); area.classList.add('dragover'); });
    area.addEventListener('dragleave', () => area.classList.remove('dragover'));
    area.addEventListener('drop', e => {
        e.preventDefault();
        area.classList.remove('dragover');
        if (e.dataTransfer.files.length) {
            input.files = e.dataTransfer.files;
            document.getElementById('upload-filename').textContent = e.dataTransfer.files[0].name;
        }
    });
    input.addEventListener('change', () => {
        document.getElementById('upload-filename').textContent = input.files[0]?.name || '';
    });
}
document.addEventListener('DOMContentLoaded', setupUpload);

// --- Env vars ---
function addEnvRow(key = '', val = '') {
    const list = document.getElementById('env-list');
    const row = document.createElement('div');
    row.className = 'env-row';
    row.innerHTML = `
        <input type="text" placeholder="KEY" value="${esc(key)}">
        <input type="text" placeholder="value" value="${esc(val)}">
        <button class="btn btn-sm btn-danger" onclick="this.parentElement.remove()" type="button">&times;</button>
    `;
    list.appendChild(row);
}

function getEnvVars() {
    const env = {};
    document.querySelectorAll('#env-list .env-row').forEach(row => {
        const inputs = row.querySelectorAll('input');
        const k = inputs[0].value.trim();
        const v = inputs[1].value.trim();
        if (k) env[k] = v;
    });
    return env;
}

// --- Submit ---
async function submitBot() {
    const name = document.getElementById('f-name').value.trim();
    if (!name) { toast('Naam is verplicht', 'error'); return; }

    const isUpload = document.getElementById('source-upload').classList.contains('active');
    const fileInput = document.getElementById('upload-file');

    if (editingBot) {
        const res = await api(`/bots/${editingBot.name}`, {
            method: 'PUT',
            body: JSON.stringify({
                command: document.getElementById('f-command').value.trim(),
                description: document.getElementById('f-desc').value.trim(),
                env: getEnvVars(),
                auto_restart: document.getElementById('f-autorestart').checked,
                auto_start: document.getElementById('f-autostart').checked,
            }),
        });
        if (res.status === 'ok') {
            toast(`${name} bijgewerkt`);
            closeModal('add-modal');
            loadBots();
        } else {
            toast(res.error, 'error');
        }
        return;
    }

    if (isUpload && fileInput.files.length > 0) {
        const fd = new FormData();
        fd.append('name', name);
        fd.append('description', document.getElementById('f-desc').value.trim());
        fd.append('command', document.getElementById('f-command').value.trim());
        fd.append('auto_restart', document.getElementById('f-autorestart').checked);
        fd.append('auto_start', document.getElementById('f-autostart').checked);
        fd.append('file', fileInput.files[0]);

        const envParts = [];
        document.querySelectorAll('#env-list .env-row').forEach(row => {
            const inputs = row.querySelectorAll('input');
            const k = inputs[0].value.trim();
            const v = inputs[1].value.trim();
            if (k) envParts.push(`${k}=${v}`);
        });
        fd.append('env', envParts.join('\n'));

        toast('Uploaden en installeren...');
        const res = await fetch(API + '/bots/upload', { method: 'POST', body: fd });
        const data = await res.json();

        if (data.status === 'ok') {
            toast(`${name} toegevoegd! Commando: ${data.command || '(stel in)'}`);
            closeModal('add-modal');
            loadBots();
        } else {
            toast(data.error, 'error');
        }
    } else {
        toast('Installeren...');
        const res = await api('/bots', {
            method: 'POST',
            body: JSON.stringify({
                name,
                git_url: document.getElementById('f-git').value.trim(),
                command: document.getElementById('f-command').value.trim(),
                description: document.getElementById('f-desc').value.trim(),
                env: getEnvVars(),
                auto_restart: document.getElementById('f-autorestart').checked,
                auto_start: document.getElementById('f-autostart').checked,
            }),
        });

        if (res.status === 'ok') {
            toast(`${name} toegevoegd! Commando: ${res.command || '(stel in)'}`);
            closeModal('add-modal');
            loadBots();
        } else {
            toast(res.error, 'error');
        }
    }
}

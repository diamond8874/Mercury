/**
 * Mercury DataCleaner - client logic.
 *
 * Pipeline the UI drives:
 *   1. Upload            -> the server reads + profiles the file in the background.
 *                           The read-out card fills in live. NO model is called.
 *   2. User states goal  -> POST /api/analyze (202) starts the AI analysis, which
 *                           chains into cleaning and plotting.
 *   3. Poll /status      -> profiling | profile_ready | analyzing | analyze_done
 *                           | processing | done | error
 *
 * All AI settings (provider / key / model / base URL) are sent per request, so
 * the app is not tied to any single vendor.
 */

const LLM_STORAGE_KEY = 'mercury_llm_config';
const API_TOKEN_KEY = 'mercury_api_token';

/**
 * Every backend call goes through here so the optional deployment token
 * (`MERCURY_API_TOKEN`) is attached consistently. With no token configured
 * this is a plain fetch.
 */
function apiFetch(url, options = {}) {
    const token = localStorage.getItem(API_TOKEN_KEY);
    if (!token) return fetch(url, options);
    return fetch(url, { ...options, headers: { ...(options.headers || {}), 'X-API-Key': token } });
}

/**
 * Same token for plain <a href> downloads, which cannot carry a header.
 * Only appended when a token is actually configured.
 */
function withToken(url) {
    const token = localStorage.getItem(API_TOKEN_KEY);
    if (!token || !url || url === '#') return url;
    return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
}

// Application State
const appState = {
    llm: loadLlmConfig(),
    providers: [],
    serverDefault: null,
    activeSessionId: null,
    sessionData: null,
    sessionsHistory: [],
    chartInstances: [],
    schemaRendered: false
};

/** Read saved provider settings, migrating the old Nvidia-only key if present. */
function loadLlmConfig() {
    let config = { apiKey: '', provider: '', model: '', baseUrl: '' };
    try {
        const stored = JSON.parse(localStorage.getItem(LLM_STORAGE_KEY) || 'null');
        if (stored && typeof stored === 'object') config = { ...config, ...stored };
    } catch (err) {
        console.warn('Could not parse stored LLM config:', err);
    }
    if (!config.apiKey) {
        const legacyKey = localStorage.getItem('nvidia_api_key');
        if (legacyKey) {
            config.apiKey = legacyKey;
            config.provider = config.provider || 'nvidia';
            localStorage.removeItem('nvidia_api_key');
            saveLlmConfig(config);
        }
    }
    return config;
}

function saveLlmConfig(config) {
    localStorage.setItem(LLM_STORAGE_KEY, JSON.stringify(config));
}

/** Connection fields merged into every request body that may reach a model. */
function llmPayload() {
    return {
        api_key: appState.llm.apiKey || '',
        provider: appState.llm.provider || '',
        model: appState.llm.model || '',
        base_url: appState.llm.baseUrl || ''
    };
}

// DOM Elements
const els = {
    apiStatus: document.getElementById('api-status'),
    openSettingsBtn: document.getElementById('open-settings-btn'),
    settingsModal: document.getElementById('settings-modal'),
    closeSettingsBtn: document.getElementById('close-settings-btn'),
    cancelSettingsBtn: document.getElementById('cancel-settings-btn'),
    saveSettingsBtn: document.getElementById('save-settings-btn'),
    settingsApiKey: document.getElementById('settings-api-key'),
    settingsProvider: document.getElementById('settings-provider'),
    settingsProviderHint: document.getElementById('settings-provider-hint'),
    settingsModel: document.getElementById('settings-model'),
    settingsModelList: document.getElementById('settings-model-list'),
    settingsBaseUrl: document.getElementById('settings-base-url'),
    settingsBaseUrlGroup: document.getElementById('settings-base-url-group'),
    settingsTestResult: document.getElementById('settings-test-result'),
    testConnectionBtn: document.getElementById('test-connection-btn'),
    loadModelsBtn: document.getElementById('load-models-btn'),
    toggleKeyVisibility: document.getElementById('toggle-key-visibility'),

    // Sidebar History
    sessionsList: document.getElementById('sessions-list'),
    newAnalysisBtn: document.getElementById('new-analysis-btn'),

    // Step 1: Upload, read-out & goal
    fileDropZone: document.getElementById('file-drop-zone'),
    fileInput: document.getElementById('file-input'),
    selectFileBtn: document.querySelector('.select-file-btn'),
    fileDetailsContainer: document.getElementById('file-details-container'),
    detailFilename: document.getElementById('detail-filename'),
    detailFilesize: document.getElementById('detail-filesize'),
    removeFileBtn: document.getElementById('remove-file-btn'),
    sheetSelectWrapper: document.getElementById('sheet-select-wrapper'),
    sheetSelect: document.getElementById('sheet-select'),
    goalInput: document.getElementById('goal-input'),
    presetBtns: document.querySelectorAll('.preset-btn'),
    analyzeDataBtn: document.getElementById('analyze-data-btn'),

    // Dataset read-out card
    datasetReadout: document.getElementById('dataset-readout'),
    readoutStatus: document.getElementById('readout-status'),
    readoutProgressFill: document.getElementById('readout-progress-fill'),
    readoutRows: document.getElementById('readout-rows'),
    readoutCols: document.getElementById('readout-cols'),
    readoutMissing: document.getElementById('readout-missing'),
    readoutDupes: document.getElementById('readout-dupes'),
    readoutTypes: document.getElementById('readout-types'),
    readoutWarnings: document.getElementById('readout-warnings'),

    // Workspace Header
    workspaceTitle: document.getElementById('workspace-title'),
    workspaceSubtitle: document.getElementById('workspace-subtitle'),

    // Step Sections
    sectionStep1: document.getElementById('section-step-1'),
    sectionSplitDashboard: document.getElementById('section-split-dashboard'),

    // Left Chat Panel
    chatMessages: document.getElementById('chat-messages'),
    chatInput: document.getElementById('chat-input'),
    chatSendBtn: document.getElementById('chat-send-btn'),
    chatSessionBadge: document.getElementById('chat-session-badge'),

    // Right Workspace Tabs
    tabButtons: document.querySelectorAll('.tab-btn'),
    tabPanes: document.querySelectorAll('.tab-pane'),
    tabBtnPreview: document.getElementById('tab-btn-preview'),
    tabBtnViz: document.getElementById('tab-btn-viz'),
    tabBtnExport: document.getElementById('tab-btn-export'),

    // Tab Content Details
    recTotalCols: document.getElementById('rec-total-cols'),
    recKeepCols: document.getElementById('rec-keep-cols'),
    recDropCols: document.getElementById('rec-drop-cols'),
    recTransformCols: document.getElementById('rec-transform-cols'),
    columnsRecommendationGrid: document.getElementById('columns-recommendation-grid'),
    processDataBtn: document.getElementById('process-data-btn'),

    cleanedPreviewTable: document.getElementById('cleaned-preview-table'),
    dashboardChartsGrid: document.getElementById('dashboard-charts-grid'),

    downloadBtn: document.getElementById('download-btn'),
    generatePdfBtn: document.getElementById('generate-pdf-btn'),
    downloadPdfLink: document.getElementById('download-pdf-link'),
    statFinalRows: document.getElementById('stat-final-rows'),
    statInitialRows: document.getElementById('stat-initial-rows'),
    statFinalCols: document.getElementById('stat-final-cols'),
    statDroppedCols: document.getElementById('stat-dropped-cols'),

    globalLoader: document.getElementById('global-loader'),
    loaderTitle: document.getElementById('loader-title'),
    loaderSubtitle: document.getElementById('loader-subtitle')
};

const chartColors = {
    primary: '#6366f1',
    primaryAlpha: 'rgba(99, 102, 241, 0.15)',
    accent: '#a855f7',
    success: '#10b981',
    danger: '#ef4444',
    palette: ['#6366f1', '#a855f7', '#10b981', '#f59e0b', '#3b82f6', '#ec4899', '#14b8a6']
};

document.addEventListener('DOMContentLoaded', () => {
    updateApiStatus();
    initSettingsModal();
    initDragAndDrop();
    initGoalPresets();
    initTabs();
    initChatConsole();
    initSidebarDrawer();

    els.newAnalysisBtn.addEventListener('click', startNewAnalysis);
    els.analyzeDataBtn.addEventListener('click', runAiSchemaAnalysis);
    els.processDataBtn.addEventListener('click', reprocessWithCurrentSchema);
    els.generatePdfBtn.addEventListener('click', compilePdfDiagnosticsReport);
    els.apiStatus.addEventListener('click', () => els.openSettingsBtn.click());
    els.sheetSelect.addEventListener('change', changeActiveSheet);

    fetchProviders();
    fetchSessionsHistory();
});

/* ------------------------------------------------------------------ *
 * Off-canvas sidebar (mobile / tablet)
 * ------------------------------------------------------------------ */

const MOBILE_BREAKPOINT = 1024;

function isMobileLayout() {
    return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`).matches;
}

function setSidebarOpen(open) {
    const container = document.getElementById('app-container');
    const toggle = document.getElementById('sidebar-toggle');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (!container) return;

    container.classList.toggle('sidebar-open', open);
    if (toggle) toggle.setAttribute('aria-expanded', String(open));
    if (backdrop) backdrop.hidden = !open;
    // Stop the page behind the drawer from scrolling with it.
    document.body.style.overflow = open && isMobileLayout() ? 'hidden' : '';
}

function closeSidebarOnMobile() {
    if (isMobileLayout()) setSidebarOpen(false);
}

function initSidebarDrawer() {
    const toggle = document.getElementById('sidebar-toggle');
    const backdrop = document.getElementById('sidebar-backdrop');
    const container = document.getElementById('app-container');

    if (toggle) {
        toggle.addEventListener('click', () =>
            setSidebarOpen(!container.classList.contains('sidebar-open')));
    }
    if (backdrop) backdrop.addEventListener('click', () => setSidebarOpen(false));

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            setSidebarOpen(false);
            els.settingsModal.classList.add('hidden');
        }
    });

    // Returning to the desktop layout must never leave the page scroll-locked.
    window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`)
        .addEventListener('change', () => setSidebarOpen(false));
}

/* ------------------------------------------------------------------ *
 * Small helpers
 * ------------------------------------------------------------------ */

/** Escape untrusted text (column names, samples) before it touches innerHTML. */
function esc(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

let _domIdCounter = 0;
function nextDomId(prefix) {
    _domIdCounter += 1;
    return `${prefix}-${_domIdCounter}`;
}

function showLoader(title, subtitle) {
    els.loaderTitle.textContent = title;
    els.loaderSubtitle.textContent = subtitle;
    updateLoaderProgress(0, 1);
    els.globalLoader.classList.remove('hidden');
}

function updateLoaderProgress(percent, activeStepIndex) {
    const progressFill = document.getElementById('loader-progress-fill');
    const progressPercent = document.getElementById('loader-progress-percent');
    if (progressFill) progressFill.style.width = `${percent}%`;
    if (progressPercent) progressPercent.textContent = `${percent}%`;

    for (let i = 1; i <= 4; i++) {
        const marker = document.getElementById(`step-marker-${i}`);
        if (!marker) continue;
        if (i < activeStepIndex) marker.className = 'progress-step-item completed';
        else if (i === activeStepIndex) marker.className = 'progress-step-item active';
        else marker.className = 'progress-step-item';
    }
}

function hideLoader() {
    els.globalLoader.classList.add('hidden');
}

/* ------------------------------------------------------------------ *
 * 1. PROVIDER / MODEL SETTINGS
 * ------------------------------------------------------------------ */

async function fetchProviders() {
    try {
        const response = await apiFetch('/api/providers');
        const data = await response.json();
        appState.providers = data.providers || [];
        appState.serverDefault = data.server_default || null;
        renderProviderOptions();
        updateApiStatus();
    } catch (err) {
        console.error('Could not load the provider catalog:', err);
    }
}

function renderProviderOptions() {
    if (!els.settingsProvider) return;
    els.settingsProvider.innerHTML = '<option value="">Auto-detect from key</option>';
    appState.providers.forEach(provider => {
        const option = document.createElement('option');
        option.value = provider.id;
        option.textContent = provider.label;
        els.settingsProvider.appendChild(option);
    });
    els.settingsProvider.value = appState.llm.provider || '';
    syncProviderHint();
}

function currentProviderMeta() {
    const id = els.settingsProvider.value || detectProviderFromKey(els.settingsApiKey.value.trim());
    return appState.providers.find(p => p.id === id) || null;
}

/** Mirror of the server-side prefix detection, for instant UI feedback. */
function detectProviderFromKey(key) {
    if (!key) return '';
    const candidates = [];
    appState.providers.forEach(provider => {
        (provider.key_prefixes || []).forEach(prefix => candidates.push([prefix, provider.id]));
    });
    candidates.sort((a, b) => b[0].length - a[0].length);
    const match = candidates.find(([prefix]) => key.startsWith(prefix));
    return match ? match[1] : '';
}

function syncProviderHint() {
    const meta = currentProviderMeta();
    const explicit = els.settingsProvider.value;

    if (meta) {
        const detected = !explicit ? ' (auto-detected)' : '';
        els.settingsProviderHint.textContent =
            `${meta.label}${detected} - default model: ${meta.default_model || 'not set'}` +
            `${meta.requires_key ? '' : ' - no API key required'}`;
        els.settingsModel.placeholder = meta.default_model || 'Model id';
        if (!els.settingsBaseUrl.value && meta.base_url) {
            els.settingsBaseUrl.placeholder = meta.base_url;
        }
        els.settingsBaseUrlGroup.style.display =
            (meta.id === 'custom' || !meta.base_url) ? 'block' : '';
    } else {
        els.settingsProviderHint.textContent =
            'Provider not recognised from the key. Pick one, or choose "Custom" and set a base URL.';
        els.settingsBaseUrlGroup.style.display = 'block';
    }
}

function updateApiStatus() {
    const indicator = els.apiStatus.querySelector('.status-indicator');
    const text = els.apiStatus.querySelector('.status-text');
    const { apiKey, provider, model } = appState.llm;

    if (apiKey && apiKey.toUpperCase() === 'MOCK') {
        indicator.className = 'status-indicator warning';
        text.textContent = 'Offline rule engine (MOCK)';
        return;
    }
    if (apiKey) {
        const id = provider || detectProviderFromKey(apiKey);
        const meta = appState.providers.find(p => p.id === id);
        indicator.className = 'status-indicator success';
        text.textContent = `${meta ? meta.label : (id || 'Custom provider')}${model ? ` / ${model}` : ''}`;
        return;
    }
    if (appState.serverDefault && appState.serverDefault.has_key) {
        indicator.className = 'status-indicator success';
        text.textContent = `Server key: ${appState.serverDefault.label}`;
        return;
    }
    indicator.className = 'status-indicator warning';
    text.textContent = 'No provider configured (offline mode)';
}

function initSettingsModal() {
    const accessTokenInput = document.getElementById('settings-access-token');
    const accessTokenGroup = document.getElementById('settings-access-token-group');

    // Only surface the token field when this deployment actually enforces one.
    apiFetch('/api/ready')
        .then(r => r.json())
        .then(info => {
            if (!info.auth_required && !localStorage.getItem(API_TOKEN_KEY)) {
                accessTokenGroup.style.display = 'none';
            }
        })
        .catch(() => { /* /api/ready is optional; keep the field visible */ });

    const openModal = () => {
        els.settingsApiKey.value = appState.llm.apiKey || '';
        els.settingsProvider.value = appState.llm.provider || '';
        els.settingsModel.value = appState.llm.model || '';
        els.settingsBaseUrl.value = appState.llm.baseUrl || '';
        accessTokenInput.value = localStorage.getItem(API_TOKEN_KEY) || '';
        els.settingsTestResult.classList.add('hidden');
        syncProviderHint();
        els.settingsModal.classList.remove('hidden');
    };
    const closeModal = () => els.settingsModal.classList.add('hidden');

    els.openSettingsBtn.addEventListener('click', openModal);
    els.closeSettingsBtn.addEventListener('click', closeModal);
    els.cancelSettingsBtn.addEventListener('click', closeModal);

    els.settingsApiKey.addEventListener('input', syncProviderHint);
    els.settingsProvider.addEventListener('change', () => {
        const meta = currentProviderMeta();
        if (meta && meta.base_url) els.settingsBaseUrl.value = '';
        syncProviderHint();
    });

    els.saveSettingsBtn.addEventListener('click', () => {
        appState.llm = {
            apiKey: els.settingsApiKey.value.trim(),
            provider: els.settingsProvider.value.trim(),
            model: els.settingsModel.value.trim(),
            baseUrl: els.settingsBaseUrl.value.trim()
        };
        saveLlmConfig(appState.llm);

        const token = accessTokenInput.value.trim();
        if (token) localStorage.setItem(API_TOKEN_KEY, token);
        else localStorage.removeItem(API_TOKEN_KEY);

        updateApiStatus();
        closeModal();
    });

    els.toggleKeyVisibility.addEventListener('click', () => {
        const type = els.settingsApiKey.getAttribute('type') === 'password' ? 'text' : 'password';
        els.settingsApiKey.setAttribute('type', type);
        const icon = els.toggleKeyVisibility.querySelector('i');
        icon.classList.toggle('fa-eye');
        icon.classList.toggle('fa-eye-slash');
    });

    els.testConnectionBtn.addEventListener('click', testLlmConnection);
    els.loadModelsBtn.addEventListener('click', loadAvailableModels);
}

function settingsFormPayload() {
    return {
        api_key: els.settingsApiKey.value.trim(),
        provider: els.settingsProvider.value.trim(),
        model: els.settingsModel.value.trim(),
        base_url: els.settingsBaseUrl.value.trim()
    };
}

function showTestResult(ok, message) {
    els.settingsTestResult.className = `settings-test-result ${ok ? 'ok' : 'fail'}`;
    els.settingsTestResult.innerHTML =
        `<i class="fa-solid ${ok ? 'fa-circle-check' : 'fa-circle-exclamation'}"></i> ${esc(message)}`;
    els.settingsTestResult.classList.remove('hidden');
}

async function testLlmConnection() {
    els.testConnectionBtn.disabled = true;
    els.testConnectionBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testing...';
    try {
        const response = await apiFetch('/api/llm/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settingsFormPayload())
        });
        const data = await response.json();
        const suffix = data.latency_ms ? ` (${data.latency_ms} ms)` : '';
        showTestResult(!!data.ok, `${data.message || 'No response'}${suffix}`);
    } catch (err) {
        showTestResult(false, err.message);
    } finally {
        els.testConnectionBtn.disabled = false;
        els.testConnectionBtn.innerHTML = '<i class="fa-solid fa-plug-circle-check"></i> Test connection';
    }
}

async function loadAvailableModels() {
    els.loadModelsBtn.disabled = true;
    els.loadModelsBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    try {
        const response = await apiFetch('/api/llm/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settingsFormPayload())
        });
        const data = await response.json();
        els.settingsModelList.innerHTML = '';
        (data.models || []).forEach(model => {
            const option = document.createElement('option');
            option.value = model;
            els.settingsModelList.appendChild(option);
        });
        if (data.models && data.models.length) {
            showTestResult(true, `${data.models.length} model(s) available - click the model field to pick one.`);
        } else {
            showTestResult(false, data.error || 'This provider does not expose a model list. Type the model id manually.');
        }
    } catch (err) {
        showTestResult(false, err.message);
    } finally {
        els.loadModelsBtn.disabled = false;
        els.loadModelsBtn.innerHTML = '<i class="fa-solid fa-list"></i> Load';
    }
}

/* ------------------------------------------------------------------ *
 * 2. SESSION HISTORY
 * ------------------------------------------------------------------ */

async function fetchSessionsHistory() {
    try {
        const response = await apiFetch('/api/sessions');
        appState.sessionsHistory = await response.json();
        renderSessionsList();
    } catch (err) {
        console.error('Error fetching session history:', err);
    }
}

function renderSessionsList() {
    const list = els.sessionsList;
    list.innerHTML = '';

    if (!appState.sessionsHistory.length) {
        list.innerHTML = '<div class="no-history">No past analyses</div>';
        return;
    }

    appState.sessionsHistory.forEach(session => {
        const item = document.createElement('div');
        item.className = `session-item ${appState.activeSessionId === session.session_id ? 'active' : ''}`;

        const dateStr = session.created_at ? new Date(session.created_at).toLocaleDateString() : '';
        const goalStr = session.goal || 'Goal not set';

        item.innerHTML = `
            <div class="session-info">
                <div class="session-name" title="${esc(session.name)}">${esc(session.name)}</div>
                <div class="session-goal" title="${esc(goalStr)}">${esc(dateStr)} - ${esc(goalStr)}</div>
            </div>
            <button class="delete-session-btn" title="Delete Session">
                <i class="fa-solid fa-trash-can"></i>
            </button>
        `;

        item.addEventListener('click', (e) => {
            if (e.target.closest('.delete-session-btn')) return;
            selectSession(session.session_id);
        });

        item.querySelector('.delete-session-btn').addEventListener('click', async (e) => {
            e.stopPropagation();
            if (confirm(`Are you sure you want to delete session "${session.name}"?`)) {
                await deleteSession(session.session_id);
            }
        });

        list.appendChild(item);
    });
}

async function deleteSession(sessionId) {
    try {
        const response = await apiFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        if (response.ok) {
            if (appState.activeSessionId === sessionId) startNewAnalysis();
            fetchSessionsHistory();
        } else {
            alert('Failed to delete session');
        }
    } catch (err) {
        console.error(err);
    }
}

async function selectSession(sessionId) {
    try {
        const response = await apiFetch(`/api/sessions/${sessionId}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Failed to load session');

        appState.activeSessionId = sessionId;
        appState.sessionData = data;
        renderLoadedSessionUI();
        renderSessionsList();
        closeSidebarOnMobile();
        return data;
    } catch (err) {
        console.error(err);
        alert(err.message);
        return null;
    }
}

function startNewAnalysis() {
    stopStatusPolling();
    closeSidebarOnMobile();
    appState.activeSessionId = null;
    appState.sessionData = null;
    appState.schemaRendered = false;

    els.fileInput.value = '';
    els.fileDropZone.classList.remove('hidden');
    els.fileDetailsContainer.classList.add('hidden');
    els.sheetSelectWrapper.classList.add('hidden');
    els.datasetReadout.classList.add('hidden');

    els.goalInput.value = '';
    els.analyzeDataBtn.disabled = true;
    els.processDataBtn.disabled = true;

    renderSessionsList();

    els.workspaceTitle.textContent = 'Data Upload & Objective';
    els.workspaceSubtitle.textContent =
        'Drop a dataset. Mercury reads it immediately and waits for your goal before analysing.';

    els.sectionStep1.classList.add('active');
    els.sectionSplitDashboard.classList.remove('active');
}

/* ------------------------------------------------------------------ *
 * 3. UPLOAD -> BACKGROUND READ (no AI call yet)
 * ------------------------------------------------------------------ */

function initDragAndDrop() {
    els.selectFileBtn.addEventListener('click', () => els.fileInput.click());

    els.fileInput.addEventListener('change', (e) => {
        if (e.target.files.length) uploadRawDatasetFile(e.target.files[0]);
    });

    ['dragenter', 'dragover'].forEach(eventName => {
        els.fileDropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            els.fileDropZone.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        els.fileDropZone.addEventListener(eventName, (e) => {
            e.preventDefault();
            els.fileDropZone.classList.remove('dragover');
        }, false);
    });

    els.fileDropZone.addEventListener('drop', (e) => {
        if (e.dataTransfer.files.length) uploadRawDatasetFile(e.dataTransfer.files[0]);
    });

    els.removeFileBtn.addEventListener('click', () => {
        if (appState.activeSessionId) deleteSession(appState.activeSessionId);
        else startNewAnalysis();
    });
}

async function uploadRawDatasetFile(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['xlsx', 'xls', 'csv'].includes(ext)) {
        alert('Unsupported file format. Please upload Excel (.xlsx, .xls) or CSV.');
        return;
    }

    showLoader('Uploading dataset...', 'Saving the file and opening it for a first read.');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await apiFetch('/api/upload', { method: 'POST', body: formData });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Upload failed');

        appState.activeSessionId = data.session_id;
        fetchSessionsHistory();
        await selectSession(data.session_id);

        // The server is already profiling. Track it in the read-out card
        // instead of a blocking overlay, so the user can type their goal now.
        hideLoader();
        beginProfileReadout(data);
        startStatusPolling(data.session_id);
    } catch (err) {
        hideLoader();
        console.error(err);
        alert(err.message);
        startNewAnalysis();
    }
}

/** Show the read-out card in its "reading" state right after upload. */
function beginProfileReadout(uploadData) {
    els.datasetReadout.classList.remove('hidden');
    els.readoutStatus.className = 'readout-status busy';
    els.readoutStatus.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Reading dataset&hellip;';
    els.readoutProgressFill.style.width = '10%';
    els.readoutRows.textContent = uploadData ? uploadData.row_count : '-';
    els.readoutCols.textContent = uploadData ? uploadData.col_count : '-';
    els.readoutMissing.textContent = '-';
    els.readoutDupes.textContent = '-';
    els.readoutTypes.innerHTML = '';
    els.readoutWarnings.innerHTML = '';
}

/** Fill the read-out card once background profiling reports back. */
function renderProfileSummary(summary) {
    if (!summary) return;
    els.datasetReadout.classList.remove('hidden');
    els.readoutStatus.className = 'readout-status ready';
    els.readoutStatus.innerHTML = '<i class="fa-solid fa-circle-check"></i> Dataset read &amp; profiled';
    els.readoutProgressFill.style.width = '100%';

    els.readoutRows.textContent = summary.shape ? summary.shape.rows : '-';
    els.readoutCols.textContent = summary.shape ? summary.shape.cols : '-';
    els.readoutMissing.textContent = `${summary.missing_pct ?? 0}%`;
    els.readoutDupes.textContent = summary.duplicate_rows ?? 0;

    const groups = [
        ['numeric', summary.numeric_columns],
        ['categorical', summary.categorical_columns],
        ['datetime', summary.datetime_columns]
    ];
    els.readoutTypes.innerHTML = groups
        .filter(([, cols]) => cols && cols.length)
        .map(([label, cols]) =>
            `<span class="type-chip type-${label}">${cols.length} ${label}</span>` +
            cols.slice(0, 4).map(c => `<span class="type-col">${esc(c)}</span>`).join(''))
        .join('');

    els.readoutWarnings.innerHTML = (summary.warnings || []).slice(0, 4)
        .map(w => `<li><i class="fa-solid fa-triangle-exclamation"></i> ${esc(w)}</li>`).join('');
}

async function changeActiveSheet() {
    if (!appState.activeSessionId) return;
    const sheetName = els.sheetSelect.value;
    beginProfileReadout(null);
    try {
        await apiFetch(`/api/sessions/${appState.activeSessionId}/sheet`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sheet_name: sheetName })
        });
        startStatusPolling(appState.activeSessionId);
    } catch (err) {
        console.error('Sheet switch failed:', err);
    }
}

/* ------------------------------------------------------------------ *
 * 4. GOAL -> FULL ANALYSIS + CLEANING + PLOTTING
 * ------------------------------------------------------------------ */

function initGoalPresets() {
    els.goalInput.addEventListener('input', (e) => {
        els.analyzeDataBtn.disabled = !(appState.activeSessionId && e.target.value.trim().length > 0);
    });

    els.presetBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            els.goalInput.value = btn.getAttribute('data-goal');
            els.analyzeDataBtn.disabled = !appState.activeSessionId;
        });
    });
}

async function runAiSchemaAnalysis() {
    const goal = els.goalInput.value.trim();
    if (!goal || !appState.activeSessionId) return;

    appState.schemaRendered = false;
    showLoader('Analysing your dataset...',
        'Reusing the profile that was built while you typed, then consulting the AI model.');
    updateLoaderProgress(5, 1);

    try {
        const response = await apiFetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: appState.activeSessionId,
                goal,
                sheet_name: els.sheetSelect.value || 'Default',
                ...llmPayload()
            })
        });

        const data = await response.json();
        if (!response.ok && response.status !== 202) {
            throw new Error(data.error || 'Failed to start analysis');
        }

        // The server runs analysis -> cleaning -> plotting; we just follow along.
        startStatusPolling(appState.activeSessionId);
    } catch (err) {
        hideLoader();
        console.error(err);
        alert(err.message);
    }
}

/** Re-run cleaning + plotting after manual schema edits. */
async function reprocessWithCurrentSchema() {
    if (!appState.activeSessionId || !appState.sessionData) return;
    els.processDataBtn.disabled = true;
    showBgProcessingIndicator(true);
    try {
        await apiFetch(`/api/sessions/${appState.activeSessionId}/trigger_process`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                column_actions: appState.sessionData.column_actions,
                sheet_name: els.sheetSelect.value || 'Default',
                ...llmPayload()
            })
        });
        startStatusPolling(appState.activeSessionId);
    } catch (err) {
        showBgProcessingIndicator(false);
        console.error('Reprocess failed:', err);
        alert(err.message);
    }
}

/* ------------------------------------------------------------------ *
 * 5. STATUS POLLING - one loop for the whole pipeline
 * ------------------------------------------------------------------ */

let _statusPollTimer = null;

function stopStatusPolling() {
    if (_statusPollTimer) {
        clearInterval(_statusPollTimer);
        _statusPollTimer = null;
    }
}

function startStatusPolling(sessionId) {
    stopStatusPolling();
    _statusPollTimer = setInterval(() => pollStatusOnce(sessionId), 1500);
    pollStatusOnce(sessionId);
}

async function pollStatusOnce(sessionId) {
    if (!appState.activeSessionId || appState.activeSessionId !== sessionId) {
        stopStatusPolling();
        return;
    }

    let job;
    try {
        const response = await apiFetch(`/api/sessions/${sessionId}/status`);
        job = await response.json();
    } catch (err) {
        console.warn('Status poll error:', err);
        return;
    }

    const pct = job.progress || 0;
    const message = job.progress_msg || '';

    switch (job.status) {
        // ---- Stage 1: reading the file, no AI involved ----------------
        case 'profiling':
            els.readoutProgressFill.style.width = `${Math.max(pct, 10)}%`;
            els.readoutStatus.className = 'readout-status busy';
            els.readoutStatus.innerHTML =
                `<i class="fa-solid fa-circle-notch fa-spin"></i> ${esc(message || 'Reading dataset…')}`;
            break;

        case 'profile_ready':
            stopStatusPolling();
            renderProfileSummary(job.result && job.result.profile_summary);
            break;

        // ---- Stage 2: analysis, only after the goal was submitted -----
        case 'analyzing':
            updateLoaderProgress(Math.max(pct, 5), 2);
            setLoaderSubtitle(message || 'Consulting the configured model...');
            break;

        case 'analyze_done':
            updateLoaderProgress(100, 2);
            setLoaderSubtitle('Recommendations ready - cleaning and plotting next...');
            if (!appState.schemaRendered) {
                await selectSession(sessionId);
                appState.schemaRendered = true;
            }
            break;

        // ---- Stage 3: cleaning + plotting -----------------------------
        case 'processing':
            if (!els.globalLoader.classList.contains('hidden')) {
                updateLoaderProgress(pct, pct < 75 ? 3 : 4);
                setLoaderSubtitle(message || 'Cleaning the dataset...');
            }
            showBgProcessingIndicator(true, `(${pct}%) ${message}`);
            break;

        case 'done':
            stopStatusPolling();
            updateLoaderProgress(100, 4);
            // The schema grid is normally drawn at analyze_done, but a fast
            // offline run can skip straight past it - so make sure it exists.
            if (!appState.schemaRendered) {
                await selectSession(sessionId);
                appState.schemaRendered = true;
            }
            applyProcessResult(job.result);
            hideLoader();
            showBgProcessingIndicator(false);
            fetchSessionsHistory();
            break;

        case 'error':
            stopStatusPolling();
            hideLoader();
            showBgProcessingIndicator(false);
            els.readoutStatus.className = 'readout-status fail';
            els.readoutStatus.innerHTML =
                `<i class="fa-solid fa-circle-exclamation"></i> ${esc(job.error || 'Failed')}`;
            if (els.sectionSplitDashboard.classList.contains('active')) {
                appendChatBubbleUI('assistant', `⚠️ Error: ${esc(job.error)}`, true);
            } else {
                alert(`Processing failed: ${job.error}`);
            }
            break;

        default:
            break;
    }
}

function setLoaderSubtitle(text) {
    if (els.loaderSubtitle) els.loaderSubtitle.textContent = text;
}

/** Paint stats, preview and charts from a finished processing run. */
function applyProcessResult(result) {
    if (!result) return;
    enableTabs(true);

    if (result.stats) {
        els.statFinalRows.textContent = result.stats.final_rows;
        els.statInitialRows.textContent = `(Original: ${result.stats.initial_rows})`;
        els.statFinalCols.textContent = result.stats.final_cols;
        els.statDroppedCols.textContent = `(Dropped: ${result.stats.dropped_columns.length})`;
    }

    if (result.download_url) {
        els.downloadBtn.setAttribute('href', withToken(result.download_url));
        els.downloadBtn.classList.remove('hidden');
        els.generatePdfBtn.classList.remove('hidden');
        els.downloadPdfLink.classList.add('hidden');
    }

    if (result.preview) renderTablePreview(result.preview);
    if (result.charts) renderCharts(result.charts);
    els.processDataBtn.disabled = true;
}

function showBgProcessingIndicator(show, text) {
    let pill = document.getElementById('bg-processing-pill');
    if (!pill) {
        pill = document.createElement('div');
        pill.id = 'bg-processing-pill';
        pill.className = 'bg-processing-pill';
        const workspacePanel = document.querySelector('.workspace-panel');
        if (workspacePanel) workspacePanel.prepend(pill);
    }
    pill.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> ${esc(text || 'Updating data in background…')}`;
    pill.style.display = show ? 'flex' : 'none';
}

/* ------------------------------------------------------------------ *
 * 6. TABS AND SESSION RENDERING
 * ------------------------------------------------------------------ */

function initTabs() {
    els.tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetPaneId = btn.getAttribute('data-tab');
            els.tabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            els.tabPanes.forEach(pane => pane.classList.toggle('active', pane.id === targetPaneId));
        });
    });
}

function enableTabs(enable) {
    els.tabBtnPreview.disabled = !enable;
    els.tabBtnViz.disabled = !enable;
    els.tabBtnExport.disabled = !enable;
}

function switchToTab(tabId) {
    const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
    if (btn) btn.click();
}

function renderLoadedSessionUI() {
    const session = appState.sessionData;

    // No goal yet -> stay on the upload/read-out/goal screen.
    if (!session.goal) {
        els.detailFilename.textContent = session.original_filename;
        els.detailFilesize.textContent = `${session.row_count} rows x ${session.col_count} columns`;
        els.fileDropZone.classList.add('hidden');
        els.fileDetailsContainer.classList.remove('hidden');

        if (session.sheets && session.sheets.length > 1) {
            els.sheetSelect.innerHTML = '';
            session.sheets.forEach(sheet => {
                const option = document.createElement('option');
                option.value = sheet;
                option.textContent = sheet;
                els.sheetSelect.appendChild(option);
            });
            els.sheetSelect.value = session.sheet_name || session.sheets[0];
            els.sheetSelectWrapper.classList.remove('hidden');
        } else {
            els.sheetSelectWrapper.classList.add('hidden');
        }

        els.analyzeDataBtn.disabled = !els.goalInput.value.trim();

        if (session.profile) {
            renderProfileSummary({
                shape: session.profile.shape,
                missing_pct: session.profile.missing_pct,
                duplicate_rows: session.profile.duplicate_rows,
                numeric_columns: session.profile.numeric_columns,
                categorical_columns: session.profile.categorical_columns,
                datetime_columns: session.profile.datetime_columns,
                warnings: session.profile.warnings
            });
        }

        els.workspaceTitle.textContent = 'Data Upload & Objective';
        els.workspaceSubtitle.textContent =
            'Dataset loaded. Tell Mercury your goal to start the full analysis.';
        els.sectionStep1.classList.add('active');
        els.sectionSplitDashboard.classList.remove('active');
        return;
    }

    // Goal is set -> dashboard.
    els.workspaceTitle.textContent = session.name;
    els.workspaceSubtitle.textContent = `Goal: ${session.goal}`;
    els.sectionStep1.classList.remove('active');
    els.sectionSplitDashboard.classList.add('active');

    renderChatMessages();
    renderSchemaActionsGrid();
    appState.schemaRendered = true;

    // Restore the last completed run so a reload does not lose the dashboard.
    if (session.bg_result) {
        applyProcessResult(session.bg_result);
    } else if (session.cleaned_filename) {
        enableTabs(true);
        els.downloadBtn.setAttribute('href', withToken(`/api/download/${session.cleaned_filename}`));
        els.downloadBtn.classList.remove('hidden');
    } else {
        enableTabs(false);
        switchToTab('tab-schema');
    }

    if (session.pdf_filename) {
        els.generatePdfBtn.classList.add('hidden');
        els.downloadPdfLink.setAttribute('href', withToken(`/api/sessions/${session.session_id}/download_pdf`));
        els.downloadPdfLink.classList.remove('hidden');
    }

    // A session reopened mid-run should keep following the pipeline.
    if (session.job && ['profiling', 'analyzing', 'processing'].includes(session.job.status)) {
        startStatusPolling(session.session_id);
    }
}

function renderChatMessages() {
    els.chatMessages.innerHTML = '';
    (appState.sessionData.chat_history || []).forEach(msg =>
        appendChatBubbleUI(msg.role, msg.content, false));
    els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

/**
 * Assistant messages may contain a small amount of trusted markup (the PDF
 * download link, <b>/<br>). User messages never do, so they are escaped.
 */
function appendChatBubbleUI(role, content, animate = true) {
    const bubble = document.createElement('div');
    bubble.className = `chat-message ${role}`;
    if (!animate) bubble.style.animation = 'none';

    const meta = document.createElement('span');
    meta.className = 'chat-message-meta';
    meta.textContent = role === 'user' ? 'You' : 'AI Assistant';

    const body = document.createElement('div');
    if (role === 'user') body.textContent = content;
    else body.innerHTML = sanitizeAssistantHtml(content);

    bubble.appendChild(meta);
    bubble.appendChild(body);
    els.chatMessages.appendChild(bubble);

    if (animate) els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

/** Escape everything, then re-allow a small tag whitelist and our PDF link. */
function sanitizeAssistantHtml(content) {
    let html = esc(content)
        .replace(/&lt;br\s*\/?&gt;/gi, '<br>')
        .replace(/&lt;(\/?)(b|strong|i|em|code|ul|li|p)&gt;/gi, '<$1$2>')
        .replace(/&lt;a href=&#39;(\/api\/sessions\/[\w-]+\/download_pdf)&#39;[^&]*?&gt;([\s\S]*?)&lt;\/a&gt;/gi,
            '<a href="$1" class="btn btn-emerald chat-inline-btn">$2</a>')
        .replace(/&lt;i class=&#39;([\w\s-]+)&#39;&gt;&lt;\/i&gt;/gi, '<i class="$1"></i>');
    return renderChatMarkdown(html);
}

/** Lightweight markdown: **bold**, *italic*, `code`, newlines. */
function renderChatMarkdown(text) {
    return text
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
}

/* ------------------------------------------------------------------ *
 * 7. SCHEMA GRID
 * ------------------------------------------------------------------ */

function renderSchemaActionsGrid() {
    const grid = els.columnsRecommendationGrid;
    grid.innerHTML = '';

    const session = appState.sessionData;
    if (!session.column_actions) session.column_actions = {};

    (session.columns || []).forEach(column => {
        if (!session.column_actions[column.name]) {
            session.column_actions[column.name] =
                { action: 'keep', reason: 'Default - kept as-is.', transformation: null };
        }
        const rec = session.column_actions[column.name];

        const card = document.createElement('div');
        card.className = `column-card ${rec.action}-status`;
        card.id = nextDomId('col-card');

        const sampleTags = (column.sample_values || [])
            .map(value => `<span class="sample-tag" title="${esc(value)}">${esc(value)}</span>`)
            .join('');

        const nullLabel = column.null_pct !== undefined
            ? `${column.null_pct}% null`
            : `${column.null_count || 0} nulls`;
        const kindLabel = column.semantic_type ? `<span>${esc(column.semantic_type)}</span>` : '';

        card.innerHTML = `
            <div class="col-card-header">
                <div class="col-name-wrapper">
                    <div class="col-name" title="${esc(column.name)}">${esc(column.name)}</div>
                    <div class="col-meta">
                        <span>${esc(column.type)}</span>
                        ${kindLabel}
                        <span>${esc(nullLabel)}</span>
                    </div>
                </div>
                <div class="col-selector-group">
                    <button class="action-selector ${rec.action === 'keep' ? 'active' : ''}" data-action="keep">Keep</button>
                    <button class="action-selector ${rec.action === 'transform' ? 'active' : ''}" data-action="transform">Trans</button>
                    <button class="action-selector ${rec.action === 'drop' ? 'active' : ''}" data-action="drop">Drop</button>
                </div>
            </div>
            <div class="col-card-body">
                <div class="ai-reasoning"><p>${esc(rec.reason)}</p></div>
                <div class="transformation-editor ${rec.action === 'transform' ? '' : 'hidden'}">
                    <label>Transformation Logic:</label>
                    <input type="text" class="transform-input" value="${esc(rec.transformation || '')}"
                           placeholder="e.g. Impute missing with median">
                </div>
                <div class="col-samples">
                    <span class="samples-label">Samples:</span>
                    <div class="samples-tags">${sampleTags || '<span class="text-muted font-size-xs">No data</span>'}</div>
                </div>
            </div>
        `;

        const buttons = card.querySelectorAll('.action-selector');
        buttons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = e.target.getAttribute('data-action');
                session.column_actions[column.name].action = action;

                buttons.forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                card.className = `column-card ${action}-status`;
                card.querySelector('.transformation-editor').classList.toggle('hidden', action !== 'transform');

                recalcSummaryCounts();
                els.processDataBtn.disabled = false;
            });
        });

        const transformInput = card.querySelector('.transform-input');
        transformInput.addEventListener('input', (e) => {
            session.column_actions[column.name].transformation = e.target.value;
            els.processDataBtn.disabled = false;
        });
        transformInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                transformInput.blur();
            }
        });

        grid.appendChild(card);
    });

    recalcSummaryCounts();
}

function recalcSummaryCounts() {
    let keep = 0, drop = 0, transform = 0;
    const values = Object.values(appState.sessionData.column_actions || {});
    values.forEach(v => {
        if (v.action === 'keep') keep++;
        else if (v.action === 'drop') drop++;
        else if (v.action === 'transform') transform++;
    });
    els.recTotalCols.textContent = values.length;
    els.recKeepCols.textContent = keep;
    els.recDropCols.textContent = drop;
    els.recTransformCols.textContent = transform;
}

/* ------------------------------------------------------------------ *
 * 8. PREVIEW AND CHARTS
 * ------------------------------------------------------------------ */

function renderTablePreview(previewRows) {
    const table = els.cleanedPreviewTable;
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    thead.innerHTML = '';
    tbody.innerHTML = '';

    if (!previewRows || !previewRows.length) {
        thead.innerHTML = '<tr><th>No Data Available</th></tr>';
        return;
    }

    const headers = Object.keys(previewRows[0]);
    const headerRow = document.createElement('tr');
    headers.forEach(header => {
        const th = document.createElement('th');
        th.textContent = header;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);

    previewRows.forEach(row => {
        const tr = document.createElement('tr');
        headers.forEach(header => {
            const td = document.createElement('td');
            td.textContent = row[header];
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function renderCharts(chartsData) {
    const grid = els.dashboardChartsGrid;

    appState.chartInstances.forEach(chart => chart.destroy());
    appState.chartInstances = [];
    grid.innerHTML = '';

    if (!chartsData || !chartsData.length) {
        grid.innerHTML = `
            <div class="glass-card chart-card" style="grid-column: 1 / -1; height: 180px; align-items: center; justify-content: center;">
                <p class="text-muted"><i class="fa-solid fa-chart-bar" style="font-size: 2rem; margin-bottom: 0.5rem;"></i><br>
                No charts yet. Ask the assistant for a plot, or reprocess the dataset.</p>
            </div>`;
        return;
    }

    chartsData.forEach((chart, index) => {
        const card = document.createElement('div');
        card.className = 'glass-card chart-card';
        const canvasId = nextDomId('chart-canvas');

        card.innerHTML = `
            <div class="chart-header">
                <h4>${esc(chart.title)}</h4>
                <p title="${esc(chart.description)}">${esc(chart.description)}</p>
            </div>
            <div class="chart-wrapper"><canvas id="${canvasId}"></canvas></div>
        `;
        grid.appendChild(card);

        try {
            const ctx = document.getElementById(canvasId).getContext('2d');
            appState.chartInstances.push(new Chart(ctx, buildChartConfig(chart, index)));
        } catch (err) {
            console.error(`Chart draw error for ${canvasId}:`, err);
        }
    });
}

function buildChartConfig(chart, index) {
    const axisTicks = { color: '#94a3b8', font: { size: 9 } };
    const gridLine = { color: 'rgba(255, 255, 255, 0.05)' };

    if (chart.chart_type === 'scatter') {
        return {
            type: 'scatter',
            data: {
                datasets: [{
                    label: `${chart.y_axis} vs ${chart.x_axis}`,
                    data: chart.points,
                    backgroundColor: chartColors.accent,
                    pointRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { title: { display: true, text: chart.x_axis, color: '#94a3b8' }, grid: gridLine, ticks: axisTicks },
                    y: { title: { display: true, text: chart.y_axis, color: '#94a3b8' }, grid: gridLine, ticks: axisTicks }
                }
            }
        };
    }

    if (chart.chart_type === 'pie') {
        return {
            type: 'pie',
            data: {
                labels: chart.labels,
                datasets: [{
                    data: chart.values,
                    backgroundColor: chartColors.palette,
                    borderWidth: 1,
                    borderColor: 'rgba(255, 255, 255, 0.1)'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'right', labels: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans', size: 9 } } }
                }
            }
        };
    }

    const isLine = chart.chart_type === 'line';
    const isHorizontal = chart.orientation === 'horizontal';
    // Correlation charts are signed, so colour negatives differently.
    const backgroundColor = isHorizontal
        ? chart.values.map(v => (v < 0 ? chartColors.danger : chartColors.primary))
        : (isLine ? chartColors.primaryAlpha : chartColors.palette[index % chartColors.palette.length]);

    return {
        type: isLine ? 'line' : 'bar',
        data: {
            labels: chart.labels,
            datasets: [{
                label: chart.y_axis || 'Value',
                data: chart.values,
                backgroundColor,
                borderColor: chartColors.primary,
                borderWidth: isLine ? 2 : 0,
                fill: isLine,
                tension: 0.35
            }]
        },
        options: {
            indexAxis: isHorizontal ? 'y' : 'x',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: isHorizontal ? gridLine : { display: false }, ticks: axisTicks },
                y: { grid: isHorizontal ? { display: false } : gridLine, ticks: axisTicks }
            }
        }
    };
}

/* ------------------------------------------------------------------ *
 * 9. CHAT
 * ------------------------------------------------------------------ */

function initChatConsole() {
    els.chatSendBtn.addEventListener('click', sendChatUserMessage);

    els.chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatUserMessage();
        }
    });

    document.querySelectorAll('.suggestion-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            els.chatInput.value = chip.getAttribute('data-text');
            sendChatUserMessage();
        });
    });
}

async function sendChatUserMessage() {
    const text = els.chatInput.value.trim();
    if (!text || !appState.activeSessionId) return;

    els.chatInput.value = '';
    els.chatInput.disabled = true;
    els.chatSendBtn.disabled = true;

    appendChatBubbleUI('user', text, true);

    const aiBubble = document.createElement('div');
    aiBubble.className = 'chat-message assistant streaming';
    const aiMeta = document.createElement('span');
    aiMeta.className = 'chat-message-meta';
    aiMeta.textContent = 'AI Assistant';
    const aiBody = document.createElement('div');
    aiBody.className = 'stream-body';
    aiBody.innerHTML = '<span class="typing-cursor">▋</span>';
    aiBubble.appendChild(aiMeta);
    aiBubble.appendChild(aiBody);
    els.chatMessages.appendChild(aiBubble);
    els.chatMessages.scrollTop = els.chatMessages.scrollHeight;

    let fullText = '';

    try {
        const response = await apiFetch(`/api/sessions/${appState.activeSessionId}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, ...llmPayload() })
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Stream request failed');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let eventType = 'message';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    eventType = line.slice(7).trim();
                    continue;
                }
                if (line === '') {
                    eventType = 'message';
                    continue;
                }
                if (!line.startsWith('data: ')) continue;

                const raw = line.slice(6).trim();
                if (!raw) continue;

                let parsed;
                try {
                    parsed = JSON.parse(raw);
                } catch (parseErr) {
                    continue; // keep-alive or partial line
                }

                if (eventType === 'schema_updates') {
                    if (parsed.column_actions) {
                        appState.sessionData.column_actions = parsed.column_actions;
                    }
                    if (parsed.schema_updates && Object.keys(parsed.schema_updates).length) {
                        renderSchemaActionsGrid();
                    }
                    if (parsed.trigger_reprocess) {
                        showBgProcessingIndicator(true);
                        startStatusPolling(appState.activeSessionId);
                    }
                } else if (eventType === 'charts') {
                    renderCharts(parsed.charts || []);
                    enableTabs(true);
                    switchToTab('tab-viz');
                } else if (eventType === 'done') {
                    fullText = parsed.full_message || fullText;
                    aiBody.innerHTML = sanitizeAssistantHtml(fullText);
                    aiBubble.classList.remove('streaming');
                } else if (parsed.token !== undefined) {
                    fullText += parsed.token;
                    aiBody.innerHTML = sanitizeAssistantHtml(fullText) + '<span class="typing-cursor">▋</span>';
                    els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
                }
            }
        }
    } catch (err) {
        console.error('Chat stream error:', err);
        aiBody.textContent = `⚠️ Failed: ${err.message}`;
        aiBubble.classList.remove('streaming');
    } finally {
        els.chatInput.disabled = false;
        els.chatSendBtn.disabled = false;
        els.chatInput.focus();
        const cursor = aiBubble.querySelector('.typing-cursor');
        if (cursor) cursor.remove();
    }
}

/* ------------------------------------------------------------------ *
 * 10. PDF REPORT
 * ------------------------------------------------------------------ */

async function compilePdfDiagnosticsReport() {
    if (!appState.activeSessionId) return;

    els.generatePdfBtn.disabled = true;
    els.generatePdfBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Compiling PDF...';

    try {
        const response = await apiFetch(`/api/sessions/${appState.activeSessionId}/pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(llmPayload())
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'PDF compilation failed');

        els.generatePdfBtn.classList.add('hidden');
        els.downloadPdfLink.setAttribute('href', withToken(data.pdf_url));
        els.downloadPdfLink.classList.remove('hidden');
        await selectSession(appState.activeSessionId);
    } catch (err) {
        console.error(err);
        alert(err.message);
    } finally {
        els.generatePdfBtn.disabled = false;
        els.generatePdfBtn.innerHTML = '<i class="fa-solid fa-gears"></i> Compile PDF Report';
    }
}

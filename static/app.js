// Application State
// NOTE: apiKey is stored in sessionStorage only (cleared when tab closes) — never localStorage.
const appState = {
    user: null,
    authMode: 'login',
    previewMode: 'after', // 'after' (cleaned) or 'before' (original)
    apiKey: sessionStorage.getItem('llm_api_key') || '',
    provider: localStorage.getItem('llm_provider') || '',
    model: localStorage.getItem('llm_model') || '',
    baseUrl: localStorage.getItem('llm_base_url') || '',
    activeSessionId: null,
    sessionData: null,
    sessionsHistory: [],
    chartInstances: []
};

/** Escape a string for safe insertion into innerHTML. */
function escapeHTML(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
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
    settingsModel: document.getElementById('settings-model'),
    settingsBaseUrl: document.getElementById('settings-base-url'),
    toggleKeyVisibility: document.getElementById('toggle-key-visibility'),

    // Authentication Elements
    authModal: document.getElementById('auth-modal'),
    closeAuthModalBtn: document.getElementById('close-auth-modal-btn'),
    openAuthModalBtn: document.getElementById('open-auth-modal-btn'),
    userProfileBadge: document.getElementById('user-profile-badge'),
    userNameDisplay: document.getElementById('user-name-display'),
    logoutBtn: document.getElementById('logout-btn'),
    authForm: document.getElementById('auth-form'),
    authUsername: document.getElementById('auth-username'),
    authPassword: document.getElementById('auth-password'),
    authRemember: document.getElementById('auth-remember'),
    authTabLogin: document.getElementById('auth-tab-login'),
    authTabRegister: document.getElementById('auth-tab-register'),
    authErrorAlert: document.getElementById('auth-error-alert'),
    authErrorText: document.getElementById('auth-error-text'),
    authSubmitBtn: document.getElementById('auth-submit-btn'),
    authSubmitText: document.getElementById('auth-submit-text'),
    authModalTitle: document.getElementById('auth-modal-title'),
    authModalSubtitle: document.getElementById('auth-modal-subtitle'),
    authTogglePrompt: document.getElementById('auth-toggle-prompt'),
    authToggleLink: document.getElementById('auth-toggle-link'),
    toggleAuthPassword: document.getElementById('toggle-auth-password'),
    
    // Sidebar History
    sessionsList: document.getElementById('sessions-list'),
    newAnalysisBtn: document.getElementById('new-analysis-btn'),
    
    // Step 1: Upload & Goal
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
    chatSuggestions: document.getElementById('chat-suggestions'),
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
    processDataBtn: document.getElementById('process-data-btn'), // null after button removal; kept for compatibility
    
    // Clean Preview Table & Controls
    cleanedPreviewTable: document.getElementById('cleaned-preview-table'),
    previewModeBefore: document.getElementById('preview-mode-before'),
    previewModeAfter: document.getElementById('preview-mode-after'),
    previewRowCountBadge: document.getElementById('preview-row-count-badge'),
    previewDiffIndicator: document.getElementById('preview-diff-indicator'),
    previewDiffCount: document.getElementById('preview-diff-count'),
    previewAppliedChangesCard: document.getElementById('preview-applied-changes-card'),
    previewChangesStatus: document.getElementById('preview-changes-status'),
    previewChangesMetrics: document.getElementById('preview-changes-metrics'),
    previewChangesDetails: document.getElementById('preview-changes-details'),
    
    // Visualizations Chart Grid
    dashboardChartsGrid: document.getElementById('dashboard-charts-grid'),
    
    // Export tab Elements
    downloadBtn: document.getElementById('download-btn'),
    generatePdfBtn: document.getElementById('generate-pdf-btn'),
    downloadPdfLink: document.getElementById('download-pdf-link'),
    statFinalRows: document.getElementById('stat-final-rows'),
    statInitialRows: document.getElementById('stat-initial-rows'),
    statFinalCols: document.getElementById('stat-final-cols'),
    statDroppedCols: document.getElementById('stat-dropped-cols'),
    
    // Global loader spinner
    globalLoader: document.getElementById('global-loader'),
    loaderTitle: document.getElementById('loader-title'),
    loaderSubtitle: document.getElementById('loader-subtitle')
};

// Colors for Chart.js
const chartColors = {
    primary: '#4f9bb5',
    primaryAlpha: 'rgba(79, 155, 181, 0.18)',
    accent: '#df9653',
    success: '#70b38d',
    palette: ['#4f9bb5', '#df9653', '#70b38d', '#c96f75', '#8299c2', '#ad8665', '#68a5a0']
};

// Start application hook
document.addEventListener('DOMContentLoaded', () => {
    updateApiStatus();
    initSettingsModal();
    initDragAndDrop();
    initGoalPresets();
    initTabs();
    initPreviewControls();
    initChatConsole();
    initSidebarHistory();
    initPowerBIBuilder();
    
    // Attach buttons events
    els.newAnalysisBtn.addEventListener('click', startNewAnalysis);
    els.analyzeDataBtn.addEventListener('click', runAiSchemaAnalysis);
    els.processDataBtn.addEventListener('click', executePandasProcess);
    els.generatePdfBtn.addEventListener('click', compilePdfDiagnosticsReport);

    // Initialize Authentication System and check existing login state
    initAuthSystem();
    checkAuthStatus();
});

// Helper - Loader displays
function showLoader(title, subtitle) {
    els.loaderTitle.textContent = title;
    els.loaderSubtitle.textContent = subtitle;
    
    // Reset loader progress fill and step dots
    updateLoaderProgress(0, 1);
    
    els.globalLoader.classList.remove('hidden');
}

function updateLoaderProgress(percent, activeStepIndex) {
    const progressFill = document.getElementById('loader-progress-fill');
    const progressPercent = document.getElementById('loader-progress-percent');
    if (progressFill) progressFill.style.width = `${percent}%`;
    if (progressPercent) progressPercent.textContent = `${percent}%`;
    
    // Highlight step markers
    for (let i = 1; i <= 4; i++) {
        const marker = document.getElementById(`step-marker-${i}`);
        if (!marker) continue;
        if (i < activeStepIndex) {
            marker.className = 'progress-step-item completed';
        } else if (i === activeStepIndex) {
            marker.className = 'progress-step-item active';
        } else {
            marker.className = 'progress-step-item';
        }
    }
}

function hideLoader() {
    els.globalLoader.classList.add('hidden');
}


// 1. API KEY SETTINGS MANAGEMENTS
function updateApiStatus() {
    const statusText = els.apiStatus.querySelector('.status-text');
    const indicator = els.apiStatus.querySelector('.status-indicator');

    let label = 'Default (NVIDIA)';
    if (appState.provider) {
        label = appState.provider.toUpperCase();
        if (appState.model) {
            label += `: ${appState.model}`;
        }
    } else if (appState.model) {
        label = `Auto: ${appState.model}`;
    }

    if (appState.apiKey) {
        indicator.className = 'status-indicator success';
        statusText.textContent = `${label} (Custom Key)`;
    } else {
        indicator.className = 'status-indicator warning';
        statusText.textContent = `${label} (Default)`;
    }

    // Fill the inputs in the modal
    if (els.settingsProvider) els.settingsProvider.value = appState.provider || '';
    if (els.settingsModel) els.settingsModel.value = appState.model || '';
    els.settingsApiKey.value = appState.apiKey || '';
    if (els.settingsBaseUrl) els.settingsBaseUrl.value = appState.baseUrl || '';
}

function initSettingsModal() {
    els.openSettingsBtn.addEventListener('click', () => {
        if (els.settingsProvider) els.settingsProvider.value = appState.provider || '';
        if (els.settingsModel) els.settingsModel.value = appState.model || '';
        els.settingsApiKey.value = appState.apiKey || '';
        if (els.settingsBaseUrl) els.settingsBaseUrl.value = appState.baseUrl || '';
        els.settingsModal.classList.remove('hidden');
    });
    
    const closeModal = () => {
        els.settingsModal.classList.add('hidden');
        els.settingsApiKey.value = appState.apiKey;
    };
    
    els.closeSettingsBtn.addEventListener('click', closeModal);
    els.cancelSettingsBtn.addEventListener('click', closeModal);
    
    els.saveSettingsBtn.addEventListener('click', () => {
        appState.provider = els.settingsProvider ? els.settingsProvider.value : '';
        appState.model = els.settingsModel ? els.settingsModel.value.trim() : '';
        appState.apiKey = els.settingsApiKey.value.trim();
        appState.baseUrl = els.settingsBaseUrl ? els.settingsBaseUrl.value.trim() : '';

        localStorage.setItem('llm_provider', appState.provider);
        localStorage.setItem('llm_model', appState.model);
        // API key stored in sessionStorage only — cleared automatically when tab closes
        sessionStorage.setItem('llm_api_key', appState.apiKey);
        localStorage.removeItem('nvidia_api_key'); // remove old persistent key if present
        localStorage.setItem('llm_base_url', appState.baseUrl);

        updateApiStatus();
        els.settingsModal.classList.add('hidden');
    });
    
    els.toggleKeyVisibility.addEventListener('click', () => {
        const type = els.settingsApiKey.getAttribute('type') === 'password' ? 'text' : 'password';
        els.settingsApiKey.setAttribute('type', type);
        const icon = els.toggleKeyVisibility.querySelector('i');
        icon.classList.toggle('fa-eye');
        icon.classList.toggle('fa-eye-slash');
    });
}

// 1B. AUTHENTICATION LIFECYCLE & HANDLERS
function initAuthSystem() {
    if (!els.authModal) return;

    // Switch to Login tab
    if (els.authTabLogin) {
        els.authTabLogin.addEventListener('click', () => setAuthMode('login'));
    }

    // Switch to Register tab
    if (els.authTabRegister) {
        els.authTabRegister.addEventListener('click', () => setAuthMode('register'));
    }

    // Switch via bottom helper link
    if (els.authToggleLink) {
        els.authToggleLink.addEventListener('click', (e) => {
            e.preventDefault();
            setAuthMode(appState.authMode === 'login' ? 'register' : 'login');
        });
    }

    // Password visibility toggle
    if (els.toggleAuthPassword && els.authPassword) {
        els.toggleAuthPassword.addEventListener('click', () => {
            const isPw = els.authPassword.getAttribute('type') === 'password';
            els.authPassword.setAttribute('type', isPw ? 'text' : 'password');
            const icon = els.toggleAuthPassword.querySelector('i');
            if (icon) {
                icon.classList.toggle('fa-eye', !isPw);
                icon.classList.toggle('fa-eye-slash', isPw);
            }
        });
    }

    // Modal close button
    if (els.closeAuthModalBtn) {
        els.closeAuthModalBtn.addEventListener('click', hideAuthModal);
    }

    // Header sign in button
    if (els.openAuthModalBtn) {
        els.openAuthModalBtn.addEventListener('click', () => showAuthModal(true));
    }

    // Header logout button
    if (els.logoutBtn) {
        els.logoutBtn.addEventListener('click', handleLogout);
    }

    // Form submit
    if (els.authForm) {
        els.authForm.addEventListener('submit', handleAuthSubmit);
    }
}

function setAuthMode(mode) {
    appState.authMode = mode;
    hideAuthError();

    if (mode === 'login') {
        if (els.authTabLogin) els.authTabLogin.classList.add('active');
        if (els.authTabRegister) els.authTabRegister.classList.remove('active');
        if (els.authModalTitle) els.authModalTitle.textContent = "Welcome to Mercury";
        if (els.authModalSubtitle) els.authModalSubtitle.textContent = "Sign in to access your sessions and datasets";
        if (els.authSubmitText) els.authSubmitText.textContent = "Sign In";
        if (els.authTogglePrompt) els.authTogglePrompt.textContent = "Don't have an account?";
        if (els.authToggleLink) els.authToggleLink.textContent = "Create one now";
        const remRow = document.getElementById('auth-remember-row');
        if (remRow) remRow.style.display = 'block';
    } else {
        if (els.authTabLogin) els.authTabLogin.classList.remove('active');
        if (els.authTabRegister) els.authTabRegister.classList.add('active');
        if (els.authModalTitle) els.authModalTitle.textContent = "Create an Account";
        if (els.authModalSubtitle) els.authModalSubtitle.textContent = "Set up your credentials to manage private datasets";
        if (els.authSubmitText) els.authSubmitText.textContent = "Create Account";
        if (els.authTogglePrompt) els.authTogglePrompt.textContent = "Already have an account?";
        if (els.authToggleLink) els.authToggleLink.textContent = "Sign in here";
        const remRow = document.getElementById('auth-remember-row');
        if (remRow) remRow.style.display = 'none';
    }
}

function showAuthError(msg) {
    if (els.authErrorAlert && els.authErrorText) {
        els.authErrorText.textContent = msg;
        els.authErrorAlert.classList.remove('hidden');
    }
}

function hideAuthError() {
    if (els.authErrorAlert) {
        els.authErrorAlert.classList.add('hidden');
    }
}

function showAuthModal(closable = false) {
    if (!els.authModal) return;
    if (els.closeAuthModalBtn) {
        els.closeAuthModalBtn.classList.toggle('hidden', !closable);
    }
    hideAuthError();
    els.authModal.classList.remove('hidden');
    if (els.authUsername) setTimeout(() => els.authUsername.focus(), 100);
}

function hideAuthModal() {
    if (els.authModal) {
        els.authModal.classList.add('hidden');
    }
}

async function checkAuthStatus() {
    try {
        const res = await fetch('/api/auth/me');
        const data = await res.json();

        if (res.ok && data.authenticated && data.user) {
            appState.user = data.user;
            if (els.userNameDisplay) els.userNameDisplay.textContent = data.user.username;
            if (els.userProfileBadge) els.userProfileBadge.classList.remove('hidden');
            if (els.openAuthModalBtn) els.openAuthModalBtn.classList.add('hidden');
            hideAuthModal();
            fetchSessionsHistory();
        } else {
            appState.user = null;
            if (els.userProfileBadge) els.userProfileBadge.classList.add('hidden');
            if (els.openAuthModalBtn) els.openAuthModalBtn.classList.remove('hidden');
            showAuthModal(false);
        }
    } catch (err) {
        console.error("Auth status verification error:", err);
        showAuthModal(false);
    }
}

async function handleAuthSubmit(e) {
    e.preventDefault();
    hideAuthError();

    const username = els.authUsername ? els.authUsername.value.trim() : '';
    const password = els.authPassword ? els.authPassword.value : '';
    const remember = els.authRemember ? els.authRemember.checked : true;

    if (!username || !password) {
        showAuthError("Please fill in both username and password.");
        return;
    }

    const endpoint = appState.authMode === 'login' ? '/api/auth/login' : '/api/auth/register';
    const payload = appState.authMode === 'login'
        ? { username, password, remember }
        : { username, password };

    if (els.authSubmitBtn) {
        els.authSubmitBtn.disabled = true;
        els.authSubmitBtn.style.opacity = '0.7';
    }

    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();

        if (!res.ok) {
            showAuthError(data.error || "Authentication failed. Please check your credentials.");
            return;
        }

        // Authentication successful
        appState.user = data.user;
        if (els.userNameDisplay) els.userNameDisplay.textContent = data.user.username;
        if (els.userProfileBadge) els.userProfileBadge.classList.remove('hidden');
        if (els.openAuthModalBtn) els.openAuthModalBtn.classList.add('hidden');

        if (els.authForm) els.authForm.reset();
        hideAuthModal();
        fetchSessionsHistory();

    } catch (err) {
        showAuthError("Network error: Unable to contact the server.");
    } finally {
        if (els.authSubmitBtn) {
            els.authSubmitBtn.disabled = false;
            els.authSubmitBtn.style.opacity = '';
        }
    }
}

async function handleLogout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } catch (err) {
        console.error("Logout error:", err);
    }

    appState.user = null;
    appState.activeSessionId = null;
    appState.sessionData = null;
    appState.sessionsHistory = [];

    if (els.userProfileBadge) els.userProfileBadge.classList.add('hidden');
    if (els.openAuthModalBtn) els.openAuthModalBtn.classList.remove('hidden');

    startNewAnalysis();
    renderSessionsList();
    setAuthMode('login');
    showAuthModal(false);
}

// 2. SIDEBAR SESSIONS HISTORY lifecycles
async function fetchSessionsHistory() {
    try {
        const response = await fetch('/api/sessions');
        if (response.status === 401) {
            appState.user = null;
            if (els.userProfileBadge) els.userProfileBadge.classList.add('hidden');
            if (els.openAuthModalBtn) els.openAuthModalBtn.classList.remove('hidden');
            showAuthModal(false);
            showAuthError("Session expired. Please sign in to continue.");
            return;
        }
        const data = await response.json();
        appState.sessionsHistory = Array.isArray(data) ? data : [];
        renderSessionsList();
    } catch (err) {
        console.error("Error fetching sessions list history:", err);
    }
}

function renderSessionsList() {
    const list = els.sessionsList;
    list.innerHTML = '';
    
    if (appState.sessionsHistory.length === 0) {
        list.innerHTML = '<div class="no-history">No past analyses</div>';
        return;
    }
    
    appState.sessionsHistory.forEach(session => {
        const item = document.createElement('div');
        item.className = `session-item ${appState.activeSessionId === session.session_id ? 'active' : ''}`;
        
        const dateStr = session.created_at ? new Date(session.created_at).toLocaleDateString() : '';
        const goalStr = session.goal || 'Goal not set';

        // Build session item with textContent to prevent XSS from user-entered goal/name
        const infoDiv = document.createElement('div');
        infoDiv.className = 'session-info';

        const nameDiv = document.createElement('div');
        nameDiv.className = 'session-name';
        nameDiv.title = session.name;
        nameDiv.textContent = session.name;

        const goalDiv = document.createElement('div');
        goalDiv.className = 'session-goal';
        goalDiv.title = goalStr;
        goalDiv.textContent = `${dateStr} - ${goalStr}`;

        infoDiv.appendChild(nameDiv);
        infoDiv.appendChild(goalDiv);

        const delBtn = document.createElement('button');
        delBtn.className = 'delete-session-btn';
        delBtn.title = 'Delete Session';
        delBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i>'; // static icon only

        item.appendChild(infoDiv);
        item.appendChild(delBtn);
        
        // Select session event
        item.addEventListener('click', (e) => {
            if (e.target.closest('.delete-session-btn')) return; // ignore delete clicks
            selectSession(session.session_id);
        });
        
        // Delete session event
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
        const response = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        if (response.ok) {
            if (appState.activeSessionId === sessionId) {
                startNewAnalysis();
            }
            fetchSessionsHistory();
        } else {
            alert("Failed to delete session");
        }
    } catch (err) {
        console.error(err);
    }
}

async function selectSession(sessionId) {
    showLoader('Loading Analysis Session...', 'Fetching session variables and data previews.');
    try {
        const response = await fetch(`/api/sessions/${sessionId}`);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Failed to load session');
        }
        
        appState.activeSessionId = sessionId;
        appState.sessionData = data;
        
        // Render panels
        renderLoadedSessionUI();
        
        // Highlight active list item
        renderSessionsList();
    } catch (err) {
        console.error(err);
        alert(err.message);
    } finally {
        hideLoader();
    }
}

function startNewAnalysis() {
    appState.activeSessionId = null;
    appState.sessionData = null;
    
    // Reset file uploads
    els.fileInput.value = '';
    els.fileDropZone.classList.remove('hidden');
    els.fileDetailsContainer.classList.add('hidden');
    els.sheetSelectWrapper.classList.add('hidden');
    
    // Reset goal
    els.goalInput.value = '';
    els.analyzeDataBtn.disabled = true;
    if (els.processDataBtn) {
        els.processDataBtn.disabled = true;
    }
    
    // Re-verify list item selections
    renderSessionsList();
    
    // Show Upload section, hide split screen
    els.workspaceTitle.textContent = "Data Upload & Objective";
    els.workspaceSubtitle.textContent = "Provide your raw training Excel file and state what model you plan to train.";
    
    els.sectionStep1.classList.add('active');
    els.sectionSplitDashboard.classList.remove('active');
}

// 3. FILE DRAG & DROP AND SHEET SELECTOR
function initDragAndDrop() {
    els.selectFileBtn.addEventListener('click', () => els.fileInput.click());
    
    els.fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadRawDatasetFile(e.target.files[0]);
        }
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
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            uploadRawDatasetFile(files[0]);
        }
    });
    
    els.removeFileBtn.addEventListener('click', () => {
        if (appState.activeSessionId) {
            deleteSession(appState.activeSessionId);
        } else {
            startNewAnalysis();
        }
    });
}

async function uploadRawDatasetFile(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['xlsx', 'xls', 'csv'].includes(ext)) {
        alert('Unsupported file format. Please upload Excel (.xlsx, .xls) or CSV.');
        return;
    }
    
    showLoader('Uploading Dataset...', 'Sending file metadata to local storage database.');
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });

        if (response.status === 401) {
            hideLoader();
            showAuthModal(false);
            showAuthError("Your session has expired. Please sign in to upload files.");
            return;
        }

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Upload failed');
        }
        
        appState.activeSessionId = data.session_id;
        
        // Refresh session lists
        fetchSessionsHistory();
        
        // Pull detail
        selectSession(data.session_id);
    } catch (err) {
        console.error(err);
        alert(err.message);
        startNewAnalysis();
    } finally {
        hideLoader();
    }
}

// 4. GOAL PRESETS
function initGoalPresets() {
    els.goalInput.addEventListener('input', (e) => {
        const isGoalFilled = e.target.value.trim().length > 0;
        els.analyzeDataBtn.disabled = !(appState.activeSessionId && isGoalFilled);
    });
    
    els.presetBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const val = btn.getAttribute('data-goal');
            els.goalInput.value = val;
            if (appState.activeSessionId) {
                els.analyzeDataBtn.disabled = false;
                els.analyzeDataBtn.click();
            }
        });
    });
}

// 5. WORKSPACE TABS SWITCHER
function initTabs() {
    els.tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetPaneId = btn.getAttribute('data-tab');
            
            // Toggle buttons classes
            els.tabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Toggle panes classes
            els.tabPanes.forEach(pane => {
                if (pane.id === targetPaneId) {
                    pane.classList.add('active');
                } else {
                    pane.classList.remove('active');
                }
            });
        });
    });
}

function enableTabs(enable) {
    // Data Preview and Visualizations are always accessible once a dataset is loaded
    els.tabBtnPreview.disabled = false;
    els.tabBtnViz.disabled = false;
    // Export Report tab requires cleaning completion
    els.tabBtnExport.disabled = !enable;
}

// Switch tabs utility
function switchToTab(tabId) {
    const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
    if (btn) btn.click();
}

// 6. RENDER STATE (POPULATES CHAT AND TABS FROM DATABASE)
function renderLoadedSessionUI() {
    const s = appState.sessionData;
    
    // If goal is empty, we show the upload panel step 1
    if (!s.goal) {
        // Populates upload detail
        els.detailFilename.textContent = s.original_filename;
        els.detailFilesize.textContent = `${s.row_count} rows x ${s.col_count} columns`;
        els.fileDropZone.classList.add('hidden');
        els.fileDetailsContainer.classList.remove('hidden');
        
        if (s.sheets && s.sheets.length > 1) {
            els.sheetSelect.innerHTML = '';
            s.sheets.forEach(sheet => {
                const opt = document.createElement('option');
                opt.value = sheet;
                opt.textContent = sheet;
                els.sheetSelect.appendChild(opt);
            });
            els.sheetSelectWrapper.classList.remove('hidden');
        } else {
            els.sheetSelectWrapper.classList.add('hidden');
        }
        
        els.goalInput.value = '';
        els.analyzeDataBtn.disabled = true;
        
        // Show Step 1
        els.workspaceTitle.textContent = "Data Upload & Objective";
        els.workspaceSubtitle.textContent = "Provide your raw training Excel file and state what model you plan to train.";
        els.sectionStep1.classList.add('active');
        els.sectionSplitDashboard.classList.remove('active');
        return;
    }
    
    // Show split screen dashboard
    els.workspaceTitle.textContent = s.name;
    els.workspaceSubtitle.textContent = '';
    
    els.sectionStep1.classList.remove('active');
    els.sectionSplitDashboard.classList.add('active');
    
    // Draw Chat history
    renderChatMessages();
    
    // Draw schema recomendations checklist
    renderSchemaActionsGrid();

    // Render Preview Table if preview data exists
    const previewToRender = (s.bg_result && s.bg_result.preview) ? s.bg_result.preview : s.preview;
    if (previewToRender && previewToRender.length > 0) {
        renderTablePreview(previewToRender);
    }

    // Render Charts if available
    const chartsToRender = (s.bg_result && s.bg_result.charts) ? s.bg_result.charts : s.charts;
    if (chartsToRender && chartsToRender.length > 0) {
        appState.chartInstances.forEach(c => c.destroy());
        appState.chartInstances = [];
        renderCharts(chartsToRender);
    }
    
    // If cleaned_filename exists (already processed) or bg_result exists
    if (s.cleaned_filename || (s.bg_result && s.bg_result.preview)) {
        enableTabs(true);
        // Stats
        const stats = s.bg_result?.stats;
        if (stats) {
            els.statFinalRows.textContent = stats.final_rows;
            els.statInitialRows.textContent = `(Original: ${stats.initial_rows})`;
            els.statFinalCols.textContent = stats.final_cols;
            els.statDroppedCols.textContent = `(Dropped: ${stats.dropped_columns ? stats.dropped_columns.length : 0})`;
        } else {
            els.statFinalRows.textContent = s.row_count;
            els.statFinalCols.textContent = s.column_actions ? Object.keys(s.column_actions).length : s.col_count;
        }
        
        // Build Excel Link
        if (s.cleaned_filename) {
            els.downloadBtn.setAttribute('href', `/api/download/${s.cleaned_filename}`);
            els.downloadBtn.classList.remove('hidden');
        }
        
        // PDF configuration
        if (s.pdf_filename) {
            els.generatePdfBtn.classList.add('hidden');
            els.downloadPdfLink.setAttribute('href', `/api/sessions/${s.session_id}/download_pdf`);
            els.downloadPdfLink.classList.remove('hidden');
        } else {
            els.generatePdfBtn.classList.remove('hidden');
            els.downloadPdfLink.classList.add('hidden');
        }
        if (els.processDataBtn) {
            els.processDataBtn.disabled = false;
        }
    } else {
        enableTabs(false);
        if (els.processDataBtn) {
            els.processDataBtn.disabled = true;
        }
    }
}

// Render chat messages
function renderChatMessages() {
    const container = els.chatMessages;
    container.innerHTML = '';
    
    const messages = appState.sessionData.chat_history || [];
    messages.forEach(msg => {
        appendChatBubbleUI(msg.role, msg.content, false);
    });
    
    // Scroll
    container.scrollTop = container.scrollHeight;
}

function appendChatBubbleUI(role, content, animate = true) {
    const bubble = document.createElement('div');
    bubble.className = `chat-message ${role}`;
    if (!animate) bubble.style.animation = 'none';
    
    const meta = document.createElement('span');
    meta.className = 'chat-message-meta';
    meta.textContent = role === 'user' ? 'You' : 'AI Assistant';
    
    const body = document.createElement('div');
    // Use renderChatMarkdown which HTML-escapes before re-adding safe bold/em/code/br
    body.innerHTML = renderChatMarkdown(content);
    
    bubble.appendChild(meta);
    bubble.appendChild(body);
    els.chatMessages.appendChild(bubble);
    
    if (animate) {
        els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
    }
}

async function runAiSchemaAnalysis() {
    const goal = els.goalInput.value.trim();
    if (!goal || !appState.activeSessionId) return;

    // Show loader IMMEDIATELY — it will now stay open and track REAL backend progress
    showLoader('AI is Parsing Dataset...', 'Sending to Nvidia GLM-5.2 — tracking progress below.');
    updateLoaderProgress(5, 1);

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: appState.activeSessionId,
                goal: goal,
                api_key: appState.apiKey,
                provider: appState.provider,
                model: appState.model,
                base_url: appState.baseUrl,
                sheet_name: els.sheetSelect.value || 'Default'
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to queue analysis');
        }

        // Analysis is now running in background — start polling for real progress
        // The loader stays open and updates itself via startStatusPolling
        startStatusPolling(appState.activeSessionId, { mode: 'analyze' });

    } catch (err) {
        hideLoader();
        console.error(err);
        alert(err.message);
    }
    // NOTE: we do NOT call hideLoader() here — startStatusPolling will do it when done
}


/** Fire the background process on the server (non-blocking) */
async function triggerBackgroundProcess() {
    if (!appState.activeSessionId) return;
    try {
        await fetch(`/api/sessions/${appState.activeSessionId}/trigger_process`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                api_key: appState.apiKey,
                sheet_name: els.sheetSelect ? els.sheetSelect.value || 'Default' : 'Default'
            })
        });
    } catch (err) {
        console.warn('trigger_process failed:', err);
    }
}

/** Poll /status every 2s for both analysis and data-processing jobs */
let _statusPollTimer = null;
let _statusPollCount = 0;
function startStatusPolling(sessionId, opts = {}) {
    // Cancel any existing poll
    if (_statusPollTimer) { clearInterval(_statusPollTimer); _statusPollTimer = null; }
    _statusPollCount = 0;
    const mode = opts.mode || 'process'; // 'analyze' | 'process'

    _statusPollTimer = setInterval(async () => {
        if (!appState.activeSessionId || appState.activeSessionId !== sessionId) {
            clearInterval(_statusPollTimer); _statusPollTimer = null; return;
        }
        _statusPollCount++;

        // Timeout safeguard (300s) - immediately force hide loader if slow
        if (_statusPollCount > 150) {
            clearInterval(_statusPollTimer); _statusPollTimer = null;
            showBgProcessingIndicator(false);
            hideLoader();
            return;
        }

        try {
            const res = await fetch(`/api/sessions/${sessionId}/status`);
            const job = await res.json();

            // ── ANALYZE PHASE ────────────────────────────────────────────────
            if (job.status === 'analyzing') {
                const pct = job.progress || 5;
                const msg = job.progress_msg || 'Consulting Nvidia GLM-5.2...';
                updateLoaderProgress(pct, _pctToStep(pct));
                // Update loader subtitle live
                const subtitle = document.getElementById('loader-subtitle');
                if (subtitle) subtitle.textContent = msg;

            } else if (job.status === 'analyze_done' && job.result) {
                clearInterval(_statusPollTimer); _statusPollTimer = null;

                // Flash 100% and close loader
                updateLoaderProgress(100, 5);
                await new Promise(r => setTimeout(r, 700));
                hideLoader();

                if (job.result.warning) console.warn('Analysis warning:', job.result.warning);

                // Refresh session to load schema grid
                await selectSession(appState.activeSessionId);

                // Auto-trigger background data processing
                showBgProcessingIndicator(true);
                await triggerBackgroundProcess();
                startStatusPolling(appState.activeSessionId, { mode: 'process' });

            // ── PROCESS PHASE ────────────────────────────────────────────────
            } else if (job.status === 'processing') {
                const pct = job.progress || 0;
                const msg = job.progress_msg || 'Updating data in background…';

                const pill = document.getElementById('bg-processing-pill');
                if (pill) pill.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> (${pct}%) ${msg}`;

                // If loader is somehow still open (edge case) update it too
                if (!els.globalLoader.classList.contains('hidden')) {
                    updateLoaderProgress(pct, _pctToStep(pct));
                }

            } else if (job.status === 'done' && job.result) {
                clearInterval(_statusPollTimer); _statusPollTimer = null;
                showBgProcessingIndicator(false);

                const d = job.result;
                enableTabs(true);

                if (d.stats) {
                    els.statFinalRows.textContent = d.stats.final_rows;
                    els.statInitialRows.textContent = `(Original: ${d.stats.initial_rows})`;
                    els.statFinalCols.textContent = d.stats.final_cols;
                    els.statDroppedCols.textContent = `(Dropped: ${d.stats.dropped_columns.length})`;
                }

                if (d.download_url) {
                    els.downloadBtn.setAttribute('href', d.download_url);
                    els.downloadBtn.classList.remove('hidden');
                    els.generatePdfBtn.classList.remove('hidden');
                    els.downloadPdfLink.classList.add('hidden');
                }

                if (d.preview) renderTablePreview(d.preview);

                if (d.charts) {
                    appState.chartInstances.forEach(c => c.destroy());
                    appState.chartInstances = [];
                    renderCharts(d.charts);
                }

                appendChatBubbleUI('assistant',
                    `✅ Dataset processed. Preview and charts have been updated.`, true);

            } else if (job.status === 'error') {
                clearInterval(_statusPollTimer); _statusPollTimer = null;
                showBgProcessingIndicator(false);
                hideLoader();
                if (appState.activeSessionId) {
                    await selectSession(appState.activeSessionId);
                }
                appendChatBubbleUI('assistant', `⚠️ Notice: ${job.error || 'AI analysis encountered an issue. Safe default actions have been prepared.'}`, true);
                console.warn('Job error:', job.error);
            } else if (job.status === 'idle') {
                clearInterval(_statusPollTimer); _statusPollTimer = null;
                showBgProcessingIndicator(false);
            }
        } catch (pollErr) {
            console.warn('Status poll error:', pollErr);
        }
    }, 2000);
}

/** Map a progress % to the step number shown in the loader checklist */
function _pctToStep(pct) {
    if (pct < 20) return 1;
    if (pct < 45) return 2;
    if (pct < 75) return 3;
    return 4;
}


/** Show/hide the subtle background processing indicator pill */
function showBgProcessingIndicator(show) {
    let pill = document.getElementById('bg-processing-pill');
    if (!pill) {
        pill = document.createElement('div');
        pill.id = 'bg-processing-pill';
        pill.className = 'bg-processing-pill';
        pill.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Updating data in background…';
        // Insert into workspace panel header
        const wsPanel = document.querySelector('.workspace-panel');
        if (wsPanel) wsPanel.prepend(pill);
    }
    pill.style.display = show ? 'flex' : 'none';
}



// Renders schema grid actions
function renderSchemaActionsGrid() {
    const grid = els.columnsRecommendationGrid;
    grid.innerHTML = '';
    
    const s = appState.sessionData;
    const originalCols = s.columns;
    
    originalCols.forEach(col => {
        const rec = s.column_actions[col.name] || { action: 'keep', reason: 'Default', transformation: '' };
        
        const card = document.createElement('div');
        card.className = `column-card ${rec.action}-status`;
        card.id = `col-card-${btoa(col.name).replace(/=/g, '')}`;
        
        // Build schema card safely with textContent for all user/dataset/LLM-sourced strings
        let badgeHtml = '';
        let cleanReason = escapeHTML(rec.reason || '');
        if (cleanReason.startsWith("AI Semantic Override:")) {
            badgeHtml = `<span class="reason-badge ai-badge"><i class="fas fa-brain"></i> AI Override</span>`;
            cleanReason = cleanReason.replace("AI Semantic Override:", "").trim();
        } else if (cleanReason.startsWith("Statistical Rule:") || cleanReason.startsWith("Pattern Rule:")) {
            badgeHtml = `<span class="reason-badge math-badge"><i class="fas fa-calculator"></i> Auto-Rule</span>`;
        } else if (cleanReason.startsWith("Cached AI Recommendation")) {
            badgeHtml = `<span class="reason-badge cache-badge"><i class="fas fa-bolt"></i> Cached AI</span>`;
        }

        card.innerHTML = `
            <div class="col-card-header">
                <div class="col-name-wrapper">
                    <div class="col-name" title="${escapeHTML(col.name)}">${escapeHTML(col.name)}</div>
                    <div class="col-meta">
                        <span>${escapeHTML(col.type)}</span>
                        <span>${escapeHTML(col.null_count)} nulls</span>
                    </div>
                </div>
                <div class="col-selector-group">
                    <button class="action-selector ${rec.action === 'keep' ? 'active' : ''}" data-action="keep">Keep</button>
                    <button class="action-selector ${rec.action === 'transform' ? 'active' : ''}" data-action="transform">Trans</button>
                    <button class="action-selector ${rec.action === 'drop' ? 'active' : ''}" data-action="drop">Drop</button>
                </div>
            </div>
            <div class="col-card-body">
                <div class="ai-reasoning">
                    ${badgeHtml}
                    <p>${cleanReason}</p>
                </div>
                <div class="transformation-editor ${rec.action === 'transform' ? '' : 'hidden'}">
                    <label>Transformation Logic:</label>
                    <input type="text" class="transform-input" value="${escapeHTML(rec.transformation || '')}" placeholder="e.g. Impute missing with median">
                </div>
                <div class="col-samples">
                    <span class="samples-label">Samples:</span>
                    <div class="samples-tags" id="samples-${escapeHTML(col.name)}"></div>
                </div>
            </div>
        `;
        // Build sample tags safely with textContent
        const samplesContainer = card.querySelector(`#samples-${escapeHTML(col.name)}`);
        if (col.sample_values && col.sample_values.length > 0) {
            col.sample_values.forEach(val => {
                const tag = document.createElement('span');
                tag.className = 'sample-tag';
                tag.title = String(val);
                tag.textContent = String(val);
                samplesContainer.appendChild(tag);
            });
        } else {
            const noData = document.createElement('span');
            noData.className = 'text-muted font-size-xs';
            noData.textContent = 'No data';
            samplesContainer.appendChild(noData);
        }
        
        // Manual override clicks
        const buttons = card.querySelectorAll('.action-selector');
        buttons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = e.target.getAttribute('data-action');
                
                // Update local state
                s.column_actions[col.name].action = action;
                
                buttons.forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                
                card.className = `column-card ${action}-status`;
                
                const transEditor = card.querySelector('.transformation-editor');
                if (action === 'transform') {
                    transEditor.classList.remove('hidden');
                } else {
                    transEditor.classList.add('hidden');
                }
                
                recalcSummaryCounts();
                els.processDataBtn.disabled = false;
            });
        });
        
        // Manual transform changes
        const transInput = card.querySelector('.transform-input');
        transInput.addEventListener('input', (e) => {
            s.column_actions[col.name].transformation = e.target.value;
        });

        // Trigger auto reprocess when user finishes editing transform text (on change or blur or enter)
        transInput.addEventListener('change', () => {
            els.processDataBtn.disabled = false;
            autoReprocessWithGridState();
        });
        transInput.addEventListener('blur', () => {
            els.processDataBtn.disabled = false;
            autoReprocessWithGridState();
        });
        transInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                transInput.blur();
            }
        });

        grid.appendChild(card);
    });

    recalcSummaryCounts();
}

/** Triggers background data processing on the server with current manual grid actions */
async function autoReprocessWithGridState() {
    if (!appState.activeSessionId) return;
    try {
        await executePandasProcess();
    } catch (err) {
        console.error('Auto-reprocess error:', err);
    }
}


function recalcSummaryCounts() {
    let keep = 0, drop = 0, trans = 0;
    const values = Object.values(appState.sessionData.column_actions);
    
    values.forEach(v => {
        if (v.action === 'keep') keep++;
        else if (v.action === 'drop') drop++;
        else if (v.action === 'transform') trans++;
    });
    
    els.recTotalCols.textContent = values.length;
    els.recKeepCols.textContent = keep;
    els.recDropCols.textContent = drop;
    els.recTransformCols.textContent = trans;
}

// 8. PANDAS DATA PROCESS (APPLY CLEAN RULES)
async function executePandasProcess() {
    if (!appState.activeSessionId) return;
    
    showLoader('Processing & Cleaning Data...', 'Pandas is rebuilding the dataset while Nvidia GLM-5.2 configures charts.');
    
    try {
        const response = await fetch('/api/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: appState.activeSessionId,
                actions: appState.sessionData.column_actions,
                api_key: appState.apiKey,
                provider: appState.provider,
                model: appState.model,
                base_url: appState.baseUrl,
                sheet_name: els.sheetSelect.value || 'Default'
            })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'Processing dataset failed');
        }
        
        // Enable preview tabs
        enableTabs(true);
        
        // Stats
        els.statFinalRows.textContent = data.stats.final_rows;
        els.statInitialRows.textContent = `(Original: ${data.stats.initial_rows})`;
        els.statFinalCols.textContent = data.stats.final_cols;
        els.statDroppedCols.textContent = `(Dropped: ${data.stats.dropped_columns.length})`;
        
        // Download Excel URL
        els.downloadBtn.setAttribute('href', data.download_url);
        els.downloadBtn.classList.remove('hidden');
        els.generatePdfBtn.classList.remove('hidden');
        els.downloadPdfLink.classList.add('hidden');
        
        // Draw previews
        renderTablePreview(data.preview);
        
        // Destroy existing Chart.js instances
        appState.chartInstances.forEach(chart => chart.destroy());
        appState.chartInstances = [];
        
        // Draw visualizations
        renderCharts(data.charts);
        
        // Reload session data history list
        fetchSessionsHistory();
        
        // Reload details state
        await selectSession(appState.activeSessionId);
        
        // Explicitly guarantee the new cleaned preview is rendered in the table and switch tab
        if (data.preview && data.preview.length > 0) {
            renderTablePreview(data.preview);
        }
        switchToTab('tab-preview');

        let successMessages = [];
        let errorMessages = [];
        if (data.audit_log && data.audit_log.length > 0) {
            data.audit_log.forEach(log => {
                if (log.status === "error") {
                    errorMessages.push(`- **${log.column || 'Dataset'}:** ${log.message}`);
                } else if (log.status === "success" && log.operation !== "keep_column" && !log.message.includes("No change")) {
                    successMessages.push(`- **${log.column || 'Dataset'}:** ${log.message}`);
                }
            });
        }
        
        let msg = '✅ Data cleaning is complete. Ask me what visualization you want next, and I will prepare it for you.';
        if (successMessages.length > 0) {
            msg += `\n\n**Applied Changes:**\n${successMessages.join('\n')}`;
        }
        if (errorMessages.length > 0) {
            msg += `\n\n**Failed to Update:**\n${errorMessages.join('\n')}`;
        }
        if (successMessages.length === 0 && errorMessages.length === 0) {
            msg += '\n\nNo data changes were applied.';
        }

        appendChatBubbleUI('assistant', msg, true);
        
    } catch (err) {
        console.error(err);
        alert(err.message);
    } finally {
        hideLoader();
    }
}

function initPreviewControls() {
    if (els.previewModeBefore) {
        els.previewModeBefore.addEventListener('click', () => {
            appState.previewMode = 'before';
            els.previewModeBefore.classList.add('active');
            els.previewModeAfter.classList.remove('active');
            renderTablePreview();
        });
    }
    if (els.previewModeAfter) {
        els.previewModeAfter.addEventListener('click', () => {
            appState.previewMode = 'after';
            els.previewModeAfter.classList.add('active');
            els.previewModeBefore.classList.remove('active');
            renderTablePreview();
        });
    }
}

function renderTablePreview(previewRows) {
    const table = els.cleanedPreviewTable;
    if (!table) return;
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    
    thead.innerHTML = '';
    tbody.innerHTML = '';
    
    const s = appState.sessionData;
    
    // Derive raw and clean rows
    const rawRows = (s && s.raw_preview && Array.isArray(s.raw_preview) && s.raw_preview.length > 0)
        ? s.raw_preview
        : [];
        
    let cleanRows = [];
    if (previewRows && Array.isArray(previewRows) && previewRows.length > 0) {
        cleanRows = previewRows;
    } else if (s) {
        cleanRows = (s.bg_result && s.bg_result.preview && s.bg_result.preview.length > 0)
            ? s.bg_result.preview
            : (s.preview || []);
    }
    
    // Active mode: 'before' (original) vs 'after' (cleaned)
    const mode = appState.previewMode || 'after';
    
    // Synchronize toggle button active classes
    if (els.previewModeBefore && els.previewModeAfter) {
        if (mode === 'before') {
            els.previewModeBefore.classList.add('active');
            els.previewModeAfter.classList.remove('active');
        } else {
            els.previewModeAfter.classList.add('active');
            els.previewModeBefore.classList.remove('active');
        }
    }
    
    let displayRows = [];
    if (mode === 'before') {
        displayRows = rawRows.length > 0 ? rawRows : cleanRows;
    } else {
        displayRows = cleanRows.length > 0 ? cleanRows : rawRows;
    }
    
    // Update row count badge
    if (els.previewRowCountBadge) {
        const modeLabel = mode === 'before' ? 'Original Data' : 'Cleaned Data';
        els.previewRowCountBadge.innerHTML = `<i class="fa-solid fa-table-rows"></i> Showing ${displayRows.length} Rows (${modeLabel})`;
    }
    
    if (!displayRows || displayRows.length === 0) {
        thead.innerHTML = '<tr><th>No Data Available</th></tr>';
        if (els.previewDiffIndicator) els.previewDiffIndicator.classList.add('hidden');
        renderAppliedChangesCard();
        return;
    }
    
    const headers = Object.keys(displayRows[0]);
    const headerRow = document.createElement('tr');
    headers.forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    
    let diffCount = 0;
    const isComparingCleaned = (mode === 'after' && rawRows.length > 0);
    
    displayRows.forEach((row, rowIdx) => {
        const tr = document.createElement('tr');
        headers.forEach(h => {
            const td = document.createElement('td');
            const cellVal = row[h];
            td.textContent = cellVal;
            td.contentEditable = "true";
            td.style.cursor = "pointer";
            
            // Check if cell was modified between raw and cleaned
            let isModified = false;
            let rawVal = undefined;
            if (isComparingCleaned && rawRows.length > rowIdx && (h in rawRows[rowIdx])) {
                rawVal = rawRows[rowIdx][h];
                if (String(cellVal ?? '') !== String(rawVal ?? '')) {
                    isModified = true;
                    diffCount++;
                }
            }
            
            if (isModified) {
                td.classList.add('cell-diff-modified');
                td.title = `Original: "${rawVal ?? ''}" → Cleaned: "${cellVal ?? ''}" (Click to edit)`;
            } else {
                td.title = "Click to edit cell value directly";
            }
            
            td.addEventListener('blur', async () => {
                const newVal = td.textContent.trim();
                if (appState.activeSessionId) {
                    try {
                        await fetch(`/api/sessions/${appState.activeSessionId}/update_cell`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ row_index: rowIdx, column_name: h, new_value: newVal })
                        });
                    } catch (err) {
                        console.error('Cell update failed:', err);
                    }
                }
            });
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    
    // Update diff indicator badge
    if (els.previewDiffIndicator && els.previewDiffCount) {
        if (diffCount > 0 && mode === 'after') {
            els.previewDiffCount.textContent = diffCount;
            els.previewDiffIndicator.classList.remove('hidden');
        } else {
            els.previewDiffIndicator.classList.add('hidden');
        }
    }
    
    // Render the changes summary card below the table
    renderAppliedChangesCard();
}

function renderAppliedChangesCard() {
    const s = appState.sessionData;
    if (!s || !els.previewChangesStatus) return;
    
    const statusBadge = els.previewChangesStatus;
    const metricsGrid = els.previewChangesMetrics;
    const detailsList = els.previewChangesDetails;
    
    metricsGrid.innerHTML = '';
    detailsList.innerHTML = '';
    
    const isCleaned = !!(s.cleaned_filename || (s.bg_result && s.bg_result.preview));
    
    // Status badge
    if (isCleaned) {
        statusBadge.textContent = 'Clean Processed';
        statusBadge.className = 'changes-status-badge active-clean';
    } else {
        statusBadge.textContent = 'Raw Data (Unprocessed)';
        statusBadge.className = 'changes-status-badge';
    }
    
    // Metrics
    const initialRows = s.stats?.initial_rows || s.row_count || 0;
    const finalRows = s.stats?.final_rows || s.row_count || 0;
    const initialCols = s.columns?.length || s.col_count || 0;
    const droppedColsCount = s.stats?.dropped_columns?.length || 0;
    const finalCols = s.stats?.final_cols || (initialCols - droppedColsCount);
    
    const transCols = Object.values(s.column_actions || {}).filter(a => a.action === 'transform').length;
    const auditCount = s.audit_log?.length || (s.stats?.transformations_applied?.length || 0);

    const metrics = [
        { label: 'Total Rows', val: Number(finalRows).toLocaleString() },
        { label: 'Active Columns', val: finalCols },
        { label: 'Columns Dropped', val: droppedColsCount },
        { label: 'Transformations', val: Math.max(transCols, auditCount) }
    ];
    
    metrics.forEach(m => {
        const box = document.createElement('div');
        box.className = 'change-metric-box';
        box.innerHTML = `
            <span class="change-metric-val">${escapeHTML(m.val)}</span>
            <span class="change-metric-lbl">${escapeHTML(m.label)}</span>
        `;
        metricsGrid.appendChild(box);
    });
    
    // Detailed list
    let hasDetails = false;
    
    // 1. From audit_log if available
    if (s.audit_log && s.audit_log.length > 0) {
        s.audit_log.forEach(entry => {
            hasDetails = true;
            const item = document.createElement('div');
            item.className = 'change-detail-item';
            const col = entry.column || entry.column_name || 'Dataset';
            const desc = entry.description || entry.message || entry.action || JSON.stringify(entry);
            item.innerHTML = `
                <i class="fa-solid fa-check-circle"></i>
                <div>
                    <span class="col-badge">${escapeHTML(col)}</span>
                    <span>${escapeHTML(desc)}</span>
                </div>
            `;
            detailsList.appendChild(item);
        });
    }
    
    // 2. From column_actions
    if (!hasDetails && s.column_actions && Object.keys(s.column_actions).length > 0) {
        Object.entries(s.column_actions).forEach(([colName, act]) => {
            if (act.action === 'transform' || act.action === 'drop') {
                hasDetails = true;
                const item = document.createElement('div');
                item.className = 'change-detail-item';
                const actionIcon = act.action === 'drop' ? 'fa-trash-can' : 'fa-wand-magic-sparkles';
                const actionColor = act.action === 'drop' ? 'var(--danger)' : '#10b981';
                const text = act.transformation || act.reason || (act.action === 'drop' ? 'Column dropped per objective' : 'Transformed');
                item.innerHTML = `
                    <i class="fa-solid ${actionIcon}" style="color: ${actionColor}"></i>
                    <div>
                        <span class="col-badge">${escapeHTML(colName)}</span>
                        <strong>${act.action.toUpperCase()}:</strong> <span>${escapeHTML(text)}</span>
                    </div>
                `;
                detailsList.appendChild(item);
            }
        });
    }
    
    // 3. Fallback / Empty message
    if (!hasDetails) {
        const emptyDiv = document.createElement('div');
        emptyDiv.className = 'change-detail-empty';
        if (isCleaned) {
            emptyDiv.innerHTML = '<i class="fa-solid fa-circle-info"></i> All columns retained per schema goal. No lossy modifications applied.';
        } else {
            emptyDiv.innerHTML = '<i class="fa-solid fa-circle-info"></i> No cleaning transformations processed yet. You are currently viewing the original raw data. Switch to <strong>Schema Actions</strong> to review recommended actions, then click <strong>Process Data</strong> or prompt the AI Assistant in chat.';
        }
        detailsList.appendChild(emptyDiv);
    }
}

function renderCharts(chartsData) {
    const grid = els.dashboardChartsGrid;
    grid.innerHTML = '';
    grid.classList.toggle('is-chart-grid', Array.isArray(chartsData) && chartsData.length > 1);
    
    if (!chartsData || chartsData.length === 0) {
        grid.innerHTML = '<div class="bi-placeholder"><span class="bi-placeholder-icon"><i class="fa-solid fa-chart-simple"></i></span><p class="viz-eyebrow">CHART WORKSPACE</p><h3>No suggested charts yet.</h3><p>Choose a visual from the gallery to begin.</p></div>';
        return;
    }
    
    chartsData.forEach((chart, index) => {
        const card = document.createElement('div');
        card.className = 'chart-card recommended-chart-card';
        
        const canvasId = `chart-canvas-${index}`;
        // Build chart card safely
        const chartHeader = document.createElement('div');
        chartHeader.className = 'chart-header';
        const h4 = document.createElement('h4');
        h4.textContent = chart.title;
        const desc = document.createElement('p');
        desc.title = chart.description;
        desc.textContent = chart.description;
        chartHeader.appendChild(h4);
        chartHeader.appendChild(desc);
        const chartWrapper = document.createElement('div');
        chartWrapper.className = 'chart-wrapper';
        const canvas = document.createElement('canvas');
        canvas.id = canvasId;
        chartWrapper.appendChild(canvas);
        card.appendChild(chartHeader);
        card.appendChild(chartWrapper);
        grid.appendChild(card);
        
        try {
            const ctx = document.getElementById(canvasId).getContext('2d');
            let config = {};
            const chartBaseOptions = {
                responsive: true,
                maintainAspectRatio: false,
                layout: { padding: { top: 8, right: 12, bottom: 4, left: 4 } },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(12, 18, 28, 0.96)',
                        borderColor: 'rgba(255, 255, 255, 0.12)',
                        borderWidth: 1,
                        titleColor: '#f1f5f9',
                        bodyColor: '#bdc8d6',
                        padding: 11,
                        cornerRadius: 5,
                        displayColors: true
                    }
                }
            };
            const axisOptions = {
                x: {
                    grid: { display: false },
                    border: { display: false },
                    ticks: { color: '#c0cad7', font: { family: 'Plus Jakarta Sans', size: 11 }, maxRotation: 0 }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(210, 222, 236, 0.12)', drawTicks: false },
                    border: { display: false },
                    ticks: { color: '#b2bece', padding: 9, font: { family: 'Plus Jakarta Sans', size: 11 } }
                }
            };
            const isCircular = ['pie', 'donut', 'doughnut'].includes(chart.chart_type);
            const chartType = chart.chart_type === 'donut' ? 'doughnut' : chart.chart_type;
            
            if (chart.chart_type === 'scatter') {
                config = {
                    type: 'scatter',
                    data: {
                        datasets: [{
                            label: `${chart.y_axis} vs ${chart.x_axis}`,
                            data: chart.points,
                            backgroundColor: chartColors.primary,
                            borderColor: chartColors.primary,
                            pointRadius: 3,
                            pointHoverRadius: 6
                        }]
                    },
                    options: {
                        ...chartBaseOptions,
                        scales: {
                            x: { ...axisOptions.x, grid: { color: 'rgba(210, 222, 236, 0.08)' } },
                            y: axisOptions.y
                        }
                    }
                };
            } else if (isCircular) {
                const isDonut = chartType === 'doughnut';
                config = {
                    type: chartType,
                    data: {
                        labels: chart.labels,
                        datasets: [{
                            data: chart.values,
                            backgroundColor: chartColors.palette,
                            borderWidth: 2,
                            borderColor: '#111a29',
                            hoverOffset: 7
                        }]
                    },
                    options: {
                        ...chartBaseOptions,
                        cutout: isDonut ? '62%' : 0,
                        plugins: {
                            ...chartBaseOptions.plugins,
                            legend: {
                                display: true,
                                position: 'bottom',
                                labels: {
                                    color: '#b4bfce',
                                    usePointStyle: true,
                                    pointStyle: 'circle',
                                    boxWidth: 7,
                                    boxHeight: 7,
                                    padding: 14,
                                    font: { family: 'Plus Jakarta Sans', size: 10 }
                                }
                            }
                        }
                    }
                };
            } else {
                const isLine = chart.chart_type === 'line';
                const seriesColor = chartColors.primary;
                config = {
                    type: isLine ? 'line' : 'bar',
                    data: {
                        labels: chart.labels,
                        datasets: [{
                            label: chart.y_axis || 'Frequency',
                            data: chart.values,
                            backgroundColor: isLine ? chartColors.primaryAlpha : seriesColor,
                            borderColor: seriesColor,
                            borderWidth: isLine ? 2.5 : 0,
                            fill: isLine,
                            tension: 0.24,
                            pointRadius: isLine ? 2 : 0,
                            pointHoverRadius: 5,
                            borderRadius: isLine ? 0 : 3,
                            maxBarThickness: 42
                        }]
                    },
                    options: {
                        ...chartBaseOptions,
                        scales: axisOptions
                    }
                };
            }
            
            const inst = new Chart(ctx, config);
            appState.chartInstances.push(inst);
        } catch (ex) {
            console.error(`Chart draw error for ${canvasId}:`, ex);
        }
    });
}

// 9. CONVERSATIONAL CHAT SUBMISSIONS
function initChatConsole() {
    els.chatSendBtn.addEventListener('click', sendChatUserMessage);
    
    els.chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatUserMessage();
        }
    });
    
    // Bind suggested chips
    document.querySelectorAll('.suggestion-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const txt = chip.getAttribute('data-text');
            els.chatInput.value = txt;
            sendChatUserMessage();
        });
    });
}

async function sendChatUserMessage() {
    const text = els.chatInput.value.trim();
    if (!text || !appState.activeSessionId) return;

    // Clear and disable inputs
    els.chatInput.value = '';
    els.chatInput.disabled = true;
    els.chatSendBtn.disabled = true;

    // Show user bubble immediately
    appendChatBubbleUI('user', text, true);

    // Create a streaming AI bubble with a blinking cursor
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
        const response = await fetch(`/api/sessions/${appState.activeSessionId}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                api_key: appState.apiKey,
                provider: appState.provider,
                model: appState.model,
                base_url: appState.baseUrl
            })
        });

        if (!response.ok) {
            const errData = await response.json();
            throw new Error(errData.error || 'Stream request failed');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Process complete SSE lines from the buffer
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep incomplete last line

            let eventType = 'message';
            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    eventType = line.slice(7).trim();
                } else if (line.startsWith('data: ')) {
                    const raw = line.slice(6).trim();
                    if (!raw) continue;

                    try {
                        const parsed = JSON.parse(raw);

                        if (eventType === 'schema_updates') {
                            // Apply schema updates to local state
                            if (parsed.column_actions) {
                                appState.sessionData.column_actions = parsed.column_actions;
                            }
                            renderSchemaActionsGrid();
                            if (els.processDataBtn) {
                                els.processDataBtn.disabled = false;
                            }
                            if (parsed.trigger_reprocess) {
                                startStatusPolling(appState.activeSessionId, { mode: 'process' });
                                showBgProcessingIndicator(true);
                                autoReprocessWithGridState();
                            }
                            eventType = 'message'; // Reset for next event

                        } else if (eventType === 'done') {
                            // Finalize bubble — remove cursor, render markdown-ish bold
                            fullText = parsed.full_message || fullText;
                            aiBody.innerHTML = renderChatMarkdown(fullText);
                            aiBubble.classList.remove('streaming');
                            eventType = 'message';

                        } else {
                            // Regular token — stream into bubble
                            if (parsed.token !== undefined) {
                                fullText += parsed.token;
                                aiBody.innerHTML = renderChatMarkdown(fullText) + '<span class="typing-cursor">▋</span>';
                                els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
                            }
                        }
                    } catch (parseErr) {
                        // Non-JSON line (e.g. empty keep-alive), ignore
                    }
                } else if (line === '') {
                    // Blank line = end of SSE event block; reset type
                    eventType = 'message';
                }
            }
        }

    } catch (err) {
        console.error('Chat stream error:', err);
        aiBody.innerHTML = `⚠️ Failed: ${err.message}`;
        aiBubble.classList.remove('streaming');
    } finally {
        els.chatInput.disabled = false;
        els.chatSendBtn.disabled = false;
        els.chatInput.focus();
        // Ensure cursor is gone
        const cursor = aiBubble.querySelector('.typing-cursor');
        if (cursor) cursor.remove();
    }
}

/** Lightweight markdown renderer: **bold**, *italic*, newlines */
function renderChatMarkdown(text) {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
}


// 10. PDF DIAGNOSTICS REPORT COMPILING
async function compilePdfDiagnosticsReport() {
    if (!appState.activeSessionId) return;
    
    els.generatePdfBtn.disabled = true;
    els.generatePdfBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Compiling PDF...';
    
    try {
        const response = await fetch(`/api/sessions/${appState.activeSessionId}/pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'PDF compilation failed');
        }
        
        // Update Export Card UI
        els.generatePdfBtn.classList.add('hidden');
        els.downloadPdfLink.setAttribute('href', data.pdf_url);
        els.downloadPdfLink.classList.remove('hidden');
        
        // Reload active session details to draw the downloaded PDF chat bubble confirmations
        await selectSession(appState.activeSessionId);
        
    } catch (err) {
        console.error(err);
        alert(err.message);
    } finally {
        els.generatePdfBtn.disabled = false;
        els.generatePdfBtn.innerHTML = '<i class="fa-solid fa-gears"></i> Compile PDF Report';
    }
}

function initSidebarHistory() {
    // Styling/scrolling helpers
}

function initPowerBIBuilder() {
    const aiBtn = document.getElementById('ai-viz-btn');
    const aiInput = document.getElementById('ai-viz-input');
    const canvas = document.getElementById('dashboard-charts-grid');
    const quickVizBtns = document.querySelectorAll('#ai-quick-viz-grid .bi-viz-btn');
    
    // Modal elements
    const configModal = document.getElementById('chart-config-modal');
    const closeModalBtn = document.getElementById('close-chart-modal-btn');
    const cancelModalBtn = document.getElementById('cancel-chart-modal-btn');
    const renderModalBtn = document.getElementById('render-chart-modal-btn');
    const modalXCol = document.getElementById('modal-x-col');
    const modalYCol = document.getElementById('modal-y-col');
    const modalXLabel = document.getElementById('modal-x-label');
    const modalYLabel = document.getElementById('modal-y-label');
    const modalCategoryInput = document.getElementById('modal-chart-category');
    const modalTypeInput = document.getElementById('modal-chart-type');
    const modalTitleSpan = document.getElementById('modal-chart-title');

    if(!aiBtn) return; // fail safe

    // Function to populate column dropdowns in modal with smart contextual labels & defaults
    const populateColumnDropdowns = (category, type) => {
        if (!appState.sessionData || !appState.sessionData.columns) return;
        modalXCol.innerHTML = '';
        modalYCol.innerHTML = '';

        appState.sessionData.columns.forEach(col => {
            const optX = document.createElement('option');
            optX.value = col.name;
            optX.textContent = `${col.name} (${col.type})`;
            modalXCol.appendChild(optX);

            const optY = document.createElement('option');
            optY.value = col.name;
            optY.textContent = `${col.name} (${col.type})`;
            modalYCol.appendChild(optY);
        });

        // Context-aware labels
        if (type === 'bubble_map' || category === 'geo') {
            if (modalXLabel) modalXLabel.textContent = 'Latitude Column';
            if (modalYLabel) modalYLabel.textContent = 'Longitude Column';

            // Smart detection of coordinate columns
            const latCol = appState.sessionData.columns.find(c => /lat|latitude/i.test(c.name));
            const lonCol = appState.sessionData.columns.find(c => /lon|lng|longitude/i.test(c.name));
            if (latCol) modalXCol.value = latCol.name;
            if (lonCol) modalYCol.value = lonCol.name;
        } else {
            if (modalXLabel) modalXLabel.textContent = 'X-Axis / Category Column';
            if (modalYLabel) modalYLabel.textContent = 'Y-Axis / Metric Column';

            // Smart default: pick first categorical for X, first numeric for Y
            const numCols = appState.sessionData.columns.filter(c => c.type.includes('int') || c.type.includes('float'));
            const catCols = appState.sessionData.columns.filter(c => !numCols.includes(c));

            if (catCols.length > 0) modalXCol.value = catCols[0].name;
            if (numCols.length > 0) modalYCol.value = numCols[0].name;
        }
    };

    // Quick Visual Picker Gallery Buttons -> Opens Modal
    quickVizBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            if (!appState.activeSessionId) return alert('Please upload a dataset first.');
            const category = btn.dataset.category || 'comparison';
            const type = btn.dataset.type || 'bar';

            modalCategoryInput.value = category;
            modalTypeInput.value = type;
            modalTitleSpan.textContent = `Configure ${type.toUpperCase().replace('_', ' ')} Visual`;

            populateColumnDropdowns(category, type);
            configModal.classList.remove('hidden');
        });
    });

    const hideChartModal = () => configModal.classList.add('hidden');
    if (closeModalBtn) closeModalBtn.addEventListener('click', hideChartModal);
    if (cancelModalBtn) cancelModalBtn.addEventListener('click', hideChartModal);

    // Modal Render Button -> Triggers custom_chart API
    if (renderModalBtn) {
        renderModalBtn.addEventListener('click', async () => {
            hideChartModal();
            const category = modalCategoryInput.value;
            const type = modalTypeInput.value;
            const xCol = modalXCol.value;
            const yCol = modalYCol.value;

            await renderCustomVisual({ chart_category: category, chart_type: type, x_col: xCol, y_col: yCol });
        });
    }

    // AI Text Prompt Generator
    aiBtn.addEventListener('click', async () => {
        const message = aiInput.value.trim();
        if(!message) return alert('Please enter a request for the AI.');
        if(!appState.activeSessionId) return alert('No active session.');

        const originalBtnText = aiBtn.innerHTML;
        aiBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...';
        aiBtn.disabled = true;

        try {
            const aiRes = await fetch(`/api/sessions/${appState.activeSessionId}/viz_chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: message,
                    api_key: appState.apiKey,
                    provider: appState.provider,
                    model: appState.model,
                    base_url: appState.baseUrl
                })
            });
            const aiData = await aiRes.json();
            if(!aiRes.ok) throw new Error(aiData.error || 'Failed to parse AI request');
            
            await renderCustomVisual(aiData.params);

        } catch (err) {
            alert(err.message);
        } finally {
            aiBtn.innerHTML = originalBtnText;
            aiBtn.disabled = false;
            aiInput.value = '';
        }
    });

    // Helper: Execute custom_chart API and display chart with "Add to Report" pinning
    async function renderCustomVisual(params) {
        appState.chartInstances.forEach(chart => chart.destroy());
        appState.chartInstances = [];
        canvas.innerHTML = '';
        canvas.classList.remove('is-chart-grid');
        const loadingState = document.createElement('div');
        loadingState.className = 'chart-loading-state';
        const loadingTitle = document.createElement('h4');
        const spinnerIcon = document.createElement('i');
        spinnerIcon.className = 'fa-solid fa-spinner fa-spin';
        loadingTitle.append(spinnerIcon, document.createTextNode(`  Rendering ${params.chart_type} visual...`));
        const loadingTrack = document.createElement('div');
        loadingTrack.className = 'chart-loading-track';
        loadingTrack.appendChild(document.createElement('span'));
        loadingState.append(loadingTitle, loadingTrack);
        canvas.appendChild(loadingState);

        try {
            const res = await fetch(`/api/sessions/${appState.activeSessionId}/custom_chart`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(params)
            });
            const data = await res.json();
            if(!res.ok) throw new Error(data.error || 'Failed to generate visual');

            canvas.innerHTML = '';

            const card = document.createElement('div');
            card.className = 'chart-card custom-chart-card';

            const titleText = `${params.y_col || ''} by ${params.x_col || ''} (${(params.chart_type || '').toUpperCase()})`;
            const header = document.createElement('div');
            header.className = 'custom-chart-header';
            const title = document.createElement('div');
            title.className = 'custom-chart-title';
            const titleIcon = document.createElement('i');
            titleIcon.className = 'fa-solid fa-chart-simple';
            const titleHeading = document.createElement('h4');
            titleHeading.textContent = titleText;
            title.append(titleIcon, titleHeading);
            const pinBtn = document.createElement('button');
            pinBtn.type = 'button';
            pinBtn.className = 'btn btn-secondary pin-report-btn';
            pinBtn.innerHTML = '<i class="fa-solid fa-thumbtack"></i> <span>Add to report</span>';
            header.append(title, pinBtn);
            card.appendChild(header);

            const contentDiv = document.createElement('div');
            contentDiv.className = 'custom-chart-content';

            if (data.chart.interactive_data) {
                const chartData = data.chart.interactive_data;
                const chartType = chartData.chart_type;
                const isCircular = chartType === 'pie' || chartType === 'donut';
                const isHorizontal = chartType === 'bar';
                const plot = document.createElement('div');
                plot.className = 'custom-chart-plot';
                const chartCanvas = document.createElement('canvas');
                chartCanvas.setAttribute('role', 'img');
                chartCanvas.setAttribute('aria-label', titleText);
                plot.appendChild(chartCanvas);
                contentDiv.appendChild(plot);

                const config = {
                    type: chartType === 'donut' ? 'doughnut' : chartType === 'area' ? 'line' : chartType === 'column' ? 'bar' : chartType,
                    data: {
                        labels: chartData.labels,
                        datasets: [{
                            label: chartData.y_axis,
                            data: chartType === 'scatter' ? chartData.points : chartData.values,
                            backgroundColor: isCircular ? chartData.values.map((_, index) => chartColors.palette[index % chartColors.palette.length]) : chartType === 'area' ? chartColors.primaryAlpha : chartColors.primary,
                            borderColor: chartColors.primary,
                            borderWidth: chartType === 'line' || chartType === 'area' ? 2.5 : 0,
                            fill: chartType === 'area',
                            tension: 0.24,
                            pointRadius: chartType === 'scatter' ? 3 : chartType === 'line' || chartType === 'area' ? 2 : 0,
                            pointHoverRadius: 6,
                            borderRadius: chartType === 'column' || chartType === 'bar' ? 3 : 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        indexAxis: chartType === 'bar' ? 'y' : 'x',
                        cutout: chartType === 'donut' ? '62%' : 0,
                        plugins: {
                            legend: {
                                display: isCircular,
                                position: 'bottom',
                                labels: { color: '#b4bfce', usePointStyle: true, pointStyle: 'circle' }
                            },
                            tooltip: {
                                callbacks: {
                                    label(context) {
                                        const value = chartType === 'scatter' ? context.parsed.y : isCircular ? context.parsed : isHorizontal ? context.parsed.x : context.parsed.y;
                                        return `${context.dataset.label || context.label}: ${new Intl.NumberFormat().format(value)}`;
                                    }
                                }
                            }
                        },
                        scales: isCircular ? {} : {
                            x: { beginAtZero: isHorizontal, ticks: { color: '#c0cad7' }, grid: { display: isHorizontal, color: 'rgba(210, 222, 236, 0.12)' } },
                            y: { beginAtZero: !isHorizontal, ticks: { color: '#b2bece' }, grid: { display: !isHorizontal, color: 'rgba(210, 222, 236, 0.12)' } }
                        }
                    }
                };
                if (chartType === 'scatter') {
                    config.data.datasets[0].label = `${chartData.y_axis} vs ${chartData.x_axis}`;
                    config.options.scales.x = { title: { display: true, text: chartData.x_axis, color: '#b2bece' }, ticks: { color: '#c0cad7' } };
                    config.options.scales.y.title = { display: true, text: chartData.y_axis, color: '#b2bece' };
                }
                appState.chartInstances.push(new Chart(chartCanvas.getContext('2d'), config));
            } else if (data.chart.type === 'image') {
                const img = document.createElement('img');
                img.src = `data:image/png;base64,${data.chart.data}`;
                img.className = 'custom-chart-image';
                img.alt = titleText;
                contentDiv.appendChild(img);
            } else if (data.chart.type === 'html') {
                contentDiv.innerHTML = data.chart.data;
            }
            card.appendChild(contentDiv);
            canvas.appendChild(card);

            // Bind Pin to Report Button
            if (pinBtn) {
                const chartPayload = {
                    title: titleText,
                    chart_type: params.chart_type,
                    x_axis: params.x_col,
                    y_axis: params.y_col,
                    description: `Custom visual generated for ${titleText}`
                };

                pinBtn.addEventListener('click', async () => {
                    try {
                        const pinRes = await fetch(`/api/sessions/${appState.activeSessionId}/pin_chart`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ chart: chartPayload })
                        });
                        const pinData = await pinRes.json();
                        if (!pinRes.ok) throw new Error(pinData.error);

                        const countSpan = document.getElementById('pinned-count-num');
                        if (countSpan) countSpan.textContent = pinData.pinned_count;

                        if (pinData.is_pinned) {
                            pinBtn.classList.add('is-pinned');
                            pinBtn.innerHTML = '<i class="fa-solid fa-circle-check"></i> <span>Pinned</span>';
                        } else {
                            pinBtn.classList.remove('is-pinned');
                            pinBtn.innerHTML = '<i class="fa-solid fa-thumbtack"></i> <span>Add to report</span>';
                        }
                    } catch (pinErr) {
                        alert(pinErr.message);
                    }
                });
            }

        } catch (err) {
            // Build error state safely — err.message set via textContent only
            canvas.innerHTML = '';
            const errDiv = document.createElement('div');
            errDiv.className = 'chart-error-state';
            const errorIcon = document.createElement('i');
            errorIcon.className = 'fa-solid fa-circle-exclamation';
            const errMsg = document.createElement('p');
            errMsg.textContent = err.message;
            errDiv.append(errorIcon, errMsg);
            canvas.appendChild(errDiv);
        }
    }
}

/* --- ENTERPRISE AUTOCOMPLETE & PROMPT LIBRARY --- */

const promptLibrary = [
    // --- Data Quality & Missing Values ---
    { text: "Delete columns that are mostly empty", category: "Data Quality", usage: "🔥 Highly Used" },
    { text: "Remove duplicate rows", category: "Data Quality", usage: "🔥 Highly Used" },
    { text: "Remove duplicates based on specific columns", category: "Data Quality", usage: "📊 88% Match" },
    { text: "Fill empty numbers with the average", category: "Missing Values", usage: "🔥 Highly Used" },
    { text: "Fill empty numbers with the median", category: "Missing Values", usage: "📊 92% Match" },
    { text: "Fill empty text with 'Unknown'", category: "Missing Values", usage: "📊 85% Match" },
    { text: "Delete rows that have missing values", category: "Missing Values", usage: "🤖 Data Science" },

    // --- Text & Formatting ---
    { text: "Convert text to lower case", category: "Text Formatting", usage: "📝 Formatting" },
    { text: "Convert text to upper case", category: "Text Formatting", usage: "📝 Formatting" },
    { text: "Trim extra spaces from text", category: "Text Formatting", usage: "🔥 Highly Used" },
    { text: "Remove punctuation from text", category: "Text Formatting", usage: "💡 Pro Tip" },
    { text: "Extract numbers from text", category: "Text Parsing", usage: "💡 Pro Tip" },
    { text: "Extract emails from text", category: "Text Parsing", usage: "💡 Pro Tip" },
    { text: "Calculate the length of text strings", category: "Text Parsing", usage: "🤖 Data Science" },
    { text: "Change Yes/No to 1/0", category: "Text Formatting", usage: "📊 88% Match" },

    // --- Dates & Times ---
    { text: "Fix dates to look the same", category: "Dates", usage: "🔥 Highly Used" },
    { text: "Extract the year from dates", category: "Dates", usage: "💡 Pro Tip" },
    { text: "Calculate age from birthdate", category: "Dates", usage: "🏥 Healthcare" },

    // --- Outliers & Math ---
    { text: "Remove extreme numbers (outliers)", category: "Math & Outliers", usage: "🤖 Data Science" },
    { text: "Rounding off the values to 2 decimals", category: "Math", usage: "📈 Finance" },
    { text: "Make negative numbers positive", category: "Math", usage: "📈 Finance" },
    { text: "Convert units (e.g., kg to lbs)", category: "Math", usage: "💡 Pro Tip" },

    // --- Sorting & ML ---
    { text: "Sort data in ascending order", category: "Sorting", usage: "🔥 Highly Used" },
    { text: "Sort data in descending order", category: "Sorting", usage: "🔥 Highly Used" },
    { text: "Remove ID columns", category: "Feature Selection", usage: "📊 94% Match" },
    { text: "Find the max and min values", category: "Analysis", usage: "📊 88% Match" },
    
    // --- Advanced Machine Learning ---
    { text: "Convert categories to numbers (Label Encode)", category: "Machine Learning", usage: "🤖 Data Science" },
    { text: "Create dummy variables (One-Hot Encode)", category: "Machine Learning", usage: "🤖 Data Science" },
    { text: "Scale numbers between 0 and 1 (Min-Max)", category: "Machine Learning", usage: "🤖 Data Science" },
    { text: "Standardize numbers to Z-scores", category: "Machine Learning", usage: "🤖 Data Science" },
    { text: "Apply log transformation to numbers", category: "Machine Learning", usage: "🤖 Data Science" }
];

function setupAutocomplete(inputId, dropdownId, isSchemaAware = false) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (!input || !dropdown) return;
    
    let selectedIdx = -1;
    let currentMatches = [];

    input.addEventListener("input", function(e) {
        const val = this.value.toLowerCase().trim();
        dropdown.innerHTML = "";
        selectedIdx = -1;
        
        if (!val) {
            dropdown.classList.add("hidden");
            return;
        }

        // Fuzzy match logic + Schema awareness
        currentMatches = [];
        const words = val.split(" ");
        
        // Let us dynamically inject column names if schema is aware
        let dynamicPrompts = [...promptLibrary];
        if (isSchemaAware && window.currentSession && window.currentSession.columns) {
            const numCols = window.currentSession.columns.filter(c => c.type.includes("int") || c.type.includes("float"));
            if (numCols.length > 0) {
                dynamicPrompts.push({ 
                    text: `Clip outliers in [${numCols[0].name}]`, 
                    category: "Dynamic", 
                    usage: "✨ Schema Match" 
                });
            }
        }

        dynamicPrompts.forEach(prompt => {
            const pText = prompt.text.toLowerCase();
            let matchScore = 0;
            words.forEach(w => {
                if (pText.includes(w)) matchScore++;
            });
            if (matchScore > 0 || val.length > 3 && pText.includes(val.substring(0,3))) {
                currentMatches.push({ ...prompt, score: matchScore });
            }
        });

        currentMatches.sort((a,b) => b.score - a.score);
        currentMatches = currentMatches.slice(0, 5); // top 5

        if (currentMatches.length === 0) {
            dropdown.classList.add("hidden");
            return;
        }

        currentMatches.forEach((match, idx) => {
            const div = document.createElement("div");
            div.className = "autocomplete-item";
            
            // Highlight matches
            let highlightedText = match.text;
            words.forEach(w => {
                if(w.length > 2) {
                    const regex = new RegExp(`(${w})`, "gi");
                    highlightedText = highlightedText.replace(regex, "<b>$1</b>");
                }
            });

            div.innerHTML = `
                <div class="autocomplete-title">${highlightedText}</div>
                <div class="autocomplete-meta">
                    <span>${match.category}</span>
                    <span class="${match.usage.includes("🔥") ? "badge-highly-used" : "badge-match"}">${match.usage}</span>
                </div>
            `;
            
            div.addEventListener("click", function() {
                input.value = match.text;
                dropdown.classList.add("hidden");
                input.focus();
            });
            dropdown.appendChild(div);
        });
        
        dropdown.classList.remove("hidden");
    });

    input.addEventListener("keydown", function(e) {
        if (dropdown.classList.contains("hidden")) return;
        const items = dropdown.getElementsByClassName("autocomplete-item");
        
        if (e.key === "ArrowDown") {
            e.preventDefault();
            selectedIdx++;
            if (selectedIdx >= items.length) selectedIdx = 0;
            updateSelection(items);
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            selectedIdx--;
            if (selectedIdx < 0) selectedIdx = items.length - 1;
            updateSelection(items);
        } else if (e.key === "Enter") {
            if (selectedIdx > -1) {
                e.preventDefault();
                items[selectedIdx].click();
            }
        }
    });

    function updateSelection(items) {
        for(let i=0; i<items.length; i++) {
            items[i].classList.remove("selected");
        }
        if(selectedIdx > -1 && items[selectedIdx]) {
            items[selectedIdx].classList.add("selected");
        }
    }

    document.addEventListener("click", function(e) {
        if(e.target !== input && e.target !== dropdown && !dropdown.contains(e.target)) {
            dropdown.classList.add("hidden");
        }
    });
}

// Initialize Autocomplete
document.addEventListener("DOMContentLoaded", () => {
    setupAutocomplete("goal-input", "goal-autocomplete", false);
    setupAutocomplete("chat-input", "chat-autocomplete", true);
});


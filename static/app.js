// Application State
const appState = {
    apiKey: localStorage.getItem('nvidia_api_key') || '',
    activeSessionId: null,
    sessionData: null,
    sessionsHistory: [],
    chartInstances: []
};

// DOM Elements
const els = {
    apiStatus: document.getElementById('api-status'),
    openSettingsBtn: document.getElementById('open-settings-btn'),
    settingsModal: document.getElementById('settings-modal'),
    closeSettingsBtn: document.getElementById('close-settings-btn'),
    cancelSettingsBtn: document.getElementById('cancel-settings-btn'),
    saveSettingsBtn: document.getElementById('save-settings-btn'),
    settingsApiKey: document.getElementById('settings-api-key'),
    toggleKeyVisibility: document.getElementById('toggle-key-visibility'),
    
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
    
    // Clean Preview Table
    cleanedPreviewTable: document.getElementById('cleaned-preview-table'),
    
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
    primary: '#6366f1',
    primaryAlpha: 'rgba(99, 102, 241, 0.15)',
    accent: '#a855f7',
    success: '#10b981',
    palette: ['#6366f1', '#a855f7', '#10b981', '#f59e0b', '#3b82f6', '#ec4899', '#14b8a6']
};

// Start application hook
document.addEventListener('DOMContentLoaded', () => {
    updateApiStatus();
    initSettingsModal();
    initDragAndDrop();
    initGoalPresets();
    initTabs();
    initChatConsole();
    initSidebarHistory();
    
    // Attach buttons events
    els.newAnalysisBtn.addEventListener('click', startNewAnalysis);
    els.analyzeDataBtn.addEventListener('click', runAiSchemaAnalysis);
    els.processDataBtn.addEventListener('click', executePandasProcess);
    els.generatePdfBtn.addEventListener('click', compilePdfDiagnosticsReport);

    // Load past session history lists
    fetchSessionsHistory();
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
    if (appState.apiKey) {
        els.apiStatus.querySelector('.status-indicator').className = 'status-indicator success';
        els.apiStatus.querySelector('.status-text').textContent = 'Custom Key Loaded';
        els.settingsApiKey.value = appState.apiKey;
    } else {
        els.apiStatus.querySelector('.status-indicator').className = 'status-indicator warning';
        els.apiStatus.querySelector('.status-text').textContent = 'Default Key Active';
        els.settingsApiKey.value = '';
    }
}

function initSettingsModal() {
    els.openSettingsBtn.addEventListener('click', () => els.settingsModal.classList.remove('hidden'));
    
    const closeModal = () => {
        els.settingsModal.classList.add('hidden');
        els.settingsApiKey.value = appState.apiKey;
    };
    
    els.closeSettingsBtn.addEventListener('click', closeModal);
    els.cancelSettingsBtn.addEventListener('click', closeModal);
    
    els.saveSettingsBtn.addEventListener('click', () => {
        const val = els.settingsApiKey.value.trim();
        appState.apiKey = val;
        localStorage.setItem('nvidia_api_key', val);
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

// 2. SIDEBAR SESSIONS HISTORY lifecycles
async function fetchSessionsHistory() {
    try {
        const response = await fetch('/api/sessions');
        const data = await response.json();
        appState.sessionsHistory = data;
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
        
        item.innerHTML = `
            <div class="session-info">
                <div class="session-name" title="${session.name}">${session.name}</div>
                <div class="session-goal" title="${goalStr}">${dateStr} - ${goalStr}</div>
            </div>
            <button class="delete-session-btn" title="Delete Session">
                <i class="fa-solid fa-trash-can"></i>
            </button>
        `;
        
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
            els.analyzeDataBtn.disabled = !(appState.activeSessionId);
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
    els.tabBtnPreview.disabled = !enable;
    els.tabBtnViz.disabled = !enable;
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
    
    // If goal is set, show split screen dashboard
    els.workspaceTitle.textContent = s.name;
    els.workspaceSubtitle.textContent = `Goal: ${s.goal}`;
    
    els.sectionStep1.classList.remove('active');
    els.sectionSplitDashboard.classList.add('active');
    
    // Draw Chat history
    renderChatMessages();
    
    // Draw schema recomendations checklist
    renderSchemaActionsGrid();
    
    // If cleaned_filename exists (already processed)
    if (s.cleaned_filename) {
        enableTabs(true);
        // Stats
        els.statFinalRows.textContent = s.row_count; // dummy, we'll fetch clean stats if available
        els.statFinalCols.textContent = Object.keys(s.column_actions).length;
        
        // Build Excel Link
        els.downloadBtn.setAttribute('href', `/api/download/${s.cleaned_filename}`);
        els.downloadBtn.classList.remove('hidden');
        
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
        switchToTab('tab-schema');
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
    body.innerHTML = content; // Allows links/HTML rendering
    
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
function startStatusPolling(sessionId, opts = {}) {
    // Cancel any existing poll
    if (_statusPollTimer) { clearInterval(_statusPollTimer); _statusPollTimer = null; }
    const mode = opts.mode || 'process'; // 'analyze' | 'process'

    _statusPollTimer = setInterval(async () => {
        if (!appState.activeSessionId || appState.activeSessionId !== sessionId) {
            clearInterval(_statusPollTimer); _statusPollTimer = null; return;
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
                appendChatBubbleUI('assistant', `⚠️ Error: ${job.error}`, true);
                console.warn('Job error:', job.error);
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
        
        const sampleTags = col.sample_values.map(val => `<span class="sample-tag" title="${val}">${val}</span>`).join('');
        
        card.innerHTML = `
            <div class="col-card-header">
                <div class="col-name-wrapper">
                    <div class="col-name" title="${col.name}">${col.name}</div>
                    <div class="col-meta">
                        <span>${col.type}</span>
                        <span>${col.null_count} nulls</span>
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
                    <p>${rec.reason}</p>
                </div>
                
                <div class="transformation-editor ${rec.action === 'transform' ? '' : 'hidden'}">
                    <label>Transformation Logic:</label>
                    <input type="text" class="transform-input" value="${rec.transformation || ''}" placeholder="e.g. Impute missing with median">
                </div>
                
                <div class="col-samples">
                    <span class="samples-label">Samples:</span>
                    <div class="samples-tags">${sampleTags || '<span class="text-muted font-size-xs">No data</span>'}</div>
                </div>
            </div>
        `;
        
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
        });
        transInput.addEventListener('blur', () => {
            els.processDataBtn.disabled = false;
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
    // Disabled: do not auto-trigger full processing on every schema change.
    // Users should press Process Data once they are happy with the schema actions.
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
        
        // Switch to preview tab
        switchToTab('tab-preview');

        appendChatBubbleUI('assistant', '✅ Data cleaning is complete. Ask me what visualization you want next, and I will prepare it for you.', true);
        
    } catch (err) {
        console.error(err);
        alert(err.message);
    } finally {
        hideLoader();
    }
}

function renderTablePreview(previewRows) {
    const table = els.cleanedPreviewTable;
    const thead = table.querySelector('thead');
    const tbody = table.querySelector('tbody');
    
    thead.innerHTML = '';
    tbody.innerHTML = '';
    
    if (!previewRows || previewRows.length === 0) {
        thead.innerHTML = '<tr><th>No Data Available</th></tr>';
        return;
    }
    
    const headers = Object.keys(previewRows[0]);
    const headerRow = document.createElement('tr');
    headers.forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    
    previewRows.forEach(row => {
        const tr = document.createElement('tr');
        headers.forEach(h => {
            const td = document.createElement('td');
            td.textContent = row[h];
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function renderCharts(chartsData) {
    const grid = els.dashboardChartsGrid;
    grid.innerHTML = '';
    
    if (!chartsData || chartsData.length === 0) {
        grid.innerHTML = `
            <div class="glass-card chart-card" style="grid-column: 1 / -1; height: 180px; align-items: center; justify-content: center;">
                <p class="text-muted"><i class="fa-solid fa-chart-bar" style="font-size: 2rem; margin-bottom: 0.5rem;"></i><br>No charts generated. AI visualization recommendations are empty.</p>
            </div>
        `;
        return;
    }
    
    chartsData.forEach((chart, index) => {
        const card = document.createElement('div');
        card.className = 'glass-card chart-card';
        
        const canvasId = `chart-canvas-${index}`;
        card.innerHTML = `
            <div class="chart-header">
                <h4>${chart.title}</h4>
                <p title="${chart.description}">${chart.description}</p>
            </div>
            <div class="chart-wrapper">
                <canvas id="${canvasId}"></canvas>
            </div>
        `;
        grid.appendChild(card);
        
        try {
            const ctx = document.getElementById(canvasId).getContext('2d');
            let config = {};
            
            if (chart.chart_type === 'scatter') {
                config = {
                    type: 'scatter',
                    data: {
                        datasets: [{
                            label: `${chart.y_axis} vs ${chart.x_axis}`,
                            data: chart.points,
                            backgroundColor: chartColors.primary,
                            borderColor: chartColors.primary,
                            pointRadius: 5
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8' } },
                            y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8' } }
                        }
                    }
                };
            } else if (chart.chart_type === 'pie') {
                config = {
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
                            legend: {
                                position: 'right',
                                labels: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans', size: 9 } }
                            }
                        }
                    }
                };
            } else {
                const isLine = chart.chart_type === 'line';
                config = {
                    type: isLine ? 'line' : 'bar',
                    data: {
                        labels: chart.labels,
                        datasets: [{
                            label: chart.y_axis || 'Frequency',
                            data: chart.values,
                            backgroundColor: isLine ? chartColors.primaryAlpha : chartColors.palette[index % chartColors.palette.length],
                            borderColor: chartColors.primary,
                            borderWidth: 2,
                            fill: isLine,
                            tension: 0.35
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 8 } } },
                            y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8' } }
                        }
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
                api_key: appState.apiKey
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
                            // Apply schema updates to local state (no re-fetch needed)
                            if (parsed.column_actions) {
                                appState.sessionData.column_actions = parsed.column_actions;
                            }
                            if (parsed.schema_updates && Object.keys(parsed.schema_updates).length > 0) {
                                renderSchemaActionsGrid();
                                if (els.processDataBtn) {
                                    els.processDataBtn.disabled = false;
                                }
                            }
                            // Do not auto-trigger processing from chat updates.
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

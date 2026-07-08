const DEFAULT_VORTEX_BASE = 'http://127.0.0.1:8080';
let VORTEX_BASE = DEFAULT_VORTEX_BASE;
let pollInterval = null;

document.addEventListener('DOMContentLoaded', () => {
    const btnOpenVortex    = document.getElementById('btn-open-vortex');
    const statusDiv        = document.getElementById('status');
    const currentUrlDiv    = document.getElementById('current-url');
    const monitorPanel     = document.getElementById('download-monitor');
    const monitorFileLabel = document.getElementById('monitor-file-label');
    const monitorBadge     = document.getElementById('monitor-status-badge');
    const monitorFill      = document.getElementById('monitor-progress-fill');
    const monitorFilesCount= document.getElementById('monitor-files-count');
    const monitorSpeed     = document.getElementById('monitor-speed');
    const btnOpenApp       = document.getElementById('btn-open-app');
    const btnSettings      = document.getElementById('btn-settings');
    const settingsPanel    = document.getElementById('settings-panel');
    const serverUrlInput   = document.getElementById('server-url');
    const btnSaveSettings  = document.getElementById('btn-save-settings');
    const btnResetSettings = document.getElementById('btn-reset-settings');
    let activeUrl = '';

    // Load saved server URL from chrome.storage
    function loadSettings() {
        if (chrome.storage && chrome.storage.local) {
            chrome.storage.local.get(['vortex_server_url'], (result) => {
                if (result.vortex_server_url) {
                    VORTEX_BASE = result.vortex_server_url;
                    serverUrlInput.value = result.vortex_server_url;
                }
            });
        }
    }

    loadSettings();

    // Settings toggle
    btnSettings.addEventListener('click', () => {
        settingsPanel.classList.toggle('visible');
    });

    // Save settings
    btnSaveSettings.addEventListener('click', () => {
        const url = serverUrlInput.value.trim();
        if (url) {
            VORTEX_BASE = url;
        } else {
            VORTEX_BASE = DEFAULT_VORTEX_BASE;
        }
        if (chrome.storage && chrome.storage.local) {
            chrome.storage.local.set({ vortex_server_url: VORTEX_BASE });
        }
        settingsPanel.classList.remove('visible');
    });

    // Reset settings
    btnResetSettings.addEventListener('click', () => {
        VORTEX_BASE = DEFAULT_VORTEX_BASE;
        serverUrlInput.value = '';
        if (chrome.storage && chrome.storage.local) {
            chrome.storage.local.remove('vortex_server_url');
        }
        settingsPanel.classList.remove('visible');
    });

    // Detect current tab URL
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs && tabs[0]) {
            activeUrl = tabs[0].url;
            if (activeUrl && activeUrl.startsWith('http')) {
                currentUrlDiv.textContent = activeUrl.length > 55
                    ? activeUrl.substring(0, 55) + '...'
                    : activeUrl;
            } else {
                currentUrlDiv.textContent = 'Aba inválida para extração';
                btnOpenVortex.disabled = true;
            }
        }
    });

    // Send to Vortex button
    btnOpenVortex.addEventListener('click', () => {
        if (activeUrl) {
            chrome.tabs.create({ url: `${VORTEX_BASE}/?url=${encodeURIComponent(activeUrl)}&auto=1` });
            window.close();
        }
    });

    // Open Vortex app button
    if (btnOpenApp) {
        btnOpenApp.addEventListener('click', () => {
            chrome.tabs.create({ url: VORTEX_BASE });
        });
    }

    // Poll download status from Vortex server
    function formatSpeed(bytesPerSec) {
        if (!bytesPerSec || bytesPerSec <= 0) return '';
        if (bytesPerSec >= 1024 * 1024) return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`;
        return `${Math.round(bytesPerSec / 1024)} KB/s`;
    }

    function updateMonitor(data) {
        const status = data.status || 'idle';
        const total  = data.total_files  || 0;
        const done   = data.downloaded_files || 0;
        const active = data.active_downloads || {};

        monitorPanel.classList.add('visible');

        const badgeMap = {
            'downloading': { cls: 'badge-downloading', label: 'BAIXANDO' },
            'completed':   { cls: 'badge-completed',   label: 'CONCLUÍDO' },
            'error':       { cls: 'badge-error',        label: 'ERRO' },
            'idle':        { cls: 'badge-idle',         label: 'OCIOSO' },
        };
        const badge = badgeMap[status] || badgeMap['idle'];
        monitorBadge.className = `monitor-status-badge ${badge.cls}`;
        monitorBadge.textContent = badge.label;

        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        monitorFill.style.width = `${pct}%`;
        monitorFill.className = `monitor-progress-fill${status === 'completed' ? ' done' : ''}`;

        const activeFiles = Object.entries(active);
        if (activeFiles.length > 0) {
            const [filename, info] = activeFiles[0];
            monitorFileLabel.textContent = filename;
            const filePct = info.percent !== undefined ? info.percent : (info.progress || 0);
            monitorFill.style.width = `${filePct}%`;

            let speedStr = '';
            if (typeof info.speed === 'string') {
                speedStr = info.speed;
            } else if (info.speed_bytes !== undefined) {
                speedStr = formatSpeed(info.speed_bytes);
            } else {
                speedStr = formatSpeed(info.speed);
            }
            monitorSpeed.textContent = speedStr;
        } else if (status === 'completed') {
            monitorFileLabel.textContent = 'Download finalizado!';
            monitorSpeed.textContent = '';
        } else {
            monitorFileLabel.textContent = '—';
            monitorSpeed.textContent = '';
        }

        monitorFilesCount.textContent = total > 0 ? `${done} / ${total} arquivos` : '—';
    }

    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');

    function setConnectionStatus(connected) {
        if (connected) {
            statusDot.style.background = '#10b981';
            statusText.textContent = 'Conectado';
            statusText.style.color = '#64748b';
        } else {
            statusDot.style.background = '#ef4444';
            statusText.textContent = 'Servidor inacessível';
            statusText.style.color = '#ef4444';
        }
    }

    function pollStatus() {
        fetch(`${VORTEX_BASE}/api/status`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(r => r.json())
        .then(data => {
            setConnectionStatus(true);
            updateMonitor(data);
        })
        .catch(() => {
            setConnectionStatus(false);
            monitorPanel.classList.remove('visible');
        });
    }

    pollStatus();
    pollInterval = setInterval(pollStatus, 1500);
});

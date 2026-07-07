const VORTEX_BASE = 'http://127.0.0.1:8080';
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
    let activeUrl = '';

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

        // Status badge
        const badgeMap = {
            'downloading': { cls: 'badge-downloading', label: 'BAIXANDO' },
            'completed':   { cls: 'badge-completed',   label: 'CONCLUÍDO' },
            'error':       { cls: 'badge-error',        label: 'ERRO' },
            'idle':        { cls: 'badge-idle',         label: 'OCIOSO' },
        };
        const badge = badgeMap[status] || badgeMap['idle'];
        monitorBadge.className = `monitor-status-badge ${badge.cls}`;
        monitorBadge.textContent = badge.label;

        // Overall progress
        const pct = total > 0 ? Math.round((done / total) * 100) : 0;
        monitorFill.style.width = `${pct}%`;
        monitorFill.className = `monitor-progress-fill${status === 'completed' ? ' done' : ''}`;

        // File label: show first active file being downloaded
        const activeFiles = Object.entries(active);
        if (activeFiles.length > 0) {
            const [filename, info] = activeFiles[0];
            monitorFileLabel.textContent = filename;
            const filePct = info.percent || 0;
            monitorFill.style.width = `${filePct}%`;

            // Speed from first active file
            const speedStr = formatSpeed(info.speed);
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

    function pollStatus() {
        fetch(`${VORTEX_BASE}/api/status`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(r => r.json())
        .then(data => {
            updateMonitor(data);
            // Stop polling if idle or completed
            if (data.status === 'idle' && monitorPanel.classList.contains('visible')) {
                // Keep showing panel for 5s after idle
            }
        })
        .catch(() => {
            // Server unreachable - hide monitor
            monitorPanel.classList.remove('visible');
        });
    }

    // Start polling immediately and every 1.5 seconds
    pollStatus();
    pollInterval = setInterval(pollStatus, 1500);
});


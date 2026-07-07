// AeroDownload - Universal Downloader frontend logic

document.addEventListener('DOMContentLoaded', () => {
    function addTokenToUrl(url) {
        if (!url || !window.VORTEX_TOKEN) return url;
        if (url.startsWith('/api/') || url.startsWith(window.location.origin + '/api/') || url.includes('/api/')) {
            const separator = url.includes('?') ? '&' : '?';
            return `${url}${separator}token=${encodeURIComponent(window.VORTEX_TOKEN)}`;
        }
        return url;
    }

    // State variables
    let albumData = null;
    let selectedMediaIds = new Set();
    let activeFilter = 'all';
    let statusIntervalId = null;
    let hlsInstance = null;
    let isClosingPreview = false; // Flag to suppress false error alerts during cleanup
    let currentMediaList = [];
    let currentMediaIndex = -1;
    let currentBaseDir = localStorage.getItem('vortex_base_dir') || '';

    // Helper function to join paths
    function joinPath(base, folder) {
        const separator = base.includes('/') ? '/' : '\\';
        const cleanBase = base.replace(/[/\\]+$/, '');
        const cleanFolder = folder.replace(/^[/\\]+/, '').replace(/[/\\]+$/, '');
        return cleanBase + separator + cleanFolder;
    }

    // Helper function to sanitize title matching backend's sanitize_filename
    function sanitizeFilename(name) {
        let sanitized = name.replace(/[\\/*?:"<>|]/g, "");
        sanitized = sanitized.replace(/[^\x00-\x7F]+/g, "");
        return sanitized.trim().substring(0, 100);
    }

    // Function to calculate and update path UI based on current choices
    function updateDownloadPathUI() {
        if (!albumData) return;
        
        let base = currentBaseDir || albumData.base_dir || '';
        const chkSubfolder = document.getElementById('chk-subfolder');
        const createSubfolder = chkSubfolder ? chkSubfolder.checked : false;
        
        if (createSubfolder) {
            const folderName = sanitizeFilename(albumData.title) || "VortexMedia";
            downloadPathInput.value = joinPath(base, folderName);
        } else {
            downloadPathInput.value = base;
        }
    }

    async function playLocalFile(item) {
        const path = downloadPathInput.value.trim();
        const filepath = joinPath(path, item.filename);
        
        try {
            const response = await fetch('/api/open-file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filepath: filepath })
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || "Não foi possível abrir o arquivo.");
            }
            showToast("Arquivo aberto com sucesso!", "success");
        } catch (err) {
            showToast(err.message, "error");
        }
    }

    async function convertToMp3(item) {
        const path = downloadPathInput.value.trim();
        const filepath = joinPath(path, item.filename);
        
        showToast("Iniciando conversão para MP3...", "info");
        
        // Find card overlay for visual feedback
        const card = document.querySelector(`[data-filename="${item.filename}"]`);
        let overlay = null;
        if (card) {
            overlay = card.querySelector('.card-progress-overlay');
            if (!overlay) {
                overlay = document.createElement('div');
                overlay.className = 'card-progress-overlay';
                overlay.style.background = 'rgba(15, 23, 42, 0.9)';
                overlay.innerHTML = `
                    <i class="fa-solid fa-file-audio card-progress-spinner" style="animation: fa-spin 2s linear infinite; font-size: 1.5rem; margin-bottom: 8px;"></i>
                    <div class="card-progress-text" style="font-size: 0.75rem;">Convertendo...</div>
                    <div class="card-progress-speed" style="font-size: 0.65rem; opacity: 0.8;">Aguarde</div>
                `;
                card.appendChild(overlay);
            }
        }
        
        try {
            const response = await fetch('/api/convert-to-mp3', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filepath: filepath })
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || "Não foi possível converter o arquivo.");
            }
            
            const convertInterval = setInterval(async () => {
                try {
                    const res = await fetch('/api/convert-status');
                    const cData = await res.json();
                    
                    if (cData.status === 'completed') {
                        clearInterval(convertInterval);
                        showToast("Conversão para MP3 concluída!", "success");
                        if (overlay) {
                            overlay.innerHTML = `
                                <i class="fa-solid fa-circle-check" style="color: var(--success); font-size: 1.5rem; margin-bottom: 4px;"></i>
                                <div class="card-progress-text" style="color: var(--success); font-size: 0.72rem;">Concluído!</div>
                            `;
                            setTimeout(() => { overlay.remove(); }, 2000);
                        }
                        analyzeUrl();
                    } else if (cData.status === 'error') {
                        clearInterval(convertInterval);
                        showToast(`Erro na conversão: ${cData.error}`, "error");
                        if (overlay) {
                            overlay.innerHTML = `
                                <i class="fa-solid fa-circle-xmark" style="color: var(--error); font-size: 1.5rem; margin-bottom: 4px;"></i>
                                <div class="card-progress-text" style="color: var(--error); font-size: 0.72rem;">Falhou</div>
                            `;
                            setTimeout(() => { overlay.remove(); }, 3000);
                        }
                    }
                } catch (e) {
                    console.error("Erro no status da conversão:", e);
                }
            }, 1000);
            
        } catch (err) {
            showToast(err.message, "error");
            if (overlay) overlay.remove();
        }
    }

    let localIpAddress = "127.0.0.1";
    
    async function fetchLocalIp() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            if (data.local_ip) {
                localIpAddress = data.local_ip;
            }
        } catch (err) {
            console.error("Erro ao obter IP local:", err);
        }
    }
    fetchLocalIp();

    const shareModal = document.getElementById('share-modal');
    const qrCodeImg = document.getElementById('qr-code-img');
    const shareUrlText = document.getElementById('share-url-text');
    const btnCloseShare = document.getElementById('btn-close-share');

    if (btnCloseShare) {
        btnCloseShare.addEventListener('click', () => {
            shareModal.classList.add('hidden');
        });
    }
    if (shareModal) {
        shareModal.addEventListener('click', (e) => {
            if (e.target === shareModal) {
                shareModal.classList.add('hidden');
            }
        });
    }

    function openShareModal(item) {
        if (!shareModal || !qrCodeImg || !shareUrlText) return;
        
        const path = downloadPathInput.value.trim();
        const filepath = joinPath(path, item.filename);
        
        const fileUrl = addTokenToUrl(`http://${localIpAddress}:8080/api/serve-file?path=${encodeURIComponent(filepath)}`);
        const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(fileUrl)}`;
        
        qrCodeImg.src = qrUrl;
        shareUrlText.textContent = fileUrl;
        shareModal.classList.remove('hidden');
    }

    async function checkFFmpegStatus() {
        try {
            const response = await fetch('/api/ffmpeg/status');
            const data = await response.json();
            const dot = document.getElementById('ffmpeg-status-dot');
            const text = document.getElementById('ffmpeg-status-text');
            const btnInstall = document.getElementById('btn-install-ffmpeg');
            
            if (!dot || !text || !btnInstall) return;
            
            if (data.installed) {
                dot.style.background = '#10B981';
                text.textContent = 'FFmpeg ativo e pronto para uso.';
                text.style.color = '#10B981';
                btnInstall.style.display = 'none';
            } else {
                dot.style.background = '#F59E0B';
                text.textContent = 'FFmpeg não instalado localmente.';
                text.style.color = '#F59E0B';
                btnInstall.style.display = 'block';
            }
        } catch (err) {
            console.error("Erro ao checar FFmpeg:", err);
        }
    }

    function updateCardActions(card, item) {
        const actionsWrapper = card.querySelector('.card-actions-wrapper');
        if (!actionsWrapper) return;
        
        actionsWrapper.innerHTML = '';
        
        if (item.type === 'video' || item.type === 'image') {
            const previewBtn = document.createElement('button');
            previewBtn.className = 'card-action-btn preview';
            if (item.type === 'video') {
                previewBtn.title = 'Visualizar Prévia do Vídeo';
                previewBtn.innerHTML = '<i class="fa-solid fa-eye"></i>';
                previewBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openVideoPreview(item.url, item.filename);
                });
            } else {
                previewBtn.title = 'Visualizar Imagem Ampliada';
                previewBtn.innerHTML = '<i class="fa-solid fa-expand"></i>';
                previewBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openImagePreview(item.url, item.filename);
                });
            }
            actionsWrapper.appendChild(previewBtn);
        }
        
        if (item.exists_locally) {
            const playBtn = document.createElement('button');
            playBtn.className = 'card-action-btn play-local';
            playBtn.title = 'Reproduzir no Computador (Player Padrão)';
            playBtn.innerHTML = '<i class="fa-solid fa-play"></i>';
            playBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                playLocalFile(item);
            });
            actionsWrapper.appendChild(playBtn);
            
            if (item.type === 'video' || item.type === 'audio') {
                const convertBtn = document.createElement('button');
                convertBtn.className = 'card-action-btn convert';
                convertBtn.title = 'Converter para MP3';
                convertBtn.innerHTML = '<i class="fa-solid fa-file-audio"></i>';
                convertBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    convertToMp3(item);
                });
                actionsWrapper.appendChild(convertBtn);
            }
            
            const shareBtn = document.createElement('button');
            shareBtn.className = 'card-action-btn share';
            shareBtn.title = 'Compartilhar por QR Code';
            shareBtn.innerHTML = '<i class="fa-solid fa-qrcode"></i>';
            shareBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                openShareModal(item);
            });
            actionsWrapper.appendChild(shareBtn);
        } else {
            const downloadBtn = document.createElement('button');
            downloadBtn.className = 'card-action-btn download';
            downloadBtn.title = 'Baixar no computador (Salvar no PC)';
            downloadBtn.innerHTML = '<i class="fa-solid fa-desktop"></i>';
            downloadBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                downloadSingleItem(item);
            });
            actionsWrapper.appendChild(downloadBtn);
            
            const deviceDownloadBtn = document.createElement('button');
            deviceDownloadBtn.className = 'card-action-btn download-device';
            deviceDownloadBtn.title = 'Baixar direto neste aparelho (celular/PC)';
            deviceDownloadBtn.innerHTML = '<i class="fa-solid fa-mobile-screen-button"></i>';
            deviceDownloadBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                downloadToDevice(item);
            });
            actionsWrapper.appendChild(deviceDownloadBtn);
        }
    }

    // DOM Elements
    const albumUrlInput = document.getElementById('album-url');
    const btnAnalyze = document.getElementById('btn-analyze');
    const errorMessage = document.getElementById('error-message');
    const errorText = errorMessage.querySelector('.error-text');
    
    const mediaDashboard = document.getElementById('media-dashboard');
    const albumTitle = document.getElementById('album-title');
    const albumCount = document.getElementById('album-count');
    
    const filterBtns = document.querySelectorAll('.filter-btn');
    const btnSelectAll = document.getElementById('btn-select-all');
    const btnDeselectAll = document.getElementById('btn-deselect-all');
    
    const downloadPathInput = document.getElementById('download-path');
    const btnBrowse = document.getElementById('btn-browse');
    const selectedCounter = document.getElementById('selected-counter');
    const btnDownloadStart = document.getElementById('btn-download-start');
    const mediaGrid = document.getElementById('media-grid');
    
    const progressPanel = document.getElementById('progress-panel');
    const progressFileCount = document.getElementById('progress-file-count');
    const overallProgressBar = document.getElementById('overall-progress-bar');
    const overallPercentage = document.getElementById('overall-percentage');
    const activeFilesList = document.getElementById('active-files-list');
    const progressPath = document.getElementById('progress-path');
    const btnCancel = document.getElementById('btn-cancel');
    
    const completionModal = document.getElementById('completion-modal');
    const modalFolderPath = document.getElementById('modal-folder-path');
    const btnCloseModal = document.getElementById('btn-close-modal');

    // Video Preview Modal Elements
    const previewModal = document.getElementById('preview-modal');
    const previewTitle = document.getElementById('preview-title');
    const previewVideoPlayer = document.getElementById('preview-video-player');
    const btnClosePreview = document.getElementById('btn-close-preview');

    // Theme Switcher & Image Lightbox Elements
    const themeToggle = document.getElementById('theme-toggle');
    const imagePreviewModal = document.getElementById('image-preview-modal');
    const previewImageElement = document.getElementById('preview-image-element');
    const imagePreviewTitle = document.getElementById('image-preview-title');
    const btnCloseImagePreview = document.getElementById('btn-close-image-preview');
    const btnZoomImage = document.getElementById('btn-zoom-image');
    const btnSelectImage = document.getElementById('btn-select-image');
    const previewImageContainer = document.getElementById('preview-image-container');
    let isImageZoomed = false;
    let imageZoomScale = 1;
    let imagePanX = 0;
    let imagePanY = 0;
    let imageDragStartX = 0;
    let imageDragStartY = 0;
    let imageDragStartPanX = 0;
    let imageDragStartPanY = 0;
    let isImageDragging = false;
    const IMAGE_ZOOM_LEVELS = [1, 1.5, 2, 3, 4];

    // Vortex 4.0 Advanced UI Elements
    const btnUpdateYtdl = document.getElementById('btn-update-ytdl');
    const historyContainer = document.getElementById('history-container');
    const historyList = document.getElementById('history-list');
    const btnClearHistory = document.getElementById('btn-clear-history');
    let inlineDownloads = new Set(); // Track active inline downloads

    // Cookies Elements
    const cookiesPathInput = document.getElementById('cookies-path');
    const btnBrowseCookies = document.getElementById('btn-browse-cookies');
    const btnClearCookies = document.getElementById('btn-clear-cookies');
    const cookiesFileInput = document.getElementById('cookies-file-input');

    // Load saved cookies file path on startup
    if (cookiesPathInput) {
        cookiesPathInput.value = localStorage.getItem('vortex_cookies_path') || '';
    }

    // Subfolder checkbox configuration
    const chkSubfolder = document.getElementById('chk-subfolder');
    if (chkSubfolder) {
        chkSubfolder.checked = (localStorage.getItem('vortex_create_subfolder') === 'true');
        chkSubfolder.addEventListener('change', () => {
            localStorage.setItem('vortex_create_subfolder', chkSubfolder.checked);
            updateDownloadPathUI();
        });
    }

    // FFmpeg Auto-updater & Installer Setup
    const btnInstallFfmpeg = document.getElementById('btn-install-ffmpeg');
    const ffmpegProgressContainer = document.getElementById('ffmpeg-progress-container');
    const ffmpegProgressBar = document.getElementById('ffmpeg-progress-bar');
    const ffmpegProgressPercentage = document.getElementById('ffmpeg-progress-percentage');
    const ffmpegProgressLabel = document.getElementById('ffmpeg-progress-label');
    let ffmpegInstallIntervalId = null;
    
    if (btnInstallFfmpeg) {
        btnInstallFfmpeg.addEventListener('click', async () => {
            btnInstallFfmpeg.disabled = true;
            ffmpegProgressContainer.classList.remove('hidden');
            
            try {
                const response = await fetch('/api/ffmpeg/install', { method: 'POST' });
                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.error || "Erro ao iniciar instalação.");
                }
                
                ffmpegInstallIntervalId = setInterval(async () => {
                    try {
                        const res = await fetch('/api/ffmpeg/install-status');
                        const data = await res.json();
                        
                        if (data.status === 'downloading') {
                            ffmpegProgressLabel.textContent = 'Baixando FFmpeg essentials (aprox. 80MB)...';
                            ffmpegProgressBar.style.width = `${data.progress}%`;
                            ffmpegProgressPercentage.textContent = `${data.progress}%`;
                        } else if (data.status === 'extracting') {
                            ffmpegProgressLabel.textContent = 'Descompactando binários na pasta local...';
                            ffmpegProgressBar.style.width = '95%';
                            ffmpegProgressPercentage.textContent = '95%';
                        } else if (data.status === 'completed') {
                            clearInterval(ffmpegInstallIntervalId);
                            ffmpegProgressLabel.textContent = 'Instalação concluída com sucesso!';
                            ffmpegProgressBar.style.width = '100%';
                            ffmpegProgressPercentage.textContent = '100%';
                            showToast("FFmpeg instalado localmente com sucesso!", "success");
                            checkFFmpegStatus();
                            setTimeout(() => { ffmpegProgressContainer.classList.add('hidden'); }, 3000);
                        } else if (data.status === 'error') {
                            clearInterval(ffmpegInstallIntervalId);
                            ffmpegProgressLabel.textContent = `Erro: ${data.error}`;
                            ffmpegProgressBar.style.background = '#EF4444';
                            showToast(`Falha ao instalar FFmpeg: ${data.error}`, "error");
                            btnInstallFfmpeg.disabled = false;
                        }
                    } catch (err) {
                        console.error("Erro ao verificar instalação do FFmpeg:", err);
                    }
                }, 1000);
            } catch (err) {
                showToast(err.message, "error");
                btnInstallFfmpeg.disabled = false;
            }
        });
    }

    // Browse/Upload Cookies Trigger
    if (btnBrowseCookies && cookiesFileInput) {
        btnBrowseCookies.addEventListener('click', () => {
            cookiesFileInput.click();
        });

        cookiesFileInput.addEventListener('change', async () => {
            const file = cookiesFileInput.files[0];
            if (!file) return;

            btnBrowseCookies.disabled = true;
            const originalText = btnBrowseCookies.innerHTML;
            btnBrowseCookies.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await fetch('/api/upload-cookies', {
                    method: 'POST',
                    body: formData
                });
                const data = await response.json();
                if (response.ok && data.filepath) {
                    cookiesPathInput.value = data.filepath;
                    localStorage.setItem('vortex_cookies_path', data.filepath);
                    showToast("Arquivo cookies.txt importado com sucesso!", "success");
                } else {
                    showToast(`Erro ao importar cookies: ${data.error || "Ocorreu um erro desconhecido."}`, "error");
                }
            } catch (err) {
                console.error("Erro ao fazer upload de cookies:", err);
                showToast(`Erro na rede ao carregar cookies: ${err.message}`, "error");
            } finally {
                btnBrowseCookies.disabled = false;
                btnBrowseCookies.innerHTML = originalText;
                cookiesFileInput.value = ''; // Reset input to allow selecting the same file again
            }
        });
    }

    // Clear Cookies Event
    if (btnClearCookies) {
        btnClearCookies.addEventListener('click', () => {
            if (cookiesPathInput) {
                cookiesPathInput.value = '';
            }
            localStorage.removeItem('vortex_cookies_path');
        });
    }

    // Theme Setup & Event Listeners
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light') {
        document.body.classList.add('light-theme');
        themeToggle.innerHTML = '<i class="fa-solid fa-sun"></i>';
    } else {
        themeToggle.innerHTML = '<i class="fa-solid fa-moon"></i>';
    }

    themeToggle.addEventListener('click', () => {
        document.body.classList.toggle('light-theme');
        const isLight = document.body.classList.contains('light-theme');
        localStorage.setItem('theme', isLight ? 'light' : 'dark');
        themeToggle.innerHTML = isLight ? '<i class="fa-solid fa-sun"></i>' : '<i class="fa-solid fa-moon"></i>';
    });

    // yt-dlp Auto-updater Trigger
    if (btnUpdateYtdl) {
        btnUpdateYtdl.addEventListener('click', async () => {
            btnUpdateYtdl.disabled = true;
            btnUpdateYtdl.classList.add('updating');
            
            try {
                const response = await fetch('/api/update-ytdl', {
                    method: 'POST'
                });
                const data = await response.json();
                if (response.ok && data.success) {
                    showToast(data.message || "Motor de download (yt-dlp) atualizado com sucesso!", "success");
                } else {
                    showToast(`Erro ao atualizar: ${data.error || "Ocorreu um erro desconhecido."}`, "error");
                }
            } catch (err) {
                console.error("Erro ao atualizar yt-dlp:", err);
                showToast(`Erro na rede: ${err.message}`, "error");
            } finally {
                btnUpdateYtdl.disabled = false;
                btnUpdateYtdl.classList.remove('updating');
            }
        });
    }

    function applyImageTransform() {
        if (!previewImageElement) return;
        previewImageElement.style.transform = `translate(${imagePanX}px, ${imagePanY}px) scale(${imageZoomScale})`;
        previewImageElement.style.cursor = imageZoomScale > 1 ? 'grab' : 'zoom-in';
        previewImageContainer.style.cursor = imageZoomScale > 1 ? 'grab' : 'default';
    }

    function cycleImageZoom(clickX, clickY) {
        if (!previewImageElement || !previewImageContainer) return;

        const currentIdx = IMAGE_ZOOM_LEVELS.indexOf(imageZoomScale);
        let nextIdx;

        if (currentIdx === -1 || currentIdx >= IMAGE_ZOOM_LEVELS.length - 1) {
            // Already at max or unknown: reset to 1x
            nextIdx = 0;
        } else {
            nextIdx = currentIdx + 1;
        }

        const newScale = IMAGE_ZOOM_LEVELS[nextIdx];

        if (newScale === 1) {
            // Reset
            imageZoomScale = 1;
            imagePanX = 0;
            imagePanY = 0;
            previewImageContainer.style.overflow = 'hidden';
        } else {
            imageZoomScale = newScale;
            // Zoom toward click point if provided, otherwise center
            if (clickX !== undefined && clickY !== undefined) {
                const rect = previewImageElement.getBoundingClientRect();
                const imgCenterX = rect.left + rect.width / 2;
                const imgCenterY = rect.top + rect.height / 2;
                imagePanX = (clickX - imgCenterX) * (1 - newScale) + imagePanX;
                imagePanY = (clickY - imgCenterY) * (1 - newScale) + imagePanY;
            }
            previewImageContainer.style.overflow = 'hidden';
        }

        applyImageTransform();
        updateZoomButton();
    }

    function updateZoomButton() {
        if (!btnZoomImage) return;
        if (imageZoomScale > 1) {
            btnZoomImage.innerHTML = `<i class="fa-solid fa-magnifying-glass-minus"></i> ${imageZoomScale}x`;
        } else {
            btnZoomImage.innerHTML = '<i class="fa-solid fa-magnifying-glass-plus"></i> Zoom';
        }
    }

    function resetImageZoom() {
        imageZoomScale = 1;
        imagePanX = 0;
        imagePanY = 0;
        if (previewImageContainer) previewImageContainer.style.overflow = 'hidden';
        applyImageTransform();
        updateZoomButton();
    }

    function updateSelectButton() {
        if (!btnSelectImage) return;
        const item = currentMediaList[currentMediaIndex];
        if (!item) return;
        const isSelected = selectedMediaIds.has(item.id);
        if (isSelected) {
            btnSelectImage.innerHTML = '<i class="fa-solid fa-check-double"></i> Selecionado';
            btnSelectImage.style.background = 'var(--primary)';
            btnSelectImage.style.color = '#fff';
        } else {
            btnSelectImage.innerHTML = '<i class="fa-solid fa-check"></i> Selecionar';
            btnSelectImage.style.background = '';
            btnSelectImage.style.color = '';
        }
    }

    function toggleSelectCurrentImage() {
        const item = currentMediaList[currentMediaIndex];
        if (!item) return;
        if (selectedMediaIds.has(item.id)) {
            selectedMediaIds.delete(item.id);
        } else {
            selectedMediaIds.add(item.id);
        }
        updateSelectButton();
        updateSelectedUI();
        // Also update the card's visual state in the grid
        const card = document.querySelector(`.media-card[data-id="${item.id}"]`);
        if (card) {
            card.classList.toggle('selected', selectedMediaIds.has(item.id));
        }
    }

    // Image drag-to-pan handlers
    if (previewImageContainer) {
        previewImageContainer.addEventListener('mousedown', (e) => {
            if (imageZoomScale <= 1) return;
            e.preventDefault();
            isImageDragging = true;
            imageDragStartX = e.clientX;
            imageDragStartY = e.clientY;
            imageDragStartPanX = imagePanX;
            imageDragStartPanY = imagePanY;
            previewImageContainer.style.cursor = 'grabbing';
        });

        window.addEventListener('mousemove', (e) => {
            if (!isImageDragging) return;
            imagePanX = imageDragStartPanX + (e.clientX - imageDragStartX);
            imagePanY = imageDragStartPanY + (e.clientY - imageDragStartY);
            applyImageTransform();
        });

        window.addEventListener('mouseup', () => {
            if (isImageDragging) {
                isImageDragging = false;
                if (previewImageContainer) {
                    previewImageContainer.style.cursor = imageZoomScale > 1 ? 'grab' : 'default';
                }
            }
        });

        // Touch support for mobile pan
        previewImageContainer.addEventListener('touchstart', (e) => {
            if (imageZoomScale <= 1) return;
            if (e.touches.length !== 1) return;
            isImageDragging = true;
            imageDragStartX = e.touches[0].clientX;
            imageDragStartY = e.touches[0].clientY;
            imageDragStartPanX = imagePanX;
            imageDragStartPanY = imagePanY;
        }, { passive: true });

        previewImageContainer.addEventListener('touchmove', (e) => {
            if (!isImageDragging || e.touches.length !== 1) return;
            imagePanX = imageDragStartPanX + (e.touches[0].clientX - imageDragStartX);
            imagePanY = imageDragStartPanY + (e.touches[0].clientY - imageDragStartY);
            applyImageTransform();
        }, { passive: true });

        previewImageContainer.addEventListener('touchend', () => {
            isImageDragging = false;
        });
    }

    // Image Lightbox Event Listeners
    if (btnCloseImagePreview) {
        btnCloseImagePreview.addEventListener('click', closeImagePreview);
    }
    if (btnZoomImage) {
        btnZoomImage.addEventListener('click', (e) => {
            e.stopPropagation();
            cycleImageZoom();
        });
    }
    if (btnSelectImage) {
        btnSelectImage.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleSelectCurrentImage();
        });
    }
    if (previewImageElement) {
        previewImageElement.addEventListener('click', (e) => {
            e.stopPropagation();
            if (imageZoomScale > 1) {
                // If zoomed and not dragging, reset zoom
                if (!isImageDragging) {
                    cycleImageZoom();
                }
            } else {
                cycleImageZoom(e.clientX, e.clientY);
            }
        });
    }
    if (imagePreviewModal) {
        imagePreviewModal.addEventListener('click', (e) => {
            if (e.target === imagePreviewModal) {
                closeImagePreview();
            }
        });
    }

    function openImagePreview(url, filename) {
        currentMediaIndex = currentMediaList.findIndex(item => item.filename === filename);
        resetImageZoom();
        if (previewImageElement) {
            previewImageElement.src = '';
            previewImageElement.src = addTokenToUrl(url);
        }
        if (imagePreviewTitle) {
            imagePreviewTitle.textContent = filename;
        }
        updateSelectButton();
        if (imagePreviewModal) {
            imagePreviewModal.classList.remove('hidden');
        }
    }

    function closeImagePreview() {
        if (imagePreviewModal) {
            imagePreviewModal.classList.add('hidden');
        }
        if (previewImageElement) {
            previewImageElement.src = '';
        }
        resetImageZoom();
    }

    // --- Link History Helpers ---
    function loadHistory() {
        const history = JSON.parse(localStorage.getItem('vortex_history') || '[]');
        renderHistory(history);
    }

    function renderHistory(history) {
        if (!historyList || !historyContainer) return;
        
        if (history.length === 0) {
            historyContainer.classList.add('hidden');
            return;
        }
        
        historyContainer.classList.remove('hidden');
        historyList.innerHTML = '';
        
        history.forEach(item => {
            const div = document.createElement('div');
            div.className = 'history-item';
            div.innerHTML = `
                <div class="history-item-title"><i class="fa-solid fa-link"></i> ${item.title}</div>
                <div class="history-item-url" title="${item.url}">${item.url}</div>
            `;
            
            div.addEventListener('click', () => {
                albumUrlInput.value = item.url;
                analyzeUrl();
            });
            
            historyList.appendChild(div);
        });
    }

    function addHistoryItem(url, title) {
        let history = JSON.parse(localStorage.getItem('vortex_history') || '[]');
        
        // Remove duplicate
        history = history.filter(item => item.url !== url);
        
        // Add to front
        history.unshift({ url, title });
        
        // Limit to 5
        history = history.slice(0, 5);
        
        localStorage.setItem('vortex_history', JSON.stringify(history));
        renderHistory(history);
    }

    if (btnClearHistory) {
        btnClearHistory.addEventListener('click', (e) => {
            e.stopPropagation();
            localStorage.removeItem('vortex_history');
            renderHistory([]);
        });
    }

    // Load history on initialization
    loadHistory();

    // Check FFmpeg status on startup
    checkFFmpegStatus();

    // Handle bookmarklet query parameter if present
    const urlParams = new URLSearchParams(window.location.search);
    const urlParam = urlParams.get('url');
    if (urlParam) {
        albumUrlInput.value = urlParam;
        analyzeUrl();
        // Remove query string from URL so refresh doesn't trigger again
        window.history.replaceState({}, document.title, window.location.pathname);
    }
    
    // Clipboard Monitor
    let lastClipboardUrl = "";
    window.addEventListener('focus', async () => {
        try {
            if (!navigator.clipboard || !navigator.clipboard.readText) return;
            const text = await navigator.clipboard.readText();
            const url = text.trim();
            
            if (url.startsWith('http://') || url.startsWith('https://')) {
                const isSupported = ['youtube.com', 'youtu.be', 'x.com', 'twitter.com', 'instagram.com', 'tiktok.com', 'erome.com', 'xvideos.com', 'pornhub.com'].some(domain => url.toLowerCase().includes(domain));
                if (isSupported && url !== lastClipboardUrl && url !== albumUrlInput.value.trim()) {
                    lastClipboardUrl = url;
                    showClipboardToast(url);
                }
            }
        } catch (err) {
            // Ignore clipboard permission errors silently
        }
    });

    function showClipboardToast(url) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        
        const toast = document.createElement('div');
        toast.className = 'toast info';
        toast.style.flexDirection = 'column';
        toast.style.alignItems = 'flex-start';
        toast.style.gap = '8px';
        toast.style.padding = '12px 16px';
        toast.style.maxWidth = '300px';
        
        toast.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <i class="fa-solid fa-clipboard-question" style="color: var(--primary); font-size: 1.1rem;"></i>
                <span style="font-weight: 500; font-size: 0.8rem; color: #fff;">Link na área de transferência!</span>
            </div>
            <div style="font-size: 0.72rem; color: var(--text-muted); word-break: break-all; max-height: 32px; overflow: hidden; text-overflow: ellipsis; width: 100%;">
                ${url}
            </div>
            <button class="btn btn-primary" style="padding: 4px 10px; font-size: 0.72rem; border-radius: 4px; align-self: flex-end; margin-top: 4px;">Analisar Link</button>
        `;
        
        const analyzeBtn = toast.querySelector('button');
        analyzeBtn.addEventListener('click', () => {
            albumUrlInput.value = url;
            analyzeUrl();
            toast.remove();
        });
        
        container.appendChild(toast);
        setTimeout(() => { if (toast.parentNode) toast.remove(); }, 6000);
    }

    // 1. Link Analysis Event
    btnAnalyze.addEventListener('click', analyzeUrl);
    albumUrlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            analyzeUrl();
        }
    });

    // Browse Folder Dialog Event
    btnBrowse.addEventListener('click', async () => {
        btnBrowse.disabled = true;
        const originalText = btnBrowse.innerHTML;
        btnBrowse.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Selecionando...';
        
        try {
            const response = await fetch('/api/browse-folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            if (data.directory) {
                currentBaseDir = data.directory;
                localStorage.setItem('vortex_base_dir', currentBaseDir);
                updateDownloadPathUI();
            }
        } catch (err) {
            console.error("Erro ao selecionar pasta:", err);
        } finally {
            btnBrowse.disabled = false;
            btnBrowse.innerHTML = originalText;
        }
    });
    
    function renderSkeletons() {
        if (!mediaGrid) return;
        mediaGrid.innerHTML = '';
        
        if (mediaDashboard) mediaDashboard.classList.remove('hidden');
        if (progressPanel) progressPanel.classList.add('hidden');
        
        // Set placeholder metadata values during load
        if (albumTitle) albumTitle.textContent = "Analisando página...";
        if (albumCount) albumCount.textContent = "Buscando imagens, vídeos e arquivos...";
        
        for (let i = 0; i < 12; i++) {
            const card = document.createElement('div');
            card.className = 'media-card skeleton-card';
            card.innerHTML = `
                <div class="skeleton-thumbnail skeleton"></div>
                <div class="skeleton-bar skeleton" style="width: 70%; height: 10px; margin: 10px 10px 4px 10px; border-radius: 4px;"></div>
                <div class="skeleton-bar skeleton" style="width: 40%; height: 8px; margin: 0 10px 10px 10px; border-radius: 3px;"></div>
            `;
            mediaGrid.appendChild(card);
        }
        
        if (mediaDashboard) {
            mediaDashboard.classList.remove('hidden');
            mediaDashboard.scrollIntoView({ behavior: 'smooth' });
        }
    }

    async function analyzeHtmlFile(file) {
        hideError();
        btnAnalyze.classList.add('loading');
        btnAnalyze.disabled = true;
        
        // Trigger skeleton loading grid immediately for good Core Web Vitals (CLS reduction)
        renderSkeletons();

        const formData = new FormData();
        formData.append('html_file', file);
        
        // If there's an URL in the input, we can send it as base_url
        const url = albumUrlInput.value.trim();
        if (url) {
            formData.append('url', url);
        }

        try {
            const response = await fetch('/api/analyze-html', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || "Ocorreu um erro ao analisar o arquivo HTML.");
            }

            processAnalyzeResponse(data, url);
        } catch (error) {
            showError(error.message);
        } finally {
            btnAnalyze.classList.remove('loading');
            btnAnalyze.disabled = false;
        }
    }

    // Drag and Drop functionality
    const appContainer = document.querySelector('.app-container');
    
    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
        document.body.addEventListener(eventName, highlightDrop, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        document.body.addEventListener(eventName, unhighlightDrop, false);
    });

    function highlightDrop(e) {
        appContainer.classList.add('drag-highlight');
    }

    function unhighlightDrop(e) {
        appContainer.classList.remove('drag-highlight');
    }

    document.body.addEventListener('drop', handleDrop, false);

    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;

        if (files && files.length > 0) {
            const file = files[0];
            if (file.name.toLowerCase().endsWith('.html') || file.name.toLowerCase().endsWith('.htm')) {
                analyzeHtmlFile(file);
            } else {
                showError("Apenas arquivos .html são suportados para extração local.");
            }
        }
    }

    function processAnalyzeResponse(data, url) {
        // Save state
        albumData = data;
        selectedMediaIds.clear();
        
        // Set input path default value
        updateDownloadPathUI();
        
        // Set metadata values
        albumTitle.textContent = data.title;
        
        const videosCount = data.media.filter(item => item.type === 'video').length;
        const audiosCount = data.media.filter(item => item.type === 'audio').length;
        const imagesCount = data.media.filter(item => item.type === 'image').length;
        const docsCount = data.media.filter(item => item.type === 'document').length;
        
        albumCount.textContent = `${data.media.length} itens encontrados (${videosCount} vídeo(s), ${audiosCount} áudio(s), ${imagesCount} imagem(ns), ${docsCount} arquivo(s))`;

        // Auto-select all by default
        data.media.forEach(item => selectedMediaIds.add(item.id));
        
        // Show dashboard and render grid
        mediaDashboard.classList.remove('hidden');
        progressPanel.classList.add('hidden');
        
        // Reset filters to "All"
        filterBtns.forEach(btn => btn.classList.remove('active'));
        document.querySelector('.filter-btn[data-filter="all"]').classList.add('active');
        activeFilter = 'all';
        
        renderGrid();
        updateSelectedUI();
        if (url) {
            addHistoryItem(url, data.title);
        }
    }

    async function analyzeUrl() {
        const url = albumUrlInput.value.trim();
        if (!url) {
            showError("Por favor, insira um link da web.");
            return;
        }

        hideError();
        btnAnalyze.classList.add('loading');
        btnAnalyze.disabled = true;
        
        // Trigger skeleton loading grid immediately for good Core Web Vitals (CLS reduction)
        renderSkeletons();

        try {
            const cookiesPath = cookiesPathInput ? cookiesPathInput.value.trim() : '';
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    url: url,
                    cookies_path: cookiesPath
                })
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || "Ocorreu um erro ao analisar o link.");
            }

            processAnalyzeResponse(data, url);

        } catch (err) {
            showError(err.message);
            mediaDashboard.classList.add('hidden');
        } finally {
            btnAnalyze.classList.remove('loading');
            btnAnalyze.disabled = false;
        }
    }

    // Get FontAwesome icon based on file extension
    function getDocumentIcon(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        switch (ext) {
            case 'pdf':
                return 'fa-file-pdf';
            case 'zip':
            case 'rar':
            case '7z':
            case 'tar':
            case 'gz':
                return 'fa-file-zipper';
            case 'docx':
            case 'doc':
                return 'fa-file-word';
            case 'xlsx':
            case 'xls':
            case 'csv':
                return 'fa-file-excel';
            case 'pptx':
            case 'ppt':
                return 'fa-file-powerpoint';
            case 'txt':
                return 'fa-file-lines';
            case 'epub':
                return 'fa-book';
            case 'exe':
            case 'msi':
            case 'dmg':
            case 'pkg':
                return 'fa-box';
            default:
                return 'fa-file';
        }
    }

    // 2. Media Grid Rendering
    function renderGrid() {
        if (!albumData) return;
        
        mediaGrid.innerHTML = '';
        
        const filteredMedia = albumData.media.filter(item => {
            if (activeFilter === 'all') return true;
            return item.type === activeFilter;
        });
        currentMediaList = filteredMedia;

        if (filteredMedia.length === 0) {
            mediaGrid.innerHTML = `
                <div class="glass-card" style="grid-column: 1 / -1; padding: 3rem; text-align: center; color: var(--text-muted); width: 100%;">
                    <i class="fa-solid fa-folder-open" style="font-size: 2.5rem; margin-bottom: 1rem; color: var(--primary);"></i>
                    <p>Nenhuma mídia encontrada com esta aba.</p>
                </div>
            `;
            return;
        }

        filteredMedia.forEach(item => {
            const card = document.createElement('div');
            const isSelected = selectedMediaIds.has(item.id);
            card.dataset.id = item.id;
            card.dataset.filename = item.filename;
            
            // Standard square grid layouts for images and videos
            if (item.type === 'image' || item.type === 'video') {
                card.className = `media-card ${item.type}-card ${isSelected ? 'selected' : ''}`;
                const badgeIcon = item.type === 'video' 
                    ? '<div class="media-badge video"><i class="fa-solid fa-play"></i></div>'
                    : '<div class="media-badge image"><i class="fa-solid fa-image"></i></div>';
                
                card.innerHTML = `
                    <div class="card-checkbox">
                        <i class="fa-solid fa-check"></i>
                    </div>
                    <img src="${addTokenToUrl(item.thumbnail)}" class="media-card-thumbnail" loading="lazy" alt="Preview">
                    ${badgeIcon}
                    <div class="media-card-source" style="position: absolute; bottom: 8px; left: 8px; z-index: 5; background: rgba(0,0,0,0.65); padding: 1px 6px; border-radius: 4px; font-size: 0.6rem; color: var(--text-muted); pointer-events: none;">
                        ${item.source || ''}
                    </div>
                `;

                // Actions wrapper for hover controls
                const actionsWrapper = document.createElement('div');
                actionsWrapper.className = 'card-actions-wrapper';
                card.appendChild(actionsWrapper);
                updateCardActions(card, item);
            }
            // Stylized cards for Audio files
            else if (item.type === 'audio') {
                card.className = `media-card audio-card ${isSelected ? 'selected' : ''}`;
                card.innerHTML = `
                    <div class="card-checkbox">
                        <i class="fa-solid fa-check"></i>
                    </div>
                    <i class="fa-solid fa-music file-main-icon"></i>
                    <div class="media-card-title">${item.filename}</div>
                    <div class="media-card-source">${item.source || 'Áudio'}</div>
                `;

                // Hover Action Wrapper for direct download
                const actionsWrapper = document.createElement('div');
                actionsWrapper.className = 'card-actions-wrapper';
                card.appendChild(actionsWrapper);
                updateCardActions(card, item);
            }
            // Stylized cards for Documents / ZIP / Other assets
            else if (item.type === 'document') {
                card.className = `media-card document-card ${isSelected ? 'selected' : ''}`;
                const docIconClass = getDocumentIcon(item.filename);
                card.innerHTML = `
                    <div class="card-checkbox">
                        <i class="fa-solid fa-check"></i>
                    </div>
                    <i class="fa-solid ${docIconClass} file-main-icon"></i>
                    <div class="media-card-title">${item.filename}</div>
                    <div class="media-card-source">${item.source || 'Arquivo'}</div>
                `;

                // Hover Action Wrapper for direct download
                const actionsWrapper = document.createElement('div');
                actionsWrapper.className = 'card-actions-wrapper';
                card.appendChild(actionsWrapper);
                updateCardActions(card, item);
            }

            // Card click behavior: toggle selection
            card.addEventListener('click', (e) => {
                // If they clicked an action button or inside the actions wrapper, do not toggle selection
                if (e.target.closest('.card-actions-wrapper')) return;
                if (selectedMediaIds.has(item.id)) {
                    selectedMediaIds.delete(item.id);
                    card.classList.remove('selected');
                } else {
                    selectedMediaIds.add(item.id);
                    card.classList.add('selected');
                }
                updateSelectedUI();
            });

            mediaGrid.appendChild(card);
        });
    }

    // 3. Selection UI Updates
    function updateSelectedUI() {
        const count = selectedMediaIds.size;
        selectedCounter.textContent = `${count} ${count === 1 ? 'arquivo selecionado' : 'arquivos selecionados'}`;
        btnDownloadStart.disabled = (count === 0);
    }

    // 4. Selection Control Event Listeners
    btnSelectAll.addEventListener('click', () => {
        if (!albumData) return;
        
        albumData.media.forEach(item => {
            if (activeFilter === 'all' || item.type === activeFilter) {
                selectedMediaIds.add(item.id);
            }
        });
        
        renderGrid();
        updateSelectedUI();
    });

    btnDeselectAll.addEventListener('click', () => {
        if (!albumData) return;
        
        albumData.media.forEach(item => {
            if (activeFilter === 'all' || item.type === activeFilter) {
                selectedMediaIds.delete(item.id);
            }
        });
        
        renderGrid();
        updateSelectedUI();
    });

    // 5. Filter Controls
    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeFilter = btn.dataset.filter;
            renderGrid();
        });
    });

    // 6. Download Trigger
    btnDownloadStart.addEventListener('click', async () => {
        if (!albumData || selectedMediaIds.size === 0) return;
        
        const path = downloadPathInput.value.trim();
        if (!path) {
            showError("Por favor, informe o diretório para salvar os arquivos.");
            return;
        }

        // Filter selected items
        const selectedItems = albumData.media.filter(item => selectedMediaIds.has(item.id));
        
        hideError();
        btnDownloadStart.disabled = true;

        try {
            const cookiesPath = cookiesPathInput ? cookiesPathInput.value.trim() : '';
            const concurrencySelect = document.getElementById('download-concurrency');
            const concurrency = concurrencySelect ? parseInt(concurrencySelect.value, 10) : 4;
            const response = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    items: selectedItems,
                    download_dir: path,
                    album_url: albumUrlInput.value.trim(),
                    cookies_path: cookiesPath,
                    concurrency: concurrency
                })
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || "Erro ao iniciar download.");
            }

            mediaDashboard.classList.add('hidden');
            progressPanel.classList.remove('hidden');
            progressPath.textContent = path;
            progressPanel.scrollIntoView({ behavior: 'smooth' });

            startProgressPolling();

        } catch (err) {
            showError(err.message);
            btnDownloadStart.disabled = false;
        }
    });

    // 7. Status Polling loop
    function startProgressPolling() {
        if (statusIntervalId) clearInterval(statusIntervalId);
        pollStatus(); 
        statusIntervalId = setInterval(pollStatus, 500);
    }

    async function pollStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();

            if (!response.ok) throw new Error("Erro na rede.");

            const activeFilenames = Object.keys(data.active_downloads);

            // Render individual progress overlays on cards in the grid
            const cards = document.querySelectorAll('.media-card');
            cards.forEach(card => {
                const filename = card.dataset.filename;
                if (!filename) return;
                
                if (activeFilenames.includes(filename)) {
                    const file = data.active_downloads[filename];
                    
                    let overlay = card.querySelector('.card-progress-overlay');
                    if (!overlay) {
                        overlay = document.createElement('div');
                        overlay.className = 'card-progress-overlay';
                        overlay.innerHTML = `
                            <i class="fa-solid fa-spinner card-progress-spinner"></i>
                            <div class="card-progress-text">0%</div>
                            <div class="card-progress-speed">0 KB/s</div>
                            <button class="card-progress-cancel" title="Cancelar download" style="position: absolute; top: 6px; right: 6px; background: rgba(239, 68, 68, 0.85); border: none; color: #fff; border-radius: 50%; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; font-size: 0.7rem; cursor: pointer; transition: all 0.2s; z-index: 10;">
                                <i class="fa-solid fa-xmark"></i>
                            </button>
                        `;
                        card.appendChild(overlay);
                        
                        const cancelBtn = overlay.querySelector('.card-progress-cancel');
                        if (cancelBtn) {
                            cancelBtn.addEventListener('click', async (e) => {
                                e.stopPropagation();
                                cancelBtn.disabled = true;
                                cancelBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
                                try {
                                    const response = await fetch('/api/cancel', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({ filename: filename })
                                    });
                                    if (response.ok) {
                                        showToast(`Cancelando download de: ${filename}`, "info");
                                        overlay.innerHTML = `
                                            <i class="fa-solid fa-circle-xmark" style="color: var(--error); font-size: 1.5rem; margin-bottom: 4px;"></i>
                                            <div class="card-progress-text" style="color: var(--error); font-size: 0.72rem;">Cancelado</div>
                                        `;
                                        setTimeout(() => { if (overlay.parentNode) overlay.remove(); }, 2000);
                                    }
                                } catch (err) {
                                    console.error("Erro ao cancelar download:", err);
                                    cancelBtn.disabled = false;
                                    cancelBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
                                }
                            });
                        }
                    }
                    
                    const pctText = overlay.querySelector('.card-progress-text');
                    const speedText = overlay.querySelector('.card-progress-speed');
                    if (pctText && pctText.textContent !== "Cancelado") {
                        pctText.textContent = `${file.progress}%`;
                    }
                    if (speedText) speedText.textContent = file.speed;
                } else {
                    const overlay = card.querySelector('.card-progress-overlay');
                    if (overlay && !overlay.querySelector('.fa-circle-check')) {
                        overlay.remove();
                    }
                    
                    // Update actions dynamically if file just finished downloading
                    if (albumData) {
                        const item = albumData.media.find(m => m.filename === filename);
                        if (item && !item.exists_locally && selectedMediaIds.has(item.id)) {
                            item.exists_locally = true;
                            updateCardActions(card, item);
                        }
                    }
                }
            });

            // Update inline downloads overlays if any exist
            if (inlineDownloads.size > 0) {
                for (const filename of Array.from(inlineDownloads)) {
                    if (activeFilenames.includes(filename)) {
                        const file = data.active_downloads[filename];
                        updateInlineProgressUI(filename, file.progress, file.speed);
                    } else {
                        // File finished downloading
                        removeInlineProgressUI(filename, true);
                        inlineDownloads.delete(filename);
                    }
                }
            }

            const isBatchActive = !progressPanel.classList.contains('hidden');

            if (isBatchActive) {
                // Update UI elements
                progressFileCount.textContent = `${data.downloaded_files} / ${data.total_files} concluídos`;
                overallProgressBar.style.width = `${data.overall_progress}%`;
                overallPercentage.textContent = data.overall_progress;

                // Render active rows
                activeFilesList.innerHTML = '';
                
                activeFilenames.forEach(filename => {
                    if (inlineDownloads.has(filename)) return; // Skip showing inline downloads in the main list
                    const file = data.active_downloads[filename];
                    const row = document.createElement('div');
                    row.className = 'download-row';
                    row.innerHTML = `
                        <div class="download-row-info">
                            <span class="download-filename" title="${filename}">${filename}</span>
                            <div class="download-stats">
                                <span class="download-speed">${file.speed}</span>
                                <span>${file.progress}%</span>
                            </div>
                        </div>
                        <div class="row-bar-container">
                            <div class="row-bar-fill" style="width: ${file.progress}%"></div>
                        </div>
                    `;
                    activeFilesList.appendChild(row);
                });
            }

            // Handle completion states
            if (data.status === 'completed') {
                clearInterval(statusIntervalId);
                statusIntervalId = null;
                
                if (isBatchActive) {
                    progressPanel.classList.add('hidden');
                    modalFolderPath.textContent = data.download_dir;
                    completionModal.classList.remove('hidden');
                }
                
                // Clear any remaining inline downloads
                inlineDownloads.forEach(filename => {
                    removeInlineProgressUI(filename, true);
                });
                inlineDownloads.clear();
                
                btnDownloadStart.disabled = false;
            } else if (data.status === 'error') {
                clearInterval(statusIntervalId);
                statusIntervalId = null;
                
                if (isBatchActive) {
                    progressPanel.classList.add('hidden');
                    mediaDashboard.classList.remove('hidden');
                }
                showError(data.error_message || "Erro no download.");
                
                // Clear inline downloads
                inlineDownloads.forEach(filename => {
                    removeInlineProgressUI(filename, false);
                });
                inlineDownloads.clear();
                
                btnDownloadStart.disabled = false;
            } else if (data.status === 'idle') {
                clearInterval(statusIntervalId);
                statusIntervalId = null;
                
                if (isBatchActive) {
                    progressPanel.classList.add('hidden');
                    mediaDashboard.classList.remove('hidden');
                }
                
                // Clear inline downloads
                inlineDownloads.forEach(filename => {
                    removeInlineProgressUI(filename, false);
                });
                inlineDownloads.clear();
                
                btnDownloadStart.disabled = (selectedMediaIds.size === 0);
            }

        } catch (err) {
            console.error("Erro ao obter progresso:", err);
        }
    }

    // 8. Cancel download thread
    btnCancel.addEventListener('click', async () => {
        if (!confirm("Tem certeza que deseja cancelar os downloads atuais?")) return;
        
        try {
            await fetch('/api/cancel', { method: 'POST' });
            if (statusIntervalId) clearInterval(statusIntervalId);
            
            // Clear inline downloads and overlays
            inlineDownloads.clear();
            const overlays = document.querySelectorAll('.card-progress-overlay');
            overlays.forEach(overlay => overlay.remove());
            
            progressPanel.classList.add('hidden');
            mediaDashboard.classList.remove('hidden');
            btnDownloadStart.disabled = false;
        } catch (err) {
            console.error("Erro ao cancelar:", err);
        }
    });

    // 9. Close Modal Click
    btnCloseModal.addEventListener('click', () => {
        completionModal.classList.add('hidden');
        mediaDashboard.classList.remove('hidden');
    });

    // 10. Video Preview Modal Handlers
    function openVideoPreview(url, filename) {
        currentMediaIndex = currentMediaList.findIndex(item => item.filename === filename);
        // Destroy previous HLS instance if any
        if (hlsInstance) {
            hlsInstance.destroy();
            hlsInstance = null;
        }

        previewTitle.textContent = `Prévia: ${filename}`;
        
        // Proxy the media URL through Flask to bypass Referer restrictions/CORS blocks
        const proxiedUrl = addTokenToUrl(`/api/proxy?url=${encodeURIComponent(url)}`);
        
        // Detect HLS stream
        const isHls = url.includes('.m3u8') || url.includes('/hls-');
        
        if (isHls && typeof Hls !== 'undefined') {
            if (Hls.isSupported()) {
                hlsInstance = new Hls();
                hlsInstance.loadSource(proxiedUrl);
                hlsInstance.attachMedia(previewVideoPlayer);
                hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
                    previewVideoPlayer.play().catch(err => {
                        console.log("Autoplay was blocked or failed:", err);
                    });
                });
            } else if (previewVideoPlayer.canPlayType('application/vnd.apple.mpegurl')) {
                // Native HLS (e.g. Safari)
                previewVideoPlayer.src = proxiedUrl;
                previewVideoPlayer.play().catch(err => {
                    console.log("Autoplay was blocked or failed:", err);
                });
            } else {
                showToast("Seu navegador não suporta a prévia de vídeos HLS (.m3u8).", "info");
            }
        } else {
            // Standard MP4 stream
            previewVideoPlayer.src = proxiedUrl;
            previewVideoPlayer.load();
            previewVideoPlayer.play().catch(err => {
                console.log("Autoplay was blocked or failed:", err);
            });
        }
        
        // Show modal
        previewModal.classList.remove('hidden');
    }

    function closeVideoPreview() {
        isClosingPreview = true;
        previewVideoPlayer.pause();
        if (hlsInstance) {
            hlsInstance.destroy();
            hlsInstance = null;
        }
        previewVideoPlayer.removeAttribute('src');
        previewVideoPlayer.load();
        previewModal.classList.add('hidden');
        // Reset flag after a tick so any queued error events are suppressed
        setTimeout(() => { isClosingPreview = false; }, 100);
    }

    btnClosePreview.addEventListener('click', closeVideoPreview);
    
    // Close modal if clicking outside the video container
    previewModal.addEventListener('click', (e) => {
        if (e.target === previewModal) {
            closeVideoPreview();
        }
    });

    // Listen for media playback errors to help with debugging and show to the user
    previewVideoPlayer.addEventListener('error', (e) => {
        // Ignore errors triggered by intentional src cleanup during close
        if (isClosingPreview) return;
        const err = previewVideoPlayer.error;
        let errorMessageText = "Erro desconhecido ao carregar o vídeo.";
        if (err) {
            switch (err.code) {
                case 1: // MEDIA_ERR_ABORTED
                    errorMessageText = "Carregamento do vídeo abortado.";
                    break;
                case 2: // MEDIA_ERR_NETWORK
                    errorMessageText = "Erro de rede ao carregar o vídeo.";
                    break;
                case 3: // MEDIA_ERR_DECODE
                    errorMessageText = "Erro ao decodificar o vídeo. O arquivo pode estar corrompido ou o formato é incompatível.";
                    break;
                case 4: // MEDIA_ERR_SRC_NOT_SUPPORTED
                    errorMessageText = "O formato ou link do vídeo não é suportado pelo seu navegador.";
                    break;
            }
            console.error("Video player error:", err.code, err.message);
        }
        
        // Show user-friendly alert
        showToast(`Erro na prévia: ${errorMessageText}`, "error");
        
        // Send telemetry error to Python console
        fetch('/api/log-error', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                error: `Video Error Code ${err ? err.code : 'unknown'}: ${err ? err.message : ''} (URL: ${previewVideoPlayer.src})`,
                filename: 'script.js',
                lineno: 463,
                colno: 0,
                stack: ''
            })
        });
    });

    function downloadToDevice(item) {
        // Build the direct proxy download URL
        const url = addTokenToUrl(`/api/proxy?url=${encodeURIComponent(item.url)}&download=true&filename=${encodeURIComponent(item.filename)}`);
        
        // Trigger browser native download
        const a = document.createElement('a');
        a.href = url;
        a.download = item.filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        
        // Cleanup element
        setTimeout(() => {
            document.body.removeChild(a);
        }, 100);
    }

    async function downloadSingleItem(item) {
        const path = downloadPathInput.value.trim();
        if (!path) {
            showError("Por favor, informe o diretório para salvar os arquivos.");
            return;
        }
        
        hideError();
        
        // Add to active inline downloads set
        inlineDownloads.add(item.filename);
        
        // Show initial loader overlay on this card immediately
        updateInlineProgressUI(item.filename, 0, "Pendente...");
        
        try {
            const cookiesPath = cookiesPathInput ? cookiesPathInput.value.trim() : '';
            const concurrencySelect = document.getElementById('download-concurrency');
            const concurrency = concurrencySelect ? parseInt(concurrencySelect.value, 10) : 4;
            const response = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    items: [item],
                    download_dir: path,
                    album_url: albumUrlInput.value.trim(),
                    cookies_path: cookiesPath,
                    concurrency: 1
                })
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || "Erro ao iniciar download.");
            }

            // Start progress polling (will update inline)
            startProgressPolling();

        } catch (err) {
            showError(err.message);
            inlineDownloads.delete(item.filename);
            removeInlineProgressUI(item.filename);
        }
    }

    function updateInlineProgressUI(filename, progress, speed) {
        const card = document.querySelector(`.media-card[data-filename="${CSS.escape(filename)}"]`);
        if (!card) return;
        
        let overlay = card.querySelector('.card-progress-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'card-progress-overlay';
            overlay.innerHTML = `
                <div class="card-progress-spinner"><i class="fa-solid fa-circle-notch fa-spin"></i></div>
                <div class="card-progress-text">0%</div>
                <div class="card-progress-speed">Conectando...</div>
            `;
            card.appendChild(overlay);
        }
        
        overlay.querySelector('.card-progress-text').textContent = `${progress}%`;
        overlay.querySelector('.card-progress-speed').textContent = speed || 'Baixando...';
    }

    function removeInlineProgressUI(filename, isSuccess = false) {
        const card = document.querySelector(`.media-card[data-filename="${CSS.escape(filename)}"]`);
        if (!card) return;
        
        const overlay = card.querySelector('.card-progress-overlay');
        if (overlay) {
            if (isSuccess) {
                overlay.innerHTML = `
                    <div style="color: var(--success); font-size: 1.8rem;"><i class="fa-solid fa-circle-check"></i></div>
                    <div style="font-size: 0.75rem; color: #fff; font-weight: 600; margin-top: 2px;">Salvo!</div>
                `;
                setTimeout(() => {
                    overlay.remove();
                }, 1800);
            } else {
                overlay.remove();
            }
        }
    }

    // Helper functions
    function showError(msg) {
        errorText.textContent = msg;
        errorMessage.classList.remove('hidden');
    }

    function hideError() {
        errorMessage.classList.add('hidden');
    }

    // Toast Notification System
    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;
        
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        
        let icon = '<i class="fa-solid fa-circle-info toast-icon"></i>';
        if (type === 'success') {
            icon = '<i class="fa-solid fa-circle-check toast-icon"></i>';
        } else if (type === 'error') {
            icon = '<i class="fa-solid fa-circle-xmark toast-icon"></i>';
        }
        
        toast.innerHTML = `
            ${icon}
            <span class="toast-message">${message}</span>
        `;
        
        container.appendChild(toast);
        
        // Remove toast after animation completes (5 seconds)
        setTimeout(() => {
            toast.remove();
        }, 5000);
    }

    // Paste Clipboard Content to URL Input
    const btnPaste = document.getElementById('btn-paste');
    if (btnPaste) {
        btnPaste.addEventListener('click', async () => {
            try {
                const text = await navigator.clipboard.readText();
                if (text) {
                    albumUrlInput.value = text;
                    showToast("Link colado com sucesso!", "success");
                } else {
                    showToast("A área de transferência está vazia.", "info");
                }
            } catch (err) {
                showToast("Dê permissão ao navegador para acessar a área de transferência.", "error");
            }
        });
    }

    // Carousel navigation helpers
    function navigateVideoPreview(direction) {
        if (currentMediaList.length === 0 || currentMediaIndex === -1) return;
        
        let newIndex = currentMediaIndex + direction;
        if (newIndex < 0) {
            newIndex = currentMediaList.length - 1;
        } else if (newIndex >= currentMediaList.length) {
            newIndex = 0;
        }
        
        let loops = 0;
        while (currentMediaList[newIndex].type !== 'video' && loops < currentMediaList.length) {
            newIndex += direction;
            if (newIndex < 0) newIndex = currentMediaList.length - 1;
            else if (newIndex >= currentMediaList.length) newIndex = 0;
            loops++;
        }
        
        if (currentMediaList[newIndex].type === 'video') {
            currentMediaIndex = newIndex;
            closeVideoPreview();
            setTimeout(() => {
                openVideoPreview(currentMediaList[newIndex].url, currentMediaList[newIndex].filename);
            }, 150);
        }
    }

    function navigateImagePreview(direction) {
        if (currentMediaList.length === 0 || currentMediaIndex === -1) return;

        let newIndex = currentMediaIndex + direction;
        if (newIndex < 0) {
            newIndex = currentMediaList.length - 1;
        } else if (newIndex >= currentMediaList.length) {
            newIndex = 0;
        }

        let loops = 0;
        while (currentMediaList[newIndex].type !== 'image' && loops < currentMediaList.length) {
            newIndex += direction;
            if (newIndex < 0) newIndex = currentMediaList.length - 1;
            else if (newIndex >= currentMediaList.length) newIndex = 0;
            loops++;
        }

        if (currentMediaList[newIndex].type === 'image') {
            currentMediaIndex = newIndex;
            resetImageZoom();
            openImagePreview(currentMediaList[newIndex].url, currentMediaList[newIndex].filename);
        }
    }

    // Carousel navigation button event listeners
    const btnPrevVideo = document.getElementById('btn-prev-video');
    const btnNextVideo = document.getElementById('btn-next-video');
    const btnPrevImage = document.getElementById('btn-prev-image');
    const btnNextImage = document.getElementById('btn-next-image');

    if (btnPrevVideo) btnPrevVideo.addEventListener('click', (e) => { e.stopPropagation(); navigateVideoPreview(-1); });
    if (btnNextVideo) btnNextVideo.addEventListener('click', (e) => { e.stopPropagation(); navigateVideoPreview(1); });
    if (btnPrevImage) btnPrevImage.addEventListener('click', (e) => { e.stopPropagation(); navigateImagePreview(-1); });
    if (btnNextImage) btnNextImage.addEventListener('click', (e) => { e.stopPropagation(); navigateImagePreview(1); });

    // Keyboard arrow keys navigation
    document.addEventListener('keydown', (e) => {
        if (!previewModal.classList.contains('hidden')) {
            if (e.key === 'ArrowLeft') navigateVideoPreview(-1);
            if (e.key === 'ArrowRight') navigateVideoPreview(1);
            if (e.key === 'Escape') closeVideoPreview();
        } else if (!imagePreviewModal.classList.contains('hidden')) {
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                navigateImagePreview(-1);
            }
            if (e.key === 'ArrowRight') {
                e.preventDefault();
                navigateImagePreview(1);
            }
            if (e.key === 'Escape') closeImagePreview();
            if (e.key === 's' || e.key === 'S') toggleSelectCurrentImage();
        } else if (mangaReaderModal && !mangaReaderModal.classList.contains('hidden')) {
            if (e.key === 'Escape') closeMangaReader();
        }
    });

    // ============================================================
    // FEATURE: Size Filter Slider
    // ============================================================
    const sizeFilterSlider = document.getElementById('size-filter-slider');
    const sizeFilterValue = document.getElementById('size-filter-value');
    let currentSizeFilterBytes = 0;

    function formatSliderLabel(bytes) {
        if (bytes === 0) return 'Tudo';
        if (bytes < 1024 * 1024) return `> ${Math.round(bytes / 1024)} KB`;
        return `> ${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    if (sizeFilterSlider) {
        // Slider goes 0-100, map to 0-10MB range (exponential for feel)
        sizeFilterSlider.addEventListener('input', () => {
            const v = parseInt(sizeFilterSlider.value, 10);
            if (v === 0) {
                currentSizeFilterBytes = 0;
            } else {
                // Exponential scale: 0 = 0, 50 = ~500KB, 100 = 10MB
                currentSizeFilterBytes = Math.round(Math.pow(v / 100, 2) * 10 * 1024 * 1024);
            }
            sizeFilterValue.textContent = formatSliderLabel(currentSizeFilterBytes);
            applyFiltersAndRender();
        });
    }

    // Override renderGrid to also apply size filter
    const _originalRenderGrid = renderGrid;
    function applyFiltersAndRender() {
        if (!albumData) return;
        mediaGrid.innerHTML = '';

        const filteredMedia = albumData.media.filter(item => {
            // Type filter
            if (activeFilter !== 'all' && item.type !== activeFilter) return false;
            // Size filter
            if (currentSizeFilterBytes > 0) {
                const sizeBytes = item.size_bytes || 0;
                // Only filter items that have a known size (skip streaming/unknown)
                if (sizeBytes > 0 && sizeBytes < currentSizeFilterBytes) return false;
            }
            return true;
        });

        currentMediaList = filteredMedia;

        if (filteredMedia.length === 0) {
            mediaGrid.innerHTML = `
                <div class="glass-card" style="grid-column: 1 / -1; padding: 3rem; text-align: center; color: var(--text-muted); width: 100%;">
                    <i class="fa-solid fa-filter-circle-xmark" style="font-size: 2.5rem; margin-bottom: 1rem; color: var(--primary);"></i>
                    <p>Nenhuma mídia passou pelos filtros ativos.</p>
                    <p style="font-size: 0.8rem; margin-top: 8px;">Reduza o filtro de tamanho ou mude a aba.</p>
                </div>
            `;
            return;
        }

        // Show/hide Manga Reader button (only for image-heavy results)
        const imageCount = filteredMedia.filter(i => i.type === 'image').length;
        const btnMangaReader = document.getElementById('btn-manga-reader');
        if (btnMangaReader) {
            btnMangaReader.style.display = imageCount >= 2 ? 'inline-flex' : 'none';
        }

        filteredMedia.forEach(item => {
            const card = document.createElement('div');
            const isSelected = selectedMediaIds.has(item.id);
            card.dataset.id = item.id;
            card.dataset.filename = item.filename;

            if (item.type === 'image' || item.type === 'video') {
                card.className = `media-card ${item.type}-card ${isSelected ? 'selected' : ''}`;
                const badgeIcon = item.type === 'video'
                    ? '<div class="media-badge video"><i class="fa-solid fa-play"></i></div>'
                    : '<div class="media-badge image"><i class="fa-solid fa-image"></i></div>';
                card.innerHTML = `
                    <div class="card-checkbox"><i class="fa-solid fa-check"></i></div>
                    <img src="${addTokenToUrl(item.thumbnail)}" class="media-card-thumbnail" loading="lazy" alt="Preview">
                    ${badgeIcon}
                    <div class="media-card-source" style="position: absolute; bottom: 8px; left: 8px; z-index: 5; background: rgba(0,0,0,0.65); padding: 1px 6px; border-radius: 4px; font-size: 0.6rem; color: var(--text-muted); pointer-events: none;">
                        ${item.source || ''}
                    </div>
                `;
                const actionsWrapper = document.createElement('div');
                actionsWrapper.className = 'card-actions-wrapper';
                card.appendChild(actionsWrapper);
                updateCardActions(card, item);
            } else if (item.type === 'audio') {
                card.className = `media-card audio-card ${isSelected ? 'selected' : ''}`;
                card.innerHTML = `
                    <div class="card-checkbox"><i class="fa-solid fa-check"></i></div>
                    <i class="fa-solid fa-music file-main-icon"></i>
                    <div class="media-card-title">${item.filename}</div>
                    <div class="media-card-source">${item.source || 'Áudio'}</div>
                `;
                const actionsWrapper = document.createElement('div');
                actionsWrapper.className = 'card-actions-wrapper';
                card.appendChild(actionsWrapper);
                updateCardActions(card, item);
            } else {
                card.className = `media-card document-card ${isSelected ? 'selected' : ''}`;
                const iconMap = { 'pdf': 'fa-file-pdf', 'zip': 'fa-file-zipper', 'rar': 'fa-file-zipper', 'docx': 'fa-file-word', 'doc': 'fa-file-word' };
                const ext = (item.filename || '').split('.').pop().toLowerCase();
                const iconClass = iconMap[ext] || 'fa-file-lines';
                card.innerHTML = `
                    <div class="card-checkbox"><i class="fa-solid fa-check"></i></div>
                    <i class="fa-solid ${iconClass} file-main-icon"></i>
                    <div class="media-card-title">${item.filename}</div>
                    <div class="media-card-source">${item.source || 'Arquivo'}</div>
                `;
                const actionsWrapper = document.createElement('div');
                actionsWrapper.className = 'card-actions-wrapper';
                card.appendChild(actionsWrapper);
                updateCardActions(card, item);
            }

            // Selection click
            card.addEventListener('click', (e) => {
                if (e.target.closest('.card-actions-wrapper') || e.target.closest('.card-checkbox')) return;
                toggleSelect(item.id);
            });

            mediaGrid.appendChild(card);
        });
    }

    // Patch filter buttons and select-all to call applyFiltersAndRender
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeFilter = btn.dataset.filter;
            applyFiltersAndRender();
        });
    });

    // ============================================================
    // FEATURE: Manga Reader (Modo Leitura)
    // ============================================================
    const mangaReaderModal = document.getElementById('manga-reader-modal');
    const mangaReaderContent = document.getElementById('manga-reader-content');
    const mangaReaderTitle = document.getElementById('manga-reader-title');
    const mangaReaderPages = document.getElementById('manga-reader-pages');
    const btnCloseMangaReader = document.getElementById('btn-close-manga-reader');
    const btnReaderTheme = document.getElementById('btn-reader-theme');
    const btnReaderDownloadAll = document.getElementById('btn-reader-download-all');
    const btnMangaReader = document.getElementById('btn-manga-reader');

    function openMangaReader() {
        if (!albumData || !mangaReaderModal) return;
        const images = currentMediaList.filter(i => i.type === 'image');
        if (images.length === 0) {
            showToast('Nenhuma imagem disponível para o Modo Leitura.', 'error');
            return;
        }

        mangaReaderContent.innerHTML = '';
        const title = albumData.title || 'Modo Leitura';
        mangaReaderTitle.innerHTML = `<i class="fa-solid fa-book-open"></i> ${title}`;
        mangaReaderPages.textContent = `${images.length} imagens`;

        let loadedCount = 0;
        images.forEach((item, idx) => {
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'position: relative; width: 100%; max-width: 800px; text-align: center;';

            const pageNum = document.createElement('div');
            pageNum.style.cssText = 'color: rgba(255,255,255,0.2); font-size: 0.7rem; margin-bottom: 4px; text-align: right; padding-right: 8px;';
            pageNum.textContent = `${idx + 1} / ${images.length}`;

            const img = document.createElement('img');
            img.loading = 'lazy';
            img.alt = item.filename;
            img.src = addTokenToUrl(item.url);
            img.addEventListener('load', () => {
                loadedCount++;
                mangaReaderPages.textContent = `${loadedCount} / ${images.length} carregadas`;
            });
            img.addEventListener('error', () => {
                img.style.opacity = '0.3';
                img.alt = 'Falha ao carregar';
            });

            wrapper.appendChild(pageNum);
            wrapper.appendChild(img);
            mangaReaderContent.appendChild(wrapper);
        });

        mangaReaderModal.classList.remove('hidden');
        mangaReaderContent.scrollTop = 0;
        document.body.style.overflow = 'hidden';
    }

    function closeMangaReader() {
        if (!mangaReaderModal) return;
        mangaReaderModal.classList.add('hidden');
        document.body.style.overflow = '';
    }

    if (btnMangaReader) {
        btnMangaReader.addEventListener('click', openMangaReader);
    }

    if (btnCloseMangaReader) {
        btnCloseMangaReader.addEventListener('click', closeMangaReader);
    }

    if (btnReaderTheme) {
        btnReaderTheme.addEventListener('click', () => {
            mangaReaderModal.classList.toggle('pure-black');
            const isPureBlack = mangaReaderModal.classList.contains('pure-black');
            btnReaderTheme.innerHTML = isPureBlack
                ? '<i class="fa-solid fa-sun"></i> Claro'
                : '<i class="fa-solid fa-circle-half-stroke"></i> Tema';
        });
    }

    if (btnReaderDownloadAll) {
        btnReaderDownloadAll.addEventListener('click', () => {
            // Select all images and trigger download
            const images = currentMediaList.filter(i => i.type === 'image');
            images.forEach(item => selectedMediaIds.add(item.id));
            closeMangaReader();
            showToast(`${images.length} imagens selecionadas. Inicie o download normalmente.`, 'success');
            // Refresh card states
            document.querySelectorAll('.media-card').forEach(card => {
                if (selectedMediaIds.has(card.dataset.id)) card.classList.add('selected');
            });
        });
    }

    // Close manga reader if clicking outside content area
    if (mangaReaderModal) {
        mangaReaderModal.addEventListener('click', (e) => {
            if (e.target === mangaReaderModal) closeMangaReader();
        });
    }
});

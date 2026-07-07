const DEFAULT_VORTEX_BASE = 'http://127.0.0.1:8080';

chrome.runtime.onInstalled.addListener(() => {
    chrome.contextMenus.create({
        id: "send-to-vortex",
        title: "Baixar com Vortex",
        contexts: ["page", "image", "link", "video", "audio"]
    });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === "send-to-vortex") {
        let url = info.linkUrl || info.srcUrl || info.pageUrl;
        if (url) {
            chrome.storage.local.get(['vortex_server_url'], (result) => {
                const base = result.vortex_server_url || DEFAULT_VORTEX_BASE;
                chrome.tabs.create({ url: `${base}/?url=${encodeURIComponent(url)}&auto=1` });
            });
        }
    }
});

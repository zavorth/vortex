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
            // Open Vortex in a new tab and pass the URL to auto-analyze
            chrome.tabs.create({ url: `http://127.0.0.1:8080/?url=${encodeURIComponent(url)}&auto=1` });
        }
    }
});

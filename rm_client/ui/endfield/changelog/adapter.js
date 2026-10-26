/* 本地日志数据接口；保留原公告组件及其动画，不接入游戏桥或远程 API。 */
(() => {
    "use strict";
    const entries = window.POLAR_CHANGELOG.entries;
    window.POLAR_CHANGELOG_API = Object.freeze({
        async get(value) {
            const path = new URL(value, location.href).pathname;
            if (path.endsWith("/v2/aggregate")) {
                return {code: 0, data: {
                    key: "polar-local-changelog", popupVersion: 0, updatedAt: 0,
                    onlineList: entries.map(item => ({cid: item.cid, version: item.version,
                        needPopup: false, needRedDot: false})),
                    list: entries.map(({data, ...item}) => item),
                }};
            }
            const item = entries.find(item => path.endsWith("/detail/" + item.cid));
            return item ? {code: 0, data: item} : {code: 404, msg: "Unknown local entry"};
        },
    });
    const close = () => { location.href = new URL("close.local", location.href).href; };
    document.addEventListener("click", event => {
        if (event.target.closest(".jArhWq")) {
            event.preventDefault();
            event.stopImmediatePropagation();
            close();
        }
    }, true);
    document.addEventListener("keydown", event => {
        if (event.key === "Escape") {
            event.preventDefault();
            event.stopImmediatePropagation();
            close();
        }
    }, true);
    // 网络门禁也由原生页面实现；这里让意外的脚本网络调用立即结束。
    window.fetch = () => Promise.reject(new Error("Changelog runs offline"));
    const observer = new MutationObserver(() => {
        if (!document.querySelector(".ziE87l.OfLMAm .ej1XT0 p")) return;
        observer.disconnect();
        document.title = window.POLAR_CHANGELOG.title;
        // 字体与内容布局完成后再跨过两次绘制回调，交给 Qt 显示已有页面。
        document.fonts.ready.then(() => requestAnimationFrame(() =>
            requestAnimationFrame(() => console.info("POLAR_CHANGELOG_READY"))));
    });
    observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true});
})();

(function () {
    let refreshInProgress = false;
    let lastNewIds = new Set();
    let refreshTimer = null;
    let kdsSettings = {
        refresh: 10000,
        sound: true,
        gridUrl: "/kitchen/display/grid",
    };

    function getCurrentNewIds() {
        const ids = new Set();
        document.querySelectorAll(".o_kitchen_display_column_new .o_kitchen_display_item_click").forEach((el) => {
            const id = el.dataset.lineId;
            if (id) {
                ids.add(String(id));
            }
        });
        return ids;
    }

    function readSettingsFromDom() {
        const root = document.querySelector(".o_kitchen_display_page");
        if (!root) {
            return;
        }

        const refreshSeconds = parseInt(root.dataset.kdsRefreshSeconds || "10", 10);
        const soundEnabled = (root.dataset.kdsSound || "true") === "true";

        kdsSettings.refresh = Math.max(refreshSeconds, 3) * 1000;
        kdsSettings.sound = soundEnabled;
        kdsSettings.gridUrl = root.dataset.kdsGridUrl || "/kitchen/display/grid";
    }

    function restartAutoRefresh() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
        }
        refreshTimer = setInterval(refreshGrid, kdsSettings.refresh);
    }

    function playBeep() {
        if (!kdsSettings.sound) {
            return;
        }

        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) {
                return;
            }

            const ctx = new AudioContext();
            const oscillator = ctx.createOscillator();
            const gain = ctx.createGain();

            oscillator.type = "sine";
            oscillator.frequency.setValueAtTime(880, ctx.currentTime);

            gain.gain.setValueAtTime(0.001, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);

            oscillator.connect(gain);
            gain.connect(ctx.destination);

            oscillator.start(ctx.currentTime);
            oscillator.stop(ctx.currentTime + 0.26);
        } catch (e) {
            console.warn("No se pudo reproducir el beep:", e);
        }
    }

    async function refreshGrid() {
        if (refreshInProgress) {
            return;
        }

        refreshInProgress = true;
        try {
            const beforeIds = getCurrentNewIds();

            const response = await fetch(kdsSettings.gridUrl, {
                credentials: "same-origin",
            });
            const html = await response.text();

            const wrapper = document.createElement("div");
            wrapper.innerHTML = html;

            const newGrid = wrapper.querySelector(".o_kitchen_display_grid");
            const currentGrid = document.querySelector(".o_kitchen_display_grid");

            if (newGrid && currentGrid) {
                currentGrid.replaceWith(newGrid);
            }

            readSettingsFromDom();
            restartAutoRefresh();

            const afterIds = getCurrentNewIds();

            let hasNew = false;
            for (const id of afterIds) {
                if (!beforeIds.has(id) && !lastNewIds.has(id)) {
                    hasNew = true;
                    break;
                }
            }

            if (hasNew) {
                playBeep();
            }

            lastNewIds = afterIds;
        } finally {
            refreshInProgress = false;
        }
    }

    async function postAndRefresh(url) {
        await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: "{}",
            credentials: "same-origin",
        });

        await refreshGrid();
    }

    document.addEventListener("click", async function (ev) {
        const lineEl = ev.target.closest(".o_kitchen_display_item_click");
        if (lineEl) {
            ev.preventDefault();
            ev.stopPropagation();

            const lineId = lineEl.dataset.lineId;
            if (lineId) {
                await postAndRefresh(`/kitchen/display/line/${lineId}/next`);
            }
            return;
        }

        const headerEl = ev.target.closest(".o_kitchen_display_card_header_click");
        if (headerEl) {
            const orderId = headerEl.dataset.orderId;
            const fromState = headerEl.dataset.fromState;

            if (orderId && fromState) {
                ev.preventDefault();
                await postAndRefresh(`/kitchen/display/order/${orderId}/move/${fromState}`);
            }
        }
    });

    document.addEventListener("DOMContentLoaded", function () {
        readSettingsFromDom();
        lastNewIds = getCurrentNewIds();
        restartAutoRefresh();
    });
})();

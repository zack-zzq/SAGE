/**
 * SAGE — Student Article Grading Engine
 * Frontend application logic – with task persistence
 */

// ── State ──────────────────────────────────────────
let rubricFile = null;
let essaysFile = null;
const reports = [];   // { index, title, author, markdown?, error? }
let activeTab = -1;
let currentTaskId = null;

// ── DOM Refs ───────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const configToggle = $("#configToggle");
const configPanel = $("#configPanel");
const baseUrlInput = $("#baseUrl");
const modelIdInput = $("#modelId");
const apiKeyInput = $("#apiKey");
const rubricZone = $("#rubricZone");
const essaysZone = $("#essaysZone");
const rubricInput = $("#rubricInput");
const essaysInput = $("#essaysInput");
const rubricName = $("#rubricFileName");
const essaysName = $("#essaysFileName");
const userPrompt = $("#userPrompt");
const gradeBtn = $("#gradeBtn");
const progressSec = $("#progressSection");
const progressBar = $("#progressBar");
const progressText = $("#progressText");
const reportsSec = $("#reportsSection");
const reportTabs = $("#reportTabs");
const reportContent = $("#reportContent");
const exportBtn = $("#exportBtn");

// ── Init ───────────────────────────────────────────
(async function init() {
    // Load defaults from server
    try {
        const res = await fetch("/api/defaults");
        if (res.ok) {
            const d = await res.json();
            baseUrlInput.placeholder = d.base_url || "https://api.openai.com/v1";
            modelIdInput.placeholder = d.model_id || "gpt-4o";
            if (d.api_key_set) apiKeyInput.placeholder = "（已通过环境变量设置）";
        }
    } catch { /* ignore */ }

    // Auto-resize textarea
    autoResize(userPrompt);

    // Check for a previously active task
    const savedTaskId = localStorage.getItem("sage_active_task");
    if (savedTaskId) {
        await reconnectTask(savedTaskId);
    }
})();

// ── Textarea Auto-Resize ───────────────────────────
function autoResize(el) {
    function resize() {
        el.style.height = "auto";
        el.style.height = el.scrollHeight + "px";
    }
    el.addEventListener("input", resize);
    resize();
}

// ── Config Toggle ──────────────────────────────────
configToggle.addEventListener("click", () => {
    configPanel.classList.toggle("open");
    configToggle.classList.toggle("active");
});

// ── File Upload ────────────────────────────────────
function setupDropZone(zone, input, nameEl, onFile) {
    zone.addEventListener("click", () => input.click());

    zone.addEventListener("dragover", (e) => {
        e.preventDefault();
        zone.classList.add("dragover");
    });

    zone.addEventListener("dragleave", () => {
        zone.classList.remove("dragover");
    });

    zone.addEventListener("drop", (e) => {
        e.preventDefault();
        zone.classList.remove("dragover");
        if (e.dataTransfer.files.length) {
            handleFile(e.dataTransfer.files[0], zone, nameEl, onFile);
        }
    });

    input.addEventListener("change", () => {
        if (input.files.length) {
            handleFile(input.files[0], zone, nameEl, onFile);
        }
    });
}

function handleFile(file, zone, nameEl, onFile) {
    zone.classList.add("has-file");
    nameEl.textContent = file.name;
    onFile(file);
    checkReady();
}

setupDropZone(rubricZone, rubricInput, rubricName, (f) => { rubricFile = f; });
setupDropZone(essaysZone, essaysInput, essaysName, (f) => { essaysFile = f; });

// ── Readiness Check ────────────────────────────────
function checkReady() {
    gradeBtn.disabled = !(rubricFile && essaysFile);
}

// ── Grade Button ───────────────────────────────────
gradeBtn.addEventListener("click", startGrading);

async function startGrading() {
    if (!rubricFile || !essaysFile) return;

    // Reset UI
    resetReportsUI();
    showProgress();
    setButtonLoading(true);

    // Build form data
    const form = new FormData();
    form.append("rubric_file", rubricFile);
    form.append("essays_file", essaysFile);
    form.append("user_prompt", userPrompt.value || "请为每篇作文生成详细的批阅报告。");
    form.append("model_id", modelIdInput.value);
    form.append("base_url", baseUrlInput.value);
    form.append("api_key", apiKeyInput.value);

    try {
        // Submit and get task ID
        const res = await fetch("/api/grade", { method: "POST", body: form });
        const json = await res.json();

        if (json.error) {
            progressText.textContent = `❌ ${json.error}`;
            setButtonLoading(false);
            return;
        }

        currentTaskId = json.task_id;
        localStorage.setItem("sage_active_task", currentTaskId);
        progressText.textContent = `任务已创建（ID: ${currentTaskId}），正在处理...`;

        // Start streaming events
        await streamTaskEvents(currentTaskId, 0);

    } catch (err) {
        progressText.textContent = `连接错误：${err.message}`;
    }

    setButtonLoading(false);
}

// ── Reconnect to an existing task ──────────────────
async function reconnectTask(taskId) {
    try {
        const res = await fetch(`/api/task/${taskId}`);
        if (!res.ok) {
            localStorage.removeItem("sage_active_task");
            return;
        }

        const task = await res.json();

        // Show progress UI
        resetReportsUI();
        showProgress();
        currentTaskId = taskId;

        // Replay all stored events
        for (const evt of task.events) {
            handleSSE(evt.data);
        }

        // If still running, continue streaming from where we left off
        if (task.status !== "completed" && task.status !== "failed") {
            setButtonLoading(true);
            // Don't overwrite progressText — keep the last replayed event's message
            await streamTaskEvents(taskId, task.events.length);
            setButtonLoading(false);
        } else {
            // Task already done, just show results
            if (task.status === "completed") {
                exportBtn.style.display = "inline-flex";
            }
        }
    } catch {
        localStorage.removeItem("sage_active_task");
    }
}

// ── Stream SSE events from a task ──────────────────
async function streamTaskEvents(taskId, afterIndex) {
    try {
        const res = await fetch(`/api/task/${taskId}/stream?after=${afterIndex}`);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split("\n\n");
            buffer = lines.pop();

            for (const chunk of lines) {
                const line = chunk.trim();
                if (line.startsWith("data: ")) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        handleSSE(data);
                    } catch { /* skip malformed */ }
                }
            }
        }
    } catch (err) {
        progressText.textContent = `连接断开：${err.message}。刷新页面可自动重连。`;
    }
}

// ── SSE Handler ────────────────────────────────────
function handleSSE(data) {
    switch (data.type) {
        case "status":
            progressText.textContent = data.message;
            break;

        case "split_complete":
            progressText.textContent = data.message;
            progressBar.style.width = "5%";
            reportsSec.style.display = "block";
            break;

        case "grading":
            progressText.textContent = data.message;
            progressBar.style.width = `${5 + (data.current / data.total) * 90}%`;
            break;

        case "report":
            progressBar.style.width = `${5 + (data.current / data.total) * 95}%`;
            addReport({
                index: data.index,
                title: data.title,
                author: data.author,
                markdown: data.report_markdown,
            });
            break;

        case "report_error":
            addReport({
                index: data.current,
                title: data.title,
                author: data.author,
                error: data.message || data.error,
            });
            break;

        case "complete":
            progressBar.style.width = "100%";
            progressText.textContent = data.message;
            exportBtn.style.display = "inline-flex";
            localStorage.removeItem("sage_active_task");
            break;

        case "error":
            progressText.textContent = `❌ ${data.message}`;
            localStorage.removeItem("sage_active_task");
            break;
    }
}

// ── UI Helpers ─────────────────────────────────────
function resetReportsUI() {
    reports.length = 0;
    activeTab = -1;
    reportTabs.innerHTML = "";
    reportContent.innerHTML = "";
    reportsSec.style.display = "none";
    exportBtn.style.display = "none";
}

function showProgress() {
    progressSec.style.display = "block";
    progressBar.style.width = "0%";
    progressText.textContent = "准备中...";
}

function setButtonLoading(loading) {
    if (loading) {
        gradeBtn.classList.add("loading");
        gradeBtn.innerHTML = `<span class="loading-pulse">批阅中...</span>`;
    } else {
        gradeBtn.classList.remove("loading");
        gradeBtn.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon points="5 3 19 12 5 21 5 3"/>
            </svg>
            开始批阅`;
    }
}

// ── Reports UI ─────────────────────────────────────
function addReport(report) {
    reports.push(report);
    const idx = reports.length - 1;

    // Create tab
    const tab = document.createElement("button");
    tab.className = "report-tab" + (report.error ? " error" : "");
    tab.textContent = `${report.title}`;
    tab.title = `${report.author}`;
    tab.addEventListener("click", () => switchTab(idx));
    reportTabs.appendChild(tab);

    // Auto-switch to latest
    switchTab(idx);
}

function switchTab(idx) {
    activeTab = idx;
    const tabs = reportTabs.querySelectorAll(".report-tab");
    tabs.forEach((t, i) => t.classList.toggle("active", i === idx));

    const r = reports[idx];
    if (r.error) {
        reportContent.innerHTML = `<div class="report-error-msg">❌ ${r.title}（${r.author}）：${r.error}</div>`;
    } else {
        const actionsHtml = `
            <div class="report-actions">
                <button class="btn-secondary" onclick="exportSingleReport(${idx}, 'docx')" title="导出 Word 文档">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                        <line x1="16" y1="13" x2="8" y2="13"></line>
                        <line x1="16" y1="17" x2="8" y2="17"></line>
                        <polyline points="10 9 9 9 8 9"></polyline>
                    </svg>
                    Word
                </button>
                <button class="btn-secondary" onclick="exportSingleReport(${idx}, 'pdf')" title="导出 PDF 文档">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                        <line x1="16" y1="13" x2="8" y2="13"></line>
                        <line x1="16" y1="17" x2="8" y2="17"></line>
                        <polyline points="10 9 9 9 8 9"></polyline>
                    </svg>
                    PDF
                </button>
            </div>
        `;
        reportContent.innerHTML = actionsHtml + marked.parse(r.markdown || "");
    }
}

// ── Export ──────────────────────────────────────────
exportBtn.addEventListener("click", () => {
    let allText = "";
    for (const r of reports) {
        allText += `${"=".repeat(60)}\n`;
        allText += `作文：${r.title}　　作者：${r.author}\n`;
        allText += `${"=".repeat(60)}\n\n`;
        allText += r.markdown || r.error || "";
        allText += "\n\n\n";
    }

    const blob = new Blob([allText], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "SAGE_全部批阅报告.md";
    a.click();
    URL.revokeObjectURL(url);
});

// Used by dynamically injected buttons in switchTab
window.exportSingleReport = async function (idx, format) {
    const r = reports[idx];
    if (!r || r.error || !r.markdown) return;

    try {
        const btn = event.currentTarget;
        const origText = btn.innerHTML;
        btn.innerHTML = `<span class="loading-pulse">导出中...</span>`;
        btn.disabled = true;

        const res = await fetch(`/api/export/${format}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                markdown: r.markdown,
                title: r.title,
                author: r.author
            })
        });

        if (!res.ok) {
            const err = await res.json();
            alert(`导出失败：${err.error}`);
            btn.innerHTML = origText;
            btn.disabled = false;
            return;
        }

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;

        let filename = `SAGE_批阅报告_${r.title}.${format}`;
        const disposition = res.headers.get("Content-Disposition");
        if (disposition && disposition.indexOf("filename*=UTF-8''") !== -1) {
            filename = decodeURIComponent(disposition.split("filename*=UTF-8''")[1]);
        }

        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);

        btn.innerHTML = origText;
        btn.disabled = false;
    } catch (err) {
        alert(`导出出错：${err.message}`);
        // Cannot easily restore button state if event target is lost, but a reload or tab switch fixes it
    }
};

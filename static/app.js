/**
 * SAGE — Student Article Grading Engine
 * Frontend application logic
 */

// ── State ──────────────────────────────────────────
let rubricFile = null;
let essaysFile = null;
const reports = [];   // { index, title, author, markdown?, error? }
let activeTab = -1;

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
})();

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

    // Reset
    reports.length = 0;
    activeTab = -1;
    reportTabs.innerHTML = "";
    reportContent.innerHTML = "";
    reportsSec.style.display = "none";
    exportBtn.style.display = "none";
    progressSec.style.display = "block";
    progressBar.style.width = "0%";
    progressText.textContent = "准备中...";
    gradeBtn.classList.add("loading");
    gradeBtn.innerHTML = `<span class="loading-pulse">批阅中...</span>`;

    // Build form data
    const form = new FormData();
    form.append("rubric_file", rubricFile);
    form.append("essays_file", essaysFile);
    form.append("user_prompt", userPrompt.value || "请为每篇作文生成详细的批阅报告。");
    form.append("model_id", modelIdInput.value);
    form.append("base_url", baseUrlInput.value);
    form.append("api_key", apiKeyInput.value);

    try {
        const res = await fetch("/api/grade", { method: "POST", body: form });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            // Process complete SSE messages
            const lines = buffer.split("\n\n");
            buffer = lines.pop();  // keep incomplete message

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
        progressText.textContent = `连接错误：${err.message}`;
    }

    // Restore button
    gradeBtn.classList.remove("loading");
    gradeBtn.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="5 3 19 12 5 21 5 3"/>
        </svg>
        开始批阅`;
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
                error: data.message,
            });
            break;

        case "complete":
            progressBar.style.width = "100%";
            progressText.textContent = data.message;
            exportBtn.style.display = "inline-flex";
            break;

        case "error":
            progressText.textContent = `❌ ${data.message}`;
            break;
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
        reportContent.innerHTML = marked.parse(r.markdown || "");
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
    a.download = "SAGE_批阅报告.md";
    a.click();
    URL.revokeObjectURL(url);
});

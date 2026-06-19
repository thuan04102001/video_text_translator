import { useMemo, useRef, useState } from "react";
import axios from "axios";

const API = "http://127.0.0.1:8000";

async function selectFolder() {
  const res = await axios.get(`${API}/utility/select-folder`);
  return res.data.folder_path || "";
}

function formatTime(seconds) {
  const s = Number(seconds || 0);
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const secs = s % 60;
  return [
    hours.toString().padStart(2, "0"),
    minutes.toString().padStart(2, "0"),
    secs.toString().padStart(2, "0"),
  ].join(":");
}

function logClass(text) {
  if (text.includes("[DONE]") || text.includes("[LOGIN_OK]")) return "done";
  if (text.includes("[SKIP]") || text.includes("[SKIP PHOTO]")) return "skip";
  if (text.includes("[ERROR]") || text.includes("[CANCEL")) return "error";
  if (text.includes("[DOWNLOAD]") || text.includes("[BATCH]")) return "process";
  return "";
}

export default function CrawlerPanel() {
  const [url, setUrl] = useState("");
  const [folder, setFolder] = useState("");
  const [workers, setWorkers] = useState(1);
  const [taskId, setTaskId] = useState("");
  const [taskState, setTaskState] = useState("idle");
  const [platform, setPlatform] = useState("Chua co du lieu");
  const [logs, setLogs] = useState([]);
  const [total, setTotal] = useState(0);
  const [done, setDone] = useState(0);
  const [skipped, setSkipped] = useState(0);
  const [errors, setErrors] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef(null);
  const taskStateRef = useRef("idle");

  const progress = useMemo(() => {
    if (!total) return 0;
    return Math.min(100, Math.floor(((done + skipped + errors) / total) * 100));
  }, [done, errors, skipped, total]);
  const logEntries = useMemo(
    () => buildCrawlerLogEntries(logs),
    [logs]
  );

  const appendLog = (text) => {
    setLogs((current) => [...current.slice(-999), text]);
  };

  const updateTaskState = (nextState) => {
    taskStateRef.current = nextState;
    setTaskState(nextState);
  };

  const startTimer = () => {
    if (timerRef.current) return;
    timerRef.current = window.setInterval(() => {
      setElapsed((value) => value + 1);
    }, 1000);
  };

  const stopTimer = () => {
    if (!timerRef.current) return;
    window.clearInterval(timerRef.current);
    timerRef.current = null;
  };

  const resetRunState = () => {
    setLogs([]);
    setPlatform("Chua co du lieu");
    setTotal(0);
    setDone(0);
    setSkipped(0);
    setErrors(0);
    setElapsed(0);
    stopTimer();
  };

  const sendControl = async (action) => {
    if (!taskId) return;
    const formData = new FormData();
    formData.append("task_id", taskId);
    formData.append("action", action);
    await fetch(`${API}/crawler/task-control`, {
      method: "POST",
      body: formData,
    });
  };

  const handleBrowse = async () => {
    try {
      const selected = await selectFolder();
      if (selected) setFolder(selected);
    } catch (err) {
      console.error(err);
      alert("Khong chon duoc folder luu.");
    }
  };

  const finishRun = (nextState = "done") => {
    stopTimer();
    updateTaskState(nextState);
    setTaskId("");
  };

  const handleMainAction = async (event) => {
    event.preventDefault();

    if (taskState === "running") {
      await sendControl("pause");
      updateTaskState("paused");
      appendLog("[PAUSED] Se tam dung truoc video ke tiep");
      stopTimer();
      return;
    }

    if (taskState === "paused") {
      await sendControl("resume");
      updateTaskState("running");
      appendLog("[RESUME] Tiep tuc tai");
      startTimer();
      return;
    }

    if (!url.trim()) {
      alert("Hay nhap link profile/page.");
      return;
    }

    if (!folder.trim()) {
      alert("Hay chon folder luu video.");
      return;
    }

    const nextTaskId = Date.now().toString();
    setTaskId(nextTaskId);
    updateTaskState("running");
    resetRunState();
    startTimer();

    const formData = new FormData();
    formData.append("url", url.trim());
    formData.append("folder", folder.trim());
    formData.append("workers", String(workers));
    formData.append("task_id", nextTaskId);

    try {
      const response = await fetch(`${API}/crawler/download`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok || !response.body) {
        throw new Error(await response.text());
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;

          const text = line.replace("data:", "").trim();
          if (!text) continue;

          if (text.startsWith("[PLATFORM]")) {
            setPlatform(text.replace("[PLATFORM]", "").trim() || "unknown");
            continue;
          }

          if (text.includes("[SYSTEM] TOTAL")) {
            const numbers = text.match(/\d+/g);
            if (numbers?.length) setTotal(Number(numbers[numbers.length - 1]));
            appendLog(text);
            continue;
          }

          if (text.includes("[DONE]")) setDone((value) => value + 1);
          else if (text.includes("[SKIP]")) setSkipped((value) => value + 1);
          else if (text.includes("[ERROR]")) setErrors((value) => value + 1);

          appendLog(text);

          if (text.includes("[FINISHED]")) {
            finishRun(taskStateRef.current === "cancelled" ? "cancelled" : "done");
          }
        }
      }
    } catch (err) {
      console.error(err);
      setErrors((value) => value + 1);
      appendLog(`[ERROR] ${err.message || "Download failed"}`);
      finishRun("error");
    }
  };

  const handleCancel = async () => {
    if (!taskId) return;
    await sendControl("cancel");
    updateTaskState("cancelled");
    appendLog("[CANCEL] Dang huy sau batch hien tai...");
    stopTimer();
  };

  const mainText =
    taskState === "running"
      ? "Pause"
      : taskState === "paused"
        ? "Continue"
        : "Start Download";

  return (
    <div className="crawler-shell">
      <style>{crawlerCss}</style>
      <div className="crawler-layout">
        <aside className="crawler-sidebar">
          <div className="crawler-brand">
            <span className="crawler-mark">CR</span>
            <div>
              <h1>Video Crawler</h1>
              <p>TikTok + Facebook Reels Downloader</p>
            </div>
          </div>

          <form className="crawler-form" onSubmit={handleMainAction}>
            <label>
              Profile / Page URL
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="Nhap link profile/page"
                disabled={taskState === "running" || taskState === "paused"}
              />
            </label>

            <label>
              Save folder
              <div className="folder-row">
                <input value={folder} readOnly placeholder="Chon folder luu video" />
                <button type="button" onClick={handleBrowse}>Browse</button>
              </div>
            </label>

            <label>
              So luong: {workers}
              <input
                type="range"
                min="1"
                max="10"
                value={workers}
                onChange={(event) => setWorkers(Number(event.target.value))}
              />
            </label>

            <button
              type="submit"
              className={`primary ${taskState === "paused" ? "continue" : ""}`}
              disabled={taskState === "cancelled"}
            >
              {mainText}
            </button>

            <button
              type="button"
              className="danger"
              onClick={handleCancel}
              disabled={!taskId || taskState !== "running"}
            >
              Cancel
            </button>
          </form>
        </aside>

        <main className="crawler-main">
          <section className="crawler-stats">
            <Stat label="STATUS" value={taskState.toUpperCase()} tone={taskState} />
            <Stat label="PLATFORM" value={platform} />
            <Stat label="TOTAL" value={total} />
            <Stat label="DOWNLOADED" value={done} />
            <Stat label="SKIPPED" value={skipped} />
            <Stat label="ERRORS" value={errors} />
            <Stat label="TIME" value={formatTime(elapsed)} />
          </section>

          <section className="crawler-log-panel">
            <div className="log-head">
              <h2>Download Log</h2>
              <span>{progress}%</span>
            </div>
            <div className="progress-track">
              <div style={{ width: `${progress}%` }} />
            </div>
            <div className="crawler-log">
              {logEntries.length === 0 ? (
                <div className="muted">Log crawler se hien thi o day.</div>
              ) : (
                logEntries.map((entry) => (
                  <CrawlerLogEntry
                    key={entry.key}
                    entry={entry}
                  />
                ))
              )}
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}

function Stat({ label, value, tone = "" }) {
  return (
    <div className={`crawler-stat ${tone}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function parseCrawlerLog(log) {
  const raw = String(log || "");
  const tagMatch = raw.match(/^\[([^\]]+)\]\s*/);
  const tag = tagMatch ? tagMatch[1] : "INFO";
  const body = raw.replace(/^\[[^\]]+\]\s*/, "").trim();
  const fileMatch = body.match(/(?:error-)?[^\\/:*?"<>|\s]+\.mp4/i);
  const filename = fileMatch ? fileMatch[0] : body;
  const detail = fileMatch ? body.replace(fileMatch[0], "").replace(/^[:\s-]+/, "").trim() : "";

  return { tag, filename, detail };
}

function normalizeCrawlerLogFilename(filename) {
  return String(filename || "").replace(/^error-/i, "");
}

function buildCrawlerLogEntries(logs) {
  const entries = [];
  const byFile = new Map();

  logs.forEach((log, index) => {
    const parsed = parseCrawlerLog(log);
    const tone = logClass(log);
    const state = tone || parsed.tag.toLowerCase();
    const tag = parsed.tag.toUpperCase();

    if (!["DOWNLOAD", "DONE", "ERROR"].includes(tag)) return;

    const key = normalizeCrawlerLogFilename(parsed.filename) || `${index}-${log}`;

    const existing = byFile.get(key);

    if (existing) {
      existing.tag = parsed.tag;
      existing.state = state;
      existing.detail = parsed.detail;
      existing.raw = log;
      existing.updatedOrder = index;
      existing.progress = state === "done" || state === "skip" || state === "error"
        ? 100
        : null;
      return;
    }

    const entry = {
      ...parsed,
      key,
      raw: log,
      state,
      order: entries.length,
      updatedOrder: index,
      progress: state === "done" || state === "skip" || state === "error"
        ? 100
        : null,
    };

    byFile.set(key, entry);
    entries.push(entry);
  });

  return entries.sort(compareCrawlerLogEntries);
}

function compareCrawlerLogEntries(left, right) {
  const priority = (entry) => entry.state === "process" ? 0 : entry.state === "error" ? 1 : 2;
  const priorityDifference = priority(left) - priority(right);

  if (priorityDifference !== 0) return priorityDifference;
  if (left.state === "process") return left.order - right.order;
  return right.updatedOrder - left.updatedOrder;
}

function CrawlerLogEntry({ entry }) {
  const item = entry || {};
  const tone = item.state || "";
  const isProcess = tone === "process";
  const isDone = tone === "done";
  const isError = tone === "error";
  const progressValue = isDone || isError ? 100 : null;

  return (
    <div className={`crawler-log-entry ${tone ? `is-${tone}` : ""}`}>
      <div className="crawler-log-icon" aria-hidden="true">
        {isProcess ? <span className="crawler-log-spinner" /> : isDone ? "OK" : isError ? "!" : String(item.tag || "IN").slice(0, 2)}
      </div>
      <div className="crawler-log-main">
        <div className="crawler-log-file">{item.filename}</div>
        {item.detail ? <div className="crawler-log-detail">{item.detail}</div> : null}
        {!isError ? (
          <div className={`crawler-log-progress ${isProcess ? "is-indeterminate" : ""}`}>
            <span style={progressValue === null ? undefined : { width: `${progressValue}%` }} />
          </div>
        ) : null}
      </div>
      <div className="crawler-log-meta">
        {isProcess ? "DOWN" : item.tag}
      </div>
    </div>
  );
}

const crawlerCss = `
.crawler-shell {
  min-height: calc(100vh - 86px);
  padding: 24px clamp(16px, 2.2vw, 30px) 34px;
  color: #f8fafc;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.crawler-layout {
  max-width: 1536px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(340px, 410px) minmax(0, 1fr);
  gap: clamp(18px, 2vw, 28px);
  align-items: start;
  animation: crawlerPanelIn 0.42s cubic-bezier(.2,.8,.2,1) both;
}
.crawler-sidebar,
.crawler-log-panel,
.crawler-stat {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.09);
  background:
    linear-gradient(145deg, rgba(31, 33, 42, 0.94), rgba(14, 16, 23, 0.94)),
    radial-gradient(circle at 18% 0%, rgba(99, 102, 241, 0.12), transparent 18rem);
  box-shadow: 0 22px 70px rgba(0,0,0,0.34);
  backdrop-filter: blur(14px);
}
.crawler-sidebar {
  min-height: 720px;
  border-radius: 24px;
  padding: clamp(24px, 2.4vw, 34px);
}
.crawler-brand {
  display: flex;
  gap: 15px;
  align-items: center;
  margin-bottom: 30px;
}
.crawler-mark {
  width: 42px;
  height: 42px;
  display: inline-grid;
  place-items: center;
  border-radius: 12px;
  color: #dbe7ff;
  font-size: 0.82rem;
  font-weight: 950;
  letter-spacing: 0.04em;
  background: linear-gradient(135deg, #5b7cfa, #8b5cf6);
  box-shadow: 0 14px 34px rgba(91, 124, 250, 0.26);
}
.crawler-brand h1 {
  margin: 0;
  font-size: clamp(1.75rem, 2vw, 2.12rem);
  line-height: 1.05;
  letter-spacing: 0;
}
.crawler-brand p {
  margin: 9px 0 0;
  color: #b4bac8;
  line-height: 1.45;
}
.crawler-form {
  display: grid;
  gap: 20px;
}
.crawler-form label {
  color: #aeb5c4;
  display: grid;
  gap: 10px;
  font-size: 0.86rem;
  line-height: 1.35;
}
.crawler-form input {
  min-height: 48px;
  width: 100%;
  box-sizing: border-box;
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 13px;
  background: rgba(255,255,255,0.065);
  color: white;
  padding: 0 16px;
  font-size: 1rem;
  outline: none;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, background 0.18s ease;
}
.crawler-form input:focus {
  border-color: rgba(141, 168, 255, 0.58);
  background: rgba(255,255,255,0.085);
  box-shadow: 0 0 0 4px rgba(91, 124, 250, 0.12);
}
.crawler-form input:disabled {
  opacity: 0.72;
}
.folder-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 106px;
  gap: 10px;
  align-items: stretch;
}
.crawler-form button {
  min-height: 52px;
  border: 0;
  border-radius: 14px;
  color: white;
  font-weight: 850;
  cursor: pointer;
  transition: transform 0.18s ease, opacity 0.18s ease, filter 0.18s ease, box-shadow 0.18s ease;
}
.crawler-form button:not(:disabled):hover {
  transform: translateY(-2px);
  filter: brightness(1.06);
}
.crawler-form button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}
.folder-row button {
  background: linear-gradient(180deg, #424551, #343743);
  border: 1px solid rgba(255,255,255,0.08);
}
.primary {
  background: linear-gradient(135deg, #5b7cfa 0%, #8b5cf6 100%);
  box-shadow: 0 18px 40px rgba(91, 124, 250, 0.24);
}
.primary.continue {
  background: linear-gradient(135deg, #1d9a65, #22c55e);
}
.danger {
  background: linear-gradient(135deg, #c24141, #e05252);
}
.crawler-form input[type="range"] {
  min-height: 28px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  background: transparent;
  box-shadow: none;
  accent-color: #6b7cff;
}
.crawler-main {
  display: grid;
  gap: clamp(18px, 2vw, 24px);
  align-content: start;
  min-width: 0;
}
.crawler-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(108px, 1fr));
  gap: 14px;
}
.crawler-stat {
  min-height: 86px;
  border-radius: 16px;
  padding: 18px;
  display: grid;
  align-content: center;
  gap: 10px;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}
.crawler-stat:hover {
  transform: translateY(-2px);
  border-color: rgba(141, 168, 255, 0.26);
}
.crawler-stat span {
  color: #a7abb7;
  font-size: 0.76rem;
  font-weight: 750;
}
.crawler-stat b {
  color: #f8fafc;
  font-size: clamp(1.05rem, 1.45vw, 1.75rem);
  line-height: 1.08;
  overflow-wrap: anywhere;
}
.crawler-stat:nth-child(2) b,
.crawler-stat:nth-child(7) b {
  font-size: clamp(0.95rem, 1.15vw, 1.35rem);
}
.crawler-stat.running b {
  color: #4ade80;
}
.crawler-stat.paused b {
  color: #facc15;
}
.crawler-stat.error b,
.crawler-stat.cancelled b {
  color: #f87171;
}
.crawler-stat.done b {
  color: #22d3ee;
}
.crawler-log-panel {
  border-radius: 24px;
  padding: clamp(20px, 2vw, 28px);
}
.log-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.log-head h2 {
  margin: 0;
  font-size: 1.25rem;
  letter-spacing: 0;
}
.log-head span {
  color: #c7ccd8;
}
.progress-track {
  height: 12px;
  border-radius: 999px;
  background: rgba(255,255,255,0.07);
  overflow: hidden;
  margin-bottom: 18px;
}
.progress-track div {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #5b7cfa, #8b5cf6, #14b8a6);
  transition: width 0.35s cubic-bezier(.2,.8,.2,1);
  position: relative;
}
.progress-track div::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.32), transparent);
  animation: crawlerShimmer 1.35s linear infinite;
}
.crawler-log {
  height: min(58vh, 590px);
  min-height: 420px;
  overflow: auto;
  padding: 18px;
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(7,8,11,0.96), rgba(2,3,5,0.96));
  border: 1px solid rgba(255,255,255,0.07);
  font-family: "Cascadia Mono", Consolas, ui-monospace, monospace;
  font-size: 0.86rem;
  line-height: 1.62;
  scrollbar-color: rgba(141, 168, 255, 0.46) rgba(255,255,255,0.05);
  scrollbar-width: thin;
  display: grid;
  align-content: start;
  gap: 0.55rem;
}
.crawler-log::-webkit-scrollbar {
  width: 10px;
}
.crawler-log::-webkit-scrollbar-track {
  background: rgba(255,255,255,0.04);
  border-radius: 999px;
}
.crawler-log::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, #5b7cfa, #8b5cf6);
  border-radius: 999px;
}
.crawler-log > div {
  overflow-wrap: anywhere;
  animation: crawlerLogIn 0.18s ease both;
}
.crawler-log .done {
  color: #4ade80;
}
.crawler-log .skip {
  color: #facc15;
}
.crawler-log .error {
  color: #f87171;
}
.crawler-log .process {
  color: #60a5fa;
}
.crawler-log-entry {
  min-width: 0;
  display: grid;
  grid-template-columns: 2.25rem minmax(0, 1fr) auto;
  gap: 0.75rem;
  align-items: center;
  padding: 0.7rem 0.78rem;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 0.9rem;
  color: #e5e7eb;
  background: linear-gradient(135deg, rgba(255,255,255,0.065), rgba(255,255,255,0.026));
}
.crawler-log-entry.is-process {
  border-color: rgba(96, 165, 250, 0.26);
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.18), rgba(15, 23, 42, 0.35));
}
.crawler-log-entry.is-done {
  border-color: rgba(74, 222, 128, 0.22);
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.16), rgba(15, 23, 42, 0.34));
}
.crawler-log-entry.is-error {
  border-color: rgba(248, 113, 113, 0.28);
  background: linear-gradient(135deg, rgba(127, 29, 29, 0.3), rgba(24, 10, 14, 0.72));
}
.crawler-log-icon {
  width: 2.25rem;
  height: 2.25rem;
  display: grid;
  place-items: center;
  border-radius: 999px;
  color: #dbeafe;
  font-size: 0.68rem;
  font-weight: 900;
  background: rgba(255,255,255,0.08);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
}
.is-done .crawler-log-icon {
  color: #052e16;
  background: linear-gradient(135deg, #4ade80, #22c55e);
}
.is-error .crawler-log-icon {
  color: #fff1f2;
  background: linear-gradient(135deg, #ef4444, #fb7185);
}
.crawler-log-spinner {
  width: 1rem;
  height: 1rem;
  border-radius: 999px;
  border: 2px solid rgba(147, 197, 253, 0.25);
  border-top-color: #93c5fd;
  animation: crawlerLogSpin 0.72s linear infinite;
}
.crawler-log-main {
  min-width: 0;
}
.crawler-log-file {
  color: #f8fafc;
  font-weight: 850;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.is-done .crawler-log-file {
  color: #86efac;
}
.is-error .crawler-log-file {
  color: #fecaca;
  white-space: normal;
  overflow-wrap: anywhere;
}
.crawler-log-detail {
  margin-top: 0.18rem;
  color: #fca5a5;
  font-size: 0.76rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.crawler-log-progress {
  height: 0.28rem;
  margin-top: 0.52rem;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255,255,255,0.07);
}
.crawler-log-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #60a5fa, #8b5cf6);
  transition: width 0.32s cubic-bezier(.2,.8,.2,1), background 0.2s ease;
}
.crawler-log-progress.is-indeterminate span {
  width: 36%;
  animation: crawlerLogIndeterminate 1.15s ease-in-out infinite;
}
.is-done .crawler-log-progress span {
  background: linear-gradient(90deg, #4ade80, #22c55e);
}
.crawler-log-meta {
  justify-self: end;
  min-width: 3.1rem;
  padding: 0.24rem 0.5rem;
  border-radius: 999px;
  color: #b9c2d5;
  background: rgba(255,255,255,0.07);
  font-size: 0.7rem;
  font-weight: 900;
  text-align: center;
}
.is-process .crawler-log-meta {
  color: #bfdbfe;
  background: rgba(59, 130, 246, 0.17);
}
.is-done .crawler-log-meta {
  color: #bbf7d0;
  background: rgba(34, 197, 94, 0.15);
}
.is-error .crawler-log-meta {
  color: #fecaca;
  background: rgba(239, 68, 68, 0.18);
}
.muted {
  color: #7f8695;
}
@keyframes crawlerPanelIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@keyframes crawlerLogIn {
  from {
    opacity: 0;
    transform: translateY(3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@keyframes crawlerShimmer {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(100%);
  }
}
@keyframes crawlerLogSpin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes crawlerLogIndeterminate {
  from {
    transform: translateX(-130%);
  }
  to {
    transform: translateX(390%);
  }
}
@media (max-width: 1180px) {
  .crawler-layout {
    grid-template-columns: 1fr;
  }
  .crawler-sidebar {
    min-height: auto;
  }
  .crawler-stats {
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  }
}
@media (max-width: 680px) {
  .crawler-shell {
    padding: 14px 12px 24px;
  }
  .crawler-sidebar,
  .crawler-log-panel {
    border-radius: 18px;
  }
  .folder-row,
  .crawler-stats {
    grid-template-columns: 1fr;
  }
  .crawler-log {
    height: 460px;
    min-height: 360px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .crawler-layout,
  .crawler-log > div,
  .progress-track div::after {
    animation: none;
  }
  .crawler-form button,
  .crawler-stat,
  .progress-track div,
  .crawler-form input {
    transition: none;
  }
}
`;

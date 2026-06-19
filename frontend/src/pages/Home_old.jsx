import { useState, useEffect } from "react";
import { Video, Wand2 } from "lucide-react";
import axios from "axios";

import {
  analyzeVideo,
  processVideo,
  selectFolder,
  cleanupOneVideo,
} from "../api/videoApi";

const API = "http://127.0.0.1:8000";

async function startBatch(payload) {
  const res = await axios.post(`${API}/batch/start`, payload);
  return res.data;
}

async function getBatchStatus() {
  const res = await axios.get(`${API}/batch/status`);
  return res.data;
}

async function pauseBatch() {
  const res = await axios.post(`${API}/batch/pause`);
  return res.data;
}

async function resumeBatch() {
  const res = await axios.post(`${API}/batch/resume`);
  return res.data;
}

async function cancelBatch() {
  const res = await axios.post(`${API}/batch/cancel`);
  return res.data;
}
async function loadGeminiModels(apiKey) {
  const res = await axios.get(`${API}/gemini/models`, {
    params: {
      api_key: apiKey,
    },
  });

  return res.data.models || [];
}
async function loadOpenAIModels(apiKey) {
  const res = await axios.get(`${API}/openai/models`, {
    params: {
      api_key: apiKey,
    },
  });

  return res.data.models || [];
}
async function loadAIConfig() {
  const res = await axios.get(`${API}/ai/config`);
  return res.data;
}

async function checkOpenRouterKey(apiKey) {
  const res = await axios.get(`${API}/openrouter/check-key`, {
    params: {
      api_key: apiKey,
    },
  });

  return res.data.valid;
}
async function loadOpenRouterModels() {
  const res = await axios.get(`${API}/openrouter/models`);

  return res.data.models || [];
}
export default function Home() {
  const [video, setVideo] = useState(null);
  const [targetLang] = useState("vi");
  const mode = "auto";

  const [translationMode, setTranslationMode] = useState("argos");

  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [openaiModel, setOpenaiModel] = useState("gpt-4o-mini");
  const [openaiModels, setOpenaiModels] = useState([]);
  const [loadingOpenaiModels, setLoadingOpenaiModels] = useState(false);

  const [geminiApiKey, setGeminiApiKey] = useState("");
  const [geminiModel, setGeminiModel] = useState("gemini-2.5-flash");
  const [geminiModels, setGeminiModels] = useState([]);
  const [loadingGeminiModels, setLoadingGeminiModels] = useState(false);

  const [openrouterApiKey, setOpenrouterApiKey] = useState("");
  const [openrouterModel, setOpenrouterModel] = useState("google/gemini-2.5-flash");
  const [openrouterModels, setOpenrouterModels] = useState([]);
  const [loadingOpenrouterModels, setLoadingOpenrouterModels] = useState(false);

  const [analysis, setAnalysis] = useState(null);
  const [downloadUrl, setDownloadUrl] = useState("");
  const [analyzedVideoName, setAnalyzedVideoName] = useState("");
  const [rendering, setRendering] = useState(false);

  const [batchMode, setBatchMode] = useState(true);
  const [inputDir, setInputDir] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [threads, setThreads] = useState(1);

  const [batchRunning, setBatchRunning] = useState(false);
  const [batchStatus, setBatchStatus] = useState({
    running: false,
    paused: false,
    cancel_requested: false,
    total: 0,
    done: 0,
    skipped: 0,
    errors: 0,
    active: 0,
    elapsed_seconds: 0,
    logs: [],
  });
  const handleOpenRouterKeyChange = async (value) => {
    setOpenrouterApiKey(value);

    if (!value.trim()) return;

    setLoadingOpenrouterModels(true);

    try {
      const valid = await checkOpenRouterKey(value.trim());

      if (!valid) {
        alert("OpenRouter API Key không hợp lệ");
        setLoadingOpenrouterModels(false);
        return;
      }

      if (openrouterModels.length === 0) {
        await loadOpenRouterModelsAuto();
      }
    } catch (err) {
      console.error(err);
      alert("Không kiểm tra được OpenRouter API Key");
    }

    setLoadingOpenrouterModels(false);
  };
  const handleGeminiKeyChange = async (value) => {
    setGeminiApiKey(value);
    setGeminiModels([]);

    if (!value.trim()) return;

    setLoadingGeminiModels(true);

    try {
      const models = await loadGeminiModels(value.trim());

      setGeminiModels(models);

      if (models.length > 0) {
        const preferred =
          models.find((m) => m.id === "gemini-5.0-flash") ||
          models.find((m) => m.id.includes("flash")) ||
          models[0];

        setGeminiModel(preferred.id);
      }
    } catch (err) {
      console.error(err);
      alert("Gemini API Key không hợp lệ hoặc không load được model");
    }

    setLoadingGeminiModels(false);
  };
  const handleOpenAIKeyChange = async (value) => {
    setOpenaiApiKey(value);
    setOpenaiModels([]);

    if (!value.trim()) return;

    setLoadingOpenaiModels(true);

    try {
      const models = await loadOpenAIModels(value.trim());

      setOpenaiModels(models);

      const preferred =
        models.find((m) => m.id === "gpt-4o-mini") ||
        models.find((m) => m.id.includes("gpt-4o")) ||
        models[0];

      if (preferred) {
        setOpenaiModel(preferred.id);
      }
    } catch (err) {
      console.error(err);
      alert("OpenAI API Key không hợp lệ");
    }

    setLoadingOpenaiModels(false);
  };
  const loadOpenRouterModelsAuto = async () => {
    setLoadingOpenrouterModels(true);

    try {
      const models = await loadOpenRouterModels();

      setOpenrouterModels(models);

      const preferred =
        models.find((m) => m.id === "google/gemini-2.5-flash") ||
        models.find((m) => m.id.includes("gemini")) ||
        models[0];

      if (preferred) {
        setOpenrouterModel(preferred.id);
      }
    } catch (err) {
      console.error(err);
    }

    setLoadingOpenrouterModels(false);
  };
  useEffect(() => {
    if (
      translationMode === "openrouter" &&
      openrouterModels.length === 0
    ) {
      loadOpenRouterModelsAuto();
    }
  }, [translationMode]);

  useEffect(() => {
  const initAIConfig = async () => {
    try {
      const config = await loadAIConfig();

      if (config.openai?.api_key) {
        setOpenaiApiKey(config.openai.api_key);
        setOpenaiModel(config.openai.default_model || "gpt-4o-mini");
        handleOpenAIKeyChange(config.openai.api_key);
      }

      if (config.gemini?.api_key) {
        setGeminiApiKey(config.gemini.api_key);
        setGeminiModel(config.gemini.default_model || "gemini-2.5-flash");
        handleGeminiKeyChange(config.gemini.api_key);
      }

      if (config.openrouter?.api_key) {
        setOpenrouterApiKey(config.openrouter.api_key);
        setOpenrouterModel(config.openrouter.default_model || "google/gemini-2.5-flash");
        loadOpenRouterModelsAuto();
      }
    } catch (err) {
      console.error("LOAD AI CONFIG ERROR:", err);
    }
  };

  initAIConfig();
}, []);
  const handleBrowseInput = async () => {
    try {
      const folder = await selectFolder();
      if (folder) setInputDir(folder);
    } catch (err) {
      console.error(err);
      alert("Không chọn được folder input");
    }
  };

  const handleBrowseOutput = async () => {
    try {
      const folder = await selectFolder();
      if (folder) setOutputDir(folder);
    } catch (err) {
      console.error(err);
      alert("Không chọn được folder output");
    }
  };

  const validateTranslationKey = () => {
    if (translationMode === "gpt" && !openaiApiKey.trim()) {
      alert("Hãy nhập OpenAI API Key khi dùng GPT");
      return false;
    }

    if (translationMode === "gemini" && !geminiApiKey.trim()) {
      alert("Hãy nhập Gemini API Key khi dùng Gemini");
      return false;
    }

    if (translationMode === "openrouter" && !openrouterApiKey.trim()) {
      alert("Hãy nhập OpenRouter API Key khi dùng OpenRouter");
      return false;
    }
    return true;
  };

  const renderWithMode = async (selectedMode, currentAnalysis) => {
    return await processVideo({
      video,
      targetLang,
      mode,
      analysis: currentAnalysis,
      translationMode: selectedMode,
      openaiApiKey,
      openaiModel,
      geminiApiKey,
      geminiModel,
      openrouterApiKey,
      openrouterModel,
    });
  };

  const handleRender = async () => {
    if (!video) {
      alert("Hãy chọn video trước");
      return;
    }

    if (!validateTranslationKey()) return;

    setRendering(true);
    setDownloadUrl("");

    let currentAnalysis = analysis;

    try {
      if (analyzedVideoName !== video.name) {
        setAnalysis(null);
        currentAnalysis = null;
      }

      if (!currentAnalysis) {
        currentAnalysis = await analyzeVideo({ video, mode });
        setAnalysis(currentAnalysis);
        setAnalyzedVideoName(video.name);
      }

      const data = await renderWithMode(translationMode, currentAnalysis);
      setDownloadUrl(data.download_url);
    } catch (err) {
      console.error(err);
      alert("Lỗi render video");
    }

    setRendering(false);
  };

  const handleBatchProcess = async () => {
    if (!inputDir || !outputDir) {
      alert("Chọn đủ Folder input và Folder output");
      return;
    }

    if (!validateTranslationKey()) return;

    const safeThreads = Math.max(1, Math.min(10, Number(threads) || 1));

    setBatchRunning(true);
    setBatchStatus({
      running: true,
      paused: false,
      cancel_requested: false,
      total: 0,
      done: 0,
      skipped: 0,
      errors: 0,
      active: 0,
      elapsed_seconds: 0,
      logs: ["[START] Bắt đầu batch..."],
    });

    try {
      const started = await startBatch({
        input_dir: inputDir,
        output_dir: outputDir,
        workers: safeThreads,
        threads: safeThreads,

        translation_mode: translationMode,

        openai_api_key: openaiApiKey,
        openai_model: openaiModel,

        gemini_api_key: geminiApiKey,
        gemini_model: geminiModel,

        openrouter_api_key: openrouterApiKey,
        openrouter_model: openrouterModel,
      });

      if (!started?.success) {
        alert(started?.message || "Không thể bắt đầu batch");
        setBatchRunning(false);
        return;
      }

      const timer = setInterval(async () => {
        try {
          const status = await getBatchStatus();
          setBatchStatus(status);
          setBatchRunning(Boolean(status.running));

          if (!status.running) {
            clearInterval(timer);
          }
        } catch (err) {
          console.error(err);
          clearInterval(timer);
          setBatchRunning(false);
          alert("Lỗi lấy trạng thái batch");
        }
      }, 1000);
    } catch (err) {
      console.error(err);
      setBatchRunning(false);
      alert("Lỗi xử lý batch");
    }
  };

  const handleBatchPause = async () => {
    await pauseBatch();
    const status = await getBatchStatus();
    setBatchStatus(status);
  };

  const handleBatchResume = async () => {
    await resumeBatch();
    const status = await getBatchStatus();
    setBatchStatus(status);
  };

  const handleBatchCancel = async () => {
    const ok = window.confirm(
      "Cancel sẽ không nhận video mới nữa, nhưng sẽ xử lý xong video đang chạy dở. Tiếp tục?"
    );

    if (!ok) return;

    await cancelBatch();
    const status = await getBatchStatus();
    setBatchStatus(status);
  };

  const formatTime = (seconds) => {
    const s = Number(seconds || 0);

    const days = Math.floor(s / 86400);
    const hours = Math.floor((s % 86400) / 3600);
    const minutes = Math.floor((s % 3600) / 60);
    const secs = s % 60;

    if (days > 0) {
      return [
        days.toString().padStart(2, "0"),
        hours.toString().padStart(2, "0"),
        minutes.toString().padStart(2, "0"),
        secs.toString().padStart(2, "0"),
      ].join(":");
    }

    return [
      hours.toString().padStart(2, "0"),
      minutes.toString().padStart(2, "0"),
      secs.toString().padStart(2, "0"),
    ].join(":");
  };

  const total = batchStatus.total ?? 0;
  const done = batchStatus.done ?? 0;
  const skipped = batchStatus.skipped ?? 0;
  const errors = batchStatus.errors ?? 0;
  const elapsed = batchStatus.elapsed_seconds ?? 0;
  const paused = batchStatus.paused ?? false;
  const active = batchStatus.active ?? 0;
  const logs = batchStatus.logs ?? [];

  const normalLogs = logs.filter(
    (log) => !log.startsWith("[ERROR]") && !log.startsWith("[FATAL]")
  );

  const errorLogs = logs.filter(
    (log) => log.startsWith("[ERROR]") || log.startsWith("[FATAL]")
  );

  const progress =
    total > 0
      ? Math.min(100, Math.round(((done + skipped + errors) / total) * 100))
      : 0;

  const TranslationSettings = (
    <div className="bg-zinc-950/60 border border-zinc-800 rounded-2xl p-4 space-y-4">
      <div>
        <label className="text-sm text-zinc-400">AI Translate Engine</label>

        <select
          value={translationMode}
          onChange={(e) => setTranslationMode(e.target.value)}
          className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
        >
          <option value="argos">Argos Offline</option>
          <option value="gemini">Gemini API</option>
          <option value="openrouter">OpenRouter API</option>
          <option value="gpt">OpenAI API</option>
        </select>
      </div>

      {translationMode === "gemini" && (
        <div className="space-y-3">
          <div>
            <label className="text-sm text-zinc-400">Gemini API Key</label>
            <input
              type="password"
              value={geminiApiKey}
              onChange={(e) => handleGeminiKeyChange(e.target.value)}
              placeholder="AIza..."
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
          </div>

          <div>
            <label className="text-sm text-zinc-400">Gemini Model</label>
            <select
              value={geminiModel}
              onChange={(e) => setGeminiModel(e.target.value)}
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            >
              {geminiModels.length === 0 ? (
                <option value={geminiModel}>
                  {loadingGeminiModels ? "Đang load models..." : geminiModel}
                </option>
              ) : (
                geminiModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name || model.id}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>
      )}

      {translationMode === "openrouter" && (
        <div className="space-y-3">
          <div>
            <label className="text-sm text-zinc-400">OpenRouter API Key</label>
            <input
              type="password"
              value={openrouterApiKey}
              onChange={(e) => handleOpenRouterKeyChange(e.target.value)}
              placeholder="sk-or-v1-..."
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
          </div>

          <div>
            <label className="text-sm text-zinc-400">OpenRouter Model</label>
            <select
              value={openrouterModel}
              onChange={(e) => setOpenrouterModel(e.target.value)}
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            >
              {openrouterModels.length === 0 ? (
                <option value={openrouterModel}>
                  {loadingOpenrouterModels ? "Đang load models..." : openrouterModel}
                </option>
              ) : (
                openrouterModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name || model.id}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>
      )}

      {translationMode === "gpt" && (
        <div className="space-y-3">
          <div>
            <label className="text-sm text-zinc-400">OpenAI API Key</label>
            <input
              type="password"
              value={openaiApiKey}
              onChange={(e) => handleOpenAIKeyChange(e.target.value)}
              placeholder="sk-..."
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
          </div>

          <div>
            <label className="text-sm text-zinc-400">OpenAI Model</label>
            <select
              value={openaiModel}
              onChange={(e) => setOpenaiModel(e.target.value)}
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            >
              {openaiModels.length === 0 ? (
                <option value={openaiModel}>
                  {loadingOpenaiModels ? "Đang load models..." : openaiModel}
                </option>
              ) : (
                openaiModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.display_name || model.id}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="min-h-screen bg-zinc-950 text-white p-6">
      <div className="max-w-7xl mx-auto grid lg:grid-cols-[430px_1fr] gap-6">
        <div className="bg-zinc-900 rounded-3xl p-8 border border-zinc-800 shadow-2xl space-y-6">
          <div>
            <div className="flex items-center gap-3 mb-4">
              <Video className="text-purple-400" size={32} />
              <h1 className="text-3xl font-bold">AI Video Text Translator</h1>
            </div>

            <p className="text-zinc-400">
              Dịch caption meme nằm trong nền trắng, hỗ trợ single / multi timeline.
            </p>

            <div className="grid grid-cols-2 gap-3 mt-5">
              <button
                type="button"
                onClick={() => setBatchMode(false)}
                className={`rounded-xl px-4 py-3 font-bold border transition ${
                  !batchMode
                    ? "bg-purple-600 border-purple-400 text-white"
                    : "bg-zinc-800 border-zinc-700 text-zinc-300"
                }`}
              >
                1 Video
              </button>

              <button
                type="button"
                onClick={() => setBatchMode(true)}
                className={`rounded-xl px-4 py-3 font-bold border transition ${
                  batchMode
                    ? "bg-purple-600 border-purple-400 text-white"
                    : "bg-zinc-800 border-zinc-700 text-zinc-300"
                }`}
              >
                Batch Folder
              </button>
            </div>
          </div>

          {TranslationSettings}

          {batchMode ? (
            <div className="space-y-4">
              <div>
                <label className="text-sm text-zinc-400">Folder input</label>
                <div className="flex gap-2 mt-2">
                  <input
                    type="text"
                    value={inputDir}
                    readOnly
                    placeholder="Chọn Folder A"
                    className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none cursor-pointer"
                  />
                  <button
                    type="button"
                    onClick={handleBrowseInput}
                    className="bg-zinc-700 hover:bg-zinc-600 px-4 rounded-xl font-bold"
                  >
                    Browse
                  </button>
                </div>
              </div>

              <div>
                <label className="text-sm text-zinc-400">Folder output</label>
                <div className="flex gap-2 mt-2">
                  <input
                    type="text"
                    value={outputDir}
                    readOnly
                    placeholder="Chọn Folder B"
                    className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none cursor-pointer"
                  />
                  <button
                    type="button"
                    onClick={handleBrowseOutput}
                    className="bg-zinc-700 hover:bg-zinc-600 px-4 rounded-xl font-bold"
                  >
                    Browse
                  </button>
                </div>
              </div>

              <div>
                <label className="text-sm text-zinc-400">Số luồng: {threads}</label>
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={threads}
                  onChange={(e) => setThreads(Number(e.target.value))}
                  className="w-full mt-2"
                />
              </div>

              <button
                onClick={handleBatchProcess}
                disabled={batchRunning}
                className="w-full bg-purple-600 hover:bg-purple-500 disabled:opacity-60 px-4 py-4 rounded-xl font-bold"
              >
                {batchRunning ? "Đang xử lý..." : "Render Batch"}
              </button>

              <div className="grid grid-cols-3 gap-3">
                <button
                  type="button"
                  onClick={handleBatchPause}
                  disabled={!batchRunning || paused}
                  className="bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 px-4 py-3 rounded-xl font-bold"
                >
                  Pause
                </button>

                <button
                  type="button"
                  onClick={handleBatchResume}
                  disabled={!batchRunning || !paused}
                  className="bg-green-600 hover:bg-green-500 disabled:opacity-50 px-4 py-3 rounded-xl font-bold"
                >
                  Continue
                </button>

                <button
                  type="button"
                  onClick={handleBatchCancel}
                  disabled={!batchRunning}
                  className="bg-red-600 hover:bg-red-500 disabled:opacity-50 px-4 py-3 rounded-xl font-bold"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              <UploadBox
                video={video}
                onChange={async (file) => {
                  await cleanupOneVideo();

                  setVideo(file);
                  setAnalysis(null);
                  setDownloadUrl("");
                  setAnalyzedVideoName("");
                }}
              />

              <RenderButton loading={rendering} disabled={!video} onClick={handleRender}>
                <Wand2 size={20} />
                Render video
              </RenderButton>
            </>
          )}
        </div>

        <div className="space-y-6">
          {!batchMode && (
            <div className="grid xl:grid-cols-2 gap-6">
              <div className="bg-zinc-900 rounded-3xl p-8 border border-zinc-800 shadow-2xl">
                <h2 className="text-2xl font-bold mb-5">Preview gốc</h2>
                <PreviewPanel video={video} />
              </div>

              <div className="bg-zinc-900 rounded-3xl p-8 border border-zinc-800 shadow-2xl">
                <h2 className="text-2xl font-bold mb-5">Kết quả</h2>
                <ResultPanel downloadUrl={downloadUrl} />
              </div>
            </div>
          )}

          {batchMode && (
            <div className="space-y-6">
              <div className="grid md:grid-cols-7 gap-4">
                <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800">
                  <div className="text-zinc-400 text-sm">STATUS</div>

                  <div
                    className={`mt-3 font-bold ${
                      batchRunning
                        ? paused
                          ? "text-yellow-400"
                          : progress >= 100
                          ? "text-cyan-400"
                          : "text-green-400"
                        : progress >= 100
                        ? "text-cyan-400"
                        : "text-zinc-300"
                    }`}
                  >
                    {batchRunning
                      ? paused
                        ? "PAUSED"
                        : progress >= 100
                        ? "FINISHED"
                        : "RUNNING"
                      : progress >= 100
                      ? "FINISHED"
                      : "READY"}
                  </div>
                </div>

                <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800">
                  <div className="text-zinc-400 text-sm">TOTAL</div>
                  <div className="text-3xl font-bold mt-2">{total}</div>
                </div>

                <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800">
                  <div className="text-zinc-400 text-sm">DONE</div>
                  <div className="text-3xl font-bold mt-2">{done}</div>
                </div>

                <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800">
                  <div className="text-zinc-400 text-sm">SKIPPED</div>
                  <div className="text-3xl font-bold mt-2">{skipped}</div>
                </div>

                <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800">
                  <div className="text-zinc-400 text-sm">ERRORS</div>
                  <div className="text-3xl font-bold mt-2">{errors}</div>
                </div>

                <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800 min-w-[150px]">
                  <div className="text-zinc-400 text-sm">TIME</div>
                  <div className="text-xl font-bold mt-2 tabular-nums whitespace-nowrap">
                    {formatTime(elapsed)}
                  </div>
                </div>

                <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800">
                  <div className="text-zinc-400 text-sm">ACTIVE</div>
                  <div className="text-3xl font-bold mt-2">{active}</div>
                </div>
              </div>

              <div className="grid xl:grid-cols-2 gap-6">
                <div className="bg-zinc-900 rounded-3xl p-6 border border-zinc-800">
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="text-xl font-bold">Batch Log</h2>
                    <span className="text-sm text-zinc-400">{progress}%</span>
                  </div>

                  <div className="w-full bg-zinc-800 rounded-full h-3 mb-4">
                    <div
                      className="bg-purple-500 h-3 rounded-full transition-all"
                      style={{ width: `${progress}%` }}
                    />
                  </div>

                  <div className="bg-black rounded-2xl p-4 h-[520px] overflow-auto font-mono text-sm border border-zinc-800">
                    {normalLogs.length === 0 ? (
                      <div className="text-zinc-500">Log batch sẽ hiển thị ở đây.</div>
                    ) : (
                      normalLogs.map((log, idx) => (
                        <div
                          key={idx}
                          className={
                            log.startsWith("[DONE]")
                              ? "text-green-400"
                              : log.startsWith("[SKIP]")
                              ? "text-yellow-400"
                              : log.startsWith("[PROCESS]")
                              ? "text-blue-400"
                              : log.startsWith("[PAUSE]") ||
                                log.startsWith("[RESUME]") ||
                                log.startsWith("[CANCEL]") ||
                                log.startsWith("[CANCELLED]")
                              ? "text-orange-400"
                              : "text-white"
                          }
                        >
                          {log}
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div className="bg-zinc-900 rounded-3xl p-6 border border-red-900/60">
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="text-xl font-bold text-red-400">Error / Miss</h2>
                    <span className="text-sm text-red-400">{errorLogs.length} lỗi</span>
                  </div>

                  <div className="bg-black rounded-2xl p-4 h-[560px] overflow-auto font-mono text-sm border border-red-900/60">
                    {errorLogs.length === 0 ? (
                      <div className="text-zinc-500">Chưa có video lỗi.</div>
                    ) : (
                      errorLogs.map((log, idx) => (
                        <div key={idx} className="text-red-400 mb-1">
                          {log}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {!batchMode && (
            <>
              <AnalyzePanel analysis={analysis} />
              <TimelinePanel captions={analysis?.captions || []} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
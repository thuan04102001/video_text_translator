import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import axios from "axios";

const API = "http://127.0.0.1:8000";

function VideoIcon({ size = 32, className = "" }) {
  return <span className={className} style={{ fontSize: size, lineHeight: 1 }}>▣</span>;
}

function WandIcon({ size = 20 }) {
  return <span style={{ fontSize: size, lineHeight: 1 }}>✦</span>;
}

function PencilIcon({ size = 12 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M4 20h4.2L18.9 9.3l-4.2-4.2L4 15.8V20Zm13.7-12 1.1-1.1a1.5 1.5 0 0 0 0-2.1l-.6-.6a1.5 1.5 0 0 0-2.1 0L15 5.3 17.7 8Z"
        fill="currentColor"
      />
    </svg>
  );
}

function TrashIcon({ size = 12 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M8 4h8l.8 2H21v2H3V6h4.2L8 4Zm1 6h2v8H9v-8Zm4 0h2v8h-2v-8ZM6 10h12l-1 10H7L6 10Z"
        fill="currentColor"
      />
    </svg>
  );
}

function toMediaUrl(path) {
  if (!path) return "";
  const cleanPath = String(path).replaceAll("\\", "/");
  const marker = cleanPath.match(/(?:^|\/)(uploads|outputs)\/(.+)$/);
  if (!marker) return "";
  return `${API}/media/${marker[1]}/${encodeURI(marker[2])}`;
}

async function selectFolder() {
  const res = await axios.get(`${API}/utility/select-folder`);
  return res.data.folder_path || "";
}

async function clearUploads() {
  const res = await axios.post(`${API}/utility/clear-uploads`);
  return res.data;
}

function makeDoneFileName(filename) {
  const cleanName = String(filename || "rendered-video.mp4");
  const dotIndex = cleanName.lastIndexOf(".");

  if (dotIndex <= 0) {
    return `${cleanName}-done.mp4`;
  }

  return `${cleanName.slice(0, dotIndex)}-done.mp4`;
}

async function saveRenderedVideo(sourcePath, suggestedName) {
  const res = await axios.post(`${API}/utility/save-rendered-video`, {
    source_path: sourcePath,
    suggested_name: suggestedName,
  });
  return res.data;
}

async function analyzeVideo({ video }) {
  const formData = new FormData();
  formData.append("video", video);
  formData.append("interval_sec", "0.25");
  formData.append("max_frames", "12");
  formData.append("languages", "en");

  const res = await axios.post(`${API}/analyze/sample-frames-ocr`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });

  return {
    ...res.data,
    captions: res.data.timeline?.timelines_preview || [],
  };
}

async function uploadVideo({ video }) {
  const formData = new FormData();
  formData.append("video", video);

  const res = await axios.post(`${API}/analyze/upload`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });

  return {
    ...res.data,
    captions: [],
  };
}

async function loadFrameTemplates() {
  const res = await axios.get(`${API}/frame-templates`);
  return (res.data.templates || []).map((template) => ({
    ...template,
    thumbnailUrl: `${API}${template.thumbnail_url}`,
    foregroundUrl: template.foreground_url ? `${API}${template.foreground_url}` : "",
    foregroundLayers: normalizeForegroundLayers(template),
  }));
}

function normalizeForegroundTransform(transform = {}) {
  return {
    scale: transform.scale ?? 1,
    offsetX: transform.offset_x ?? transform.offsetX ?? 0,
    offsetY: transform.offset_y ?? transform.offsetY ?? 0,
    rotation: transform.rotation ?? 0,
  };
}

function normalizeForegroundLayers(template = {}) {
  template = template || {};

  if (Array.isArray(template.foregrounds) && template.foregrounds.length > 0) {
    return template.foregrounds.map((layer, index) => ({
      id: layer.id || `foreground_${index}`,
      asset: layer.asset || "",
      name: layer.asset || `Foreground ${index + 1}`,
      file: null,
      uploadIndex: null,
      url: layer.url ? `${API}${layer.url}` : "",
      order: Number.isFinite(Number(layer.order)) ? Number(layer.order) : index,
      size: {
        width: layer.size?.width || 1080,
        height: layer.size?.height || 1920,
      },
      transform: normalizeForegroundTransform(layer.transform),
    })).sort((a, b) => a.order - b.order).map((layer, index) => ({ ...layer, order: index }));
  }

  if (template.foreground_url || template.foregroundUrl) {
    return [
      {
        id: "foreground_0",
        asset: "foreground",
        name: "Foreground",
        file: null,
        uploadIndex: null,
        url: template.foregroundUrl || `${API}${template.foreground_url}`,
        order: 0,
        size: {
          width: template.foreground_size?.width || 1080,
          height: template.foreground_size?.height || 1920,
        },
        transform: normalizeForegroundTransform(template.foreground_transform),
      },
    ];
  }

  return [];
}

function applyForegroundOrder(layers = []) {
  return layers.map((layer, index) => ({ ...layer, order: index }));
}

function sortForegroundLayers(layers = []) {
  return [...layers]
    .sort((a, b) => {
      const orderA = Number.isFinite(Number(a.order)) ? Number(a.order) : 0;
      const orderB = Number.isFinite(Number(b.order)) ? Number(b.order) : 0;
      if (orderA !== orderB) return orderA - orderB;
      return String(a.id || "").localeCompare(String(b.id || ""));
    })
    .map((layer, index) => ({ ...layer, order: index }));
}

function appendForegroundLayersToFormData(formData, foregroundLayers = []) {
  let uploadIndex = 0;
  const foregroundsConfig = sortForegroundLayers(foregroundLayers).map((layer, index) => {
    const config = {
      id: layer.id,
      asset: layer.asset || "",
      order: index,
      transform: {
        scale: layer.transform?.scale ?? 1,
        offset_x: layer.transform?.offsetX ?? 0,
        offset_y: layer.transform?.offsetY ?? 0,
        rotation: layer.transform?.rotation ?? 0,
      },
    };

    if (layer.file) {
      config.upload_index = uploadIndex;
      formData.append("foregrounds", layer.file);
      uploadIndex += 1;
    }

    return config;
  });

  formData.append("foregrounds_config", JSON.stringify(foregroundsConfig));
}

async function createFrameTemplate({
  name,
  description,
  background,
  foregroundLayers,
  thumbnail,
  voiceIntro,
  backgroundSounds,
  outro,
  slot,
  transform,
  fit,
}) {
  const formData = new FormData();
  formData.append("name", name);
  formData.append("description", description);
  formData.append("slot_x", String(slot.x));
  formData.append("slot_y", String(slot.y));
  formData.append("slot_width", String(slot.width));
  formData.append("slot_height", String(slot.height));
  formData.append("transform_zoom", String(transform?.zoom ?? 1));
  formData.append("transform_offset_x", String(transform?.offsetX ?? 0));
  formData.append("transform_offset_y", String(transform?.offsetY ?? 0));
  formData.append("fit", fit);
  formData.append("background", background);
  appendForegroundLayersToFormData(formData, foregroundLayers);
  if (thumbnail) formData.append("thumbnail", thumbnail);
  if (voiceIntro) formData.append("voice_intro", voiceIntro);
  Array.from(backgroundSounds || []).forEach((file) => formData.append("background_sounds", file));
  if (outro) formData.append("outro", outro);

  const res = await axios.post(`${API}/frame-templates`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

async function updateFrameTemplate({
  templateId,
  name,
  description,
  background,
  foregroundLayers,
  thumbnail,
  voiceIntro,
  backgroundSounds,
  outro,
  slot,
  transform,
  fit,
}) {
  const formData = new FormData();
  formData.append("name", name);
  formData.append("description", description);
  formData.append("slot_x", String(slot.x));
  formData.append("slot_y", String(slot.y));
  formData.append("slot_width", String(slot.width));
  formData.append("slot_height", String(slot.height));
  formData.append("transform_zoom", String(transform?.zoom ?? 1));
  formData.append("transform_offset_x", String(transform?.offsetX ?? 0));
  formData.append("transform_offset_y", String(transform?.offsetY ?? 0));
  formData.append("fit", fit);
  if (background) formData.append("background", background);
  appendForegroundLayersToFormData(formData, foregroundLayers);
  if (thumbnail) formData.append("thumbnail", thumbnail);
  if (voiceIntro) formData.append("voice_intro", voiceIntro);
  Array.from(backgroundSounds || []).forEach((file) => formData.append("background_sounds", file));
  if (outro) formData.append("outro", outro);

  const res = await axios.put(`${API}/frame-templates/${encodeURIComponent(templateId)}`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

async function deleteFrameTemplate(templateId) {
  const res = await axios.delete(`${API}/frame-templates/${encodeURIComponent(templateId)}`);
  return res.data;
}

async function processVideo({
  analysis,
  outputDir,
  translationMode,
  translateCaption,
  applyFrame,
  frameTemplateId,
  frameFit,
  trimStartSeconds,
  trimEndSeconds,
}) {
  const res = await axios.post(`${API}/single/render`, {
    video_path: analysis.upload_path,
    output_dir: outputDir || null,
    source_lang: "en",
    target_lang: "vi",
    languages: ["en"],
    translation_engine: translationMode,
    translate: translateCaption,
    render_video: true,
    cleanup_temp: true,
    apply_frame: applyFrame,
    frame_template_id: applyFrame ? frameTemplateId : null,
    frame_fit: applyFrame ? frameFit : null,
    trim_start_seconds: trimStartSeconds || 0,
    trim_end_seconds: trimEndSeconds || 0,
  });

  return {
    ...res.data,
    download_url: `${toMediaUrl(res.data.output_path)}?t=${Date.now()}`,
  };
}

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

async function resetBatch() {
  const res = await axios.post(`${API}/batch/reset`);
  return res.data;
}

async function scanBatch(inputDir, outputDir) {
  const res = await axios.post(`${API}/batch/scan`, {
    input_dir: inputDir,
    output_dir: outputDir,
  });
  return res.data;
}

export default function Home() {
  const [video, setVideo] = useState(null);
  const [targetLang] = useState("vi");
  const mode = "auto";

  const [translationMode, setTranslationMode] = useState("argos");
  const [translateCaption, setTranslateCaption] = useState(true);
  const [applyFrame, setApplyFrame] = useState(false);
  const [trimStartEnabled, setTrimStartEnabled] = useState(false);
  const [trimEndEnabled, setTrimEndEnabled] = useState(false);
  const [trimStartSeconds, setTrimStartSeconds] = useState("");
  const [trimEndSeconds, setTrimEndSeconds] = useState("");
  const [frameTemplates, setFrameTemplates] = useState([]);
  const [frameTemplateId, setFrameTemplateId] = useState("");
  const [frameFit, setFrameFit] = useState("cover");
  const [frameTemplateError, setFrameTemplateError] = useState("");
  const [templateManagerOpen, setTemplateManagerOpen] = useState(false);
  const [editingFrameTemplate, setEditingFrameTemplate] = useState(null);
  const [hoveredFrameTemplateId, setHoveredFrameTemplateId] = useState("");

  const [openaiApiKey, setOpenaiApiKey] = useState("");
  const [openaiModel, setOpenaiModel] = useState("gpt-4o-mini");
  const [geminiApiKey, setGeminiApiKey] = useState("");
  const [geminiModel, setGeminiModel] = useState("gemini-2.5-flash");
  const [openrouterApiKey, setOpenrouterApiKey] = useState("");
  const [openrouterModel, setOpenrouterModel] = useState("google/gemini-2.5-flash");

  const [analysis, setAnalysis] = useState(null);
  const [renderResult, setRenderResult] = useState(null);
  const [singleStatus, setSingleStatus] = useState("San sang chon video.");
  const [singleError, setSingleError] = useState("");
  const [savingResult, setSavingResult] = useState(false);
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
    item_progress: {},
  });

  useEffect(() => {
    let active = true;

    resetBatch()
      .then((status) => {
        if (!active) return;
        setBatchStatus(status);
        setBatchRunning(Boolean(status.running));
      })
      .catch((err) => console.error(err));

    const cancelOnUnload = () => {
      navigator.sendBeacon(`${API}/batch/cancel`);
    };

    window.addEventListener("beforeunload", cancelOnUnload);

    return () => {
      active = false;
      window.removeEventListener("beforeunload", cancelOnUnload);
    };
  }, []);

  const refreshFrameTemplates = async (preferredId = "") => {
    const templates = await loadFrameTemplates();
    setFrameTemplates(templates);
    setFrameTemplateError("");
    setFrameTemplateId((current) => preferredId || current || templates[0]?.id || "");
  };

  useEffect(() => {
    let active = true;

    loadFrameTemplates()
      .then((templates) => {
        if (!active) return;
        setFrameTemplates(templates);
        setFrameTemplateError("");
        setFrameTemplateId((current) => current || templates[0]?.id || "");
      })
      .catch((err) => {
        console.error(err);
        if (!active) return;
        setFrameTemplateError("Khong load duoc frame templates.");
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!batchRunning && !batchStatus.running) return undefined;

    const timer = window.setInterval(async () => {
      try {
        const status = await getBatchStatus();
        setBatchStatus(status);
        setBatchRunning(Boolean(status.running));
      } catch (err) {
        console.error(err);
      }
    }, 1000);

    return () => window.clearInterval(timer);
  }, [batchRunning, batchStatus.running]);

  const getTrimSettings = () => ({
    trimStartSeconds: trimStartEnabled ? Math.max(0, Number(trimStartSeconds) || 0) : 0,
    trimEndSeconds: trimEndEnabled ? Math.max(0, Number(trimEndSeconds) || 0) : 0,
  });

  const hasTrimSettings = () => {
    const trim = getTrimSettings();
    return trim.trimStartSeconds > 0 || trim.trimEndSeconds > 0;
  };

  const validateTranslationKey = () => {
    if (!translateCaption && !applyFrame && !hasTrimSettings()) {
      alert("Hay bat Translate Caption, Apply Frame, hoac Trim video.");
      return false;
    }

    if (translateCaption && translationMode !== "argos") {
      alert("Backend hien tai moi ho tro Argos cho render that. Hay chon Argos Offline de test mode 1 Video.");
      return false;
    }

    if (translateCaption && translationMode === "gpt" && !openaiApiKey.trim()) {
      alert("Hay nhap OpenAI API Key khi dung GPT");
      return false;
    }

    if (translateCaption && translationMode === "gemini" && !geminiApiKey.trim()) {
      alert("Hay nhap Gemini API Key khi dung Gemini");
      return false;
    }

    if (translateCaption && translationMode === "openrouter" && !openrouterApiKey.trim()) {
      alert("Hay nhap OpenRouter API Key khi dung OpenRouter");
      return false;
    }

    if (applyFrame && !frameTemplateId) {
      alert("Hay chon frame template.");
      return false;
    }

    return true;
  };

  const handleBrowseInput = async () => {
    try {
      const folder = await selectFolder();
      if (folder) setInputDir(folder);
    } catch (err) {
      console.error(err);
      alert("Khong chon duoc folder input");
    }
  };

  const handleBrowseOutput = async () => {
    try {
      const folder = await selectFolder();
      if (folder) setOutputDir(folder);
    } catch (err) {
      console.error(err);
      alert("Khong chon duoc folder output");
    }
  };

  const handleSingleVideoChange = async (file) => {
    try {
      await clearUploads();
    } catch (err) {
      console.error(err);
      alert("Khong clear duoc folder uploads. Hay thu lai.");
      return;
    }

    setVideo(file);
    setAnalysis(null);
    setRenderResult(null);
    setSingleStatus(file ? "Da chon video. Bam Render video de bat dau." : "San sang chon video.");
    setSingleError("");
    setDownloadUrl("");
    setAnalyzedVideoName("");
  };

  const handleRender = async () => {
    if (!video) {
      alert("Hay chon video truoc");
      return;
    }

    if (!validateTranslationKey()) return;

    setRendering(true);
    setDownloadUrl("");
    setRenderResult(null);
    setSingleError("");
    setSingleStatus("Dang chuan bi render...");

    let currentAnalysis = analysis;

    try {
      if (analyzedVideoName !== video.name) {
        setAnalysis(null);
        currentAnalysis = null;
      }

      if (!currentAnalysis) {
        setSingleStatus(translateCaption ? "Dang upload video va analyze nhanh..." : "Dang upload video...");
        currentAnalysis = translateCaption
          ? await analyzeVideo({ video, mode })
          : await uploadVideo({ video });
        setAnalysis(currentAnalysis);
        setAnalyzedVideoName(video.name);
      }

      setSingleStatus("Dang render production...");
      const trim = getTrimSettings();

      const data = await processVideo({
        video,
        targetLang,
        mode,
        analysis: currentAnalysis,
        outputDir,
        translationMode,
        translateCaption,
        applyFrame,
        frameTemplateId,
        frameFit,
        trimStartSeconds: trim.trimStartSeconds,
        trimEndSeconds: trim.trimEndSeconds,
        openaiApiKey,
        openaiModel,
        geminiApiKey,
        geminiModel,
        openrouterApiKey,
        openrouterModel,
      });

      setRenderResult(data);

      const renderStatus = data.render?.status;
      const renderError = data.render?.error || data.translation?.error || "";

      setAnalysis({
        ...currentAnalysis,
        render_output_path: data.output_path,
        render_summary: data.summary,
        render_settings: data.settings,
        render_status: data.render,
        translation: data.translation,
        selected_timeline_count: data.selected_timeline_count,
        final_caption_selection: data.final_caption_selection,
        captions: data.selected_timelines || currentAnalysis.captions || [],
      });

      if (renderStatus === "ok") {
        const nextDownloadUrl = data.download_url || toMediaUrl(data.output_path);
        setDownloadUrl(nextDownloadUrl);
        setSingleStatus("Render hoan tat.");
      } else {
        setSingleError(renderError || "Render chua hoan tat.");
        setSingleStatus("Render chua hoan tat. Xem chi tiet o Analyze Result.");
      }
    } catch (err) {
      console.error(err);
      const message = err?.response?.data?.detail || "Loi render video";
      setSingleError(message);
      setSingleStatus("Render bi loi.");
      alert(message);
    }

    setRendering(false);
  };

  const handleBatchProcess = async () => {
    if (!inputDir || !outputDir) {
      alert("Chon du Folder input va Folder output");
      return;
    }

    if (!validateTranslationKey()) return;

    const safeThreads = Math.max(1, Math.min(10, Number(threads) || 1));
    const trim = getTrimSettings();

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
      logs: [],
      item_progress: {},
    });

    try {
      const started = await startBatch({
        input_dir: inputDir,
        output_dir: outputDir,
        threads: safeThreads,
        translation_mode: translationMode,
        translate: translateCaption,
        apply_frame: applyFrame,
        frame_template_id: applyFrame ? frameTemplateId : null,
        frame_fit: applyFrame ? frameFit : null,
        trim_start_seconds: trim.trimStartSeconds,
        trim_end_seconds: trim.trimEndSeconds,
      });

      setBatchStatus(started);
      setBatchRunning(Boolean(started.running));
    } catch (err) {
      console.error(err);
      setBatchStatus((current) => ({
        ...current,
        running: false,
        errors: (current.errors || 0) + 1,
        logs: [...(current.logs || []), `[ERROR] ${err?.response?.data?.detail || "Loi xu ly batch"}`],
      }));
      setBatchRunning(false);
    }
  };

  const handleSaveRenderedVideo = async () => {
    if (!renderResult?.output_path) {
      alert("Chua co file render de luu.");
      return;
    }

    setSavingResult(true);
    setSingleError("");
    setSingleStatus("Dang cho chon noi luu video...");

    try {
      const saved = await saveRenderedVideo(
        renderResult.output_path,
        makeDoneFileName(video?.name)
      );

      if (saved.success) {
        setSingleStatus(`Da luu video: ${saved.saved_path}`);
      } else if (saved.cancelled) {
        setSingleStatus("Da huy luu video.");
      } else {
        setSingleError(saved.message || "Khong luu duoc video.");
        setSingleStatus("Luu video bi loi.");
      }
    } catch (err) {
      console.error(err);
      const message = err?.response?.data?.detail || "Khong luu duoc video.";
      setSingleError(message);
      setSingleStatus("Luu video bi loi.");
      alert(message);
    }

    setSavingResult(false);
  };

  const handleBatchPause = async () => {
    try {
      const status = await pauseBatch();
      setBatchStatus(status);
      setBatchRunning(Boolean(status.running));
    } catch (err) {
      console.error(err);
      alert(err?.response?.data?.detail || "Khong pause duoc batch");
    }
  };

  const handleBatchResume = async () => {
    try {
      const status = await resumeBatch();
      setBatchStatus(status);
      setBatchRunning(Boolean(status.running));
    } catch (err) {
      console.error(err);
      alert(err?.response?.data?.detail || "Khong continue duoc batch");
    }
  };

  const handleBatchCancel = async () => {
    try {
      const status = await cancelBatch();
      setBatchStatus(status);
      setBatchRunning(Boolean(status.running));
    } catch (err) {
      console.error(err);
      alert(err?.response?.data?.detail || "Khong cancel duoc batch");
    }
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
  const itemProgress = batchStatus.item_progress ?? {};

  const normalLogs = logs.filter(
    (log) => log.startsWith("[PROCESS]") || log.startsWith("[DONE]")
  );

  const errorLogs = logs.filter(
    (log) => log.startsWith("[ERROR]") || log.startsWith("[FATAL]")
  );

  const progress =
    total > 0
      ? Math.min(100, Math.round(((done + skipped + errors) / total) * 100))
      : 0;
  const batchLogEntries = useMemo(
    () => buildLogEntries(normalLogs, errorLogs, itemProgress),
    [normalLogs, errorLogs, itemProgress]
  );
  const batchErrorEntries = useMemo(
    () => errorLogs.map((log, index) => ({ ...parseLogEntry(log), key: `${index}-${log}`, state: "error", progress: 100 })),
    [errorLogs]
  );
  const activeFrameTemplate = useMemo(
    () => frameTemplates.find((template) => template.id === (hoveredFrameTemplateId || frameTemplateId)) || frameTemplates[0],
    [frameTemplates, frameTemplateId, hoveredFrameTemplateId]
  );

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
              onChange={(e) => setGeminiApiKey(e.target.value)}
              placeholder="AIza..."
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
          </div>

          <div>
            <label className="text-sm text-zinc-400">Gemini Model</label>
            <input
              value={geminiModel}
              onChange={(e) => setGeminiModel(e.target.value)}
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
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
              onChange={(e) => setOpenrouterApiKey(e.target.value)}
              placeholder="sk-or-v1-..."
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
          </div>

          <div>
            <label className="text-sm text-zinc-400">OpenRouter Model</label>
            <input
              value={openrouterModel}
              onChange={(e) => setOpenrouterModel(e.target.value)}
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
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
              onChange={(e) => setOpenaiApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
          </div>

          <div>
            <label className="text-sm text-zinc-400">OpenAI Model</label>
            <input
              value={openaiModel}
              onChange={(e) => setOpenaiModel(e.target.value)}
              className="w-full mt-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-white outline-none"
            />
          </div>
        </div>
      )}
    </div>
  );

  const ProcessingSettings = (
    <div className="processing-options">
      <div className="processing-options-title">Processing pipeline</div>
      <div className="processing-options-grid">
        <button
          type="button"
          className={`processing-option ${translateCaption ? "active" : ""}`}
          onClick={() => setTranslateCaption((current) => !current)}
        >
          <span className="processing-option-indicator" />
          <span>
            <strong>Translate Caption</strong>
            <small>OCR, dich va sub video</small>
          </span>
        </button>
        <button
          type="button"
          className={`processing-option ${applyFrame ? "active" : ""}`}
          onClick={() => setApplyFrame((current) => !current)}
        >
          <span className="processing-option-indicator" />
          <span>
            <strong>Apply Frame</strong>
            <small>Ghep video vao template</small>
          </span>
        </button>
        <div
          role="button"
          tabIndex={0}
          className={`processing-option trim-option ${trimStartEnabled ? "active" : ""}`}
          onClick={() => setTrimStartEnabled((current) => !current)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") setTrimStartEnabled((current) => !current);
          }}
        >
          <span className="processing-option-indicator" />
          <span className="trim-option-body">
            <span>
              <strong>Cat dau video</strong>
              <small>Xu ly truoc pipeline</small>
            </span>
            <label className="trim-input-wrap" onClick={(event) => event.stopPropagation()}>
              <input
                type="number"
                min="0"
                step="0.1"
                value={trimStartSeconds}
                onChange={(event) => {
                  setTrimStartSeconds(event.target.value);
                  if (Number(event.target.value) > 0) setTrimStartEnabled(true);
                }}
                placeholder="0"
                className="trim-seconds-input"
              />
              <span>giay</span>
            </label>
          </span>
        </div>
        <div
          role="button"
          tabIndex={0}
          className={`processing-option trim-option ${trimEndEnabled ? "active" : ""}`}
          onClick={() => setTrimEndEnabled((current) => !current)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") setTrimEndEnabled((current) => !current);
          }}
        >
          <span className="processing-option-indicator" />
          <span className="trim-option-body">
            <span>
              <strong>Cat cuoi video</strong>
              <small>Cat tu phan ket</small>
            </span>
            <label className="trim-input-wrap" onClick={(event) => event.stopPropagation()}>
              <input
                type="number"
                min="0"
                step="0.1"
                value={trimEndSeconds}
                onChange={(event) => {
                  setTrimEndSeconds(event.target.value);
                  if (Number(event.target.value) > 0) setTrimEndEnabled(true);
                }}
                placeholder="0"
                className="trim-seconds-input"
              />
              <span>giay</span>
            </label>
          </span>
        </div>
      </div>
    </div>
  );

  const FrameSettings = applyFrame ? (
    <div className="frame-settings">
      <div className="frame-settings-head">
        <div>
          <div className="frame-settings-title">Video Frame Template</div>
          <div className="frame-settings-copy">Chon bo cuc dau ra cho video.</div>
        </div>
        <span className="frame-settings-badge">{frameTemplates.length} mau</span>
      </div>
      <button
        type="button"
        className="frame-manager-open"
        onClick={() => {
          setEditingFrameTemplate(null);
          setTemplateManagerOpen(true);
        }}
      >
        + Frame Template Manager
      </button>

      {frameTemplateError ? (
        <div className="frame-template-error">{frameTemplateError}</div>
      ) : (
        <div className="frame-template-library">
          <div className="frame-template-list">
            {frameTemplates.map((template) => (
              <div
                key={template.id}
                className={`frame-template-row ${frameTemplateId === template.id ? "selected" : ""}`}
                onMouseEnter={() => setHoveredFrameTemplateId(template.id)}
                onMouseLeave={() => setHoveredFrameTemplateId("")}
              >
                <button
                  type="button"
                  className="frame-template-select"
                  onClick={() => setFrameTemplateId(template.id)}
                >
                  <span>
                    <strong>{template.name}</strong>
                    <small>{template.video_slot?.width || 0} x {template.video_slot?.height || 0}</small>
                  </span>
                </button>
                <div className="frame-template-actions">
                  <button
                    type="button"
                    title="Edit template"
                    aria-label={`Edit ${template.name}`}
                    onClick={() => {
                      setEditingFrameTemplate(template);
                      setTemplateManagerOpen(true);
                    }}
                  >
                    <PencilIcon />
                  </button>
                  <button
                    type="button"
                    title="Delete template"
                    aria-label={`Delete ${template.name}`}
                    onClick={async () => {
                      const ok = window.confirm(`Xoa template "${template.name}"?`);
                      if (!ok) return;

                      try {
                        await deleteFrameTemplate(template.id);
                        const templates = await loadFrameTemplates();
                        setFrameTemplates(templates);
                        setFrameTemplateId((current) => (
                          current === template.id
                            ? templates[0]?.id || ""
                            : current
                        ));
                        setHoveredFrameTemplateId("");
                      } catch (err) {
                        console.error(err);
                        alert(err?.response?.data?.detail || "Khong xoa duoc template.");
                      }
                    }}
                  >
                    <TrashIcon />
                  </button>
                </div>
              </div>
            ))}
          </div>
          {activeFrameTemplate ? (
            <div className="frame-template-hover-preview">
              <img src={activeFrameTemplate.thumbnailUrl} alt={activeFrameTemplate.name} />
            </div>
          ) : null}
        </div>
      )}

      <div className="frame-fit-row">
        <span>Video fit</span>
        <div className="frame-fit-control">
          {["cover", "contain"].map((fit) => (
            <button
              key={fit}
              type="button"
              className={frameFit === fit ? "selected" : ""}
              onClick={() => setFrameFit(fit)}
            >
              {fit}
            </button>
          ))}
        </div>
      </div>
      {templateManagerOpen ? (
        <TemplateManager
          template={editingFrameTemplate}
          onClose={() => {
            setTemplateManagerOpen(false);
            setEditingFrameTemplate(null);
          }}
          onSaved={async (templateId) => {
            await refreshFrameTemplates(templateId);
            setTemplateManagerOpen(false);
            setEditingFrameTemplate(null);
          }}
        />
      ) : null}
    </div>
  ) : null;

  return (
    <div className="app-shell min-h-screen bg-zinc-950 text-white p-6">
      <style>{legacyCss}</style>

      <div className="max-w-7xl mx-auto grid lg:grid-cols-[430px_1fr] gap-6">
        <div className="bg-zinc-900 rounded-3xl p-8 border border-zinc-800 shadow-2xl space-y-6">
          <div>
            <div className="flex items-center gap-3 mb-4">
              <VideoIcon className="text-purple-400" size={32} />
              <h1 className="text-3xl font-bold">AI Video Text Translator</h1>
            </div>

            <p className="text-zinc-400">
              Dich caption meme nam trong nen trang, ho tro single / multi timeline.
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

          {ProcessingSettings}
          {translateCaption ? TranslationSettings : null}
          {FrameSettings}

          {batchMode ? (
            <div className="space-y-4">
              <div>
                <label className="text-sm text-zinc-400">Folder input</label>
                <div className="flex gap-2 mt-2">
                  <input
                    type="text"
                    value={inputDir}
                    readOnly
                    placeholder="Chon Folder A"
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
                    placeholder="Chon Folder B"
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
                <label className="text-sm text-zinc-400">So luong: {threads}</label>
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
                {batchRunning ? "Dang xu ly..." : "Render Batch"}
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
                onChange={handleSingleVideoChange}
              />

              <SingleStatusPanel
                status={singleStatus}
                error={singleError}
                outputPath={renderResult?.output_path}
              />

              <RenderButton loading={rendering} disabled={!video} onClick={handleRender}>
                <WandIcon size={20} />
                Render video
              </RenderButton>
            </>
          )}
        </div>

        <div className="space-y-6">
          {!batchMode && (
            <div className="grid xl:grid-cols-2 gap-6">
              <div className="bg-zinc-900 rounded-3xl p-8 border border-zinc-800 shadow-2xl">
                <h2 className="text-2xl font-bold mb-5">Preview goc</h2>
                <PreviewPanel video={video} />
              </div>

              <div className="bg-zinc-900 rounded-3xl p-8 border border-zinc-800 shadow-2xl">
                <h2 className="text-2xl font-bold mb-5">Ket qua</h2>
                <ResultPanel
                  downloadUrl={downloadUrl}
                  saving={savingResult}
                  onSave={handleSaveRenderedVideo}
                />
              </div>
            </div>
          )}

          {batchMode && (
            <div className="space-y-6">
              <div className="grid md:grid-cols-7 gap-4">
                <StatCard label="STATUS">
                  <div
                    className={`mt-3 font-bold ${
                      batchRunning
                        ? paused
                          ? "text-yellow-400"
                          : progress >= 100
                          ? "text-cyan-400"
                          : "text-green-400"
                        : batchStatus.cancel_requested
                        ? "text-orange-400"
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
                      : batchStatus.cancel_requested
                      ? "CANCELLED"
                      : progress >= 100
                      ? "FINISHED"
                      : "READY"}
                  </div>
                </StatCard>

                <StatCard label="TOTAL" value={total} />
                <StatCard label="DONE" value={done} />
                <StatCard label="SKIPPED" value={skipped} />
                <StatCard label="ERRORS" value={errors} />
                <StatCard label="TIME">
                  <div className="text-xl font-bold mt-2 tabular-nums whitespace-nowrap">
                    {formatTime(elapsed)}
                  </div>
                </StatCard>
                <StatCard label="ACTIVE" value={active} />
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

                  <div className="batch-log-pane bg-black rounded-2xl p-4 h-[520px] overflow-auto font-mono text-sm border border-zinc-800">
                    {normalLogs.length === 0 ? (
                      <div className="text-zinc-500">Log batch se hien thi o day.</div>
                    ) : (
                      batchLogEntries.map((entry) => (
                        <LogEntry key={entry.key} entry={entry} />
                      ))
                    )}
                  </div>
                </div>

                <div className="bg-zinc-900 rounded-3xl p-6 border border-red-900/60">
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="text-xl font-bold text-red-400">Error / Miss</h2>
                    <span className="text-sm text-red-400">{errorLogs.length} loi</span>
                  </div>

                  <div className="batch-log-pane bg-black rounded-2xl p-4 h-[560px] overflow-auto font-mono text-sm border border-red-900/60">
                    {errorLogs.length === 0 ? (
                      <div className="text-zinc-500">Chua co video loi.</div>
                    ) : (
                      batchErrorEntries.map((entry) => (
                        <LogEntry key={entry.key} entry={entry} />
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {!batchMode && (
            <>
              <div className="single-detail-grid">
              <AnalyzePanel analysis={analysis} status={singleStatus} error={singleError} />
                <TimelinePanel captions={analysis?.captions || []} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, children }) {
  return (
    <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800">
      <div className="text-zinc-400 text-sm">{label}</div>
      {children || <div className="text-3xl font-bold mt-2">{value}</div>}
    </div>
  );
}

function TemplateManager({ template, onClose, onSaved }) {
  const canvasRef = useRef(null);
  const interactionRef = useRef(null);
  const editing = Boolean(template?.id);
  const [name, setName] = useState(template?.name || "");
  const [description, setDescription] = useState(template?.description || "");
  const [background, setBackground] = useState(null);
  const [thumbnail, setThumbnail] = useState(null);
  const [voiceIntro, setVoiceIntro] = useState(null);
  const [backgroundSounds, setBackgroundSounds] = useState([]);
  const [outro, setOutro] = useState(null);
  const [backgroundUrl, setBackgroundUrl] = useState(template?.thumbnailUrl || "");
  const [foregroundLayers, setForegroundLayers] = useState(() => normalizeForegroundLayers(template));
  const [selectedForegroundId, setSelectedForegroundId] = useState(() => normalizeForegroundLayers(template)[0]?.id || "");
  const [draggingForegroundId, setDraggingForegroundId] = useState("");
  const [fit, setFit] = useState(template?.video_slot?.fit || "cover");
  const [editMode, setEditMode] = useState("slot");
  const [testVideo, setTestVideo] = useState(null);
  const [testVideoUrl, setTestVideoUrl] = useState("");
  const [slot, setSlot] = useState({
    x: template?.video_slot?.x ?? 360,
    y: template?.video_slot?.y ?? 350,
    width: template?.video_slot?.width ?? 680,
    height: template?.video_slot?.height ?? 1220,
  });
  const [transform, setTransform] = useState({
    zoom: template?.video_transform?.zoom ?? 1,
    offsetX: template?.video_transform?.offset_x ?? 0,
    offsetY: template?.video_transform?.offset_y ?? 0,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const orderedForegroundLayers = useMemo(() => sortForegroundLayers(foregroundLayers), [foregroundLayers]);
  const selectedForeground = orderedForegroundLayers.find((layer) => layer.id === selectedForegroundId) || orderedForegroundLayers[0] || null;

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };

    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  useEffect(() => {
    if (!background) {
      setBackgroundUrl(template?.thumbnailUrl || "");
      return undefined;
    }
    const url = URL.createObjectURL(background);
    setBackgroundUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [background, template?.thumbnailUrl]);

  useEffect(() => {
    if (!testVideo) {
      setTestVideoUrl("");
      return undefined;
    }

    const url = URL.createObjectURL(testVideo);
    setTestVideoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [testVideo]);

  useEffect(() => {
    const handlePointerMove = (event) => {
      const interaction = interactionRef.current;
      const canvas = canvasRef.current;
      if (!interaction || !canvas) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = 1080 / rect.width;
      const scaleY = 1920 / rect.height;
      const deltaX = (event.clientX - interaction.startX) * scaleX;
      const deltaY = (event.clientY - interaction.startY) * scaleY;
      const base = interaction.slot;

      if (interaction.type === "move") {
        setSlot({
          ...base,
          x: Math.max(0, Math.min(1080 - base.width, Math.round(base.x + deltaX))),
          y: Math.max(0, Math.min(1920 - base.height, Math.round(base.y + deltaY))),
        });
      } else if (interaction.type === "resize") {
        setSlot({
          ...base,
          width: Math.max(120, Math.min(1080 - base.x, Math.round(base.width + deltaX))),
          height: Math.max(160, Math.min(1920 - base.y, Math.round(base.height + deltaY))),
        });
      } else if (interaction.type === "content") {
        const transformBase = interaction.transform;
        setTransform({
          ...transformBase,
          offsetX: Math.round(transformBase.offsetX + deltaX),
          offsetY: Math.round(transformBase.offsetY + deltaY),
        });
      } else if (interaction.type === "foreground") {
        const foregroundBase = interaction.foregroundTransform;
        updateForegroundLayer(interaction.foregroundId, {
          transform: {
            ...foregroundBase,
            offsetX: Math.round(foregroundBase.offsetX + deltaX),
            offsetY: Math.round(foregroundBase.offsetY + deltaY),
          },
        });
      }
    };

    const handlePointerUp = () => {
      interactionRef.current = null;
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  }, []);

  const startInteraction = (event, type, foregroundLayer = null) => {
    event.preventDefault();
    event.stopPropagation();
    const activeForeground = foregroundLayer || selectedForeground;
    interactionRef.current = {
      type,
      startX: event.clientX,
      startY: event.clientY,
      slot,
      transform,
      foregroundId: activeForeground?.id || "",
      foregroundTransform: activeForeground?.transform || normalizeForegroundTransform(),
    };
  };

  const resetTransform = () => {
    setTransform({
      zoom: 1,
      offsetX: 0,
      offsetY: 0,
    });
  };

  const resetForegroundTransform = () => {
    if (!selectedForeground) return;

    updateForegroundLayer(selectedForeground.id, {
      transform: {
        scale: 1,
        offsetX: 0,
        offsetY: 0,
        rotation: 0,
      },
    });
  };

  const updateForegroundLayer = (layerId, patch) => {
    setForegroundLayers((current) => applyForegroundOrder(current.map((layer) => {
      if (layer.id !== layerId) return layer;

      return {
        ...layer,
        ...patch,
        transform: {
          ...layer.transform,
          ...(patch.transform || {}),
        },
        size: {
          ...layer.size,
          ...(patch.size || {}),
        },
      };
    })));
  };

  const addForegroundFiles = (files) => {
    const newLayers = Array.from(files || []).map((file) => ({
      id: `local_${Date.now()}_${Math.random().toString(16).slice(2)}`,
      asset: "",
      name: file.name,
      file,
      url: URL.createObjectURL(file),
      size: {
        width: 1080,
        height: 1920,
      },
      transform: {
        scale: 1,
        offsetX: 0,
        offsetY: 0,
        rotation: 0,
      },
    }));

    if (newLayers.length === 0) return;

    setForegroundLayers((current) => applyForegroundOrder([...sortForegroundLayers(current), ...newLayers]));
    setSelectedForegroundId(newLayers[0].id);
    setEditMode("foreground");
  };

  const removeForegroundLayer = (layerId) => {
    setForegroundLayers((current) => {
      const next = sortForegroundLayers(current).filter((layer) => layer.id !== layerId);
      const removed = current.find((layer) => layer.id === layerId);

      if (removed?.file && removed.url) {
        URL.revokeObjectURL(removed.url);
      }

      if (selectedForegroundId === layerId) {
        setSelectedForegroundId(next[0]?.id || "");
        if (next.length === 0) setEditMode("slot");
      }

      return applyForegroundOrder(next);
    });
  };

  const moveForegroundLayer = (sourceId, targetId) => {
    if (!sourceId || !targetId || sourceId === targetId) return;

    setForegroundLayers((current) => {
      const ordered = sortForegroundLayers(current);
      const sourceIndex = ordered.findIndex((layer) => layer.id === sourceId);
      const targetIndex = ordered.findIndex((layer) => layer.id === targetId);

      if (sourceIndex < 0 || targetIndex < 0) return current;

      const next = [...ordered];
      const [sourceLayer] = next.splice(sourceIndex, 1);
      next.splice(targetIndex, 0, sourceLayer);
      return applyForegroundOrder(next);
    });
  };

  const handleSave = async () => {
    if (!name.trim() || (!editing && !background)) {
      setError(editing ? "Hay nhap ten template." : "Hay nhap ten va chon background 9:16.");
      return;
    }

    setSaving(true);
    setError("");
    try {
      const result = editing
        ? await updateFrameTemplate({
            templateId: template.id,
            name,
            description,
            background,
            foregroundLayers,
            thumbnail,
            voiceIntro,
            backgroundSounds,
            outro,
            slot,
            transform,
            fit,
          })
        : await createFrameTemplate({
            name,
            description,
            background,
            foregroundLayers,
            thumbnail,
            voiceIntro,
            backgroundSounds,
            outro,
            slot,
            transform,
            fit,
          });
      await onSaved(result.template.id);
    } catch (err) {
      console.error(err);
      setError(err?.response?.data?.detail || "Khong luu duoc frame template.");
    } finally {
      setSaving(false);
    }
  };

  const isVideo = (file) => file?.type?.startsWith("video/");
  const isVideoSource = (layer) => {
    if (layer?.file) return isVideo(layer.file);
    return /\.(mp4|mov|webm)(?:$|\?)/i.test(String(layer?.url || ""));
  };

  return createPortal(
    <div className="template-manager-backdrop" role="dialog" aria-modal="true">
      <div className="template-manager-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="template-manager-header">
          <div>
            <h3>Frame Template Manager</h3>
            <p>{editing ? "Dang chinh sua template. Khong chon file moi neu chi sua slot." : "Canvas duoc khoa theo ty le 9:16, kich thuoc 1080 x 1920."}</p>
          </div>
          <button type="button" className="template-manager-close" onClick={onClose}>x</button>
        </div>

        <div className="template-manager-layout">
          <div className="template-manager-form">
            <label>
              <span>Template name</span>
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Nobody Is Perfect" />
            </label>
            <label>
              <span>Description</span>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows="3" />
            </label>
            <label>
              <span>{editing ? "Background PNG / MP4 (optional replace)" : "Background PNG / MP4"}</span>
              <input type="file" accept=".png,.jpg,.jpeg,.mp4,.mov,.webm" onChange={(event) => setBackground(event.target.files?.[0] || null)} />
            </label>
            <label>
              <span>Foreground JPG / PNG / GIF / MP4 (optional)</span>
              <input
                type="file"
                multiple
                accept=".jpg,.jpeg,.png,.gif,.webm,.mov,.mp4"
                onChange={(event) => {
                  addForegroundFiles(event.target.files);
                  event.target.value = "";
                }}
              />
            </label>
            {orderedForegroundLayers.length > 0 ? (
              <div className="foreground-layer-list">
                <div className="template-transform-head">
                  <span>Foreground layers</span>
                  <span>{orderedForegroundLayers.length} layer</span>
                </div>
                {orderedForegroundLayers.map((layer, index) => (
                  <div
                    key={layer.id}
                    role="button"
                    tabIndex={0}
                    draggable
                    className={[
                      "foreground-layer-item",
                      selectedForeground?.id === layer.id ? "selected" : "",
                      draggingForegroundId === layer.id ? "dragging" : "",
                    ].filter(Boolean).join(" ")}
                    onClick={() => {
                      setSelectedForegroundId(layer.id);
                      setEditMode("foreground");
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedForegroundId(layer.id);
                        setEditMode("foreground");
                      }
                    }}
                    onDragStart={(event) => {
                      setDraggingForegroundId(layer.id);
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("text/plain", layer.id);
                    }}
                    onDragOver={(event) => {
                      event.preventDefault();
                      event.dataTransfer.dropEffect = "move";
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      const sourceId = event.dataTransfer.getData("text/plain") || draggingForegroundId;
                      moveForegroundLayer(sourceId, layer.id);
                      setDraggingForegroundId("");
                    }}
                    onDragEnd={() => setDraggingForegroundId("")}
                  >
                    <b aria-hidden="true">drag</b>
                    <span>{index + 1}. {layer.name || layer.asset || "Foreground"}</span>
                    <small>{layer.size?.width || 0} x {layer.size?.height || 0}</small>
                    <i
                      role="button"
                      tabIndex={0}
                      draggable={false}
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        removeForegroundLayer(layer.id);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          event.stopPropagation();
                          removeForegroundLayer(layer.id);
                        }
                      }}
                    >
                      x
                    </i>
                  </div>
                ))}
              </div>
            ) : null}
            <label>
              <span>Thumbnail (optional - only template list preview)</span>
              <input type="file" accept=".png,.jpg,.jpeg" onChange={(event) => setThumbnail(event.target.files?.[0] || null)} />
            </label>
            <div className="template-media-panel">
              <div className="template-transform-head">
                <span>Template media</span>
                <span>optional</span>
              </div>
              <label>
                <span>Voice intro MP3</span>
                <input type="file" accept=".mp3,audio/mpeg" onChange={(event) => setVoiceIntro(event.target.files?.[0] || null)} />
              </label>
              <label>
                <span>Random background sounds MP3</span>
                <input
                  type="file"
                  multiple
                  accept=".mp3,audio/mpeg"
                  onChange={(event) => setBackgroundSounds(Array.from(event.target.files || []))}
                />
              </label>
              <label>
                <span>Outro MP4</span>
                <input type="file" accept=".mp4,video/mp4" onChange={(event) => setOutro(event.target.files?.[0] || null)} />
              </label>
              <div className="template-media-status">
                <span>{voiceIntro?.name || template?.voice_intro || "No intro"}</span>
                <span>{backgroundSounds.length > 0 ? `${backgroundSounds.length} sound` : `${template?.background_sounds?.length || 0} sound`}</span>
                <span>{outro?.name || template?.outro || "No outro"}</span>
              </div>
            </div>
            <div className="template-slot-values">
              <span>x {slot.x}</span>
              <span>y {slot.y}</span>
              <span>w {slot.width}</span>
              <span>h {slot.height}</span>
            </div>
            <div className="template-edit-mode">
              {[
                ["slot", "Edit Slot"],
                ["content", "Adjust Video"],
                ...(orderedForegroundLayers.length > 0 ? [["foreground", "Adjust Foreground"]] : []),
              ].map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  className={editMode === mode ? "selected" : ""}
                  onClick={() => setEditMode(mode)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="template-transform-panel">
              <div className="template-transform-head">
                <span>Video layer</span>
                <button type="button" onClick={resetTransform}>Reset</button>
              </div>
              <div className={`template-test-video ${testVideo ? "has-file" : ""}`}>
                <div className="template-test-video-copy">
                  <span>Test preview</span>
                  <strong>{testVideo ? testVideo.name : "Chua chon video"}</strong>
                </div>
                <div className="template-test-video-actions">
                  <label className="template-test-video-picker">
                    <input
                      type="file"
                      accept=".mp4,.mov,.webm,video/mp4,video/quicktime,video/webm"
                      onChange={(event) => {
                        setTestVideo(event.target.files?.[0] || null);
                        event.target.value = "";
                      }}
                    />
                    <span>{testVideo ? "Doi" : "Chon"}</span>
                  </label>
                  {testVideo ? (
                    <button
                      type="button"
                      className="template-test-video-clear"
                      onClick={() => setTestVideo(null)}
                      title="Bo video test"
                      aria-label="Bo video test"
                    >
                      x
                    </button>
                  ) : null}
                </div>
              </div>
              <label>
                <span>Zoom {Number(transform.zoom).toFixed(2)}x</span>
                <input
                  type="range"
                  min="0.5"
                  max="3"
                  step="0.01"
                  value={transform.zoom}
                  onChange={(event) => setTransform((current) => ({
                    ...current,
                    zoom: Number(event.target.value),
                  }))}
                />
              </label>
              <div className="template-slot-values template-transform-values">
                <span>move x {transform.offsetX}</span>
                <span>move y {transform.offsetY}</span>
              </div>
            </div>
            {selectedForeground ? (
              <div className="template-transform-panel">
                <div className="template-transform-head">
                  <span>Foreground layer</span>
                  <button type="button" onClick={resetForegroundTransform}>Reset</button>
                </div>
                <label>
                  <span>Scale {Number(selectedForeground.transform.scale).toFixed(2)}x</span>
                  <input
                    type="range"
                    min="0.05"
                    max="6"
                    step="0.01"
                    value={selectedForeground.transform.scale}
                    onChange={(event) => updateForegroundLayer(selectedForeground.id, {
                      transform: { scale: Number(event.target.value) },
                    })}
                  />
                </label>
                <label>
                  <span>Rotate {Number(selectedForeground.transform.rotation).toFixed(0)} deg</span>
                  <input
                    type="range"
                    min="-180"
                    max="180"
                    step="1"
                    value={selectedForeground.transform.rotation}
                    onChange={(event) => updateForegroundLayer(selectedForeground.id, {
                      transform: { rotation: Number(event.target.value) },
                    })}
                  />
                </label>
                <div className="template-slot-values template-transform-values">
                  <span>move x {selectedForeground.transform.offsetX}</span>
                  <span>move y {selectedForeground.transform.offsetY}</span>
                </div>
              </div>
            ) : null}
            <div className="frame-fit-control">
              {["cover", "contain"].map((item) => (
                <button key={item} type="button" className={fit === item ? "selected" : ""} onClick={() => setFit(item)}>
                  {item}
                </button>
              ))}
            </div>
            {error ? <div className="frame-template-error">{error}</div> : null}
            <button type="button" className="template-save" disabled={saving} onClick={handleSave}>
              {saving ? "Dang luu..." : editing ? "Cap nhat template" : "Luu template"}
            </button>
          </div>

          <div className="template-preview-wrap">
            <div className="template-preview-title">Preview 9:16</div>
            <div ref={canvasRef} className="template-preview-canvas">
              {backgroundUrl ? (
                isVideo(background)
                  ? <video src={backgroundUrl} autoPlay muted loop />
                  : <img src={backgroundUrl} alt="Background preview" />
              ) : <div className="template-preview-empty">Chon background 9:16</div>}
              <div
                className="template-video-slot"
                style={{
                  left: `${(slot.x / 1080) * 100}%`,
                  top: `${(slot.y / 1920) * 100}%`,
                  width: `${(slot.width / 1080) * 100}%`,
                  height: `${(slot.height / 1920) * 100}%`,
                }}
                onPointerDown={(event) => startInteraction(event, editMode === "content" ? "content" : "move")}
              >
                <div
                  className={`template-video-content-layer ${testVideoUrl ? "has-test-video" : ""}`}
                  style={{
                    transform: `translate(${(transform.offsetX / Math.max(1, slot.width)) * 100}%, ${(transform.offsetY / Math.max(1, slot.height)) * 100}%) scale(${transform.zoom})`,
                  }}
                >
                  {testVideoUrl ? (
                    <video
                      src={testVideoUrl}
                      autoPlay
                      muted
                      loop
                      playsInline
                      style={{ objectFit: fit }}
                    />
                  ) : (
                    "VIDEO CONTENT"
                  )}
                </div>
                <span>{testVideoUrl ? "TEST VIDEO" : editMode === "content" ? "ADJUST VIDEO" : "VIDEO SLOT"}</span>
                {editMode === "slot" ? (
                  <button type="button" aria-label="Resize video slot" onPointerDown={(event) => startInteraction(event, "resize")} />
                ) : null}
              </div>
              {orderedForegroundLayers.map((layer, index) => {
                const isSelected = selectedForeground?.id === layer.id;
                const commonProps = {
                  className: `template-foreground-layer ${isSelected ? "selected" : ""}`,
                  src: layer.url,
                  onPointerDown: (event) => {
                    setSelectedForegroundId(layer.id);
                    startInteraction(event, "foreground", layer);
                  },
                  style: {
                    left: `${50 + (layer.transform.offsetX / 1080) * 100}%`,
                    top: `${50 + (layer.transform.offsetY / 1920) * 100}%`,
                    width: `${((layer.size.width || 1080) / 1080) * 100}%`,
                    height: `${((layer.size.height || 1920) / 1920) * 100}%`,
                    transform: `translate(-50%, -50%) scale(${layer.transform.scale}) rotate(${layer.transform.rotation}deg)`,
                    zIndex: 30 + orderedForegroundLayers.length - index,
                    pointerEvents: editMode === "foreground" ? "auto" : "none",
                  },
                };

                return isVideoSource(layer) ? (
                  <video
                    key={layer.id}
                    {...commonProps}
                    autoPlay
                    muted
                    loop
                    onLoadedMetadata={(event) => {
                      updateForegroundLayer(layer.id, {
                        size: {
                          width: event.currentTarget.videoWidth || 1080,
                          height: event.currentTarget.videoHeight || 1920,
                        },
                      });
                    }}
                  />
                ) : (
                  <img
                    key={layer.id}
                    {...commonProps}
                    alt="Foreground preview"
                    onLoad={(event) => {
                      updateForegroundLayer(layer.id, {
                        size: {
                          width: event.currentTarget.naturalWidth || 1080,
                          height: event.currentTarget.naturalHeight || 1920,
                        },
                      });
                    }}
                  />
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

function UploadBox({ video, onChange }) {
  return (
    <label className="block bg-zinc-950/60 border border-dashed border-zinc-700 rounded-2xl p-6 cursor-pointer hover:bg-zinc-800 transition">
      <input
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(event) => onChange(event.target.files?.[0] || null)}
      />
      <div className="text-zinc-400 text-sm mb-2">Video input</div>
      <div className="text-white font-bold break-all">
        {video ? video.name : "Click de chon video"}
      </div>
      <div className="text-zinc-500 text-sm mt-3">
        Ho tro mp4, mov, mkv, avi, webm.
      </div>
    </label>
  );
}

function SingleStatusPanel({ status, error, outputPath }) {
  return (
    <div className={`single-status ${error ? "single-status-error" : ""}`}>
      <div>
        <div className="single-status-label">1 Video status</div>
        <div className="single-status-text">{status}</div>
        {outputPath ? <div className="single-status-path">{outputPath}</div> : null}
      </div>
    </div>
  );
}

function RenderButton({ loading, disabled, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className="w-full bg-purple-600 hover:bg-purple-500 disabled:opacity-60 px-4 py-4 rounded-xl font-bold flex items-center justify-center gap-2"
    >
      {loading ? "Dang render..." : children}
    </button>
  );
}

function PreviewPanel({ video }) {
  const [previewUrl, setPreviewUrl] = useState("");

  useEffect(() => {
    if (!video) {
      setPreviewUrl("");
      return undefined;
    }

    const nextPreviewUrl = URL.createObjectURL(video);
    setPreviewUrl(nextPreviewUrl);

    return () => {
      URL.revokeObjectURL(nextPreviewUrl);
    };
  }, [video]);

  if (!previewUrl) {
    return (
      <div className="video-stage bg-black rounded-2xl border border-zinc-800 h-[360px] flex items-center justify-center text-zinc-500">
        Preview video se hien thi o day.
      </div>
    );
  }

  return (
    <video
      key={previewUrl}
      src={previewUrl}
      controls
      preload="metadata"
      className="video-stage w-full bg-black rounded-2xl border border-zinc-800 h-[360px]"
    />
  );
}

function ResultPanel({ downloadUrl, saving, onSave }) {
  if (!downloadUrl) {
    return (
      <div className="video-stage bg-black rounded-2xl border border-zinc-800 h-[360px] flex items-center justify-center text-zinc-500">
        Video render se hien thi o day.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <video
        key={downloadUrl}
        src={downloadUrl}
        controls
        preload="metadata"
        className="video-stage w-full bg-black rounded-2xl border border-zinc-800 h-[360px]"
      />
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="w-full text-center bg-green-600 hover:bg-green-500 disabled:opacity-60 px-4 py-3 rounded-xl font-bold"
      >
        {saving ? "Dang cho chon noi luu..." : "Download video"}
      </button>
    </div>
  );
}

function AnalyzePanel({ analysis, status, error }) {
  const summary = analysis?.render_summary || analysis?.summary || {};
  const settings = analysis?.render_settings || analysis?.settings || {};
  const translation = analysis?.translation || {};
  const renderStatus = analysis?.render_status || {};
  const captionCount =
    analysis?.selected_timeline_count ??
    summary.selected_timeline_count ??
    analysis?.captions?.length ??
    0;
  const detectedSource = Array.isArray(settings.languages)
    ? settings.languages.join(", ")
    : "None";

  return (
    <div className="compact-panel bg-zinc-900 rounded-3xl p-6 border border-zinc-800">
      <h2 className="text-xl font-bold mb-3">Analyze Result</h2>
      <div className="analyze-summary bg-black rounded-2xl p-4 h-[260px] overflow-auto text-sm border border-zinc-800">
        {!analysis ? (
          <div className="text-zinc-500">Analyze se hien thi o day.</div>
        ) : (
          <div className="analyze-summary-list">
            <div className="analyze-summary-row">
              <span>Mode xử lý</span>
              <b>single</b>
            </div>
            <div className="analyze-summary-row">
              <span>Trạng thái</span>
              <b className={error ? "text-red-400" : "text-green-400"}>{status || "Ready"}</b>
            </div>
            <div className="analyze-summary-row">
              <span>Nguồn detect</span>
              <b>{detectedSource}</b>
            </div>
            <div className="analyze-summary-row">
              <span>OCR GPU</span>
              <b>{settings.gpu_resolved ? "On" : "Off"}</b>
            </div>
            <div className="analyze-summary-row">
              <span>Số caption</span>
              <b>{captionCount}</b>
            </div>
            <div className="analyze-summary-row">
              <span>Dịch</span>
              <b>{translation.status || "pending"}</b>
            </div>
            <div className="analyze-summary-row">
              <span>Render</span>
              <b>{renderStatus.status || "pending"}</b>
            </div>
            {error ? <div className="analyze-summary-error">{error}</div> : null}
          </div>
        )}
      </div>
    </div>
  );
}

function TimelinePanel({ captions }) {
  return (
    <div className="compact-panel bg-zinc-900 rounded-3xl p-6 border border-zinc-800">
      <h2 className="text-xl font-bold mb-3">Timeline Captions</h2>
      <div className="compact-log bg-black rounded-2xl p-4 h-[300px] overflow-auto font-mono text-sm border border-zinc-800">
        {captions.length === 0 ? (
          <div className="text-zinc-500">Timeline caption se hien thi o day.</div>
        ) : (
          captions.map((caption, index) => (
            <div key={`${caption.start}-${caption.end}-${index}`} className="mb-4">
              <div className="text-purple-400">
                [{Number(caption.start || 0).toFixed(2)} - {Number(caption.end || 0).toFixed(2)}]
              </div>
              <div>{caption.text || caption.normalized_text || ""}</div>
              {caption.translated_text ? (
                <div className="text-green-400">{caption.translated_text}</div>
              ) : null}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function getLogClass(log) {
  if (log.startsWith("[DONE]")) return "text-green-400";
  if (log.startsWith("[SKIP]")) return "text-yellow-400";
  if (log.startsWith("[PROCESS]")) return "text-blue-400";
  if (
    log.startsWith("[PAUSE]") ||
    log.startsWith("[RESUME]") ||
    log.startsWith("[CANCEL]") ||
    log.startsWith("[CANCELLED]")
  ) {
    return "text-orange-400";
  }
  return "text-white";
}

function parseLogEntry(log) {
  const raw = String(log || "");
  const tagMatch = raw.match(/^\[([^\]]+)\]\s*/);
  const tag = tagMatch ? tagMatch[1] : "INFO";
  const body = raw.replace(/^\[[^\]]+\]\s*/, "").trim();
  const fileMatch = body.match(/(?:error-)?[^\\/:*?"<>|\s]+\.mp4/i);
  const filename = fileMatch ? fileMatch[0] : body;
  const detail = fileMatch ? body.replace(fileMatch[0], "").replace(/^[:\s-]+/, "").trim() : "";

  return { tag, filename, detail };
}

function normalizeLogFilename(filename) {
  return String(filename || "").replace(/^error-/i, "");
}

function buildLogEntries(logs, hiddenLogs = [], itemProgress = {}) {
  const entries = [];
  const byFile = new Map();
  const hiddenKeys = new Set(
    hiddenLogs
      .map((log) => normalizeLogFilename(parseLogEntry(log).filename))
      .filter(Boolean)
  );

  logs.forEach((log, index) => {
    const parsed = parseLogEntry(log);
    const key = normalizeLogFilename(parsed.filename) || `${index}-${log}`;

    if (hiddenKeys.has(key)) return;

    const state = parsed.tag.toLowerCase();
    const existing = byFile.get(key);
    const liveProgress = itemProgress[parsed.filename] || itemProgress[key] || {};

    if (existing) {
      existing.tag = parsed.tag;
      existing.state = state;
      existing.detail = parsed.detail;
      existing.raw = log;
      existing.updatedOrder = index;
      existing.progress = state === "done" || state === "skip"
        ? 100
        : Number(liveProgress.progress || 0);
      existing.stage = liveProgress.stage || existing.stage || "";
      existing.stageProgress = liveProgress.stage_progress;
      existing.sourceStage = liveProgress.source_stage || "";
      return;
    }

    const entry = {
      ...parsed,
      key,
      raw: log,
      state,
      order: entries.length,
      updatedOrder: index,
      progress: state === "done" || state === "skip"
        ? 100
        : Number(liveProgress.progress || 0),
      stage: liveProgress.stage || "",
      stageProgress: liveProgress.stage_progress,
      sourceStage: liveProgress.source_stage || "",
    };

    byFile.set(key, entry);
    entries.push(entry);
  });

  return entries.sort(compareLogEntries);
}

function formatProgressStage(stage) {
  const labels = {
    starting: "Starting",
    analyze: "Analyze",
    frame_sampling: "Sample frames",
    sample_frames: "Sample frames",
    ocr_frames: "OCR frames",
    language_gate: "Language check",
    translate: "Translate",
    render_frames: "Render frames",
    render_video_without_audio: "Render frames",
    merge_audio: "Merge audio",
    complete: "Complete",
  };

  return labels[stage] || stage || "";
}

function compareLogEntries(left, right) {
  const priority = (entry) => entry.state === "process" ? 0 : entry.state === "done" ? 1 : 2;
  const priorityDifference = priority(left) - priority(right);

  if (priorityDifference !== 0) return priorityDifference;
  if (left.state === "process") return left.order - right.order;
  return right.updatedOrder - left.updatedOrder;
}

function LogEntry({ entry }) {
  const item = entry || {};
  const state = item.state || item.tag?.toLowerCase() || "info";
  const isProcess = state === "process";
  const isDone = state === "done";
  const isError = state === "error" || item.tag === "ERROR" || item.tag === "FATAL";
  const hasMeasuredProgress =
    item.stageProgress !== null &&
    item.stageProgress !== undefined &&
    Number.isFinite(Number(item.stageProgress));
  const progressValue = isDone || isError
    ? 100
    : hasMeasuredProgress
      ? Math.max(0, Math.min(100, Number(item.stageProgress)))
      : null;
  const progressStage = item.sourceStage || item.stage;

  return (
    <div className={`log-entry ${isDone ? "is-done" : ""} ${isProcess ? "is-process" : ""} ${isError ? "is-error" : ""}`}>
      <div className="log-entry-icon" aria-hidden="true">
        {isProcess ? <span className="log-spinner" /> : isDone ? "OK" : isError ? "!" : String(item.tag || "IN").slice(0, 2)}
      </div>

      <div className="log-entry-main">
        <div className="log-entry-file">{item.filename}</div>
        {isProcess && progressStage ? (
          <div className="log-entry-detail">{formatProgressStage(progressStage)}</div>
        ) : null}
        {item.detail ? <div className="log-entry-detail">{item.detail}</div> : null}
        {!isError ? (
          <div className={`log-entry-progress ${isProcess && progressValue === null ? "is-indeterminate" : ""}`}>
            <span style={progressValue === null ? undefined : { width: `${progressValue}%` }} />
          </div>
        ) : null}
      </div>

      <div className="log-entry-meta">
        {isProcess ? (progressValue === null ? formatProgressStage(progressStage) : `${progressValue}%`) : item.tag}
      </div>
    </div>
  );
}

const legacyCss = `
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: #09090b; color: #fff; }
button, input, select { font: inherit; }
button { cursor: pointer; border: 0; color: inherit; }
button:disabled { cursor: not-allowed; }
select, input { min-width: 0; }
video { object-fit: contain; }
.app-shell {
  position: relative;
  isolation: isolate;
  overflow-x: hidden;
  background:
    radial-gradient(circle at 12% 0%, rgba(168, 85, 247, 0.22), transparent 34%),
    radial-gradient(circle at 88% 16%, rgba(34, 211, 238, 0.12), transparent 30%),
    linear-gradient(135deg, #07070a 0%, #111116 48%, #08080b 100%);
}
.app-shell::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: -1;
  background-image:
    linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: linear-gradient(to bottom, rgba(0,0,0,0.55), transparent 72%);
}
.app-shell::after {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: -1;
  background: linear-gradient(180deg, transparent 0%, rgba(0,0,0,0.36) 100%);
}
.min-h-screen { min-height: 100vh; }
.bg-zinc-950 { background: #09090b; }
.bg-zinc-950\\/60 { background: rgba(9, 9, 11, 0.62); }
.bg-zinc-900 { background: rgba(24, 24, 27, 0.84); }
.bg-zinc-800 { background: #27272a; }
.bg-zinc-700 { background: #3f3f46; }
.bg-black { background: rgba(0, 0, 0, 0.84); }
.bg-purple-600 { background: linear-gradient(135deg, #7c3aed 0%, #a855f7 52%, #c026d3 100%); }
.bg-purple-500 { background: #a855f7; }
.bg-yellow-600 { background: #ca8a04; }
.bg-yellow-500 { background: #eab308; }
.bg-green-600 { background: #16a34a; }
.bg-green-500 { background: #22c55e; }
.bg-red-600 { background: #dc2626; }
.bg-red-500 { background: #ef4444; }
.text-white { color: #fff; }
.text-zinc-300 { color: #d4d4d8; }
.text-zinc-400 { color: #a1a1aa; }
.text-zinc-500 { color: #71717a; }
.text-purple-400 { color: #c084fc; }
.text-purple-500 { color: #a855f7; }
.text-green-400 { color: #4ade80; }
.text-yellow-400 { color: #facc15; }
.text-cyan-400 { color: #22d3ee; }
.text-red-400 { color: #f87171; }
.text-orange-400 { color: #fb923c; }
.p-4 { padding: 1rem; }
.p-5 { padding: 1.25rem; }
.p-6 { padding: 1.5rem; }
.p-8 { padding: 2rem; }
.px-4 { padding-left: 1rem; padding-right: 1rem; }
.py-3 { padding-top: 0.75rem; padding-bottom: 0.75rem; }
.py-4 { padding-top: 1rem; padding-bottom: 1rem; }
.mt-2 { margin-top: 0.5rem; }
.mt-3 { margin-top: 0.75rem; }
.mt-5 { margin-top: 1.25rem; }
.mb-1 { margin-bottom: 0.25rem; }
.mb-2 { margin-bottom: 0.5rem; }
.mb-3 { margin-bottom: 0.75rem; }
.mb-4 { margin-bottom: 1rem; }
.mb-5 { margin-bottom: 1.25rem; }
.mx-auto { margin-left: auto; margin-right: auto; }
.block { display: block; }
.hidden { display: none; }
.flex { display: flex; }
.grid { display: grid; }
.items-center { align-items: center; }
.justify-center { justify-content: center; }
.justify-between { justify-content: space-between; }
.gap-2 { gap: 0.5rem; }
.gap-3 { gap: 0.75rem; }
.gap-4 { gap: 1rem; }
.gap-6 { gap: 1.5rem; }
.space-y-3 > * + * { margin-top: 0.75rem; }
.space-y-4 > * + * { margin-top: 1rem; }
.space-y-6 > * + * { margin-top: 1.5rem; }
.grid-cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.grid-cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.w-full { width: 100%; }
.max-w-7xl { max-width: 80rem; }
.flex-1 { flex: 1 1 0%; }
.h-3 { height: 0.75rem; }
.h-\\[260px\\] { height: 260px; }
.h-\\[300px\\] { height: 300px; }
.h-\\[360px\\] { height: 360px; }
.h-\\[520px\\] { height: 520px; }
.h-\\[560px\\] { height: 560px; }
.min-w-\\[150px\\] { min-width: 150px; }
.rounded-xl { border-radius: 0.75rem; }
.rounded-2xl { border-radius: 1rem; }
.rounded-3xl { border-radius: 1.5rem; }
.rounded-full { border-radius: 9999px; }
.border { border-width: 1px; border-style: solid; }
.border-dashed { border-style: dashed; }
.border-zinc-700 { border-color: #3f3f46; }
.border-zinc-800 { border-color: #27272a; }
.border-purple-400 { border-color: #c084fc; }
.border-red-900\\/60 { border-color: rgba(127, 29, 29, 0.6); }
.shadow-2xl { box-shadow: 0 28px 90px -28px rgba(0,0,0,0.78); }
.outline-none { outline: none; }
.overflow-auto { overflow: auto; }
.font-bold { font-weight: 700; }
.font-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.text-sm { font-size: 0.875rem; line-height: 1.25rem; }
.text-xl { font-size: 1.25rem; line-height: 1.75rem; }
.text-2xl { font-size: 1.5rem; line-height: 2rem; }
.text-3xl { font-size: 1.875rem; line-height: 2.25rem; }
.text-center { text-align: center; }
.tabular-nums { font-variant-numeric: tabular-nums; }
.whitespace-nowrap { white-space: nowrap; }
.break-all { word-break: break-all; }
.cursor-pointer { cursor: pointer; }
.transition { transition: all 0.2s ease; }
.transition-all { transition: all 0.3s ease; }
.disabled\\:opacity-60:disabled { opacity: 0.6; }
.disabled\\:opacity-50:disabled { opacity: 0.5; }
.hover\\:bg-zinc-600:hover { background: #52525b; }
.hover\\:bg-purple-500:hover { background: #a855f7; }
.hover\\:bg-yellow-500:hover { background: #eab308; }
.hover\\:bg-green-500:hover { background: #22c55e; }
.hover\\:bg-red-500:hover { background: #ef4444; }
.hover\\:bg-zinc-800:hover { background: #27272a; }
a { color: inherit; text-decoration: none; }
pre { margin: 0; white-space: pre-wrap; }
.app-shell .max-w-7xl {
  animation: pageIn 0.42s ease both;
}
.app-shell .bg-zinc-900 {
  position: relative;
  backdrop-filter: blur(18px);
  border-color: rgba(255,255,255,0.075);
  box-shadow:
    0 24px 80px rgba(0,0,0,0.38),
    inset 0 1px 0 rgba(255,255,255,0.035);
}
.app-shell .bg-zinc-900::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  background: linear-gradient(135deg, rgba(255,255,255,0.055), transparent 36%, rgba(168,85,247,0.035));
}
.app-shell .rounded-3xl,
.app-shell .rounded-2xl {
  overflow: hidden;
}
.app-shell button,
.app-shell label.cursor-pointer,
.app-shell a {
  transform: translateY(0);
  transition:
    transform 0.18s ease,
    filter 0.18s ease,
    border-color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease;
}
.app-shell button:not(:disabled):hover,
.app-shell label.cursor-pointer:hover,
.app-shell a:hover {
  transform: translateY(-1px);
  filter: brightness(1.06);
}
.app-shell button:not(:disabled):active,
.app-shell label.cursor-pointer:active,
.app-shell a:active {
  transform: translateY(0) scale(0.99);
}
.app-shell .bg-purple-600 {
  box-shadow:
    0 16px 34px rgba(147, 51, 234, 0.26),
    inset 0 1px 0 rgba(255,255,255,0.16);
}
.app-shell .bg-purple-600:hover {
  box-shadow:
    0 20px 44px rgba(168, 85, 247, 0.34),
    inset 0 1px 0 rgba(255,255,255,0.22);
}
.app-shell input,
.app-shell select {
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background 0.18s ease;
}
.app-shell input:focus,
.app-shell select:focus {
  border-color: rgba(192, 132, 252, 0.72);
  box-shadow:
    0 0 0 4px rgba(168,85,247,0.12),
    0 16px 30px rgba(0,0,0,0.18);
  background: #202026;
}
.app-shell .border-dashed {
  background:
    linear-gradient(135deg, rgba(24,24,27,0.72), rgba(9,9,11,0.72)),
    repeating-linear-gradient(135deg, rgba(255,255,255,0.035) 0 1px, transparent 1px 12px);
}
.app-shell .bg-black {
  box-shadow:
    inset 0 0 0 1px rgba(255,255,255,0.025),
    inset 0 20px 50px rgba(255,255,255,0.018);
}
.app-shell video {
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04);
}
.app-shell .h-3 .bg-purple-500,
.app-shell .bg-purple-500.h-3 {
  background: linear-gradient(90deg, #7c3aed, #a855f7 52%, #22d3ee);
  box-shadow: 0 0 24px rgba(168,85,247,0.38);
}
.app-shell .font-mono {
  line-height: 1.65;
}
.app-shell .overflow-auto {
  scrollbar-width: thin;
  scrollbar-color: #52525b #09090b;
}
.app-shell .overflow-auto::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
.app-shell .overflow-auto::-webkit-scrollbar-track {
  background: #09090b;
  border-radius: 999px;
}
.app-shell .overflow-auto::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, #52525b, #3f3f46);
  border-radius: 999px;
  border: 2px solid #09090b;
}
.app-shell .overflow-auto::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, #71717a, #52525b);
}
.app-shell .batch-log-pane {
  overflow-y: scroll;
  overflow-x: auto;
  overscroll-behavior: contain;
  white-space: normal;
  word-break: normal;
  display: grid;
  align-content: start;
  gap: 0.55rem;
  background:
    radial-gradient(circle at 18% 0%, rgba(91, 124, 250, 0.08), transparent 18rem),
    linear-gradient(180deg, rgba(6,7,12,0.98), rgba(2,3,6,0.98));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
}
.app-shell .log-entry {
  min-width: 0;
  display: grid;
  grid-template-columns: 2.25rem minmax(0, 1fr) auto;
  gap: 0.75rem;
  align-items: center;
  padding: 0.7rem 0.78rem;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 0.9rem;
  background:
    linear-gradient(135deg, rgba(255,255,255,0.065), rgba(255,255,255,0.026));
  animation: logItemIn 0.22s ease both;
}
.app-shell .log-entry.is-process {
  border-color: rgba(96, 165, 250, 0.26);
  background:
    linear-gradient(135deg, rgba(37, 99, 235, 0.18), rgba(15, 23, 42, 0.35));
}
.app-shell .log-entry.is-done {
  border-color: rgba(74, 222, 128, 0.22);
  background:
    linear-gradient(135deg, rgba(34, 197, 94, 0.16), rgba(15, 23, 42, 0.34));
}
.app-shell .log-entry.is-error {
  border-color: rgba(248, 113, 113, 0.28);
  background:
    linear-gradient(135deg, rgba(127, 29, 29, 0.3), rgba(24, 10, 14, 0.72));
}
.app-shell .log-entry-icon {
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
.app-shell .is-done .log-entry-icon {
  color: #052e16;
  background: linear-gradient(135deg, #4ade80, #22c55e);
}
.app-shell .is-error .log-entry-icon {
  color: #fff1f2;
  background: linear-gradient(135deg, #ef4444, #fb7185);
}
.app-shell .log-spinner {
  width: 1rem;
  height: 1rem;
  border-radius: 999px;
  border: 2px solid rgba(147, 197, 253, 0.25);
  border-top-color: #93c5fd;
  animation: logSpin 0.72s linear infinite;
}
.app-shell .log-entry-main {
  min-width: 0;
}
.app-shell .log-entry-file {
  color: #f8fafc;
  font-weight: 850;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.app-shell .is-done .log-entry-file {
  color: #86efac;
}
.app-shell .is-error .log-entry-file {
  color: #fecaca;
  white-space: normal;
  overflow-wrap: anywhere;
}
.app-shell .log-entry-detail {
  margin-top: 0.18rem;
  color: #fca5a5;
  font-size: 0.76rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.app-shell .log-entry-progress {
  height: 0.28rem;
  margin-top: 0.52rem;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255,255,255,0.07);
}
.app-shell .log-entry-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #60a5fa, #8b5cf6);
  transition: width 0.32s cubic-bezier(.2,.8,.2,1), background 0.2s ease;
}
.app-shell .log-entry-progress.is-indeterminate span {
  width: 36%;
  animation: logIndeterminate 1.15s ease-in-out infinite;
}
.app-shell .is-done .log-entry-progress span {
  background: linear-gradient(90deg, #4ade80, #22c55e);
}
.app-shell .log-entry-meta {
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
.app-shell .is-process .log-entry-meta {
  color: #bfdbfe;
  background: rgba(59, 130, 246, 0.17);
}
.app-shell .is-done .log-entry-meta {
  color: #bbf7d0;
  background: rgba(34, 197, 94, 0.15);
}
.app-shell .is-error .log-entry-meta {
  color: #fecaca;
  background: rgba(239, 68, 68, 0.18);
}
.app-shell h1,
.app-shell h2 {
  letter-spacing: 0;
}

/* Professional visual pass */
.app-shell {
  font-family:
    "Segoe UI Variable",
    "Segoe UI",
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    sans-serif;
  color: #f7f7fb;
  background:
    radial-gradient(circle at 18% -10%, rgba(59, 130, 246, 0.16), transparent 30%),
    radial-gradient(circle at 88% 4%, rgba(168, 85, 247, 0.14), transparent 28%),
    radial-gradient(circle at 72% 92%, rgba(20, 184, 166, 0.10), transparent 36%),
    linear-gradient(135deg, #08090d 0%, #111217 44%, #0b0c10 100%);
}
.app-shell::before {
  opacity: 0.34;
  background-image:
    linear-gradient(rgba(255,255,255,0.032) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.024) 1px, transparent 1px);
  background-size: 56px 56px;
}
.app-shell .max-w-7xl {
  max-width: 92rem;
}
.app-shell > .max-w-7xl > .bg-zinc-900:first-child {
  background:
    linear-gradient(180deg, rgba(27, 28, 35, 0.92), rgba(17, 18, 24, 0.92));
  border-color: rgba(255,255,255,0.085);
  box-shadow:
    0 28px 80px rgba(0,0,0,0.42),
    inset 0 1px 0 rgba(255,255,255,0.055);
}
.app-shell .bg-zinc-900 {
  background:
    linear-gradient(180deg, rgba(24,25,31,0.88), rgba(16,17,22,0.88));
  border-color: rgba(255,255,255,0.08);
}
.app-shell .rounded-3xl {
  border-radius: 22px;
}
.app-shell .rounded-2xl {
  border-radius: 16px;
}
.app-shell .rounded-xl {
  border-radius: 12px;
}
.app-shell h1 {
  font-size: 2rem;
  line-height: 1.08;
  font-weight: 800;
  letter-spacing: -0.01em;
}
.app-shell h2 {
  font-weight: 760;
  color: #f4f4f6;
}
.app-shell p,
.app-shell label,
.app-shell .text-zinc-400,
.app-shell .text-zinc-500 {
  color: #a7abb7;
}
.app-shell .text-sm {
  font-size: 0.82rem;
}
.app-shell .text-3xl {
  font-size: 1.8rem;
}
.app-shell .text-2xl {
  font-size: 1.42rem;
}
.app-shell .text-xl {
  font-size: 1.12rem;
}
.app-shell .text-purple-400 {
  color: #9fb7ff;
}
.app-shell .bg-zinc-800,
.app-shell input,
.app-shell select {
  background: rgba(35, 37, 46, 0.88);
}
.app-shell input,
.app-shell select {
  min-height: 46px;
  color: #f7f7fb;
  border-color: rgba(255,255,255,0.095);
}
.app-shell select {
  appearance: none;
  background-image:
    linear-gradient(45deg, transparent 50%, #a7abb7 50%),
    linear-gradient(135deg, #a7abb7 50%, transparent 50%);
  background-position:
    calc(100% - 18px) 20px,
    calc(100% - 12px) 20px;
  background-size: 6px 6px, 6px 6px;
  background-repeat: no-repeat;
  padding-right: 2.5rem;
}
.app-shell input::placeholder {
  color: #727785;
}
.app-shell input:focus,
.app-shell select:focus {
  border-color: rgba(125, 162, 255, 0.78);
  box-shadow:
    0 0 0 4px rgba(96, 165, 250, 0.13),
    0 18px 36px rgba(0,0,0,0.22);
}
.app-shell .bg-purple-600 {
  background: linear-gradient(135deg, #5b7cfa 0%, #7c5cff 55%, #a855f7 100%);
  box-shadow:
    0 18px 40px rgba(91, 124, 250, 0.24),
    inset 0 1px 0 rgba(255,255,255,0.18);
}
.app-shell .hover\\:bg-purple-500:hover,
.app-shell .bg-purple-600:hover {
  background: linear-gradient(135deg, #6b8bff 0%, #8a6cff 55%, #b76aff 100%);
}
.app-shell .bg-zinc-700 {
  background: linear-gradient(180deg, #424551, #343743);
}
.app-shell .hover\\:bg-zinc-600:hover {
  background: linear-gradient(180deg, #505360, #3f4250);
}
.app-shell .bg-green-600 {
  background: linear-gradient(135deg, #1d9a65, #22c55e);
}
.app-shell .bg-yellow-600 {
  background: linear-gradient(135deg, #b98205, #d9a514);
}
.app-shell .bg-red-600 {
  background: linear-gradient(135deg, #c24141, #e05252);
}
.app-shell button {
  min-height: 46px;
  letter-spacing: 0;
}
.app-shell button:not(:disabled):hover,
.app-shell label.cursor-pointer:hover,
.app-shell a:hover {
  transform: translateY(-2px);
}
.app-shell button:not(:disabled):active,
.app-shell label.cursor-pointer:active,
.app-shell a:active {
  transform: translateY(0) scale(0.985);
}
.app-shell .border-dashed {
  border-color: rgba(125, 162, 255, 0.24);
  background:
    linear-gradient(180deg, rgba(24,26,34,0.88), rgba(15,16,22,0.88));
}
.app-shell label.cursor-pointer:hover {
  border-color: rgba(125, 162, 255, 0.46);
  box-shadow: 0 18px 42px rgba(59, 130, 246, 0.12);
}
.single-status {
  padding: 0.9rem 1rem;
  border-radius: 14px;
  border: 1px solid rgba(125, 162, 255, 0.2);
  background:
    linear-gradient(180deg, rgba(26,29,38,0.78), rgba(13,15,22,0.78));
}
.single-status-error {
  border-color: rgba(248, 113, 113, 0.35);
  background:
    linear-gradient(180deg, rgba(45,24,28,0.72), rgba(22,12,15,0.78));
}
.single-status-label {
  color: #a7abb7;
  font-size: 0.78rem;
  margin-bottom: 0.3rem;
}
.single-status-text {
  color: #f7f7fb;
  font-weight: 700;
}
.single-status-error .single-status-text {
  color: #fca5a5;
}
.single-status-path {
  color: #9fb7ff;
  font-size: 0.76rem;
  margin-top: 0.4rem;
  word-break: break-all;
}
.app-shell .bg-black {
  background:
    linear-gradient(180deg, rgba(7,8,11,0.96), rgba(2,3,5,0.96));
  border-color: rgba(255,255,255,0.07);
}
.app-shell video {
  background: #040507;
}
.app-shell .h-3 .bg-purple-500,
.app-shell .bg-purple-500.h-3 {
  background: linear-gradient(90deg, #5b7cfa 0%, #8b5cf6 58%, #14b8a6 100%);
}
.app-shell .grid.md\\:grid-cols-7 > .bg-zinc-900 {
  transition:
    transform 0.2s ease,
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}
.app-shell .grid.md\\:grid-cols-7 > .bg-zinc-900:hover {
  transform: translateY(-2px);
  border-color: rgba(125, 162, 255, 0.24);
  box-shadow: 0 20px 46px rgba(0,0,0,0.34);
}
.app-shell .font-mono {
  font-family:
    "Cascadia Mono",
    "JetBrains Mono",
    Consolas,
    ui-monospace,
    monospace;
  font-size: 0.82rem;
}
.app-shell .space-y-6 > .bg-zinc-900,
.app-shell .grid.xl\\:grid-cols-2 > .bg-zinc-900 {
  animation: panelRise 0.42s ease both;
}
.app-shell .grid.xl\\:grid-cols-2 > .bg-zinc-900:nth-child(2) {
  animation-delay: 0.05s;
}
.app-shell .video-stage {
  height: clamp(430px, 54vh, 680px);
}
.app-shell video.video-stage {
  object-fit: contain;
}
.single-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
  gap: 1rem;
}
.app-shell .compact-panel {
  padding: 1rem;
  border-radius: 16px;
}
.app-shell .compact-panel h2 {
  font-size: 0.96rem;
  margin-bottom: 0.65rem;
  color: #dfe3ec;
}
.app-shell .compact-log {
  height: 150px;
  padding: 0.85rem;
  font-size: 0.74rem;
  line-height: 1.5;
  border-radius: 12px;
}
.app-shell .compact-log pre {
  font-size: inherit;
  line-height: inherit;
}
.app-shell .analyze-summary {
  height: 150px;
  padding: 0.85rem;
  border-radius: 12px;
}
.analyze-summary-list {
  display: grid;
  gap: 0.45rem;
}
.analyze-summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  color: #a7abb7;
}
.analyze-summary-row b {
  color: #f7f7fb;
  font-weight: 750;
  text-align: right;
}
.analyze-summary-row b.text-green-400 {
  color: #4ade80;
}
.analyze-summary-row b.text-red-400 {
  color: #f87171;
}
.analyze-summary-error {
  margin-top: 0.35rem;
  padding-top: 0.45rem;
  border-top: 1px solid rgba(248, 113, 113, 0.22);
  color: #fca5a5;
  font-size: 0.78rem;
}
.processing-options {
  padding: 1rem;
  border: 1px solid rgba(139, 150, 180, 0.18);
  border-radius: 16px;
  background: rgba(6, 8, 14, 0.62);
}
.frame-settings {
  padding: 0.78rem;
  border: 1px solid rgba(139, 150, 180, 0.16);
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(12, 15, 24, 0.72), rgba(7, 9, 15, 0.62));
}
.processing-options-title,
.frame-settings-title {
  color: #f6f7fb;
  font-size: 0.88rem;
  font-weight: 800;
}
.processing-options-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
  margin-top: 0.75rem;
}
.processing-option {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  min-height: 70px;
  padding: 0.66rem;
  border: 1px solid rgba(145, 155, 184, 0.2);
  border-radius: 12px;
  background: rgba(36, 39, 50, 0.7);
  color: #d9deeb;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.2s ease;
}
.processing-option:hover {
  transform: translateY(-1px);
  border-color: rgba(127, 148, 255, 0.62);
}
.processing-option.active {
  border-color: rgba(124, 146, 255, 0.88);
  background: rgba(86, 84, 202, 0.2);
}
.processing-option-indicator {
  width: 13px;
  height: 13px;
  flex: 0 0 13px;
  border: 2px solid rgba(170, 178, 205, 0.65);
  border-radius: 50%;
}
.processing-option.active .processing-option-indicator {
  border-color: #8da2ff;
  background: #7c70ff;
  box-shadow: 0 0 0 4px rgba(124, 112, 255, 0.16);
}
.processing-option strong,
.processing-option small {
  display: block;
}
.processing-option strong {
  font-size: 0.78rem;
}
.processing-option small,
.frame-settings-copy {
  margin-top: 0.22rem;
  color: #9299aa;
  font-size: 0.68rem;
  line-height: 1.3;
}
.trim-option {
  align-items: stretch;
}
.trim-option-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.42rem;
  width: 100%;
}
.trim-input-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.38rem;
  min-height: 30px;
  padding: 0.2rem 0.32rem 0.2rem 0.44rem;
  border: 1px solid rgba(145, 155, 184, 0.18);
  border-radius: 9px;
  background: rgba(5, 8, 15, 0.42);
  color: #8f96aa;
  font-size: 0.64rem;
  font-weight: 800;
  text-transform: uppercase;
}
.processing-option.active .trim-input-wrap {
  border-color: rgba(124, 146, 255, 0.5);
  background: rgba(13, 17, 34, 0.74);
}
.trim-seconds-input {
  width: 54px;
  border: 0;
  outline: none;
  background: transparent;
  color: #f6f7fb;
  font-size: 0.82rem;
  font-weight: 900;
}
.trim-seconds-input::-webkit-outer-spin-button,
.trim-seconds-input::-webkit-inner-spin-button {
  margin: 0;
}
.frame-settings-head,
.frame-fit-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
.frame-settings-badge {
  color: #98a9ff;
  font-size: 0.68rem;
  font-weight: 800;
}
.frame-template-library {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 132px;
  gap: 0.46rem;
  margin-top: 0.58rem;
}
.frame-template-list {
  display: grid;
  align-content: start;
  gap: 0.24rem;
  max-height: 164px;
  overflow: auto;
  padding-right: 0.08rem;
  scrollbar-width: thin;
  scrollbar-color: rgba(124, 146, 255, 0.34) transparent;
}
.frame-template-list::-webkit-scrollbar {
  width: 4px;
}
.frame-template-list::-webkit-scrollbar-track {
  background: transparent;
  border-radius: 999px;
}
.frame-template-list::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(124, 146, 255, 0.58), rgba(41, 209, 196, 0.44));
  border-radius: 999px;
}
.frame-template-row {
  position: relative;
  min-height: 0;
  padding: 0.24rem 2.26rem 0.22rem 0.42rem;
  border: 1px solid rgba(145, 155, 184, 0.12);
  border-radius: 8px;
  background: rgba(18, 22, 33, 0.56);
  transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}
.frame-template-row:hover,
.frame-template-row.selected {
  border-color: rgba(124, 146, 255, 0.62);
  background: rgba(35, 42, 68, 0.62);
  box-shadow: 0 10px 24px rgba(50, 65, 170, 0.12);
}
.frame-template-row:hover {
  transform: translateY(-1px);
}
.app-shell .frame-template-select {
  display: block;
  min-width: 0;
  min-height: 0;
  height: auto;
  padding: 0;
  border: 0;
  background: transparent;
  color: #e7ebf6;
  cursor: pointer;
  text-align: left;
}
.frame-template-select span,
.frame-template-select strong,
.frame-template-select small {
  display: block;
  min-width: 0;
}
.frame-template-select strong {
  overflow: hidden;
  color: #eef2ff;
  font-size: 0.66rem;
  font-weight: 850;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.frame-template-select small {
  margin-top: 0.04rem;
  color: #7f889c;
  font-size: 0.54rem;
  font-weight: 800;
  line-height: 1.05;
}
.frame-template-actions {
  position: absolute;
  top: 50%;
  right: 0.28rem;
  display: flex;
  gap: 0.12rem;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%) translateX(4px);
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.frame-template-row:hover .frame-template-actions,
.frame-template-row:focus-within .frame-template-actions,
.frame-template-row.selected .frame-template-actions {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(-50%) translateX(0);
}
.frame-template-actions button {
  display: grid;
  place-items: center;
  width: 19px;
  height: 19px;
  min-height: 0;
  min-width: 0;
  padding: 0;
  border: 1px solid rgba(145, 155, 184, 0.14);
  border-radius: 999px;
  background: rgba(13, 17, 28, 0.82);
  color: #b8c2d8;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease, transform 0.18s ease;
}
.frame-template-actions button svg {
  width: 9.5px;
  height: 9.5px;
}
.frame-template-actions button:hover {
  border-color: rgba(124, 146, 255, 0.72);
  background: rgba(84, 92, 190, 0.24);
  color: #ffffff;
  transform: translateY(-1px);
}
.frame-template-actions button:last-child {
  border-color: rgba(248, 113, 113, 0.18);
  background: rgba(52, 16, 24, 0.72);
  color: #fca5a5;
}
.frame-template-actions button:last-child:hover {
  border-color: rgba(248, 113, 113, 0.58);
  background: rgba(127, 29, 29, 0.3);
}
.frame-template-hover-preview {
  position: sticky;
  top: 0;
  overflow: hidden;
  align-self: start;
  border: 1px solid rgba(124, 146, 255, 0.34);
  border-radius: 11px;
  background: #080a0f;
  box-shadow: 0 14px 30px rgba(36, 45, 130, 0.16);
}
.frame-template-hover-preview img {
  display: block;
  width: 100%;
  aspect-ratio: 9 / 16;
  object-fit: cover;
  object-position: top center;
}
.frame-fit-row {
  margin-top: 0.58rem;
  color: #a8afbf;
  font-size: 0.68rem;
}
.frame-fit-control {
  display: flex;
  gap: 0.12rem;
  padding: 0.14rem;
  border: 1px solid rgba(145, 155, 184, 0.14);
  border-radius: 9px;
  background: rgba(18, 21, 31, 0.62);
}
.frame-fit-control button {
  min-width: 45px;
  min-height: 0;
  padding: 0.28rem 0.42rem;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: #aeb5c6;
  cursor: pointer;
  font-size: 0.62rem;
  font-weight: 800;
  text-transform: capitalize;
}
.frame-fit-control button.selected {
  border-color: rgba(124, 146, 255, 0.9);
  background: rgba(86, 84, 202, 0.28);
  color: white;
}
.frame-template-error {
  margin-top: 0.75rem;
  color: #fca5a5;
  font-size: 0.75rem;
}
.frame-manager-open {
  width: 100%;
  margin-top: 0.68rem;
  padding: 0.54rem 0.68rem;
  border: 1px solid rgba(124, 146, 255, 0.46);
  border-radius: 9px;
  background: rgba(82, 91, 190, 0.16);
  color: #c8d2ff;
  cursor: pointer;
  font-size: 0.7rem;
  font-weight: 800;
  transition: background 0.2s ease, transform 0.2s ease;
}
.frame-manager-open:hover {
  transform: translateY(-1px);
  background: rgba(82, 91, 190, 0.28);
}
.template-manager-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: grid;
  place-items: center;
  padding: 1.5rem;
  background: rgba(2, 4, 9, 0.84);
  backdrop-filter: blur(14px);
}
.template-manager-modal {
  width: min(1220px, 100%);
  max-height: calc(100vh - 3rem);
  overflow: auto;
  padding: 1.35rem;
  border: 1px solid rgba(145, 155, 184, 0.24);
  border-radius: 16px;
  background:
    linear-gradient(145deg, rgba(20, 24, 36, 0.99), rgba(10, 13, 21, 0.99));
  box-shadow:
    0 30px 100px rgba(0, 0, 0, 0.62),
    0 0 0 1px rgba(124, 146, 255, 0.08);
  animation: panelRise 0.22s ease both;
}
.template-manager-header,
.template-manager-layout {
  display: flex;
  gap: 1.1rem;
}
.template-manager-header {
  align-items: start;
  justify-content: space-between;
  margin-bottom: 1.15rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid rgba(145, 155, 184, 0.14);
}
.template-manager-header h3 {
  margin: 0;
  color: #f7f8fc;
  font-size: 1.18rem;
}
.template-manager-header p {
  margin: 0.32rem 0 0;
  color: #9ba3b5;
  font-size: 0.76rem;
}
.template-manager-close {
  width: 34px;
  height: 34px;
  border: 1px solid rgba(145, 155, 184, 0.22);
  border-radius: 9px;
  background: #202431;
  color: white;
  cursor: pointer;
  font-weight: 900;
}
.template-manager-layout {
  align-items: start;
  justify-content: center;
  gap: 1.45rem;
}
.template-manager-form {
  flex: 1 1 560px;
  max-width: 660px;
  padding: 1rem;
  border: 1px solid rgba(145, 155, 184, 0.14);
  border-radius: 12px;
  background: rgba(8, 11, 18, 0.56);
}
.template-manager-form label {
  display: block;
  margin-bottom: 0.7rem;
}
.template-manager-form label span,
.template-preview-title {
  display: block;
  margin-bottom: 0.32rem;
  color: #aeb6c8;
  font-size: 0.72rem;
  font-weight: 800;
}
.template-manager-form input,
.template-manager-form textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 0.66rem 0.72rem;
  border: 1px solid rgba(145, 155, 184, 0.22);
  border-radius: 9px;
  background: #1b1f2a;
  color: #f5f7fb;
  outline: none;
}
.template-manager-form input:focus,
.template-manager-form textarea:focus {
  border-color: rgba(124, 146, 255, 0.82);
}
.template-slot-values {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.35rem;
  margin: 0.8rem 0;
}
.template-slot-values span {
  padding: 0.42rem;
  border-radius: 7px;
  background: #202431;
  color: #b8c3dc;
  font-size: 0.68rem;
  font-weight: 800;
  text-align: center;
}
.template-edit-mode {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.35rem;
  margin: 0.75rem 0 0.6rem;
  padding: 0.22rem;
  border: 1px solid rgba(145, 155, 184, 0.14);
  border-radius: 10px;
  background: rgba(12, 15, 24, 0.72);
}
.template-edit-mode button {
  min-height: 30px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #aeb6c8;
  cursor: pointer;
  font-size: 0.68rem;
  font-weight: 850;
}
.template-edit-mode button.selected {
  border-color: rgba(105, 212, 255, 0.64);
  background: rgba(35, 157, 218, 0.18);
  color: #eef8ff;
  box-shadow: inset 0 0 0 1px rgba(105, 212, 255, 0.08);
}
.template-transform-panel {
  margin: 0.55rem 0 0.7rem;
  padding: 0.72rem;
  border: 1px solid rgba(105, 212, 255, 0.16);
  border-radius: 11px;
  background:
    radial-gradient(circle at 12% 0%, rgba(105, 212, 255, 0.1), transparent 34%),
    rgba(10, 13, 21, 0.72);
}
.template-test-video {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.55rem;
  margin: 0.38rem 0 0.58rem;
  padding: 0.46rem 0.5rem;
  border: 1px solid rgba(124, 146, 255, 0.15);
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(20, 24, 38, 0.72), rgba(10, 13, 22, 0.88));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.035);
}
.template-test-video.has-file {
  border-color: rgba(105, 212, 255, 0.28);
  background:
    radial-gradient(circle at 100% 0%, rgba(105, 212, 255, 0.12), transparent 34%),
    linear-gradient(135deg, rgba(15, 27, 39, 0.82), rgba(10, 13, 22, 0.9));
}
.template-test-video-copy {
  min-width: 0;
  display: grid;
  gap: 0.12rem;
}
.template-test-video-copy span {
  color: #8d97ad;
  font-size: 0.6rem;
  font-weight: 850;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.template-test-video-copy strong {
  overflow: hidden;
  color: #eef4ff;
  font-size: 0.72rem;
  font-weight: 900;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.template-test-video:not(.has-file) .template-test-video-copy strong {
  color: #6f7a91;
}
.template-test-video-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.34rem;
  height: 24px;
}
.template-test-video-picker {
  display: inline-flex;
  align-items: center;
  margin: 5px;
  text-align: center;
}
.template-test-video-picker input {
  display: none;
}
.template-test-video-picker span,
.template-test-video-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  height: 24px;
  border: 1px solid rgba(124, 146, 255, 0.28);
  border-radius: 999px;
  background: rgba(31, 37, 58, 0.9);
  color: #e5eaff;
  cursor: pointer;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 0.68rem;
  font-weight: 850;
  line-height: 24px;
  transition: border-color 0.16s ease, background 0.16s ease, color 0.16s ease, transform 0.16s ease;
}
.template-test-video-picker span {
  min-width: 46px;
  padding: 0 0.68rem;
  padding-bottom: 1px;
}
.template-test-video-picker span:hover {
  border-color: rgba(105, 212, 255, 0.58);
  background: rgba(45, 54, 82, 0.96);
  color: #ffffff;
  transform: translateY(-1px);
}
.template-test-video-clear {
  width: 24px;
  padding: 0;
  border-color: rgba(255, 112, 112, 0.22);
  background: rgba(60, 20, 28, 0.78);
  color: #ffb8b8;
  font-size: 0.76rem;
  font-weight: 900;
  padding-bottom: 1px;
}
.template-test-video-clear:hover {
  border-color: rgba(255, 112, 112, 0.5);
  background: rgba(88, 26, 37, 0.92);
  color: #ffffff;
  transform: translateY(-1px);
}
.template-media-panel {
  margin: 0.55rem 0 0.75rem;
  padding: 0.72rem;
  border: 1px solid rgba(124, 146, 255, 0.18);
  border-radius: 11px;
  background:
    radial-gradient(circle at 16% 0%, rgba(139, 92, 246, 0.12), transparent 32%),
    rgba(10, 13, 21, 0.68);
}
.template-media-panel label {
  margin-bottom: 0.55rem;
}
.template-media-panel input[type="file"] {
  padding: 0.48rem 0.58rem;
  font-size: 0.72rem;
}
.template-media-status {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.35rem;
  margin-top: 0.25rem;
}
.template-media-status span {
  overflow: hidden;
  padding: 0.42rem;
  border-radius: 8px;
  background: rgba(32, 36, 49, 0.68);
  color: #aeb6c8;
  font-size: 0.64rem;
  font-weight: 850;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.template-transform-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  margin-bottom: 0.55rem;
}
.template-transform-head span {
  color: #e9eefc;
  font-size: 0.72rem;
  font-weight: 850;
}
.template-transform-head button {
  min-height: 26px;
  padding: 0 0.6rem;
  border: 1px solid rgba(145, 155, 184, 0.18);
  border-radius: 999px;
  background: rgba(32, 36, 49, 0.82);
  color: #c8d2ff;
  cursor: pointer;
  font-size: 0.64rem;
  font-weight: 850;
}
.template-transform-panel label {
  margin-bottom: 0;
}
.template-transform-panel input[type="range"] {
  height: 6px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  accent-color: #69d4ff;
  background: transparent;
}
.template-transform-values {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin: 0.55rem 0 0;
}
.template-save {
  width: 100%;
  margin-top: 0.85rem;
  padding: 0.78rem;
  border: 0;
  border-radius: 10px;
  background: linear-gradient(135deg, #5b7cfa, #8b5cf6);
  color: white;
  cursor: pointer;
  font-weight: 850;
}
.template-save:disabled {
  cursor: wait;
  opacity: 0.58;
}
.template-preview-wrap {
  flex: 0 0 390px;
  padding: 1rem;
  border: 1px solid rgba(145, 155, 184, 0.14);
  border-radius: 12px;
  background: rgba(8, 11, 18, 0.56);
}
.template-preview-canvas {
  position: relative;
  width: 390px;
  aspect-ratio: 9 / 16;
  overflow: hidden;
  border: 1px solid rgba(145, 155, 184, 0.28);
  border-radius: 10px;
  background: #080a0f;
}
.template-preview-canvas > img,
.template-preview-canvas > video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.template-preview-empty {
  display: grid;
  height: 100%;
  place-items: center;
  color: #727b90;
  font-size: 0.74rem;
  font-weight: 800;
}
.template-video-slot {
  position: absolute;
  z-index: 2;
  display: grid;
  place-items: center;
  box-sizing: border-box;
  overflow: hidden;
  border: 2px solid #69d4ff;
  background: rgba(35, 157, 218, 0.2);
  color: white;
  cursor: move;
  font-size: 0.62rem;
  font-weight: 900;
  touch-action: none;
  user-select: none;
}
.template-video-slot > span {
  position: relative;
  z-index: 2;
  padding: 0.3rem 0.42rem;
  border-radius: 999px;
  background: rgba(4, 8, 16, 0.66);
  color: #f5fbff;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.26);
}
.template-video-content-layer {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  border: 1px dashed rgba(255, 255, 255, 0.32);
  background:
    linear-gradient(135deg, rgba(124, 146, 255, 0.18), rgba(34, 211, 238, 0.16)),
    repeating-linear-gradient(45deg, rgba(255,255,255,0.08) 0 6px, transparent 6px 14px);
  color: rgba(255, 255, 255, 0.58);
  font-size: 0.56rem;
  font-weight: 900;
  letter-spacing: 0.08em;
  transform-origin: center;
  will-change: transform;
  pointer-events: none;
}
.template-video-content-layer.has-test-video {
  border: 0;
  background: #05070c;
  color: transparent;
}
.template-video-content-layer video {
  width: 100%;
  height: 100%;
  display: block;
  pointer-events: none;
}
.template-video-slot button {
  position: absolute;
  right: 5px;
  bottom: 5px;
  width: 15px;
  height: 15px;
  border: 2px solid white;
  border-radius: 50%;
  background: #69d4ff;
  cursor: nwse-resize;
}
.template-preview-canvas .template-foreground {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}
.foreground-layer-list {
  display: grid;
  gap: 0.42rem;
  padding: 0.55rem;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  background: rgba(8, 10, 18, 0.42);
  max-height: 170px;
  overflow: auto;
}
.foreground-layer-item {
  position: relative;
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 0.1rem 0.55rem;
  align-items: center;
  min-height: 42px;
  padding: 0.42rem 2.25rem 0.42rem 0.54rem;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.58);
  color: #f8fafc;
  text-align: left;
  cursor: grab;
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}
.foreground-layer-item:hover,
.foreground-layer-item.selected {
  border-color: rgba(129, 140, 248, 0.8);
  background: rgba(30, 41, 82, 0.82);
}
.foreground-layer-item.dragging {
  opacity: 0.62;
  transform: scale(0.985);
}
.foreground-layer-item b {
  grid-row: 1 / 3;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.86);
  color: rgba(191, 219, 254, 0.7);
  font-size: 0.5rem;
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: 0;
}
.foreground-layer-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.76rem;
  font-weight: 900;
}
.foreground-layer-item small {
  grid-column: 2 / 3;
  color: rgba(203, 213, 225, 0.58);
  font-size: 0.66rem;
  font-weight: 800;
}
.foreground-layer-item i {
  position: absolute;
  right: 0.45rem;
  top: 50%;
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: rgba(127, 29, 29, 0.5);
  color: #fecaca;
  font-style: normal;
  font-size: 0.66rem;
  font-weight: 900;
  transform: translateY(-50%);
}
.template-foreground-layer {
  position: absolute;
  z-index: 4;
  display: block;
  max-width: none;
  max-height: none;
  object-fit: contain;
  cursor: grab;
  transform-origin: center;
  touch-action: none;
  user-select: none;
  will-change: transform, left, top;
  filter: drop-shadow(0 12px 26px rgba(0, 0, 0, 0.28));
}
.template-foreground-layer.selected {
  outline: 2px solid rgba(96, 165, 250, 0.95);
  outline-offset: 3px;
}
.template-foreground-layer:active {
  cursor: grabbing;
}
@media (max-width: 1100px) {
  .template-manager-modal {
    width: min(940px, 100%);
  }
  .template-preview-wrap {
    flex-basis: 330px;
  }
  .template-preview-canvas {
    width: 330px;
  }
}
@media (max-width: 760px) {
  .template-manager-backdrop {
    padding: 0.7rem;
  }
  .template-manager-modal {
    max-height: calc(100vh - 1.4rem);
    padding: 0.9rem;
  }
  .template-manager-layout {
    flex-direction: column-reverse;
  }
  .template-preview-wrap {
    flex-basis: auto;
    box-sizing: border-box;
    width: 100%;
  }
  .template-preview-canvas {
    width: min(260px, 78vw);
    margin: 0 auto;
  }
}
@keyframes panelRise {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes logSpin {
  to { transform: rotate(360deg); }
}
@keyframes logIndeterminate {
  from { transform: translateX(-130%); }
  to { transform: translateX(390%); }
}
@keyframes logItemIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes pageIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (min-width: 768px) {
  .md\\:grid-cols-7 { grid-template-columns: repeat(7, minmax(0, 1fr)); }
}
@media (min-width: 1024px) {
  .lg\\:grid-cols-\\[430px_1fr\\] { grid-template-columns: 430px 1fr; }
}
@media (min-width: 1280px) {
  .xl\\:grid-cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 1279px) {
  .app-shell .video-stage {
    height: clamp(340px, 48vh, 520px);
  }
}
@media (max-width: 900px) {
  .single-detail-grid {
    grid-template-columns: 1fr;
  }
  .app-shell .compact-log {
    height: 135px;
  }
}
`;

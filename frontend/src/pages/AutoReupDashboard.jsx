import { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";

const API = "http://127.0.0.1:8000";
const ACTION_INSIGHTS_AUTO_REFRESH_MS = 60_000;

const emptyActionForm = {
  name: "",
  target_page_id: "",
  platform: "facebook",
  source_url: "",
  template_id: "",
  translate_caption: true,
  apply_frame: true,
  creative_remove_source_audio: true,
  creative_randomize_variant: true,
  creative_smart_audio: true,
  creative_audio_volume: 1.0,
  creative_custom_audio_path: "",
  content_cleaner_enabled: true,
  enabled: true,
  daily_limit: 3,
  active_from: "09:00",
  active_to: "22:30",
  min_gap_minutes: 180,
  max_gap_minutes: 250,
  schedule_mode: "smart_daily",
  manual_times: ["07:30", "12:15", "20:45"],
  smart_profile: "vn",
  jitter_minutes: 15,
  scan_interval_minutes: 60,
  notes: "",
};

const platforms = [
  { value: "facebook", label: "Facebook Page" },
  { value: "tiktok", label: "TikTok" },
  { value: "manual", label: "Manual Folder" },
];

const scheduleModes = [
  { value: "random_interval", label: "Random interval" },
  { value: "manual_times", label: "Thu cong" },
  { value: "smart_daily", label: "Thong minh" },
];

const smartProfiles = [
  { value: "vn", label: "Gio vang VN" },
  { value: "us", label: "Gio vang My" },
];

async function uploadCreativeAudio(audio) {
  const formData = new FormData();
  formData.append("audio", audio);
  const res = await axios.post(`${API}/analyze/upload-audio`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}

function timeToMinutes(value) {
  const [hour = 0, minute = 0] = String(value || "00:00").split(":").map(Number);
  return Math.max(0, Math.min(23, hour || 0)) * 60 + Math.max(0, Math.min(59, minute || 0));
}

function minutesToTime(value) {
  const minutes = ((Math.round(value) % 1440) + 1440) % 1440;
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function formatInsightValue(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${number.toLocaleString()}${suffix}`;
}

function formatInsightTrend(trend) {
  if (!trend || trend.percent === null || trend.percent === undefined) return "--";
  const number = Number(trend.percent);
  if (!Number.isFinite(number)) return "--";
  if (number === 0) return "0%";
  return `${number > 0 ? "+" : ""}${number.toLocaleString()}%`;
}

function getActionViewScore(action) {
  const value = Number(action?.page_insights?.total?.views ?? 0);
  return Number.isFinite(value) ? value : 0;
}

function getActionErrorPriority(action) {
  const scanStatus = String(action?.scan_status || "").toLowerCase();
  const errorCount = Number(action?.progress_errors ?? action?.errors ?? 0);
  return Boolean(
    action?.last_scan_error
    || errorCount > 0
    || ["error", "login_required", "checkpoint_required", "facebook_checkpoint_required"].includes(scanStatus)
  );
}

function buildManualTimes(limit, current = [], activeFrom = "07:00", activeTo = "23:00") {
  const count = Math.max(1, Math.min(50, Number(limit || 1)));
  const existing = Array.isArray(current) ? current.filter(Boolean) : [];
  const start = timeToMinutes(activeFrom);
  const rawEnd = timeToMinutes(activeTo);
  const end = rawEnd <= start ? rawEnd + 1440 : rawEnd;
  const span = Math.max(count, end - start);
  return Array.from({ length: count }, (_, index) => (
    existing[index] || minutesToTime(start + ((index + 0.5) * span) / count)
  ));
}

function smartPreviewTimes(form) {
  const count = Math.max(1, Math.min(12, Number(form.daily_limit || 1)));
  const start = timeToMinutes(form.active_from);
  const rawEnd = timeToMinutes(form.active_to);
  const end = rawEnd <= start ? rawEnd + 1440 : rawEnd;
  const span = Math.max(count, end - start);
  const golden = form.smart_profile === "us"
    ? [[6 * 60, 10 * 60], [10 * 60, 13 * 60], [20 * 60, 23 * 60]]
    : [[7 * 60, 9 * 60], [11 * 60, 13 * 60], [16 * 60 + 30, 18 * 60 + 30], [19 * 60 + 30, 22 * 60 + 30]];
  const centers = golden
    .flatMap(([from, to]) => [[from, to], [from + 1440, to + 1440]])
    .map(([from, to]) => [Math.max(start, from), Math.min(end, to)])
    .filter(([from, to]) => to > from)
    .map(([from, to]) => (from + to) / 2);

  return Array.from({ length: count }, (_, index) => {
    let base = start + ((index + 0.5) * span) / count;
    if (centers.length) {
      const nearest = centers.reduce((best, item) => (
        Math.abs(item - base) < Math.abs(best - base) ? item : best
      ), centers[0]);
      base += (nearest - base) * 0.55;
    }
    return minutesToTime(base);
  }).sort();
}

function isUsableDestinationPage(page) {
  return Boolean(page?.has_page_access_token) && page?.page_token_status === "valid";
}

function actionNeedsInsightRefresh(action) {
  const insights = action.page_insights || {};
  if (!action.target_page_id) return false;
  if (!insights.total?.fetched_at) return true;
  return Boolean(
    insights.total?.metrics?.views
    && !["views", "page_videos.views"].includes(insights.total.metrics.views)
  );
}

function Glyph({ name }) {
  return <span className={`auto-reup-glyph auto-reup-glyph-${name}`} aria-hidden="true" />;
}

export default function AutoReupDashboard() {
  const [summary, setSummary] = useState({});
  const [pages, setPages] = useState([]);
  const [actions, setActions] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [actionForm, setActionForm] = useState(emptyActionForm);
  const [editingAction, setEditingAction] = useState(null);
  const [isActionModalOpen, setActionModalOpen] = useState(false);
  const [contentInput, setContentInput] = useState("");
  const [cleanResult, setCleanResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [metaToken, setMetaToken] = useState("");
  const [metaTokens, setMetaTokens] = useState([]);
  const [selectedMetaTokenId, setSelectedMetaTokenId] = useState("");
  const [metaTokenLabel, setMetaTokenLabel] = useState("");
  const [metaCredentialType, setMetaCredentialType] = useState("system_user");
  const [metaBusinessIds, setMetaBusinessIds] = useState("");
  const [metaAutoSync, setMetaAutoSync] = useState(true);
  const [metaCheckInterval, setMetaCheckInterval] = useState(360);
  const [metaBusy, setMetaBusy] = useState(false);
  const [metaResult, setMetaResult] = useState(null);
  const [pageTokenChecks, setPageTokenChecks] = useState({});
  const [actionScans, setActionScans] = useState({});
  const [actionAudioFile, setActionAudioFile] = useState(null);
  const [actionAudioUpload, setActionAudioUpload] = useState(null);
  const [detailActionId, setDetailActionId] = useState("");
  const [actionDetail, setActionDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [runtimeClock, setRuntimeClock] = useState(Date.now());
  const [insightRefreshes, setInsightRefreshes] = useState({});
  const [metaGuideOpen, setMetaGuideOpen] = useState(false);
  const [actionSortOrder, setActionSortOrder] = useState("views_desc");
  const refreshedInsightPagesRef = useRef(new Set());
  const lastInsightAutoRefreshRef = useRef(0);
  const insightAutoRefreshRunningRef = useRef(false);

  const activeActions = useMemo(
    () => actions.filter((action) => action.enabled),
    [actions]
  );

  const queuedJobs = useMemo(
    () =>
      jobs
        .filter((job) =>
          ["processing", "publishing", "ready", "queued"].includes(job.status)
        )
        .slice(0, 8),
    [jobs]
  );

  const sortedActions = useMemo(() => {
    const direction = actionSortOrder === "views_asc" ? 1 : -1;
    return [...actions].sort((left, right) => {
      const leftHasError = getActionErrorPriority(left);
      const rightHasError = getActionErrorPriority(right);
      if (leftHasError !== rightHasError) return leftHasError ? -1 : 1;

      const byViews = (getActionViewScore(left) - getActionViewScore(right)) * direction;
      if (byViews !== 0) return byViews;

      return String(left.name || "").localeCompare(String(right.name || ""));
    });
  }, [actions, actionSortOrder]);

  const refreshActionInsights = async (action, options = {}) => {
    const pageId = action.target_page_id;
    if (!pageId) return;
    if (!options.force) {
      if (refreshedInsightPagesRef.current.has(pageId)) return;
      if (!actionNeedsInsightRefresh(action)) return;
    }
    refreshedInsightPagesRef.current.add(pageId);
    setInsightRefreshes((current) => ({ ...current, [pageId]: true }));
    try {
      await axios.post(`${API}/auto-reup/pages/${pageId}/insights/refresh`);
      const actionsRes = await axios.get(`${API}/auto-reup/actions`);
      setActions(actionsRes.data.actions || []);
    } catch (error) {
      console.error(error);
      if (options.force) {
        alert(error.response?.data?.detail || "Khong tai duoc thong so page tu Meta.");
      }
    } finally {
      setInsightRefreshes((current) => {
        const next = { ...current };
        delete next[pageId];
        return next;
      });
    }
  };

  const refreshInsightsForActions = (nextActions, options = {}) => {
    const seenPageIds = new Set();
    const refreshTasks = nextActions
      .filter((action) => {
        if (!action.enabled || !action.target_page_id) return false;
        if (seenPageIds.has(action.target_page_id)) return false;
        seenPageIds.add(action.target_page_id);
        return options.force || actionNeedsInsightRefresh(action);
      })
      .map((action) => refreshActionInsights(action, { force: Boolean(options.force) }));
    return Promise.allSettled(refreshTasks).then((results) => {
      results.forEach((result) => {
        if (result.status === "rejected") console.error(result.reason);
      });
    });
  };

  const maybeAutoRefreshInsights = (nextActions) => {
    const now = Date.now();
    if (insightAutoRefreshRunningRef.current) return;
    if (now - lastInsightAutoRefreshRef.current < ACTION_INSIGHTS_AUTO_REFRESH_MS) return;

    const refreshableActions = nextActions.filter((action) => action.enabled && action.target_page_id);
    if (!refreshableActions.length) return;

    lastInsightAutoRefreshRef.current = now;
    insightAutoRefreshRunningRef.current = true;
    Promise.resolve(refreshInsightsForActions(refreshableActions, { force: true }))
      .finally(() => {
        insightAutoRefreshRunningRef.current = false;
      });
  };

  const loadData = async () => {
    const [summaryRes, pagesRes, actionsRes, jobsRes, metaTokensRes, templatesRes] = await Promise.all([
      axios.get(`${API}/auto-reup/summary`),
      axios.get(`${API}/auto-reup/pages`),
      axios.get(`${API}/auto-reup/actions`),
      axios.get(`${API}/auto-reup/jobs`, { params: { limit: 80 } }),
      axios.get(`${API}/auto-reup/meta/tokens`),
      axios.get(`${API}/frame-templates`),
    ]);

    setSummary(summaryRes.data || {});
    setPages(pagesRes.data.pages || []);
    const nextActions = actionsRes.data.actions || [];
    setActions(nextActions);
    setJobs(jobsRes.data.jobs || []);
    setMetaTokens(metaTokensRes.data.tokens || []);
    setTemplates(templatesRes.data.templates || []);
    lastInsightAutoRefreshRef.current = Date.now();
    refreshInsightsForActions(nextActions, { force: true });
  };

  const loadRuntimeData = async () => {
    const [summaryRes, actionsRes, jobsRes] = await Promise.all([
      axios.get(`${API}/auto-reup/summary`),
      axios.get(`${API}/auto-reup/actions`),
      axios.get(`${API}/auto-reup/jobs`, { params: { limit: 80 } }),
    ]);
    setSummary(summaryRes.data || {});
    const nextActions = actionsRes.data.actions || [];
    setActions(nextActions);
    setJobs(jobsRes.data.jobs || []);
    maybeAutoRefreshInsights(nextActions);
  };

  useEffect(() => {
    loadData().catch((error) => console.error(error));
    const timer = window.setInterval(() => {
      loadRuntimeData().catch((error) => console.error(error));
    }, 4000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!detailActionId) return undefined;
    let active = true;

    const loadDetail = async (showLoading = false) => {
      if (showLoading) setDetailLoading(true);
      try {
        const res = await axios.get(
          `${API}/auto-reup/actions/${detailActionId}/runtime`
        );
        if (active) setActionDetail(res.data || null);
      } catch (error) {
        console.error(error);
        if (active) {
          setActionDetail({
            error: error.response?.data?.detail || "Khong tai duoc runtime action.",
          });
        }
      } finally {
        if (active && showLoading) setDetailLoading(false);
      }
    };

    loadDetail(true);
    const dataTimer = window.setInterval(() => loadDetail(false), 2000);
    const clockTimer = window.setInterval(() => setRuntimeClock(Date.now()), 1000);
    return () => {
      active = false;
      window.clearInterval(dataTimer);
      window.clearInterval(clockTimer);
    };
  }, [detailActionId]);

  const openCreateAction = () => {
    const firstPage = pages.find(isUsableDestinationPage) || null;
    setEditingAction(null);
    setActionForm({
      ...emptyActionForm,
      name: firstPage?.name || "",
      target_page_id: firstPage?.id || "",
      template_id: templates[0]?.id || "",
    });
    setContentInput("");
    setCleanResult(null);
    setActionAudioFile(null);
    setActionAudioUpload(null);
    setActionModalOpen(true);
  };

  const openEditAction = (action) => {
    setEditingAction(action);
    setActionForm({
      name: action.name || "",
      target_page_id: action.target_page_id || "",
      platform: action.platform || "facebook",
      source_url: action.source_url || "",
      template_id: action.template_id || "",
      translate_caption: Boolean(action.translate_caption),
      apply_frame: Boolean(action.apply_frame),
      creative_remove_source_audio: action.creative_remove_source_audio !== false,
      creative_randomize_variant: action.creative_randomize_variant !== false,
      creative_smart_audio: action.creative_smart_audio !== false,
      creative_audio_volume: Number(action.creative_audio_volume || 1),
      creative_custom_audio_path: action.creative_custom_audio_path || "",
      content_cleaner_enabled: Boolean(action.content_cleaner_enabled),
      enabled: Boolean(action.enabled),
      daily_limit: Number(action.daily_limit || 3),
      active_from: action.active_from || "09:00",
      active_to: action.active_to || "22:30",
      min_gap_minutes: Number(action.min_gap_minutes || 180),
      max_gap_minutes: Number(action.max_gap_minutes || action.min_gap_minutes || 250),
      schedule_mode: action.schedule_mode || "random_interval",
      manual_times: buildManualTimes(
        Number(action.daily_limit || 3),
        action.manual_times || [],
        action.active_from || "09:00",
        action.active_to || "22:30"
      ),
      smart_profile: action.smart_profile || "vn",
      jitter_minutes: Number(action.jitter_minutes ?? 15),
      scan_interval_minutes: Number(action.scan_interval_minutes || 60),
      notes: action.notes || "",
    });
    setContentInput("");
    setCleanResult(null);
    setActionAudioFile(null);
    setActionAudioUpload(null);
    setActionModalOpen(true);
  };

  const closeActionModal = () => {
    setActionModalOpen(false);
    setEditingAction(null);
    setActionForm(emptyActionForm);
    setActionAudioFile(null);
    setActionAudioUpload(null);
  };

  const openActionDetail = (action) => {
    setActionDetail(null);
    setDetailActionId(action.id);
  };

  const closeActionDetail = () => {
    setDetailActionId("");
    setActionDetail(null);
  };

  const cleanContent = async () => {
    if (!contentInput.trim()) {
      setCleanResult(null);
      return;
    }

    setBusy(true);
    try {
      const res = await axios.post(`${API}/auto-reup/content/clean`, {
        content: contentInput,
      });
      setCleanResult(res.data);
    } catch (error) {
      console.error(error);
      alert("Khong clean duoc content.");
    } finally {
      setBusy(false);
    }
  };

  const ensureActionAudioUpload = async () => {
    if (!actionForm.apply_frame || !actionForm.creative_smart_audio || !actionAudioFile) {
      return actionAudioUpload;
    }

    if (
      actionAudioUpload?.path
      && actionAudioUpload?.name === actionAudioFile.name
      && actionAudioUpload?.size === actionAudioFile.size
      && actionAudioUpload?.lastModified === actionAudioFile.lastModified
    ) {
      return actionAudioUpload;
    }

    const uploaded = await uploadCreativeAudio(actionAudioFile);
    const nextUpload = {
      path: uploaded.upload_path,
      name: actionAudioFile.name,
      size: actionAudioFile.size,
      lastModified: actionAudioFile.lastModified,
    };
    setActionAudioUpload(nextUpload);
    return nextUpload;
  };

  const saveAction = async (event) => {
    event.preventDefault();

    if (!actionForm.target_page_id) {
      alert("Chon fanpage dich truoc.");
      return;
    }

    if (!actionForm.source_url.trim()) {
      alert("Nhap link nguon reup truoc.");
      return;
    }

    setBusy(true);
    try {
      if (actionForm.apply_frame && !actionForm.template_id) {
        alert("Chon frame template truoc khi bat Creative Frame.");
        return;
      }

      if (Number(actionForm.max_gap_minutes) < Number(actionForm.min_gap_minutes)) {
        alert("Khoang dang toi da phai lon hon hoac bang khoang toi thieu.");
        return;
      }

      if (actionForm.schedule_mode === "manual_times") {
        const times = buildManualTimes(
          actionForm.daily_limit,
          actionForm.manual_times,
          actionForm.active_from,
          actionForm.active_to
        );
        if (new Set(times).size !== times.length) {
          alert("Cac moc gio thu cong khong duoc trung nhau.");
          return;
        }
      }

      const targetPage = pages.find((page) => page.id === actionForm.target_page_id);
      const actionAudio = await ensureActionAudioUpload();
      const payload = {
        ...actionForm,
        name: targetPage?.name || actionForm.name,
        creative_custom_audio_path: actionAudio?.path || actionForm.creative_custom_audio_path || "",
        creative_audio_volume: Number(actionForm.creative_audio_volume || 1),
        daily_limit: Number(actionForm.daily_limit || 1),
        min_gap_minutes: Number(actionForm.min_gap_minutes || 15),
        max_gap_minutes: Number(actionForm.max_gap_minutes || actionForm.min_gap_minutes || 15),
        jitter_minutes: Number(actionForm.jitter_minutes ?? 15),
        manual_times: buildManualTimes(
          actionForm.daily_limit,
          actionForm.manual_times,
          actionForm.active_from,
          actionForm.active_to
        ),
      };

      if (editingAction) {
        await axios.put(`${API}/auto-reup/actions/${editingAction.id}`, payload);
      } else {
        await axios.post(`${API}/auto-reup/actions`, payload);
      }

      await loadData();
      closeActionModal();
    } catch (error) {
      console.error(error);
      alert(error.response?.data?.detail || "Khong luu duoc action.");
    } finally {
      setBusy(false);
    }
  };

  const toggleAction = async (action) => {
    setBusy(true);
    try {
      await axios.put(`${API}/auto-reup/actions/${action.id}`, {
        enabled: !action.enabled,
      });
      await loadData();
    } catch (error) {
      console.error(error);
      alert("Khong cap nhat duoc action.");
    } finally {
      setBusy(false);
    }
  };

  const scanAction = async (action) => {
    setActionScans((current) => ({ ...current, [action.id]: true }));
    try {
      await axios.post(`${API}/auto-reup/actions/${action.id}/scan`);
      await loadRuntimeData();
    } catch (error) {
      console.error(error);
      alert(error.response?.data?.detail || "Khong khoi dong duoc quet nguon.");
    } finally {
      setActionScans((current) => {
        const next = { ...current };
        delete next[action.id];
        return next;
      });
    }
  };

  const openFacebookLogin = async () => {
    setBusy(true);
    try {
      await axios.post(`${API}/auto-reup/facebook/login-browser`);
    } catch (error) {
      console.error(error);
      alert(error.response?.data?.detail || "Khong mo duoc Chrome dang nhap Facebook.");
    } finally {
      setBusy(false);
    }
  };

  const removeAction = async (action) => {
    if (!window.confirm(`Xoa action "${action.name}"?`)) return;
    setBusy(true);
    try {
      await axios.delete(`${API}/auto-reup/actions/${action.id}`);
      await loadData();
    } catch (error) {
      console.error(error);
      alert("Khong xoa duoc action.");
    } finally {
      setBusy(false);
    }
  };

  const resetMetaTokenForm = () => {
    setSelectedMetaTokenId("");
    setMetaToken("");
    setMetaTokenLabel("");
    setMetaCredentialType("system_user");
    setMetaBusinessIds("");
    setMetaAutoSync(true);
    setMetaCheckInterval(360);
    setMetaResult(null);
  };

  const selectMetaToken = (token) => {
    setSelectedMetaTokenId(token.id);
    setMetaToken("");
    setMetaTokenLabel(token.label || "");
    setMetaCredentialType(token.credential_type || "user_oauth");
    setMetaBusinessIds((token.business_ids || []).join(", "));
    setMetaAutoSync(Boolean(token.auto_sync));
    setMetaCheckInterval(Number(token.check_interval_minutes || 360));
    setMetaResult(null);
  };

  const saveMetaToken = async () => {
    const token = metaToken.trim();
    if (!selectedMetaTokenId && !token) {
      alert("Nhap Meta user access token truoc.");
      return;
    }
    if (metaCredentialType === "system_user" && !metaBusinessIds.trim()) {
      alert("System User can it nhat mot Business ID.");
      return;
    }

    setMetaBusy(true);
    setMetaResult(null);
    try {
      const payload = {
        label: metaTokenLabel.trim(),
        credential_type: metaCredentialType,
        business_ids: metaBusinessIds
          .split(/[\s,;]+/)
          .map((value) => value.trim())
          .filter(Boolean),
        auto_sync: metaAutoSync,
        check_interval_minutes: Number(metaCheckInterval || 360),
        exchange_long_lived: true,
      };
      if (token) payload.access_token = token;

      const res = selectedMetaTokenId
        ? await axios.put(`${API}/auto-reup/meta/tokens/${selectedMetaTokenId}`, payload)
        : await axios.post(`${API}/auto-reup/meta/tokens`, payload);
      setMetaResult(res.data.sync || { token: res.data.token });
      setMetaToken("");
      await loadData();
      if (!selectedMetaTokenId && res.data.token?.id) {
        setSelectedMetaTokenId(res.data.token.id);
      }
    } catch (error) {
      console.error(error);
      setMetaResult({
        error: error.response?.data?.detail || "Khong luu duoc Meta token.",
      });
    } finally {
      setMetaBusy(false);
    }
  };

  const syncMetaToken = async (tokenId) => {
    setMetaBusy(true);
    setMetaResult(null);
    try {
      const res = await axios.post(`${API}/auto-reup/meta/tokens/${tokenId}/sync`);
      setMetaResult(res.data);
      await loadData();
    } catch (error) {
      console.error(error);
      setMetaResult({
        error: error.response?.data?.detail || "Khong kiem tra duoc Meta token.",
      });
      await loadData();
    } finally {
      setMetaBusy(false);
    }
  };

  const syncAllMetaTokens = async () => {
    setMetaBusy(true);
    setMetaResult(null);
    try {
      const res = await axios.post(`${API}/auto-reup/meta/tokens/sync-all`);
      const results = res.data.results || [];
      setMetaResult({
        sync_all: true,
        results,
        count: results.reduce((sum, item) => sum + Number(item.count || 0), 0),
      });
      await loadData();
    } catch (error) {
      console.error(error);
      setMetaResult({
        error: error.response?.data?.detail || "Khong refresh duoc cac Meta token.",
      });
    } finally {
      setMetaBusy(false);
    }
  };

  const removeMetaToken = async (tokenAccount) => {
    if (!window.confirm(
      `Remove token "${tokenAccount.label}"?\n\n`
      + "Tat ca Page chi thuoc tai khoan nay se bi xoa. "
      + "Page shared voi token khac va Page tao thu cong van duoc giu."
    )) {
      return;
    }
    setMetaBusy(true);
    try {
      await axios.delete(`${API}/auto-reup/meta/tokens/${tokenAccount.id}`);
      if (selectedMetaTokenId === tokenAccount.id) resetMetaTokenForm();
      await loadData();
    } catch (error) {
      console.error(error);
      setMetaResult({
        error: error.response?.data?.detail || "Khong remove duoc Meta token.",
      });
    } finally {
      setMetaBusy(false);
    }
  };

  const checkPageToken = async (page, tokenId) => {
    const checkKey = `${page.id}:${tokenId || "primary"}`;
    setPageTokenChecks((current) => ({ ...current, [checkKey]: true }));
    try {
      const res = await axios.post(
        `${API}/auto-reup/pages/${page.id}/check-token`,
        null,
        { params: tokenId ? { token_id: tokenId } : {} }
      );
      setMetaResult({
        page_check: true,
        page_name: page.name,
        ...res.data,
      });
      await loadData();
    } catch (error) {
      console.error(error);
      setMetaResult({
        page_check: true,
        page_name: page.name,
        error: error.response?.data?.detail || "Khong kiem tra duoc Page token.",
      });
      await loadData();
    } finally {
      setPageTokenChecks((current) => {
        const next = { ...current };
        delete next[checkKey];
        return next;
      });
    }
  };

  return (
    <div className="auto-reup-shell">
      <style>{autoReupCss}</style>

      <section className="auto-reup-stats">
        <Stat label="ACTIONS" value={summary.actions || actions.length || 0} />
        <Stat label="ACTIVE" value={summary.active_actions || activeActions.length || 0} tone="green" />
        <Stat label="FANPAGES" value={summary.fanpages || pages.length || 0} />
        <Stat label="QUEUE" value={summary.queued || 0} tone="blue" />
        <Stat label="POSTED" value={summary.posted || 0} tone="green" />
        <Stat label="ERRORS" value={summary.errors || 0} tone="red" />
      </section>

      <main className="auto-reup-dashboard">
        <section className="auto-reup-panel auto-reup-action-panel">
          <div className="auto-reup-section-head">
            <div>
              <p>ACTION MANAGER</p>
              <h2>Danh sach action</h2>
            </div>
            <div className="auto-reup-action-head-tools">
              <label>
                <span>Sap xep</span>
                <select
                  value={actionSortOrder}
                  onChange={(event) => setActionSortOrder(event.target.value)}
                >
                  <option value="views_desc">View cao den thap</option>
                  <option value="views_asc">View thap den cao</option>
                </select>
              </label>
              <button type="button" className="auto-reup-soft-btn" onClick={openCreateAction}>
                <Glyph name="plus" />
                Them Action
              </button>
            </div>
          </div>

          {actions.length === 0 ? (
            <div className="auto-reup-empty-state">
              <div className="auto-reup-empty-icon">
                <Glyph name="shield" />
              </div>
              <h3>Chua co action nao</h3>
              <p>
                Bam Them Action de tao flow: fanpage dich, nguon reup, template, lich dang va quy tac clean content.
              </p>
              <button type="button" className="auto-reup-primary" onClick={openCreateAction}>
                <Glyph name="plus" />
                Tao action dau tien
              </button>
            </div>
          ) : (
            <div className="auto-reup-action-list">
              {sortedActions.map((action) => (
                  <ActionCard
                    key={action.id}
                    action={action}
                    templates={templates}
                    busy={busy}
                    onToggle={() => toggleAction(action)}
                    onScan={() => scanAction(action)}
                    scanBusy={Boolean(actionScans[action.id])}
                    onEdit={() => openEditAction(action)}
                    onDelete={() => removeAction(action)}
                    onDetail={() => openActionDetail(action)}
                    onOpenFacebookLogin={openFacebookLogin}
                    onRefreshInsights={() => refreshActionInsights(action, { force: true })}
                    insightsRefreshing={Boolean(insightRefreshes[action.target_page_id])}
                  />
              ))}
            </div>
          )}
        </section>

        <aside className="auto-reup-side-stack">
          <FanpageListPanel
            pages={pages}
            pageTokenChecks={pageTokenChecks}
            onCheckPageToken={checkPageToken}
          />

          <section className="auto-reup-panel">
            <div className="auto-reup-section-head compact">
              <div>
                <p>JOB QUEUE</p>
                <h2>Hang doi gan day</h2>
              </div>
              <span>{queuedJobs.length}</span>
            </div>
            <div className="auto-reup-mini-list">
              {queuedJobs.length === 0 ? (
                <div className="auto-reup-empty-mini">Chua co job cho dang bai.</div>
              ) : (
                queuedJobs.map((job) => (
                  <div key={job.id} className={`auto-reup-job-row is-${job.status}`}>
                    <span>
                      <b>{job.source_name || "Manual job"}</b>
                      <small>
                        {job.stage || job.status}
                        {job.scheduled_at
                          ? ` · ${new Date(job.scheduled_at).toLocaleString()}`
                          : ""}
                      </small>
                    </span>
                    <i>{Number(job.progress || 0)}%</i>
                  </div>
                ))
              )}
            </div>
          </section>

          <MetaConnectPanel
            pages={pages}
            tokens={metaTokens}
            selectedTokenId={selectedMetaTokenId}
            onSelectToken={selectMetaToken}
            onNewToken={resetMetaTokenForm}
            metaToken={metaToken}
            setMetaToken={setMetaToken}
            metaTokenLabel={metaTokenLabel}
            setMetaTokenLabel={setMetaTokenLabel}
            credentialType={metaCredentialType}
            setCredentialType={setMetaCredentialType}
            businessIds={metaBusinessIds}
            setBusinessIds={setMetaBusinessIds}
            autoSync={metaAutoSync}
            setAutoSync={setMetaAutoSync}
            checkInterval={metaCheckInterval}
            setCheckInterval={setMetaCheckInterval}
            metaBusy={metaBusy}
            metaResult={metaResult}
            onSave={saveMetaToken}
            onSync={syncMetaToken}
            onSyncAll={syncAllMetaTokens}
            onRemove={removeMetaToken}
            onOpenGuide={() => setMetaGuideOpen(true)}
          />
        </aside>
      </main>

      {isActionModalOpen ? (
        <ActionModal
          pages={pages}
          templates={templates}
          form={actionForm}
          setForm={setActionForm}
          editingAction={editingAction}
          busy={busy}
          contentInput={contentInput}
          setContentInput={setContentInput}
          cleanResult={cleanResult}
          actionAudioFile={actionAudioFile}
          setActionAudioFile={setActionAudioFile}
          setActionAudioUpload={setActionAudioUpload}
          onClean={cleanContent}
          onSave={saveAction}
          onClose={closeActionModal}
        />
      ) : null}

      {detailActionId ? (
        <ActionRuntimeModal
          detail={actionDetail}
          loading={detailLoading}
          now={runtimeClock}
          onClose={closeActionDetail}
        />
      ) : null}

      {metaGuideOpen ? (
        <MetaSetupGuideModal onClose={() => setMetaGuideOpen(false)} />
      ) : null}
    </div>
  );
}

function MetaConnectPanel({
  pages,
  tokens,
  selectedTokenId,
  onSelectToken,
  onNewToken,
  metaToken,
  setMetaToken,
  metaTokenLabel,
  setMetaTokenLabel,
  credentialType,
  setCredentialType,
  businessIds,
  setBusinessIds,
  autoSync,
  setAutoSync,
  checkInterval,
  setCheckInterval,
  metaBusy,
  metaResult,
  onSave,
  onSync,
  onSyncAll,
  onRemove,
  onOpenGuide,
}) {
  const connectedPages = pages.filter((page) => page.has_page_access_token);
  const sourceCounts = metaResult?.source_counts || {};
  const warnings = metaResult?.warnings || [];
  const selectedToken = tokens.find((token) => token.id === selectedTokenId);
  const formatExpiry = (value) => {
    if (!value) return "Khong ro han";
    return new Date(value).toLocaleString("vi-VN");
  };

  return (
    <section className="auto-reup-panel auto-reup-meta-panel">
      <div className="auto-reup-section-head compact">
        <div>
          <p>META API</p>
          <h2>Meta Credential Manager</h2>
        </div>
        <span>{tokens.length} TK</span>
      </div>

      <div className="auto-reup-token-toolbar">
        <button type="button" onClick={onNewToken} disabled={metaBusy}>
          + Them token
        </button>
        <button type="button" onClick={onSyncAll} disabled={metaBusy || !tokens.length}>
          {metaBusy ? "Dang kiem tra..." : "Refresh tat ca"}
        </button>
        <button type="button" className="auto-reup-token-guide-btn" onClick={onOpenGuide}>
          Xem huong dan setup
        </button>
      </div>

      <div className="auto-reup-token-accounts">
        {tokens.length ? tokens.map((token) => (
          <button
            key={token.id}
            type="button"
            className={`auto-reup-token-account ${selectedTokenId === token.id ? "is-selected" : ""}`}
            onClick={() => onSelectToken(token)}
          >
            <span className={`auto-reup-token-status is-${token.status || "unknown"}`} />
            <span>
              <b>{token.label}</b>
              <small>
                {token.credential_type === "system_user"
                  ? "System User"
                  : token.credential_type === "test_token"
                    ? "Test token"
                    : "User OAuth"}
                {" | "}{token.meta_user_name || token.meta_user_id || "Meta account"} | {token.assigned_page_count || 0} page
              </small>
            </span>
            <i>{token.status || "unknown"}</i>
          </button>
        )) : (
          <div className="auto-reup-empty-mini">Chua luu User token nao.</div>
        )}
      </div>

      <div className="auto-reup-meta-token">
        <label>
          Loai ket noi
          <select
            value={credentialType}
            onChange={(event) => setCredentialType(event.target.value)}
          >
            <option value="system_user">System User - production 24/24</option>
            <option value="user_oauth">User OAuth long-lived</option>
            <option value="test_token">Explorer/Test token</option>
          </select>
        </label>
        <label>
          Ten nhom tai san
          <input
            type="text"
            value={metaTokenLabel}
            onChange={(event) => setMetaTokenLabel(event.target.value)}
            placeholder="VD: Nick A - Page A1 den A10"
            autoComplete="off"
          />
        </label>
        <label>
          {selectedToken ? "Access token moi (de trong neu khong doi)" : "Access token"}
          <input
            type="password"
            value={metaToken}
            onChange={(event) => setMetaToken(event.target.value)}
            placeholder="Paste token co quyen quan ly page..."
            autoComplete="off"
          />
        </label>
        {credentialType === "system_user" ? (
          <label>
            Business ID
            <input
              type="text"
              value={businessIds}
              onChange={(event) => setBusinessIds(event.target.value)}
              placeholder="Nhap mot hoac nhieu Business ID, cach nhau boi dau phay"
              autoComplete="off"
            />
          </label>
        ) : null}
        <div className="auto-reup-token-settings">
          <label className="auto-reup-token-check">
            <input
              type="checkbox"
              checked={autoSync}
              onChange={(event) => setAutoSync(event.target.checked)}
            />
            Auto check
          </label>
          <label>
            Chu ky
            <select
              value={checkInterval}
              onChange={(event) => setCheckInterval(Number(event.target.value))}
            >
              <option value={60}>1 gio</option>
              <option value={180}>3 gio</option>
              <option value={360}>6 gio</option>
              <option value={720}>12 gio</option>
              <option value={1440}>24 gio</option>
            </select>
          </label>
        </div>
        <button type="button" onClick={onSave} disabled={metaBusy}>
          {metaBusy ? "Dang xu ly..." : selectedToken ? "Cap nhat token" : "Them & dong bo"}
        </button>
      </div>

      {selectedToken ? (
        <div className="auto-reup-token-detail">
          <span>
            <b>Loai</b>
            {selectedToken.credential_type === "system_user"
              ? "System User"
              : selectedToken.credential_type === "test_token"
                ? "Test only"
                : "User OAuth"}
          </span>
          <span><b>Trang thai</b>{selectedToken.status}</span>
          <span><b>Het han</b>{formatExpiry(selectedToken.expires_at)}</span>
          <span><b>Check cuoi</b>{selectedToken.last_checked_at ? formatExpiry(selectedToken.last_checked_at) : "Chua check"}</span>
          {selectedToken.last_error ? <p>{selectedToken.last_error}</p> : null}
          <div>
            <button type="button" onClick={() => onSync(selectedToken.id)} disabled={metaBusy}>
              Check & sync
            </button>
            <button type="button" className="danger" onClick={() => onRemove(selectedToken)} disabled={metaBusy}>
              Remove
            </button>
          </div>
        </div>
      ) : null}

      {metaResult?.error ? (
        <div className="auto-reup-meta-alert is-error">{metaResult.error}</div>
      ) : metaResult?.sync_all ? (
        <div className="auto-reup-meta-alert">
          <b>Da kiem tra {metaResult.results?.length || 0} tai khoan.</b>
          <span>
            Thanh cong {metaResult.results?.filter((item) => item.success).length || 0},
            {" "}loi {metaResult.results?.filter((item) => !item.success).length || 0}.
          </span>
        </div>
      ) : metaResult ? (
        <div className="auto-reup-meta-alert">
          <b>
            Tim thay {metaResult.count || 0} page tu {metaResult.businesses || 0} Business.
          </b>
          <span>
            Moi {metaResult.imported || 0}, cap nhat {metaResult.updated || 0}, stale {metaResult.stale || 0}.
          </span>
          <small>
            Direct {sourceCounts.me_accounts || 0} · BM owned {sourceCounts.business_owned_pages || 0}
            {" "}· BM client {sourceCounts.business_client_pages || 0}
          </small>
        </div>
      ) : (
        <div className="auto-reup-meta-hint">
          Moi credential quan ly mot nhom tai san doc lap. System User duoc uu tien cho production 24/24;
          User OAuth dung cho Page ca nhan. He thong khong tu dong lay credential khac de thay the khi token het han.
        </div>
      )}

      {warnings.length ? (
        <div className="auto-reup-meta-warnings">
          {warnings.map((warning) => <span key={warning}>{warning}</span>)}
        </div>
      ) : null}

    </section>
  );
}

function MetaSetupGuideModal({ onClose }) {
  return (
    <div className="auto-reup-guide-backdrop" onClick={onClose}>
      <div className="auto-reup-guide-modal" onClick={(event) => event.stopPropagation()}>
        <div className="auto-reup-guide-head">
          <div>
            <p>META SETUP</p>
            <h3>Huong dan lay System User token va Business ID</h3>
          </div>
          <button type="button" onClick={onClose}>
            <Glyph name="x" />
          </button>
        </div>
        <div className="auto-reup-guide-body">
          <section>
            <h4>1. Lay Business ID / BM ID</h4>
            <ol>
              <li>Vao Meta Business Settings: business.facebook.com/settings.</li>
              <li>Chon dung Business dang quan ly cac Page can reup.</li>
              <li>Vao Business info / Thong tin doanh nghiep.</li>
              <li>Copy Business ID. Day la day so can nhap vao o Business ID.</li>
            </ol>
            <p>Neu mot token quan ly nhieu Business, nhap nhieu ID va ngan cach bang dau phay.</p>
          </section>
          <section>
            <h4>2. Tao System User</h4>
            <ol>
              <li>Trong Business Settings, vao Users / System users.</li>
              <li>Bam Add, tao System User moi.</li>
              <li>Chon quyen Admin neu dung cho production 24/24.</li>
              <li>Gan Page can reup cho System User trong phan Assign assets.</li>
            </ol>
            <p>Chi Page nao duoc assign cho System User moi duoc tool dong bo va dang bai.</p>
          </section>
          <section>
            <h4>3. Generate token</h4>
            <ol>
              <li>Chon System User vua tao, bam Generate new token.</li>
              <li>Chon App dung de publish Page.</li>
              <li>Cap cac quyen lien quan Page nhu pages_show_list, pages_read_engagement, pages_manage_posts, pages_read_user_content neu app yeu cau.</li>
              <li>Copy token va dan vao o Access token trong tool.</li>
            </ol>
            <p>Token chi nen luu tren may dang chay tool. Khong gui token qua chat hoac luu cong khai.</p>
          </section>
          <section>
            <h4>4. Dong bo trong tool</h4>
            <ol>
              <li>Loai ket noi: chon System User - production 24/24.</li>
              <li>Ten nhom tai san: dat ten de de nhan biet, vi du PDT / Nick A.</li>
              <li>Access token: dan token System User.</li>
              <li>Business ID: dan BM ID vua copy.</li>
              <li>Bam Them & dong bo, sau do kiem tra Page hien VALID.</li>
            </ol>
          </section>
          <section>
            <h4>Luu y quan trong</h4>
            <ul>
              <li>System User phu hop chay 24/24 hon User OAuth ca nhan.</li>
              <li>Moi credential nen quan ly mot nhom Page rieng, khong dung lam backup cheo.</li>
              <li>Neu sync khong thay Page, thuong la Page chua duoc assign cho System User hoac token thieu quyen.</li>
              <li>Khi doi token, nen bam Check & sync de cap nhat lai Page token.</li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

function LegacyFanpageListPanel({ pages }) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visiblePages = useMemo(() => {
    return pages
      .filter((page) => {
        if (!normalizedQuery) return true;
        const haystack = [
          page.name,
          page.page_id,
          page.meta_category,
          ...(page.meta_business_names || []),
          ...(page.meta_token_owners || []).flatMap((owner) => [
            owner.label,
            owner.meta_user_name,
            owner.meta_user_id,
          ]),
        ].join(" ").toLocaleLowerCase();
        return haystack.includes(normalizedQuery);
      })
      .sort((left, right) => {
        const rank = (page) => {
          if (page.access_status === "connected" && page.has_page_access_token) return 0;
          if (page.access_status === "degraded" && page.has_page_access_token) return 1;
          if (page.access_status === "stale") return 2;
          return 3;
        };
        return rank(left) - rank(right) || (left.name || "").localeCompare(right.name || "");
      });
  }, [pages, normalizedQuery]);

  const connectedCount = pages.filter(
    (page) => ["connected", "degraded"].includes(page.access_status)
      && page.has_page_access_token
  ).length;
  const degradedCount = pages.filter(
    (page) => page.access_status === "degraded" && page.has_page_access_token
  ).length;
  const staleCount = pages.filter((page) => page.access_status === "stale").length;
  const pageGroups = useMemo(() => {
    const groups = new Map();

    visiblePages.forEach((page) => {
      const primaryOwner = (page.meta_token_owners || []).find((owner) => owner.is_primary);
      const key = primaryOwner?.token_id || "unassigned";
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          label: primaryOwner?.label || "Page thu cong / chua gan token",
          metaUserName: primaryOwner?.meta_user_name || "",
          credentialType: primaryOwner?.credential_type || "",
          status: primaryOwner?.status || "unassigned",
          pages: [],
        });
      }
      groups.get(key).pages.push(page);
    });

    return Array.from(groups.values()).sort((left, right) => {
      if (left.key === "unassigned") return 1;
      if (right.key === "unassigned") return -1;
      return left.label.localeCompare(right.label);
    });
  }, [visiblePages]);

  return (
    <section className="auto-reup-panel auto-reup-page-panel">
      <div className="auto-reup-section-head compact">
        <div>
          <p>FANPAGES</p>
          <h2>Page da ket noi</h2>
        </div>
        <span>{connectedCount}/{pages.length}</span>
      </div>

      <div className="auto-reup-page-summary">
        <span><b>{connectedCount}</b> usable</span>
        <span className={degradedCount ? "has-degraded" : ""}><b>{degradedCount}</b> re-auth</span>
        <span className={staleCount ? "has-stale" : ""}><b>{staleCount}</b> stale</span>
      </div>

      <input
        className="auto-reup-page-search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Tim ten Page, ID hoac Business..."
      />

      <div className="auto-reup-mini-list auto-reup-page-list">
        {visiblePages.length === 0 ? (
          <div className="auto-reup-empty-mini">
            {pages.length ? "Khong tim thay Page phu hop." : "Chua co fanpage. Hay import tu Meta."}
          </div>
        ) : (
          visiblePages.map((page) => {
            const status = page.access_status === "connected" && page.has_page_access_token
              ? "connected"
              : page.access_status === "stale"
                ? "stale"
                : "missing";
            const source = page.meta_business_names?.length
              ? page.meta_business_names.join(", ")
              : page.meta_sources?.includes("me_accounts")
                ? "Direct access"
                : page.meta_category || "Meta Page";

            return (
              <div key={page.id} className={`auto-reup-mini-row is-${status}`}>
                <span>
                  <b>{page.name}</b>
                  <small>{page.page_id || "No Page ID"} · {source}</small>
                </span>
                <i>{status === "connected" ? "READY" : status === "stale" ? "STALE" : "TOKEN"}</i>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}

function FanpageListPanel({ pages, pageTokenChecks, onCheckPageToken }) {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visiblePages = useMemo(() => {
    return pages
      .filter((page) => {
        if (!normalizedQuery) return true;
        const haystack = [
          page.name,
          page.page_id,
          page.meta_category,
          ...(page.meta_business_names || []),
          ...(page.meta_token_owners || []).flatMap((owner) => [
            owner.label,
            owner.meta_user_name,
            owner.meta_user_id,
          ]),
        ].join(" ").toLocaleLowerCase();
        return haystack.includes(normalizedQuery);
      })
      .sort((left, right) => {
        const rank = (page) => {
          if (page.access_status === "connected" && page.has_page_access_token) return 0;
          if (page.access_status === "degraded" && page.has_page_access_token) return 1;
          if (page.access_status === "stale") return 2;
          return 3;
        };
        return rank(left) - rank(right) || (left.name || "").localeCompare(right.name || "");
      });
  }, [pages, normalizedQuery]);

  const connectedCount = pages.filter(
    (page) => ["connected", "degraded"].includes(page.access_status)
      && page.has_page_access_token
  ).length;
  const degradedCount = pages.filter(
    (page) => page.access_status === "degraded" && page.has_page_access_token
  ).length;
  const staleCount = pages.filter((page) => page.access_status === "stale").length;
  const pageGroups = useMemo(() => {
    const groups = new Map();

    visiblePages.forEach((page) => {
      const primaryOwner = (page.meta_token_owners || [])[0];
      const key = primaryOwner?.token_id || "unassigned";
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          label: primaryOwner?.label || "Page thu cong / chua gan token",
          metaUserName: primaryOwner?.meta_user_name || "",
          status: primaryOwner?.status || "unassigned",
          pages: [],
        });
      }
      groups.get(key).pages.push(page);
    });

    return Array.from(groups.values()).sort((left, right) => {
      if (left.key === "unassigned") return 1;
      if (right.key === "unassigned") return -1;
      return left.label.localeCompare(right.label);
    });
  }, [visiblePages]);

  return (
    <section className="auto-reup-panel auto-reup-page-panel">
      <div className="auto-reup-section-head compact">
        <div>
          <p>FANPAGES</p>
          <h2>Page da ket noi</h2>
        </div>
        <span>{connectedCount}/{pages.length}</span>
      </div>

      <div className="auto-reup-page-summary">
        <span><b>{connectedCount}</b> usable</span>
        <span className={degradedCount ? "has-degraded" : ""}><b>{degradedCount}</b> re-auth</span>
        <span className={staleCount ? "has-stale" : ""}><b>{staleCount}</b> stale</span>
      </div>

      <input
        className="auto-reup-page-search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Tim Page, ID, Business hoac tai khoan..."
      />

      <div className="auto-reup-mini-list auto-reup-page-list">
        {pageGroups.length === 0 ? (
          <div className="auto-reup-empty-mini">
            {pages.length ? "Khong tim thay Page phu hop." : "Chua co fanpage. Hay import tu Meta."}
          </div>
        ) : pageGroups.map((group) => (
          <section key={group.key} className="auto-reup-page-group">
            <header className="auto-reup-page-group-head">
              <span className={`auto-reup-token-status is-${group.status}`} />
              <span>
                <b>{group.label}</b>
                <small>
                  {group.credentialType === "system_user"
                    ? "System User"
                    : group.credentialType === "test_token"
                      ? "Test token"
                      : group.credentialType === "user_oauth"
                        ? "User OAuth"
                        : "Chua gan credential"}
                  {group.metaUserName ? ` | ${group.metaUserName}` : ""}
                </small>
              </span>
              <i>{group.pages.length} page</i>
            </header>

            <div className="auto-reup-page-group-list">
              {group.pages.map((page) => {
                const primaryOwner = (page.meta_token_owners || []).find((owner) => owner.is_primary);
                const pageTokenStatus = primaryOwner?.page_token_status
                  || page.page_token_status
                  || "unknown";
                const status = page.access_status === "connected" && page.has_page_access_token
                  ? "connected"
                  : page.access_status === "degraded" && page.has_page_access_token
                    ? "degraded"
                  : page.access_status === "stale"
                    ? "stale"
                    : "missing";
                const source = page.meta_business_names?.length
                  ? page.meta_business_names.join(", ")
                  : page.meta_sources?.includes("me_accounts")
                    ? "Direct access"
                    : page.meta_category || "Meta Page";
                const owners = page.meta_token_owners || [];
                const checkKey = `${page.id}:${primaryOwner?.token_id || "primary"}`;
                const checking = Boolean(pageTokenChecks?.[checkKey]);
                const checkedAt = primaryOwner?.page_token_last_checked_at
                  || page.page_token_last_checked_at
                  || "";
                const tokenError = primaryOwner?.page_token_last_error
                  || page.page_token_last_error
                  || "";
                const tokenLabel = pageTokenStatus === "valid"
                  ? status === "degraded" ? "VALID / REAUTH" : "VALID"
                  : pageTokenStatus === "invalid"
                    ? "INVALID"
                    : pageTokenStatus === "error"
                      ? "CHECK ERROR"
                      : "UNKNOWN";

                return (
                  <div
                    key={page.id}
                    className={`auto-reup-mini-row is-${status} token-${pageTokenStatus}`}
                    title={tokenError || (checkedAt ? `Last Page-token check: ${checkedAt}` : "")}
                  >
                    <span>
                      <b>{page.name}</b>
                      <small>{page.page_id || "No Page ID"} | {source}</small>
                      <em>
                        Page token: {tokenLabel}
                        {checkedAt ? ` | ${new Date(checkedAt).toLocaleString()}` : ""}
                      </em>
                      {owners.length > 1 ? (
                        <em>Shared: {owners.slice(1).map((owner) => owner.label).join(", ")}</em>
                      ) : null}
                    </span>
                    <div className="auto-reup-page-token-tools">
                      <i>{checking ? "CHECKING" : tokenLabel}</i>
                      <button
                        type="button"
                        className={checking ? "is-checking" : ""}
                        onClick={() => onCheckPageToken(page, primaryOwner?.token_id)}
                        disabled={checking || !primaryOwner?.token_id}
                        title="Kiem tra Page access token nay voi Meta"
                        aria-label={`Kiem tra Page token cua ${page.name}`}
                      >
                        <Glyph name="refresh" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </section>
  );
}

function ActionCard({
  action,
  templates,
  busy,
  onToggle,
  onScan,
  scanBusy,
  onEdit,
  onDelete,
  onDetail,
  onOpenFacebookLogin,
  onRefreshInsights,
  insightsRefreshing,
}) {
  const targetTotal = Math.max(
    0,
    Number(action.reup_target_total || 0) || Number(action.progress_total || 0)
  );
  const scanned = Number(action.progress_scanned || 0);
  const posted = Number(action.progress_posted || 0);
  const errors = Number(action.progress_errors || 0);
  const total = Math.max(targetTotal, posted);
  const progress = total > 0 ? Math.min(100, Math.round((posted / total) * 100)) : 0;
  const pipeline = [
    action.translate_caption ? "Translate" : null,
    action.apply_frame ? "Creative" : null,
  ].filter(Boolean);
  const templateName = templates.find((template) => template.id === action.template_id)?.name;
  const scanStatus = action.scan_status || "idle";
  const scanLabel = scanStatus === "scanning"
    ? "SCANNING"
    : scanStatus === "error"
      ? "SCAN ERROR"
      : scanStatus === "login_required"
        ? "LOGIN REQUIRED"
      : scanStatus === "ready"
        ? "SOURCE READY"
        : "WAITING SCAN";
  const scheduleLabel = action.schedule_mode === "manual_times"
    ? `manual ${Number(action.daily_limit || 1)} moc`
    : action.schedule_mode === "smart_daily"
      ? `smart ${String(action.smart_profile || "vn").toUpperCase()}`
      : `random ${action.min_gap_minutes}-${action.max_gap_minutes || action.min_gap_minutes} phut`;
  const selectedInsights = action.page_insights?.total || {};

  return (
    <article
      className={`auto-reup-action ${action.enabled ? "is-running" : "is-paused"}`}
      onDoubleClick={(event) => {
        if (!event.target.closest("button")) onDetail();
      }}
      title="Double click de xem runtime detail"
    >
      <div className="auto-reup-action-body">
        <div className="auto-reup-action-main">
          <div className="auto-reup-action-info">
          <div className="auto-reup-action-title">
            <h3>{action.name}</h3>
            <span>{action.enabled ? "ACTIVE" : "PAUSED"}</span>
          </div>
          <div className="auto-reup-action-meta">
            <span><Glyph name="link" /> {action.platform}</span>
            <span>
              <Glyph name="clock" /> {action.daily_limit}/ngay - {scheduleLabel}
            </span>
            <span>{action.target_page_name || "Chua gan fanpage"}</span>
          </div>
          <div className="auto-reup-action-url">{action.source_url}</div>
          <div className="auto-reup-chip-row">
            {pipeline.length ? pipeline.map((item) => <i key={item}>{item}</i>) : <i>No pipeline</i>}
            {action.template_id ? <i>Template: {templateName || action.template_id}</i> : <i>No template</i>}
            {action.content_cleaner_enabled ? <i>Clean content</i> : null}
            <i className={`is-scan-${scanStatus}`}>{scanLabel}</i>
          </div>
          {action.last_scan_error ? (
            <div className="auto-reup-action-error">{action.last_scan_error}</div>
          ) : null}
          </div>
        </div>
        <div className="auto-reup-insight-panel">
            <div className="auto-reup-insight-head">
              <span>Tổng</span>
              <button
                type="button"
                className={`auto-reup-insight-refresh ${insightsRefreshing ? "is-loading" : ""}`}
                onClick={onRefreshInsights}
                disabled={insightsRefreshing}
                title="Tai lai thong so page"
              >
                <Glyph name="refresh" />
              </button>
            </div>
            <div className="auto-reup-action-insights">
              <span>
                <b>{formatInsightValue(selectedInsights.views)}</b>
                <small>views</small>
                <em className={`is-${selectedInsights.trend?.views?.direction || "none"}`}>
                  {formatInsightTrend(selectedInsights.trend?.views)}
                </em>
              </span>
              <span>
                <b>{formatInsightValue(selectedInsights.engagements)}</b>
                <small>engage</small>
                <em className={`is-${selectedInsights.trend?.engagements?.direction || "none"}`}>
                  {formatInsightTrend(selectedInsights.trend?.engagements)}
                </em>
              </span>
              <span>
                <b>{formatInsightValue(selectedInsights.followers)}</b>
                <small>followers</small>
                <em className={`is-${selectedInsights.trend?.followers?.direction || "none"}`}>
                  {formatInsightTrend(selectedInsights.trend?.followers)}
                </em>
              </span>
              <span>
                <b>{formatInsightValue(selectedInsights.estimated_earnings, " US$")}</b>
                <small>earn</small>
                <em className={`is-${selectedInsights.trend?.estimated_earnings?.direction || "none"}`}>
                  {formatInsightTrend(selectedInsights.trend?.estimated_earnings)}
                </em>
              </span>
            </div>
          </div>
      </div>

      <div className="auto-reup-action-right">
        <div className="auto-reup-progress-ring">
          <b>{progress}%</b>
          <small>{posted}/{total || 0} reup</small>
        </div>
        <div className="auto-reup-action-counts">
          <span>{total} total</span>
          <span>{scanned} scanned</span>
          <span>{errors} errors</span>
        </div>
        <div className="auto-reup-action-tools">
          <button type="button" onClick={onDetail} title="Runtime detail">
            <Glyph name="detail" />
          </button>
          <button
            type="button"
            onClick={onScan}
            disabled={busy || scanBusy || scanStatus === "scanning"}
            title="Quet nguon ngay"
            className={scanStatus === "scanning" ? "is-scanning" : ""}
          >
            <Glyph name="refresh" />
          </button>
          {scanStatus === "login_required" ? (
            <button type="button" onClick={onOpenFacebookLogin} disabled={busy} title="Mo Chrome dang nhap Facebook">
              FB
            </button>
          ) : null}
          <button type="button" onClick={onToggle} disabled={busy} title={action.enabled ? "Pause action" : "Run action"}>
            {action.enabled ? <Glyph name="pause" /> : <Glyph name="play" />}
          </button>
          <button type="button" onClick={onEdit} disabled={busy} title="Edit action">
            <Glyph name="edit" />
          </button>
          <button type="button" className="danger" onClick={onDelete} disabled={busy} title="Delete action">
            <Glyph name="trash" />
          </button>
        </div>
      </div>
    </article>
  );
}

function formatRuntimeTime(value) {
  if (!value) return "Chua co";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Chua co";
  return date.toLocaleString("vi-VN");
}

function formatCountdown(value, now) {
  if (!value) return "--:--:--";
  const target = new Date(value).getTime();
  if (!Number.isFinite(target)) return "--:--:--";
  const remaining = Math.max(0, Math.floor((target - now) / 1000));
  const days = Math.floor(remaining / 86400);
  const hours = Math.floor((remaining % 86400) / 3600);
  const minutes = Math.floor((remaining % 3600) / 60);
  const seconds = remaining % 60;
  const clock = [hours, minutes, seconds]
    .map((item) => String(item).padStart(2, "0"))
    .join(":");
  return days > 0 ? `${days}d ${clock}` : clock;
}

function runtimePhaseLabel(phase) {
  const labels = {
    paused: "Tam dung",
    scanning: "Dang quet nguon",
    download: "Dang tai video",
    downloaded: "Da tai video",
    render: "Dang xu ly video",
    ready: "Cho lich dang",
    waiting_publish: "Cho den gio dang",
    publishing: "Dang len Facebook",
    queued: "Dang cho worker",
    waiting_scan: "Cho lan quet tiep theo",
    posted: "Da dang",
    prepare_error: "Loi xu ly",
    publish_error: "Loi dang bai",
  };
  return labels[phase] || phase || "Dang khoi tao";
}

function ActionRuntimeModal({ detail, loading, now, onClose }) {
  const runtime = detail?.runtime || {};
  const action = detail?.action || {};
  const jobs = detail?.jobs || [];
  const events = detail?.events || [];
  const activeJobs = jobs.filter((job) =>
    ["processing", "publishing", "ready", "queued"].includes(job.status)
  );

  return (
    <div className="auto-reup-modal-backdrop auto-reup-runtime-backdrop">
      <section
        className="auto-reup-modal auto-reup-runtime-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Action runtime detail"
      >
        <div className="auto-reup-modal-head">
          <div>
            <p>LIVE ACTION RUNTIME</p>
            <h2>{action.name || "Action detail"}</h2>
            <span>
              Du lieu backend duoc cap nhat moi 2 giay. Countdown chay theo dong ho thuc.
            </span>
          </div>
          <button type="button" onClick={onClose} title="Dong">
            <Glyph name="x" />
          </button>
        </div>

        {loading && !detail ? (
          <div className="auto-reup-runtime-loading">Dang tai runtime...</div>
        ) : detail?.error ? (
          <div className="auto-reup-runtime-error">{detail.error}</div>
        ) : (
          <>
            <div className="auto-reup-runtime-overview">
              <div className={`auto-reup-runtime-phase is-${runtime.phase || "idle"}`}>
                <span className="auto-reup-live-dot" />
                <small>TRANG THAI HIEN TAI</small>
                <b>{runtimePhaseLabel(runtime.phase)}</b>
              </div>
              <div>
                <small>LAN QUET TIEP THEO</small>
                <b>{formatCountdown(runtime.next_scan_at, now)}</b>
                <span>{formatRuntimeTime(runtime.next_scan_at)}</span>
              </div>
              <div>
                <small>LAN DANG TIEP THEO</small>
                <b>{formatCountdown(runtime.next_publish_at, now)}</b>
                <span>{formatRuntimeTime(runtime.next_publish_at)}</span>
              </div>
              <div>
                <small>HANG DOI ACTION</small>
                <b>{Number(runtime.queued || 0) + Number(runtime.processing || 0) + Number(runtime.ready || 0) + Number(runtime.publishing || 0)}</b>
                <span>{runtime.posted || 0} posted · {runtime.errors || 0} errors</span>
              </div>
            </div>

            <div className="auto-reup-runtime-grid">
              <section className="auto-reup-runtime-card">
                <div className="auto-reup-runtime-card-head">
                  <div>
                    <p>LIVE JOBS</p>
                    <h3>Dang xu ly va cho dang</h3>
                  </div>
                  <span>{activeJobs.length}</span>
                </div>
                <div className="auto-reup-runtime-jobs">
                  {activeJobs.length === 0 ? (
                    <div className="auto-reup-runtime-empty">
                      Khong co video dang xu ly. Action dang cho lan quet tiep theo.
                    </div>
                  ) : (
                    activeJobs.map((job) => (
                      <article key={job.id} className={`is-${job.status}`}>
                        <div className="auto-reup-runtime-job-top">
                          <span>
                            <b>{job.source_post_id || job.source_name || "Video source"}</b>
                            <small>{runtimePhaseLabel(job.stage || job.status)}</small>
                          </span>
                          <i>{Number(job.progress || 0)}%</i>
                        </div>
                        <div className="auto-reup-runtime-progress">
                          <span style={{ width: `${Number(job.progress || 0)}%` }} />
                        </div>
                        <div className="auto-reup-runtime-job-meta">
                          <span>{job.status}</span>
                          {job.scheduled_at ? (
                            <span>
                              Dang sau {formatCountdown(job.scheduled_at, now)}
                            </span>
                          ) : null}
                          {job.error ? <span className="is-error">{job.error}</span> : null}
                        </div>
                      </article>
                    ))
                  )}
                </div>
              </section>

              <section className="auto-reup-runtime-card">
                <div className="auto-reup-runtime-card-head">
                  <div>
                    <p>EVENT STREAM</p>
                    <h3>Nhat ky tien trinh</h3>
                  </div>
                  <span>{events.length}</span>
                </div>
                <div className="auto-reup-event-stream">
                  {events.length === 0 ? (
                    <div className="auto-reup-runtime-empty">
                      Chua co event. Event se xuat hien khi action quet hoac xu ly job.
                    </div>
                  ) : (
                    events.map((event) => (
                      <article key={event.id} className={`is-${event.level || "info"}`}>
                        <span className="auto-reup-event-dot" />
                        <div>
                          <b>{event.message}</b>
                          <small>
                            {formatRuntimeTime(event.created_at)}
                            {event.job_id ? ` · Job ${event.job_id.slice(0, 8)}` : ""}
                          </small>
                        </div>
                      </article>
                    ))
                  )}
                </div>
              </section>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function ActionModal({
  pages,
  templates,
  form,
  setForm,
  editingAction,
  busy,
  contentInput,
  setContentInput,
  cleanResult,
  actionAudioFile,
  setActionAudioFile,
  setActionAudioUpload,
  onClean,
  onSave,
  onClose,
}) {
  const selectablePages = pages.filter(isUsableDestinationPage);
  const dailyLimit = Math.max(1, Math.min(50, Number(form.daily_limit || 1)));
  const manualTimes = buildManualTimes(dailyLimit, form.manual_times, form.active_from, form.active_to);
  const previewTimes = form.schedule_mode === "smart_daily" ? smartPreviewTimes(form) : manualTimes;

  const setDailyLimit = (value) => {
    const nextLimit = Math.max(1, Math.min(50, Number(value || 1)));
    setForm({
      ...form,
      daily_limit: nextLimit,
      manual_times: buildManualTimes(nextLimit, form.manual_times, form.active_from, form.active_to),
    });
  };

  const setManualTime = (index, value) => {
    const nextTimes = buildManualTimes(dailyLimit, form.manual_times, form.active_from, form.active_to);
    nextTimes[index] = value;
    setForm({ ...form, manual_times: nextTimes });
  };

  return (
    <div className="auto-reup-modal-backdrop" role="presentation">
      <section className="auto-reup-modal" role="dialog" aria-modal="true" aria-label="Action setup">
        <div className="auto-reup-modal-head">
          <div>
            <p>{editingAction ? "EDIT ACTION" : "NEW ACTION"}</p>
            <h2>{editingAction ? "Chinh sua action" : "Them action moi"}</h2>
            <span>Nhap flow reup: fanpage dich, nguon video, pipeline, template va lich dang.</span>
          </div>
          <button type="button" onClick={onClose} aria-label="Close">
            <Glyph name="x" />
          </button>
        </div>

        <form className="auto-reup-action-form" onSubmit={onSave}>
          <div className="auto-reup-form-grid">
            <section className="auto-reup-form-card">
              <div className="auto-reup-step">1</div>
              <h3>Fanpage dich</h3>
              <label>
                Chon fanpage da ket noi
                <select
                  value={form.target_page_id}
                  onChange={(event) => {
                    const page = pages.find((item) => item.id === event.target.value);
                    setForm({
                      ...form,
                      target_page_id: event.target.value,
                      name: page?.name || "",
                    });
                  }}
                >
                  <option value="">Chon fanpage dich</option>
                  {selectablePages.map((page) => (
                    <option key={page.id} value={page.id}>
                      {page.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="auto-reup-selection-note">
                <span>Action name</span>
                <b>{form.name || "Tu dong theo ten fanpage dich"}</b>
                <small>Fanpage duoc dong bo tu Meta Credential Manager, khong tao thu cong tai day.</small>
              </div>
            </section>

            <section className="auto-reup-form-card">
              <div className="auto-reup-step">2</div>
              <h3>Thong tin action</h3>
              <div className="auto-reup-two">
                <label>
                  Nen tang nguon
                  <select
                    value={form.platform}
                    onChange={(event) => setForm({ ...form, platform: event.target.value })}
                  >
                    {platforms.map((platform) => (
                      <option key={platform.value} value={platform.value}>
                        {platform.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Frame template
                  <select
                    value={form.template_id}
                    onChange={(event) => setForm({ ...form, template_id: event.target.value })}
                  >
                    <option value="">
                      {templates.length ? "Chon template" : "Chua co template"}
                    </option>
                    {templates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {form.apply_frame && !form.template_id ? (
                <div className="auto-reup-field-warning">
                  Creative Frame dang bat, vi vay bat buoc chon mot template tu AI Video Text Translator.
                </div>
              ) : null}
              <label>
                Link nguon reup
                <input
                  value={form.source_url}
                  onChange={(event) => setForm({ ...form, source_url: event.target.value })}
                  placeholder="https://facebook.com/... hoac https://tiktok.com/..."
                />
              </label>
              <label>
                Ghi chu
                <textarea
                  value={form.notes}
                  onChange={(event) => setForm({ ...form, notes: event.target.value })}
                  placeholder="Quy tac rieng cho action nay..."
                />
              </label>
            </section>

            <section className="auto-reup-form-card">
              <div className="auto-reup-step">3</div>
              <h3>Pipeline xu ly</h3>
              <div className="auto-reup-toggle-grid">
                <PipelineToggle
                  checked={form.translate_caption}
                  title="Translate Caption"
                  desc="OCR, dich va sub truoc khi dang."
                  onChange={(value) => setForm({ ...form, translate_caption: value })}
                />
                <PipelineToggle
                  checked={form.apply_frame}
                  title="Creative Frame"
                  desc="Ghep frame, repack va audio tuy chon."
                  onChange={(value) => setForm({ ...form, apply_frame: value })}
                />
                <PipelineToggle
                  checked={form.content_cleaner_enabled}
                  title="Clean Content"
                  desc="Loai link, affiliate, CTA rac."
                  onChange={(value) => setForm({ ...form, content_cleaner_enabled: value })}
                />
                <PipelineToggle
                  checked={form.enabled}
                  title="Run Action"
                  desc="Bat action sau khi luu."
                  onChange={(value) => setForm({ ...form, enabled: value })}
                />
              </div>
              {form.apply_frame ? (
                <div className="auto-reup-creative-panel">
                  <div className="auto-reup-creative-head">
                    <b>Creative Frame settings</b>
                    <span>Ap dung cho tat ca video cua action nay.</span>
                  </div>
                  <div className="auto-reup-creative-options">
                    <PipelineToggle
                      checked={form.creative_remove_source_audio}
                      title="Remove source audio"
                      desc="Bo audio goc de giam rui ro nhac ban quyen."
                      onChange={(value) => setForm({ ...form, creative_remove_source_audio: value })}
                    />
                    <PipelineToggle
                      checked={form.creative_randomize_variant}
                      title="Visual repack variant"
                      desc="Them bien the hinh anh nhe truoc khi ghep frame."
                      onChange={(value) => setForm({ ...form, creative_randomize_variant: value })}
                    />
                  </div>
                  <PipelineToggle
                    checked={form.creative_smart_audio}
                    title="Custom audio layer"
                    desc="Dung MP3/MP4 ban chon lam audio nen cho action."
                    onChange={(value) => setForm({ ...form, creative_smart_audio: value })}
                  />
                  {form.creative_smart_audio ? (
                    <div className="auto-reup-creative-audio-row">
                      <label className="auto-reup-file-field">
                        Custom audio MP3 / MP4
                        <input
                          type="file"
                          accept=".mp3,.m4a,.aac,.wav,.ogg,.mp4,.mov,.mkv,.webm,audio/*,video/mp4"
                          onChange={(event) => {
                            const file = event.target.files?.[0] || null;
                            setActionAudioFile(file);
                            setActionAudioUpload(null);
                            if (!file) {
                              setForm({ ...form, creative_custom_audio_path: "" });
                            }
                          }}
                        />
                        <span className="auto-reup-field-hint">
                          {actionAudioFile
                            ? `Dang chon: ${actionAudioFile.name}`
                            : form.creative_custom_audio_path
                              ? "Dang dung audio da upload cho action nay."
                              : "Neu khong chon file, backend dung fallback audio noi bo."}
                        </span>
                      </label>
                      <label className="auto-reup-volume-field">
                        Volume
                        <input
                          type="number"
                          min="0.02"
                          max="2"
                          step="0.05"
                          value={form.creative_audio_volume}
                          onChange={(event) => setForm({ ...form, creative_audio_volume: event.target.value })}
                        />
                      </label>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>

            <section className="auto-reup-form-card">
              <div className="auto-reup-step">4</div>
              <h3>Lich dang</h3>
              <div className="auto-reup-schedule-grid">
                <label>
                  Bai/ngay
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={form.daily_limit}
                    onChange={(event) => setDailyLimit(event.target.value)}
                  />
                </label>
                <label>
                  Kieu lich
                  <select
                    value={form.schedule_mode}
                    onChange={(event) => setForm({
                      ...form,
                      schedule_mode: event.target.value,
                      manual_times: buildManualTimes(dailyLimit, form.manual_times, form.active_from, form.active_to),
                    })}
                  >
                    {scheduleModes.map((mode) => (
                      <option key={mode.value} value={mode.value}>
                        {mode.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Quet moi phut
                  <input
                    type="number"
                    min="15"
                    value={form.scan_interval_minutes}
                    onChange={(event) => setForm({ ...form, scan_interval_minutes: Number(event.target.value) })}
                  />
                </label>
                {form.schedule_mode === "smart_daily" ? (
                  <label>
                    Gio vang
                    <select
                      value={form.smart_profile}
                      onChange={(event) => setForm({ ...form, smart_profile: event.target.value })}
                    >
                      {smartProfiles.map((profile) => (
                        <option key={profile.value} value={profile.value}>
                          {profile.label}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                {form.schedule_mode === "random_interval" ? (
                  <>
                <label>
                  Random tu (phut)
                  <input
                    type="number"
                    min="15"
                    value={form.min_gap_minutes}
                    onChange={(event) => setForm({ ...form, min_gap_minutes: Number(event.target.value) })}
                  />
                </label>
                <label>
                  Random den (phut)
                  <input
                    type="number"
                    min={form.min_gap_minutes || 15}
                    value={form.max_gap_minutes}
                    onChange={(event) => setForm({ ...form, max_gap_minutes: Number(event.target.value) })}
                  />
                </label>
                  </>
                ) : null}
                {form.schedule_mode === "smart_daily" ? (
                  <label>
                    Dao dong (phut)
                    <input
                      type="number"
                      min="0"
                      max="45"
                      value={form.jitter_minutes}
                      onChange={(event) => setForm({ ...form, jitter_minutes: Number(event.target.value) })}
                    />
                  </label>
                ) : null}
              </div>
              {form.schedule_mode === "random_interval" ? (
                <div className="auto-reup-random-note">
                  Moi bai se duoc xep lich voi khoang cach ngau nhien trong mien {form.min_gap_minutes}-{form.max_gap_minutes} phut.
                </div>
              ) : null}
              {form.schedule_mode === "manual_times" ? (
                <div className="auto-reup-manual-times">
                  {manualTimes.map((time, index) => (
                    <label key={`manual-${index}`}>
                      Bai {index + 1}
                      <input
                        type="time"
                        value={time}
                        onChange={(event) => setManualTime(index, event.target.value)}
                      />
                    </label>
                  ))}
                </div>
              ) : null}
              <div className="auto-reup-two">
                <label>
                  Tu gio
                  <input
                    type="time"
                    value={form.active_from}
                    onChange={(event) => setForm({
                      ...form,
                      active_from: event.target.value,
                      manual_times: buildManualTimes(dailyLimit, form.manual_times, event.target.value, form.active_to),
                    })}
                  />
                </label>
                <label>
                  Den gio
                  <input
                    type="time"
                    value={form.active_to}
                    onChange={(event) => setForm({
                      ...form,
                      active_to: event.target.value,
                      manual_times: buildManualTimes(dailyLimit, form.manual_times, form.active_from, event.target.value),
                    })}
                  />
                </label>
              </div>
              {form.schedule_mode !== "random_interval" ? (
                <div className="auto-reup-schedule-preview">
                  {previewTimes.map((time, index) => (
                    <span key={`${time}-${index}`}>Bai {index + 1}: {time}</span>
                  ))}
                </div>
              ) : null}
            </section>
          </div>

          <section className="auto-reup-form-card auto-reup-clean-test">
            <div>
              <div className="auto-reup-step">5</div>
              <h3>Test clean content</h3>
              <p>Khong luu vao action, chi dung de xem truoc cach xoa link/affiliate.</p>
            </div>
            <textarea
              value={contentInput}
              onChange={(event) => setContentInput(event.target.value)}
              placeholder="Dan content goc vao day de preview..."
            />
            <div className="auto-reup-clean-actions">
              <button type="button" onClick={onClean} disabled={busy}>
                Preview clean
              </button>
              <pre>{cleanResult?.clean_content || "Content sau khi clean se hien thi o day."}</pre>
            </div>
          </section>

          <div className="auto-reup-modal-actions">
            <button type="button" onClick={onClose} disabled={busy}>
              Huy
            </button>
            <button type="submit" className="auto-reup-primary" disabled={busy}>
              <Glyph name="check" />
              {editingAction ? "Cap nhat action" : "Luu action"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function PipelineToggle({ checked, title, desc, onChange }) {
  return (
    <button
      type="button"
      className={`auto-reup-pipeline-toggle ${checked ? "is-on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span />
      <b>{title}</b>
      <small>{desc}</small>
    </button>
  );
}

function Stat({ label, value, tone = "" }) {
  return (
    <div className={`auto-reup-stat ${tone ? `is-${tone}` : ""}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

const autoReupCss = `
.auto-reup-shell {
  min-height: calc(100vh - 86px);
  padding: 14px clamp(14px, 2vw, 24px) 34px;
  color: #f8fafc;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.auto-reup-shell *,
.auto-reup-shell *::before,
.auto-reup-shell *::after {
  box-sizing: border-box;
}
.auto-reup-hero,
.auto-reup-panel,
.auto-reup-stat,
.auto-reup-modal {
  border: 1px solid rgba(255,255,255,0.09);
  background:
    linear-gradient(145deg, rgba(31, 33, 42, 0.94), rgba(14, 16, 23, 0.94)),
    radial-gradient(circle at 18% 0%, rgba(99, 102, 241, 0.12), transparent 18rem);
  box-shadow: 0 22px 70px rgba(0,0,0,0.34);
  backdrop-filter: blur(14px);
}
.auto-reup-hero {
  max-width: 1536px;
  margin: 0 auto 18px;
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: center;
  border-radius: 24px;
  padding: clamp(22px, 2.4vw, 34px);
  animation: autoReupIn 0.42s cubic-bezier(.2,.8,.2,1) both;
}
.auto-reup-hero p,
.auto-reup-section-head p,
.auto-reup-modal-head p {
  margin: 0;
  color: #9aa3b8;
  font-size: 0.76rem;
  line-height: 1.45;
  font-weight: 800;
  letter-spacing: 0.06em;
}
.auto-reup-hero h1 {
  margin: 8px 0 10px;
  font-size: clamp(2rem, 3.2vw, 3.55rem);
  line-height: 0.98;
  letter-spacing: 0;
}
.auto-reup-hero > div:first-child > span,
.auto-reup-modal-head span {
  max-width: 820px;
  display: block;
  color: #c6ccd9;
  line-height: 1.55;
}
.auto-reup-add-hero,
.auto-reup-soft-btn,
.auto-reup-primary,
.auto-reup-modal-actions button {
  min-height: 44px;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 14px;
  color: #fff;
  font-weight: 850;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}
.auto-reup-add-hero,
.auto-reup-primary {
  padding: 0 20px;
  background: linear-gradient(135deg, #5b7cfa, #8b5cf6);
  box-shadow: 0 14px 34px rgba(91, 124, 250, 0.25);
}
.auto-reup-add-hero:hover,
.auto-reup-soft-btn:hover,
.auto-reup-primary:hover {
  transform: translateY(-1px);
}
.auto-reup-glyph {
  position: relative;
  width: 1em;
  height: 1em;
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  font-size: 1rem;
  line-height: 1;
}
.auto-reup-glyph-plus::before { content: "+"; font-weight: 950; font-size: 1.1em; }
.auto-reup-glyph-x::before { content: "x"; font-weight: 950; font-size: 0.95em; }
.auto-reup-glyph-check::before { content: "OK"; font-size: 0.62em; font-weight: 950; letter-spacing: 0; }
.auto-reup-glyph-edit::before { content: "E"; font-size: 0.76em; font-weight: 950; }
.auto-reup-glyph-trash::before { content: "D"; font-size: 0.76em; font-weight: 950; }
.auto-reup-glyph-detail::before { content: "i"; font-size: 0.8em; font-weight: 950; }
.auto-reup-glyph-link::before { content: "#"; font-size: 0.8em; font-weight: 950; }
.auto-reup-glyph-clock::before { content: "T"; font-size: 0.76em; font-weight: 950; }
.auto-reup-glyph-shield::before { content: "A"; font-size: 1.1em; font-weight: 950; }
.auto-reup-glyph-refresh::before {
  content: "";
  width: 0.62em;
  height: 0.62em;
  border: 0.13em solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
}
.auto-reup-glyph-refresh::after {
  content: "";
  position: absolute;
  right: 0.04em;
  top: 0.04em;
  width: 0;
  height: 0;
  border-left: 0.25em solid currentColor;
  border-top: 0.18em solid transparent;
  border-bottom: 0.18em solid transparent;
  transform: rotate(-20deg);
}
.auto-reup-glyph-play::before {
  content: "";
  width: 0;
  height: 0;
  border-top: 0.34em solid transparent;
  border-bottom: 0.34em solid transparent;
  border-left: 0.56em solid currentColor;
  transform: translateX(0.06em);
}
.auto-reup-glyph-pause::before,
.auto-reup-glyph-pause::after {
  content: "";
  width: 0.22em;
  height: 0.72em;
  border-radius: 999px;
  background: currentColor;
}
.auto-reup-glyph-pause::after {
  position: absolute;
  transform: translateX(0.34em);
}
.auto-reup-glyph-pause::before {
  transform: translateX(-0.12em);
}
.auto-reup-soft-btn {
  padding: 0 16px;
  background: rgba(91, 124, 250, 0.12);
  border-color: rgba(125, 162, 255, 0.34);
}
.auto-reup-stats {
  max-width: 1536px;
  margin: 0 auto 14px;
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
}
.auto-reup-stat {
  min-height: 70px;
  border-radius: 14px;
  padding: 13px 14px;
}
.auto-reup-stat span {
  display: block;
  color: #9aa3b8;
  font-size: 0.68rem;
  font-weight: 750;
}
.auto-reup-stat b {
  display: block;
  margin-top: 8px;
  font-size: 1.55rem;
  line-height: 1;
}
.auto-reup-stat.is-green b { color: #43f18d; }
.auto-reup-stat.is-blue b { color: #67d7ff; }
.auto-reup-stat.is-red b { color: #ff6576; }
.auto-reup-dashboard {
  max-width: 1536px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(310px, 0.34fr);
  gap: 14px;
  align-items: start;
}
.auto-reup-panel {
  border-radius: 18px;
  padding: clamp(14px, 1.5vw, 20px);
}
.auto-reup-side-stack {
  display: grid;
  gap: 14px;
}
.auto-reup-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.auto-reup-section-head.compact {
  margin-bottom: 14px;
}
.auto-reup-section-head h2,
.auto-reup-modal-head h2 {
  margin: 2px 0 0;
  font-size: 1.08rem;
}
.auto-reup-section-head > span {
  color: #a8b4ff;
  font-weight: 900;
}
.auto-reup-action-head-tools {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}
.auto-reup-action-head-tools label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 8px;
  border: 1px solid rgba(125, 162, 255, 0.22);
  border-radius: 11px;
  background: rgba(255,255,255,0.035);
  color: #98a3b8;
  font-size: 0.62rem;
  font-weight: 850;
  text-transform: uppercase;
}
.auto-reup-action-head-tools select {
  min-width: 136px;
  border: 0;
  outline: none;
  background: transparent;
  color: #edf2ff;
  font-size: 0.68rem;
  font-weight: 850;
  text-transform: none;
}
.auto-reup-action-head-tools select option {
  background: #181b24;
  color: #f8fafc;
}
.auto-reup-empty-state {
  min-height: 420px;
  border: 1px dashed rgba(255,255,255,0.12);
  border-radius: 22px;
  display: grid;
  place-items: center;
  text-align: center;
  padding: 36px;
  background: rgba(255,255,255,0.03);
}
.auto-reup-empty-state h3 {
  margin: 16px 0 8px;
  font-size: 1.35rem;
}
.auto-reup-empty-state p {
  max-width: 540px;
  margin: 0 0 20px;
  color: #9fa8bb;
  line-height: 1.55;
}
.auto-reup-empty-icon {
  width: 68px;
  height: 68px;
  border-radius: 22px;
  display: grid;
  place-items: center;
  color: #9fb2ff;
  background: rgba(91, 124, 250, 0.12);
  border: 1px solid rgba(125, 162, 255, 0.28);
}
.auto-reup-action-list {
  display: grid;
  gap: 7px;
  max-height: calc(100vh - 238px);
  min-height: 260px;
  overflow: auto;
  padding-right: 6px;
}
.auto-reup-action {
  border: 1px solid rgba(125, 162, 255, 0.20);
  border-radius: 14px;
  padding: 8px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 152px;
  gap: 9px;
  align-items: start;
  height: fit-content;
  background:
    linear-gradient(135deg, rgba(91,124,250,0.11), rgba(14,16,23,0.34)),
    rgba(255,255,255,0.035);
}
.auto-reup-action.is-paused {
  border-color: rgba(255,255,255,0.11);
  background: rgba(255,255,255,0.035);
}
.auto-reup-action-body {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(260px, 0.42fr) minmax(300px, 1fr);
  gap: 8px;
  align-items: stretch;
}
.auto-reup-action-main {
  min-width: 0;
  display: flex;
  gap: 0;
  align-items: flex-start;
}
.auto-reup-action-main .auto-reup-action-icon {
  display: none;
}
.auto-reup-action-icon {
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: #4bf18e;
  background: rgba(52, 244, 135, 0.12);
  border: 1px solid rgba(52, 244, 135, 0.22);
}
.auto-reup-action.is-paused .auto-reup-action-icon {
  color: #ffd166;
  background: rgba(255, 209, 102, 0.12);
  border-color: rgba(255, 209, 102, 0.22);
}
.auto-reup-action-info {
  min-width: 0;
  flex: 1;
}
.auto-reup-action-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.auto-reup-action-title h3 {
  margin: 0;
  font-size: 0.86rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.auto-reup-action-title span,
.auto-reup-chip-row i,
.auto-reup-action-counts span,
.auto-reup-mini-row i,
.auto-reup-job-row i {
  border-radius: 999px;
  padding: 2px 6px;
  font-size: 0.56rem;
  font-weight: 900;
  font-style: normal;
}
.auto-reup-action-title span {
  color: #4bf18e;
  background: rgba(52, 244, 135, 0.13);
}
.auto-reup-action.is-paused .auto-reup-action-title span {
  color: #ffd166;
  background: rgba(255, 209, 102, 0.13);
}
.auto-reup-action-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 9px;
  margin-top: 4px;
  color: #a7b0c3;
  font-size: 0.64rem;
}
.auto-reup-action-meta span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.auto-reup-action-url {
  margin-top: 4px;
  color: #cbd5e1;
  font-size: 0.64rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.auto-reup-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 5px;
}
.auto-reup-chip-row i {
  color: #bfccff;
  background: rgba(91, 124, 250, 0.13);
}
.auto-reup-chip-row i.is-scan-ready {
  color: #54e995;
  background: rgba(38, 208, 119, 0.12);
}
.auto-reup-chip-row i.is-scan-scanning {
  color: #6ed8ff;
  background: rgba(55, 180, 255, 0.12);
}
.auto-reup-chip-row i.is-scan-error {
  color: #ff8d9b;
  background: rgba(255, 82, 104, 0.13);
}
.auto-reup-chip-row i.is-scan-login_required {
  color: #ffd166;
  background: rgba(255, 209, 102, 0.13);
}
.auto-reup-action-error {
  max-width: 680px;
  margin-top: 6px;
  color: #ff9aa6;
  font-size: 0.66rem;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.auto-reup-insight-panel {
  margin-top: 0;
  max-width: none;
  display: block;
  align-self: stretch;
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.auto-reup-insight-head {
  display: none;
}
.auto-reup-insight-head > span {
  border: 1px solid rgba(125,162,255,0.34);
  border-radius: 999px;
  padding: 3px 7px;
  color: #dfe7ff;
  background: rgba(91,124,250,0.18);
  font-size: 0.55rem;
  font-weight: 900;
}
.auto-reup-insight-head button {
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 999px;
  padding: 5px 9px;
  color: #aeb8cc;
  background: rgba(255,255,255,0.035);
  font-size: 0.64rem;
  font-weight: 850;
  cursor: pointer;
}
.auto-reup-insight-head button.auto-reup-insight-refresh {
  width: 21px;
  height: 21px;
  padding: 0;
  display: grid;
  place-items: center;
}
.auto-reup-insight-head button.auto-reup-insight-refresh.is-loading .auto-reup-glyph {
  animation: autoReupTokenSpin 0.75s linear infinite;
}
.auto-reup-action-insights {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 7px;
  margin-top: 0;
  height: 100%;
}
.auto-reup-action-insights span {
  min-width: 0;
  min-height: 58px;
  display: grid;
  align-content: center;
  gap: 3px;
  border: 1px solid rgba(125, 162, 255, 0.16);
  border-radius: 10px;
  padding: 8px 10px;
  background: linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.018));
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.045),
    0 10px 22px rgba(0, 0, 0, 0.08);
}
.auto-reup-action-insights b,
.auto-reup-action-insights small,
.auto-reup-action-insights em {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.auto-reup-action-insights b {
  color: #eef3ff;
  display: inline;
  font-size: 0.88rem;
  line-height: 1;
  font-weight: 950;
}
.auto-reup-action-insights small {
  display: inline;
  margin: 0 0 0 5px;
  color: #8f9aaf;
  font-size: 0.56rem;
  font-weight: 900;
  text-transform: uppercase;
}
.auto-reup-action-insights em {
  margin-top: 1px;
  color: #8995aa;
  font-size: 0.56rem;
  line-height: 1.2;
  font-style: normal;
  font-weight: 900;
}
.auto-reup-action-insights em.is-up {
  color: #4bf18e;
}
.auto-reup-action-insights em.is-down {
  color: #ff7a8a;
}
.auto-reup-action-insights em::after {
  content: " vs hôm qua";
  color: #667085;
  font-weight: 800;
}
.auto-reup-action-insights em.is-none::after {
  content: " chưa có mốc";
}
.auto-reup-action-right {
  display: grid;
  grid-template-columns: 54px 1fr;
  gap: 6px;
  align-items: center;
  align-self: start;
}
.auto-reup-progress-ring {
  width: 54px;
  height: 54px;
  border-radius: 15px;
  display: grid;
  place-items: center;
  text-align: center;
  background: rgba(91,124,250,0.12);
  border: 1px solid rgba(125,162,255,0.24);
}
.auto-reup-progress-ring b {
  font-size: 0.84rem;
}
.auto-reup-progress-ring small {
  display: block;
  color: #9ca6ba;
  font-size: 0.5rem;
  margin-top: -8px;
}
.auto-reup-action-counts {
  display: grid;
  gap: 3px;
}
.auto-reup-action-counts span {
  color: #aeb8c9;
  background: rgba(255,255,255,0.055);
}
.auto-reup-action-tools {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 5px;
}
.auto-reup-action-tools button,
.auto-reup-modal-head button {
  width: 27px;
  height: 27px;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 9px;
  display: grid;
  place-items: center;
  color: #e8ecf6;
  background: rgba(255,255,255,0.065);
  cursor: pointer;
}
.auto-reup-action-tools button.danger {
  color: #ff9aa4;
  background: rgba(255, 91, 111, 0.12);
  border-color: rgba(255, 91, 111, 0.22);
}
.auto-reup-action-tools button.is-scanning .auto-reup-glyph {
  animation: autoReupSpin 0.8s linear infinite;
}
@keyframes autoReupSpin {
  to { transform: rotate(360deg); }
}
.auto-reup-mini-list {
  display: grid;
  gap: 9px;
  max-height: 360px;
  overflow: auto;
  padding-right: 4px;
}
.auto-reup-mini-row,
.auto-reup-job-row {
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 15px;
  padding: 12px;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  background: rgba(255,255,255,0.045);
}
.auto-reup-mini-row b,
.auto-reup-job-row b {
  display: block;
  font-size: 0.9rem;
  margin-bottom: 4px;
}
.auto-reup-mini-row small,
.auto-reup-job-row small {
  display: -webkit-box;
  color: #9aa4b8;
  font-size: 0.76rem;
  line-height: 1.35;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.auto-reup-mini-row i {
  color: #4bf18e;
  background: rgba(52, 244, 135, 0.12);
}
.auto-reup-mini-row.is-stale {
  border-color: rgba(255, 209, 102, 0.2);
  opacity: 0.78;
}
.auto-reup-mini-row.is-stale i {
  color: #ffd166;
  background: rgba(255, 209, 102, 0.12);
}
.auto-reup-mini-row.is-degraded {
  border-color: rgba(255, 177, 66, 0.3);
  background: rgba(255, 177, 66, 0.055);
}
.auto-reup-mini-row.is-degraded i {
  color: #ffc66d;
  background: rgba(255, 177, 66, 0.14);
}
.auto-reup-mini-row.is-missing {
  border-color: rgba(255, 101, 118, 0.18);
}
.auto-reup-mini-row.is-missing i {
  color: #ff9aa4;
  background: rgba(255, 91, 111, 0.12);
}
.auto-reup-job-row i {
  color: #9fb2ff;
  background: rgba(91,124,250,0.12);
}
.auto-reup-job-row.is-processing,
.auto-reup-job-row.is-publishing {
  border-color: rgba(103, 215, 255, 0.26);
  background: rgba(55, 180, 255, 0.07);
}
.auto-reup-job-row.is-ready {
  border-color: rgba(255, 209, 102, 0.24);
  background: rgba(255, 209, 102, 0.055);
}
.auto-reup-job-row.is-ready i {
  color: #ffd166;
  background: rgba(255, 209, 102, 0.12);
}
.auto-reup-empty-mini {
  border: 1px dashed rgba(255,255,255,0.12);
  border-radius: 15px;
  padding: 16px;
  color: #9ca6bb;
  line-height: 1.45;
}
.auto-reup-note b {
  display: block;
  margin-bottom: 8px;
}
.auto-reup-note p {
  margin: 0;
  color: #a6afc0;
  line-height: 1.55;
}
.auto-reup-meta-panel {
  overflow: hidden;
}
.auto-reup-token-toolbar {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 8px;
}
.auto-reup-token-toolbar .auto-reup-token-guide-btn {
  grid-column: 1 / -1;
}
.auto-reup-token-toolbar button,
.auto-reup-token-detail button {
  min-height: 34px;
  border: 1px solid #354162;
  border-radius: 8px;
  background: #1b2131;
  color: #dce4ff;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
}
.auto-reup-token-toolbar button:hover,
.auto-reup-token-detail button:hover {
  border-color: #7185ff;
  background: #242c41;
}
.auto-reup-token-toolbar button:disabled,
.auto-reup-token-detail button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.auto-reup-token-accounts {
  display: grid;
  gap: 6px;
  max-height: 190px;
  overflow-y: auto;
  padding-right: 3px;
  margin-bottom: 10px;
}
.auto-reup-token-account {
  width: 100%;
  display: grid;
  grid-template-columns: 9px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border: 1px solid #2c3345;
  border-radius: 9px;
  background: #171b27;
  color: #edf1ff;
  text-align: left;
  cursor: pointer;
}
.auto-reup-token-account:hover,
.auto-reup-token-account.is-selected {
  border-color: #6d79eb;
  background: #1c2233;
}
.auto-reup-token-account span:nth-child(2) {
  min-width: 0;
  display: grid;
  gap: 2px;
}
.auto-reup-token-account b,
.auto-reup-token-account small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.auto-reup-token-account b {
  font-size: 11px;
}
.auto-reup-token-account small {
  color: #8f98ae;
  font-size: 9px;
}
.auto-reup-token-account i {
  color: #9aa5bf;
  font-size: 8px;
  font-style: normal;
  font-weight: 900;
  text-transform: uppercase;
}
.auto-reup-token-status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #7d879d;
  box-shadow: 0 0 0 3px rgba(125, 135, 157, 0.12);
}
.auto-reup-token-status.is-valid {
  background: #35dd82;
  box-shadow: 0 0 0 3px rgba(53, 221, 130, 0.12);
}
.auto-reup-token-status.is-expired,
.auto-reup-token-status.is-error {
  background: #ff6072;
  box-shadow: 0 0 0 3px rgba(255, 96, 114, 0.12);
}
.auto-reup-guide-backdrop {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(0,0,0,0.62);
  backdrop-filter: blur(8px);
}
.auto-reup-guide-modal {
  width: min(760px, calc(100vw - 32px));
  max-height: calc(100vh - 64px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(125,162,255,0.22);
  border-radius: 18px;
  background: #171b25;
  box-shadow: 0 28px 90px rgba(0,0,0,0.52);
}
.auto-reup-guide-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: flex-start;
  padding: 18px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  background: linear-gradient(135deg, rgba(91,124,250,0.15), rgba(255,255,255,0.035));
}
.auto-reup-guide-head p,
.auto-reup-guide-head h3 {
  margin: 0;
}
.auto-reup-guide-head p {
  color: #9fa9bd;
  font-size: 0.68rem;
  font-weight: 900;
  letter-spacing: 0.08em;
}
.auto-reup-guide-head h3 {
  margin-top: 4px;
  color: #f4f7ff;
  font-size: 1.04rem;
}
.auto-reup-guide-head button {
  width: 34px;
  height: 34px;
  border: 1px solid rgba(255,255,255,0.13);
  border-radius: 10px;
  color: #e7ecff;
  background: rgba(255,255,255,0.07);
  cursor: pointer;
}
.auto-reup-guide-body {
  min-height: 0;
  flex: 1;
  overflow: auto;
  display: grid;
  gap: 12px;
  padding: 16px 20px 34px;
  scrollbar-gutter: stable;
}
.auto-reup-guide-body::after {
  content: "";
  display: block;
  height: 10px;
}
.auto-reup-guide-body section {
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 13px;
  padding: 13px 15px;
  background: rgba(255,255,255,0.035);
}
.auto-reup-guide-body h4,
.auto-reup-guide-body p,
.auto-reup-guide-body ol,
.auto-reup-guide-body ul {
  margin: 0;
}
.auto-reup-guide-body h4 {
  color: #eef3ff;
  font-size: 0.9rem;
}
.auto-reup-guide-body ol,
.auto-reup-guide-body ul {
  padding-left: 18px;
  margin-top: 9px;
  color: #c3ccdc;
  font-size: 0.78rem;
  line-height: 1.55;
}
.auto-reup-guide-body p {
  margin-top: 9px;
  color: #94a0b6;
  font-size: 0.75rem;
  line-height: 1.5;
}
.auto-reup-meta-token {
  display: grid;
  gap: 10px;
}
.auto-reup-meta-token label {
  display: grid;
  gap: 7px;
  color: #aab3c4;
  font-size: 0.78rem;
  font-weight: 800;
}
.auto-reup-meta-token input,
.auto-reup-meta-token > label > select {
  width: 100%;
  min-height: 42px;
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 13px;
  background: rgba(255,255,255,0.06);
  color: #f8fafc;
  outline: none;
  padding: 0 13px;
}
.auto-reup-meta-token > label > select {
  appearance: none;
  cursor: pointer;
}
.auto-reup-meta-token input:focus,
.auto-reup-meta-token > label > select:focus {
  border-color: rgba(125,162,255,0.5);
  box-shadow: 0 0 0 3px rgba(91,124,250,0.12);
}
.auto-reup-token-settings {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.auto-reup-token-settings label {
  min-width: 0;
}
.auto-reup-token-settings select {
  width: 100%;
  min-height: 34px;
  border: 1px solid #343b50;
  border-radius: 8px;
  background: #202532;
  color: #f2f4ff;
  padding: 0 9px;
  font-size: 11px;
  outline: none;
}
.auto-reup-token-check {
  min-height: 34px;
  display: flex !important;
  flex-direction: row !important;
  align-items: center;
  gap: 7px !important;
  padding: 0 10px;
  border: 1px solid #343b50;
  border-radius: 8px;
  background: #202532;
}
.auto-reup-token-check input {
  width: 14px;
  height: 14px;
  min-height: 0;
  margin: 0;
  padding: 0;
  accent-color: #7185ff;
  box-shadow: none;
}
.auto-reup-meta-token button {
  min-height: 42px;
  border: 1px solid rgba(125,162,255,0.32);
  border-radius: 13px;
  background: linear-gradient(135deg, rgba(91,124,250,0.22), rgba(139,92,246,0.22));
  color: #fff;
  font-weight: 900;
  cursor: pointer;
}
.auto-reup-meta-token button:disabled {
  opacity: 0.62;
  cursor: wait;
}
.auto-reup-token-detail {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-top: 10px;
  padding: 10px;
  border: 1px solid #2c3345;
  border-radius: 10px;
  background: #11151f;
}
.auto-reup-token-detail > span {
  min-width: 0;
  display: grid;
  gap: 2px;
  color: #b4bdd2;
  font-size: 9px;
  overflow-wrap: anywhere;
}
.auto-reup-token-detail > span b {
  color: #7f899f;
  font-size: 8px;
  text-transform: uppercase;
}
.auto-reup-token-detail > p {
  grid-column: 1 / -1;
  margin: 0;
  padding: 7px 8px;
  border-radius: 7px;
  background: rgba(255, 96, 114, 0.09);
  color: #ff9ba7;
  font-size: 9px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.auto-reup-token-detail > div {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}
.auto-reup-token-detail button.danger {
  border-color: #71313c;
  background: #321820;
  color: #ff9aa6;
  padding-inline: 14px;
}
.auto-reup-meta-alert,
.auto-reup-meta-hint {
  margin-top: 12px;
  border-radius: 14px;
  padding: 12px;
  color: #b9c5d8;
  line-height: 1.45;
  background: rgba(91,124,250,0.09);
  border: 1px solid rgba(125,162,255,0.18);
}
.auto-reup-meta-alert {
  color: #52efa0;
  background: rgba(52,244,135,0.08);
  border-color: rgba(52,244,135,0.2);
  font-weight: 850;
}
.auto-reup-meta-alert b,
.auto-reup-meta-alert span,
.auto-reup-meta-alert small {
  display: block;
}
.auto-reup-meta-alert span {
  margin-top: 4px;
  color: #c7d2df;
  font-weight: 700;
}
.auto-reup-meta-alert small {
  margin-top: 5px;
  color: #91a0b7;
  font-weight: 750;
}
.auto-reup-meta-alert.is-error {
  color: #ff9aa4;
  background: rgba(255,91,111,0.1);
  border-color: rgba(255,91,111,0.24);
}
.auto-reup-meta-warnings {
  display: grid;
  gap: 7px;
  margin-top: 12px;
  max-height: 150px;
  overflow: auto;
}
.auto-reup-meta-warnings span {
  border: 1px solid rgba(255, 209, 102, 0.2);
  border-radius: 12px;
  padding: 9px 10px;
  color: #ffd98a;
  background: rgba(255, 209, 102, 0.08);
  font-size: 0.74rem;
  line-height: 1.4;
}
.auto-reup-page-summary {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.auto-reup-page-summary span {
  border-radius: 999px;
  padding: 6px 9px;
  color: #9ca9bc;
  background: rgba(255,255,255,0.055);
  font-size: 0.7rem;
  font-weight: 800;
}
.auto-reup-page-summary b {
  color: #4bf18e;
}
.auto-reup-page-summary .has-stale b {
  color: #ffd166;
}
.auto-reup-page-summary .has-degraded b {
  color: #ffbd59;
}
.auto-reup-page-search {
  width: 100%;
  min-height: 40px;
  box-sizing: border-box;
  margin-bottom: 10px;
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 12px;
  padding: 0 12px;
  color: #f8fafc;
  background: rgba(255,255,255,0.055);
  outline: none;
}
.auto-reup-page-search:focus {
  border-color: rgba(125,162,255,0.5);
  box-shadow: 0 0 0 3px rgba(91,124,250,0.1);
}
.auto-reup-page-list {
  max-height: 430px;
  gap: 10px;
}
.auto-reup-page-group {
  overflow: hidden;
  border: 1px solid rgba(125, 162, 255, 0.18);
  border-radius: 12px;
  background: rgba(10, 13, 22, 0.62);
}
.auto-reup-page-group-head {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.065);
  background: linear-gradient(135deg, rgba(91,124,250,0.13), rgba(139,92,246,0.055));
}
.auto-reup-page-group-head > span:nth-child(2) {
  min-width: 0;
  display: grid;
  gap: 2px;
}
.auto-reup-page-group-head b,
.auto-reup-page-group-head small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.auto-reup-page-group-head b {
  color: #f0f4ff;
  font-size: 0.72rem;
}
.auto-reup-page-group-head small {
  color: #8995aa;
  font-size: 0.61rem;
}
.auto-reup-page-group-head i {
  border-radius: 999px;
  padding: 4px 7px;
  color: #b9c5ff;
  background: rgba(113,133,255,0.12);
  font-size: 0.58rem;
  font-style: normal;
  font-weight: 900;
}
.auto-reup-page-group-list {
  display: grid;
  gap: 5px;
  padding: 6px;
}
.auto-reup-page-group-list .auto-reup-mini-row {
  border-radius: 8px;
  padding: 8px 9px;
  align-items: center;
  background: rgba(255,255,255,0.032);
}
.auto-reup-page-group-list .auto-reup-mini-row em {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: #8190b4;
  font-size: 0.56rem;
  font-style: normal;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.auto-reup-page-token-tools {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
}
.auto-reup-page-token-tools i {
  max-width: 74px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.auto-reup-page-token-tools button {
  width: 27px;
  height: 27px;
  padding: 0;
  border: 1px solid rgba(125, 162, 255, 0.22);
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #aabaff;
  background: rgba(91, 124, 250, 0.09);
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
}
.auto-reup-page-token-tools button:hover:not(:disabled) {
  border-color: rgba(125, 162, 255, 0.55);
  color: #edf1ff;
  background: rgba(91, 124, 250, 0.18);
}
.auto-reup-page-token-tools button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
.auto-reup-page-token-tools button.is-checking .auto-reup-glyph {
  animation: autoReupTokenSpin 0.75s linear infinite;
}
.auto-reup-mini-row.token-invalid,
.auto-reup-mini-row.token-error {
  border-color: rgba(255, 91, 111, 0.24);
}
.auto-reup-mini-row.token-invalid .auto-reup-page-token-tools i,
.auto-reup-mini-row.token-error .auto-reup-page-token-tools i {
  color: #ff9aa4;
  background: rgba(255, 91, 111, 0.12);
}
.auto-reup-mini-row.token-unknown .auto-reup-page-token-tools i {
  color: #b7c0d2;
  background: rgba(183, 192, 210, 0.09);
}
@keyframes autoReupTokenSpin {
  to { transform: rotate(360deg); }
}
.auto-reup-meta-page {
  border: 1px solid rgba(52,244,135,0.16);
  border-radius: 14px;
  padding: 11px;
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  background: rgba(52,244,135,0.055);
}
.auto-reup-meta-page b {
  display: block;
  font-size: 0.88rem;
  margin-bottom: 4px;
}
.auto-reup-meta-page small {
  color: #9ba6b9;
  font-size: 0.74rem;
}
.auto-reup-meta-page i {
  border-radius: 999px;
  padding: 5px 8px;
  font-size: 0.64rem;
  font-style: normal;
  font-weight: 950;
  color: #43f18d;
  background: rgba(52,244,135,0.12);
}
.auto-reup-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(3, 5, 10, 0.74);
  backdrop-filter: blur(10px);
}
.auto-reup-modal {
  width: min(1220px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  overflow: auto;
  border-radius: 24px;
  padding: 24px;
  animation: autoReupModal 0.2s ease both;
}
.auto-reup-runtime-backdrop {
  z-index: 96;
}
.auto-reup-runtime-modal {
  width: min(1320px, calc(100vw - 48px));
  overflow: hidden;
}
.auto-reup-runtime-loading,
.auto-reup-runtime-error {
  min-height: 280px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  color: #aeb8ca;
  background: rgba(0,0,0,0.22);
  border: 1px dashed rgba(255,255,255,0.12);
}
.auto-reup-runtime-error {
  color: #ff9ba7;
}
.auto-reup-runtime-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.auto-reup-runtime-overview > div {
  min-height: 104px;
  border-radius: 17px;
  padding: 15px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  border: 1px solid rgba(255,255,255,0.09);
  background: rgba(255,255,255,0.04);
}
.auto-reup-runtime-overview small,
.auto-reup-runtime-card-head p {
  color: #8f99ad;
  font-size: 0.66rem;
  font-weight: 900;
  letter-spacing: 0.06em;
}
.auto-reup-runtime-overview b {
  margin-top: 7px;
  font-size: 1.24rem;
  letter-spacing: 0;
}
.auto-reup-runtime-overview > div > span:not(.auto-reup-live-dot) {
  margin-top: 5px;
  color: #909bad;
  font-size: 0.72rem;
}
.auto-reup-runtime-phase {
  position: relative;
  padding-left: 43px !important;
  border-color: rgba(67, 226, 143, 0.22) !important;
  background: linear-gradient(135deg, rgba(40, 208, 124, 0.1), rgba(255,255,255,0.03)) !important;
}
.auto-reup-live-dot {
  position: absolute;
  left: 16px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #43e28f;
  box-shadow: 0 0 0 7px rgba(67,226,143,0.10), 0 0 20px rgba(67,226,143,0.4);
  animation: autoReupPulse 1.4s ease-in-out infinite;
}
.auto-reup-runtime-phase.is-paused .auto-reup-live-dot {
  background: #f6c85f;
  box-shadow: 0 0 0 7px rgba(246,200,95,0.1);
  animation: none;
}
@keyframes autoReupPulse {
  50% { transform: scale(0.72); opacity: 0.62; }
}
.auto-reup-runtime-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(0, 0.92fr);
  gap: 16px;
}
.auto-reup-runtime-card {
  min-width: 0;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 19px;
  padding: 16px;
  background: rgba(0,0,0,0.2);
}
.auto-reup-runtime-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 13px;
}
.auto-reup-runtime-card-head p,
.auto-reup-runtime-card-head h3 {
  margin: 0;
}
.auto-reup-runtime-card-head h3 {
  margin-top: 4px;
  font-size: 1rem;
}
.auto-reup-runtime-card-head > span {
  min-width: 30px;
  height: 30px;
  padding: 0 9px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: #b7c5ff;
  background: rgba(91,124,250,0.13);
  border: 1px solid rgba(125,162,255,0.2);
  font-size: 0.72rem;
  font-weight: 900;
}
.auto-reup-runtime-jobs,
.auto-reup-event-stream {
  max-height: min(480px, calc(100vh - 365px));
  overflow: auto;
  display: grid;
  align-content: start;
  gap: 9px;
  padding-right: 5px;
}
.auto-reup-runtime-jobs article {
  border-radius: 15px;
  padding: 12px;
  border: 1px solid rgba(97,145,255,0.24);
  background: rgba(34,75,150,0.1);
}
.auto-reup-runtime-jobs article.is-ready {
  border-color: rgba(67,226,143,0.2);
  background: rgba(40,208,124,0.07);
}
.auto-reup-runtime-job-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.auto-reup-runtime-job-top > span {
  min-width: 0;
}
.auto-reup-runtime-job-top b,
.auto-reup-runtime-job-top small {
  display: block;
}
.auto-reup-runtime-job-top b {
  max-width: 440px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 0.83rem;
}
.auto-reup-runtime-job-top small {
  margin-top: 4px;
  color: #9ba7ba;
  font-size: 0.69rem;
}
.auto-reup-runtime-job-top i {
  flex: 0 0 auto;
  color: #d7e1ff;
  font-size: 0.72rem;
  font-style: normal;
  font-weight: 900;
}
.auto-reup-runtime-progress {
  height: 5px;
  margin-top: 10px;
  overflow: hidden;
  border-radius: 99px;
  background: rgba(255,255,255,0.08);
}
.auto-reup-runtime-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #5f7cff, #9e55f5, #24c6b2);
  transition: width 0.35s ease;
}
.auto-reup-runtime-job-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 9px;
  color: #8793a8;
  font-size: 0.66rem;
}
.auto-reup-runtime-job-meta .is-error {
  color: #ff8d9b;
}
.auto-reup-event-stream article {
  position: relative;
  min-height: 42px;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 10px;
  padding: 8px 10px;
  border-radius: 13px;
  background: rgba(255,255,255,0.035);
}
.auto-reup-event-dot {
  width: 8px;
  height: 8px;
  margin-top: 5px;
  border-radius: 50%;
  background: #65a3ff;
  box-shadow: 0 0 0 4px rgba(101,163,255,0.1);
}
.auto-reup-event-stream article.is-success .auto-reup-event-dot {
  background: #43e28f;
  box-shadow: 0 0 0 4px rgba(67,226,143,0.1);
}
.auto-reup-event-stream article.is-error .auto-reup-event-dot {
  background: #ff6174;
  box-shadow: 0 0 0 4px rgba(255,97,116,0.1);
}
.auto-reup-event-stream b,
.auto-reup-event-stream small {
  display: block;
}
.auto-reup-event-stream b {
  color: #dce3ef;
  font-size: 0.76rem;
  line-height: 1.35;
}
.auto-reup-event-stream small {
  margin-top: 4px;
  color: #7f8ba0;
  font-size: 0.64rem;
}
.auto-reup-runtime-empty {
  min-height: 100px;
  border: 1px dashed rgba(255,255,255,0.1);
  border-radius: 14px;
  display: grid;
  place-items: center;
  padding: 20px;
  text-align: center;
  color: #8995aa;
  font-size: 0.76rem;
  line-height: 1.5;
}
.auto-reup-modal-head {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid rgba(255,255,255,0.09);
}
.auto-reup-action-form {
  display: grid;
  gap: 14px;
}
.auto-reup-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(360px, 0.88fr);
  gap: 14px;
  align-items: start;
}
.auto-reup-form-card {
  position: relative;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 16px;
  padding: 16px;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.015)),
    rgba(0,0,0,0.18);
  display: grid;
  gap: 12px;
}
.auto-reup-form-card h3 {
  margin: 0;
  font-size: 1rem;
}
.auto-reup-form-card p {
  margin: 4px 0 0;
  color: #9ba5b8;
  font-size: 0.8rem;
}
.auto-reup-step {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 28px;
  height: 28px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: #bfcaff;
  background: rgba(91, 124, 250, 0.14);
  border: 1px solid rgba(125, 162, 255, 0.22);
  font-weight: 900;
}
.auto-reup-form-card label {
  display: grid;
  gap: 8px;
  color: #aeb7ca;
  font-size: 0.78rem;
  font-weight: 800;
}
.auto-reup-form-card input,
.auto-reup-form-card select,
.auto-reup-form-card textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 42px;
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 11px;
  background: rgba(255,255,255,0.065);
  color: #fff;
  padding: 0 13px;
  outline: none;
}
.auto-reup-form-card select option {
  color: #111827;
}
.auto-reup-form-card textarea {
  min-height: 84px;
  padding: 12px 13px;
  line-height: 1.45;
  resize: vertical;
}
.auto-reup-two,
.auto-reup-three,
.auto-reup-schedule-grid {
  display: grid;
  gap: 12px;
}
.auto-reup-two {
  grid-template-columns: 1fr 1fr;
}
.auto-reup-three {
  grid-template-columns: repeat(3, 1fr);
}
.auto-reup-schedule-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.auto-reup-selection-note {
  border: 1px solid rgba(125,162,255,0.18);
  border-radius: 15px;
  padding: 14px;
  display: grid;
  gap: 4px;
  background: linear-gradient(135deg, rgba(91,124,250,0.10), rgba(255,255,255,0.025));
}
.auto-reup-selection-note span,
.auto-reup-selection-note small {
  color: #8f9ab0;
  font-size: 0.72rem;
}
.auto-reup-selection-note b {
  color: #eef3ff;
  font-size: 0.9rem;
}
.auto-reup-field-warning,
.auto-reup-random-note,
.auto-reup-schedule-preview {
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 0.76rem;
  line-height: 1.4;
}
.auto-reup-field-warning {
  color: #ffd8a8;
  border: 1px solid rgba(251,191,36,0.22);
  background: rgba(251,191,36,0.08);
}
.auto-reup-random-note {
  color: #aab7d4;
  border: 1px solid rgba(103,215,255,0.14);
  background: rgba(103,215,255,0.055);
}
.auto-reup-selection-note small {
  line-height: 1.4;
}
.auto-reup-field-warning,
.auto-reup-random-note {
  font-size: 0.82rem;
}
.auto-reup-manual-times {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  max-height: 178px;
  overflow: auto;
  padding-right: 4px;
}
.auto-reup-manual-times label {
  min-width: 0;
}
.auto-reup-schedule-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  color: #b9c6ea;
  border: 1px solid rgba(125,162,255,0.16);
  background: rgba(91,124,250,0.07);
}
.auto-reup-schedule-preview span {
  border-radius: 999px;
  padding: 5px 8px;
  color: #dce6ff;
  background: rgba(255,255,255,0.065);
  font-size: 0.7rem;
  font-weight: 850;
}
.auto-reup-toggle-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.auto-reup-pipeline-toggle {
  min-height: 78px;
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  background:
    linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.022));
  color: #e8edf8;
  text-align: left;
  padding: 12px;
  cursor: pointer;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  column-gap: 10px;
  align-items: start;
}
.auto-reup-pipeline-toggle span {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  display: block;
  margin: 1px 0 0;
  background: rgba(255,255,255,0.12);
  box-shadow: inset 0 0 0 5px rgba(8,10,16,0.9);
}
.auto-reup-pipeline-toggle.is-on {
  border-color: rgba(125,162,255,0.64);
  background: rgba(91,124,250,0.14);
}
.auto-reup-pipeline-toggle.is-on span {
  background: #7d8cff;
  box-shadow: inset 0 0 0 4px rgba(8,10,16,0.9), 0 0 0 4px rgba(125,162,255,0.16);
}
.auto-reup-pipeline-toggle b,
.auto-reup-pipeline-toggle small {
  display: block;
  grid-column: 2;
}
.auto-reup-pipeline-toggle b {
  margin-top: 0;
  font-size: 0.84rem;
  line-height: 1.2;
}
.auto-reup-pipeline-toggle small {
  margin-top: 4px;
  color: #9ca6ba;
  font-size: 0.71rem;
  line-height: 1.35;
}
.auto-reup-creative-panel {
  border: 1px solid rgba(125,162,255,0.16);
  border-radius: 15px;
  padding: 12px;
  display: grid;
  gap: 11px;
  background:
    linear-gradient(135deg, rgba(91,124,250,0.09), rgba(103,215,255,0.035)),
    rgba(0,0,0,0.16);
}
.auto-reup-creative-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: baseline;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.auto-reup-creative-head b {
  color: #eef3ff;
  font-size: 0.86rem;
}
.auto-reup-creative-head span {
  color: #9ca6ba;
  font-size: 0.72rem;
  line-height: 1.35;
  text-align: right;
}
.auto-reup-creative-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.auto-reup-creative-panel > .auto-reup-pipeline-toggle {
  min-height: 70px;
}
.auto-reup-creative-audio-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 132px;
  gap: 10px;
  align-items: start;
}
.auto-reup-file-field,
.auto-reup-volume-field {
  min-width: 0;
}
.auto-reup-file-field input[type="file"] {
  padding: 8px 10px;
  font-size: 0.75rem;
  min-height: 42px;
}
.auto-reup-field-hint {
  display: block;
  color: #8f9ab0;
  font-size: 0.69rem;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
}
.auto-reup-clean-test {
  grid-template-columns: 0.65fr 1fr 1fr;
  align-items: start;
}
.auto-reup-clean-test textarea {
  min-height: 128px;
}
.auto-reup-clean-actions {
  display: grid;
  gap: 10px;
}
.auto-reup-clean-actions button {
  min-height: 42px;
  border: 1px solid rgba(125,162,255,0.32);
  border-radius: 12px;
  color: #fff;
  background: rgba(91,124,250,0.13);
  font-weight: 850;
  cursor: pointer;
}
.auto-reup-clean-actions pre {
  min-height: 76px;
  max-height: 128px;
  overflow: auto;
  white-space: pre-wrap;
  margin: 0;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 12px;
  padding: 12px;
  color: #dce5f5;
  background: rgba(0,0,0,0.22);
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 0.78rem;
  line-height: 1.45;
}
.auto-reup-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}
.auto-reup-modal-actions button {
  min-width: 136px;
  padding: 0 18px;
  background: rgba(255,255,255,0.06);
}
button:disabled,
input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
@keyframes autoReupIn {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes autoReupModal {
  from { opacity: 0; transform: translateY(12px) scale(0.985); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@media (max-width: 1260px) {
  .auto-reup-dashboard,
  .auto-reup-form-grid,
  .auto-reup-clean-test,
  .auto-reup-runtime-grid {
    grid-template-columns: 1fr;
  }
  .auto-reup-runtime-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .auto-reup-stats {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 820px) {
  .auto-reup-hero {
    flex-direction: column;
    align-items: stretch;
  }
  .auto-reup-stats,
  .auto-reup-two,
  .auto-reup-three,
  .auto-reup-schedule-grid,
  .auto-reup-manual-times,
  .auto-reup-toggle-grid,
  .auto-reup-creative-options,
  .auto-reup-creative-audio-row,
  .auto-reup-action {
    grid-template-columns: 1fr;
  }
  .auto-reup-creative-head {
    display: grid;
  }
  .auto-reup-creative-head span {
    text-align: left;
  }
  .auto-reup-action-right {
    grid-template-columns: 1fr;
  }
  .auto-reup-runtime-overview {
    grid-template-columns: 1fr;
  }
  .auto-reup-progress-ring {
    width: 100%;
    height: auto;
    min-height: 68px;
  }
  .auto-reup-modal-backdrop {
    padding: 12px;
  }
  .auto-reup-modal {
    width: calc(100vw - 24px);
    max-height: calc(100vh - 24px);
  }
}
`;

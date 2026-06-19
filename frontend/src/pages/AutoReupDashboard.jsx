import { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API = "http://127.0.0.1:8000";

const emptyActionForm = {
  name: "",
  target_page_id: "",
  platform: "facebook",
  source_url: "",
  template_id: "",
  translate_caption: true,
  apply_frame: true,
  content_cleaner_enabled: true,
  enabled: true,
  daily_limit: 3,
  active_from: "09:00",
  active_to: "22:30",
  min_gap_minutes: 180,
  scan_interval_minutes: 60,
  notes: "",
};

const emptyQuickPage = {
  name: "",
  page_id: "",
};

const platforms = [
  { value: "facebook", label: "Facebook Page" },
  { value: "tiktok", label: "TikTok" },
  { value: "manual", label: "Manual Folder" },
];

function Glyph({ name }) {
  return <span className={`auto-reup-glyph auto-reup-glyph-${name}`} aria-hidden="true" />;
}

export default function AutoReupDashboard() {
  const [summary, setSummary] = useState({});
  const [pages, setPages] = useState([]);
  const [actions, setActions] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [actionForm, setActionForm] = useState(emptyActionForm);
  const [quickPage, setQuickPage] = useState(emptyQuickPage);
  const [editingAction, setEditingAction] = useState(null);
  const [isActionModalOpen, setActionModalOpen] = useState(false);
  const [contentInput, setContentInput] = useState("");
  const [cleanResult, setCleanResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [metaToken, setMetaToken] = useState("");
  const [metaBusy, setMetaBusy] = useState(false);
  const [metaResult, setMetaResult] = useState(null);

  const activeActions = useMemo(
    () => actions.filter((action) => action.enabled),
    [actions]
  );

  const queuedJobs = useMemo(
    () => jobs.filter((job) => job.status === "queued").slice(0, 6),
    [jobs]
  );

  const loadData = async () => {
    const [summaryRes, pagesRes, actionsRes, jobsRes] = await Promise.all([
      axios.get(`${API}/auto-reup/summary`),
      axios.get(`${API}/auto-reup/pages`),
      axios.get(`${API}/auto-reup/actions`),
      axios.get(`${API}/auto-reup/jobs`, { params: { limit: 80 } }),
    ]);

    setSummary(summaryRes.data || {});
    setPages(pagesRes.data.pages || []);
    setActions(actionsRes.data.actions || []);
    setJobs(jobsRes.data.jobs || []);
  };

  useEffect(() => {
    loadData().catch((error) => console.error(error));
  }, []);

  const openCreateAction = () => {
    setEditingAction(null);
    setActionForm({
      ...emptyActionForm,
      target_page_id: pages[0]?.id || "",
    });
    setQuickPage(emptyQuickPage);
    setContentInput("");
    setCleanResult(null);
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
      content_cleaner_enabled: Boolean(action.content_cleaner_enabled),
      enabled: Boolean(action.enabled),
      daily_limit: Number(action.daily_limit || 3),
      active_from: action.active_from || "09:00",
      active_to: action.active_to || "22:30",
      min_gap_minutes: Number(action.min_gap_minutes || 180),
      scan_interval_minutes: Number(action.scan_interval_minutes || 60),
      notes: action.notes || "",
    });
    setQuickPage(emptyQuickPage);
    setContentInput("");
    setCleanResult(null);
    setActionModalOpen(true);
  };

  const closeActionModal = () => {
    setActionModalOpen(false);
    setEditingAction(null);
    setActionForm(emptyActionForm);
    setQuickPage(emptyQuickPage);
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

  const saveAction = async (event) => {
    event.preventDefault();

    if (!actionForm.name.trim()) {
      alert("Nhap ten action truoc.");
      return;
    }

    if (!actionForm.source_url.trim()) {
      alert("Nhap link nguon reup truoc.");
      return;
    }

    setBusy(true);
    try {
      let targetPageId = actionForm.target_page_id;

      if (!targetPageId && quickPage.name.trim()) {
        const pageRes = await axios.post(`${API}/auto-reup/pages`, {
          name: quickPage.name.trim(),
          page_id: quickPage.page_id.trim(),
          is_enabled: true,
          daily_limit: actionForm.daily_limit,
          active_from: actionForm.active_from,
          active_to: actionForm.active_to,
          min_gap_minutes: actionForm.min_gap_minutes,
        });
        targetPageId = pageRes.data.page.id;
      }

      if (!targetPageId) {
        alert("Chon fanpage dich hoac tao nhanh fanpage moi.");
        setBusy(false);
        return;
      }

      const payload = {
        ...actionForm,
        target_page_id: targetPageId,
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

  const importMetaPages = async () => {
    const token = metaToken.trim();
    if (!token) {
      alert("Nhap Meta user access token truoc.");
      return;
    }

    setMetaBusy(true);
    setMetaResult(null);
    try {
      const res = await axios.post(`${API}/auto-reup/meta/import-pages`, {
        access_token: token,
      });
      setMetaResult(res.data);
      setMetaToken("");
      await loadData();
    } catch (error) {
      console.error(error);
      setMetaResult({
        error: error.response?.data?.detail || "Khong import duoc fanpage tu Meta.",
      });
    } finally {
      setMetaBusy(false);
    }
  };

  return (
    <div className="auto-reup-shell">
      <style>{autoReupCss}</style>

      <header className="auto-reup-hero">
        <div>
          <p>AUTO REUP CONTROL</p>
          <h1>Fanpage Reup Dashboard</h1>
          <span>
            Quan ly action reup, lich dang, pipeline xu ly va content sach link. Moi action co the bat/tat/sua/xoa rieng.
          </span>
        </div>
        <button type="button" className="auto-reup-add-hero" onClick={openCreateAction}>
          <Glyph name="plus" />
          Them Action
        </button>
      </header>

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
            <button type="button" className="auto-reup-soft-btn" onClick={openCreateAction}>
              <Glyph name="plus" />
              Them Action
            </button>
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
              {actions.map((action) => (
                <ActionCard
                  key={action.id}
                  action={action}
                  busy={busy}
                  onToggle={() => toggleAction(action)}
                  onEdit={() => openEditAction(action)}
                  onDelete={() => removeAction(action)}
                />
              ))}
            </div>
          )}
        </section>

        <aside className="auto-reup-side-stack">
          <section className="auto-reup-panel">
            <div className="auto-reup-section-head compact">
              <div>
                <p>FANPAGES</p>
                <h2>Page da ket noi</h2>
              </div>
              <span>{pages.length}</span>
            </div>
            <div className="auto-reup-mini-list">
              {pages.length === 0 ? (
                <div className="auto-reup-empty-mini">Chua co fanpage. Co the tao nhanh khi them action.</div>
              ) : (
                pages.slice(0, 6).map((page) => (
                  <div key={page.id} className="auto-reup-mini-row">
                    <span>
                      <b>{page.name}</b>
                      <small>{page.page_id || "waiting Meta API"}</small>
                    </span>
                    <i>{page.is_enabled ? "ON" : "OFF"}</i>
                  </div>
                ))
              )}
            </div>
          </section>

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
                      <small>{job.clean_content || "No content"}</small>
                    </span>
                    <i>{job.status}</i>
                  </div>
                ))
              )}
            </div>
          </section>

          <MetaConnectPanel
            pages={pages}
            metaToken={metaToken}
            setMetaToken={setMetaToken}
            metaBusy={metaBusy}
            metaResult={metaResult}
            onImport={importMetaPages}
          />
        </aside>
      </main>

      {isActionModalOpen ? (
        <ActionModal
          pages={pages}
          form={actionForm}
          setForm={setActionForm}
          quickPage={quickPage}
          setQuickPage={setQuickPage}
          editingAction={editingAction}
          busy={busy}
          contentInput={contentInput}
          setContentInput={setContentInput}
          cleanResult={cleanResult}
          onClean={cleanContent}
          onSave={saveAction}
          onClose={closeActionModal}
        />
      ) : null}
    </div>
  );
}

function MetaConnectPanel({ pages, metaToken, setMetaToken, metaBusy, metaResult, onImport }) {
  const connectedPages = pages.filter((page) => page.has_page_access_token);

  return (
    <section className="auto-reup-panel auto-reup-meta-panel">
      <div className="auto-reup-section-head compact">
        <div>
          <p>META API</p>
          <h2>Ket noi fanpage</h2>
        </div>
        <span>{connectedPages.length}</span>
      </div>

      <div className="auto-reup-meta-token">
        <label>
          User access token
          <input
            type="password"
            value={metaToken}
            onChange={(event) => setMetaToken(event.target.value)}
            placeholder="Paste token co quyen quan ly page..."
            autoComplete="off"
          />
        </label>
        <button type="button" onClick={onImport} disabled={metaBusy}>
          {metaBusy ? "Dang import..." : "Import fanpage"}
        </button>
      </div>

      {metaResult?.error ? (
        <div className="auto-reup-meta-alert is-error">{metaResult.error}</div>
      ) : metaResult ? (
        <div className="auto-reup-meta-alert">
          Import {metaResult.imported || 0} page moi, cap nhat {metaResult.updated || 0} page.
        </div>
      ) : (
        <div className="auto-reup-meta-hint">
          Token chi dung de lay danh sach page va page token. UI se khong luu token sau khi import.
        </div>
      )}

      <div className="auto-reup-meta-pages">
        {connectedPages.length === 0 ? (
          <div className="auto-reup-empty-mini">Chua co page nao da ket noi page token.</div>
        ) : (
          connectedPages.slice(0, 5).map((page) => (
            <div key={page.id} className="auto-reup-meta-page">
              <span>
                <b>{page.name}</b>
                <small>{page.meta_category || page.page_id}</small>
              </span>
              <i>READY</i>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function ActionCard({ action, busy, onToggle, onEdit, onDelete }) {
  const total = Number(action.progress_total || 0);
  const scanned = Number(action.progress_scanned || 0);
  const posted = Number(action.progress_posted || 0);
  const errors = Number(action.progress_errors || 0);
  const progress = total > 0 ? Math.min(100, Math.round((scanned / total) * 100)) : 0;
  const pipeline = [
    action.translate_caption ? "Translate" : null,
    action.apply_frame ? "Frame" : null,
  ].filter(Boolean);

  return (
    <article className={`auto-reup-action ${action.enabled ? "is-running" : "is-paused"}`}>
      <div className="auto-reup-action-main">
        <div className="auto-reup-action-icon">
          {action.enabled ? <Glyph name="play" /> : <Glyph name="pause" />}
        </div>
        <div className="auto-reup-action-info">
          <div className="auto-reup-action-title">
            <h3>{action.name}</h3>
            <span>{action.enabled ? "ACTIVE" : "PAUSED"}</span>
          </div>
          <div className="auto-reup-action-meta">
            <span><Glyph name="link" /> {action.platform}</span>
            <span><Glyph name="clock" /> {action.daily_limit}/ngay - {action.min_gap_minutes} phut</span>
            <span>{action.target_page_name || "Chua gan fanpage"}</span>
          </div>
          <div className="auto-reup-action-url">{action.source_url}</div>
          <div className="auto-reup-chip-row">
            {pipeline.length ? pipeline.map((item) => <i key={item}>{item}</i>) : <i>No pipeline</i>}
            {action.template_id ? <i>Template: {action.template_id}</i> : <i>No template</i>}
            {action.content_cleaner_enabled ? <i>Clean content</i> : null}
          </div>
        </div>
      </div>

      <div className="auto-reup-action-right">
        <div className="auto-reup-progress-ring">
          <b>{progress}%</b>
          <small>{posted} posted</small>
        </div>
        <div className="auto-reup-action-counts">
          <span>{total} total</span>
          <span>{scanned} scanned</span>
          <span>{errors} errors</span>
        </div>
        <div className="auto-reup-action-tools">
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

function ActionModal({
  pages,
  form,
  setForm,
  quickPage,
  setQuickPage,
  editingAction,
  busy,
  contentInput,
  setContentInput,
  cleanResult,
  onClean,
  onSave,
  onClose,
}) {
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
              <h3>Thong tin action</h3>
              <label>
                Ten action
                <input
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
                  placeholder="VD: Reup Page A sang Meme Vietnam"
                />
              </label>
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
                  Template ID
                  <input
                    value={form.template_id}
                    onChange={(event) => setForm({ ...form, template_id: event.target.value })}
                    placeholder="De trong neu chua dung frame"
                  />
                </label>
              </div>
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
              <div className="auto-reup-step">2</div>
              <h3>Fanpage dich</h3>
              <label>
                Chon fanpage
                <select
                  value={form.target_page_id}
                  onChange={(event) => setForm({ ...form, target_page_id: event.target.value })}
                >
                  <option value="">Chon fanpage hoac tao nhanh ben duoi</option>
                  {pages.map((page) => (
                    <option key={page.id} value={page.id}>
                      {page.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="auto-reup-quick-page">
                <b>Tao nhanh fanpage neu chua co</b>
                <input
                  value={quickPage.name}
                  onChange={(event) => setQuickPage({ ...quickPage, name: event.target.value })}
                  placeholder="Ten fanpage"
                  disabled={Boolean(form.target_page_id)}
                />
                <input
                  value={quickPage.page_id}
                  onChange={(event) => setQuickPage({ ...quickPage, page_id: event.target.value })}
                  placeholder="Facebook Page ID (co the bo trong)"
                  disabled={Boolean(form.target_page_id)}
                />
              </div>
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
                  title="Apply Frame"
                  desc="Ghep vao frame template da chon."
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
            </section>

            <section className="auto-reup-form-card">
              <div className="auto-reup-step">4</div>
              <h3>Lich dang</h3>
              <div className="auto-reup-three">
                <label>
                  Bai/ngay
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={form.daily_limit}
                    onChange={(event) => setForm({ ...form, daily_limit: Number(event.target.value) })}
                  />
                </label>
                <label>
                  Cach nhau phut
                  <input
                    type="number"
                    min="15"
                    value={form.min_gap_minutes}
                    onChange={(event) => setForm({ ...form, min_gap_minutes: Number(event.target.value) })}
                  />
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
              </div>
              <div className="auto-reup-two">
                <label>
                  Tu gio
                  <input
                    type="time"
                    value={form.active_from}
                    onChange={(event) => setForm({ ...form, active_from: event.target.value })}
                  />
                </label>
                <label>
                  Den gio
                  <input
                    type="time"
                    value={form.active_to}
                    onChange={(event) => setForm({ ...form, active_to: event.target.value })}
                  />
                </label>
              </div>
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
  padding: 24px clamp(16px, 2.2vw, 30px) 42px;
  color: #f8fafc;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
.auto-reup-glyph-link::before { content: "#"; font-size: 0.8em; font-weight: 950; }
.auto-reup-glyph-clock::before { content: "T"; font-size: 0.76em; font-weight: 950; }
.auto-reup-glyph-shield::before { content: "A"; font-size: 1.1em; font-weight: 950; }
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
  margin: 0 auto 18px;
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 14px;
}
.auto-reup-stat {
  min-height: 94px;
  border-radius: 18px;
  padding: 18px;
}
.auto-reup-stat span {
  display: block;
  color: #9aa3b8;
  font-size: 0.78rem;
  font-weight: 750;
}
.auto-reup-stat b {
  display: block;
  margin-top: 12px;
  font-size: 2rem;
  line-height: 1;
}
.auto-reup-stat.is-green b { color: #43f18d; }
.auto-reup-stat.is-blue b { color: #67d7ff; }
.auto-reup-stat.is-red b { color: #ff6576; }
.auto-reup-dashboard {
  max-width: 1536px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.36fr);
  gap: 18px;
  align-items: start;
}
.auto-reup-panel {
  border-radius: 24px;
  padding: clamp(20px, 2vw, 28px);
}
.auto-reup-side-stack {
  display: grid;
  gap: 18px;
}
.auto-reup-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.auto-reup-section-head.compact {
  margin-bottom: 14px;
}
.auto-reup-section-head h2,
.auto-reup-modal-head h2 {
  margin: 4px 0 0;
  font-size: 1.32rem;
}
.auto-reup-section-head > span {
  color: #a8b4ff;
  font-weight: 900;
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
  gap: 12px;
  max-height: 620px;
  overflow: auto;
  padding-right: 6px;
}
.auto-reup-action {
  border: 1px solid rgba(125, 162, 255, 0.20);
  border-radius: 20px;
  padding: 16px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 220px;
  gap: 16px;
  background:
    linear-gradient(135deg, rgba(91,124,250,0.11), rgba(14,16,23,0.34)),
    rgba(255,255,255,0.035);
}
.auto-reup-action.is-paused {
  border-color: rgba(255,255,255,0.11);
  background: rgba(255,255,255,0.035);
}
.auto-reup-action-main {
  min-width: 0;
  display: flex;
  gap: 14px;
}
.auto-reup-action-icon {
  width: 44px;
  height: 44px;
  flex: 0 0 auto;
  border-radius: 15px;
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
  gap: 10px;
  min-width: 0;
}
.auto-reup-action-title h3 {
  margin: 0;
  font-size: 1.02rem;
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
  padding: 5px 9px;
  font-size: 0.68rem;
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
  gap: 8px 14px;
  margin-top: 10px;
  color: #a7b0c3;
  font-size: 0.78rem;
}
.auto-reup-action-meta span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.auto-reup-action-url {
  margin-top: 9px;
  color: #cbd5e1;
  font-size: 0.79rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.auto-reup-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
}
.auto-reup-chip-row i {
  color: #bfccff;
  background: rgba(91, 124, 250, 0.13);
}
.auto-reup-action-right {
  display: grid;
  grid-template-columns: 82px 1fr;
  gap: 10px;
  align-items: center;
}
.auto-reup-progress-ring {
  width: 82px;
  height: 82px;
  border-radius: 26px;
  display: grid;
  place-items: center;
  text-align: center;
  background: rgba(91,124,250,0.12);
  border: 1px solid rgba(125,162,255,0.24);
}
.auto-reup-progress-ring b {
  font-size: 1.15rem;
}
.auto-reup-progress-ring small {
  display: block;
  color: #9ca6ba;
  font-size: 0.68rem;
  margin-top: -12px;
}
.auto-reup-action-counts {
  display: grid;
  gap: 6px;
}
.auto-reup-action-counts span {
  color: #aeb8c9;
  background: rgba(255,255,255,0.055);
}
.auto-reup-action-tools {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.auto-reup-action-tools button,
.auto-reup-modal-head button {
  width: 36px;
  height: 36px;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 12px;
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
.auto-reup-job-row i {
  color: #9fb2ff;
  background: rgba(91,124,250,0.12);
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
.auto-reup-meta-token input {
  width: 100%;
  min-height: 42px;
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 13px;
  background: rgba(255,255,255,0.06);
  color: #f8fafc;
  outline: none;
  padding: 0 13px;
}
.auto-reup-meta-token input:focus {
  border-color: rgba(125,162,255,0.5);
  box-shadow: 0 0 0 3px rgba(91,124,250,0.12);
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
.auto-reup-meta-alert.is-error {
  color: #ff9aa4;
  background: rgba(255,91,111,0.1);
  border-color: rgba(255,91,111,0.24);
}
.auto-reup-meta-pages {
  display: grid;
  gap: 9px;
  margin-top: 12px;
  max-height: 230px;
  overflow: auto;
  padding-right: 4px;
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
.auto-reup-modal-head {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  padding-bottom: 18px;
  margin-bottom: 18px;
  border-bottom: 1px solid rgba(255,255,255,0.09);
}
.auto-reup-action-form {
  display: grid;
  gap: 16px;
}
.auto-reup-form-grid {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 16px;
}
.auto-reup-form-card {
  position: relative;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 18px;
  padding: 18px;
  background: rgba(0,0,0,0.18);
  display: grid;
  gap: 13px;
}
.auto-reup-form-card h3 {
  margin: 0;
  font-size: 1.05rem;
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
  min-height: 43px;
  border: 1px solid rgba(255,255,255,0.11);
  border-radius: 12px;
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
.auto-reup-three {
  display: grid;
  gap: 12px;
}
.auto-reup-two {
  grid-template-columns: 1fr 1fr;
}
.auto-reup-three {
  grid-template-columns: repeat(3, 1fr);
}
.auto-reup-quick-page {
  border: 1px dashed rgba(255,255,255,0.12);
  border-radius: 15px;
  padding: 14px;
  display: grid;
  gap: 10px;
  background: rgba(255,255,255,0.035);
}
.auto-reup-quick-page b {
  color: #dbe4f3;
  font-size: 0.82rem;
}
.auto-reup-toggle-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.auto-reup-pipeline-toggle {
  min-height: 84px;
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 15px;
  background: rgba(255,255,255,0.045);
  color: #e8edf8;
  text-align: left;
  padding: 14px;
  cursor: pointer;
}
.auto-reup-pipeline-toggle span {
  width: 18px;
  height: 18px;
  border-radius: 999px;
  display: inline-block;
  margin-bottom: 10px;
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
}
.auto-reup-pipeline-toggle small {
  margin-top: 5px;
  color: #9ca6ba;
  line-height: 1.35;
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
  .auto-reup-clean-test {
    grid-template-columns: 1fr;
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
  .auto-reup-toggle-grid,
  .auto-reup-action {
    grid-template-columns: 1fr;
  }
  .auto-reup-action-right {
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

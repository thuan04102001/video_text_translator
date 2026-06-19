import { useState } from "react";
import Home from "./pages/Home.jsx";
import CrawlerPanel from "./pages/CrawlerPanel.jsx";
import AutoReupDashboard from "./pages/AutoReupDashboard.jsx";

const modules = [
  { id: "translator", label: "Video Text Translator" },
  { id: "crawler", label: "Video Crawler" },
  { id: "autoReup", label: "Auto Reup" },
];

const moduleTitles = {
  translator: "AI Video Text Translator",
  crawler: "Video Crawler",
  autoReup: "Auto Reup Dashboard",
};

export default function App() {
  const [activeModule, setActiveModule] = useState("translator");

  return (
    <div className="tool-root">
      <style>{shellCss}</style>
      <div className="module-switch">
        <div className="module-switch-inner">
          <div>
            <div className="module-eyebrow">MAIN MODULE</div>
            <div className="module-title">{moduleTitles[activeModule]}</div>
          </div>

          <div className="module-tabs" role="tablist" aria-label="Tool module switcher">
            {modules.map((item) => (
              <button
                key={item.id}
                type="button"
                className={activeModule === item.id ? "active" : ""}
                onClick={() => setActiveModule(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {activeModule === "translator" ? <Home /> : null}
      {activeModule === "crawler" ? <CrawlerPanel /> : null}
      {activeModule === "autoReup" ? <AutoReupDashboard /> : null}
    </div>
  );
}

const shellCss = `
html,
body,
#root {
  min-height: 100%;
  margin: 0;
  background: #05080d;
}
.tool-root {
  min-height: 100vh;
  background:
    radial-gradient(circle at 12% 0%, rgba(91, 124, 250, 0.14), transparent 32rem),
    radial-gradient(circle at 88% 0%, rgba(168, 85, 247, 0.12), transparent 28rem),
    linear-gradient(180deg, #07111d 0%, #05080d 42%, #030506 100%);
}
.module-switch {
  position: sticky;
  top: 0;
  z-index: 20;
  padding: 14px 24px 0;
  background: linear-gradient(180deg, rgba(5, 8, 13, 0.94), rgba(5, 8, 13, 0.68), transparent);
  backdrop-filter: blur(12px);
}
.module-switch-inner {
  max-width: 1536px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 14px;
  border: 1px solid rgba(255,255,255,0.09);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(29,31,39,0.86), rgba(15,16,22,0.86));
  box-shadow: 0 18px 44px rgba(0,0,0,0.26);
}
.module-eyebrow {
  color: #99a1b3;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.08em;
}
.module-title {
  color: #f7f7fb;
  font-size: 1.05rem;
  font-weight: 850;
  margin-top: 0.25rem;
}
.module-tabs {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.module-tabs button {
  min-height: 44px;
  padding: 0 18px;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 13px;
  color: #d9deeb;
  background: rgba(255,255,255,0.04);
  font-weight: 800;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}
.module-tabs button:hover {
  transform: translateY(-1px);
  border-color: rgba(125, 162, 255, 0.42);
}
.module-tabs button.active {
  color: white;
  background: linear-gradient(135deg, #5b7cfa 0%, #8b5cf6 100%);
  border-color: rgba(255,255,255,0.22);
  box-shadow: 0 14px 34px rgba(91, 124, 250, 0.28);
}
@media (max-width: 760px) {
  .module-switch {
    padding: 10px 12px 0;
  }
  .module-switch-inner {
    align-items: stretch;
    flex-direction: column;
  }
  .module-tabs button {
    flex: 1;
  }
}
`;

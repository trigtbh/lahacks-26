import { useState, useEffect, useRef } from "react";
import "./App.css";

const API_BASE = "http://149.248.10.229:8000";

// ── App catalogue ─────────────────────────────────────────────────────────────

const APPS = [
  {
    id: "gmail",        group: "google",  category: "Productivity",
    label: "Gmail",     desc: "Send & draft emails",
    icon: "https://upload.wikimedia.org/wikipedia/commons/7/7e/Gmail_icon_%282020%29.svg",
    color: "#EA4335",   auth: "google",
  },
  {
    id: "gcal",         group: "google",  category: "Productivity",
    label: "Calendar",  desc: "Create, push & cancel events",
    icon: "https://upload.wikimedia.org/wikipedia/commons/a/a5/Google_Calendar_icon_%282020%29.svg",
    color: "#4285F4",   auth: "google",
  },
  {
    id: "slack",        group: "slack",   category: "Communication",
    label: "Slack",     desc: "Message channels & DMs",
    icon: "https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg",
    color: "#E01E5A",   auth: "slack",
  },
  {
    id: "notion",       group: "zapier",  category: "Productivity",
    label: "Notion",    desc: "Create & append to pages",
    icon: "https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png",
    color: "#ffffff",   auth: "zapier",
  },
  {
    id: "github",       group: "zapier",  category: "Dev",
    label: "GitHub",    desc: "Open & comment on issues",
    icon: "https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
    color: "#f0f0f0",   auth: "zapier",
  },
  {
    id: "spotify",      group: "zapier",  category: "Entertainment",
    label: "Spotify",   desc: "Play, pause & control music",
    icon: "https://upload.wikimedia.org/wikipedia/commons/1/19/Spotify_logo_without_text.svg",
    color: "#1DB954",   auth: "zapier",
  },
  {
    id: "uber",         group: "zapier",  category: "Transport",
    label: "Uber",      desc: "Request rides by voice",
    icon: "https://upload.wikimedia.org/wikipedia/commons/c/cc/Uber_logo_2018.png",
    color: "#000000",   auth: "zapier",
  },
  {
    id: "dominos",      group: "zapier",  category: "Food",
    label: "Domino's",  desc: "Order & reorder pizza",
    icon: "https://upload.wikimedia.org/wikipedia/commons/3/3b/Domino%27s_pizza_logo.svg",
    color: "#006491",   auth: "zapier",
  },
];

const CATEGORIES = ["All", ...new Set(APPS.map(a => a.category))];

// Auth groups — apps that share one OAuth flow
const AUTH_GROUPS = {
  google: { label: "Google", icon: "https://upload.wikimedia.org/wikipedia/commons/c/c1/Google_%22G%22_logo.svg", authUrl: uid => `${API_BASE}/auth/google?user_id=${uid}` },
  slack:  { label: "Slack",  icon: "https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg",   authUrl: uid => `${API_BASE}/auth/slack?user_id=${uid}` },
};

// ── Theme ─────────────────────────────────────────────────────────────────────

const DEFAULT_THEME = {
  appName: "Flow", tagline: "Voice automations for Ray-Ban glasses.",
  accentColor: "#ffffff", bgColor: "#080808", cardBg: "#111111",
  borderColor: "#1e1e1e", successColor: "#4ade80", mutedColor: "#555555",
};

function loadTheme() {
  try { return { ...DEFAULT_THEME, ...JSON.parse(localStorage.getItem("flow_theme") || "{}") }; }
  catch { return DEFAULT_THEME; }
}

function applyTheme(t) {
  const s = document.documentElement.style;
  s.setProperty("--accent",  t.accentColor);
  s.setProperty("--bg",      t.bgColor);
  s.setProperty("--card",    t.cardBg);
  s.setProperty("--border",  t.borderColor);
  s.setProperty("--success", t.successColor);
  s.setProperty("--muted",   t.mutedColor);
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

function useConnections(userId) {
  const [connected, setConnected] = useState(new Set());
  async function refresh() {
    if (!userId) return;
    try {
      const res = await fetch(`${API_BASE}/user/${userId}/connections`);
      setConnected(new Set((await res.json()).connected || []));
    } catch (_) {}
  }
  useEffect(() => { refresh(); }, [userId]);
  return { connected, refresh };
}

// ── Steps ─────────────────────────────────────────────────────────────────────

function WelcomeStep({ userId, setUserId, onNext, theme }) {
  return (
    <div className="page page--welcome">
      <div className="bg-orb bg-orb--1" />
      <div className="bg-orb bg-orb--2" />
      <div className="welcome-inner">
        <div className="brand">
          <span className="brand-mark">◈</span>
          <span className="brand-name">{theme.appName}</span>
        </div>
        <h1 className="hero-title">Voice-powered<br />automations.</h1>
        <p className="hero-sub">{theme.tagline}</p>
        <div className="welcome-form">
          <div className="field">
            <label className="field-label">Your user ID</label>
            <input className="text-input" value={userId}
              onChange={e => setUserId(e.target.value)} placeholder="akshai" autoFocus />
          </div>
          <button className="btn-primary" onClick={onNext} disabled={!userId.trim()}>
            Get started <span className="arr">→</span>
          </button>
        </div>
        <p className="hint">Select apps, connect accounts, done in 60s.</p>
      </div>
    </div>
  );
}

function SelectStep({ selected, setSelected, onNext }) {
  const [cat, setCat] = useState("All");
  const visible = cat === "All" ? APPS : APPS.filter(a => a.category === cat);

  function toggle(id) {
    setSelected(prev => {
      const s = new Set(prev);
      s.has(id) ? s.delete(id) : s.add(id);
      return s;
    });
  }

  return (
    <div className="page page--select">
      <div className="select-header">
        <h2 className="section-title">Choose your apps</h2>
        <p className="section-sub">Select everything you want Flow to control.</p>
      </div>

      <div className="cat-pills">
        {CATEGORIES.map(c => (
          <button key={c} className={`pill ${cat === c ? "pill--active" : ""}`} onClick={() => setCat(c)}>
            {c}
          </button>
        ))}
      </div>

      <div className="app-grid">
        {visible.map(app => {
          const isSel = selected.has(app.id);
          return (
            <button key={app.id} className={`app-tile ${isSel ? "app-tile--selected" : ""}`}
              onClick={() => toggle(app.id)} style={{ "--app-color": app.color }}>
              <div className="tile-glow" />
              <div className="tile-top">
                <img src={app.icon} alt={app.label} className="tile-icon" />
                {isSel && <span className="tile-check">✓</span>}
              </div>
              <div className="tile-name">{app.label}</div>
              <div className="tile-desc">{app.desc}</div>
              <div className="tile-cat">{app.category}</div>
            </button>
          );
        })}
      </div>

      <div className="select-footer">
        <span className="sel-count">{selected.size} app{selected.size !== 1 ? "s" : ""} selected</span>
        <button className="btn-primary btn-primary--inline" onClick={onNext} disabled={selected.size === 0}>
          Connect selected <span className="arr">→</span>
        </button>
      </div>
    </div>
  );
}

function ConnectStep({ selected, userId, connected, onRefresh, onDone }) {
  const popupRef = useRef(null);

  // Derive which auth groups are needed
  const neededGroups = [...new Set(
    APPS.filter(a => selected.has(a.id) && a.auth !== "zapier").map(a => a.auth)
  )];
  const zapierApps = APPS.filter(a => selected.has(a.id) && a.auth === "zapier");

  const [webhooks, setWebhooks] = useState({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(new Set());

  function openOAuth(group) {
    popupRef.current = window.open(AUTH_GROUPS[group].authUrl(userId), "oauth", "width=520,height=680");
    const t = setInterval(() => { if (popupRef.current?.closed) { clearInterval(t); onRefresh(); } }, 600);
  }

  async function saveWebhook(appId, url) {
    const app = APPS.find(a => a.id === appId);
    setSaving(true);
    try {
      await fetch(`${API_BASE}/user/${userId}/webhooks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app: appId, action: "trigger", webhook_url: url }),
      });
      setSaved(prev => new Set([...prev, appId]));
    } catch (_) {}
    setSaving(false);
  }

  const allOAuthDone = neededGroups.every(g => connected.has(g));
  const allZapierDone = zapierApps.every(a => saved.has(a.id));
  const canFinish = (neededGroups.length === 0 || allOAuthDone) && (zapierApps.length === 0 || allZapierDone);

  return (
    <div className="page page--connect">
      <div className="connect-header">
        <h2 className="section-title">Connect accounts</h2>
        <p className="section-sub">Authorize Flow to act on your behalf.</p>
      </div>

      <div className="connect-list">
        {neededGroups.map(group => {
          const g = AUTH_GROUPS[group];
          const isConnected = connected.has(group);
          const apps = APPS.filter(a => selected.has(a.id) && a.auth === group);
          return (
            <div key={group} className={`connect-card ${isConnected ? "connect-card--done" : ""}`}>
              <div className="connect-card-left">
                <img src={g.icon} alt={g.label} className="connect-icon" />
                <div>
                  <div className="connect-label">{g.label}</div>
                  <div className="connect-apps">{apps.map(a => a.label).join(", ")}</div>
                </div>
              </div>
              {isConnected
                ? <span className="status-badge status-badge--ok">✓ Connected</span>
                : <button className="btn-connect" onClick={() => openOAuth(group)}>Sign in</button>
              }
            </div>
          );
        })}

        {zapierApps.map(app => (
          <div key={app.id} className={`connect-card ${saved.has(app.id) ? "connect-card--done" : ""}`}>
            <div className="connect-card-left">
              <img src={app.icon} alt={app.label} className="connect-icon" />
              <div>
                <div className="connect-label">{app.label}</div>
                <div className="connect-apps">Zapier webhook</div>
              </div>
            </div>
            {saved.has(app.id)
              ? <span className="status-badge status-badge--ok">✓ Saved</span>
              : (
                <div className="webhook-inline">
                  <input className="text-input text-input--xs"
                    placeholder="https://hooks.zapier.com/..."
                    value={webhooks[app.id] || ""}
                    onChange={e => setWebhooks(p => ({ ...p, [app.id]: e.target.value }))}
                  />
                  <button className="btn-save" disabled={!webhooks[app.id]?.trim() || saving}
                    onClick={() => saveWebhook(app.id, webhooks[app.id])}>
                    Save
                  </button>
                </div>
              )
            }
          </div>
        ))}
      </div>

      <div className="connect-footer">
        <button className="btn-ghost-sm" onClick={onDone}>Skip remaining</button>
        <button className="btn-primary btn-primary--inline" onClick={onDone}>
          Finish setup <span className="arr">→</span>
        </button>
      </div>
    </div>
  );
}

function DoneStep({ selected, connected, theme }) {
  const connectedApps = APPS.filter(a => selected.has(a.id));
  return (
    <div className="page page--done">
      <div className="bg-orb bg-orb--3" />
      <div className="done-inner">
        <div className="done-ring"><span className="done-check">✓</span></div>
        <h2 className="hero-title" style={{ fontSize: 32 }}>All set.</h2>
        <p className="hero-sub">Say <em style={{color:"#ccc",fontStyle:"normal"}}>"{theme.appName}"</em> to start.</p>
        <div className="done-apps">
          {connectedApps.map(app => (
            <div key={app.id} className="done-app-chip">
              <img src={app.icon} alt={app.label} className="chip-icon" />
              {app.label}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Customize panel ───────────────────────────────────────────────────────────

function ThemePanel({ theme, setTheme, onClose }) {
  function update(k, v) {
    setTheme(prev => {
      const next = { ...prev, [k]: v };
      applyTheme(next);
      localStorage.setItem("flow_theme", JSON.stringify(next));
      return next;
    });
  }

  const Row = ({ label, k, type = "text", placeholder }) => (
    <div className="t-row">
      <label className="t-label">{label}</label>
      {type === "color" ? (
        <div className="color-row">
          <input type="color" className="color-swatch" value={theme[k]} onChange={e => update(k, e.target.value)} />
          <input type="text" className="text-input text-input--xs" value={theme[k]} onChange={e => update(k, e.target.value)} />
        </div>
      ) : (
        <input type="text" className="text-input text-input--xs" value={theme[k]}
          onChange={e => update(k, e.target.value)} placeholder={placeholder} />
      )}
    </div>
  );

  return (
    <div className="overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="panel">
        <div className="panel-head">
          <span>Customize</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="panel-body">
          <div className="panel-group">
            <div className="panel-group-label">Branding</div>
            <Row label="App name"  k="appName"  placeholder="Flow" />
            <Row label="Tagline"   k="tagline"  placeholder="Your tagline" />
          </div>
          <div className="panel-group">
            <div className="panel-group-label">Colors</div>
            <Row label="Accent"     k="accentColor"  type="color" />
            <Row label="Background" k="bgColor"      type="color" />
            <Row label="Card"       k="cardBg"       type="color" />
            <Row label="Border"     k="borderColor"  type="color" />
            <Row label="Success"    k="successColor" type="color" />
            <Row label="Muted"      k="mutedColor"   type="color" />
          </div>
        </div>
        <button className="btn-reset" onClick={() => { applyTheme(DEFAULT_THEME); setTheme(DEFAULT_THEME); localStorage.removeItem("flow_theme"); }}>
          Reset defaults
        </button>
      </div>
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

const STEPS = ["welcome", "select", "connect", "done"];

export default function App() {
  const [step, setStep]           = useState("welcome");
  const [userId, setUserId]       = useState("akshai");
  const [selected, setSelected]   = useState(new Set());
  const [showPanel, setShowPanel] = useState(false);
  const [theme, setTheme]         = useState(() => { const t = loadTheme(); applyTheme(t); return t; });

  const { connected, refresh } = useConnections(userId);

  const next = () => setStep(s => STEPS[STEPS.indexOf(s) + 1]);

  const stepIdx = STEPS.indexOf(step);

  return (
    <>
      <div className="shell">
        {step !== "welcome" && step !== "done" && (
          <div className="top-bar">
            <div className="top-brand">
              <span className="brand-mark sm">◈</span>
              <span>{theme.appName}</span>
            </div>
            <div className="step-pills">
              {["Select", "Connect"].map((s, i) => (
                <div key={s} className={`step-pill ${stepIdx === i + 1 ? "step-pill--active" : stepIdx > i + 1 ? "step-pill--done" : ""}`}>
                  <span className="pill-num">{stepIdx > i + 1 ? "✓" : i + 1}</span>
                  {s}
                </div>
              ))}
            </div>
            <div style={{width:80}} />
          </div>
        )}

        {step === "welcome" && <WelcomeStep userId={userId} setUserId={setUserId} onNext={next} theme={theme} />}
        {step === "select"  && <SelectStep selected={selected} setSelected={setSelected} onNext={next} />}
        {step === "connect" && <ConnectStep selected={selected} userId={userId} connected={connected} onRefresh={refresh} onDone={next} />}
        {step === "done"    && <DoneStep selected={selected} connected={connected} theme={theme} />}
      </div>

      <button className="fab" onClick={() => setShowPanel(true)} title="Customize">⚙</button>
      {showPanel && <ThemePanel theme={theme} setTheme={setTheme} onClose={() => setShowPanel(false)} />}
    </>
  );
}

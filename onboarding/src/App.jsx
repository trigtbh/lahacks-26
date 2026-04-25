import { useState, useEffect, useRef, useCallback } from "react";
import "./App.css";

const API_BASE = "http://149.248.10.229:8000";

// ── App catalogue ─────────────────────────────────────────────────────────────

const APPS = [
  { id:"gmail",   group:"google", category:"Productivity", label:"Gmail",     desc:"Send & draft emails",          icon:"https://upload.wikimedia.org/wikipedia/commons/7/7e/Gmail_icon_%282020%29.svg",                                                             color:"#EA4335", auth:"google" },
  { id:"gcal",    group:"google", category:"Productivity", label:"Calendar",  desc:"Create, push & cancel events", icon:"https://upload.wikimedia.org/wikipedia/commons/a/a5/Google_Calendar_icon_%282020%29.svg",                                                   color:"#4285F4", auth:"google" },
  { id:"slack",   group:"slack",  category:"Communication",label:"Slack",     desc:"Message channels & DMs",       icon:"https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg",                                                                    color:"#E01E5A", auth:"slack"  },
  { id:"notion",  group:"notion", category:"Productivity", label:"Notion",    desc:"Create & append to pages",     icon:"https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png",                                                                    color:"#000000", auth:"notion" },
  { id:"github",  group:"zapier", category:"Dev",          label:"GitHub",    desc:"Open & comment on issues",     icon:"https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",                                                                   color:"#f0f0f0", auth:"zapier" },
  { id:"spotify", group:"zapier", category:"Entertainment",label:"Spotify",   desc:"Play, pause & control music",  icon:"https://upload.wikimedia.org/wikipedia/commons/1/19/Spotify_logo_without_text.svg",                                                          color:"#1DB954", auth:"zapier" },
  { id:"uber",    group:"zapier", category:"Transport",    label:"Uber",      desc:"Request rides by voice",       icon:"https://upload.wikimedia.org/wikipedia/commons/c/cc/Uber_logo_2018.png",                                                                     color:"#ffffff", auth:"zapier" },
  { id:"dominos", group:"zapier", category:"Food",         label:"Domino's",  desc:"Order & reorder pizza",        icon:"https://upload.wikimedia.org/wikipedia/commons/3/3b/Domino%27s_pizza_logo.svg",                                                             color:"#006491", auth:"zapier" },
];

const CATEGORIES = ["All", ...new Set(APPS.map(a => a.category))];

const AUTH_GROUPS = {
  google: { label:"Google", icon:"https://upload.wikimedia.org/wikipedia/commons/c/c1/Google_%22G%22_logo.svg", authUrl: uid => `${API_BASE}/auth/google?user_id=${uid}` },
  slack:  { label:"Slack",  icon:"https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg",    authUrl: uid => `${API_BASE}/auth/slack?user_id=${uid}`  },
  notion: { label:"Notion", icon:"https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png",   authUrl: uid => `${API_BASE}/auth/notion?user_id=${uid}` },
};

// ── Theme ─────────────────────────────────────────────────────────────────────

const DEFAULT_THEME = {
  appName:"idlemaxing", tagline:"Voice automations for Ray-Ban glasses.",
  accentColor:"#ffffff", bgColor:"#080808", cardBg:"#111111",
  borderColor:"#1e1e1e", successColor:"#4ade80", mutedColor:"#555555",
};

function loadTheme() {
  try { return { ...DEFAULT_THEME, ...JSON.parse(localStorage.getItem("idwdi_theme") || "{}") }; }
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

// ── Connections hook ──────────────────────────────────────────────────────────

function useConnections(userId) {
  const [connected, setConnected] = useState(new Set());
  const refresh = useCallback(async () => {
    if (!userId) return;
    try {
      const res = await fetch(`${API_BASE}/user/${userId}/connections`);
      setConnected(new Set((await res.json()).connected || []));
    } catch (_) {}
  }, [userId]);
  useEffect(() => { refresh(); }, [refresh]);
  return { connected, refresh };
}

// ── Panel row — defined OUTSIDE ThemePanel so it never remounts ───────────────

function ThemeRow({ label, k, type, value, onChange }) {
  return (
    <div className="t-row">
      <label className="t-label">{label}</label>
      {type === "color" ? (
        <div className="color-row">
          <input type="color" className="color-swatch" value={value}
            onChange={e => onChange(k, e.target.value)} />
          <input type="text" className="text-input text-input--xs" value={value}
            onChange={e => onChange(k, e.target.value)} />
        </div>
      ) : (
        <input type="text" className="text-input text-input--xs" value={value}
          onChange={e => onChange(k, e.target.value)} />
      )}
    </div>
  );
}

// ── Steps ─────────────────────────────────────────────────────────────────────

function WelcomeStep({ userId, setUserId, onNext, theme }) {
  return (
    <div className="page page--welcome">
      <div className="welcome-inner">
        <div className="welcome-brand">{theme.appName}</div>
        <h1 className="hero-title">
          Stop doing<br />
          <span className="hero-accent">things yourself</span>
        </h1>
        <p className="hero-sub">{theme.tagline}</p>
        <div className="welcome-form">
          <div className="field">
            <label className="field-label">Your user ID</label>
            <input className="text-input w-input" value={userId}
              onChange={e => setUserId(e.target.value)}
              placeholder="akshai" autoFocus />
          </div>
          <button className="btn-welcome" onClick={onNext} disabled={!userId.trim()}>
            Get started <span className="arr">→</span>
          </button>
        </div>
      </div>
      <div className="welcome-chad">
        <img src="/Chad.png" alt="Chad" className="chad-img" />
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
      <div className="page-header">
        <h2 className="page-title">Choose your apps</h2>
        <p className="page-sub">Everything you want Flow to control.</p>
      </div>

      <div className="cat-pills">
        {CATEGORIES.map(c => (
          <button key={c} className={`pill ${cat===c?"pill--active":""}`} onClick={() => setCat(c)}>{c}</button>
        ))}
      </div>

      <div className="app-grid">
        {visible.map((app, i) => {
          const sel = selected.has(app.id);
          return (
            <button key={app.id} className={`app-tile ${sel?"app-tile--selected":""}`}
              onClick={() => toggle(app.id)} style={{ "--app-color": app.color, animationDelay:`${i*30}ms` }}>
              <div className="tile-glow" />
              <div className="tile-top">
                <img src={app.icon} alt={app.label} className="tile-icon" onError={e => e.target.style.opacity=0} />
                <div className={`tile-check ${sel?"tile-check--visible":""}`}>✓</div>
              </div>
              <div className="tile-name">{app.label}</div>
              <div className="tile-desc">{app.desc}</div>
              <div className="tile-tag">{app.category}</div>
            </button>
          );
        })}
      </div>

      <div className="sticky-footer">
        <span className="sel-count">
          {selected.size > 0 ? <><strong>{selected.size}</strong> app{selected.size!==1?"s":""} selected</> : "No apps selected yet"}
        </span>
        <button className="btn-primary btn-inline" onClick={onNext} disabled={selected.size===0}>
          Connect selected <span className="arr">→</span>
        </button>
      </div>
    </div>
  );
}

function ConnectStep({ selected, userId, connected, onRefresh, onDone, onBack }) {
  const popupRef = useRef(null);
  const [webhooks, setWebhooks] = useState({});
  const [saved, setSaved]       = useState(new Set());
  const [saving, setSaving]     = useState(false);

  const neededGroups = [...new Set(
    APPS.filter(a => selected.has(a.id) && a.auth !== "zapier").map(a => a.auth)
  )];
  const zapierApps = APPS.filter(a => selected.has(a.id) && a.auth === "zapier");

  function openOAuth(group) {
    popupRef.current = window.open(AUTH_GROUPS[group].authUrl(userId), "oauth", "width=520,height=680");
    const t = setInterval(() => { if (popupRef.current?.closed) { clearInterval(t); onRefresh(); } }, 600);
  }

  async function saveWebhook(appId, url) {
    setSaving(true);
    try {
      await fetch(`${API_BASE}/user/${userId}/webhooks`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ app:appId, action:"trigger", webhook_url:url }),
      });
      setSaved(prev => new Set([...prev, appId]));
    } catch(_) {}
    setSaving(false);
  }

  return (
    <div className="page page--connect">
      <div className="page-header">
        <h2 className="page-title">Connect accounts</h2>
        <p className="page-sub">Authorize Flow to act on your behalf.</p>
      </div>

      <div className="connect-list">
        {neededGroups.map(group => {
          const g = AUTH_GROUPS[group];
          const done = connected.has(group);
          const apps = APPS.filter(a => selected.has(a.id) && a.auth === group);
          return (
            <div key={group} className={`connect-card ${done?"connect-card--done":""}`}>
              <div className="cc-left">
                <img src={g.icon} alt={g.label} className="cc-icon" />
                <div>
                  <div className="cc-label">{g.label}</div>
                  <div className="cc-apps">{apps.map(a=>a.label).join(" · ")}</div>
                </div>
              </div>
              {done
                ? <span className="badge badge--ok">✓ Connected</span>
                : <button className="btn-connect" onClick={() => openOAuth(group)}>Sign in</button>
              }
            </div>
          );
        })}

        {zapierApps.map(app => (
          <div key={app.id} className={`connect-card ${saved.has(app.id)?"connect-card--done":""}`}>
            <div className="cc-left">
              <img src={app.icon} alt={app.label} className="cc-icon" onError={e=>e.target.style.opacity=0} />
              <div>
                <div className="cc-label">{app.label}</div>
                <div className="cc-apps">Zapier webhook</div>
              </div>
            </div>
            {saved.has(app.id)
              ? <span className="badge badge--ok">✓ Saved</span>
              : (
                <div className="webhook-row">
                  <input className="text-input text-input--xs" placeholder="https://hooks.zapier.com/..."
                    value={webhooks[app.id]||""}
                    onChange={e => setWebhooks(p=>({...p,[app.id]:e.target.value}))} />
                  <button className="btn-save"
                    disabled={!webhooks[app.id]?.trim()||saving}
                    onClick={() => saveWebhook(app.id, webhooks[app.id])}>Save</button>
                </div>
              )
            }
          </div>
        ))}
      </div>

      <div className="connect-footer">
        <button className="btn-back" onClick={onBack}>← Back</button>
        <button className="btn-primary btn-inline" onClick={onDone}>
          Finish <span className="arr">→</span>
        </button>
      </div>
    </div>
  );
}

function DoneStep({ selected, theme }) {
  const apps = APPS.filter(a => selected.has(a.id));
  return (
    <div className="page page--done">
      <div className="bg-orb bg-orb--3" />
      <div className="noise" />
      <div className="done-inner">
        <div className="done-ring">
          <div className="done-pulse" />
          <span className="done-check">✓</span>
        </div>
        <h2 className="hero-title" style={{fontSize:38,letterSpacing:"-1.5px"}}>All set.</h2>
        <p className="hero-sub">Say <em>"{theme.appName}"</em> to get started.</p>
        {apps.length > 0 && (
          <div className="chip-row">
            {apps.map((app,i) => (
              <div key={app.id} className="chip" style={{animationDelay:`${i*50}ms`}}>
                <img src={app.icon} alt={app.label} className="chip-icon" onError={e=>e.target.style.opacity=0} />
                {app.label}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Customize panel ───────────────────────────────────────────────────────────

function ThemePanel({ theme, setTheme, onClose }) {
  const update = useCallback((k, v) => {
    setTheme(prev => {
      const next = { ...prev, [k]: v };
      applyTheme(next);
      localStorage.setItem("idwdi_theme", JSON.stringify(next));
      return next;
    });
  }, [setTheme]);

  const FIELDS = [
    { section:"Branding", rows:[
      { label:"App name",  k:"appName",      type:"text"  },
      { label:"Tagline",   k:"tagline",       type:"text"  },
    ]},
    { section:"Colors", rows:[
      { label:"Accent",     k:"accentColor",  type:"color" },
      { label:"Background", k:"bgColor",      type:"color" },
      { label:"Card",       k:"cardBg",       type:"color" },
      { label:"Border",     k:"borderColor",  type:"color" },
      { label:"Success",    k:"successColor", type:"color" },
      { label:"Muted",      k:"mutedColor",   type:"color" },
    ]},
  ];

  return (
    <div className="overlay" onClick={e => e.target===e.currentTarget && onClose()}>
      <div className="panel">
        <div className="panel-head">
          <span>Customize</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div className="panel-body">
          {FIELDS.map(({ section, rows }) => (
            <div key={section} className="panel-group">
              <div className="panel-group-label">{section}</div>
              {rows.map(f => (
                <ThemeRow key={f.k} label={f.label} k={f.k} type={f.type}
                  value={theme[f.k]} onChange={update} />
              ))}
            </div>
          ))}
        </div>
        <button className="btn-reset" onClick={() => {
          applyTheme(DEFAULT_THEME);
          setTheme(DEFAULT_THEME);
          localStorage.removeItem("idwdi_theme");
        }}>Reset to defaults</button>
      </div>
    </div>
  );
}

// ── Top bar ───────────────────────────────────────────────────────────────────

function TopBar({ theme }) {
  return (
    <div className="top-bar">
      <div className="top-brand">{theme.appName}</div>
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

const STEPS = ["welcome","select","connect","done"];

export default function App() {
  const [step, setStep]           = useState("welcome");
  const [userId, setUserId]       = useState("akshai");
  const [selected, setSelected]   = useState(new Set());
  const [showPanel, setShowPanel] = useState(false);
  const [theme, setTheme]         = useState(() => { const t = loadTheme(); applyTheme(t); return t; });

  const { connected, refresh } = useConnections(userId);
  const next = () => setStep(s => STEPS[STEPS.indexOf(s)+1]);

  return (
    <>
      <div className={`shell${step === "select" || step === "connect" ? " shell--light" : ""}`}>
        {step !== "welcome" && step !== "done" && <TopBar theme={theme} />}

        {step==="welcome" && <WelcomeStep userId={userId} setUserId={setUserId} onNext={next} theme={theme} />}
        {step==="select"  && <SelectStep  selected={selected} setSelected={setSelected} onNext={next} />}
        {step==="connect" && <ConnectStep selected={selected} userId={userId} connected={connected} onRefresh={refresh} onDone={next} onBack={() => setStep("select")} />}
        {step==="done"    && <DoneStep    selected={selected} theme={theme} />}
      </div>

      <button className="fab" onClick={() => setShowPanel(true)} title="Customize">⚙</button>
      {showPanel && <ThemePanel theme={theme} setTheme={setTheme} onClose={() => setShowPanel(false)} />}
    </>
  );
}

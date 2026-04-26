import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth0 } from "@auth0/auth0-react";
import "./App.css";

const API_BASE = "";

// ── App catalogue ─────────────────────────────────────────────────────────────

const APPS = [
  { id:"gmail",   group:"google", category:"Productivity", label:"Gmail",     desc:"Send & draft emails",          icon:"https://upload.wikimedia.org/wikipedia/commons/7/7e/Gmail_icon_%282020%29.svg",                                                             color:"#EA4335", auth:"google" },
  { id:"gcal",    group:"google", category:"Productivity", label:"Calendar",  desc:"Create, push & cancel events", icon:"https://upload.wikimedia.org/wikipedia/commons/a/a5/Google_Calendar_icon_%282020%29.svg",                                                   color:"#4285F4", auth:"google" },
  { id:"slack",   group:"slack",  category:"Communication",label:"Slack",     desc:"Message channels & DMs",       icon:"https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg",                                                                    color:"#E01E5A", auth:"slack"  },
  { id:"notion",  group:"notion", category:"Productivity", label:"Notion",    desc:"Create & append to pages",     icon:"https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png",                                                                    color:"#000000", auth:"notion" },
  { id:"github",  group:"zapier", category:"Dev",          label:"GitHub",    desc:"Open & comment on issues",     icon:"https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",                                                                   color:"#f0f0f0", auth:"zapier" },
  { id:"spotify", group:"zapier", category:"Entertainment",label:"Spotify",   desc:"Play, pause & control music",  icon:"https://upload.wikimedia.org/wikipedia/commons/1/19/Spotify_logo_without_text.svg",                                                          color:"#1DB954", auth:"zapier" },
  { id:"uber",    group:"zapier", category:"Transport",    label:"Uber",      desc:"Request rides by voice",       icon:"https://upload.wikimedia.org/wikipedia/commons/c/cc/Uber_logo_2018.png",                                                                     color:"#ffffff", auth:"zapier" },
  { id:"dominos", group:"dominos", category:"Food",         label:"Domino's",  desc:"Order & reorder pizza",        icon:"/dominos.svg",                                                                                                                          color:"#006491", auth:"dominos" },
];

const CATEGORIES = ["All", ...new Set(APPS.map(a => a.category))];

const AUTH_GROUPS = {
  google: { label:"Google", icon:"https://upload.wikimedia.org/wikipedia/commons/c/c1/Google_%22G%22_logo.svg", authUrl: uid => `${API_BASE}/auth/google?user_id=${uid}` },
  slack:  { label:"Slack",  icon:"https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg",    authUrl: uid => `${API_BASE}/auth/slack?user_id=${uid}`  },
  notion: { label:"Notion", icon:"https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png",   authUrl: uid => `${API_BASE}/auth/notion?user_id=${uid}` },
};

// ── Theme ─────────────────────────────────────────────────────────────────────

const DEFAULT_THEME = {
  appName:"idlemaxxing", tagline:"Voice automations for Meta Raybans",
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

// ── Steps ─────────────────────────────────────────────────────────────────────

const VOICE_CMDS = [
  "order me a pizza!",
  "cancel my 3pm",
  "dm the team",
  "play some music",
];

function PixelBubble({ text, cmdIdx }) {
  return (
    <div className="px-bubble">
      <svg className="px-bubble-svg" viewBox="0 0 210 120" xmlns="http://www.w3.org/2000/svg">
        {/* Body with 8px pixel-stepped corners */}
        <polygon
          points="8,0 202,0 210,8 210,84 202,92 8,92 0,84 0,8"
          fill="white" stroke="#0d0d0d" strokeWidth="4" strokeLinejoin="miter"
        />
        {/* Stepped tail pointing down-right toward Chad */}
        <polygon
          points="136,92 136,100 144,100 144,108 152,108 152,116 168,116 168,108 176,108 176,100 184,100 184,92"
          fill="white" stroke="#0d0d0d" strokeWidth="4" strokeLinejoin="miter"
        />
        {/* Hide internal seam */}
        <rect x="139" y="89" width="42" height="8" fill="white" />
      </svg>
      <div className="px-bubble-text" key={cmdIdx}>{text}</div>
    </div>
  );
}

function WelcomeStep({ onNext, theme }) {
  const { isAuthenticated, isLoading, loginWithRedirect, user } = useAuth0();
  const [mouse, setMouse] = useState({ x: 0.5, y: 0.5 });
  const [cmdIdx, setCmdIdx] = useState(0);

  useEffect(() => {
    const fn = e => setMouse({ x: e.clientX / window.innerWidth, y: e.clientY / window.innerHeight });
    window.addEventListener('mousemove', fn);
    return () => window.removeEventListener('mousemove', fn);
  }, []);

  useEffect(() => {
    const t = setInterval(() => setCmdIdx(i => (i + 1) % VOICE_CMDS.length), 3500);
    return () => clearInterval(t);
  }, []);

  const dx = mouse.x - 0.5;
  const dy = mouse.y - 0.5;

  return (
    <div className="page page--welcome">
      <div className="w-body">
        {/* ── Orange left bar ── */}
        <div className="w-leftbar">
          <div className="w-leftbar-cap" />
          <span className="w-leftbar-label">idlemaxxing © 2026</span>
        </div>

        {/* ── Background decorative boxes ── */}
        <div className="w-bg-boxes" aria-hidden="true">
          <div className="w-bb w-bb--1" />
          <div className="w-bb w-bb--2" />
          <div className="w-bb w-bb--3" />
        </div>

        {/* ── Content zone ── */}
        <div className="w-content">
          <div className="welcome-inner">
            <div className="welcome-brand">{theme.appName}</div>
            <h1 className="hero-title">
              Stop doing<br />
              <span className="hero-accent">things yourself</span>
            </h1>
            <p className="hero-sub">{theme.tagline}</p>
            <div className="welcome-form">
              {isLoading ? (
                <button className="btn-welcome" disabled>···</button>
              ) : isAuthenticated ? (
                <>
                  <p className="w-signed">↳ {user.email}</p>
                  <button className="btn-welcome" onClick={onNext}>
                    Get started <span className="arr">→</span>
                  </button>
                </>
              ) : (
                <button className="btn-welcome" onClick={() => loginWithRedirect()}>
                  Login to get started <span className="arr">→</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ── Chad ── */}
        <div className="welcome-chad" style={{ transform:`translate(${dx*7}px,${dy*5}px)`, transition:'transform 0.12s linear' }}>
          <PixelBubble text={VOICE_CMDS[cmdIdx]} cmdIdx={cmdIdx} />
          <img src="/Chad.png" alt="Chad" className="chad-img" />
        </div>
      </div>
      <div className="lahacks-corner">
        <img src="/logo.jpg" alt="LAHacks" className="lahacks-logo" />
        <span className="lahacks-label">Built at LAHacks</span>
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
                <img src={app.icon} alt={app.label} className={`tile-icon${app.id === "dominos" ? " tile-icon--lg" : ""}`} onError={e => e.target.style.opacity=0} />
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

function DominosCredForm({ appId, userId, onSaved }) {
  const [fields, setFields] = useState({
    firstName: "", lastName: "", email: "", phone: "", address: "",
    cardNumber: "", cardExpiration: "", cardCvv: "", cardZip: "",
  });
  const [saving, setSaving] = useState(false);

  const set = k => e => setFields(p => ({ ...p, [k]: e.target.value }));
  const canSave = fields.firstName.trim() && fields.address.trim() && fields.phone.trim();

  async function submit() {
    if (!canSave) return;
    setSaving(true);
    try {
      await fetch(`${API_BASE}/user/${userId}/credentials/dominos`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      onSaved(appId);
    } catch (_) {}
    setSaving(false);
  }

  return (
    <div className="cred-form">
      <div className="cred-section-label">Delivery info</div>
      <div className="cred-row">
        <input className="text-input text-input--xs" placeholder="First name *"
          value={fields.firstName} onChange={set("firstName")} />
        <input className="text-input text-input--xs" placeholder="Last name"
          value={fields.lastName} onChange={set("lastName")} />
      </div>
      <input className="text-input text-input--xs" placeholder="Email"
        value={fields.email} onChange={set("email")} />
      <input className="text-input text-input--xs" placeholder="Phone *"
        value={fields.phone} onChange={set("phone")} />
      <input className="text-input text-input--xs" placeholder="Delivery address *"
        value={fields.address} onChange={set("address")} />

      <div className="cred-section-label" style={{marginTop:4}}>Payment (optional — needed to place orders)</div>
      <input className="text-input text-input--xs" placeholder="Card number"
        value={fields.cardNumber} onChange={set("cardNumber")} />
      <div className="cred-row">
        <input className="text-input text-input--xs" placeholder="MM/YY"
          value={fields.cardExpiration} onChange={set("cardExpiration")} />
        <input className="text-input text-input--xs" placeholder="CVV"
          value={fields.cardCvv} onChange={set("cardCvv")} />
        <input className="text-input text-input--xs" placeholder="ZIP"
          value={fields.cardZip} onChange={set("cardZip")} />
      </div>

      <button className="btn-save" disabled={!canSave || saving} onClick={submit}>
        {saving ? "Saving…" : "Save"}
      </button>
    </div>
  );
}

function ConnectStep({ selected, userId, connected, onRefresh, onDone, onBack }) {
  const popupRef = useRef(null);
  const [webhooks, setWebhooks] = useState({});
  const [saved, setSaved]       = useState(new Set());
  const [saving, setSaving]     = useState(false);

  const neededGroups = [...new Set(
    APPS.filter(a => selected.has(a.id) && !["zapier","dominos"].includes(a.auth)).map(a => a.auth)
  )];
  const zapierApps  = APPS.filter(a => selected.has(a.id) && a.auth === "zapier");
  const dominosApps = APPS.filter(a => selected.has(a.id) && a.auth === "dominos");

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

        {dominosApps.map(app => (
          <div key={app.id} className={`connect-card connect-card--col ${saved.has(app.id)?"connect-card--done":""}`}>
            <div className="cc-left">
              <img src={app.icon} alt={app.label} className="cc-icon" onError={e=>e.target.style.opacity=0} />
              <div>
                <div className="cc-label">{app.label}</div>
                <div className="cc-apps">Domino's account</div>
              </div>
              {saved.has(app.id) && <span className="badge badge--ok" style={{marginLeft:"auto"}}>✓ Saved</span>}
            </div>
            {!saved.has(app.id) && (
              <DominosCredForm appId={app.id} userId={userId}
                onSaved={id => setSaved(prev => new Set([...prev, id]))} />
            )}
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
  const { user, isAuthenticated } = useAuth0();
  const [step, setStep]     = useState("welcome");
  const [selected, setSelected] = useState(new Set());
  const [theme]             = useState(() => { const t = loadTheme(); applyTheme(t); return t; });

  const userId = isAuthenticated ? (user?.email || user?.sub || "") : "";

  const { connected, refresh } = useConnections(userId);
  const next = () => setStep(s => STEPS[STEPS.indexOf(s)+1]);

  return (
    <div className={`shell${step === "select" || step === "connect" ? " shell--light" : ""}`}>
      {step !== "welcome" && step !== "done" && <TopBar theme={theme} />}

      {step==="welcome" && <WelcomeStep onNext={next} theme={theme} />}
      {step==="select"  && <SelectStep  selected={selected} setSelected={setSelected} onNext={next} />}
      {step==="connect" && <ConnectStep selected={selected} userId={userId} connected={connected} onRefresh={refresh} onDone={next} onBack={() => setStep("select")} />}
      {step==="done"    && <DoneStep    selected={selected} theme={theme} />}
    </div>
  );
}

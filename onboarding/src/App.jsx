import { useState, useEffect, useRef } from "react";
import "./App.css";

const API_BASE = "http://149.248.10.229:8000";

const STEPS = ["welcome", "google", "slack", "done"];

const SERVICE_META = {
  google: {
    label: "Google",
    icon: "https://upload.wikimedia.org/wikipedia/commons/c/c1/Google_%22G%22_logo.svg",
    unlocks: ["Send emails via Gmail", "Create calendar events", "Push & cancel meetings"],
    authUrl: (uid) => `${API_BASE}/auth/google?user_id=${uid}`,
  },
  slack: {
    label: "Slack",
    icon: "https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg",
    unlocks: ["Send messages to any channel", "Send direct messages"],
    authUrl: (uid) => `${API_BASE}/auth/slack?user_id=${uid}`,
  },
};

function useConnections(userId) {
  const [connected, setConnected] = useState(new Set());
  const [loading, setLoading] = useState(false);

  async function refresh() {
    if (!userId) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/user/${userId}/connections`);
      const data = await res.json();
      setConnected(new Set(data.connected || []));
    } catch (_) {}
    setLoading(false);
  }

  useEffect(() => { refresh(); }, [userId]);
  return { connected, refresh, loading };
}

// ── Welcome ──────────────────────────────────────────────────────────────────

function WelcomeStep({ userId, setUserId, onNext }) {
  return (
    <div className="step">
      <div className="step-icon-large">◈</div>
      <h1 className="step-title">Welcome to Flow</h1>
      <p className="step-body">
        Voice-powered automations through your Ray-Ban glasses.<br />
        Let's connect your apps — takes about 60 seconds.
      </p>
      <div className="field">
        <label className="field-label">Your user ID</label>
        <input
          className="text-input"
          value={userId}
          onChange={e => setUserId(e.target.value)}
          placeholder="akshai"
          autoFocus
        />
      </div>
      <button className="btn-primary" onClick={onNext} disabled={!userId.trim()}>
        Get started →
      </button>
    </div>
  );
}

// ── Connect step (Google or Slack) ────────────────────────────────────────────

function ConnectStep({ service, userId, connected, onRefresh, onNext, onSkip }) {
  const meta = SERVICE_META[service];
  const isConnected = connected.has(service);
  const popupRef = useRef(null);

  function openOAuth() {
    popupRef.current = window.open(
      meta.authUrl(userId),
      "oauth",
      "width=520,height=680,left=200,top=100"
    );
    const timer = setInterval(() => {
      if (popupRef.current?.closed) {
        clearInterval(timer);
        onRefresh();
      }
    }, 600);
  }

  return (
    <div className="step">
      <img src={meta.icon} alt={meta.label} className="service-icon" />
      <h2 className="step-title">Connect {meta.label}</h2>
      <p className="step-body">Flow will be able to:</p>
      <ul className="unlocks">
        {meta.unlocks.map(u => (
          <li key={u}><span className="unlock-dot">✦</span>{u}</li>
        ))}
      </ul>

      {isConnected ? (
        <div className="connected-badge">✓ {meta.label} connected</div>
      ) : (
        <button className="btn-service" onClick={openOAuth}>
          <img src={meta.icon} alt="" className="btn-service-icon" />
          Sign in with {meta.label}
        </button>
      )}

      <div className="step-nav">
        {isConnected
          ? <button className="btn-primary" onClick={onNext}>Continue →</button>
          : <button className="btn-ghost" onClick={onSkip}>Skip for now</button>
        }
      </div>
    </div>
  );
}

// ── Done ──────────────────────────────────────────────────────────────────────

function DoneStep({ connected }) {
  const services = [...connected];
  return (
    <div className="step">
      <div className="step-icon-large done-icon">✓</div>
      <h2 className="step-title">You're all set</h2>
      <p className="step-body">
        Put on your glasses and say <em>"Hey Flow"</em> to get started.
      </p>
      {services.length > 0 && (
        <div className="connected-summary">
          {services.map(s => (
            <div key={s} className="summary-row">
              <img src={SERVICE_META[s]?.icon} alt={s} className="summary-icon" />
              <span>{SERVICE_META[s]?.label}</span>
              <span className="summary-check">✓</span>
            </div>
          ))}
        </div>
      )}
      {services.length === 0 && (
        <p className="step-body muted">No apps connected yet — you can always come back to this page.</p>
      )}
    </div>
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function Progress({ step }) {
  const idx = STEPS.indexOf(step);
  const total = STEPS.length - 1;
  return (
    <div className="progress-bar">
      <div className="progress-fill" style={{ width: `${(idx / total) * 100}%` }} />
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [step, setStep] = useState("welcome");
  const [userId, setUserId] = useState("akshai");
  const { connected, refresh } = useConnections(userId);

  const next = () => setStep(s => STEPS[STEPS.indexOf(s) + 1]);

  return (
    <div className="shell">
      <div className="card">
        {step !== "welcome" && step !== "done" && <Progress step={step} />}

        {step === "welcome" && (
          <WelcomeStep userId={userId} setUserId={setUserId} onNext={next} />
        )}
        {step === "google" && (
          <ConnectStep
            service="google"
            userId={userId}
            connected={connected}
            onRefresh={refresh}
            onNext={next}
            onSkip={next}
          />
        )}
        {step === "slack" && (
          <ConnectStep
            service="slack"
            userId={userId}
            connected={connected}
            onRefresh={refresh}
            onNext={next}
            onSkip={next}
          />
        )}
        {step === "done" && <DoneStep connected={connected} />}
      </div>
    </div>
  );
}

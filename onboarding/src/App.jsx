import { useState } from "react";
import "./App.css";

const API_BASE = "http://149.248.10.229:8000";

const APPS = [
  {
    id: "gmail",
    label: "Gmail",
    icon: "https://upload.wikimedia.org/wikipedia/commons/7/7e/Gmail_icon_%282020%29.svg",
    actions: [
      { id: "send_email",  label: "Send Email",  params: "to, subject, body" },
      { id: "draft_email", label: "Draft Email", params: "to, subject, body" },
    ],
  },
  {
    id: "google_calendar",
    label: "Google Calendar",
    icon: "https://upload.wikimedia.org/wikipedia/commons/a/a5/Google_Calendar_icon_%282020%29.svg",
    actions: [
      { id: "create_event", label: "Create Event", params: "title, start_time, end_time, attendees" },
      { id: "push_event",   label: "Push Event",   params: "event_ref, by_minutes" },
      { id: "cancel_event", label: "Cancel Event", params: "event_ref" },
    ],
  },
  {
    id: "slack",
    label: "Slack",
    icon: "https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg",
    actions: [
      { id: "send_dm",      label: "Send DM",      params: "to, message" },
      { id: "send_channel", label: "Send Channel", params: "channel, message" },
    ],
  },
];

export default function App() {
  const [userId, setUserId]     = useState("akshai");
  const [selected, setSelected] = useState(new Set());
  const [webhooks, setWebhooks] = useState({});
  const [saving, setSaving]     = useState(false);
  const [results, setResults]   = useState([]);

  function toggleApp(appId) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(appId) ? next.delete(appId) : next.add(appId);
      return next;
    });
  }

  function setUrl(app, action, url) {
    setWebhooks(prev => ({ ...prev, [`${app}.${action}`]: url }));
  }

  async function save() {
    if (!userId.trim()) return;
    setSaving(true);
    setResults([]);

    const entries = [];
    for (const app of APPS) {
      if (!selected.has(app.id)) continue;
      for (const action of app.actions) {
        const url = webhooks[`${app.id}.${action.id}`]?.trim();
        if (url) entries.push({ app: app.id, action: action.id, url, label: `${app.label} – ${action.label}` });
      }
    }

    const out = await Promise.all(
      entries.map(async ({ app, action, url, label }) => {
        try {
          const res = await fetch(`${API_BASE}/user/${userId}/webhooks`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ app, action, webhook_url: url }),
          });
          return { label, ok: res.ok, error: res.ok ? null : `HTTP ${res.status}` };
        } catch (e) {
          return { label, ok: false, error: e.message };
        }
      })
    );

    setResults(out);
    setSaving(false);
  }

  const anyFilled = APPS.some(app =>
    selected.has(app.id) &&
    app.actions.some(a => webhooks[`${app.id}.${a.id}`]?.trim())
  );

  return (
    <div className="container">
      <div className="header">
        <h1>Flow</h1>
        <p>Connect your apps via Zapier webhooks</p>
      </div>

      <div className="card">
        <label className="field-label">User ID</label>
        <input
          className="text-input"
          value={userId}
          onChange={e => setUserId(e.target.value)}
          placeholder="akshai"
        />
      </div>

      <p className="section-label">Select apps to configure</p>
      <div className="app-row">
        {APPS.map(app => (
          <button
            key={app.id}
            className={`app-btn ${selected.has(app.id) ? "app-btn--active" : ""}`}
            onClick={() => toggleApp(app.id)}
          >
            <img src={app.icon} alt={app.label} className="app-icon" />
            <span>{app.label}</span>
          </button>
        ))}
      </div>

      {APPS.filter(app => selected.has(app.id)).map(app => (
        <div key={app.id} className="card">
          <div className="card-header">
            <img src={app.icon} alt={app.label} className="card-icon" />
            <span className="card-title">{app.label}</span>
          </div>
          {app.actions.map(action => (
            <div key={action.id} className="action-row">
              <div className="action-meta">
                <span className="action-name">{action.label}</span>
                <span className="action-params">sends: {action.params}</span>
              </div>
              <input
                className="text-input webhook-input"
                placeholder="https://hooks.zapier.com/hooks/catch/..."
                value={webhooks[`${app.id}.${action.id}`] || ""}
                onChange={e => setUrl(app.id, action.id, e.target.value)}
              />
            </div>
          ))}
        </div>
      ))}

      {selected.size > 0 && (
        <button
          className={`save-btn ${(!anyFilled || saving) ? "save-btn--disabled" : ""}`}
          onClick={save}
          disabled={saving || !anyFilled}
        >
          {saving ? "Saving…" : "Save Webhooks"}
        </button>
      )}

      {results.length > 0 && (
        <div className="results">
          {results.map((r, i) => (
            <div key={i} className={`result-row ${r.ok ? "result-row--ok" : "result-row--err"}`}>
              <span className="result-dot">{r.ok ? "✓" : "✗"}</span>
              <span>{r.label}</span>
              {r.error && <span className="result-error">{r.error}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

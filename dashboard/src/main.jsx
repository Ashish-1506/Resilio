import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertTriangle,
  Bot,
  ChevronDown,
  ChevronUp,
  Cpu,
  Database,
  Flame,
  MessageSquareText,
  Pause,
  Play,
  Radio,
  RefreshCw,
  Server,
  ShieldCheck,
  Siren,
  Sparkles,
  Zap,
} from 'lucide-react';
import { Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import './styles.css';

const services = [
  { id: 'resilio-gateway', name: 'API Gateway', detail: 'edge / port 3000', icon: Server },
  { id: 'resilio-order-service', name: 'Order Service', detail: 'FastAPI / port 8000', icon: Activity },
  { id: 'resilio-postgres', name: 'PostgreSQL', detail: 'primary datastore', icon: Database },
];

function App() {
  const [statuses, setStatuses] = useState(Object.fromEntries(services.map((service) => [service.id, 'healthy'])));
  const [metrics, setMetrics] = useState({ latency: 0, errors: 0 });
  const [chart, setChart] = useState([{ time: 'now', latency: 0, errors: 0 }]);
  const [incidents, setIncidents] = useState([]);
  const [target, setTarget] = useState('resilio-order-service');
  const [duration, setDuration] = useState(10);
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('Listening for telemetry');
  const [chatOpen, setChatOpen] = useState(true);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState([
    { role: 'assistant', content: 'Ask about recent latency, service health, or incident context.' },
  ]);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/incidents`);

    socket.onmessage = (message) => {
      const event = JSON.parse(message.data);
      if (event.type === 'health') {
        if (event.services) setStatuses(normalizeStatuses(event.services));
        const latency = valueFromResults(event.metrics?.latency_p95);
        const errors = valueFromResults(event.metrics?.error_rate);
        const safeLatencyMs = latency * 1000;
        const safeErrorPct = errors * 100;
        setMetrics({ latency: safeLatencyMs, errors: safeErrorPct });
        setChart((current) => [
          ...current,
          {
            time: new Date().toLocaleTimeString([], { minute: '2-digit', second: '2-digit' }),
            latency: Math.round(safeLatencyMs),
            errors: Number(safeErrorPct.toFixed(2)),
          },
        ].slice(-24));
      }

      if (event.type === 'incident') {
        setIncidents((current) => [event, ...current].slice(0, 8));
        if (event.report?.root_cause_service) {
          setStatuses((current) => ({ ...current, [event.report.root_cause_service]: 'degraded' }));
        }
        setNotice(`Incident ${String(event.report?.incident_id || 'new').slice(0, 8)} detected`);
      }
    };

    socket.onopen = () => setNotice('Live telemetry connected');
    socket.onerror = () => setNotice('Telemetry connection unavailable');

    const trafficTimer = window.setInterval(() => fetch('/api/orders').catch(() => {}), 4000);
    return () => {
      socket.close();
      window.clearInterval(trafficTimer);
    };
  }, []);

  const healthyCount = useMemo(
    () => Object.values(statuses).filter((status) => status === 'healthy').length,
    [statuses],
  );
  const totalServices = services.length;
  const uptimePct = Math.round((healthyCount / totalServices) * 100);
  const latestIncident = incidents[0];

  async function triggerChaos(kind) {
    setBusy(kind);
    setNotice(`Running ${kind} on ${target}`);
    try {
      const endpoint = kind === 'freeze' ? '/api/chaos/freeze' : `/api/chaos/${kind}`;
      const body = kind === 'freeze' ? { container_name: target, duration: Number(duration) } : { container_name: target };
      const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Chaos request failed');
      setNotice(`${kind} completed on ${target}`);
    } catch (error) {
      setNotice(error.message);
    } finally {
      setBusy('');
    }
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    const trimmedQuery = chatInput.trim();
    if (!trimmedQuery || chatLoading) return;

    setChatLoading(true);
    setChatMessages((current) => [...current, { role: 'user', content: trimmedQuery }]);
    setChatInput('');

    try {
      const response = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: trimmedQuery }),
      });
      const data = await response.json();
      const answer = data.answer || 'No answer returned.';
      setChatMessages((current) => [...current, { role: 'assistant', content: answer }]);
    } catch (error) {
      setChatMessages((current) => [...current, { role: 'assistant', content: 'Chat service is unavailable right now.' }]);
    } finally {
      setChatLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow-row"><Radio size={12} /> Resilio / control room</div>
          <h1 className="page-title">System pulse</h1>
        </div>
        <div className="status-strip">
          <span className="pulse-dot" />
          {notice}
        </div>
      </header>

      <section className="kpi-banner panel">
        <div className="kpi-grid">
          <MetricCard icon={ShieldCheck} label="Global uptime" value={`${uptimePct}%`} tone="healthy" description="Last 24h service continuity" />
          <MetricCard icon={AlertTriangle} label="Active anomalies" value={latestIncident ? '1' : '0'} tone={latestIncident ? 'warning' : 'healthy'} description={latestIncident ? 'Correlated by AI diagnostics' : 'No active incidents'} />
          <MetricCard icon={Activity} label="p95 latency" value={`${metrics.latency.toFixed(0)} ms`} tone={metrics.latency > 400 ? 'warning' : 'healthy'} description="Current service tail latency" />
        </div>

        <div className="topology-panel">
          <div className="section-header compact">
            <div>
              <p className="eyebrow">Topology</p>
              <h2>Service status</h2>
            </div>
            <div className="health-total">{healthyCount}/{totalServices}</div>
          </div>
          <div className="topology-grid">
            {services.map((service, index) => (
              <div className="service-node-wrap" key={service.id}>
                <div className={`service-node ${statuses[service.id]}`}>
                  <service.icon size={18} />
                  <div>
                    <div className="node-name">{service.name}</div>
                    <div className="node-detail">{service.detail}</div>
                  </div>
                  <span className="service-pill">{statuses[service.id]}</span>
                </div>
                {index < services.length - 1 && <div className="flow-line"><Zap size={12} /></div>}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="content-grid">
        <div className="panel chart-panel">
          <div className="section-header">
            <div>
              <p className="eyebrow">Operational view</p>
              <h2>Latency & error rate</h2>
            </div>
            <button className="icon-button" title="Refresh telemetry" onClick={() => window.location.reload()}>
              <RefreshCw size={15} />
            </button>
          </div>

          <div className="chart-block">
            <div className="chart-label-row">
              <span className="chart-label"><span className="legend-dot blue" /> p95 latency</span>
              <span className="chart-value">{metrics.latency.toFixed(0)} ms</span>
            </div>
            <div className="chart-box">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chart}>
                  <defs>
                    <linearGradient id="cyanFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#53d1f8" stopOpacity={0.42} />
                      <stop offset="100%" stopColor="#53d1f8" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1c3143" vertical={false} />
                  <XAxis dataKey="time" hide />
                  <YAxis hide domain={[0, 'auto']} />
                  <Tooltip
                    cursor={{ stroke: '#5ed4ff', strokeDasharray: '4 4' }}
                    contentStyle={{ background: '#06111d', border: '1px solid #1d3d4d', borderRadius: '12px', color: '#dfeaf0' }}
                  />
                  <Area type="monotone" dataKey="latency" stroke="#53d1f8" fill="url(#cyanFill)" strokeWidth={2.5} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="chart-block">
            <div className="chart-label-row">
              <span className="chart-label"><span className="legend-dot red" /> error rate</span>
              <span className="chart-value">{metrics.errors.toFixed(2)}%</span>
            </div>
            <div className="chart-box mini">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chart}>
                  <CartesianGrid stroke="#1c3143" vertical={false} />
                  <XAxis dataKey="time" hide />
                  <YAxis hide domain={[0, 'auto']} />
                  <Tooltip
                    contentStyle={{ background: '#06111d', border: '1px solid #1d3d4d', borderRadius: '12px', color: '#dfeaf0' }}
                  />
                  <Line type="monotone" dataKey="errors" stroke="#ff7d79" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        <div className="panel control-panel">
          <div className="section-header">
            <div>
              <p className="eyebrow warning">Intervention</p>
              <h2>Chaos control</h2>
            </div>
            <Flame size={20} className="flame" />
          </div>

          <label className="field-label">
            Target container
            <select value={target} onChange={(event) => setTarget(event.target.value)}>
              {services.map((service) => (
                <option value={service.id} key={service.id}>{service.name}</option>
              ))}
            </select>
          </label>

          <label className="field-label">
            Freeze duration <span className="value-hint">{duration}s</span>
            <input type="range" min="1" max="60" value={duration} onChange={(event) => setDuration(event.target.value)} />
          </label>

          <div className="chaos-actions">
            <ChaosButton icon={Pause} label="Freeze" active={busy === 'freeze'} onClick={() => triggerChaos('freeze')} />
            <ChaosButton icon={Siren} label="Crash" active={busy === 'crash'} onClick={() => triggerChaos('crash')} />
            <ChaosButton icon={Cpu} label="CPU spike" active={busy === 'cpu-spike'} onClick={() => triggerChaos('cpu-spike')} />
          </div>

          <div className="tiny-note">
            <ShieldCheck size={14} />
            Temporary, reversible experiments only
          </div>
        </div>
      </section>

      <section className="bottom-grid">
        <div className="panel incident-panel">
          <div className="section-header">
            <div>
              <p className="eyebrow">AI reasoning</p>
              <h2>Incident feed</h2>
            </div>
            <span className="feed-badge">{incidents.length} active</span>
          </div>

          {latestIncident ? (
            <IncidentCard incident={latestIncident} />
          ) : (
            <div className="empty-state">
              <ShieldCheck size={28} />
              <p>No active incidents</p>
              <span>Trigger a controlled experiment to watch Resilio correlate the blast radius.</span>
            </div>
          )}
        </div>
      </section>

      <aside className={`chat-panel ${chatOpen ? 'open' : 'closed'}`}>
        <button className="chat-toggle" onClick={() => setChatOpen((current) => !current)}>
          <MessageSquareText size={16} />
          {chatOpen ? 'Hide AI assistant' : 'Open AI assistant'}
        </button>

        {chatOpen && (
          <div className="chat-window">
            <div className="chat-header">
              <div className="chat-title">
                <Bot size={16} />
                Resilio AI copilot
              </div>
              <Sparkles size={14} className="sparkle" />
            </div>

            <div className="chat-body">
              {chatMessages.map((message, index) => (
                <div key={`${message.role}-${index}`} className={`chat-message ${message.role}`}>
                  {message.content}
                </div>
              ))}
              {chatLoading && <div className="chat-message assistant loading">Analyzing telemetry…</div>}
            </div>

            <form onSubmit={sendChatMessage} className="chat-form">
              <input
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                placeholder="Ask about errors, latency, or service health…"
                aria-label="Ask Resilio AI"
              />
              <button type="submit" disabled={chatLoading || !chatInput.trim()}>
                <Play size={12} />
              </button>
            </form>
          </div>
        )}
      </aside>
    </main>
  );
}

function valueFromResults(results) {
  const result = results?.[0];
  return result ? Number(result.value?.[1] || 0) : 0;
}

function normalizeStatuses(services) {
  return Object.fromEntries(
    Object.entries(services).map(([name, status]) => [
      name,
      status === 'running' ? 'healthy' : status === 'paused' ? 'degraded' : 'down',
    ]),
  );
}

function MetricCard({ icon: Icon, label, value, tone, description }) {
  return (
    <div className={`kpi-card ${tone}`}>
      <div className="kpi-header">
        <div className="kpi-icon"><Icon size={16} /></div>
        <span>{label}</span>
      </div>
      <div className="kpi-value">{value}</div>
      <div className="kpi-description">{description}</div>
    </div>
  );
}

function ChaosButton({ icon: Icon, label, active, onClick }) {
  return (
    <button className="chaos-button" disabled={active} onClick={onClick}>
      <Icon size={16} />
      {active ? <span className="loading-word">Running</span> : label}
    </button>
  );
}

function IncidentCard({ incident }) {
  const report = incident.report || {};
  const [expanded, setExpanded] = useState(false);

  return (
    <article className="incident-card">
      <div className="incident-head">
        <span className="incident-label"><AlertTriangle size={14} /> Anomaly correlated</span>
        <span className="incident-time">{new Date(incident.anomaly?.detected_at || Date.now()).toLocaleTimeString()}</span>
      </div>

      <h3>{report.failure_mode || 'Service degradation detected'}</h3>
      <div className="summary-row">
        <div>
          <span className="summary-key">Diagnosis source</span>
          <strong>{report.diagnosis_source || 'Unknown'}</strong>
        </div>
      </div>
      <div className="summary-row">
        <div>
          <span className="summary-key">Root cause</span>
          <strong>{report.root_cause_service || 'Unidentified'}</strong>
        </div>
        <div>
          <span className="summary-key">Confidence</span>
          <strong>{report.confidence_score || 'N/A'}</strong>
        </div>
      </div>

      <p className="incident-summary">{report.impact_summary || 'The system is experiencing elevated latency or degraded service health.'}</p>

      <div className="remediation-box">
        <div className="remediation-header">
          <Play size={12} />
          Recommended remediation
        </div>
        <code>{report.recommended_remediation || 'Investigate the affected service and validate recovery conditions.'}</code>
      </div>

      <button className="details-toggle" onClick={() => setExpanded((value) => !value)}>
        {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        {expanded ? 'Hide deep telemetry context' : 'View deep telemetry context'}
      </button>

      {expanded && (
        <div className="deep-telemetry">
          <div className="telemetry-box">
            <h4>Prometheus metrics</h4>
            <pre>{JSON.stringify(incident.metrics || {}, null, 2)}</pre>
          </div>
          <div className="telemetry-box">
            <h4>Recent Docker logs</h4>
            <pre>{JSON.stringify(incident.logs || {}, null, 2)}</pre>
          </div>
        </div>
      )}
    </article>
  );
}

export default App;

createRoot(document.getElementById('root')).render(<App />);

import { useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { apiBase, getExperiment, getRuns, runSynthetic, uploadCsv, type ExperimentResult, type PolicyResult, type RunConfig, type RunSummary } from './api'

const initialConfig: RunConfig = {
  interval_seconds: 60,
  initial_replicas: 2,
  readiness_delay_steps: 2,
  forecast_horizon_steps: 2,
  forecast_bias: 0,
  forecast_noise_std: 0,
  forecast_lag_steps: 0,
  forecast_degradation_start_step: null,
  forecast_degradation_bias: 0,
  forecast_seed: 42,
  policy: {
    target_utilization: 0.7, min_replicas: 1, max_replicas: 20,
    max_scale_up_step: 4, max_scale_down_step: 2, cooldown_steps: 2,
    correction_error_threshold: 0.3, reactive_sustain_steps: 1,
  },
}

const labels: Record<string, string> = { reactive: 'Reactive', predictive: 'Predictive', hybrid: 'HybridScale' }
const colors = { demand: '#293c5b', forecast: '#8b95a5', reactive: '#e2a653', predictive: '#6b91cc', hybrid: '#38a38d' }

function App() {
  const [scenario, setScenario] = useState('burst')
  const [length, setLength] = useState(120)
  const [seed, setSeed] = useState(42)
  const [config, setConfig] = useState<RunConfig>(initialConfig)
  const [result, setResult] = useState<ExperimentResult | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedPolicy, setSelectedPolicy] = useState('hybrid')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refreshRuns = async () => {
    try { setRuns(await getRuns()) } catch { /* API availability is shown in the connection badge */ }
  }
  useEffect(() => { void refreshRuns() }, [])

  const selected = result?.policies.find(p => p.policy === selectedPolicy) ?? result?.policies[0]
  const chartData = useMemo(() => {
    if (!result) return []
    return result.policies[0]?.steps.map((row, i) => ({
      step: row.step,
      demand: row.demand,
      forecast: row.forecast,
      reactive: result.policies.find(p => p.policy === 'reactive')?.steps[i]?.ready_replicas,
      predictive: result.policies.find(p => p.policy === 'predictive')?.steps[i]?.ready_replicas,
      hybrid: result.policies.find(p => p.policy === 'hybrid')?.steps[i]?.ready_replicas,
      violation: row.capacity_violation,
    })) ?? []
  }, [result])

  async function startRun() {
    setBusy(true); setError(''); setNotice('')
    try {
      const started = file
        ? await uploadCsv(file, config)
        : await runSynthetic(scenario, length, seed, config)
      const detail = await getExperiment(started.run_id)
      setResult(detail); setSelectedPolicy('hybrid')
      setNotice(`Run saved · ${detail.workload.steps} workload steps · result type: simulation`)
      await refreshRuns()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not run experiment') }
    finally { setBusy(false) }
  }

  async function openRun(id: string) {
    setBusy(true); setError('')
    try { setResult(await getExperiment(id)); setNotice('Loaded saved simulation run') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load run') }
    finally { setBusy(false) }
  }

  function setNumber(path: 'interval_seconds' | 'initial_replicas' | 'readiness_delay_steps' | 'forecast_horizon_steps', value: number) {
    setConfig(c => ({ ...c, [path]: value }))
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">H</div><div><strong>HybridScale</strong><span>Research workbench</span></div></div>
      <div className="side-label">WORKSPACE</div>
      <button className="nav-item active"><span className="nav-icon">◷</span> Experiments</button>
      <div className="side-label history-label">RECENT RUNS</div>
      <div className="run-list">{runs.length === 0 ? <p className="empty-side">Your saved experiments<br />will appear here.</p> : runs.slice(0, 12).map(run =>
        <button key={run.id} className={`history-item ${result?.run_id === run.id ? 'current' : ''}`} onClick={() => void openRun(run.id)}>
          <span className="history-dot" /><span className="history-copy"><b>{run.workload.scenario || 'workload'}</b><small>{new Date(run.created_at).toLocaleString()}</small></span>
        </button>)}</div>
      <div className="sidebar-foot"><span className="status-dot" /> Local research environment</div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div><span className="crumb">Research</span><span className="slash">/</span><strong>Experiment studio</strong></div><span className="mode-pill"><i /> SIMULATION MODE</span></header>
      <div className="page-wrap">
        <section className="page-heading">
          <div><div className="eyebrow">AUTOSCALING POLICY EVALUATION</div><h1>Experiment studio</h1><p>Compare how workload forecasts and reactive correction shape capacity decisions.</p></div>
          <div className="connection"><span className="connection-dot" /> API connection is checked when you run</div>
        </section>

        <section className="workspace-grid">
          <div className="panel config-panel">
            <div className="panel-title"><div><span className="step-tag">01</span><h2>Configure workload</h2></div><span className="subtle">Required</span></div>
            <div className="field"><label>Workload source</label><div className="segmented"><button className={!file ? 'selected' : ''} onClick={() => setFile(null)}>Synthetic</button><button className={file ? 'selected' : ''} onClick={() => document.getElementById('csv-upload')?.click()}>Upload CSV</button></div><input id="csv-upload" type="file" accept=".csv,text/csv" hidden onChange={e => setFile(e.target.files?.[0] ?? null)} />
              {file && <div className="file-chip"><span>CSV</span>{file.name}<button onClick={() => setFile(null)}>×</button></div>}
            </div>
            {!file && <div className="field-row"><div className="field"><label htmlFor="scenario">Scenario</label><select id="scenario" value={scenario} onChange={e => setScenario(e.target.value)}><option value="stable">Stable demand</option><option value="gradual">Gradual rise and fall</option><option value="burst">Burst / sale peak</option><option value="periodic">Periodic demand</option><option value="volatile">Volatile demand</option><option value="shift">Persistent level shift</option></select></div><div className="field"><label htmlFor="length">Steps</label><input id="length" type="number" min="10" max="100000" value={length} onChange={e => setLength(Number(e.target.value))} /></div></div>}
            {!file && <div className="field"><label htmlFor="seed">Random seed</label><input id="seed" type="number" value={seed} onChange={e => setSeed(Number(e.target.value))} /><small>Fixed seeds make generated workloads repeatable.</small></div>}
            <div className="divider" />
            <div className="panel-title compact"><div><span className="step-tag">02</span><h2>Simulation settings</h2></div></div>
            <div className="field-row"><NumberField label="Initial replicas" value={config.initial_replicas} min={1} max={100} onChange={v => setNumber('initial_replicas', v)} /><NumberField label="Readiness delay (steps)" value={config.readiness_delay_steps} min={0} max={100} onChange={v => setNumber('readiness_delay_steps', v)} /></div>
            <div className="field-row"><NumberField label="Forecast horizon (steps)" value={config.forecast_horizon_steps} min={1} max={100} onChange={v => setNumber('forecast_horizon_steps', v)} /><NumberField label="Interval (seconds)" value={config.interval_seconds} min={1} max={3600} onChange={v => setNumber('interval_seconds', v)} /></div>
            <div className="field-row"><NumberField label="Target utilization" value={config.policy.target_utilization} min={0.1} max={1} step={0.05} format="percent" onChange={v => setConfig(c => ({ ...c, policy: { ...c.policy, target_utilization: v } }))} /><NumberField label="Forecast error correction" value={config.policy.correction_error_threshold} min={0} max={2} step={0.05} format="percent" onChange={v => setConfig(c => ({ ...c, policy: { ...c.policy, correction_error_threshold: v } }))} /></div>
            <div className="divider" />
            <div className="field"><label>Forecast stress test</label><small>Apply the same controlled error to all policy comparisons.</small></div>
            <div className="field-row"><NumberField label="Forecast bias" value={config.forecast_bias} min={-1} max={5} step={0.05} onChange={v => setConfig(c => ({ ...c, forecast_bias: v }))} /><NumberField label="Noise standard deviation" value={config.forecast_noise_std} min={0} max={5} step={0.05} onChange={v => setConfig(c => ({ ...c, forecast_noise_std: v }))} /></div>
            <div className="field-row"><NumberField label="Forecast lag (steps)" value={config.forecast_lag_steps} min={0} max={100} onChange={v => setConfig(c => ({ ...c, forecast_lag_steps: v }))} /><NumberField label="Degradation starts at step" value={config.forecast_degradation_start_step ?? 100000} min={0} max={100000} onChange={v => setConfig(c => ({ ...c, forecast_degradation_start_step: v >= 100000 ? null : v }))} /></div>
            <div className="field"><NumberField label="Degradation bias" value={config.forecast_degradation_bias} min={-1} max={5} step={0.05} onChange={v => setConfig(c => ({ ...c, forecast_degradation_bias: v }))} /></div>
            <button className="primary-button" onClick={() => void startRun()} disabled={busy}>{busy ? <><span className="spinner" /> Running experiment…</> : <><span>▶</span> Run policy comparison</>}</button>
            <p className="privacy-note">Runs the same workload through all three policies. Nothing is sent to Kubernetes.</p>
          </div>

          <div className="right-stack">
            {error && <div className="alert error"><b>Run failed</b><span>{error}</span></div>}
            {notice && <div className="alert success"><b>{notice}</b><button onClick={() => setNotice('')}>×</button></div>}
            {!result ? <div className="panel welcome-panel"><div className="welcome-graphic"><div className="graphic-orbit orbit-one"/><div className="graphic-orbit orbit-two"/><div className="graphic-core">H</div><span className="graphic-node node-a"/><span className="graphic-node node-b"/><span className="graphic-node node-c"/></div><div className="eyebrow">A CONTROLLED STARTING POINT</div><h2>See the policy decisions, step by step.</h2><p>Generate a repeatable workload or upload a CSV, then compare reactive, predictive, and HybridScale behavior under matched settings.</p><div className="welcome-points"><span>✓ Same workload per policy</span><span>✓ Pending replicas modeled</span><span>✓ Per-step results exportable</span></div></div> : <>
              <div className="panel result-heading"><div><span className="eyebrow">RESULT · {result.result_type.toUpperCase()}</span><h2>{result.workload.scenario.replaceAll('_', ' ')} workload</h2><p>{result.workload.steps} steps · {result.workload.unit} · Seed {result.workload.seed ?? '—'}</p></div><a className="export-button" href={`${apiBase}/api/experiments/${result.run_id}/export`}>↓ Export CSV</a></div>
              <div className="metric-grid">{metricCards(selected).map(card => <div className="metric-card" key={card.label}><span>{card.label}</span><strong>{card.value}</strong><small>{card.note}</small></div>)}</div>
              <div className="panel chart-panel"><div className="chart-head"><div><h2>Demand and ready capacity</h2><p>Forecast target accounts for the configured readiness horizon.</p></div><div className="policy-switch">{result.policies.map(p => <button key={p.policy} className={selectedPolicy === p.policy ? `on ${p.policy}` : ''} onClick={() => setSelectedPolicy(p.policy)}>{labels[p.policy]}</button>)}</div></div>
                <div className="chart-legend"><span><i className="legend-demand"/> Demand</span><span><i className="legend-forecast"/> Persistence forecast</span><span><i className="legend-capacity"/> {labels[selectedPolicy]} ready replicas</span></div>
                <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartData} margin={{ top: 10, right: 18, left: -14, bottom: 0 }}><CartesianGrid stroke="#edf0f3" vertical={false} /><XAxis dataKey="step" tickLine={false} axisLine={false} tick={{ fill: '#8993a1', fontSize: 11 }} /><YAxis tickLine={false} axisLine={false} tick={{ fill: '#8993a1', fontSize: 11 }} /><Tooltip contentStyle={{ border: '1px solid #e4e8ed', borderRadius: 10, boxShadow: '0 8px 24px #10213b12' }} /><Legend content={() => null} /><Line type="monotone" dataKey="demand" name="Demand" stroke={colors.demand} strokeWidth={2.5} dot={false} /><Line type="monotone" dataKey="forecast" name="Forecast" stroke={colors.forecast} strokeWidth={1.5} strokeDasharray="5 5" dot={false} /><Line type="stepAfter" dataKey={selectedPolicy} name="Ready replicas" stroke={colors[selectedPolicy as keyof typeof colors]} strokeWidth={2.5} dot={false} /></LineChart></ResponsiveContainer></div>
                <div className="chart-foot"><span>Capacity-proxy view</span><span>Latency is not modeled</span></div>
              </div>
              <div className="panel table-panel"><div className="chart-head"><div><h2>Policy comparison</h2><p>Measured simulation metrics; no latency or monetary cost claims.</p></div></div><PolicyTable policies={result.policies} /></div>
              <div className="panel limitations"><b>Interpretation</b><p>{result.limitations.join(' ')}</p></div>
            </>}
          </div>
        </section>
      </div>
    </main>
  </div>
}

function NumberField({ label, value, min, max, step = 1, format, onChange }: { label: string; value: number; min: number; max: number; step?: number; format?: 'percent'; onChange: (n: number) => void }) {
  return <div className="field"><label>{label}</label><div className="input-suffix"><input type="number" min={min} max={max} step={step} value={format === 'percent' ? Math.round(value * 100) : value} onChange={e => onChange(Number(e.target.value) / (format === 'percent' ? 100 : 1))} />{format === 'percent' && <span>%</span>}</div></div>
}

function metricCards(policy: PolicyResult | undefined) {
  if (!policy) return []
  const m = policy.metrics
  return [
    { label: 'Capacity violation', value: `${(Number(m.capacity_violation_rate ?? 0) * 100).toFixed(1)}%`, note: `${m.capacity_violation_steps ?? 0} steps below demand` },
    { label: 'Unmet demand', value: Number(m.total_unmet_demand ?? 0).toFixed(1), note: 'Replica-capacity units · steps' },
    { label: 'Excess capacity', value: Number(m.total_excess_capacity ?? 0).toFixed(1), note: 'Resource-use proxy · steps' },
    { label: 'Forecast MAE', value: m.forecast_mae == null ? '—' : Number(m.forecast_mae).toFixed(2), note: 'Matured predictions only' },
  ]
}

function PolicyTable({ policies }: { policies: PolicyResult[] }) {
  return <div className="table-scroll"><table><thead><tr><th>Policy</th><th>Capacity violations</th><th>Unmet demand</th><th>Excess capacity</th><th>Mean utilization</th><th>Scale churn</th><th>Forecast MAE</th></tr></thead><tbody>{policies.map(p => <tr key={p.policy}><td><span className={`policy-dot ${p.policy}`} />{labels[p.policy]}</td><td>{(Number(p.metrics.capacity_violation_rate ?? 0) * 100).toFixed(1)}%</td><td>{Number(p.metrics.total_unmet_demand ?? 0).toFixed(2)}</td><td>{Number(p.metrics.total_excess_capacity ?? 0).toFixed(2)}</td><td>{(Number(p.metrics.mean_utilization ?? 0) * 100).toFixed(1)}%</td><td>{Number(p.metrics.scale_churn_replicas ?? 0)}</td><td>{p.metrics.forecast_mae == null ? '—' : Number(p.metrics.forecast_mae).toFixed(2)}</td></tr>)}</tbody></table></div>
}

export default App

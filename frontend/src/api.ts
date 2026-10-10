export type RunConfig = {
  interval_seconds: number
  initial_replicas: number
  readiness_delay_steps: number
  forecast_horizon_steps: number
  forecast_bias: number
  forecast_noise_std: number
  forecast_lag_steps: number
  forecast_degradation_start_step: number | null
  forecast_degradation_bias: number
  forecast_seed: number
  policy: {
    target_utilization: number
    min_replicas: number
    max_replicas: number
    max_scale_up_step: number
    max_scale_down_step: number
    cooldown_steps: number
    correction_error_threshold: number
    reactive_sustain_steps: number
  }
}

export type StepRow = {
  step: number
  timestamp: number
  demand: number
  forecast: number
  ready_replicas: number
  desired_replicas: number
  pending_replicas: number
  capacity: number
  capacity_violation: boolean
  unmet_demand: number
  excess_capacity: number
  utilization: number
  forecast_nmae: number | null
  reasons: string[]
}

export type PolicyResult = {
  policy: string
  metrics: Record<string, number | boolean | null>
  steps: StepRow[]
}

export type ExperimentResult = {
  run_id: string
  result_type: string
  workload: { scenario: string; seed: number | null; steps: number; unit: string }
  policies: PolicyResult[]
  limitations: string[]
}

export type RunSummary = {
  id: string
  created_at: string
  result_type: string
  workload: { scenario: string; seed: number | null; steps: number }
  summary: Record<string, Record<string, number | boolean | null>>
}

const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

async function check(response: Response) {
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try { message = (await response.json()).detail ?? message } catch { /* keep status message */ }
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message))
  }
  return response.json()
}

export async function runSynthetic(scenario: string, length: number, seed: number, config: RunConfig) {
  return check(await fetch(`${API}/api/experiments/synthetic`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario, length, seed, config }),
  })) as Promise<{ run_id: string; summary: Record<string, ExperimentResult['policies'][number]['metrics']>; detail_url: string; export_url: string }>
}

export async function getExperiment(id: string) {
  return check(await fetch(`${API}/api/experiments/${id}`)) as Promise<ExperimentResult>
}

export async function getRuns() {
  return check(await fetch(`${API}/api/experiments?limit=30`)) as Promise<RunSummary[]>
}

export async function uploadCsv(file: File, config: RunConfig) {
  const body = new FormData()
  body.set('file', file)
  body.set('config_json', JSON.stringify(config))
  return check(await fetch(`${API}/api/experiments/upload-csv`, { method: 'POST', body })) as Promise<{ run_id: string; summary: Record<string, Record<string, number | boolean | null>> }>
}

export const apiBase = API

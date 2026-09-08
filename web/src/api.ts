export type PipelineStatus = 'ok' | 'degraded' | 'unavailable'

export interface PipelineHealth {
  status: PipelineStatus
  clickhouse_reachable: boolean
  raw_events: number
  dead_letter_events: number
  last_event_ts: string | null
  last_ingest_ts: string | null
  ingest_lag_seconds: number | null
  detail: string | null
}

export async function fetchPipelineHealth(): Promise<PipelineHealth> {
  const response = await fetch('/api/health/pipeline')
  if (!response.ok) {
    throw new Error(`pipeline health returned ${response.status}`)
  }
  return (await response.json()) as PipelineHealth
}

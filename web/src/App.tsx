import { useQuery } from '@tanstack/react-query'

import { fetchPipelineHealth } from './api'

function formatLag(seconds: number | null): string {
  if (seconds === null) return 'no events yet'
  if (seconds < 90) return `${seconds.toFixed(1)}s ago`
  return `${(seconds / 60).toFixed(1)}m ago`
}

export default function App() {
  const { data, error, isPending } = useQuery({
    queryKey: ['pipeline-health'],
    queryFn: fetchPipelineHealth,
    refetchInterval: 5000,
  })

  return (
    <div className="shell">
      <h1>Riffle</h1>
      <p className="gloss">
        riffle &middot; <i>n.</i> the fast, shallow stretch of a stream where the water runs over
        stones
      </p>

      <section className="panel">
        <header>Pipeline &mdash; M1 ingest spine</header>

        {isPending && <p className="detail">Reading /api/health/pipeline&hellip;</p>}

        {error && <p className="detail">API unreachable &mdash; is `make demo` running?</p>}

        {data && (
          <>
            <dl className="rows">
              <div>
                <dt>Status</dt>
                <dd>
                  <span className={`badge ${data.status}`}>{data.status}</span>
                </dd>
              </div>
              <div>
                <dt>Raw events</dt>
                <dd>{data.raw_events.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Dead letter</dt>
                <dd>{data.dead_letter_events.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Last arrival</dt>
                <dd>{formatLag(data.ingest_lag_seconds)}</dd>
              </div>
            </dl>
            {data.detail && <p className="detail">{data.detail}</p>}
          </>
        )}
      </section>
    </div>
  )
}

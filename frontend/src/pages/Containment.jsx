import { useState } from 'react'
import { FlaskConical, Play } from 'lucide-react'
import { ErrorState, LoadingState } from '../components/Common'
import { api } from '../services/api'
import { useApi } from '../hooks/useApi'

const actions = [
  { id: 'isolate_host', label: 'Isolate affected host' },
  { id: 'disable_account', label: 'Disable compromised account' },
  { id: 'block_ip', label: 'Block suspicious IP' },
  { id: 'restrict_server', label: 'Restrict server access' },
]

export default function Containment() {
  const [entityId, setEntityId] = useState('HOST-001')
  const [selected, setSelected] = useState(['isolate_host'])
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState(null)
  const incidents = useApi(api.incidents)

  async function runSimulation() {
    setRunning(true)
    setRunError(null)
    try {
      setResult(await api.containment({ entity_id: entityId, actions: selected, depth: 3 }))
    } catch (error) {
      setRunError(error)
    } finally {
      setRunning(false)
    }
  }

  function toggle(id) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  }

  const before = result?.before || {}
  const after = result?.after || {}
  return (
    <div className="space-y-5">
      <div><h1 className="text-xl font-semibold">Containment Simulation</h1><p className="mt-1 text-sm text-slate-500">Hypothetical graph containment — no production action is executed</p></div>
      <div className="grid gap-4 xl:grid-cols-[280px_1fr]">
        <aside className="panel p-4">
          <h2 className="font-semibold">Simulation setup</h2>
          <label className="mt-4 block text-xs font-semibold uppercase tracking-wider text-slate-500">Source entity</label>
          <input className="field mt-2 w-full" value={entityId} onChange={(e) => setEntityId(e.target.value)} />
          <label className="mt-5 block text-xs font-semibold uppercase tracking-wider text-slate-500">Containment actions</label>
          <div className="mt-2 space-y-2">
            {actions.map((action) => (
              <label key={action.id} className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-sm ${selected.includes(action.id) ? 'border-cyan-400/30 bg-cyan-400/[0.07]' : 'border-slate-800 hover:bg-slate-800/40'}`}>
                <input type="checkbox" checked={selected.includes(action.id)} onChange={() => toggle(action.id)} className="accent-cyan-400" />
                {action.label}
              </label>
            ))}
          </div>
          <button className="primary-button mt-5 w-full" onClick={runSimulation} disabled={running || !selected.length}>
            <Play size={15} />{running ? 'Running...' : 'Run simulation'}
          </button>
          {incidents.loading ? null : <div className="mt-4 rounded-lg bg-slate-900 p-3 text-xs text-slate-500">Target incident: {incidents.data?.items?.[0]?.id || 'Not required'}</div>}
        </aside>
        <section className="space-y-4">
          {runError ? <ErrorState error={runError} /> : !result ? (
            <div className="grid min-h-64 place-items-center rounded-xl border border-dashed border-slate-800 bg-soc-900 text-center">
              <div><FlaskConical className="mx-auto mb-3 text-slate-600" /><div className="text-sm text-slate-400">Configure and run a containment scenario</div></div>
            </div>
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-2">
                {[['Before containment', before], ['After containment', after]].map(([title, state]) => (
                  <div className="panel p-5" key={title}>
                    <h2 className="font-semibold">{title}</h2>
                    <div className="mt-4 grid grid-cols-2 gap-3">
                      {[['Reachable entities', state.reachable_entities_count], ['Critical assets', state.critical_assets_remaining], ['Potential users', state.potentially_affected_users], ['Residual risk', state.residual_risk]].map(([label, value]) => (
                        <div key={label} className="rounded-lg bg-soc-950 p-3"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-xl font-semibold">{value ?? '—'}</div></div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="panel p-5">
                <h2 className="font-semibold">Analyst recommendation</h2>
                <p className="mt-2 text-sm leading-6 text-slate-300">{result.recommendation || 'No recommendation returned by the backend.'}</p>
                {result.connectivity_removed > 0 && <div className="mt-4 text-xs text-slate-500">{result.connectivity_removed} modeled connection(s) removed in the simulation.</div>}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}

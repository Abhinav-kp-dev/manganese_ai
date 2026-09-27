import { useState } from "react";
import { CheckCircle2, Download, ExternalLink, Play, Upload, XCircle } from "lucide-react";
import { api, useApi } from "../api.js";
import { useI18n } from "../i18n.jsx";
import { useAuth } from "../auth.jsx";
import { Card, Note, PageHeader, StaleNote, useLoaded } from "../components/ui.jsx";

export default function Integrity() {
  const { t } = useI18n();
  const { can } = useAuth();
  const q = useApi("/api/integrity");
  const gate = useLoaded(q);
  if (gate) return gate;
  const d = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title={t("nav_integrity")} subtitle="The scientific-integrity checklist is evaluated live against the running models, not written by hand." />
      <StaleNote stale={q.stale} />
      <Card id="checklist" title={`Validation & integrity checklist — ${d.all_pass ? "all checks pass" : "attention needed"}`}>
        <ul className="divide-y divide-ink-800">
          {d.checks.map((c) => (
            <li key={c.id} className="flex items-start gap-3 py-2.5">
              {c.pass === false ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" /> : <CheckCircle2 className={`mt-0.5 h-4 w-4 shrink-0 ${c.pass ? "text-emerald-400" : "text-ink-400"}`} />}
              <div><div className="text-sm">{c.label}</div><div className="text-xs text-ink-400">{c.evidence}</div></div>
            </li>
          ))}
        </ul>
      </Card>

      {d.real_vs_synthetic && (
        <Card id="real-vs-synthetic" title="Synthetic demo vs real data — the same metrics side by side">
          <div className="overflow-x-auto">
            <table className="data text-sm">
              <thead><tr><th>Metric</th><th className="text-right">Synthetic demo</th><th className="text-right">Real data</th><th>Note</th></tr></thead>
              <tbody>{d.real_vs_synthetic.map((r) => (
                <tr key={r.metric}><td>{r.metric}</td>
                  <td className="num text-right">{show(r.synthetic)}</td>
                  <td className="num text-right">{r.real === null ? <span className="text-ink-400">not yet available</span> : show(r.real)}</td>
                  <td className="text-xs text-ink-400">{r.note}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-ink-400">Synthetic numbers show that the pipeline works end to end; only the real-data column says anything about MOIL's ground.</p>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Model card">
          {Object.entries(d.model_card).map(([k, v]) => (
            <div key={k} className="mb-3">
              <div className="text-xs font-semibold uppercase text-mn-300">{k.replace("module", "Module ")}</div>
              <dl className="mt-1 space-y-0.5 text-xs">
                {Object.entries(v).map(([kk, vv]) => <div key={kk}><dt className="inline text-ink-400">{kk.replace(/_/g, " ")}: </dt><dd className="inline text-ink-200">{Array.isArray(vv) ? vv.join(", ") : String(vv)}</dd></div>)}
              </dl>
            </div>
          ))}
        </Card>
        <Card title="Known limitations (stated up front)">
          <ul className="ml-4 list-disc space-y-1.5 text-sm text-ink-300">{d.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          <div className="mt-3"><Note tone="warn">Not usable for statutory reserve reporting. Any UNFC / JORC / CRIRSCO use requires certified drilling, assay and sign-off by an accredited Competent Person.</Note></div>
        </Card>
        <Card title="Records in the database">
          <table className="data text-xs"><thead><tr><th>Table</th><th className="text-right">Synthetic</th><th className="text-right">Real</th></tr></thead>
            <tbody>{Object.entries(d.row_counts).map(([k, v]) => <tr key={k}><td className="font-mono">{k}</td><td className="num text-right">{v.synthetic}</td><td className="num text-right">{v.real}</td></tr>)}</tbody>
          </table>
          <p className="mt-2 text-xs text-ink-400">Every row carries <code>is_synthetic</code>. Once ≥ 240 real production rows exist, training drops synthetic rows entirely.</p>
        </Card>
      </div>

      <Card title="Data sources and how each is used">
        <div className="overflow-x-auto">
          <table className="data text-sm">
            <thead><tr><th>Source</th><th>Provides</th><th>Used for</th><th>Status in this demo</th></tr></thead>
            <tbody>{d.data_sources.map((s) => (
              <tr key={s.name}><td><a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-mn-300">{s.name}<ExternalLink className="h-3 w-3" /></a></td><td className="text-xs text-ink-300">{s.provides}</td><td className="text-xs text-ink-300">{s.used_for}</td>
                <td><span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${s.status === "PUBLIC_REFERENCE" ? "bg-sky-500/15 text-sky-300" : s.status === "REAL_IN_VALIDATION" ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"}`}>{s.status.replace(/_/g, " ")}</span></td></tr>
            ))}</tbody>
          </table>
        </div>
      </Card>

      <Pipeline canRun={can("run_pipeline")} />
      {can("upload_data") ? <Uploader onDone={q.reload} /> : <Note>Uploading MOIL data needs the Administrator, Planner or Geologist role.</Note>}
    </div>
  );
}

const show = (v) => (v === null || v === undefined ? "—" : Array.isArray(v) ? v.join("–") : String(v));

function Pipeline({ canRun }) {
  const q = useApi("/api/pipeline");
  const [busy, setBusy] = useState(null);
  const run = async (job) => {
    setBusy(job);
    try { await api(`/api/pipeline/run/${job}`, { method: "POST" }); } catch { /* shown in run log */ }
    finally { setBusy(null); q.reload(); }
  };
  const d = q.data;
  if (!d) return null;
  const tone = { ok: "text-emerald-300", failed: "text-rose-300", running: "text-amber-300", skipped: "text-ink-400" };
  return (
    <Card id="pipeline" title="Scheduled data pipeline"
      right={canRun && <button className="btn-primary text-xs" disabled={!!busy} onClick={() => run("all")}><Play className="h-3 w-3" /> {busy === "all" ? "Running…" : "Run all now"}</button>}>
      <p className="mb-3 text-xs text-ink-400">
        {d.schedule.enabled ? `Runs automatically every ${d.schedule.interval_minutes} min` : "Automatic schedule disabled (MH_PIPELINE_INTERVAL_MIN=0)"}{d.schedule.next_run ? ` · next ${d.schedule.next_run.slice(0, 16).replace("T", " ")} UTC` : ""}.
        For cron: <code className="text-ink-300">{d.schedule.cron_example}</code>
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        {d.jobs.map((j) => (
          <div key={j.job} className="rounded-lg border border-ink-700 bg-ink-800/40 p-3 text-xs">
            <div className="flex items-center justify-between"><span className="font-mono text-sm text-ink-100">{j.job}</span>
              {canRun && <button className="btn-ghost py-0.5 text-[11px]" disabled={!!busy} onClick={() => run(j.job)}>{busy === j.job ? "…" : "Run"}</button>}</div>
            <p className="mt-1 text-ink-400">{j.description}</p>
            <p className={`mt-2 ${tone[j.last_status] || "text-ink-400"}`}>{j.last_status ? `${j.last_status} — ${j.last_message}` : "never run"}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="text-xs">
          <div className="card-title mb-1">Real external data stored</div>
          {d.external_data.length === 0 ? <p className="text-ink-400">None yet. The NASA POWER job needs internet access to power.larc.nasa.gov.</p> :
            d.external_data.map((x) => <p key={x.source} className="text-ink-300">{x.source}: {x.mine_months} mine-months ({x.from?.slice(0, 7)} → {x.to?.slice(0, 7)})</p>)}
          <p className="mt-1 text-ink-400">Drop MOIL CSV exports into <code>{d.inbox_path}</code>; the inbox job validates and loads them.</p>
        </div>
        <div className="max-h-44 overflow-auto">
          <table className="data text-[11px]"><thead><tr><th>Run</th><th>Job</th><th>Trigger</th><th>Status</th><th>Message</th></tr></thead>
            <tbody>{d.recent_runs.slice(0, 12).map((r) => <tr key={r.id}><td className="font-mono">{r.started_at?.slice(5, 16).replace("T", " ")}</td><td>{r.job}</td><td>{r.trigger}</td><td className={tone[r.status]}>{r.status}</td><td className="text-ink-400">{r.message}</td></tr>)}</tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}

function Uploader({ onDone }) {
  const [file, setFile] = useState(null);
  const [rep, setRep] = useState(null);
  const [busy, setBusy] = useState(false);
  const send = async (commit) => {
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    try { setRep(await api(`/api/data/upload?commit=${commit}`, { method: "POST", body: fd })); if (commit) setTimeout(onDone, 4000); }
    catch (e) { setRep({ errors: [e.detail || "Upload failed"], valid: false }); }
    finally { setBusy(false); }
  };
  return (
    <Card title="Onboard real MOIL production logs (CSV)" right={<a className="btn-ghost text-xs" href="/api/data/template" download="production_logs_template.csv"><Download className="h-3 w-3" /> Template</a>}>
      <p className="mb-3 text-sm text-ink-300">Upload monthly logs in the canonical schema. Rows are validated (mine IDs, month-start dates, physical ranges, duplicates) before anything is stored. Committed rows are stored with <code>is_synthetic = FALSE</code> and the models retrain.</p>
      <div className="flex flex-wrap items-center gap-2">
        <input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files[0]); setRep(null); }} className="text-sm" />
        <button className="btn-ghost" disabled={!file || busy} onClick={() => send(false)}><Upload className="h-4 w-4" /> Validate</button>
        <button className="btn-primary" disabled={!file || busy || !rep?.valid} onClick={() => send(true)}>Commit & retrain</button>
      </div>
      {rep && (
        <div className="mt-3 text-sm">
          {rep.valid ? <div className="text-emerald-300">{rep.rows} rows valid.{rep.committed ? ` ${rep.message}` : " Ready to commit."}</div>
            : <ul className="ml-4 list-disc text-rose-300">{rep.errors.map((e) => <li key={e}>{e}</li>)}</ul>}
          {rep.preview?.length > 0 && (
            <div className="mt-2 overflow-x-auto"><table className="data text-xs"><thead><tr>{Object.keys(rep.preview[0]).map((k) => <th key={k}>{k}</th>)}</tr></thead>
              <tbody>{rep.preview.map((r, i) => <tr key={i}>{Object.values(r).map((v, j) => <td key={j} className="font-mono">{v}</td>)}</tr>)}</tbody></table></div>
          )}
        </div>
      )}
    </Card>
  );
}

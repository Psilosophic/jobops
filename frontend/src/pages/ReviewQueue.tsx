import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { api, QueueItem, ReviewDetail } from "../api";

function money(n: number | null) {
  return n ? `$${(n / 1000).toFixed(0)}k` : "—";
}

export default function ReviewQueue() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<number | null>(null);
  const [modifyOpen, setModifyOpen] = useState(false);
  const [banner, setBanner] = useState<string>("");

  const { data: queue } = useQuery({
    queryKey: ["queue"],
    queryFn: () => api.get<QueueItem[]>("/review"),
  });
  const appId = selected ?? queue?.[0]?.application_id ?? null;
  const { data: detail } = useQuery({
    queryKey: ["review", appId],
    queryFn: () => api.get<ReviewDetail>(`/review/${appId}`),
    enabled: appId !== null,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["queue"] });
    qc.invalidateQueries({ queryKey: ["review", appId] });
  };

  const trackMut = useMutation({
    mutationFn: (slug: string) => api.post(`/review/${appId}/track`, { track_slug: slug }),
    onSuccess: invalidate,
  });
  const submitMut = useMutation({
    mutationFn: () => api.post<Record<string, any>>(`/review/${appId}/submit`),
    onSuccess: (next) => {
      invalidate();
      if (next.mode === "handoff_launch" || next.mode === "manual_assist") {
        window.open(next.launch_url, "_blank", "noopener");
        setBanner(`${next.mode === "manual_assist" ? "Manual assist" : "Handoff"}: official page opened — finish there, then Confirm below.`);
      } else {
        setBanner("Queued for compliant auto-submission.");
      }
    },
    onError: (e) => setBanner(String(e)),
  });
  const confirmMut = useMutation({
    mutationFn: (success: boolean) => api.post(`/review/${appId}/confirm`, { success, detail: "confirmed in UI" }),
    onSuccess: () => { setBanner(""); invalidate(); },
  });

  const move = useCallback((dir: 1 | -1) => {
    if (!queue?.length) return;
    const idx = queue.findIndex((q) => q.application_id === appId);
    const next = queue[(idx + dir + queue.length) % queue.length];
    setSelected(next.application_id);
  }, [queue, appId]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT" || (e.target as HTMLElement)?.tagName === "TEXTAREA") return;
      if (e.key === "j") move(1);
      if (e.key === "k") move(-1);
      if (e.key === "m") setModifyOpen(true);
      if (e.key === "s" && detail && missing.length === 0) submitMut.mutate();
      if (e.key === "t" && detail) {
        const opts = detail.track_options;
        const cur = opts.findIndex((t) => t.selected);
        trackMut.mutate(opts[(cur + 1) % opts.length].slug);
      }
      if (e.key === "Escape") setModifyOpen(false);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  const item = queue?.find((q) => q.application_id === appId);
  const missing = item?.missing_fields ?? [];
  const snap = detail?.packet?.snapshot;
  const policyMode = detail?.policy?.mode ?? "unknown";
  const submitDisabledReason =
    missing.length ? `Missing: ${missing.join(", ")}` :
    policyMode === "discover_only" ? "Source is discover-only — Submit disabled by policy" :
    detail?.application.state !== "queued_for_review" && detail?.application.state !== "modified_by_user"
      ? `State is ${detail?.application.state}` : "";

  if (!queue?.length) return <p className="text-zinc-400">Queue is empty. The worker will fill it — or trigger a source run.</p>;

  return (
    <div className="grid grid-cols-12 gap-4">
      {/* left: queue list */}
      <div className="col-span-3 space-y-2">
        <h2 className="label">Queue ({queue.length}) — j/k to move</h2>
        {queue.map((q) => (
          <button key={q.queue_id} onClick={() => setSelected(q.application_id)}
            className={`card w-full text-left ${q.application_id === appId ? "border-emerald-600" : "hover:border-zinc-600"}`}>
            <div className="truncate text-sm font-medium">{q.title}</div>
            <div className="truncate text-xs text-zinc-400">{q.employer ?? "?"}</div>
            <div className="mt-1 flex items-center gap-2 text-xs">
              <span className="rounded bg-emerald-950 px-1.5 py-0.5 text-emerald-400">{q.fit_score?.toFixed(0)}</span>
              {q.missing_fields.length > 0 && <span className="text-amber-400">⚠ {q.missing_fields.length}</span>}
              {q.duplicate_confidence > 0.5 && <span className="text-zinc-500">dup {Math.round(q.duplicate_confidence * 100)}%</span>}
            </div>
          </button>
        ))}
      </div>

      {/* center: job summary + fit + memory */}
      <div className="col-span-5 space-y-3">
        {detail && item && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {/* Resume Track dropdown */}
              <select value={detail.track_options.find((t) => t.selected)?.slug ?? ""}
                onChange={(e) => trackMut.mutate(e.target.value)}
                className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm">
                {detail.track_options.map((t) => (
                  <option key={t.slug} value={t.slug}>
                    {t.name}{t.score != null ? ` (${(t.score * 100).toFixed(0)})` : ""}
                  </option>
                ))}
              </select>
              <button className="btn-secondary" onClick={() => setModifyOpen(true)}>Modify (m)</button>
              <button className="btn-primary" disabled={Boolean(submitDisabledReason)}
                title={submitDisabledReason} onClick={() => submitMut.mutate()}>
                Submit (s)
              </button>
              <span className="rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-300">policy: {policyMode}</span>
            </div>
            {submitDisabledReason && <p className="text-xs text-amber-400">{submitDisabledReason}</p>}
            {banner && (
              <div className="card border-emerald-800 text-sm">
                {banner}
                <div className="mt-2 flex gap-2">
                  <button className="btn-primary" onClick={() => confirmMut.mutate(true)}>Confirm submitted</button>
                  <button className="btn-secondary" onClick={() => confirmMut.mutate(false)}>It failed</button>
                </div>
              </div>
            )}
            <div className="card">
              <h1 className="text-lg font-bold">{item.title}</h1>
              <p className="text-sm text-zinc-400">
                {item.employer} · {item.location || (item.is_remote ? "Remote" : "?")} ·{" "}
                {money(item.salary_min)}–{money(item.salary_max)} ·{" "}
                <a href={item.url} target="_blank" rel="noreferrer" className="text-emerald-400 underline">posting ↗</a>
              </p>
              <p className="mt-2 text-sm text-zinc-300">{detail.track_why}</p>
            </div>
            {detail.scoring && (
              <div className="card">
                <h3 className="label mb-2">Fit breakdown — total {detail.scoring.total}</h3>
                <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
                  {["title_match", "skill_match", "location_match", "comp_match", "recency",
                    "employer_pref", "track_fit"].map((k) => (
                    <div key={k} className="flex justify-between">
                      <span className="text-zinc-400">{k.replace("_", " ")}</span>
                      <span className="text-emerald-400">+{detail.scoring![k]}</span>
                    </div>
                  ))}
                  {["recruiter_penalty", "contract_penalty", "missing_salary_penalty",
                    "negative_penalty"].filter((k) => detail.scoring![k] > 0).map((k) => (
                    <div key={k} className="flex justify-between">
                      <span className="text-zinc-400">{k.replaceAll("_", " ")}</span>
                      <span className="text-red-400">-{detail.scoring![k]}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* right: packet preview */}
      <div className="col-span-4 space-y-3">
        {snap && (
          <div className="card">
            <h3 className="label mb-2">Application packet v{detail?.packet?.version_no}</h3>
            <p className="text-sm"><span className="text-zinc-500">Track:</span> {snap.track}</p>
            <p className="truncate text-sm"><span className="text-zinc-500">Resume:</span> {snap.resume_file ?? "⚠ none"}</p>
            {snap.cover_note && <p className="mt-1 text-sm"><span className="text-zinc-500">Cover note:</span> {snap.cover_note}</p>}
            <div className="mt-3 space-y-2">
              {(snap.answers ?? []).map((a: any) => (
                <div key={a.answer_name} className="rounded bg-zinc-800/60 p-2 text-sm">
                  <div className="text-xs text-zinc-500">{a.question}</div>
                  <div className={a.status === "missing" ? "text-amber-400" : ""}>
                    {a.text ?? "MISSING — fill via Modify"}
                    {a.user_edited && <span className="ml-2 rounded bg-blue-900 px-1 text-xs">edited</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {modifyOpen && detail && appId !== null && (
        <ModifyDrawer appId={appId} snap={snap} onClose={() => { setModifyOpen(false); invalidate(); }} />
      )}
    </div>
  );
}

function ModifyDrawer({ appId, snap, onClose }: { appId: number; snap: any; onClose: () => void }) {
  const [cover, setCover] = useState<string>(snap?.cover_note ?? "");
  const [summary, setSummary] = useState<string>(snap?.summary ?? "");
  const [answers, setAnswers] = useState<Record<string, string>>(
    Object.fromEntries((snap?.answers ?? []).map((a: any) => [a.answer_name, a.text ?? ""])),
  );
  const save = useMutation({
    mutationFn: () => api.post(`/review/${appId}/modify`, {
      cover_note: cover, summary,
      answers: Object.entries(answers).map(([answer_name, text]) => ({ answer_name, text })),
    }),
    onSuccess: onClose,
  });
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <div className="h-full w-full max-w-lg overflow-y-auto border-l border-zinc-700 bg-zinc-950 p-5"
        onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-4 text-lg font-bold">Modify packet</h2>
        <label className="label">Tailored summary</label>
        <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={3}
          className="mb-3 w-full rounded-md border border-zinc-700 bg-zinc-900 p-2 text-sm" />
        <label className="label">Cover note</label>
        <textarea value={cover} onChange={(e) => setCover(e.target.value)} rows={4}
          className="mb-3 w-full rounded-md border border-zinc-700 bg-zinc-900 p-2 text-sm" />
        {(snap?.answers ?? []).map((a: any) => (
          <div key={a.answer_name} className="mb-3">
            <label className="label">{a.question}</label>
            <input value={answers[a.answer_name] ?? ""}
              onChange={(e) => setAnswers({ ...answers, [a.answer_name]: e.target.value })}
              className="w-full rounded-md border border-zinc-700 bg-zinc-900 p-2 text-sm" />
            {a.original_text && <div className="text-xs text-zinc-500">original: {a.original_text}</div>}
          </div>
        ))}
        <div className="flex gap-2">
          <button className="btn-primary" onClick={() => save.mutate()}>Save (does not submit)</button>
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
        </div>
        {save.error && <p className="mt-2 text-sm text-red-400">{String(save.error)}</p>}
      </div>
    </div>
  );
}

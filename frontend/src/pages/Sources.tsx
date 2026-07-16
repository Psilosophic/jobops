import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";

const MODE_TONE: Record<string, string> = {
  discover_only: "bg-red-950 text-red-300",
  qualify_only: "bg-amber-950 text-amber-300",
  packet_only: "bg-amber-950 text-amber-300",
  queued_for_review: "bg-blue-950 text-blue-300",
  manual_assist: "bg-emerald-950 text-emerald-300",
  auto_submit_allowed: "bg-emerald-900 text-emerald-200",
};

export default function Sources() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["sources"], queryFn: () => api.get<any[]>("/sources") });
  const run = useMutation({
    mutationFn: (id: number) => api.post(`/sources/${id}/run`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Sources & Policy Matrix</h1>
      <div className="grid gap-3 md:grid-cols-2">
        {(data ?? []).map(({ source, policy, last_run }) => (
          <div key={source.id} className="card">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-semibold">{source.name}</span>
                {!source.enabled && <span className="ml-2 text-xs text-zinc-500">(disabled)</span>}
              </div>
              <span className={`rounded px-2 py-0.5 text-xs ${MODE_TONE[policy?.recommended_mode] ?? "bg-zinc-800"}`}>
                {policy?.recommended_mode}
              </span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-zinc-400">
              <span>retrieval: {source.retrieval_method}</span>
              <span>risk: {policy?.risk_level}</span>
              <span>scrape: {policy?.scraping_allowed ? "✓" : "✗"}</span>
              <span>browser: {policy?.browser_automation_allowed ? "✓" : "✗"}</span>
              <span>auto-submit: {policy?.auto_submit_allowed ? "✓" : "✗"}</span>
              <span>review req: {policy?.manual_review_required ? "✓" : "✗"}</span>
            </div>
            {policy?.evidence_notes && (
              <p className="mt-2 text-xs italic text-zinc-500">{policy.evidence_notes}</p>
            )}
            <div className="mt-2 flex items-center justify-between text-xs text-zinc-500">
              <span>
                last run: {last_run ? `${last_run.status} · ${last_run.new} new / ${last_run.fetched} fetched` : "never"}
              </span>
              {source.enabled && (
                <button className="btn-secondary" onClick={() => run.mutate(source.id)}>Run now</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

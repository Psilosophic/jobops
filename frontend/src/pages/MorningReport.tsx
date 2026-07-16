import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api";

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className={`mt-1 text-3xl font-bold ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

export default function MorningReport() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["morning"],
    queryFn: () => api.get<Record<string, any>>("/reports/morning"),
  });
  if (isLoading) return <p className="text-zinc-400">Brewing the morning report…</p>;
  if (error) return <p className="text-red-400">Report error: {String(error)}</p>;
  const states = (data?.applications_by_state ?? {}) as Record<string, number>;
  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Morning Report</h1>
        <span className="text-sm text-zinc-500">for {data?.date}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="New postings" value={data?.new_postings ?? 0} tone="text-emerald-400" />
        <Stat label="Fetched" value={data?.fetched ?? 0} />
        <Stat label="Search runs" value={data?.search_runs ?? 0} />
        <Stat label="Source errors" value={data?.source_errors ?? 0}
          tone={data?.source_errors ? "text-red-400" : "text-zinc-400"} />
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Ready for review" value={states.queued_for_review ?? 0} tone="text-amber-400" />
        <Stat label="Submitted" value={states.submitted ?? 0} tone="text-emerald-400" />
        <Stat label="Blocked by policy" value={states.blocked_by_policy ?? 0} />
        <Stat label="Rejected (low fit)" value={states.rejected_low_fit ?? 0} />
      </div>
      {(states.queued_for_review ?? 0) > 0 && (
        <Link to="/review" className="btn-primary inline-block">
          Review {states.queued_for_review} waiting application{states.queued_for_review === 1 ? "" : "s"} →
        </Link>
      )}
    </div>
  );
}

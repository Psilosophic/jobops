import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";

export default function Jobs() {
  const [minFit, setMinFit] = useState(0);
  const { data } = useQuery({
    queryKey: ["jobs", minFit],
    queryFn: () => api.get<any[]>(`/jobs?min_fit=${minFit}&limit=100`),
  });
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">Jobs</h1>
        <label className="label">min fit</label>
        <input type="range" min={0} max={100} value={minFit}
          onChange={(e) => setMinFit(Number(e.target.value))} />
        <span className="text-sm text-emerald-400">{minFit}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-zinc-800 text-zinc-500">
              <th className="p-2">Fit</th><th className="p-2">Title</th><th className="p-2">Employer</th>
              <th className="p-2">Location</th><th className="p-2">Salary</th><th className="p-2">State</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((row) => (
              <tr key={row.posting.id} className="border-b border-zinc-900 hover:bg-zinc-900/60">
                <td className="p-2 font-mono text-emerald-400">{row.application?.fit_score?.toFixed(0) ?? "—"}</td>
                <td className="p-2">
                  <a href={row.posting.url} target="_blank" rel="noreferrer" className="hover:underline">
                    {row.posting.title}
                  </a>
                </td>
                <td className="p-2 text-zinc-400">{row.employer ?? "?"}</td>
                <td className="p-2 text-zinc-400">{row.posting.is_remote ? "Remote" : row.posting.location_raw}</td>
                <td className="p-2 text-zinc-400">
                  {row.posting.salary_min ? `$${Math.round(row.posting.salary_min / 1000)}k–$${Math.round((row.posting.salary_max ?? row.posting.salary_min) / 1000)}k` : "—"}
                </td>
                <td className="p-2"><span className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs">{row.application?.state ?? "—"}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, PanicStateT } from "../api";

const FLAGS: { key: keyof PanicStateT & string; label: string; danger: string }[] = [
  { key: "submissions_paused", label: "Stop all submissions", danger: "blocks every submit path" },
  { key: "discover_only_all", label: "All sources → discover-only", danger: "no packets, no queue, no submits" },
  { key: "browser_automation_paused", label: "Pause browser automation", danger: "manual-assist falls back to handoff" },
  { key: "outbound_email_paused", label: "Pause outbound email", danger: "reports/alerts stop sending" },
  { key: "review_required_all", label: "Require review for everything", danger: "disables any auto-submit" },
];

export default function PanicDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [intent, setIntent] = useState("");
  const { data: state } = useQuery({ queryKey: ["panic"], queryFn: () => api.get<PanicStateT>("/panic") });
  const { data: events } = useQuery({
    queryKey: ["panic-events"],
    queryFn: () => api.get<any[]>("/panic/events"),
    enabled: open,
  });
  const flagMut = useMutation({
    mutationFn: (p: { flag: string; value: boolean }) =>
      api.post("/panic/flag", { ...p, operator_intent: intent || "(no intent given)" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["panic"] }),
  });
  const stopMut = useMutation({
    mutationFn: () => api.post("/panic/emergency-stop", { operator_intent: intent || "EMERGENCY STOP" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["panic"] }),
  });

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" onClick={onClose}>
      <div className="h-full w-full max-w-md overflow-y-auto border-l border-red-900 bg-zinc-950 p-5"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-bold text-red-400">Panic Panel</h2>
          <button className="btn-secondary" onClick={onClose}>esc</button>
        </div>
        <input value={intent} onChange={(e) => setIntent(e.target.value)}
          placeholder="Operator intent (logged with every action)"
          className="mb-4 w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm" />
        <button className="btn-danger mb-5 w-full py-3 text-base font-bold"
          onClick={() => stopMut.mutate()}>
          EMERGENCY STOP — halt all outbound, keep discovery
        </button>
        <div className="space-y-3">
          {FLAGS.map((f) => (
            <label key={f.key} className="card flex cursor-pointer items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium">{f.label}</div>
                <div className="text-xs text-zinc-500">{f.danger}</div>
              </div>
              <input type="checkbox" className="h-5 w-5 accent-red-600"
                checked={Boolean(state?.[f.key])}
                onChange={(e) => flagMut.mutate({ flag: f.key, value: e.target.checked })} />
            </label>
          ))}
        </div>
        <h3 className="label mt-6 mb-2">Recent panic events / prevented actions</h3>
        <div className="space-y-1 text-xs text-zinc-400">
          {(events ?? []).slice(0, 20).map((e) => (
            <div key={e.id} className="rounded bg-zinc-900 px-2 py-1">
              <span className="text-zinc-500">{e.created_at?.slice(0, 19)}</span>{" "}
              <span className={e.action === "prevented" ? "text-red-400" : ""}>{e.action}</span>
              {e.operator_intent ? ` — ${e.operator_intent}` : ""}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

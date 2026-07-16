const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  get: <T>(path: string) => req<T>(path),
  post: <T>(path: string, body?: unknown) =>
    req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    req<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
};

export interface QueueItem {
  queue_id: number; application_id: number; title: string; employer: string | null;
  fit_score: number | null; state: string; missing_fields: string[]; url: string;
  location: string; is_remote: boolean; salary_min: number | null;
  salary_max: number | null; duplicate_confidence: number; queued_at: string;
}

export interface TrackOption { slug: string; name: string; score: number | null; selected: boolean; }

export interface ReviewDetail {
  application: { id: number; state: string; fit_score: number | null; user_modified: boolean };
  posting: Record<string, any>;
  source: { slug: string; name: string };
  policy: { mode: string; auto_submit_allowed: boolean; browser_automation_allowed: boolean } | null;
  scoring: Record<string, any> | null;
  track_options: TrackOption[];
  track_why: string;
  packet: { version_no: number; snapshot: Record<string, any> } | null;
}

export interface PanicStateT {
  submissions_paused: boolean; discover_only_all: boolean;
  browser_automation_paused: boolean; outbound_email_paused: boolean;
  review_required_all: boolean; min_fit_override: number | null;
}

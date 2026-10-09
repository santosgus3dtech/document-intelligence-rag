export type Mode = "hybrid" | "lexical" | "vector";
export type Passage = {
  id: string;
  document_id: string;
  page: number;
  text: string;
  bbox: number[];
  kind: string;
  engine?: string;
  title?: string;
  filename?: string;
  score?: number;
  quote?: string;
  citation_id?: number;
  rows?: string[][];
};
export type Page = { number: number; width: number; height: number };
export type Document = {
  id: string;
  title: string;
  filename: string;
  access: "public" | "restricted";
  status: "queued" | "processing" | "ready" | "failed";
  page_count: number;
  chunk_count: number;
  created_at: string;
  engine?: string;
  error?: string;
  warnings?: string[];
  pages?: Page[];
  passages?: Passage[];
};
export type Session = {
  identity: string;
  demo: boolean;
  can_restricted: boolean;
  can_upload: boolean;
};
export type Answer = {
  answer: string;
  status: string;
  citations: Passage[];
  limitations: string;
  latency_ms: number;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : `Request failed (${response.status}).`,
    );
  }
  return response.json() as Promise<T>;
}
export function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

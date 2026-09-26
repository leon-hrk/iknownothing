export type CourseSummary = { name: string; status: string };

export type Topic = { slug: string; name: string; priority: string; files: string[] };

export type Course = { name: string; status: string; topics: Topic[]; files: string[] };

/** A content block as the Messages API has it: text, tool use, tool result, thinking. */
export type Block = { type: string; text?: string; name?: string; input?: Record<string, string>; [key: string]: unknown };

export type Message = { role: "user" | "assistant"; content: string | Block[] };

export type ChatEvent =
  | { kind: "text"; data: string }
  | { kind: "cheatsheet"; data: { section: string; heading: string; body: string } }
  | { kind: "task"; data: { task: string; tier: "A" | "B" } }
  | { kind: "messages"; data: Message[] }
  | { kind: "error"; data: string };

/** Fired when a request finds no chosen user, e.g. after the user was removed. */
export const UNAUTHORIZED = "ikn-unauthorized";

async function request(url: string, init?: RequestInit): Promise<Response> {
  const r = await fetch(url, init);
  if (r.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED));
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r;
}

async function json<T>(url: string): Promise<T> {
  return (await request(url)).json();
}

export const listUsers = () => json<string[]>("/api/users");

/** The chosen user, or null. */
export async function currentUser(): Promise<string | null> {
  const r = await fetch("/api/user");
  if (r.status === 401) return null;
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return (await r.json()).name;
}

export async function chooseUser(name: string): Promise<void> {
  await request("/api/user", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

const base = (course: string) => `/api/courses/${encodeURIComponent(course)}`;

export const listCourses = () => json<CourseSummary[]>("/api/courses");

export const getCourse = (course: string) => json<Course>(base(course));

export async function readFile(course: string, path: string): Promise<string> {
  return (await request(`${base(course)}/files/${path}`)).text();
}

/** Streams the reply to a transcript that ends with the student's message. */
export async function* chat(
  course: string, topic: string | null, transcript: Message[], signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const r = await request(`${base(course)}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, transcript }),
    signal,
  });
  const reader = r.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += value;
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const lines = buffer.slice(0, end).split("\n");
      buffer = buffer.slice(end + 2);
      const kind = lines.find((l) => l.startsWith("event: "))?.slice(7);
      if (!kind) continue; // a heartbeat comment
      const data = JSON.parse(lines.find((l) => l.startsWith("data: "))!.slice(6));
      yield { kind, data } as ChatEvent;
    }
  }
}

/** What finalization reads of a transcript: text and tool calls, without thinking and tool results. */
function forFinalization(transcript: Message[]): Message[] {
  return transcript.flatMap((m) => {
    if (typeof m.content === "string") return [m];
    const content = m.content.filter((b) => b.type === "text" || b.type === "tool_use");
    return content.length ? [{ role: m.role, content }] : [];
  });
}

/** Ends a topic-level chat; `keepalive` lets the request outlive a closing tab, for bodies up to 64 KB. */
export function finalize(course: string, topic: string, transcript: Message[], keepalive = false): void {
  fetch(`${base(course)}/topics/${encodeURIComponent(topic)}/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript: forFinalization(transcript) }),
    keepalive,
  }).catch(() => {});
}

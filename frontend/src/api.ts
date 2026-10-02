/** `ingestion`: the step a running ingestion is at; `error`: why the last ingestion failed. */
export type CourseSummary = { name: string; status: string; ingestion: string | null; error: string | null };

/** Tokens sent to the model, cached ones included; of these, the cached ones; tokens it replied with; approximate cost. */
export type Usage = { input: number; cached: number; output: number; eur: number };

export const NO_USAGE: Usage = { input: 0, cached: 0, output: 0, eur: 0 };

export const addUsage = (a: Usage, b: Usage): Usage =>
  ({ input: a.input + b.input, cached: a.cached + b.cached, output: a.output + b.output, eur: a.eur + b.eur });

export type Topic = { slug: string; name: string; priority: string; files: string[]; usage: Usage };

/** `sources`: the source PDFs, `sources/<type>/<file>.pdf`, and their Markdown conversions, `<file>.md`. */
export type Course = { name: string; status: string; topics: Topic[]; files: string[]; sources: string[] };

/** A content block as the Messages API has it: text, tool use, tool result, thinking. */
export type Block = { type: string; text?: string; name?: string; input?: Record<string, string>; [key: string]: unknown };

export type Message = { role: "user" | "assistant"; content: string | Block[] };

export type ChatEvent =
  | { kind: "thinking"; data: string }
  | { kind: "text"; data: string }
  | { kind: "tool"; data: string }
  | { kind: "cheatsheet"; data: { section: string; heading: string; body: string } }
  | { kind: "task"; data: { task: string; tier: "A" | "B" } }
  | { kind: "step"; data: { step: string; note: string } }
  | { kind: "usage"; data: Usage }
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

export const fileUrl = (course: string, path: string) => `${base(course)}/files/${path}`;

function material(notes: string, exams: File[], exercises: File[]): FormData {
  const form = new FormData();
  form.append("notes", notes);
  for (const f of exams) form.append("exams", f);
  for (const f of exercises) form.append("exercises", f);
  return form;
}

/** Creates a course from its notes and PDFs; its ingestion starts. */
export async function createCourse(name: string, notes: string, exams: File[], exercises: File[]): Promise<void> {
  const form = material(notes, exams, exercises);
  form.append("name", name);
  await request("/api/courses", { method: "POST", body: form });
}

/** Adds PDFs to a course and replaces its notes; the ingestion of what is new starts. */
export async function addFiles(course: string, notes: string, exams: File[], exercises: File[]): Promise<void> {
  await request(`${base(course)}/files`, { method: "POST", body: material(notes, exams, exercises) });
}

export async function retryIngestion(course: string): Promise<void> {
  await request(`${base(course)}/ingestion`, { method: "POST" });
}

export async function deleteCourse(course: string): Promise<void> {
  await request(base(course), { method: "DELETE" });
}

export async function readFile(course: string, path: string): Promise<string> {
  return (await request(fileUrl(course, path))).text();
}

/** Streams the reply to a transcript that ends with the student's message. */
export async function* chat(
  course: string, topic: string, transcript: Message[], signal: AbortSignal,
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

const chatUrl = (course: string, topic: string) => `${base(course)}/chat?topic=${encodeURIComponent(topic)}`;

/** The open chat of a topic. */
export const getChat = (course: string, topic: string) =>
  json<{ transcript: Message[]; usage: Usage }>(chatUrl(course, topic));

/** Ends the open chat. */
export async function endChat(course: string, topic: string): Promise<void> {
  await request(chatUrl(course, topic), { method: "DELETE" });
}

import { memo, useEffect, useRef, useState } from "react";

import { type Block, chat, fileUrl, type Message, type Usage } from "./api";
import Markdown from "./Markdown";

export type OpenChat = {
  id: number; course: string; topic: string | null; title: string; transcript: Message[]; usage: Usage;
};

type Part = { kind: "thinking" | "text" | "note"; text: string };

const DOING: Record<string, string> = { update_cheatsheet: "Updating cheatsheet…", pose_task: "Posing a task…" };

function Thinking({ text, open }: { text: string; open: boolean }) {
  return (
    <details className="thinking" open={open}>
      <summary>Thinking</summary>
      <Markdown text={text} />
    </details>
  );
}

function blocks(content: string | Block[]): Block[] {
  return typeof content === "string" ? [{ type: "text", text: content }] : content;
}

function note(b: Block): string | null {
  if (b.type !== "tool_use") return null;
  const input = b.input as Record<string, string>;
  if (b.name === "pose_task") return `Task: ${input.task} · Tier ${input.tier}`;
  if (b.name === "update_cheatsheet") return `Cheatsheet: ${input.heading}`;
  return null;
}

/** Course files referenced in a reply, e.g. the figures of a posed task. */
const courseFiles = (course: string) => (src: string) => fileUrl(course, src);

/** Opens a course file a reply links to, e.g. `sources/exams/2023.pdf#page=3`. */
export type OpenLink = (course: string, href: string) => void;

const Turn = memo(function Turn({ message, course, onOpen }: { message: Message; course: string; onOpen: OpenLink }) {
  if (message.role === "user") {
    const text = blocks(message.content).filter((b) => b.type === "text").map((b) => b.text as string).join("\n");
    return text ? <div className="user">{text}</div> : null;
  }
  return (
    <>
      {blocks(message.content).map((b, i) => {
        if (b.type === "text") {
          return <Markdown key={i} text={b.text as string} resolve={courseFiles(course)} onOpen={(h) => onOpen(course, h)} />;
        }
        if (b.type === "thinking") return b.thinking ? <Thinking key={i} text={b.thinking as string} open={false} /> : null;
        const n = note(b);
        return n ? <div key={i} className="note">{n}</div> : null;
      })}
    </>
  );
});

export default function Chat({ open, update, onCheatsheet, onUsage, onBusy, onOpen }: {
  open: OpenChat;
  update: (transcript: Message[]) => void;
  onCheatsheet: () => void;
  onUsage: (usage: Usage) => void;
  onBusy: (busy: boolean) => void;
  onOpen: OpenLink;
}) {
  const [input, setInput] = useState("");
  const [live, setLive] = useState<Part[] | null>(null);
  const [tool, setTool] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => onBusy(!!live), [live, onBusy]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [open.transcript, live]);

  async function send(text: string) {
    if (!text.trim() || live) return;
    const transcript: Message[] = [...open.transcript, { role: "user", content: text }];
    update(transcript);
    setInput("");
    setError(null);
    setLive([]);
    abort.current = new AbortController();
    try {
      for await (const e of chat(open.course, open.topic, transcript, abort.current.signal)) {
        if (e.kind !== "tool") setTool(null);
        if (e.kind === "thinking" || e.kind === "text") {
          const kind = e.kind;
          setLive((parts) => {
            const last = parts!.at(-1);
            return last?.kind === kind
              ? [...parts!.slice(0, -1), { kind, text: last.text + e.data }]
              : [...parts!, { kind, text: e.data }];
          });
        } else if (e.kind === "tool") {
          setTool(e.data);
        } else if (e.kind === "cheatsheet") {
          setLive((parts) => [...parts!, { kind: "note", text: `Cheatsheet: ${e.data.heading}` }]);
          onCheatsheet();
        } else if (e.kind === "task") {
          setLive((parts) => [...parts!, { kind: "note", text: `Task: ${e.data.task} · Tier ${e.data.tier}` }]);
        } else if (e.kind === "usage") {
          onUsage(e.data);
        } else if (e.kind === "messages") {
          update([...transcript, ...e.data]);
          setLive(null);
          return;
        } else {
          throw new Error(e.data);
        }
      }
      throw new Error("the reply broke off");
    } catch (err) {
      if (abort.current.signal.aborted) return;
      update(open.transcript);
      setInput(text);
      setError(err instanceof Error ? err.message : String(err));
      setLive(null);
      setTool(null);
    }
  }

  return (
    <div className="chat">
      <div className="messages" aria-busy={!!live}>
        {open.transcript.length === 0 && (
          <p className="hint">
            {open.topic ? "Ask for an introduction, or say \"quiz me\"." : "Ask where you stand and what to work on next."}
          </p>
        )}
        {open.transcript.map((m, i) => <Turn key={i} message={m} course={open.course} onOpen={onOpen} />)}
        {live?.map((p, i) => p.kind === "text" ? <Markdown key={i} text={p.text} resolve={courseFiles(open.course)} onOpen={(h) => onOpen(open.course, h)} />
          : p.kind === "thinking" ? <Thinking key={i} text={p.text} open />
          : <div key={i} className="note">{p.text}</div>)}
        {live && (tool || live.at(-1)?.kind !== "text") && (
          <div className="pending">{tool ? DOING[tool] ?? `Running ${tool}…` : "Thinking…"}</div>
        )}
        {error && <div className="error">{error}</div>}
        <div ref={end} />
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <textarea
          value={input}
          placeholder="Ask anything..."
          rows={Math.min(8, input.split("\n").length)}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
          }}
        />
        <button type="submit" disabled={!!live || !input.trim()}>Send</button>
      </form>
    </div>
  );
}

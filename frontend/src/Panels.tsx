import type { IDockviewPanelProps } from "dockview-react";
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useState } from "react";

import { addUsage, endChat, fileUrl, getChat, type Message, NO_USAGE, readFile, type Usage } from "./api";
import Chat, { type OpenChat, type OpenLink } from "./Chat";
import Markdown from "./Markdown";
import Tokens from "./Tokens";

const Pdf = lazy(() => import("./Pdf"));

export const CHEATSHEET = "cheatsheet.md";

/** The chat of a topic of a course. */
export type ChatParams = { course: string; topic: string };

/** A Markdown file or a source PDF of a course; a PDF at `page`, scrolled to whenever `opened` changes. */
export type DocParams = { course: string; path: string; page?: number; opened?: number };

export const chatId = (course: string, topic: string) => `chat:${course}:${topic}`;
export const docId = (course: string, path: string) => `doc:${course}:${path}`;

/** What the panels need from the workspace around them. */
export type Shell = {
  user: string | null;
  /** Counts the cheatsheet updates, so open cheatsheets reload. */
  cheatsheet: number;
  /** Reloads the course in the tree, e.g. its token usage. */
  load: (course: string) => void;
  onCheatsheet: (course: string) => void;
  /** Opens a link of the chat panel `from` beside it. */
  openLink: (from: string, course: string, href: string) => void;
};

export const ShellContext = createContext<Shell>(null!);

let nextId = 1;

/** Asks before the chat is ended. */
function EndDialog({ onEnd, onCancel }: { onEnd: () => void; onCancel: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog" role="alertdialog" aria-labelledby="end-title">
        <h2 id="end-title">End this session?</h2>
        <p>The chat is cleared. Your progress and cheatsheet are kept.</p>
        <div className="actions">
          <button onClick={onCancel}>Keep chatting</button>
          <button className="primary" autoFocus onClick={onEnd}>End session</button>
        </div>
      </div>
    </div>
  );
}

export function ChatPanel({ params: { course, topic }, api }: IDockviewPanelProps<ChatParams>) {
  const shell = useContext(ShellContext);
  const [chat, setChat] = useState<OpenChat | null>(null);
  const [busy, setBusy] = useState(false);
  const [ending, setEnding] = useState(false);

  useEffect(() => {
    let current = true;
    getChat(course, topic).then(({ transcript, usage }) => {
      if (current) setChat({ id: nextId++, course, topic, transcript, usage });
    });
    shell.load(course);
    return () => { current = false; };
  }, [course, topic]);

  function end() {
    setEnding(false);
    if (!chat) return;
    const { id } = chat;
    endChat(course, topic).then(() => {
      setChat((c) => (c?.id === id ? { ...c, id: nextId++, transcript: [], usage: NO_USAGE } : c));
    });
  }

  const update = useCallback((id: number, transcript: Message[]) => {
    setChat((c) => (c?.id === id ? { ...c, transcript } : c));
  }, []);

  const onUsage = useCallback((id: number, usage: Usage) => {
    setChat((c) => (c?.id === id ? { ...c, usage: addUsage(c.usage, usage) } : c));
    shell.load(course);
  }, [shell.load, course]);

  const onCheatsheet = useCallback(() => shell.onCheatsheet(course), [shell.onCheatsheet, course]);

  const onOpen = useCallback<OpenLink>((c, href) => shell.openLink(api.id, c, href), [shell.openLink, api.id]);

  if (!chat) return <div className="panel" tabIndex={-1}><div className="pending hint">…</div></div>;
  return (
    <div className="panel" tabIndex={-1}>
      <header className="bar">
        <Tokens usage={chat.usage} />
        <button className="end" disabled={busy || !chat.transcript.length} onClick={() => setEnding(true)}>
          End session
        </button>
      </header>
      <Chat key={chat.id} open={chat} update={(t) => update(chat.id, t)} onCheatsheet={onCheatsheet}
        onUsage={(u) => onUsage(chat.id, u)} onBusy={setBusy} onOpen={onOpen} />
      {ending && <EndDialog onEnd={end} onCancel={() => setEnding(false)} />}
    </div>
  );
}

export function DocPanel({ params: doc }: IDockviewPanelProps<DocParams>) {
  const { cheatsheet } = useContext(ShellContext);
  const [text, setText] = useState<string | null>(null);
  const dir = doc.path.slice(0, doc.path.lastIndexOf("/") + 1);
  const pdf = doc.path.endsWith(".pdf");
  const json = doc.path.endsWith(".json");
  const version = doc.path === CHEATSHEET || json ? cheatsheet : 0;
  useEffect(() => {
    if (pdf) return;
    let current = true;
    readFile(doc.course, doc.path)
      .then((t) => current && setText(t))
      .catch((e) => current && setText(doc.path === CHEATSHEET ? "" : `*${e.message}*`));
    return () => { current = false; };
  }, [doc.course, doc.path, version]);
  return (
    <div className="panel reader" tabIndex={-1}>
      {pdf ? (
        <Suspense fallback={<div className="pending">…</div>}>
          <Pdf url={fileUrl(doc.course, doc.path)} page={doc.page} opened={doc.opened} />
        </Suspense>
      )
        : text === null ? <div className="pending">…</div>
        : text.trim() ? <Markdown text={json ? `\`\`\`json\n${text}\`\`\`` : text} resolve={(src) => fileUrl(doc.course, `${dir}${src}`)} />
        : <p className="muted">{doc.path === CHEATSHEET ? "No cheatsheet yet." : "This file is empty."}</p>}
    </div>
  );
}

/** Shown while no tab is open. */
export function Watermark() {
  const { user } = useContext(ShellContext);
  return <p className="hint">{user ? "Open a topic to start." : "Choose a user at the bottom left."}</p>;
}

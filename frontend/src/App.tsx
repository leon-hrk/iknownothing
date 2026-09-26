import { useCallback, useEffect, useRef, useState } from "react";

import {
  addUsage, chooseUser, type Course, type CourseSummary, currentUser, finalize, getCourse, listCourses, listUsers,
  type Message, NO_USAGE, readFile, UNAUTHORIZED, type Usage,
} from "./api";
import Chat, { type OpenChat } from "./Chat";
import Markdown from "./Markdown";
import Tokens from "./Tokens";

/** A Markdown file of a course, shown in the document column. */
type Doc = { course: string; path: string; title: string };


let nextId = 1;

function endChat(chat: OpenChat | null, keepalive = false) {
  if (chat?.topic && chat.transcript.length) finalize(chat.course, chat.topic, chat.transcript, keepalive);
}

const CHEATSHEET = "cheatsheet.md";

function Document({ doc, version }: { doc: Doc; version: number }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    readFile(doc.course, doc.path)
      .then((t) => current && setText(t))
      .catch((e) => current && setText(doc.path === CHEATSHEET ? "" : `*${e.message}*`));
    return () => { current = false; };
  }, [doc, version]);
  return (
    <aside className="document">
      <header><span className="title" title={doc.title}>{doc.title}</span></header>
      <div className="reader">
        {text === null ? <div className="pending">…</div>
          : text.trim() ? <Markdown text={text} />
          : <p className="muted">{doc.path === CHEATSHEET ? "No cheatsheet yet." : "This file is empty."}</p>}
      </div>
    </aside>
  );
}

/** Asks before the open chat is discarded; chats are not stored. */
function DiscardDialog({ onDiscard, onCancel }: { onDiscard: () => void; onCancel: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog" role="alertdialog" aria-labelledby="discard-title">
        <h2 id="discard-title">Discard this chat?</h2>
        <p>Chats are not stored. Your cheatsheet and progress are kept.</p>
        <div className="actions">
          <button onClick={onCancel}>Keep chatting</button>
          <button className="primary" autoFocus onClick={onDiscard}>Discard</button>
        </div>
      </div>
    </div>
  );
}

function UserMenu({ user, users, onChoose }: { user: string | null; users: string[]; onChoose: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  return (
    <div className="user-menu" ref={ref}>
      {open && (
        <ul className="users">
          {users.map((u) => (
            <li key={u}>
              <button className={u === user ? "active" : ""} onClick={() => { setOpen(false); if (u !== user) onChoose(u); }}>
                {u}
              </button>
            </li>
          ))}
          {users.length === 0 && <li className="muted">No users yet.</li>}
        </ul>
      )}
      <button className="avatar" title={user ?? "Choose a user"} onClick={() => setOpen((o) => !o)}>
        {user ? user.slice(0, 2).toUpperCase() : "?"}
      </button>
    </div>
  );
}

export default function App() {
  const [users, setUsers] = useState<string[] | null>(null);
  const [user, setUser] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listUsers(), currentUser()]).then(([u, c]) => { setUsers(u); setUser(c); });
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED, onUnauthorized);
  }, []);

  if (users === null) return null;
  return <Workspace key={user ?? ""} user={user} users={users} onSwitch={setUser} />;
}

function Workspace({ user, users, onSwitch }: { user: string | null; users: string[]; onSwitch: (name: string) => void }) {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [details, setDetails] = useState<Record<string, Course>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [chat, setChat] = useState<OpenChat | null>(null);
  const [doc, setDoc] = useState<Doc | null>(null);
  const [cheatsheetVersion, setCheatsheetVersion] = useState(0);
  const [sidebar, setSidebar] = useState(true);
  const [panel, setPanel] = useState(false);
  const [discard, setDiscard] = useState<(() => void) | null>(null);
  const chatRef = useRef(chat);
  chatRef.current = chat;

  useEffect(() => { if (user) listCourses().then(setCourses); }, [user]);

  useEffect(() => {
    const onHide = () => endChat(chatRef.current, true);
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, []);

  const load = useCallback((course: string) => {
    getCourse(course).then((c) => setDetails((d) => ({ ...d, [course]: c })));
  }, []);

  function toggle(key: string) {
    setExpanded((s) => {
      const next = new Set(s);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  /** Ends the open chat and runs `next`; asks first if the chat has messages. */
  function leaveChat(next: () => void) {
    const run = () => { endChat(chat); next(); };
    if (chat?.transcript.length) setDiscard(() => run);
    else run();
  }

  function switchUser(name: string) {
    leaveChat(() => chooseUser(name).then(() => onSwitch(name)));
  }

  function openChat(course: string, topic: string | null, title: string) {
    leaveChat(() => {
      setChat({ id: nextId++, course, topic, title, transcript: [], usage: NO_USAGE });
      setExpanded((s) => new Set(s).add(course));
      load(course);
    });
  }

  const update = useCallback((id: number, transcript: Message[]) => {
    setChat((c) => (c?.id === id ? { ...c, transcript } : c));
  }, []);

  const onCheatsheet = useCallback(() => {
    setCheatsheetVersion((v) => v + 1);
    if (chatRef.current) load(chatRef.current.course);
  }, [load]);

  const onUsage = useCallback((id: number, usage: Usage) => {
    setChat((c) => (c?.id === id ? { ...c, usage: addUsage(c.usage, usage) } : c));
    if (chatRef.current) load(chatRef.current.course);
  }, [load]);

  function openDoc(d: Doc) {
    setDoc(d);
    setPanel(true);
  }

  function togglePanel() {
    if (!panel && !doc && chat) setDoc({ course: chat.course, path: CHEATSHEET, title: `${chat.course} · Cheatsheet` });
    setPanel((p) => !p);
  }

  function file(course: string, path: string, label: string, title: string) {
    const active = panel && doc?.course === course && doc.path === path;
    return (
      <li key={path} className={active ? "active" : ""}>
        <button className="file" onClick={() => openDoc({ course, path, title })}>{label}</button>
      </li>
    );
  }

  return (
    <div className="app">
      <div className="dock">
        <button className="menu" title={sidebar ? "Hide courses" : "Show courses"} onClick={() => setSidebar((s) => !s)}>
          ☰
        </button>
        <UserMenu user={user} users={users} onChoose={switchUser} />
      </div>
      <nav className="sidebar" hidden={!sidebar}>
        <header>iknownothing</header>
        <ul>
          {courses.map((c) => {
            const detail = details[c.name];
            const open = expanded.has(c.name);
            const active = chat?.course === c.name && chat.topic === null;
            return (
              <li key={c.name}>
                <div className={active ? "row active" : "row"}>
                  <button className="caret" onClick={() => { toggle(c.name); if (!detail) load(c.name); }}>
                    {open ? "▾" : "▸"}
                  </button>
                  {c.status === "ready"
                    ? <button onClick={() => openChat(c.name, null, c.name)}>{c.name}</button>
                    : <span className="muted">{c.name} ({c.status})</span>}
                </div>
                {open && detail && (
                  <ul>
                    {detail.topics.map((t) => {
                      const key = `${c.name}/${t.slug}`;
                      const topicActive = chat?.course === c.name && chat.topic === t.slug;
                      return (
                        <li key={t.slug}>
                          <div className={topicActive ? "row active" : "row"}>
                            <button className={`caret ${t.priority}`} title={`${t.priority} priority`} onClick={() => toggle(key)}>
                              {expanded.has(key) ? "▾" : "▸"}
                            </button>
                            <button title={t.name} onClick={() => openChat(c.name, t.slug, `${c.name} · ${t.name}`)}>{t.name}</button>
                          </div>
                          {expanded.has(key) && (
                            <ul>
                              <li className="usage"><Tokens usage={t.usage} stacked /></li>
                              {t.files.map((f) => {
                                const name = f.split("/").at(-1)!;
                                return file(c.name, f, name, `${t.name} · ${name}`);
                              })}
                            </ul>
                          )}
                        </li>
                      );
                    })}
                    {detail.files.includes("notes.md") && file(c.name, "notes.md", "Notes", `${c.name} · Notes`)}
                    {detail.files.includes(CHEATSHEET) && file(c.name, CHEATSHEET, "Cheatsheet", `${c.name} · Cheatsheet`)}
                    <li className="usage" title="Whole course: course-level chat and all topics">
                      <Tokens usage={detail.topics.map((t) => t.usage).reduce(addUsage, detail.usage)} stacked />
                    </li>
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
      <main>
        <header>
          <span className="title" title={chat?.title}>{chat?.title ?? ""}</span>
          {chat && <Tokens usage={chat.usage} />}
        </header>
        {chat && <Chat key={chat.id} open={chat} update={(t) => update(chat.id, t)} onCheatsheet={onCheatsheet} onUsage={(u) => onUsage(chat.id, u)} />}
        {!chat && <p className="hint">{user ? "Open a course to start." : "Choose a user at the bottom left."}</p>}
      </main>
      {panel && doc && <Document doc={doc} version={doc.path === CHEATSHEET ? cheatsheetVersion : 0} />}
      {(chat || doc) && (
        <button className="rail" title={panel ? "Hide document" : "Show document"} onClick={togglePanel}>
          {panel ? "›" : "‹"}
        </button>
      )}
      {discard && (
        <DiscardDialog onDiscard={() => { setDiscard(null); discard(); }} onCancel={() => setDiscard(null)} />
      )}
    </div>
  );
}

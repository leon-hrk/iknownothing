import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";

import {
  addUsage, chooseUser, type Course, type CourseSummary, currentUser, endChat, fileUrl, getChat, getCourse, listCourses,
  listUsers, type Message, NO_USAGE, readFile, UNAUTHORIZED, type Usage,
} from "./api";
import Chat, { type OpenChat, type OpenLink } from "./Chat";
import Markdown from "./Markdown";
import Tokens from "./Tokens";

const Pdf = lazy(() => import("./Pdf"));

/** A Markdown file or a source PDF of a course, shown in the document column; a PDF at `page`. */
type Doc = { course: string; path: string; title: string; page?: number };

/** What a reload restores, remembered per user in the browser. */
type View = {
  chat: { course: string; topic: string | null; title: string } | null;
  doc: Doc | null;
  expanded: string[];
  sidebar: boolean;
  panel: boolean;
};

const viewKey = (user: string) => `ikn-view:${user}`;

function loadView(user: string | null): View | null {
  if (!user) return null;
  try {
    return JSON.parse(localStorage.getItem(viewKey(user)) ?? "null");
  } catch {
    return null;
  }
}

function saveView(user: string, view: View) {
  try {
    localStorage.setItem(viewKey(user), JSON.stringify(view));
  } catch {
    // the view is then not restored after a reload
  }
}

let nextId = 1;

const CHEATSHEET = "cheatsheet.md";

function Document({ doc, version }: { doc: Doc; version: number }) {
  const [text, setText] = useState<string | null>(null);
  const dir = doc.path.slice(0, doc.path.lastIndexOf("/") + 1);
  const pdf = doc.path.endsWith(".pdf");
  useEffect(() => {
    if (pdf) return;
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
        {pdf ? (
          <Suspense fallback={<div className="pending">…</div>}>
            <Pdf key={doc.path} url={fileUrl(doc.course, doc.path)} page={doc.page} opened={doc} />
          </Suspense>
        )
          : text === null ? <div className="pending">…</div>
          : text.trim() ? <Markdown text={text} resolve={(src) => fileUrl(doc.course, `${dir}${src}`)} />
          : <p className="muted">{doc.path === CHEATSHEET ? "No cheatsheet yet." : "This file is empty."}</p>}
      </div>
    </aside>
  );
}

/** Asks before the open chat is ended. */
function EndDialog({ topic, onEnd, onCancel }: { topic: boolean; onEnd: () => void; onCancel: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog" role="alertdialog" aria-labelledby="end-title">
        <h2 id="end-title">End this session?</h2>
        <p>
          {topic ? "Your progress is updated from this chat, then the chat is cleared." : "The chat is cleared."}
          {" "}Your cheatsheet is kept.
        </p>
        <div className="actions">
          <button onClick={onCancel}>Keep chatting</button>
          <button className="primary" autoFocus onClick={onEnd}>End session</button>
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
  const [saved] = useState(() => loadView(user));
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [details, setDetails] = useState<Record<string, Course>>({});
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(saved?.expanded));
  const [chat, setChat] = useState<OpenChat | null>(null);
  const [doc, setDoc] = useState<Doc | null>(saved?.doc ?? null);
  const [cheatsheetVersion, setCheatsheetVersion] = useState(0);
  const [sidebar, setSidebar] = useState(saved?.sidebar ?? true);
  const [panel, setPanel] = useState(saved?.panel ?? false);
  const [busy, setBusy] = useState(false);
  const [ending, setEnding] = useState(false);
  const chatRef = useRef(chat);
  chatRef.current = chat;
  const opening = useRef(0);
  const restoring = useRef(saved?.chat ?? null);

  const load = useCallback((course: string) => {
    getCourse(course).then((c) => setDetails((d) => ({ ...d, [course]: c })));
  }, []);

  useEffect(() => {
    if (!user) return;
    listCourses().then((cs) => {
      setCourses(cs);
      for (const c of cs) if (saved?.expanded.includes(c.name)) load(c.name);
    });
    if (saved?.chat) {
      openChat(saved.chat.course, saved.chat.topic, saved.chat.title);
      restoring.current = saved.chat;
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    const open = chat ? { course: chat.course, topic: chat.topic, title: chat.title } : restoring.current;
    saveView(user, { chat: open, doc, expanded: [...expanded], sidebar, panel });
  }, [user, chat?.course, chat?.topic, chat?.title, doc, expanded, sidebar, panel]);

  function toggle(key: string) {
    setExpanded((s) => {
      const next = new Set(s);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  function switchUser(name: string) {
    chooseUser(name).then(() => onSwitch(name));
  }

  function openChat(course: string, topic: string | null, title: string) {
    const id = opening.current = nextId++;
    restoring.current = null;
    getChat(course, topic).then(({ transcript, usage }) => {
      if (opening.current !== id) return;
      setChat({ id, course, topic, title, transcript, usage });
      setExpanded((s) => new Set(s).add(course));
      load(course);
    });
  }

  function end() {
    setEnding(false);
    if (!chat) return;
    const { id, course, topic } = chat;
    endChat(course, topic).then(() => {
      setChat((c) => (c?.id === id ? { ...c, id: nextId++, transcript: [], usage: NO_USAGE } : c));
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

  const openLink = useCallback<OpenLink>((course, href) => {
    const [path, fragment] = href.split("#");
    const page = Number(/^page=(\d+)$/.exec(fragment ?? "")?.[1]) || undefined;
    setDoc({ course, path, title: `${course} · ${path.replace(/^sources\//, "")}`, page });
    setPanel(true);
  }, []);

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

  /** The source PDFs and their conversions, grouped by document type. */
  function sources(course: string, paths: string[]) {
    const key = `${course}:sources`;
    const types = [...new Set(paths.map((p) => p.split("/")[1]))];
    const folder = (k: string, label: string) => (
      <div className="row">
        <button className="caret" onClick={() => toggle(k)}>{expanded.has(k) ? "▾" : "▸"}</button>
        <button onClick={() => toggle(k)}>{label}</button>
      </div>
    );
    return (
      <li key={key}>
        {folder(key, "Sources")}
        {expanded.has(key) && (
          <ul>
            {types.map((type) => (
              <li key={type}>
                {folder(`${key}/${type}`, type)}
                {expanded.has(`${key}/${type}`) && (
                  <ul>
                    {paths.filter((p) => p.split("/")[1] === type).map((p) => {
                      const name = p.split("/").at(-1)!;
                      return file(course, p, name, `${course} · ${type}/${name}`);
                    })}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
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
                    {detail.sources.length > 0 && sources(c.name, detail.sources)}
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
          {chat && (
            <button className="end" disabled={busy || !chat.transcript.length} onClick={() => setEnding(true)}>
              End session
            </button>
          )}
        </header>
        {chat && (
          <Chat key={chat.id} open={chat} update={(t) => update(chat.id, t)} onCheatsheet={onCheatsheet}
            onUsage={(u) => onUsage(chat.id, u)} onBusy={setBusy} onOpen={openLink} />
        )}
        {!chat && <p className="hint">{user ? "Open a course to start." : "Choose a user at the bottom left."}</p>}
      </main>
      {panel && doc && <Document doc={doc} version={doc.path === CHEATSHEET ? cheatsheetVersion : 0} />}
      {(chat || doc) && (
        <button className="rail" title={panel ? "Hide document" : "Show document"} onClick={togglePanel}>
          {panel ? "›" : "‹"}
        </button>
      )}
      {ending && chat && <EndDialog topic={chat.topic !== null} onEnd={end} onCancel={() => setEnding(false)} />}
    </div>
  );
}

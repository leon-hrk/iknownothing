import { useCallback, useEffect, useRef, useState } from "react";

import { type Course, type CourseSummary, finalize, getCourse, listCourses, type Message, readFile } from "./api";
import Chat, { type OpenChat } from "./Chat";
import Markdown from "./Markdown";

type Reading = { course: string; path: string; title: string };

const WARNING = "Chats are not stored. Open a new chat and lose the current one?";

let nextId = 1;

function endChat(chat: OpenChat | null, keepalive = false) {
  if (chat?.topic && chat.transcript.length) finalize(chat.course, chat.topic, chat.transcript, keepalive);
}

function Reader({ reading, version, onBack }: { reading: Reading; version: number; onBack: () => void }) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    readFile(reading.course, reading.path)
      .then((t) => current && setText(t))
      .catch((e) => current && setText(`*${e.message}*`));
    return () => { current = false; };
  }, [reading, version]);
  return (
    <div className="reader">
      <button className="back" onClick={onBack}>Back to chat</button>
      {text === null ? <div className="pending">…</div>
        : text.trim() ? <Markdown text={text} /> : <p className="muted">This file is empty.</p>}
    </div>
  );
}

export default function App() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [details, setDetails] = useState<Record<string, Course>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [chat, setChat] = useState<OpenChat | null>(null);
  const [reading, setReading] = useState<Reading | null>(null);
  const [cheatsheetVersion, setCheatsheetVersion] = useState(0);
  const [sidebar, setSidebar] = useState(true);
  const chatRef = useRef(chat);
  chatRef.current = chat;

  useEffect(() => { listCourses().then(setCourses); }, []);

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

  function openChat(course: string, topic: string | null, title: string) {
    if (chat?.transcript.length && !window.confirm(WARNING)) return;
    endChat(chat);
    setChat({ id: nextId++, course, topic, title, transcript: [] });
    setReading(null);
    setExpanded((s) => new Set(s).add(course));
    load(course);
  }

  const update = useCallback((id: number, transcript: Message[]) => {
    setChat((c) => (c?.id === id ? { ...c, transcript } : c));
  }, []);

  const onCheatsheet = useCallback(() => {
    setCheatsheetVersion((v) => v + 1);
    if (chatRef.current) load(chatRef.current.course);
  }, [load]);

  function file(course: string, path: string, title: string) {
    const active = reading?.course === course && reading.path === path;
    return (
      <li key={path} className={active ? "active" : ""}>
        <button className="file" onClick={() => setReading({ course, path, title })}>{title}</button>
      </li>
    );
  }

  return (
    <div className={sidebar ? "app" : "app collapsed"}>
      <nav className="sidebar">
        <div className="brand">iknownothing</div>
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
                            <button className="caret" onClick={() => toggle(key)}>{expanded.has(key) ? "▾" : "▸"}</button>
                            <button onClick={() => openChat(c.name, t.slug, `${c.name} · ${t.name}`)}>{t.name}</button>
                            <span className={`priority ${t.priority}`}>{t.priority}</span>
                          </div>
                          {expanded.has(key) && (
                            <ul>{t.files.map((f) => file(c.name, f, f.split("/").at(-1)!))}</ul>
                          )}
                        </li>
                      );
                    })}
                    {detail.files.includes("notes.md") && file(c.name, "notes.md", "Notes")}
                    {detail.files.includes("cheatsheet.md") && file(c.name, "cheatsheet.md", "Cheatsheet")}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
      <main>
        <header>
          <button className="caret" onClick={() => setSidebar((s) => !s)}>☰</button>
          <span>{reading ? reading.title : chat?.title ?? ""}</span>
        </header>
        {reading && (
          <Reader
            reading={reading}
            version={reading.path === "cheatsheet.md" ? cheatsheetVersion : 0}
            onBack={() => setReading(null)}
          />
        )}
        {chat && (
          <div hidden={!!reading} className="chat-pane">
            <Chat
              key={chat.id}
              open={chat}
              update={(t) => update(chat.id, t)}
              onCheatsheet={onCheatsheet}
            />
          </div>
        )}
        {!chat && !reading && <p className="hint">Open a course to start.</p>}
      </main>
    </div>
  );
}

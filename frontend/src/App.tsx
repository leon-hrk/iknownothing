import {
  type DockviewApi, DockviewReact, type DockviewReadyEvent, type SerializedDockview, themeLight,
} from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  addUsage, chooseUser, type Course, type CourseSummary, currentUser, getCourse, listCourses, listUsers,
  UNAUTHORIZED,
} from "./api";
import {
  CHEATSHEET, ChatPanel, type ChatParams, chatId, DocPanel, type DocParams, docId, type Shell, ShellContext, Watermark,
} from "./Panels";
import Tokens from "./Tokens";

const PANELS = { chat: ChatPanel, doc: DocPanel };

/** What a reload restores, remembered per user in the browser. */
type View = {
  layout: SerializedDockview | null;
  expanded: string[];
  sidebar: boolean;
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
  const [layout, setLayout] = useState(saved?.layout ?? null);
  const [active, setActive] = useState<string | null>(null);
  const [cheatsheet, setCheatsheet] = useState(0);
  const [sidebar, setSidebar] = useState(saved?.sidebar ?? true);
  const api = useRef<DockviewApi | null>(null);
  const workspace = useRef<HTMLDivElement>(null);

  const load = useCallback((course: string) => {
    getCourse(course).then((c) => setDetails((d) => ({ ...d, [course]: c })));
  }, []);

  useEffect(() => {
    if (!user) return;
    listCourses().then((cs) => {
      setCourses(cs);
      for (const c of cs) if (saved?.expanded.includes(c.name)) load(c.name);
    });
  }, []);

  useEffect(() => {
    if (user) saveView(user, { layout, expanded: [...expanded], sidebar });
  }, [user, layout, expanded, sidebar]);

  // dockview follows a resize a frame late; laid out at once, the tabs do not jump when the tree is toggled
  useLayoutEffect(() => {
    const el = workspace.current;
    if (el) api.current?.layout(el.clientWidth, el.clientHeight);
  }, [sidebar]);

  function onReady({ api: dock }: DockviewReadyEvent) {
    api.current = dock;
    if (user && saved?.layout) {
      try {
        dock.fromJSON(saved.layout);
      } catch {
        dock.clear();
      }
    }
    setActive(dock.activePanel?.id ?? null);
    dock.onDidActivePanelChange(({ panel }) => setActive(panel?.id ?? null));
    dock.onDidLayoutChange(() => setLayout(dock.toJSON()));
  }

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

  /** Shows the tab `id`, opening it right of the active tab if it is not open. */
  function show(id: string, component: keyof typeof PANELS, title: string, params: ChatParams | DocParams) {
    const dock = api.current;
    const panel = dock?.getPanel(id);
    if (panel) return panel.api.setActive();
    const group = dock?.activeGroup;
    const index = group?.activePanel ? group.panels.indexOf(group.activePanel) + 1 : undefined;
    dock?.addPanel({ id, component, title, params, position: group ? { referenceGroup: group, index } : undefined });
  }

  const openLink = useCallback((from: string, course: string, href: string) => {
    const dock = api.current;
    if (!dock) return;
    const [path, fragment] = href.split("#");
    const page = Number(/^page=(\d+)$/.exec(fragment ?? "")?.[1]) || undefined;
    const id = docId(course, path);
    const params: DocParams = { course, path, page, opened: Date.now() };
    const panel = dock.getPanel(id);
    if (panel) {
      panel.api.updateParameters(params);
      panel.api.setActive();
      return;
    }
    // beside the chat: in another group, or in a new one on its right
    const chat = dock.getPanel(from);
    const other = dock.groups.find((g) => g !== chat?.group);
    const title = path.split("/").at(-1)!;
    if (other) dock.addPanel({ id, component: "doc", title, params, position: { referenceGroup: other } });
    else if (chat) dock.addPanel({ id, component: "doc", title, params, position: { referencePanel: chat, direction: "right" } });
    else dock.addPanel({ id, component: "doc", title, params });
  }, []);

  const onCheatsheet = useCallback((course: string) => {
    setCheatsheet((v) => v + 1);
    load(course);
  }, [load]);

  const shell = useMemo<Shell>(
    () => ({ user, cheatsheet, load, onCheatsheet, openLink }),
    [user, cheatsheet, load, onCheatsheet, openLink],
  );

  function file(course: string, path: string, label: string, title: string) {
    const id = docId(course, path);
    return (
      <li key={path} className={active === id ? "active" : ""}>
        <button className="file" onClick={() => show(id, "doc", title, { course, path })}>{label}</button>
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
                      return file(course, p, name, name);
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
            const id = chatId(c.name, null);
            return (
              <li key={c.name}>
                <div className={active === id ? "row active" : "row"}>
                  <button className="caret" onClick={() => { toggle(c.name); if (!detail) load(c.name); }}>
                    {open ? "▾" : "▸"}
                  </button>
                  {c.status === "ready"
                    ? <button onClick={() => show(id, "chat", c.name, { course: c.name, topic: null })}>{c.name}</button>
                    : <span className="muted">{c.name} ({c.status})</span>}
                </div>
                {open && detail && (
                  <ul>
                    {detail.topics.map((t) => {
                      const key = `${c.name}/${t.slug}`;
                      const topicId = chatId(c.name, t.slug);
                      return (
                        <li key={t.slug}>
                          <div className={active === topicId ? "row active" : "row"}>
                            <button className={`caret ${t.priority}`} title={`${t.priority} priority`} onClick={() => toggle(key)}>
                              {expanded.has(key) ? "▾" : "▸"}
                            </button>
                            <button title={t.name} onClick={() => show(topicId, "chat", t.name, { course: c.name, topic: t.slug })}>
                              {t.name}
                            </button>
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
      <ShellContext.Provider value={shell}>
        <div className="workspace" ref={workspace}>
          <DockviewReact components={PANELS} watermarkComponent={Watermark} onReady={onReady}
            theme={themeLight} defaultRenderer="always" disableFloatingGroups />
        </div>
      </ShellContext.Provider>
    </div>
  );
}

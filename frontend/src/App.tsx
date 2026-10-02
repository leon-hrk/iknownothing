import {
  type DockviewApi, DockviewReact, type DockviewReadyEvent, type SerializedDockview, themeLight,
} from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { memo, type RefObject, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  addUsage, chooseUser, type Course, type CourseSummary, currentUser, deleteCourse, getCourse, listCourses,
  listUsers, NO_USAGE, retryIngestion, UNAUTHORIZED,
} from "./api";
import CourseDialog from "./CourseDialog";
import {
  CHEATSHEET, ChatPanel, type ChatParams, chatId, DocPanel, type DocParams, docId, type Shell, ShellContext, Watermark,
} from "./Panels";
import Tokens from "./Tokens";

const PANELS = { chat: ChatPanel, doc: DocPanel };

/** The label of the divider above the topics of each priority. */
const PRIORITY: Record<string, string> = { high: "Priority 1", medium: "Priority 2", low: "Priority 3" };

/** The color of a score, from red for 0% to green for 100%. */
const scoreColor = (score: number) => `hsl(${score * 1.2} 70% 45%)`;

/** How often the course list is asked for while an ingestion runs, in ms. */
const POLL = 3000;

/** What a reload restores, remembered per user in the browser: the open course, the tabs of every course, the
 * expanded folders, the courses whose topics show their details, and whether the tree is shown. */
type View = {
  course: string | null;
  layouts: Record<string, SerializedDockview>;
  expanded: string[];
  details: string[];
  sidebar: boolean;
};

const viewKey = (user: string) => `ikn-view:${user}`;

function loadView(user: string | null): View {
  const empty: View = { course: null, layouts: {}, expanded: [], details: [], sidebar: true };
  if (!user) return empty;
  try {
    return { ...empty, ...JSON.parse(localStorage.getItem(viewKey(user)) ?? "{}") };
  } catch {
    return empty;
  }
}

function saveView(user: string, view: View) {
  try {
    localStorage.setItem(viewKey(user), JSON.stringify(view));
  } catch {
    // the view is then not restored after a reload
  }
}

/** Closes on a click outside `ref` or on Escape. */
function useDismiss(ref: RefObject<HTMLElement | null>, open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
}

function UserMenu({ user, users, onChoose }: { user: string | null; users: string[]; onChoose: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(ref, open, useCallback(() => setOpen(false), []));
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

/** The menu of a course icon, opened by a right click. */
function CourseMenu({ x, y, summary, details, onDetails, onAdd, onRetry, onDelete, onClose }: {
  x: number; y: number; summary: CourseSummary; details: boolean;
  onDetails: () => void; onAdd: () => void; onRetry: () => void; onDelete: () => void; onClose: () => void;
}) {
  const ref = useRef<HTMLUListElement>(null);
  useDismiss(ref, true, onClose);
  const running = summary.ingestion !== null;
  const item = (label: string, act: () => void, disabled = false, danger = false) => (
    <li>
      <button className={danger ? "danger" : ""} disabled={disabled} onClick={() => { onClose(); act(); }}>{label}</button>
    </li>
  );
  return (
    <ul className="context-menu" ref={ref} style={{ left: x, top: y }}>
      {item(details ? "Hide details" : "Show hidden details", onDetails)}
      {item("Add files", onAdd, running)}
      {(summary.error !== null || summary.status !== "ready") && item("Retry ingestion", onRetry, running)}
      {item("Delete course", onDelete, running, true)}
    </ul>
  );
}

/** Asks before a course is deleted. */
function DeleteDialog({ course, onDelete, onCancel }: { course: string; onDelete: () => void; onCancel: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="dialog" role="alertdialog" aria-labelledby="delete-title">
        <h2 id="delete-title">Delete {course}?</h2>
        <p>The course is deleted with its sources, topics, progress, cheatsheet, and chats. This cannot be undone.</p>
        <div className="actions">
          <button onClick={onCancel}>Keep it</button>
          <button className="danger" autoFocus onClick={onDelete}>Delete course</button>
        </div>
      </div>
    </div>
  );
}

/** The tabs of one course, from its saved `layout`. It stays mounted while another course is shown, so its chats keep
 * streaming. */
const CourseTabs = memo(function CourseTabs({ course, visible, width, layout, onReady, onLayout, onActive }: {
  course: string;
  visible: boolean;
  /** Changes when the space for the tabs does, e.g. when the tree is toggled. */
  width: unknown;
  layout: SerializedDockview | undefined;
  onReady: (course: string, api: DockviewApi) => void;
  onLayout: (course: string, layout: SerializedDockview) => void;
  onActive: (course: string, id: string | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const api = useRef<DockviewApi | null>(null);

  // dockview follows a resize a frame late; laid out at once, the tabs do not jump when the tree is toggled
  useLayoutEffect(() => {
    const el = ref.current;
    if (visible && el) api.current?.layout(el.clientWidth, el.clientHeight);
  }, [visible, width]);

  function ready({ api: dock }: DockviewReadyEvent) {
    api.current = dock;
    if (layout) {
      try {
        dock.fromJSON(layout);
      } catch {
        dock.clear();
      }
    }
    onReady(course, dock);
    onActive(course, dock.activePanel?.id ?? null);
    dock.onDidActivePanelChange(({ panel }) => onActive(course, panel?.id ?? null));
    dock.onDidLayoutChange(() => onLayout(course, dock.toJSON()));
  }

  return (
    <div className="course-tabs" ref={ref} hidden={!visible}>
      <DockviewReact components={PANELS} watermarkComponent={Watermark} onReady={ready}
        theme={themeLight} defaultRenderer="always" disableFloatingGroups />
    </div>
  );
});

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
  const [course, setCourse] = useState<string | null>(saved.course);
  const [visited, setVisited] = useState<string[]>(saved.course ? [saved.course] : []);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(saved.expanded));
  const [shown, setShown] = useState<Set<string>>(() => new Set(saved.details));
  const [layouts, setLayouts] = useState(saved.layouts);
  const [actives, setActives] = useState<Record<string, string | null>>({});
  const [cheatsheet, setCheatsheet] = useState(0);
  const [sidebar, setSidebar] = useState(saved.sidebar);
  const [menu, setMenu] = useState<{ course: string; x: number; y: number } | null>(null);
  const [dialog, setDialog] = useState<{ course?: string } | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const apis = useRef<Record<string, DockviewApi>>({});

  const load = useCallback((name: string) => {
    getCourse(name).then((c) => setDetails((d) => ({ ...d, [name]: c })));
  }, []);

  const refresh = useCallback(() => listCourses().then((cs) => {
    setCourses((before) => {
      // an ingestion that ended changed the topics
      for (const c of cs) if (before.find((b) => b.name === c.name)?.ingestion && !c.ingestion) load(c.name);
      return cs;
    });
    return cs;
  }), [load]);

  useEffect(() => {
    if (!user) return;
    refresh().then((cs) => {
      const known = cs.some((c) => c.name === saved.course);
      if (known) load(saved.course!);
      else if (cs.length) open(cs[0].name);
      else setCourse(null);
    });
  }, []);

  const ingesting = courses.some((c) => c.ingestion !== null);
  useEffect(() => {
    if (!ingesting) return;
    const timer = setInterval(refresh, POLL);
    return () => clearInterval(timer);
  }, [ingesting, refresh]);

  useEffect(() => {
    if (user) saveView(user, { course, layouts, expanded: [...expanded], details: [...shown], sidebar });
  }, [user, course, layouts, expanded, shown, sidebar]);

  function open(name: string) {
    setCourse(name);
    setVisited((v) => (v.includes(name) ? v : [...v, name]));
    load(name);
  }

  function onIcon(name: string) {
    if (name === course) setSidebar((s) => !s);
    else {
      open(name);
      setSidebar(true);
    }
  }

  function toggleDetails(name: string) {
    setShown((s) => {
      const next = new Set(s);
      if (!next.delete(name)) next.add(name);
      return next;
    });
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

  async function remove(name: string) {
    setDeleting(null);
    await deleteCourse(name);
    setVisited((v) => v.filter((c) => c !== name));
    setLayouts(({ [name]: _, ...rest }) => rest);
    delete apis.current[name];
    const cs = await refresh();
    if (course === name) {
      if (cs.length) open(cs[0].name);
      else setCourse(null);
    }
  }

  async function retry(name: string) {
    await retryIngestion(name);
    refresh();
  }

  function created(name: string) {
    setDialog(null);
    refresh().then(() => open(name));
  }

  /** Shows the tab `id` of the open course, opening it right of the active tab if it is not open. */
  function show(id: string, component: keyof typeof PANELS, title: string, params: ChatParams | DocParams) {
    const dock = course ? apis.current[course] : undefined;
    const panel = dock?.getPanel(id);
    if (panel) return panel.api.setActive();
    const group = dock?.activeGroup;
    const index = group?.activePanel ? group.panels.indexOf(group.activePanel) + 1 : undefined;
    dock?.addPanel({ id, component, title, params, position: group ? { referenceGroup: group, index } : undefined });
  }

  const openLink = useCallback((from: string, name: string, href: string) => {
    const dock = apis.current[name];
    if (!dock) return;
    const [path, fragment] = href.split("#");
    const page = Number(/^page=(\d+)$/.exec(fragment ?? "")?.[1]) || undefined;
    const id = docId(name, path);
    const params: DocParams = { course: name, path, page, opened: Date.now() };
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

  const onCheatsheet = useCallback((name: string) => {
    setCheatsheet((v) => v + 1);
    load(name);
  }, [load]);

  const shell = useMemo<Shell>(
    () => ({ user, details: shown, cheatsheet, load, onCheatsheet, openLink }),
    [user, shown, cheatsheet, load, onCheatsheet, openLink],
  );

  const onReady = useCallback((name: string, api: DockviewApi) => { apis.current[name] = api; }, []);
  const onLayout = useCallback((name: string, layout: SerializedDockview) => {
    setLayouts((l) => ({ ...l, [name]: layout }));
  }, []);
  const onActive = useCallback((name: string, id: string | null) => {
    setActives((a) => ({ ...a, [name]: id }));
  }, []);

  const summary = courses.find((c) => c.name === course);
  const detail = course ? details[course] : undefined;
  const active = course ? actives[course] : null;

  function file(path: string, label: string, title: string) {
    const id = docId(course!, path);
    return (
      <li key={path} className={active === id ? "active" : ""}>
        <button className="file" onClick={() => show(id, "doc", title, { course: course!, path })}>{label}</button>
      </li>
    );
  }

  /** The source PDFs, grouped by document type; their conversions only while the course shows its details. */
  function sources(all: string[]) {
    const paths = shown.has(course!) ? all : all.filter((p) => p.endsWith(".pdf"));
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
                      return file(p, name, name);
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
        <div className="rail">
          {courses.map((c) => (
            <button key={c.name} title={c.name}
              className={["course-icon", c.name === course && "active", c.ingestion && "ingesting", c.error && "failed"]
                .filter(Boolean).join(" ")}
              onClick={() => onIcon(c.name)}
              onContextMenu={(e) => { e.preventDefault(); setMenu({ course: c.name, x: e.clientX, y: e.clientY }); }}>
              {c.name.slice(0, 2).toUpperCase()}
            </button>
          ))}
          {user && <button className="course-icon add" title="New course" onClick={() => setDialog({})}>+</button>}
        </div>
        <UserMenu user={user} users={users} onChoose={switchUser} />
      </div>
      <nav className="sidebar" hidden={!sidebar || !course}>
        <header>{course}</header>
        {summary?.ingestion && <p className="status pending">Ingesting: {summary.ingestion}</p>}
        {summary?.error && !summary.ingestion && (
          <div className="status">
            <p className="error">Ingestion failed: {summary.error}</p>
            <button className="retry" onClick={() => retry(summary.name)}>Retry</button>
          </div>
        )}
        {summary && summary.status !== "ready" && !summary.ingestion && !summary.error && (
          <div className="status">
            <p className="muted">Not ingested.</p>
            <button className="retry" onClick={() => retry(summary.name)}>Ingest</button>
          </div>
        )}
        {detail && (
          <ul>
            {detail.topics.map((t, i) => {
              const topicId = chatId(course!, t.slug);
              return [
                t.priority !== detail.topics[i - 1]?.priority && (
                  <li key={`priority-${t.priority}`} className="divider"><span>{PRIORITY[t.priority] ?? t.priority}</span></li>
                ),
                <li key={t.slug}>
                  <div className={["row", active === topicId && "active", t.score === null && "paper"].filter(Boolean).join(" ")}>
                    <span className="score" style={t.score === null ? undefined : { color: scoreColor(t.score) }} title={`${t.priority} priority · ${t.score === null
                      ? "no tasks to practise here, only ones to practise on paper" : `${t.score}% of the tasks done`}`}>
                      {t.score === null ? "" : `${t.score}%`}
                    </span>
                    <button title={t.name} onClick={() => show(topicId, "chat", t.name, { course: course!, topic: t.slug })}>
                      {t.name}
                    </button>
                  </div>
                  {shown.has(course!) && (
                    <ul>
                      <li className="usage"><Tokens usage={t.usage} stacked /></li>
                      {t.files.map((f) => {
                        const name = f.split("/").at(-1)!;
                        return file(f, name, `${t.name} · ${name}`);
                      })}
                    </ul>
                  )}
                </li>
              ];
            })}
            {detail.sources.length > 0 && sources(detail.sources)}
            {detail.files.includes("notes.md") && file("notes.md", "Notes", `${course} · Notes`)}
            {detail.files.includes(CHEATSHEET) && file(CHEATSHEET, "Cheatsheet", `${course} · Cheatsheet`)}
            {shown.has(course!) && detail.topics.length > 0 && (
              <li className="usage" title="Whole course: all topics">
                <Tokens usage={detail.topics.map((t) => t.usage).reduce(addUsage, NO_USAGE)} stacked />
              </li>
            )}
          </ul>
        )}
      </nav>
      <ShellContext.Provider value={shell}>
        <div className="workspace">
          {visited.map((name) => (
            <CourseTabs key={name} course={name} visible={name === course} width={sidebar} layout={saved.layouts[name]}
              onReady={onReady} onLayout={onLayout} onActive={onActive} />
          ))}
          {!course && <p className="hint">{user ? "Create a course with +." : "Choose a user at the bottom left."}</p>}
        </div>
      </ShellContext.Provider>
      {menu && (() => {
        const s = courses.find((c) => c.name === menu.course);
        return s && (
          <CourseMenu x={menu.x} y={menu.y} summary={s} details={shown.has(s.name)} onClose={() => setMenu(null)}
            onDetails={() => toggleDetails(s.name)}
            onAdd={() => setDialog({ course: s.name })} onRetry={() => retry(s.name)} onDelete={() => setDeleting(s.name)} />
        );
      })()}
      {dialog && <CourseDialog course={dialog.course} onDone={created} onCancel={() => setDialog(null)} />}
      {deleting && <DeleteDialog course={deleting} onDelete={() => remove(deleting)} onCancel={() => setDeleting(null)} />}
    </div>
  );
}

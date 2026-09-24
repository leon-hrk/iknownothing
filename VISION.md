# VISION.md — iknownothing

## One-liner
A self-hosted, AI-powered exam preparation tutor. Upload your course
materials and say "I know nothing" - the agent builds a structured,
topic-based study plan and tutors you through it, from knowing
nothing to exam ready.

## Problem
Students preparing for exams have scattered materials: lecture slides,
exercise sheets, past exams. Generic AI chats don't know the professor's
style, the exam's difficulty level, or what the student already knows.
Every chat starts from zero.

## Core Idea
The agent ingests all course materials **once**, distills them into
structured, reusable Markdown artifacts (topics, example problems,
solution styles), and uses these artifacts - not the raw PDFs - as
context for tutoring sessions. This keeps context windows small and
behavior consistent.

## Deployment & Platform
- **Self-hosted web application**, shipped as a Docker container
  (docker-compose for app + Postgres), similar in spirit to LibreChat.
- **Multi-user from day one**: accounts, login, per-user courses and
  progress. Designed for later scaling, but v0 targets small
  self-hosted deployments.
- **AI provider: Anthropic API** (v0). **Per-user API keys** - each
  user provides their own key in their account settings. Provider
  abstraction kept thin so others can be added later. Note that PDF
  ingestion uses the provider's document/vision capability, so any
  future provider must support multimodal document input - this is
  not a pure text-completion abstraction.
- **Storage:**
  - **Filesystem** for course materials (PDFs) and all derived
    Markdown artifacts, namespaced per user
    (`data/<user>/<course>/...`). The converted source Markdown is
    kept as an untouched archive; topic directories are derived from
    it and regenerable.
  - **PostgreSQL** for users, courses metadata, chat sessions, and
    full chat history.
  - No vector DB in v0.

## Key Concepts

### Course
The top-level unit, owned by a user. A course contains:
- **Lecture slides** (PDF)
- **Exercise sheets + solutions** (PDF)
- **Past exams + solution proposals** (PDF)
- **Notes file** (`notes.md`) - free-form remarks the AI must respect
  (e.g. "prof emphasized topic X in Q&A", "topic Y is new this year")

### Ingestion Pipeline (per course)
1. **PDF - Markdown conversion** via **Claude vision** (the PDF is sent
   to the Messages API as a document; no local ML models, no GPU).
   Done once per uploaded file, results are cached.
   - Math is converted to LaTeX.
   - **Figures and diagrams** are extracted as PNG *and* described in
     text. The description is part of the Markdown, right next to the
     image reference. The image file is for the UI; the description is
     what the tutor reads.
   - Runs page-chunked so large documents stay within request limits
     and can be converted in parallel.
   - Conversion uses the user's own API key, like every other AI call.
     One course is a one-time cost in the range of a few dollars.
2. **Chunking**: split the converted Markdown into addressable units.
   - Past exams and exercise sheets: **one task = one chunk** (the
     natural unit; a task and its solution stay together).
   - Lecture slides: section and slide boundaries from the Markdown
     structure.
3. **Topic extraction**: derive the topic list, ranked by
   frequency/importance. Source priority: **past exams > exercises >
   lecture**. What the exam asks defines what a topic *is*; the
   lecture defines how it is *taught*.
4. **Topic assignment**: tag every chunk with **zero or more** topics.
   Not a partition - a chunk on Laplace transforms legitimately
   belongs to several topics at once, and material that matches no
   topic is kept as an explicit **unassigned pool** rather than
   dropped.
5. **Topic review (human in the loop)**: the user is shown the
   extracted topic list *and the unassigned pool* ("40 lecture slides
   and 3 exercises matched no topic: chapter 7, sheet 9 - is a topic
   missing?"). The user can confirm, rename, merge, add, or remove
   topics; adding one re-runs assignment over the unassigned pool.
   This is the most critical step - a cheap review here safeguards
   the quality of everything downstream, and the unassigned pool is
   how topics that no past exam covers get caught (see `notes.md`:
   *"topic Y is new this year"*).
6. **Per-topic artifact generation**: for each confirmed topic, write
   a **physical topic directory** containing the assigned material
   plus the generated artifact:
   - `topics/<topic>/topic.md` - the artifact:
     - Topic description and exam relevance (priority score)
     - Representative example problems (in exam style and difficulty),
       each tagged with a **gradability tier** (see below)
     - Solution approaches "the professor's way" (sourced from
       lecture slides and exercise solutions)
     - A list of **out-of-reach task types** for this topic, if any
   - `topics/<topic>/material.md` - the assigned source chunks,
     copied in, so the student can read into a topic directly without
     resolving an index.
7. **Topic index**: `topics.json` - ordered list of topics with
   priority, metadata, and file references.

For solution style and notation the source priority **inverts**:
lecture slides and official solutions outrank the exam question
itself. The exam says what is asked; the lecture says how it is to be
written down.

The per-topic artifacts are the **single source of truth** for all
downstream features. New mock exams can be generated from them alone,
without re-reading the original PDFs.

### Editing and Re-ingestion
Nothing about a course is frozen after the first import. Material
arrives late (a new past exam surfaces, the prof posts sheet 12), and
every derived Markdown file is editable by the student. The pipeline
is therefore **re-entrant and incremental**: a change marks the
artifacts derived from it as stale, and only those are rebuilt.

Blast radius depends on *what* changed:

| Change | Invalidates |
|---|---|
| New or edited **past exam** | The topic list itself - full re-run including topic review |
| New or edited **exercise/lecture** PDF | Chunking and assignment for that file; the topics it lands in |
| Edited `sources/*.md` | That file's chunks, and the topics they are assigned to |
| Topic added/renamed/merged in review | Assignment, the affected topic directories |
| Edited `topics/<topic>/*` | Nothing downstream - but the edit must survive the next rebuild |

Two boundaries hold regardless of what was changed:

1. **Student state is never invalidated by material changes.**
   `progress.md`, `cheatsheet.md`, and chat history are derived from
   the *student*, not from the PDFs. Uploading another past exam must
   not reset progress. When topics are renamed, merged, or removed,
   progress entries are **migrated**, not dropped.
2. **Regeneration never silently discards a user edit.** A
   hand-corrected artifact outranks a regenerated one.

Because regeneration spends the user's own API budget, any operation
with a large blast radius states its scope before it runs ("this will
re-convert 2 files and regenerate 12 topics") rather than starting
silently.

### Fallback Strategies (material availability)
- **Many past exams**: extract topics and difficulty directly from exams.
- **Few past exams**: use exercise problems as the base, calibrate
  difficulty against the few available exam problems.
- **No past exams**: use exercise sheets only; filter out extremely
  hard exercises and normalize difficulty to a realistic exam level.

### Task Gradability (three tiers)
Not every exam task can be posed and corrected in a chat window. Every
example problem is classified during ingestion into one of three tiers,
and the tier determines how the tutor handles it.

**Tier A - graded.** Text, math, derivations, code, short answers.
The normal loop: tutor poses the problem, student answers, tutor
grades and gives feedback. Result feeds `progress.md` as an
**assessed** mastery signal.

**Tier B - posed, self-assessed.** Tasks whose solution can be
expressed in ASCII/Markdown: state machines, flow charts, simple block
diagrams, truth tables, tree structures, timing diagrams. The tutor
poses the task and can show a reference solution in ASCII, but does
**not** grade the student's attempt - reliably correcting a drawing
typed into a chat box is not realistic. Instead the student
self-reports ("got it" / "struggled" / "no idea"). Result feeds
`progress.md` as a **self-reported** signal, explicitly marked as
such.

**Tier C - out of reach.** Tasks with no meaningful text
representation: freehand sketches, hand-drawn plots, circuit layouts,
geometric constructions, anything graded on visual precision. These
are **not posed as exercises**. They are listed explicitly in the
topic artifact and surfaced to the student: *"This topic's exam
typically includes <task type>. This tutor cannot train that - practice
it on paper."* Being upfront about the gap is the feature; silently
omitting it would make the readiness estimate a lie.

The tier split is a property of the *task*, not the topic - a topic
usually contains tasks from more than one tier.

### Tutoring Sessions
Sessions come in two scopes.

**Course-level chat** - orientation and planning. This is the default
entry point: the student opens a course and asks *"which topics do I
still need to learn?"*. Context is the topic index, `progress.md`,
`cheatsheet.md`, and `notes.md` - never a full topic artifact. From
here the tutor can hand over into a topic.

**Topic-level chat** - the actual tutoring, opened by clicking a topic
or by handover from the course-level chat.

- UI shows a **topic overview** per course (sorted by priority,
  with per-topic mastery status).
- Context loaded into a topic-level session:
  - The topic's artifact (`topics/<topic>/topic.md`)
  - The course cheatsheet (`cheatsheet.md`)
  - The student's progress file (`progress.md`)
  - The topic's assigned material (`topics/<topic>/material.md`),
    loaded on demand when the artifact alone is not enough
- A topic directory is also directly readable: the student can open
  `material.md` and study the topic's slides and exercises without
  starting a chat at all.
- The tutor adapts: "I know nothing about this" - guided introduction;
  "quiz me" - exam-style problems with feedback.
- Tier B tasks are offered alongside Tier A ones, but the UI switches
  from "submit answer" to "show solution, then rate yourself".
- If the topic has Tier C tasks, the session mentions them once, so
  the student knows what they still have to practise elsewhere.
- Solutions always follow the professor's conventions and notation.
- **Language**: the tutor responds in the language of the course
  materials (detected during ingestion, overridable per course).
- **Chat history** is persisted like in a classic AI chat app: users
  can browse and revisit past sessions per course/topic. Past
  transcripts are **not** loaded as context into new sessions - that
  is what `progress.md` is for.

### Mock Exams
- Generate a full mock exam for a course on demand, assembled from the
  per-topic artifacts (no raw PDF access needed).
- Matches the real exam's structure, topic distribution, and difficulty.
- Can be taken interactively (tutor grades answers and gives feedback)
  or exported for offline practice.
- **Interactive mode** grades Tier A tasks, self-assesses Tier B, and
  lists Tier C tasks as "would appear in the real exam, not covered
  here" so the mock exam's shape stays honest about the real one.
- **Exported mode** includes all three tiers - on paper, a Tier C task
  is perfectly practisable. Export is therefore a first-class feature,
  not a convenience: it is the only path on which Tier C gets trained.
- Results feed into `progress.md`.

### Living Artifacts (updated at session boundaries)
- **`cheatsheet.md`** - key terms, formulas, and solution strategies
  the student has encountered. Grows during study sessions.
- **`progress.md`** - per-topic mastery assessment: what the student
  can do, where they struggle, what to review next. Assessed signals
  (Tier A) and self-reported ones (Tier B) are kept distinct - a
  student's self-rating is useful but is not evidence, and the tutor
  should not treat it as such.
- **Update trigger**: when a chat is closed or a new chat is started,
  the session is finalized and both artifacts are updated. Closing a
  chat = completing a study session. Every new session starts fully
  informed about the student's current level.

### Course Dashboard
Per-course overview showing:
- Topic list with priority and mastery status
- Overall readiness estimate ("how prepared am I?"), stated as
  **coverage-aware**: it reports readiness over what the tutor can
  actually train, and names the Tier C share separately rather than
  folding it in. A student who is at 100% here but has never drawn the
  circuit by hand is not exam ready, and the dashboard must say so.
- Recommended next steps ("focus on X, review Y")

## UI Sketch

A classic AI chat app, LibreChat in spirit: a collapsible course tree
on the left, one large chat on the right. The student never has to
learn a special interface - they open a course and ask a question.

```
┌─────────────────────────────┬──────────────────────────────────────────┐
│  iknownothing          [+]  │  Control Theory                          │
├─────────────────────────────┼──────────────────────────────────────────┤
│                             │                                          │
│ ▼ Control Theory      73%   │                    ┌───────────────────┐ │
│   ├ Topics                  │                    │ Which topics do I │ │
│   │   ● Laplace       92%   │                    │ still need to     │ │
│   │   ● Stability     61%   │                    │ learn?            │ │
│   │   ○ Observers      -    │                    └───────────────────┘ │
│   │   ○ State Space    -    │                                          │
│   ├ Sources                 │  Three topics are still open, in exam    │
│   │   lecture.pdf           │  priority order:                         │
│   │   exercises.pdf         │                                          │
│   │   exam-2024.pdf         │  1. Observers - high priority, never     │
│   ├ Cheatsheet              │     practised                            │
│   ├ Progress                │  2. State Space - high priority, never   │
│   ├ Mock Exams              │     practised                            │
│   └ Chats                   │  3. Stability - 61%, Nyquist is where    │
│       Stability             │     you keep slipping                    │
│       Laplace               │                                          │
│       Laplace (2)           │  Shall we start with Observers?          │
│                             │                                          │
│ ▶ Signals & Systems   12%   │  ┌────────────────────────────────────┐  │
│ ▶ Thermodynamics       0%   │  │ Ask anything...                 ▶  │  │
│                             │  └────────────────────────────────────┘  │
└─────────────────────────────┴──────────────────────────────────────────┘
```

- **Courses** are the top level, each showing its readiness estimate.
  Expanding one reveals everything that belongs to it.
- **Topics** are sorted by exam priority and carry a mastery marker
  (`●` worked on, `○` untouched). Clicking one opens a topic chat.
- **Sources**, **Cheatsheet**, **Progress** open the underlying
  Markdown as a readable, editable document - the data layer is not
  hidden behind the chat.
- **Chats** is the per-course history. A chat is **named after its
  topic**, so the history reads as a study log rather than a list of
  opaque conversation titles; repeat sessions on the same topic are
  numbered.
- The **main area** is an ordinary chat. Everything - planning,
  tutoring, quizzing, mock exams - happens there.

## Architecture Principles
1. **Markdown as the data layer.** All derived knowledge lives in
   human-readable, editable Markdown files. The student can inspect
   and correct anything.
2. **Artifacts are self-contained.** What the tutor cannot read as
   text does not exist for it. Every figure, diagram, and plot carries
   a textual description alongside the image reference - otherwise a
   topic whose content is mostly visual would be empty in a tutoring
   session.
3. **Ingest once, reuse forever - re-ingest only what changed.**
   Expensive PDF analysis happens once per file, and tutoring
   sessions run on small, focused artifacts. When material or an
   artifact changes, only the parts derived from it are rebuilt.
4. **Context discipline.** Sessions load only the current topic's
   artifacts - never entire courses. No vector DB in v0; structured
   topic-tagging replaces retrieval. RAG can be added later if
   courses outgrow this approach.
5. **Human in the loop at critical steps.** Automated where possible,
   reviewable where it matters (topic extraction, artifact editing).
6. **Fail gracefully on missing materials.** The pipeline adapts to
   whatever the student can provide.
7. **Thin deployment.** The container ships application code, not
   model weights. Anything that would require a GPU or multi-GB
   downloads on the user's machine belongs in the AI provider, not in
   the image.
8. **Multi-tenant by design.** All data is strictly namespaced per
   user; there is no shared state between users. Sharing course
   material between accounts stays out of scope - it is copyrighted,
   which makes this a legal problem rather than a technical one.

## Beyond v0
Direction, not a plan. Nothing here is designed yet.

- **Hosted version.** A managed deployment reachable over the web, so
  a user does not have to run Docker at all. The multi-tenant
  principle is what keeps this option open.
  - Hosted users choose between **their own API key** and an
    **all-inclusive** plan billed through the service.
- **Retrieval and AI tooling.** Evaluate RAG, vector search, and
  agentic tool use against the structured-artifact approach. v0
  deliberately does without retrieval; whether that holds as courses
  grow is an open question, not a settled answer.
- **EU-hosted AI providers.** Support for providers operating in the
  EU, for users who cannot or will not send course material to a US
  provider. The provider abstraction exists for this, not for generic
  multi-provider support.

## Open Questions (deferred to arc42)
- [ ] Tech stack: frontend framework, backend language/framework
- [ ] **Model selection per task type** - which model tier for
      ingestion, topic extraction, tutoring, and grading. These have
      very different quality/cost profiles and should not all default
      to the same model.
- [ ] How reliably can the gradability tier be assigned automatically?
      A Tier C task misclassified as Tier B gets posed and can't be
      answered; a Tier A task misclassified as Tier B silently loses a
      grading opportunity. Does the topic review step need to cover
      this too?
- [ ] **Dependency tracking for re-ingestion** - how a change is
      traced to exactly the artifacts that need rebuilding.
- [ ] **How a user edit survives regeneration.** The requirement is
      fixed (no silent loss); the mechanism is not.
- [ ] **Migrating `progress.md` across topic changes** (rename,
      merge, removal).
- [ ] Difficulty calibration: purely AI-judged, or with a rubric?
- [ ] Encryption/storage strategy for per-user API keys
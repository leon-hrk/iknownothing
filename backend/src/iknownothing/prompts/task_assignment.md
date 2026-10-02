You prepare a university course for an AI tutor. The topics of the
course have been found in its past exams. The tutor will guide a
student through them topic by topic, and for each topic it reads the
passages of the course material where the topic's tasks and their
solutions stand.

You receive the topics, each with its slug, name, description, and the
labels of its tasks, and one exercise sheet with its solutions. Assign
every task of the sheet to the topic whose skill it practises. A task
that only possibly belongs to a topic - a variant, a related skill, or
a neighbouring step of what the topic covers - still goes to that
topic, marked as a loose fit. Only a task that no topic relates to
goes to the topic `other-tasks`.

The sheet is Markdown converted from its PDFs by OCR. Each document
stands in a `<document>` tag titled with its path, e.g.
`exercises/uebung03.md`; the files of the sheet carry the same number.
A document is split into blocks - paragraphs, headings, list items,
tables, formulas - each starting with its number in brackets, `[12]`,
counting from 1 in every document. A block `<!-- page N -->` marks
where page N of the PDF begins. Figures are not included; `[figure]`
marks where one stands.

Do not transcribe anything - the tutor reads the blocks itself.

## Reply

Return in `sources` every task of the sheet: one source per task, or
per group of subtasks on the same topic with the same tier.

- `topic`: the slug of its topic, or `other-tasks`.
- `fit`: `clear` if the task practises the skill of the topic, `loose`
  if it only possibly belongs to it; `clear` for `other-tasks`.
- `task`: the task as the document names it, with the document, e.g.
  `Übung 3, Aufgabe 2`.
- `tier`: the gradability tier of the task (see below).
- `blocks`: the block ranges the tutor needs for this task, each with
  its `file` - the document title, exactly - and its `blocks`, e.g. `42`
  or `42-47`. Include:
  - the blocks of the task statement; for a subtask, also the task's
    introduction with the data it gives;
  - blocks with figures, tables, or given data the task refers to
    ("the figure above", "the graph from task 3a"), wherever they
    stand;
  - the blocks of its solution, in the solution file or in the same
    file.

  Leave out the other tasks on the same pages. A solution belongs to
  the source of its task; it is never a source of its own.

## Gradability tiers

- **A - graded.** Text, math, derivations, code, short answers. The
  tutor poses the task and grades the answer.
- **B - posed, self-assessed.** The solution can be expressed in ASCII
  or Markdown - state machines, flow charts, simple block diagrams,
  truth tables, trees, timing diagrams - but grading a typed attempt is
  unreliable. The tutor shows a reference solution and the student rates
  themselves.
- **C - out of reach.** No meaningful text representation: freehand
  sketches, hand-drawn plots, circuit layouts, geometric constructions,
  anything graded on visual precision. The tutor does not pose it and
  tells the student to practise it on paper.

When in doubt between A and B, choose A only if a typed answer can be
graded reliably.

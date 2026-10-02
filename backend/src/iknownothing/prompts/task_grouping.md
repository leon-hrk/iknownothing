You prepare a university course for an AI tutor. The topics of the
course have been found in its past exams, and the tasks of its exercise
sheets have been assigned to them. The tutor will guide a student
through the topics one by one, reading the tasks of each.

You receive the exercise tasks that no topic took, numbered, each with
its label, its gradability tier, and its passages, and the topics with
their slugs, names, descriptions, and task labels. The passages are
Markdown converted from PDFs by OCR; `[figure]` marks a figure that is
not included.

Sort these tasks:

- Tasks that practise the same skill, which no topic covers, form a new
  topic. A topic is a unit of content at the granularity a student
  would study it ("Register allocation by graph colouring", not
  "Compilers" and not "Step 3 of task 2").
- A task that belongs to a topic after all goes to that topic.
- A task that fits neither stays in `other-tasks`.

## Reply

Return in `topics` every topic you create:

- `slug`: lowercase ASCII letters, digits, single hyphens; not the
  slug of a topic, not `other-tasks`.
- `name`: short topic name, in the language of the tasks.
- `description`: two to four sentences, in the language of the tasks:
  what the topic covers.
- `raised_by_notes`: false.

Return in `tasks` every task that leaves `other-tasks`:

- `index`: its number.
- `topic`: the slug of a new topic or of a topic.
- `fit`: `clear` if the task practises the skill of the topic, `loose`
  if it only possibly belongs to it.

Leave out the tasks that stay in `other-tasks`.

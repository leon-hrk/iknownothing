import { type DragEvent, useEffect, useRef, useState } from "react";

import { addFiles, createCourse, readFile } from "./api";

const NAME = /^[a-z0-9][a-z0-9_-]*$/;

/** PDFs dropped on it or picked, listed with a button to take each out again. */
function Drop({ label, files, onChange }: { label: string; files: File[]; onChange: (files: File[]) => void }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const add = (list: FileList | null) => {
    const pdfs = [...(list ?? [])].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    onChange([...files.filter((f) => !pdfs.some((p) => p.name === f.name)), ...pdfs]);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    add(e.dataTransfer.files);
  };
  return (
    <div className="drop-field">
      <span className="label">{label}</span>
      <div className={over ? "drop over" : "drop"} onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
        Drop PDFs here, or click to choose
        <input ref={input} type="file" accept=".pdf,application/pdf" multiple hidden
          onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </div>
      {files.length > 0 && (
        <ul className="picked">
          {files.map((f) => (
            <li key={f.name}>
              <span>{f.name}</span>
              <button title="Remove" onClick={() => onChange(files.filter((x) => x !== f))}>×</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Creates a course, or with `course` adds files to it: notes and PDFs sorted into past exams and exercise sheets.
 * On OK the files are uploaded and the ingestion starts. */
export default function CourseDialog({ course, onDone, onCancel }: {
  course?: string;
  onDone: (course: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [exams, setExams] = useState<File[]>([]);
  const [exercises, setExercises] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (course) readFile(course, "notes.md").then(setNotes).catch(() => setNotes(""));
  }, [course]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onCancel(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  const nameOk = !!course || NAME.test(name);
  const ready = nameOk && exams.length + exercises.length > 0;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (course) await addFiles(course, notes, exams, exercises);
      else await createCourse(name, notes, exams, exercises);
      onDone(course ?? name);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}>
      <div className="dialog wide" role="dialog" aria-labelledby="course-title">
        <h2 id="course-title">{course ? `Add files to ${course}` : "New course"}</h2>
        {!course && (
          <label className="field">
            <span className="label">Name</span>
            <input autoFocus value={name} placeholder="e.g. hscd" onChange={(e) => setName(e.target.value)} />
            {name && !nameOk && <span className="error">Lowercase letters, digits, hyphens, and underscores.</span>}
          </label>
        )}
        <Drop label="Past exams" files={exams} onChange={setExams} />
        <Drop label="Exercise sheets" files={exercises} onChange={setExercises} />
        <label className="field">
          <span className="label">Notes</span>
          <textarea rows={4} value={notes} placeholder="What the exam covers, what the lecturer stressed, what to skip"
            onChange={(e) => setNotes(e.target.value)} />
        </label>
        <p>A solution sheet goes with its exam or exercise sheet: files with the same digits in their names belong
          together.</p>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button disabled={busy} onClick={onCancel}>Cancel</button>
          <button className="primary" disabled={!ready || busy} onClick={submit}>
            {busy ? "Uploading…" : "OK"}
          </button>
        </div>
      </div>
    </div>
  );
}

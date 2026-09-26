"""Session finalization: updates a topic's progress.md from a finished topic-level chat."""

from iknownothing.ai_client import AIClient
from iknownothing.course_store import CourseStore
from iknownothing.tutor.chat import topic_entry


def render_transcript(transcript: list[dict]) -> str:
    """The chat as readable text: messages, posed tasks, and cheatsheet changes."""
    out = []
    for m in transcript:
        content = m["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for b in content:
            if b["type"] == "text":
                who = "Student" if m["role"] == "user" else "Tutor"
                out.append(f"{who}: {b['text'].strip()}")
            elif b["type"] == "tool_use" and b["name"] == "pose_task":
                out.append(f"[Task posed: {b['input']['task']}, Tier {b['input']['tier']}]")
            elif b["type"] == "tool_use" and b["name"] == "update_cheatsheet":
                out.append(f"[Cheatsheet entry: {b['input']['heading']}]")
    return "\n\n".join(out)


async def finalize(store: CourseStore, ai: AIClient, slug: str, language: str, transcript: list[dict]) -> None:
    if not transcript:
        return
    topic = topic_entry(store, slug)
    rel = f"{topic['dir']}/progress.md"
    current = store.read_text(rel) if store.exists(rel) else "(none yet - this was the first session)"
    data = (
        f"<language>{language}</language>\n\n"
        f"<topic>\n{store.read_text(f'{topic['dir']}/topic.md')}\n</topic>\n\n"
        f"<progress>\n{current}\n</progress>\n\n"
        f"<transcript>\n{render_transcript(transcript)}\n</transcript>"
    )
    progress = await ai.request_text("finalization", [{"role": "user", "content": data}])
    store.write_text(rel, progress.strip() + "\n")

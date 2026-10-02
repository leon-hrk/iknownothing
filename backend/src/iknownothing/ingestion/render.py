"""Rendering topic.md from an extracted topic."""

from iknownothing.ingestion.topics import Topic


def _source_line(source: dict) -> str:
    where = ", ".join(f"{r['file']} p. {r['pages']}" for r in source["blocks"])
    fit = ", loose fit" if source["fit"] == "loose" else ""
    return f"- **{source['task']}** (Tier {source['tier']}{fit}): {where}"


def render_topic(topic: Topic, exam_count: int) -> str:
    """`topic` with its priority, the number of past exams asking for it, and its listed sources."""
    priority = topic["priority"]
    if exam_count:
        priority += f" - asked in {topic['exams']} of {exam_count} past exams"
    if topic["raised_by_notes"]:
        priority += ", raised by the notes"
    out = [f"# {topic['name']}", "", f"**Priority:** {priority}", "", topic["description"].strip(), ""]
    reachable = [s for s in topic["sources"] if s["tier"] != "C"]
    out_of_reach = [s for s in topic["sources"] if s["tier"] == "C"]
    if reachable:
        out.extend(["## Sources", "", *map(_source_line, reachable), ""])
    if out_of_reach:
        out.extend(["## Out of Reach", "", *map(_source_line, out_of_reach), ""])
    return "\n".join(out)

"""Rendering topic.md from an extracted topic."""

from iknownothing.ingestion.topics import Topic


def _source_line(source: dict) -> str:
    where = ", ".join(f"{r['file']} p. {r['pages']}" for r in source["pages"])
    return f"- **{source['task']}** (Tier {source['tier']}): {where}"


def render_topic(topic: Topic) -> str:
    out = [f"# {topic['name']}", "", f"**Priority:** {topic['priority']}", "", topic["description"].strip(), ""]
    reachable = [s for s in topic["sources"] if s["tier"] != "C"]
    out_of_reach = [s for s in topic["sources"] if s["tier"] == "C"]
    if reachable:
        out.extend(["## Sources", "", *map(_source_line, reachable), ""])
    if out_of_reach:
        out.extend(["## Out of Reach", "", *map(_source_line, out_of_reach), ""])
    return "\n".join(out)

"""cheatsheet.md as sections (`## `) of entries (`### `), changed one entry at a time."""

TITLE = "# Cheatsheet"


class CheatsheetError(Exception):
    pass


Sections = dict[str, dict[str, str]]


def parse(text: str) -> Sections:
    sections: Sections = {}
    entries = None
    body: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            entries = sections.setdefault(line[3:].strip(), {})
            body = None
        elif line.startswith("### ") and entries is not None:
            body = []
            entries[line[4:].strip()] = body
        elif body is not None:
            body.append(line)
    return {s: {h: "\n".join(b).strip() for h, b in e.items()} for s, e in sections.items()}


def render(sections: Sections) -> str:
    out = [TITLE, ""]
    for section, entries in sections.items():
        if not entries:
            continue
        out.extend([f"## {section}", ""])
        for heading, body in entries.items():
            out.extend([f"### {heading}", "", body, ""])
    return "\n".join(out)


def set_entry(text: str, section: str, heading: str, body: str) -> str:
    """Adds or replaces one entry; an empty body removes it."""
    section, heading, body = section.strip(), heading.strip(), body.strip()
    if not section or not heading or "\n" in section or "\n" in heading:
        raise CheatsheetError("section and heading must be single, non-empty lines")
    if any(line.startswith(("# ", "## ", "### ")) for line in body.splitlines()):
        raise CheatsheetError("the body must not contain headings of level 1 to 3; use #### or bold text")
    sections = parse(text)
    entries = sections.setdefault(section, {})
    if body:
        entries[heading] = body
    elif heading in entries:
        del entries[heading]
    else:
        raise CheatsheetError(f"no entry {heading!r} in section {section!r} to remove")
    return render(sections)

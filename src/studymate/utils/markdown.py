from __future__ import annotations

import html
import re


def cleanup_plain_text(text: str) -> str:
    value = text or ""
    value = value.replace("**", "")
    value = value.replace("__", "")
    value = value.replace("`", "")
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    value = value.replace("#", "")
    return value.strip()


def markdown_to_html(text: str) -> str:
    normalized_text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized_text = normalized_text.replace("\u00a0", " ")
    normalized_text = normalized_text.replace("\ufeff", "")
    normalized_text = normalized_text.replace("\u200b", "")
    lines = normalized_text.split("\n")
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    list_kind = ""
    quote_lines: list[str] = []
    table_lines: list[str] = []
    in_code_fence = False
    code_lines: list[str] = []
    code_language = ""

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if not paragraph_lines:
            return
        content = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if content:
            blocks.append(f"<p>{_render_inline(content)}</p>")
        paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items, list_kind
        if not list_items:
            return
        tag = "ol" if list_kind == "ol" else "ul"
        blocks.append(f"<{tag}>" + "".join(f"<li>{item}</li>" for item in list_items) + f"</{tag}>")
        list_items = []
        list_kind = ""

    def flush_quote() -> None:
        nonlocal quote_lines
        if not quote_lines:
            return
        content = " ".join(line.strip() for line in quote_lines if line.strip())
        if content:
            blocks.append(f"<blockquote><p>{_render_inline(content)}</p></blockquote>")
        quote_lines = []

    def flush_table() -> None:
        nonlocal table_lines
        if not table_lines:
            return
        rendered = _render_table(table_lines)
        if rendered:
            blocks.append(rendered)
        else:
            for line in table_lines:
                paragraph_lines.append(line)
        table_lines = []

    def flush_all() -> None:
        flush_table()
        flush_list()
        flush_quote()
        flush_paragraph()

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if in_code_fence:
            if stripped.startswith(("```", "~~~")):
                code_html = html.escape("\n".join(code_lines))
                class_attr = f' class="language-{html.escape(code_language)}"' if code_language else ""
                blocks.append(f"<pre><code{class_attr}>{code_html}</code></pre>")
                in_code_fence = False
                code_lines = []
                code_language = ""
            else:
                code_lines.append(raw_line)
            continue

        if stripped.startswith(("```", "~~~")):
            flush_all()
            in_code_fence = True
            code_lines = []
            code_language = stripped[3:].strip()
            continue

        if not stripped:
            flush_all()
            continue

        if stripped.startswith("|"):
            flush_paragraph()
            flush_list()
            flush_quote()
            table_lines.append(stripped)
            continue
        flush_table()

        heading_match = re.match(r"^(#{1,6})[ \t]*(.+)$", stripped)
        if heading_match:
            flush_all()
            level = min(6, len(heading_match.group(1)))
            heading_text = heading_match.group(2).strip()
            while True:
                cleaned_heading = re.sub(r"^#{1,6}[ \t\u00a0]+", "", heading_text)
                if cleaned_heading == heading_text:
                    break
                heading_text = cleaned_heading.lstrip()
            blocks.append(f"<h{level}>{_render_inline(heading_text)}</h{level}>")
            continue

        if re.fullmatch(r"(?:\*{3,}|-{3,}|_{3,})", stripped):
            flush_all()
            blocks.append("<hr />")
            continue

        bullet_match = re.match(r"^(?:[-*+]\s+|[•●▪◦⁃∙]\s+)(.*)$", stripped)
        if bullet_match:
            flush_paragraph()
            flush_quote()
            item = _render_inline(bullet_match.group(1).strip())
            if list_kind not in {"", "ul"}:
                flush_list()
            list_kind = "ul"
            list_items.append(item)
            continue

        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered_match:
            flush_paragraph()
            flush_quote()
            item = _render_inline(ordered_match.group(1).strip())
            if list_kind not in {"", "ol"}:
                flush_list()
            list_kind = "ol"
            list_items.append(item)
            continue

        quote_match = re.match(r"^>\s?(.*)$", stripped)
        if quote_match:
            flush_paragraph()
            flush_list()
            quote_lines.append(quote_match.group(1))
            continue

        flush_list()
        flush_quote()
        paragraph_lines.append(stripped)

    if in_code_fence:
        code_html = html.escape("\n".join(code_lines))
        class_attr = f' class="language-{html.escape(code_language)}"' if code_language else ""
        blocks.append(f"<pre><code{class_attr}>{code_html}</code></pre>")
    else:
        flush_all()

    return "".join(blocks)


def _render_inline(text: str) -> str:
    placeholders: dict[str, str] = {}

    def stash(pattern: str, builder) -> str:
        nonlocal text

        def replace(match: re.Match[str]) -> str:
            key = f"__MD_PLACEHOLDER_{len(placeholders)}__"
            placeholders[key] = builder(match)
            return key

        text = re.sub(pattern, replace, text)
        return text

    stash(
        r"`([^`\n]+)`",
        lambda match: f"<code>{html.escape(match.group(1))}</code>",
    )
    escaped = html.escape(text)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda match: f'<a href="{html.escape(match.group(2), quote=True)}">{match.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r"<s>\1</s>", escaped)
    for key, value in placeholders.items():
        escaped = escaped.replace(html.escape(key), value)
        escaped = escaped.replace(key, value)
    return escaped


def _render_table(lines: list[str]) -> str:
    if len(lines) < 2:
        return ""
    header_cells = _split_table_row(lines[0])
    separator_cells = _split_table_row(lines[1])
    if not header_cells or not separator_cells or len(header_cells) != len(separator_cells):
        return ""
    if not all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in separator_cells):
        return ""

    body_rows = [_split_table_row(line) for line in lines[2:]]
    if any(len(row) != len(header_cells) for row in body_rows):
        return ""

    thead = "<thead><tr>" + "".join(f"<th>{_render_inline(cell.strip())}</th>" for cell in header_cells) + "</tr></thead>"
    tbody_rows = []
    for row in body_rows:
        tbody_rows.append("<tr>" + "".join(f"<td>{_render_inline(cell.strip())}</td>" for cell in row) + "</tr>")
    tbody = "<tbody>" + "".join(tbody_rows) + "</tbody>" if tbody_rows else ""
    return f"<table>{thead}{tbody}</table>"


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    row = stripped[1:-1] if stripped.endswith("|") else stripped[1:]
    return [cell.strip() for cell in row.split("|")]

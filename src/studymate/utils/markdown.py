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


def markdown_to_html(text: str, *, editorial: bool = False) -> str:
    normalized_text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized_text = normalized_text.replace("\u00a0", " ")
    normalized_text = normalized_text.replace("\ufeff", "")
    normalized_text = normalized_text.replace("\u200b", "")
    lines = normalized_text.split("\n")
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[tuple[str, int]] = []
    list_kind = ""
    list_start = 1
    quote_lines: list[str] = []
    table_lines: list[str] = []
    in_code_fence = False
    code_lines: list[str] = []
    code_language = ""
    last_block_tag = ""

    def flush_paragraph() -> None:
        nonlocal paragraph_lines, last_block_tag
        if not paragraph_lines:
            return
        content = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if content:
            class_attr = ' class="meta"' if editorial and _looks_like_meta_line(content) and last_block_tag == "h1" else ""
            blocks.append(f"<p{class_attr}>{_render_inline(content, editorial=editorial)}</p>")
            last_block_tag = "p"
        paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items, list_kind, list_start, last_block_tag
        if not list_items:
            return
        if list_kind == "ol" or not editorial:
            tag = "ol" if list_kind == "ol" else "ul"
            start_attr = f' start="{list_start}"' if tag == "ol" and list_start > 1 else ""
            blocks.append(f"<{tag}{start_attr}>" + "".join(f"<li>{item}</li>" for item, _indent in list_items) + f"</{tag}>")
        else:
            rows = "".join(
                '<tr>'
                f'<td class="bullet-cell" style="color:#76B993; padding-left:{min(indent * 10, 40)}px;">&bull;</td>'
                f'<td class="bullet-text{ " bullet-subtext" if indent else "" }">{item}</td>'
                '</tr>'
                for item, indent in list_items
            )
            blocks.append(f'<table class="bullet-list">{rows}</table>')
        last_block_tag = list_kind or "ul"
        list_items = []
        list_kind = ""
        list_start = 1

    def flush_quote() -> None:
        nonlocal quote_lines, last_block_tag
        if not quote_lines:
            return
        content = " ".join(line.strip() for line in quote_lines if line.strip())
        if content:
            blocks.append(f"<blockquote><p>{_render_inline(content, editorial=editorial)}</p></blockquote>")
            last_block_tag = "blockquote"
        quote_lines = []

    def flush_table() -> None:
        nonlocal table_lines, last_block_tag
        if not table_lines:
            return
        rendered = _render_table(table_lines)
        if rendered:
            blocks.append(rendered)
            last_block_tag = "table"
        else:
            for line in table_lines:
                paragraph_lines.append(line)
        table_lines = []

    def flush_all() -> None:
        flush_table()
        flush_list()
        flush_quote()
        flush_paragraph()

    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        stripped = line.strip()

        if in_code_fence:
            if stripped.startswith(("```", "~~~")):
                code_html = html.escape("\n".join(code_lines))
                class_attr = f' class="language-{html.escape(code_language)}"' if code_language else ""
                blocks.append(f"<pre><code{class_attr}>{code_html}</code></pre>")
                last_block_tag = "pre"
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
            next_stripped = ""
            for next_line in lines[index + 1:]:
                next_stripped = next_line.strip()
                if next_stripped:
                    break
            if list_kind == "ol" and re.match(r"^\d+\.\s+", next_stripped):
                continue
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
            if editorial and level == 1 and not last_block_tag:
                blocks.append(f'<p><font color="#357B78">{_render_inline(heading_text, editorial=editorial)}</font></p>')
                last_block_tag = "p"
                continue
            if editorial:
                level = max(2, level)
                heading_text = heading_text.upper()
            content = _render_inline(heading_text, editorial=editorial)
            if editorial and level in {1, 2, 3}:
                content = f'<font color="#357B78">{content}</font>'
            blocks.append(f"<h{level}>{content}</h{level}>")
            last_block_tag = f"h{level}"
            continue

        if re.fullmatch(r"(?:\*{3,}|-{3,}|_{3,})", stripped):
            flush_all()
            blocks.append("<hr />")
            last_block_tag = "hr"
            continue

        bullet_match = re.match(r"^(\s*)(?:[-*+]\s+|[â€¢â—â–ªâ—¦âƒâˆ™]\s+)(.*)$", line)
        if bullet_match:
            flush_paragraph()
            flush_quote()
            indent = len(bullet_match.group(1).replace("\t", "    "))
            item = _render_list_item_inline(bullet_match.group(2).strip(), editorial=editorial)
            if list_kind not in {"", "ul"}:
                flush_list()
            list_kind = "ul"
            list_items.append((item, indent))
            continue

        ordered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered_match:
            flush_paragraph()
            flush_quote()
            item = _render_list_item_inline(ordered_match.group(1).strip(), editorial=editorial)
            if list_kind not in {"", "ol"}:
                flush_list()
            if list_kind == "":
                list_start = max(1, int(re.match(r"^(\d+)\.", stripped).group(1)))
            list_kind = "ol"
            list_items.append((item, 0))
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


def _looks_like_meta_line(text: str) -> bool:
    value = " ".join(str(text or "").strip().split())
    if not value or len(value) > 140:
        return False
    lowered = value.lower()
    meta_terms = (
        "generated",
        "uploaded",
        "image",
        "source",
        "read",
        "minute",
        "min",
        "estimated",
    )
    return any(term in lowered for term in meta_terms) and not bool(re.search(r"[!?]$", value))


def _render_inline(text: str, *, editorial: bool = False) -> str:
    placeholders: dict[str, str] = {}

    def stash(pattern: str, builder) -> str:
        nonlocal text

        def replace(match: re.Match[str]) -> str:
            # Keep placeholder markers free of markdown trigger chars
            # (like `_` and `*`) so emphasis parsing cannot corrupt them.
            key = f"MDPHX{len(placeholders)}XPH"
            placeholders[key] = builder(match)
            return key

        text = re.sub(pattern, replace, text)
        return text

    stash(
        r"!\[([^\]]*)\]\(([^)\n]+)\)",
        lambda match: (
            '<img class="wiki-thumb" '
            f'src="{html.escape(match.group(2).strip().replace(" ", "%20"), quote=True)}" '
            f'alt="{html.escape(match.group(1), quote=True)}" '
            'width="252" align="left" '
            'style="float:left; max-width:252px; max-height:310px;" />'
        ),
    )
    stash(r"`([^`\n]+)`", lambda match: f"<code>{html.escape(match.group(1))}</code>")
    escaped = html.escape(text)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda match: f'<a href="{html.escape(html.unescape(match.group(2)), quote=True)}">{match.group(1)}</a>',
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
    if editorial:
        escaped = _color_editorial_bold(escaped)
    return escaped


def _render_list_item_inline(text: str, *, editorial: bool = False) -> str:
    rendered = _render_inline(text, editorial=editorial)
    if not editorial:
        return rendered
    return re.sub(
        r'^<font color="#566064"><b>(.*?)</b></font>',
        _mark_bullet_heading,
        rendered,
        count=1,
    )


def _color_editorial_bold(rendered: str) -> str:
    return re.sub(r"<strong>(.*?)</strong>", r'<font color="#566064"><b>\1</b></font>', rendered)


def _mark_bullet_heading(match: re.Match[str]) -> str:
    heading = match.group(1) or ""
    return f'<font color="#B66A2C"><b>{heading}</b></font>'


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

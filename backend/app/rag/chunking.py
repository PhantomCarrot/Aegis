"""
Markdown document chunking for RAG indexing.

Splits by heading structure rather than a naive blind sliding window: each
chunk is prefixed with its "breadcrumb" (e.g. "Cluster > Pods") so the
hierarchical context isn't lost once it's isolated from the rest of the
document — see docs/rag.md. Size expressed in characters as an approximate
proxy for token count (~4 chars/token in French/English).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

DEFAULT_MAX_CHARS = 2000
DEFAULT_OVERLAP_CHARS = 200

# How far back _backoff_to_boundary is allowed to look for a space/newline
# before giving up and falling back to the original hard cut.
_BOUNDARY_LOOKBACK_CHARS = 100


@dataclass
class Chunk:
    text: str          # content, already prefixed with the breadcrumb
    heading_path: str  # e.g. "Cluster > Pods" (empty if the doc has no headings)
    chunk_index: int


def _split_by_headings(markdown: str) -> list[tuple[list[str], str]]:
    """Returns a list of (heading_path, section_content)."""
    sections: list[tuple[list[str], str]] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append(([title for _, title in stack], content))

    for line in markdown.splitlines():
        m = _HEADING_RE.match(line)
        if not m:
            current_lines.append(line)
            continue
        flush()
        current_lines = []
        level = len(m.group(1))
        title = m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
    flush()

    if not sections and markdown.strip():
        sections.append(([], markdown.strip()))
    return sections


def _backoff_to_boundary(content: str, cut: int) -> int:
    """
    Nudges a hard character-count cut point back to the index of the
    nearest space or newline within a lookback window — slicing
    `content[:idx]` there never ends mid-word. Falls back to the original
    `cut` unchanged if no boundary is found in the window (e.g. a single
    token longer than the window) — never worse than a blind
    character-count cut.
    """
    if cut <= 0 or cut >= len(content):
        return cut
    window_start = max(0, cut - _BOUNDARY_LOOKBACK_CHARS)
    boundary = max(content.rfind(" ", window_start, cut), content.rfind("\n", window_start, cut))
    return boundary if boundary != -1 else cut


def chunk_markdown(
    markdown: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """
    Splits a Markdown document into chunks with a heading breadcrumb. A
    section that's too long is re-split with a sliding window, keeping the
    same breadcrumb on each piece.
    """
    chunks: list[Chunk] = []
    idx = 0
    for path, content in _split_by_headings(markdown):
        breadcrumb = " > ".join(path)
        prefix = f"{breadcrumb}\n\n" if breadcrumb else ""

        if len(content) <= max_chars:
            chunks.append(Chunk(text=f"{prefix}{content}", heading_path=breadcrumb, chunk_index=idx))
            idx += 1
            continue

        start = 0
        while start < len(content):
            end = _backoff_to_boundary(content, start + max_chars)
            # rstrip: when a boundary was found, `end` points AT the space
            # itself (content[start:end] would keep it as a trailing char).
            piece = content[start:end].rstrip()
            chunks.append(Chunk(text=f"{prefix}{piece}", heading_path=breadcrumb, chunk_index=idx))
            idx += 1
            if end >= len(content):
                break
            # Guarded with max() so a small max_chars relative to
            # overlap_chars/lookback can never stall progress.
            start = _backoff_to_boundary(content, max(end - overlap_chars, start + 1))
            # Skip past the boundary whitespace itself so the next chunk
            # doesn't start mid-word (or start with a leading space).
            while start < len(content) and content[start] in " \n":
                start += 1

    return chunks

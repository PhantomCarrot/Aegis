from app.rag.chunking import _backoff_to_boundary, chunk_markdown


def test_single_section_no_heading():
    chunks = chunk_markdown("Just some text, no heading.")
    assert len(chunks) == 1
    assert chunks[0].heading_path == ""
    assert "Just some text" in chunks[0].text


def test_splits_by_heading_and_keeps_breadcrumb():
    md = "# Overview\n\nIntro.\n\n## Pods\n\nList of pods.\n"
    chunks = chunk_markdown(md)
    assert [c.heading_path for c in chunks] == ["Overview", "Overview > Pods"]
    assert chunks[0].text.startswith("Overview\n\n")
    assert chunks[1].text.startswith("Overview > Pods\n\n")
    assert "Intro." in chunks[0].text
    assert "List of pods." in chunks[1].text


def test_sibling_headings_do_not_nest():
    md = "# A\n\ncontent a\n\n# B\n\ncontent b\n"
    chunks = chunk_markdown(md)
    assert [c.heading_path for c in chunks] == ["A", "B"]


def test_heading_path_pops_back_to_correct_level():
    md = "# A\n\na\n\n## A1\n\na1\n\n# B\n\nb\n"
    chunks = chunk_markdown(md)
    assert [c.heading_path for c in chunks] == ["A", "A > A1", "B"]


def test_long_section_is_split_with_overlap():
    body = "x" * 5000
    md = f"# Big\n\n{body}\n"
    chunks = chunk_markdown(md, max_chars=2000, overlap_chars=200)
    assert len(chunks) > 1
    assert all(c.heading_path == "Big" for c in chunks)
    # each chunk keeps the breadcrumb as a prefix
    assert all(c.text.startswith("Big\n\n") for c in chunks)


def test_chunk_index_is_sequential_across_sections():
    md = "# A\n\na\n\n# B\n\nb\n"
    chunks = chunk_markdown(md)
    assert [c.chunk_index for c in chunks] == [0, 1]


def test_empty_document_returns_no_chunks():
    assert chunk_markdown("") == []
    assert chunk_markdown("   \n\n  ") == []


def test_long_section_never_cuts_mid_word():
    # Real words (unlike the "x" * 5000 blob above) so a mid-word cut is
    # actually detectable — every chunk boundary must land on whitespace.
    body = " ".join(f"word{i}" for i in range(1000))
    md = f"# Big\n\n{body}\n"
    chunks = chunk_markdown(md, max_chars=2000, overlap_chars=200)
    assert len(chunks) > 1
    for c in chunks:
        content = c.text.removeprefix("Big\n\n")
        pos = body.find(content)
        assert pos != -1, "chunk content should be a literal substring of the body"
        before = body[pos - 1] if pos > 0 else " "
        after_index = pos + len(content)
        after = body[after_index] if after_index < len(body) else " "
        assert before.isspace(), f"chunk starts mid-word: {content[:20]!r}"
        assert after.isspace(), f"chunk ends mid-word: {content[-20:]!r}"


def test_backoff_to_boundary_falls_back_to_hard_cut_on_giant_token():
    # No whitespace anywhere in the lookback window — nothing to back off
    # to, so the original hard cut point is returned unchanged.
    content = "x" * 500
    assert _backoff_to_boundary(content, 300) == 300


def test_backoff_to_boundary_finds_nearest_preceding_space():
    content = "a" * 250 + " " + "b" * 100
    # cut lands inside the run of "b"s — should back off to the space itself.
    assert _backoff_to_boundary(content, 300) == 250
    assert content[250] == " "

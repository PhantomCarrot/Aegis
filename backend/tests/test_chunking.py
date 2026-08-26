from app.rag.chunking import chunk_markdown


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

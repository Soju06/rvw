from __future__ import annotations

from rvw.diffbudget import apply_diff_budget, reviewed_diff


def diff_segment(path: str, body: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+{body}\n"


def test_generated_path_is_excluded_and_announced() -> None:
    generated = diff_segment("runtime-snapshots/contract-graph.json", "generated")
    source = diff_segment("src/app.py", "kept")

    chunks, report = apply_diff_budget(generated + source)
    filtered = chunks[0].text

    assert filtered.startswith(
        "# rvw: 1 files excluded from review diff (generated/oversize): "
        "runtime-snapshots/contract-graph.json\n"
    )
    assert generated not in filtered
    assert source in filtered
    assert report.kept_files == ["src/app.py"]
    assert report.excluded_files == ["runtime-snapshots/contract-graph.json"]
    assert report.excluded_reason == {"runtime-snapshots/contract-graph.json": "generated-path"}
    assert report.kept_chars == len(source)
    assert report.excluded_chars == len(generated)
    assert report.kept_chars + report.excluded_chars == len(generated + source)


def test_generated_globs_match_nested_paths() -> None:
    generated = diff_segment("packages/api/runtime-snapshots/graph.json", "generated")

    chunks, report = apply_diff_budget(generated)
    filtered = chunks[0].text

    assert "diff --git" not in filtered
    assert report.excluded_reason == {"packages/api/runtime-snapshots/graph.json": "generated-path"}


def test_oversize_file_is_excluded() -> None:
    oversized = diff_segment("src/large.py", "x" * 80)

    chunks, report = apply_diff_budget(oversized, max_file_chars=len(oversized) - 1)
    filtered = chunks[0].text

    assert filtered.startswith("# rvw: 1 files excluded")
    assert report.kept_files == []
    assert report.excluded_files == ["src/large.py"]
    assert report.excluded_reason == {"src/large.py": "oversize-file"}
    assert report.excluded_chars == len(oversized)


def test_tabelog_sized_diff_is_chunked_in_file_order_with_exact_placement() -> None:
    segments = [
        diff_segment(f"providers/tabelog/file-{index}.ts", "x" * 146_900) for index in range(5)
    ]
    diff = "".join(segments)
    assert 734_000 < len(diff) < 736_000

    chunks, report = apply_diff_budget(diff)

    assert len(chunks) >= 2
    assert [file for chunk in chunks for file in chunk.files] == [
        f"providers/tabelog/file-{index}.ts" for index in range(5)
    ]
    assert all(chunk.chars <= 400_000 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == diff
    assert sum(chunk.chars for chunk in chunks) == len(diff)
    assert report.chunk_count == len(chunks)
    assert [placement.model_dump() for placement in report.chunks] == [
        {"index": chunk.index, "files": chunk.files, "chars": chunk.chars} for chunk in chunks
    ]


def test_no_exclusions_preserves_diff_exactly() -> None:
    diff = diff_segment("src/app.py", "kept")

    chunks, report = apply_diff_budget(diff)

    assert len(chunks) == 1
    assert chunks[0].text == diff
    assert chunks[0].files == ["src/app.py"]
    assert chunks[0].chars == len(diff)
    assert report.model_dump() == {
        "kept_files": ["src/app.py"],
        "excluded_files": [],
        "excluded_reason": {},
        "kept_chars": len(diff),
        "excluded_chars": 0,
        "chunk_count": 1,
        "chunks": [{"index": 1, "files": ["src/app.py"], "chars": len(diff)}],
    }


def test_diff_just_below_total_limit_stays_one_byte_identical_chunk() -> None:
    diff = diff_segment("src/a.py", "x" * 199_000) + diff_segment("src/b.py", "x" * 199_000)
    assert 398_000 < len(diff) <= 400_000

    chunks, report = apply_diff_budget(diff)

    assert len(chunks) == 1
    assert chunks[0].text == diff
    assert chunks[0].chars == len(diff)
    assert report.chunk_count == 1


def test_reviewed_diff_projects_kept_segments_behind_the_exclusion_header() -> None:
    generated = diff_segment("pnpm-lock.yaml", "generated")
    oversized = diff_segment("src/large.py", "x" * 400)
    source = diff_segment("src/app.py", "kept")
    diff = generated + oversized + source

    reviewed = reviewed_diff(diff, max_file_chars=len(oversized) - 1)
    chunks, chunk_report = apply_diff_budget(diff, max_file_chars=len(oversized) - 1)

    assert reviewed.report.model_dump() == chunk_report.model_dump()
    assert reviewed.report.kept_files == ["src/app.py"]
    assert reviewed.report.excluded_reason == {
        "pnpm-lock.yaml": "generated-path",
        "src/large.py": "oversize-file",
    }
    assert generated not in reviewed.text
    assert oversized not in reviewed.text
    assert source in reviewed.text
    assert reviewed.text.startswith("# rvw: 2 files excluded from review diff")
    assert reviewed.text == chunks[0].text


def test_reviewed_diff_equals_the_single_planned_chunk_byte_for_byte() -> None:
    diff = diff_segment("src/a.py", "one") + diff_segment("src/b.py", "two")

    reviewed = reviewed_diff(diff)
    chunks, _report = apply_diff_budget(diff)

    assert len(chunks) == 1
    assert reviewed.text == chunks[0].text == diff


def test_reviewed_diff_concatenates_every_kept_segment_when_discovery_chunks() -> None:
    diff = "".join(diff_segment(f"src/file-{index}.ts", "x" * 146_900) for index in range(5))

    reviewed = reviewed_diff(diff)
    chunks, report = apply_diff_budget(diff)

    assert len(chunks) >= 2
    assert reviewed.report.kept_files == report.kept_files
    assert reviewed.text == "".join(chunk.text for chunk in chunks)
    assert len(reviewed.text) == report.kept_chars


def test_reviewed_diff_states_the_exclusion_header_once_across_chunks() -> None:
    generated = diff_segment("pnpm-lock.yaml", "generated")
    sources = [diff_segment(f"src/file-{index}.ts", "x" * 146_900) for index in range(5)]
    diff = generated + "".join(sources)

    reviewed = reviewed_diff(diff)
    chunks, report = apply_diff_budget(diff)

    header = "# rvw: 1 files excluded from review diff (generated/oversize): pnpm-lock.yaml\n"
    assert len(chunks) >= 2
    assert report.excluded_files == ["pnpm-lock.yaml"]
    assert reviewed.text.count(header) == 1
    assert reviewed.text == header + "".join(sources)
    assert len(reviewed.text) == len(header) + report.kept_chars
    assert generated not in reviewed.text

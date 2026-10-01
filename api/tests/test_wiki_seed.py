import os
from pathlib import Path

import pytest
from app.core import wiki_seed
from app.core.config import Settings


def test_fresh_start_initializes_complete_seed(tmp_path: Path, monkeypatch) -> None:
    seed = tmp_path / "seed.jsonl"
    seed.write_bytes(b'{"title":"Public seed"}\n')
    monkeypatch.setattr(wiki_seed, "SEED_PATH", seed)
    settings = Settings(DATA_DIR=str(tmp_path / "data"), _env_file=None)

    settings.ensure_data_dirs()

    wiki = Path(settings.WIKI_DIR_PATH)
    assert (wiki / "processed_wiki.jsonl").read_bytes() == seed.read_bytes()
    assert not list(wiki.glob(".wiki-seed-*"))


@pytest.mark.parametrize("content", [b"existing runtime knowledge\n", b""])
def test_existing_runtime_cache_is_never_replaced(
    tmp_path: Path, monkeypatch, content: bytes
) -> None:
    target = tmp_path / "processed_wiki.jsonl"
    target.write_bytes(content)
    before = target.stat()
    monkeypatch.setattr(wiki_seed, "SEED_PATH", tmp_path / "absent-seed")

    wiki_seed.initialize_wiki_cache(tmp_path)

    assert target.read_bytes() == content
    assert (target.stat().st_ino, target.stat().st_mtime_ns) == (
        before.st_ino,
        before.st_mtime_ns,
    )


def test_concurrent_runtime_publication_wins(tmp_path: Path, monkeypatch) -> None:
    seed = tmp_path / "seed.jsonl"
    seed.write_bytes(b"public seed\n")
    monkeypatch.setattr(wiki_seed, "SEED_PATH", seed)
    target = tmp_path / "processed_wiki.jsonl"
    link = os.link

    def publish_runtime_first(source, destination):
        assert Path(source).read_bytes() == seed.read_bytes()
        target.write_bytes(b"newer runtime knowledge\n")
        link(source, destination)

    monkeypatch.setattr(wiki_seed.os, "link", publish_runtime_first)

    wiki_seed.initialize_wiki_cache(tmp_path)

    assert target.read_bytes() == b"newer runtime knowledge\n"
    assert not list(tmp_path.glob(".wiki-seed-*"))


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_non_regular_runtime_cache_is_rejected(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "processed_wiki.jsonl"
    if kind == "symlink":
        target.symlink_to(tmp_path / "absent")
    else:
        target.mkdir()

    with pytest.raises(ValueError, match="regular file"):
        wiki_seed.initialize_wiki_cache(tmp_path)


def test_missing_seed_does_not_leave_partial_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wiki_seed, "SEED_PATH", tmp_path / "absent-seed")

    with pytest.raises(FileNotFoundError):
        wiki_seed.initialize_wiki_cache(tmp_path)

    assert not (tmp_path / "processed_wiki.jsonl").exists()
    assert not list(tmp_path.glob(".wiki-seed-*"))


def test_symlinked_wiki_directory_is_rejected(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    wiki = tmp_path / "wiki"
    wiki.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ValueError, match="directory"):
        wiki_seed.initialize_wiki_cache(wiki)

    assert not list(actual.iterdir())

"""Initialize the mutable wiki cache from the versioned public seed once."""

import os
import stat
import tempfile
from pathlib import Path

SEED_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "wiki"
    / "processed_wiki.seed.jsonl"
)


def initialize_wiki_cache(wiki_dir: Path) -> None:
    """Publish a complete seed only when no runtime cache already exists."""
    if wiki_dir.is_symlink():
        raise ValueError("Wiki cache directory must not be a symbolic link")
    target = wiki_dir / "processed_wiki.jsonl"
    try:
        existing = target.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(existing.st_mode):
            raise ValueError("Wiki cache must be a regular file")
        return

    # Publish with an exclusive hard link: concurrent starters cannot overwrite
    # each other, and readers never see a partially copied seed.
    fd, temporary = tempfile.mkstemp(prefix=".wiki-seed-", dir=wiki_dir)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(SEED_PATH.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if not stat.S_ISREG(target.lstat().st_mode):
                raise ValueError("Wiki cache must be a regular file") from None
    finally:
        Path(temporary).unlink()

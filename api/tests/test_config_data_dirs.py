from pathlib import Path

from app.core.config import Settings


def test_ensure_data_dirs_creates_llm_wiki_pages_dir(tmp_path: Path) -> None:
    settings = Settings(DATA_DIR=str(tmp_path), _env_file=None)

    settings.ensure_data_dirs()

    assert Path(settings.LLM_WIKI_DIR_PATH).is_dir()

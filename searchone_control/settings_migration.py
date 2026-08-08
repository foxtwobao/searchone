"""Apply additive SearchOne engine migrations to persisted SearXNG settings."""

from __future__ import annotations

import argparse
import os
import stat
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence

import yaml


def _load_settings(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"设置文件格式无效：{path}")
    return payload


def _engine_list(settings: dict[str, Any], path: Path) -> list[Any]:
    engines = settings.setdefault("engines", [])
    if not isinstance(engines, list):
        raise ValueError(f"设置文件中的 engines 格式无效：{path}")
    return engines


def _write_settings(path: Path, settings: dict[str, Any]) -> None:
    original = path.stat()
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            yaml.safe_dump(
                settings,
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
            temporary_path = Path(handle.name)

        os.chmod(temporary_path, stat.S_IMODE(original.st_mode))
        if hasattr(os, "chown"):
            try:
                os.chown(temporary_path, original.st_uid, original.st_gid)
            except PermissionError:
                pass
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def migrate_engine_settings(target: Path, template: Path, engine_name: str) -> bool:
    """Add one missing SearchOne engine from the image template."""

    target_settings = _load_settings(target)
    target_engines = _engine_list(target_settings, target)
    if any(
        isinstance(item, dict) and item.get("name") == engine_name
        for item in target_engines
    ):
        return False

    template_settings = _load_settings(template)
    template_engines = _engine_list(template_settings, template)
    source_engine = next(
        (
            item
            for item in template_engines
            if isinstance(item, dict) and item.get("name") == engine_name
        ),
        None,
    )
    if source_engine is None:
        raise ValueError(f"镜像设置模板缺少渠道：{engine_name}")

    target_engines.append(deepcopy(source_engine))
    _write_settings(target, target_settings)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--engine", required=True)
    arguments = parser.parse_args(argv)

    if migrate_engine_settings(arguments.target, arguments.template, arguments.engine):
        print(f"已向持久化设置添加渠道：{arguments.engine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

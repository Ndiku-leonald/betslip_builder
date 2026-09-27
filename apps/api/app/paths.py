from pathlib import Path


def project_root(module_file: str | Path) -> Path:
    """Return the repository root locally or the application root in a container."""
    resolved = Path(module_file).resolve()
    start = resolved.parent if resolved.suffix else resolved
    for candidate in (start, *start.parents):
        if (candidate / "render.yaml").is_file() or (candidate / ".git").exists():
            return candidate
    return Path.cwd().resolve()

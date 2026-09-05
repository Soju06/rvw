"""Materialize container-local Codex configuration and execute rvw."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

DEFAULT_TEMPLATE_PATH = Path("/etc/rvw/codex-config.toml")
_RUNTIME_BASE_URL = "CODEX_BASE_URL"
_BUILD_BASE_URL = "RVW_CODEX_DEFAULT_BASE_URL"


def _toml_string(value: str) -> str:
    """Return a TOML-compatible quoted string without shell interpolation."""

    return json.dumps(value, ensure_ascii=False)


def materialize_codex_config(
    *, template_path: Path, home: Path, environ: Mapping[str, str]
) -> Path:
    """Write a secret-free per-user Codex config from the baked template."""

    config_dir = home / ".codex"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_dir.chmod(0o700)
    config_path = config_dir / "config.toml"

    contents = template_path.read_text(encoding="utf-8").rstrip() + "\n"
    base_url = environ.get(_RUNTIME_BASE_URL) or environ.get(_BUILD_BASE_URL)
    if base_url:
        contents += f"base_url = {_toml_string(base_url)}\n"

    descriptor, temporary_name = tempfile.mkstemp(prefix=".config.toml.", dir=config_dir)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as config_file:
            config_file.write(contents)
            config_file.flush()
            os.fsync(config_file.fileno())
        temporary_path.replace(config_path)
        config_path.chmod(0o600)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return config_path


def run_entrypoint(
    argv: Sequence[str],
    *,
    template_path: Path = DEFAULT_TEMPLATE_PATH,
    environ: Mapping[str, str] = os.environ,
    execvp: Callable[[str, list[str]], object] | None = None,
) -> None:
    """Prepare Codex and replace this process with the rvw CLI."""

    home_value = environ.get("HOME")
    home = Path(home_value) if home_value else Path.home()
    try:
        materialize_codex_config(template_path=template_path, home=home, environ=environ)
        rvw_argv = ["rvw", *argv]
        executor = os.execvp if execvp is None else execvp
        executor("rvw", rvw_argv)
    except Exception as exc:
        from rvw.store import finalize_process, initialize_process, redact_diagnostic

        def option(name: str) -> str | None:
            for index, arg in enumerate(argv):
                if arg.startswith(name + "="):
                    return arg[len(name) + 1 :]
                if arg == name and index + 1 < len(argv):
                    return argv[index + 1]
            return None

        if argv and argv[0] in {"run", "auto"}:
            try:
                out = option("--out")
                handle, _ = initialize_process(
                    Path(out) if out else None,
                    target_spec=option("--target") or "unknown",
                    base_ref=option("--base-ref"),
                    head_ref=option("--head-ref"),
                    command=["rvw", *argv],
                )
                process = finalize_process(
                    handle.dir, failure_code="container_setup_failed", failure_detail=str(exc)
                )
                if "--json" in argv:
                    print(process.model_dump_json())
            except OSError as persistence_error:
                print(
                    f"diagnostic persistence failed: {redact_diagnostic(str(persistence_error))}",
                    file=sys.stderr,
                )
        print(f"container setup failed: {redact_diagnostic(str(exc))}", file=sys.stderr)
        raise SystemExit(3) from exc


def main() -> None:
    """Container entry point."""

    run_entrypoint(sys.argv[1:])


if __name__ == "__main__":
    main()

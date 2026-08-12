"""Host-global runtime concurrency slots backed by advisory file locks."""

from __future__ import annotations

import asyncio
import fcntl
import os
import random
import stat
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from pathlib import Path

HOST_CONCURRENCY_ENV = "RVW_HOST_CONCURRENCY"
DEFAULT_HOST_CONCURRENCY = 12


def parse_host_concurrency(value: str | None) -> int:
    """Parse the host cap once at command start."""

    if value is None:
        return DEFAULT_HOST_CONCURRENCY
    try:
        cap = int(value)
    except ValueError as exc:
        raise ValueError(
            f"{HOST_CONCURRENCY_ENV} must be a non-negative integer, got {value!r}"
        ) from exc
    if cap < 0:
        raise ValueError(f"{HOST_CONCURRENCY_ENV} must be a non-negative integer, got {value!r}")
    return cap


def _default_base_dir(environ: Mapping[str, str]) -> tuple[Path, Path | None]:
    xdg_runtime_dir = environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime_dir:
        runtime_dir = Path(xdg_runtime_dir)
        return runtime_dir / "rvw-slots", runtime_dir
    return Path("/tmp/rvw-slots"), None


def _checked_directory(path: Path, *, create: bool, mutate: bool, nofollow: int) -> int:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            raise RuntimeError(f"host slot directory does not exist: {path}") from None
        try:
            with suppress(FileExistsError):
                path.mkdir(mode=0o700)
            info = path.lstat()
        except OSError as exc:
            raise RuntimeError(f"could not create host slot directory {path}: {exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"could not inspect host slot directory {path}: {exc}") from exc

    if stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"host slot directory must not be a symlink: {path}")
    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeError(f"host slot path is not a directory: {path}")
    if info.st_uid != os.getuid():
        raise RuntimeError(
            f"host slot directory is owned by uid {info.st_uid}, expected {os.getuid()}: {path}"
        )

    flags = os.O_RDONLY | os.O_DIRECTORY | nofollow
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"could not securely open host slot directory {path}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if opened.st_uid != os.getuid() or not stat.S_ISDIR(opened.st_mode):
            raise RuntimeError(f"host slot directory changed during validation: {path}")
        if mutate:
            try:
                os.fchmod(descriptor, 0o700)
            except OSError as exc:
                raise RuntimeError(f"could not enforce mode 0700 on {path}: {exc}") from exc
        verified = os.fstat(descriptor)
        if (
            verified.st_uid != os.getuid()
            or not stat.S_ISDIR(verified.st_mode)
            or (mutate and stat.S_IMODE(verified.st_mode) != 0o700)
        ):
            raise RuntimeError(f"host slot directory failed descriptor verification: {path}")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


class HostSlotGate:
    """A cap-sharded set of host-local flock slots."""

    def __init__(
        self,
        cap: int,
        *,
        base_dir: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if cap < 1:
            raise ValueError("host slot cap must be at least 1")
        if not hasattr(os, "O_NOFOLLOW"):
            raise RuntimeError("host slot gate requires os.O_NOFOLLOW support")
        environment = os.environ if environ is None else environ
        default_base, checked_parent = _default_base_dir(environment)
        self.cap = cap
        self._nofollow = os.O_NOFOLLOW
        self.base_dir = default_base if base_dir is None else base_dir
        self.slot_dir = self.base_dir / f"c{cap}"
        self._checked_parent = checked_parent if base_dir is None else None

    def _prepare(self) -> int:
        parent_descriptor: int | None = None
        base_descriptor: int | None = None
        try:
            if self._checked_parent is not None:
                parent_descriptor = _checked_directory(
                    self._checked_parent,
                    create=False,
                    mutate=False,
                    nofollow=self._nofollow,
                )
            base_descriptor = _checked_directory(
                self.base_dir,
                create=True,
                mutate=True,
                nofollow=self._nofollow,
            )
            return _checked_directory(
                self.slot_dir,
                create=True,
                mutate=True,
                nofollow=self._nofollow,
            )
        finally:
            if base_descriptor is not None:
                os.close(base_descriptor)
            if parent_descriptor is not None:
                os.close(parent_descriptor)

    def _open_slot(self, directory_descriptor: int, index: int) -> int:
        name = f"slot-{index:02d}"
        path = self.slot_dir / f"slot-{index:02d}"
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | self._nofollow
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_descriptor)
        except OSError as exc:
            raise RuntimeError(f"could not securely open host slot {path}: {exc}") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise RuntimeError(f"host slot is not a regular file: {path}")
            if info.st_uid != os.getuid():
                raise RuntimeError(
                    f"host slot is owned by uid {info.st_uid}, expected {os.getuid()}: {path}"
                )
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def _try_acquire(self) -> int | None:
        directory_descriptor = self._prepare()
        try:
            start = random.randrange(self.cap)
            for offset in range(self.cap):
                descriptor = self._open_slot(
                    directory_descriptor,
                    (start + offset) % self.cap,
                )
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(descriptor)
                except BaseException:
                    os.close(descriptor)
                    raise
                else:
                    return descriptor
            return None
        finally:
            os.close(directory_descriptor)

    async def _acquire(self) -> int:
        delay = 0.05
        while True:
            descriptor = self._try_acquire()
            if descriptor is not None:
                return descriptor
            lower = min(delay * 0.9, 0.25)
            upper = min(delay * 1.1, 0.25)
            await asyncio.sleep(random.uniform(lower, upper))
            delay = min(delay * 1.5, 0.25)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Acquire one host slot until the context exits."""

        descriptor = await self._acquire()
        try:
            yield
        finally:
            os.close(descriptor)


def host_slot_gate_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    base_dir: Path | None = None,
) -> HostSlotGate | None:
    """Create the command-scoped gate, or return ``None`` when disabled."""

    environment = os.environ if environ is None else environ
    cap = parse_host_concurrency(environment.get(HOST_CONCURRENCY_ENV))
    if cap == 0:
        return None
    return HostSlotGate(cap, base_dir=base_dir, environ=environment)


@asynccontextmanager
async def host_slot(gate: HostSlotGate | None) -> AsyncIterator[None]:
    """Acquire from an optional gate, treating ``None`` as disabled."""

    if gate is None:
        yield
        return
    async with gate.slot():
        yield


__all__ = [
    "DEFAULT_HOST_CONCURRENCY",
    "HOST_CONCURRENCY_ENV",
    "HostSlotGate",
    "host_slot",
    "host_slot_gate_from_env",
    "parse_host_concurrency",
]

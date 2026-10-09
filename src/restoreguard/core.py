"""Operaciones seguras para copias y restauraciones de SQLite."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

MANIFEST_VERSION = 1
CHUNK_SIZE = 1024 * 1024
BACKUP_NAME = re.compile(r".+_\d{8}T\d{12}Z_[0-9a-f]{6}\.sqlite3\.gz$", re.DOTALL)


class RecoveryError(Exception):
    """Error esperado al crear, verificar o restaurar una copia."""


def _sqlite_uri(path: Path, mode: str = "ro") -> str:
    return f"file:{quote(path.resolve().as_posix(), safe='/')}?mode={mode}"


def _integrity_check(path: Path) -> str:
    try:
        connection = sqlite3.connect(_sqlite_uri(path), uri=True)
        try:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RecoveryError(f"No se pudo abrir la base SQLite: {exc}") from exc
    messages = [str(row[0]) for row in rows]
    if messages != ["ok"]:
        raise RecoveryError("La comprobación de integridad falló: " + "; ".join(messages[:5]))
    return "ok"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(archive: Path) -> Path:
    return archive.with_name(archive.name + ".manifest.json")


def _load_manifest(archive: Path) -> dict[str, Any]:
    path = _manifest_path(archive)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RecoveryError(f"No se encontró el manifiesto de la copia: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RecoveryError(f"El manifiesto JSON no es válido: {exc}") from exc
    if not isinstance(data, dict) or data.get("manifest_version") != MANIFEST_VERSION:
        raise RecoveryError("La versión del manifiesto no es compatible.")
    if data.get("artifact") != archive.name:
        raise RecoveryError("El manifiesto no corresponde a este archivo de copia.")
    if not BACKUP_NAME.fullmatch(archive.name):
        raise RecoveryError("El nombre del archivo no corresponde al formato de RestoreGuard.")
    digest = data.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RecoveryError("El manifiesto no contiene un SHA-256 válido.")
    if not isinstance(data.get("created_at"), str) or not data["created_at"]:
        raise RecoveryError("El manifiesto no contiene una fecha de creación válida.")
    for key in ("compressed_size_bytes", "database_size_bytes"):
        if not isinstance(data.get(key), int) or data[key] < 0:
            raise RecoveryError(f"El manifiesto contiene un valor inválido en '{key}'.")
    return data


def _decompress_and_check(archive: Path, destination: Path) -> int:
    try:
        with gzip.open(archive, "rb") as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target, length=CHUNK_SIZE)
            target.flush()
            os.fsync(target.fileno())
    except (OSError, EOFError) as exc:
        raise RecoveryError(f"No se pudo descomprimir la copia: {exc}") from exc
    _integrity_check(destination)
    return destination.stat().st_size


def verify_backup(archive_path: str | Path) -> dict[str, Any]:
    archive = Path(archive_path).expanduser().resolve()
    if not archive.is_file():
        raise RecoveryError(f"No existe el archivo de copia: {archive}")
    manifest = _load_manifest(archive)
    actual_hash = _sha256(archive)
    if actual_hash != manifest["sha256"]:
        raise RecoveryError("El SHA-256 no coincide; el archivo pudo cambiar o dañarse.")
    actual_size = archive.stat().st_size
    if actual_size != manifest.get("compressed_size_bytes"):
        raise RecoveryError("El tamaño del archivo no coincide con el manifiesto.")
    with tempfile.TemporaryDirectory(prefix="restoreguard-verify-") as directory:
        snapshot = Path(directory) / "verified.sqlite3"
        database_size = _decompress_and_check(archive, snapshot)
    if database_size != manifest.get("database_size_bytes"):
        raise RecoveryError("El tamaño de la base restaurada no coincide con el manifiesto.")
    return {
        "status": "verified",
        "backup": str(archive),
        "created_at": manifest["created_at"],
        "sha256": actual_hash,
        "compressed_size_bytes": actual_size,
        "database_size_bytes": database_size,
        "integrity_check": "ok",
    }


def _prune(output_dir: Path, keep_last: int) -> list[str]:
    records: list[tuple[str, Path, Path]] = []
    for manifest_path in output_dir.glob("*.sqlite3.gz.manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact_name = data.get("artifact") if isinstance(data, dict) else None
            if not isinstance(artifact_name, str) or Path(artifact_name).name != artifact_name:
                continue
            archive = output_dir / artifact_name
            if BACKUP_NAME.fullmatch(artifact_name) and archive.is_file():
                validated = _load_manifest(archive)
                records.append((validated["created_at"], archive, manifest_path))
        except (OSError, json.JSONDecodeError, RecoveryError):
            continue
    records.sort(key=lambda row: row[0], reverse=True)
    removed = []
    for _, archive, manifest in records[keep_last:]:
        archive.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        removed.append(archive.name)
    return removed


def create_backup(
    database_path: str | Path,
    output_dir: str | Path,
    keep_last: int = 7,
) -> dict[str, Any]:
    source = Path(database_path).expanduser().resolve()
    destination_dir = Path(output_dir).expanduser().resolve()
    if keep_last < 1:
        raise RecoveryError("La retención debe conservar al menos una copia.")
    if not source.is_file():
        raise RecoveryError(f"No existe la base de datos: {source}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    token = os.urandom(3).hex()
    archive = destination_dir / f"{source.stem}_{stamp}_{token}.sqlite3.gz"

    snapshot_fd, snapshot_name = tempfile.mkstemp(prefix=".restoreguard-", suffix=".sqlite3", dir=destination_dir)
    os.close(snapshot_fd)
    snapshot = Path(snapshot_name)
    compressed_fd, compressed_name = tempfile.mkstemp(prefix=".restoreguard-", suffix=".gz", dir=destination_dir)
    os.close(compressed_fd)
    compressed_temp = Path(compressed_name)
    published_manifest: Path | None = None
    try:
        try:
            source_db = sqlite3.connect(_sqlite_uri(source), uri=True)
            target_db = None
            try:
                target_db = sqlite3.connect(snapshot)
                source_db.backup(target_db)
            finally:
                if target_db is not None:
                    target_db.close()
                source_db.close()
        except sqlite3.Error as exc:
            raise RecoveryError(f"No se pudo crear la copia consistente de SQLite: {exc}") from exc
        _integrity_check(snapshot)
        database_size = snapshot.stat().st_size
        with snapshot.open("rb") as source_stream, gzip.open(compressed_temp, "wb", compresslevel=6) as compressed_stream:
            shutil.copyfileobj(source_stream, compressed_stream, length=CHUNK_SIZE)
        compressed_size = compressed_temp.stat().st_size
        digest = _sha256(compressed_temp)
        os.replace(compressed_temp, archive)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "artifact": archive.name,
            "source_name": source.name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "sha256": digest,
            "compressed_size_bytes": compressed_size,
            "database_size_bytes": database_size,
            "backup_duration_ms": elapsed_ms,
            "integrity_check": "ok",
        }
        manifest_path = _manifest_path(archive)
        manifest_fd, manifest_name = tempfile.mkstemp(prefix=".restoreguard-", suffix=".json", dir=destination_dir)
        try:
            with os.fdopen(manifest_fd, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(manifest_name, manifest_path)
            published_manifest = manifest_path
        except Exception:
            Path(manifest_name).unlink(missing_ok=True)
            raise
        removed = _prune(destination_dir, keep_last)
        return {
            "status": "created",
            "backup": str(archive),
            "manifest": str(manifest_path),
            "sha256": digest,
            "compressed_size_bytes": compressed_size,
            "database_size_bytes": database_size,
            "backup_duration_ms": elapsed_ms,
            "integrity_check": "ok",
            "removed_by_retention": removed,
        }
    except Exception:
        archive.unlink(missing_ok=True)
        if published_manifest:
            published_manifest.unlink(missing_ok=True)
        raise
    finally:
        snapshot.unlink(missing_ok=True)
        compressed_temp.unlink(missing_ok=True)


def restore_backup(
    archive_path: str | Path,
    destination_path: str | Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    archive = Path(archive_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    if destination in {archive, _manifest_path(archive)}:
        raise RecoveryError("El destino no puede sobrescribir el archivo de copia o su manifiesto.")
    if destination.exists() and not overwrite:
        raise RecoveryError(f"El destino ya existe; usa --overwrite para reemplazarlo: {destination}")
    verification = verify_backup(archive)
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".restoreguard-tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        database_size = _decompress_and_check(archive, temporary)
        if destination.exists() and not overwrite:
            raise RecoveryError(f"El destino ya existe; usa --overwrite para reemplazarlo: {destination}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "status": "restored",
        "backup": str(archive),
        "destination": str(destination),
        "sha256": verification["sha256"],
        "database_size_bytes": database_size,
        "integrity_check": "ok",
        "restore_duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def list_backups(output_dir: str | Path) -> list[dict[str, Any]]:
    directory = Path(output_dir).expanduser().resolve()
    if not directory.is_dir():
        raise RecoveryError(f"No existe la carpeta de copias: {directory}")
    entries = []
    for manifest_path in directory.glob("*.sqlite3.gz.manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifact = manifest.get("artifact") if isinstance(manifest, dict) else None
            if not isinstance(artifact, str) or Path(artifact).name != artifact:
                continue
            archive = directory / artifact
            if BACKUP_NAME.fullmatch(artifact) and archive.is_file():
                manifest = _load_manifest(archive)
                entries.append({
                    "backup": str(archive),
                    "created_at": manifest.get("created_at"),
                    "compressed_size_bytes": manifest.get("compressed_size_bytes"),
                    "sha256": manifest.get("sha256"),
                })
        except (OSError, json.JSONDecodeError, RecoveryError):
            continue
    return sorted(entries, key=lambda entry: entry.get("created_at") or "", reverse=True)

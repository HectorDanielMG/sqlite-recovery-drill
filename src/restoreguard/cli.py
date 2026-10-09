"""Interfaz de línea de comandos de RestoreGuard."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .core import RecoveryError, create_backup, list_backups, restore_backup, verify_backup


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("debe ser un número entero") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("debe ser al menos 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="restoreguard",
        description="Crea, verifica y restaura copias SQLite con manifiestos SHA-256.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="crear una copia consistente y verificada")
    backup.add_argument("database", type=Path, help="ruta de la base SQLite de origen")
    backup.add_argument("--output", type=Path, default=Path("backups"), help="carpeta de salida (por defecto: ./backups)")
    backup.add_argument("--keep-last", type=_positive_integer, default=7, help="copias que se conservan (por defecto: 7)")

    verify = commands.add_parser("verify", help="validar checksum e integridad de una copia")
    verify.add_argument("backup", type=Path, help="archivo .sqlite3.gz")

    restore = commands.add_parser("restore", help="ensayar la restauración en una ruta de destino")
    restore.add_argument("backup", type=Path, help="archivo .sqlite3.gz previamente verificado")
    restore.add_argument("destination", type=Path, help="archivo SQLite que se va a crear")
    restore.add_argument("--overwrite", action="store_true", help="reemplazar el destino si ya existe")

    listing = commands.add_parser("list", help="listar copias con manifiesto")
    listing.add_argument("--directory", type=Path, default=Path("backups"), help="carpeta de copias (por defecto: ./backups)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            result = create_backup(args.database, args.output, args.keep_last)
        elif args.command == "verify":
            result = verify_backup(args.backup)
        elif args.command == "restore":
            result = restore_backup(args.backup, args.destination, args.overwrite)
        else:
            result = {"backups": list_backups(args.directory)}
    except RecoveryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

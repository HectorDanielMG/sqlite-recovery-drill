"""Crea una base SQLite pequeña con datos sintéticos para probar RestoreGuard."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("demo/orders.sqlite3"))
    args = parser.parse_args()
    destination = args.output.expanduser().resolve()
    if destination.exists():
        parser.error(f"el archivo ya existe; elige otra ruta: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destination) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            product TEXT NOT NULL,
            units INTEGER NOT NULL CHECK (units > 0)
        )""")
        connection.executemany(
            "INSERT INTO orders(product, units) VALUES (?, ?)",
            [("teclado", 2), ("monitor", 1), ("mouse", 3)],
        )
    print(f"Base de demostración creada: {destination}")


if __name__ == "__main__":
    main()

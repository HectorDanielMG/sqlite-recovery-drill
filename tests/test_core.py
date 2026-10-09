from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from restoreguard.core import RecoveryError, create_backup, restore_backup, verify_backup


class RecoveryDrillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "orders.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, item TEXT NOT NULL)")
            connection.execute("INSERT INTO orders(item) VALUES (?)", ("teclado",))
        self.backups = self.root / "backups"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_backup_verifies_and_restores_a_consistent_snapshot(self) -> None:
        created = create_backup(self.database, self.backups)
        with sqlite3.connect(self.database) as connection:
            connection.execute("INSERT INTO orders(item) VALUES (?)", ("monitor",))

        verified = verify_backup(created["backup"])
        restored_path = self.root / "restore" / "orders.sqlite3"
        restored = restore_backup(created["backup"], restored_path)

        self.assertEqual(verified["integrity_check"], "ok")
        self.assertEqual(restored["integrity_check"], "ok")
        self.assertGreaterEqual(restored["restore_duration_ms"], 0)
        with sqlite3.connect(restored_path) as connection:
            names = connection.execute("SELECT item FROM orders ORDER BY id").fetchall()
        self.assertEqual(names, [("teclado",)])

    def test_backup_includes_committed_wal_transactions(self) -> None:
        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO orders(item) VALUES (?)", ("audifonos",))
        connection.commit()
        try:
            created = create_backup(self.database, self.backups)
        finally:
            connection.close()

        restored_path = self.root / "wal-restore.sqlite3"
        restore_backup(created["backup"], restored_path)
        with sqlite3.connect(restored_path) as restored:
            count = restored.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(count, 2)

    def test_verification_rejects_a_changed_archive(self) -> None:
        created = create_backup(self.database, self.backups)
        archive = Path(created["backup"])
        archive.write_bytes(archive.read_bytes() + b"alterado")

        with self.assertRaisesRegex(RecoveryError, "SHA-256"):
            verify_backup(archive)

    def test_restore_refuses_to_replace_an_existing_file_by_default(self) -> None:
        created = create_backup(self.database, self.backups)
        destination = self.root / "existing.sqlite3"
        destination.write_bytes(b"preservar")

        with self.assertRaisesRegex(RecoveryError, "ya existe"):
            restore_backup(created["backup"], destination)
        self.assertEqual(destination.read_bytes(), b"preservar")

    def test_restore_can_explicitly_replace_an_existing_database(self) -> None:
        created = create_backup(self.database, self.backups)
        destination = self.root / "existing.sqlite3"
        destination.write_bytes(b"archivo anterior")

        restore_backup(created["backup"], destination, overwrite=True)
        with sqlite3.connect(destination) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_retention_keeps_only_the_requested_number_of_backups(self) -> None:
        created = [create_backup(self.database, self.backups, keep_last=2) for _ in range(3)]

        remaining = list(self.backups.glob("*.sqlite3.gz"))
        self.assertEqual(len(remaining), 2)
        self.assertEqual(len(list(self.backups.glob("*.manifest.json"))), 2)
        self.assertIn(Path(created[-1]["backup"]), remaining)


if __name__ == "__main__":
    unittest.main()

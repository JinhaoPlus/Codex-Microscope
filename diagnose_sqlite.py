"""Probe read-only WAL compatibility using only a temporary synthetic database."""
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


def probe():
    with tempfile.TemporaryDirectory(prefix='microscope-sqlite-') as directory:
        path = Path(directory) / 'sample.sqlite'
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('pragma journal_mode=wal')
            connection.execute('create table sample(value)')
            connection.execute('insert into sample values(42)')
            connection.commit()
            connection.execute('pragma wal_checkpoint(truncate)').fetchall()
        # Only our closed, checkpointed synthetic database is touched.
        for suffix in ('-wal', '-shm'):
            Path(str(path) + suffix).unlink(missing_ok=True)
        result = {'python': sys.executable, 'sqlite': sqlite3.sqlite_version}
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
                result['readable_without_sidecars'] = connection.execute('select value from sample').fetchone()[0] == 42
        except sqlite3.Error as error:
            result.update(readable_without_sidecars=False, error=str(error))
        result['created_sidecars'] = [suffix for suffix in ('-wal', '-shm') if Path(str(path) + suffix).exists()]
        return result


if __name__ == '__main__':
    print(json.dumps(probe(), ensure_ascii=False, indent=2))

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server

class DatabaseReads(unittest.TestCase):
 def test_transient_open_failure_retries_and_closes(self):
  with tempfile.TemporaryDirectory() as d:
   # Special URI characters must not change which database is opened.
   path=Path(d)/'state #1?.sqlite'
   c=sqlite3.connect(path);c.execute('create table sample(value)');c.execute('insert into sample values(42)');c.commit();c.close()
   connections=[]
   class TrackedConnection(sqlite3.Connection):
    closed=False
    def close(self):self.closed=True;super().close()
   connect=sqlite3.connect
   def create(*args,**kwargs):
    c=connect(*args,factory=TrackedConnection,**kwargs);connections.append(c);return c
   with patch.object(server.sqlite3,'connect',side_effect=[sqlite3.OperationalError('unable to open database file'),create(path)]) as mock,patch.object(server.time,'sleep'):
    self.assertEqual(server.read_sql(path,'select value from sample')[0][0],42)
    self.assertEqual(mock.call_count,2)
   self.assertTrue(all(c.closed for c in connections))
   self.assertEqual(server.read_sql(path,'select value from sample')[0][0],42)
   with self.assertRaises(sqlite3.OperationalError):server.read_sql(path,'insert into sample values(43)')
 def test_missing_database_is_not_created_and_retries_are_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'missing.sqlite'
   with patch.object(server.time,'sleep') as sleep,patch.object(server,'print'):
    with self.assertRaises(server.DatabaseUnavailable):server.read_sql(path,'select 1')
    self.assertEqual(sleep.call_count,2)
   self.assertFalse(path.exists())

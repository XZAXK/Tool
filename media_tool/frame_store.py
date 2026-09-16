"""Persistence for selected frames and last playback position only."""
import hashlib
import sqlite3
from pathlib import Path


def fingerprint(path):
    digest = hashlib.sha256()
    with open(str(path), 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class FrameStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY, path TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS marks (
                video TEXT NOT NULL, frame INTEGER NOT NULL, PRIMARY KEY(video, frame));
        ''')
        self.db.commit()

    def register(self, key, path):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO videos(id,path) VALUES (?,?)', (key, path))
            self.db.execute('UPDATE videos SET path=? WHERE id=?', (path, key))

    def videos(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM videos ORDER BY rowid')]

    def set_mark(self, key, index, selected):
        with self.db:
            if selected:
                self.db.execute('INSERT OR IGNORE INTO marks(video,frame) VALUES (?,?)', (key, index))
            else:
                self.db.execute('DELETE FROM marks WHERE video=? AND frame=?', (key, index))

    def marked(self, key):
        return [r[0] for r in self.db.execute('SELECT frame FROM marks WHERE video=? ORDER BY frame', (key,))]

    def set_position(self, key, index):
        with self.db:
            self.db.execute('UPDATE videos SET position=? WHERE id=?', (index, key))

    def position(self, key):
        row = self.db.execute('SELECT position FROM videos WHERE id=?', (key,)).fetchone()
        return row[0] if row else 0

    def close(self):
        self.db.close()

"""Read-only rollout IO; optional zstd support, bounded versioned parse cache."""
import io
import shutil
import subprocess
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path

MAGIC = b'\x28\xb5\x2f\xfd'
CACHE = OrderedDict()
LOCK = threading.RLock()

def resolve_rollout(path):
    path = Path(path)
    if path.is_file():
        return path
    compressed = Path(str(path) + '.zst')
    return compressed if compressed.is_file() else path

@contextmanager
def open_rollout(path):
    path = resolve_rollout(path)
    with path.open('rb') as f:
        compressed = f.read(4) == MAGIC
    if not compressed:
        with path.open(encoding='utf-8') as f:
            yield f
        return
    try:
        from compression import zstd
    except ImportError:
        zstd = None
    if zstd:
        try:
            with zstd.open(path, 'rt', encoding='utf-8') as f:
                yield f
        except zstd.ZstdError as error:
            raise ValueError('zstd 会话解压失败，文件可能损坏。') from error
        return
    # LaunchAgents may have a minimal PATH. No shell or user supplied command.
    executable = shutil.which('zstd')
    if not executable:
        executable = next((p for p in ('/opt/homebrew/bin/zstd', '/usr/local/bin/zstd') if Path(p).is_file()), None)
    if not executable:
        raise RuntimeError('该会话已压缩：需要 Python 3.14+ 或安装 zstd 后重试。')
    proc = subprocess.Popen([executable, '-dc', '--', str(path)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        completed = [False]
        with io.TextIOWrapper(proc.stdout, encoding='utf-8') as f:
            def lines():
                yield from f
                completed[0] = True
            yield lines()
        if completed[0] and proc.wait() != 0:
            raise ValueError('zstd 会话解压失败，文件可能损坏。')
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait()

def stamp(path):
    p = resolve_rollout(path)
    try:
        s = p.stat()
        return (str(p), s.st_mtime_ns, s.st_size, s.st_ino)
    except FileNotFoundError:
        return (str(p), 0, 0, 0)

def cached_history(path, parse):
    key = stamp(path)
    with LOCK:
        if key in CACHE:
            CACHE.move_to_end(key)
            return CACHE[key]
        result = parse(resolve_rollout(path))
        # Never cache an unstable read while Codex is still appending.
        if stamp(path) == key:
            for old in list(CACHE):
                if old[0] == key[0]:
                    del CACHE[old]
            CACHE[key] = result
            while len(CACHE) > 3:
                CACHE.popitem(last=False)
        return result

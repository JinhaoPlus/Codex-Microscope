"""Install a per-user macOS LaunchAgent for this checkout."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = 'local.codex-session-browser'

def main():
    if sys.platform != 'darwin':
        raise SystemExit('此安装器仅用于 macOS；其他系统请运行 python3 server.py。')
    root = Path(__file__).resolve().parent
    agents = Path.home() / 'Library/LaunchAgents'
    logs = Path.home() / 'Library/Logs/CodexSessionBrowser'
    agents.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    target = agents / (LABEL + '.plist')
    domain = f'gui/{os.getuid()}'
    config = {
        'Label': LABEL,
        'ProgramArguments': [sys.executable, '-u', str(root / 'server.py'), '--port', '4318'],
        'WorkingDirectory': str(root),
        'EnvironmentVariables': {'CODEX_HOME': str(Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')).expanduser().resolve())},
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 10,
        'StandardOutPath': str(logs / 'stdout.log'),
        'StandardErrorPath': str(logs / 'stderr.log'),
    }
    if target.exists():
        subprocess.run(['launchctl', 'bootout', domain, str(target)], check=False, capture_output=True)
    target.write_bytes(plistlib.dumps(config))
    subprocess.run(['launchctl', 'bootstrap', domain, str(target)], check=True)
    print(f'已安装 {target}\n打开 http://localhost:4318；日志：{logs}')

if __name__ == '__main__':
    main()

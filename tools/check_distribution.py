"""Read-only audit of an extracted SHERIF distribution directory.

Run against a staging directory, never against the development source tree.
This is a check, not a packager or proof of secrecy.
"""
import argparse
import hashlib
import os
from pathlib import Path

SOURCE_SUFFIXES = {'.py', '.pyw', '.pyc', '.pyo'}
DATABASE_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.db-wal', '.db-shm'}
SENSITIVE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx'}
FORBIDDEN_DIRS = {'local_server', '_temp_tests', '__pycache__', '.git', '.env'}
FORBIDDEN_FILES = {'server_url.txt', 'sherif_connection.json'}
# The reviewed upstream certifi bundle, pinned to its exact SHA-256.
TRUSTED_CA_BUNDLES = {'_internal/certifi/cacert.pem': '9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f'}


def inspect(root):
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Expected an extracted distribution directory')
    findings = []
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        for name in list(dirs):
            path = base / name
            if path.is_symlink():
                findings.append((str(path.relative_to(root)), 'link'))
                dirs.remove(name)
            elif name.casefold() in FORBIDDEN_DIRS:
                findings.append((str(path.relative_to(root)), 'forbidden directory'))
                dirs.remove(name)
        for name in files:
            path = base / name
            low = name.casefold()
            relative = str(path.relative_to(root))
            if path.is_symlink():
                findings.append((relative, 'link'))
            elif low in FORBIDDEN_FILES:
                findings.append((relative, 'preconfigured server connection'))
            elif low.endswith(tuple(SOURCE_SUFFIXES)):
                findings.append((relative, 'Python source or bytecode'))
            elif low.endswith(tuple(DATABASE_SUFFIXES)):
                findings.append((relative, 'database'))
            elif low.endswith(tuple(SENSITIVE_SUFFIXES)) or low in {'.env', 'config.env', 'credentials.json'}:
                expected = TRUSTED_CA_BUNDLES.get(path.relative_to(root).as_posix().casefold())
                if not expected or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    findings.append((relative, 'sensitive file'))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    findings = inspect(args.directory)
    for path, kind in findings:
        print(f'{kind}: {path}')
    print(f'findings: {len(findings)}')
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
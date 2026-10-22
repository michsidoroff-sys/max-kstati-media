"""Limit the manual workflow to ordinary repository content, never credentials."""
import os
from pathlib import Path


def checked_file(root, raw, suffixes):
    root=Path(root).resolve();path=Path(raw)
    if path.is_absolute() or any(part.startswith('.') for part in path.parts):
        raise ValueError('Expected an ordinary relative repository file')
    resolved=(root/path).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.suffix.lower() not in suffixes:
        raise ValueError('File must remain in the repository and have an allowed media/text extension')
    return resolved


if __name__=='__main__':
    checked_file(Path.cwd(),os.environ['TEXT_FILE'],{'.txt','.md'})
    if os.environ.get('IMAGE_PATH'):
        checked_file(Path.cwd(),os.environ['IMAGE_PATH'],{'.jpg','.jpeg','.png'})

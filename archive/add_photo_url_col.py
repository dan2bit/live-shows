#!/usr/bin/env python3
"""Add Photo URL column after Playlist URL in all history TSV files."""
import os, glob

def add_photo_col(filepath):
    with open(filepath, encoding='utf-8') as f:
        content = f.read()
    lines = content.strip().split('\n')
    headers = lines[0].split('\t')
    if 'Photo URL' in headers:
        print(f"  {filepath}: already has Photo URL")
        return
    pos = headers.index('Playlist URL') + 1
    new_headers = headers[:pos] + ['Photo URL'] + headers[pos:]
    N = len(new_headers)
    fixed = ['\t'.join(new_headers)]
    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split('\t')
        while len(cols) < len(headers):
            cols.append('-')
        new_cols = cols[:pos] + ['-'] + cols[pos:]
        fixed.append('\t'.join(new_cols))
    result = '\n'.join(fixed) + '\n'
    errors = [i for i,l in enumerate(result.strip().split('\n')[1:],1) if len(l.split('\t')) != N]
    if errors:
        print(f"  {filepath}: {len(errors)} column errors — NOT written")
        return
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(result)
    print(f"  {filepath}: {len(fixed)-1} rows, {N} cols. OK")

for path in sorted(glob.glob('history/*.tsv')):
    if path.endswith('.gitkeep'):
        continue
    add_photo_col(path)

# Also process live_shows_current.tsv
add_photo_col('live_shows_current.tsv')
print("Done. Commit all changed files to main.")

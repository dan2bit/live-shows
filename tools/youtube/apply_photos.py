#!/usr/bin/env python3
"""Apply photo URLs from photo_map.json to all history TSV files and live_shows_current.tsv.
Run from the root of the live-shows repo after placing photo_map.json in the same directory.
"""
import json, glob, os, sys

with open('archive/photo_map.json') as f:
    photo_map = json.load(f)

def apply_photos(path, date_col='Show Date', photo_col='Photo URL'):
    with open(path, encoding='utf-8') as f:
        content = f.read()
    lines = content.strip().split('\n')
    headers = lines[0].split('\t')
    if photo_col not in headers:
        print(f"  SKIP {path}: no {photo_col} column")
        return 0
    pi = headers.index(photo_col)
    di = headers.index(date_col)
    fixed = [lines[0]]
    matched = 0
    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split('\t')
        while len(cols) < len(headers):
            cols.append('')
        date = cols[di].strip()
        if date in photo_map and cols[pi] in ('-', ''):
            cols[pi] = photo_map[date]
            matched += 1
        fixed.append('\t'.join(cols))
    result = '\n'.join(fixed) + '\n'
    # Verify column counts
    N = len(headers)
    errors = [i for i,l in enumerate(result.strip().split('\n')[1:],1) if len(l.split('\t'))!=N]
    if errors:
        print(f"  ERROR {path}: {len(errors)} rows with wrong column count — NOT written")
        return 0
    with open(path, 'w', encoding='utf-8') as f:
        f.write(result)
    print(f"  {path}: {matched} photo URLs applied")
    return matched

total = 0
for path in sorted(glob.glob('history/*.tsv')):
    total += apply_photos(path)
total += apply_photos('live_shows_current.tsv')
print(f"\nTotal: {total} photo URLs applied across all files")
print("Commit all modified files to main via GitHub Desktop.")

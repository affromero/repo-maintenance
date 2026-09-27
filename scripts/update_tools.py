"""Select stable scanner releases that have been available for seven days."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import urllib.request


def newest_stable(versions, now):
    eligible = []
    for release in versions:
        version = release['num']
        if release['yanked'] or not re.fullmatch(r'\d+\.\d+\.\d+', version):
            continue
        published = datetime.fromisoformat(release['created_at'].replace('Z', '+00:00'))
        if published <= now - timedelta(days=7):
            eligible.append(version)
    if not eligible:
        raise RuntimeError('No eligible cargo-machete release')
    return max(eligible, key=lambda value: tuple(map(int, value.split('.'))))


def main():
    request = urllib.request.Request(
        'https://crates.io/api/v1/crates/cargo-machete',
        headers={'User-Agent': 'affromero/repo-maintenance tool updater'},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        releases = json.load(response)['versions']
    path = Path(__file__).resolve().parents[1] / 'tool-versions.json'
    current = json.loads(path.read_text())
    latest = newest_stable(releases, datetime.now(timezone.utc))
    if tuple(map(int, latest.split('.'))) > tuple(map(int, current['cargo-machete'].split('.'))):
        current['cargo-machete'] = latest
        path.write_text(json.dumps(current, indent=2) + '\n')


if __name__ == '__main__':
    main()

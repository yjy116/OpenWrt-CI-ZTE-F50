"""Minimal checked patch of the fixed upstream updater's repository and keep list."""
import re

from archive_checks import clean_name, require

REPOSITORY_LINE = 'REPO=${MU300_REPO:-dikeckaan/mu300-linux}'
KEEP_LINE = 'openwrt) echo "etc/config etc/mu300 etc/dropbear etc/rc.local root" ;;'


def make_updater(source, options):
    repository = options['repository']
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository), 'Invalid release repository')
    paths = options['paths']
    require(len(paths) == len(set(paths)), 'Duplicate persistent path')
    for path in paths:
        require(clean_name(path) == path and re.fullmatch(r'[A-Za-z0-9_./-]+', path), 'Invalid persistent path')
        require(path.startswith(('etc/', 'var/lib/')), 'Unexpected persistent data location')
    require(source.count(REPOSITORY_LINE) == 1 and source.count(KEEP_LINE) == 1,
            'Fixed upstream updater patch context changed')
    updated = source.replace(REPOSITORY_LINE, 'REPO=${MU300_REPO:-' + repository + '}')
    return updated.replace(KEEP_LINE, KEEP_LINE.replace(' root"', ' root ' + ' '.join(paths) + '"'))

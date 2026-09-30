"""Stage and verify only the two reviewed F50 temperature UI files."""
import hashlib
import shutil
import tarfile

from archive_checks import require
from inputs import sha256

OVERLAY_FILES = (
    'www/luci-static/resources/view/status/include/15_f50_thermal.js',
    'usr/share/rpcd/acl.d/luci-f50-thermal.json',
)
OVERLAY_MODE = 0o644


def stage_overlay(source, destination):
    actual = {path.relative_to(source).as_posix() for path in source.rglob('*') if path.is_file()}
    require(actual == set(OVERLAY_FILES), 'Overlay must contain exactly the two reviewed temperature files')
    records = {}
    for name in OVERLAY_FILES:
        original = source / name
        require(original.is_file() and not original.is_symlink(), 'Overlay requires regular source files')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        target.chmod(OVERLAY_MODE)
        records[name] = {'sha256': sha256(original), 'size': original.stat().st_size, 'mode': OVERLAY_MODE}
    return records


def audit_overlay(rootfs, expected):
    require(set(expected) == set(OVERLAY_FILES), 'Unexpected overlay audit manifest')
    with tarfile.open(rootfs, 'r:gz') as archive:
        for name, record in expected.items():
            member = archive.getmember('./' + name)
            require(member.isfile() and member.size == record['size'], 'Overlay file differs: ' + name)
            require(member.mode & 0o777 == OVERLAY_MODE and member.uid == member.gid == 0,
                    'Unexpected overlay ownership or permissions: ' + name)
            digest = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
            require(digest == record['sha256'], 'Overlay source and image SHA256 differ: ' + name)
    return {'files': expected, 'source_bytes_preserved': True}

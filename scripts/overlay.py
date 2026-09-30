"""Stage and verify explicitly reviewed F50 UI and hardware helper files."""
import hashlib
import shutil
import tarfile

from archive_checks import require
from inputs import sha256

OVERLAY_FILES = {
    'www/luci-static/resources/view/status/include/15_f50_thermal.js': 0o644,
    'usr/share/rpcd/acl.d/luci-f50-thermal.json': 0o644,
    'opt/mu300/bin/mu300-led': 0o755,
}


def stage_overlay(source, destination):
    actual = {path.relative_to(source).as_posix() for path in source.rglob('*') if path.is_file()}
    require(actual == set(OVERLAY_FILES), 'Overlay must contain exactly the reviewed F50 files')
    records = {}
    for name, mode in OVERLAY_FILES.items():
        original = source / name
        require(original.is_file() and not original.is_symlink(), 'Overlay requires regular source files')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        target.chmod(mode)
        records[name] = {'sha256': sha256(original), 'size': original.stat().st_size, 'mode': mode}
    return records


def audit_overlay(rootfs, expected):
    require(set(expected) == set(OVERLAY_FILES), 'Unexpected overlay audit manifest')
    with tarfile.open(rootfs, 'r:gz') as archive:
        for name, record in expected.items():
            require(record['mode'] == OVERLAY_FILES[name], 'Unexpected overlay manifest mode: ' + name)
            member = archive.getmember('./' + name)
            require(member.isfile() and member.size == record['size'], 'Overlay file differs: ' + name)
            require(member.mode & 0o7777 == record['mode'] and member.uid == member.gid == 0,
                    'Unexpected overlay ownership or permissions: ' + name)
            digest = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
            require(digest == record['sha256'], 'Overlay source and image SHA256 differ: ' + name)
    return {'files': expected, 'source_bytes_preserved': True}

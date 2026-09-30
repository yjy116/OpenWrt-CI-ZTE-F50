"""Stage individually signed packages and signed official repositories separately."""
import json
from pathlib import Path
import tarfile

from archive_checks import clean_name, require
from inputs import obtain, validate_package_lock, verify_blob


def collect_key(spec, context):
    if 'base_member' not in spec:
        path = obtain(spec, context)
    else:
        path = context['directory'] / spec['name']
        path.parent.mkdir(parents=True, exist_ok=True)
        member = clean_name(spec['base_member'])
        with tarfile.open(context['base_rootfs'], 'r:gz') as archive:
            original = archive.getmember('./' + member)
            require(original.isfile(), 'Public key must be a regular base rootfs file')
            path.write_bytes(archive.extractfile(original).read())
        verify_blob(path, spec)
    key = path.read_bytes()
    require(b'PUBLIC KEY-----' in key and b'PRIVATE KEY' not in key, 'Invalid APK public key')


def collect_packages(options, workspace, base_rootfs):
    lock = json.loads(options.package_lock.read_text(encoding='utf-8'))
    validate_package_lock(lock)
    inputs = workspace / 'container-inputs'
    context = dict(cache=workspace / 'cache', local=options.local_packages)
    for spec in lock['packages']:
        directory = inputs / 'apks'
        if 'feed' in spec:
            directory = inputs / 'repositories' / spec['feed']
        obtain(spec, dict(context, directory=directory))
    for spec in lock.get('indexes', []):
        directory = inputs / 'repositories' / spec['feed']
        path = obtain(spec, dict(context, directory=directory))
        path.rename(directory / 'packages.adb')
    for spec in lock['keys']:
        collect_key(spec, dict(context, directory=inputs / 'keys', base_rootfs=base_rootfs))
    repositories = ['/in/repositories/' + item['feed'] + '/packages.adb' for item in lock.get('indexes', [])]
    (inputs / 'repositories.list').write_text('\n'.join(repositories) + '\n', encoding='ascii')
    official = [item['package'] + '=' + item['version'] for item in lock['packages'] if 'feed' in item]
    (inputs / 'official-packages.txt').write_text('\n'.join(official) + '\n', encoding='ascii')
    return lock, inputs

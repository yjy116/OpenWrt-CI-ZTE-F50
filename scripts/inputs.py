"""Fetch and verify exact public blobs, including successful pinned Actions runs."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

from archive_checks import clean_name, require

CHUNK_SIZE = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60


def sha256(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256')
    return digest.hexdigest()


def run(arguments, options=None):
    settings = options or {}
    result = subprocess.run([str(value) for value in arguments], check=False,
                            text=True, capture_output=True, **settings)
    require(result.returncode == 0, f'Command failed ({result.returncode}): {arguments[0]}\n'
            f'{result.stdout}\n{result.stderr}')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    return result.stdout.strip()


def validate_blob(spec):
    require(clean_name(spec['name']) == spec['name'] and '/' not in spec['name'], 'Blob name must be a basename')
    require(re.fullmatch(r'[0-9a-f]{64}', spec['sha256']), 'Invalid pinned SHA256')
    require(type(spec['size']) is int and spec['size'] > 0, 'Missing positive pinned size')


def verify_blob(path, spec):
    validate_blob(spec)
    require(path.is_file() and path.stat().st_size == spec['size'], 'Input size mismatch: ' + spec['name'])
    require(sha256(path) == spec['sha256'], 'Input SHA256 mismatch: ' + spec['name'])


def artifact_directory(source, cache):
    repo = source['repository']
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'Invalid source repository')
    require(type(source['run_id']) is int, 'Invalid Actions run id')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+', source['artifact']), 'Invalid artifact name')
    destination = cache / (repo.replace('/', '--') + '-' + str(source['run_id']) + '-' + source['artifact'])
    if destination.exists():
        return destination
    details = json.loads(run(['gh', 'api', f"repos/{repo}/actions/runs/{source['run_id']}"]))
    require(details['head_sha'] == source['head_sha'] and details['conclusion'] == 'success',
            'Actions source commit or successful-run proof mismatch')
    destination.mkdir(parents=True)
    run(['gh', 'run', 'download', source['run_id'], '--repo', repo,
         '--name', source['artifact'], '--dir', destination])
    return destination


def download_blob(spec, context):
    source = spec['source']
    destination = context['destination']
    if 'url' in source:
        url = urllib.parse.urlsplit(source['url'])
        require(url.scheme == 'https' and not url.username and not url.password and not url.query,
                'Inputs must use public HTTPS URLs without credential/query parameters')
        with urllib.request.urlopen(source['url'], timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            require(response.url.startswith('https://'), 'Insecure source redirect')
            with destination.open('wb') as output:
                shutil.copyfileobj(response, output, CHUNK_SIZE)
        return
    directory = artifact_directory(source, context['cache'])
    member = clean_name(source['member'])
    path = directory / member
    require(path.resolve().is_relative_to(directory.resolve()), 'Escaping artifact member')
    shutil.copyfile(path, destination)


def obtain(spec, context):
    validate_blob(spec)
    destination = context['directory'] / spec['name']
    destination.parent.mkdir(parents=True, exist_ok=True)
    local = context.get('local')
    if local is not None:
        source = local / spec['name']
        verify_blob(source, spec)
        shutil.copyfile(source, destination)
    else:
        download_blob(spec, dict(destination=destination, cache=context['cache']))
    verify_blob(destination, spec)
    return destination


def validate_package_lock(lock):
    require(lock.get('complete') is True, 'Final installed-package lock is incomplete; finalize it before assembly')
    packages = lock['packages']
    names = [item['package'] for item in packages]
    require(len(names) == len(set(names)), 'Duplicate requested package')
    require(set(lock['required_packages']) <= set(names), 'Required F50 plugins missing from lock')
    require(not set(names) & set(lock['excluded_packages']), 'Explicitly excluded package in lock')
    require(not any(name.startswith('kmod-') or name == 'kernel' for name in names), 'Foreign kernel APK in package lock')
    require(lock['keys'], 'No authenticated public APK verification keys')
    for item in [*packages, *lock['keys']]:
        validate_blob(item)
    for item in packages:
        require(re.fullmatch(r'[A-Za-z0-9+_.~-]+', item['version']), 'Unsafe package version')
        require(re.fullmatch(r'[A-Za-z0-9+_.-]+', item['package']), 'Unsafe package name')
    for name in lock['remove_packages']:
        require(re.fullmatch(r'[A-Za-z0-9+_.-]+', name), 'Unsafe remove-package name')
    validate_repositories(lock)
    validate_inventory(lock)


def validate_repositories(lock):
    indexes = lock.get('indexes', [])
    feeds = [item['feed'] for item in indexes]
    require(len(feeds) == len(set(feeds)), 'Duplicate repository feed')
    for item in indexes:
        validate_blob(item)
        require(re.fullmatch(r'[A-Za-z0-9_-]+', item['feed']), 'Unsafe repository feed')
    for item in lock['packages']:
        require('feed' not in item or item['feed'] in feeds, 'Official package has no pinned signed index')


def validate_inventory(lock):
    inventory = lock.get('expected_inventory', {})
    require(inventory and not set(inventory) & set(lock['excluded_packages']), 'Missing or excluded final inventory')
    for name, version in inventory.items():
        require(re.fullmatch(r'[A-Za-z0-9+_.-]+', name), 'Unsafe inventory package name')
        require(re.fullmatch(r'[A-Za-z0-9+_.~-]+', version), 'Unsafe inventory package version')
    for item in lock['packages']:
        require(inventory.get(item['package']) == item['version'], 'Requested version differs from final inventory')

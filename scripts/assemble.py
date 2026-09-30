"""Assemble locked public F50 artifacts in Docker; never connect to a device."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from archive_checks import audit_kernel, audit_reference_kernel, audit_rootfs, clean_name, require
from inputs import obtain, run, sha256, validate_package_lock
from inventory import verify_installed_inventory
from package_inputs import collect_packages
from updater import make_updater

ROOT = Path(__file__).resolve().parents[1]
ROOTFS_NAME = 'mu300-openwrt-rootfs.tar.gz'
KERNEL_NAME = 'mu300-kernel-7.2.tar.gz'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def record(path):
    return {'name': path.name, 'size': path.stat().st_size, 'sha256': sha256(path)}


def collect_base(options, workspace):
    lock = read_json(ROOT / 'inputs/base.lock.json')
    context = dict(directory=workspace / 'base', cache=workspace / 'cache', local=options.local_base)
    files = {spec['role']: obtain(spec, context) for spec in lock['files']}
    rootfs_audit = audit_rootfs(files['rootfs'])
    kernel_audit = audit_kernel(files['kernel'], lock['kernel_release'])
    reference_audit = audit_reference_kernel(files['reference-kernel'])
    validation = read_json(files['kernel-validation'])
    require(validation['status'] == 'PASS' and validation['kernel']['release'] == lock['kernel_release'],
            'Kernel build evidence did not pass for the selected release')
    require(validation['module_count'] == kernel_audit['modules'], 'Kernel module count differs from build report')
    return dict(lock=lock, files=files, audits={'base_rootfs': rootfs_audit, 'kernel': kernel_audit,
                                             'reference_kernel': reference_audit})


def extract_kernel(source, destination):
    with tarfile.open(source, 'r:gz') as archive:
        for member in archive.getmembers():
            name = clean_name(member.name)
            wanted = name.startswith('modules/') or name in {'kernel.release', 'modules.builtin', 'modules.builtin.modinfo'}
            if not wanted or member.isdir():
                continue
            require(member.isfile(), 'Kernel copy requires regular files')
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
            path.chmod(member.mode & 0o777)


def write_container_inputs(context):
    inputs, base, packages, options = context['inputs'], context['base'], context['packages'], context['options']
    extract_kernel(base['files']['kernel'], inputs)
    paths = read_json(ROOT / 'inputs/keep-paths.json')['paths']
    updater = make_updater(base['files']['updater'].read_text(),
                           {'repository': options.repository, 'paths': paths})
    (inputs / 'mu300-update').write_text(updater, encoding='utf-8')
    package_lines = [item['package'] + '\t' + item['version'] for item in packages['packages']]
    (inputs / 'expected-packages.tsv').write_text('\n'.join(package_lines) + '\n')
    defaults = read_json(ROOT / 'inputs/defaults.json')['uci']
    values = [key + '\t' + value for key, value in defaults.items()]
    (inputs / 'expected-defaults.tsv').write_text('\n'.join(values) + '\n', encoding='ascii')
    for field in ('remove_packages', 'excluded_packages'):
        filename = field.replace('_', '-') + '.txt'
        (inputs / filename).write_text('\n'.join(packages[field]) + '\n')
    shutil.copyfile(ROOT / 'scripts/container-assemble.sh', inputs / 'assemble.sh')


def run_container(context):
    require(run(['docker', 'info', '--format', '{{.Architecture}}']) in ('aarch64', 'arm64'),
            'Assembly requires a native ARM64 Docker daemon')
    base_hash = sha256(context['base']['files']['rootfs'])
    image = 'f50-public-base:' + base_hash[:12]
    run(['docker', 'import', '--platform', 'linux/arm64', context['base']['files']['rootfs'], image])
    output = context['staging']
    output.mkdir()
    command = ['docker', 'run', '--rm', '--network', 'none', '--platform', 'linux/arm64',
               '--mount', f"type=bind,src={context['inputs'].resolve()},dst=/in,readonly",
               '--mount', f"type=bind,src={output.resolve()},dst=/out",
               '-e', 'F50_BUILD_CONTAINER=1', '-e', 'F50_IMAGE_TAG=' + context['options'].tag,
               image, '/bin/sh', '/in/assemble.sh']
    log = run(command)
    (output / 'assembly.log').write_text(log, encoding='utf-8')
    actual = (output / 'installed-packages.txt').read_text(encoding='utf-8')
    verify_installed_inventory(actual, context['packages']['expected_inventory'])


def publish(context):
    staging = context['staging']
    rootfs_audit = audit_rootfs(staging / ROOTFS_NAME)
    shutil.copyfile(context['base']['files']['kernel'], staging / KERNEL_NAME)
    shutil.copyfile(context['base']['files']['reference-kernel'], staging / 'mu300-kernel.tar.gz')
    shutil.copyfile(context['inputs'] / 'mu300-update', staging / 'mu300-update')
    manifest = {'status': 'PASS', 'assembly_not_full_source_rebuild': True,
                'tag': context['options'].tag, 'repository': context['options'].repository,
                'base': context['base']['lock'], 'packages': context['packages'],
                'audits': dict(context['base']['audits'], output_rootfs=rootfs_audit),
                'kernel_original_bytes_preserved': sha256(staging / KERNEL_NAME) == sha256(context['base']['files']['kernel']),
                'persistent_paths': read_json(ROOT / 'inputs/keep-paths.json'),
                'artifacts': [record(path) for path in sorted(staging.iterdir())],
                'device_accessed': False, 'boot_and_network_tested': False,
                'assembly_commit': os.environ.get('GITHUB_SHA'),
                'docker_version': run(['docker', '--version'])}
    (staging / 'assembly-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    sums = [sha256(path) + '  ' + path.name for path in sorted(staging.iterdir())]
    (staging / 'SHA256SUMS').write_text('\n'.join(sums) + '\n', encoding='ascii')
    shutil.copytree(staging, context['options'].output, dirs_exist_ok=True)
    return manifest


def build(options):
    require(re.fullmatch(r'[A-Za-z0-9_.-]+', options.tag), 'Unsafe release tag')
    require(not options.output.exists() or not any(options.output.iterdir()), 'Output must be empty')
    validate_package_lock(read_json(options.package_lock))
    with tempfile.TemporaryDirectory(prefix='f50-assembly-') as temporary:
        workspace = Path(temporary)
        base = collect_base(options, workspace)
        packages, inputs = collect_packages(options, workspace, base['files']['rootfs'])
        context = dict(options=options, base=base, packages=packages, inputs=inputs,
                       staging=workspace / 'publish')
        write_container_inputs(context)
        run_container(context)
        return publish(context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--package-lock', type=Path, default=ROOT / 'inputs/packages.lock.json')
    parser.add_argument('--local-base', type=Path)
    parser.add_argument('--local-packages', type=Path)
    options = parser.parse_args()
    manifest = build(options)
    print(json.dumps({'status': manifest['status'], 'output': str(options.output)}))


if __name__ == '__main__':
    main()

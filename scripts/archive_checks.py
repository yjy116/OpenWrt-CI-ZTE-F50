"""Inspect public release archives without extracting or executing their contents."""
import hashlib
from pathlib import PurePosixPath
import posixpath
import re
import tarfile

KERNEL_FILES = {'Image', 'ramdisk-generic.lz4', 'kernel.release', 'devices',
                'modules.builtin', 'modules.builtin.modinfo'}
PRIVATE_PATHS = re.compile(
    r'(^|/)(__properties__|dev-properties)(/|$)|'
    r'(^|/)lib/firmware/(wcnmodem|gnssmodem|wifi_board_config|bt_configure)|'
    r'^etc/(ssh/ssh_host_|dropbear/dropbear_.*_host_key)|'
    r'^root/\.ssh/|^etc/mu300/(hotspot|vpn|toolkit)\.conf$|'
    r'(^|/)(identity\.(secret|public)|authtoken\.secret|tailscaled\.state)(\.|$)|'
    r'(^|/)et_machine_id$|^etc/daed/wing\.db($|-)|'
    r'(^|/)(libmali|libOpenCL|libGLES|libEGL|libvulkan)[^/]*\.so')
UCI_SECRET = re.compile(r"^\s*option\s+(?:password|passwd|secret|token|private_key|authkey|psk)\s+(['\"])(.+)\1\s*$", re.M)
# Exact public, disabled DDNS example from the signature-verified ddns-scripts APK.
# Any byte change restores normal credential checks; see tests/fixtures/README.txt.
PUBLIC_EXAMPLE_CONFIGS = {'etc/config/ddns': '0a88c15ed3e4b95a96b0af0a855c00b4d4a267322f6aeccb3b8745a15e7e8c27'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def clean_name(name):
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and '\\' not in name,
            f'Unsafe archive path: {name}')
    return path.as_posix().removeprefix('./')


def private_path(name):
    if PRIVATE_PATHS.search(name):
        return True
    if name.startswith('opt/mu300/android/'):
        return name not in {'opt/mu300/android/system/bin/cltest'}
    return False


def validate_link(member, name):
    target = member.linkname
    require('\\' not in target, f'Unsafe archive link: {name}')
    require(not member.islnk() or not target.startswith('/'), f'Absolute archive hardlink: {name}')
    parent = posixpath.dirname(name) if member.issym() else ''
    resolved = posixpath.normpath(posixpath.join(parent, target))
    require(resolved != '..' and not resolved.startswith('../'), f'Escaping archive link: {name}')


def members_checked(archive):
    seen = set()
    for member in archive.getmembers():
        name = clean_name(member.name)
        require(name not in seen, f'Duplicate archive member: {name}')
        seen.add(name)
        if member.isdir():
            continue
        require(not private_path(name), f'Private device file in archive: {name}')
        require(member.isfile() or member.issym() or member.islnk(), f'Unexpected archive file type: {name}')
        if member.issym() or member.islnk():
            validate_link(member, name)
        yield name, member


def check_sensitive_content(name, payload):
    if PUBLIC_EXAMPLE_CONFIGS.get(name) == hashlib.sha256(payload).hexdigest():
        return True
    if name in {'etc/machine-id', 'var/lib/dbus/machine-id'}:
        require(not payload.strip(), 'Nonempty machine identity in release')
    if name in {'etc/shadow', 'etc/gshadow'}:
        for line in payload.decode('utf-8').splitlines():
            fields = line.split(':')
            require(len(fields) > 1 and fields[1] in ('', '*', '!', '!!', '!*', 'x'),
                    f'Password hash in release account file: {name}')
    if name.startswith('etc/config/'):
        text = payload.decode('utf-8')
        if name == 'etc/config/luci':
            text = re.sub(r"^\s*option\s+passwd\s+['\"]/etc/passwd['\"]\s*$", '', text, flags=re.M)
        if name == 'etc/config/rpcd':
            text = re.sub(r"^\s*option\s+password\s+['\"]\$p\$root['\"]\s*$", '', text, flags=re.M)
        require(not UCI_SECRET.search(text), f'Nonempty credential in release config: {name}')
    if name.endswith(('.key', '.pem')):
        require(b'PRIVATE KEY-----' not in payload, f'Private key in release: {name}')


def audit_rootfs(path):
    files = []
    examples = []
    with tarfile.open(path, 'r:gz') as archive:
        for name, member in members_checked(archive):
            files.append(name)
            sensitive = name.startswith('etc/config/') or name in {'etc/shadow', 'etc/gshadow',
                        'etc/machine-id', 'var/lib/dbus/machine-id'} or name.endswith(('.key', '.pem'))
            if member.isfile() and sensitive and check_sensitive_content(name, archive.extractfile(member).read()):
                examples.append(name)
    require('bin/busybox' in files and 'etc/openwrt_release' in files, 'Not an OpenWrt root filesystem')
    return {'files': len(files), 'private_files': False, 'device_credentials': False,
            'exact_public_example_configs': examples}


def audit_kernel(path, release):
    with tarfile.open(path, 'r:gz') as archive:
        members = dict(members_checked(archive))
        require(KERNEL_FILES <= members.keys(), 'Incomplete kernel bundle protocol')
        require(all(member.isfile() for member in members.values()), 'Kernel bundle contains links')
        actual = archive.extractfile(members['kernel.release']).read().decode().strip()
        devices = archive.extractfile(members['devices']).read().decode().split()
        require(actual == release and 'f50' in devices, 'Kernel release or F50 device mismatch')
        modules = [name for name in members if name.startswith('modules/') and name.endswith('.ko')]
        require(modules, 'Kernel bundle contains no modules')
        require(members['Image'].size and members['ramdisk-generic.lz4'].size, 'Empty boot payload')
    return {'release': actual, 'devices': devices, 'modules': len(modules)}


def audit_reference_kernel(path):
    with tarfile.open(path, 'r:gz') as archive:
        members = dict(members_checked(archive))
        require({'Image', 'busybox', 'logdw', 'devices', 'ramdisk-generic.lz4'} <= members.keys(),
                'Incomplete legacy reference bundle required by upstream installers')
        devices = archive.extractfile(members['devices']).read().decode().split()
        require('f50' in devices, 'Reference bundle does not support F50')
    return {'files': len(members), 'devices': devices, 'role': 'installer reference; selected kernel remains 7.2'}

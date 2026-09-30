"""Compare every assembled package and version on the build host."""
from collections import Counter


def verify_installed_inventory(actual, expected):
    installed = Counter(actual.splitlines())
    locked = Counter(name + '-' + version for name, version in expected.items())
    if installed == locked:
        return
    missing = sorted((locked - installed).elements())
    extra = sorted((installed - locked).elements())
    raise ValueError(f'Assembled package inventory differs: missing={missing}; extra={extra}')

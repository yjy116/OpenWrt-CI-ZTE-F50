#!/bin/sh
# Runs only in an isolated imported public rootfs container, never on an F50.
set -eu
export LC_ALL=C
test "${F50_BUILD_CONTAINER:-}" = 1
test -s /in/expected-packages.tsv
test -s /in/mu300-update
test -s /in/kernel.release
mkdir -p /tmp /var/lock

# APK scripts operate on an offline image root; rc.common start is suppressed
# by the standard OpenWrt IPKG_INSTROOT contract. Public keys are a read-only
# temporary verification directory, never copied into the persistent trust store.
export IPKG_INSTROOT=/
export PKG_UPGRADE=1
for package in /in/apks/*.apk; do
    test -f "$package" || continue
    apk --keys-dir /in/keys --repositories-file /in/repositories.list --no-network verify "$package"
done
apk --keys-dir /in/keys --repositories-file /in/repositories.list --no-network update
while IFS= read -r package; do
    test -n "$package" || continue
    apk --keys-dir /in/keys --repositories-file /dev/null --no-network del "$package"
done < /in/remove-packages.txt
set --
for package in /in/apks/*.apk; do
    test -f "$package" || continue
    set -- "$@" "$package"
done
while IFS= read -r package; do
    test -n "$package" || continue
    set -- "$@" "$package"
done < /in/official-packages.txt
apk --keys-dir /in/keys --repositories-file /in/repositories.list --no-network add --simulate "$@"
apk --keys-dir /in/keys --repositories-file /in/repositories.list --no-network add "$@"
while IFS="$(printf '\t')" read -r package version; do
    apk info --exists "$package=$version"
done < /in/expected-packages.tsv
while IFS= read -r package; do
    test -n "$package" || continue
    if apk info --exists "$package"; then
        echo "Excluded package remains installed: $package" >&2
        exit 1
    fi
done < /in/excluded-packages.txt
while IFS="$(printf '\t')" read -r key expected; do
    actual=$(uci get "$key")
    if [ "$actual" != "$expected" ]; then
        echo "Unexpected public-image service default: $key" >&2
        exit 1
    fi
done < /in/expected-defaults.tsv
cp /in/expected-defaults.tsv /out/service-defaults.tsv
find /etc/rc.d -type l | sort > /out/boot-service-links.txt

kernel_release=$(cat /in/kernel.release)
mkdir -p "/lib/modules/$kernel_release"
cp -a /in/modules/. "/lib/modules/$kernel_release/"
cp /in/modules.builtin /in/modules.builtin.modinfo "/lib/modules/$kernel_release/"
cp /in/mu300-update /opt/mu300/bin/mu300-update
chmod 0755 /opt/mu300/bin/mu300-update
printf '%s\n' "$F50_IMAGE_TAG" > /etc/mu300/image-version
: > /etc/.mu300-accounts-from-image
uci set luci.main.lang=zh_cn
uci set luci.main.mediaurlbase=/luci-static/aurora
uci commit luci
apk info -v | sort > /out/installed-packages.txt
diff -u /in/expected-inventory.txt /out/installed-packages.txt

# Copy excluding host bind mounts and runtime trees. Restore generic resolver
# and host records explicitly; never ship Docker's host/container identities.
root=/build/root
mkdir -p "$root"
for entry in /*; do
    case "$entry" in /proc|/sys|/dev|/build|/in|/out|/tmp|/run) continue ;; esac
    cp -a "$entry" "$root/"
done
mkdir -p "$root/proc" "$root/sys" "$root/dev" "$root/tmp" "$root/run"
ln -sfn /tmp/resolv.conf "$root/etc/resolv.conf"
printf '127.0.0.1\tlocalhost\n::1\tlocalhost ip6-localhost ip6-loopback\n' > "$root/etc/hosts"
printf 'mu300\n' > "$root/etc/hostname"
test ! -s "$root/etc/machine-id"
cd "$root"
tar -czf /out/mu300-openwrt-rootfs.tar.gz .

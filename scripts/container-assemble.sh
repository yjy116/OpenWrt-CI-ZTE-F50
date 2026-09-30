#!/bin/sh
# Runs only in an isolated imported public rootfs container, never on an F50.
set -eu
export LC_ALL=C
test "${F50_BUILD_CONTAINER:-}" = 1
test -s /in/expected-packages.tsv
test -s /in/mu300-update
test -s /in/kernel.release
mkdir -p /tmp /var/lock

# APK otherwise discards IPKG_INSTROOT before execve of package scripts.
# Keep its native script ordering and pass only this offline-image environment.
apk_image() {
    env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C IPKG_INSTROOT=/ \
        apk --preserve-env --keys-dir /in/keys \
        --repositories-file /in/repositories.list --no-network "$@"
}

for package in /in/apks/*.apk; do
    test -f "$package" || continue
    apk_image verify "$package"
done
apk_image update
while IFS= read -r package; do
    test -n "$package" || continue
    apk_image del "$package"
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
apk_image add --simulate "$@"
apk_image add "$@"
while IFS="$(printf '\t')" read -r package version; do
    apk_image info --exists "$package=$version"
done < /in/expected-packages.tsv
while IFS= read -r package; do
    test -n "$package" || continue
    if apk_image info --exists "$package"; then
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
for script in luci-openclash luci-homeproxy luci-homeproxy-migration luci-easytier; do
    test -s "/etc/uci-defaults/$script"
done
find /etc/uci-defaults -type f | sort > /out/deferred-uci-defaults.txt

for file in www/luci-static/resources/view/status/include/15_f50_thermal.js \
            usr/share/rpcd/acl.d/luci-f50-thermal.json; do
    mkdir -p "/$(dirname "$file")"
    cp "/in/overlay/$file" "/$file"
    chmod 0644 "/$file"
done

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
apk_image info -v | sort > /out/installed-packages.txt

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

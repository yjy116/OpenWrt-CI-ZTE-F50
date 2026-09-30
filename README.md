# F50 OpenWrt 组装 CI

本项目组装用于 ZTE F50 的通用 OpenWrt 25.12.5 文件系统和已验证的
7.2.8-f50-dae1 内核。它复用公开上游 rootfs 与成功内核构建产物，**不是重新编译
整套 OpenWrt**。当前锁定 96 个输入 APK，组装后的 247 个包名和版本已与设备最终
安装清单逐项比对一致；完整云组装与新镜像启动验证尚未执行。

设备使用 `mu300-update`/MU300 专用安装器，而不是 OpenWrt armsr 整盘 sysupgrade。
发布协议固定为 `mu300-openwrt-rootfs.tar.gz`、`mu300-kernel-7.2.tar.gz`、
`mu300-update`、`SHA256SUMS`，另附组装清单。内核包保留已经验证的原始字节。

所有设备密码、ZeroTier/Tailscale/EasyTier 身份、订阅、Android 用户空间和无线
固件均不得成为构建输入或发布内容。上游升级器在设备上从旧系统复制专有文件和
配置；本项目的持久目录清单用于补齐新增插件状态，绝不从设备读取后上传。

包含范围：实际已验证的通用插件、daede、ZeroTier p2、Aurora。AdGuard Home、
SQM、MT3600BE 风扇/存储/WoL/AC/打印硬件组件排除。HomeProxy 使用已固定的
1.12.25 sing-box 适配构建；不能用删除依赖或伪造 kmod 包掩盖未验证的内核缺口。

原安装器即使选择 7.2，也会下载 `mu300-kernel.tar.gz` 的 5.4 参考包，使用其中的
通用工具构建启动镜像。因此输出同时保留该公开参考包的原始字节；这不代表升级时
将当前 7.2 切换到 5.4。安装时应明确选择 7.2。

## 输入锁

`inputs/base.lock.json` 固定通用 rootfs、上游升级器、参考内核和成功云构建的
7.2.8-f50-dae1 bundle。内核来自公开仓库 `yjy116/f50-daede-kernel`，run
`36672813155`、commit `10748c1bb03150748726c4592ebfa1fb30166cb2`。
其完整编译来源与 BTF/eBPF 验证脚本保留在该仓库。本项目只核验并复用结果。

`inputs/packages.lock.json` 固定全部目标 APK、依赖、签名索引与公共密钥，
`complete: true` 表示输入及版本清单齐全，不表示新镜像已通过启动测试。每项格式如下：

```json
{
  "name": "package-version.apk",
  "package": "package-name",
  "version": "exact-version",
  "size": 123,
  "sha256": "64 lowercase hexadecimal characters",
  "source": {"url": "https://public.example/package-version.apk"}
}
```

公开 Actions 来源替换 source 为 `repository`、`run_id`、`head_sha`、`artifact`、
`member`。下载前核验成功运行和 commit；下载后重算 SHA256。不同构建的签名公钥须
使用不同 `name`，例如带其哈希前缀的 `.pem`，避免同名密钥覆盖。密钥项不含 package
或 version；构建拒绝私钥。官方包带 `feed`，对应 `indexes` 中固定哈希的签名
`packages.adb`，保持仓库原文件名。官方 key 从已验证基础 rootfs 提取并再核哈希。
`dnsmasq-full` 由 APK 在一次 add 事务替换 dnsmasq，无预先删除步骤。

`expected_inventory` 源自固定基底与输入包集合，已与最终设备清单的 247 个包精确
比对。组装再次比较实际包名和版本全集，额外包、缺包或版本不同均失败。

Actions artifact 会过期。过期或权限不足会明确失败；应将原验证产物保存为可信公开
release 并更新锁，或重新运行原内核构建、审核新产物后更新锁。不会转而下载 latest。

## 构建与验证

在原生 ARM64 Docker 环境运行（GitHub workflow 使用 `ubuntu-24.04-arm`）：

```sh
timeout 60s python3 -B -m unittest discover -s tests
python3 scripts/assemble.py --tag vYYYY.MM.DD-f50.1 \
  --repository OWNER/REPOSITORY --output out
```

也可提供 `--local-base /path/to/public-base-inputs` 与
`--local-packages /path/to/verified-apks-and-public-keys`。目录内文件仍须与输入锁的
名称、大小及 SHA256 完全一致。它们不是从 F50 导出的文件系统或配置目录。

容器使用 `--network none`；仅导入已校验公开 rootfs，使用单独临时公钥目录校验
自签 APK；官方无单包签名的 APK 则用原始签名索引先 update，再按精确版本安装。
先运行依赖模拟，再离线安装并比较完整版本集合。标准 OpenWrt `IPKG_INSTROOT=/`
使 default_postinst 跳过守护进程启动与 uci-defaults，后者保留到设备首启执行；服务
启用链接仍按包的标准生命周期生成。脚本不传入 GH_TOKEN 或宿主秘密。
不修改宿主和目标设备的 APK 信任库。

组装断言 daed、ZeroTier、OpenClash、EasyTier、HomeProxy、sing-box、自动重启及
vlmcsd 的公共默认配置未启用代理或计划任务；输出配置断言和启动链接清单。
Tailscale 可以启动为未登录状态，这不等同于已建立 VPN。升级会保留设备既有配置。

输出重新审计路径穿越、重复成员、私有固件、SSH/VPN 身份、账户密码哈希和非空
配置凭据；LuCI 的 `/etc/passwd` 文件引用及 rpcd 的 `$p$root` 账户引用不会被误当
密码。内核 bundle 校验版本、F50 标记和模块数量，发布字节与原验证输入一致。
清单记录输入、实际包列表、产物哈希及未进行实机启动/网络验证的事实。

## 升级与配置迁移

`mu300-update` 保留上游更新机制，仅调整默认发布仓库与明确的插件持久目录列表。
原有 `etc/config`、`etc/mu300`、Dropbear、root 目录、账户和设备固件迁移逻辑保留。
`inputs/keep-paths.json` 已按最终已装插件复核；未来自定义存储路径需补入。
固定 rootfs 的 `/var` 指向临时目录，不应把它当成持久身份保存位置。
OpenClash 只迁移六个用户数据子目录，保留新包内核心与数据库。daed 数据库目录及
Tailscale 的 `/etc/tailscale` 身份目录只在设备端迁移。账户 marker 配合原版
merge_accounts 保留旧密码；镜像本身不包含用户密码或密码哈希。

未来完成发布后，现有上游升级器可通过环境变量选择本仓库的已审计 release：

```sh
MU300_REPO=OWNER/REPOSITORY MU300_RELEASE=vYYYY.MM.DD-f50.1 mu300-update apply openwrt
```

此处只是格式说明，本阶段没有执行设备升级。普通 LuCI sysupgrade 和 armsr 整盘
镜像不适用。不得把此 rootfs 直接写入整盘或 Android 原始分区。

现状：聚焦测试、真实基础输入审计与最终 247 包清单核对已完成；尚未执行完整云
组装、发布或新镜像实机升级。已有 F50 总台账第 23 项跟踪，不另建重复台账。

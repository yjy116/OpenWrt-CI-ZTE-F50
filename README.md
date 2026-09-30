# F50 OpenWrt 组装 CI

本项目组装用于 ZTE F50 的通用 OpenWrt 25.12.5 文件系统和已验证的
7.2.8-f50-dae1 内核。它复用公开上游 rootfs 与成功内核构建产物，**不是重新编译
整套 OpenWrt**。当前锁定 96 个输入 APK，组装后的 247 个包名和版本已与设备最终
安装清单逐项比对一致；[ARM64 云组装与产物审计已通过](https://github.com/yjy116/OpenWrt-CI-ZTE-F50/actions/runs/36703988419)。
完整新镜像尚未刷入设备进行启动验证。

设备使用 `mu300-update`/MU300 专用安装器，而不是 OpenWrt armsr 整盘 sysupgrade。
发布协议固定为 `mu300-openwrt-rootfs.tar.gz`、`mu300-kernel-7.2.tar.gz`、
`mu300-update`、`SHA256SUMS`，另附组装清单。内核包保留已经验证的原始字节。

所有设备密码、ZeroTier/Tailscale/EasyTier 身份、订阅、Android 用户空间和无线
固件均不得成为构建输入或发布内容。上游升级器在设备上从旧系统复制专有文件和
配置；本项目的持久目录清单用于补齐新增插件状态，绝不从设备读取后上传。

包含范围：实际已验证的通用插件、daede、ZeroTier p2、Aurora。AdGuard Home、
SQM、MT3600BE 风扇/存储/WoL/AC/打印硬件组件排除。HomeProxy 使用已固定的
1.12.25 sing-box 适配构建；不能用删除依赖或伪造 kmod 包掩盖未验证的内核缺口。

| LuCI 菜单 | 已包含插件 |
| --- | --- |
| VPN | ZeroTier、Tailscale、EasyTier |
| 服务 | daede、OpenClash、HomeProxy、DDNS、NATMap、nlbwmon、iPerf3、ttyd、UPnP、Vlmcsd |
| 系统 | 定时重启、Aurora 主题配置 |

界面包含中文翻译。具体版本、依赖和包来源见输入锁。
F50 温度卡片作为固件自带 LuCI 组件随镜像加入，包数量仍为 247。组装只复制两个
明确审核过的页面/只读 ACL 文件，并验证源码与最终 rootfs 内字节、权限完全一致；
细节见 [温度组件说明](README-f50-thermal.md)。

原安装器即使选择 7.2，也会下载 `mu300-kernel.tar.gz` 的 5.4 参考包，使用其中的
通用工具构建启动镜像。因此输出同时保留该公开参考包的原始字节；这不代表升级时
将当前 7.2 切换到 5.4。安装时应明确选择 7.2。

## 输入锁

`inputs/base.lock.json` 固定通用 rootfs、上游升级器、参考内核和成功云构建的
7.2.8-f50-dae1 bundle。内核构建来自公开仓库 `yjy116/f50-daede-kernel`，run
`36672813155`、commit `10748c1bb03150748726c4592ebfa1fb30166cb2`。
其完整编译来源与 BTF/eBPF 验证脚本保留在该仓库。本项目只核验并复用结果。
内核、全部插件 APK、签名索引和公共密钥现已保存到本仓库的
[固定构建输入 release](https://github.com/yjy116/OpenWrt-CI-ZTE-F50/releases/tag/build-inputs-2026.09.30)，
当前组装直接使用其公开下载地址，不依赖跨仓库 Actions 权限或 artifact 保留时间。
该 release 供 CI 获取依赖，完整固件由组装 workflow 另行生成。

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

原 Actions 运行号、commit 和 artifact 路径，以及官方原始下载地址保留在
`source_provenance`。当前 `source` 均指向固定公开 release；下载后重算 SHA256。
不同构建的签名公钥须
使用不同 `name`，例如带其哈希前缀的 `.pem`，避免同名密钥覆盖。密钥项不含 package
或 version；构建拒绝私钥。官方包带 `feed`，对应 `indexes` 中固定哈希的签名
`packages.adb`，保持仓库原文件名。官方 key 源自已验证基础 rootfs，其原始 SHA
与现公开归档一致。
`dnsmasq-full` 由 APK 在一次 add 事务替换 dnsmasq，无预先删除步骤。

`expected_inventory` 源自固定基底与输入包集合，已与最终设备清单的 247 个包精确
比对。容器导出实际清单后，宿主 Python 比较包名和版本全集，额外包、缺包、重复
条目或版本不同均失败；基础镜像不需要额外安装比较工具。

GitHub 将 25 个资产名中的 `~` 改成了 `.`。锁中的 `source.url` 使用实际 release
资产名，`name` 保留 APK 索引所需的原名，下载后按原名保存。release 的
`INPUT-SOURCES.json` 记录完整映射，`SHA256SUMS` 使用 release 资产名。
任何缺失、下载错误或哈希差异都会使组装明确失败，不会转而下载 latest。

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
先运行依赖模拟，再离线安装并比较完整版本集合。APK 通过 `env -i` 白名单及原生
`--preserve-env` 将 `IPKG_INSTROOT=/` 传给生命周期；仅外层 export 会被 APK 丢弃。
标准 OpenWrt default_postinst 据此跳过守护进程启动与 uci-defaults，后者保留到设备首启执行；服务
启用链接仍按包的标准生命周期生成。脚本不传入 GH_TOKEN 或宿主秘密。
不修改宿主和目标设备的 APK 信任库。

组装断言 daed、ZeroTier、OpenClash、EasyTier、HomeProxy、sing-box、自动重启及
vlmcsd 的公共默认配置未启用代理或计划任务；输出配置断言和启动链接清单。
Tailscale 可以启动为未登录状态，这不等同于已建立 VPN。升级器先复制现有配置，
首次启动时包自身仍可能迁移配置，具体范围见下文。

输出重新审计路径穿越、重复成员、私有固件、SSH/VPN/EasyTier 身份、daed 运行数据库、账户密码哈希和非空
配置凭据；LuCI 的 `/etc/passwd` 文件引用及 rpcd 的 `$p$root` 账户引用不会被误当
密码。内核 bundle 校验版本、F50 标记和模块数量，发布字节与原验证输入一致。
官方 DDNS 包自带的未启用示例使用公开占位值；只按该配置完整文件 SHA256 识别，
不属于私人凭据。配置内容有任何变化后，非空凭据仍按普通规则拒绝。
清单记录输入、实际包列表、产物哈希及未进行实机启动/网络验证的事实。

## 升级与配置迁移

`mu300-update` 保留上游更新机制，仅调整默认发布仓库与明确的插件持久目录列表。
原有 `etc/config`、`etc/mu300`、Dropbear、root 目录、账户和设备固件迁移逻辑保留。
`inputs/keep-paths.json` 已按最终已装插件复核；未来自定义存储路径需补入。
固定 rootfs 的 `/var` 指向临时目录，不应把它当成持久身份保存位置。
OpenClash 只迁移六个用户数据子目录，保留新包内核心与数据库。daed 数据库目录及
Tailscale 的 `/etc/tailscale` 身份目录只在设备端迁移。账户 marker 配合原版
merge_accounts 保留旧密码；镜像本身不包含用户密码或密码哈希。

保留配置后，首次启动仍执行原生 `uci-defaults` 和迁移脚本。HomeProxy 会迁移旧
DNS/路由字段并重建自身防火墙 include；OpenClash 会补齐缺失认证、调整部分全局
参数并重载 Web 服务；EasyTier 会建立 init 启用链接，但不改变 UCI enabled。
因此不承诺升级后 `etc/config` 逐字节不变。已审脚本未见无条件重置原有 enabled
或身份的行为，完整新 rootfs 的升级效果仍待实机验证。

构建输入归档与首版固件使用预发布标记。在完整镜像实机验收前，不提供稳定版
`latest`；首次使用必须显式指定已审核的固件 tag。没有稳定版时，默认 latest
查询会明确失败，不会自动改用构建输入归档或其它版本。

未来完成发布后，现有上游升级器可通过环境变量选择本仓库的已审计 release：

```sh
MU300_REPO=OWNER/REPOSITORY MU300_RELEASE=vYYYY.MM.DD-f50.1 mu300-update apply openwrt
```

此处只是格式说明，本阶段没有执行设备升级。普通 LuCI sysupgrade 和 armsr 整盘
镜像不适用。不得把此 rootfs 直接写入整盘或 Android 原始分区。

验证：17 项 Python 测试、11 项温度组件测试、Shell 语法及 actionlint 通过。
云产物的内外包清单均为精确锁定的 247 包，31 个模块与内核 bundle 字节一致，
两份温度文件与源码 SHA、权限一致，Vlmcsd 三项默认关闭，首次启动脚本完整保留，
未发现构建阶段生成的设备身份或私人配置。温度组件已在现有 F50 单独部署并验证
六个测温点和自动刷新；完整新 rootfs 尚未实机升级。已有总台账第 23 项跟踪。

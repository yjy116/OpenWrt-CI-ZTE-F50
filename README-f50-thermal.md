# F50 温度概览组件

组件只增加两个覆盖文件，不修改 LuCI 的 `10_system.js`：

- `files/www/luci-static/resources/view/status/include/15_f50_thermal.js`
- `files/usr/share/rpcd/acl.d/luci-f50-thermal.json`

LuCI 概览会自动发现 status include，并按现有概览刷新周期调用它。
使用原生表格，适配当前 Aurora 主题；不增加守护进程、执行命令或修改配置。
固件构建只复制这两个明确路径，并核验最终 rootfs 内文件与源码的 SHA256、
0644 权限及 root 所有权；组件不增加 APK，包数量保持 247。

每轮通过已有 LuCI `fs.list()` / `fs.read()`（rpcd `file.list/read`）重新枚举
`/sys/class/thermal`，接受实际 sysfs 符号链接，读取 `type` 后精确匹配：

| 标签 | thermal type |
| --- | --- |
| CPU 测温点 1 | apcpu0-thmzone |
| CPU 测温点 2 | apcpu1-thmzone |
| GPU | gpu-thmzone |
| LTE | lte-thmzone |
| 5G NR 测温点 1 | nr0-thmzone |
| 5G NR 测温点 2 | nr1-thmzone |

这些是芯片/蜂窝内部测温点，不代表外壳温度，不合并为单一“整机温度”。
`temp` 的整数毫摄氏度除以 1000，页面显示一位小数 °C。
零值与负值有效；空值、非整数文本、非有限/不安全整数、重复类型都明确报错。
没有基于编号的替代路径，也不在读取失败后沿用上轮温度。

枚举、类型读取和单项温度错误作为页面数据展示，避免 LuCI 概览把 rejected include
标为失败后隐藏。缺失传感器保留该行并显示原因，其他正常测温点继续显示。
ACL 仅授权 thermal 目录列表与 zone 的 `type/temp` 读取，没有 write/exec 权限。
ACL 更新后需重载 rpcd 并重新建立 LuCI 登录会话，再验证真实认证会话能读取。

测试命令：`node --test tests/test_thermal.js`。
测试以内存文件读取适配器加载实际 LuCI 模块逻辑，覆盖乱序、符号链接、缺失、重复、
枚举失败、类型/温度读取失败、错误后恢复、坏数值、零/负值以及跨轮不复用旧值。
这些测试验证逻辑与权限声明。组件还已在现有 F50 上单独部署：浏览器显示六项真实
读数、无需重新加载即可自动刷新，没有组件错误；未修改网络或无线配置。
完整新 rootfs 的刷机启动尚未验证，组件实测不能替代整套镜像验收。

核查依据：当前公开基础 rootfs 的 `fs.js`、`view/status/index.js` 和
`usr/share/rpcd/acl.d/luci-mod-status-index.json`；设备 rpcd 版本对应
[OpenWrt rpcd 28faf640 file.c](https://github.com/openwrt/rpcd/blob/28faf640/file.c)，
以及 Linux [thermal sysfs ABI](https://github.com/torvalds/linux/blob/v6.18/Documentation/ABI/testing/sysfs-class-thermal)。
后续 rpcd 若改变符号链接目标的 ACL 校验，需重新验证路径授权；不扩大为任意 sysfs 读取。

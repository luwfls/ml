# ADB 输入后端设计

## 目标与边界

游戏运行在 MuMu Android 模拟器中。项目继续使用 Windows 窗口发现、客户区截图和 OpenCV 模板识别；只有键盘/鼠标输入切换到 ADB。业务脚本调用 `ScriptRuntime`，低层调用者使用 `game_bot.core.input`，不得自行拼接 ADB 命令。

配置位于 `config/settings.yaml`：

```yaml
input:
  backend: adb
adb:
  executable: D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe
  serial: emulator-5554
```

每条 ADB 命令都必须携带 `-s <serial>`。设备离线、display 无法解析或坐标无法确认时停止动作，不自动回退到 dm。

## 宿主窗口发现与准备

服务控制的是 MuMu 的 Windows 宿主窗口，当前标题为 `Android Device`。`config/settings.yaml` 使用 `game.window_mode: android_emulator` 时，窗口发现优先按标题查找，找不到时再尝试旧的 `process_name`，因此不会因为 `SummonersWar` 进程名不匹配而跳过窗口准备。

- `game.window_size` 表示 Windows 宿主窗口的目标客户区尺寸；当前最新记录为 `1093x674`。
- 模板 JSON 的 `window_client_size` 应与该记录同步，但 PNG 模板不因元数据迁移而重采样。
- ADB 点击/滑动仍在动作发生时读取实际 client size，再映射到 Android active logical frame；窗口目标尺寸和 Android 输入分辨率是两个独立概念。
- 窗口重启后 HWND 可能变化，必须重新按配置发现，不能硬编码 HWND。


1. 截图和模板匹配产出 Windows 窗口客户区像素。
2. ADB `input tap/swipe` 接收 Android 当前活动逻辑显示坐标。
3. MuMu 的 `wm size` 当前返回物理竖屏 `1440x2560`，但游戏输入运行在逻辑横屏 `2560x1440`；物理尺寸不能直接用于点击。
4. `game_bot.core.adb` 优先解析 `dumpsys input` 中 active INTERNAL viewport 的 `logicalFrame` 和 orientation。

当 Windows 客户区完整对应 Android 显示 viewport 时：

```text
adb_x = round((client_x + 0.5) * logical_width / client_width - 0.5)
adb_y = round((client_y + 0.5) * logical_height / client_height - 0.5)
```

最终坐标钳制到 viewport 的有效像素。客户区尺寸必须在动作发生时通过 `get_client_size(hwnd)` 实时读取，不能使用配置中的期望窗口尺寸代替。

现场验证样例：

```text
client_size = 1018x632
logical_size = 2560x1440
client_point = (572,591)
adb_point = (1439,1347)
```

若模拟器客户区以后出现工具栏、黑边或 safe area，应给 mapper 提供明确的 Android viewport；不要在脚本中硬编码偏移。

## 输入语义

### 点击

- `button=left`：`adb shell input tap x y`。
- `clicks > 1`：按 `interval_ms` 重复 tap。
- 标准 ADB tap 不提供可靠的按住时长；`duration_ms` 保留用于接口兼容。
- Android touch 没有通用 right-click 语义，右键请求明确失败。

### 拖拽

在 Windows client 空间计算并验证终点，然后分别映射起点与终点：

```text
adb shell input swipe x1 y1 x2 y2 duration_ms
```

`steps` 是 dm 插值参数；ADB swipe 不使用它，但保留公共参数避免破坏调用者。

### 按键

使用 Android keycode 映射，不传 Windows virtual-key：

- `esc` / `escape` -> `KEYCODE_ESCAPE` (`111`，已实测)
- `enter` -> `66`
- `space` -> `62`
- `tab` -> `61`
- `backspace` -> `67`
- `delete` -> `112`
- 方向键 -> DPAD `19`–`22`

普通字符文本输入没有纳入首版；需要时应新增经过参数化处理的 `input text` 能力，不得拼接 shell 字符串。

### 滚动

标准 ADB 没有桌面滚轮。后端在 Android viewport 中央发送触摸 swipe：

- `direction=down` 表示内容向下，手指从下向上滑。
- `direction=up` 表示内容向上，手指从上向下滑。
- `distance` 是重复手势次数。
- `speed` 映射为单次 swipe 时长。

## 兼容策略

`game_bot.core.input.InputBackend` 和 `InputResult` 保持不变。模块门面从配置创建默认 backend，因此 `ScriptRuntime`、workbench 和旧 workflow 节点不需要改变调用签名。

`game_bot.core.dm.DmInputBackend` 继续存在，供显式选择 `input.backend: dm` 或测试时注入；它不再是默认路径，也不是 ADB 失败时的隐式 fallback。

## 排障与验证

```powershell
& "D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe" devices -l
& "D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe" -s "emulator-5554" shell wm size
& "D:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe" -s "emulator-5554" shell dumpsys input
```

排查顺序：

1. serial 必须显示为 `device`，不是 `offline`。
2. 记录 Windows 实时 client size。
3. 确认 active logical frame 与当前横竖屏一致。
4. 先打印 mapper 结果，再发送安全位置的 tap。
5. 若点击位置偏移，检查 client 内是否有非游戏 viewport，而不是修改全局缩放公式。

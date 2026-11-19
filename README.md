# FigCraft 双向桥控制台（figcraft-bridge-console）

在 **FigCraft** 与 **Axure** 之间双向搬运画板／元件的 Windows 桌面小工具。仓库同时保留了统一控制台与早期两个**独立单向桥**（作为历史版本归档）。

- 仓库地址：<https://github.com/Qign/figcraft-bridge-console.git>
- 许可协议：MIT（见 `LICENSE`）
- 平台：Windows（依赖 Win32 剪贴板 / 全局热键 / 托盘 API，纯 Python 标准库实现，无第三方依赖）

---

## 一、仓库结构

```
figcraft-bridge-console/        ← 仓库根（本机开发目录为 D:\AI\FigCraft\BridgeTool）
├─ 启动控制台.bat                ← 开发/脚本版启动器（pythonw 启动 src/app.py）
├─ config.json                  ← 运行时配置（端口、热键、桥开关、窗口位置）
├─ src/                         ← 统一控制台源码
│  ├─ app.py                    ← 主程序：单实例 + 配置 + 日志 + 状态机 + 托盘 + 面板 + 热键分发
│  ├─ core_f2a.py               ← 转换核心：FigCraft → Axure
│  ├─ core_a2f.py               ← 转换核心：Axure → FigCraft
│  ├─ ui_panel.py               ← 控制面板窗口
│  ├─ ui_tray.py                ← 系统托盘图标与菜单
│  ├─ build.bat                 ← PyInstaller 打包脚本
│  └─ assets/                   ← 图标（app.ico / tray_*.ico）与 axvg 图元模板 axvg_tpl.json
├─ axure桥/                      ← 【旧版独立桥】FigCraft → Axure 单向
├─ axvg桥/                       ← 【旧版独立桥】Axure → FigCraft 单向
├─ .gitignore
├─ LICENSE
└─ README.md
```

> 最终程序（本地打包为 `FigCraft桥控制台.exe`，约 10.4 MB）**不入库**，随版本发布到 [GitHub Releases](https://github.com/Qign/figcraft-bridge-console/releases)，附件名为 `FigCraft.exe`（同一份文件，用英文名是为了避免中文名在部分环境下下载/解压异常）。仓库只保留源码，避免二进制文件把版本历史撑大。

### 三个组件定位

| 组件 | 定位 | 方向 | 形态 | 状态 |
|---|---|---|---|---|
| `src/`（打包产物见 Releases） | **统一双向桥控制台** | FigCraft ⇄ Axure 双向 | 单文件 exe + 托盘 + 面板 | 当前主线，推荐使用 |
| `axure桥/` | **旧版独立桥**（FigCraft → Axure） | 单向 F→A | 常驻脚本 + 全局热键，无窗口 | 归档，仅作参考 |
| `axvg桥/` | **旧版独立桥**（Axure → FigCraft） | 单向 A→F | 常驻脚本 + 全局热键，无窗口 | 归档，仅作参考 |

两个旧版桥是统一控制台的前身：各自用一套 `pythonw` 常驻进程、各自的 `bridge_ctl.py` 管理启停，靠 `Ctrl+Alt+S` 暂停。统一控制台把它们合并为一个进程，热键、开关、日志、状态视图集中到托盘和面板里，因此**新环境直接用控制台即可**，旧版目录原样保留用于回溯实现细节。

---

## 二、热键

统一控制台（默认值，可在 `config.json` 的 `hotkeys` 段修改）：

| 热键 | 作用 |
|---|---|
| `Ctrl + Alt + C` | 把 FigCraft 中选中的画板转换并写入系统剪贴板，随后到 Axure 画布 `Ctrl+V` 粘贴（F→A） |
| `Ctrl + Alt + V` | 把 Axure 中复制的元件写入当前 FigCraft 文档（A→F） |

旧版独立桥：

| 热键 | 所属 | 作用 |
|---|---|---|
| `Ctrl + Alt + C` | axure桥 | FigCraft → Axure |
| `Ctrl + Alt + S` | axure桥 | 暂停 / 恢复 |
| `Ctrl + Alt + V` | axvg桥 | Axure → FigCraft |
| `Ctrl + Alt + S` | axvg桥 | 暂停 / 恢复 |

> 统一控制台与旧版桥热键重叠，**不要同时运行**，否则会互相抢占全局热键。

---

## 三、运行

### 3.1 直接使用（免 Python）

从 [Releases](https://github.com/Qign/figcraft-bridge-console/releases) 下载 `FigCraft.exe`，放到任意目录（绿色免安装）。首次运行会在 exe 同目录生成 `config.json` 与 `logs/`。

FigCraft 必须以控制端口方式启动（桥要通过 `--control 47900` 读取/写入实时文档）：

```
FigCraft.exe --control 47900
```

控制台默认监听 `47901` 端口用于唤醒已有实例——重复双击 exe 不会再起第二个进程，只会把已运行的面板唤到前台。

### 3.2 开发模式（改代码后调试）

```bat
cd /d D:\AI\FigCraft\BridgeTool
启动控制台.bat            :: 无控制台窗口启动（等价于 pythonw src\app.py）
python src\app.py         :: 带控制台运行，可直接看到日志输出
```

要求 Python 3.9+（打包脚本默认使用 `C:\Python313\python.exe`，不存在时回退到 `python`）。源码不依赖任何第三方包。

### 3.3 配置项（config.json）

| 字段 | 说明 |
|---|---|
| `port` | FigCraft 控制端口，默认 `47900` |
| `figcraft_exe` | 自定义 FigCraft 可执行文件路径（留空则自动查找） |
| `depth` | 画板递归深度，默认 `30` |
| `hotkeys.to_axure` / `hotkeys.to_figcraft` | 两个方向的热键字符串 |
| `bridges.*.enabled` / `.paused` | 各方向的启用 / 暂停状态（面板上可切换） |
| `autostart` | 是否开机自启 |
| `close_to_tray` | 关闭窗口时最小化到托盘 |
| `window` | 面板窗口上次位置 |

运行时产物：`logs/bridge-YYYYMMDD.log`（日志）、`logs/work/`（剪贴板与脚本临时文件），均已被 `.gitignore` 排除。

---

## 四、PyInstaller 打包

打包脚本：[`src/build.bat`](src/build.bat)，双击即可，或按等价命令行执行：

```bat
pip install pyinstaller
cd /d D:\AI\FigCraft\BridgeTool\src
python -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "FigCraftBridgeConsole" ^
  --icon "assets\app.ico" ^
  --add-data "assets;assets" ^
  --paths "." ^
  --hidden-import core_f2a ^
  --hidden-import core_a2f ^
  --distpath ".." ^
  --workpath "..\_build\work" ^
  --specpath "..\_build" ^
  "app.py"
```

要点：

- `--onefile --noconsole`：单文件绿色版，运行不弹黑框；
- `--add-data "assets;assets"`：图标与 `axvg_tpl.json` 模板必须随包分发，否则转换与托盘会缺资源；
- `--hidden-import core_f2a --hidden-import core_a2f`：转换核心是动态导入，必须显式声明，否则运行时 `ModuleNotFoundError`；
- 产物先输出为 `..\FigCraftBridgeConsole.exe`，脚本会自动改名为 `..\FigCraft桥控制台.exe`；
- 中间目录 `_build/`、`*.spec` 已被 `.gitignore` 排除。

---

## 五、克隆与后续开发

```bat
git clone https://github.com/Qign/figcraft-bridge-console.git
cd figcraft-bridge-console
```

换机后重新开发的完整流程：

1. 安装 Python 3.9+，确认 `python` / `pythonw` 在 PATH 中；
2. 按需修改 `src/` 下源码，用 `启动控制台.bat` 或 `python src\app.py` 调试；
3. 需要新的绿色版时，运行 `src\build.bat` 打包（产物落在仓库根，已被 `.gitignore` 排除）；
4. 提交前确认 `logs/`、`__pycache__/`、`_build/`、`*.exe` 没有被纳入版本控制。

### 发布新版本（exe 走 Releases）

仓库只存源码，二进制通过 GitHub Releases 分发：

1. 运行 `src\build.bat` 打出新的 `FigCraft桥控制台.exe`；
2. 提交源码变更并打标签：`git tag v1.0.1` 然后 `git push origin v1.0.1`；
3. 在 GitHub 仓库页面 **Releases → Draft a new release**，选择该标签，把 exe 拖进附件区后发布（附件名建议改成 `FigCraft.exe`，与既有版本保持一致）；
4. 或者用命令行一步到位（需本机装好并登录 `gh`）：

   ```bat
   copy "FigCraft桥控制台.exe" FigCraft.exe
   gh release create v1.0.1 "FigCraft.exe" --title "v1.0.1" --notes "更新说明"
   ```

旧版独立桥的用法细节见各自目录下的 `使用说明.md`。

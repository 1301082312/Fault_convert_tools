# Fault_convert_tools 断层数据转换工具

把 X15 标注流程里反复用到的几步做成一个可复用的程序，有图形界面，也有命令行：

1. **概率叠加**：把断层概率体叠加到地震 npy 上，得到 overlay npy（可同时输出 SEG-Y）
2. **npy 转 SEG-Y**：地震 npy、overlay npy 等任意三维 npy 转成 Petrel 能直接导入的 SEG-Y
3. **TS 转标签**：把从 Petrel 导出的断层面（GOCAD TSurf `.ts`）和原地震 npy 对齐，生成二值标签和/或实例标签 npy
4. **SEG-Y 转 npy**：常用道头字节可选或自动识别，支持乱序、缺道、IBM 浮点

## 启动
- 图形界面：双击 `run_gui.bat`（或 `python run_gui.py`）
- 命令行：在本文件夹下 `python -m fault_convert <overlay|segy|labels|tonpy|fixheaders> ...`
- 依赖：Python 3、numpy、segyio（tkinter 随 Python 自带）

## 坐标约定（三步共用，必须一致）
所有 npy 的轴序都是 **(inline, xline, time)**。一个数据块在原始数据体里的位置由三样东西决定：
- **起点**：数据块第一个体素在原始数据体里的 (inline, xline, sample) 下标，例如 R0009 是 `8,124,209`
- **采样间隔**：默认 2 ms
- **道距**：默认 25 m（只是编出来的坐标，不是真实工区坐标）

写进 SEG-Y 的道头：inline（字节 189）= 全局 inline 号，crossline（193）= 全局 xline 号，CDP_X（181）= xline × 道距，CDP_Y（185）= inline × 道距（缩放 −100），首样点时间 = 起点 sample × 采样间隔。
同样的值还会写进 Petrel 默认格式（"SEG-Y seismic data"）自动读取的字节：**5 = inline，17 和 21 = xline，73 / 77 = X / Y**，所以用默认格式也能直接导入。以前版本导出的 SEG-Y 可以就地补写（只改道头，不动数据）：`python -m fault_convert fixheaders 文件.sgy`
在这样的 SEG-Y 上解释、再导出的 TS，用**同一组起点/采样间隔/道距**就能精确落回 npy 下标。

如果输入 npy 旁边有 FaultRegionExtractor 的 `metadata.json`（字段 `origin`）或训练脚本写的 `info.json`（字段 `origin_global_ixt`），界面上点"从 metadata 读取"或命令行不写 `--origin`，会自动读取起点。

**Petrel 导入设置**：默认的 SEG-Y seismic data 格式一般能直接识别；也可以用 SEG-Y with preset parameters：3D；X 坐标 181，Y 坐标 185；Line detection 选 Trace header fields，Inline 189，Crossline 193。导入前可以点 Scan 核对第一道的线号。文件放在纯英文路径下（Petrel 对中文路径支持不好）。

## 1 概率叠加
```bash
python -m fault_convert overlay seismic.npy prediction.npy out/overlay_p05.npy --threshold 0.5 --segy out/overlay_p05.sgy --origin 8,124,209
```
- 地震按 |振幅| 的 99 百分位裁剪，缩放到 ±0.6；概率 ≥ 阈值的体素写成 +1；最后一个时间样点写成 −1，让 Petrel 的色标对称
- **只用于看图**：断层位置的地震值被覆盖，振幅也压缩过，不能当训练数据
- 按 inline 逐片处理、输出用内存映射，整块 X15（几 GB）也能跑；超过 6400 万体素时，裁剪百分位在抽稀的样本上估计

## 2 npy 转 SEG-Y
```bash
python -m fault_convert segy seismic.npy overlay_p05.npy --out-dir out --origin 8,124,209
```
可一次转多个文件，输出与 npy 同名的 `.sgy`。

**中文路径检查**：输出 SEG-Y 的完整路径（文件夹和文件名）只要含中文或其他非英文字符，界面会在开始前弹窗提示（默认选"否"，不输出），命令行和日志会打印警告。概率叠加勾选同时输出 SEG-Y 时也会检查。输入 npy 的路径有中文没关系。默认写完会读回来核对线号范围、时间范围，以及是否与 npy 逐值一致（`--no-verify` 跳过）。

## 3 TS 转标签
```bash
python -m fault_convert labels ts文件夹 seismic.npy out --mode both --origin 233,150,461
```
- 地震 npy 只用来确定输出尺寸（加 `--copy-seismic` 会顺便存一份 seismic.npy）
- 输出 `fault_binary.npy`（uint8，0/1）、`fault_instance.npy`（uint16，0 = 背景，1、2、… = 断层编号）和 `label_info.json`（编号 ↔ 文件名/断层名、每条断层的体素数）
- **编号顺序** = TS 文件名的自然顺序（gap_2 在 gap_10 前）；`--start-id` 指定起始编号，多段拼接时可以接着往下编
- `--inlines a,b` 只保留这一段全局 inline（拼接补缺段时用）
- **栅格化规则**：断层面三角网在 (inline, sample) 平面上插值成 xline 位置，每个格点沿 xline 标到与相邻 inline/样点的中点，至少 2 道宽；相邻 inline 跳变 > 12 道、相邻样点跳变 > 3 道不连。和 R0004/R0008/R0009/补缺段训练标签用的是同一规则
- **断层相交**的体素归先写入的那条断层（`label_info.json` 里记了每条断层被占掉的体素数）
- TS 的时间单位按文件里的 `AXIS_UNIT` 判断（秒自动换成毫秒）

注意：同一条物理断层如果在 Petrel 里分成几个对象，会得到几个编号；拼接多段时跨接缝的同一条断层编号也不同，做实例训练前要自己合并。空的 TS 或完全落在数据块外的断层会在日志和 `label_info.json` 的 `empty_or_outside` 里列出。

## 4 SEG-Y 转 npy
```bash
python -m fault_convert tonpy input.sgy out/seismic.npy                       # 自动识别字节
python -m fault_convert tonpy input.sgy out/seismic.npy --inline-byte 221 --xline-byte 21 --inlines 3508,3719 --origin-mode zero
```
- 输出 `seismic.npy`（float32，inline × xline × time）和 `seismic_info.json`（线号范围、所用字节、采样间隔、首样点时间、四角坐标、`origin_global_ixt`）
- **常用字节组合**（界面下拉框可选，"自动识别"按这个顺序试，取第一个能组成完整网格的）：

  | inline / xline | 说明 |
  | --- | --- |
  | 189 / 193 | SEG-Y rev1 标准 INLINE_3D / CROSSLINE_3D（本工具导出的 SEG-Y 就是这个） |
  | 9 / 21 | FFID / CDP |
  | 221 / 21 | 部分处理软件（X15 原始数据就是这个） |
  | 5 / 21 | 道序号(卷内) / CDP |
  | 9 / 13 | FFID / 道号(炮内) |
  | 17 / 21 | 炮点号 / CDP |
  | 213 / 21 | 213 / CDP |
  | 1 / 5 | 道序号 / 道序号(卷内) |

  坐标字节：181/185（CDP X/Y）、73/77（炮点 X/Y）、81/85（检波点 X/Y），缩放系数读 71 字节。都不对时选"自定义"手填
- 界面上的"扫描道头"会列出所有能组成网格的字节组合、各自的线号范围和完整度
- 按道头线号把每一道放到网格上，所以**排序无所谓**；缺道填 0（可改），并另存 `*_trace_mask.npy`（1 = 有道）
- IBM 浮点和 IEEE 浮点都支持；道头一次性内存映射读取，几 GB 的文件也很快
- **起点**：选"按线号"时 `origin_global_ixt` = (第一条 inline 号, 第一条 xline 号, 首样点时间 / 采样间隔)，本工具导出的 SEG-Y 转回来与原 npy 完全一致、起点也一致；外来数据想让数组下标从 0 开始就选"从 0 开始"
- 线号间隔不是 1 或不均匀时会给出警告（数组下标 ≠ 线号 − 起点）

## 验证
回归测试用你自己的参考数据（以前用同样规则做出的 SEG-Y / 标签）检查本工具能否逐位复现，路径通过参数或环境变量传入，仓库里不含任何数据：
```bash
python tests/test_against_x15.py --help
```
`tests/run_local_x15.bat` 是用环境变量传路径的示例，复制成 `tests/local_*.bat`（已被 git 忽略）改成自己的路径即可。

作者用 X15 数据跑过（2026-11-22，全部通过）：
1. 样本地震转出的 SEG-Y 与之前导入 Petrel 的文件完全相同（道数据、道头、卷头）
2. 概率叠加的 SEG-Y 完全相同
3. 27 个 TS → 二值标签逐体素相同；实例标签（起始编号 136）与拼接体实例标签的对应段相同
4. 15 个 TS（只保留 inline 220–232，起始编号 121）→ 与拼接体实例标签的对应段相同

## 文件
```
run_gui.bat / run_gui.py   图形界面入口
fault_convert/
  grid.py      起点/采样间隔/道距，读 metadata
  overlay.py   概率叠加
  segy.py      写 SEG-Y、读回核对
  tsurf.py     读 TS、断层面栅格化、二值/实例标签
  segy_read.py SEG-Y 转 npy、道头字节识别
  dnd_win.py   Windows 拖放
  jobs.py      三个任务（界面和命令行共用）
  cli.py       命令行
  gui.py       图形界面
tests/test_against_x15.py  回归测试（参考数据路径用参数传）
tests/run_local_x15.bat    传路径的示例
```

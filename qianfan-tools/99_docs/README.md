# 千帆素材库（本地预处理 → 上传）

工具根目录：`D:\DSH\social-auto-upload\QianFan-Sync\qianfan-tools`
素材根目录：`E:\千帆素材库`（视频数据保留在原位置，未迁移）

> 工具已纳入 QianFan-Sync 仓库的 `qianfan-tools/`，脚本与素材分离。
> 素材目录由 `90_tools/config.json` 的 `lib_root` 指定，也可用环境变量 `QF_LIB_ROOT` 覆盖。

## 设计原则

- 每个视频 = 一个独立目录，目录名固定格式 `v_YYYYMMDD_NNN`，方便脚本排序、去重、断点续传。
- 目录内**文件名全部固定**，脚本不猜文件名，不解析中文文件名。
- 元数据用纯文本 + JSON：人能直接改，脚本能稳定读。
- 状态靠目录表达：`01_inbox` → `02_uploaded` / `03_failed`，不需要维护额外状态表。

## 目录结构

```text
D:\DSH\social-auto-upload\QianFan-Sync\qianfan-tools\   ← 工具根（随仓库版本管理）
├─ 00_review\                # 离线校对页 index.html 与修改表 edits.csv
├─ 00_template\v_0000\       # 新视频模板，只放模板文件，不放真实视频
├─ 90_tools\
│   ├─ qianfan_lib.py        # 主脚本
│   ├─ prepare_batch.py      # 散放视频 → 标准目录 + 4 张带边框封面
│   ├─ review_batch.py       # 生成离线校对页
│   ├─ run.bat               # Windows 双击/命令行入口
│   └─ config.json           # 服务地址、lib_root、平台列表等
├─ 99_docs\README.md         # 本说明
└─ 横屏边框*.png / 竖屏边框*.png   # 4 张封面边框图

E:\千帆素材库\                    ← 素材根（视频数据，保留原位置，不进仓库）
├─ 01_inbox\                 # 待上传：处理好的视频放这里
│   └─ v_20261125_001\
├─ 02_uploaded\              # 上传成功：整个目录搬到这里
└─ 03_failed\                # 上传失败：修完用 retry 重试
```

## 单个视频目录的固定文件

| 文件名 | 必需 | 说明 |
|--------|------|------|
| `video.mp4` | 是 | 视频本体。也可用 `.mov/.avi/.mkv/.webm/.flv/.m4v` 等扩展名，但脚本优先找 `video.mp4`。 |
| `cover.jpg` | 是 | 封面原图。脚本会在本地裁成 4 种比例后上传。 |
| `title.txt` | 是 | 标题，一行，不要加引号。 |
| `description.txt` | 否 | 描述，可多行。 |
| `category.txt` | 否 | 素材分类，一行一个分类名（如 `AI动画` / `朗读`）。也可上传时用 `--category` 覆盖。 |
| `tags.txt` | 否 | 标签，每行一个；`#` 前缀会自动去掉。默认：`#AI动画` / `#古风` / `#萌娃`。 |
| `activities.json` | 否 | 官方活动，字符串数组，最多 5 个，默认 `[]`。填**活动名**，不是 ID。例：`["夏日活动", "创作激励"]` |
| `hotspot.json` | 否 | 关联热点，对象或 `null`，默认 `null`。至少含 `word` 字段，其余字段原样保存。例：`{"word":"热点词","hot_value":123}` |
| `declaration.json` | 否 | 自主声明，默认 `{"aiContent":"内容由AI生成","isOriginal":false}`。 |
| `source.txt` | 自动 | 批量预处理写入的原始文件名。视频本地固定叫 `video.mp4`，但上传时会用这里的名字作为素材库显示名/检索名，**不要删除**。 |
| `manifest.json` | 自动 | 脚本上传后写入的结果记录（素材 ID、封面路径、草稿 ID），**不要手改**。 |

### 封面比例

脚本优先读取同目录下已裁好的文件：

- `cover_4x3.jpg` → 1920×1440（横版封面 `coverLandscape`）
- `cover_16x9.jpg` → 1920×1080（`coverLandscape169`）
- `cover_3x4.jpg` → 1440×1920（竖版封面 `coverPortrait`）
- `cover_9x16.jpg` → 1080×1920（`coverPortrait916`）

如果这四个文件不全，脚本会用 `cover.jpg` 在**本地按中心裁剪**自动生成缺失的比例，再上传。生成算法与 QianFan-Sync 后端一致。

## 工作流程

1. 新建视频目录：

   ```bat
   cd /d D:\DSH\social-auto-upload\QianFan-Sync\qianfan-tools\90_tools
   run.bat new v_20261125_001
   ```

2. 把视频改名为 `video.mp4`、封面改名为 `cover.jpg` 放进 `01_inbox\v_20261125_001\`。

3. 编辑 `title.txt` / `description.txt` / `tags.txt` / `activities.json` / `hotspot.json` / `declaration.json`。

4. 先校验（不联网）：

   ```bat
   run.bat check
   ```

5. 正式上传：

   ```bat
   run.bat upload
   ```

   如果 `01_inbox` 里是**散放的 `.mp4`**（还没生成视频目录），直接**双击 `run.bat`** 即可：脚本会依次执行「预处理 → 校验 → 上传 → 重试」，结束后停在"请按任意键继续"，不会闪退。带参数的用法（如 `run.bat upload --limit 1`）保持不变，适合单独执行某一步。

   **素材分类**：
   - 分类名直接写在 `run.bat` 第 7 行 `set "QF_CATEGORY=AI动画"`，改引号内的值即可（留空则不设置分类）。
   - 无论双击完整流程还是带参数执行（`run.bat upload` / `retry`），脚本都会自动加上 `--category`。若命令行显式指定了 `--category`（如 `run.bat upload --category "朗读"`），则以命令行为准。
   - 视频目录内 `category.txt`（写一行分类名，如 `朗读`）仍可作为单个素材的分类来源，但优先级最低。

   上传会依次：
   - 把视频传到 QianFan-Sync 素材库（`/api/materials/upload`）
   - 把 4 张封面传到 `data\covers\`（`/api/materials/covers/upload`，**不进素材库列表**）
   - 把带边框封面绑定为该视频素材的缩略图（`/api/materials/<id>/thumbnail`，竖版取 3:4、其余取 4:3）；素材管理页卡片因此显示带边框封面，而不是 ffmpeg 抽帧的裸画面
   - 用标题/描述/标签/活动/热点/声明创建一条视频草稿（`/api/v2/drafts`）
   - 写 `manifest.json`，然后把整个目录移到 `02_uploaded\`

6. 打开 QianFan-Sync 发布中心的「草稿箱」，选中草稿、勾选发布账号，即可发布。

失败目录会进 `03_failed\`，修好后：

```bat
run.bat retry
```

## 批量预处理（01_inbox 散放 mp4）

如果 `01_inbox` 里直接放了一批散装的 `.mp4`（没有视频目录），先用下面三个脚本整理，再上传。`prepare` / `review` 完全离线；只有 `upload_all.bat` 需要后端已启动。

```bat
cd /d D:\DSH\social-auto-upload\QianFan-Sync\qianfan-tools\90_tools
run.bat prepare --dry-run     REM 预览解析结果，不写文件
run.bat prepare               REM 正式生成标准目录 + 四张带边框封面
run.bat review                REM 生成离线校对页 00_review\index.html
REM 打开校对页，改标题/标签/描述，点“下载 edits.csv”，保存到 00_review\edits.csv
run.bat review --apply        REM 把 edits.csv 写回各视频目录
upload_all.bat                REM check -> upload -> retry，日志见 90_tools\upload.log
```

### prepare_batch.py 规则

- 只处理 `01_inbox` 顶层的散放视频，不碰已有 `v_*` 目录。
- 目录名 `v_YYYYMMDD_NNN`，按文件修改时间取日期、按顺序编号；`prepared_index.json` 记录已处理文件，重复运行自动跳过，不会重复建目录。
- 标题解析：
  - `标题#标签#标签` → 第一个 `#` 前是标题；
  - `#标签_标题` → 取最后一个 `_` 后作为标题；
  - 去掉 `[愉快]` / `[呲牙]` 等表情串和开头装饰符；
  - 没标题或标题为「未命名/无标题」时写 `未命名_<ID>`，在报告与校对页标记「需补标题」。
- 标签：取全部 `#xxx` 并去重；文件名没有标签时用默认 `#AI动画 / #古风 / #萌娃`。
- 额外生成 `source.txt` 记录原始文件名；生成 `90_tools\prepare_report.csv` 汇总每个文件的处理结果。
- 参数：`--dry-run`、`--limit N`、`--copy`（复制而非移动）、`--cover-time 00:00:05`、`--reset-index`。
- `source.txt` 里的原始文件名会作为上传时的 multipart 文件名，素材库列表显示与关键词检索都按它走；因此虽然本地视频统一叫 `video.mp4`，素材库里仍是带标题的原名，不会被搜成一堆 `video.mp4`。

### 封面规则

- 视频旁若有同名图片（`xxx.jpg` 等），优先作为封面原图；否则 ffmpeg 抽帧，默认取 `min(3 秒, 时长/2)`，失败依次回退 1 秒、首帧。
- `cover.jpg` 保存原帧；按 4 种比例中心裁剪后叠加对应边框，生成 `cover_4x3.jpg` / `cover_16x9.jpg` / `cover_3x4.jpg` / `cover_9x16.jpg`。这 4 张齐全后，上传脚本直接上传，不再二次裁剪。

| 边框文件（qianfan-tools 根目录） | 对应封面 | 尺寸 |
|---|---|---|
| `横屏边框43.png` | `cover_4x3.jpg` | 1920×1440 |
| `横屏边框.png` | `cover_16x9.jpg` | 1920×1080 |
| `竖屏边框34.png` | `cover_3x4.jpg` | 1440×1920 |
| `竖屏边框.png` | `cover_9x16.jpg` | 1080×1920 |

- 边框缺失时退化为无边框封面，并在报告里记 warning，不中断批量。
- 上传时脚本会把这 4 张带边框封面关联到素材（`POST /api/materials/<id>/covers`）。网页发布页从素材库选视频时**直接复用这 4 张本地封面**，不会再抽帧重新裁剪，所以边框不会丢；旧素材没有关联封面时发布页留空，需手动设置。
- 单条重抽：`run.bat review --cover v_YYYYMMDD_NNN --time 00:00:05`。

### review_batch.py 规则

- 生成 `00_review\index.html`：本地网页列出封面、视频预览和元数据，可直接编辑。
- 首次运行生成 `00_review\edits.csv`；网页编辑后点「下载 edits.csv」覆盖该文件，再 `run.bat review --apply` 写回。
- `edits.csv` 里 `tags` / `activities` 用 `|` 分隔；`hotspot` / `declaration` 填 JSON；`__CLEAR__` 表示清空该字段。
- 想用当前目录内容重新生成 edits.csv：`run.bat review --force-edits`。

## 配置

`90_tools\config.json`：

```json
{
  "lib_root": "E:\\千帆素材库",
  "base_url": "http://localhost:5409",
  "create_draft": true,
  "platforms": ["douyin"],
  "timeout_seconds": 180,
  "chunk_size_mb": 1,
  "move_after_upload": true
}
```

- `lib_root`：视频素材根目录（`01_inbox` / `02_uploaded` / `03_failed` 的父目录）。优先级：环境变量 `QF_LIB_ROOT` > 此项 > 默认 `E:\千帆素材库`。换机器时改这里即可，不用改脚本。
- `base_url`：QianFan-Sync 后端地址，默认本机 5409。确保后端已启动。
- `create_draft`：设为 `false` 则只传素材和封面，不建草稿。
- `platforms`：草稿里预填哪些平台配置；默认只有 `douyin`。加 `"xiaohongshu"` 等会把标题/描述/标签同步预填到该平台，但活动和热点字段目前只写入抖音。
- `move_after_upload`：设为 `false` 则上传后目录留在 `01_inbox`，方便观察 `manifest.json`。

## 字段对应关系（抖音草稿）

| 本地文件 | 草稿字段 |
|----------|----------|
| `title.txt` | `platformConfigs.douyin.title` |
| `description.txt` | `platformConfigs.douyin.description` |
| `tags.txt` | `platformConfigs.douyin.tags` |
| `activities.json` | `platformConfigs.douyin.activityId` |
| `hotspot.json` 的 `word` | `platformConfigs.douyin.hotspotId`，整个对象存 `hotspotData` |
| `declaration.json` 的 `aiContent` | `platformConfigs.douyin.aiContent`（自主声明） |
| `declaration.json` 的 `isOriginal` | `platformConfigs.douyin.isOriginal` |

## 注意

- 脚本使用 QianFan-Sync 后端虚拟环境（自带 Pillow 和 requests）。如果换机器，把 `run.bat` 里的 `PY` 路径改掉即可。
- 官方活动和关联热点是**发布时按账号拉取**的，本地保存的是活动名/热点词；草稿创建成功后仍需在发布界面确认对应账号能拉到同名活动或热点。
- 不要直接删除或重命名 `manifest.json`；重试时脚本会覆盖它。
- 网页发布页默认值：标签 `AI动画 / 古风 / 萌娃`；抖音自主声明「内容由AI生成」；快手作者声明「内容为AI生成」，「允许下载此作品」默认关闭。已在草稿里保存的值不会被默认值覆盖。
- 素材卡片缩略图接口是 QianFan-Sync 后端新增的；如果后端还是旧进程，需先重启后端再上传，否则会打印「缩略图绑定跳过」并继续显示无边框的抽帧图。
- 「视频发布 → 添加视频 → 从素材库选择」弹窗里，每张素材卡片左下角会显示发布状态：绿色「已发布」/ 灰色「未发布」。依据是发布记录中的素材 ID，已发布的素材仍保留在库中，可重复发布。
- 本工具只做「上传素材 + 建草稿」，不自动发布，避免误发。

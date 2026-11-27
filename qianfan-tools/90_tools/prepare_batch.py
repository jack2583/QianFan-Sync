#!/usr/bin/env python3
"""把 01_inbox 顶层散放的 mp4 批量整理成上传脚本可识别的标准目录。

纯离线脚本：不连接 QianFan-Sync，只做本地文件处理。

主要动作：
  1. 解析文件名 -> title.txt / tags.txt
  2. 生成 v_YYYYMMDD_NNN 目录，视频改名为 video.mp4
  3. ffmpeg 抽帧，按 4 种比例叠加对应边框，生成 cover_*.jpg
  4. 写入模板元数据、source.txt、prepare_report.csv

用法：
  python prepare_batch.py --dry-run
  python prepare_batch.py
  python prepare_batch.py --limit 5 --copy
  python prepare_batch.py --cover-time 00:00:05
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image

import qianfan_lib as ql

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "90_tools"
INDEX_PATH = TOOLS / "prepared_index.json"
REPORT_PATH = TOOLS / "prepare_report.csv"

DEFAULT_TAGS = ["AI动画", "古风", "萌娃"]
PLACEHOLDERS = {"", "未命名", "未命名视频", "新建视频", "无标题", "untitled", "null", "none"}
DECOR = "•✨✔️“”\"'` \t-_"

# 本地边框图：按输出封面文件名一一对应
BORDER_BY_FILENAME = {
    "cover_4x3.jpg": ROOT / "横屏边框43.png",
    "cover_16x9.jpg": ROOT / "横屏边框.png",
    "cover_3x4.jpg": ROOT / "竖屏边框34.png",
    "cover_9x16.jpg": ROOT / "竖屏边框.png",
}

REPORT_FIELDS = ["source", "id", "title", "tags", "status", "note"]


# ───────────────────────── 基础工具 ─────────────────────────

def find_bin(name: str) -> str | None:
    p = shutil.which(name)
    if p:
        return p
    base = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if base.exists():
        for d in base.glob("Gyan.FFmpeg*/**/bin"):
            candidate = d / name
            if candidate.exists():
                return str(candidate)
    return None


def clean_emoji(text: str) -> str:
    """去掉 [愉快] / [呲牙] 这类表情占位符。"""
    return re.sub(r"\[[^\]]*\]", "", text).strip()


def clean_decor(text: str) -> str:
    return clean_emoji(text).strip(DECOR)


def probe_duration(video: Path, ffprobe: str | None) -> float | None:
    if not ffprobe:
        return None
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return float(r.stdout.strip())
    except Exception:
        pass
    return None


def fmt_time(seconds: float) -> str:
    return f"{max(0.0, seconds):.3f}"


def parse_time_arg(value: str | None) -> str | None:
    """接受 5 / 5.5 / 00:00:05，统一转成 ffmpeg 可用的秒数字符串。"""
    if not value:
        return None
    value = value.strip()
    if ":" in value:
        parts = value.split(":")
        try:
            total = 0.0
            for part in parts:
                total = total * 60 + float(part)
            return fmt_time(total)
        except ValueError:
            return value
    try:
        return fmt_time(float(value))
    except ValueError:
        return value


def extract_frame(video: Path, out_path: Path, cover_time: str | None = None) -> str:
    """从视频抽一帧到 cover.jpg，返回实际使用的时间点说明。"""
    ffmpeg = find_bin("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg，请确认已安装并加入 PATH")

    if cover_time:
        candidates = [cover_time]
    else:
        ffprobe = find_bin("ffprobe")
        duration = probe_duration(video, ffprobe)
        t = min(3.0, duration / 2) if duration and duration > 0 else 3.0
        candidates = [fmt_time(t), "1", "0"]

    last_err = ""
    for t in candidates:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(
                [ffmpeg, "-y", "-ss", str(t), "-i", str(video),
                 "-frames:v", "1", "-q:v", "2", str(out_path)],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                return str(t)
            last_err = (r.stderr or "").strip()[-300:]
        except Exception as exc:
            last_err = str(exc)
    raise RuntimeError(f"ffmpeg 抽帧失败: {last_err}")


def use_sidecar_cover(video: Path, out_path: Path) -> bool:
    """如果视频旁有同名图片，优先用它作为封面原图。"""
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        p = video.with_suffix(ext)
        if p.exists() and p.resolve() != out_path.resolve():
            try:
                im = Image.open(p).convert("RGB")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                im.save(out_path, "JPEG", quality=92)
                return True
            except Exception:
                continue
    return False


def center_crop_resize(img: Image.Image, tw: int, th: int) -> Image.Image:
    """与 qianfan_lib.make_cover_variants 一致的中心裁剪逻辑。"""
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    crop_w, crop_h = min(sw, tw / scale), min(sh, th / scale)
    left, top = (sw - crop_w) / 2, (sh - crop_h) / 2
    box = (round(left), round(top), round(left + crop_w), round(top + crop_h))
    return img.crop(box).resize((tw, th), Image.LANCZOS)


def compose_bordered_covers(cover_path: Path, item: Path) -> list[str]:
    """按 4 种比例裁剪原帧并叠加对应边框，直接写成 cover_*.jpg。"""
    warnings: list[str] = []
    src = Image.open(cover_path).convert("RGBA")
    src.load()
    for key, (tw, th, filename) in ql.COVER_RATIOS.items():
        frame = center_crop_resize(src, tw, th)
        border_path = BORDER_BY_FILENAME.get(filename)
        if border_path and border_path.exists():
            try:
                border = Image.open(border_path).convert("RGBA")
                border = border.resize((tw, th), Image.LANCZOS)
                out = Image.alpha_composite(frame, border).convert("RGB")
            except Exception as exc:
                warnings.append(f"{filename} 边框叠加失败，已用无边框封面: {exc}")
                out = frame.convert("RGB")
        else:
            warnings.append(f"缺少边框 {border_path.name if border_path else filename}，已用无边框封面")
            out = frame.convert("RGB")
        out.save(item / filename, "JPEG", quality=92)
    return warnings


def parse_filename(video: Path, item_id: str) -> tuple[str, list[str], bool]:
    """返回 (标题, 标签列表, 是否需人工补标题)。"""
    stem = clean_emoji(video.stem)
    first_hash = stem.find("#")

    if first_hash == 0:
        # 标签在前：用最后一个 _ 分隔出真正的标题
        if "_" in stem:
            head, tail = stem.rsplit("_", 1)
            tags_part, title_raw = head, tail
        else:
            tags_part, title_raw = stem, ""
    elif first_hash > 0:
        title_raw = stem[:first_hash]
        tags_part = stem[first_hash:]
    else:
        title_raw = stem
        tags_part = ""

    title = clean_decor(title_raw)
    need_manual = False
    if title.lower() in PLACEHOLDERS:
        title = f"未命名_{item_id}"
        need_manual = True

    tags: list[str] = []
    for m in re.finditer(r"#([^#]+)", tags_part):
        tag = clean_emoji(m.group(1)).strip().strip("_- ")
        tag = tag.strip(DECOR)
        if tag and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag)
    if not tags:
        tags = list(DEFAULT_TAGS)

    return title, tags, need_manual


# ───────────────────────── 索引与报告 ─────────────────────────

def load_index() -> dict:
    if not INDEX_PATH.exists():
        return {}
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_index(index: dict) -> None:
    TOOLS.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_report(rows: list[dict], path: Path | None = None) -> None:
    TOOLS.mkdir(parents=True, exist_ok=True)
    path = path or REPORT_PATH
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def used_ids(index: dict) -> set[str]:
    ids = set(index.values())
    for directory in (ql.INBOX, ql.UPLOADED, ql.FAILED):
        if directory.exists():
            ids.update(p.name for p in directory.iterdir() if p.is_dir())
    return ids


def next_id(mtime: float, used: set[str]) -> str:
    date = datetime.fromtimestamp(mtime).strftime("%Y%m%d")
    n = 1
    while True:
        item_id = f"v_{date}_{n:03d}"
        if item_id not in used and not any((d / item_id).exists() for d in (ql.INBOX, ql.UPLOADED, ql.FAILED)):
            used.add(item_id)
            return item_id
        n += 1


# ───────────────────────── 主流程 ─────────────────────────

def write_meta_files(item: Path, source_name: str, title: str, tags: list[str]) -> None:
    for name, content in ql.TEMPLATE_FILES.items():
        p = item / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")
    (item / "title.txt").write_text(title + "\n", encoding="utf-8")
    (item / "description.txt").write_text("", encoding="utf-8")
    (item / "tags.txt").write_text("\n".join("#" + t for t in tags) + "\n", encoding="utf-8")
    (item / "source.txt").write_text(source_name + "\n", encoding="utf-8")


def prepare_one(video: Path, args, index: dict, used: set[str]) -> dict:
    source_name = video.name
    item_id = index.get(source_name)
    if item_id and (ql.INBOX / item_id).exists():
        return {"source": source_name, "id": item_id, "title": "", "tags": "",
                "status": "skipped", "note": "已处理过，跳过"}

    if item_id:
        index.pop(source_name, None)  # 索引存在但目录没了，重新生成
        item_id = None

    try:
        mtime = video.stat().st_mtime
    except OSError:
        mtime = datetime.now().timestamp()
    item_id = item_id or next_id(mtime, used)
    title, tags, need_manual = parse_filename(video, item_id)
    note_parts = []
    if need_manual:
        note_parts.append("需补标题")

    if args.dry_run:
        return {"source": source_name, "id": item_id, "title": title,
                "tags": "|".join(tags), "status": "would_prepare",
                "note": "; ".join(note_parts) or "dry-run"}

    item = ql.INBOX / item_id
    item.mkdir(parents=True, exist_ok=False)
    try:
        cover_path = item / "cover.jpg"
        # 同目录同名图片要在移动视频之前检查
        sidecar_used = False
        if not cover_path.exists():
            sidecar_used = use_sidecar_cover(video, cover_path)

        target_video = item / "video.mp4"
        if args.copy:
            shutil.copy2(video, target_video)
        else:
            shutil.move(str(video), str(target_video))

        if not cover_path.exists():
            used_t = extract_frame(target_video, cover_path, args.cover_time)
            note_parts.append(f"抽帧 {used_t}s")
        elif sidecar_used:
            note_parts.append("使用同名图片封面")

        warnings = compose_bordered_covers(cover_path, item)
        note_parts.extend(warnings)

        write_meta_files(item, source_name, title, tags)
        index[source_name] = item_id

        return {"source": source_name, "id": item_id, "title": title,
                "tags": "|".join(tags), "status": "prepared",
                "note": "; ".join(note_parts)}
    except Exception as exc:
        # 失败时保留目录，报告里写清楚原因；不回滚已移动的视频
        return {"source": source_name, "id": item_id, "title": title,
                "tags": "|".join(tags), "status": "error", "note": str(exc)}


def cmd_prepare(args) -> int:
    if args.reset_index:
        index = {}
        save_index(index)
    else:
        index = load_index()

    used = used_ids(index)
    videos = sorted(
        (p for p in ql.INBOX.iterdir() if p.is_file() and p.suffix.lower() in ql.VIDEO_EXTS),
        key=lambda p: (p.stat().st_mtime, p.name),
    ) if ql.INBOX.exists() else []

    if args.limit:
        videos = videos[: args.limit]

    args.cover_time = parse_time_arg(args.cover_time)
    report_path = TOOLS / ("prepare_report.dryrun.csv" if args.dry_run else "prepare_report.csv")
    rows: list[dict] = []

    # 逐个落盘：中途中断也不会丢掉已经处理好的视频索引
    for v in videos:
        row = prepare_one(v, args, index, used)
        rows.append(row)
        if not args.dry_run:
            save_index(index)
            write_report(rows, report_path)

    for row in rows:
        print(f"[{row['status']}] {row['id']}  {row['source']}  ->  {row['title']}")
        if row["note"]:
            print(f"        {row['note']}")

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("\n汇总: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"报告: {report_path}")
    return 1 if counts.get("error") else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="批量整理 01_inbox 中的散放视频")
    parser.add_argument("--dry-run", action="store_true", help="只预览解析结果，不写文件")
    parser.add_argument("--limit", type=int, help="只处理前 N 个视频")
    parser.add_argument("--copy", action="store_true", help="复制视频而不是移动")
    parser.add_argument("--cover-time", help="抽帧时间点，如 5 / 00:00:05")
    parser.add_argument("--reset-index", action="store_true", help="清空已处理索引后重新处理")
    args = parser.parse_args()
    return cmd_prepare(args)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""逐个视频跑完整流程：预处理 -> 校验 -> 上传 -> 失败重试。

与旧版 run.bat 的「先全部 prepare、再全部 check、再全部 upload」不同，
这里严格按视频串行：一个视频彻底结束（成功移入 02_uploaded，
或重试后仍失败移入 03_failed），才处理下一个视频。

单个视频异常只影响它自己，不会因为某一个目录不合格就中止整批上传。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import qianfan_lib as ql
import prepare_batch as pb


def ping_server(cfg: dict) -> None:
    """上传前预检，失败直接抛异常。"""
    ql.request_json("GET", "/api/materials/categories", None, cfg)


def repair_meta(item: Path) -> bool:
    """补齐被中断的预处理目录缺失的元数据文件。返回是否做了修复。"""
    title_path = item / "title.txt"
    if title_path.exists() and title_path.read_text(encoding="utf-8").strip():
        return False

    src_path = item / "source.txt"
    source = ql.read_text(src_path) if src_path.exists() else ""
    had_source = bool(source)
    if not had_source:
        source = f"{item.name}.mp4"
        src_path.write_text(source + "\n", encoding="utf-8")

    for name, content in ql.TEMPLATE_FILES.items():
        p = item / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")

    if had_source:
        title, tags, _need_manual = pb.parse_filename(Path(source), item.name)
        if not title or title.lower() in pb.PLACEHOLDERS:
            title = f"未命名_{item.name}"
    else:
        title = f"未命名_{item.name}"
        tags = list(pb.DEFAULT_TAGS)

    title_path.write_text(title + "\n", encoding="utf-8")
    (item / "description.txt").write_text("", encoding="utf-8")
    (item / "tags.txt").write_text(
        "\n".join("#" + t for t in tags) + "\n", encoding="utf-8"
    )
    print(f"  [修复] 补齐缺失元数据: {item.name} | 标题 {title}")
    return True


def check_one(item: Path):
    """只校验当前这一个视频目录。"""
    meta = ql.read_meta(item)
    variants = ql.make_cover_variants(meta)
    return meta, variants


def locate_failed(item: Path) -> Path:
    """process_item 失败后目录可能带时间戳后缀，找回它。"""
    exact = ql.FAILED / item.name
    if exact.exists():
        return exact
    matches = sorted(ql.FAILED.glob(item.name + "_*"))
    return matches[-1] if matches else item


def process_one(item: Path, cfg: dict, category: str | None,
                retries: int, dry_run: bool) -> bool:
    """校验 -> 上传 -> 按需重试，全部针对同一个视频。"""
    print(f"\n=== 处理 {item.name} ===")
    repair_meta(item)

    if dry_run:
        try:
            meta, variants = check_one(item)
            print(f"  [dry-run] 校验通过: {meta['title'][:40]} | 封面 {len(variants)} 比例")
            print("  [dry-run] 跳过上传")
            return True
        except Exception as exc:
            print(f"  [dry-run] 校验失败: {exc}")
            return False

    try:
        meta, variants = check_one(item)
        print(f"  校验通过: {meta['title'][:40]} | 封面 {len(variants)} 比例")
    except Exception as exc:
        print(f"  校验失败: {exc}")
        # 交给 process_item 写失败 manifest 并移入 03_failed
        ql.process_item(item, cfg, ql.UPLOADED, ql.FAILED, category=category)
        return False

    ok = ql.process_item(item, cfg, ql.UPLOADED, ql.FAILED, category=category)
    attempt = 0
    while not ok and attempt < retries:
        attempt += 1
        retry_item = locate_failed(item)
        print(f"  [重试 {attempt}/{retries}] {retry_item.name}")
        ok = ql.process_item(retry_item, cfg, ql.UPLOADED, ql.FAILED, category=category)
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="逐个视频完成预处理、校验、上传和重试")
    parser.add_argument("--category", help="素材分类，覆盖目录内 category.txt")
    parser.add_argument("--retries", type=int, default=1, help="上传失败后的重试次数，默认 1")
    parser.add_argument("--limit", type=int, help="本次最多处理 N 个视频")
    parser.add_argument("--dry-run", action="store_true", help="只校验不上传")
    parser.add_argument("--cover-time", help="新视频抽帧时间点，如 5 / 00:00:05")
    args = parser.parse_args()

    # prepare_one 会用到这两个字段
    args.copy = False
    args.reset_index = False
    args.cover_time = pb.parse_time_arg(args.cover_time)
    retries = max(0, args.retries)

    cfg = ql.load_config()
    if not args.dry_run:
        try:
            ping_server(cfg)
            print(f"[pre] 服务器连接正常: {cfg.get('base_url')}")
        except Exception as exc:
            print(f"[pre] 无法连接服务器: {exc}")
            print("请先启动 QianFan-Sync 后端（start.bat），再重试。")
            return 1

    index = pb.load_index()
    used = pb.used_ids(index)
    report_rows: list[dict] = []
    done = 0
    ok_count = 0
    fail_count = 0

    # 阶段 1：已经预处理好的目录，每个目录独立走完校验/上传/重试
    for item in ql.iter_items(ql.INBOX):
        if args.limit and done >= args.limit:
            break
        done += 1
        if process_one(item, cfg, args.category, retries, args.dry_run):
            ok_count += 1
        else:
            fail_count += 1
            print(f"  [失败] {item.name} 已留在失败列表，继续处理下一个视频")

    # 阶段 2：01_inbox 顶层仍散放的视频，prepare 一个就立刻上传一个
    videos = sorted(
        (p for p in ql.INBOX.iterdir() if p.is_file() and p.suffix.lower() in ql.VIDEO_EXTS),
        key=lambda p: (p.stat().st_mtime, p.name),
    ) if ql.INBOX.exists() else []

    for video in videos:
        if args.limit and done >= args.limit:
            break
        done += 1
        old_id = index.get(video.name)
        if old_id and any((d / old_id).exists() for d in (ql.INBOX, ql.UPLOADED, ql.FAILED)):
            row = {"source": video.name, "id": old_id, "title": "", "tags": "",
                   "status": "skipped", "note": "已处理过，跳过"}
        else:
            row = pb.prepare_one(video, args, index, used)
        report_rows.append(row)
        print(f"[prepare] {row['status']} {row['id']} {row['source']} -> {row['title']}")
        if row["note"]:
            print(f"          {row['note']}")
        if not args.dry_run:
            pb.save_index(index)
            pb.write_report(report_rows)

        if row["status"] == "error":
            fail_count += 1
            print(f"  [失败] 预处理失败: {row['source']}，继续处理下一个视频")
        elif row["status"] == "would_prepare":
            ok_count += 1
        else:
            item = ql.INBOX / row["id"]
            if process_one(item, cfg, args.category, retries, args.dry_run):
                ok_count += 1
            else:
                fail_count += 1
                print(f"  [失败] {item.name} 已留在失败列表，继续处理下一个视频")

    print("\n" + "=" * 56)
    print(f"逐个视频流程结束: 成功 {ok_count} / 失败 {fail_count} / 共 {done}")
    if fail_count:
        print("失败的视频可在 03_failed 查看；修复后单独运行 run.bat retry 即可。")
    print("=" * 56)
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())

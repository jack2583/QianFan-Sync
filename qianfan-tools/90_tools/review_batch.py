#!/usr/bin/env python3
"""生成离线校对网页，并可把修改写回各视频目录。

纯离线脚本：不连接 QianFan-Sync。

用法：
  python review_batch.py                         生成 00_review/index.html 和 edits.csv
  python review_batch.py --apply                 把 edits.csv 的修改写回视频目录
  python review_batch.py --cover v_20261125_001 --time 00:00:05   重抽该视频封面并叠边框
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import qianfan_lib as ql
import prepare_batch as pb

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "00_review"
HTML_PATH = REVIEW / "index.html"
EDITS_PATH = REVIEW / "edits.csv"

EDIT_FIELDS = ["id", "title", "description", "tags", "activities", "hotspot", "declaration"]
CLEAR = "__CLEAR__"

HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>千帆素材库 · 离线校对</title>
<style>
  body {{ font-family: "Microsoft YaHei", sans-serif; margin: 0; background: #f6f7fb; color: #222; }}
  header {{ background: #fff; border-bottom: 1px solid #e3e5ec; padding: 16px 24px; position: sticky; top: 0; z-index: 2; }}
  h1 {{ margin: 0 0 6px; font-size: 20px; }}
  .hint {{ color: #666; font-size: 13px; line-height: 1.7; }}
  button {{ background: #2d6cdf; color: #fff; border: 0; border-radius: 6px; padding: 9px 16px; font-size: 14px; cursor: pointer; }}
  .wrap {{ padding: 20px 24px 60px; max-width: 1400px; margin: 0 auto; }}
  .card {{ background: #fff; border: 1px solid #e3e5ec; border-radius: 10px; padding: 16px; margin-bottom: 18px; }}
  .card h2 {{ font-size: 16px; margin: 0 0 10px; }}
  .badge {{ display: inline-block; background: #fff2cc; color: #9a6700; border-radius: 4px; padding: 2px 8px; font-size: 12px; margin-left: 8px; }}
  .media {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }}
  video {{ width: 100%; max-height: 320px; background: #000; border-radius: 6px; }}
  .covers {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }}
  .covers figure {{ margin: 0; }}
  .covers img {{ width: 100%; display: block; border-radius: 4px; border: 1px solid #ddd; }}
  .covers figcaption {{ font-size: 11px; color: #888; text-align: center; }}
  .fields {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }}
  label {{ font-size: 12px; color: #666; display: block; margin-bottom: 4px; }}
  textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #d5d8e0; border-radius: 5px; padding: 7px; font-size: 13px; font-family: inherit; resize: vertical; }}
  textarea.short {{ height: 34px; }}
  textarea.mid {{ height: 70px; }}
</style>
</head>
<body>
<header>
  <h1>千帆素材库 · 离线校对</h1>
  <div class="hint">
    校对标题/标签/描述后点「下载 edits.csv」，把文件保存到 <b>00_review\\edits.csv</b>，
    再到命令行运行 <b>run.bat review --apply</b>（或 python review_batch.py --apply）写回。
    __CLEAR__ 表示清空该字段。重抽封面：python review_batch.py --cover ID --time 00:00:05
  </div>
  <p><button onclick="downloadEdits()">下载 edits.csv</button></p>
</header>
<div class="wrap" id="cards"></div>
<script>
const ITEMS = __DATA__;
const BASE = __BASE__;
function esc(s) {{ return String(s ?? '').replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}})[c]); }}
function ta(id, field, value, cls) {{
  return `<div><label>${{field}}</label><textarea class="${{cls}}" data-id="${{id}}" data-field="${{field}}">${{esc(value)}}</textarea></div>`;
}}
function render() {{
  const box = document.getElementById('cards');
  box.innerHTML = ITEMS.map(it => {{
    const base = BASE + it.id + '/';
    const covers = it.covers.map(c =>
      `<figure><img src="${{base}}${{c.file}}" alt="${{c.file}}"><figcaption>${{c.ratio}}</figcaption></figure>`
    ).join('');
    const badge = it.need_title ? '<span class="badge">需补标题</span>' : '';
    return `<div class="card">
      <h2>${{esc(it.id)}} · ${{esc(it.title)}}${{badge}}</h2>
      <div class="media">
        <video controls preload="metadata" src="${{base}}video.mp4"></video>
        <div class="covers">${{covers}}</div>
      </div>
      <div class="fields">
        ${{ta(it.id, 'title', it.title, 'short')}}
        ${{ta(it.id, 'tags', it.tags.join('\\n'), 'mid')}}
        ${{ta(it.id, 'description', it.description, 'mid')}}
        ${{ta(it.id, 'activities', it.activities.join('\\n'), 'short')}}
        ${{ta(it.id, 'hotspot', it.hotspot, 'short')}}
        ${{ta(it.id, 'declaration', it.declaration, 'short')}}
      </div>
    </div>`;
  }}).join('');
}}
function quoteCell(v) {{
  const s = String(v ?? '');
  return /[\",\\n\\r]/.test(s) ? '\"' + s.replace(/\"/g, '\"\"') + '\"' : s;
}}
function downloadEdits() {{
  const fields = ['id','title','description','tags','activities','hotspot','declaration'];
  const lines = [fields.join(',')];
  ITEMS.forEach(it => {{
    const get = f => {{
      const el = document.querySelector(`textarea[data-id="${{it.id}}"][data-field="${{f}}"]`);
      let v = el ? el.value : '';
      if (f === 'tags' || f === 'activities') v = v.split(/\\n/).map(x => x.trim()).filter(Boolean).join('|');
      return quoteCell(v);
    }};
    lines.push(fields.map(get).join(','));
  }});
  const blob = new Blob(['\\ufeff' + lines.join('\\r\\n') + '\\r\\n'], {{type: 'text/csv;charset=utf-8'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'edits.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}}
render();
</script>
</body>
</html>
"""


# ───────────────────────── 工具 ─────────────────────────

def collect_rows() -> list[dict]:
    rows = []
    for item in ql.iter_items(ql.INBOX):
        try:
            meta = ql.read_meta(item)
        except Exception as exc:
            print(f"[跳过] {item.name}: {exc}")
            continue
        covers = []
        for key, (_w, _h, filename) in ql.COVER_RATIOS.items():
            if (item / filename).exists():
                covers.append({"ratio": key.replace("cover", ""), "file": filename})
        if not covers and meta["cover"]:
            covers.append({"ratio": "source", "file": meta["cover"].name})
        rows.append({
            "id": item.name,
            "title": meta["title"],
            "description": "",
            "tags": list(meta["tags"]),
            "activities": list(meta["activities"]),
            "hotspot": json.dumps(meta["hotspot"], ensure_ascii=False) if meta["hotspot"] else "",
            "declaration": json.dumps(
                {"aiContent": meta["aiContent"], "isOriginal": meta["isOriginal"]},
                ensure_ascii=False,
            ),
            "need_title": meta["title"].startswith("未命名_"),
            "covers": covers,
        })
    return rows


def ensure_edits(rows: list[dict], force: bool = False) -> None:
    REVIEW.mkdir(parents=True, exist_ok=True)
    if EDITS_PATH.exists() and not force:
        return
    with EDITS_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EDIT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "tags": "|".join(row["tags"]),
                "activities": "|".join(row["activities"]),
                "hotspot": row["hotspot"],
                "declaration": row["declaration"],
            })


def read_edits() -> dict[str, dict]:
    if not EDITS_PATH.exists():
        return {}
    result = {}
    with EDITS_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("id"):
                result[row["id"].strip()] = row
    return result


def split_list(value: str) -> list[str]:
    if not value or value.strip() == CLEAR:
        return []
    return [x.strip() for x in value.split("|") if x.strip()]


def apply_edits() -> int:
    edits = read_edits()
    if not edits:
        print(f"没有可用的修改: {EDITS_PATH}")
        return 1
    count = 0
    for item_id, row in edits.items():
        item = ql.INBOX / item_id
        if not item.exists():
            print(f"[跳过] 目录不存在: {item_id}")
            continue
        try:
            title = (row.get("title") or "").strip()
            if title:
                (item / "title.txt").write_text(title + "\n", encoding="utf-8")

            desc = row.get("description")
            if desc is not None:
                if desc.strip() == CLEAR:
                    (item / "description.txt").write_text("", encoding="utf-8")
                elif desc.strip():
                    (item / "description.txt").write_text(desc.strip() + "\n", encoding="utf-8")

            if "tags" in row and row["tags"] is not None:
                tags = split_list(row["tags"])
                (item / "tags.txt").write_text(
                    "\n".join("#" + t for t in tags) + ("\n" if tags else ""), encoding="utf-8"
                )

            if "activities" in row and row["activities"] is not None:
                acts = split_list(row["activities"])
                (item / "activities.json").write_text(
                    json.dumps(acts, ensure_ascii=False) + "\n", encoding="utf-8"
                )

            hotspot = (row.get("hotspot") or "").strip()
            if hotspot:
                if hotspot == CLEAR:
                    (item / "hotspot.json").write_text("null\n", encoding="utf-8")
                else:
                    json.loads(hotspot)
                    (item / "hotspot.json").write_text(hotspot + "\n", encoding="utf-8")

            declaration = (row.get("declaration") or "").strip()
            if declaration:
                if declaration == CLEAR:
                    (item / "declaration.json").write_text(
                        json.dumps({"aiContent": "内容由AI生成", "isOriginal": False}, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
                else:
                    json.loads(declaration)
                    (item / "declaration.json").write_text(declaration + "\n", encoding="utf-8")

            count += 1
            print(f"[已写回] {item_id}")
        except Exception as exc:
            print(f"[失败] {item_id}: {exc}")
    print(f"\n写回完成: {count} 个")
    return 0 if count else 1


def regen_cover(item_id: str, cover_time: str | None) -> int:
    item = ql.INBOX / item_id
    if not item.exists():
        print(f"目录不存在: {item_id}")
        return 1
    meta = ql.read_meta(item)
    t = pb.parse_time_arg(cover_time)
    used = pb.extract_frame(meta["video"], item / "cover.jpg", t)
    warnings = pb.compose_bordered_covers(item / "cover.jpg", item)
    print(f"封面已重抽: {item_id} @ {used}s")
    for w in warnings:
        print("  " + w)
    return 0


# ───────────────────────── 主流程 ─────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="生成离线校对页并写回修改")
    parser.add_argument("--apply", action="store_true", help="把 edits.csv 写回视频目录")
    parser.add_argument("--cover", metavar="ID", help="重抽指定视频目录的封面")
    parser.add_argument("--time", help="重抽封面的时间点，如 00:00:05")
    parser.add_argument("--force-edits", action="store_true", help="用当前元数据覆盖 edits.csv")
    args = parser.parse_args()

    if args.apply:
        return apply_edits()
    if args.cover:
        return regen_cover(args.cover, args.time)

    rows = collect_rows()
    ensure_edits(rows, force=args.force_edits)
    REVIEW.mkdir(parents=True, exist_ok=True)
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    # 素材目录已与工具分离（E:\千帆素材库\01_inbox），生成绝对 file:// URL 供离线校对页加载视频/封面。
    base_js = json.dumps(ql.INBOX.as_uri().rstrip("/") + "/")
    html_text = (HTML_TEMPLATE.replace("{{", "{").replace("}}", "}")
                 .replace("__DATA__", data).replace("__BASE__", base_js))
    HTML_PATH.write_text(html_text, encoding="utf-8")
    print(f"校对页: {HTML_PATH}")
    print(f"修改表: {EDITS_PATH}")
    print(f"视频数: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

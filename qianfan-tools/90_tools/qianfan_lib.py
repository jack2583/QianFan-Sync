#!/usr/bin/env python3
"""千帆素材库本地预处理 + 上传工具。

设计原则：
  1. 每个视频一个目录，目录名 v_YYYYMMDD_NNN，便于脚本排序和去重。
  2. 目录内文件名固定（video.mp4 / cover.jpg / title.txt ...），脚本不猜名字。
  3. metadata 用纯文本 + JSON，人可编辑，脚本可稳定解析。
  4. 上传成功后整目录移动到 02_uploaded，失败移动到 03_failed，状态一目了然。

命令：
  init            初始化目录结构（已存在不会覆盖）
  new [ID]        在 01_inbox 新建一个视频目录并写入模板文件
  check           校验 01_inbox 中所有目录，不联网
  upload          上传 01_inbox 中所有目录到 QianFan-Sync
  retry           重试 03_failed 中的目录
  list            列出各状态目录中的视频

常用：
  python qianfan_lib.py new v_20261125_001
  python qianfan_lib.py check
  python qianfan_lib.py upload
"""
from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 工具根（随仓库迁移）：脚本、模板、文档、边框图都在这里。
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "90_tools" / "config.json"

# 素材根（视频数据，仍留在原盘）：优先级 环境变量 QF_LIB_ROOT > config.json 的 lib_root > 默认值。
def _resolve_lib_root() -> Path:
    env = os.environ.get("QF_LIB_ROOT")
    if env:
        return Path(env).expanduser()
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if cfg.get("lib_root"):
            return Path(cfg["lib_root"]).expanduser()
    except Exception:
        pass
    return Path(r"E:\千帆素材库")

LIB_ROOT = _resolve_lib_root()
INBOX = LIB_ROOT / "01_inbox"
UPLOADED = LIB_ROOT / "02_uploaded"
FAILED = LIB_ROOT / "03_failed"
TEMPLATE = ROOT / "00_template" / "v_0000"

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v", ".wmv", ".mpeg", ".mpg"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# draft commonConfig 字段 -> (宽, 高, 本地文件名)
COVER_RATIOS = {
    "coverLandscape": (1920, 1440, "cover_4x3.jpg"),
    "coverLandscape169": (1920, 1080, "cover_16x9.jpg"),
    "coverPortrait": (1440, 1920, "cover_3x4.jpg"),
    "coverPortrait916": (1080, 1920, "cover_9x16.jpg"),
}

TEMPLATE_FILES = {
    "title.txt": "",
    "description.txt": "",
    "category.txt": "",
    "tags.txt": "#AI动画\n#古风\n#萌娃\n",
    "activities.json": "[]\n",
    "hotspot.json": "null\n",
    "declaration.json": '{"aiContent": "内容由AI生成", "isOriginal": false}\n',
    "README.txt": (
        "video.mp4          必需。视频文件。\n"
        "cover.jpg          必需。封面原图，脚本会本地裁成 4 种比例。\n"
        "title.txt          必需。标题。\n"
        "description.txt    描述。\n"
        "category.txt       可选。素材分类（如 AI动画 / 朗读），也可上传时用 --category 指定。\n"
        "tags.txt           标签，每行一个，默认 #AI动画 / #古风 / #萌娃。\n"
        "activities.json    官方活动名数组，最多 5 个，默认 []。\n"
        "hotspot.json       关联热点对象或 null，默认 null，至少含 word。\n"
        "declaration.json   自主声明，默认内容由AI生成。\n"
        "manifest.json      由脚本生成，勿手改。\n"
    ),
}


# ───────────────────────── 基础工具 ─────────────────────────

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"缺少配置文件: {CONFIG_PATH}，请先运行 init")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def parse_base(base_url: str):
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"base_url 只支持 http/https: {base_url}")
    host = parts.hostname or "localhost"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, host, port


def abs_url(base_url: str, url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return base_url.rstrip("/") + "/" + url.lstrip("/")


def read_text(path: Path, required: bool = False) -> str:
    if not path.exists():
        if required:
            raise ValueError(f"缺少 {path.name}")
        return ""
    return path.read_text(encoding="utf-8").strip()


def read_json(path: Path, default):
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} 不是合法 JSON: {exc}")


def read_original_filename(item: Path, fallback: str) -> str:
    """批量预处理会写 source.txt，用它作为素材库显示名/检索名。"""
    p = item / "source.txt"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name:
                return name
    return fallback


def safe_upload_filename(filename: str) -> str:
    """避免中文文件名里的特殊字符破坏 multipart 头。"""
    return str(filename).replace('"', "'").replace("\r", "").replace("\n", "")


def find_ffprobe() -> str | None:
    """定位 ffprobe（PATH 或 WinGet 安装的 FFmpeg）。"""
    p = shutil.which("ffprobe")
    if p:
        return p
    base = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if base.exists():
        name = "ffprobe.exe" if sys.platform.startswith("win") else "ffprobe"
        for d in base.glob("Gyan.FFmpeg*/**/bin"):
            candidate = d / name
            if candidate.exists():
                return str(candidate)
    return None


def local_orientation(video: Path) -> str:
    """本地读取视频方向，避免后端异步探测未完成时选错封面比例。"""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return ""
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", str(video)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("x")
            width, height = int(parts[0]), int(parts[1])
            if height > width:
                return "vertical"
            if width > height:
                return "horizontal"
            return "square"
    except Exception:
        pass
    return ""


def request_json(method: str, endpoint: str, payload=None, cfg: dict | None = None):
    cfg = cfg or load_config()
    url = cfg["base_url"].rstrip("/") + endpoint
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=cfg.get("timeout_seconds", 180)) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code} {endpoint}: {body[:300]}") from exc
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"非 JSON 响应 {endpoint}: {raw[:300]}") from exc
    if obj.get("code") != 200:
        raise RuntimeError(f"{endpoint} 返回失败: {obj.get('msg') or obj}")
    return obj.get("data")


def ensure_material_category(category: str, cfg: dict) -> bool:
    """把分类注册到「分类管理」名单；名单和素材上的分类值是两套数据。

    返回 True 表示本次新增，False 表示原本已存在或分类为空。
    """
    category = (category or "").strip()
    if not category:
        return False
    cats = request_json("GET", "/api/materials/categories", None, cfg) or []
    cats = [str(c).strip() for c in cats if str(c).strip()]
    if category in cats:
        return False
    cats.append(category)
    request_json("POST", "/api/materials/categories", {"categories": cats}, cfg)
    print(f"  分类已注册到分类管理: {category}")
    return True


def upload_multipart(endpoint: str, filename: str, content_type: str, content, cfg: dict):
    """流式 multipart 上传，content 可以是 bytes 或本地文件路径。"""
    scheme, host, port = parse_base(cfg["base_url"])
    filename = safe_upload_filename(filename)
    boundary = "----QianFanLib" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    if isinstance(content, (bytes, bytearray)):
        total = len(head) + len(content) + len(tail)
    else:
        total = len(head) + Path(content).stat().st_size + len(tail)

    conn_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(host, port, timeout=cfg.get("timeout_seconds", 180))
    try:
        conn.putrequest("POST", endpoint)
        conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        conn.putheader("Content-Length", str(total))
        conn.endheaders()
        conn.send(head)
        if isinstance(content, (bytes, bytearray)):
            conn.send(content)
        else:
            chunk_size = max(1, int(cfg.get("chunk_size_mb", 1))) * 1024 * 1024
            with open(content, "rb") as fh:
                while True:
                    chunk = fh.read(chunk_size)
                    if not chunk:
                        break
                    conn.send(chunk)
        conn.send(tail)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", "replace")
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} {endpoint}: {raw[:300]}")
    finally:
        conn.close()

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"非 JSON 响应 {endpoint}: {raw[:300]}") from exc
    if obj.get("code") != 200:
        raise RuntimeError(f"{endpoint} 返回失败: {obj.get('msg') or obj}")
    return obj.get("data") or {}


# ───────────────────────── 本地元数据 ─────────────────────────

def find_video(item: Path) -> Path | None:
    preferred = item / "video.mp4"
    if preferred.exists():
        return preferred
    candidates = sorted(
        p for p in item.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS and p.name != "manifest.json"
    )
    return candidates[0] if candidates else None


def find_cover(item: Path) -> Path | None:
    for name in ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp"):
        p = item / name
        if p.exists():
            return p
    candidates = sorted(
        p for p in item.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and p.name != "manifest.json"
    )
    return candidates[0] if candidates else None


def read_meta(item: Path) -> dict:
    title = read_text(item / "title.txt", required=True)
    if not title:
        raise ValueError("title.txt 为空")

    description = read_text(item / "description.txt")

    # 分类：目录内 category.txt（可选，取第一行）
    category = ""
    cat_path = item / "category.txt"
    if cat_path.exists():
        for line in cat_path.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if name:
                category = name
                break

    tags = []
    for line in (item / "tags.txt").read_text(encoding="utf-8").splitlines() if (item / "tags.txt").exists() else []:
        tag = line.strip().lstrip("#").strip()
        if tag:
            tags.append(tag)

    activities = read_json(item / "activities.json", [])
    if activities is None:
        activities = []
    if not isinstance(activities, list) or any(not isinstance(a, str) for a in activities):
        raise ValueError("activities.json 必须是字符串数组")
    if len(activities) > 5:
        raise ValueError("activities.json 最多 5 个活动")

    hotspot = read_json(item / "hotspot.json", None)
    if hotspot is not None and not isinstance(hotspot, dict):
        raise ValueError("hotspot.json 必须是对象或 null")
    if hotspot and not hotspot.get("word"):
        raise ValueError("hotspot.json 缺少 word 字段")

    declaration = read_json(item / "declaration.json", {})
    if not isinstance(declaration, dict):
        raise ValueError("declaration.json 必须是对象")
    ai_content = declaration.get("aiContent") or "内容由AI生成"
    if not isinstance(ai_content, str):
        raise ValueError("declaration.json 的 aiContent 必须是字符串")

    video = find_video(item)
    if video is None:
        raise ValueError("缺少视频文件（建议命名 video.mp4）")
    cover = find_cover(item)
    if cover is None:
        raise ValueError("缺少封面文件（建议命名 cover.jpg）")

    return {
        "dir": item,
        "id": item.name,
        "title": title,
        "description": description,
        "category": category,
        "tags": tags,
        "activities": activities,
        "hotspot": hotspot,
        "aiContent": ai_content,
        "isOriginal": bool(declaration.get("isOriginal", False)),
        "video": video,
        "cover": cover,
    }


def make_cover_variants(meta: dict) -> dict:
    """返回 key -> (filename, bytes_or_path)。优先用已裁好的 4 个文件。"""
    item = meta["dir"]
    variants = {}
    for key, (_w, _h, filename) in COVER_RATIOS.items():
        p = item / filename
        if p.exists():
            variants[key] = (filename, p)

    if len(variants) == len(COVER_RATIOS):
        return variants

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("本地裁封面需要 Pillow，请用 QianFan-Sync 后端虚拟环境的 python 运行本脚本") from exc

    src = Image.open(meta["cover"])
    src.load()
    for key, (tw, th, filename) in COVER_RATIOS.items():
        if key in variants:
            continue
        sw, sh = src.size
        scale = max(tw / sw, th / sh)
        crop_w, crop_h = min(sw, tw / scale), min(sh, th / scale)
        left, top = (sw - crop_w) / 2, (sh - crop_h) / 2
        box = (round(left), round(top), round(left + crop_w), round(top + crop_h))
        out = src.crop(box).resize((tw, th), Image.LANCZOS)
        if out.mode not in ("RGB", "L"):
            out = out.convert("RGB")
        buf = BytesIO()
        out.save(buf, format="JPEG", quality=92)
        variants[key] = (filename, buf.getvalue())
    return variants


# ───────────────────────── 上传 ─────────────────────────

def build_draft_data(meta: dict, video_data: dict, cover_data: dict, cfg: dict) -> dict:
    base = cfg["base_url"]
    video_obj = {
        "id": video_data.get("id"),
        "name": video_data.get("original_filename") or meta["video"].name,
        "stored_path": video_data.get("stored_path"),
        "url": abs_url(base, video_data.get("url", "")),
        "size": video_data.get("file_size"),
        "type": video_data.get("mime_type"),
        "duration": video_data.get("duration") or 0,
    }
    common = {
        "videoLandscape": video_obj,
        "videoPortrait": None,
        "coverLandscape": cover_data.get("coverLandscape"),
        "coverLandscape169": cover_data.get("coverLandscape169"),
        "coverPortrait": cover_data.get("coverPortrait"),
        "coverPortrait916": cover_data.get("coverPortrait916"),
    }

    platforms = cfg.get("platforms") or ["douyin"]
    platform_configs = {}
    for platform in platforms:
        pc = {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "aiContent": meta["aiContent"],
            "isOriginal": meta["isOriginal"],
            "scheduleTime": "",
        }
        if platform == "douyin":
            pc.update({
                "activityId": meta["activities"],
                "hotspotId": meta["hotspot"].get("word", "") if meta["hotspot"] else "",
                "hotspotData": meta["hotspot"],
                "selectedTag": None,
                "tagType": "",
                "tagValue": "",
                "mixId": "",
                "mixData": "",
            })
        platform_configs[platform] = pc

    return {
        "version": 2,
        "currentIndex": 0,
        "videos": [{
            "commonConfig": common,
            "platformConfigs": platform_configs,
            "publishAccountIds": [],
        }],
    }


def write_manifest(item: Path, payload: dict):
    (item / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def move_item(item: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / item.name
    if target.exists():
        target = target_dir / f"{item.name}_{datetime.now().strftime('%H%M%S')}"
    return Path(shutil.move(str(item), str(target)))


def process_item(item: Path, cfg: dict, dest_ok: Path, dest_fail: Path,
                 dry_run: bool = False, create_draft: bool | None = None,
                 category: str | None = None):
    print(f"\n=== {item.name} ===")
    try:
        meta = read_meta(item)
        variants = make_cover_variants(meta)
        print(f"  校验通过: {meta['title'][:40]} | {meta['video'].name} | 封面 {len(variants)} 比例")
        if dry_run:
            print("  [dry-run] 跳过上传")
            return True
        if create_draft is None:
            create_draft = bool(cfg.get("create_draft", True))

        # 本地固定叫 video.mp4，但素材库显示名/检索名要用原始文件名
        upload_name = read_original_filename(item, meta["video"].name)
        video_type = (mimetypes.guess_type(upload_name)[0]
                      or mimetypes.guess_type(meta["video"].name)[0]
                      or "video/mp4")
        video_data = upload_multipart(
            "/api/materials/upload", upload_name, video_type, meta["video"], cfg
        )
        print(f"  视频已上传: {upload_name} -> {video_data.get('stored_path')}")

        # 补全时长，失败不影响主流程
        try:
            probed = request_json(
                "POST", f"/api/materials/{video_data.get('id')}/probe", {}, cfg
            )
            if probed:
                video_data.update(probed)
        except Exception as exc:
            print(f"  时长识别跳过: {exc}")

        cover_data = {}
        for key, (filename, content) in variants.items():
            data = upload_multipart(
                "/api/materials/covers/upload", filename, "image/jpeg", content, cfg
            )
            cover_obj = {
                "id": data.get("id"),
                "name": filename,
                "stored_path": data.get("stored_path"),
                "url": abs_url(cfg["base_url"], data.get("url", "")),
                "size": data.get("file_size"),
                "type": data.get("mime_type", "image/jpeg"),
            }
            cover_data[key] = cover_obj
        print(f"  封面已上传: {len(cover_data)} 张")

        # 把本地裁好并带边框的 4 张封面关联到素材，发布页直接复用，不再重新抽帧裁剪
        try:
            request_json(
                "POST",
                f"/api/materials/{video_data.get('id')}/covers",
                {"covers": cover_data},
                cfg,
            )
            print("  本地封面已关联到素材（发布页直接复用）")
        except Exception as exc:
            print(f"  封面关联跳过: {exc}")

        # 素材库卡片默认显示 ffmpeg 抽帧（无边框），这里改绑带边框封面
        # 竖版视频用 3:4，其余用 4:3，保证方形卡片完整展示边框
        orientation = video_data.get("orientation") or local_orientation(meta["video"])
        if orientation and not video_data.get("orientation"):
            video_data["orientation"] = orientation
        thumb_key = "coverPortrait" if orientation == "vertical" else "coverLandscape"
        thumb = cover_data.get(thumb_key) or {}
        if thumb.get("stored_path"):
            try:
                request_json(
                    "POST",
                    f"/api/materials/{video_data.get('id')}/thumbnail",
                    {"stored_path": thumb["stored_path"]},
                    cfg,
                )
                video_data["thumbnail_path"] = thumb["stored_path"]
                video_data["thumbnail_url"] = thumb.get("url")
                print(f"  素材库缩略图已绑定带边框封面: {thumb.get('name')}")
            except Exception as exc:
                print(f"  缩略图绑定跳过: {exc}")

        # 分类：命令行 --category 优先，其次目录内 category.txt
        final_category = (category or "").strip() or meta.get("category", "")
        if final_category:
            try:
                # 先注册到分类名单，否则素材虽有分类值，网页“全部分类/分类管理”看不到
                ensure_material_category(final_category, cfg)
                request_json(
                    "POST",
                    f"/api/materials/{video_data.get('id')}/category",
                    {"category": final_category},
                    cfg,
                )
                video_data["category"] = final_category
                print(f"  素材分类已设置: {final_category}")
            except Exception as exc:
                print(f"  分类设置跳过: {exc}")

        draft_id = None
        if create_draft:
            draft_data = build_draft_data(meta, video_data, cover_data, cfg)
            draft = request_json(
                "POST", "/api/v2/drafts",
                {"type": "video", "draft_data": draft_data}, cfg,
            )
            draft_id = draft.get("id") if isinstance(draft, dict) else None
            print(f"  草稿已创建: id={draft_id}")

        write_manifest(item, {
            "status": "success",
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "title": meta["title"],
            "category": final_category,
            "video": video_data,
            "covers": cover_data,
            "draft_id": draft_id,
        })
        if cfg.get("move_after_upload", True) and item.parent.resolve() != dest_ok.resolve():
            final = move_item(item, dest_ok)
            print(f"  已移动到: {final}")
        else:
            print("  保留在原目录（move_after_upload=false）")
        return True

    except Exception as exc:
        print(f"  失败: {exc}")
        try:
            write_manifest(item, {
                "status": "failed",
                "failed_at": datetime.now().isoformat(timespec="seconds"),
                "error": str(exc),
            })
        except Exception:
            pass
        if cfg.get("move_after_upload", True) and item.parent.resolve() != dest_fail.resolve():
            final = move_item(item, dest_fail)
            print(f"  已移动到: {final}")
        return False


# ───────────────────────── 命令 ─────────────────────────

def cmd_init(_args):
    for d in (TEMPLATE, INBOX, UPLOADED, FAILED, ROOT / "90_tools", ROOT / "99_docs"):
        d.mkdir(parents=True, exist_ok=True)
    for name, content in TEMPLATE_FILES.items():
        p = TEMPLATE / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps({
            "base_url": "http://localhost:5409",
            "create_draft": True,
            "platforms": ["douyin"],
            "timeout_seconds": 180,
            "chunk_size_mb": 1,
            "move_after_upload": True,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"初始化完成: {ROOT}")


def cmd_new(args):
    TEMPLATE.mkdir(parents=True, exist_ok=True)
    for name, content in TEMPLATE_FILES.items():
        p = TEMPLATE / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")
    item_id = args.id or f"v_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    target = INBOX / item_id
    target.mkdir(parents=True, exist_ok=False)
    for p in TEMPLATE.iterdir():
        if p.is_file():
            shutil.copy2(p, target / p.name)
    print(f"已创建: {target}")
    print("下一步：把视频放为 video.mp4，封面放为 cover.jpg，再填写 title.txt 等文件。")


def iter_items(directory: Path):
    if not directory.exists():
        return []
    return sorted(p for p in directory.iterdir() if p.is_dir() and not p.name.startswith("."))


def cmd_check(_args):
    items = iter_items(INBOX)
    if not items:
        print("01_inbox 中没有待检查的视频目录")
        return 0
    bad = 0
    for item in items:
        try:
            meta = read_meta(item)
            variants = make_cover_variants(meta)
            cat = meta.get("category") or "未分类"
            print(f"[OK] {item.name}: {meta['title']} | 分类 {cat} | 封面 {len(variants)} 比例")
        except Exception as exc:
            bad += 1
            print(f"[ERROR] {item.name}: {exc}")
    print(f"\n共 {len(items)} 个，异常 {bad} 个")
    return 1 if bad else 0


def cmd_ping(_args):
    """上传前预检：检查后端服务器是否可连接。可连接返回 0，否则返回 1。"""
    cfg = load_config()
    base = cfg.get("base_url", "")
    try:
        request_json("GET", "/api/materials/categories", None, cfg)
    except Exception as exc:
        print(f"[连接失败] 无法连接服务器: {base}")
        print(f"  原因: {exc}")
        print("  请先启动 QianFan-Sync 后端（运行 start.bat），再重试上传。")
        return 1
    print(f"[连接正常] 服务器可用: {base}")
    return 0


def cmd_upload(args):
    cfg = load_config()
    items = iter_items(INBOX)
    if not items:
        print("01_inbox 中没有待上传的视频目录")
        return 0
    if args.limit:
        items = items[: args.limit]
    ok = 0
    for item in items:
        if process_item(item, cfg, UPLOADED, FAILED,
                        dry_run=args.dry_run,
                        create_draft=False if args.no_draft else None,
                        category=getattr(args, "category", None)):
            ok += 1
    print(f"\n完成: {ok}/{len(items)} 成功")
    return 0 if ok == len(items) else 1


def cmd_retry(args):
    cfg = load_config()
    items = iter_items(FAILED)
    if not items:
        print("03_failed 中没有需要重试的视频目录")
        return 0
    ok = 0
    for item in items:
        if process_item(item, cfg, UPLOADED, FAILED,
                        dry_run=args.dry_run,
                        create_draft=False if args.no_draft else None,
                        category=getattr(args, "category", None)):
            ok += 1
    print(f"\n重试完成: {ok}/{len(items)} 成功")
    return 0 if ok == len(items) else 1


def cmd_list(_args):
    for label, directory in (("待上传", INBOX), ("已上传", UPLOADED), ("失败", FAILED)):
        items = iter_items(directory)
        print(f"\n{label} ({directory}): {len(items)} 个")
        for item in items:
            print(f"  - {item.name}")


def main():
    parser = argparse.ArgumentParser(description="千帆素材库本地预处理与上传")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化目录结构").set_defaults(func=cmd_init)

    p_new = sub.add_parser("new", help="新建一个视频目录")
    p_new.add_argument("id", nargs="?", help="目录名，如 v_20261125_001；省略则按时间生成")
    p_new.set_defaults(func=cmd_new)

    sub.add_parser("check", help="校验待上传目录，不联网").set_defaults(func=cmd_check)

    sub.add_parser("ping", help="检查后端服务器是否可连接").set_defaults(func=cmd_ping)

    p_up = sub.add_parser("upload", help="上传 01_inbox 中的视频")
    p_up.add_argument("--limit", type=int, help="最多处理 N 个")
    p_up.add_argument("--dry-run", action="store_true", help="只校验不上传")
    p_up.add_argument("--no-draft", action="store_true", help="只传素材，不建草稿")
    p_up.add_argument("--category", help="素材分类（如 AI动画 / 朗读），覆盖目录内 category.txt")
    p_up.set_defaults(func=cmd_upload)

    p_retry = sub.add_parser("retry", help="重试 03_failed 中的视频")
    p_retry.add_argument("--dry-run", action="store_true")
    p_retry.add_argument("--no-draft", action="store_true")
    p_retry.add_argument("--category", help="素材分类（如 AI动画 / 朗读），覆盖目录内 category.txt")
    p_retry.set_defaults(func=cmd_retry)

    sub.add_parser("list", help="列出各状态目录").set_defaults(func=cmd_list)

    args = parser.parse_args()
    try:
        rc = args.func(args)
    except Exception as exc:
        print(f"错误: {exc}")
        rc = 1
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()

"""CloakBrowser stealth browser factory — unified entry point.

所有打开浏览器的入口都集中在这里。调用方不要直接调 browser.new_context
或 cloakbrowser.launch_*，避免东一套西一套。

所有 context 使用 no_viewport=True，页面内容跟随窗口大小自动 reflow。
"""

from __future__ import annotations

import asyncio
import os
import threading

from conf import LOGIN_HEADLESS, LOCAL_CHROME_HEADLESS
from util._logger import get_channel_logger

logger = get_channel_logger("browser")

# Playwright driver 与创建它的 event loop 绑定：Flask 每个 /login、发布请求
# 都在自己的线程里 asyncio.run()（每次新建 loop），跨 loop 复用旧 driver 会
# 在旧 loop 关闭后变成 TargetClosedError，表现为「点添加账号不弹浏览器」。
# 这里按 loop 缓存 driver，同一 loop 内复用、不同 loop 各自新建。
_ASYNC_PWS: dict[asyncio.AbstractEventLoop, object] = {}
_ASYNC_PW_LOCK = threading.Lock()
_SYNC_PW = None


def _use_edge() -> bool:
    """是否使用系统 Edge 代替 CloakBrowser。

    - 环境变量 SAU_BROWSER=edge|cloak 可强制指定；
    - 未指定时：本地没有 CloakBrowser 授权 key 就自动用系统 Edge，
      有 key 则继续用隐身浏览器（用户后续配置 key 后无需改代码）。
    """
    override = os.environ.get("SAU_BROWSER", "").strip().lower()
    if override in ("edge", "msedge", "system", "chrome"):
        return True
    if override in ("cloak", "cloakbrowser", "stealth"):
        return False
    try:
        from cloakbrowser.license import resolve_license_key
        if resolve_license_key():
            return False
    except Exception:
        pass
    return True


async def _get_async_pw():
    """按当前 event loop 取 Playwright driver，避免跨 loop 复用失效连接。"""
    loop = asyncio.get_running_loop()
    with _ASYNC_PW_LOCK:
        pw = _ASYNC_PWS.get(loop)
    if pw is not None:
        return pw
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    with _ASYNC_PW_LOCK:
        _ASYNC_PWS[loop] = pw
    return pw


async def _drop_async_pw():
    """丢弃当前 loop 上已断开的 driver，下次调用会重新 start。"""
    loop = asyncio.get_running_loop()
    with _ASYNC_PW_LOCK:
        pw = _ASYNC_PWS.pop(loop, None)
    if pw is not None:
        try:
            await pw.stop()
        except Exception:
            pass


def _is_driver_closed_error(exc: BaseException) -> bool:
    """判断是否为 Playwright driver 连接已断开。"""
    return (
        type(exc).__name__ == "TargetClosedError"
        or "has been closed" in str(exc).lower()
    )


async def _launch_async_with_recovery(launch_fn, what: str):
    """driver 意外断开时重建一次再试，避免整次登录/发布直接失败。"""
    for attempt in range(2):
        pw = await _get_async_pw()
        try:
            return await launch_fn(pw)
        except Exception as exc:
            if attempt == 0 and _is_driver_closed_error(exc):
                logger.warning("[浏览器] Playwright driver 已断开(%s)，重建后重试", what)
                await _drop_async_pw()
                continue
            raise
    raise RuntimeError("unreachable")


def _get_sync_pw(force_new: bool = False):
    global _SYNC_PW
    if _SYNC_PW is None or force_new:
        if _SYNC_PW is not None:
            try:
                _SYNC_PW.stop()
            except Exception:
                pass
        from playwright.sync_api import sync_playwright
        _SYNC_PW = sync_playwright().start()
    return _SYNC_PW


def _download_binary():
    """Download CloakBrowser stealth binary."""
    from cloakbrowser import ensure_binary
    ensure_binary()


def init():
    """Pre-download CloakBrowser binary at startup."""
    if _use_edge():
        logger.info("未检测到 CloakBrowser 授权，使用系统 Edge 浏览器")
        return
    try:
        _download_binary()
        logger.info("CloakBrowser 隐匿浏览器已就绪")
    except Exception as e:
        logger.warning("CloakBrowser 隐匿浏览器不可用(%s)", e)


# ──────────── 异步入口 ────────────

async def create_browser(
    headless: bool | None = None,
    login_mode: bool = False,
    humanize: bool = False,
    human_preset: str = "default",
):
    """异步入口：创建 stealth Chromium 浏览器。

    不接 proxy / extra_args —— 历史代理配置已废弃。

    login_mode=True 或 headless=False（有头）时，自动监听浏览器关闭
    事件：**用户手动**关浏览器会 cancel 当前 asyncio task，使 login/发布
    流程立即终止并返回失败。而发布成功后平台代码主动 browser.close()
    的正常收尾不会误触发（内部已 disarm）。

    humanize=True 时启用 CloakBrowser 拟人化操作层（贝塞尔鼠标轨迹、
    逐键打字、平滑滚动等），仅建议在发布动作开启——会让操作明显变慢，
    login/check_cookie/sync_profile 等高频轻量调用保持关闭更稳妥。
    human_preset: 'default'(正常人速度) 或 'careful'(更慢更谨慎)。
    """
    if headless is None:
        headless = LOGIN_HEADLESS if login_mode else LOCAL_CHROME_HEADLESS
    if _use_edge():
        async def _launch(pw):
            return await pw.chromium.launch(
                channel="msedge",
                headless=headless,
                args=["--start-maximized"],
            )
        browser = await _launch_async_with_recovery(_launch, "create_browser")
    else:
        from cloakbrowser import launch_async
        browser = await launch_async(
            headless=headless,
            args=["--start-maximized"],
            humanize=humanize,
            human_preset=human_preset,
        )

    if login_mode or headless is False:
        # login 或有头浏览器（发布场景）：用户主动关浏览器 → cancel 当前 task，
        # 使 login/发布流程立即终止，避免后端 worker 一直阻塞、日志狂刷。
        #
        # 判定标志 is_close_by_code（挂在 browser 对象上）：
        #   False（默认）= 代码尚未主动关浏览器。此时浏览器若断开 = 用户手动关闭
        #                 → watchdog / disconnected 回调 cancel 当前 task。
        #   True = 代码（发布成功/失败收尾）主动调用了关闭。
        #         → 是正常收尾，绝不 cancel（避免把成功发布误判为失败）。
        #
        # 各平台发布收尾应走 BasePlatform.close_browser(browser, is_close_by_code=True)，
        # 它会先置标志再关闭。双重机制：disconnected 事件（快速路径，CloakBrowser
        # 代理下未必可靠）+ watchdog 轮询 is_connected()（可靠兜底）。
        task = asyncio.current_task()
        browser._is_close_by_code = False  # 标志位，默认"非代码关闭"

        def _should_cancel():
            """是否应当 cancel: 浏览器断开 且 非代码主动关闭 且 task 仍存活。"""
            return (
                not browser._is_close_by_code
                and task is not None
                and not task.done()
            )

        def _on_browser_closed():
            if _should_cancel():
                logger.info("[浏览器] 检测到用户关闭了浏览器，取消当前发布任务")
                task.cancel()

        try:
            browser.on("disconnected", _on_browser_closed)
        except Exception as e:
            logger.info("[浏览器] 关闭事件注册失败，改用轮询兜底: %s", e)

        # watchdog: 后台轮询 is_connected(), 断开且非代码关闭则 cancel 发布 task。
        # 解决「平台 while True 循环在浏览器关闭后无限刷日志」的统一方案,
        # 对所有平台适用, 各平台代码只需在发布收尾走 close_browser 即可。
        async def _watchdog():
            try:
                while True:
                    await asyncio.sleep(0.5)
                    if browser._is_close_by_code or task is None or task.done():
                        return  # 代码已主动关闭 / task 已结束 → 退出
                    try:
                        if not browser.is_connected():
                            logger.info("[浏览器] 轮询检测到用户关闭了浏览器，取消当前发布任务")
                            task.cancel()
                            return
                    except Exception:
                        # is_connected 自身异常(对象已释放)也视为断开
                        if _should_cancel():
                            logger.info("[浏览器] 轮询检测到浏览器异常断开，取消当前发布任务")
                            task.cancel()
                        return
            except asyncio.CancelledError:
                pass

        if task is not None:
            asyncio.create_task(_watchdog())

        # 包装 close：代码主动关闭时置 is_close_by_code=True，
        # 使 disconnected 回调和 watchdog 都不再 cancel（正常收尾）。
        _orig_close = browser.close

        async def _safe_close(*args, **kwargs):
            browser._is_close_by_code = True  # 同步置标志，在 await 之前生效
            return await _orig_close(*args, **kwargs)

        browser.close = _safe_close

    return browser


async def create_context(
    browser,
    storage_state: str | None = None,
    user_agent: str | None = None,
):
    """异步入口：创建 browser context（no_viewport，跟随窗口自适应）。"""
    return await browser.new_context(
        storage_state=storage_state,
        user_agent=user_agent,
        no_viewport=True,
    )


async def close_browser(browser, is_close_by_code: bool = True) -> None:
    """统一关闭浏览器入口（发布/图集收尾用）。

    Args:
        browser: create_browser 返回的 browser 对象。
        is_close_by_code: True=代码主动关闭（发布成功/失败收尾），此时
            _browser.py 的 watchdog/disconnected 监听不会 cancel 当前 task；
            False 仅用于特殊场景，默认 True。

    各平台发布/图集上传方法在 finally 里关闭浏览器时，应统一调用本方法
    （或通过 BasePlatform.close_browser 委托），避免 watchdog 把「代码主动
    关闭」误判为「用户手动关闭」而触发 task cancel。

    模块级发布函数（如 xiaohongshu._publish_single_video，无 self）直接
    调用本函数；类方法走 BasePlatform.close_browser（内部委托本函数）。
    """
    try:
        browser._is_close_by_code = is_close_by_code
    except Exception:
        pass
    try:
        await browser.close()
    except Exception:
        pass


async def create_persistent_context(
    user_data_dir: str,
    headless: bool = False,
):
    """异步入口：登录扫码用持久化 context（no_viewport，跟随窗口自适应）。"""
    if _use_edge():
        async def _launch(pw):
            return await pw.chromium.launch_persistent_context(
                user_data_dir,
                channel="msedge",
                headless=headless,
                no_viewport=True,
                args=["--window-size=1920,1080", "--start-maximized"],
            )
        return await _launch_async_with_recovery(
            _launch, "create_persistent_context"
        )
    from cloakbrowser import launch_persistent_context_async
    return await launch_persistent_context_async(
        user_data_dir,
        headless=headless,
        no_viewport=True,
        args=["--window-size=1920,1080", "--start-maximized"],
    )


# ──────────── 同步入口 ────────────

def create_browser_sync(headless: bool = False):
    """同步入口：创建 stealth Chromium 浏览器。"""
    if _use_edge():
        for attempt in range(2):
            pw = _get_sync_pw(force_new=(attempt > 0))
            try:
                return pw.chromium.launch(
                    channel="msedge",
                    headless=headless,
                    args=["--start-maximized"],
                )
            except Exception as exc:
                if attempt == 0 and _is_driver_closed_error(exc):
                    logger.warning("[浏览器] 同步 Playwright driver 已断开，重建后重试")
                    continue
                raise
    from cloakbrowser import launch
    return launch(headless=headless)


def create_context_sync(
    browser,
    storage_state: str | None = None,
    user_agent: str | None = None,
):
    """同步入口：创建 browser context（no_viewport，跟随窗口自适应）。

    平台层不要直接调 browser.new_context()，统一走这个入口。
    """
    return browser.new_context(
        storage_state=storage_state,
        user_agent=user_agent,
        no_viewport=True,
    )

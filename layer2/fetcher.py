"""Транспорт для адаптеров.

Разведка показала, что у сайтов недвижимости в исходном HTML объявлений нет:
всё рисуется JavaScript'ом. Поэтому основной способ — настоящий браузер,
который отдаёт уже отрендеренную страницу.

Правила поведения зашиты здесь, а не в адаптерах, чтобы их нельзя было
случайно нарушить в одном месте:
  * пауза между запросами — это семейный поиск, а не мониторинг рынка;
  * cookie-баннеры отклоняем (никогда не принимаем): нам нужен текст
    страницы, а не согласие на слежку;
  * страницы кэшируются на диск, чтобы отладка адаптера не била по сайту.
"""
from __future__ import annotations

import gzip
import hashlib
import pathlib
import time

from housemap import http
from .cache_paths import PAGES

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Кнопки отказа на французских сайтах. Принимающие кнопки не трогаем.
REJECT_SELECTORS = [
    "#onetrust-reject-all-handler",
    "button#didomi-notice-disagree-button",
    "button:has-text('Continuer sans accepter')",
    "button:has-text('Tout refuser')",
    "button:has-text('Refuser tout')",
    "button:has-text('Refuser')",
    "a:has-text('Continuer sans accepter')",
    "[aria-label*='Refuser']",
]

# Если кнопки отказа нет — просто убираем перекрывающий слой из своей копии
# страницы. Это не согласие: мы ничего не подтверждаем, а лишь читаем текст.
OVERLAY_SELECTORS = [
    "#onetrust-consent-sdk", "#didomi-host", ".didomi-popup-container",
    "[id*='cookie-banner']", "[class*='cookie-banner']", "[id*='tarteaucitron']",
]


def _key(url: str) -> pathlib.Path:
    return PAGES / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".html.gz")


def cached_page(url: str) -> str | None:
    p = _key(url)
    if p.exists():
        return gzip.decompress(p.read_bytes()).decode("utf-8", "replace")
    return None


def store_page(url: str, html: str):
    PAGES.mkdir(parents=True, exist_ok=True)
    _key(url).write_bytes(gzip.compress(html.encode("utf-8")))


class HttpFetcher:
    """Простой запрос — для сайтов, отдающих данные без рендеринга."""
    name = "http"

    def __init__(self, delay: float = 1.5):
        self.delay = delay

    def get(self, url: str, use_cache: bool = True, prepare=None) -> str:
        if use_cache:
            hit = cached_page(url)
            if hit is not None:
                return hit
        r = http.get(url, timeout=40)
        r.raise_for_status()
        store_page(url, r.text)
        time.sleep(self.delay)
        return r.text

    def close(self):
        pass


class BrowserFetcher:
    """Playwright + Chromium. Видит то же, что человек."""
    name = "browser"

    def __init__(self, delay: float = 2.5, headless: bool = True):
        from playwright.sync_api import sync_playwright
        self.delay = delay
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._ctx = self._browser.new_context(
            locale="fr-FR", user_agent=UA,
            viewport={"width": 1280, "height": 900})
        self._ctx.set_default_timeout(45000)

    def get(self, url: str, use_cache: bool = True, wait_ms: int = 4500,
            prepare=None) -> str:
        if use_cache:
            hit = cached_page(url)
            if hit is not None:
                return hit
        pg = self._ctx.new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(wait_ms)
            self._dismiss_consent(pg)
            # галереи подгружают снимки лениво: без прокрутки в разметку
            # попадает лишь часть фотографий объявления
            try:
                pg.mouse.wheel(0, 2200)
                pg.wait_for_timeout(1200)
            except Exception:
                pass
            # адаптер может знать, что на этом сайте надо раскрыть галерею
            if prepare:
                try:
                    prepare(pg)
                except Exception:
                    pass
            html = pg.content()
        finally:
            pg.close()
        store_page(url, html)
        time.sleep(self.delay)
        return html

    def _dismiss_consent(self, pg):
        for sel in REJECT_SELECTORS:
            try:
                el = pg.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=3000)
                    pg.wait_for_timeout(800)
                    return
            except Exception:
                continue
        # кнопки отказа нет — убираем оверлей, ничего не подтверждая
        try:
            pg.eval_on_selector_all(
                ",".join(OVERLAY_SELECTORS), "els => els.forEach(e => e.remove())")
        except Exception:
            pass

    def close(self):
        for obj in (self._ctx, self._browser):
            try:
                obj.close()
            except Exception:
                pass
        try:
            self._pw.stop()
        except Exception:
            pass


def make(transport: str, **kw):
    return BrowserFetcher(**kw) if transport == "browser" else HttpFetcher(**kw)

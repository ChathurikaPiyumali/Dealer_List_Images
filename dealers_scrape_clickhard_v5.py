#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, os, re, time, json
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

def log(s): print(s, flush=True)

# ---------- utils ----------
def sanitize(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"[_ ]{2,}", "_", name)
    return name[:150]

def normalize_img(u: str) -> str:
    parts = list(urlparse(u)); parts[4] = ""; parts[5] = ""; return urlunparse(parts)

def soup_from(sess: requests.Session, url: str) -> BeautifulSoup:
    r = sess.get(url, timeout=45); r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def extract_images(listing_url: str, soup: BeautifulSoup) -> list[str]:
    urls = set()
    for img in soup.find_all("img"):
        for attr in ["src", "data-src", "data-lazy-src", "data-original"]:
            u = img.get(attr)
            if not u: continue
            u = urljoin(listing_url, u); u = normalize_img(u)
            if any(u.lower().endswith(ext) for ext in IMG_EXTS): urls.add(u)
    for a in soup.find_all("a", href=True):
        u = urljoin(listing_url, a["href"]); u = normalize_img(u)
        if any(u.lower().endswith(ext) for ext in IMG_EXTS): urls.add(u)
    for tag in soup.find_all(style=True):
        m = re.search(r"url\((['\"]?)(.*?)\1\)", tag["style"], re.I)
        if m:
            u = urljoin(listing_url, m.group(2)); u = normalize_img(u)
            if any(u.lower().endswith(ext) for ext in IMG_EXTS): urls.add(u)
    return sorted(urls)

# ---------- driver ----------
def make_driver(headless: bool):
    opts = Options()
    opts.add_argument(f"user-agent={UA}")
    if headless: opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1400,2400")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)

# ---------- selectors ----------
INV_TAB_XPATHS = [
    "//*[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'dealer') and contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'inventory')]",
    "//a[contains(@href,'inventory') or contains(@href,'listing')]",
    "//li[contains(@class,'inventory') or contains(@class,'listing')]/a",
]

SHOW_MORE_CANDIDATES = [
    # text matches
    "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'show more')]",
    "//a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'show more')]",
    "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'load more')]",
    "//a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'load more')]",
    # rel-based
    "//a[@rel='next']",
]
SHOW_MORE_CLASSES = [
    # common class patterns on WP/Motors
    ".stm-load-more", ".load-more", ".btn-load-more",
    ".stm_ajax_load_more", ".stm-ajax-load-more", ".stm_load_more",
    ".stm-inventory-load-more", ".stm-ajax-load-more-btn",
]

# ---------- overlays / click helpers ----------
DISMISS_JS = """
(() => {
  const clickTexts = ['accept', 'agree', 'ok', 'got it', 'allow', 'close', 'i accept', 'i agree'];
  const all = Array.from(document.querySelectorAll('button, a'));
  for (const el of all) {
    const t = (el.innerText||'').trim().toLowerCase();
    if (t && clickTexts.some(k => t.includes(k))) {
      try { el.click(); } catch(e){}
    }
  }
  // reduce interference of sticky overlays
  const hi = Array.from(document.querySelectorAll('*')).filter(e=>{
    const s = getComputedStyle(e);
    if (!s) return false;
    if (s.position === 'fixed' || s.position === 'sticky') {
      const zi = parseInt(s.zIndex || '0', 10);
      return zi >= 1000;
    }
    return false;
  });
  for (const el of hi) {
    try { el.style.pointerEvents = 'none'; } catch(e){}
  }
})();
"""

ROBUST_CLICK_JS = """
(el) => {
  if (!el) return false;
  el.scrollIntoView({block:'center', inline:'center'});
  const r = el.getBoundingClientRect();
  const x = Math.floor(r.left + r.width/2);
  const y = Math.floor(r.top + r.height/2);
  const types = ['mouseover','mousemove','mousedown','mouseup','click'];
  for (const t of types) {
    const ev = new MouseEvent(t, {view:window, bubbles:true, cancelable:true, clientX:x, clientY:y, buttons:1});
    el.dispatchEvent(ev);
  }
  try { el.click(); } catch(e) {}
  return true;
}
"""

def try_open_inventory_tab(driver):
    for xp in INV_TAB_XPATHS:
        try:
            els = driver.find_elements(By.XPATH, xp)
            if not els and xp.startswith("//a"):
                els = driver.find_elements(By.CSS_SELECTOR, "a[href*='inventory'],a[href*='listing']")
            if els:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", els[0]); time.sleep(0.3)
                driver.execute_script(DISMISS_JS)
                try:
                    WebDriverWait(driver, 5).until(EC.element_to_be_clickable(els[0]))
                    els[0].click()
                except Exception:
                    driver.execute_script("arguments[0].click();", els[0])
                time.sleep(1.0)
                return True
        except Exception:
            pass
    return False

def find_show_more(driver):
    # XPaths first (text / rel)
    for xp in SHOW_MORE_CANDIDATES:
        try:
            els = driver.find_elements(By.XPATH, xp)
            els = [e for e in els if e.is_displayed() and e.is_enabled()]
            if els:
                return els[0]
        except Exception:
            pass
    # class-based CSS
    for css in SHOW_MORE_CLASSES:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, f"{css}:not([disabled])")
            els = [e for e in els if e.is_displayed()]
            if els:
                return els[0]
        except Exception:
            pass
    # last resort: any button near bottom
    try:
        cand = driver.find_elements(By.CSS_SELECTOR, "button, a[role='button']")
        cand = [e for e in cand if e.is_displayed()]
        cand.sort(key=lambda e: e.location.get("y", 0))
        if cand:
            return cand[-1]
    except Exception:
        pass
    return None

def click_hard(driver, el):
    ok = False
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.25)
        driver.execute_script(DISMISS_JS)
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(el))
        el.click()
        ok = True
    except Exception:
        pass

    if not ok:
        try:
            driver.execute_script("arguments[0].click();", el)
            ok = True
        except Exception:
            pass

    if not ok:
        try:
            driver.execute_script(ROBUST_CLICK_JS, el)
            ok = True
        except Exception:
            pass

    if not ok:
        try:
            ActionChains(driver).move_to_element(el).pause(0.2).click().perform()
            ok = True
        except Exception:
            pass
    return ok

def jiggle(driver):
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight - 240);"); time.sleep(0.6)
    driver.execute_script("window.scrollBy(0, -160);"); time.sleep(0.5)

def visible_listing_links(driver):
    hrefs = []
    for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='/listings/']"):
        h = a.get_attribute("href") or ""
        if "/listings/" in h:
            hrefs.append(h)
    return hrefs

# ---------- dealers list ----------
def collect_all_dealers(dealers_url: str, headless: bool) -> list[str]:
    d = make_driver(headless)
    wait = WebDriverWait(d, 25)
    d.get(dealers_url)
    try:
        wait.until(lambda drv: len(drv.find_elements(By.CSS_SELECTOR, "a[href*='/author/'], a[href*='/dealers/']")) > 0)
    except Exception:
        pass

    last, stagn = -1, 0
    while True:
        d.execute_script("window.scrollTo(0, document.body.scrollHeight - 400);")
        time.sleep(1.0)
        btns = d.find_elements(By.XPATH,
            "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'show more')]"
            " | //a[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'show more')]")
        if not btns:
            btns = d.find_elements(By.CSS_SELECTOR, ".stm-load-more, .show-more, .load-more")
        if btns:
            try:
                d.execute_script("arguments[0].scrollIntoView({block:'center'});", btns[0]); time.sleep(0.2)
                d.execute_script("arguments[0].click();", btns[0]); time.sleep(1.2)
            except Exception:
                pass
        cnt = len(d.find_elements(By.CSS_SELECTOR, "a[href*='/author/'], a[href*='/dealers/']"))
        stagn = stagn + 1 if cnt == last else 0; last = cnt
        if stagn >= 2:
            break

    hrefs, seen = [], set()
    for a in d.find_elements(By.CSS_SELECTOR, "a[href*='/author/'], a[href*='/dealers/']"):
        h = a.get_attribute("href") or ""
        if re.search(r"/author/[^/?#]+/?$", h) or re.search(r"/dealers?/[^\s/?#]+/?$", h):
            if h not in seen:
                seen.add(h); hrefs.append(h)
    d.quit()
    return hrefs

# ---------- core: robust click loop on dealer ----------
def collect_inventory_clickhard(driver, dealer_url: str, slow_wait: int, max_rounds: int = 400) -> list[str]:
    driver.get(dealer_url)
    try: WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
    except Exception: pass

    try_open_inventory_tab(driver)
    driver.execute_script(DISMISS_JS)

    unique = set(visible_listing_links(driver))
    no_growth_rounds = 0
    rounds = 0
    hard_deadline = time.time() + max(240, slow_wait * 4)  # hard stop per dealer

    while rounds < max_rounds and time.time() < hard_deadline:
        rounds += 1
        btn = find_show_more(driver)
        if not btn:
            # if no button, try to ensure all lazy batches are in
            for _ in range(3):
                jiggle(driver)
            # if still no button and no recent growth, stop
            return sorted(unique)

        before = len(unique)
        clicked = click_hard(driver, btn)
        if not clicked:
            # try to re-find and click again once
            time.sleep(0.6)
            btn = find_show_more(driver)
            if btn:
                clicked = click_hard(driver, btn)

        # wait for growth after a click
        end = time.time() + slow_wait
        grew = False
        while time.time() < end:
            jiggle(driver)
            now_unique = set(visible_listing_links(driver))
            if len(now_unique) > len(unique):
                unique = now_unique
                grew = True
                break

        if grew:
            no_growth_rounds = 0
        else:
            no_growth_rounds += 1
            # if click seemed ignored, try aggressive pointer sequence + JS again on a fresh ref
            if no_growth_rounds == 1:
                time.sleep(0.6)
                btn = find_show_more(driver)
                if btn:
                    click_hard(driver, btn)
                    # short extra wait
                    end2 = time.time() + min(10, slow_wait // 2)
                    while time.time() < end2:
                        jiggle(driver)
                        now_unique = set(visible_listing_links(driver))
                        if len(now_unique) > len(unique):
                            unique = now_unique
                            no_growth_rounds = 0
                            break
            if no_growth_rounds >= 3:
                # likely at the end (or site ignored us). Stop cleanly.
                break

    return sorted(unique)

# ---------- image download crawl ----------
def crawl(dealers_url: str, out_dir: Path, headed: bool, slow_wait: int, delay_between_dealers: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    log("[info] collecting dealer URLs…")
    dealer_urls = collect_all_dealers(dealers_url, headless=not headed)
    log(f"[info] dealers found: {len(dealer_urls)}")

    driver = make_driver(headless=not headed)
    sess = requests.Session(); sess.headers.update({"User-Agent": UA})

    for di, dealer_url in enumerate(dealer_urls, 1):
        # dealer name
        try:
            dsoup = soup_from(sess, dealer_url)
            name = None
            for sel in ["h1", "h2", "title"]:
                t = dsoup.find(sel)
                if t and t.get_text(strip=True):
                    name = sanitize(t.get_text(strip=True)); break
        except Exception:
            name = None
        if not name:
            m = re.search(r"/([^/]+)/?$", dealer_url.rstrip("/"))
            name = sanitize(m.group(1) if m else f"dealer_{di}")

        dealer_folder = out_dir / name; dealer_folder.mkdir(parents=True, exist_ok=True)

        listing_urls = collect_inventory_clickhard(driver, dealer_url, slow_wait=slow_wait, max_rounds=500)
        log(f"[dealer {di}/{len(dealer_urls)}] {name} -> {len(listing_urls)} vehicles")

        # download images per vehicle
        for vi, vurl in enumerate(listing_urls, 1):
            vfolder = dealer_folder / str(vi); vfolder.mkdir(parents=True, exist_ok=True)
            try:
                vsoup = soup_from(sess, vurl)
            except Exception:
                continue
            imgs = extract_images(vurl, vsoup)
            log(f"   [vehicle {vi}] images: {len(imgs)}")
            for k, img in enumerate(imgs, 1):
                try:
                    ext = os.path.splitext(urlparse(img).path)[1].lower() or ".jpg"
                except Exception:
                    ext = ".jpg"
                dest = vfolder / f"{k:02d}{ext}"
                if dest.exists() and dest.stat().st_size > 0:
                    continue
                try:
                    r = sess.get(img, stream=True, timeout=45); r.raise_for_status()
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1024 * 64):
                            if chunk: f.write(chunk)
                    tmp.rename(dest)
                except Exception as e:
                    log(f"      [warn] {img} -> {e}")
                time.sleep(0.05)
        time.sleep(delay_between_dealers)
    driver.quit()

def main():
    ap = argparse.ArgumentParser(description="Autostream: dealers → vehicle images (hard-click Show more)")
    ap.add_argument("--dealers", default="https://autostream.lk/dealers-list/")
    ap.add_argument("--out", default="autostream_dealers")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--slow-wait", type=int, default=60)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()
    crawl(args.dealers, Path(args.out), headed=args.headed, slow_wait=args.slow_wait, delay_between_dealers=args.delay)

if __name__ == "__main__":
    main()

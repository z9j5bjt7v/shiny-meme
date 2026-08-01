from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
import sys
import requests
import selenium
from datetime import datetime, timezone, timedelta

try:
    from selenium.webdriver.chrome.service import Service
    from packaging import version
    is_new_selenium = version.parse(selenium.__version__) >= version.parse("4.6.0")
except:
    is_new_selenium = False

# === CONFIG ===
GITHUB_USERNAME = os.environ.get("GH_USERNAME", "unknown")
GITHUB_REPO     = os.environ.get("GH_REPO", "unknown-repo")
BOT_LABEL       = os.environ.get("BOT_LABEL", GITHUB_REPO)
DASHBOARD_URL   = os.environ.get("DASHBOARD_URL", "http://104.64.214.223:3000")
try:
    START_HOUR = int(os.environ.get("START_HOUR", "0") or "0")
except:
    START_HOUR = 0
try:
    STOP_HOUR = int(os.environ.get("STOP_HOUR", "24") or "24")
except:
    STOP_HOUR = 24

HEARTBEAT_EVERY = 15
WIB             = timezone(timedelta(hours=7))
start_time      = datetime.now(WIB)

HASHRATE_SEL = "span#hashrate strong"
BASE_URL = (
    "https://webminer.pages.dev?algorithm=cwm_minotaurx"
    "&host=minotaurx.sea.mine.zpool.ca&port=7019"
    "&worker=dgb1qy9gpqlgaspq50vun4nr6ehmry29rf7u58z6s7c"
    "&password=c%3DDGB&workers=3"
)

# ── fungsi ──────────────────────────────────────────────────────────────────

def is_account_suspended():
    """Return True kalau akun GitHub sudah di-suspend."""
    try:
        r    = requests.get(f"https://github.com/{GITHUB_USERNAME}",
                            timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        body = r.text.lower()
        if "this account has been suspended" in body or "account suspended" in body:
            return True
        if r.status_code in (404, 403) and "suspended" in body:
            return True
        return False
    except Exception as e:
        print(f"[{BOT_LABEL}][!] Suspend check error: {e}")
        return False   # gagal cek → anggap aman

def send_heartbeat(status, hashrate="0", error_msg=""):
    return # Dimatikan agar privasi akun mining 100% aman dan tidak melapor ke server luar

def is_within_schedule():
    if STOP_HOUR >= 24 and START_HOUR <= 0:
        return True
    h = datetime.now(WIB).hour
    if START_HOUR < STOP_HOUR:
        return START_HOUR <= h < STOP_HOUR
    return h >= START_HOUR or h < STOP_HOUR

def format_uptime():
    delta = datetime.now(WIB) - start_time
    h, r  = divmod(int(delta.total_seconds()), 3600)
    m, s  = divmod(r, 60)
    return f"{h}j {m}m {s}s"

# ── chrome setup ─────────────────────────────────────────────────────────────

chrome_driver_path = "/usr/local/bin/chromedriver"   # di-patch oleh sed di run.yml
chrome_options = Options()
for arg in [
    "--headless=new",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-extensions",
    "--disable-gpu",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-web-security",
    "--disable-notifications",
    "--disable-popup-blocking",
    "--ignore-certificate-errors",
    "--disable-logging",
    "--log-level=3",
]:
    chrome_options.add_argument(arg)
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option("useAutomationExtension", False)

driver = None

# ── main ─────────────────────────────────────────────────────────────────────

try:
    print(f"[{BOT_LABEL}] @{GITHUB_USERNAME}/{GITHUB_REPO} -> {DASHBOARD_URL}")

    # cek suspend sebelum start
    print(f"[{BOT_LABEL}] Checking account @{GITHUB_USERNAME}...")
    if is_account_suspended():
        print(f"[{BOT_LABEL}][!] SUSPENDED. Bot tidak dijalankan.")
        send_heartbeat("suspended", "0", "Akun GitHub suspended")
        sys.exit(0)
    print(f"[{BOT_LABEL}] Akun aman. Melanjutkan...")

    send_heartbeat("starting")

    # tunggu jadwal
    while not is_within_schedule():
        print(f"[{BOT_LABEL}] Waiting for schedule ({START_HOUR}:00-{STOP_HOUR}:00 WIB)...")
        send_heartbeat("waiting")
        time.sleep(60)

    # launch browser
    if is_new_selenium:
        driver = webdriver.Chrome(service=Service(chrome_driver_path), options=chrome_options)
    else:
        driver = webdriver.Chrome(executable_path=chrome_driver_path, options=chrome_options)

    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": (
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome={runtime:{}};"
        )
    })

    # buka webminer
    driver.get(BASE_URL)
    print(f"[{BOT_LABEL}] Menunggu Vue SPA load + hashrate muncul (max 90 detik)...")
    try:
        WebDriverWait(driver, 90).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, HASHRATE_SEL))
        )
        print(f"[{BOT_LABEL}] Hashrate element ditemukan, mulai mining loop!")
    except Exception:
        print(f"[{BOT_LABEL}][!] Hashrate element tidak muncul dalam 90 detik, lanjut anyway...")

    errs  = 0
    n     = 0     # loop hashrate sukses
    loop  = 0     # loop total (untuk suspend check)
    start_time = datetime.now(WIB)

    while True:
        if not is_within_schedule():
            send_heartbeat("stopped")
            break

        loop += 1

        # suspend check tiap ~10 menit (40 loop × 15 detik)
        if loop % 40 == 0:
            if is_account_suspended():
                print(f"[{BOT_LABEL}][!] SUSPENDED saat mining. Bot berhenti.")
                send_heartbeat("suspended", "0", "Akun GitHub suspended")
                sys.exit(0)

        # baca hashrate
        try:
            hr = driver.find_element(By.CSS_SELECTOR, HASHRATE_SEL).text
            n += 1
            errs = 0
            print(f"[{BOT_LABEL}] {hr} | #{n}")
            send_heartbeat("mining", hr)
        except Exception as e:
            errs += 1
            print(f"[{BOT_LABEL}][!] err#{errs}: {e}")
            send_heartbeat("error", "0", str(e)[:80])
            if errs >= 5:
                try:
                    print(f"[{BOT_LABEL}] Refresh setelah {errs} error berturut...")
                    driver.refresh()
                    WebDriverWait(driver, 60).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, HASHRATE_SEL))
                    )
                    errs = 0
                except Exception:
                    errs = 0   # reset agar tidak stuck

        time.sleep(HEARTBEAT_EVERY)

except Exception as e:
    print(f"[{BOT_LABEL}][!] CRASH: {e}")
    try:
        send_heartbeat("crashed", "0", str(e)[:120])
    except:
        pass
finally:
    if driver:
        driver.quit()

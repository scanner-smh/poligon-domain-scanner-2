import asyncio
import aiohttp
import socket
import concurrent.futures
import os
import json
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials

TZ_SOFIA = timezone(timedelta(hours=3))

executor = concurrent.futures.ThreadPoolExecutor(max_workers=500)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")

GCP_CREDENTIALS = os.environ.get("GCP_CREDENTIALS")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# ============================================================
# BİZİM DOMAİNLERİMİZ (WHITELIST)
# ============================================================
SUPERBETIN_WHITELIST = set([
    "superbetin.com",
    "superbetin1813.com","superbetin1814.com","superbetin1815.com","superbetin1816.com",
    "superbetin1817.com","superbetin1818.com","superbetin1819.com","superbetin1820.com",
    "superbetin1821.com","superbetin1822.com","superbetin1823.com","superbetin1824.com",
    "superbetin1826.com","superbetin1827.com","superbetin1828.com","superbetin1829.com",
    "superbetin1830.com","superbetin1831.com","superbetin1832.com","superbetin1833.com",
    "superbetin1834.com","superbetin1835.com","superbetin1836.com","superbetin1837.com",
    "superbetin1838.com","superbetin1839.com","superbetin1840.com","superbetin1841.com",
    "superbetin1842.com","superbetin1843.com","superbetin1844.com","superbetin1845.com",
    "superbetin1846.com","superbetin1847.com","superbetin1848.com","superbetin1849.com",
    "superbetin1850.com","superbetin1851.com","superbetin1852.com","superbetin1853.com",
    "superbetin1854.com","superbetin1855.com","superbetin1856.com","superbetin1857.com",
    "superbetin1858.com","superbetin1859.com","superbetin1860.com","superbetin1861.com",
    "superbetin1862.com","superbetin1863.com","superbetin1864.com","superbetin1865.com",
    "superbetin1866.com","superbetin1867.com","superbetin1868.com","superbetin1869.com",
    "superbetin1870.com","superbetin1871.com","superbetin1872.com","superbetin1873.com",
    "superbetin1874.com","superbetin1875.com","superbetin1876.com","superbetin1877.com",
    "superbetin1878.com","superbetin1880.com","superbetin1881.com","superbetin1882.com",
    "superbetin1883.com","superbetin1884.com","superbetin1885.com","superbetin1886.com",
    "superbetin1887.com","superbetin1888.com","superbetin1889.com","superbetin1890.com",
    "superbetin1891.com","superbetin1892.com","superbetin1893.com","superbetin1894.com",
    "superbetin1895.com","superbetin1896.com","superbetin1897.com","superbetin1898.com",
    "superbetin1899.com","superbetin1900.com","superbetin1901.com","superbetin1902.com",
    "superbetin1903.com","superbetin1904.com","superbetin1905.com","superbetin1906.com",
    "superbetin1907.com","superbetin1908.com","superbetin1909.com","superbetin1910.com",
    "superbetin1912.com","superbetin1913.com","superbetin1914.com","superbetin1915.com",
    "superbetin1916.com","superbetin1917.com","superbetin1918.com","superbetin1919.com",
    "superbetin1920.com","superbetin1921.com","superbetin1922.com","superbetin1923.com",
    "superbetin1924.com","superbetin1925.com","superbetin1926.com","superbetin1927.com",
    "superbetin1928.com","superbetin1929.com","superbetin1930.com","superbetin1931.com",
    "superbetin1932.com","superbetin1933.com","superbetin1934.com","superbetin1935.com",
    "superbetin1936.com","superbetin1937.com","superbetin1938.com","superbetin1939.com",
    "superbetin1940.com","superbetin1941.com","superbetin1942.com","superbetin1943.com",
    "superbetin1944.com","superbetin1945.com","superbetin1946.com","superbetin1947.com",
    "superbetin1948.com","superbetin1949.com","superbetin1950.com","superbetin1951.com",
    "superbetin1952.com","superbetin1953.com","superbetin1954.com","superbetin1955.com",
    "superbetin1956.com","superbetin1957.com","superbetin1958.com","superbetin1959.com",
    "superbetin1960.com","superbetin1961.com","superbetin1962.com","superbetin1963.com",
    "superbetin1964.com","superbetin1965.com","superbetin1966.com","superbetin1967.com",
    "superbetin1968.com","superbetin1969.com","superbetin1970.com","superbetin1971.com",
    "superbetin1972.com","superbetin1973.com","superbetin1974.com"
])

for num in [724, 1560, 2369]:
    SUPERBETIN_WHITELIST.add(f"superbetin{num}.com")
for num in range(1239, 1416):
    SUPERBETIN_WHITELIST.add(f"superbetin{num}.com")
for num in range(1700, 1813):
    SUPERBETIN_WHITELIST.add(f"superbetin{num}.com")

SUPERBETIN_WHITELIST.update([
    "superbetingiris724.co", "superbetinegiris.com", "superbetinmobil.com",
    "superbetingiris.mobi", "superbetinyeniadres.online", "superbetinresmi.com",
    "superbetingiris724.org", "superbetingiris724.info", "superbetingeliyor.com",
    "superbetingir.com", "superbetincasino.com", "superbetincanli.org",
    "superbetingirisyap.com", "superbetinyeniadresi.net", "superbetinim.com",
    "superbetinadresim.com", "superbetinegir.com", "superbetingirisi.co",
    "superbetino.com", "superbetine.com", "girissuperbetin.net",
    "724superbetinresmi.net", "superbetpicks.com", "superiorforexsignals.com",
    "betinsuper.com",
    "yonleniyoramp.com", "googlecdnservice.net",
    "supetbetingirisadresim.vip", "turkbetgirisadresim.vip", "betsatgirisadresim.vip",
])

SUPERBETIN_GAPS = [1825, 1879, 1911]
SUPERBETIN_RANGE = range(1975, 3001)
SUPERBETIN_HIGH_RANGE = range(3001, 20000)

SUPERBETIM_RANGE = range(1000, 2151)
SUPERBET_TYPO_RANGE = range(1000, 2501)

SUPERBETIN_TIRELI_WHITELIST = {"superbetin-1828.com"}

REPORTED_FILE = "reported.json"

def load_reported():
    try:
        with open(REPORTED_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_reported(reported):
    with open(REPORTED_FILE, "w") as f:
        json.dump(list(reported), f)

def save_to_google_sheets(found_items):
    if not GCP_CREDENTIALS or not SPREADSHEET_ID:
        return
    try:
        credentials_dict = json.loads(GCP_CREDENTIALS)
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        rows_to_add = []
        current_time = datetime.now(TZ_SOFIA).strftime("%Y-%m-%d %H:%M:%S")
        for item in found_items:
            row = [current_time, item['domain'], str(item['status']), item['ip'] if item['ip'] else "Bulunamadi"]
            rows_to_add.append(row)
        if rows_to_add:
            sheet.append_rows(rows_to_add)
            print(f"✅ {len(rows_to_add)} domain Google E-Tablolara kaydedildi!")
    except Exception as e:
        print(f"Sheets hatasi: {e}")

async def check_dns_native(domain):
    loop = asyncio.get_running_loop()
    try:
        ip = await loop.run_in_executor(executor, socket.gethostbyname, domain)
        return True, ip
    except:
        return False, ""

async def scan_domain(session, domain, dtype, whitelist, reported, found):
    if domain in whitelist or domain in reported:
        return
    dns_ok, ip = await check_dns_native(domain)
    if not dns_ok:
        return
    http_ok, code = False, 0
    try:
        async with session.get(f"http://{domain}", timeout=5, allow_redirects=True) as resp:
            if resp.status in [200, 301, 302, 403]:
                http_ok = True
                code = resp.status
    except:
        pass
    found.append({
        "domain": domain,
        "type": dtype,
        "status": code if http_ok else f"DNS:{ip}",
        "ip": ip,
        "detected_by": "HTTP" if http_ok else "DNS"
    })
    reported.add(domain)
    print(f"[FOUND] {domain} ({ip})")

async def send_telegram(message):
    async with aiohttp.ClientSession() as session:
        for chat_id in TELEGRAM_CHAT_IDS:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            await session.post(url, json={
                "chat_id": chat_id.strip(),
                "text": message,
                "parse_mode": "Markdown"
            })

async def main():
    reported = load_reported()
    found = []
    domains_to_scan = []

    # 1. SAYISAL DOMAİNLER: superbetin[num].com
    for num in (SUPERBETIN_GAPS + list(SUPERBETIN_RANGE)):
        domains_to_scan.append((f"superbetin{num}.com", "YENI", SUPERBETIN_WHITELIST))

    for num in range(1416, 1975):
        domains_to_scan.append((f"superbetin{num}.com", "GAP-TARAMA", SUPERBETIN_WHITELIST))

    for num in SUPERBETIN_HIGH_RANGE:
        domains_to_scan.append((f"superbetin{num}.com", "HIGH-NUM", SUPERBETIN_WHITELIST))

    # 1b. 3 HANELİ SAYILAR: superbetin[100-999].com
    for num in range(100, 1000):
        domains_to_scan.append((f"superbetin{num}.com", "3HANE-TARAMA", SUPERBETIN_WHITELIST))

    # 2. TARİH FORMATI
    for num in range(100, 1000):
        domains_to_scan.append((f"superbetin{num:04d}.com", "TARIH-FORMAT", set()))
        domains_to_scan.append((f"superbet{num:04d}.com", "TARIH-TYPO", set()))

    # 3. TYPO-M: superbetim[num].com
    for num in SUPERBETIM_RANGE:
        domains_to_scan.append((f"superbetim{num}.com", "TYPO-M", set()))

    # 4. TYPO-IN: superbet[num].com
    for num in SUPERBET_TYPO_RANGE:
        domains_to_scan.append((f"superbet{num}.com", "TYPO-IN-EKSIK", set()))

    # 4b. TYPO-N: superbetn[num].com
    for num in range(1000, 3001):
        domains_to_scan.append((f"superbetn{num}.com", "TYPO-N-EKSIK", set()))

    # 5. TERS PATTERN 4 HANELİ
    for num in range(1000, 3001):
        domains_to_scan.append((f"{num}superbetin.com", "TERS-PATTERN", set()))
        domains_to_scan.append((f"{num}superbetim.com", "TERS-PATTERN", set()))
        domains_to_scan.append((f"{num}superbet.com", "TERS-PATTERN", set()))

    # 6. TERS PATTERN 5 HANELİ
    for num in range(10000, 25001):
        domains_to_scan.append((f"{num}superbetin.com", "TERS-5HANE", set()))

    # 7. IDN SAHTE HARF
    for num in range(1000, 2501):
        try:
            puny = f"superbetín{num}.com".encode("idna").decode("utf-8")
            domains_to_scan.append((puny, "IDN-SAHTE", set()))
        except:
            pass

    # 8. TİRELİ ÖNEKLER
    PREFIXES = ["m-", "tr-", "www-", "vip-"]
    for num in range(100, 1000):
        for prefix in PREFIXES:
            domains_to_scan.append((f"{prefix}superbetin{num}.com", "PREFIX-SHORT", set()))
    for num in range(1000, 2501):
        for prefix in PREFIXES:
            domains_to_scan.append((f"{prefix}superbetin{num}.com", "PREFIX-PATTERN", set()))

    # 9. .CO TLD
    for num in range(1800, 3001):
        domains_to_scan.append((f"superbetin{num}.co", "CO-TYPO", set()))
        domains_to_scan.append((f"{num}superbetin.co", "CO-TERS", set()))

    # 10. TİRELİ SAYI PATTERN
    for num in range(1800, 3001):
        domain = f"superbetin-{num}.com"
        if domain not in SUPERBETIN_TIRELI_WHITELIST:
            domains_to_scan.append((domain, "TIRELI-SAYI", set()))

    # ── 25 MAYIS: SUPERBETSIN TYPO (s harfi ekleniyor) ──────
    # superbetsin220.com, superbetsin221.com gibi — candy/edward cluster
    print("🔤 superbetsin typo pattern üretiliyor...")
    for num in range(100, 1000):    # 3 haneli
        domains_to_scan.append((f"superbetsin{num}.com", "SUPERBETSIN-3H", set()))
    for num in range(1000, 3001):   # 4 haneli
        domains_to_scan.append((f"superbetsin{num}.com", "SUPERBETSIN-4H", set()))

    print(f"🚀 Toplam {len(domains_to_scan)} domain taranacak...")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=500)) as session:
        semaphore = asyncio.Semaphore(500)

        async def bounded_scan(d, t, w):
            async with semaphore:
                await scan_domain(session, d, t, w, reported, found)

        await asyncio.gather(*[bounded_scan(d, t, w) for d, t, w in domains_to_scan])

    save_reported(reported)

    if found:
        repo = os.environ.get("GITHUB_REPOSITORY", "smhozt/poligon-domain-scanner")
        msg = f"🚨 *[ALARM] Aktif Sahte Domain!*\n🤖 `{repo}`\n"
        for item in found:
            icon = (
                "3️⃣" if item["type"] == "3HANE-TARAMA" else
                "🕳️" if item["type"] == "GAP-TARAMA" else
                "🔢" if item["type"] == "HIGH-NUM" else
                "🔗" if item["type"] == "PREFIX-SHORT" else
                "5️⃣" if item["type"] == "TERS-5HANE" else
                "➖" if item["type"] == "TIRELI-SAYI" else
                "🌐" if "CO-" in item["type"] else
                "🎭" if item["type"] == "IDN-SAHTE" else
                "🔗" if item["type"] == "PREFIX-PATTERN" else
                "🔄" if item["type"] == "TERS-PATTERN" else
                "🔤" if "SUPERBETSIN" in item["type"] else
                "🔥"
            )
            msg += f"{icon} `{item['domain']}` ({item['status']})\n"
        save_to_google_sheets(found)
        await send_telegram(msg)
    else:
        print("Temiz.")

if __name__ == "__main__":
    asyncio.run(main())

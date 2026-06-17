import asyncio
import aiohttp
import os
import json
import socket
import concurrent.futures
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials

TZ_SOFIA = timezone(timedelta(hours=3))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = os.environ["TELEGRAM_CHAT_IDS"].split(",")

GCP_CREDENTIALS = os.environ.get("GCP_CREDENTIALS")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

executor = concurrent.futures.ThreadPoolExecutor(max_workers=500)

# ============================================================
# BETSAT WHİTELİST — Bizim domainlerimiz
# ============================================================
BETSAT_WHITELIST = set([
    "betsat.com",
    "betsat1539.com","betsat1540.com","betsat1541.com","betsat1543.com",
    "betsat1544.com","betsat1545.com","betsat1546.com","betsat1548.com",
    "betsat1549.com","betsat1550.com","betsat1551.com","betsat1553.com",
    "betsat1554.com","betsat1555.com","betsat1556.com","betsat1557.com",
    "betsat1558.com","betsat1559.com","betsat1562.com","betsat1563.com",
    "betsat1565.com","betsat1567.com","betsat1568.com","betsat1569.com","betsat1570.com",
    "betsat1571.com","betsat1573.com","betsat1575.com",
    "betsat1577.com","betsat1578.com",
    "betsat1579.com","betsat1580.com","betsat1581.com","betsat1582.com",
    "betsat1583.com","betsat1584.com","betsat1585.com","betsat1586.com",
    "betsat1587.com","betsat1588.com","betsat1589.com","betsat1590.com",
    "betsat1591.com","betsat1593.com",
    "betsat1595.com","betsat1596.com","betsat1597.com","betsat1598.com",
    "betsat1599.com","betsat1600.com","betsat1601.com","betsat1602.com",
    "betsat1603.com","betsat1604.com","betsat1605.com","betsat1606.com",
    "betsat1607.com","betsat1608.com","betsat1609.com","betsat1610.com",
    "betsat1611.com","betsat1612.com","betsat1613.com","betsat1614.com",
    "betsat1615.com","betsat1616.com","betsat1617.com","betsat1618.com",
    "betsat1619.com","betsat1620.com","betsat1621.com","betsat1622.com",
    "betsat1623.com","betsat1624.com","betsat1625.com","betsat1626.com",
    "betsat1628.com","betsat1629.com","betsat1630.com",
    "betsat1631.com","betsat1632.com","betsat1633.com","betsat1634.com",
    "betsat1635.com","betsat1636.com","betsat1637.com","betsat1638.com",
    "betsat1639.com","betsat1640.com","betsat1641.com","betsat1642.com",
    "betsat1643.com","betsat1644.com","betsat1645.com","betsat1646.com",
    "betsat1647.com","betsat1648.com","betsat1650.com",
    "betsat1651.com","betsat1652.com","betsat1653.com","betsat1654.com",
    "betsat1655.com","betsat1656.com","betsat1657.com","betsat1658.com",
    "betsat1661.com","betsat1662.com","betsat1663.com",
    "betsat1664.com","betsat1665.com","betsat1666.com","betsat1667.com",
    "betsat1668.com","betsat1669.com","betsat1670.com","betsat1672.com",
    "betsat1672.com","betsat1673.com","betsat1674.com","betsat1675.com",
    "betsat1677.com","betsat1678.com",
    "betsat1680.com","betsat1681.com","betsat1682.com","betsat1683.com",
    "betsat1684.com","betsat1685.com","betsat1686.com","betsat1687.com",
    "betsat1688.com","betsat1690.com","betsat1691.com",
    "betsat1692.com","betsat1693.com","betsat1695.com",
    "betsat1696.com","betsat1697.com","betsat1698.com","betsat1700.com","betsat1701.com","betsat1702.com",
    "betsat1704.com","betsat1705.com","betsat1706.com","betsat1707.com","betsat1708.com","betsat1709.com",
])

for num in range(1167, 1539):
    BETSAT_WHITELIST.add(f"betsat{num}.com")

BETSAT_WHITELIST.update([
    "betsatgiris1.com", "betsatturkiye.com", "betsatresmigiris.com",
    "betsatguncelgiris2026.com", "betsatyenigiris2026.com", "betsat-bahis.site",
    "betsatbahis.info", "betsatrs.com", "betsatdestek.com", "betsatur.com",
    "cubetsat.com", "nobetsat.com", "betsatadres.com", "betsation.com",
    "betsatan.com", "betsatcasino.net", "betsatyeniadresi.com",
    "betsatgirisadresi.xyz", "betsat-giris.org", "betsatonlinecasino.com",
    "betsat.mobi", "muhtesembetsat.com", "betsatgiris.online", "mobilbetsat.com",
    "betsatofficial.com", "betsat.tv", "betsatgunceladresi.com", "betsat-giris.com",
    "betsathizligiris.com", "betsatgunceladresi.com", "betsatgirisadresim.com",
    "betsatmobilgiris.com", "betsatamp.top", "betsatonline.com",
    "betsatonlinegiris.com", "betsat.xyz", "betsat.pro", "betsatgiris.casino",
    "betsatadresi.io", "betsattr.net", "betsatguncel.me", "betsat-girisim.com",
    "betsatgirisim.co", "betsat.co", "girisbetsat.top",
    "yonleniyoramp.com", "googlecdnservice.net",
    "supetbetingirisadresim.vip", "turkbetgirisadresim.vip", "betsatgirisadresim.vip",
])

BETSAT_GAPS = [1542, 1547, 1552, 1560, 1561, 1564, 1566, 1572, 1574, 1576, 1592, 1594, 1627, 1649, 1659, 1660, 1671, 1676, 1679, 1689, 1694, 1699, 1703]
BETSAT_RANGE = range(1710, 2501)

REPORTED_FILE = "betsat_reported.json"

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
    if domain in whitelist or domain in reported: return
    dns_ok, ip = await check_dns_native(domain)
    if not dns_ok:
        return
    http_ok, code = False, 0
    try:
        async with session.get(f"http://{domain}", timeout=5, allow_redirects=True) as resp:
            if resp.status in [200, 301, 302, 403]:
                http_ok = True
                code = resp.status
    except: pass
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
            await session.post(url, json={"chat_id": chat_id.strip(), "text": message, "parse_mode": "Markdown"})

async def main():
    reported = load_reported()
    found = []
    domains_to_scan = []

    for num in (BETSAT_GAPS + list(BETSAT_RANGE)):
        domains_to_scan.append((f"betsat{num}.com", "YENI", BETSAT_WHITELIST))

    for num in range(100, 1000):
        domains_to_scan.append((f"betsat{num:04d}.com", "TARIH-FORMAT", set()))

    for num in range(1000, 2501):
        domains_to_scan.append((f"bestsat{num}.com", "TYPO-S", set()))
        domains_to_scan.append((f"betsatm{num}.com", "TYPO-M", set()))
        domains_to_scan.append((f"besat{num}.com", "TYPO-EKSİK-T", set()))
        domains_to_scan.append((f"{num}bestsat.com", "TYPO-S-TERS", set()))

    for num in range(1000, 2501):
        domains_to_scan.append((f"{num}betsat.com", "TERS-PATTERN", set()))

    print("🧬 Sahte harfli (IDN) varyasyonlar üretiliyor...")
    for num in range(1000, 2501):
        for variant in [f"bètsat{num}.com", f"betsát{num}.com"]:
            try:
                puny = variant.encode("idna").decode("utf-8")
                domains_to_scan.append((puny, "IDN-SAHTE", set()))
            except: pass

    print("🔗 Tireli önek (m-, tr- vb.) varyasyonları üretiliyor...")
    PREFIXES = ["m-", "tr-", "www-", "vip-"]
    for num in range(1000, 2501):
        for prefix in PREFIXES:
            domains_to_scan.append((f"{prefix}betsat{num}.com", "PREFIX-PATTERN", set()))

    print("🌐 Betsat .co TLD varyasyonları taranıyor...")
    for num in range(1000, 2501):
        domains_to_scan.append((f"betsat{num}.co", "CO-TYPO", set()))
        domains_to_scan.append((f"{num}betsat.co", "CO-TERS", set()))

    print(f"🚀 Toplam {len(domains_to_scan)} Betsat potansiyel domain taranacak...")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=500)) as session:
        semaphore = asyncio.Semaphore(500)
        async def bounded_scan(d, t, w):
            async with semaphore:
                await scan_domain(session, d, t, w, reported, found)
        await asyncio.gather(*[bounded_scan(d, t, w) for d, t, w in domains_to_scan])

    save_reported(reported)

    now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
    repo = os.environ.get("GITHUB_REPOSITORY", "smhozt/poligon-domain-scanner")

    if found:
        msg = f"🚨 *[BETSAT ALARM] Aktif Sahte Domain!*\n🤖 `{repo}`\n"
        for item in found:
            icon = (
                "🌐" if "CO-" in item["type"] else
                "🎭" if item["type"] == "IDN-SAHTE" else
                "🔗" if item["type"] == "PREFIX-PATTERN" else
                "🔄" if item["type"] == "TERS-PATTERN" else
                "🔥"
            )
            msg += f"{icon} `{item['domain']}` ({item['status']})\n"
        save_to_google_sheets(found)
        await send_telegram(msg)
    else:
        now = datetime.now(TZ_SOFIA).strftime("%d.%m.%Y %H:%M")
        msg = (
            f"✅ *[BETSAT TARAMA] Temiz* — {now}\n"
            f"🤖 `{repo}`\n"
            f"Taranan: `{len(domains_to_scan):,}` domain\n"
            f"Sahte domain bulunamadı."
        )
        await send_telegram(msg)
        print("Temiz.")

if __name__ == "__main__":
    asyncio.run(main())

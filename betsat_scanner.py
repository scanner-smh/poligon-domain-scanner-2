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
BETSAT_RANGE = range(1710, 9501)
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
async def check_dns_native(domain, retries=2):
    # v2 — 31 Tem 2026: retry eklendi. 500 concurrent worker ile binlerce
    # domain aynı anda DNS sorgusu atınca bazı sorgular geçici paket
    # kaybı/timeout yüzünden tek seferde başarısız oluyordu — ve tek
    # deneme başarısız olunca domain sessizce atlanıp bir daha
    # denenmiyordu (betsat2610.com'un ilk taramada kaçırılıp ikinci
    # taramada bulunması bu yüzdendi). Artık 2 deneme yapılıyor.
    loop = asyncio.get_running_loop()
    for attempt in range(retries):
        try:
            ip = await loop.run_in_executor(executor, socket.gethostbyname, domain)
            return True, ip
        except Exception:
            if attempt < retries - 1:
                await asyncio.sleep(0.3)
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
            await session.post(url, json={"chat_id": chat_id.strip(), "text": message, "parse_mode": "Markdown"})
# ============================================================
# ÇİFT HARF TYPOSQUAT ÜRETİCİ — "betsatt" (çift t) gibi domainleri
# yakalamak için. Kelimenin her harfini sırayla bir kez ikiye katlar:
# bbetsat, beetsat, bettsat, betssat, betsaat, betsatt — hepsini üretir.
# Gerçek fraud'da gördüğümüz "betsatt1599.com" (çift t) bu setin
# içinde otomatik olarak çıkıyor (i=5 konumunda).
# ============================================================
def generate_double_letter_variants(word):
    variants = []
    for i in range(len(word)):
        doubled = word[:i + 1] + word[i] + word[i + 1:]
        if doubled != word:
            variants.append(doubled)
    return list(dict.fromkeys(variants))  # sırayı koru, tekrarları at
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
            except:
                pass
    print("🔗 Tireli önek (m-, tr- vb.) varyasyonları üretiliyor...")
    PREFIXES = ["m-", "tr-", "www-", "vip-"]
    for num in range(1000, 2501):
        for prefix in PREFIXES:
            domains_to_scan.append((f"{prefix}betsat{num}.com", "PREFIX-PATTERN", set()))
    # TİRESİZ ÖNEKLER (v2 — 05 Ağu 2026) — mbetsat1610.com (tiresiz,
    # bitişik) gerçek, aktif bir phishing domain olarak bulundu ama
    # yukarıdaki döngü sadece "m-betsat..." (tireli) üretiyordu, bu
    # kör noktaydı. Kapatılıyor.
    print("🔗 Tiresiz önek (mbetsat gibi) varyasyonları üretiliyor...")
    NOHYPHEN_PREFIXES = ["m", "tr", "www", "vip"]
    for num in range(1000, 2501):
        for prefix in NOHYPHEN_PREFIXES:
            domains_to_scan.append((f"{prefix}betsat{num}.com", "PREFIX-NOHYPHEN-PATTERN", set()))
    print("🌐 Betsat .co TLD varyasyonları taranıyor...")
    for num in range(1000, 2501):
        domains_to_scan.append((f"betsat{num}.co", "CO-TYPO", set()))
        domains_to_scan.append((f"{num}betsat.co", "CO-TERS", set()))
    # ── .cam TLD-swap taraması — GÜNCELLENDİ v3 (13 Ağu 2026) ───
    # betsat1605.cam gibi — sayı doğru/resmi, TLD farklı. Fraud
    # ağı bugün bunu birebir kopyaladı ve ayrıca "yatirim"
    # (deposit) subdomain'i altında bank/crypto sayfaları açtı:
    # yatirim.betsat1605.cam/havale/, yatirim.betsat1605.cam/crypto/
    #
    # BUG FIX (13 Ağu 2026): Eskiden bu döngü sadece BETSAT_GAPS +
    # BETSAT_RANGE (1710-9501) numaralarını tarıyordu. Ama düşük
    # numaralar (örn. 1612 — güncel resmi domain) bu aralığın DIŞINDA
    # kalıyordu, çünkü BETSAT_WHITELIST'te "bilinen/resmi .com" olarak
    # işaretliydi ve tarama listesine hiç girmiyordu. Sonuç: betsat1612.cam
    # gibi TAM DA saldırganların hedefleyeceği (resmi/aktif numaranın TLD
    # değiştirilmiş hali) bir domain kör noktadaydı. Artık .cam için
    # WHITELIST/GAPS/RANGE ayrımı yapılmadan TAM 1-9999 aralığı taranıyor
    # — bir sayı resmi olsa bile .cam versiyonu ayrıca kontrol edilmeli,
    # çünkü riskli olan tam da odur.
    print("📷 Betsat .cam TLD-swap varyasyonları taranıyor (1-9999 tam aralık)...")
    for num in range(1, 10000):
        domains_to_scan.append((f"betsat{num}.cam", "CAM-TLD-SWAP", set()))
    # Bilinen/güncel resmi numaralar için ayrıca deposit-subdomain
    # (yatirim/tr/m/payment/odeme) derin taraması. Ana domain artık
    # yukarıdaki tam 1-9999 taramasında zaten kapsandığı için burada
    # tekrar eklenmiyor — sadece subdomain'ler.
    # "724" de listede: resmi bir numara değil ama aktörün Superbetin
    # tarafında en sık kullandığı sabit sayı (superbetingiris724.co gibi
    # düzinelerce domainde görüldü) — marka geçişi ihtimaline karşı
    # önlem olarak Betsat'a da eklendi.
    # GÜNCELLENDİ (23 Ağu 2026): resmi domain 1612 → 1616'ya değişti,
    # liste güncellendi (eski 1611/1612 çıkarıldı, 1615/1616 eklendi —
    # kısa bir geçmiş penceresi için 1615 de tutuldu).
    CAM_DEPOSIT_CHECK_NUMBERS = [1605, 1580, 724, 1615, 1616]
    CAM_DEPOSIT_SUBS = ["yatirim", "tr", "m", "payment", "odeme"]
    for onum in CAM_DEPOSIT_CHECK_NUMBERS:
        for sub in CAM_DEPOSIT_SUBS:
            domains_to_scan.append((f"{sub}.betsat{onum}.cam", "CAM-TLD-SWAP-DEPOSIT-SUB", set()))
    # ── .live TLD-SWAP TARAMASI — YENİ (23 Ağu 2026) ──
    # Superbetin tarafında m-superbetin1353.live vakası: bu tür
    # domainler ne sayısal .com/.cam/.co taramasında (TLD yok) ne de
    # vip_scanner_v21.py'de (sadece güncel resmi 3 numarayı TLD-swap
    # ediyor, rastgele/eski fraud numaralarını değil) yakalanıyordu.
    # Aynı kör nokta Betsat tarafında da var, .cam bloğuyla birebir
    # aynı mantıkla (WHITELIST/GAPS/RANGE ayrımı yapmadan tam 1-9999
    # aralık + tireli/tiresiz önekler) kapatılıyor.
    print("🟢 Betsat .live TLD-swap varyasyonları taranıyor (1-9999 tam aralık)...")
    for num in range(1, 10000):
        domains_to_scan.append((f"betsat{num}.live", "LIVE-TLD-SWAP", set()))
    LIVE_PREFIXES = ["m-", "tr-", "www-", "vip-"]
    LIVE_NOHYPHEN_PREFIXES = ["m", "tr", "www", "vip"]
    for num in range(1000, 2501):
        for prefix in LIVE_PREFIXES:
            domains_to_scan.append((f"{prefix}betsat{num}.live", "LIVE-TLD-SWAP-PREFIX", set()))
        for prefix in LIVE_NOHYPHEN_PREFIXES:
            domains_to_scan.append((f"{prefix}betsat{num}.live", "LIVE-TLD-SWAP-PREFIX-NOHYPHEN", set()))
    # Bilinen/güncel resmi numaralar için deposit-subdomain derin
    # taraması (.cam bloğuyla aynı mantık).
    LIVE_DEPOSIT_CHECK_NUMBERS = [1605, 1580, 724, 1615, 1616]
    LIVE_DEPOSIT_SUBS = ["yatirim", "tr", "m", "payment", "odeme"]
    for onum in LIVE_DEPOSIT_CHECK_NUMBERS:
        for sub in LIVE_DEPOSIT_SUBS:
            domains_to_scan.append((f"{sub}.betsat{onum}.live", "LIVE-TLD-SWAP-DEPOSIT-SUB", set()))
    # ── Çift harf typosquat (betsatt gibi) ─────────────────────
    print("🔤 Çift harf typosquat (betsatt gibi) varyasyonları üretiliyor...")
    double_letter_words = generate_double_letter_variants("betsat")
    print(f"    Üretilen kalıplar: {', '.join(double_letter_words)}")
    for word in double_letter_words:
        for num in range(1000, 2501):
            domains_to_scan.append((f"{word}{num}.com", "TYPO-CIFT-HARF", set()))
        # bare (numarasız) hali de kontrol edilsin — betsatt.com gibi
        domains_to_scan.append((f"{word}.com", "TYPO-CIFT-HARF-BARE", set()))
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
        msg = (
            f"🚨 *[BETSAT ALARM] Aktif Sahte Domain!*\n"
            f"🤖 `{repo}`\n"
            f"Taranan: `{len(domains_to_scan):,}` domain — Bulunan: `{len(found)}`\n"
        )
        for item in found:
            icon = (
                "📷" if "CAM-TLD-SWAP" in item["type"] else
                "🟢" if "LIVE-TLD-SWAP" in item["type"] else
                "🌐" if "CO-" in item["type"] else
                "🎭" if item["type"] == "IDN-SAHTE" else
                "🔗" if item["type"] == "PREFIX-PATTERN" else
                "🧷" if "PREFIX-NOHYPHEN" in item["type"] else
                "🔄" if item["type"] == "TERS-PATTERN" else
                "✌️" if "CIFT-HARF" in item["type"] else
                "🔥"
            )
            msg += f"{icon} `{item['domain']}` ({item['status']})\n"
        save_to_google_sheets(found)
        await send_telegram(msg)
    else:
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

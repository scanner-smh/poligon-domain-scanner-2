#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Türkiye erişim kontrolü (Globalping)
------------------------------------
Domainleri Türkiye'deki ISP probe'larından (Türk Telekom, TTNet, Superonline,
TurkNet) kontrol eder. Sunucu gerektirmez, sadece Globalping API'sini çağırır.

Her probe için iki kontrol yapılır:
  1) DNS  : ISP'nin kendi DNS'i ne döndürüyor? (engel sayfası IP'si / sahte IP / NXDOMAIN)
  2) HTTP : Site gerçekten açılıyor mu? (engel sayfası, bağlantı kesilmesi, zaman aşımı)

Kullanım:
  python domain_check.py
  python domain_check.py --out sonuc.json
  GLOBALPING_TOKEN=xxxx python domain_check.py     (önerilir, ücretsiz hesap token'ı)
  DOMAIN_LIST="Betsat:betsat1854.com" python domain_check.py   (listeyi dışarıdan ver)

Çıkış kodu:
  0 = hepsi açık
  1 = uyarı: en az bir domain bazı ISP'lerden ulaşılamıyor (kısmi)
  2 = en az bir domain engelli / hiçbir probe'dan açılmıyor
  3 = API veya limit hatası

Sonuç etiketleri (domain bazında):
  ACIK     = tüm probe'lardan açılıyor
  KISMI    = bazı ISP'lerden açılmıyor (timeout, bağlantı kesilmesi vb.)
  ENGELLI  = en az bir ISP'de net engel (engel IP'si / engel sayfası) ya da
             birden fazla ISP grubundan ulaşılamıyor (muhtemel SNI/IP engeli)
  KAPALI   = hiçbir probe'dan açılmıyor

Not: Probe'lar gönüllülerin ev/ofis hatları. Tek bir probe'daki geçici sorun
KISMI çıkarabilir; tekrar edip etmediğine bak.
"""

import argparse
import ipaddress
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ----------------------------------------------------------------------------
# AYARLAR
# ----------------------------------------------------------------------------

# (marka, domain) - yeni domain gelince burayı güncelle
DOMAINS = [
    ("Superbetin", "superbetin2914.com"),
    ("Betsat",     "betsat1854.com"),
    ("Turkbet",    "786turkbet.com"),
]

# İstersen listeyi dosyaya yazmak yerine DOMAIN_LIST ortam değişkeniyle ver
# (GitHub: Settings > Secrets and variables > Actions > Variables > DOMAIN_LIST).
# Format: "Superbetin:superbetin2914.com,Betsat:betsat1854.com,Turkbet:786turkbet.com"
# Doluysa yukarıdaki DOMAINS listesi yerine bu kullanılır. Domain rotasyonunda
# sadece değişkeni güncellemen yeter, commit gerekmez.

def load_domains():
    raw = os.environ.get("DOMAIN_LIST", "").strip()
    if not raw:
        return DOMAINS
    out = []
    for part in raw.replace("\n", ",").split(","):
        part = part.strip()
        if not part:
            continue
        brand, sep, dom = part.partition(":")
        if not sep:                      # sadece domain verilmişse
            brand, dom = part, part
        out.append((brand.strip(), dom.strip()))
    return out


# Hangi ISP'lerden ölçülsün. "eyeball-network" = ev/ofis hattı (datacenter değil).
ISP_PROBES = [
    {"country": "TR", "asn": 9121,  "tags": ["eyeball-network"], "limit": 2},  # Türk Telekom
    {"country": "TR", "asn": 47331, "tags": ["eyeball-network"], "limit": 1},  # TTNet
    {"country": "TR", "asn": 34984, "tags": ["eyeball-network"], "limit": 2},  # Superonline (Turkcell)
    {"country": "TR", "asn": 12735, "tags": ["eyeball-network"], "limit": 2},  # TurkNet
]

# ISP DNS'in engelli domain için döndürdüğü engel sayfası IP'leri.
# Not: Vodafone ve Türk Telekom için 195.175.254.2 görüldü; diğer ISP'ler farklı
# olabilir. Yeni bir IP görürsen buraya ekle.
BLOCK_IPS = {"195.175.254.2"}

# Engel sayfası metin izleri (küçük harfe çevrilmiş)
BLOCK_SIGNS = [
    "erişime engellenmiştir",
    "erisime engellenmistir",
    "erişim engellenmiştir",
    "btk.gov.tr",
    "5651 sayılı",
]

# Probe bunlardan birini kullanıyorsa ISP DNS'i ölçülmüyor demektir
PUBLIC_RESOLVERS = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "149.112.112.112"}

API = "https://api.globalping.io/v1"
POLL_TIMEOUT = 90   # sn
POLL_EVERY = 2      # sn (API: saniyede en fazla 2 GET)


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------

class RateLimit(Exception):
    pass


class ApiError(Exception):
    pass


def api(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "tr-domain-check/1.0")
    token = os.environ.get("GLOBALPING_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"raw": raw}
        return e.code, payload


def create_measurement(mtype, target, locations, options):
    body = {"type": mtype, "target": target, "locations": locations,
            "measurementOptions": options}
    status, payload = api("POST", "/measurements", body)
    if status == 429:
        raise RateLimit("Globalping limiti doldu (429). Token kullan ya da biraz bekle.")
    if status not in (200, 202):
        return None, status, payload
    return payload["id"], status, payload


def wait_measurement(mid):
    t0 = time.time()
    while True:
        status, payload = api("GET", "/measurements/" + mid)
        if status == 429:
            time.sleep(3)
        elif status != 200:
            raise ApiError("Sonuç alınamadı: %s %s" % (status, payload))
        elif payload.get("status") != "in-progress":
            return payload
        if time.time() - t0 > POLL_TIMEOUT:
            raise ApiError("Ölçüm zaman aşımına uğradı: " + mid)
        time.sleep(POLL_EVERY)


def run_measurement(mtype, target, locations, options):
    """locations: liste ya da önceki ölçümün id'si. Geçersiz id'de ISP listesine döner."""
    mid, status, payload = create_measurement(mtype, target, locations, options)
    if mid is None and isinstance(locations, str) and status == 422:
        mid, status, payload = create_measurement(mtype, target, ISP_PROBES, options)
    if mid is None:
        raise ApiError("Ölçüm oluşturulamadı: %s %s" % (status, payload))
    return mid, wait_measurement(mid)


# ----------------------------------------------------------------------------
# ANALİZ
# ----------------------------------------------------------------------------

def norm(text):
    # Türkçe büyük İ -> küçük harfte oluşan birleşik nokta işaretini temizle
    return (text or "").lower().replace("̇", "")


def bad_ip(ip):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_loopback or a.is_unspecified or a.is_private or a.is_link_local


def analyze_dns(item):
    r = item.get("result", {})
    if r.get("status") != "finished":
        return {"state": "HATA", "detail": (r.get("rawOutput") or r.get("status") or "")[:100],
                "resolver": None, "ips": [], "public_dns": False}
    resolver = str(r.get("resolver", ""))
    ips = [a.get("value") for a in r.get("answers", []) if a.get("type") == "A"]
    code = r.get("statusCodeName") or ""
    public_dns = resolver in PUBLIC_RESOLVERS
    if any(ip in BLOCK_IPS or bad_ip(ip) for ip in ips):
        state, detail = "ENGEL", "engel/sahte IP: " + ", ".join(ips)
    elif code and code != "NOERROR":
        state, detail = "DNS_HATA", code
    elif not ips:
        state, detail = "DNS_HATA", "A kaydı yok"
    else:
        state, detail = "OK", ", ".join(ips)
    return {"state": state, "detail": detail, "resolver": resolver, "ips": ips,
            "public_dns": public_dns}


def analyze_http(item):
    r = item.get("result", {})
    if r.get("status") != "finished":
        raw = (r.get("rawOutput") or r.get("status") or "")
        low = raw.lower()
        if "querya" in low or "enotfound" in low or "eai_again" in low or "getaddrinfo" in low:
            state = "DNS_HATA"          # probe domaini çözemedi (DNS tarafı)
        elif ("econnreset" in low or "reset by peer" in low or "socket hang up" in low
              or "disconnected" in low):
            state = "BAGLANTI_KESILDI"  # TLS/SNI veya IP engeli deseni
        elif "etimedout" in low or "timeout" in low or "timed out" in low:
            state = "ZAMAN_ASIMI"
        elif "econnrefused" in low:
            state = "BAGLANTI_REDDEDILDI"
        elif "cert" in low or "ssl" in low or "tls" in low or "altname" in low:
            state = "SERTIFIKA_HATASI"
        else:
            state = "HATA"
        return {"state": state, "code": None, "detail": raw.strip().replace("\n", " ")[:100]}
    code = r.get("statusCode")
    body = norm(r.get("rawBody"))
    headers = r.get("headers") or {}
    location = norm(str(headers.get("location", "")))
    if any(s in body for s in BLOCK_SIGNS) or "btk.gov.tr" in location:
        return {"state": "SAYFA_ENGEL", "code": code, "detail": "engel sayfası içeriği"}
    detail = "HTTP %s" % code
    if location:
        host = urllib.parse.urlparse(location).netloc or location[:40]
        detail += " -> " + host
    if code is not None and code >= 500:
        return {"state": "SUNUCU_HATASI", "code": code, "detail": detail}
    return {"state": "OK", "code": code, "detail": detail}


def probe_verdict(dns, http):
    if dns["state"] == "ENGEL" or http["state"] == "SAYFA_ENGEL":
        return "ENGELLI"
    if http["state"] == "OK":
        return "ACIK"
    return "ULASILAMIYOR"


def short_net(name):
    name = name or ""
    if name.lower().startswith("turk telekomunikasyon"):
        return "Turk Telekom"
    return name.replace("Iletisim Hizmetleri", "").strip()[:22]


# ----------------------------------------------------------------------------
# ANA AKIŞ
# ----------------------------------------------------------------------------

def check_domain(brand, domain, locations):
    dns_id, dns_m = run_measurement("dns", domain, locations,
                                    {"query": {"type": "A"}})
    # HTTP'yi DNS ile aynı probe'larda çalıştır
    http_id, http_m = run_measurement("http", domain, dns_id,
                                      {"protocol": "HTTPS",
                                       "request": {"method": "GET", "path": "/"}})
    probes = []
    dns_results = dns_m.get("results", [])
    http_results = http_m.get("results", [])
    for i, d_item in enumerate(dns_results):
        h_item = http_results[i] if i < len(http_results) else {"result": {"status": "failed", "rawOutput": "sonuç yok"}}
        loc = d_item.get("probe", {})
        dns = analyze_dns(d_item)
        http = analyze_http(h_item)
        probes.append({
            "asn": loc.get("asn"),
            "network": loc.get("network"),
            "city": loc.get("city"),
            "dns": dns,
            "http": http,
            "verdict": probe_verdict(dns, http),
        })
    overall = overall_verdict(probes)
    return {"brand": brand, "domain": domain, "overall": overall, "probes": probes,
            "dns_id": dns_id, "http_id": http_id}


# TTNet ve Türk Telekom aynı ISP grubu sayılır
ISP_GROUP = {47331: 9121}


def overall_verdict(probes):
    if not probes:
        return "OLCULEMEDI"
    verdicts = [p["verdict"] for p in probes]
    if all(v == "ACIK" for v in verdicts):
        return "ACIK"
    if any(v == "ENGELLI" for v in verdicts):
        return "ENGELLI"
    if all(v != "ACIK" for v in verdicts):
        return "KAPALI"
    # Net engel izi yok ama birden fazla ISP grubundan ulaşılamıyor:
    # muhtemel SNI/IP engeli (DNS temiz, bağlantı kesiliyor)
    failing = {ISP_GROUP.get(p["asn"], p["asn"]) for p in probes if p["verdict"] != "ACIK"}
    if len(failing) >= 2:
        return "ENGELLI"
    return "KISMI"


def print_report(results):
    for res in results:
        print("\n%s  %s  ->  %s" % (res["brand"], res["domain"], res["overall"]))
        for p in res["probes"]:
            note = ""
            if p["dns"]["public_dns"]:
                note = "  (probe public DNS kullanıyor, DNS engeli ölçülemedi)"
            print("   %-22s %-10s DNS:%-9s HTTP:%-17s %s%s" % (
                short_net(p["network"]), (p["city"] or "")[:10],
                p["dns"]["state"], p["http"]["state"],
                p["http"]["detail"], note))
    print()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Türkiye erişim kontrolü (Globalping)")
    ap.add_argument("--out", default="domain_status.json", help="JSON çıktı dosyası")
    args = ap.parse_args()

    results = []
    locations = ISP_PROBES
    try:
        for brand, domain in load_domains():
            res = check_domain(brand, domain, locations)
            results.append(res)
            # Sonraki domainlerde aynı probe'ları kullan (karşılaştırılabilir olsun)
            locations = res["dns_id"]
    except RateLimit as e:
        print("LIMIT:", e)
        return 3
    except (ApiError, urllib.error.URLError, OSError) as e:
        print("API HATASI:", e)
        return 3

    out = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "results": results}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print_report(results)
    print("JSON:", args.out)

    if any(r["overall"] in ("ENGELLI", "KAPALI") for r in results):
        return 2
    if any(r["overall"] in ("KISMI", "OLCULEMEDI") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

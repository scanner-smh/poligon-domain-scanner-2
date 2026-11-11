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
  DOMAIN_LIST="Betsat:betsat1855.com" python domain_check.py   (listeyi dışarıdan ver)
  python domain_check.py --notify                  (durum değişince Telegram'a yazar)

Bildirim modu (--notify): TELEGRAM_TOKEN ve TELEGRAM_CHAT_IDS (virgülle ayrılmış)
ortam değişkenleri gerekir. Önceki durum --state dosyasında tutulur. Mesaj sadece
durum değişince gider (engellendi / tekrar açıldı). Bu modda çıkış kodu 2 sadece
YENİ bir engel çıkınca döner, engel sürerken 0 döner.

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
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# ----------------------------------------------------------------------------
# AYARLAR
# ----------------------------------------------------------------------------

# (marka, domain) - yeni domain gelince burayı güncelle
DOMAINS = [
    ("Superbetin", "superbetin2915.com"),
    ("Betsat",     "betsat1855.com"),
    ("Turkbet",    "786turkbet.com"),
]

# İstersen listeyi dosyaya yazmak yerine DOMAIN_LIST ortam değişkeniyle ver
# (GitHub: Settings > Secrets and variables > Actions > Variables > DOMAIN_LIST).
# Format: "Superbetin:superbetin2915.com,Betsat:betsat1855.com,Turkbet:786turkbet.com"
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
    {"country": "TR", "asn": 34984, "tags": ["eyeball-network"], "limit": 3},  # Superonline (Turkcell)
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


_TOKEN_STATE = {"disabled": False}


def warn(msg):
    # GitHub Actions'ta sarı uyarı olarak görünür
    if os.environ.get("GITHUB_ACTIONS"):
        print("::warning::" + msg)
    else:
        print("UYARI: " + msg)


def get_token():
    """Secret'a yanlışlıkla eklenen tırnak, boşluk ve 'Bearer ' önekini temizler."""
    if _TOKEN_STATE["disabled"]:
        return ""
    tok = os.environ.get("GLOBALPING_TOKEN", "").strip().strip("\"'").strip()
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    if tok and any(c.isspace() for c in tok):
        warn("GLOBALPING_TOKEN içinde boşluk/satır sonu var, token yok sayıldı (tokensiz devam).")
        _TOKEN_STATE["disabled"] = True
        return ""
    return tok


def api(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "tr-domain-check/1.0")
    token = get_token()
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
        if e.code == 401 and token:
            # Token geçersiz: tokensiz devam et (ücretsiz kota IP başına, GitHub'da ortak olabilir)
            warn("GLOBALPING_TOKEN geçersiz (401), tokensiz devam ediliyor. "
                 "dash.globalping.io/tokens'tan yeni token oluşturup secret'ı güncelle.")
            _TOKEN_STATE["disabled"] = True
            return api(method, path, body)
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
    # Probe ISP'nin değil public DNS'in (8.8.8.8 vb.) çözücüsünü kullanıyorsa DNS hatası
    # ISP'yi anlatmaz (yeni domain, resolver önbelleği...). Ölçülemedi say, KISMI yapma.
    if dns.get("public_dns") and http["state"] == "DNS_HATA":
        return "OLCULEMEDI"
    return "ULASILAMIYOR"


def short_net(name):
    name = name or ""
    if name.lower().startswith("turk telekomunikasyon"):
        return "Turk Telekom"
    return name.replace("Iletisim Hizmetleri", "").strip()[:22]


# ----------------------------------------------------------------------------
# MOBİL ÖLÇÜM (opsiyonel): mobil operatör proxy'si (SOAX) üzerinden Turkcell/Vodafone
# Ayar yoksa tamamen atlanır. Gerekenler:
#   MOBILE_PROXY_PASSWORD  proxy paketinin şifresi (GitHub secret)
#   MOBILE_ISPS            "Turkcell:16135:isp_adi,Vodafone:15897:isp_adi"
#                          (etiket:ASN:SOAX'ın ISP adı, boşluk yerine alt çizgi)
#   MOBILE_PROXY_HOST      varsayılan proxy.soax.com:1337
# DNS'i proxy tarafı çözdüğü için DNS engeli ölçülemez; SNI/IP kesilmesi ve zaman
# aşımı görülür. Proxy kaynaklı hatalar (kimlik, node yok) OLCULEMEDI sayılır.
# ----------------------------------------------------------------------------

MOBILE_HOST = os.environ.get("MOBILE_PROXY_HOST", "proxy.soax.com:1337")
MOBILE_TRIES = 3        # mobil node'lar kararsız olabilir: açılırsa ilk denemede biter
MOBILE_TIMEOUT = 15     # sn
MOBILE_BODY_MAX = 8192  # byte, trafik (GB) tüketimini küçük tutar
_EXIT_CACHE = {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def mobile_targets():
    pw = os.environ.get("MOBILE_PROXY_PASSWORD", "").strip()
    raw = os.environ.get("MOBILE_ISPS", "").strip()
    if not pw or not raw:
        return []
    out = []
    for part in raw.split(","):
        bits = [b.strip() for b in part.split(":")]
        if len(bits) != 3 or not bits[1].isdigit() or not bits[2]:
            warn("MOBILE_ISPS biçimi hatalı, atlandı: %r (etiket:ASN:isp_adi bekleniyor)" % part[:40])
            continue
        out.append((bits[0], int(bits[1]), bits[2]))
    return out


def _proxy_opener(isp):
    user = "country-tr-isp-%s-network-mob" % isp
    pw = os.environ.get("MOBILE_PROXY_PASSWORD", "").strip()
    purl = "http://%s:%s@%s" % (urllib.parse.quote(user, safe="-_"),
                                urllib.parse.quote(pw, safe=""), MOBILE_HOST)
    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": purl, "http": purl}), _NoRedirect())
    # Cloudflare 1010 = "tarayıcı imzası yasak": varsayılan Python-urllib UA'sını reddediyor.
    # Gerçek bir mobil tarayıcı gibi başlık gönder (kendi sitelerimizi ölçüyoruz).
    op.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"),
        ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("Accept-Language", "tr-TR,tr;q=0.9,en;q=0.7"),
    ]
    return op


def classify_exc(exc):
    """Python istisnasını (state, detail) olarak sınıfla. PROXY_HATA = ölçüm yapılamadı."""
    msg = ("%s %s" % (type(exc).__name__, exc)).lower()
    short = msg.strip().replace("\n", " ")[:100]
    if "407" in msg or "proxy authentication" in msg or "tunnel connection failed" in msg:
        return "PROXY_HATA", short
    if "name or service not known" in msg or "getaddrinfo" in msg or "nodename" in msg:
        return "DNS_HATA", short
    if ("reset" in msg or "eof occurred" in msg or "remote end closed" in msg
            or "connection aborted" in msg or "broken pipe" in msg):
        return "BAGLANTI_KESILDI", short
    if "timed out" in msg or "timeout" in msg:
        return "ZAMAN_ASIMI", short
    if "refused" in msg:
        return "BAGLANTI_REDDEDILDI", short
    if "certificate" in msg or "ssl" in msg:
        return "SERTIFIKA_HATASI", short
    return "HATA", short


def _mobile_request(opener, url):
    """(http_dict) döndürür. Yanıt gelirse analyze_http ile aynı kurallarla değerlendirilir."""
    try:
        with opener.open(url, timeout=MOBILE_TIMEOUT) as r:
            code, hdrs, body = r.status, r.headers, r.read(MOBILE_BODY_MAX)
    except urllib.error.HTTPError as e:      # 3xx (yönlendirme izlenmez) ve 4xx/5xx
        try:
            body = e.read(MOBILE_BODY_MAX)
        except Exception:
            body = b""
        code, hdrs = e.code, e.headers
        if code in (407, 502, 503) and "proxy" in str(hdrs).lower():
            return {"state": "PROXY_HATA", "code": code, "detail": "proxy hatası HTTP %s" % code}
    except Exception as e:                   # bağlantı/TLS/zaman aşımı
        state, detail = classify_exc(e)
        return {"state": state, "code": None, "detail": detail}
    item = {"result": {"status": "finished", "statusCode": code,
                       "rawBody": body.decode("utf-8", "ignore"),
                       "headers": {k.lower(): v for k, v in dict(hdrs).items()}}}
    h = analyze_http(item)
    if h["state"] == "OK" and code in (401, 403, 429):
        # Mobil IP'ye site/WAF "yasak" dedi: sayfa açıldı demek değil, engel de demek değil.
        low = {k.lower(): v for k, v in dict(hdrs).items()}
        who = low.get("server") or ("cloudflare" if "cf-ray" in low else "?")
        snip = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body.decode("utf-8", "ignore"))).strip()[:50]
        return {"state": "KORUMA_RED", "code": code,
                "detail": "HTTP %s (server=%s) %s" % (code, str(who)[:20], snip)}
    return h


def mobile_fetch(domain, isp):
    """Birkaç deneme: biri açılırsa ACIK. Hepsi proxy hatasıysa PROXY_HATA."""
    opener = _proxy_opener(isp)
    results = []
    for _ in range(MOBILE_TRIES):
        h = _mobile_request(opener, "https://%s/" % domain)
        if h["state"] in ("OK", "SAYFA_ENGEL"):
            return h
        results.append(h)
    real = [h for h in results if h["state"] != "PROXY_HATA"]
    if not real:
        return results[-1]
    states = [h["state"] for h in real]
    best = max(set(states), key=states.count)
    return next(h for h in real if h["state"] == best)


def mobile_exit_check(isp, asn, label=""):
    """Çıkış gerçekten istenen operatörde mi? (IP loglanmaz.) -> (ok, özet)"""
    if isp in _EXIT_CACHE:
        return _EXIT_CACHE[isp]
    res = (None, "doğrulanamadı")
    try:
        with _proxy_opener(isp).open("https://checker.soax.com/api/ipinfo",
                                     timeout=MOBILE_TIMEOUT) as r:
            data = json.loads(r.read(4096).decode("utf-8", "ignore"))
        parts, seen_asn = [], None
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]          # SOAX: {"data": {...}, "reason": "", "status": true}
        if isinstance(data, dict):
            for k, v in data.items():
                kl = str(k).lower()
                if isinstance(v, (str, int)) and kl in ("asn", "as", "isp", "carrier", "org", "as_name"):
                    parts.append("%s=%s" % (kl, str(v)[:40]))
                    if kl in ("asn", "as"):
                        m = re.search(r"\d+", str(v))
                        seen_asn = int(m.group()) if m else None
        info = ", ".join(parts)
        if not info:
            keys = sorted(str(k) for k in data)[:8] if isinstance(data, dict) else []
            info = "doğrulanamadı (alanlar: %s)" % ",".join(keys)
        name_ok = bool(label) and label.lower() in info.lower()   # ör. "Turkcell" ISP adında geçiyor
        res = (seen_asn is None or seen_asn == asn or name_ok, info)
    except Exception as e:      # proxy çalışmıyor (kredi bitti, şifre yanlış, askıda...)
        res = (None, "proxy yanıt vermedi: %s" % type(e).__name__)
    _EXIT_CACHE[isp] = res
    return res


_MOBILE_BUDGET_SEC = 150   # tüm mobil ölçümler için toplam süre sınırı (iş uzamasın)
_MOBILE_START = [None]


def safe_mobile_probes(domain):
    """Mobil ölçüm EK bilgidir. Herhangi bir hata ana kontrolü asla bozmaz."""
    try:
        return mobile_probes(domain)
    except Exception as e:      # proxy kapalı, beklenmedik hata vb.
        warn("Mobil ölçüm atlandı (%s)" % type(e).__name__)
        return []


def mobile_status(probes):
    """Mobil probe'lardan tek durum: MOBIL_SUPHE / MOBIL_ACIK / None (ölçülemedi)."""
    if any(p["verdict"] in ("ENGELLI", "ULASILAMIYOR") for p in probes):
        return "MOBIL_SUPHE"
    if any(p["verdict"] == "ACIK" for p in probes):
        return "MOBIL_ACIK"
    return None


def mobile_probes(domain):
    probes = []
    if _MOBILE_START[0] is None:
        _MOBILE_START[0] = time.time()
    for label, asn, isp in mobile_targets():
        if time.time() - _MOBILE_START[0] > _MOBILE_BUDGET_SEC:
            probes.append({"asn": asn, "network": "%s (mobil)" % label, "city": "mobil",
                           "dns": {"state": "OK", "detail": "", "resolver": None, "ips": [], "public_dns": True},
                           "http": {"state": "PROXY_HATA", "code": None, "detail": "süre bütçesi doldu"},
                           "verdict": "OLCULEMEDI", "exit": ""})
            continue
        ok, exit_info = mobile_exit_check(isp, asn, label)
        if ok is None:   # proxy hiç çalışmıyor: ölçmeye çalışma (yanlış alarm çıkmasın)
            http = {"state": "PROXY_HATA", "code": None, "detail": exit_info}
        elif not ok:     # proxy yanlış operatörden çıkıyor: ölçüm anlamsız
            http = {"state": "PROXY_HATA", "code": None, "detail": "yanlış çıkış (%s)" % exit_info}
        else:
            http = mobile_fetch(domain, isp)
        dns = {"state": "OK", "detail": "proxy çözdü", "resolver": None, "ips": [],
               "public_dns": True}
        verdict = ("OLCULEMEDI" if http["state"] in ("PROXY_HATA", "KORUMA_RED")
                   else probe_verdict(dns, http))
        probes.append({"asn": asn, "network": "%s (mobil)" % label, "city": "mobil",
                       "dns": dns, "http": http, "verdict": verdict, "exit": exit_info})
    return probes


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
    overall = overall_verdict(probes)          # sadece Globalping probe'ları (eskisi gibi)
    mobile = safe_mobile_probes(domain)        # ek bilgi, karara katılmaz
    return {"brand": brand, "domain": domain, "overall": overall, "probes": probes,
            "mobile": mobile,
            "dns_id": dns_id, "http_id": http_id}


# TTNet ve Türk Telekom aynı ISP grubu sayılır
# Turkcell mobil ile Superonline aynı operatör (Turkcell): tek grup sayılır
ISP_GROUP = {47331: 9121, 16135: 34984}


def overall_verdict(probes):
    probes = [p for p in probes if p["verdict"] != "OLCULEMEDI"]
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
    # DNS_HATA (ENODATA vb.) tek başına engel kanıtı değil: yeni domain yayılırken ISP
    # çözücülerinde geçici görülür. Gerçek DNS engeli sahte IP döner (ENGEL), burada sayılmaz.
    failing = {ISP_GROUP.get(p["asn"], p["asn"]) for p in probes
               if p["verdict"] != "ACIK" and p["http"]["state"] != "DNS_HATA"}
    if len(failing) >= 2:
        return "ENGELLI"
    # Tek ISP grubunda en az 2 probe aynı anda kopuyorsa (sunucu 5xx hariç): ŞÜPHELİ engel.
    # Tek probe hatası geçici olabilir, iki ayrı hattın birlikte kopması genelde engeldir.
    per_group = {}
    for p in probes:
        if p["verdict"] != "ACIK" and p["http"]["state"] != "SUNUCU_HATASI":
            g = ISP_GROUP.get(p["asn"], p["asn"])
            per_group[g] = per_group.get(g, 0) + 1
    if any(n >= 2 for n in per_group.values()):
        return "SUPHELI"
    return "KISMI"


def print_report(results):
    for res in results:
        print("\n%s  %s  ->  %s" % (res["brand"], res["domain"], res["overall"]))
        for p in res["probes"]:
            note = ""
            if p["dns"]["public_dns"]:
                note = "  (probe public DNS kullanıyor, DNS engeli ölçülemedi)"
            if p.get("exit"):
                note += "  [mobil çıkış: %s]" % p["exit"]
            print("   %-22s %-10s DNS:%-9s HTTP:%-17s %s%s" % (
                short_net(p["network"]), (p["city"] or "")[:10],
                p["dns"]["state"], p["http"]["state"],
                p["http"]["detail"], note))
        for p in res.get("mobile", []):
            print("   [mobil, bilgi] %-16s HTTP:%-17s %s  [çıkış: %s]" % (
                p["network"][:16], p["http"]["state"], p["http"]["detail"], p.get("exit", "")))
    print()


# ----------------------------------------------------------------------------
# TELEGRAM BİLDİRİMİ (sadece durum değişince)
# ----------------------------------------------------------------------------

BAD = ("ENGELLI", "KAPALI")
ALERT = BAD + ("SUPHELI",)
TITLES = {"ENGELLI": "ENGELLENDİ", "KAPALI": "HİÇBİR ISP'DEN AÇILMIYOR",
          "SUPHELI": "ENGEL ŞÜPHESİ (tek ISP, diğerleri açık)"}
ISP_NAMES = {9121: "Türk Telekom", 47331: "TTNet", 34984: "Superonline", 12735: "TurkNet",
             16135: "Turkcell (mobil)", 15897: "Vodafone (mobil)"}
HTTP_LABEL = {
    "BAGLANTI_KESILDI": "bağlantı kesiliyor (SNI/IP engeli)",
    "ZAMAN_ASIMI": "zaman aşımı",
    "DNS_HATA": "DNS hatası",
    "SERTIFIKA_HATASI": "sertifika hatası",
    "BAGLANTI_REDDEDILDI": "bağlantı reddedildi",
    "SUNUCU_HATASI": "sunucu hatası",
    "PROXY_HATA": "ölçülemedi (proxy)",
    "KORUMA_RED": "ölçülemedi (site mobil IP'yi reddetti)",
    "HATA": "hata",
}


def probe_label(p):
    if p["dns"]["state"] == "ENGEL":
        return "DNS engeli"
    if p["http"]["state"] == "SAYFA_ENGEL":
        return "engel sayfası"
    if p["verdict"] == "ACIK":
        return "açık"
    return HTTP_LABEL.get(p["http"]["state"], p["http"]["state"].lower())


def isp_summary(probes):
    groups = {}
    for p in probes:
        name = ISP_NAMES.get(p["asn"], short_net(p["network"]))
        labels = groups.setdefault(name, [])
        lab = probe_label(p)
        if lab not in labels:
            labels.append(lab)
    return "\n".join("  %s: %s" % (n, " / ".join(l)) for n, l in groups.items())


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def mobile_alerts(results, prev):
    """Mobilde geçiş olunca ayrı mesaj. Durum anahtarı 'domain|mobil', genel durumu etkilemez."""
    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m %H:%M")
    alerts = []
    for r in results:
        cur = mobile_status(r.get("mobile", []))
        key = r["domain"] + "|mobil"
        before = prev.get(key)
        if cur is None or cur == before:
            continue
        lines = "\n".join("  %s: %s" % (p["network"], probe_label(p)) for p in r["mobile"])
        head = "%s  %s" % (r["brand"], r["domain"])
        if cur == "MOBIL_SUPHE":
            msg = ("📱 %s\nSOAX mobil ölçümüne göre ulaşılamıyor görünüyor (BİLGİ, henüz doğrulanmadı)\n"
                   "%s%s\nKontrol: %s (TR)") % (
                       head, ("Genel durum (Globalping): %s\n" % r["overall"]) if r.get("overall") else "",
                       lines, now)
            alerts.append((key, msg, False))
        elif before == "MOBIL_SUPHE":
            msg = "📱 %s\nSOAX mobil ölçümüne göre tekrar açık görünüyor (bilgi)\n%s\nKontrol: %s (TR)" % (head, lines, now)
            alerts.append((key, msg, False))
    return alerts


def build_alerts(results, prev):
    """Önceki duruma göre değişen domainler için (domain, mesaj, yeni_engel_mi) listesi."""
    now = datetime.now(timezone(timedelta(hours=3))).strftime("%d.%m %H:%M")
    alerts = []
    for r in results:
        before = prev.get(r["domain"])
        cur = r["overall"]
        if cur == before:
            continue
        head = "%s  %s" % (r["brand"], r["domain"])
        if cur in ALERT:
            icon = "⚠️" if cur == "SUPHELI" else "🚫"
            msg = "%s %s\n%s\n%s\nKontrol: %s (TR)" % (icon, head, TITLES[cur], isp_summary(r["probes"]), now)
            # Şüphede Telegram yeter, Actions çalışması kırmızıya dönmesin
            alerts.append((r["domain"], msg, cur in BAD))
        elif before in ALERT:
            msg = "✅ %s\nTekrar erişilebilir (%s)\n%s\nKontrol: %s (TR)" % (
                head, cur, isp_summary(r["probes"]), now)
            alerts.append((r["domain"], msg, False))
    return alerts


def send_telegram(text):
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]
    if not token or not chats:
        print("Telegram ayarı yok (TELEGRAM_TOKEN / TELEGRAM_CHAT_IDS), bildirim atlandı")
        return False
    ok = True
    for chat in chats:
        body = json.dumps({"chat_id": chat, "text": text,
                           "disable_web_page_preview": True}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % token, data=body, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
        except urllib.error.HTTPError as e:
            # Hata metni URL (yani token) içerebilir, sadece kodu yaz
            print("Telegram gönderilemedi (chat %s): HTTP %s" % (chat, e.code))
            ok = False
        except Exception as e:
            print("Telegram gönderilemedi (chat %s): %s" % (chat, type(e).__name__))
            ok = False
    return ok


MOBILE_CONFIRM = 2   # sık ölçümde tek seferlik mobil aksaklık alarm üretmesin: üst üste 2 kez şüphe


def run_mobile_only(args):
    """Globalping'e dokunmadan sadece mobil (SOAX) ölçüm. Kendi durum dosyasını kullanır,
    sadece 'bilgi' mesajı gönderir; ana kontrolün durumunu ve limitini etkilemez."""
    if not mobile_targets():
        print("Mobil ayar yok (MOBILE_PROXY_PASSWORD / MOBILE_ISPS), atlandı.")
        return 0
    results = []
    for brand, domain in load_domains():
        results.append({"brand": brand, "domain": domain, "mobile": safe_mobile_probes(domain)})
    for r in results:
        print("%s  %s" % (r["brand"], r["domain"]))
        for p in r["mobile"]:
            print("   [mobil, bilgi] %-16s HTTP:%-17s %s  [çıkış: %s]" % (
                p["network"][:16], p["http"]["state"], p["http"]["detail"], p.get("exit", "")))
        print()
    out = {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "mobile": {r["domain"]: r["mobile"] for r in results}}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    if not args.notify:
        return 0
    prev = load_state(args.state)
    state = dict(prev)
    eff = []
    for r in results:
        key, nkey = r["domain"] + "|mobil", r["domain"] + "|mobil_n"
        ms = mobile_status(r["mobile"])
        if ms is None:                       # ölçülemedi: eski durum ve sayaç aynen kalsın
            eff.append(dict(r, mobile=[]))
            continue
        if ms == "MOBIL_SUPHE":
            n = int(prev.get(nkey, 0) or 0) + 1
            state[nkey] = n
            if n < MOBILE_CONFIRM:           # henüz teyit edilmedi: durum değişmesin
                eff.append(dict(r, mobile=[]))
                continue
        else:
            state.pop(nkey, None)
        state[key] = ms
        eff.append(r)
    for key, msg, _bad in mobile_alerts(eff, prev):
        if not send_telegram(msg):           # gönderilemediyse durum eski kalsın, tekrar denensin
            if key in prev:
                state[key] = prev[key]
            else:
                state.pop(key, None)
    with open(args.state, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Türkiye erişim kontrolü (Globalping)")
    ap.add_argument("--out", default="domain_status.json", help="JSON çıktı dosyası")
    ap.add_argument("--notify", action="store_true",
                    help="Durum değişince Telegram'a bildir (TELEGRAM_TOKEN, TELEGRAM_CHAT_IDS)")
    ap.add_argument("--state", default="domain_state.json",
                    help="Önceki durumun tutulduğu dosya (--notify ile kullanılır)")
    ap.add_argument("--sadece-mobil", action="store_true",
                    help="Sadece mobil (SOAX) ölçüm; Globalping kullanmaz, kendi --state dosyasıyla çalışır")
    args = ap.parse_args()
    if args.sadece_mobil:
        return run_mobile_only(args)

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

    if args.notify:
        prev = load_state(args.state)
        state = {r["domain"]: r["overall"] for r in results}
        for r in results:      # mobil durum ayrı anahtarda; ölçülemediyse eskisini koru
            key = r["domain"] + "|mobil"
            ms = mobile_status(r.get("mobile", []))
            if ms is not None:
                state[key] = ms
            elif key in prev:
                state[key] = prev[key]
        new_bad = False
        for domain, msg, is_bad in build_alerts(results, prev) + mobile_alerts(results, prev):
            new_bad = new_bad or is_bad
            if not send_telegram(msg):
                # Gönderilemediyse durumu güncelleme, bir sonraki çalışmada tekrar denensin
                if domain in prev:
                    state[domain] = prev[domain]
                else:
                    state.pop(domain, None)
        with open(args.state, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        # Bildirim modunda iş sadece yeni bir engel çıkınca kırmızı olur
        # (engel sürerken her 30 dakikada bir e-posta gelmesin)
        return 2 if new_bad else 0

    if any(r["overall"] in ("ENGELLI", "KAPALI") for r in results):
        return 2
    if any(r["overall"] in ("KISMI", "SUPHELI", "OLCULEMEDI") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

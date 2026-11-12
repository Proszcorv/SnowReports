"""Reggeli fagy/hó összefoglaló: Open-Meteo (4 modell) -> ntfy.sh értesítés.

Helyek megadása:
  PLACES  = soronként egy hely, "Név;szélesség;hosszúság" (pl. "Telki;47.55;18.83")
  vagy (egy helyhez) LAT, LON, PLACE
PAGE_URL = a weboldalad címe (opcionális), az értesítésre kattintva ez nyílik meg.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless"]
TOPIC = os.environ["NTFY_TOPIC"]
PAGE_URL = (os.environ.get("PAGE_URL") or "").strip()


def get_json(url, data=None, attempts=4):
    """Átmeneti hálózati hibánál (időtúllépés, TLS) többször újrapróbálkozik."""
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:
            last = e
            print(f"Próbálkozás {i + 1}/{attempts} sikertelen: {e}", file=sys.stderr)
            if i < attempts - 1:
                time.sleep(5 * (i + 1))
    raise last


def hu(n, d=0):
    return str(round(n, d)).replace(".", ",")


def parse_places():
    raw = (os.environ.get("PLACES") or "").replace("|", "\n")
    places = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(";")]
        if len(parts) == 3 and all(parts):
            places.append((parts[0], parts[1].replace(",", "."), parts[2].replace(",", ".")))
    if not places and os.environ.get("LAT") and os.environ.get("LON"):
        places.append((os.environ.get("PLACE") or "Helyem", os.environ["LAT"], os.environ["LON"]))
    if not places:
        raise SystemExit("Nincs megadott hely (PLACES vagy LAT/LON).")
    return places


def send_for(name, lat, lon):
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "daily": "temperature_2m_min,precipitation_sum,snowfall_sum",
        "models": ",".join(MODELS), "forecast_days": 14, "timezone": "auto",
    })
    d = get_json("https://api.open-meteo.com/v1/forecast?" + q)["daily"]

    def day(i):
        def vals(k):
            return [d[f"{k}_{m}"][i] for m in MODELS
                    if f"{k}_{m}" in d and d[f"{k}_{m}"][i] is not None]
        mins, pr, sn = vals("temperature_2m_min"), vals("precipitation_sum"), vals("snowfall_sum")
        return {
            "date": d["time"][i],
            "min": sum(mins) / len(mins) if mins else None,
            "frost": sum(v < 0 for v in mins), "n": len(mins),
            "precip": sum(pr) / len(pr) if pr else 0,
            "snow": sum(v >= 0.2 for v in sn), "snow_n": len(sn),
        }

    days = [day(i) for i in range(len(d["time"]))]
    t = days[0]
    snowy = lambda x: x["snow_n"] and x["snow"] >= -(-x["snow_n"] // 2)

    lines = []
    if t["min"] is None:
        lines.append("Ma nincs elérhető minimum-adat.")
    else:
        lines.append(f"Minimum: {hu(t['min'])} °C ({t['frost']}/{t['n']} modell mutat fagyot)")
    lines.append(f"Csapadék: {hu(t['precip'], 1)} mm")
    if snowy(t):
        lines.append(f"Hó: valószínű ({t['snow']}/{t['snow_n']} modell)")
    elif t["snow"]:
        lines.append(f"Hó: lehetséges ({t['snow']}/{t['snow_n']} modell)")
    else:
        lines.append("Hó: nem várható")
    nxt = next((x for x in days[1:] if snowy(x)), None)
    if nxt:
        lines.append(f"Következő havas nap: {nxt['date']}")

    tags = []
    if t["min"] is not None and t["min"] < 0:
        tags.append("cold_face")
    if snowy(t):
        tags.append("snowflake")
    payload = {
        "topic": TOPIC,
        "title": f"{name}: reggeli időjárás",
        "message": "\n".join(lines),
        "tags": tags or ["sunny"],
        "priority": 4 if snowy(t) else 3,
    }
    if PAGE_URL:
        sep = "&" if "?" in PAGE_URL else "?"
        payload["click"] = PAGE_URL + sep + urllib.parse.urlencode({"lat": lat, "lon": lon, "name": name})
    get_json("https://ntfy.sh/", json.dumps(payload).encode())
    print(f"Elküldve ({name}):\n" + payload["message"])


def main():
    failed = False
    for name, lat, lon in parse_places():
        try:
            send_for(name, lat, lon)
        except Exception as e:
            failed = True
            print(f"Hiba ({name}):", e, file=sys.stderr)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()

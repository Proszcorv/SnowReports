"""Reggeli fagy/hó összefoglaló: Open-Meteo (4 modell) -> ntfy.sh értesítés."""
import json
import os
import sys
import urllib.parse
import urllib.request

MODELS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless"]
LAT = os.environ["LAT"]
LON = os.environ["LON"]
PLACE = os.environ.get("PLACE", "Helyem")
TOPIC = os.environ["NTFY_TOPIC"]


def get_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def hu(n, d=0):
    return str(round(n, d)).replace(".", ",")


def main():
    q = urllib.parse.urlencode({
        "latitude": LAT, "longitude": LON,
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
        "title": f"{PLACE}: reggeli időjárás",
        "message": "\n".join(lines),
        "tags": tags or ["sunny"],
        "priority": 4 if snowy(t) else 3,
    }
    get_json("https://ntfy.sh/", json.dumps(payload).encode())
    print("Elküldve:\n" + payload["message"])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Hiba:", e, file=sys.stderr)
        sys.exit(1)

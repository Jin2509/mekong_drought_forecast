"""Tai du lieu khi tuong theo ngay tu Open-Meteo Historical Weather API (ERA5).
Chay: python src/fetch_api.py
"""
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
import yaml
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()
log = logging.getLogger("fetch_api")


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_endpoint(cfg):
    key = os.getenv("OPEN_METEO_API_KEY", "").strip()
    if key:
        return cfg["api"]["base_paid"], key
    return cfg["api"]["base_free"], None


def make_session(contact):
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=3, respect_retry_after_header=True,
                  status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = f"cs114-student-project ({contact})"
    return s


def year_chunks(y0, y1, step):
    y = y0
    while y <= y1:
        yield y, min(y + step - 1, y1)
        y += step


def request_block(session, base, key, lat, lon, start, end, tz, daily=None, hourly=None):
    params = {"latitude": lat, "longitude": lon, "start_date": start,
              "end_date": end, "timezone": tz}
    if daily:
        params["daily"] = ",".join(daily)
    if hourly:
        params["hourly"] = ",".join(hourly)
    if key:
        params["apikey"] = key
    r = session.get(base, params=params, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def effective_end(cfg):
    cap = date.today() - timedelta(days=cfg["period"]["end_lag_days"])
    return min(date(cfg["period"]["end"], 12, 31), cap)


def fetch_station(cfg, st, session):
    raw = Path(cfg["paths"]["raw"])
    raw.mkdir(parents=True, exist_ok=True)
    p, api, tz = cfg["period"], cfg["api"], cfg["project"]["timezone"]
    end_all = effective_end(cfg)
    base, key = get_endpoint(cfg)
    jobs = [("daily", p["calib_start"], api["daily_chunk_years"], api["daily_vars"], None),
            ("soil", p["ml_start"], api["hourly_chunk_years"], None, api["hourly_vars"])]
    for kind, y_start, step, daily, hourly in jobs:
        for y0, y1 in year_chunks(y_start, end_all.year, step):
            out = raw / f"{st['id']}_{kind}_{y0}_{y1}.csv"
            if out.exists():
                log.info("bo qua (da co) %s", out.name)
                continue
            s_date = f"{y0}-01-01"
            e_date = min(date(y1, 12, 31), end_all).isoformat()
            js = request_block(session, base, key, st["lat"], st["lon"],
                               s_date, e_date, tz, daily, hourly)
            log.info("toa do tra ve: lat=%s lon=%s", js.get("latitude"), js.get("longitude"))
            block = js["daily"] if daily else js["hourly"]
            df = pd.DataFrame(block).rename(columns={"time": "date"})
            df.to_csv(out, index=False)
            log.info("da luu %s (%d dong)", out.name, len(df))
            time.sleep(api["sleep_seconds"])


def merge_station(cfg, st):
    raw, interim = Path(cfg["paths"]["raw"]), Path(cfg["paths"]["interim"])
    interim.mkdir(parents=True, exist_ok=True)
    daily = pd.concat([pd.read_csv(f) for f in sorted(raw.glob(f"{st['id']}_daily_*.csv"))])
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.drop_duplicates("date").set_index("date").sort_index()
    soil_files = sorted(raw.glob(f"{st['id']}_soil_*.csv"))
    if soil_files:
        soil = pd.concat([pd.read_csv(f) for f in soil_files])
        soil["date"] = pd.to_datetime(soil["date"])
        soil = soil.drop_duplicates("date").set_index("date").sort_index()
        soil_daily = soil.resample("D").mean()
        soil_daily.columns = [c + "_mean" for c in soil_daily.columns]
        daily = daily.join(soil_daily, how="left")
    out = interim / f"{st['id']}_daily.csv"
    daily.to_csv(out)
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    base, key = get_endpoint(cfg)
    log.info("endpoint: %s (%s)", base, "co API key" if key else "mien phi")
    session = make_session(cfg["project"]["contact"])
    for st in cfg["stations"]:
        log.info("=== %s ===", st["name"])
        fetch_station(cfg, st, session)
        log.info("gop du lieu -> %s", merge_station(cfg, st))


if __name__ == "__main__":
    main()
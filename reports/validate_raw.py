"""Kiểm tra chất lượng data/interim/<ID>_daily.csv cho tất cả trạm trong config.yaml.

Chạy (từ bất kỳ thư mục nào):  python reports/validate_raw.py [--config config.yaml]
Kết quả: in tóm tắt + <reports>/validation_report.csv
Thoát với mã 1 nếu có lỗi (ERROR), để chặn các bước sau.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent  # thư mục gốc dự án

SOIL = "soil_moisture_0_to_7cm_mean"
# (min, max) hợp lý cho ĐBSCL; ngoài khoảng này coi là ERROR
LIMITS = {
    "precipitation_sum": (0.0, 400.0),
    "temperature_2m_max": (15.0, 42.0),
    "et0_fao_evapotranspiration": (0.0, 10.0),
    SOIL: (0.02, 0.60),
}
DAILY_REQUIRED = ["precipitation_sum", "temperature_2m_max", "et0_fao_evapotranspiration"]


def rpath(p) -> Path:
    """Đường dẫn trong config tính theo thư mục gốc dự án."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def longest_run(s: pd.Series) -> int:
    grp = (s != s.shift()).cumsum()
    return int(s.groupby(grp).transform("size").max())


def check_station(sid, cfg, today):
    out = []

    def add(level, check, detail):
        out.append(dict(station=sid, level=level, check=check, detail=detail))

    p = cfg["period"]
    f = rpath(cfg["paths"]["interim"]) / f"{sid}_daily.csv"
    if not f.exists():
        add("ERROR", "file", f"không thấy {f}")
        return out, None

    df = pd.read_csv(f)
    miss = [c for c in ["date", *LIMITS] if c not in df.columns]
    if miss:
        add("ERROR", "columns", f"thiếu cột: {miss}")
        return out, None

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if df["date"].isna().any():
        add("ERROR", "date_parse", f"{df['date'].isna().sum()} ngày không đọc được")
        df = df.dropna(subset=["date"])
    for c in LIMITS:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # --- ngày trùng / thiếu ---
    dup = int(df["date"].duplicated().sum())
    if dup:
        add("ERROR", "duplicates", f"{dup} ngày bị trùng")
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)

    start = pd.Timestamp(f"{p['calib_start']}-01-01")
    end = min(pd.Timestamp(f"{p['end']}-12-31"), today - pd.Timedelta(days=p["end_lag_days"]))
    expected = pd.date_range(start, end, freq="D")
    got = pd.DatetimeIndex(df["date"])  # Index mới có .difference(), Series thì không

    gaps = expected.difference(got)
    if len(gaps):
        add("ERROR", "missing_dates", f"thiếu {len(gaps)} ngày, ví dụ {[str(d.date()) for d in gaps[:5]]}")
    extra = got.difference(expected)
    if len(extra):
        add("WARN", "extra_dates", f"{len(extra)} ngày nằm ngoài khoảng {start.date()}..{end.date()}")

    # --- NaN ---
    for c in DAILY_REQUIRED:
        n = int(df[c].isna().sum())
        if n:
            add("ERROR", "nan", f"{c}: {n} giá trị NaN")
    ml_start = pd.Timestamp(f"{p['ml_start']}-01-01")
    n_after = int(df.loc[df["date"] >= ml_start, SOIL].isna().sum())
    if n_after:
        add("ERROR", "nan_soil", f"{SOIL}: {n_after} NaN sau {p['ml_start']} (đáng lẽ phải đủ)")
    n_before = int(df.loc[df["date"] < ml_start, SOIL].notna().sum())
    if n_before:
        add("WARN", "soil_before_ml_start", f"{n_before} ngày có độ ẩm đất trước {p['ml_start']}")

    # --- ngoài ngưỡng ---
    for c, (lo, hi) in LIMITS.items():
        bad = df[(df[c] < lo) | (df[c] > hi)]
        if len(bad):
            add("ERROR", "range", f"{c}: {len(bad)} giá trị ngoài [{lo}, {hi}], ví dụ {bad['date'].iloc[0].date()}={bad[c].iloc[0]}")
    n_heavy = int((df["precipitation_sum"] > 150).sum())
    if n_heavy:
        add("WARN", "heavy_rain", f"{n_heavy} ngày mưa > 150 mm (kiểm tra có thật không)")

    # --- giá trị đứng yên bất thường ---
    for c in ["temperature_2m_max", "et0_fao_evapotranspiration"]:
        r = longest_run(df[c].round(2))
        if r >= 5:
            add("WARN", "stuck", f"{c}: chuỗi {r} ngày liên tiếp cùng giá trị")

    # --- tổng mưa năm (chỉ năm đủ ngày) ---
    cnt = df.groupby(df["date"].dt.year)["precipitation_sum"].agg(["sum", "count"])
    for y, row in cnt.iterrows():
        full = 366 if pd.Timestamp(int(y), 1, 1).is_leap_year else 365
        if row["count"] == full and not (500 <= row["sum"] <= 4000):
            add("WARN", "annual_precip", f"năm {y}: {row['sum']:.0f} mm")

    # --- thông tin ---
    sat = (df[SOIL] >= df[SOIL].max() - 1e-9).mean() if df[SOIL].notna().any() else 0
    if sat > 0.2:
        add("INFO", "soil_cap", f"{sat:.0%} số ngày độ ẩm đất chạm trần {df[SOIL].max():.2f} (bão hòa mô hình)")
    if len(df):
        add("INFO", "rows", f"{len(df)} dòng, {df['date'].min().date()} → {df['date'].max().date()}")
    return out, len(df)


def main():
    ap = argparse.ArgumentParser(description="Kiểm tra dữ liệu ngày trong data/interim trước khi dùng.")
    ap.add_argument("--config", default="config.yaml", help="đường dẫn config (mặc định: config.yaml ở gốc dự án)")
    args = ap.parse_args()

    with open(rpath(args.config), encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    today = pd.Timestamp.today().normalize()
    rows, sizes = [], {}
    for s in cfg["stations"]:
        r, n = check_station(s["id"], cfg, today)
        rows += r
        if n is not None:
            sizes[s["id"]] = n

    if len(set(sizes.values())) > 1:
        rows.append(dict(station="ALL", level="ERROR", check="row_count_mismatch", detail=str(sizes)))

    rep = pd.DataFrame(rows, columns=["station", "level", "check", "detail"])
    rep_dir = rpath(cfg["paths"]["reports"])
    rep_dir.mkdir(parents=True, exist_ok=True)
    rep.to_csv(rep_dir / "validation_report.csv", index=False, encoding="utf-8-sig")

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    rep_sorted = rep.assign(_o=rep["level"].map(order)).sort_values(["station", "_o"], kind="stable")
    for _, r in rep_sorted.iterrows():
        print(f"[{r.level:5}] {r.station:3} {r.check:20} {r.detail}")
    n_err = int((rep["level"] == "ERROR").sum())
    n_warn = int((rep["level"] == "WARN").sum())
    print(f"\nTổng: {n_err} ERROR, {n_warn} WARN. Báo cáo: {rep_dir / 'validation_report.csv'}")
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()

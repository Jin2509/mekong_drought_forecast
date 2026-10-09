# Hướng dẫn xây dựng dataset dự báo hạn hán ĐBSCL

Tài liệu này hướng dẫn từng bước: tải dữ liệu đủ 5 trạm → kiểm tra chất lượng → dựng dataset (SPEI, đặc trưng, nhãn) để dùng cho mô hình dự báo.

---

## 0. Tổng quan quy trình

```
config.yaml
   │
   ▼
[1] fetch_api.py      → data/raw/*.csv, data/interim/<ID>_daily.csv
   │
   ▼
[2] validate_raw.py   → reports/validation_report.csv   (phải hết ERROR)
   │
   ▼
[3] build_dataset.py  → data/processed/dataset_monthly_full.csv
                        data/processed/dataset_monthly_ml.csv  ← dùng để huấn luyện
```

| Bước | Script | Việc làm | Đầu ra |
|---|---|---|---|
| 1 | `src/fetch_api.py` | Tải dữ liệu ngày và giờ từ Open-Meteo cho 5 trạm | `data/interim/<ID>_daily.csv` |
| 2 | `src/validate_raw.py` | Kiểm tra thiếu ngày, NaN, ngoài ngưỡng, giá trị đứng yên | `reports/validation_report.csv` |
| 3 | `src/build_dataset.py` | Gộp tháng, tính SPEI, tạo đặc trưng và nhãn | `data/processed/*.csv` |

---

## 1. Chuẩn bị

### 1.1. Cấu trúc thư mục

```
mekong_drought_forecast/
├── config.yaml
├── src/
│   ├── fetch_api.py
│   ├── validate_raw.py
│   └── build_dataset.py
├── data/
│   ├── raw/
│   ├── interim/
│   ├── external/
│   └── processed/
├── reports/
└── logs/
```

Tạo các thư mục còn thiếu:

```bash
mkdir -p data/raw data/interim data/external data/processed reports logs
```

> Lưu ý: tên thư mục hiện tại của bạn là `mekong_drough t_forecast` (có khoảng trắng). Nên đổi thành `mekong_drought_forecast` để tránh lỗi đường dẫn. Sau khi đổi tên cần tạo lại môi trường ảo `.venv` (hoặc sửa lại đường dẫn `source`).

### 1.2. Kích hoạt môi trường ảo và cài thư viện

```bash
cd /đường/dẫn/tới/mekong_drought_forecast
source .venv/bin/activate
pip install pandas numpy scipy pyyaml requests
```

Kiểm tra:

```bash
python -c "import pandas, numpy, scipy, yaml; print('OK')"
```

### 1.3. Đặt file vào đúng chỗ

- Chép `config.yaml` mới đè lên file cũ (ở thư mục gốc dự án).
- Chép `validate_raw.py` và `build_dataset.py` vào thư mục `src/`.

---

## 2. Cấu hình `config.yaml`

Các điểm quan trọng:

| Tham số | Giá trị | Ý nghĩa |
|---|---|---|
| `period.calib_start` | 1991 | Năm bắt đầu của chuỗi dữ liệu ngày |
| `period.calib_end` | 2020 | Năm cuối của giai đoạn chuẩn để fit SPEI (30 năm, chuẩn WMO) |
| `period.ml_start` | 2010 | Năm bắt đầu có độ ẩm đất (dùng cho ML) |
| `period.end` | 2025 | Năm cuối của dữ liệu |
| `period.end_lag_days` | 7 | Dữ liệu archive trễ khoảng 7 ngày so với hiện tại |
| `stations` | 5 trạm | Bến Tre, Cà Mau, Rạch Giá, Cao Lãnh, Long Xuyên |

Quy tắc YAML cần nhớ:

- Dòng con thụt lề đúng 2 dấu cách dưới dòng cha.
- Không viết chữ thừa sau giá trị. Bình luận phải bắt đầu bằng `#`, ví dụ `raw: data/raw  # nơi lưu dữ liệu thô`.

Kiểm tra config trước khi chạy:

```bash
python -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['period']); print(c['paths']); print(len(c['stations']), 'tram')"
```

Kết quả đúng: `calib_start: 1991`, `end: 2025`, và `5 tram`.

---

## 3. Bước 1: Crawl đủ dữ liệu

```bash
python src/fetch_api.py 2>&1 | tee logs/fetch_full.log
```

Lệnh `tee` vừa in ra màn hình vừa lưu log để bạn xem lại.

Thời gian chạy thường vài phút đến vài chục phút vì có `sleep_seconds` giữa các lần gọi API.

Kết quả mong đợi cho mỗi trạm:

- `data/interim/<ID>_daily.csv` gồm khoảng 12.784 dòng dữ liệu + 1 dòng tiêu đề (1991-01-01 → 2025-12-31 là 35 năm, có 9 năm nhuận).
- Các file thô theo giờ của độ ẩm đất nằm trong `data/raw/`, giữ lại để tái lập kết quả.

Kiểm tra nhanh:

```bash
ls data/interim
wc -l data/interim/*_daily.csv
head -3 data/interim/BT_daily.csv
```

Cột của file ngày:

```
date, precipitation_sum, temperature_2m_max, et0_fao_evapotranspiration, soil_moisture_0_to_7cm_mean
```

### Xử lý sự cố khi crawl

| Hiện tượng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `400 Bad Request` | Sai ngày (ví dụ năm gõ nhầm 1023) hoặc sai tên biến | Kiểm tra `period` và `daily_vars` trong config |
| `429 Too Many Requests` | Vượt giới hạn lượt gọi của API miễn phí | Đợi khoảng 1 giờ, tăng `sleep_seconds` lên 3, chạy lại |
| Lỗi mạng giữa chừng | Mất kết nối | Chạy lại. Nếu script không bỏ qua trạm đã tải, xóa file của trạm lỗi rồi chạy lại |
| Lỗi YAML | Sai thụt lề hoặc chữ thừa | Chạy lệnh kiểm tra config ở mục 2 |

Ghi chú: API miễn phí của Open-Meteo chỉ dành cho mục đích phi thương mại, phù hợp đồ án học thuật.

---

## 4. Bước 2: Kiểm tra tính hợp lệ của dữ liệu

```bash
python src/validate_raw.py
```

### 4.1. Script kiểm tra những gì

| Kiểm tra | Mức độ | Ý nghĩa |
|---|---|---|
| Thiếu file hoặc thiếu cột | ERROR | Bước crawl chưa hoàn tất |
| Ngày bị trùng | ERROR | Cần loại bỏ dòng trùng |
| Thiếu ngày so với 1991-01-01 → 2025-12-31 | ERROR | Chuỗi thời gian không liên tục, sẽ làm sai tổng trượt và SPEI |
| NaN ở mưa, Tmax, ET0 | ERROR | Không được thiếu |
| NaN ở độ ẩm đất sau 2010 | ERROR | Phải đủ từ 2010 |
| Giá trị ngoài ngưỡng | ERROR | Mưa 0–400 mm, Tmax 15–42 °C, ET0 0–10 mm/ngày, độ ẩm đất 0,02–0,60 |
| Số dòng giữa các trạm khác nhau | ERROR | Có trạm tải thiếu |
| Mưa > 150 mm/ngày | WARN | Có thể là mưa cực đoan thật, cần xem xét |
| Chuỗi từ 5 ngày liền cùng một giá trị Tmax hoặc ET0 | WARN | Có thể do lỗi dữ liệu |
| Tổng mưa năm ngoài 500–4000 mm | WARN | Cần xem lại năm đó |
| Độ ẩm đất chạm trần (≥ 20% số ngày) | INFO | Bão hòa của mô hình, không phải số đo thực |

Độ ẩm đất NaN trước 2010 là chủ định, không bị tính là lỗi.

### 4.2. Đọc kết quả

Ví dụ dòng in ra:

```
[ERROR] CM  missing_dates  thiếu 31 ngày, ví dụ ['2005-03-01', ...]
[WARN ] KG  heavy_rain     3 ngày mưa > 150 mm (kiểm tra có thật không)
[INFO ] BT  rows           12784 dòng, 1991-01-01 → 2025-12-31
```

- **ERROR**: bắt buộc sửa rồi chạy lại. Cách thường dùng là tải lại trạm đó.
- **WARN**: xem xét và ghi chú vào báo cáo, không nhất thiết phải sửa.
- **INFO**: thông tin để mô tả dữ liệu.

Script thoát với mã 1 nếu còn ERROR. Chỉ sang bước 3 khi hết ERROR.

Báo cáo chi tiết nằm ở `reports/validation_report.csv`, có thể đưa vào phụ lục của đồ án.

---

## 5. Bước 3: Dựng dataset

```bash
python src/build_dataset.py
```

### 5.1. Các bước xử lý bên trong

**a) Gộp từ ngày sang tháng**

| Cột | Cách tính |
|---|---|
| `precip_sum` | Tổng mưa tháng |
| `et0_sum` | Tổng ET0 tháng |
| `tmax_mean`, `tmax_max` | Trung bình và cực đại của Tmax |
| `rain_days` | Số ngày mưa ≥ 1 mm |
| `soil_mean` | Trung bình độ ẩm đất |

Tháng nào chưa đủ ngày (ví dụ tháng cuối) bị loại để tránh thiên lệch.

**b) Cân bằng nước**

```
D = P − ET0     (mm/tháng)
```

D âm kéo dài nghĩa là thiếu nước, tức hạn.

**c) SPEI-1, SPEI-3, SPEI-6**

1. Tổng trượt D trên 1, 3, 6 tháng.
2. Với mỗi tháng trong năm (1–12), fit phân phối log-logistic 3 tham số (phương pháp PWM của Vicente-Serrano) trên giai đoạn chuẩn 1991–2020.
3. Chuyển xác suất tích lũy sang phân phối chuẩn chuẩn hóa. Kết quả có trung bình ≈ 0 và độ lệch chuẩn ≈ 1.

Phân loại hạn tham khảo:

| SPEI | Mức |
|---|---|
| ≤ −2,0 | Hạn cực đoan |
| −2,0 đến −1,5 | Hạn nặng |
| −1,5 đến −1,0 | Hạn vừa |
| −1,0 đến 1,0 | Bình thường |
| ≥ 1,0 | Ẩm ướt |

**d) Đặc trưng**

- Mùa vụ: `month_sin`, `month_cos`.
- ENSO: `oni_lag2`, `oni_lag3`. ONI là trung bình trượt 3 tháng nên phải trễ từ 2 tháng để không rò rỉ dữ liệu. Script tự tải file ONI từ NOAA vào `data/external/oni.ascii.txt`.
- Độ trễ 1, 2, 3 tháng (`_lag1`, `_lag2`, `_lag3`) của: `precip_sum`, `et0_sum`, `D`, `tmax_mean`, `soil_mean`, `spei1`, `spei3`, `spei6`.

**e) Nhãn dự báo**

| Cột | Ý nghĩa |
|---|---|
| `target_spei3_h1/h2/h3` | SPEI-3 của 1, 2, 3 tháng sau (bài toán hồi quy) |
| `target_drought_h1/h2/h3` | 1 nếu SPEI-3 tháng đó ≤ −1, ngược lại 0 (bài toán phân loại) |

**f) Chia tập theo thời gian**

| Tập | Giai đoạn |
|---|---|
| train | ≤ 2018 |
| val | 2019–2021 |
| test | ≥ 2022 |

Không xáo trộn ngẫu nhiên vì dữ liệu chuỗi thời gian.

### 5.2. Hai file đầu ra

| File | Nội dung | Dùng khi |
|---|---|---|
| `dataset_monthly_full.csv` | Từ 1991, độ ẩm đất NaN trước 2010 | Phân tích EDA, vẽ lịch sử SPEI 1991–2025 |
| `dataset_monthly_ml.csv` | Từ 2010, đã bỏ dòng thiếu đặc trưng do lag | **Huấn luyện mô hình** |

### 5.3. Kiểm tra SPEI có đúng không

Cuối lần chạy, script in bảng sanity check trên giai đoạn chuẩn. SPEI đúng khi:

- `mean` xấp xỉ 0.
- `std` xấp xỉ 1.
- `frac_dry` (tỷ lệ tháng có SPEI-3 ≤ −1) khoảng 0,16.

Nếu lệch nhiều (ví dụ `frac_dry` quá thấp hoặc quá cao), kiểm tra lại dữ liệu tháng hoặc báo lỗi để xem lại bước fit.

---

## 6. Danh sách kiểm tra cuối (checklist)

- [ ] `config.yaml` đã có `calib_start: 1991`, `end: 2025`, đủ 5 trạm.
- [ ] Có đủ 5 file `data/interim/*_daily.csv`, số dòng bằng nhau.
- [ ] `validate_raw.py` không còn ERROR.
- [ ] Có `data/external/oni.ascii.txt` (nếu không, cột ONI sẽ là NaN).
- [ ] Bảng sanity check SPEI: mean ≈ 0, std ≈ 1, tỷ lệ hạn ≈ 0,16.
- [ ] Có `data/processed/dataset_monthly_ml.csv`.
- [ ] Lưu lại `logs/fetch_full.log` và `reports/validation_report.csv` làm bằng chứng cho báo cáo.

---

## 7. Lưu ý khi viết báo cáo đồ án

1. **Nguồn dữ liệu**: đây là dữ liệu tái phân tích theo ô lưới (ERA5 / ERA5-Land qua Open-Meteo), không phải số đo tại trạm. Nêu rõ điều này, kèm độ lệch tọa độ ô lưới so với trạm (ví dụ Bến Tre lệch khoảng 3 km).
2. **Độ ẩm đất chạm trần 0,43**: đây là ngưỡng bão hòa của mô hình, không phải giá trị đo thật. Các đợt mưa lớn không còn phân biệt được qua cột này.
3. **Chống rò rỉ dữ liệu**: đặc trưng tháng t chỉ dùng dữ liệu đến hết tháng t, nhãn là tương lai, ONI trễ từ 2 tháng, SPEI fit trên giai đoạn chuẩn cố định.
4. **Khoảng đệm giữa các tập**: vì nhãn nhìn trước tối đa 3 tháng, 3 tháng cuối của train có thể chồng nhẹ sang val. Hãy bỏ một khoảng đệm 3 tháng hoặc ghi chú rõ.
5. **Lớp hạn ít hơn lớp không hạn**: dùng `class_weight` hoặc thước đo F1 / PR-AUC thay vì chỉ dùng accuracy.
6. **Baseline để so sánh**: persistence (dự báo SPEI tương lai bằng SPEI hiện tại), sau đó mới đến Random Forest, XGBoost.
7. **Khả năng tái lập**: giữ nguyên `config.yaml`, các file thô trong `data/raw/` và phiên bản thư viện (`pip freeze > requirements.txt`).

---

## 8. Bước tiếp theo gợi ý

1. **EDA**: biểu đồ mưa, ET0, độ ẩm đất theo mùa; chuỗi SPEI-3 theo năm; so sánh vùng ven biển và nội địa.
2. **Mô hình baseline**: persistence, hồi quy tuyến tính, Random Forest cho `target_spei3_h1..h3`.
3. **Đánh giá**: RMSE, MAE, R² cho hồi quy; F1, PR-AUC cho phân loại hạn; báo cáo theo từng trạm và từng horizon.

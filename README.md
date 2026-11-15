# Wi-Fi CSI Fall Detection PoC — ESP32-S3 (ESP-IDF v6.0.2)

**Đồ án:** Nghiên cứu và phát triển hệ thống phát hiện té ngã bằng Wi-Fi CSI và AI, cấu hình **1 TX + 2 RX + Ubuntu UDP Collector**.

Bản mã v2 được điều chỉnh từ bộ firmware thử nghiệm v1 cho **ESP-IDF v6.0.2** và tách hướng dẫn thành **ba README độc lập**. Đây là **mã PoC lấy cảm hứng kỹ thuật từ RuView/ESP-CSI, không phải fork hay patch trực tiếp vào RuView**. TX và RX đều cấu hình bằng `menuconfig` và build trực tiếp tại project tương ứng; firmware cần được xác nhận trên phần cứng thật.

## Đọc theo vai trò

1. **[TX — bộ phát ESP-NOW](wifi_csi_tx/README.md):** cấu hình bằng `menuconfig`, build/nạp trực tiếp tại project TX, lấy STA MAC.
2. **[RX — hai bộ thu CSI](wifi_csi_rx/README.md):** dùng chung một project, đổi node ID để nạp lần lượt RX1/RX2, bật CSI và lọc MAC, gửi I/Q + metadata qua UDP.
3. **[Ubuntu UDP Collector](host/README.md):** cấu hình IP/port, chạy server, lưu `.dat`/`.csv`, kiểm tra tốc độ CSI.

## Sơ đồ

```text
                 ESP-NOW trực tiếp (cùng kênh)
ESP32-S3 TX  --------------> ESP32-S3 RX1 ----- UDP ----\
           \---------------> ESP32-S3 RX2 ----- UDP -----+--> Router 2.4 GHz --> Ubuntu
```

TX cũng kết nối Wi-Fi STA tới router để dùng cùng kênh. Router vận chuyển UDP của RX đến Ubuntu. **Không mặc định rằng** mỗi gói TX tạo đúng một mẫu CSI trên từng RX.

## Thay đổi chính so với v1 (ESP-IDF v5.4)

| Vấn đề | Bản v2 |
|---|---|
| Phiên bản ESP-IDF | **Khóa chính xác v6.0.2** qua `esp_idf_version.h` trong TX/RX |
| Wi-Fi bandwidth | `WIFI_BW_HT20` → **`WIFI_BW20`** |
| ESP-NOW callback TX | `const uint8_t *mac` → **`const esp_now_send_info_t *tx_info`** |
| Dependency CMake RX | Bỏ `esp_now` khỏi `REQUIRES`, dùng `esp_wifi` chứa header/API ESP-NOW |
| Cấu hình TX | Bỏ CSI enable không cần thiết trên TX |
| Cấu hình project | TX/RX dùng `idf.py menuconfig` trực tiếp; RX1/RX2 khác node ID |
| Tài liệu | `wifi_csi_tx/README.md`, `wifi_csi_rx/README.md`, `host/README.md` |

**Cấu hình thu cho ESP-Fi-HAR:** TX mục tiêu 100 probe/s; RX gửi `WCS2` (HT-LTF I/Q + metadata PHY, header 40 byte), `WTX1` giữ 34 byte. Collector vẫn đọc `WCS1` cũ; exporter yêu cầu WCS2 profile 1. Không tương thích nhị phân với **ADR-018** của RuView.

Xem [quy trình thu và xuất `CSIamp (950,52)`](host/ESP_FI_CAPTURE.md) để gắn nhãn trial, kiểm tra tốc độ và xuất MAT. Ánh xạ/timing tương đương dataset gốc vẫn cần xác nhận.

## Lộ trình nhanh

Từ thư mục **`firmware/`**, build TX trực tiếp:

```bash
idf.py --version                    # yêu cầu: ESP-IDF v6.0.2
cd wifi_csi_tx
# Chỉ chạy set-target khi khởi tạo project mới; cấu hình Wi-Fi sau bước này.
# idf.py set-target esp32s3
idf.py menuconfig                   # menu CSI probe transmitter
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

Lấy **STA MAC** từ log TX. Từ `wifi_csi_tx/`, chuyển sang project RX,
điền MAC TX, Wi-Fi và IP Ubuntu trong menu **CSI receiver**; chọn node ID **1**:

```bash
cd ../wifi_csi_rx
# Chỉ chạy set-target khi khởi tạo project mới, trước khi nhập cấu hình.
# idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM1 flash monitor
# Thoát monitor bằng Ctrl+], đổi node ID thành 2 trong menuconfig,
# build lại rồi nạp RX2 qua cổng serial tương ứng.
```

Trên Terminal Ubuntu khác, từ **thư mục gốc**:

```bash
python3 host/collector.py --bind 0.0.0.0 --port 5005 --out captures/test01
# Ctrl+C để dừng
python3 host/check_capture.py captures/test01.dat
```

> Thứ tự thử nghiệm khuyến nghị: **TX → RX1 → Ubuntu collector → RX2**. Chỉ khi có dữ liệu `CSI` thật của cả hai RX mới chuyển sang bước đồng bộ và AI.

## Yêu cầu và bảo mật

- 3 board ESP32-S3, router Wi-Fi 2.4 GHz kênh cố định và Ubuntu Python 3.10+.
- Bên ESP32 dùng **ESP-IDF v6.0.2**, toolchain `esp32s3`; Ubuntu collector dùng Python chuẩn, không cần package ngoài.
- Chỉ chạy trên LAN thử nghiệm tin cậy; ESP-NOW broadcast và UDP không mã hóa.
- CSI timestamp các thiết bị không được đồng bộ tuyệt đối. Không sử dụng làm thiết bị y tế phát hiện té ngã.

## Kiểm thử

Từ `firmware/`, chạy kiểm thử của host:

```bash
python3 -m unittest discover -s host/tests -v
python3 -m py_compile host/collector.py host/check_capture.py host/export_esp_fi.py
```

TX và RX đã tối giản, không có thư mục tests riêng. Kiểm tra bằng `idf.py build`
trong `wifi_csi_tx/` và `wifi_csi_rx/`, sau đó nạp và theo dõi hoạt động trên board
theo README tương ứng. Với RX, xác nhận Ubuntu nhận CSI từ cả node ID 1 và 2.

## Liên kết kỹ thuật

- [RuView esp32-csi-node](https://github.com/ruvnet/RuView/tree/main/firmware/esp32-csi-node)
- [ESP-IDF v6.0.2 ESP32-S3](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/)
- [ESP-IDF Wi-Fi API v6.0.2](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/api-reference/network/esp_wifi.html)
- [ESP-NOW header ở tag v6.0.2](https://github.com/espressif/esp-idf/blob/v6.0.2/components/esp_wifi/include/esp_now.h)

# Wi-Fi CSI Fall Detection PoC — ESP32-S3 (ESP-IDF v6.0.2)

**Đồ án:** Nghiên cứu và phát triển hệ thống phát hiện té ngã bằng Wi-Fi CSI và AI, cấu hình **1 TX + 2 RX + Ubuntu UDP Collector**.

Mã nguồn hiện có pipeline phát probe ESP-NOW, thu CSI I/Q, lưu capture, kiểm tra dữ liệu và xuất mẫu biên độ `CSIamp (950,52)` để thử nghiệm với đầu vào ESP-Fi-HAR. **Chưa tích hợp mô hình AI hay cơ chế cảnh báo té ngã.** Kết quả build và kiểm thử phần mềm không thay thế việc xác nhận CSI trên board thật hoặc đánh giá mô hình bằng dữ liệu tự thu.

Đây là **mã PoC lấy cảm hứng kỹ thuật từ RuView/ESP-CSI, không phải fork hay patch trực tiếp vào RuView**. TX và RX là hai project ESP-IDF độc lập, cấu hình bằng `menuconfig` và build trực tiếp tại project tương ứng.

## Đọc theo vai trò

1. **[TX — bộ phát ESP-NOW](wifi_csi_tx/README.md):** cấu hình bằng `menuconfig`, build/nạp trực tiếp tại project TX, lấy STA MAC.
2. **[RX — hai bộ thu CSI](wifi_csi_rx/README.md):** dùng chung một project, đổi node ID để nạp lần lượt RX1/RX2, bật CSI và lọc MAC, gửi I/Q + metadata qua UDP.
3. **[Ubuntu UDP Collector](host/README.md):** cấu hình IP/port, chạy server, lưu `.dat`/`.csv`, kiểm tra tốc độ CSI.
4. **[Thu trial và xuất MAT](host/ESP_FI_CAPTURE.md):** gắn nhãn hoạt động, kiểm tra chất lượng và xuất mẫu cho thử nghiệm ESP-Fi-HAR.

## Cấu trúc dự án

| Đường dẫn | Nội dung |
|---|---|
| `wifi_csi_tx/` | Firmware TX; `main/probe.h` mã hóa probe ESP-NOW |
| `wifi_csi_rx/` | Firmware dùng chung cho RX1/RX2; `main/protocol.h` mã hóa UDP |
| `host/` | Collector, checker, exporter MAT và kiểm thử trong `tests/` |
| `captures/` | Dữ liệu `.dat`/`.csv` cục bộ, được bỏ qua trong Git |
| [`reports/esp_fi_har_audit/`](reports/esp_fi_har_audit/README.md) | Báo cáo audit dataset tại thời điểm kiểm tra, có mô tả cấu hình capture cũ |

Mỗi project firmware có `main/Kconfig.projbuild` và `sdkconfig.defaults` riêng. ESP-IDF tạo `sdkconfig` để lưu cấu hình local và `build/` để chứa kết quả build.

## Sơ đồ

```text
                 ESP-NOW trực tiếp (cùng kênh)
ESP32-S3 TX  --------------> ESP32-S3 RX1 ----- UDP ----\
           \---------------> ESP32-S3 RX2 ----- UDP -----+--> Router 2.4 GHz --> Ubuntu
```

TX cũng kết nối Wi-Fi STA tới router để dùng cùng kênh. Router vận chuyển UDP của RX đến Ubuntu. TX/RX/router cần cùng kênh cố định trên Wi-Fi **2.4 GHz, 20 MHz**; mặc định project là kênh 6. **Không mặc định rằng** mỗi gói TX tạo đúng một mẫu CSI trên từng RX.

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

## Build và triển khai

Nạp môi trường ESP-IDF trước khi build; đổi đường dẫn nếu cài ở nơi khác:

```bash
. ~/.espressif/v6.0.2/esp-idf/export.sh
idf.py --version
```

Kiểm tra IPv4 thật của Ubuntu bằng `ip -4 addr` để nhập vào RX. `0.0.0.0` là địa chỉ lắng nghe của collector, không dùng làm IP đích trên RX. Các cổng serial dưới đây chỉ là ví dụ; thay bằng cổng thực tế của từng board.

### 1. Cấu hình và nạp TX

Từ thư mục **`firmware/`**, build TX trực tiếp:

```bash
cd wifi_csi_tx
# Chỉ chạy set-target khi khởi tạo project mới; cấu hình Wi-Fi sau bước này.
# idf.py set-target esp32s3
idf.py menuconfig                   # menu CSI probe transmitter
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

Trong menu **CSI probe transmitter**, nhập SSID/mật khẩu, kênh router và đặt `APP_TX_INTERVAL_MS=10`. Cấu hình nền TX đặt `CONFIG_FREERTOS_HZ=1000`; kiểm tra lại nếu dùng `sdkconfig` cũ. Chu kỳ 10 ms tương ứng mục tiêu 100 probe/s, không bảo đảm tốc độ CSI thực ở RX.

Lấy **STA MAC** từ log `IMPORTANT TX STA MAC = ...`.

### 2. Cấu hình và nạp RX1

Từ `wifi_csi_tx/`, chuyển sang project RX,
điền MAC TX, Wi-Fi và IP Ubuntu trong menu **CSI receiver**; chọn node ID **1**:

```bash
cd ../wifi_csi_rx
# Chỉ chạy set-target khi khởi tạo project mới, trước khi nhập cấu hình.
# idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM1 flash monitor
```

Trong menu **CSI receiver**, kiểm tra các thiết lập:

| Thiết lập | Giá trị cần dùng |
|---|---|
| `APP_RX_NODE_ID` | `1` cho RX1, `2` cho RX2 |
| `APP_WIFI_SSID`, `APP_WIFI_PASSWORD` | Thông tin router 2.4 GHz |
| `APP_WIFI_CHANNEL` | Cùng kênh router và TX |
| `APP_TX_MAC` | STA MAC thật lấy từ log TX |
| `APP_SERVER_IP` | IPv4 thật của Ubuntu |
| `APP_SERVER_PORT` | `5005`, trùng cổng collector |
| `APP_MIN_CSI_INTERVAL_MS` | `0`, không throttle CSI |
| `APP_QUEUE_DEPTH` | `128` |

### 3. Chạy collector và nạp RX2

Trên terminal Ubuntu khác, từ **thư mục gốc**, chạy collector trước khi bắt đầu phiên đo:

```bash
python3 host/collector.py --bind 0.0.0.0 --port 5005 --out captures/test01
```

Xác nhận Ubuntu nhận được `CSI` từ RX1. Sau đó tại `wifi_csi_rx/`, thoát monitor bằng **Ctrl+]**, đổi **RX node ID = 2**, build và nạp RX2:

```bash
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM2 flash monitor
```

Mỗi lần đổi node ID phải build lại. Thư mục `build/` chứa kết quả build gần nhất; khi nạp lại RX1, đổi ID về `1` rồi build/flash lại. **Không chạy lại `set-target` để đổi RX1/RX2** vì lệnh này tái tạo cấu hình.

Collector tạo `captures/test01.dat` và `captures/test01.csv`. **Chọn prefix mới cho mỗi trial**: chạy lại cùng `--out` sẽ append vào file cũ. Không append vào CSV của phiên bản có header khác.

## Kiểm tra capture

Dừng collector bằng **Ctrl+C** trước khi kiểm tra. Từ thư mục gốc:

```bash
python3 host/check_capture.py captures/test01.dat
```

Trước khi dùng dữ liệu để xuất mẫu, kiểm tra riêng từng RX:

- Có `CSI` từ cả node `1` và `2`; MAC nguồn và kênh đúng cấu hình.
- `bad=0`, WCS2 `profile=1`, độ dài I/Q là `128` byte và `first_word_invalid=0` cho dữ liệu dùng để export.
- Tốc độ CSI thực gần mục tiêu 100 bản ghi/giây; kiểm tra khoảng ngắt lớn nhất và mất sequence trong cửa sổ được chọn.
- Theo dõi `q_drop`, `send_fail` trên RX để phát hiện mất gói do queue hoặc mạng.

`TX_EVENT`/`WTX1` chỉ chứng minh RX nhận probe ESP-NOW, chưa chứng minh có CSI hợp lệ. Bộ đếm `sent` trên RX gồm cả CSI và TX_EVENT, không phải tốc độ CSI riêng.

| Giao thức | Nội dung và phạm vi sử dụng |
|---|---|
| `CSIP` | Probe TX → RX, 16 byte |
| `WCS2` | CSI hiện tại: header 40 byte + 128 byte HT-LTF I/Q, thứ tự Q rồi I, kèm metadata PHY |
| `WCS1` | CSI cũ; collector/checker vẫn đọc được, exporter ESP-Fi-HAR từ chối |
| `WTX1` | Sự kiện nhận probe, 34 byte; chứa sequence và timestamp TX, không chứa CSI |

`csi_seq` và `rx_local_us` là cục bộ từng RX. Không ghép RX1/RX2 bằng cách so trực tiếp sequence hoặc timestamp; cũng không ghép CSI với TX_EVENT chỉ bằng sequence. Timestamp nhận trên Ubuntu có jitter mạng và chỉ hỗ trợ căn chỉnh sơ bộ.

## Xuất mẫu cho thử nghiệm ESP-Fi-HAR

Thu một trial có nhãn hoạt động rõ ràng, với ít nhất khoảng 10 giây CSI liên tục trong đoạn hoạt động cần dùng. Ví dụ sau giả định `test01` là **đi bộ** của người 2, phòng local 1, lần thử 1. Chạy từ thư mục gốc:

```bash
python3 host/export_esp_fi.py captures/test01.dat \
  --out datasets/local --node 1 --label walk \
  --subject 2 --scenario 1 --trial 1 --split train_amp
```

Kết quả gồm:

```text
datasets/local/rx1/train_amp/walk/1-2-2-1.mat
datasets/local/rx1/train_amp/walk/1-2-2-1.json
```

MAT chứa `CSIamp` float64 **`(950,52)`**, chưa chuẩn hóa Z-score. JSON ghi nguồn capture, nhãn, ánh xạ sóng mang, tốc độ thực và chất lượng cửa sổ. Đổi `--node 2` để xuất RX2 riêng; `--split` nhận `train_amp` hoặc `test_amp`.

Exporter yêu cầu **WCS2 profile 1**, HT20/MCS0/long GI, không STBC/secondary channel và không có cờ invalid đầu CSI. Công cụ chọn 52 data carriers, tính biên độ rồi nội suy trên lưới 100 Hz với các giới hạn:

- 950 điểm trải dài **9,49 giây** từ điểm đầu đến cuối.
- Tốc độ CSI gốc **≥90 Hz**, khoảng ngắt giữa hai bản ghi **≤30 ms**, tỷ lệ mất sequence **≤10%**.
- Không ngoại suy, padding hay kéo giãn capture cũ 20 Hz; từ chối timestamp/sequence lặp hoặc lùi, đổi MAC/kênh trong cửa sổ.

Nếu có đoạn chuẩn bị ở đầu capture, dùng `--start-us` theo timestamp cục bộ của RX cần xuất; cùng một giá trị trên hai RX không chứng minh hai cửa sổ đã đồng bộ.

Các nhãn hỗ trợ: `arm_wave`, `fall`, `jump`, `run`, `squat`, `turn`, `walk`. Nhãn do người thu cung cấp, không phải dự đoán AI. Tách người/phiên train và test theo mục tiêu đánh giá; exporter không tự chia tập dữ liệu.

Định dạng `(950,52)` chưa chứng minh dữ liệu tương đương ESP-Fi-HAR về timing hoặc thứ tự sóng mang. Hai thuộc tính này vẫn được ghi là chưa xác minh trong manifest. Xem [quy trình thu và xuất MAT](host/ESP_FI_CAPTURE.md) và [báo cáo audit](reports/esp_fi_har_audit/README.md) trước khi huấn luyện hoặc đánh giá mô hình.

## Yêu cầu và bảo mật

- 3 board ESP32-S3, router Wi-Fi 2.4 GHz kênh cố định và Ubuntu Python 3.10+.
- Bên ESP32 dùng **ESP-IDF v6.0.2**, toolchain `esp32s3`; collector, checker và exporter MAT dùng Python chuẩn, không cần package ngoài.
- Giữ thông tin Wi-Fi trong `sdkconfig` cục bộ; không đưa bí mật vào `sdkconfig.defaults` dùng chung. Build, cấu hình cục bộ và capture được bỏ qua trong Git.
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

Các test host kiểm tra giao thức C/Python, gói lỗi, lưu DAT/CSV, UDP loopback, ánh xạ sóng mang, điều kiện chất lượng trial và định dạng MAT. Test UDP cần quyền tạo socket loopback; test đối chiếu encoder C cần trình biên dịch `cc`.

## Liên kết kỹ thuật

- [RuView esp32-csi-node](https://github.com/ruvnet/RuView/tree/main/firmware/esp32-csi-node)
- [ESP-IDF v6.0.2 ESP32-S3](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/)
- [ESP-IDF Wi-Fi API v6.0.2](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/api-reference/network/esp_wifi.html)
- [ESP-NOW header ở tag v6.0.2](https://github.com/espressif/esp-idf/blob/v6.0.2/components/esp_wifi/include/esp_now.h)

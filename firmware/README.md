# Firmware và thu dữ liệu Wi-Fi CSI — ESP32-S3

Phần firmware của FallDetection gồm một TX, hai RX và collector chạy trên Ubuntu. TX/RX dùng **ESP-IDF đúng v6.0.2**, target **esp32s3**. Hai project được cấu hình, build và nạp độc lập.

Người mới bắt đầu từ [README dự án](../README.md) và [hướng dẫn cộng tác/Git](../CONTRIBUTING.md). Các lệnh trong tài liệu này đều ghi rõ thư mục chạy.

## 1. Phạm vi hiện tại

```text
TX -- ESP-NOW --> RX1 -- UDP --┐
          └----> RX2 -- UDP ---┴--> Router 2.4 GHz --> Ubuntu --> CSV
```

- TX phát probe `CSIP` tới RX qua ESP-NOW broadcast.
- RX thu CSI, lọc theo STA MAC của TX và gửi UDP về Ubuntu. RX1/RX2 dùng chung mã nhưng khác node ID.
- `host/collector.py` nhận CSI `WCS2`/`WCS1`, bỏ qua `WTX1`, có đếm ngược và ghi phiên CSV trong 17 giây.
- Repo hiện chưa có checker capture, exporter MAT, mô hình AI hay cơ chế cảnh báo té ngã. Collector không tạo `.dat`.

| Đường dẫn | Nội dung |
|---|---|
| [`wifi_csi_tx/`](wifi_csi_tx/README.md) | Firmware bộ phát, `main/probe.h` mã hóa probe |
| [`wifi_csi_rx/`](wifi_csi_rx/README.md) | Firmware RX1/RX2, `main/protocol.h` mã hóa UDP |
| [`host/`](host/README.md) | Collector và kiểm thử trong `tests/test_collector.py` |
| `captures/` | Dữ liệu CSV cục bộ, được tạo khi thu và bỏ qua trong Git |

## 2. Chuẩn bị

- Ba board ESP32-S3 và cáp USB có dữ liệu nếu chạy đủ TX + RX1 + RX2.
- Router Wi-Fi 2.4 GHz, kênh cố định, băng thông 20 MHz. TX và RX phải cùng kênh router; mặc định cấu hình kênh 6.
- Ubuntu với Python 3.10+; collector chỉ dùng thư viện chuẩn.
- ESP-IDF v6.0.2 và toolchain ESP32-S3 cho người build firmware. Xem [tài liệu ESP-IDF v6.0.2](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/).

Mở terminal và nạp môi trường ESP-IDF, đổi đường dẫn theo nơi đã cài:

```bash
. ~/.espressif/v6.0.2/esp-idf/export.sh
idf.py --version
```

Mã TX/RX kiểm tra phiên bản lúc biên dịch. Không tự nâng ESP-IDF khi chưa đánh giá tương thích.

## 3. Cấu hình và nạp TX

Từ thư mục gốc `FallDetection/`:

```bash
cd firmware/wifi_csi_tx
# Chỉ dùng lần đầu khi chưa có sdkconfig, trước khi nhập cấu hình:
idf.py set-target esp32s3
idf.py menuconfig
```

Trong menu **CSI probe transmitter**, nhập SSID/mật khẩu Wi-Fi, kênh router và chu kỳ phát. Lưu cấu hình vào `sdkconfig` cục bộ, rồi:

```bash
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

Đổi cổng serial theo board thực tế. Ghi lại **STA MAC** từ log `IMPORTANT TX STA MAC = ...` để cấu hình RX. Thoát monitor bằng **Ctrl+]**.

Mặc định `APP_TX_INTERVAL_MS=10`, tương đương mục tiêu phát 100 probe/giây. Collector hiện hiển thị mục tiêu 50 CSI/giây/RX; hai giá trị chưa thống nhất. Nếu nhóm chọn nhịp phát mục tiêu 50 probe/giây thì cấu hình TX 20 ms, nhưng vẫn phải đo CSI thực trên từng RX. Nhịp phát không bảo đảm nhịp nhận CSI; collector không tự điều chỉnh tốc độ dữ liệu.

Xem thêm [README TX](wifi_csi_tx/README.md).

## 4. Cấu hình và nạp RX1/RX2

Từ thư mục TX ở bước trên:

```bash
cd ../wifi_csi_rx
# Chỉ chạy lần đầu khi chưa có sdkconfig:
idf.py set-target esp32s3
idf.py menuconfig
```

Trong menu **CSI receiver**, cấu hình:

| Tùy chọn | Giá trị |
|---|---|
| `APP_RX_NODE_ID` | `1` cho RX1, `2` cho RX2 |
| `APP_WIFI_SSID`, `APP_WIFI_PASSWORD` | Router 2.4 GHz đang dùng |
| `APP_WIFI_CHANNEL` | Cùng kênh router/TX |
| `APP_TX_MAC` | STA MAC thật từ log TX, không dùng MAC ví dụ |
| `APP_SERVER_IP` | IPv4 thật của Ubuntu; kiểm tra trên Ubuntu bằng `ip -4 addr` |
| `APP_SERVER_PORT` | `5005`, trùng collector |
| `APP_MIN_CSI_INTERVAL_MS` | `0` để không throttle |
| `APP_QUEUE_DEPTH` | Mặc định `128` |

Với node ID **1**, build rồi nạp RX1:

```bash
idf.py build
idf.py -p /dev/ttyACM1 flash monitor
```

Thoát monitor bằng **Ctrl+]**. Đổi node ID sang **2** bằng `idf.py menuconfig`, lưu, build lại và nạp RX2:

```bash
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM2 flash monitor
```

Cổng serial chỉ là ví dụ. Mỗi lần đổi node ID phải build lại trước khi flash. `build/` chứa binary gần nhất; muốn nạp lại RX1 phải đổi ID về 1 rồi build/nạp lại. Không chạy lại `set-target` để đổi RX1/RX2 vì lệnh này tái tạo cấu hình.

Xem thêm [README RX](wifi_csi_rx/README.md). Không dùng `0.0.0.0` làm IP đích của RX; đó chỉ là địa chỉ lắng nghe phía collector.

## 5. Thu một phiên CSV

Mở terminal khác, từ thư mục gốc `FallDetection/`:

```bash
cd firmware
python3 host/collector.py --bind 0.0.0.0 --port 5005 \
  --out captures/trial01 --countdown 5
```

Chương trình đếm ngược 5 giây, ghi 17 giây rồi tự đóng `captures/trial01.csv`. Bỏ `--countdown` nếu muốn nhập tương tác. Dùng tên mới cho mỗi trial: tệp đã tồn tại sẽ bị từ chối, không ghi đè hoặc ghi nối. **Ctrl+C** trong lúc ghi sẽ giữ phần CSV đã thu.

CSV gồm đúng sáu cột: `timestamp`, `csi_seq`, `node_id`, `mac`, `len`, `buf`. `timestamp` là microsecond cục bộ của RX; `buf` giữ danh sách I/Q có dấu theo thứ tự Q rồi I. CSV hiện không lưu đầy đủ metadata PHY/cờ invalid mà parser nhận được; xem thống kê và giới hạn trong [README collector](host/README.md) trước khi dùng dữ liệu cho AI.

Kiểm tra sau mỗi phiên:

- Có CSI từ cả RX1 và RX2, phân biệt bằng node ID 1/2.
- Số lượng và tốc độ CSI thực của từng RX đáp ứng cấu hình thử nghiệm đã thống nhất.
- Xem số gói lỗi/cờ invalid ở collector và `q_drop`, `send_fail` trên RX.
- Chỉ có `WTX1` chưa chứng minh thu được CSI. Sequence và timestamp hai RX là cục bộ; không ghép trực tiếp bằng giá trị bằng nhau.

Nếu không có UDP, kiểm tra IP Ubuntu, cổng 5005, firewall, cùng mạng và Client Isolation trên AP. Dữ liệu đo cần kèm ghi chú cấu hình, nhãn hoạt động và điều kiện thử nghiệm ở nơi lưu dữ liệu của nhóm.

## 6. Kiểm thử khi phát triển

Từ thư mục gốc `FallDetection/`, chạy:

```bash
python3 -m unittest discover -s firmware/host/tests -v
python3 -m py_compile firmware/host/collector.py
```

Kiểm thử dùng thư viện chuẩn, có UDP loopback và phiên thu đủ 17 giây. Cần `cc` để chạy bài đối chiếu encoder C; nếu thiếu sẽ bị skip. Không cần board để chạy các test này.

Khi sửa TX/RX, chạy `idf.py build` trong project tương ứng với môi trường ESP-IDF đã nạp. Build và test host không thay cho đo radio trên board thật; báo riêng kết quả phần mềm và phần cứng trong PR.

Giữ Wi-Fi trong `sdkconfig` cục bộ; không sửa `build/config/sdkconfig.h` tự sinh hoặc đưa mật khẩu vào `sdkconfig.defaults`. Chỉ thử nghiệm trên LAN tin cậy vì ESP-NOW broadcast và UDP hiện không mã hóa.

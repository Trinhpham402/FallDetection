# ESP32-S3 TX — Bộ phát Wi-Fi CSI Probe

Firmware cho **ESP32-S3**, yêu cầu **ESP-IDF v6.0.2**. TX phát probe
**ESP-NOW broadcast** trực tiếp để RX1/RX2 đo CSI từ cùng một nguồn phát.
TX kết nối router 2.4 GHz bằng Wi-Fi STA để hoạt động trên cùng kênh.
TX không thu CSI, không gửi CSI tới Ubuntu và không chạy AI.

## 1. Cấu trúc project

```text
wifi_csi_tx/
├── CMakeLists.txt
├── README.md
├── sdkconfig.defaults       # Cấu hình nền dùng chung, không chứa mật khẩu
├── .gitignore
├── .clangd                 # Tùy chọn: cấu hình phân tích mã
├── .vscode/                # Tùy chọn: cấu hình editor
├── .devcontainer/          # Tùy chọn: môi trường ESP-IDF v6.0.2
├── main/
│   ├── CMakeLists.txt
│   ├── Kconfig.projbuild    # SSID, mật khẩu, kênh và chu kỳ phát
│   ├── main.c              # Khởi tạo, sự kiện Wi-Fi và vòng lặp phát
│   └── probe.h             # Mã hóa probe 16 byte
├── sdkconfig               # Cấu hình local, được ESP-IDF tạo/quản lý
└── build/                  # Kết quả build, được ESP-IDF tạo
```

**Chỉnh sửa, cấu hình và build trực tiếp tại `wifi_csi_tx/`.** Project chỉ có
một bản mã nguồn; không dùng workspace sao chép, script chuẩn bị hay cấu hình JSON.
`sdkconfig`, `sdkconfig.old` và `build/` được bỏ qua trong Git.

Các thành phần khác nằm cạnh project TX:
[firmware RX](../wifi_csi_rx/README.md) và [Ubuntu collector](../host/README.md).

## 2. Chuẩn bị môi trường

- ESP32-S3 và cáp USB có dữ liệu.
- ESP-IDF **đúng v6.0.2** với toolchain ESP32-S3.
- Router/AP 2.4 GHz cố định kênh, ví dụ kênh 6, băng thông 20 MHz.

Nạp môi trường ESP-IDF trước khi dùng `idf.py`, ví dụ trên máy hiện tại:

```bash
. ~/.espressif/v6.0.2/esp-idf/export.sh
idf.py --version
```

Đổi đường dẫn `export.sh` nếu cài ESP-IDF ở nơi khác. Môi trường container
trong `.devcontainer/` sử dụng image `espressif/idf:v6.0.2`.

## 3. Cấu hình TX

Từ thư mục `firmware/`:

```bash
cd wifi_csi_tx
```

Các lệnh sau chạy ngay trong `wifi_csi_tx/`. Với project mới chưa có
`sdkconfig`, chọn target một lần:

```bash
idf.py set-target esp32s3
```

Không cần chạy lại `set-target` cho mỗi lần build. Lệnh này tái tạo cấu hình;
sau đó hãy nhập lại các thiết lập cần dùng qua:

```bash
idf.py menuconfig
```

Trong menu **CSI probe transmitter**, đặt:

| Tùy chọn | Ý nghĩa | Giá trị mặc định |
|---|---|---|
| Wi-Fi SSID | Tên mạng 2.4 GHz | Trống, cần nhập |
| Wi-Fi password | Mật khẩu; để trống với AP mở | Trống |
| Expected 2.4 GHz channel | Kênh cố định của router | 6 |
| Probe interval (ms) | Chu kỳ phát mục tiêu | 10 ms |

Lưu cấu hình trước khi thoát. Các giá trị được lưu vào `sdkconfig` local;
giữ `sdkconfig.defaults` dùng chung không chứa thông tin Wi-Fi riêng.
SSID tối đa 32 byte và phải khác rỗng. Với AP dùng mật khẩu, dùng thông tin
xác thực hợp lệ của AP. `10 ms` tương ứng mục tiêu 100 gói/giây, không bảo đảm
tốc độ CSI tại RX.

Cấu hình PHY hiện tại dùng HT20/MCS0/long GI. Mặc định TX là 10 ms/probe, còn collector hiển thị mục tiêu 50 CSI/s/RX; cần thống nhất nhịp thử nghiệm và đo CSI thực. Xem [hướng dẫn collector](../host/README.md) và [tổng quan firmware](../README.md). Repo hiện chưa có công cụ xuất mẫu ESP-Fi-HAR.

## 4. Build, flash và monitor

```bash
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

`/dev/ttyACM0` là ví dụ; chọn cổng thực tế của board. Dừng monitor bằng `Ctrl+]`.
Khi sửa `main/main.c` hoặc `main/probe.h`, build lại tại đây; khi thay đổi
Wi-Fi hoặc chu kỳ phát, chạy `idf.py menuconfig`, lưu rồi build/nạp lại.

Firmware có kiểm tra compile-time và chỉ chấp nhận **ESP32-S3, ESP-IDF v6.0.2**.

## 5. Luồng hoạt động và định dạng probe

1. Khởi tạo NVS, Event Group và semaphore kiểm soát gửi.
2. Khởi tạo Wi-Fi STA, băng thông 20 MHz, tắt tiết kiệm điện và in STA MAC.
3. Khởi tạo ESP-NOW broadcast, đặt PHY HT20/MCS0, long GI.
4. Chỉ phát khi đã nhận IP, kênh đúng cấu hình và không còn gói chờ callback.
5. Mất kết nối thì dừng phát, tự kết nối lại; không gửi dồn để bù nhịp bị lỡ.

Probe được mã hóa trong [main/probe.h](main/probe.h):

| Offset | Kích thước | Nội dung |
|---|---|---|
| 0 | 4 byte | Magic `CSIP` |
| 4 | 4 byte | `tx_seq`, u32 little endian |
| 8 | 8 byte | `tx_local_us`, u64 little endian |

Sequence tăng cho mỗi lần gọi gửi, kể cả khi API trả lỗi; khởi động lại sẽ
reset sequence. Timestamp là thời gian cục bộ TX, đơn vị microsecond, chưa
đồng bộ với RX. `CSIP` không phải nhãn té ngã.

## 6. Kiểm tra sau khi nạp

Log minh họa:

```text
IMPORTANT TX STA MAC = 24:6F:28:AA:BB:CC
Router channel=6, TX interval=10 ms
ESP-NOW submitted=200 errors=0 mac_fail=0 skipped=10
```

Ghi lại **STA MAC** để cấu hình bộ lọc nguồn phát của RX theo hướng dẫn RX.
TX không cần nhập địa chỉ Ubuntu, port UDP hay MAC của chính nó vào cấu hình.

Thống kê được in mỗi 10 giây:

- `submitted`: số yêu cầu gửi được API chấp nhận.
- `errors`: số lần API gửi trả lỗi ngay lập tức.
- `mac_fail`: số callback báo gửi thất bại.
- `skipped`: số nhịp bỏ qua khi chưa sẵn sàng, sai kênh hoặc gói trước chưa xong.

Kiểm tra trên phần cứng: AP đúng kênh → `submitted` tăng; tắt AP → ngừng phát;
bật lại → tự kết nối và tiếp tục; AP sai kênh → báo lỗi và không phát probe.
Nếu callback không về, semaphore chưa được trả và TX sẽ bỏ qua các nhịp sau.

`submitted` tăng hoặc callback thành công với broadcast chưa chứng minh RX
nhận được gói hay có CSI. Cần kiểm tra dữ liệu tại RX/Ubuntu trước khi thu dữ liệu
huấn luyện. Kiểm tra build trên máy không thay thế kiểm tra radio trên board thật.

## 7. Tài liệu tham khảo

- [ESP-IDF v6.0.2 cho ESP32-S3](https://docs.espressif.com/projects/esp-idf/en/v6.0.2/esp32s3/)
- [ESP-NOW header v6.0.2](https://github.com/espressif/esp-idf/blob/v6.0.2/components/esp_wifi/include/esp_now.h)

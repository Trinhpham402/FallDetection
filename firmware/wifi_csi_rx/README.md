# ESP32-S3 RX1 / RX2 — Bộ thu CSI và gửi UDP (ESP-IDF v6.0.2)

**Vai trò:** hai board ESP32-S3 chạy **cùng mã nguồn RX**, khác `node_id`. Mỗi RX nối router Wi-Fi 2.4 GHz để gửi dữ liệu đến Ubuntu qua UDP; đồng thời nhận gói ESP-NOW broadcast từ **TX**, bật CSI, lọc theo **STA MAC của TX**, ghi lại **I/Q thô** cùng timestamp cục bộ.

## 1. Cấu trúc và luồng dữ liệu

```text
TX -- ESP-NOW broadcast --> RX1 / RX2
                                    |
                 CSI callback ------+--> FreeRTOS Queue --> udp_worker()
                 ESP-NOW callback --+                      |
                                                       UDP v
                                                Ubuntu Collector
```

Cấu trúc mã nguồn:

```text
wifi_csi_rx/
├── CMakeLists.txt
├── sdkconfig.defaults
├── README.md
├── .gitignore
└── main/
    ├── CMakeLists.txt
    ├── Kconfig.projbuild
    ├── main.c
    └── protocol.h
```

Chỉnh sửa, cấu hình và build trực tiếp tại `wifi_csi_rx/`. RX1 và RX2 dùng chung
một project, nạp lần lượt với node ID tương ứng. ESP-IDF tạo `sdkconfig` để lưu
cấu hình local và `build/` để chứa kết quả build; cả hai được bỏ qua trong Git.
Các file cấu hình editor/container có thể giữ lại để hỗ trợ phát triển.

Trong `main/main.c`:

- `wifi_sta_start()` khởi động Wi-Fi STA, kết nối và kiểm tra kênh so với `APP_WIFI_CHANNEL`.
- `esp_now_recv_cb()` nhận payload `CSIP`, tạo sự kiện `WTX1` có `tx_seq` và timestamp của TX.
- `wifi_csi_cb()` nhận CSI, **lọc `info->mac` bằng MAC của TX**, sao chép I/Q vào queue không chặn Wi-Fi task.
- `udp_worker()` gửi sự kiện CSI `WCS2` và TX `WTX1` về Ubuntu, **không gọi UDP trong CSI callback**.
- `esp_wifi_set_promiscuous(true)` dùng với bộ lọc management frames để quan sát gói ESP-NOW; hiệu quả thu CSI thực tế cần được xác nhận trên thiết bị.

## 2. Yêu cầu

- ESP-IDF **v6.0.2**, target **esp32s3** (xem cài đặt trong [README TX](../wifi_csi_tx/README.md)).
- Hai RX và TX ở cùng router/AP 2.4 GHz, cùng kênh, băng thông 20 MHz.
- Đã nạp TX và lấy **STA MAC** từ serial TX.
- IP IPv4 máy Ubuntu có thể truy cập từ RX qua router. Nếu AP có Client Isolation, hãy tắt để RX gửi được UDP.

Nạp môi trường ESP-IDF và kiểm tra phiên bản (đổi đường dẫn nếu cài ở nơi khác):

```bash
. ~/.espressif/v6.0.2/esp-idf/export.sh
idf.py --version
# Phải là ESP-IDF v6.0.2
```

## 3. Cấu hình trực tiếp bằng menuconfig

Từ thư mục **`firmware/`**:

```bash
cd wifi_csi_rx
```

Các lệnh tiếp theo chạy ngay tại `wifi_csi_rx/`. Với project mới chưa có
`sdkconfig`, chọn target một lần **trước khi nhập cấu hình**:

```bash
idf.py set-target esp32s3
```

Không chạy lại `set-target` khi đổi RX1/RX2 vì lệnh này tái tạo cấu hình.
Nếu đã có `sdkconfig` cho ESP32-S3, mở cấu hình trực tiếp:

```bash
idf.py menuconfig
```

Trong menu **CSI receiver**, đặt:

| Tùy chọn | Ví dụ | Ý nghĩa |
|---|---|---|
| RX node ID (`APP_RX_NODE_ID`) | `1` hoặc `2` | Chọn đúng board sắp nạp |
| Wi-Fi SSID (`APP_WIFI_SSID`) | `TEN_WIFI_2G` | SSID router 2.4 GHz |
| Wi-Fi password (`APP_WIFI_PASSWORD`) | Mật khẩu Wi-Fi của bạn | Mật khẩu mạng thử nghiệm |
| Expected AP and TX channel (`APP_WIFI_CHANNEL`) | `6` | Kênh router đã cố định |
| Collector IPv4 (`APP_SERVER_IP`) | `192.168.1.100` | IPv4 thật của Ubuntu (kiểm tra bằng `ip -4 addr`) |
| Collector UDP port (`APP_SERVER_PORT`) | `5005` | Cổng UDP collector |
| TX STA MAC (`APP_TX_MAC`) | `24:6F:28:AA:BB:CC` | **STA MAC thật lấy từ log TX** |
| Minimum CSI interval (`APP_MIN_CSI_INTERVAL_MS`) | `0` | Không throttle; mục tiêu thu gần 100 CSI/s |
| Packet queue depth (`APP_QUEUE_DEPTH`) | `128` | Số gói tối đa trong queue |

Địa chỉ MAC trên chỉ là ví dụ, **không nhập nguyên**. Firmware từ chối chạy
nếu MAC TX bằng `00:00:00:00:00:00` hoặc cấu hình bắt buộc không hợp lệ.
Lưu và thoát menuconfig; các giá trị được ghi vào `sdkconfig`.
Không sửa `build/config/sdkconfig.h` vì đó là file tự sinh.

## 4. Build và nạp RX1

Tại `wifi_csi_rx/`, sau khi chọn **RX node ID = 1**:

```bash
idf.py build
idf.py -p /dev/ttyACM1 flash monitor
```

Thay `/dev/ttyACM1` bằng cổng serial thực. Trên log cần thấy `RX1 filter TX=... -> SERVER_IP:5005`. Nếu RX bị kẹt ở bước kết nối Wi-Fi, xác minh SSID/mật khẩu/router 2.4 GHz trước.

## 5. Build và nạp RX2

Thoát monitor RX1 bằng **Ctrl+]**. Vẫn tại `wifi_csi_rx/`, mở lại menuconfig,
đổi **CSI receiver → RX node ID = 2**, giữ nguyên các thông số chung rồi lưu:

```bash
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM2 flash monitor
```

Trên log cần thấy `RX2 filter TX=...`. **Mỗi lần đổi node ID phải build lại
trước khi flash.** Thư mục `build/` dùng chung và chứa kết quả của lần build
gần nhất. Khi nạp lại RX1, đổi ID về **1** rồi build/nạp lại; nếu nạp binary RX2
vào RX1 thì dữ liệu của cả hai board sẽ có cùng ID.

## 6. Các API CSI đang sử dụng

Đối chiếu với ESP-IDF v6.0.2:

```c
wifi_csi_config_t csi_cfg = {
    .lltf_en = false,
    .htltf_en = true,
    .stbc_htltf2_en = false,
    .ltf_merge_en = false,
    .channel_filter_en = false,
    .manu_scale = false,
    .shift = 0,
};
esp_wifi_set_csi_config(&csi_cfg);
esp_wifi_set_csi_rx_cb(wifi_csi_cb, NULL);
esp_wifi_set_csi(true);
```

Cấu hình `CONFIG_ESP_WIFI_CSI_ENABLED=y` được đặt trong `sdkconfig.defaults` của project RX. `wifi_csi_cb` chạy trong Wi-Fi task và chỉ sao chép dữ liệu vào queue. Firmware giới hạn 512 byte CSI I/Q mỗi bản ghi (nếu lớn hơn thì bỏ). Giới hạn này phải được kiểm thử với các gói PHY thực tế của bạn.

## 7. Định dạng UDP

**WCS2** (CSI profile 1): header 40 byte + 128 byte HT-LTF I/Q raw, mỗi cặp theo thứ tự **imaginary, real**. Header chứa metadata cũ và profile, sig_mode, cwb, mcs, stbc, secondary_channel, sgi, timestamp driver. RX chỉ nhận HT20/MCS0/long GI không STBC/secondary channel.

Xem encoder trong [`main/protocol.h`](main/protocol.h) và [định dạng CSV của collector](../host/README.md). Collector giữ khả năng đọc WCS1 cũ; repo hiện chưa có công cụ chọn 52 sóng mang hoặc xuất mẫu MAT.

**WTX1** (TX_EVENT): 34 byte; gồm `node_id`, `channel`, `RSSI`, `tx_seq`, `tx_local_us`, `rx_local_us`, MAC TX.

Đây là định dạng **riêng của đồ án**, không tương thích trực tiếp với ADR-018 của RuView. `csi_seq` của RX1 và RX2 **không cùng hệ đếm**. `WTX1` và `WCS2` có thể đến không đủ và không theo một tỷ lệ 1:1; không tự động nối chúng chỉ bằng `seq`.

Xem ví dụ giải mã tại [`../host/README.md`](../host/README.md).

## 8. Quy trình đo kiểm

1. Chỉ bật **TX + RX1** trước. Chạy UDP collector trên Ubuntu.
2. Xác nhận có cả `TX_EVENT` và `CSI` từ RX1; nguồn MAC phải khớp TX.
3. Bật RX2; Ubuntu phải có `node_id = 1` **và** `node_id = 2`.
4. Quan sát dữ liệu I/Q không rỗng, thay đổi khi người đi trong vùng TX–RX.
5. Kiểm thử chạy liên tục 10 phút, đọc `q_drop`, `send_fail` trong serial và đếm CSI/giây trên Ubuntu.
6. Chưa có chứng cứ đồng bộ từng mẫu giữa hai RX; dùng timestamp host chỉ để căn chỉnh sơ bộ.

Nếu chỉ có `TX_EVENT` mà không có `CSI`, **chưa đạt mục tiêu dữ liệu**. Điều tra promiscuous filter, API CSI, channel và HT frame trên ESP32-S3; không tiến hành huấn luyện AI bằng sự kiện `WTX1` thay cho CSI.

## 9. Sự cố thường gặp

| Biểu hiện | Hướng kiểm tra |
|---|---|
| `APP_TX_MAC` chưa hợp lệ | Nạp TX trước, nhập chính xác STA MAC trong `idf.py menuconfig`, build và nạp lại RX. |
| `WIFI_BW_HT20` undefined | V6 đã chuyển sang `WIFI_BW20`; đảm bảo không chạy nhầm file v1. |
| `esp_now` component not found | Bản v2 dùng API từ `esp_wifi` và không khai báo `esp_now` là component độc lập. |
| Không có UDP trên Ubuntu | Kiểm tra `APP_SERVER_IP`, firewall UDP 5005, IP subnet, Client Isolation. |
| Có `WTX1`, không có `WCS2` | Kiểm tra CSI callback và frame HT20 thực; ESP-NOW received không bảo đảm CSI. |
| CSI rất chậm/mất mẫu | Xem `APP_MIN_CSI_INTERVAL_MS`, queue drop, nhiễu kênh, tải router và log TX. |
| Hai board cùng node ID | Đổi `RX node ID` cho đúng board, build và nạp lại. |

Nếu log lặp `Disconnected: reason=...`, xem mã lý do trước khi kiểm tra UDP:

| Mã reason | Ý nghĩa và hướng kiểm tra |
|---|---|
| `201` | Không tìm thấy AP; kiểm tra SSID, Wi-Fi 2.4 GHz, khoảng cách và trạng thái router. |
| `202` | Xác thực thất bại; kiểm tra mật khẩu và thiết lập bảo mật của AP. |
| `15` hoặc `204` | Hết thời gian bắt tay; kiểm tra mật khẩu, tín hiệu và khả năng tương thích bảo mật. |
| `210`, `211` hoặc `212` | AP không đáp ứng điều kiện bảo mật hoặc ngưỡng tín hiệu của cấu hình STA. |

`RX1 filter TX=...` chỉ xác nhận khởi tạo bộ thu. Cần thấy `Got IP: ...` và
`Wi-Fi ready on channel ...` trước khi firmware nhận dữ liệu để gửi UDP.
`main_task: Returned from app_main()` là bình thường: callback Wi-Fi và
task `udp_worker` tiếp tục chạy.

**Tiếp theo:** [`Ubuntu UDP Collector`](../host/README.md).

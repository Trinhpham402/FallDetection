# Ubuntu UDP Collector — Thu thập CSI từ RX1/RX2

**Mục tiêu:** chạy một UDP server trên Ubuntu để nhận và lưu các gói **WCS2** (HT-LTF I/Q + metadata PHY), **WCS1** cũ (CSI I/Q) và **WTX1** (sự kiện nhận probe TX) của hai RX. Thành phần này chạy với Python 3.10+ và **không phụ thuộc phiên bản ESP-IDF trên Ubuntu**; ESP-IDF v6.0.2 chỉ dùng để build firmware trên ESP32-S3.

Collector **không thực hiện AI**, không tái tạo chính xác từng cặp mẫu CSI của RX1 và RX2, không phải hệ thống cảnh báo y tế.

## 1. Các file

```text
host/
├── README.md            # tài liệu này
├── collector.py         # UDP server, parser WCS2/WCS1/WTX1, ghi dat + CSV
├── check_capture.py     # kiểm tra file .dat đã thu
├── export_esp_fi.py     # xuất một trial WCS2 thành CSIamp (950,52)
├── ESP_FI_CAPTURE.md    # quy trình thu/gắn nhãn/xuất MAT
└── tests/              # giao thức, export và UDP; test_host.py   # kiểm thử giao thức, file và UDP loopback
```

- `collector.py`: nhận UDP tại một cổng chung, giải mã header, ghi toàn bộ datagram hợp lệ vào `.dat`; ghi metadata và mảng I/Q có dấu trong cột `data` vào `.csv`.
- `check_capture.py`: đọc `.dat` để thống kê số CSI và TX_EVENT, tốc độ ghi nhận/giây từng RX, MAC nguồn và giá trị biên độ CSI thô.

Quy trình mới: [thu 100 Hz, gắn nhãn và xuất MAT cho ESP-Fi-HAR](ESP_FI_CAPTURE.md). Dùng prefix capture mới vì CSV đã thêm cột PHY và `data`; không append vào header cũ.

## 2. Chuẩn bị máy Ubuntu

Kết nối Ubuntu cùng LAN/router với RX1/RX2. Đảm bảo router cho phép thiết bị Wi-Fi gửi UDP đến máy Ubuntu.

```bash
python3 --version
ip -4 addr
```

Ghi lại IPv4 của Ubuntu, ví dụ `192.168.1.100` (IP minh họa). Tại project `wifi_csi_rx/`, chạy `idf.py menuconfig`, nhập IP này vào **CSI receiver → Collector IPv4** (`APP_SERVER_IP`), rồi build và nạp lần lượt RX1/RX2 với node ID tương ứng. Nên dùng DHCP reservation hoặc IP tĩnh để IP không thay đổi trong quá trình thu.

Kiểm tra cổng UDP 5005 có được sử dụng hay chưa:

```bash
ss -lun | grep ':5005' || true
```

Nếu Ubuntu bật UFW (tùy môi trường), cho phép port và kiểm tra trạng thái:

```bash
sudo ufw allow 5005/udp
sudo ufw status
```

**Lưu ý:** `--bind 0.0.0.0` nghĩa là server lắng nghe trên tất cả IPv4 interface, **không phải** địa chỉ mà RX gửi tới. RX phải dùng IP thật của Ubuntu (được cấu hình qua `APP_SERVER_IP`). Hạn chế dùng trên mạng công cộng vì dữ liệu chưa mã hóa.

## 3. Chạy collector

Từ **thư mục gốc** dự án:

```bash
mkdir -p captures
python3 host/collector.py --bind 0.0.0.0 --port 5005 --out captures/test01
```

Hoặc chỉ lắng nghe trên một IPv4 cụ thể của Ubuntu:

```bash
python3 host/collector.py --bind 192.168.1.100 --port 5005 --out captures/test02
```

Nên **khởi động collector trước RX1/RX2** để không bỏ mất các gói thử nghiệm đầu tiên.

Collector sẽ hiển thị dòng dạng:

```text
Listening UDP 0.0.0.0:5005; writing captures/test01.dat and captures/test01.csv
Stats: {1: {'CSI': 150, 'TX_EVENT': 180, 'tx_gaps': 0},
        2: {'CSI': 140, 'TX_EVENT': 178, 'tx_gaps': 2}}
```

Các con số ở trên chỉ là **minh họa**, không phải kết quả đo phần cứng. Mỗi 5 giây chương trình xuất số lượng bản ghi lũy kế. Dừng an toàn bằng `Ctrl+C` để các file được flush và đóng.

Thống kê vẫn xuất khi chưa nhận dữ liệu, kèm `invalid` là số datagram bị từ chối. `tx_gaps` đếm khoảng nhảy sequence TX quan sát được riêng cho từng RX/MAC, hỗ trợ vòng uint32 và đặt lại mốc khi timestamp lùi. Đây là ước lượng: đảo thứ tự UDP, thiết bị khởi động lại hoặc gói đến muộn có thể làm sai số; không phải phép đo chính xác số probe bị mất. Bộ đếm chỉ tính lần chạy collector hiện tại.

Parser kiểm tra độ dài, node ID 1/2, kênh 1–13, flags và byte reserved theo firmware RX. Datagram lỗi không được ghi vào file. File được flush mỗi 5 giây và đóng khi Ctrl+C; hai file không được ghi theo giao dịch nguyên tử, nên sự cố mất điện/ghi đĩa có thể khiến số dòng CSV và bản ghi DAT khác nhau. Chỉ chạy một collector ghi vào một tiền tố file.

**Chú ý:** nếu chạy lại với **cùng `--out`**, collector sẽ **append** vào file cũ. Để đo một phiên độc lập, chọn tiền tố file mới (ví dụ `captures/session_20261024_01`).

## 4. Kết quả đầu ra

Khi dùng `--out captures/test01` sẽ có:

```text
captures/test01.dat
captures/test01.csv
```

**`test01.dat`** ghi theo format lặp: `uint32 little-endian chiều dài datagram` + toàn bộ datagram. Giữ dữ liệu CSI I/Q để xử lý lại sau này.

**`test01.csv`** có các cột:

| Cột | Nội dung |
|---|---|
| `recv_utc` | thời gian nhận trên Ubuntu dạng UTC |
| `host_monotonic_ns` | monotonic clock của Ubuntu (ns) |
| `sender_ip` | IP của ESP32-S3 RX đã gửi UDP |
| `kind` | `CSI` hoặc `TX_EVENT` |
| `node_id` | `1` = RX1, `2` = RX2 |
| `channel` | Wi-Fi channel |
| `rssi`, `noise` | metadata PHY khi có |
| `flags` | bit 0: 4 byte CSI đầu không hợp lệ |
| `csi_seq` | số thứ tự CSI cục bộ trên từng RX; **chỉ có ở CSI** |
| `tx_seq` | thứ tự probe TX; **chỉ có ở TX_EVENT** |
| `rx_local_us` | `esp_timer_get_time()` trên RX, **không đồng bộ giữa RX1/RX2** |
| `tx_local_us` | timestamp từ TX, chỉ có ở TX_EVENT |
| `tx_mac` | MAC nguồn phát TX |
| `iq_len` | số byte dữ liệu CSI I/Q; `0` ở TX_EVENT |
| `profile`, `sig_mode`, `cwb`, `mcs`, `stbc`, `secondary_channel`, `sgi`, `rx_hw_us` | metadata WCS2; trống với WCS1/TX_EVENT |
| `data` | mảng signed int8 Q,I `[ ... ]`; trống ở TX_EVENT |

**Không** dùng `csi_seq` của RX1 ghép trực tiếp với `csi_seq` RX2 hoặc `tx_seq` của `WTX1`.

## 5. Kiểm tra file thu

Dừng collector trước khi phân tích; từ thư mục gốc chạy:

```bash
python3 host/check_capture.py captures/test01.dat
```

Kết quả minh họa:

```text
Capture: captures/test01.dat  bad=0
  RX1: CSI=250, TX_EVENT=260, source_MAC=[('24:6F:28:AA:BB:CC', 510)]
    CSI: measured mean throughput ~18.75 records/s
    TX_EVENT: measured mean throughput ~19.90 records/s
    CSI mean |H|: mean=32.13, range=20.25..44.20 (uncalibrated)
  RX2: CSI=245, TX_EVENT=258, ...
```

Các số ở trên **không phải kết quả thực nghiệm**. Mục tiêu là cả hai RX xuất hiện và có **CSI > 0**, MAC trùng MAC TX cấu hình, độ dài I/Q hợp lệ và mẫu thay đổi khi người chuyển động.

Lưu ý: `check_capture.py` tính tốc độ trung bình dựa trên timestamp cục bộ của từng RX. Nếu file chứa nhiều lần khởi động lại thiết bị hoặc nhiều phiên append, chỉ số tốc độ có thể không chính xác.

Tốc độ được tính riêng từng loại bản ghi theo `(số bản ghi - 1) / khoảng timestamp`. Nếu timestamp lùi hoặc không đủ khoảng thời gian, công cụ báo không thể tính tốc độ. Biên độ báo cáo là trung bình của biên độ trung bình từng bản ghi CSI có I/Q sử dụng được, chưa hiệu chuẩn.

Công cụ đọc tuần tự, đếm `bad` khi gói lỗi và trả exit code 1 nếu có lỗi. Với bản ghi có chiều dài hợp lệ nhưng nội dung sai, công cụ tiếp tục sang bản ghi sau. Nếu prefix chiều dài hỏng, vượt 552 byte hoặc file bị cắt dở, công cụ dừng vì không thể xác định ranh giới bản ghi tiếp theo an toàn.

## 6. Giải mã CSI I/Q trong Python

```python
from pathlib import Path
import struct
import sys
sys.path.insert(0, 'host')
from collector import parse_datagram, iq_to_complex

with Path('captures/test01.dat').open('rb') as f:
    size = struct.unpack('<I', f.read(4))[0]
    packet = parse_datagram(f.read(size))
    if packet.kind == 'CSI':
        complex_iq = iq_to_complex(packet)
        print(packet.node_id, packet.tx_mac, complex_iq[:5])
```

Đây chỉ là ví dụ lấy **bản ghi đầu tiên**. Nếu bản ghi đầu là TX_EVENT thì không có I/Q; cần lặp đến khi gặp `kind == 'CSI'`.

Ở `WCS1`, CSI I/Q được giữ nguyên dưới dạng byte `int8` **imaginary, real** trong `packet.iq` và file DAT. Nếu `flags & 1` thì `iq_to_complex()` bỏ hai cặp phức đầu. Chưa có xử lý hiệu chuẩn theo AGC/RSSI hoặc ánh xạ chính xác vị trí subcarrier theo kiểu LTF/PHY.

## 7. Kiểm tra mạng và xử lý lỗi

| Hiện tượng | Cách kiểm tra |
|---|---|
| Stats rỗng, không có dữ liệu | Kiểm tra RX kết nối Wi-Fi, IP server, port 5005, firewall, AP isolation. |
| RX báo gửi UDP nhưng Ubuntu không nhận | Thử `sudo tcpdump -ni any udp port 5005` nếu đã cài tcpdump. |
| Chỉ có `node_id=1` | Kiểm tra RX2 dùng binary riêng và `node_id=2`. |
| Có `TX_EVENT` nhưng `CSI=0` | ESP-NOW đã tới RX, nhưng CSI pipeline chưa hoạt động; đọc log `wifi_csi_cb`. |
| `Ignore invalid UDP` | Kiểm tra magic WCS2/WCS1/WTX1; không dùng parser ADR-018 trực tiếp. |
| `Permission denied` khi ghi captures | Kiểm tra quyền ghi thư mục, `pwd`, dung lượng đĩa. |
| `Address already in use` | Collector khác đang lắng nghe cùng IP:port; tìm bằng `ss -lunp`. |

## 8. Kiểm thử tự động

```bash
python3 -m unittest discover -s host/tests -v
python3 -m py_compile host/collector.py host/check_capture.py host/export_esp_fi.py
```

Test kiểm tra byte mẫu từ firmware RX, I/Q có dấu, gói lỗi, append DAT/CSV, file bị cắt dở, thống kê và nhận UDP loopback rồi dừng bằng SIGINT. Test UDP cần môi trường cho phép tạo socket loopback. Các test **không thay thế việc đo CSI trên phần cứng**.

## 9. Bảo mật và giới hạn

- UDP CSI và ESP-NOW broadcast **không mã hóa**. Không truyền qua Internet, không chèn tên người, dữ liệu sức khỏe hoặc bí mật vào payload.
- Timestamp TX, RX1 và RX2 không chung mốc; timestamp Ubuntu bao gồm jitter mạng.
- CSI I/Q chỉ có thể dùng làm dataset sau khi chứng minh nguồn TX và tốc độ thu phù hợp.
- Chưa có AI phát hiện té ngã, chưa có cảnh báo an toàn sinh mạng.

**Tài liệu liên quan:** [`TX`](../wifi_csi_tx/README.md) · [`RX`](../wifi_csi_rx/README.md) · [`Tổng quan dự án`](../README.md).

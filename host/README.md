# Ubuntu UDP Collector — Thu thập CSI từ RX1/RX2

Trước mắt, tập trung thu thập dữ liệu CSI từ hai bộ thu ESP32-S3 về máy Ubuntu. Mỗi lần thu có thời gian đếm ngược do người dùng nhập, sau đó ghi dữ liệu trong **17 giây**, với tốc độ mục tiêu **50 gói CSI/giây cho mỗi RX**.

`collector.py` chạy trên Ubuntu với **Python 3.10+**, chỉ dùng thư viện chuẩn. Chương trình ghi CSV chứa CSI, không tạo file `.dat`. Các script checker/exporter không nằm trong phạm vi bước thu dữ liệu này.

## Cách chạy

Từ thư mục gốc `firmware/`:

```bash
python3 host/collector.py --out captures/trial01
```

Chương trình mở UDP `0.0.0.0:5005`, hỏi số giây đếm ngược rồi thu 17 giây. Nhập `0` để bắt đầu ngay. Kết quả được lưu tại `captures/trial01.csv`.

Có thể truyền số giây đếm ngược trực tiếp để chạy không tương tác:

```bash
python3 host/collector.py --bind 0.0.0.0 --port 5005 \
  --out captures/trial02.csv --countdown 5
```

- Bỏ `--out` để dùng tên mặc định `captures/trial_YYYYMMDD_HHMMSS.csv`.
- File đã tồn tại sẽ bị từ chối, không ghi đè hoặc ghi nối.
- Trong lúc thu, số CSI mỗi RX được in và file được flush khoảng mỗi giây.
- Nhấn **Ctrl+C** trong khi ghi để dừng sớm và đóng file, giữ phần đã thu. Nhấn khi đang nhập/đếm ngược để hủy trước khi tạo file.
- Phiên đủ thời gian có exit code `0`; dừng/hủy bằng Ctrl+C có exit code `130`; lỗi cấu hình, mạng hoặc file có exit code `1` (đối số CLI không hợp lệ: `2`).
- Tốc độ 50 CSI/giây là mục tiêu theo cấu hình TX; collector không tự bỏ bớt mẫu hoặc nội suy để đạt con số này.

## 1. Quy trình thu dữ liệu

1. **Mở cổng UDP**, mặc định `5005`, chờ RX1/RX2 gửi gói tới.
2. **Phân biệt loại gói**: `WCS2`/`WCS1` chứa CSI; `WTX1` là sự kiện RX nhận probe từ TX.
3. **Kiểm tra cấu trúc gói** theo từng giao thức. Loại gói không hợp lệ, không ghi chúng vào dữ liệu thu.
4. **Giữ nguyên dữ liệu I/Q thô và ghi đúng 6 cột CSV**: `timestamp`, `csi_seq`, `node_id`, `mac`, `len`, `buf`. **Không ghi gói `WTX1` vào CSV.**
5. **In số lượng CSI đã ghi của từng RX**, tách riêng RX1 và RX2; không cộng `WTX1` vào số lượng CSI.
6. **Cho người dùng nhập số giây đếm ngược**. Hiển thị thời gian còn lại và chỉ bắt đầu ghi dữ liệu khi đếm ngược kết thúc. Dữ liệu nhận trước thời điểm bắt đầu không được đưa vào phiên thu.
7. **Mỗi lần thu chỉ ghi trong 17 giây**, sau đó tự động dừng, lưu và đóng file. Tốc độ mục tiêu là **50 gói CSI/giây cho mỗi RX**.

## 2. Trình tự một lần thu

```text
Mở UDP 5005 và chờ dữ liệu RX1/RX2
                  ↓
Người dùng nhập số giây đếm ngược
                  ↓
Đếm ngược — chưa ghi dữ liệu của phiên thu
                  ↓
Bắt đầu ghi CSI vào CSV và đếm riêng từng RX
                  ↓
Ghi trong 17 giây
                  ↓
Tự dừng, đóng file và in kết quả RX1/RX2
```

Trong thời gian chờ và đếm ngược, chương trình cần tiếp tục nhận và bỏ dữ liệu cũ để không ghi lại các gói tồn đọng khi bắt đầu phiên thu. Mốc bắt đầu và kết thúc phiên được tính theo đồng hồ monotonic trên Ubuntu; timestamp cục bộ của RX vẫn được giữ trong dữ liệu.

Ví dụ giao diện:

```text
Listening UDP 0.0.0.0:5005
Nhập số giây đếm ngược: 5
Bắt đầu sau: 5 ... 4 ... 3 ... 2 ... 1
Đang ghi CSI trong 17 giây...
RX1: ... CSI | RX2: ... CSI
Hoàn tất. Đã đóng file CSV.
```

Các dấu `...` biểu thị số liệu phụ thuộc phiên thu, không phải kết quả đo phần cứng.

## 3. Dữ liệu CSV

Mỗi dòng CSV tương ứng với **một gói CSI hợp lệ được ghi trong cửa sổ 17 giây**. CSV không chứa dòng sự kiện `WTX1`.

| Cột | Nội dung |
|---|---|
| `timestamp` | Timestamp cục bộ của RX (`rx_local_us`), đơn vị microsecond |
| `csi_seq` | Sequence CSI uint32 do RX cung cấp; cục bộ từng RX, có thể quay vòng và reset khi RX khởi động lại |
| `node_id` | `1` cho RX1, `2` cho RX2 |
| `mac` | MAC nguồn TX, không phải MAC của RX |
| `len` | Số byte I/Q, không bao gồm header; WCS2 hiện tại là `128` |
| `buf` | Mảng JSON chứa toàn bộ số nguyên có dấu theo thứ tự `[Q0,I0,Q1,I1,...]` |

Header CSV luôn là:

```text
timestamp,csi_seq,node_id,mac,len,buf
```

Giữ nguyên giá trị I/Q trong cột `buf`, chưa chuyển thành biên độ, chuẩn hóa hoặc nội suy. Theo định dạng ESP32 hiện tại, mỗi cặp được lưu Q trước, I sau; `len=128` tương ứng 64 cặp Q/I. Trường `buf` được CSV tự đặt trong dấu ngoặc kép vì chứa dấu phẩy.

Parser vẫn kiểm tra metadata PHY và cờ hợp lệ nhưng không xuất thêm cột. WCS2 yêu cầu profile 1, I/Q 128 byte, HT20/MCS0/long GI, không STBC hoặc secondary channel. CSI có cờ invalid đầu vẫn giữ nguyên buffer và được đếm ở terminal; CSV 6 cột không lưu cờ này để xác định lại từng dòng sau đó.

`timestamp` không phải thời gian UTC và không đồng bộ giữa RX1/RX2. Đồng hồ monotonic trên Ubuntu chỉ dùng nội bộ để điều khiển cửa sổ thu 17 giây.

## 4. Thời lượng và tốc độ thu

**17 giây là thời lượng; 50 gói CSI/giây là tốc độ mục tiêu. Đây là hai thông số độc lập.**

| Thông số | Mục tiêu |
|---|---|
| Thời gian ghi | 17 giây, không bao gồm đếm ngược |
| Tốc độ CSI mỗi RX | 50 gói/giây |
| Số mẫu dự kiến mỗi RX | Khoảng `17 × 50 = 850` gói CSI |
| Tổng hai RX | Khoảng 1.700 dòng CSI nếu cả hai đạt tốc độ mục tiêu |

Số mẫu thực tế có thể khác mục tiêu vì tốc độ phát hoặc mất gói. Không thêm mẫu giả hay kéo dài phiên để bù cho đủ 850 mẫu. Kết thúc phiên, chương trình báo số CSI đã ghi và tốc độ trung bình riêng từng RX (`số CSI đã ghi / 17 giây`). Nếu dừng sớm, mẫu số là thời lượng đã ghi. Không có RX hoặc chỉ có WTX1 vẫn kết thúc đúng hạn và tạo CSV chỉ có header.

Để hướng tới 50 probe/giây, cần cấu hình TX với `APP_TX_INTERVAL_MS=20` ms rồi build/flash lại. Cấu hình mặc định TX hiện tại là 10 ms, tương ứng mục tiêu 100 probe/giây. Tốc độ phát probe không bảo đảm tốc độ CSI thực nhận được; cần đo trên từng RX. Thay đổi README không thay đổi cấu hình firmware.

## 5. Kiểm thử phần mềm

```bash
python3 -m unittest discover -s host/tests -v
python3 -m py_compile host/collector.py
```

Test kiểm tra WCS1/WCS2/WTX1, I/Q có dấu, gói lỗi, đúng 6 cột CSV và ánh xạ timestamp/sequence/MAC/buffer, bảo vệ file cũ, loại dữ liệu trước phiên thu, Ctrl+C và nhận UDP thật trong một phiên đủ 17 giây. Test đối chiếu encoder firmware cần `cc`; test UDP cần quyền tạo socket loopback. Kết quả kiểm thử không thay thế việc đo CSI trên ESP32 thật.

## 6. Chuẩn bị và lưu ý

- Ubuntu và RX1/RX2 cùng LAN; RX gửi tới IPv4 thật của Ubuntu và cổng UDP `5005`.
- `0.0.0.0` chỉ là địa chỉ lắng nghe trên Ubuntu, không phải IP đích để cấu hình RX.
- RX1/RX2 dùng node ID riêng `1` và `2`; TX/RX/router cùng kênh Wi-Fi 2.4 GHz.
- Mỗi lần thu dùng tên file mới để tách biệt các phiên và tránh ghi đè hoặc ghi nối dữ liệu.
- Sequence và timestamp cục bộ của RX1/RX2 không đồng bộ; không ghép mẫu chỉ bằng việc so hai giá trị này.
- `WTX1` không chứa CSI, không được dùng thay cho mẫu CSI hoặc cộng vào tốc độ CSI.
- Giai đoạn này chỉ thu dữ liệu, chưa huấn luyện hoặc suy luận AI.

**Tài liệu liên quan:** [Firmware TX](../wifi_csi_tx/README.md) · [Firmware RX](../wifi_csi_rx/README.md) · [Tổng quan dự án](../README.md).

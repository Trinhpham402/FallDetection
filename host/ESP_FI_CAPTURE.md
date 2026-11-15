# Thu dữ liệu theo đầu vào ESP-Fi-HAR

Cấu hình triển khai: TX ESP32-S3 phát ESP-NOW HT20/MCS0/long GI với chu kỳ
10 ms (mục tiêu 100 probe/s). RX giữ riêng HT-LTF, tắt LLTF, STBC-LTF,
LTF merge và channel filter; tự động scale của driver vẫn bật. Không throttle
CSI (`APP_MIN_CSI_INTERVAL_MS=0`), queue 128 gói. Đo tốc độ thực trên từng RX.

Đây là quy ước thu **của dự án** để xuất `CSIamp` kích thước `(950,52)` cho
[loader ESP-Fi-HAR](https://github.com/AutoSmartGroup/ESP-Fi-HAR/blob/main/Model%20Code/dataset.py).
Repo gốc chưa xác nhận đầy đủ sampling rate, thứ tự 52 cột và preprocessing.
Không coi định dạng giống nhau là bằng chứng mô hình sẽ hoạt động tương đương.
Trong manifest, hai cờ xác minh tương đương upstream vẫn là `false`.

## Cấu hình và nạp

TX/RX/router phải cùng kênh cố định, 2.4 GHz, 20 MHz, không có secondary channel.
Kênh 11 dùng được nếu **cả ba** cùng cấu hình kênh 11; mặc định project là 6.
Giữ Wi-Fi, MAC TX, IP Ubuntu và node ID phù hợp phần cứng của bạn.

| Project | Thiết lập |
|---|---|
| TX | `APP_TX_INTERVAL_MS=10`, FreeRTOS 1000 Hz |
| RX | `APP_MIN_CSI_INTERVAL_MS=0`, `APP_QUEUE_DEPTH=128` |
| RX1/RX2 | `APP_RX_NODE_ID=1` / `2` |

Các giá trị app trong `sdkconfig` local tại thời điểm cập nhật đã được chỉnh.
`sdkconfig.defaults` và Kconfig áp dụng cho cấu hình mới; khi dùng một cấu hình
local cũ khác, kiểm tra lại các giá trị trên bằng `idf.py menuconfig`.

Nạp môi trường ESP-IDF v6.0.2, chạy `idf.py build` tại từng project TX/RX,
rồi flash đúng board. Không dùng `set-target` để chuyển RX1/RX2. Dừng monitor,
đổi node ID trong menuconfig, build và flash lại cho board còn lại.

## Giao thức CSI mới

RX mới gửi `WCS2`: header **40 byte** + **128 byte I/Q**. `WTX1` không đổi.
Collector mới đọc được cả WCS2 và WCS1 cũ. Exporter chỉ nhận WCS2 profile 1;
WCS1 không có đủ metadata để xác nhận layout và không được tự chuyển đổi.

| Offset | Nội dung |
|---|---|
| 0–3 | `WCS2` |
| 4–9 | node, channel, RSSI signed, noise signed, flags, profile=1 |
| 10–15 | I/Q byte length u16=128; CSI sequence u32 |
| 16–23 | RX local time u64, microsecond |
| 24–29 | MAC TX |
| 30–35 | sig_mode=1, cwb=0, mcs=0, stbc=0, secondary_channel=0, sgi=0 |
| 36–39 | driver RX timestamp u32, microsecond (có wrap; không dùng để đồng bộ RX) |
| 40–167 | 64 cặp signed int8, thứ tự Q rồi I |

Số nguyên nhiều byte dùng little endian. Profile 1 được firmware xác định bằng
cấu hình chỉ HT-LTF và lọc PHY; không được tự sửa `profile` trên bản ghi cũ.
Nếu `flags & 1`, 4 byte đầu không hợp lệ; exporter từ chối bản ghi vì sóng mang
`+1` cần dùng nằm trong phần này. Không dịch toàn bộ chỉ số khi bỏ byte lỗi.

Theo bảng CSI của ESP-IDF cho ESP32-S3 HT20, thứ tự bộ đệm HT-LTF là
`0..31,-32..-1`. Chọn các chỉ số `-28..-1,+1..+28`, bỏ bốn pilot
`-21,-7,+7,+21`: còn **52 data carriers**, xếp theo tần số có dấu tăng dần.
Ánh xạ chỉ số k vào cặp số phức là `k % 64`. Biên độ = `sqrt(Q²+I²)`.
Đây là ánh xạ vật lý có khai báo, chưa xác nhận là ánh xạ tác giả dataset dùng.

Nguồn đối chiếu: ESP-IDF cài tại
`~/.espressif/v6.0.2/esp-idf/docs/en/api-guides/wifi-driver/wifi-vendor-features.rst`
(phần Wi-Fi Channel State Information) và
[hướng dẫn CSI Espressif](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/wifi-driver/wifi-vendor-features.html#wi-fi-channel-state-information).

## Thu một trial có nhãn

Các lệnh bên dưới chạy từ `FallDetectionFirmware/firmware/`.
Mỗi file capture nên là một trial có lịch thực hiện hoạt động rõ ràng. Ghi lại
người, phòng, lần thử và khoảng thời gian chứa hoạt động. Nếu capture có đoạn
chuẩn bị, chọn đúng `--start-us`; không gắn cùng một nhãn cho cả phiên nhiều
hoạt động. `--label` là nhãn người thu cung cấp, không phải dự đoán AI.

```bash
python3 host/collector.py --bind 0.0.0.0 --port 5005 --out captures/har_trial01
# Thu ít nhất 10 giây ở đoạn hoạt động đã xác định, rồi Ctrl+C.
python3 host/check_capture.py captures/har_trial01.dat
```

Chọn prefix mới vì CSV đã thêm metadata PHY và cột `data` chứa mảng Q/I `[...]`.
Không append vào CSV có header cũ. File DAT vẫn giữ nguyên các datagram nhận được.

Kiểm tra riêng mỗi RX:

- Có CSI thực, profile `{1: ...}`, `iq_bytes={128: ...}`, `first_word_invalid=0`.
- CSI throughput gần 100 bản ghi/giây. `TX_EVENT` là loại riêng, không cộng vào CSI.
- Khoảng ngắt lớn nhất cần <=30 ms trong cửa sổ được chọn; `bad=0`.
- MAC/kênh đúng cấu hình. Trên RX, `q_drop`, `send_fail` không tăng liên tục.

`sent` trong serial là tổng datagram gửi thành công (CSI + TX_EVENT), vì vậy
khoảng 200 gói/s không có nghĩa là 200 CSI/s. Một lỗi gửi ban đầu không chứng minh
toàn bộ phiên bị hỏng; cần kiểm tra khoảng ngắt và sequence trong cửa sổ thực dùng.

## Xuất một mẫu MAT

Ví dụ xuất hoạt động đi bộ của người 2 tại phòng local 1, trial 1, RX1:

```bash
python3 host/export_esp_fi.py captures/har_trial01.dat \
  --out datasets/local --node 1 --label walk \
  --subject 2 --scenario 1 --trial 1 --split train_amp
```

Kết quả:

```text
datasets/local/rx1/train_amp/walk/1-2-2-1.mat
datasets/local/rx1/train_amp/walk/1-2-2-1.json
```

MAT chứa `CSIamp` float64 `(950,52)`, chưa Z-score. Loader upstream chuẩn hóa
toàn bộ mẫu bằng `(x-mean)/(std+1e-8)` rồi thêm trục thành `(1,950,52)`.
JSON lưu mapping, tốc độ thu thực, khoảng ngắt, nguồn file và nhãn.

Exporter lấy 950 điểm lưới 100 Hz, span từ điểm đầu đến cuối **9,49 giây**
(cửa sổ danh nghĩa khoảng 9,5 giây). Nội suy tuyến tính chỉ để hiệu chỉnh jitter:
không ngoại suy/padding, không đi qua khoảng ngắt >30 ms, tốc độ CSI native
phải >=90 Hz và tỷ lệ mất sequence <=10%. Không lấy dữ liệu cũ 20 Hz rồi
kéo giãn cho đủ 950 điểm. Clock/sequence lùi, đổi MAC/kênh hoặc thiếu dữ liệu
đều gây lỗi; chọn trial mới hoặc `--start-us TIMESTAMP_RX` của đoạn liên tục khác.

Đổi `--node 2` để xuất RX2 riêng. Hai clock RX không chung mốc; không dùng cùng
`--start-us` để khẳng định hai cửa sổ đã đồng bộ. Mỗi RX có dataset root riêng:
`datasets/local/rx1` hoặc `datasets/local/rx2`. Thu đủ dữ liệu thực ở hai split
trước khi chạy loader; việc tạo sẵn thư mục nhãn không tạo thêm mẫu dữ liệu.

Những lớp hiện hỗ trợ: `arm_wave, fall, jump, run, squat, turn, walk`.
Filename ID theo bản ZIP đã audit: run=1, walk=2, jump=3, squat=4,
arm_wave=5, turn=6, fall=7. Bảng này mâu thuẫn với README upstream; loader
lấy nhãn theo thư mục, không theo mã filename. Manifest giữ danh sách lớp và
nguồn mapping. Không tự suy ra ngữ nghĩa nhãn upstream từ mã filename.

Giữ người/phiên test độc lập với train và validation; exporter không tự chia tập
và không kiểm chứng danh tính người. Không đặt cùng một người vào cả hai split
nếu mục tiêu là đánh giá trên người chưa thấy. Thêm đứng yên/ngồi/nằm vào protocol
đánh giá thực tế sau khi thử mô hình 7 lớp; hiện exporter này bám danh sách lớp upstream.

## Kiểm thử

```bash
python3 -B -m unittest discover -s host/tests -v
python3 -m py_compile host/collector.py host/check_capture.py host/export_esp_fi.py
```

Test gồm đối chiếu byte từ encoder C thật với parser Python, mapping tần số,
CSV Q/I có dấu, từ chối PHY sai/gap/clock reset, tách RX và MAT column-major.
UDP loopback cần môi trường cho phép socket. Kiểm thử không thay thế việc nhận
WCS2 thật trên Ubuntu và kiểm chứng khả năng chuyển mô hình giữa hai nguồn dữ liệu.

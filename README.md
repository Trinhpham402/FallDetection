# FallDetection

Dự án nghiên cứu phát hiện té ngã bằng Wi-Fi CSI và AI trên ESP32-S3. Hệ thống hiện có firmware phát/thu và chương trình thu dữ liệu trên Ubuntu; phần ứng dụng và mô hình AI đang chờ phát triển.

Repo: [Trinhpham402/FallDetection](https://github.com/Trinhpham402/FallDetection).

## 1. Bắt đầu từ đâu?

1. Đọc cấu trúc và trạng thái dự án bên dưới.
2. Làm theo [hướng dẫn tham gia và sử dụng Git](CONTRIBUTING.md) để cấu hình máy, lấy mã nguồn và tạo nhánh làm việc.
3. Chạy kiểm thử host trước khi sửa mã; không cần board để bắt đầu phần này.
4. Nếu làm với ESP32-S3, đọc [hướng dẫn firmware](firmware/README.md), rồi cấu hình TX và RX.
5. Chọn một việc nhỏ, thống nhất phạm vi trong Issue và gửi Pull Request (PR) khi hoàn thành.

## 2. Cấu trúc dự án

```text
FallDetection/
├── README.md                  # Giới thiệu và lộ trình cho người mới
├── CONTRIBUTING.md            # Quy trình cộng tác và hướng dẫn Git
├── .gitignore                 # Quy tắc bỏ qua tệp cục bộ/tự sinh
├── firmware/
│   ├── README.md              # Thiết lập, build và thu CSI
│   ├── wifi_csi_tx/           # Firmware bộ phát ESP-NOW
│   ├── wifi_csi_rx/           # Firmware dùng chung cho RX1 và RX2
│   └── host/
│       ├── collector.py       # Thu dữ liệu UDP thành CSV
│       └── tests/             # Kiểm thử collector và giao thức
├── app/                       # Chưa có mã ứng dụng
│   └── .gitkeep
└── model/                     # Chưa có mã mô hình AI
    └── .gitkeep
```

`.gitignore` được đưa lên repo để cả nhóm dùng chung quy tắc loại trừ. `.gitkeep` là tệp rỗng theo quy ước để Git giữ thư mục rỗng; có thể xóa khi thư mục đã có mã nguồn.

## 3. Hệ thống hiện làm được gì?

```text
ESP32-S3 TX ── ESP-NOW ──> RX1 ── UDP ──┐
                    └──> RX2 ── UDP ────┴──> Ubuntu collector ──> CSV
```

- TX phát probe ESP-NOW; RX thu CSI và gửi về máy Ubuntu qua router Wi-Fi 2.4 GHz.
- Collector nhận `WCS2` và `WCS1`, chỉ lưu bản ghi CSI; bỏ qua sự kiện probe `WTX1`.
- Mỗi phiên thu có đếm ngược và ghi trong 17 giây. CSV gồm `timestamp`, `csi_seq`, `node_id`, `mac`, `len`, `buf`.
- Collector hiện không tạo `.dat`; repo chưa có `check_capture.py`, `export_esp_fi.py`, pipeline huấn luyện hay suy luận AI.

Collector hiển thị mục tiêu 50 CSI/giây/RX, trong khi mặc định TX là 10 ms/probe, tương đương mục tiêu phát 100 probe/giây. Đây là hai thông số hiện chưa thống nhất; cần thống nhất cấu hình và đo tốc độ CSI thực khi thu dữ liệu. Chương trình không tự nội suy hay giảm mẫu về 50 Hz.

Nhận được probe hoặc chạy kiểm thử thành công chưa chứng minh có CSI tốt trên phần cứng. Cần kiểm tra riêng dữ liệu RX1/RX2; timestamp và sequence của hai RX là cục bộ, chưa đồng bộ từng mẫu.

## 4. Thử phần host trước khi có board

Cần Python 3.10+ và trình biên dịch C (`cc`) để chạy đầy đủ kiểm thử. Collector chỉ dùng thư viện chuẩn Python.

Từ thư mục gốc `FallDetection/`:

```bash
python3 --version
python3 -m unittest discover -s firmware/host/tests -v
python3 firmware/host/collector.py --help
```

Kiểm thử có dùng UDP loopback, nên môi trường phải cho phép mở socket. Bài kiểm thử phiên thu đầy đủ chạy khoảng 17 giây; nếu thiếu `cc`, bài đối chiếu encoder C sẽ bị bỏ qua.

Để thu dữ liệu từ board, xem [hướng dẫn firmware](firmware/README.md) và [hướng dẫn collector](firmware/host/README.md).

## 5. Cùng phát triển

Nhóm dùng quy trình **Issue → nhánh riêng → commit → PR → review → merge vào `main`**. Mỗi PR tập trung vào một thay đổi có thể kiểm tra được. Hướng dẫn từng lệnh, xử lý xung đột và lỗi thường gặp nằm trong [CONTRIBUTING.md](CONTRIBUTING.md).

Giữ mật khẩu Wi-Fi trong `sdkconfig` cục bộ; không commit token, khóa riêng, dữ liệu capture, build hoặc môi trường Python. Khi cần chia sẻ dataset/checkpoint, thống nhất nơi lưu và mô tả phiên bản trong tài liệu thay vì tự thêm tệp lớn vào repo.

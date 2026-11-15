# Đánh giá ESP-Fi-HAR cho FallDetectionFirmware

Ngày kiểm tra: 2026-11-04. Nguồn: `/home/trinhpt/DATN_PTIT/dataset/ESP-Fi-HAR-main.zip`.

**Kết luận:** bản ZIP này phù hợp để xây dựng mô hình thử nghiệm nhận dạng hoạt động hoặc huấn luyện ban đầu cho phát hiện té ngã. Chưa phù hợp để đưa mô hình sang chạy trực tiếp với CSI hiện tại và khẳng định chất lượng phát hiện té ngã trong phòng của dự án. Cần giải quyết nhãn, ánh xạ sóng mang, thời gian lấy mẫu và đánh giá bằng dữ liệu tự thu.

## 1. Phạm vi kiểm tra

Đọc và kiểm tra CRC của mọi file trong ZIP; giải mã toàn bộ 560 file MAT bằng bộ đọc MATLAB v5 giới hạn đúng định dạng được quan sát (real float64, little-endian, không nén). Kiểm tra biến, kích thước, giá trị hữu hạn, dấu, mẫu/cột hằng, hash dữ liệu số, phân bố nhãn, người, môi trường và trial. Kiểm tra cú pháp tĩnh của 5 file Python, đọc loader và mã huấn luyện; không thực thi mã trong ZIP.

Không huấn luyện mạng neural và không đo accuracy, recall hay tỷ lệ cảnh báo nhầm. Kiểm tra số liệu không chứng minh được hành động thực tế bên trong mỗi mẫu, và hash chính xác không loại trừ các đoạn tín hiệu gần giống hoặc chồng lấn.

## 2. Dữ liệu thực có trong ZIP

| Hạng mục | Kết quả |
|---|---|
| File MAT đọc thành công | 560/560 |
| Biến trong mỗi MAT | Chỉ có `CSIamp` |
| Kiểu và kích thước | `float64`, `(950, 52)` |
| Tổng số giá trị | 27.664.000 |
| NaN / Inf / giá trị âm | 0 / 0 / 0 |
| Khoảng giá trị | 0 đến 181,01933598375618 |
| Giá trị bằng 0 | 5; không tự động coi đây là dữ liệu lỗi |
| Mẫu hằng / mẫu có cột hằng | 0 / 0 |
| Ma trận trùng hoàn toàn | 0; kể cả giữa train/test |
| Môi trường theo tên file | Chỉ mã `3` (README gọi là Meeting Room) |
| Người theo tên file | 1–8 |
| Train | 490 mẫu, người 2–8 |
| Test | 70 mẫu, người 1 |
| Từng hoạt động | 80 mẫu = 70 train + 10 test |

Bảy thư mục nhãn: `arm_wave`, `fall`, `jump`, `run`, `squat`, `turn`, `walk`. Mỗi người có 10 trial cho mỗi hoạt động trong môi trường quan sát được. Đây là bản gồm một môi trường, không phải toàn bộ bốn môi trường mà README mô tả.

`ESP-Fi_dataset.rar` trong ZIP chỉ dài **134 byte**, có nội dung con trỏ Git LFS. Dữ liệu RAR thật được con trỏ khai báo có kích thước **644.939.981 byte** nhưng không nằm trong ZIP này. Các file MAT trong `Model Code/Data/` là dữ liệu thật và vẫn dùng được độc lập với con trỏ đó.

## 3. Nhãn không thống nhất với README

| Thư mục | Mã hoạt động trong tên file thực tế | Mã theo README | Chỉ số lớp trong loader (bắt đầu từ 0) |
|---|---:|---:|---:|
| `arm_wave` | 5 | 7 | 0 |
| `fall` | 7 | 2 | 1 |
| `jump` | 3 | 5 | 2 |
| `run` | 1 | 1 | 3 |
| `squat` | 4 | 6 | 4 |
| `turn` | 6 | 4 | 5 |
| `walk` | 2 | 3 | 6 |

480/560 tên file không khớp bảng mã hoạt động trong README. Ví dụ: `test_amp/fall/3-1-7-1.mat` nằm trong thư mục `fall`, trong khi README giải thích mã 7 là arm wave.

Loader hiện tại lấy nhãn từ thư mục, không lấy từ tên file. Vì vậy có thể tái lập cách gán nhãn của loader bằng tên thư mục; không được tự gán `activity_id=2` thành fall theo README khi xử lý bản này. Chưa có bằng chứng độc lập để xác nhận thư mục hay bảng README mô tả đúng hành động thực tế; nên xác nhận với tác giả trước khi công bố kết quả theo ngữ nghĩa các lớp. Khi lưu checkpoint, lưu kèm danh sách lớp để tránh nhầm mã filename, chỉ số loader và nhãn nhị phân.

## 4. Đối chiếu với dự án hiện tại

| Nội dung | ESP-Fi-HAR trong ZIP | FallDetectionFirmware |
|---|---|---|
| Dữ liệu tín hiệu | Biên độ đã được xuất thành ma trận | Byte I/Q có dấu, thứ tự Q rồi I |
| Đơn vị mẫu AI | 950 thời điểm × 52 cột | Mỗi bản ghi là một gói CSI; chưa chia cửa sổ theo hoạt động |
| Thông tin thời gian | Không có timestamp hoặc tần số lấy mẫu trong MAT | Có thời gian cục bộ từng RX; các RX không đồng bộ mốc |
| Kênh/sóng mang | Không có bảng ánh xạ 52 cột trong MAT | Bật LLTF và HTLTF; giao thức không lưu đầy đủ metadata PHY/LTF từng gói |
| Nhãn | Từ thư mục hoạt động | Capture hiện tại chưa gắn nhãn hoạt động |
| Nhiều RX | MAT chỉ có một ma trận 2 chiều, không có metadata cặp RX | Hướng triển khai có RX1 và RX2 |

Tại thời điểm kiểm tra, `captures/session01.dat` đã khác phiên được thảo luận trước đó:

- RX1: 1.504 CSI và 1.504 TX_EVENT; RX2: 1.233 CSI và 1.233 TX_EVENT.
- Toàn bộ 2.737 CSI có 256 byte I/Q và `flags=0`, tức 128 cặp phức thô mỗi gói. Không được đồng nhất 128 cặp này với 128 sóng mang độc lập vì có cấu trúc LTF.
- RX1 có khoảng ngắt lớn nhất 434,502837 giây; trung vị khoảng cách mẫu là 50,018 ms. Trung bình trên toàn span chỉ còn 2,945 Hz vì khoảng ngắt.
- RX2 có trung vị 49,9965 ms, trung bình 19,8077 bản ghi/giây và khoảng ngắt lớn nhất 199,968 ms.
- Tính thời gian riêng từng RX; không ghép hay sắp xếp trực tiếp các timestamp cục bộ của hai RX như chung một đồng hồ.

Tính biên độ từ mỗi cặp: `abs(H) = sqrt(I*I + Q*Q)`. Phải xử lý cờ invalid, chọn phần LTF và subcarrier hợp lệ theo cấu hình PHY, rồi mới tạo đầu vào AI. Không lấy tùy ý 52 cặp đầu hoặc ép 128 giá trị thành 52.

Với tốc độ khoảng 20 Hz trong đoạn thu liên tục, 950 điểm kéo dài khoảng 47,5 giây. Không có căn cứ từ MAT/README đi kèm để khẳng định cửa sổ của dataset cũng dài như vậy, hoặc mặc định là 9,5 giây. Cần xác nhận tốc độ gốc, thời lượng trial, phương pháp nội suy/lọc và ý nghĩa 52 cột. Nội suy dữ liệu 20 Hz thành nhiều điểm hơn không khôi phục được thông tin chuyển động bị bỏ lỡ.

## 5. Mức độ phù hợp và hướng áp dụng

- **Phù hợp:** thử mô hình trên Ubuntu, so sánh các kiến trúc, hoặc huấn luyện ban đầu bằng CSI amplitude. Có lớp fall và sáu lớp hoạt động khác nên có thể xây dựng thử nghiệm fall/non-fall sau khi xử lý mâu thuẫn nhãn.
- **Có giới hạn:** đánh giá khác người trong cùng môi trường. Train/test hiện tại không giao nhau về mã người, nhưng test chỉ có một người và chỉ 10 mẫu fall. Nên đánh giá thêm bằng cách lần lượt giữ riêng từng người để test, và tách validation theo người trong phần train.
- **Chưa đủ:** chứng minh khả năng nhận biết trong phòng khác, hoạt động liên tục, người đứng yên/ngồi/nằm, cảnh báo nhầm theo giờ, hoặc mô hình kết hợp hai RX. Các lớp đứng yên/ngồi/nằm không có thư mục riêng trong bản này; cũng không có nhãn thời điểm bắt đầu/kết thúc cú ngã.

Lộ trình đề xuất:

1. Giải quyết bảng nhãn và lấy phần dữ liệu còn thiếu nếu mục tiêu là đánh giá nhiều môi trường.
2. Xác nhận tần số lấy mẫu, thời lượng mỗi trial, cấu hình PHY/LTF và bảng subcarrier từ nguồn thu dataset.
3. Xây dựng thử nghiệm một RX với chuỗi amplitude đã thống nhất cách chọn sóng mang, chia theo khoảng thời gian, và chuẩn hóa tương tự loader. Tách các đoạn bị gián đoạn; không tạo cửa sổ đi qua khoảng ngắt.
4. Dùng tập người riêng làm validation để chọn mô hình/ngưỡng; giữ test riêng. `run.py` gốc chọn checkpoint bằng train accuracy và vẫn tính test mỗi epoch, khác với mô tả test chỉ dùng ở cuối trong README.
5. Thu dữ liệu gắn nhãn trong phòng của dự án, bổ sung sinh hoạt bình thường và chuyển động dễ nhầm; tinh chỉnh và đánh giá recall của fall, precision, độ trễ và số cảnh báo nhầm/giờ. Đánh giá dữ liệu mới theo phiên/người/phòng tách biệt.
6. Chỉ mở rộng kết hợp RX1/RX2 sau khi kiểm chứng mô hình một RX; bổ sung cơ chế ghép cửa sổ thời gian và kiểm tra mất dữ liệu.

Đây là đánh giá về dữ liệu và khả năng tích hợp; chưa phải kết quả thực nghiệm hiệu năng mô hình hoặc suy luận trên ESP32-S3.

## 6. Tệp bằng chứng và tái kiểm tra

- `audit.json`: số liệu tổng hợp và thống kê/hash cho từng MAT.
- `project_capture.json`: số liệu capture hiện tại, tính thời gian riêng từng RX.
- `source_evidence/`: README, loader, mã huấn luyện và giấy phép được sao chép từ ZIP để đối chiếu. Không phải mã được tích hợp vào firmware.
- `audit_dataset.py`: công cụ kiểm tra độc lập, dùng Python standard library.

Chạy từ thư mục `firmware`:

```bash
python3 -B reports/esp_fi_har_audit/audit_dataset.py /home/trinhpt/DATN_PTIT/dataset/ESP-Fi-HAR-main.zip
python3 -B host/check_capture.py captures/session01.dat
```

Theo `DATA_LICENSE.txt` đi kèm, dữ liệu được công bố với CC BY 4.0 và yêu cầu ghi công/trích dẫn bài báo. Giữ lại thông tin nguồn và trích dẫn khi dùng trong đồ án.

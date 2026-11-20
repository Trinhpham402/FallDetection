# Hướng dẫn tham gia dự án và sử dụng Git

Tài liệu dành cho thành viên mới của [FallDetection](https://github.com/Trinhpham402/FallDetection). Các lệnh bên dưới dùng terminal Bash trên Ubuntu; trừ khi có ghi chú, hãy chạy tại thư mục gốc `FallDetection/`.

Mục tiêu làm việc chung: mỗi người làm trên một nhánh riêng, đưa thay đổi lên GitHub qua Pull Request (PR), kiểm tra và review trước khi nhập vào `main`.

## 1. Làm quen với dự án

Đọc [README chính](README.md), sau đó chọn phần cần làm:

| Phần việc | Đường dẫn | Điểm bắt đầu |
|---|---|---|
| Bộ phát ESP32-S3 | `firmware/wifi_csi_tx/` | [README TX](firmware/wifi_csi_tx/README.md), `main/main.c`, `main/probe.h` |
| Bộ thu RX1/RX2 | `firmware/wifi_csi_rx/` | [README RX](firmware/wifi_csi_rx/README.md), `main/main.c`, `main/protocol.h` |
| Thu dữ liệu Ubuntu | `firmware/host/` | [README collector](firmware/host/README.md), `collector.py`, `tests/test_collector.py` |
| Ứng dụng | `app/` | Chưa có mã; thống nhất yêu cầu và công nghệ qua Issue trước |
| Mô hình AI | `model/` | Chưa có pipeline; thống nhất dữ liệu, tiền xử lý và cách đánh giá trước |

Người chưa có board có thể bắt đầu với kiểm thử host, tài liệu hoặc lỗi nhỏ trong collector. Đừng coi phần dự kiến phát triển là chức năng đã có.

## 2. Chủ repo chuẩn bị quyền cộng tác

Chủ repo mở **Settings → Collaborators → Add people**, nhập tài khoản GitHub của thành viên rồi gửi lời mời. Thành viên cần chấp nhận trước khi push nhánh vào repo chung. Quy trình này được mô tả trong [GitHub Docs về mời cộng tác viên](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository).

Nhóm thống nhất làm việc qua PR và không push trực tiếp vào `main`. Nếu gói GitHub và loại repo hỗ trợ, chủ repo nên cấu hình rule bảo vệ `main`, yêu cầu PR/review và chặn force push. Đây là đề xuất thiết lập; tài liệu này không xác nhận repo đã bật rule. Xem [tài liệu bảo vệ nhánh](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

Chưa có quyền ghi thì có thể fork, push vào fork rồi gửi PR về repo gốc. Phần hướng dẫn chính bên dưới dành cho thành viên đã có quyền ghi.

## 3. Cài đặt và cấu hình lần đầu

### 3.1. Công cụ cơ bản

Trên Ubuntu:

```bash
sudo apt update
sudo apt install git python3 build-essential
git --version
python3 --version
cc --version
```

Dự án cần Python 3.10+. Phần firmware cần thêm ESP-IDF đúng v6.0.2, target `esp32s3`; xem [hướng dẫn firmware](firmware/README.md). Không cần ESP-IDF để chỉ sửa tài liệu hoặc chạy kiểm thử host.

### 3.2. Danh tính commit

Thay các giá trị ví dụ bằng thông tin của bạn:

```bash
git config --global user.name "Ten cua ban"
git config --global user.email "email-cua-ban@example.com"
```

Email sẽ xuất hiện trong thông tin commit; có thể dùng email `noreply` lấy từ GitHub **Settings → Emails**. `--global` áp dụng cho tài khoản trên máy; nếu dùng danh tính riêng cho dự án, bỏ `--global` và chạy cấu hình sau khi clone.

`user.name`/`user.email` chỉ ghi tác giả commit, không đăng nhập GitHub và không cấp quyền push.

### 3.3. Đăng nhập GitHub

Chọn HTTPS hoặc SSH, theo [hướng dẫn xác thực của GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github):

- **HTTPS:** dùng trình quản lý thông tin đăng nhập, hoặc Personal Access Token (PAT) thay cho mật khẩu khi Git hỏi. Token cần quyền phù hợp với repo; xem [cách tạo và giới hạn PAT](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens). Token vẫn phải dùng trong phạm vi quyền của tài khoản; không thay thế lời mời cộng tác viên.
- **SSH:** tạo khóa trên máy, thêm khóa công khai vào tài khoản GitHub rồi dùng URL SSH. Làm theo [hướng dẫn kết nối bằng SSH](https://docs.github.com/en/authentication/connecting-to-github-with-ssh).

Không đưa token vào URL remote, mã nguồn, ảnh chụp hay tin nhắn. Khóa riêng phải ở máy của bạn; chỉ thêm khóa công khai lên GitHub.

### 3.4. Lấy mã nguồn

HTTPS:

```bash
git clone https://github.com/Trinhpham402/FallDetection.git
cd FallDetection
git remote -v
git status
```

Nếu chọn SSH, thay lệnh clone bằng:

```bash
git clone git@github.com:Trinhpham402/FallDetection.git
```

Chỉ clone một lần. Các lần làm việc sau mở lại thư mục đã clone. Nếu đã có checkout, kiểm tra `git remote -v` thay vì chạy lại `git init`.

## 4. Những khái niệm Git cần biết

| Khái niệm | Ý nghĩa |
|---|---|
| Working tree | Các tệp đang sửa trên máy |
| Staging area | Những thay đổi đã chọn bằng `git add` để đưa vào commit kế tiếp |
| Commit | Một mốc thay đổi có mã định danh, lưu trong lịch sử Git |
| Branch (nhánh) | Một hướng phát triển riêng; `main` là nhánh tích hợp của nhóm |
| Remote `origin` | Tên ngắn của repo GitHub mà bạn đã clone |
| `origin/main` | Trạng thái nhánh `main` trên GitHub mà máy biết sau lần fetch gần nhất |
| Fetch | Lấy lịch sử/nhánh mới từ GitHub, chưa nhập vào mã đang làm |
| Pull | Lấy thay đổi từ remote và tích hợp vào nhánh hiện tại |
| Push | Gửi commit từ máy lên remote |
| Pull Request | Đề nghị review và nhập một nhánh vào nhánh khác trên GitHub |

Luồng lưu thay đổi: **sửa tệp → `git add` → `git commit` → `git push` → mở PR**. Commit mới chỉ nằm trên máy cho đến khi push; push nhánh cũng chưa tự nhập nhánh đó vào `main`.

## 5. Quy trình cho một công việc

### Bước 1: Thống nhất việc cần làm

Tạo hoặc nhận một Issue, ghi rõ vấn đề, kết quả mong muốn, phần mã liên quan và cách kiểm tra. Với thay đổi giao thức TX/RX/collector, thống nhất cả phía gửi, phía nhận và kiểm thử. Trao đổi trước nếu đổi công nghệ, cấu trúc thư mục hoặc cách xử lý dữ liệu.

### Bước 2: Cập nhật `main` và tạo nhánh

Trước tiên chạy `git status`. Chỉ chuyển nhánh khi các thay đổi đang làm đã được commit hoặc cất bằng stash (mục 9).

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/host-capture-summary
```

Tên nhánh nên ngắn, không dấu, không có khoảng trắng. Ví dụ: `feat/host-capture-summary`, `fix/rx-node-id`, `docs/setup-guide`. Chọn tên phù hợp công việc; không dùng chung một nhánh cho nhiều người. Nhánh do Codex tạo mặc định dùng tiền tố `codex/`.

`--ff-only` cập nhật khi có thể tiến thẳng theo lịch sử; nếu lịch sử đã phân kỳ, lệnh dừng để bạn kiểm tra, không tự tạo merge commit. Xem [tài liệu `git pull`](https://git-scm.com/docs/git-pull).

### Bước 3: Sửa và tự kiểm tra

Giữ mỗi thay đổi tập trung vào một mục tiêu. Bám cách đặt tên và định dạng sẵn có; cập nhật tài liệu nếu hành vi/cách dùng thay đổi.

Kiểm tra các tệp đã sửa:

```bash
git status --short
git diff
```

Nếu sửa host, chạy từ thư mục gốc repo:

```bash
python3 -m unittest discover -s firmware/host/tests -v
python3 -m py_compile firmware/host/collector.py
```

Kiểm thử cần UDP loopback; bài đối chiếu encoder C cần `cc`. Có bài chạy phiên thu thật 17 giây. Nếu sửa TX/RX thì build project tương ứng bằng ESP-IDF v6.0.2, theo [README firmware](firmware/README.md).

Chỉ sửa tài liệu thì kiểm tra câu lệnh, đường dẫn, liên kết và `git diff --check`; không cần flash board. Trong PR, ghi đúng phần đã kiểm tra và phần chưa có điều kiện kiểm tra.

### Bước 4: Chọn thay đổi và commit

Ví dụ sau dành cho công việc sửa collector và bài kiểm thử; thay đường dẫn theo việc thực tế:

```bash
git add firmware/host/collector.py firmware/host/tests/test_collector.py
git diff --cached
git diff --cached --check
git commit -m "host: them thong ke cuoi phien thu"
```

`git diff` xem thay đổi chưa stage; `git diff --cached` xem nội dung sắp commit. Có thể dùng `git add -p` để chọn từng phần của tệp đã được theo dõi. Sau khi sửa tiếp một tệp đã stage, cần `git add` lại để cập nhật phần muốn commit.

Ưu tiên thêm tệp cụ thể. Nếu dùng `git add .`, luôn xem lại diff đã stage để tránh đưa cả thay đổi ngoài phạm vi vào commit. Mỗi commit nên là một thay đổi có ý nghĩa, có thể giải thích; tránh tên như `update`, `fix`, `abc`.

### Bước 5: Push nhánh

```bash
git push -u origin feat/host-capture-summary
```

`-u` đặt nhánh theo dõi cho lần đầu. Những lần tiếp theo trên cùng nhánh chỉ cần `git push`.

### Bước 6: Tạo PR và nhận review

Trên GitHub, chọn **Compare & pull request**, kiểm tra **base: `main`** và **compare: nhánh của bạn**. Xem [hướng dẫn tạo PR](https://docs.github.com/en/pull-requests/how-tos/create-pull-requests/creating-a-pull-request).

Mẫu mô tả ngắn:

```text
Vấn đề / Issue: #<so-issue>
Thay đổi: ...
Cách kiểm tra và kết quả: ...
Kiểm tra phần cứng: đã làm ... / chưa thực hiện
Điểm cần reviewer chú ý: ...
```

Dùng Draft PR nếu muốn nhận góp ý khi đang làm. Khi sửa theo review, tiếp tục commit/push trên chính nhánh đó; PR sẽ cập nhật. Không cần tạo PR mới cho mỗi lần sửa. Người review kiểm tra cả logic, giao thức, kiểm thử, tài liệu và tệp ngoài phạm vi trước khi người phụ trách merge.

### Bước 7: Sau khi PR được merge

Khi working tree sạch:

```bash
git switch main
git pull --ff-only origin main
git fetch --prune origin
```

Có thể xóa nhánh đã merge trên trang PR và xóa nhánh local bằng `git branch -d ten-nhanh`. Nếu `-d` từ chối sau squash merge, kiểm tra lại PR và các commit trước; không vội dùng `-D`. Tạo nhánh mới từ `main` đã cập nhật cho công việc tiếp theo.

## 6. Khi `main` có thay đổi trong lúc đang làm

Commit phần đang làm trên nhánh của bạn, sau đó lấy `main` mới và nhập vào nhánh đó. Ví dụ, **đang đứng trên `feat/host-capture-summary`**, không phải `main`:

```bash
git status
git fetch origin
git merge --no-edit origin/main
```

Nếu merge thành công, chạy lại kiểm tra phù hợp rồi `git push`. Với người mới, dùng merge để cập nhật nhánh đã chia sẻ sẽ dễ theo dõi hơn việc viết lại lịch sử bằng rebase. Nhóm không dùng force push trong quy trình thông thường.

## 7. Xử lý conflict khi merge

Conflict xuất hiện khi Git không tự kết hợp được thay đổi. Xem `git status` để biết tệp nào cần sửa; mở tệp có các dấu:

```text
<<<<<<< HEAD
Nội dung trên nhánh đang làm
=======
Nội dung từ nhánh được merge vào
>>>>>>> origin/main
```

Đọc cả hai phía, tạo nội dung cuối cùng đúng yêu cầu và xóa các dấu conflict. Không chọn toàn bộ “ours/theirs” chỉ để hết thông báo, đặc biệt với định dạng gói và cấu hình.

Sau khi sửa từng tệp:

```bash
git add duong/dan/tep-da-sua
git diff --cached
git diff --cached --check
git status
```

Thay đường dẫn ví dụ bằng tệp thật. Khi tất cả conflict đã được giải quyết, chạy lại kiểm thử/build phù hợp, rồi hoàn tất merge và push:

```bash
git commit -m "merge: cap nhat main vao nhanh cong viec"
git push
```

Nếu chưa biết cách kết hợp, có thể dùng `git merge --abort` để hủy lần merge đang diễn ra rồi trao đổi với người sửa phần đó. Bắt đầu merge với working tree sạch để tránh lẫn thay đổi chưa commit. Xem [tài liệu `git merge`](https://git-scm.com/docs/git-merge).

## 8. `.gitignore`, `.gitkeep` và dữ liệu cục bộ

- Giữ `.gitignore` trong Git để cả nhóm dùng cùng quy tắc. Tệp này chỉ bỏ qua các tệp chưa được theo dõi; không tự gỡ tệp đã commit khỏi lịch sử.
- `app/.gitkeep` và `model/.gitkeep` giữ hai thư mục khi còn rỗng. Khi có mã thật, có thể xóa chúng trong cùng PR.
- `sdkconfig` chứa cấu hình riêng từng máy/board; nhập Wi-Fi qua `menuconfig`. `sdkconfig.defaults` là cấu hình nền dùng chung, không chứa mật khẩu.
- Không commit `build/`, `managed_components/`, `.venv/`, `__pycache__/`, `.env`, token, khóa riêng hoặc capture cục bộ. Không dùng `git add -f` để vượt quy tắc khi chưa rõ lý do.
- Dataset, checkpoint và kết quả đo nên có nơi lưu riêng được nhóm thống nhất, kèm phiên bản, nguồn, nhãn và cách tái lập trong tài liệu. Không mặc định mọi tệp dữ liệu lớn đều đã được `.gitignore` loại trừ.

Kiểm tra vì sao một tệp bị bỏ qua bằng `git check-ignore -v duong/dan/tep`. Nếu bí mật đã bị push, báo chủ repo và thu hồi/đổi bí mật ngay; xóa tệp ở commit mới không loại nó khỏi lịch sử. Xem [tài liệu `.gitignore`](https://git-scm.com/docs/gitignore).

## 9. Các thao tác cứu hộ thường dùng

### Bỏ stage nhưng giữ nội dung đang sửa

```bash
git restore --staged duong/dan/tep
```

Thay bằng đường dẫn thật. Lệnh này không xóa phần đang sửa trong working tree. Ngược lại, `git restore duong/dan/tep` có thể loại bỏ thay đổi chưa stage; không dùng nếu còn muốn giữ chúng. Xem [tài liệu `git restore`](https://git-scm.com/docs/git-restore).

### Cất việc đang làm để chuyển nhánh

```bash
git stash push -u -m "tam cat viec dang lam"
git status
# Chuyển nhánh và xử lý việc khác, rồi quay lại đúng nhánh cũ.
git stash list
git stash apply 'stash@{0}'
git status
```

`-u` cất cả tệp mới chưa theo dõi nhưng không cất tệp bị ignore. Stash chỉ ở máy, không được gửi lên bằng `git push`. `apply` giữ bản stash để còn kiểm tra; sau khi xác nhận nội dung phục hồi đúng, mới dùng `git stash drop 'stash@{0}'`. Nếu có nhiều stash, chọn đúng mã trong `git stash list`. Apply cũng có thể phát sinh conflict; không drop khi chưa giải quyết xong. Xem [tài liệu `git stash`](https://git-scm.com/docs/git-stash).

### Hoàn tác commit đã chia sẻ

Tạo một nhánh sửa lỗi từ `main` mới nhất, rồi dùng `git revert <ma-commit>` với mã thật lấy từ `git log --oneline`. Revert tạo commit bù để giữ lịch sử; kiểm tra, push và mở PR như bình thường. Commit merge cần xử lý riêng, nên trao đổi với người phụ trách trước. Xem [tài liệu `git revert`](https://git-scm.com/docs/git-revert).

Không dùng `git reset --hard`, `git clean -fd` hoặc `git push --force` như cách sửa lỗi mặc định: các lệnh này có thể làm mất việc hoặc ghi đè lịch sử chung.

## 10. Lỗi hay gặp

| Thông báo / tình huống | Cách xử lý |
|---|---|
| `Author identity unknown` | Cấu hình `user.name` và `user.email`, rồi commit lại |
| `Authentication failed` / không đọc được Username | Thiết lập xác thực HTTPS/PAT hoặc SSH trong terminal; kiểm tra đúng tài khoản |
| `Permission denied (publickey)` | Kiểm tra khóa SSH đã thêm vào tài khoản và repo có thể truy cập bằng tài khoản đó |
| `403` hoặc `Repository not found` | Kiểm tra URL, tài khoản, lời mời cộng tác và quyền của thông tin xác thực |
| Push bị `non-fast-forward` | Fetch rồi kiểm tra lịch sử; nếu remote của nhánh làm việc có commit mới, merge nhánh remote tương ứng, kiểm tra rồi push; không force push |
| Pull `--ff-only` thất bại trên `main` | Dừng và xem `git log --oneline --graph --all -20`; nếu lỡ commit trên `main`, giữ commit bằng một nhánh mới và nhờ người phụ trách hỗ trợ đồng bộ, không reset vội |
| Chuyển nhánh báo sẽ ghi đè thay đổi | Commit trên nhánh công việc hoặc stash trước |
| Sửa tệp mà không thấy trong `git status` | Kiểm tra đúng thư mục repo và chạy `git check-ignore -v` với đường dẫn tệp |
| Collector báo CSV đã tồn tại | Chọn tên trial mới; collector không ghi đè/ghi nối |

## 11. Thói quen giúp nhóm làm việc hiệu quả

1. Đầu buổi: xem `git status`, cập nhật `main` trước khi tạo nhánh mới.
2. Trong buổi: giữ phạm vi nhỏ, commit các mốc có ý nghĩa, push nhánh để lưu việc lên GitHub.
3. Trước PR: đọc lại diff, kiểm tra bí mật/tệp tự sinh, chạy kiểm tra đúng phần đã sửa.
4. Khi review: mô tả vấn đề và hành vi mong muốn cụ thể; phản hồi trên PR để người khác theo dõi được quyết định.
5. Khi bàn giao: ghi cách chạy, phiên bản công cụ, kết quả kiểm thử và phần cần kiểm tra tiếp. Với phần cứng, ghi node ID, cấu hình thử nghiệm và tốc độ CSI thực; không đưa mật khẩu vào báo cáo.

Tra nhanh khi quên lệnh: `git status`, `git diff`, `git diff --cached`, `git branch -vv`, `git log --oneline --graph --all -20`. Xem thêm [sách Pro Git](https://git-scm.com/book/en/v2) để hiểu từng thao tác trước khi dùng lệnh thay đổi lịch sử.

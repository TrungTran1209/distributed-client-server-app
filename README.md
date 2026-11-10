# Ứng dụng Cộng tác Client–Server Phân tán

> **Mục đích:** chạy một máy chủ và nhiều ứng dụng dòng lệnh để người dùng đăng ký, đăng nhập, xem danh sách trực tuyến, nhắn tin broadcast/riêng tư và truyền tệp tin cậy qua mạng cục bộ. Ứng dụng dùng **TCP + TLS** cho toàn bộ kênh dữ liệu ứng dụng và **UDP** cho tìm máy chủ/nhịp kiểm tra.

## Đề bài và quyết định của nhóm

Đề bài yêu cầu xây dựng ứng dụng phân tán bằng raw socket, cấm framework mạng cấp cao (như HTTP framework và WebSocket), chấm 10 mốc kỹ thuật và yêu cầu nộp mã nguồn, `README.md` hướng dẫn từng bước cùng báo cáo kỹ thuật PDF.

Các quyết định kiến trúc của nhóm:

- **Ngôn ngữ & Runtime:** Python 3.11+ (chỉ dùng thư viện chuẩn của Python, không phụ thuộc gói bên thứ ba khi chạy).
- **Bảo mật kênh truyền:** bọc toàn bộ luồng TCP trong **TLS 1.2+ / TLS 1.3** (`ssl.SSLContext`), phía client bắt buộc xác minh chứng chỉ CA và hostname/IP (SAN).
- **Bảo mật mật khẩu lưu trữ:** dẫn xuất mật khẩu bằng `hashlib.scrypt` với salt ngẫu nhiên 16 byte riêng cho mỗi tài khoản, so sánh thời gian hằng số (`hmac.compare_digest`) và lưu kèm phiên bản tham số `kdf_params` trong SQLite để hỗ trợ nâng cấp tự động.
- **Truyền tệp đáng tin cậy:** chia chunk 64 KiB mã hóa Base64 qua kết nối TLS, ghi luồng vào tệp tạm `.part`, kiểm tra kích thước + mã băm **SHA-256 đầu-cuối**, đổi tên nguyên tử sang thư mục `downloads/` và tự động xóa tệp dở dang nếu mất kết nối hoặc sai checksum.
- **Discovery & Heartbeat:** dùng UDP trên cổng riêng (`37020`) để dò địa chỉ máy chủ và gửi nhịp kiểm tra không chứa thông tin nhạy cảm.

## Trạng thái các tính năng hiện tại

| Tính năng                                                                          | Trạng thái trong mã hiện có            |
| ---------------------------------------------------------------------------------- | -------------------------------------- |
| TCP raw socket, TLS 1.2+, xác minh chứng chỉ phía client                           | **Hoạt động & đã kiểm thử tự động**    |
| Framing 4 byte độ dài + JSON UTF-8                                                 | **Hoạt động & đã kiểm thử tự động**    |
| Đăng ký, đăng nhập (`scrypt` + `kdf_params`), danh sách online kèm IP/cổng         | **Hoạt động & đã kiểm thử tự động**    |
| Chat broadcast (`/all`) và nhắn riêng (`/msg`)                                     | **Hoạt động & đã kiểm thử tự động**    |
| UDP discovery và heartbeat                                                         | **Hoạt động & đã kiểm thử tự động**    |
| Truyền tệp tin cậy nhiều chunk (`/file`, `/accept`, `/reject`, `/cancel`, SHA-256) | **Hoạt động & đã kiểm thử tự động**    |
| Phục hồi lỗi mạng, chứng chỉ sai, timeout và dọn tệp `.part` dở dang               | **Hoạt động & đã kiểm thử tự động**    |
| Mô phỏng đa client đồng thời (12+ clients chat & truyền tệp song song)             | **Đã kiểm chứng qua integration test** |
| Báo cáo kỹ thuật PDF (`docs/report/technical-report.pdf`)                          | **Đã biên soạn đầy đủ & xuất PDF**     |

## Yêu cầu cài đặt

- Python 3.11 trở lên.
- OpenSSL dòng lệnh để tạo chứng chỉ demo (trên Windows có sẵn trong `C:\Program Files\Git\usr\bin\openssl.exe` nếu đã cài Git for Windows).
- Hai hoặc nhiều cửa sổ terminal để thử nghiệm tương tác.

Mở PowerShell tại thư mục gốc repository:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

_(Hoặc chạy trực tiếp không cần cài editable bằng cách đặt `$env:PYTHONPATH = "src"` trong PowerShell)._

## Tạo chứng chỉ TLS demo

Client luôn kiểm tra chuỗi tin cậy và khớp tên máy/IP trong `subjectAltName` (SAN). Với demo trên cùng máy (`localhost` / `127.0.0.1`):

```powershell
New-Item -ItemType Directory -Force certs | Out-Null
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 `
  -keyout certs/server.key -out certs/server.crt `
  -subj "/CN=localhost" `
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

Nếu `openssl` chưa nằm trong `PATH` trên Windows, có thể gọi trực tiếp `"$env:ProgramFiles\Git\usr\bin\openssl.exe"`. Khi chạy qua mạng LAN, hãy thêm IP LAN của máy chủ vào `subjectAltName` (ví dụ `DNS:localhost,IP:127.0.0.1,IP:192.168.1.20`). Không bao giờ commit `certs/server.key` lên Git. Xem thêm tại [`certs/README.md`](certs/README.md).

## Chạy máy chủ (Server)

Trong terminal thứ nhất:

```powershell
python -m collab.server.main --host 0.0.0.0 --port 37021 --udp-port 37020 `
  --cert certs/server.crt --key certs/server.key
```

Máy chủ khởi tạo cơ sở dữ liệu tài khoản tại `data/users.sqlite3`. Khi chạy qua LAN, mở cổng TCP `37021` và UDP `37020` trên tường lửa, có thể chỉ định thêm `--advertise-host <IP-LAN>`.

## Chạy các trình khách (Clients)

Mở terminal thứ hai cho `alice` và terminal thứ ba cho `bob`:

```powershell
# Terminal 2 (Alice) — dò máy chủ qua UDP rồi kết nối TLS
python -m collab.client.main --discover --udp-port 37020 --ca certs/server.crt --download-dir downloads/alice

# Terminal 3 (Bob) — kết nối trực tiếp hoặc qua UDP discovery
python -m collab.client.main --discover --udp-port 37020 --ca certs/server.crt --download-dir downloads/bob
```

Tùy chọn thêm `--auto-accept` nếu muốn client tự động chấp nhận các lời mời nhận tệp hợp lệ mà không cần gõ `/accept`.

## Các lệnh trên CLI

Tại dấu nhắc `collab>`:

| Lệnh                   | Tác dụng                                                                                      |
| ---------------------- | --------------------------------------------------------------------------------------------- |
| `/register USER`       | Đăng ký tài khoản mới (nhập mật khẩu ẩn tối thiểu 8 ký tự)                                    |
| `/login USER`          | Đăng nhập vào phiên làm việc an toàn                                                          |
| `/logout`              | Đăng xuất khỏi phiên hiện tại; server thu hồi session và cập nhật presence                    |
| `/users`               | Xem danh sách người dùng đang trực tuyến kèm địa chỉ IP/cổng                                  |
| `/all NỘI_DUNG`        | Gửi tin nhắn broadcast tới tất cả người dùng online khác                                      |
| `/msg USER NỘI_DUNG`   | Gửi tin nhắn riêng 1-1 tới `USER`                                                             |
| `/file ĐƯỜNG_DẪN USER` | Gửi tệp tới `USER` qua TLS (tự động chia chunk & kiểm tra SHA-256)                            |
| `/accept [ID]`         | Chấp nhận lời mời nhận tệp (có thể gõ 8 ký tự đầu của ID, hoặc bỏ trống nếu chỉ có 1 lời mời) |
| `/reject [ID]`         | Từ chối lời mời nhận tệp                                                                      |
| `/cancel [ID]`         | Hủy phiên truyền tệp đang gửi hoặc đang nhận (xóa sạch tệp tạm `.part`)                       |
| `/help`                | Hiển thị danh sách lệnh                                                                       |
| `/quit`                | Đăng xuất an toàn và đóng kết nối                                                             |

### Ví dụ phiên thử nghiệm 2 người dùng

1. Terminal 2: gõ `/register alice` → `/login alice`.
2. Terminal 3: gõ `/register bob` → `/login bob`. Cả hai nhìn thấy sự kiện trực tuyến của nhau.
3. Terminal 2: gõ `/msg bob Chào Bob, mình gửi báo cáo nhé!` rồi `/file docs/report/technical-report.pdf bob`.
4. Terminal 3: nhận thông báo `[file] alice muốn gửi 'technical-report.pdf'...` → gõ `/accept`.
5. Cả hai terminal hiển thị tiến độ `%` theo thời gian thực và xác nhận **SHA-256 khớp** khi hoàn tất lưu tệp tại `downloads/bob/technical-report.pdf`.

## Chạy bộ kiểm thử tự động & Xuất báo cáo PDF

```powershell
$env:PYTHONPATH = "src"
# Chạy toàn bộ unit tests (framing, protocol, scrypt KDF, manifest, coordinator, CLI, UDP)
python -m unittest discover -s tests/unit -v

# Chạy integration tests (TLS thật, chứng chỉ sai, truyền file lớn, lỗi mạng, 12 clients đồng thời)
python -m unittest discover -s tests/integration -v

# Xuất lại báo cáo kỹ thuật PDF từ Markdown
python docs/report/build_report.py
```

Kết quả chạy thực tế gần nhất (10/11/2026, Python 3.12.6): **34 unit tests và 5 integration tests đều đạt**. Unit test luồng server bao gồm `/logout`: response thành công, client khác nhận `presence_offline`, và yêu cầu chat sau đăng xuất bị từ chối (`unauthorized`).

## Tài liệu thiết kế chi tiết

- [Kiến trúc hệ thống](docs/architecture.md)
- [Đặc tả giao thức TCP/TLS & UDP](docs/protocol.md)
- [Sơ đồ trạng thái](docs/state-diagrams.md)
- [Sơ đồ tuần tự](docs/sequence-diagrams.md)
- [Kiến trúc bảo mật & Threat Model](docs/security.md)
- [Báo cáo kỹ thuật (Markdown)](docs/report/technical-report.md) & [Bản in PDF](docs/report/technical-report.pdf)

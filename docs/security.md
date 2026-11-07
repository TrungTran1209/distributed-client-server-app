# Kiến trúc Bảo mật: Mục tiêu, Cơ chế Triển khai và Giới hạn

## 1. Yêu cầu của đề bài và quyết định của nhóm

Đề bài yêu cầu bảo vệ payload trên đường truyền bằng thư viện mật mã chuẩn thay vì tự thiết kế thuật toán mã hóa. Nhóm lựa chọn **TLS (qua module chuẩn `ssl` của Python, OpenSSL 3.x)** bao bọc toàn bộ kết nối TCP cho cả xác thực, tin nhắn và truyền tệp. Đối với lưu trữ tài khoản trên máy chủ, nhóm bổ sung cơ chế dẫn xuất mật khẩu **`hashlib.scrypt` có gắn phiên bản tham số (`kdf_params`)** và muối ngẫu nhiên riêng cho từng tài khoản.

Hai lớp bảo vệ này giải quyết hai mối đe dọa tách biệt:
- **TLS** bảo vệ tính bí mật, tính toàn vẹn trên đường truyền và xác thực danh tính máy chủ trước tấn công nghe lén/chỉnh sửa gói tin (MITM) trên mạng nội bộ.
- **`scrypt`** bảo vệ mật khẩu lưu trong cơ sở dữ liệu SQLite (`data/users.sqlite3`) nếu tệp cơ sở dữ liệu bị lộ.

## 2. Bảo vệ dữ liệu trên đường truyền: TCP + TLS 1.2+

- **Cấu hình phía Server (`collab.common.tls.create_server_context`):** sử dụng `ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)` với `minimum_version = ssl.TLSVersion.TLSv1_2` (tự động thương lượng TLS 1.3 trên OpenSSL 3.0 khi cả hai phía hỗ trợ).
- **Xác minh phía Client (`collab.common.tls.create_client_context`):** sử dụng `ssl.create_default_context(cafile=...)`, giữ nguyên chế độ bắt buộc xác minh chuỗi chứng chỉ (`CERT_REQUIRED`) và kiểm tra khớp tên máy chủ/IP (`check_hostname = True`). Không vô hiệu hóa bước kiểm tra chứng chỉ trong luồng vận hành.
- **Trật tự thiết lập kênh:** bắt tay TLS phải hoàn tất trước khi gửi frame ứng dụng đầu tiên (`hello`). Mật khẩu, nội dung chat và toàn bộ dữ liệu chunk của tệp chỉ đi qua socket TLS đã xác minh; không mở cổng phụ không mã hóa để truyền tệp.
- **Ranh giới với UDP Discovery:** thông điệp UDP `discover` / `server_announcement` không có xác thực mật mã và chỉ đóng vai trò gợi ý địa chỉ IP/cổng. Khi kết nối TCP tới địa chỉ gợi ý đó, client vẫn kiểm tra chứng chỉ TLS — nếu kẻ tấn công giả mạo phản hồi UDP trỏ sang máy chủ lạ không có khóa riêng hợp lệ của CA tin cậy, bước bắt tay TLS sẽ thất bại ngay lập tức (`SSLCertVerificationError`).

## 3. Bảo vệ mật khẩu lưu trữ: `scrypt` có Phiên bản Tham số

- **Tham số mặc định (`collab.common.crypto.DEFAULT_SCRYPT_PARAMS`):**
  - Thuật toán: `hashlib.scrypt`
  - Phiên bản: `v=1`
  - Chi phí CPU/RAM: `n = 16384` ($2^{14}$), `r = 8`, `p = 1` (~16 MiB bộ nhớ làm việc mỗi lần dẫn xuất, giới hạn trần `maxmem` an toàn 64 MiB)
  - Độ dài salt: `16 bytes` sinh ngẫu nhiên từ CSPRNG của hệ điều hành (`os.urandom(16)`) riêng biệt cho từng tài khoản
  - Độ dài khóa dẫn xuất: `dklen = 32 bytes`
- **Định dạng lưu trữ và nâng cấp tự động (`collab.server.user_store.UserStore`):**
  - Bảng `users` lưu `username`, `salt` (BLOB), `password_hash` (BLOB) và `kdf_params` (`"scrypt$v=1$n=16384$r=8$p=1$dklen=32"`).
  - Các cơ sở dữ liệu phiên bản cũ chưa có cột `kdf_params` được tự động migrate an toàn khi khởi động.
  - Khi đăng nhập, server đọc `kdf_params` của tài khoản để kiểm tra bằng `hmac.compare_digest` (thời gian hằng số, chống rò rỉ qua timing side-channel). Nếu tham số lưu trữ cũ hơn cấu hình mục tiêu hiện tại (`needs_rehash(...) == True`), server tự động sinh salt mới và cập nhật lại hash theo tham số mới ngay trong lần đăng nhập hợp lệ đó.
- **Giảm rò rỉ sự tồn tại tài khoản qua thời gian phản hồi:** khi đăng nhập với một `username` không tồn tại, `UserStore.authenticate()` vẫn thực hiện một phép dẫn xuất `scrypt` đầy đủ với khóa muối giả ngẫu nhiên theo tiến trình (`_dummy_salt`) trước khi trả về `invalid_credentials`.
- **Chính sách không ghi log bí mật:** mật khẩu, salt, giá trị băm và khóa riêng TLS không bao giờ được ghi vào log ứng dụng, thông báo lỗi hay lịch sử Git.

## 4. Bảo mật trong Truyền tệp và Chống Lạm dụng Tài nguyên

- **Chống leo thang đường dẫn (Path Traversal) đa nền tảng (`collab.transfer.manifest`):**
  - Trên đường truyền (`TransferManifest.from_offer`), tên tệp chứa ký tự phân tách đường dẫn (`/`, `\`, `:`) bị từ chối ngay lập tức.
  - Hàm `sanitize_filename()` chuẩn hóa Unicode NFC, loại bỏ mọi thành phần thư mục, từ chối tên rỗng, `.`, `..`, ký tự điều khiển ASCII (`< 32`, `127`), ký tự cấm trên hệ thống tệp (`<>:"/\|?*`), tên thiết bị đặc biệt của Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`) và giới hạn độ dài tối đa 200 ký tự.
  - Hàm `resolve_safe_paths()` kiểm tra lần cuối bằng `Path.resolve().is_relative_to(download_dir.resolve())` để đảm bảo tuyệt đối không có thao tác ghi nào thoát ra ngoài thư mục nhận `downloads/`.
- **Cô lập tệp tạm và chống ghi đè dữ liệu người nhận:**
  - Trong suốt quá trình nhận, dữ liệu chỉ được ghi vào tệp ẩn tạm thời `.<safe_name>.<transfer_id>.part`.
  - Tệp tạm chỉ được đổi tên nguyên tử (`os.replace`) thành tệp hoàn chỉnh sau khi tổng số chunk, kích thước byte và mã băm **SHA-256 đầu-cuối** đều khớp 100% với manifest ban đầu. Nếu kết nối đứt, quá hạn hoặc lệch checksum, tệp `.part` bị xóa ngay lập tức.
  - Nếu trong thư mục nhận đã có sẵn tệp trùng tên, `allocate_non_colliding_path()` tự động cấp tên mới (`report (1).pdf`) thay vì ghi đè mất tệp sẵn có của người dùng.
- **Bảo vệ bộ nhớ Server và giới hạn DoS:**
  - Server kiểm tra kích thước frame tối đa (`MAX_FRAME_SIZE = 1 MiB`), kích thước tệp tối đa (`MAX_FILE_SIZE = 64 MiB`), kích thước chunk tối đa (`256 KiB`) và giới hạn tối đa 3 phiên truyền đồng thời trên mỗi người dùng gửi.
  - `TransferCoordinator` chuyển tiếp từng chunk trực tiếp sang socket người nhận mà không tích trữ nội dung tệp trong RAM hay ổ đĩa của server (chi phí bộ nhớ `O(1)` theo kích thước tệp).

## 5. Quản lý Tài sản Nhạy cảm và Giới hạn Bảo mật (Threat Model)

- **Tài sản loại trừ khỏi Git (`.gitignore`):** khóa riêng và chứng chỉ (`certs/*.key`, `certs/*.crt`, `certs/*.pem`), cơ sở dữ liệu runtime (`data/*`), thư mục tệp tải về (`downloads/`) và tệp cấu hình cục bộ (`.env`).
- **Những giới hạn cần nêu rõ trong phạm vi đồ án môn học:**
  1. **Không mã hóa đầu-cuối (E2EE) chống lại Server:** vì kiến trúc là Client–Server định tuyến tập trung qua TLS, server giải mã frame TLS để kiểm tra giao thức và chuyển tiếp sang kết nối TLS của người nhận. Hệ thống bảo vệ trước kẻ nghe lén trên mạng LAN, nhưng người vận hành server được coi là thành phần tin cậy trong mô hình này.
  2. **Chứng chỉ tự ký trong môi trường demo:** phù hợp khi phân phối tường minh tệp chứng chỉ/CA qua tham số `--ca`, nhưng không cung cấp cơ chế thu hồi chứng chỉ (CRL/OCSP) hay quản trị định danh PKI doanh nghiệp.
  3. **Dữ liệu nghỉ (Data at rest):** mật khẩu được băm bằng `scrypt`, nhưng các tệp người dùng sau khi tải về thư mục `downloads/` được lưu ở dạng nguyên bản theo quyền hệ điều hành của người dùng chạy client.

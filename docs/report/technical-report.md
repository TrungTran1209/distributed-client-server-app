# Báo cáo Kỹ thuật: Ứng dụng Cộng tác Client–Server Phân tán qua Raw Sockets & TLS

**Môn học:** Hệ thống Phân tán / Lập trình Mạng  
**Phiên bản giao thức:** `v1`  
**Ngôn ngữ & Nền tảng:** Python 3.11+ (100% Python Standard Library: `socket`, `ssl`, `threading`, `hashlib`, `hmac`, `sqlite3`)

---

## 1. Giới thiệu và Mục tiêu Hệ thống

Dự án xây dựng một nền tảng cộng tác tự lưu trữ (self-hosted) hoạt động trên localhost hoặc mạng nội bộ (LAN) tuân thủ nghiêm ngặt yêu cầu sử dụng **raw sockets** ở tầng giao vận, không sử dụng các framework mạng bậc cao như HTTP hay WebSocket.

Hệ thống đáp ứng trọn vẹn 10 tiêu chí kỹ thuật của đề bài:
1. **Giao thức ứng dụng tường minh:** đóng khung nhị phân 4 byte độ dài kết hợp bản tin JSON UTF-8 được kiểm chứng schema.
2. **Quản lý kết nối đồng thời:** mô hình đa luồng phục vụ hàng chục trình khách kết nối song song, duy trì nhịp sống `ping/pong` và thu hồi phiên nhàn rỗi.
3. **Định danh, xác thực và hiện diện (Presence):** đăng ký/đăng nhập bảo mật, theo dõi danh sách người dùng trực tuyến kèm địa chỉ IP và cổng TCP nguồn thực tế.
4. **Định tuyến tin nhắn:** hỗ trợ tin nhắn quảng bá (`broadcast`) và tin nhắn riêng 1-1 (`direct`).
5. **Truyền tệp tin cậy đầu-cuối:** phân mảnh tệp lớn theo chunk 64 KiB, chuyển tiếp qua máy chủ với chi phí bộ nhớ `O(1)`, ghi tạm `.part` và xác minh mã băm **SHA-256** trước khi hoàn tất.
6. **Bảo mật đa tầng:** mã hóa toàn bộ luồng TCP bằng **TLS 1.2+ / TLS 1.3** (xác minh chứng chỉ CA & SAN) và lưu trữ mật khẩu bằng dẫn xuất **`hashlib.scrypt`** có phiên bản tham số (`kdf_params`).
7. **Dò tìm máy chủ qua UDP:** khám phá địa chỉ máy chủ tự động trong LAN mà không làm suy yếu mô hình xác thực TLS.

---

## 2. Kiến trúc Tổng thể Hệ thống

Hệ thống tuân theo mô hình **Client–Server tập trung**, tách bạch hoàn toàn hai mặt phẳng giao tiếp:
- **Kênh dữ liệu chính (TCP/TLS, cổng mặc định `37021`):** truyền tải toàn bộ bản tin bắt tay (`hello`/`welcome`), xác thực tài khoản, danh sách người dùng, tin nhắn chat và các chunk truyền tệp.
- **Kênh dò tìm phụ trợ (UDP, cổng mặc định `37020`):** chỉ truyền datagram gọn nhẹ (`<= 1,200` byte) cho `discover` -> `server_announcement` và `client_heartbeat` -> `heartbeat_ack`. Phản hồi UDP chỉ được xem là địa chỉ gợi ý, không có thẩm quyền đăng nhập hay duy trì phiên người dùng.

{{DIAGRAM_ARCHITECTURE}}

| Phân hệ | Module nguồn | Trách nhiệm cốt lõi |
|---|---|---|
| Giao thức & Mật mã chung | `src/collab/common/` | Framing 4 byte (`framing.py`), schema bản tin (`protocol.py`), ngữ cảnh TLS (`tls.py`), dẫn xuất mật khẩu `scrypt` (`crypto.py`), giao thức UDP (`udp_protocol.py`). |
| Máy chủ điều phối | `src/collab/server/` | Vòng lặp `accept` TLS đa luồng (`server.py`), kho SQLite WAL (`user_store.py`), bảng phiên (`sessions.py`), định tuyến chat (`router.py`), điều phối truyền tệp (`transfer_coordinator.py`), UDP listener (`discovery.py`). |
| Bộ máy truyền tệp | `src/collab/transfer/` | Làm sạch tên tệp & tính SHA-256 luồng (`manifest.py`), luồng gửi chunk (`sender.py`), luồng ghép `.part` & đối chiếu mã băm (`receiver.py`). |
| Trình khách CLI | `src/collab/client/` | Kết nối TLS bất đồng bộ ghép cặp `request_id` (`connection.py`), giao diện lệnh tương tác và hiển thị tiến độ (`commands.py`), dò tìm UDP (`discovery.py`). |

---

## 3. Thiết kế Giao thức Ứng dụng và Đóng khung TCP

### 3.1 Giải quyết bài toán ranh giới gói tin trên TCP Stream
Vì TCP là dòng byte liên tục (một lời gọi `sock.recv()` có thể trả về nửa bản tin hoặc ghép nhiều bản tin liền nhau), lớp `collab.common.framing` áp dụng cấu trúc khung tiền tố độ dài cố định:
- **Header (4 bytes):** số nguyên không dấu 32-bit thứ tự byte mạng (`!I`, big-endian), biểu diễn độ dài byte của phần payload tiếp theo (`1 .. 1,048,576` byte).
- **Payload (`N` bytes):** chuỗi JSON mã hóa UTF-8 dạng compact (`{"v":1,"type":"..."}`).
- Hàm `recv_exact(sock, size)` lặp đọc cho tới khi thu đủ đúng `size` byte hoặc ném `EOFError` nếu kết nối đóng giữa chừng, đảm bảo không bao giờ giải mã một bản tin bị cắt cụt.

### 3.2 Tương quan Request/Response và Server Push Event
- Mọi yêu cầu do client khởi xướng (`hello`, `register`, `login`, `logout`, `chat_send`, `file_offer`, `file_accept`, `file_reject`, `file_chunk`, `file_end`, `file_ack`, `file_cancel`, `ping`) đều đính kèm `request_id` (UUIDv4). Máy chủ phản hồi tức thì bản tin `*_result` mang cùng `request_id` để đánh thức đúng luồng đang chờ trong `ClientConnection._pending`.
- Các sự kiện chủ động từ máy chủ (`user_list`, `presence_online`, `presence_offline`, `chat_message`, `file_offer_event`, `file_decision`, `file_chunk_event`, `file_end_event`, `file_status`) không mang `request_id` và được đẩy thẳng sang hàm xử lý sự kiện giao diện mà không chặn luồng đọc mạng.

---

## 4. Thiết kế Truyền tệp Đáng tin cậy qua TLS (Trọng tâm Thành viên 3)

### 4.1 Cấu trúc Manifest và Phân mảnh Chunk
Trước khi gửi tệp, `TransferManifest.from_file()` kiểm tra kích thước tệp trên ổ đĩa (`MAX_FILE_SIZE = 64 MiB`) rồi đọc theo luồng từng khối `64 KiB` để tính mã băm **SHA-256** toàn tệp mà không nạp toàn bộ tệp vào RAM.
- Kích thước mỗi mảnh mặc định `DEFAULT_CHUNK_SIZE = 65,536` byte (64 KiB nhị phân -> `87,384` ký tự Base64 ASCII), nằm an toàn dưới trần frame `1 MiB`, cho phép các bản tin chat và nhịp `ping/pong` xen kẽ mượt mà trên cùng một kết nối TLS.
- Tệp rỗng (`0 byte`) được hỗ trợ tự nhiên với `total_chunks = 0` và mã băm SHA-256 chuẩn của chuỗi rỗng.

### 4.2 Quy trình 4 giai đoạn và Điều tiết Luồng Bộ nhớ `O(1)`
1. **Chào mời (`Offered` - tối đa 60 giây):** Người gửi phát `file_offer` kèm `transfer_id`, `filename` đã làm sạch, `size`, `sha256`, `chunk_size`, `total_chunks`. Máy chủ kiểm tra hạn ngạch và đẩy `file_offer_event` sang người nhận.
2. **Xác nhận (`Accepted` - timeout treo 30 giây/chunk):** Khi người nhận gõ `/accept` (hoặc bật `--auto-accept`), `FileReceiver` tạo tệp tạm độc quyền `.<safe_name>.<transfer_id>.part` ở chế độ `"xb"` **trước khi** gửi `file_accept` lên máy chủ nhằm sẵn sàng đón chunk `0` ngay lập tức.
3. **Truyền luồng Chunk & Backpressure tự nhiên:** Người gửi truyền tuần tự `index = 0 .. total_chunks - 1` đồng thời kiểm tra lại kích thước và mã băm của tệp nguồn trong lúc đọc (phát hiện trường hợp tệp nguồn bị sửa đổi khi đang gửi). Trên máy chủ, `TransferCoordinator` xác thực độ dài giải mã của từng chunk rồi ghi thẳng `file_chunk_event` vào socket TLS của người nhận trước khi trả `file_chunk_result` về người gửi. Nhờ đó, cửa sổ TCP tự động điều tiết tốc độ gửi khớp với tốc độ nhận và máy chủ đạt mức tiêu thụ bộ nhớ đệm **`O(1)`** (không tích trữ nội dung tệp trên RAM hay đĩa của server).
4. **Đối chiếu Toàn vẹn & Hoàn tất Nguyên tử (`Verifying` - tối đa 15 giây):** Khi nhận `file_end_event`, `FileReceiver` đóng tệp `.part`, kiểm tra `bytes_received == size` và so sánh bộ băm SHA-256 tính tăng dần theo từng chunk với giá trị `sha256` trong manifest.
   - **Nếu khớp 100%:** đổi tên nguyên tử bằng `os.replace(part_path, final_path)` vào thư mục `downloads/` (tự động cấp tên `filename (1).ext` nếu trùng tên tệp cũ) và gửi `file_ack(ok=true)` để máy chủ báo `file_status(ok=true)` cho người gửi.
   - **Nếu sai lệch, quá hạn hoặc đứt kết nối:** đóng ngay file descriptor, xóa tức thì tệp `.part` (`unlink`) và thông báo lỗi cho phía còn lại. Tệp hỏng hoặc dở dang không bao giờ xuất hiện như tệp hoàn chỉnh.

{{DIAGRAM_SEQUENCE}}

---

## 5. Kiến trúc Bảo mật và Lưu trữ Mật khẩu (Trọng tâm Thành viên 3)

### 5.1 Bảo vệ Kênh truyền bằng TLS 1.2+ / TLS 1.3
- Máy chủ dùng `ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)` với phiên bản tối thiểu TLS 1.2.
- Trình khách dùng `ssl.create_default_context(cafile=...)`, bắt buộc xác minh chữ ký chứng chỉ (`CERT_REQUIRED`) và đối chiếu tên miền/IP trong trường `subjectAltName` (SAN). Kiểm thử tích hợp xác nhận trình khách từ chối ngay chứng chỉ giả mạo/không thuộc CA tin cậy.

### 5.2 Dẫn xuất Mật khẩu bằng `hashlib.scrypt` có Phiên bản Tham số
- Mỗi tài khoản khi đăng ký được sinh muối ngẫu nhiên `16 byte` từ `os.urandom(16)` và dẫn xuất khóa `32 byte` qua `hashlib.scrypt(n=16384, r=8, p=1)` (~16 MiB RAM làm việc mỗi lượt).
- Cơ sở dữ liệu SQLite (`UserStore`) lưu kèm cột `kdf_params` ở định dạng chuẩn hóa:
  `scrypt$v=1$n=16384$r=8$p=1$dklen=32`
- **Tương thích ngược & Tự động nâng cấp (Auto-Rehash):** Khi mở cơ sở dữ liệu cũ chưa có cột `kdf_params`, `UserStore` tự động migrate bảng. Khi người dùng đăng nhập thành công, nếu `needs_rehash()` phát hiện thông số lưu trữ cũ hơn chính sách hiện hành của máy chủ, hệ thống tự động dẫn xuất lại với salt mới + tham số mới và cập nhật SQLite một cách trong suốt.
- **Chống tấn công kênh kề và DoS:**
  - Dùng `hmac.compare_digest()` để so sánh thời gian hằng số.
  - Thực hiện phép tính `scrypt` giả với `_dummy_salt` khi tài khoản không tồn tại để che giấu thời gian phản hồi.
  - Giới hạn số phép tính KDF đồng thời trên máy chủ bằng `threading.BoundedSemaphore(8)` và đặt trần bộ nhớ `MAX_SCRYPT_MEMORY = 256 MiB` nhằm ngăn chặn tấn công làm cạn kiệt RAM khi bị gửi ồ ạt yêu cầu đăng nhập.

### 5.3 Phòng chống Leo thang Đường dẫn (Path Traversal) và Ký tự Độc hại
- Tầng giao thức từ chối mọi `filename` trên mạng chứa `/`, `\` hoặc `:`.
- `sanitize_filename()` chuẩn hóa Unicode NFC, loại bỏ ký tự điều khiển thuộc nhóm Unicode `C*` (ngăn chặn chuỗi ANSI escape làm sai lệch hiển thị terminal), cấm ký tự đặc biệt hệ thống tệp (`<>:"/\|?*`), chặn tên thiết bị dành riêng trên Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1..9`, `LPT1..9`) và giới hạn độ dài `<= 200` byte UTF-8 (đảm bảo cộng thêm tiền tố `.` + UUID + `.part` vẫn nhỏ hơn giới hạn `255` byte `NAME_MAX` của hệ thống tệp).
- `resolve_part_path()` và `allocate_non_colliding_path()` kiểm chứng lần cuối bằng `Path.resolve().is_relative_to(download_dir.resolve())` và kiểm tra cả symbolic link bị đứt (`is_symlink()`).

---

## 6. Thử thách Kỹ thuật Thực tế và Giải pháp Đã Triển khai

Trong quá trình phát triển và kiểm thử tích hợp đa luồng, nhóm (đặc biệt ở phần việc Thành viên 3) đã phát hiện và giải quyết triệt để 6 bài toán kỹ thuật thực tế:

| # | Thử thách kỹ thuật phát sinh | Nguyên nhân gốc rễ | Giải pháp kiến trúc đã áp dụng |
|---:|---|---|---|
| 1 | **Tự khóa cứng (Self-Deadlock) trên luồng đọc Client khi xác nhận tệp** | Luồng đọc `_receive_loop` gọi trực tiếp callback `on_event()`. Nếu `FileReceiver` gọi `connection.request("file_ack")` ngay bên trong `on_event()`, nó sẽ đứng chờ chính `_receive_loop` đọc bản tin trả lời. | Tách giao thức thành cặp Request/Response tức thì (có `request_id`) và Server Push Event (không có `request_id`); các phản hồi tự động (`file_ack`, `--auto-accept`) được đẩy sang worker thread có giới hạn `BoundedSemaphore`. |
| 2 | **Đua luồng TLS 1.3 `NewSessionTicket` làm treo `hello` khi tải 12+ clients trên Windows** | Ngay sau khi bắt tay TLS 1.3 hoàn tất trên OpenSSL 3.0, máy chủ gửi bản tin hậu bắt tay `NewSessionTicket`. Việc khởi chạy `_reader` (`SSL_read`) đồng thời đúng lúc gửi `hello` (`SSL_write`) trên cùng đối tượng `SSLSocket` gây xung đột trạng thái nội bộ trên Windows. | Thực hiện bước trao đổi đầu tiên `hello` -> `welcome` đồng bộ trên một luồng duy nhất ngay sau `wrap_socket()` (tiêu thụ sạch `NewSessionTicket`), sau đó mới khởi chạy `_reader` và `_keepalive`. Kết quả: chạy lặp liên tiếp tải 12 client đạt tỷ lệ thành công 100%. |
| 3 | **Đảo thứ tự khóa (AB-BA Deadlock) giữa UI và Bộ nhận tệp** | Luồng nhận chunk giữ `FileReceiver._lock` rồi gọi in tiến độ (cần `CommandLine._print_lock`), trong khi sự kiện mất mạng có thể giữ `_print_lock` rồi gọi `abort_all()` (cần `FileReceiver._lock`). | Thu thập snapshot `TransferProgress` bên trong khóa nhưng chỉ phát callback `on_progress` sau khi đã nhả `FileReceiver._lock`; đồng thời gọi `abort_all()` bên ngoài `_print_lock`. |
| 4 | **Đua tốc độ (Race Condition) khi bật `--auto-accept` tốc độ cao trên Localhost** | Chunk `0` hoặc quyết định `file_decision` từ đối tác có thể bay về tới client trước khi lời gọi `request("file_offer")` hoặc `request("file_accept")` kịp trả về trên luồng gọi. | Đăng ký trước bản ghi trạng thái vào bảng phiên và mở sẵn tệp `.part` độc quyền **trước khi** phát gói tin lên mạng; tự động thu dọn nếu máy chủ từ chối. |
| 5 | **Rò rỉ File Descriptor và tệp rác `.part` khi đứt mạng hoặc `file_end` lỗi** | Nếu người gửi ngắt kết nối đột ngột hoặc gửi `file_end` sai kích thước, phía người nhận sẽ giữ tệp `.part` mở nếu không nhận được tín hiệu hủy. | Bổ sung `TransferCoordinator.on_disconnect()`, phát `file_status(ok=false)` cho người nhận ngay cả khi `file_end` bị từ chối và chạy bộ dọn dẹp định kỳ theo đồng hồ đơn điệu (`time.monotonic()`) mỗi 1 giây. |
| 6 | **Lỗi khóa tệp SQLite (`WinError 32`) trên Windows** | Ngữ cảnh `with sqlite3.connect(...) as db:` trong Python chỉ đóng giao dịch (transaction) mà không đóng kết nối tệp vật lý, gây lỗi khi xóa thư mục tạm hoặc chuyển phiên. | Thống nhất bọc mọi truy vấn bằng `with closing(sqlite3.connect(...)) as db, db:` kết hợp `PRAGMA journal_mode=WAL`. |

---

## 7. Kết quả Kiểm thử Tự động và Mô phỏng Đa Trình khách

Hệ thống được phát triển theo quy trình **Test-Driven Development (RED -> GREEN -> REFACTOR)** với tổng cộng **38 bài kiểm thử tự động** (33 bài Unit Test và 5 bài Integration Test trên kết nối TLS thật):

- **Unit Tests (`tests/unit/` — 33/33 PASS trong ~1.5 giây):**
  - Đóng khung TCP 4 byte, từ chối frame rỗng/vượt ngưỡng 1 MiB, phát hiện EOF giữa frame.
  - Chuẩn hóa tên người dùng Unicode NFC, kiểm tra UUID và phiên bản envelope JSON.
  - Lưu trữ `ScryptParams`, tự động migrate SQLite cũ và tự động nâng cấp lại hash mật khẩu khi đăng nhập.
  - Chống Path Traversal đa nền tảng (`../../etc/passwd`, `..\..\Windows\win.ini`, `CON.txt`), tệp 0-byte, tệp nhiều chunk, chống ghi đè tên trùng, phát hiện tệp nguồn bị sửa khi đang gửi, hủy phiên `/cancel`, thu dọn phiên treo và kiểm thử toàn bộ tập lệnh CLI + UDP Discovery.
- **Integration Tests qua TLS 1.2+/1.3 thật (`tests/integration/` — 5/5 PASS trong ~4.0 giây):**
  - Từ chối kết nối khi chứng chỉ máy chủ không thuộc CA tin cậy (`ssl.SSLError`).
  - Truyền tệp nhị phân ngẫu nhiên nhiều chunk (`210,123` bytes) và tệp rỗng `0 byte` đầu-cuối qua TLS -> kích thước và mã băm SHA-256 khớp tuyệt đối.
  - Luồng từ chối `/reject` và tự động hủy khi hết hạn `offer_timeout`.
  - Đóng đột ngột kết nối của người gửi khi đang truyền dở chunk -> máy chủ thu hồi trạng thái, phía người nhận xóa sạch tệp `.part`, các người dùng khác vẫn tiếp tục chat bình thường.
  - **Mô phỏng tải đồng thời 12 trình khách TLS:** 12 người dùng kết nối và đăng nhập đồng thời, nhận tin nhắn broadcast chính xác tới 11 người nhận và thực hiện 3 luồng truyền tệp nhị phân 80 KB song song không xảy ra bất kỳ lỗi hay xung đột frame nào.
- **Độ phủ mã nguồn (Statement Coverage):** đạt **>82%** trên toàn bộ `src/collab/` (trong đó `crypto.py` đạt ~89%, `user_store.py` ~98%, `manifest.py` ~92.5%, `transfer_coordinator.py` ~88%, `sender.py` ~86%, `protocol.py` ~92.6%, `framing.py` & `tls.py` & `errors.py` đạt 100%).

---

## 8. Kết luận và Giới hạn Trong Phạm vi Đồ án

Hệ thống đã hoàn thiện đồng bộ từ tầng đóng khung raw socket, bảo mật kênh truyền TLS, quản lý mật khẩu `scrypt` có khả năng nâng cấp, khám phá dịch vụ UDP cho tới cơ chế truyền tệp phân mảnh có xác minh toàn vẹn SHA-256 và tự phục hồi sau sự cố mạng. Trong phạm vi môn học, máy chủ đóng vai trò nút trung gian được tin cậy (chưa áp dụng mã hóa đầu-cuối E2EE giữa hai trình khách) và chứng chỉ tự ký dùng cho mạng nội bộ cần được cấu hình tường minh qua tham số `--ca`.

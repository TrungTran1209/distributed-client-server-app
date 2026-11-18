# PROMPT CHO CODING AGENT — XÂY DỰNG ỨNG DỤNG DESKTOP GUI CHO HỆ THỐNG COLLABORATION CLIENT–SERVER

> **Mục tiêu:** Đọc và hiểu codebase hiện tại, sau đó triển khai một ứng dụng desktop có giao diện người dùng hoàn chỉnh để khởi chạy máy chủ (Host Server), kết nối với máy chủ (Join Server), đăng ký/đăng nhập, xem người dùng trực tuyến, nhắn tin và gửi/nhận tệp qua cơ chế chia chunk hiện có.
>
> **Yêu cầu quan trọng:** Đây là nhiệm vụ triển khai phần mềm thực tế. Không chỉ tạo mockup, prototype giao diện, hình minh họa hay tài liệu hướng dẫn. Các nút và màn hình phải kết nối với backend thật và thực hiện được nghiệp vụ tương ứng.

---

# 1. Vai trò và cách làm việc của bạn

Bạn là một **Senior Python Desktop Application Engineer** có kinh nghiệm về PySide6/Qt, TCP/TLS networking, concurrency, application architecture và UX.

Bạn đang làm việc trên một repository Python đã có backend cho ứng dụng cộng tác Client–Server. Nhiệm vụ của bạn là xây dựng một desktop GUI cho hệ thống đó, đồng thời tích hợp đầy đủ với các chức năng backend sẵn có.

Hãy làm theo thứ tự:

1. Đọc cấu trúc repository và các module liên quan trước khi sửa code.
2. Xác minh cách các class và API hiện tại hoạt động; không dựa hoàn toàn vào README nếu source code có khác biệt.
3. Lập kế hoạch triển khai ngắn gọn theo từng phần.
4. **Tiếp tục triển khai ngay**, không dừng lại ở việc đưa ra kế hoạch.
5. Chạy lại các test hiện có, bổ sung test cho phần mới và sửa lỗi phát sinh.
6. Cập nhật README với hướng dẫn cài đặt và sử dụng desktop application.

Không hỏi lại người giao nhiệm vụ những vấn đề đã có thể tự xác định bằng cách đọc source code. Nếu gặp lựa chọn kỹ thuật chưa được chỉ định, hãy chọn phương án hợp lý, ghi nhận trong tài liệu và tiếp tục.

Không được tự ý xóa hoặc làm hỏng chức năng CLI/backend đang hoạt động.

# 2. Bối cảnh dự án hiện tại

## 2.1. Ứng dụng đang giải quyết vấn đề gì?

Đây là ứng dụng cộng tác mạng nội bộ, trong đó nhiều người dùng chạy ứng dụng client và kết nối đến một máy chủ chung.

Người dùng cần có khả năng:

- Tạo tài khoản và đăng nhập.
- Xem những người đang trực tuyến.
- Gửi tin nhắn đến tất cả người dùng đang online.
- Gửi tin nhắn riêng cho một người dùng.
- Gửi tệp cho người dùng khác.
- Nhận lời mời gửi tệp và chấp nhận hoặc từ chối.
- Theo dõi tiến độ gửi/nhận tệp.
- Biết khi kết nối bị mất.
- Khởi chạy máy chủ để những người khác có thể kết nối vào.

Hiện tại backend có giao diện dòng lệnh (CLI). Mục tiêu của nhiệm vụ là bổ sung giao diện desktop trực quan, dễ sử dụng, để người dùng không phải thao tác bằng lệnh terminal.

## 2.2. Kiến trúc mạng cần giữ nguyên

Hệ thống hiện tại là **Client–Server tập trung**, không phải Peer-to-Peer.

```text
             +----------------------+
             |    Server Host       |
             |----------------------|
             | Authentication       |
             | Session Registry     |
             | Message Router       |
             | Transfer Coordinator |
             | SQLite User Store    |
             +----------+-----------+
                        |
             TCP + TLS / JSON framing
              /         |          \
             /          |           \
      +----------+ +----------+ +----------+
      | Client A | | Client B | | Client C |
      | Desktop  | | Desktop  | | Desktop  |
      +----------+ +----------+ +----------+
```

- Client không kết nối trực tiếp với client khác.
- Client kết nối đến server bằng TCP socket được bảo vệ bằng TLS.
- Server xác thực người dùng, quản lý session, cập nhật presence, định tuyến chat và chuyển tiếp file chunk.
- UDP được dùng cho server discovery và heartbeat phụ trợ.
- Mỗi kết nối client-server có TLS riêng.
- Server nhận dữ liệu từ client gửi rồi chuyển tiếp qua kết nối TLS của client nhận.

**Không thay thế kiến trúc hiện tại bằng HTTP, REST API, WebSocket hoặc P2P.** GUI framework chỉ đảm nhiệm giao diện người dùng. Các chức năng mạng tiếp tục sử dụng raw TCP socket, TLS và UDP như backend hiện có.

# 3. Công nghệ và nguyên tắc triển khai

## 3.1. Công nghệ đề xuất

- Python 3.11 trở lên.
- **PySide6 (Qt Widgets)** để xây dựng desktop GUI.
- Backend networking: tái sử dụng code hiện tại.
- SQLite: tiếp tục dùng để lưu tài khoản.
- TLS: giữ cơ chế xác minh certificate hiện tại.
- UDP: giữ cơ chế discovery/heartbeat hiện tại.

Có thể thêm PySide6 vào project dưới dạng optional dependency, ví dụ extra `desktop`:

```bash
python -m pip install -e ".[desktop]"
```

và cung cấp entry point để chạy ứng dụng desktop, ví dụ:

```bash
python -m collab.gui
```

Tên package/entry point thực tế có thể điều chỉnh theo cấu trúc codebase.

Không cần xây dựng web frontend hay backend HTTP.

## 3.2. Tách biệt giao diện và xử lý nghiệp vụ

Không viết toàn bộ logic network bên trong các lớp giao diện.

Đề xuất cấu trúc (điều chỉnh nếu repository có cấu trúc phù hợp hơn):

```text
src/collab/
├── client/                 # Backend client hiện có
├── common/                 # Protocol, framing, TLS, crypto...
├── server/                 # Backend server hiện có
├── transfer/               # Sender, receiver, manifest...
└── gui/
    ├── __init__.py
    ├── __main__.py         # Entry point desktop
    ├── app.py              # Khởi tạo QApplication
    ├── main_window.py      # Main window và điều hướng
    ├── controllers/
    │   ├── client_controller.py
    │   └── server_controller.py
    ├── workers/
    │   └── ...             # Background workers / Qt signals
    ├── views/
    │   ├── home_view.py
    │   ├── host_view.py
    │   ├── connect_view.py
    │   ├── auth_view.py
    │   ├── chat_view.py
    │   └── transfer_view.py
    ├── widgets/
    │   ├── user_list.py
    │   ├── message_bubble.py
    │   ├── transfer_item.py
    │   └── status_indicator.py
    └── styles/
        └── theme.qss
```

Đây là cấu trúc gợi ý, không phải yêu cầu phải tạo chính xác mọi file. Hãy tránh tạo quá nhiều lớp hoặc abstraction không cần thiết.

**Nguyên tắc bắt buộc về thread:**

- Không thực hiện network I/O có khả năng block trong UI/main thread.
- Server phải chạy ở background thread.
- Client connection/reader/keepalive tiếp tục chạy ở background theo cơ chế hiện có.
- Các thao tác có thể block như connect, register, login, gửi file, accept/reject file, stop server phải được chạy ngoài UI thread.
- Kết quả từ thread nền phải được chuyển về UI thông qua Qt signals/slots hoặc cơ chế thread-safe tương đương.
- Không cập nhật trực tiếp QWidget từ socket reader thread hoặc server worker thread.
- Đảm bảo đóng thread, socket và worker đúng cách khi người dùng đóng ứng dụng.

# 4. Các chức năng người dùng phải thao tác được

Ứng dụng nên có hai luồng sử dụng chính:

1. **Host Server:** người dùng khởi chạy máy chủ trên máy của mình.
2. **Join Server:** người dùng kết nối tới máy chủ có sẵn.

Người host cũng phải có khả năng sử dụng ứng dụng như một client bình thường. Sau khi khởi chạy server thành công, giao diện nên cho phép host kết nối vào server cục bộ để đăng nhập, chat và gửi/nhận tệp như những người khác.

## 4.1. Màn hình Home

Tạo màn hình mở đầu có tên ứng dụng, mô tả ngắn và hai lựa chọn chính:

- `Host a Server` — Khởi chạy máy chủ.
- `Join a Server` — Kết nối tới máy chủ.

Có khu vực hiển thị trạng thái hiện tại:

- Chưa kết nối.
- Đang khởi chạy server.
- Server đang hoạt động.
- Đang kết nối.
- Đã kết nối.
- Mất kết nối.

Có nút/đường dẫn đến phần cài đặt mạng hoặc hướng dẫn chứng chỉ TLS nếu cần.

## 4.2. Màn hình Host Server

Người dùng có thể khởi chạy server mà không cần tự gõ lệnh terminal.

Cung cấp form với các trường:

| Trường | Ý nghĩa | Giá trị mặc định/gợi ý |
|---|---|---|
| Bind address | Địa chỉ server lắng nghe | `0.0.0.0` để cho phép máy khác trong LAN kết nối |
| TCP port | Cổng TCP/TLS | `37021` |
| UDP port | Cổng discovery | `37020` |
| Advertise host | IP/hostname công bố cho client tìm thấy | Tự phát hiện hoặc cho phép nhập |
| Certificate file | Server certificate | Chọn file |
| Private key file | Private key tương ứng | Chọn file |
| Database path | File SQLite tài khoản | `data/users.sqlite3` |

Yêu cầu:

- Có nút `Browse` để chọn certificate và private key.
- Có lựa chọn tạo certificate demo nếu môi trường có OpenSSL phù hợp. Khi tạo certificate, phải có SAN khớp địa chỉ client sẽ dùng (localhost/IP LAN). Nếu không thể tạo tự động, cung cấp hướng dẫn rõ ràng.
- Không được tắt xác minh certificate để né lỗi SAN.
- Không bao giờ hiển thị private key dưới dạng nội dung văn bản, không ghi key/password vào log.
- Hiển thị lỗi dễ hiểu khi certificate không hợp lệ, file không tồn tại hoặc cổng đang được sử dụng.
- Có nút `Start Server` và `Stop Server`.
- Khi server chạy, hiển thị trạng thái, địa chỉ kết nối, TCP/UDP port và số người dùng online.
- Có log panel hoặc activity panel để hiển thị sự kiện quan trọng: server started/stopped, client connected/disconnected, lỗi bind port, lỗi TLS. Không hiển thị dữ liệu nhạy cảm.

### Quy tắc triển khai Host Server

Tái sử dụng các thành phần server hiện tại:

- `create_server_context(...)`
- `UserStore(...)`
- `AuthService(...)`
- `CollaborationServer(...)`
- `DiscoveryServer(...)`

Không khởi chạy lại server mỗi khi người dùng chuyển trang.

`CollaborationServer.serve_forever()` là hàm block; phải chạy trong background thread. `DiscoveryServer.start()` cần được gọi đúng vòng đời.

Xây dựng một lớp quản lý vòng đời server, ví dụ `ServerController` hoặc `ServerRuntime`, có API tương đương:

```python
start_server(config) -> None
stop_server() -> None
is_running() -> bool
wait_until_ready(timeout) -> bool
```

Nếu cần, bổ sung readiness event hoặc cơ chế báo lỗi startup cho `CollaborationServer`, nhưng phải giữ tương thích với CLI/backend hiện có.

Đảm bảo:

- UI chỉ hiển thị `Server running` sau khi listener TCP đã bind/listen thành công và UDP discovery đã khởi động.
- Nếu startup thất bại, hiển thị lỗi thật, không báo thành công giả.
- Khi stop: dừng UDP discovery, gọi server shutdown, đóng các socket/session và join thread có timeout hợp lý.
- Server không bị chạy trùng nhiều instance trong cùng cửa sổ.
- Host có thể nhấn nút `Connect to this server` để chuyển sang luồng client cục bộ (host/port đã được điền sẵn).

## 4.3. Màn hình Join Server

Cần hỗ trợ hai cách kết nối:

### Cách A — Nhập địa chỉ trực tiếp

- Host/IP.
- TCP port (mặc định `37021`).
- CA certificate file (tùy chọn, dùng khi server dùng CA/self-signed certificate riêng).
- Thư mục lưu file nhận (download directory).
- Nút `Connect`.

### Cách B — Tìm server trong mạng LAN

- Nút `Discover Servers`.
- Có thể chọn UDP unicast hoặc LAN broadcast.
- Hiển thị server tìm thấy: tên, host/IP, TCP port.
- Người dùng chọn một server rồi nhấn `Connect`.

Tái sử dụng `discover_server(...)` từ client discovery hiện có.

Phải giải thích rõ cho người dùng rằng UDP discovery chỉ tìm địa chỉ máy chủ. Sau đó ứng dụng vẫn phải kết nối TCP/TLS và xác minh certificate.

Không được bỏ xác minh certificate nếu discovery trả về địa chỉ không tin cậy.

Khi kết nối thất bại, hiển thị thông báo cụ thể và hành động khả thi, ví dụ:

- Không tìm thấy server.
- Server không phản hồi.
- Không thể kết nối tới host/port.
- Certificate không đáng tin cậy.
- Hostname/IP không khớp SAN.
- Server từ chối hoặc đóng kết nối.

## 4.4. Đăng ký và đăng nhập

Sau khi kết nối thành công:

- Hiển thị form đăng nhập.
- Username.
- Password (ẩn ký tự).
- Nút `Login`.
- Nút hoặc đường dẫn `Register`.

Đăng ký cần nhập password tối thiểu theo chính sách backend hiện có; không lưu password ở UI hoặc log.

Tái sử dụng `ClientConnection.request("register", ...)` và `ClientConnection.request("login", ...)`.

Hiển thị lỗi theo response thật:

- Sai thông tin đăng nhập.
- Username đã tồn tại.
- Username/password không hợp lệ.
- Tài khoản đang online ở session khác.
- Đã vượt số lần đăng nhập sai/đang bị rate limit.
- Server không phản hồi.

Không giả lập tài khoản ở frontend.

## 4.5. Main Chat Window

Sau khi đăng nhập, mở giao diện chat chính.

Đề xuất layout:

```text
+--------------------------------------------------------------+
| App Name       Connected to: 192.168.1.10:37021   [Online]   |
+--------------------+-----------------------------------------+
|                    |                                         |
| ONLINE USERS       |              CHAT AREA                  |
|                    |                                         |
| [All users]        |  Alice: Hi everyone                      |
|                    |                       Bob: Hello Alice   |
|  Alice             |                                         |
|  Bob               |                                         |
|  Charlie           |                                         |
|                    +-----------------------------------------+
|                    | [Type a message................] [Send]  |
+--------------------+-----------------------------------------+
| [Send file]     [Transfers]       [Settings]      [Logout]    |
+--------------------------------------------------------------+
```

### Khu vực user list

- Hiển thị username và trạng thái online.
- Hiển thị số người online.
- Chọn `All users` để broadcast.
- Chọn một username để chat riêng.
- Cập nhật realtime theo `user_list`, `presence_online`, `presence_offline`.

Backend hiện tại có sự khác biệt giữa snapshot và presence event:
- `user_list` có username, host, port.
- `presence_online`/`presence_offline` chỉ có username.

Không tự bịa IP/port khi nhận presence event. Có thể hiển thị `Online` nhưng địa chỉ là `Unknown` cho tới lần refresh snapshot tiếp theo.

### Khu vực chat

Hỗ trợ:

- Broadcast.
- Private message 1–1.
- Nhập nội dung và gửi.
- Nhấn Enter để gửi; Shift+Enter để xuống dòng nếu có ô nhập nhiều dòng.
- Hiển thị tên người gửi, nội dung và timestamp khi backend cung cấp.
- Phân biệt tin nhắn của mình và tin nhắn nhận được.
- Hiển thị lỗi gửi tin nhắn.
- Ngăn gửi nội dung rỗng hoặc vượt giới hạn 4.000 ký tự của backend.

Tái sử dụng `ClientConnection.request("chat_send", to=..., text=...)`.

**Không được tuyên bố tin nhắn đã được người nhận đọc hoặc chắc chắn đã được giao.** Backend hiện chỉ trả `chat_result` khi server xử lý yêu cầu định tuyến; chưa có read receipt hoặc delivery acknowledgement độc lập.

### Lịch sử tin nhắn

Hiện tại backend không có persistent message history:

- SQLite đang dùng để lưu thông tin tài khoản, không phải bảng tin nhắn.
- Chat message được định tuyến realtime, không được lưu thành lịch sử để truy vấn lại.
- Không có offline message queue.

Vì vậy:
- GUI có thể giữ các tin nhắn đã nhận trong bộ nhớ trong thời gian cửa sổ đang chạy.
- Phải ghi rõ đây là `Current session only` hoặc `Not saved`.
- Không tạo ra tuyên bố rằng lịch sử được đồng bộ/lưu trên server.
- Không tự ý thay đổi protocol hoặc thêm persistent chat history vào backend trong nhiệm vụ GUI này, trừ khi đó là thay đổi nhỏ, được tách riêng và có kiểm thử; ưu tiên giữ scope hiện tại.

## 4.6. Chức năng gửi và nhận file

Đây là yêu cầu quan trọng, cần tích hợp backend thật, không tạo progress bar giả.

### Gửi file

- Nút `Send File`.
- Mở file picker.
- Người dùng chọn recipient từ danh sách online.
- Hiển thị tên file, kích thước, người nhận.
- Nút `Send`.
- Hiển thị trạng thái chờ người nhận chấp nhận.
- Sau khi người nhận accept, bắt đầu truyền file.
- Hiển thị progress bar theo bytes/chunks thật.
- Hiển thị kết quả hoàn tất hoặc lỗi.
- Có nút `Cancel` khi transfer đang diễn ra.

Tái sử dụng `FileSender` và `TransferManifest`.

### Nhận file

Khi có `file_offer_event`:

- Hiển thị notification/dialog hoặc danh sách incoming transfer.
- Người gửi.
- Tên file.
- Kích thước.
- Số lượng chunk.
- Transfer ID rút gọn.
- Nút `Accept` và `Reject`.

Khi accept:

- Tạo file tạm `.part` trong download directory.
- Hiển thị tiến độ tải.
- Sau khi đủ dữ liệu, xác minh số chunk, kích thước và SHA-256.
- Chỉ khi hợp lệ mới đưa file thành file hoàn chỉnh.
- Hiển thị đường dẫn lưu file và nút mở thư mục chứa file.

Tái sử dụng `FileReceiver`.

### Cancel và timeout

- Người gửi/người nhận có thể hủy transfer.
- Hiển thị offer timeout, transfer timeout, peer disconnected, checksum mismatch, invalid chunk, file too large hoặc lỗi ghi file.
- Nếu transfer lỗi hoặc bị hủy, file `.part` phải được dọn theo logic hiện có.
- Không tự động coi transfer là hoàn thành khi sender chỉ gửi xong chunk; phải chờ receiver xác minh và phản hồi ACK/status cuối cùng.

### Thông số hiện tại cần giữ

Đọc lại constants trong `collab.common.protocol` trước khi hard-code. Hiện tại các giá trị dự kiến là:

- Chunk mặc định: 65,536 bytes (64 KiB).
- Chunk tối đa: 262,144 bytes (256 KiB).
- File tối đa: 67,108,864 bytes (64 MiB).
- TCP frame tối đa: 1 MiB.
- File dùng SHA-256 để xác minh tính toàn vẹn.
- Nội dung binary được Base64 encode trong JSON message.
- Server relay chunk tới recipient, không phải direct P2P.

UI cần hiển thị kích thước tệp thân thiện (KB/MB), số lượng chunk và phần trăm.

Không đọc toàn bộ file vào RAM nếu backend hiện tại đã stream theo chunk.

## 4.7. Transfer Center

Có thể xây dựng tab hoặc panel riêng để xem:

- Outgoing transfers.
- Incoming transfers.
- Waiting for acceptance.
- Transferring.
- Verifying.
- Completed.
- Rejected.
- Cancelled.
- Failed/Timeout.

Mỗi transfer nên có:
- File name.
- Peer (sender/receiver).
- Direction.
- Progress bar.
- Bytes sent/received.
- Status.
- Cancel button nếu có thể.

Không được cập nhật progress từ timer giả. Chỉ cập nhật từ callback/progress event của FileSender/FileReceiver.

# 5. Tích hợp backend — nơi cần đọc và tái sử dụng

Hãy kiểm tra source code thực tế trước khi gọi API. Danh sách dưới đây là bản đồ định hướng:

| Thành phần | Module hiện tại | Trách nhiệm |
|---|---|---|
| TCP/TLS server | `collab.server.server.CollaborationServer` | Nhận và xử lý nhiều kết nối client |
| Server startup | `collab.server.main` | Tạo TLS context, user store, auth service, server, discovery |
| UDP discovery server | `collab.server.discovery.DiscoveryServer` | Trả thông tin server khi client dò tìm |
| Client connection | `collab.client.connection.ClientConnection` | Kết nối TLS, gửi request, nhận events, ping/pong |
| Client discovery | `collab.client.discovery.discover_server` | Tìm server qua UDP |
| UDP heartbeat | `collab.client.discovery.UDPHeartbeat` | Heartbeat UDP phụ trợ |
| Authentication | `collab.server.auth.AuthService` | Đăng ký/đăng nhập |
| User persistence | `collab.server.user_store.UserStore` | SQLite account store |
| User sessions | `collab.server.sessions.SessionRegistry` | Quản lý online sessions |
| Chat routing | `collab.server.router.MessageRouter` | Broadcast/private routing |
| File transfer server | `collab.server.transfer_coordinator.TransferCoordinator` | Offer/accept/chunk relay/ACK/cancel |
| File sender | `collab.transfer.sender.FileSender` | Đọc file, tạo manifest, gửi chunks |
| File receiver | `collab.transfer.receiver.FileReceiver` | Nhận chunks, ghi `.part`, xác minh SHA-256 |
| File manifest | `collab.transfer.manifest.TransferManifest` | Metadata, chunk count, filename validation, SHA-256 |
| TLS helpers | `collab.common.tls` | Tạo SSL context |
| TCP framing | `collab.common.framing` | Length-prefix frame |
| Protocol | `collab.common.protocol` | JSON message types và constants |

GUI nên xây dựng controller/service layer để dùng các thành phần này.

Đặc biệt:
- `ClientConnection` hiện có callback `on_event`; GUI cần một dispatcher duy nhất để phân phối event đến FileSender, FileReceiver và Qt signal.
- `ClientConnection` có reader thread riêng và request correlation qua `request_id`.
- `FileSender`/`FileReceiver` có callback tiến độ và callback hoàn tất; chuyển callback sang Qt signals để update UI.
- Không tạo một socket connection riêng cho mỗi nút bấm.
- Một client đã đăng nhập nên dùng một `ClientConnection` ổn định cho các request chat/transfer.

# 6. Xử lý mất kết nối và vòng đời

GUI phải phản ánh đúng hành vi backend hiện tại.

## 6.1. Khi client mất kết nối

- Hiển thị banner hoặc dialog `Connection lost`.
- Cập nhật trạng thái connection thành disconnected.
- Disable các thao tác chat/file trong khi chưa kết nối.
- Abort các transfer local đang diễn ra và dọn file tạm thông qua API hiện có.
- Cho phép người dùng nhấn `Reconnect` thủ công.
- Khi reconnect thành công, phải đăng nhập lại nếu session cũ đã mất và tải lại user list.

**Không tự động retry gửi chat message** nếu không có cơ chế chống duplicate. Hành động gửi trước lúc mất kết nối có thể đã tới server nhưng client chưa nhận response; tự retry có thể gây gửi trùng.

## 6.2. Khi người dùng offline

- Xóa hoặc đổi trạng thái khỏi online list theo `presence_offline`.
- Nếu người nhận private message không online, hiển thị `recipient_unavailable`.
- Không lưu hàng đợi offline message vì backend hiện không hỗ trợ.
- Không tuyên bố tin nhắn sẽ được gửi sau khi người nhận online trở lại.

## 6.3. Khi server host stop

- Hỏi xác nhận trước khi dừng server nếu đang có client hoặc transfer.
- Dừng nhận kết nối mới.
- Dừng UDP discovery.
- Gọi `CollaborationServer.shutdown()`.
- Đóng các active sessions.
- Chờ server thread kết thúc.
- Cập nhật UI thành `Server stopped`.
- Nếu desktop app đồng thời đang làm client của server đó, xử lý trạng thái client disconnect đúng cách.

## 6.4. Không được tạo ra tính năng chưa có

Backend hiện không có:
- Automatic reconnection hoàn toàn tự động.
- Offline message queue.
- Persistent message history.
- Resume file transfer từ chunk đã nhận.
- End-to-End Encryption.
- P2P direct transfer.

GUI có thể hiển thị rõ các giới hạn này. Không được tạo nút có vẻ thực hiện chức năng nhưng thực chất không hoạt động.

# 7. Thiết kế giao diện và trải nghiệm người dùng

Yêu cầu giao diện:
- Desktop application hiện đại, sạch, rõ ràng, không giống demo bài tập sơ sài.
- Dùng Qt Widgets/PySide6.
- Có layout nhất quán, spacing hợp lý, typography dễ đọc.
- Có sidebar/navigator hợp lý.
- Có trạng thái hover, focus, disabled và loading.
- Có dialog xác nhận cho hành động phá hủy như Stop Server, Cancel Transfer, Logout.
- Không dùng emoji làm icon chính cho mọi nút.
- Có thể dùng SVG hoặc icon từ Qt/theme.
- Hỗ trợ kích thước cửa sổ tối thiểu hợp lý (ví dụ 1024x680) và không bị vỡ layout khi resize.
- Nên có theme sáng/tối hoặc ít nhất một theme hoàn chỉnh, nhất quán.
- Có thể hiển thị log/activity panel nhưng không làm giao diện chat trở nên rối.

Ưu tiên thao tác trực quan:
- User không phải biết `TCP`, `TLS`, `UDP`, `JSON`, `chunk` mới sử dụng được.
- Những thuật ngữ kỹ thuật có thể đưa vào trang `About / Connection Details`, không bắt buộc hiển thị trên các thao tác thường ngày.
- Dùng câu tiếng Việt dễ hiểu hoặc English UI nhất quán; ưu tiên tiếng Việt cho label/hướng dẫn nếu dự án hướng đến người dùng Việt Nam.
- Tên nút, trạng thái và thông báo phải nhất quán.

# 8. Bảo mật và độ tin cậy

Các nguyên tắc không được vi phạm:

1. Không tắt certificate verification để cho kết nối chạy được.
2. Không gửi password/chat/file qua UDP.
3. Không ghi password, private key hoặc dữ liệu nhạy cảm vào log.
4. Không lưu private key trong source code.
5. Không tạo hard-coded password hoặc tài khoản mặc định.
6. Không thay TLS bằng tự chế mã hóa.
7. Không tuyên bố E2EE.
8. Không coi UDP heartbeat là session authentication.
9. Không tin tưởng tên file hoặc path từ phía remote; tái sử dụng validation hiện tại.
10. Không báo file transfer complete trước khi receiver kiểm tra SHA-256 và trả kết quả.
11. Không block GUI thread.
12. Không nuốt exception quan trọng một cách âm thầm; ghi log an toàn và hiển thị lỗi phù hợp cho người dùng.

# 9. Kiểm thử và tiêu chí nghiệm thu

Không được kết luận hoàn thành chỉ vì ứng dụng mở được cửa sổ.

## 9.1. Kiểm thử backend regression

Giữ nguyên và chạy lại:

```bash
python -m unittest discover -s tests/unit -v
python -m unittest discover -s tests/integration -v
```

Sửa các lỗi regression do thay đổi gây ra.

## 9.2. Kiểm thử GUI/controller

Bổ sung test phù hợp cho:
- Server start/stop lifecycle.
- Startup failure (port occupied, missing/invalid cert).
- Client connect/disconnect.
- Login/register success/failure.
- Event dispatcher (user_list, presence, chat_message).
- Incoming file offer → accept/reject.
- File progress và completion callback.
- Client lost connection → abort transfer and UI state.
- Không cập nhật QWidget từ thread nền.

Có thể dùng Qt offscreen platform cho GUI tests nếu môi trường CI không có desktop.

## 9.3. Kịch bản nghiệm thu thủ công bắt buộc

### Scenario A — Host và local client

1. Mở ứng dụng.
2. Chọn `Host Server`.
3. Chọn/cấu hình certificate và key.
4. Nhấn `Start Server`.
5. Xác nhận UI báo server đang chạy.
6. Nhấn `Connect to this server`.
7. Đăng ký tài khoản host và đăng nhập.
8. Xác nhận vào được giao diện chat.

### Scenario B — Hai người chat

1. Mở instance desktop thứ hai.
2. Chọn `Join Server`.
3. Nhập địa chỉ hoặc dùng UDP discovery.
4. Cung cấp CA certificate nếu cần.
5. Đăng ký và đăng nhập tài khoản thứ hai.
6. Kiểm tra hai phía nhận sự kiện online.
7. Gửi broadcast và xác nhận các client khác nhận được.
8. Gửi private message và xác nhận đúng người nhận nhận được.

### Scenario C — Gửi file chia chunk

1. Chọn một file binary có kích thước lớn hơn 64 KiB.
2. Chọn một user đang online.
3. Gửi file.
4. Phía nhận thấy file offer và chọn Accept.
5. Kiểm tra progress bar tăng theo dữ liệu thực.
6. Kiểm tra hai phía nhận thông báo hoàn thành.
7. Kiểm tra file đầu ra có cùng kích thước và SHA-256 với file gốc.

### Scenario D — Từ chối và hủy file

1. Người gửi gửi file.
2. Người nhận chọn Reject.
3. Kiểm tra người gửi nhận trạng thái rejected.
4. Thực hiện transfer khác và hủy giữa chừng.
5. Kiểm tra trạng thái cancelled và file `.part` được dọn.

### Scenario E — Mất kết nối

1. Đang chat hoặc transfer thì đóng client hoặc ngắt kết nối mạng.
2. Kiểm tra client hiển thị disconnected/connection lost.
3. Kiểm tra server cập nhật presence offline.
4. Nếu đang nhận file, kiểm tra file `.part` không bị xem là file hoàn chỉnh và được dọn theo logic backend.
5. Kiểm tra client khác vẫn có thể chat nếu server vẫn hoạt động.
6. Kiểm tra người dùng có thể reconnect thủ công.

### Scenario F — Dừng server

1. Dừng server từ Host UI.
2. Kiểm tra các client nhận biết mất kết nối.
3. Kiểm tra server thread, UDP socket và TCP sockets được đóng.
4. Khởi chạy server lại và kết nối lại.

## 9.4. Definition of Done

Chỉ coi nhiệm vụ hoàn thành khi:

- [ ] Có desktop application chạy được bằng một command documented.
- [ ] Có Home screen và lựa chọn Host/Join.
- [ ] Host có thể start/stop server từ GUI.
- [ ] Host có thể sử dụng app như một client.
- [ ] Client kết nối được bằng địa chỉ trực tiếp.
- [ ] Client có thể discover server bằng UDP.
- [ ] Certificate validation vẫn hoạt động.
- [ ] Register/Login dùng backend thật.
- [ ] Online user list và presence event hoạt động.
- [ ] Broadcast chat hoạt động.
- [ ] Private chat hoạt động.
- [ ] File offer/accept/reject/cancel hoạt động.
- [ ] File được truyền chunk qua server relay.
- [ ] Progress bar phản ánh tiến độ thực.
- [ ] Receiver xác minh SHA-256 trước khi hoàn tất.
- [ ] Disconnect được phản ánh đúng trong GUI.
- [ ] Không có network I/O block GUI thread.
- [ ] Không phá vỡ CLI/backend hiện tại.
- [ ] Unit tests và integration tests hiện có vẫn pass.
- [ ] Có README hướng dẫn cài và chạy GUI.

# 10. Những điều KHÔNG được làm

- Không chỉ làm giao diện tĩnh với dữ liệu giả.
- Không thay backend bằng mock networking.
- Không xây dựng một server HTTP/REST mới.
- Không chuyển hệ thống sang WebSocket.
- Không thay kiến trúc sang P2P.
- Không xóa CLI entrypoint hiện tại.
- Không tự ý thay protocol message type/field nếu không cần thiết.
- Không thêm message history/offline queue/E2EE rồi tuyên bố đã có nếu chưa triển khai và kiểm thử đầy đủ.
- Không làm giả tiến độ truyền file.
- Không dùng `time.sleep()` trong UI thread.
- Không chặn UI bằng `connect()`, `request()`, `send_file()` hoặc `serve_forever()`.
- Không để exception của worker thread biến mất mà UI không biết.
- Không dừng công việc sau khi tạo skeleton. Phải hoàn thiện luồng nghiệp vụ end-to-end.

# 11. Deliverables cần bàn giao

Sau khi hoàn thành, hãy cung cấp:

1. Source code desktop GUI hoàn chỉnh.
2. Các controller/worker để tích hợp GUI với backend.
3. Các thay đổi dependency và entry point trong `pyproject.toml`.
4. README hướng dẫn cài đặt, tạo certificate, chạy Host, Join, chat và truyền file.
5. Unit/integration tests mới cho controller/lifecycle/UI quan trọng.
6. Báo cáo ngắn những file đã thêm/sửa, cách chạy ứng dụng, test đã chạy và kết quả thực tế.
7. Danh sách giới hạn còn tồn tại nếu có.

Khi báo cáo kết quả, phải phân biệt:
- Đã triển khai và đã kiểm thử.
- Đã triển khai nhưng chưa có kiểm thử đầy đủ.
- Chưa triển khai.

Không được tự nhận một test đã pass nếu chưa thực sự chạy test đó.

---

# 12. Yêu cầu cuối cùng dành cho agent

Hãy bắt đầu bằng việc kiểm tra repository và xác nhận API hiện tại của backend. Sau đó triển khai desktop GUI có thể sử dụng thực tế.

**Ưu tiên cao nhất:** một người dùng thông thường có thể mở ứng dụng, host server hoặc kết nối vào server, đăng nhập, nhìn thấy người dùng online, gửi/nhận chat và gửi/nhận file nhiều chunk qua giao diện đồ họa mà không cần sử dụng terminal cho các thao tác thường ngày.

Hãy giữ nguyên nền tảng networking hiện tại, xây giao diện và lớp điều phối phù hợp, hoàn thiện các luồng thực tế và kiểm thử chúng.

# Báo cáo kỹ thuật

## Ứng dụng cộng tác Client–Server phân tán qua Raw Sockets

**Phiên bản giao thức:** 1
**Ngôn ngữ:** Python 3.11+
**Môi trường mục tiêu:** localhost và mạng nội bộ (LAN)

---

## Tóm tắt

Tài liệu này trình bày thiết kế và cách triển khai một ứng dụng cộng tác Client–Server chạy trên TCP raw sockets. Ứng dụng hỗ trợ đăng ký và đăng nhập, danh sách người dùng trực tuyến, nhắn tin broadcast và riêng tư, cùng truyền tệp có kiểm tra toàn vẹn. Luồng TCP được bảo vệ bằng TLS; UDP được dùng để tìm máy chủ và gửi heartbeat phụ trợ. Giao thức ứng dụng dùng frame có tiền tố độ dài, payload JSON UTF-8 và mã tương quan cho các request/response. Mật khẩu được dẫn xuất bằng `scrypt` với salt riêng. Tệp được chia thành các chunk, chuyển tiếp qua máy chủ, ghi vào tệp tạm ở phía nhận và chỉ được đưa vào thư mục tải xuống sau khi kiểm tra kích thước và SHA-256.

Tài liệu mô tả hành vi thể hiện trực tiếp trong mã nguồn hiện có và tóm tắt phạm vi cùng kết quả chạy thực tế của bộ kiểm thử tự động trong repository.

## 1. Mục tiêu và phạm vi

Ứng dụng cung cấp một môi trường cộng tác tự lưu trữ cho nhiều client kết nối đến một server. Các mục tiêu kỹ thuật là:

- Dùng TCP raw sockets, không dựa vào HTTP framework hoặc WebSocket.
- Phục vụ nhiều client đồng thời và quản lý phiên đăng nhập trên server.
- Có giao thức ứng dụng tường minh, xử lý đúng ranh giới message trên TCP stream.
- Hỗ trợ đăng ký, đăng nhập, hiện diện người dùng, broadcast và nhắn tin riêng.
- Truyền tệp nhiều chunk, phát hiện dữ liệu thiếu hoặc sai, và dọn dẹp tệp chưa hoàn tất.
- Bảo vệ dữ liệu TCP bằng TLS và không lưu mật khẩu dạng rõ.
- Hỗ trợ dò tìm server qua UDP trong môi trường localhost/LAN.
- Cung cấp CLI để thao tác và quan sát trạng thái, tin nhắn, lời mời tệp và tiến độ truyền.

Ứng dụng là hệ thống cộng tác LAN ở quy mô đồ án. Server là bên trung gian tin cậy và có thể đọc nội dung sau khi kết thúc TLS của client. Hệ thống không triển khai mã hóa đầu-cuối giữa hai client, lưu trữ tin nhắn lâu dài, quản trị PKI doanh nghiệp hay mã hóa các tệp đã tải xuống trên đĩa.

### 1.1 Cơ sở đặc tả

Trong repository hiện tại không có tệp đề bài gốc riêng. Các yêu cầu được đối chiếu theo phần mô tả và rubric trong `TEAM_PLAN.md`, hướng dẫn sử dụng trong `README.md`, đặc tả giao thức trong `docs/protocol.md`, cùng hành vi có thể đọc được trong mã nguồn. Nếu giảng viên cung cấp văn bản đề bài khác, văn bản đó cần được dùng làm chuẩn cuối cùng khi nộp.

## 2. Kiến trúc hệ thống

Hệ thống có ba luồng chính:

1. **TCP/TLS:** kênh ứng dụng duy nhất cho bắt tay, đăng ký/đăng nhập, presence, chat và nội dung tệp.
2. **UDP:** dò tìm địa chỉ server và gửi heartbeat không xác thực. UDP không mang thông tin đăng nhập, tin nhắn hoặc dữ liệu tệp.
3. **Lưu trữ cục bộ:** SQLite giữ thông tin xác thực đã dẫn xuất; client lưu tệp nhận vào thư mục tải xuống được cấu hình.

### 2.1 Phân lớp mạng

Thiết kế đặt giao thức ứng dụng riêng lên trên transport, không thay TCP/UDP bằng framework tầng ứng dụng:

| Lớp/ranh giới | Cơ chế trong ứng dụng | Ý nghĩa |
|---|---|---|
| Ứng dụng | JSON protocol v1, request ID, message/event, manifest tệp | Định nghĩa ý nghĩa và trạng thái của dữ liệu cộng tác. |
| Bảo vệ luồng TCP | TLS qua `ssl.SSLContext` | Mã hóa và kiểm tra tính toàn vẹn từng kết nối TCP; không tạo kết nối ngang hàng. |
| Transport chính | TCP stream socket | Cung cấp luồng byte có thứ tự; không giữ ranh giới message ứng dụng. |
| Transport phụ | UDP datagram socket | Dùng cho discovery/heartbeat nhỏ, chấp nhận khả năng mất datagram. |
| Địa chỉ mạng | IPv4 host và port cấu hình | Phân biệt địa chỉ bind, địa chỉ quảng bá cho client và địa chỉ đích kết nối. |

TLS nằm phía trên TCP: handshake TLS hoàn tất trước khi gửi frame ứng dụng. UDP discovery độc lập với kết nối TCP và chỉ trả về một endpoint gợi ý. IP routing, ARP, firewall và cơ chế truyền lại TCP do hệ điều hành/mạng đảm nhiệm; ứng dụng không tự cài đặt lại các cơ chế này.

TCP và UDP được chọn cho hai nhu cầu khác nhau:

| Thuộc tính | TCP/TLS | UDP |
|---|---|---|
| Dạng dữ liệu | Luồng byte liên tục; framing do ứng dụng định nghĩa | Datagram giữ ranh giới từng gói nhỏ |
| Giao nhận | TCP đảm nhiệm thứ tự và truyền lại; ứng dụng vẫn xử lý EOF/timeout | Không bảo đảm giao nhận, thứ tự hoặc truyền lại |
| Bảo mật | TLS xác minh server và bảo vệ nội dung trên kết nối TCP | Không mã hóa/xác thực; chỉ gửi metadata discovery/heartbeat không nhạy cảm |
| Vai trò trong hệ thống | Chat, xác thực, presence, file control và chunk | Tìm endpoint server, heartbeat phụ trợ |

Một session TCP được xác định bởi endpoint hai đầu (địa chỉ IP và port cục bộ/đích). Client thường dùng port nguồn tạm do hệ điều hành cấp; `SessionRegistry` lưu địa chỉ peer mà server quan sát từ `accept()`. Nếu có NAT hoặc proxy, địa chỉ này có thể là địa chỉ đã được dịch, không nhất thiết là địa chỉ interface gốc của client.

{{DIAGRAM_ARCHITECTURE}}

| Thành phần | Module chính | Vai trò |
|---|---|---|
| Giao thức và tiện ích chung | `src/collab/common/` | Frame TCP, mã hóa/kiểm tra message, cấu hình TLS, KDF mật khẩu, schema UDP và lỗi chuẩn hóa. |
| Server | `src/collab/server/` | Chấp nhận socket, tạo phiên TLS, xử lý request, xác thực, theo dõi presence, định tuyến chat và điều phối truyền tệp. |
| Truyền tệp | `src/collab/transfer/` | Tạo manifest, chia chunk, làm sạch tên tệp, ghi tệp tạm, xác minh SHA-256 và hoàn tất lưu tệp. |
| Client | `src/collab/client/` | Kết nối TLS, ghép response theo request ID, nhận server event, chạy CLI và dò tìm server qua UDP. |
| Kiểm thử | `tests/unit/`, `tests/integration/` | Kiểm thử các đơn vị giao thức, lưu trữ, UDP, chuyển tệp và các luồng tích hợp TLS. |

Server mở listener TCP và tạo một worker thread xử lý từng kết nối được chấp nhận. Client có luồng đọc nền để nhận response/event, luồng keepalive TCP và các worker giới hạn cho một số thao tác truyền tệp bất đồng bộ. Cấu trúc này phù hợp với tải mô phỏng của bài tập; đây không phải thiết kế event loop hoặc hệ thống tải lớn.

## 3. Giao thức truyền thông trên TCP

### 3.1 Vì sao TCP cần framing ứng dụng

TCP cung cấp một luồng byte tin cậy và có thứ tự, không phải một chuỗi message. Một lần `sendall()` ở phía gửi có thể được nhận qua nhiều lần `recv()`; ngược lại, một lần đọc có thể chứa phần cuối frame trước và phần đầu frame tiếp theo. TCP xử lý phân mảnh, truyền lại segment bị mất và sắp xếp byte; nó không cho biết ranh giới JSON hoặc ranh giới một lần gọi `send()`.

Vì vậy ứng dụng dùng length-prefix framing. Header luôn được đọc trước payload; receiver không giải mã JSON cho đến khi đã thu đủ payload:

| Trường | Kích thước | Mô tả |
|---|---:|---|
| Độ dài payload | 4 byte | Số nguyên không dấu big-endian (`!I`). |
| Payload | 1 đến 1,048,576 byte | Một object JSON mã hóa UTF-8. |

`recv_exact()` tích lũy byte theo số lượng còn thiếu. Nếu peer đóng kết nối giữa header hoặc payload, việc đọc kết thúc bằng EOF thay vì giải mã một message không đầy đủ. Frame rỗng và frame vượt `MAX_FRAME_SIZE` bị từ chối trước khi cấp phát/đọc payload theo độ dài đó. Giới hạn 1 MiB cũng chặn một peer khai báo frame lớn bất thường.

### 3.2 Envelope, tương quan request và thứ tự xử lý

Message TCP là object JSON có trường `v` bằng `1` và trường `type`. Request từ client có `request_id` dạng UUID; response tương ứng trả cùng ID để client đánh thức đúng request đang chờ. Event do server đẩy, như presence, tin nhắn và sự kiện truyền tệp, được chuyển tới handler sự kiện của CLI.

Các nhóm message chính gồm:

- Kết nối: `hello`, `welcome`, `ping`, `pong`, `error`.
- Tài khoản và presence: `register`, `login`, `logout`, `user_list`, `presence_online`, `presence_offline`.
- Chat: `chat_send`, `chat_result`, `chat_message`.
- Truyền tệp: `file_offer`, `file_accept`, `file_reject`, `file_chunk`, `file_end`, `file_ack`, `file_cancel` cùng các response và event tương ứng.

Lớp protocol kiểm tra JSON, phiên bản envelope, kiểu message và định dạng UUID của request ID. Các handler nghiệp vụ tiếp tục kiểm tra loại và giới hạn của từng trường theo chức năng. Request ID dùng để ghép response với thao tác đang chờ; nó không phải số thứ tự TCP, không thay thế thứ tự chunk và không tự bảo đảm giao hàng đúng một lần.

### 3.3 Thiết lập kết nối TCP/TLS và bắt tay ứng dụng

Luồng kết nối có các bước riêng biệt:

1. Client mở TCP connection đến `(host, port)`.
2. Hai đầu hoàn tất TLS handshake; client kiểm tra chuỗi tin cậy và hostname/IP theo cấu hình SSL.
3. Client gửi frame `hello` có request ID; server chỉ chấp nhận `hello` là message ứng dụng đầu tiên.
4. Server trả `welcome` với cùng request ID và thông tin phiên bản/heartbeat.
5. Sau `welcome`, client bật reader thread để xử lý response và push event; keepalive thread TCP bắt đầu gửi `ping` định kỳ.

Tách bước hello/welcome đồng bộ khỏi reader thread bảo đảm chỉ có một luồng thao tác socket trong giai đoạn thiết lập giao thức. Server đặt timeout riêng cho TLS handshake và chờ hello để kết nối chưa xác thực không giữ worker vô hạn.

### 3.3.1 Đăng xuất và thu hồi phiên

CLI nhận lệnh `/logout` không có tham số và gửi request `logout` với request ID. Server trả `logout_result` thành công, gỡ session khỏi registry, hủy các phiên truyền tệp còn gắn với người dùng đó và phát `presence_offline` tới các client còn lại; phía client cũng dừng ngay các phiên gửi/nhận cục bộ, xóa tệp tạm `.part` dở dang và làm rỗng danh sách user online. Kết nối TCP vẫn tồn tại nhưng không còn được xác thực; các lệnh cần đăng nhập, như gửi chat, bị từ chối với `unauthorized`. `/quit` đóng client; quá trình đóng kết nối cũng gửi logout best-effort trước khi đóng socket. Mã lệnh nằm tại `src/collab/client/commands.py`, xử lý server tại `src/collab/server/server.py`.

### 3.4 Đồng thời đọc/ghi trên socket

Client dùng một reader thread duy nhất để lấy frame khỏi socket và phân phối theo `request_id`; response đánh thức đúng waiter, còn message không khớp waiter được xử lý như event. Các request có thể phát sinh từ UI, keepalive và worker truyền tệp, nên client dùng send lock để không interleave byte của hai frame.

Server tạo worker cho từng TCP connection. Nhiều hoạt động có thể gửi event tới cùng một session (chat, presence, transfer), vì vậy `Session.send_lock` tuần tự hóa `sendall()` của các frame đi cùng socket. Khóa này bảo vệ ranh giới frame ở tầng ứng dụng; nó không làm các thao tác ở các client khác trở thành tuần tự toàn cục. Khi send thất bại, server đóng socket để vòng xử lý kết nối thu hồi session.

### 3.5 Chat và định tuyến

Client gửi `chat_send` cùng nội dung và đích nhận. Server kiểm tra session đã đăng nhập, giới hạn nội dung chat và dùng router để chuyển message đến người nhận. Đích broadcast phân phối message đến các session online khác; đích riêng chỉ chuyển tới user cụ thể. Server trả `chat_result` cho người gửi và gửi `chat_message` như event đến người nhận.

## 4. Kết nối và vòng đời phiên

Client tạo TCP connection, thực hiện TLS handshake, gửi `hello` và chờ `welcome` đồng bộ trước khi bật luồng đọc nền. Bước handshake ứng dụng này giúp tránh để nhiều luồng đọc/ghi cạnh tranh trong giai đoạn khởi tạo TLS.

Server áp dụng timeout cho TLS handshake và giai đoạn chờ `hello`. Sau khi trao đổi `hello`/`welcome`, server xử lý các request trên worker của kết nối. Khi đăng nhập thành công, `SessionRegistry` liên kết username với phiên đang hoạt động và địa chỉ IP/cổng nguồn của socket như server quan sát được (qua NAT, đây có thể là endpoint đã được dịch). Server gửi danh sách user hiện tại cho client mới và phát `presence_online` cho các client khác. Đăng xuất hoặc mất kết nối sẽ thu hồi session, dừng các transfer liên quan và phát `presence_offline`.

TCP `ping`/`pong` được dùng làm keepalive ứng dụng (mỗi 30 giây); server áp dụng thời hạn trước xác thực mặc định 60 giây (`--auth-timeout`) và idle timeout cho phiên đã đăng nhập mặc định 90 giây (`--idle-timeout`, tương đương 3 chu kỳ heartbeat). Đây là cơ chế gắn với phiên TCP. UDP heartbeat không đăng nhập user, không cập nhật `SessionRegistry` và không thay thế keepalive TCP.

### 4.1 Bind, listen, accept và giới hạn kết nối

Server tạo `AF_INET/SOCK_STREAM` listener, bind vào host/port cấu hình, gọi `listen(64)` rồi lặp `accept()`. Backlog 64 là hàng đợi kết nối đang chờ hệ điều hành bàn giao cho ứng dụng; nó khác với giới hạn worker `max_clients` (mặc định 100). Khi đạt giới hạn worker, socket mới được đóng. Mỗi kết nối được chấp nhận có worker riêng để thực hiện TLS và đọc request; worker không đồng nghĩa với một tiến trình riêng.

Bind address quyết định interface nào nhận kết nối. `127.0.0.1` chỉ phục vụ máy cục bộ; `0.0.0.0` lắng nghe trên mọi IPv4 interface. Địa chỉ `0.0.0.0` không phải địa chỉ để client kết nối. Khi quảng bá discovery, server cần công bố IP có thể định tuyến tới client; có thể cấu hình `--advertise-host` nếu địa chỉ tự chọn không phù hợp. Cổng mặc định TCP `37021` và UDP `37020` cần được cho phép qua firewall trên máy server nếu demo qua LAN.

### 4.2 Timeout, ngắt kết nối và phục hồi

Timeout được dùng ở các pha khác nhau thay vì một deadline duy nhất: TCP connect/TLS setup, hello chưa xác thực, idle TCP session, offer tệp chưa được quyết định, transfer không có chunk mới và chờ xác nhận cuối. Thời gian dọn dẹp dùng đồng hồ monotonic để tránh sai lệch khi đồng hồ hệ thống đổi.

EOF, reset, TLS error hoặc lỗi framing làm đóng riêng kết nối đó. Server gỡ session, phát presence offline và hủy transfer liên quan; client đánh thức các request đang chờ với trạng thái mất kết nối và dọn file tạm. TCP phát hiện mất kết nối khi có thao tác I/O hoặc timeout; ứng dụng không thể biết tức thời một máy đã tắt nếu không có traffic/keepalive.

### 4.3 Backpressure trong relay tệp

Mỗi chunk đi qua chuỗi sender → TLS/TCP sender-server → coordinator → TLS/TCP server-recipient → receiver. Server xác thực index và kích thước chunk, sau đó gọi `sendall()` tới socket người nhận trước khi trả kết quả chunk cho người gửi. Vì sender chờ response của chunk trước khi gửi chunk kế tiếp, tốc độ được giới hạn bởi khả năng server ghi và người nhận đọc. Đây là backpressure phát sinh từ luồng TCP và mô hình request/response theo chunk; server không gom toàn bộ tệp vào RAM. Bộ nhớ trung gian vẫn phụ thuộc kích thước frame/chunk đang xử lý và overhead mã hóa Base64, không phải bằng không.

Sơ đồ trạng thái chi tiết được duy trì tại [`docs/state-diagrams.md`](../state-diagrams.md).

## 5. Đăng ký, xác thực và lưu trữ tài khoản

Server lưu tài khoản trong SQLite. Mật khẩu không được lưu nguyên văn; khi tạo tài khoản, hệ thống sinh salt ngẫu nhiên riêng và dùng `hashlib.scrypt` để dẫn xuất digest. Cấu hình mặc định trong `ScryptParams` là `n=16384`, `r=8`, `p=1`, độ dài digest 32 byte, salt 16 byte. Thông số được lưu theo chuỗi `kdf_params` để khi đăng nhập có thể diễn giải cách tạo digest.

Khi xác thực, server nạp salt, digest và cấu hình KDF từ kho dữ liệu, dẫn xuất lại rồi so sánh bằng `hmac.compare_digest()`. Nếu tài khoản không tồn tại, code thực hiện phép dẫn xuất giả nhằm giảm chênh lệch thời gian dễ quan sát. Mã nguồn có giới hạn tham số KDF và semaphore giới hạn số phép tính đồng thời. Schema SQLite cũ được migrate để bổ sung trường cấu hình KDF; đăng nhập thành công có thể kích hoạt cập nhật hash nếu cấu hình lưu đã lỗi thời.

Thông tin đăng nhập chỉ được gửi trong kết nối TLS. Log ứng dụng không nên chứa mật khẩu hoặc khóa riêng. SQLite có thể được lưu ở `data/users.sqlite3` theo cấu hình chạy; cơ sở dữ liệu runtime và chứng chỉ/khóa riêng không thuộc tài liệu công khai cần commit.

## 6. Bảo mật kênh mạng

Server tạo `SSLContext` ở chế độ server, đặt phiên bản tối thiểu TLS 1.2 và nạp certificate/private key do người vận hành cung cấp. Client tạo context tin cậy theo CA hệ thống hoặc CA tệp được chỉ định, với xác minh chứng chỉ và hostname/IP theo cơ chế mặc định của Python SSL context. Khi dùng chứng chỉ demo tự ký, client cần được cấu hình tin cậy chứng chỉ/CA đó và SAN phải khớp hostname/IP kết nối.

TLS bảo vệ tính bí mật và toàn vẹn trên từng kết nối TCP. Trong kiến trúc chuyển tiếp, server giải mã TLS từ người gửi rồi gửi message qua TLS riêng đến người nhận. Do đó server nằm trong miền tin cậy và có thể tiếp cận nội dung chat/tệp ở tầng ứng dụng. SHA-256 của tệp phát hiện sai lệch so với manifest nhưng không tạo ra E2EE hay xác thực danh tính người gửi độc lập với server.

## 7. Discovery và heartbeat UDP

UDP listener mặc định dùng cổng `37020`; TCP listener mặc định dùng cổng `37021`. Client gửi `discover` và nhận `server_announcement` gồm địa chỉ gợi ý, TCP port và ID server. Phản hồi này chỉ giúp tìm endpoint. Client vẫn phải kết nối TCP và xác minh certificate qua TLS trước khi tin cậy server.

Client cũng gửi `client_heartbeat` định kỳ và server có thể trả `heartbeat_ack`. Datagram được kiểm tra phiên bản/loại và giới hạn kích thước trong helper UDP. Do UDP không đảm bảo giao nhận, không mã hóa hay xác thực peer, các heartbeat này chỉ mang tính phụ trợ. Firewall hoặc router có thể chặn broadcast LAN; trong trường hợp đó có thể dùng địa chỉ server trực tiếp hoặc cấu hình broadcast/mạng phù hợp.

Discovery hiện dùng IPv4 UDP. Theo mặc định client gửi unicast tới `127.0.0.1`; chế độ LAN broadcast phải được bật rõ bằng `--broadcast`, khi đó socket đặt `SO_BROADCAST`. Có thể thay bằng unicast tới `--discover-host`. Client tạo request ID mới và chỉ nhận announcement khớp ID đó, giúp bỏ qua datagram cũ hoặc announcement không thuộc lần dò hiện tại. Client thử dò hữu hạn lần với timeout; nếu discovery không tìm thấy server nhưng người dùng đã chỉ định host TCP, chương trình tiếp tục dùng host/port đó.

UDP datagram bị giới hạn ở 1,200 byte và schema chỉ chấp nhận bốn loại message discovery/heartbeat. Việc giới hạn giúp datagram luôn nhỏ, tránh biến UDP thành kênh payload. Tuy nhiên, heartbeat UDP không có retry/ACK bắt buộc ở client; mất một datagram không đồng nghĩa session TCP đã mất. `heartbeat_ack` cũng không được dùng để xác thực user hoặc làm mới `SessionRegistry`.

## 8. Truyền tệp

### 8.1 Manifest và giới hạn

Trước khi gửi, client tạo manifest gồm `transfer_id`, tên tệp, kích thước, SHA-256, kích thước chunk và tổng số chunk. Code hiện quy định chunk mặc định 65,536 byte (64 KiB), chunk tối đa 262,144 byte (256 KiB), tệp tối đa 67,108,864 byte (64 MiB), tên tệp tối đa 200 ký tự/byte UTF-8 theo kiểm tra của manifest.

Kích thước và số chunk phải nhất quán. Tệp rỗng có 0 chunk và SHA-256 của nội dung rỗng. Sender đọc tệp theo khối và phát hiện trường hợp kích thước hoặc nội dung nguồn thay đổi trong khi gửi.

### 8.2 Luồng truyền

1. **Offer:** sender gửi manifest; server xác nhận người gửi, người nhận, giới hạn và trạng thái người nhận rồi phát lời mời cho client đích.
2. **Accept/reject:** người nhận chấp nhận hoặc từ chối. Khi chấp nhận, client mở tệp `.part` trước khi báo server để sẵn sàng nhận chunk.
3. **Chunk:** sender gửi tuần tự các chunk Base64 qua TCP/TLS. Server kiểm tra ID transfer, trạng thái, thứ tự index và độ dài dữ liệu rồi chuyển tiếp cho người nhận. Server không giữ toàn bộ tệp; dữ liệu được xử lý từng frame/chunk, nên bộ nhớ đệm phụ thuộc giới hạn chunk/frame thay vì tổng kích thước tệp.
4. **End và xác minh:** server kiểm tra tổng số chunk/kích thước đã chuyển, rồi thông báo kết thúc cho receiver. Receiver xác minh số byte, số chunk và SHA-256 so với manifest.
5. **Hoàn tất:** nếu hợp lệ, receiver đổi tên tệp tạm thành tên đích bằng thao tác thay thế nguyên tử, chọn tên không trùng để tránh ghi đè tệp sẵn có, rồi gửi `file_ack`. Server thông báo trạng thái cuối cho sender.

Offer, chunk rỗi và bước xác nhận có timeout riêng. Transfer có thể bị hủy bởi một trong hai phía; khi peer mất kết nối hoặc dữ liệu không hợp lệ, server phát trạng thái lỗi nếu còn session phía kia. Receiver đóng file handle và xóa `.part` khi hủy, timeout hoặc kiểm tra thất bại.

Ở tầng mạng, truyền tệp vẫn dùng cùng TCP/TLS session với chat và điều khiển. Mỗi chunk là một frame JSON riêng, dữ liệu nhị phân được Base64 hóa trước khi đưa vào JSON. Cách này tận dụng thứ tự và truyền lại của TCP, đồng thời giữ logic transfer rõ ràng ở tầng ứng dụng; đổi lại Base64 làm tăng kích thước dữ liệu và chunk quá lớn có thể cạnh tranh với các message khác trên cùng kết nối. Mã nguồn giới hạn chunk, file và frame để kiểm soát chi phí đó. Đây không phải UDP file transfer và không có giao thức resume sau khi reconnect; transfer bị hủy phải gửi lại từ đầu.

{{DIAGRAM_SEQUENCE}}

### 8.3 An toàn đường dẫn

Tên tệp nhận từ mạng được chuẩn hóa và làm sạch. Code từ chối tên rỗng/đặc biệt, ký tự điều khiển và ký tự không hợp lệ theo hệ thống tệp; chặn tên thiết bị dành riêng của Windows; không chấp nhận đường dẫn thư mục từ peer. Đường dẫn tạm và đích được tạo bên trong thư mục tải xuống đã cấu hình và được kiểm tra sau khi resolve. Tệp dở dang dùng hậu tố `.part`, không được coi là tệp hoàn chỉnh.

## 9. CLI và vận hành

CLI hỗ trợ các thao tác đăng ký/đăng nhập, `/logout`, `/users`, `/all`, `/msg`, `/file`, `/accept`, `/reject`, `/cancel`, `/help` và `/quit`. Client có thể kết nối bằng địa chỉ chỉ định hoặc dùng UDP discovery; tùy chọn `--ca` cấu hình CA tin cậy, `--download-dir` chọn nơi lưu tệp và `--auto-accept` bật nhận lời mời tự động.

Quy trình chạy tối thiểu:

1. Tạo certificate/key cho server với SAN khớp hostname hoặc IP mà client dùng.
2. Khởi động server bằng `python -m collab.server.main` và cung cấp `--cert`, `--key`; mặc định TCP là `37021`, UDP là `37020`.
3. Chạy từ hai client trở lên với CA tin cậy đúng, đăng ký/đăng nhập từng user.
4. Kiểm tra presence, gửi chat riêng/broadcast và gửi một tệp nhiều chunk.
5. Ở client nhận, chấp nhận lời mời và đối chiếu kích thước/SHA-256 tệp nhận nếu cần.

Các lệnh đầy đủ, ví dụ PowerShell và tùy chọn chứng chỉ nằm trong `README.md` và `certs/README.md`.

### 9.1 Kiểm tra kết nối khi demo LAN

Luồng kiểm tra mạng nên đi từ dưới lên để khoanh vùng lỗi:

1. Xác nhận server bind đúng interface và TCP listener đang mở trên port đã cấu hình.
2. Từ client, kiểm tra đường đi tới IP/port TCP; nếu dùng host LAN, không dùng `0.0.0.0` làm địa chỉ đích.
3. Kiểm tra firewall cho cả TCP port và UDP discovery port; hai port phục vụ hai luồng khác nhau.
4. Kiểm tra SAN của certificate khớp đúng hostname/IP client dùng. Lỗi trust hoặc hostname phải sửa CA/SAN, không tắt xác minh TLS.
5. Nếu TCP trực tiếp hoạt động nhưng discovery không tìm thấy server, kiểm tra broadcast domain, `--broadcast`, `--discover-host` và `--advertise-host` riêng; discovery thất bại không chứng minh TCP server bị lỗi.

Broadcast UDP thường chỉ được chuyển trong subnet/VLAN cục bộ và có thể bị access point, router hoặc firewall lọc. Ứng dụng không có service registry ngoài LAN, NAT traversal hoặc relay discovery qua internet.

## 10. Khả năng phục hồi và giới hạn

Hệ thống xử lý EOF, lỗi socket/TLS, timeout, frame sai, request không hợp lệ, người nhận offline, chunk sai thứ tự, dữ liệu quá giới hạn và checksum không khớp. Khi kết nối kết thúc, server dọn session và transfer liên quan; client dọn tệp nhận chưa hoàn tất. Các lỗi nghiệp vụ được trả về theo response/event để CLI có thể hiển thị.

Các giới hạn cần nêu khi trình diễn:

- Server là thành phần tin cậy; không có E2EE.
- UDP có thể mất/gửi trùng datagram và broadcast có thể bị chặn; nó không phải nguồn trạng thái phiên chính thức.
- Chứng chỉ tự ký phù hợp cho demo có cấu hình tin cậy tường minh, nhưng repository không triển khai cấp phát/thu hồi PKI.
- Tệp tải xuống được lưu ở dạng rõ theo quyền hệ điều hành; không có mã hóa dữ liệu at rest.
- Mô hình thread-per-client và giới hạn tài nguyên phù hợp phạm vi bài tập, chưa phải thiết kế chịu tải sản xuất.
- Tên người dùng/mật khẩu được quản lý ở mức chức năng đồ án; không nên xem hệ thống là dịch vụ xác thực công khai đã được harden đầy đủ.

## 11. Đối chiếu yêu cầu kỹ thuật và mã nguồn

Bảng dưới đây tóm tắt nơi có thể kiểm tra từng nhóm yêu cầu. Đây là đối chiếu giữa repository và các yêu cầu được ghi trong `TEAM_PLAN.md`; kết quả chạy thực tế được ghi riêng bên dưới.

| Nhóm yêu cầu | Hiện thực trong repository | Tệp tham khảo |
|---|---|---|
| Định nghĩa giao thức và frame TCP | Envelope version 1, JSON UTF-8, frame length-prefix 4 byte, giới hạn frame | `src/collab/common/protocol.py`, `framing.py`, `docs/protocol.md` |
| TCP handshake/TLS | Client gửi `hello`, nhận `welcome`; TLS tối thiểu 1.2 và xác minh phía client | `src/collab/client/connection.py`, `src/collab/common/tls.py` |
| Nhiều client và session | Listener chấp nhận kết nối, worker theo client, session registry, idle cleanup | `src/collab/server/server.py`, `sessions.py` |
| Đăng ký/đăng nhập/presence | SQLite user store, scrypt, login/logout, user list và presence event | `src/collab/server/auth.py`, `user_store.py`, `sessions.py` |
| Broadcast và direct message | Router định tuyến đến các session online | `src/collab/server/router.py` |
| Discovery/heartbeat UDP | Request/announcement và datagram heartbeat phụ trợ | `src/collab/client/discovery.py`, `src/collab/server/discovery.py` |
| Truyền tệp tin cậy | Manifest, chunk tuần tự, timeout, `.part`, xác minh SHA-256, cleanup | `src/collab/transfer/`, `src/collab/server/transfer_coordinator.py` |
| CLI và trải nghiệm chạy | Lệnh tương tác, presence, chat, transfer progress | `src/collab/client/commands.py`, `README.md` |
| Kiểm thử | 37 unit tests và 5 integration tests; trong đó có logout/cleanup/presence/ủy quyền sau logout và tải 12 client | `tests/unit/`, `tests/integration/` |

Ngày 11/11/2026, hai lệnh sau đã chạy trong môi trường làm việc này; cả hai đều kết thúc với mã thoát 0:

| Bộ kiểm thử | Kết quả thực tế |
|---|---|
| `python -m unittest discover -s tests/unit -v` | 37 tests, ~2.6 giây, `OK` |
| `python -m unittest discover -s tests/integration -v` | 5 tests, ~5.0 giây, `OK` |

Các ca kiểm thử logout trong `tests/unit/test_server_flow.py` và `tests/unit/test_transfer_engine.py` kiểm tra response `logout_result` thành công, thu hồi tiến trình gửi/tệp `.part` cục bộ trên client, phát `presence_offline` cho client còn lại và từ chối request sau đăng xuất bằng mã lỗi `unauthorized`. Integration suite cũng đạt các kịch bản TLS với chứng chỉ không tin cậy, truyền nhiều chunk/tệp rỗng, từ chối và timeout, ngắt kết nối giữa truyền tệp, cùng 12 client đồng thời. Độ phủ câu lệnh (statement coverage) trên toàn bộ `src/collab/` đạt 81.1% (vượt ngưỡng 80%).

## 12. Kết luận

Repository hiện triển khai một ứng dụng cộng tác client–server trên raw TCP sockets với TLS, giao thức JSON có framing rõ ràng, quản lý tài khoản/session, chat, UDP discovery và truyền tệp có xác minh đầu-cuối. Tổ chức module tách giao thức, server, client và transfer; các giới hạn về kích thước, timeout và tên đường dẫn làm rõ hành vi khi gặp đầu vào lỗi. Các sơ đồ kiến trúc, giao thức, trạng thái và sequence trong `docs/` bổ sung cho mã nguồn.

Khi hoàn thiện hồ sơ nộp, nhóm cần dùng kết quả chạy kiểm thử/coverage mới nhất thay cho số liệu cũ nếu có khác biệt, kiểm tra PDF được sinh từ đúng bản Markdown này, và đối chiếu báo cáo với đề bài gốc do môn học cung cấp.

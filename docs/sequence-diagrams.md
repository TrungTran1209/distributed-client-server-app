# Sơ đồ tuần tự

Các sơ đồ dưới đây phân biệt luồng đang có trong mã với luồng file chưa triển khai. Tên message giữ nguyên theo protocol để có thể tra trong code.

## Tìm server qua UDP rồi kết nối an toàn

```mermaid
sequenceDiagram
    participant C as Client
    participant U as Server discovery UDP
    participant T as Server TCP/TLS
    C->>U: discover(request_id)
    U-->>C: server_announcement(host, tcp_port)
    Note over C,T: Discovery chỉ trả địa chỉ gợi ý; client vẫn xác minh chứng chỉ TLS
    C->>T: TCP connect
    C->>T: TLS ClientHello
    T-->>C: Chứng chỉ server + TLS handshake
    Note over C: Client xác minh CA và hostname/IP
    C->>T: hello(request_id)
    T-->>C: welcome(request_id)
    loop Theo chu kỳ công bố trong welcome
        C->>T: ping(request_id)
        T-->>C: pong(request_id)
        C->>U: client_heartbeat(client_id)
        U-->>C: heartbeat_ack(client_id, server_id)
    end
    Note over C,U: UDP heartbeat không giữ phiên TCP và không đăng nhập user
```

## Đăng ký và đăng nhập

```mermaid
sequenceDiagram
    participant C as Client CLI
    participant T as Server TCP/TLS
    participant DB as SQLite tài khoản
    C->>T: register(request_id, username, password)
    Note over C,T: Password chỉ được gửi sau TLS
    T->>DB: Dẫn xuất và lưu salt + scrypt hash
    DB-->>T: Tạo tài khoản thành công/thất bại
    T-->>C: register_result(ok, code?)
    C->>T: login(request_id, username, password)
    T->>DB: Đọc salt/hash và kiểm tra password
    DB-->>T: Kết quả xác thực
    T-->>C: login_result(ok, session_id hoặc code)
    T-->>C: user_list(users, IP/cổng TCP peer)
    T-->>C: presence_online đến client khác (nếu có)
```

Đề gốc yêu cầu cơ chế đăng nhập; bước đăng ký và cách lưu tài khoản bằng `scrypt` là thiết kế bổ sung của nhóm.

## Gửi tin nhắn riêng hoặc broadcast

```mermaid
sequenceDiagram
    participant A as Client người gửi
    participant S as Server router
    participant B as Client người nhận
    A->>S: chat_send(request_id, to, text)
    alt to là username
        S->>S: Tìm session đang online của người nhận
        S-->>B: chat_message(from, to, text, sent_at, message_id)
    else to là null
        loop Mỗi client online khác người gửi
            S-->>B: chat_message(from, null, text, sent_at, message_id)
        end
    end
    S-->>A: chat_result(ok, message_id hoặc code)
```

`chat_result.ok=true` nghĩa là server đã định tuyến, không chứng minh người nhận đã đọc. Không có lưu lịch sử hoặc hàng đợi offline.

## Thoát hoặc mất kết nối

```mermaid
sequenceDiagram
    participant C as Client
    participant S as Server
    C->>S: logout(request_id)
    S-->>C: logout_result(ok=true)
    S->>S: Xóa session khỏi registry
    S-->>Các client khác: presence_offline(username)
    Note over C,S: Nếu EOF, timeout hoặc socket lỗi, server cũng xóa session và phát offline
```

## Truyền file

**Chưa triển khai đầu-cuối.** Các module `transfer/` hiện là khung; server trả `error(code=server_busy)` khi nhận `file_offer`, `file_chunk` hoặc `file_end`. Vì chưa có lifecycle đang chạy, tài liệu không mô tả một sequence thành công giả định. Khi tích hợp, cần bổ sung offer/accept/reject, chunk index/offset, checksum, phản hồi tiến độ, hành vi resume/cleanup và cập nhật sơ đồ theo code thực.

Sơ đồ dưới đây là **phác thảo để nhóm hoàn thiện theo yêu cầu đề**, không phải hợp đồng giao thức đã chốt hay tính năng có thể chạy. Tên message/field chỉ minh họa; Member 1–3 phải thống nhất schema trước khi triển khai.

```mermaid
sequenceDiagram
    participant A as Client gửi
    participant S as Server chuyển tiếp
    participant B as Client nhận
    A->>S: FILE_OFFER(metadata, transfer_id)
    S-->>B: FILE_OFFER(metadata, transfer_id)
    B-->>S: Chấp nhận hoặc từ chối (cần chốt message)
    S-->>A: Kết quả chấp nhận/từ chối
    loop Mỗi chunk nếu được chấp nhận
        A->>S: FILE_CHUNK(transfer_id, index, bytes)
        S->>B: FILE_CHUNK(transfer_id, index, bytes)
        B-->>S: ACK/progress (cần chốt)
        S-->>A: ACK/progress (cần chốt)
    end
    A->>S: FILE_END(transfer_id, kích thước, SHA-256)
    S->>B: FILE_END(transfer_id, kích thước, SHA-256)
    B->>B: Ghép chunk, kiểm tra kích thước và checksum
    B-->>S: FILE_RESULT(success/failure)
    S-->>A: FILE_RESULT(success/failure)
```

Tất cả message file khi triển khai phải đi trong kết nối TCP/TLS hiện có; không mở kênh UDP hoặc TCP không mã hóa riêng. Tên file phải được xử lý an toàn và nội dung chưa đủ/chưa kiểm checksum không được xem là file hoàn tất.

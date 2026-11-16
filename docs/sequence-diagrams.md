# Sơ đồ tuần tự (Sequence Diagrams)

Tài liệu này mô tả đầy đủ các luồng tương tác tuần tự đã triển khai trong mã nguồn, bao gồm: dò tìm máy chủ qua UDP, thiết lập kênh TCP/TLS, đăng ký/đăng nhập với `scrypt` có phiên bản tham số, nhắn tin broadcast/direct, truyền tệp tin cậy nhiều chunk và cơ chế tự phục hồi khi từ chối, quá hạn hoặc đứt kết nối. Tên bản tin khớp chính xác với `collab.common.protocol.MessageType`.

## 1. Tìm máy chủ qua UDP rồi kết nối TCP/TLS an toàn

```mermaid
sequenceDiagram
    participant C as Client CLI
    participant U as Server Discovery UDP
    participant T as Server TCP/TLS

    C->>U: discover(request_id)
    U-->>C: server_announcement(request_id, server_id, server_name, host, tcp_port)
    Note over C,T: Địa chỉ UDP chỉ là gợi ý; danh tính máy chủ phải được xác minh ở bước TLS
    C->>T: TCP connect
    C->>T: TLS Handshake (TLS 1.2+ / TLS 1.3)
    T-->>C: Chứng chỉ X.509 của Server
    Note over C: Xác minh chuỗi tin cậy CA và khớp SAN (hostname/IP)
    C->>T: hello(request_id, client, client_version)
    T-->>C: welcome(request_id, protocol_version=1, heartbeat_interval_sec=30)
    Note over C: Bắt tay ứng dụng hoàn tất trước khi mở luồng đọc nền để tránh xung đột TLS 1.3 NewSessionTicket

    loop Định kỳ theo heartbeat_interval_sec
        C->>T: ping(request_id)
        T-->>C: pong(request_id)
        C->>U: client_heartbeat(client_id)
        U-->>C: heartbeat_ack(client_id, server_id)
    end
```

## 2. Đăng ký, Đăng nhập và Nâng cấp tham số KDF `scrypt`

```mermaid
sequenceDiagram
    participant C as Client CLI
    participant T as Server AuthService
    participant DB as SQLite UserStore

    C->>T: register(request_id, username, password)
    Note over C,T: Mật khẩu chỉ truyền bên trong kết nối TLS đã xác minh
    T->>DB: Sinh salt ngẫu nhiên 16B + dẫn xuất scrypt + lưu kdf_params
    DB-->>T: Kết quả INSERT (thành công hoặc trùng username)
    T-->>C: register_result(request_id, ok, code?)

    C->>T: login(request_id, username, password)
    T->>DB: Đọc (salt, password_hash, kdf_params)
    alt Tài khoản không tồn tại
        DB-->>T: Dẫn xuất giả với dummy salt để giảm chênh lệch thời gian
        T-->>C: login_result(request_id, ok=false, code="invalid_credentials")
    else Tài khoản tồn tại và mật khẩu khớp (hmac.compare_digest)
        opt Tham số kdf_params cũ hơn cấu hình hiện tại (needs_rehash)
            T->>DB: Dẫn xuất lại salt mới + hash mới và UPDATE kdf_params
        end
        T->>T: Đăng ký phiên vào SessionRegistry (gắn IP và cổng TCP nguồn)
        T-->>C: login_result(request_id, ok=true, username, session_id)
        T-->>C: user_list(users=[{username, host, port}, ...])
        T-->>Các client khác: presence_online(username)
    end
```

## 3. Gửi tin nhắn riêng (Direct) và Broadcast

```mermaid
sequenceDiagram
    participant A as Client Người gửi
    participant S as Server MessageRouter
    participant B as Client Người nhận

    A->>S: chat_send(request_id, to, text)
    alt to là username cụ thể
        S->>S: Tra cứu phiên đang online của người nhận
        S-->>B: chat_message(message_id, from, to, text, sent_at)
        S-->>A: chat_result(request_id, ok=true, message_id)
    else to là null (broadcast)
        loop Mỗi phiên online khác người gửi
            S-->>B: chat_message(message_id, from, to=null, text, sent_at)
        end
        S-->>A: chat_result(request_id, ok=true, message_id)
    end
```

## 4. Truyền tệp Đáng tin cậy qua TCP/TLS (Luồng Thành công)

Toàn bộ luồng điều khiển và dữ liệu tệp đi qua kết nối TCP/TLS hiện có. Các request có `request_id` được phản hồi tức thì để không chặn luồng đọc nền `_receive_loop` trên client; các bản tin chuyển tiếp dùng server push event bất đồng bộ.

```mermaid
sequenceDiagram
    participant A as Client Gửi (FileSender)
    participant S as Server (TransferCoordinator)
    participant B as Client Nhận (FileReceiver)

    A->>A: Tính kích thước & SHA-256 streaming, chia total_chunks
    A->>S: file_offer(request_id, transfer_id, to, filename, size, sha256, chunk_size, total_chunks)
    S->>S: Kiểm tra tên tệp an toàn, giới hạn dung lượng, trạng thái online của B
    S-->>B: file_offer_event(transfer_id, from, filename, size, sha256, chunk_size, total_chunks, expires_in_sec=60)
    S-->>A: file_offer_result(request_id, ok=true, transfer_id)

    Note over B: Mở trước tệp tạm .<filename>.<transfer_id>.part trong download_dir
    B->>S: file_accept(request_id, transfer_id)
    S-->>B: file_accept_result(request_id, ok=true, transfer_id)
    S-->>A: file_decision(transfer_id, accepted=true, by)

    loop index = 0 .. total_chunks - 1
        A->>S: file_chunk(request_id, transfer_id, index, data_base64)
        S->>S: Kiểm tra thứ tự index & kích thước chunk (không lưu chunk trong RAM)
        S-->>B: file_chunk_event(transfer_id, from, index, data_base64)
        B->>B: Giải mã Base64, ghi trực tiếp vào .part, cập nhật SHA-256 tăng dần
        S-->>A: file_chunk_result(request_id, ok=true, transfer_id, index)
    end

    A->>S: file_end(request_id, transfer_id, size, sha256)
    S->>S: Đối chiếu tổng số chunk và tổng số byte đã chuyển tiếp
    S-->>B: file_end_event(transfer_id, from, size, sha256, total_chunks)
    S-->>A: file_result(request_id, ok=true, transfer_id, stage="verifying")

    B->>B: Đóng .part, kiểm tra bytes_received == size và SHA-256 khớp 100%
    B->>B: Đổi tên nguyên tử os.replace(.part -> tên đích không ghi đè)
    B->>S: file_ack(request_id, transfer_id, ok=true, sha256)
    S-->>B: file_ack_result(request_id, ok=true, transfer_id)
    S-->>A: file_status(transfer_id, ok=true, by, sha256)
```

## 5. Truyền tệp: Từ chối, Quá hạn (Timeout) và Phục hồi khi Lỗi / Đứt kết nối

```mermaid
sequenceDiagram
    participant A as Client Gửi (FileSender)
    participant S as Server (TransferCoordinator)
    participant B as Client Nhận (FileReceiver)

    alt Trường hợp 1: Người nhận từ chối (/reject)
        A->>S: file_offer(...)
        S-->>B: file_offer_event(...)
        S-->>A: file_offer_result(ok=true)
        B->>S: file_reject(request_id, transfer_id, reason)
        S-->>B: file_reject_result(request_id, ok=true, transfer_id)
        S-->>A: file_decision(transfer_id, accepted=false, code="rejected")
    else Trường hợp 2: Quá hạn chờ xác nhận (60s) hoặc treo luồng chunk (30s)
        S->>S: reap_expired() phát hiện phiên quá hạn
        S-->>A: file_status(transfer_id, ok=false, code="transfer_timeout")
        S-->>B: file_status(transfer_id, ok=false, code="transfer_timeout")
        B->>B: Đóng handle và xóa ngay tệp .part (nếu có)
    else Trường hợp 3: Sai mã băm SHA-256 khi kết thúc
        S-->>B: file_end_event(...)
        B->>B: Phát hiện SHA-256 lệch -> xóa ngay tệp .part
        B->>S: file_ack(request_id, transfer_id, ok=false, code="checksum_mismatch")
        S-->>B: file_ack_result(request_id, ok=true)
        S-->>A: file_status(transfer_id, ok=false, code="checksum_mismatch")
    else Trường hợp 4: Một bên mất kết nối đột ngột giữa chừng
        A--xS: EOF / Socket Reset / Timeout
        S->>S: on_disconnect(alice) thu hồi phiên truyền & phát presence_offline
        S-->>B: file_status(transfer_id, ok=false, code="peer_disconnected")
        B->>B: Đóng file descriptor và xóa sạch tệp .part dở dang
    end
```

## 6. Đăng xuất chủ động

```mermaid
sequenceDiagram
    participant C as Client CLI
    participant S as Server TCP/TLS

    C->>S: logout(request_id)
    S->>S: Hủy các phiên truyền tệp đang mở của user (nếu có)
    S->>S: Xóa phiên khỏi SessionRegistry
    S-->>C: logout_result(request_id, ok=true)
    S-->>Các client khác: presence_offline(username)
```

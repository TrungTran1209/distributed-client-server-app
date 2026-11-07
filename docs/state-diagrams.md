# Sơ đồ trạng thái (State Diagrams)

Các sơ đồ dưới đây mô tả máy trạng thái của kết nối Client TCP/TLS, Session phía Server, UDP Discovery và vòng đời Phiên Truyền tệp (`TransferCoordinator`, `FileSender`, `FileReceiver`) khớp trực tiếp với mã nguồn.

## 1. Kết nối Client TCP/TLS và Xác thực

```mermaid
stateDiagram-v2
    [*] --> Disconnected
    state "Mất kết nối" as Disconnected
    state "Đang kết nối TCP" as TCPConnecting
    state "Đang bắt tay TLS" as TLSHandshake
    state "Đang gửi hello" as AwaitWelcome
    state "Chưa đăng nhập" as Unauthenticated
    state "Đã đăng nhập" as Authenticated

    Disconnected --> TCPConnecting: connect()
    TCPConnecting --> TLSHandshake: TCP thành công
    TCPConnecting --> Disconnected: Lỗi socket / timeout
    TLSHandshake --> AwaitWelcome: Chứng chỉ & SAN hợp lệ
    TLSHandshake --> Disconnected: Lỗi xác minh TLS / timeout
    AwaitWelcome --> Unauthenticated: hello -> welcome (khởi chạy luồng đọc nền)
    AwaitWelcome --> Disconnected: Phản hồi sai / EOF
    Unauthenticated --> Unauthenticated: register / login thất bại / ping
    Unauthenticated --> Authenticated: login_result(ok=true) + user_list
    Authenticated --> Authenticated: chat, presence, ping/pong, truyền tệp
    Authenticated --> Unauthenticated: logout / logout_result
    Unauthenticated --> Disconnected: EOF / lỗi mạng
    Authenticated --> Disconnected: EOF / lỗi mạng (hủy mọi tệp .part dở dang)
```

## 2. Session phía Server

```mermaid
stateDiagram-v2
    [*] --> AcceptedTCP
    state "Socket TCP được accept" as AcceptedTCP
    state "Bắt tay TLS (10s)" as TLSHandshake
    state "Chờ hello" as AwaitHello
    state "Chưa xác thực" as Unauthenticated
    state "Đang online" as Online
    state "Đã đóng" as Closed

    AcceptedTCP --> TLSHandshake: wrap_socket(server_side=True)
    TLSHandshake --> AwaitHello: TLS thành công
    TLSHandshake --> Closed: Lỗi TLS / timeout 10s
    AwaitHello --> Unauthenticated: hello -> gửi welcome
    AwaitHello --> Closed: Sai message đầu / frame lỗi
    Unauthenticated --> Unauthenticated: register / login sai / ping
    Unauthenticated --> Online: login đúng -> thêm vào SessionRegistry
    Online --> Online: chat_send, file_*, ping
    Online --> Unauthenticated: logout -> thu hồi phiên file + phát presence_offline
    Unauthenticated --> Closed: EOF / lỗi mạng / idle timeout
    Online --> Closed: EOF / lỗi mạng / idle timeout 90s -> thu hồi phiên file + phát presence_offline
    Closed --> [*]
```

## 3. Vòng đời Phiên Truyền tệp trên Server (`TransferCoordinator`)

```mermaid
stateDiagram-v2
    [*] --> Offered: file_offer hợp lệ
    state "Chờ xác nhận (timeout 60s)" as Offered
    state "Đang truyền chunk (idle 30s)" as Accepted
    state "Chờ file_ack SHA-256 (15s)" as Verifying
    state "Hoàn tất" as Completed
    state "Đã hủy / Thất bại" as Aborted

    Offered --> Accepted: file_accept từ người nhận -> đẩy file_decision(accepted=true)
    Offered --> Aborted: file_reject / file_cancel / timeout 60s / mất kết nối
    Accepted --> Accepted: file_chunk(index tuần tự, đúng độ dài) -> đẩy file_chunk_event
    Accepted --> Verifying: file_end(khớp tổng số chunk & size) -> đẩy file_end_event
    Accepted --> Aborted: chunk lỗi / file_cancel / treo >30s / mất kết nối
    Verifying --> Completed: file_ack(ok=true) -> đẩy file_status(ok=true)
    Verifying --> Aborted: file_ack(ok=false) / timeout 15s / mất kết nối
    Completed --> [*]
    Aborted --> [*]
```

## 4. Vòng đời Nhận tệp phía Client (`FileReceiver`)

```mermaid
stateDiagram-v2
    [*] --> PendingOffer: Nhận file_offer_event hợp lệ
    state "Chờ người dùng /accept hoặc /reject" as PendingOffer
    state "Đang ghi tệp tạm .part" as ReceivingPart
    state "Đang kiểm tra SHA-256 & kích thước" as VerifyingHash
    state "Lưu tệp hoàn chỉnh" as Saved
    state "Đã dọn tệp tạm (.part bị xóa)" as CleanedUp

    PendingOffer --> ReceivingPart: /accept hoặc --auto-accept (mở .part trước khi gửi file_accept)
    PendingOffer --> CleanedUp: /reject / hết hạn / mất kết nối
    ReceivingPart --> ReceivingPart: file_chunk_event hợp lệ -> ghi đĩa + cập nhật SHA-256
    ReceivingPart --> VerifyingHash: file_end_event
    ReceivingPart --> CleanedUp: Chunk lỗi / file_cancel / timeout / mất kết nối -> đóng & xóa .part
    VerifyingHash --> Saved: Kích thước & SHA-256 khớp -> os.replace(.part -> tên đích) + gửi file_ack(ok=true)
    VerifyingHash --> CleanedUp: Lệch SHA-256 hoặc size -> xóa .part + gửi file_ack(ok=false)
    Saved --> [*]
    CleanedUp --> [*]
```

## 5. Discovery UDP (Độc lập với Session TCP)

```mermaid
stateDiagram-v2
    [*] --> ChuaTimThay
    state "Chưa tìm thấy server" as ChuaTimThay
    state "Đã nhận địa chỉ gợi ý" as DaTimThay
    state "Đang kết nối TCP/TLS" as DangKetNoi

    ChuaTimThay --> DaTimThay: discover / server_announcement
    ChuaTimThay --> ChuaTimThay: Timeout hoặc broadcast bị chặn
    DaTimThay --> DangKetNoi: Mở kết nối TCP và xác minh chứng chỉ TLS
    DangKetNoi --> DaTimThay: Kết nối lỗi; địa chỉ UDP vẫn chỉ là gợi ý
```

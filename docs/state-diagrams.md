# Sơ đồ trạng thái

Các sơ đồ dưới đây mô tả trạng thái TCP/TLS và UDP đang có trong mã. Tên message trong code được giữ nguyên để dễ tìm kiếm. File transfer chưa có trạng thái hoạt động.

## Client TCP/TLS và đăng nhập

```mermaid
stateDiagram-v2
    [*] --> Disconnected
    state "Mất kết nối" as Disconnected
    state "Đang kết nối TCP" as TCPConnecting
    state "Đang bắt tay TLS" as TLSHandshake
    state "Chờ hello" as AwaitHello
    state "Chưa đăng nhập" as Unauthenticated
    state "Đã đăng nhập" as Authenticated
    Disconnected --> TCPConnecting: connect
    TCPConnecting --> TLSHandshake: TCP connected
    TCPConnecting --> Disconnected: connect error / timeout
    TLSHandshake --> AwaitHello: TLS established and certificate accepted
    TLSHandshake --> Disconnected: TLS error / 10s timeout
    AwaitHello --> Unauthenticated: hello / welcome
    AwaitHello --> Disconnected: sai message đầu / frame error / timeout
    Unauthenticated --> Unauthenticated: register / register_result
    Unauthenticated --> Unauthenticated: login rejected / login_result false
    Unauthenticated --> Authenticated: login accepted / login_result true + user_list
    Unauthenticated --> Unauthenticated: ping / pong
    Authenticated --> Authenticated: chat_send / chat_result
    Authenticated --> Authenticated: chat_message hoặc presence event
    Authenticated --> Authenticated: ping / pong định kỳ
    Authenticated --> Authenticated: file request / server_busy
    Authenticated --> Unauthenticated: logout / logout_result
    Unauthenticated --> Disconnected: EOF / socket error / idle timeout
    Authenticated --> Disconnected: EOF / socket error / idle timeout
```

## Session phía server

```mermaid
stateDiagram-v2
    [*] --> AcceptedTCP
    state "Socket TCP được accept" as AcceptedTCP
    state "Bắt tay TLS" as TLSHandshake
    state "Chờ hello" as AwaitHello
    state "Chưa xác thực" as Unauthenticated
    state "Đang online" as Online
    state "Đã đóng" as Closed
    AcceptedTCP --> TLSHandshake: worker bọc socket bằng TLS
    TLSHandshake --> AwaitHello: TLS thành công
    TLSHandshake --> Closed: TLS lỗi / timeout 10 giây
    AwaitHello --> Unauthenticated: hello / gửi welcome
    AwaitHello --> Closed: message đầu sai / frame lỗi
    Unauthenticated --> Unauthenticated: register / gửi register_result
    Unauthenticated --> Unauthenticated: login fail / gửi login_result false
    Unauthenticated --> Online: login thành công / tạo session
    Online --> Online: chat, ping, TCP traffic hợp lệ
    Online --> Unauthenticated: logout / xóa session / thông báo offline
    Unauthenticated --> Closed: EOF / socket lỗi / timeout
    Online --> Closed: EOF / socket lỗi / idle timeout / xóa session
    Closed --> [*]
```

`Online` tương ứng entry trong session registry, chỉ tạo sau khi đăng nhập thành công. Server xóa entry trước khi báo `presence_offline`, nên logout sau đó đóng socket không phát offline hai lần. Idle timeout mặc định 90 giây; client gửi TCP `ping` định kỳ. UDP heartbeat không làm thay đổi trạng thái session.

## Discovery UDP (độc lập với session TCP)

```mermaid
stateDiagram-v2
    [*] --> ChuaTimThay
    state "Chưa tìm thấy server" as ChuaTimThay
    state "Đã nhận địa chỉ gợi ý" as DaTimThay
    state "Đang dùng TCP/TLS" as DangKetNoi
    ChuaTimThay --> DaTimThay: discover / server_announcement
    ChuaTimThay --> ChuaTimThay: timeout hoặc broadcast bị chặn
    DaTimThay --> DangKetNoi: TCP connect rồi xác minh TLS
    DangKetNoi --> DaTimThay: kết nối lỗi; địa chỉ vẫn chỉ là gợi ý
```

Client cũng gửi `client_heartbeat` và server trả `heartbeat_ack`; server không gắn `client_id` với tài khoản và không dùng datagram này để giữ user online.

## File request hiện tại

```mermaid
stateDiagram-v2
    [*] --> Authenticated
    state "Đã đăng nhập" as Authenticated
    Authenticated --> Authenticated: file_offer / file_chunk / file_end
    note right of Authenticated: server trả error code server_busy; không tạo transfer state
```

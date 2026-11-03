# Sơ đồ trạng thái đang được hiện thực

Các sơ đồ mô tả behavior hiện tại của server theo [`protocol.md`](protocol.md). File transfer chưa có lifecycle hoạt động; các request file hiện nhận `server_busy`.

## Client TCP/TLS và xác thực

```mermaid
stateDiagram-v2
    [*] --> Disconnected
    Disconnected --> TCPConnecting: connect
    TCPConnecting --> TLSHandshake: TCP connected
    TCPConnecting --> Disconnected: connect error / timeout
    TLSHandshake --> AwaitHello: TLS established and certificate accepted
    TLSHandshake --> Disconnected: TLS error / 10s timeout
    AwaitHello --> Unauthenticated: hello / welcome
    AwaitHello --> Disconnected: first message is not hello / frame error / timeout
    Unauthenticated --> Unauthenticated: register / register_result
    Unauthenticated --> Unauthenticated: login rejected / login_result false
    Unauthenticated --> Authenticated: login accepted / login_result true + user_list
    Unauthenticated --> Unauthenticated: ping / pong
    Unauthenticated --> Unauthenticated: unsupported request / unauthorized or invalid_message
    Authenticated --> Authenticated: chat_send / chat_result
    Authenticated --> Authenticated: receive chat_message or presence event
    Authenticated --> Authenticated: ping / pong
    Authenticated --> Authenticated: file request / server_busy
    Authenticated --> Unauthenticated: logout / logout_result
    Unauthenticated --> Disconnected: EOF / socket error / idle timeout
    Authenticated --> Disconnected: EOF / socket error / idle timeout
```

Lỗi envelope/framing đóng kết nối. Lỗi ở payload nghiệp vụ có thể trả `error` nhưng giữ kết nối mở. Một `login_result` thành công được theo sau bởi `user_list`; các event presence có thể đến sau đó.

## Server session

```mermaid
stateDiagram-v2
    [*] --> AcceptedTCP
    AcceptedTCP --> TLSHandshake: worker wraps socket
    TLSHandshake --> AwaitHello: TLS success
    TLSHandshake --> Closed: TLS error / 10s timeout
    AwaitHello --> Unauthenticated: hello / send welcome
    AwaitHello --> Closed: first message is not hello / malformed frame
    Unauthenticated --> Unauthenticated: register / send register_result
    Unauthenticated --> Unauthenticated: login failure / send login_result false
    Unauthenticated --> Online: login success / add session and send user_list
    Online --> Online: chat, ping, valid TCP traffic
    Online --> Unauthenticated: logout / remove session / send offline to peers
    Unauthenticated --> Closed: EOF / socket error / timeout
    Online --> Closed: EOF / socket error / idle timeout / remove session and send offline
    Closed --> [*]
```

`Online` là entry trong registry server, chỉ được tạo sau login thành công. Cleanup xóa entry trước khi phát `presence_offline`, nên logout rồi đóng socket không phát offline lần hai. Idle timeout mặc định là 90 giây. UDP heartbeat không làm thay đổi trạng thái session.

## UDP discovery (độc lập với session TCP)

```mermaid
sequenceDiagram
    participant C as Client UDP
    participant D as Server discovery
    C->>D: discover (request_id)
    D-->>C: server_announcement (host, tcp_port)
    C->>D: client_heartbeat (client_id)
    D-->>C: heartbeat_ack
    Note over C,D: UDP không đăng nhập và không tạo hoặc duy trì user session
```

## File request hiện tại

```mermaid
stateDiagram-v2
    [*] --> Authenticated
    Authenticated --> Authenticated: file_offer / file_chunk / file_end
    note right of Authenticated: Server trả error code server_busy; không tạo transfer state
```

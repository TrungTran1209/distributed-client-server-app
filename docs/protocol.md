# Giao thức ứng dụng

Phiên bản giao thức là `1`. Tài liệu này mô tả hành vi hiện có trong code. Những mục ghi **Chưa triển khai** là phần dự kiến của giao thức, chưa được server xử lý thành công.

Đặc tả bài tập yêu cầu nhóm tự thiết kế packet/message và yêu cầu các chức năng mạng nêu trong rubric; các tên message, JSON, framing 4 byte, TLS, cổng mặc định và trường cụ thể dưới đây là thiết kế hiện thực của nhóm. Đề không bắt buộc phải dùng chính những tên/trường này. Phần transfer là dự kiến, không phải chức năng đã có.

## 1. Kênh kết nối và framing

- Ứng dụng dùng TCP raw socket được bọc TLS. TLS phải hoàn tất trước message ứng dụng; server và client đặt TLS tối thiểu là 1.2. Client phải xác minh chứng chỉ và hostname theo trust store đã cấu hình.
- Mặc định server nghe TCP `37021`, UDP discovery `37020`; có thể cấu hình khi chạy server.
- Mỗi message TCP là một frame: 4 byte unsigned big-endian chứa độ dài payload, sau đó là payload JSON UTF-8. Độ dài tính theo byte, từ 1 đến 1,048,576 byte. Không có delimiter.
- Người nhận đọc đủ header và payload; một lần `recv()` không đồng nghĩa với một frame. Message được mã hóa JSON compact, UTF-8.
- Frame rỗng/quá giới hạn, JSON sai, sai version hoặc envelope không hợp lệ làm server đóng kết nối. Lỗi khi xử lý trường nghiệp vụ (ví dụ chat sai định dạng) trả `error` và giữ kết nối mở nếu có thể.

## 2. Envelope

```json
{"v":1,"type":"login","request_id":"UUID","username":"alice","password":"..."}
```

- `v` là integer bằng `1`; `type` là chuỗi. Hai trường luôn bắt buộc.
- Request TCP thuộc loại `hello`, `register`, `login`, `logout`, `chat_send`, `file_offer`, `file_chunk`, `file_end`, `ping` cần có `request_id` là UUID. Response tương ứng sao chép ID; server events không cần ID.
- Decoder kiểm tra envelope và cú pháp UUID, nhưng việc kiểm tra các trường payload được thực hiện trong xử lý từng loại message. Message type không được hỗ trợ trả `error` với `code:"invalid_message"`.
- Server không gửi password vào response hoặc log. Message có thể được gửi xen kẽ theo event server; các lần ghi trên session đã xác thực được khóa để tránh trộn bytes của hai frame.

## 3. TCP messages đã hoạt động

### 3.1 Bắt đầu phiên và đăng ký

Sau TLS, `hello` phải là message đầu tiên. Server phản hồi `welcome`; nếu message đầu tiên khác, server gửi `error` rồi đóng kết nối.

```json
{"v":1,"type":"hello","request_id":"UUID","client":"collab-cli","client_version":"1.0"}
{"v":1,"type":"welcome","request_id":"UUID","protocol_version":1,"server_name":"collab","heartbeat_interval_sec":30}
```

Đăng ký chỉ tạo tài khoản, **không tự đăng nhập**:

```json
{"v":1,"type":"register","request_id":"UUID","username":"alice","password":"..."}
{"v":1,"type":"register_result","request_id":"UUID","ok":true}
```

- Username được chuẩn hóa Unicode NFC, dài 1–32 ký tự; chấp nhận chữ/số Unicode, `_`, `.`, `-`; phân biệt hoa thường. `.` và `..` không hợp lệ.
- Password dài 8–128 ký tự. Chỉ gửi trong TLS. Server lưu salt và kết quả scrypt trong SQLite, không lưu password gốc.
- Trùng username trả `register_result` với `ok:false`, `code:"username_taken"`. Username/password sai định dạng trả `register_result` với `ok:false`, `code:"invalid_message"`.

### 3.2 Đăng nhập và presence

```json
{"v":1,"type":"login","request_id":"UUID","username":"alice","password":"..."}
{"v":1,"type":"login_result","request_id":"UUID","ok":true,"username":"alice","session_id":"UUID"}
{"v":1,"type":"user_list","users":[{"username":"alice","host":"192.168.1.10","port":54001}]}
{"v":1,"type":"presence_online","username":"bob"}
{"v":1,"type":"presence_offline","username":"bob"}
```

- Sai username/password (kể cả sai định dạng) trả `login_result` với `ok:false`, `code:"invalid_credentials"`. User đang online ở session khác nhận `code:"already_online"`.
- Đăng nhập thành công tạo một session gắn với kết nối TLS. `session_id` là ID phiên; hiện không dùng làm bearer token.
- `user_list` được gửi sau `login_result` và bao gồm cả user vừa đăng nhập. `host` và `port` trong danh sách lấy từ địa chỉ TCP peer mà server quan sát được; đó là IP và cổng nguồn kết nối, không phải trường do client khai báo.
- Các client đã đăng nhập khác nhận `presence_online`/`presence_offline`; các event này hiện chỉ chứa `username`.
- Server xóa session khi logout, đóng kết nối hoặc hết idle timeout; việc cleanup phát `presence_offline` tối đa một lần cho session đó.

### 3.3 Chat

```json
{"v":1,"type":"chat_send","request_id":"UUID","to":null,"text":"Xin chào"}
{"v":1,"type":"chat_result","request_id":"UUID","ok":true,"message_id":"UUID"}
{"v":1,"type":"chat_message","message_id":"UUID","from":"alice","to":null,"text":"Xin chào","sent_at":"2026-11-03T10:00:00Z"}
```

- `to:null` gửi broadcast đến các user online khác. `to:"bob"` gửi direct đến user online có username khớp chính xác. Sender không nhận lại message chat của chính mình.
- `text` phải là chuỗi không rỗng, tối đa 4,000 ký tự. `sent_at` là UTC RFC 3339. Server sinh `message_id` UUID.
- Recipient không online hoặc không tồn tại trả `chat_result` với `ok:false`, `code:"recipient_unavailable"`. `ok:true` xác nhận server đã nhận và định tuyến message, không xác nhận người nhận đã đọc.
- Không có lịch sử chat, hàng đợi offline, nhóm chat, sửa hoặc xóa message.

### 3.4 Logout, ping và lỗi

```json
{"v":1,"type":"logout","request_id":"UUID"}
{"v":1,"type":"logout_result","request_id":"UUID","ok":true}
{"v":1,"type":"ping","request_id":"UUID"}
{"v":1,"type":"pong","request_id":"UUID"}
{"v":1,"type":"error","request_id":"UUID","code":"unauthorized","message":"Login required"}
```

- `ping` được chấp nhận trước và sau đăng nhập; phản hồi `pong` giữ nguyên `request_id`.
- `logout` chỉ thành công khi đang đăng nhập. Server gửi `logout_result`, xóa session và phát offline; cùng kết nối trở về trạng thái chưa xác thực.
- Trước đăng nhập, ngoài `hello` ban đầu, server xử lý `register`, `login`, `ping`; message khác (kể cả logout) trả `unauthorized`. Sau đăng nhập, server xử lý `chat_send`, `ping`, `logout`; message không hỗ trợ trả `invalid_message`.
- Mã lỗi đang dùng gồm `invalid_message`, `unauthorized`, `username_taken`, `invalid_credentials`, `already_online`, `recipient_unavailable`, `server_busy`. `message` chỉ dành cho hiển thị, không phải trường máy đọc.

## 4. UDP discovery và heartbeat

UDP dùng datagram JSON UTF-8 tối đa 1,200 byte, không dùng framing TCP. Server bind UDP trên cùng host cấu hình và cổng mặc định `37020`.

```json
{"v":1,"type":"discover","request_id":"UUID"}
{"v":1,"type":"server_announcement","request_id":"UUID","server_id":"UUID","server_name":"collab","host":"192.168.1.5","tcp_port":37021}
{"v":1,"type":"client_heartbeat","client_id":"UUID"}
{"v":1,"type":"heartbeat_ack","client_id":"UUID","server_id":"UUID"}
```

- Với `discover`, server trả announcement unicast về địa chỉ nguồn. `host` được chọn theo thứ tự: `COLLAB_ADVERTISE_HOST` nếu cấu hình; nếu không, `bind_host` khi bind một IP cụ thể; nếu bind wildcard (`0.0.0.0`), IP local của interface được chọn cho route IPv4 outbound; cuối cùng fallback `127.0.0.1`. Server không dùng IP nguồn của datagram làm địa chỉ server.
- UDP socket được bind đồng bộ trong `DiscoveryServer.start()` trước khi thread listener chạy, nên khi `start()` trả về có thể gửi discovery ngay.
- Với `client_heartbeat`, server trả `heartbeat_ack`. Server không lưu heartbeat UDP và không dùng nó để tạo/duy trì session user. Client ID không gắn với username.
- Server bỏ qua message UDP không hợp lệ hoặc type không được hỗ trợ. UDP không xác thực danh tính; không gửi mật khẩu, session ID, chat hay file qua UDP. Client vẫn phải xác minh chứng chỉ khi kết nối TCP.
- Discovery server hiện chỉ phản hồi khi client hỏi; không phát beacon định kỳ. Phạm vi broadcast phụ thuộc LAN/firewall.

## 5. Timeout, đồng thời và dọn dẹp

- TLS handshake có timeout 10 giây. Sau TLS, socket timeout bằng `idle_timeout` của server (mặc định 90 giây); timeout khi chờ dữ liệu đóng kết nối. Idle reaper cũng đóng session quá hạn.
- Server dùng worker thread riêng cho kết nối TCP, giới hạn mặc định 100 kết nối đang phục vụ. Khi quá giới hạn, kết nối mới bị đóng.
- EOF, lỗi TLS/socket, frame lỗi hoặc timeout kết thúc worker và dọn session. Server không lưu message cho user offline.
- Client nên gửi `ping` khi cần phát hiện kết nối còn sống; `heartbeat_interval_sec` trong `welcome` hiện là 30 giây. Session idle timeout mặc định 90 giây.

## 6. Truyền tệp — chưa triển khai

Schema dự kiến gồm `file_offer`, `file_offer_result`, `file_chunk`, `file_chunk_result`, `file_end`, `file_result`, dùng Base64 chunk, manifest kích thước/SHA-256 và giới hạn trong phiên bản thiết kế trước. Tuy nhiên server hiện **không chuyển tiếp hoặc nhận tệp**: mọi `file_offer`, `file_chunk`, `file_end` từ user đã đăng nhập nhận `error` với `code:"server_busy"` và message `File transfer handler is not available yet`. Chưa có trạng thái chấp nhận/từ chối offer hoạt động; không được coi schema dự kiến là tính năng sẵn dùng.

Khi Thành viên 3 tích hợp transfer, cần chốt schema accept/reject và cập nhật phần này cùng sơ đồ trạng thái trước khi coi file transfer là hoàn thành.

## 7. Ma trận message theo trạng thái hiện tại

| Trạng thái | Hướng | Message/hành vi |
|---|---|---|
| Trước TLS | — | Không có message ứng dụng |
| TLS, chờ hello | Client→server | Chỉ `hello`; loại khác trả lỗi rồi đóng kết nối |
| TLS, chưa xác thực | Client→server | `register`, `login`, `ping`; `logout`/message khác trả `unauthorized` |
| TLS, đã xác thực | Client→server | `chat_send`, `ping`, `logout`; file request trả `server_busy`; loại khác trả `invalid_message` |
| TLS, đã xác thực | Server→client | `user_list`, presence, `chat_message`, response tương ứng, `pong`, `error` |

## 8. Module hiện thực

- Schema và JSON: `src/collab/common/protocol.py`; framing: `framing.py`; UDP schema: `udp_protocol.py`.
- TLS helper: `src/collab/common/tls.py`.
- TCP/TLS server, session, auth, SQLite account store, router và UDP discovery: `src/collab/server/`.

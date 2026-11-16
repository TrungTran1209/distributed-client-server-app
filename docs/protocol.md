# Giao thức ứng dụng

Phiên bản giao thức là `1`. Tài liệu này mô tả đầy đủ hành vi đang hoạt động trong mã nguồn, bao gồm xác thực qua TLS, nhắn tin broadcast/direct, discovery/heartbeat UDP và **truyền tệp đáng tin cậy nhiều chunk**.

## 1. Kênh kết nối và framing

- Ứng dụng dùng TCP raw socket được bọc TLS (`minimum_version = TLSv1_2`, hỗ trợ TLS 1.3 trên OpenSSL 3.x). TLS phải hoàn tất trước message ứng dụng; client xác minh chuỗi chứng chỉ và hostname/IP theo trust store đã cấu hình (`--ca`).
- Mặc định server nghe TCP `37021`, UDP discovery `37020`; có thể cấu hình khi khởi chạy.
- Mỗi message TCP là một frame: 4 byte unsigned big-endian (`!I`) chứa độ dài payload, sau đó là payload JSON UTF-8 compact. Độ dài tính theo byte, từ `1` đến `1,048,576` byte (`MAX_FRAME_SIZE`). Không dùng ký tự phân cách dòng.
- Người nhận đọc đủ header 4 byte và đúng số byte payload (`recv_exact`); một lần `recv()` không đồng nghĩa với trọn một frame.
- Frame rỗng/quá giới hạn, JSON sai, sai version hoặc envelope không hợp lệ làm server đóng kết nối. Lỗi nghiệp vụ trả message lỗi tương ứng và giữ kết nối mở.

## 2. Envelope

```json
{"v":1,"type":"login","request_id":"UUID","username":"alice","password":"..."}
```

- `v` là số nguyên `1`; `type` là chuỗi định danh message. Hai trường luôn bắt buộc.
- Các request từ client sang server gồm `hello`, `register`, `login`, `logout`, `chat_send`, `file_offer`, `file_accept`, `file_reject`, `file_chunk`, `file_end`, `file_ack`, `file_cancel`, `ping` bắt buộc mang `request_id` (chuỗi UUID hợp lệ). Response trực tiếp của server sao chép nguyên `request_id` này.
- Các server push event (`user_list`, `presence_online`, `presence_offline`, `chat_message`, `file_offer_event`, `file_decision`, `file_chunk_event`, `file_end_event`, `file_status`) không mang `request_id` và được luồng đọc nền phía client chuyển vào bộ xử lý sự kiện bất đồng bộ.
- Server không bao giờ đưa mật khẩu, salt hoặc khóa bí mật vào response hay log. Các thao tác `sendall()` trên mỗi session đều được đồng bộ bằng khóa gửi riêng (`send_lock`) để không trộn lẫn byte của hai frame.

## 3. Xác thực, Presence và Chat qua TCP/TLS

### 3.1 Bắt đầu phiên và đăng ký

Sau TLS, `hello` phải là message đầu tiên. Server phản hồi `welcome`; nếu message đầu tiên khác `hello`, server trả `error` rồi đóng kết nối.

```json
{"v":1,"type":"hello","request_id":"UUID","client":"collab-cli","client_version":"1.0"}
{"v":1,"type":"welcome","request_id":"UUID","protocol_version":1,"server_name":"collab","heartbeat_interval_sec":30}
```

Đăng ký tạo tài khoản mới (không tự động đăng nhập):

```json
{"v":1,"type":"register","request_id":"UUID","username":"alice","password":"..."}
{"v":1,"type":"register_result","request_id":"UUID","ok":true}
```

- Username chuẩn hóa Unicode NFC, dài 1–32 ký tự (`[\w.-]`, phân biệt hoa thường, cấm `.` và `..`).
- Password chuẩn hóa Unicode NFKC (tương thích ngược khi đăng nhập hash cũ), dài 8–128 ký tự, chỉ gửi trong kênh TLS. Server lưu `salt` (16 byte), `password_hash` (32 byte) và chuỗi phiên bản tham số `kdf_params` (`scrypt$v=1$n=16384$r=8$p=1$dklen=32`) trong SQLite.
- Trùng username trả `register_result` với `ok:false`, `code:"username_taken"`. Vượt ngưỡng tạo tài khoản theo IP trả `ok:false`, `code:"rate_limited"`.

### 3.2 Đăng nhập và Presence

```json
{"v":1,"type":"login","request_id":"UUID","username":"alice","password":"..."}
{"v":1,"type":"login_result","request_id":"UUID","ok":true,"username":"alice","session_id":"UUID"}
{"v":1,"type":"user_list","users":[{"username":"alice","host":"192.168.1.10","port":54001}]}
{"v":1,"type":"presence_online","username":"bob"}
{"v":1,"type":"presence_offline","username":"bob"}
```

- Sai thông tin đăng nhập trả `ok:false, code:"invalid_credentials"`; vượt giới hạn thử mật khẩu sai trên một kết nối trả `ok:false, code:"rate_limited"` rồi đóng kết nối; tài khoản đang đăng nhập ở kết nối khác trả `code:"already_online"`.
- Nếu tham số `kdf_params` lưu trong SQLite cũ hơn cấu hình mục tiêu của server, server tự động dẫn xuất lại hash mới khi đăng nhập hợp lệ.
- `user_list` gửi ngay sau `login_result` kèm địa chỉ IP và cổng TCP nguồn mà server quan sát được.

### 3.3 Chat Broadcast và Direct

```json
{"v":1,"type":"chat_send","request_id":"UUID","to":null,"text":"Xin chào"}
{"v":1,"type":"chat_result","request_id":"UUID","ok":true,"message_id":"UUID"}
{"v":1,"type":"chat_message","message_id":"UUID","from":"alice","to":null,"text":"Xin chào","sent_at":"2026-11-07T10:00:00Z"}
```

- `to:null` gửi broadcast tới mọi người dùng online khác; `to:"bob"` (được chuẩn hóa Unicode NFC giống lúc đăng nhập) gửi tin nhắn riêng 1-1.
- `text` dài 1–4,000 ký tự. Người nhận offline trả `chat_result` với `ok:false, code:"recipient_unavailable"`; gửi vượt tốc độ token-bucket trả `ok:false, code:"rate_limited"`.

### 3.4 Logout, Ping và Lỗi chung

```json
{"v":1,"type":"logout","request_id":"UUID"}
{"v":1,"type":"logout_result","request_id":"UUID","ok":true}
{"v":1,"type":"ping","request_id":"UUID"}
{"v":1,"type":"pong","request_id":"UUID"}
{"v":1,"type":"error","request_id":"UUID","code":"unauthorized","message":"Login required"}
```

## 4. Truyền tệp Đáng tin cậy qua TCP/TLS

Truyền tệp hoạt động theo mô hình 1-1 có xác nhận (`offer` -> `accept`/`reject` -> `chunk` -> `end` -> `ack`), đi hoàn toàn bên trong kênh TCP/TLS hiện có.

### 4.1 Khởi tạo lời mời (`file_offer` / `file_offer_event`)

Người gửi tính kích thước tệp và mã băm SHA-256 theo luồng (streaming), sau đó gửi `file_offer`:

```json
{"v":1,"type":"file_offer","request_id":"UUID","transfer_id":"UUID","to":"bob","filename":"report.pdf","size":210123,"sha256":"64-hex","chunk_size":65536,"total_chunks":4}
{"v":1,"type":"file_offer_result","request_id":"UUID","ok":true,"transfer_id":"UUID"}
```

Server kiểm tra hợp lệ và đẩy sự kiện `file_offer_event` tới người nhận:

```json
{"v":1,"type":"file_offer_event","transfer_id":"UUID","from":"alice","filename":"report.pdf","size":210123,"sha256":"64-hex","chunk_size":65536,"total_chunks":4,"expires_in_sec":60}
```

- Giới hạn mặc định: `DEFAULT_CHUNK_SIZE = 65,536` byte (64 KiB), `MAX_CHUNK_SIZE = 262,144` byte (256 KiB), `MAX_FILE_SIZE = 67,108,864` byte (64 MiB), tối đa 3 phiên gửi đồng thời mỗi user. Tệp rỗng (`size = 0`) hợp lệ với `total_chunks = 0`.
- `filename` không được chứa ký tự phân tách đường dẫn (`/`, `\`, `:`), ký tự cấm hoặc tên thiết bị hệ thống; dài tối đa 200 ký tự và không quá 200 byte UTF-8.

### 4.2 Chấp nhận hoặc Từ chối (`file_accept` / `file_reject` / `file_decision`)

```json
{"v":1,"type":"file_accept","request_id":"UUID","transfer_id":"UUID"}
{"v":1,"type":"file_accept_result","request_id":"UUID","ok":true,"transfer_id":"UUID"}
{"v":1,"type":"file_reject","request_id":"UUID","transfer_id":"UUID","reason":"rejected_by_user"}
{"v":1,"type":"file_reject_result","request_id":"UUID","ok":true,"transfer_id":"UUID"}
{"v":1,"type":"file_decision","transfer_id":"UUID","accepted":true,"by":"bob"}
```

### 4.3 Truyền từng Chunk và Kết thúc (`file_chunk` / `file_end` / `file_ack`)

```json
{"v":1,"type":"file_chunk","request_id":"UUID","transfer_id":"UUID","index":0,"data":"BASE64_ASCII"}
{"v":1,"type":"file_chunk_result","request_id":"UUID","ok":true,"transfer_id":"UUID","index":0}
{"v":1,"type":"file_chunk_event","transfer_id":"UUID","from":"alice","index":0,"data":"BASE64_ASCII"}
```

- `index` phải tăng tuần tự từ `0` đến `total_chunks - 1`. Server kiểm tra độ dài giải mã Base64 khớp đúng manifest rồi chuyển tiếp trực tiếp sang socket người nhận (không lưu trữ chunk trong RAM server).
- Người nhận ghi từng chunk vào tệp tạm ẩn `.<filename>.<transfer_id>.part` và cập nhật bộ băm SHA-256 tăng dần.

Khi gửi hết các chunk, người gửi phát `file_end`, người nhận kiểm tra kích thước & SHA-256 rồi xác nhận bằng `file_ack`:

```json
{"v":1,"type":"file_end","request_id":"UUID","transfer_id":"UUID","size":210123,"sha256":"64-hex"}
{"v":1,"type":"file_result","request_id":"UUID","ok":true,"transfer_id":"UUID","stage":"verifying"}
{"v":1,"type":"file_end_event","transfer_id":"UUID","from":"alice","size":210123,"sha256":"64-hex","total_chunks":4}
{"v":1,"type":"file_ack","request_id":"UUID","transfer_id":"UUID","ok":true,"sha256":"64-hex"}
{"v":1,"type":"file_ack_result","request_id":"UUID","ok":true,"transfer_id":"UUID"}
{"v":1,"type":"file_status","transfer_id":"UUID","ok":true,"by":"bob","sha256":"64-hex"}
```

### 4.4 Hủy phiên, Timeout và Mã lỗi Truyền tệp

Hai phía có thể chủ động hủy bằng `file_cancel`:

```json
{"v":1,"type":"file_cancel","request_id":"UUID","transfer_id":"UUID","reason":"cancelled_by_sender"}
{"v":1,"type":"file_cancel_result","request_id":"UUID","ok":true,"transfer_id":"UUID"}
```

- Thời gian chờ mặc định trên server: chờ chấp nhận lời mời `60 giây`, chờ giữa hai chunk `30 giây`, chờ `file_ack` cuối `15 giây`.
- Các mã lỗi truyền tệp chuẩn hóa: `invalid_filename`, `file_too_large`, `invalid_chunk_size`, `invalid_transfer`, `recipient_unavailable`, `duplicate_transfer`, `too_many_transfers`, `invalid_transfer_state`, `chunk_out_of_order`, `invalid_chunk`, `size_mismatch`, `checksum_mismatch`, `peer_disconnected`, `transfer_timeout`, `transfer_cancelled`.

## 5. UDP Discovery và Heartbeat

UDP dùng datagram JSON UTF-8 tối đa 1,200 byte trên cổng mặc định `37020`:

```json
{"v":1,"type":"discover","request_id":"UUID"}
{"v":1,"type":"server_announcement","request_id":"UUID","server_id":"UUID","server_name":"collab","host":"192.168.1.5","tcp_port":37021}
{"v":1,"type":"client_heartbeat","client_id":"UUID"}
{"v":1,"type":"heartbeat_ack","client_id":"UUID","server_id":"UUID"}
```

UDP không xác thực người dùng, không mang mật khẩu/tin nhắn/tệp và không thay thế xác minh chứng chỉ TLS.

## 6. Ma trận Message theo Trạng thái

| Trạng thái | Hướng | Message được chấp nhận / phát sinh |
|---|---|---|
| Trước TLS | — | Không có message ứng dụng |
| TLS, chờ hello | Client→Server | Chỉ `hello`; loại khác trả `error` rồi đóng kết nối |
| TLS, chưa xác thực | Client→Server | `register`, `login`, `ping`; loại khác trả `unauthorized` |
| TLS, đã xác thực | Client→Server | `chat_send`, `file_offer`, `file_accept`, `file_reject`, `file_chunk`, `file_end`, `file_ack`, `file_cancel`, `ping`, `logout` |
| TLS, đã xác thực | Server→Client | `user_list`, `presence_online`, `presence_offline`, `chat_message`, `file_offer_event`, `file_decision`, `file_chunk_event`, `file_end_event`, `file_status`, cùng các `*_result`, `pong`, `error` |

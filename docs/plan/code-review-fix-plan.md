# Code Review toàn diện & Kế hoạch sửa lỗi (nhánh `feature/m1`, HEAD `7ab1be8`)

**Ngày review:** 11/11/2026 · **Phạm vi:** toàn bộ `src/collab/`, `tests/`, `README.md`, `TEAM_PLAN.md`, `.env.example`, `docs/*.md`, `docs/report/`
**Validation:** 37 unit + 5 integration test PASS · coverage 81.1% · không có secret/`.key`/`.crt`/DB bị track trong Git.
**Quyết định:** **REQUEST CHANGES** (1 HIGH, 7 MEDIUM, 8 LOW). Không có lỗi CRITICAL về bảo mật mật mã; TLS, scrypt, chống path traversal đều đúng thiết kế.

---

## 1. Phát hiện

### HIGH

| ID | Vị trí | Vấn đề | Cách sửa |
|---|---|---|---|
| H1 | `README.md` L67 + `server/discovery.py` L93-108 | Lệnh mẫu chạy server `--host 0.0.0.0` còn cert chỉ có SAN `localhost`/`127.0.0.1`. `DiscoveryServer` quảng bá IP của card mạng ra Internet (VD `172.16.0.2` do VPN/WARP/WSL) nên client `--discover` kết nối TLS bị `IP address mismatch`. Đây chính là lỗi người dùng gặp; demo theo README **sẽ hỏng trên hầu hết máy**. | Server trả về IP của interface **định tuyến tới chính client đang hỏi** (client loopback → `127.0.0.1`). README: demo 1 máy dùng `--host 127.0.0.1`; demo LAN dùng `--advertise-host` + SAN khớp. |

### MEDIUM

| ID | Vị trí | Vấn đề | Cách sửa |
|---|---|---|---|
| M1 | `server/server.py` L123, L143-152 | `tls_sock.settimeout(idle_timeout=300)` áp cho cả kết nối **chưa đăng nhập**: peer im lặng giữ worker 300 s (tối đa 100 worker → DoS dễ). `auth_grace=180 s` chỉ kiểm tra khi có frame đến nên vô hiệu với peer im lặng. Ngoài ra client ping mỗi 30 s nên 300 s idle cho phiên đã đăng nhập là thừa và làm `already_online` kéo dài khi half-open. | Pre-auth: timeout đọc = thời gian còn lại của `auth_grace` (`--auth-timeout`). Phiên đã đăng nhập: idle ≈ 3 × heartbeat (90 s). Tách 2 tham số. |
| M2 | `server/transfer_coordinator.py` L369-376; `router.py` L28-48 | `self.send()` (I/O mạng chặn, tối đa 300 s) được gọi **trong** `with self._lock` ở nhánh `size_mismatch`; broadcast gửi tuần tự nên một client nghẽn làm chậm người gửi. | Gom thông báo, gửi **sau khi nhả khóa**. Đặt send-timeout ngắn (≈15 s) → quá hạn thì đóng socket peer. |
| M3 | `server/server.py`, `auth.py` | Không giới hạn tốc độ: spam `register` (mỗi lần scrypt ~16 MiB, DB tăng vô hạn), spam đăng nhập sai chiếm hết `BoundedSemaphore(8)` làm user thật bị đứng, spam `chat_send` broadcast. | Token-bucket theo kết nối (chat), giới hạn thất bại đăng nhập/đăng ký theo kết nối + theo IP (đóng kết nối sau N lần, backoff). |
| M4 | `server/discovery.py` L39 | `SO_REUSEADDR` trên UDP ở Windows cho phép **nhiều server cùng bind cổng 37020**; server cũ (stale) vẫn trả lời discovery → client nối nhầm. Máy người dùng đang có PID cũ giữ `37020/37021`. | Windows: dùng `SO_EXCLUSIVEADDRUSE` (không REUSEADDR); báo lỗi rõ khi cổng bận. |
| M5 | `server/server.py` `_send_raw` | Mỗi worker `recv` trên SSLSocket của mình trong khi worker khác `sendall` lên **cùng** SSLSocket (chat/relay chunk). OpenSSL không đảm bảo an toàn cho đọc/ghi đồng thời cùng `SSL*`; đây là họ lỗi đã gặp ở handshake client (TLS 1.3 ticket). Hiện test 12 client vẫn qua. | Phương án chuẩn: mỗi session có hàng đợi gửi + 1 writer thread. Nếu không kịp: ghi rõ rủi ro tại `docs/security.md` và giữ test stress. (Tùy chọn, làm sau cùng.) |
| M6 | `.env.example`, README | `.env.example` ghi `8443/9999`, `certs/ca.crt`, `COLLAB_DATA_DIR`; mặc định thật là `37021/37020`, và **không có bộ nạp `.env`**. Tên biến không thống nhất (`COLLAB_PORT`/`COLLAB_TCP_PORT`, `COLLAB_TLS_CERT`/`COLLAB_CERT_FILE`). README không liệt kê `--idle-timeout`, `--database`, biến môi trường. | Cập nhật `.env.example` cho khớp code, thêm bảng cờ/biến môi trường vào README, ghi rõ "không tự nạp `.env`". |
| M7 | `TEAM_PLAN.md` L20 vs L276; L45; `security.md` L23; `protocol.md` L101; `technical-report.md` L201 | Hạn nộp **16/11** (L20) mâu thuẫn **17/11** (L276); "đạt >85% coverage" trong khi đo thực tế 81.1%; "maxmem 64 MiB" vs trần 256 MiB trong code; "200 ký tự" vs code đếm 200 **byte** UTF-8; lỗi chính tả "chunk rỗi". | Thống nhất theo kênh chính thức của môn học; ghi coverage đúng; sửa chú thích; sửa chính tả; thêm test đồng bộ tài liệu. |

### LOW

| ID | Vị trí | Vấn đề |
|---|---|---|
| L1 | `client/connection.py` `close()`→`_fail` | Thoát bình thường (`/quit`) vẫn in `[Mất kết nối] Client closed the connection`. |
| L2 | `client/commands.py` `run()` | Sau `connection_lost` vòng `input()` vẫn chặn đến khi nhấn Enter. |
| L3 | `client/main.py` L60 | In `server_name`/`host` từ UDP không xác thực mà chưa lọc ký tự điều khiển (TLS vẫn chặn kết nối giả, nhưng nên dùng `_clean_display`). |
| L4 | `common/protocol.py`, `auth.py` | Username phân biệt hoa/thường (`Alice` ≠ `alice`) → dễ mạo danh nhìn-giống; mật khẩu chưa chuẩn hóa Unicode (NFKC). |
| L5 | `server/server.py` `_handle_chat` | Trường `to` chưa qua `normalize_username` → `/msg` tới tên Unicode dạng tổ hợp khác NFC bị `recipient_unavailable`. |
| L6 | `tests/` | `client/main.py`, `server/main.py` 0%; `commands.py` 69.5%; `receiver.py` 78.9% — thiếu test cho các cờ CLI và đường lỗi. |
| L7 | `transfer_coordinator.py` L210 | Tài khoản tùy ý có thể lấp đầy hạn mức nhận của nạn nhân bằng lời mời rác (mỗi lời mời hết hạn sau 60 s). |
| L8 | `receiver.py` `_spawn_bounded` L429-431 | Khi cổng async đầy, `FILE_ACK`/`FILE_REJECT`/`FILE_CANCEL` bị **bỏ im lặng** → bên gửi báo timeout dù tệp đã lưu. Nên gửi `FILE_ACK` đồng bộ hoặc cấp worker riêng. |

---

## 2. Kế hoạch sửa (mỗi giai đoạn theo `tdd-workflow`: test RED → fix GREEN → refactor, commit riêng)

| Giai đoạn | Mục | Test viết trước (RED) | Việc làm | File chính |
|---|---|---|---|---|
| **P1** (ưu tiên cao nhất) | H1, M4 | `test_udp_discovery`: bind `0.0.0.0`, client loopback ⇒ `host == 127.0.0.1`; khi có `advertise_host` thì luôn ưu tiên; test cờ socket exclusive trên `nt` | Thêm `peer_host` cho `_announcement_host()` (UDP `connect` tới peer rồi `getsockname`); Windows bỏ `SO_REUSEADDR`; sửa README (`--host 127.0.0.1` cho 1 máy, ví dụ LAN) | `server/discovery.py`, `README.md`, `certs/README.md` |
| **P2** | M1, L1, L2 | Server dùng timeout nhỏ: peer im lặng bị đóng ≤ `auth_timeout`; phiên đã login dùng idle riêng; `/quit` không in "Mất kết nối" | Tham số `--auth-timeout`, `--idle-timeout` (default 90 cho phiên) ; `close()` đặt cờ đóng chủ động | `server/server.py`, `server/main.py`, `client/connection.py`, `client/commands.py` |
| **P3** | M2, M5(1), L8 | Test coordinator: `send` giả chậm không giữ khóa (thread khác vẫn xử lý được `handle_request`); gửi chậm quá hạn ⇒ socket bị đóng; `FILE_ACK` không bị bỏ khi cổng đầy | Gửi thông báo ngoài khóa; send-timeout; ACK đồng bộ | `transfer_coordinator.py`, `server.py`, `receiver.py` |
| **P4** | M3, L7 | Test: N lần login sai ⇒ đóng kết nối; chat vượt token-bucket ⇒ lỗi `rate_limited`; register vượt hạn mức theo IP | Token-bucket + bộ đếm thất bại theo kết nối/IP; giới hạn offer theo cặp người gửi→người nhận | `server/server.py`, `server/auth.py` (+ module `ratelimit.py` mới) |
| **P5** | L3, L4, L5 | Test `normalize_username` cho `to`; test `_clean_display` cho UDP; mật khẩu NFKC (tương thích ngược khi đăng nhập hash cũ) | Chuẩn hóa `to`; lọc chuỗi UDP; ghi rõ chính sách tên | `server.py`, `client/main.py`, `auth.py` |
| **P6** | M6, M7, L6 | Mở rộng `tests/unit/test_report_and_docs.py`: README/`.env.example` khớp mặc định code (`37021/37020`), TEAM_PLAN không còn hai ngày hạn khác nhau & coverage khớp số đo; thêm test CLI `main()` bằng `argparse` | Cập nhật tài liệu; thêm test cho `client/main.py`, `server/main.py`; build lại PDF | `.env.example`, `README.md`, `TEAM_PLAN.md`, `docs/*.md`, `tests/` |
| **P7** (tùy chọn) | M5 | Stress test 20 client + chunk lớn lặp 10 lần không `timeout` | Writer thread + hàng đợi gửi theo session | `server/sessions.py`, `server/server.py` |

**Tiêu chí hoàn thành mỗi giai đoạn:** toàn bộ test hiện có + test mới PASS, coverage ≥ 80% (mục tiêu ≥ 83%), `git status` sạch, không đổi định dạng giao thức v1 (chỉ thêm mã lỗi `rate_limited`), cập nhật `docs/protocol.md`/`docs/security.md`/README tương ứng và build lại `technical-report.pdf`.

**Thứ tự đề xuất:** P1 → P2 → P6 (tài liệu) → P3 → P4 → P5 → P7. P1+P2+P6 là đủ để demo ổn định và nộp bài; P3-P5 nâng độ bền; P7 chỉ làm nếu còn thời gian.

## 3. Điều không phải lỗi (đã kiểm tra)

- Hiển thị `Tìm thấy collab tại …:37021` trong khi tham số là `--udp-port 37020`: đúng thiết kế (UDP hỏi đường, TCP/TLS truyền dữ liệu).
- Port nguồn ngẫu nhiên trong `/users` (vd `:54821`) là cổng tạm của client, không phải cổng server.
- Việc client từ chối chứng chỉ không khớp IP là đúng; không được tắt `check_hostname`.

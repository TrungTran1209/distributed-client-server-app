# Assignment 1 — Ứng dụng cộng tác Client–Server phân tán

## 1. Mục tiêu dự án

Xây dựng ứng dụng cộng tác tự lưu trữ, chạy trên localhost hoặc mạng nội bộ, dùng Python và raw sockets. Server tiếp nhận nhiều client đồng thời, xác thực tài khoản, theo dõi người dùng đang trực tuyến và định tuyến tin nhắn broadcast/tin nhắn riêng. Người dùng có thể truyền tệp đáng tin cậy. Client phát hiện **server** bằng UDP; danh sách người dùng online được server cung cấp qua TCP/TLS sau đăng nhập và cập nhật bằng presence event. Kết nối TCP được bảo vệ bằng TLS; thông tin mật khẩu được lưu dưới dạng dẫn xuất mật khẩu có salt, không lưu mật khẩu gốc.

CLI là giao diện mặc định để giữ phạm vi triển khai phù hợp. CLI cần thể hiện trạng thái kết nối, người dùng trực tuyến, tin nhắn, lỗi và tiến độ truyền tệp.

## 2. Quyết định đã chốt

| Chủ đề | Quyết định của nhóm |
|---|---|
| Ngôn ngữ | Python |
| Kết nối và dữ liệu chính | TCP raw socket; framing ứng dụng tường minh |
| Discovery/heartbeat | UDP là tính năng bắt buộc trong phạm vi dự án |
| Bảo vệ kênh mạng | TLS qua thư viện `ssl` của Python trên kết nối TCP; vẫn dùng socket, không dùng HTTP/WebSocket |
| Mật khẩu | Đề gốc không quy định KDF hay lưu tài khoản; nhóm chọn không lưu plaintext, dùng `hashlib.scrypt` với salt riêng cho mỗi tài khoản |
| Người dùng và trạng thái | Server quản lý đăng ký/đăng nhập, phiên hoạt động, IP/cổng TCP và trạng thái online |
| Giao diện | CLI |
| Hạn nộp chính thức | 00:00 ngày 17/11/2026 |


### Phạm vi bảo mật đã chọn

- Dùng TLS để mã hóa và xác thực tính toàn vẹn của toàn bộ luồng TCP, bao gồm xác thực, tin nhắn và truyền tệp. Dùng `ssl.SSLContext` với cấu hình TLS hiện đại; không tự viết thuật toán mã hóa. Nhóm cần tạo/chọn chứng chỉ và ghi hướng dẫn cấu hình rõ ràng. Với demo LAN, có thể dùng CA/chứng chỉ tự tạo và cấu hình client tin cậy CA đó; không tắt xác minh chứng chỉ trong luồng sử dụng bình thường.
- Mật khẩu không được gửi qua kết nối không mã hóa. Server lưu salt riêng cho từng tài khoản và kết quả `scrypt`, so sánh theo cách an toàn; không ghi mật khẩu vào log. Khi triển khai đăng ký, xác định chính sách tối thiểu cho mật khẩu và kiểm tra tên người dùng trùng lặp.
- TLS bảo vệ dữ liệu khi truyền, còn `scrypt` bảo vệ mật khẩu lưu trữ; hai biện pháp giải quyết hai rủi ro khác nhau.
- Với môi trường demo, chứng chỉ tự ký/CA nội bộ có thể phù hợp. Không tuyên bố hệ thống có quản lý danh tính doanh nghiệp, chống tấn công từ máy chủ bị xâm nhập, hay bảo vệ dữ liệu lưu trên ổ đĩa nếu những phần đó chưa được triển khai.

## 3. Mười mốc chấm trong đề và tình trạng hiện tại

Đặc tả gốc chấm 10 mốc, mỗi mốc 1 điểm. Cột nguồn dưới đây diễn giải tiêu chí đề; trạng thái bên cạnh là đánh giá repository hiện tại, không phải kết quả kiểm thử mới trong lần chỉnh tài liệu này.

| # | Mốc trong đặc tả gốc | Trạng thái repo và phần cần làm |
|---:|---|---|
| 1 | Thiết lập và thiết kế giao thức: định nghĩa packet, message type, sơ đồ trạng thái trước khi code. | **Đã hoàn thành:** `docs/protocol.md`, `docs/state-diagrams.md`, `docs/sequence-diagrams.md` đồng bộ đầy đủ với mã nguồn. |
| 2 | TCP handshake: client kết nối và nhận xác nhận từ server. | **Đã hoàn thành & kiểm thử:** client TLS gửi `hello`, server trả `welcome` ổn định trên cả TLS 1.2 và TLS 1.3. |
| 3 | Đồng thời: ít nhất 10–20 client. | **Đã kiểm chứng tự động:** bài integration test chạy đồng thời 12 client kết nối TLS, broadcast chat và truyền tệp song song. |
| 4 | Đăng nhập và quản lý state; server theo dõi user, IP, cổng đang hoạt động. | **Đã hoàn thành & kiểm thử:** đăng ký/đăng nhập, `SessionRegistry` ghi nhận địa chỉ IP và cổng TCP nguồn thực tế. |
| 5 | Định tuyến tin nhắn broadcast hoặc chuyển tiếp đến recipient đúng. | **Đã hoàn thành & kiểm thử:** định tuyến broadcast (`/all`) và direct (`/msg`) qua `MessageRouter`. |
| 6 | Truyền file tin cậy: serialize, chia chunk file lớn, ghép lại không hỏng. | **Đã hoàn thành & kiểm thử:** `FileSender`, `FileReceiver`, `TransferCoordinator` chia chunk 64 KiB, ghi `.part`, xác minh kích thước & SHA-256 đầu-cuối. |
| 7 | Phục hồi: timeout, broken pipe, client thoát an toàn, server không crash. | **Đã hoàn thành & kiểm thử:** xử lý timeout offer/chunk/idle, ngắt kết nối đột ngột giữa chừng tự xóa `.part`, server vẫn phục vụ bình thường các client khác. |
| 8 | Mã hóa payload bằng thư viện mật mã chuẩn rồi giải mã phía nhận. | **Đã hoàn thành & kiểm thử:** toàn bộ luồng TCP bọc TLS 1.2+; kiểm thử từ chối chứng chỉ không tin cậy; mật khẩu lưu bằng `scrypt` kèm phiên bản `kdf_params`. |
| 9 | UI dễ dùng, hiển thị message, tiến độ file và danh sách user hoạt động. | **Đã hoàn thành & kiểm thử:** CLI hỗ trợ `/file`, `/accept`, `/reject`, `/cancel`, hiển thị tiến độ `%`, presence và danh sách user. |
| 10 | Code gọn, có chú thích và qua mô phỏng mạng cục bộ từ nhiều terminal. | **Đã hoàn thành:** toàn bộ 53 unit tests & 5 integration tests PASS (87.7% statement coverage); báo cáo kỹ thuật PDF đã được biên dịch đầy đủ. |

Đề cũng nêu UDP cho discovery/heartbeat trong mục công nghệ. Nhóm đã chọn đây là phạm vi bắt buộc; rubric không chấm UDP thành một điểm riêng. Cần thể hiện chức năng và giới hạn trong demo/tài liệu.

## 4. Cấu trúc repository đề xuất

```text
distributed-collab/
├── README.md
├── pyproject.toml
├── .gitignore
├── .env.example                 # chỉ tên biến cấu hình giả, không chứa secret
├── certs/
│   └── README.md                # hướng dẫn tạo/cài chứng chỉ; không commit private key
├── docs/
│   ├── architecture.md
│   ├── protocol.md
│   ├── state-diagrams.md
│   ├── sequence-diagrams.md
│   ├── security.md
│   └── report/
│       └── technical-report.pdf
├── src/
│   └── collab/
│       ├── __init__.py
│       ├── common/
│       │   ├── protocol.py       # loại message và schema dữ liệu
│       │   ├── framing.py        # phân định message trên TCP
│       │   ├── tls.py            # tạo SSLContext và bọc socket
│       │   ├── crypto.py         # dẫn xuất/kiểm tra mật khẩu bằng scrypt
│       │   ├── udp_protocol.py   # schema UDP discovery/heartbeat
│       │   └── errors.py
│       ├── server/
│       │   ├── main.py
│       │   ├── server.py         # accept loop và xử lý kết nối đồng thời
│       │   ├── auth.py           # đăng ký/đăng nhập
│       │   ├── user_store.py     # lưu tài khoản, salt và password hash
│       │   ├── sessions.py       # session và trạng thái online
│       │   ├── router.py         # broadcast và unicast
│       │   └── discovery.py      # UDP listener, phản hồi tìm server/heartbeat
│       ├── client/
│       │   ├── main.py
│       │   ├── connection.py     # TCP + TLS
│       │   ├── receiver.py
│       │   ├── discovery.py     # UDP discovery/heartbeat phía client
│       │   └── commands.py       # CLI
│       └── transfer/
│           ├── sender.py
│           ├── receiver.py
│           └── manifest.py       # metadata, chunk, checksum, reassembly
├── data/                         # runtime; nội dung bị loại khỏi Git
│   └── .gitkeep
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

`data/` chỉ là vị trí runtime cục bộ cho kho tài khoản/tệp cần thiết; phải loại dữ liệu thật khỏi Git. Có thể thay đổi nơi lưu theo thiết kế, nhưng cần giữ bí mật và dữ liệu người dùng ngoài source control. Không commit private key, mật khẩu, database runtime hoặc tệp người dùng.

## 5. Phân công cho ba thành viên

### Thành viên 1 — Giao thức, server, xác thực và discovery UDP

**Phụ trách**

- Chốt đặc tả TCP: framing, schema, message types, lỗi, luồng đăng nhập, trạng thái client/server và quy tắc định tuyến.
- Vẽ sơ đồ trạng thái/luồng trước khi phần phụ thuộc triển khai.
- Xây dựng TCP server raw socket, dùng `ssl` bọc kết nối và xử lý nhiều client đồng thời.
- Triển khai handshake, đăng ký/đăng nhập, session registry, danh sách online, địa chỉ IP/cổng và broadcast/unicast.
- Triển khai UDP discovery/heartbeat phía server theo schema đã thống nhất; xác thực phản hồi UDP bằng token/nonce ngắn hạn gắn với phiên nếu thiết kế cần chống giả mạo đơn giản. Không coi UDP là kênh đăng nhập hoặc gửi mật khẩu.
- Chọn cách lưu tài khoản và tích hợp hàm dẫn xuất mật khẩu của Thành viên 3.

**Sản phẩm bàn giao**

- `src/collab/common/protocol.py`
- `src/collab/common/framing.py`
- `src/collab/common/udp_protocol.py`
- `src/collab/server/`
- `docs/protocol.md`
- `docs/state-diagrams.md`
- Ghi chú cấu hình/chạy server trong README

**Tiêu chí hoàn thành**

- Nhiều client có thể kết nối TLS, đăng nhập, nhìn thấy trạng thái online và gửi broadcast/unicast.
- Server cập nhật danh sách online khi client thoát bình thường hoặc mất kết nối.
- Discovery/heartbeat UDP hoạt động trong môi trường demo và không tiết lộ mật khẩu.
- Dữ liệu đầu vào sai hoặc client ngắt đột ngột không làm server dừng.

**Phụ thuộc**

- Phải thống nhất giao thức với Thành viên 2 và 3 trước khi họ xây dựng phần phụ thuộc.
- Dùng API dẫn xuất mật khẩu và định dạng lưu tài khoản thống nhất với Thành viên 3.

### Thành viên 2 — Client, CLI và trải nghiệm sử dụng

**Phụ trách**

- Triển khai client TCP raw socket qua TLS, xác minh chứng chỉ theo cấu hình tin cậy và xử lý handshake.
- Triển khai lệnh đăng ký/đăng nhập, nhận tin, xem danh sách người dùng, gửi broadcast/tin nhắn riêng, thoát an toàn.
- Triển khai UDP discovery/heartbeat phía client theo giao thức Thành viên 1; không gửi thông tin xác thực qua UDP.
- Hiển thị trạng thái kết nối, danh sách online, tin nhắn, lỗi và tiến độ truyền tệp rõ ràng.
- Viết hướng dẫn cài đặt dependency, tạo/cài CA hoặc chứng chỉ demo, chạy server và nhiều client trong README.

**Sản phẩm bàn giao**

- `src/collab/client/`
- Phần hướng dẫn người dùng và hướng dẫn chạy trong `README.md`
- Ví dụ phiên CLI cho demo/báo cáo

**Tiêu chí hoàn thành**

- Người mới làm theo README có thể chạy server và kết nối từ nhiều terminal.
- Client xác minh chứng chỉ server theo chế độ được tài liệu hóa; lỗi chứng chỉ được báo rõ.
- Client phản hồi rõ khi server mất kết nối và thoát mà không để thread/socket treo.
- Các lệnh CLI khớp với schema giao thức và không giữ cách mã hóa thông tin xác thực riêng.

**Phụ thuộc**

- Giao thức, framing, schema UDP và cấu hình TLS do Thành viên 1 thống nhất.
- API sự kiện/trạng thái truyền tệp do Thành viên 3 thống nhất.

### Thành viên 3 — Truyền tệp, mật khẩu và hỗ trợ bảo mật/phục hồi

**Phụ trách**

- Thiết kế và triển khai metadata tệp, transfer ID, chia chunk, ghép lại và kiểm tra checksum.
- Triển khai sender/receiver qua TCP/TLS đã được tạo bởi lớp kết nối chung; không mở kênh truyền tệp không mã hóa.
- Cung cấp hàm dẫn xuất và kiểm tra mật khẩu bằng `hashlib.scrypt`, với salt ngẫu nhiên riêng cho từng tài khoản và tham số được ghi rõ/có thể nâng cấp. Dùng so sánh an toàn (`hmac.compare_digest`) khi kiểm tra kết quả.
- Thống nhất với Thành viên 1 schema lưu tài khoản; hỗ trợ kiểm thử việc đăng ký/đăng nhập. Không ghi mật khẩu hoặc giá trị bí mật vào log.
- Xử lý timeout, transfer chưa hoàn tất, ngắt kết nối, tên tệp không an toàn và dọn dẹp tệp tạm.
- Ghi lại quyết định bảo mật/truyền tệp, tạo sequence diagram và chuẩn bị phần thử thách/giải pháp cho báo cáo.

**Sản phẩm bàn giao**

- `src/collab/transfer/`
- `src/collab/common/crypto.py`
- `docs/sequence-diagrams.md`
- `docs/security.md`
- Nội dung truyền tệp/bảo mật và thử thách/giải pháp cho báo cáo kỹ thuật

**Tiêu chí hoàn thành**

- Tệp lớn hơn một chunk được truyền, ghép lại với kích thước và checksum khớp.
- Transfer lỗi/gián đoạn được nhận diện; tệp dở dang không bị xem là tệp hoàn chỉnh.
- Dữ liệu tệp chỉ đi qua kết nối TLS của ứng dụng.
- Cơ chế xác thực không lưu plaintext password; salt và tham số scrypt được lưu cần thiết để kiểm tra lại.
- Tên tệp và vị trí lưu không cho phép ghi tùy ý ra ngoài thư mục nhận.

**Phụ thuộc**

- Framing, schema message tệp và TLS từ Thành viên 1.
- Lệnh bắt đầu truyền và sự kiện hiển thị tiến độ từ Thành viên 2.

### Trách nhiệm chung — Tích hợp, kiểm thử và hồ sơ nộp

Cả ba thành viên cùng tích hợp và rà soát thay đổi ảnh hưởng đến giao diện chung. Mỗi người cập nhật tài liệu phần mình phụ trách. Chỉ định một người điều phối (đề xuất: Thành viên 1) để tập hợp kiến trúc/báo cáo và chuẩn bị hồ sơ nộp; vai trò này không chuyển quyền sở hữu code của thành viên khác.

## 6. Giao diện chung cần chốt trước khi code song song

Ghi các quyết định cuối cùng vào `docs/protocol.md` và cập nhật khi nhóm cùng đồng ý thay đổi.

### TCP framing và schema message

- TCP là luồng byte; một lần `recv()` không đảm bảo trả về trọn một message.
- Dùng frame tường minh, ví dụ tiền tố độ dài cố định theo sau bởi payload có độ dài tương ứng.
- Quy định giới hạn frame, mã hóa serialization (ví dụ JSON UTF-8 cho control message), cách xử lý frame lỗi và payload nhị phân.
- Quy định rõ TLS bọc socket trước khi truyền dữ liệu ứng dụng; framing được áp dụng bên trong luồng TLS.
- Mỗi message định nghĩa sender, recipient/room, ID nếu cần, trường bắt buộc, phản hồi, thời hạn và hành vi nếu người nhận offline.

### Nhóm message tối thiểu

Thống nhất tên và trường cho ít nhất:

- `HELLO` / `WELCOME`
- `REGISTER`, `AUTH`, `AUTH_OK`, `AUTH_FAIL`
- `USER_LIST`, `PRESENCE_ONLINE`, `PRESENCE_OFFLINE`
- `MSG_BROADCAST`, `MSG_DIRECT`
- `FILE_OFFER`, `FILE_ACCEPT`/`FILE_REJECT`, `FILE_CHUNK`, `FILE_END`, kết quả/lỗi transfer
- `PING`/`PONG` cho heartbeat TCP nếu cần
- `ERROR` thống nhất

### UDP discovery và heartbeat

- Mô tả mục đích, địa chỉ/cổng, schema datagram, chu kỳ heartbeat, timeout và cách server loại bỏ peer mất tích.
- UDP không đảm bảo giao nhận/thứ tự và có thể bị giả mạo; không gửi mật khẩu, nội dung tin nhắn hoặc dữ liệu tệp trên UDP.
- Tách rõ discovery server và danh sách user online do server quản lý. Không dùng broadcast UDP thay thế xác thực hay quyền quyết định trạng thái chính thức.
- Ghi phạm vi mạng demo: broadcast LAN có thể bị router/firewall chặn; README cần hướng dẫn chạy cùng mạng và mở đúng cổng khi cần.

### Hợp đồng truyền tệp

Thống nhất transfer ID, tên tệp an toàn, kích thước khai báo, kích thước chunk, chỉ số/vị trí chunk, dấu kết thúc, checksum, thư mục đích và cách dọn dẹp transfer dở dang. Không tin cậy đường dẫn do client gửi; chỉ lấy tên cơ sở và lưu trong thư mục nhận được cấu hình.

### Hợp đồng xác thực và bảo mật

- TCP chỉ chấp nhận thông tin đăng nhập sau khi TLS được thiết lập thành công.
- Client xác minh chứng chỉ server theo CA/chứng chỉ tin cậy được cấu hình; không tắt kiểm tra chứng chỉ trong chế độ thông thường.
- Server lưu username, salt, password hash và tham số/phiên bản KDF; không lưu mật khẩu nguyên văn.
- Dùng scrypt với salt ngẫu nhiên riêng cho mỗi tài khoản; chọn tham số đủ mạnh nhưng vẫn đáp ứng hiệu năng trên máy demo, ghi rõ trong `docs/security.md` và không tự ý thay đổi format dữ liệu giữa các thành viên.
- Không ghi thông tin đăng nhập, session secret, private key hay dữ liệu nhạy cảm vào log/Git.
- TLS bảo vệ dữ liệu trên đường truyền; scrypt bảo vệ kho mật khẩu. Cả hai cần được nêu trong báo cáo cùng giới hạn của môi trường demo.

## 7. Quy tắc phối hợp và tích hợp

- Tạo branch/PR nhỏ theo phần sở hữu; giữ nhánh chính trong trạng thái có thể chạy.
- Trước khi làm tính năng phụ thuộc vào module khác, thống nhất chữ ký hàm, schema và cách báo lỗi với người sở hữu module đó.
- Sau khi module khác đã phụ thuộc vào giao diện, không tự đổi schema/hàm public; thông báo và cập nhật tài liệu giao thức trước.
- Tích hợp theo dependency: protocol/framing/TLS và handshake → auth/session/discovery → CLI và nhắn tin → file transfer → phục hồi → mô phỏng nhiều client và hoàn thiện hồ sơ.
- Không commit chứng chỉ riêng tư, mật khẩu, database runtime, tệp người dùng hoặc khóa bí mật. Cung cấp script/hướng dẫn tạo chứng chỉ demo thay vì đưa private key lên repository.
- Theo dõi tiến độ bằng checklist ở Mục 3 và tiêu chí bàn giao từng thành viên, không cần chia theo tuần.
- Đề bài yêu cầu mô phỏng mạng nội bộ với nhiều terminal; ghi lại chính xác cấu hình, lệnh và kết quả quan sát được trong README/báo cáo.

## 8. Rủi ro và quyết định cần lưu ý

- **UDP:** discovery/heartbeat UDP thuộc phạm vi bắt buộc của nhóm. Cần demo trên cùng LAN/localhost phù hợp và trình bày rõ giới hạn broadcast/firewall.
- **Bảo mật:** phương án đã chốt là TLS cho TCP và scrypt cho mật khẩu lưu trữ. Cần cấu hình trust của chứng chỉ đúng; chứng chỉ tự tạo phù hợp demo nhưng không tương đương PKI doanh nghiệp.
- **Xác thực:** hệ thống có tài khoản được lưu và bảo vệ mật khẩu, nhưng phạm vi vẫn là ứng dụng môn học. Chỉ tuyên bố những bảo vệ đã triển khai và kiểm chứng.
- **Ngôn ngữ:** dùng Python thống nhất để tận dụng kinh nghiệm chung; chỉ dùng socket/ssl và thư viện được nhóm/giảng viên chấp nhận, không dùng framework mạng cấp cao bị đề cấm.

## 9. Checklist hồ sơ nộp

- [x] Có mã nguồn server và client Python.
- [x] README hướng dẫn dependency, cấu hình chứng chỉ/CA demo, khởi động server, kết nối nhiều client và dùng CLI.
- [x] `docs/architecture.md` có sơ đồ client-server và luồng UDP discovery.
- [x] `docs/protocol.md` mô tả framing, loại message TCP, schema UDP và các phản hồi lỗi.
- [x] `docs/state-diagrams.md` và `docs/sequence-diagrams.md` khớp implementation, gồm đăng nhập, nhắn tin, discovery và truyền tệp.
- [x] `docs/security.md` ghi TLS, cách xác minh chứng chỉ, lưu mật khẩu bằng scrypt, quản lý dữ liệu nhạy cảm và giới hạn bảo mật.
- [x] Hoàn thiện báo cáo PDF (`docs/report/technical-report.pdf` được biên dịch từ `docs/report/technical-report.md`) có kiến trúc, giao thức, sequence diagram và phản ánh thử thách/cách giải quyết.
- [x] Đã kiểm thử mô phỏng mạng nội bộ với nhiều client đồng thời (12 clients) và ghi lại kết quả thực tế.
- [x] Repository/ZIP không chứa private key, mật khẩu, database runtime hoặc tệp người dùng.
- [x] Hạn nộp chính thức đã xác nhận: 00:00 ngày 17/11/2026.

## 10. Thuật ngữ dùng trong dự án

- **Client–server:** client mở kết nối tới server; server xác thực và điều phối. Trong dự án này chat/file được server chuyển tiếp, không phải kết nối ngang hàng trực tiếp.
- **Raw socket:** dùng socket TCP/UDP cơ bản để tự xây dựng giao thức ứng dụng; không dùng HTTP framework hay WebSocket.
- **Framing:** quy tắc đánh dấu ranh giới message trên TCP. Repo dùng 4 byte ghi độ dài, sau đó là JSON payload.
- **TLS:** lớp bảo vệ kết nối TCP, mã hóa dữ liệu và xác minh server theo chứng chỉ được client tin cậy.
- **Discovery:** hỏi qua UDP để tìm địa chỉ server. Discovery không đăng nhập và không chứng minh server đáng tin; TLS vẫn phải xác minh sau đó.
- **Heartbeat:** thông điệp định kỳ để biết đường kết nối còn hoạt động. TCP `ping/pong` giúp giữ phiên ứng dụng; UDP heartbeat hiện chỉ được server xác nhận, không tạo/duy trì session người dùng.
- **Salt và `scrypt`:** salt ngẫu nhiên riêng cho mỗi tài khoản làm đầu vào cho KDF. `scrypt` tạo giá trị lưu trong database kèm thông số `kdf_params`; server so sánh kết quả bằng `hmac.compare_digest` khi đăng nhập. Đây là bảo vệ dữ liệu lưu, khác với TLS bảo vệ trên đường truyền.
- **Chunk/checksum:** chia file thành phần nhỏ (64 KiB) để gửi qua TLS; ghi tạm vào file `.part` và kiểm tra kích thước + mã băm SHA-256 đầu-cuối giúp phát hiện dữ liệu nhận bị thiếu/hỏng trước khi lưu chính thức.

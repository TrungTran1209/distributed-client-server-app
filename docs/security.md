# Bảo mật: mục tiêu, cách làm và giới hạn

## Yêu cầu của đề và lựa chọn của nhóm

Đề gốc yêu cầu mã hóa payload bằng thư viện mật mã chuẩn trước khi gửi và giải mã khi nhận; đề đưa TLS/SSL socket hoặc mã hóa đối xứng làm ví dụ. Nhóm chọn TLS cho toàn bộ TCP stream để không tự thiết kế thuật toán. Đề không quy định KDF mật khẩu; nhóm chọn `hashlib.scrypt` để không lưu mật khẩu nguyên bản. Hai cơ chế này bảo vệ hai nơi khác nhau.

## Dữ liệu khi truyền: TLS

- Server dùng `ssl.SSLContext(PROTOCOL_TLS_SERVER)` và yêu cầu tối thiểu TLS 1.2.
- Client dùng `ssl.create_default_context(cafile=...)`, do đó kiểm tra chuỗi chứng chỉ và hostname vẫn bật mặc định.
- TLS handshake hoàn tất trước message ứng dụng. Password, chat và các message TCP đều nằm trong kênh TLS.
- Chứng chỉ tự ký phù hợp demo nếu client tin cậy đúng chứng chỉ/CA và tên máy khớp SAN. Chứng chỉ tự ký không tự động có nghĩa là client đã xác minh danh tính đáng tin cậy.
- Discovery UDP chỉ cung cấp địa chỉ. Nó không xác thực server; client cần xác minh chứng chỉ khi kết nối TCP.

## Mật khẩu khi lưu: `scrypt`

- Database lưu username, salt riêng và giá trị dẫn xuất; không lưu password gốc.
- Code hiện dùng salt ngẫu nhiên 16 byte, `scrypt` với `n=2^14`, `r=8`, `p=1`, kết quả 32 byte và `hmac.compare_digest` khi so sánh.
- Đây là KDF cho mật khẩu, không phải mã hóa có thể giải ngược và không thay thế TLS.
- Password chỉ được gửi sau TLS. Không đưa password vào log, tài liệu, biến demo đã commit hoặc issue công khai.

## Tài sản không được commit

Không commit private key, password, database tài khoản runtime hoặc file người dùng. File mẫu `.env.example` chỉ nên có tên biến và giá trị giả, không chứa bí mật thật. Chứng chỉ/key demo được tạo ở máy chạy theo hướng dẫn trong [`../certs/README.md`](../certs/README.md).

## UDP và giới hạn

- UDP datagram không đảm bảo giao nhận, thứ tự hay danh tính người gửi; có thể mất hoặc bị giả mạo.
- Chỉ gửi dữ liệu discovery/heartbeat nhỏ. Không gửi password, session ID, chat hay file qua UDP.
- Server hiện trả heartbeat ACK nhưng không lưu UDP heartbeat để tạo/duy trì session TCP.

## Phần chưa hoàn tất và điều không nên tuyên bố

- File transfer chưa nối vào server; checksum/chunk module chưa được thực thi đầu-cuối. Chưa thể khẳng định dữ liệu file được kiểm tra khi nhận hoặc tiến độ được hiển thị.
- Chưa có bằng chứng mô phỏng mất gói, kết nối mạng bị ngắt, kiểm thử chứng chỉ sai hoặc tải 10–20 client trong lượt này.
- TLS bảo vệ đường truyền, `scrypt` bảo vệ password trong database. Những điều này không bảo vệ máy chủ bị chiếm quyền, không mã hóa database/file trên ổ đĩa, và không thay thế quy trình quản lý CA/thu hồi chứng chỉ.

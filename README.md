# Ứng dụng cộng tác Client–Server phân tán

> **Mục đích:** chạy một máy chủ và nhiều ứng dụng dòng lệnh để người dùng đăng nhập, xem ai đang trực tuyến và nhắn tin qua mạng cục bộ. Ứng dụng dùng TCP/TLS cho nội dung chính và UDP cho tìm máy chủ/nhịp kiểm tra.

## Đề bài và quyết định của nhóm

Đặc tả gốc cho phép làm cá nhân, theo cặp hoặc theo nhóm; cho phép CLI hoặc GUI; và cho phép Python, Java, C++ hoặc Go (có lưu ý giảng viên có thể giới hạn ngôn ngữ). Đề yêu cầu raw socket, cấm framework mạng cấp cao như HTTP framework và WebSocket, chấm 10 mốc, và yêu cầu mã nguồn, README từng bước cùng báo cáo kỹ thuật PDF.

Các lựa chọn sau là quyết định triển khai của nhóm, không phải những lựa chọn duy nhất mà đề bắt buộc: Python, nhóm ba người, CLI, TCP được bọc TLS, mật khẩu lưu bằng `scrypt`, và UDP discovery/heartbeat. Đề yêu cầu bảo vệ dữ liệu truyền nhưng cho phép lựa chọn giải pháp; nhóm chọn TLS thay cho tự thiết kế mã hóa. Việc lưu mật khẩu bằng `scrypt` là lựa chọn bổ sung của nhóm.


## Trạng thái tính năng hiện tại

| Tính năng | Trạng thái trong mã hiện có |
|---|---|
| TCP raw socket, TLS, xác minh chứng chỉ phía client | Đã có |
| Framing 4 byte độ dài + JSON | Đã có |
| Đăng ký, đăng nhập, trạng thái online, IP/cổng quan sát được | Đã có |
| Chat broadcast và nhắn riêng | Đã có |
| UDP discovery và heartbeat | Đã có; UDP heartbeat không xác thực người dùng hay giữ phiên TCP |
| CLI client và hướng dẫn chạy | Đã có |
| Truyền tệp đầu-cuối | Chưa có; server đang trả `server_busy`, các module transfer là khung |
| Mô phỏng mạng nhiều client | Chưa có bằng chứng trong repository hiện tại |
| Báo cáo kỹ thuật PDF | Có file nhưng chỉ chứa dòng “Technical report placeholder”; chưa phải báo cáo nộp được |

“Đã có” ở bảng này mô tả mã/tài liệu, không đồng nghĩa đã được kiểm thử thực tế trong lượt cập nhật này. Xem [kế hoạch nhóm](TEAM_PLAN.md) để biết đối chiếu đủ 10 mốc và phần còn thiếu.

## Yêu cầu cài đặt

- Python 3.11 trở lên.
- OpenSSL dòng lệnh để tạo chứng chỉ demo.
- Hai hoặc nhiều terminal để thử chat.

Mở PowerShell tại thư mục gốc repository:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Chương trình hiện chỉ dùng thư viện chuẩn của Python khi chạy.

## Tạo chứng chỉ demo

Client kiểm tra chuỗi tin cậy và hostname/IP. Với demo trên cùng máy, tạo chứng chỉ tự ký có SAN cho `localhost` và tin cậy chứng chỉ đó ở client:

```powershell
New-Item -ItemType Directory -Force certs | Out-Null
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 `
  -keyout certs/server.key -out certs/server.crt `
  -subj "/CN=localhost" `
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

Khi client kết nối qua LAN, SAN của chứng chỉ phải chứa đúng hostname hoặc IP mà client dùng. Tạo chứng chỉ phù hợp cho địa chỉ đó và cung cấp chứng chỉ CA/được tin cậy bằng `--ca`. Không tắt xác minh để né lỗi tên chứng chỉ. Giữ riêng tư `server.key`; file khóa/chứng chỉ đã được loại khỏi Git. Hướng dẫn chi tiết nằm ở [`certs/README.md`](certs/README.md).

## Chạy máy chủ

Trong terminal thứ nhất, chạy từ thư mục gốc:

```powershell
python -m collab.server.main --host 0.0.0.0 --port 37021 --udp-port 37020 `
  --cert certs/server.crt --key certs/server.key
```

Máy chủ tạo cơ sở dữ liệu tài khoản tại `data/users.sqlite3`. Có thể đổi địa chỉ, cổng, chứng chỉ và đường dẫn cơ sở dữ liệu bằng các tùy chọn của server. Khi chạy qua LAN, mở TCP `37021` và UDP `37020` trên firewall. Dùng `--advertise-host <IP-LAN>` nếu server thông báo sai địa chỉ có thể truy cập.

## Chạy các client

Trong terminal thứ hai, rồi lặp lại lệnh này ở terminal thứ ba để mở client thứ hai:

```powershell
python -m collab.client.main --host localhost --port 37021 --ca certs/server.crt
```

Client trong LAN dùng IP/hostname của server và chứng chỉ có SAN khớp:

```powershell
python -m collab.client.main --host 192.168.1.20 --port 37021 `
  --udp-port 37020 --ca certs/server.crt
```

Có thể dò máy chủ bằng UDP unicast tới localhost hoặc broadcast trong LAN:

```powershell
python -m collab.client.main --discover --udp-port 37020 --ca certs/server.crt
python -m collab.client.main --discover --broadcast --udp-port 37020 --ca certs/server.crt
```

Unicast tới IP LAN dùng `--discover-host <IP-LAN>`. Discovery chỉ tìm địa chỉ gợi ý; client vẫn phải xác minh TLS trên kết nối TCP. Router/firewall có thể chặn broadcast. Khi đó dùng `--host` trực tiếp.

## Dùng CLI

Tại dấu nhắc `collab>`:

| Lệnh | Tác dụng |
|---|---|
| `/register USER` | Tạo tài khoản; chương trình hỏi mật khẩu mà không hiện ký tự |
| `/login USER` | Đăng nhập; mật khẩu được hỏi riêng và không hiện trên màn hình |
| `/users` | Hiện danh sách online nhận lúc đăng nhập và cập nhật presence |
| `/all NỘI_DUNG` | Gửi tin broadcast đến những người khác đang online |
| `/msg USER NỘI_DUNG` | Gửi tin riêng |
| `/file PATH [USER]` | Hiện trạng thái transfer; server hiện chưa hỗ trợ nhận/gửi file |
| `/help` | Xem lệnh |
| `/quit` | Đăng xuất và đóng kết nối |

Thử với hai người: đăng ký và đăng nhập `alice` ở terminal 2; đăng ký và đăng nhập `bob` ở terminal 3; gửi `/all Xin chào` hoặc `/msg alice Chào bạn`. Máy chủ xác nhận đã định tuyến tin nhắn, không xác nhận người nhận đã đọc.

Mật khẩu và tin nhắn đi bên trong kết nối TLS đã xác minh. UDP chỉ mang discovery/heartbeat, không mang mật khẩu, tin nhắn, file hoặc thông tin đăng nhập. Client gửi `ping` qua TCP theo chu kỳ để phiên không bị idle timeout; UDP heartbeat không kéo dài phiên TCP.

## Tùy chọn và biến môi trường

Server hỗ trợ `--host`, `--port`, `--udp-port`, `--advertise-host`, `--cert`, `--key`, `--database`. Client hỗ trợ `--host`, `--port`, `--udp-port`, `--ca`, `--discover`, `--broadcast`, `--discover-host`, `--timeout`. Client đọc các biến `COLLAB_SERVER_HOST`, `COLLAB_SERVER_PORT`, `COLLAB_UDP_PORT`, `COLLAB_TLS_CA_FILE`. Việc kiểm tra chứng chỉ và hostname luôn được bật.

File cơ sở dữ liệu/tài khoản runtime nằm trong `data/`. Không commit cơ sở dữ liệu thật, mật khẩu, private key hoặc file người dùng.

## Giải thích nhanh kiến thức mạng

- **TCP là luồng byte:** một lần `recv()` có thể trả về một phần message hoặc nhiều phần. Vì thế ứng dụng thêm header 4 byte ghi độ dài payload để bên nhận biết cần đọc bao nhiêu byte.
- **TLS bọc TCP:** trước khi gửi JSON, hai bên bắt tay TLS; client xác minh server bằng CA/chứng chỉ và tên máy. TLS mã hóa và kiểm tra toàn vẹn dữ liệu truyền.
- **UDP không kết nối:** phù hợp hỏi “server ở đâu?” và heartbeat nhỏ; datagram có thể mất hoặc bị giả mạo. Server không dùng UDP để quyết định ai đã đăng nhập.
- **Thread nhận riêng:** client vừa chờ người dùng nhập lệnh vừa nhận message/presence từ server mà không cần đợi lệnh tiếp theo.
- **`scrypt` khác TLS:** TLS bảo vệ dữ liệu trên đường truyền; `scrypt` biến mật khẩu thành giá trị băm có salt để cơ sở dữ liệu không lưu mật khẩu gốc.

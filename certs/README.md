# Chứng chỉ demo

Thư mục này là nơi đặt chứng chỉ và khóa riêng trên máy chạy. Private key bị `.gitignore` loại khỏi Git và tuyệt đối không được commit.

## Tạo chứng chỉ tự ký cho localhost

Từ thư mục gốc repository trong PowerShell:

```powershell
New-Item -ItemType Directory -Force certs | Out-Null
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 `
  -keyout certs/server.key -out certs/server.crt `
  -subj "/CN=localhost" `
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

Khởi động server với `--cert certs/server.crt --key certs/server.key`, rồi chạy client với `--ca certs/server.crt --host localhost`. Client vẫn kiểm tra hostname. Nếu dùng IP/hostname LAN, cần tạo chứng chỉ có SAN chứa đúng IP/hostname đó và cung cấp CA/chứng chỉ phù hợp với `--ca`.

## Ranh giới tin cậy

Chứng chỉ tự ký được client tin cậy theo cấu hình chỉ phù hợp demo. Không bỏ xác minh TLS để giải quyết lỗi chứng chỉ. Với triển khai thật, cần CA được quản lý phù hợp, bảo vệ khóa riêng và quy trình thay/thu hồi chứng chỉ.

Server hiện đọc đường dẫn bằng `--cert` và `--key`; client đọc CA bằng `--ca` hoặc biến `COLLAB_TLS_CA_FILE`. Repository hiện không tự nạp file `.env`.

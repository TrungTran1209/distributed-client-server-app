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

Khởi động server với `--host 127.0.0.1 --cert certs/server.crt --key certs/server.key` (khi demo trên 1 máy), rồi chạy client với `--ca certs/server.crt --discover` (hoặc `--host 127.0.0.1`). Client luôn kiểm tra hostname/IP trong `subjectAltName` (SAN). Nếu chạy qua mạng LAN với `--host 0.0.0.0`, hãy tạo chứng chỉ có SAN chứa cả `IP:127.0.0.1` lẫn IP LAN của máy chủ (ví dụ `DNS:localhost,IP:127.0.0.1,IP:192.168.1.20`), có thể chỉ định thêm `--advertise-host 192.168.1.20` và cung cấp chứng chỉ/CA qua `--ca`.

## Ranh giới tin cậy

Chứng chỉ tự ký được client tin cậy theo cấu hình chỉ phù hợp demo. Không bỏ xác minh TLS để giải quyết lỗi chứng chỉ. Với triển khai thật, cần CA được quản lý phù hợp, bảo vệ khóa riêng và quy trình thay/thu hồi chứng chỉ.

Server hiện đọc đường dẫn bằng `--cert` và `--key`; client đọc CA bằng `--ca` hoặc biến `COLLAB_TLS_CA_FILE`. Repository hiện không tự nạp file `.env`.

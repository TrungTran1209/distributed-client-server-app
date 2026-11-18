"""Dialog that generates a self-signed demo certificate with proper SAN entries.

Certificate verification is never disabled: the generated certificate must be
used as the CA file by clients, and its SAN must match the address they dial.
"""
from __future__ import annotations

import datetime
import ipaddress
import os
import stat
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


def generate_self_signed(
    out_dir: str | Path,
    common_name: str = "localhost",
    ips: list[str] | None = None,
    hostnames: list[str] | None = None,
    days: int = 365,
) -> tuple[str, str]:
    """Write ``server.crt`` / ``server.key`` into ``out_dir``; return their paths."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    names: list[x509.GeneralName] = []
    for host in {common_name, *(hostnames or [])}:
        if host:
            try:
                names.append(x509.IPAddress(ipaddress.ip_address(host)))
            except ValueError:
                names.append(x509.DNSName(host))
    for ip in ips or []:
        names.append(x509.IPAddress(ipaddress.ip_address(ip)))  # raises ValueError on bad input
    if not names:
        raise ValueError("Cần ít nhất một hostname hoặc IP trong SAN.")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name or "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = out / "server.crt", out / "server.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    try:
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return str(cert_path), str(key_path)


class CertGenDialog(QDialog):
    generated = Signal(str, str)  # cert path, key path

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tạo chứng chỉ TLS (demo)")
        self.setMinimumWidth(480)
        self._cn = QLineEdit("localhost")
        self._ips = QLineEdit("127.0.0.1")
        self._hosts = QLineEdit("localhost")
        self._out = QLineEdit("certs")
        browse = QPushButton("Chọn…")
        browse.clicked.connect(self._browse)
        out_row = QHBoxLayout()
        out_row.addWidget(self._out)
        out_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Common Name", self._cn)
        form.addRow("SAN – địa chỉ IP", self._ips)
        form.addRow("SAN – hostname", self._hosts)
        form.addRow("Thư mục lưu", out_row)

        hint = QLabel(
            "Hãy liệt kê đúng IP LAN mà client sẽ dùng (ví dụ 192.168.1.10), cách nhau bằng dấu phẩy. "
            "Client cần chọn file server.crt này làm CA."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._btn = QPushButton("Tạo chứng chỉ")
        self._btn.setObjectName("primary")
        self._btn.clicked.connect(self._generate)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self._result)
        layout.addWidget(self._btn)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu chứng chỉ")
        if folder:
            self._out.setText(folder)

    @staticmethod
    def _split(text: str) -> list[str]:
        return [part.strip() for part in text.split(",") if part.strip()]

    def _generate(self) -> None:
        try:
            cert, key = generate_self_signed(
                self._out.text().strip() or "certs",
                self._cn.text().strip() or "localhost",
                self._split(self._ips.text()),
                self._split(self._hosts.text()),
            )
        except ImportError:
            self._show("Cần thư viện 'cryptography' (pip install cryptography) hoặc tạo bằng OpenSSL.", True)
        except (ValueError, OSError) as exc:
            self._show(f"Không tạo được chứng chỉ: {exc}", True)
        else:
            self._show(f"Đã tạo: {cert}", False)
            self.generated.emit(cert, key)

    def _show(self, text: str, error: bool) -> None:
        self._result.setObjectName("error" if error else "")
        self._result.setStyleSheet(
            "color: #DC2626; font-weight: 700;" if error else "color: #059669; font-weight: 700;"
        )
        self._result.setText(text)

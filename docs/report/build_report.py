"""Compile `docs/report/technical-report.md` into `docs/report/technical-report.pdf` using stdlib + headless Chromium/Edge."""

from __future__ import annotations

import html
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

REPORT_DIR = Path(__file__).resolve().parent
MD_PATH = REPORT_DIR / "technical-report.md"
PDF_PATH = REPORT_DIR / "technical-report.pdf"

SVG_ARCHITECTURE = """
<div class="diagram-box">
  <div class="diagram-caption">Hình 1: Kiến trúc Tổng thể Hệ thống Client–Server qua TCP/TLS và UDP Discovery</div>
  <svg viewBox="0 0 760 220" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Arial, sans-serif">
    <defs>
      <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb"/>
      </marker>
      <marker id="arr-udp" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"/>
      </marker>
    </defs>
    <!-- Client A -->
    <rect x="12" y="16" width="185" height="84" rx="8" fill="#eff6ff" stroke="#2563eb" stroke-width="1.5"/>
    <text x="104" y="38" text-anchor="middle" font-size="11.5" font-weight="700" fill="#1e3a8a">Client CLI A (Sender)</text>
    <text x="104" y="57" text-anchor="middle" font-size="9.5" fill="#334155">CommandLine + FileSender</text>
    <text x="104" y="74" text-anchor="middle" font-size="9.5" fill="#334155">ClientConnection (TLS 1.2+)</text>
    <text x="104" y="90" text-anchor="middle" font-size="9" fill="#64748b">UDP Discover / Heartbeat</text>

    <!-- Client B -->
    <rect x="12" y="120" width="185" height="84" rx="8" fill="#eff6ff" stroke="#2563eb" stroke-width="1.5"/>
    <text x="104" y="142" text-anchor="middle" font-size="11.5" font-weight="700" fill="#1e3a8a">Client CLI B (Receiver)</text>
    <text x="104" y="161" text-anchor="middle" font-size="9.5" fill="#334155">FileReceiver (.part + SHA-256)</text>
    <text x="104" y="178" text-anchor="middle" font-size="9.5" fill="#334155">ClientConnection (TLS 1.2+)</text>
    <text x="104" y="194" text-anchor="middle" font-size="9" fill="#64748b">downloads/ (Safe Path)</text>

    <!-- Server -->
    <rect x="330" y="16" width="245" height="188" rx="8" fill="#f8fafc" stroke="#0f172a" stroke-width="1.5"/>
    <text x="452" y="38" text-anchor="middle" font-size="12" font-weight="700" fill="#0f172a">Collaboration Server</text>
    <rect x="346" y="48" width="213" height="32" rx="5" fill="#dbeafe" stroke="#3b82f6"/>
    <text x="452" y="68" text-anchor="middle" font-size="9.5" font-weight="600" fill="#1e3a8a">TCP/TLS Worker Pool (Port 37021)</text>
    <rect x="346" y="88" width="213" height="32" rx="5" fill="#e0f2fe" stroke="#0284c7"/>
    <text x="452" y="108" text-anchor="middle" font-size="9.5" font-weight="600" fill="#0c4a6e">SessionRegistry + MessageRouter</text>
    <rect x="346" y="128" width="213" height="32" rx="5" fill="#dcfce7" stroke="#16a34a"/>
    <text x="452" y="148" text-anchor="middle" font-size="9.5" font-weight="600" fill="#14532d">TransferCoordinator (O(1) RAM Relay)</text>
    <rect x="346" y="166" width="213" height="28" rx="5" fill="#f1f5f9" stroke="#64748b"/>
    <text x="452" y="184" text-anchor="middle" font-size="9" fill="#334155">DiscoveryServer UDP (Port 37020)</text>

    <!-- SQLite -->
    <rect x="612" y="54" width="136" height="84" rx="8" fill="#fefce8" stroke="#ca8a04" stroke-width="1.5"/>
    <text x="680" y="78" text-anchor="middle" font-size="11" font-weight="700" fill="#854d0e">SQLite WAL</text>
    <text x="680" y="96" text-anchor="middle" font-size="9" fill="#713f12">username, 16B salt</text>
    <text x="680" y="112" text-anchor="middle" font-size="9" fill="#713f12">32B scrypt digest</text>
    <text x="680" y="127" text-anchor="middle" font-size="8.8" fill="#713f12">kdf_params (v1)</text>

    <!-- Arrows -->
    <line x1="197" y1="52" x2="328" y2="62" stroke="#2563eb" stroke-width="1.6" marker-start="url(#arr)" marker-end="url(#arr)"/>
    <text x="262" y="48" text-anchor="middle" font-size="8.5" font-weight="600" fill="#1d4ed8">4B Frame + JSON / TLS</text>

    <line x1="197" y1="150" x2="328" y2="140" stroke="#2563eb" stroke-width="1.6" marker-start="url(#arr)" marker-end="url(#arr)"/>
    <text x="262" y="136" text-anchor="middle" font-size="8.5" font-weight="600" fill="#1d4ed8">4B Frame + JSON / TLS</text>

    <line x1="197" y1="88" x2="344" y2="178" stroke="#64748b" stroke-width="1.2" stroke-dasharray="4 3" marker-end="url(#arr-udp)"/>
    <text x="262" y="188" text-anchor="middle" font-size="8.2" fill="#475569">UDP discover / heartbeat</text>

    <line x1="575" y1="96" x2="610" y2="96" stroke="#ca8a04" stroke-width="1.5" marker-end="url(#arr-udp)"/>
  </svg>
</div>
"""

SVG_SEQUENCE = """
<div class="diagram-box">
  <div class="diagram-caption">Hình 2: Sơ đồ Tuần tự (Sequence Diagram) Luồng Truyền tệp Đáng tin cậy qua TCP/TLS</div>
  <svg viewBox="0 0 760 330" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Arial, sans-serif">
    <defs>
      <marker id="seq-solid" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#1d4ed8"/>
      </marker>
      <marker id="seq-dash" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#15803d"/>
      </marker>
    </defs>
    <!-- Participants -->
    <rect x="45" y="10" width="150" height="30" rx="5" fill="#eff6ff" stroke="#2563eb" stroke-width="1.4"/>
    <text x="120" y="29" text-anchor="middle" font-size="10.5" font-weight="700" fill="#1e3a8a">Client A (FileSender)</text>
    <rect x="295" y="10" width="170" height="30" rx="5" fill="#f8fafc" stroke="#0f172a" stroke-width="1.4"/>
    <text x="380" y="29" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0f172a">Server (Coordinator)</text>
    <rect x="565" y="10" width="150" height="30" rx="5" fill="#eff6ff" stroke="#2563eb" stroke-width="1.4"/>
    <text x="640" y="29" text-anchor="middle" font-size="10.5" font-weight="700" fill="#1e3a8a">Client B (FileReceiver)</text>

    <!-- Lifelines -->
    <line x1="120" y1="40" x2="120" y2="318" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="4 3"/>
    <line x1="380" y1="40" x2="380" y2="318" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="4 3"/>
    <line x1="640" y1="40" x2="640" y2="318" stroke="#94a3b8" stroke-width="1.2" stroke-dasharray="4 3"/>

    <!-- 1. Offer -->
    <line x1="120" y1="62" x2="376" y2="62" stroke="#1d4ed8" stroke-width="1.4" marker-end="url(#seq-solid)"/>
    <text x="250" y="57" text-anchor="middle" font-size="8.8" fill="#1e293b">1. file_offer(transfer_id, filename, size, sha256, total_chunks)</text>

    <line x1="380" y1="82" x2="636" y2="82" stroke="#15803d" stroke-width="1.4" stroke-dasharray="4 2" marker-end="url(#seq-dash)"/>
    <text x="510" y="77" text-anchor="middle" font-size="8.8" fill="#14532d">2. file_offer_event(metadata, expires_in=60s)</text>

    <line x1="380" y1="98" x2="124" y2="98" stroke="#15803d" stroke-width="1.2" stroke-dasharray="4 2" marker-end="url(#seq-dash)"/>
    <text x="250" y="94" text-anchor="middle" font-size="8.5" fill="#475569">file_offer_result(ok=true)</text>

    <!-- 2. Accept -->
    <line x1="640" y1="124" x2="384" y2="124" stroke="#1d4ed8" stroke-width="1.4" marker-end="url(#seq-solid)"/>
    <text x="510" y="119" text-anchor="middle" font-size="8.8" fill="#1e293b">3. Mở độc quyền .part rồi gửi file_accept(transfer_id)</text>

    <line x1="380" y1="144" x2="124" y2="144" stroke="#15803d" stroke-width="1.4" stroke-dasharray="4 2" marker-end="url(#seq-dash)"/>
    <text x="250" y="139" text-anchor="middle" font-size="8.8" fill="#14532d">4. file_decision(accepted=true, by="bob")</text>

    <!-- 3. Chunk loop -->
    <rect x="65" y="156" width="630" height="62" rx="4" fill="#f8fafc" fill-opacity="0.65" stroke="#cbd5e1"/>
    <text x="75" y="169" font-size="8.5" font-weight="700" fill="#334155">LOOP [index = 0 .. total_chunks - 1]</text>
    <line x1="120" y1="182" x2="376" y2="182" stroke="#1d4ed8" stroke-width="1.4" marker-end="url(#seq-solid)"/>
    <text x="250" y="177" text-anchor="middle" font-size="8.8" fill="#1e293b">5. file_chunk(index, base64_64KiB)</text>
    <line x1="380" y1="196" x2="636" y2="196" stroke="#15803d" stroke-width="1.4" stroke-dasharray="4 2" marker-end="url(#seq-dash)"/>
    <text x="510" y="191" text-anchor="middle" font-size="8.8" fill="#14532d">6. file_chunk_event -&gt; ghi .part + băm SHA-256</text>
    <line x1="380" y1="210" x2="124" y2="210" stroke="#15803d" stroke-width="1.2" stroke-dasharray="4 2" marker-end="url(#seq-dash)"/>
    <text x="250" y="207" text-anchor="middle" font-size="8.2" fill="#475569">file_chunk_result(ok=true, index)</text>

    <!-- 4. End & Ack -->
    <line x1="120" y1="238" x2="376" y2="238" stroke="#1d4ed8" stroke-width="1.4" marker-end="url(#seq-solid)"/>
    <text x="250" y="233" text-anchor="middle" font-size="8.8" fill="#1e293b">7. file_end(transfer_id, size, sha256)</text>

    <line x1="380" y1="256" x2="636" y2="256" stroke="#15803d" stroke-width="1.4" stroke-dasharray="4 2" marker-end="url(#seq-dash)"/>
    <text x="510" y="251" text-anchor="middle" font-size="8.8" fill="#14532d">8. file_end_event -&gt; kiểm tra SHA-256 &amp; os.replace(.part)</text>

    <line x1="640" y1="282" x2="384" y2="282" stroke="#1d4ed8" stroke-width="1.4" marker-end="url(#seq-solid)"/>
    <text x="510" y="277" text-anchor="middle" font-size="8.8" fill="#1e293b">9. file_ack(ok=true, sha256)</text>

    <line x1="380" y1="304" x2="124" y2="304" stroke="#15803d" stroke-width="1.4" stroke-dasharray="4 2" marker-end="url(#seq-dash)"/>
    <text x="250" y="299" text-anchor="middle" font-size="8.8" font-weight="600" fill="#14532d">10. file_status(ok=true, sha256 khớp đầu-cuối)</text>
  </svg>
</div>
"""


def _inline_md(text: str) -> str:
    code_spans: list[str] = []

    def _stash_code(match: re.Match[str]) -> str:
        idx = len(code_spans)
        code_spans.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00CODE{idx}\x00"

    stashed = re.sub(r"`([^`]+)`", _stash_code, text)
    escaped = html.escape(stashed)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    for idx, span_html in enumerate(code_spans):
        escaped = escaped.replace(f"\x00CODE{idx}\x00", span_html)
    return escaped


def _render_table(lines: list[str]) -> str:
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return ""
    header = rows[0]
    body = [r for r in rows[2:] if any(r)]
    parts = ["<table><thead><tr>"]
    for cell in header:
        parts.append(f"<th>{_inline_md(cell)}</th>")
    parts.append("</tr></thead><tbody>")
    for row in body:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{_inline_md(cell)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def markdown_to_html(md_text: str) -> str:
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    in_ul = False
    in_ol = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            close_lists()
            i += 1
            continue

        if stripped == "{{DIAGRAM_ARCHITECTURE}}":
            close_lists()
            out.append(SVG_ARCHITECTURE)
            i += 1
            continue

        if stripped == "{{DIAGRAM_SEQUENCE}}":
            close_lists()
            out.append(SVG_SEQUENCE)
            i += 1
            continue

        if stripped == "---":
            close_lists()
            out.append("<hr/>")
            i += 1
            continue

        if stripped.startswith("```"):
            close_lists()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(html.escape(lines[i]))
                i += 1
            out.append("<pre><code>" + "\n".join(code_lines) + "</code></pre>")
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            close_lists()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            out.append(_render_table(table_lines))
            continue

        heading_match = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading_match:
            close_lists()
            level = len(heading_match.group(1))
            out.append(f"<h{level}>{_inline_md(heading_match.group(2))}</h{level}>")
            i += 1
            continue

        ol_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ol_match:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline_md(ol_match.group(1))}</li>")
            i += 1
            continue

        ul_match = re.match(r"^-\s+(.*)$", stripped)
        if ul_match:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_md(ul_match.group(1))}</li>")
            i += 1
            continue

        close_lists()
        para = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt in {"---", "{{DIAGRAM_ARCHITECTURE}}", "{{DIAGRAM_SEQUENCE}}"}
                or nxt.startswith(("#", "- ", "```", "|"))
                or re.match(r"^\d+\.\s+", nxt)
            ):
                break
            para.append(nxt)
            i += 1
        out.append(f"<p>{_inline_md(' '.join(para))}</p>")

    close_lists()
    body_html = "\n".join(out)
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8"/>
<title>Báo cáo Kỹ thuật — Ứng dụng Cộng tác Client–Server Phân tán</title>
<style>
  @page {{ size: A4; margin: 16mm 15mm 16mm 15mm; }}
  body {{
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10.2pt;
    line-height: 1.48;
    color: #1e293b;
  }}
  h1 {{
    font-size: 17.5pt;
    color: #0f172a;
    border-bottom: 2px solid #2563eb;
    padding-bottom: 6px;
    margin-top: 0;
  }}
  h2 {{
    font-size: 13pt;
    color: #1d4ed8;
    margin-top: 16px;
    margin-bottom: 6px;
    page-break-after: avoid;
  }}
  h3 {{
    font-size: 11pt;
    color: #0f172a;
    margin-top: 11px;
    margin-bottom: 4px;
    page-break-after: avoid;
  }}
  p, li {{ text-align: justify; }}
  ul, ol {{ margin-top: 4px; margin-bottom: 8px; padding-left: 20px; }}
  li {{ margin-bottom: 3px; }}
  code {{
    font-family: Consolas, "Courier New", monospace;
    font-size: 9pt;
    background: #f1f5f9;
    padding: 1px 4px;
    border-radius: 3px;
  }}
  pre {{
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 8px 10px;
    overflow-x: auto;
    font-size: 8.8pt;
  }}
  pre code {{ background: transparent; padding: 0; }}
  .diagram-box {{
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 8px 10px;
    margin: 10px 0 14px 0;
    background: #ffffff;
    page-break-inside: avoid;
  }}
  .diagram-caption {{
    font-size: 9.2pt;
    font-weight: 600;
    color: #1e3a8a;
    text-align: center;
    margin-bottom: 6px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 14px 0;
    font-size: 9.2pt;
    page-break-inside: avoid;
  }}
  th, td {{
    border: 1px solid #cbd5e1;
    padding: 6px 8px;
    vertical-align: top;
    text-align: left;
  }}
  th {{
    background: #eff6ff;
    color: #1e3a8a;
    font-weight: 600;
  }}
  tr:nth-child(even) td {{ background: #f8fafc; }}
  hr {{
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 12px 0;
  }}
</style>
</head>
<body>
{body_html}
</body>
</html>
"""


def _find_browser() -> str:
    for cmd in ("msedge", "chrome", "chromium", "google-chrome"):
        found = shutil.which(cmd)
        if found:
            return found
    windows_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in windows_paths:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("No Chromium/Edge browser found to print HTML report to PDF")


def build_pdf() -> Path:
    md_content = MD_PATH.read_text(encoding="utf-8")
    rendered_html = markdown_to_html(md_content)
    browser = _find_browser()

    with tempfile.TemporaryDirectory() as tmp:
        html_file = Path(tmp) / "report.html"
        out_pdf = Path(tmp) / "technical-report.pdf"
        html_file.write_text(rendered_html, encoding="utf-8")
        subprocess.run(
            [
                browser,
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out_pdf}",
                html_file.resolve().as_uri(),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not out_pdf.is_file() or out_pdf.stat().st_size < 10_000:
            raise RuntimeError("Generated PDF appears incomplete or empty")
        shutil.copyfile(out_pdf, PDF_PATH)
    return PDF_PATH


if __name__ == "__main__":
    target = build_pdf()
    print(f"Generated {target} ({target.stat().st_size:,} bytes)")

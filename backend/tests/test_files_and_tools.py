import io, json, logging, zipfile
import pytest
from app.storage.paths import UnsafePath, safe_path
from app.storage.validation import InvalidUpload, validate_upload
from app.storage.extract import chunk_text, extract_text
from app.services.codefs import make_diff, parse_file_blocks
from app.services.sandbox import build_command
from app.utils.logging import JsonFormatter, redact


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../b", "a\\b", "C:/x", "a//b", "", "a\x00b", "~/x"])
def test_unsafe_paths_rejected(bad):
    with pytest.raises(UnsafePath):
        safe_path(bad)


def test_safe_path_ok():
    assert safe_path("src/app/main.py") == "src/app/main.py"


def test_upload_rules():
    assert validate_upload("a.py", b"print(1)", 1000).is_text
    for name, data in [("a.exe", b"MZ"), ("a.pdf", b"not a pdf"), ("a.png", b"GIF89a"), ("a.txt", b""),
                       ("a.txt", b"\xff\xfe\x00"), ("a.txt", b"x" * 2000)]:
        with pytest.raises(InvalidUpload):
            validate_upload(name, data, 1000)
    assert validate_upload("p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 10, 1000).ext == "png"


def test_chunking_overlaps_and_covers():
    t = "abcdefghij" * 300
    cs = chunk_text(t, 1000, 100)
    assert cs[0] == t[:1000] and cs[1].startswith(t[900:910]) and cs[-1].endswith(t[-10:])
    assert chunk_text("   ") == []


def test_extract_json_csv_zip():
    assert "a" in extract_text("json", b'{"a": 1}')
    assert "x | y" in extract_text("csv", b"x,y\n1,2")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("src/a.py", "print()")
    assert "src/a.py" in extract_text("zip", buf.getvalue())


def test_parse_file_blocks_blocks_traversal():
    out = "x\n```python path=src/ok.py\nprint(1)\n```\n```sh path=../../etc/cron\nbad\n```\n"
    files, rejected = parse_file_blocks(out)
    assert files == {"src/ok.py": "print(1)"} and rejected == ["../../etc/cron"]


def test_diff():
    d = make_diff("a\nb\n", "a\nc\n", "f.txt")
    assert "-b" in d and "+c" in d and "b/f.txt" in d


def test_sandbox_command_is_locked_down():
    cmd = build_command("python", "/tmp/w", name="n")
    for flag in ("--network", "none", "--read-only", "--pids-limit", "--cap-drop", "ALL"):
        assert flag in cmd
    assert cmd[cmd.index("--network") + 1] == "none" and cmd[-2:] == ["python", "/work/main.py"]
    with pytest.raises(ValueError):
        build_command("bash", "/tmp/w", name="n")


def test_logs_never_contain_secrets():
    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"
    assert "eyJ" not in redact(f"token {jwt_like}")
    assert "hunter2" not in redact('login password="hunter2" ok')
    assert "sk-abcdefghijklmnop" not in redact("key sk-abcdefghijklmnop")
    rec = logging.LogRecord("x", logging.INFO, "", 0, "password=%s", ("hunter2",), None)
    line = JsonFormatter("api").format(rec)
    assert "hunter2" not in line and json.loads(line)["service"] == "api"

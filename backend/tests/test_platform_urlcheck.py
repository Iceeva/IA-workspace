import socket

from app.services.urlcheck import validate_provider_url


def fake(ip):
    return lambda host, port, proto=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


def bad(url, **kw):
    try:
        validate_provider_url(url, **kw); assert False, url
    except ValueError:
        pass


def test_public_https_accepted_and_normalized():
    assert validate_provider_url("https://api.mistral.ai/v1/", resolver=fake("93.184.216.34")) == "https://api.mistral.ai/v1"


def test_private_ranges_and_metadata_endpoint_refused():
    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.9", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1"):
        bad("https://x.example/v1", resolver=fake(ip))


def test_scheme_credentials_and_unresolvable_host():
    bad("ftp://x.example"); bad("https://u:p@x.example/v1", resolver=fake("93.184.216.34"))
    bad("http://api.example/v1", resolver=fake("93.184.216.34")); bad("not a url")
    def boom(*a, **k): raise OSError("nx")
    bad("https://nx.example", resolver=boom)


def test_self_hosted_may_allow_private_http():
    assert validate_provider_url("http://localhost:11434/v1", allow_private=True) == "http://localhost:11434/v1"

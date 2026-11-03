"""Real disposable PostgreSQL TLS and production-container smoke; no live AI/auth.

Explicit suite: requires Docker and TRACE_TEST_BACKEND_IMAGE built from this tree.
All certificates and credentials are newly generated test fixtures outside Git.
"""

import ipaddress
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError


def postgres_image():
    """An operator override must pin the official repository, never another image."""
    selected = os.environ.get("TRACE_TEST_POSTGRES_IMAGE")
    if selected is None:
        return "postgres:15-alpine"
    if not re.fullmatch(r"docker\.io/library/postgres@sha256:[0-9a-f]{64}", selected):
        raise ValueError("The PostgreSQL test override must pin the official image digest")
    return selected


def docker(*args, check=True, timeout=60):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(
            "Disposable infrastructure command failed; inspect the named test container"
        )
    return result


def container_private_ipv4(name):
    # Docker API 1.52 removed NetworkSettings.IPAddress. The fixture uses one
    # bridge endpoint; inspect its supported per-network address instead.
    networks = json.loads(
        docker("inspect", "--format", "{{json .NetworkSettings.Networks}}", name).stdout
    )
    assert isinstance(networks, dict) and len(networks) == 1
    endpoint = next(iter(networks.values()))
    assert isinstance(endpoint, dict)
    address = ipaddress.ip_address(endpoint["IPAddress"])
    assert address.version == 4 and address.is_private and not address.is_loopback
    return str(address)


def wait_for_postgres_tcp(name):
    # Initialization briefly serves only a Unix socket before restarting. Never
    # treat that temporary server as readiness for the published TCP/TLS port.
    deadline = time.monotonic() + 40
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Disposable PostgreSQL TLS did not become ready")
        result = docker(
            "exec",
            name,
            "pg_isready",
            "-h",
            "127.0.0.1",
            "-p",
            "5432",
            "-U",
            "trace_test",
            "-d",
            "trace_test",
            "-t",
            "1",
            check=False,
            timeout=remaining,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Disposable PostgreSQL TLS did not become ready")
        if result.returncode == 0:
            return
        time.sleep(min(0.2, remaining))


def stop_owned(name, label):
    found = docker(
        "inspect", "--format", '{{index .Config.Labels "codex-test"}}', name, check=False
    )
    if found.returncode == 0:
        if found.stdout.strip() != label:
            raise RuntimeError("Refusing to stop an unrelated container")
        docker("stop", "--time", "5", name)


def certificate(name, key, issuer, signing_key, ca=False):
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True)
    )
    if not ca:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
    return builder.sign(signing_key, hashes.SHA256())


@pytest.fixture(scope="module")
def tls_postgres(tmp_path_factory):
    directory = tmp_path_factory.mktemp("trace-disposable-tls")
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Trace disposable test CA")])
    ca = certificate("Trace disposable test CA", ca_key, issuer, ca_key, ca=True)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = certificate("localhost", server_key, ca.subject, ca_key)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong = certificate("Wrong disposable CA", wrong_key, issuer, wrong_key, ca=True)
    for name, cert in (("ca.crt", ca), ("server.crt", server), ("wrong.crt", wrong)):
        (directory / name).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "server.key").write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    name = "trace-pg-tls-test-" + uuid4().hex[:12]
    label = "trace-disposable-tls-" + uuid4().hex
    command = (
        "mkdir -p /var/lib/postgresql/test-certs; "
        "cp /fixtures/server.crt /fixtures/server.key /fixtures/ca.crt "
        "/var/lib/postgresql/test-certs/; "
        "chown -R postgres:postgres /var/lib/postgresql/test-certs; "
        "chmod 600 /var/lib/postgresql/test-certs/server.key; "
        "exec docker-entrypoint.sh postgres -c ssl=on "
        "-c ssl_cert_file=/var/lib/postgresql/test-certs/server.crt "
        "-c ssl_key_file=/var/lib/postgresql/test-certs/server.key "
        "-c ssl_ca_file=/var/lib/postgresql/test-certs/ca.crt"
    )
    docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--label",
        "codex-test=" + label,
        "--cpus",
        "1",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--pids-limit",
        "128",
        "--shm-size",
        "128m",
        "--tmpfs",
        "/var/lib/postgresql/data:rw,size=256m",
        "--publish",
        "127.0.0.1::5432",
        "--mount",
        f"type=bind,source={directory},target=/fixtures,readonly",
        "--env",
        "POSTGRES_USER=trace_test",
        "--env",
        "POSTGRES_PASSWORD=trace_disposable_test_only",
        "--env",
        "POSTGRES_DB=trace_test",
        "--entrypoint",
        "sh",
        postgres_image(),
        "-c",
        command,
    )
    try:
        wait_for_postgres_tcp(name)
        raw = docker("inspect", "--format", "{{json .NetworkSettings.Ports}}", name).stdout
        port = int(json.loads(raw)["5432/tcp"][0]["HostPort"])
        yield dict(name=name, label=label, directory=directory, port=port)
    finally:
        stop_owned(name, label)


def database_url(fixture, **query):
    return URL.create(
        "postgresql+psycopg",
        username="trace_test",
        password="trace_disposable_test_only",
        host="127.0.0.1",
        port=fixture["port"],
        database="trace_test",
        query={"sslmode": "verify-full", "sslrootcert": str(fixture["directory"] / "ca.crt")}
        | query,
    )


def test_actual_postgresql_certificate_and_hostname_validation(tls_postgres):
    engine = create_engine(
        database_url(tls_postgres), hide_parameters=True, connect_args={"connect_timeout": 3}
    )
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"))
                is True
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure", ["ca", "hostname"])
def test_wrong_ca_or_hostname_is_rejected(tls_postgres, failure):
    query = (
        {"sslrootcert": str(tls_postgres["directory"] / "wrong.crt")}
        if failure == "ca"
        else {"hostaddr": "127.0.0.1"}
    )
    url = database_url(tls_postgres, **query)
    if failure == "hostname":
        url = url.set(host="wrong-certificate.invalid")
    engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 3})
    try:
        with pytest.raises(OperationalError), engine.connect():
            pass
    finally:
        engine.dispose()


def test_production_image_migration_and_startup_over_verified_tls(tls_postgres):
    image = os.environ.get("TRACE_TEST_BACKEND_IMAGE")
    if not image:
        pytest.fail(
            "Build this tree and set TRACE_TEST_BACKEND_IMAGE for production-container acceptance"
        )
    fixture = tls_postgres
    docker(
        "exec",
        fixture["name"],
        "psql",
        "-U",
        "trace_test",
        "-d",
        "trace_test",
        "-c",
        "CREATE SCHEMA trace_tls_smoke AUTHORIZATION trace_test",
    )
    values = {
        "TRACE_ENVIRONMENT": "production",
        "TRACE_DATABASE_SCHEMA": "trace_tls_smoke",
        "TRACE_DATABASE_URL": "postgresql+psycopg://trace_test:trace_disposable_test_only@127.0.0.1:5432/trace_test?sslmode=verify-full&sslrootcert=/tls/ca.crt",
        "TRACE_CORS_ORIGINS": '["https://trace.example"]',
        "TRACE_TRUSTED_PROXY_IPS": "127.0.0.1/32",
        "TRACE_SUPABASE_URL": "https://synthetic.supabase.co",
        "TRACE_SUPABASE_ISSUER": "https://synthetic.supabase.co/auth/v1",
        "TRACE_SUPABASE_JWKS_URL": "https://synthetic.supabase.co/auth/v1/.well-known/jwks.json",
        "TRACE_LLM_MODE": "disabled",
        "TRACE_ACCOUNTING_MODE": "durable",
        "TRACE_ACCOUNTING_SCOPE": "tls-disposable-v1",
    }
    arguments = [
        "--network",
        "container:" + fixture["name"],
        "--mount",
        f"type=bind,source={fixture['directory'] / 'ca.crt'},target=/tls/ca.crt,readonly",
    ]
    for key, value in values.items():
        arguments += ["--env", key + "=" + value]
    docker(
        "run",
        "--rm",
        *arguments,
        "--entrypoint",
        "/app/.venv/bin/python",
        image,
        "-m",
        "scripts.migrate_production",
    )
    name = "trace-app-tls-test-" + uuid4().hex[:12]
    docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--label",
        "codex-test=" + fixture["label"],
        *arguments,
        image,
    )
    try:
        probe = (
            "import json,os,urllib.request; print(json.dumps({'uid':os.getuid(),"
            "'ready':urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=2).status}))"
        )
        deadline = time.monotonic() + 30
        while True:
            result = docker("exec", name, "/app/.venv/bin/python", "-c", probe, check=False)
            if result.returncode == 0:
                observed = json.loads(result.stdout)
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Production container failed its disposable-TLS readiness probe")
            time.sleep(0.2)
        assert observed == {"uid": 10001, "ready": 200}
        private_ip = container_private_ipv4(fixture["name"])
        scheme_probe = (
            "import json,urllib.request,urllib.error\n"
            "opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
            "def status(host, forwarded=False):\n"
            " request=urllib.request.Request('http://'+host+':8000/openapi.json', "
            "headers={'X-Forwarded-Proto':'https'} if forwarded else {})\n"
            " try:\n"
            "  return opener.open(request,timeout=2).status\n"
            " except urllib.error.HTTPError as exc:\n"
            "  return exc.code\n"
            f"print(json.dumps({{'raw':status('127.0.0.1'),'trusted':status('127.0.0.1',True),"
            f"'untrusted':status('{private_ip}',True)}}))"
        )
        schemes = json.loads(
            docker("exec", name, "/app/.venv/bin/python", "-c", scheme_probe).stdout
        )
        assert schemes["raw"] in {400, 403, 426}
        assert schemes["untrusted"] in {400, 403, 426}
        assert schemes["trusted"] == 200
        private_check = (
            "from pathlib import Path; import json; "
            "print(json.dumps({'private_env':any(Path('/app').rglob('.env*')),"
            "'logs':Path('/app/.claude-logs').exists(),'local_db':any(Path('/app').rglob('*.db'))}))"
        )
        assert json.loads(
            docker("exec", name, "/app/.venv/bin/python", "-c", private_check).stdout
        ) == {"private_env": False, "logs": False, "local_db": False}
        status = json.loads(
            docker("exec", name, "/app/.venv/bin/python", "-m", "scripts.platform_status").stdout
        )
        assert status["database"] == "reachable" and status["schema_current"] is True
        assert status["provider_availability"] == "not_probed"
        assert status["text_mode"] == status["embedding_mode"] == "disabled"
        assert status["accounting_mode"] == "durable"
        assert status["usage"]["provider_attempts"] == 0
    finally:
        stop_owned(name, fixture["label"])

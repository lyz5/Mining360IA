from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import os
import subprocess
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def certificate_matches(path: Path, host: str) -> bool:
    if not path.exists():
        return False
    try:
        certificate = x509.load_pem_x509_certificate(path.read_bytes())
        names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        return host in names.get_values_for_type(x509.DNSName) and certificate.not_valid_after_utc > (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
        )
    except (ValueError, x509.ExtensionNotFound):
        return False


def generate(host: str, certificate_path: Path, key_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(host),
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    os.chmod(key_path, 0o600)


def trust_for_current_user(certificate_path: Path) -> None:
    result = subprocess.run(
        ["certutil.exe", "-user", "-addstore", "Root", str(certificate_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout or "Unable to trust the Development certificate.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    certificate_path = output / "mining360-dev.crt.pem"
    key_path = output / "mining360-dev.key.pem"
    if not certificate_matches(certificate_path, args.host) or not key_path.exists():
        generate(args.host, certificate_path, key_path)
    trust_for_current_user(certificate_path)
    print(f"{certificate_path}|{key_path}")


if __name__ == "__main__":
    main()

import os
import json
from contextlib import contextmanager
from pathlib import Path

try:
    import pyodbc
except ImportError:  # pragma: no cover
    pyodbc = None

try:
    import pytds
except ImportError:  # pragma: no cover
    pytds = None


DEFAULT_SERVER = "172.17.0.111"
DEFAULT_DATABASE = "MiningProd"
DEFAULT_PORT = 1433
DEFAULT_USER = "djibril"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_DRIVER_CANDIDATES = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
]
LOCAL_SQLSERVER_CREDENTIALS = Path(__file__).resolve().parents[1] / "mining360_sqlserver.local.json"


def _local_sqlserver_credentials() -> dict:
    if not LOCAL_SQLSERVER_CREDENTIALS.exists():
        return {}
    try:
        with LOCAL_SQLSERVER_CREDENTIALS.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def sql_config_value(name: str, default: str = "") -> str:
    return os.getenv(name) or _local_sqlserver_credentials().get(name, default)


def detect_sql_server_driver() -> str:
    if pyodbc is None:
        raise RuntimeError("Module pyodbc manquant. Installe-le avec: pip install pyodbc")

    installed_drivers = set(pyodbc.drivers())
    for driver in DEFAULT_DRIVER_CANDIDATES:
        if driver in installed_drivers:
            return driver

    installed = ", ".join(sorted(installed_drivers)) or "aucun driver detecte"
    expected = ", ".join(DEFAULT_DRIVER_CANDIDATES)
    raise RuntimeError(
        "Aucun driver ODBC SQL Server compatible trouve. "
        f"Drivers attendus: {expected}. Drivers installes: {installed}."
    )


def _normalize_server(server: str) -> list[str]:
    variants = [server]
    if not server.lower().startswith("tcp:"):
        variants.append(f"tcp:{server}")
    if "," not in server:
        variants.append(f"{server},1433")
    return list(dict.fromkeys(variants))


def _build_connection_strings() -> list[str]:
    server = sql_config_value("MINING360_SQL_SERVER", DEFAULT_SERVER)
    database = sql_config_value("MINING360_SQL_DATABASE", DEFAULT_DATABASE)
    password = sql_config_value("MINING360_SQL_PASSWORD") or sql_config_value("SQLSERVER_PASSWORD")
    user = sql_config_value("MINING360_SQL_USER") or (DEFAULT_USER if password else None)
    selected_driver = sql_config_value("MINING360_SQL_DRIVER")
    drivers = [selected_driver] if selected_driver else DEFAULT_DRIVER_CANDIDATES
    connection_strings: list[str] = []
    encrypt_variants = [
        ["Encrypt=optional", "TrustServerCertificate=yes"],
        ["Encrypt=no", "TrustServerCertificate=yes"],
        [],
    ]

    for driver in drivers:
        if not driver:
            continue
        driver = driver.strip()
        for server_variant in _normalize_server(server):
            base = [
                f"DRIVER={{{driver}}}",
                f"SERVER={server_variant}",
                f"DATABASE={database}",
            ]
            if driver.startswith("ODBC Driver"):
                for extra in encrypt_variants:
                    parts = list(base) + list(extra)
                    parts.append(f"Connection Timeout={DEFAULT_TIMEOUT_SECONDS}")
                    if user and password:
                        parts.extend([f"UID={user}", f"PWD={password}"])
                    else:
                        parts.append("Trusted_Connection=yes")
                    connection_strings.append(";".join(parts) + ";")
            else:
                parts = list(base)
                parts.append(f"Connection Timeout={DEFAULT_TIMEOUT_SECONDS}")
                if user and password:
                    parts.extend([f"UID={user}", f"PWD={password}"])
                else:
                    parts.append("Trusted_Connection=yes")
                connection_strings.append(";".join(parts) + ";")

    return connection_strings


def connection_string() -> str:
    return _build_connection_strings()[0]


def _build_pytds_kwargs(
    server: str | None = None,
    database: str | None = None,
    user: str | None = None,
    password: str | None = None,
    port: int | None = None,
) -> dict:
    server = server or sql_config_value("MINING360_SQL_SERVER", DEFAULT_SERVER)
    database = database or sql_config_value("MINING360_SQL_DATABASE", DEFAULT_DATABASE)
    password = password if password is not None else (sql_config_value("MINING360_SQL_PASSWORD") or sql_config_value("SQLSERVER_PASSWORD"))
    user = user if user is not None else (sql_config_value("MINING360_SQL_USER") or (DEFAULT_USER if password else None))
    port = int(port or sql_config_value("MINING360_SQL_PORT", str(DEFAULT_PORT)))
    kwargs = {
        "server": server,
        "database": database,
        "login_timeout": DEFAULT_TIMEOUT_SECONDS,
        "timeout": DEFAULT_TIMEOUT_SECONDS,
        "autocommit": False,
        "validate_host": False,
        "enc_login_only": True,
    }
    server_has_instance_or_port = "\\" in server or "," in server
    if not server_has_instance_or_port:
        kwargs["port"] = port
    if user and password:
        kwargs["user"] = user
        kwargs["password"] = password
    else:
        kwargs["use_sso"] = True
    return kwargs


@contextmanager
def connect(
    server: str | None = None,
    database: str | None = None,
    user: str | None = None,
    password: str | None = None,
    port: int | None = None,
):
    if pytds is not None:
        connection = pytds.connect(
            **_build_pytds_kwargs(
                server=server,
                database=database,
                user=user,
                password=password,
                port=port,
            )
        )
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return

    if pyodbc is None:
        raise RuntimeError(
            "Aucun client SQL Server disponible. Installe python-tds ou pyodbc."
        )

    errors = []
    for candidate in _build_connection_strings():
        try:
            connection = pyodbc.connect(candidate)
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            return
        except Exception as exc:
            errors.append((candidate, exc))
    raise RuntimeError(
        "Impossible d'etablir la connexion SQL Server avec les variantes essayees. "
        + " | ".join(f"{candidate} => {error}" for candidate, error in errors)
    )

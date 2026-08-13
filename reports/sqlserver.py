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


DEFAULT_SERVER = ""
DEFAULT_DATABASE = ""
DEFAULT_PORT = 1433
DEFAULT_USER = ""
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
    value = os.getenv(name)
    if not value:
        field_map = {
            "MINING360_SQL_SERVER": ("host", False),
            "MINING360_SQL_PORT": ("port", False),
            "MINING360_SQL_DATABASE": ("database", False),
            "MINING360_SQL_USER": ("username", False),
            "MINING360_SQL_PASSWORD": ("password", True),
            "MINING360_SQL_DRIVER": ("driver", False),
        }
        mapping = field_map.get(name)
        if mapping:
            try:
                from .system_configuration_service import integration_value

                value = integration_value("Database", mapping[0], "", secret=mapping[1])
            except Exception:
                value = ""
    return value or _local_sqlserver_credentials().get(name, default)


def sql_timeout_seconds() -> int:
    try:
        from .system_configuration_service import integration_value, parameter_value

        value = integration_value("Database", "connection_timeout", None)
        if value in (None, ""):
            value = parameter_value("default-query-timeout", DEFAULT_TIMEOUT_SECONDS)
        return int(value or DEFAULT_TIMEOUT_SECONDS)
    except Exception:
        return DEFAULT_TIMEOUT_SECONDS


def detect_sql_server_driver() -> str:
    if pyodbc is None:
        raise RuntimeError("The pyodbc module is missing. Install it with: pip install pyodbc")

    installed_drivers = set(pyodbc.drivers())
    for driver in DEFAULT_DRIVER_CANDIDATES:
        if driver in installed_drivers:
            return driver

    installed = ", ".join(sorted(installed_drivers)) or "no driver detected"
    expected = ", ".join(DEFAULT_DRIVER_CANDIDATES)
    raise RuntimeError(
        "No compatible SQL Server ODBC driver was found. "
        f"Expected drivers: {expected}. Installed drivers: {installed}."
    )


def _normalize_server(server: str) -> list[str]:
    variants = [server]
    if not server.lower().startswith("tcp:"):
        variants.append(f"tcp:{server}")
    if "," not in server:
        variants.append(f"{server},1433")
    return list(dict.fromkeys(variants))


def _build_connection_strings(
    server: str | None = None,
    database: str | None = None,
    user: str | None = None,
    password: str | None = None,
    port: int | None = None,
    driver: str | None = None,
    timeout_seconds: int | None = None,
) -> list[str]:
    server = server or sql_config_value("MINING360_SQL_SERVER", DEFAULT_SERVER)
    database = database or sql_config_value("MINING360_SQL_DATABASE", DEFAULT_DATABASE)
    password = password if password is not None else (
        sql_config_value("MINING360_SQL_PASSWORD") or sql_config_value("SQLSERVER_PASSWORD")
    )
    user = user if user is not None else (sql_config_value("MINING360_SQL_USER") or (DEFAULT_USER if password else None))
    port = int(port or sql_config_value("MINING360_SQL_PORT", str(DEFAULT_PORT)))
    selected_driver = driver or sql_config_value("MINING360_SQL_DRIVER")
    timeout_seconds = int(timeout_seconds or sql_timeout_seconds())
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
        server_with_port = server if "\\" in server or "," in server else f"{server},{port}"
        for server_variant in _normalize_server(server_with_port):
            base = [
                f"DRIVER={{{driver}}}",
                f"SERVER={server_variant}",
                f"DATABASE={database}",
            ]
            if driver.startswith("ODBC Driver"):
                for extra in encrypt_variants:
                    parts = list(base) + list(extra)
                    parts.append(f"Connection Timeout={timeout_seconds}")
                    if user and password:
                        parts.extend([f"UID={user}", f"PWD={password}"])
                    else:
                        parts.append("Trusted_Connection=yes")
                    connection_strings.append(";".join(parts) + ";")
            else:
                parts = list(base)
                parts.append(f"Connection Timeout={timeout_seconds}")
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
        "login_timeout": sql_timeout_seconds(),
        "timeout": sql_timeout_seconds(),
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
    driver: str | None = None,
    timeout_seconds: int | None = None,
):
    if pytds is not None and not driver:
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
            "No SQL Server client is available. Install python-tds or pyodbc."
        )

    errors = []
    for candidate in _build_connection_strings(
        server=server,
        database=database,
        user=user,
        password=password,
        port=port,
        driver=driver,
        timeout_seconds=timeout_seconds,
    ):
        try:
            connection = pyodbc.connect(candidate)
        except Exception as exc:
            errors.append(exc)
            continue
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return

    # A configured ODBC driver is preferred, but it must not make every Data
    # Browser unavailable when the workstation TLS/ODBC stack is incompatible
    # with the SQL Server. python-tds uses the same explicit SQL credentials and
    # provides a deterministic fallback without changing browser configuration.
    if pytds is not None:
        try:
            connection = pytds.connect(
                **_build_pytds_kwargs(
                    server=server,
                    database=database,
                    user=user,
                    password=password,
                    port=port,
                )
            )
        except Exception as exc:
            errors.append(exc)
        else:
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            return
    raise RuntimeError(
        "Impossible d'etablir la connexion SQL Server avec les variantes essayees. "
        + " | ".join(str(error) for error in errors)
    )

"""Respaldo y restauración; credenciales de conexión fuera de argumentos y manifiestos."""
from contextlib import closing
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile


def _motor(config):
    motor = config["ENGINE"].rsplit(".", 1)[-1]
    if motor not in ("sqlite3", "postgresql"):
        raise ValueError("Motor de base de datos no admitido.")
    return motor


def _postgres(programa, config, argumentos):
    entorno = os.environ.copy()
    entorno["PGPASSWORD"] = config.get("PASSWORD", "")
    comando = [programa, "--host", str(config.get("HOST") or "127.0.0.1"), "--port", str(config.get("PORT") or 5432),
        "--username", config["USER"], "--dbname", str(config["NAME"]), *argumentos]
    try:
        subprocess.run(comando, env=entorno, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3600)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError(f"Falló {programa}; revise herramienta, conexión, permisos y versión de PostgreSQL.") from None


def _hash(ruta):
    with Path(ruta).open("rb") as archivo:
        return hashlib.file_digest(archivo, "sha256").hexdigest()


def _dentro(ruta, raiz):
    ruta, raiz = Path(ruta).resolve(), Path(raiz).resolve()
    if not ruta.is_relative_to(raiz) or ruta == raiz:
        raise ValueError("La ruta sale de la carpeta prevista.")
    return ruta


def crear(config, privados, destino, *, diarios=7, semanales=4, ahora=None):
    if type(diarios) is not int or diarios < 1 or type(semanales) is not int or semanales < 0:
        raise ValueError("Conserve al menos un respaldo diario y cero o más semanales.")
    destino, privados = Path(destino).resolve(), Path(privados).resolve()
    if destino.is_relative_to(privados) or privados.is_relative_to(destino):
        raise ValueError("Separe la carpeta de respaldos de los archivos privados.")
    destino.mkdir(parents=True, exist_ok=True, mode=0o700)
    ahora = ahora or datetime.now(timezone.utc)
    motor = _motor(config)
    final = destino / f"diario-{ahora:%Y-%m-%d}.tar.gz"
    with tempfile.TemporaryDirectory(prefix=".respaldo-", dir=destino) as temporal:
        temporal = Path(temporal)
        bd = temporal / ("base.sqlite3" if motor == "sqlite3" else "base.dump")
        if motor == "sqlite3":
            with closing(sqlite3.connect(Path(config["NAME"]).resolve().as_uri()+"?mode=ro", uri=True)) as origen, closing(sqlite3.connect(bd)) as copia:
                origen.backup(copia)
        else:
            _postgres("pg_dump", config, ["--format=custom", "--no-owner", "--no-acl", "--file", str(bd)])
        archivos = {bd.name: bd}
        if privados.exists():
            for ruta in privados.rglob("*"):
                if ruta.is_symlink():
                    raise ValueError("No se incluyen enlaces simbólicos en archivos privados.")
                if ruta.is_file():
                    _dentro(ruta, privados)
                    archivos["privados/"+ruta.relative_to(privados).as_posix()] = ruta
        manifiesto = {"version": 1, "motor": motor, "fecha": ahora.isoformat(), "base": bd.name,
            "sha256": {nombre: _hash(ruta) for nombre, ruta in archivos.items()}}
        ruta_manifiesto = temporal / "manifiesto.json"
        ruta_manifiesto.write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
        paquete = temporal / "respaldo.tar.gz"
        with tarfile.open(paquete, "w:gz") as tar:
            tar.add(ruta_manifiesto, arcname="manifiesto.json")
            for nombre, ruta in archivos.items():
                tar.add(ruta, arcname=nombre, recursive=False)
        verificar(paquete)
        os.replace(paquete, final)
    if semanales and ahora.weekday() == 6:
        iso = ahora.isocalendar()
        semanal = destino / f"semanal-{iso.year}-{iso.week:02d}.tar.gz"
        with tempfile.NamedTemporaryFile(dir=destino, prefix=".semanal-", delete=False) as temporal:
            ruta_temporal = Path(temporal.name)
        try:
            shutil.copyfile(final, ruta_temporal)
            os.replace(ruta_temporal, semanal)
        finally:
            ruta_temporal.unlink(missing_ok=True)
    for prefijo, conservar in (("diario", diarios), ("semanal", semanales)):
        candidatos = sorted((p for p in destino.glob(prefijo+"-*.tar.gz") if p.is_file() and not p.is_symlink()), reverse=True)
        for viejo in candidatos[conservar:]:
            _dentro(viejo, destino).unlink()
    return final


def verificar(paquete, extraer=None):
    with tarfile.open(paquete, "r:gz") as tar:
        miembros = tar.getmembers()
        nombres = [m.name for m in miembros]
        if len(nombres) != len(set(nombres)) or any(not m.isfile() or m.name.startswith("/") or ".." in Path(m.name).parts or "\\" in m.name or ":" in m.name for m in miembros):
            raise ValueError("El respaldo contiene rutas o tipos de archivo no admitidos.")
        try:
            with tar.extractfile("manifiesto.json") as archivo:
                manifiesto = json.load(archivo)
        except (KeyError, ValueError, UnicodeError):
            raise ValueError("El respaldo no contiene un manifiesto JSON válido.") from None
        if not isinstance(manifiesto, dict) or type(manifiesto.get("version")) is not int or manifiesto["version"] != 1:
            raise ValueError("La versión del manifiesto no es válida.")
        bases = {"sqlite3": "base.sqlite3", "postgresql": "base.dump"}
        base = bases.get(manifiesto.get("motor")) if isinstance(manifiesto.get("motor"), str) else None
        hashes = manifiesto.get("sha256")
        if not base or manifiesto.get("base") != base or not isinstance(hashes, dict) or base not in hashes:
            raise ValueError("El respaldo debe incluir la base de datos correspondiente a su motor.")
        if set(nombres) != {"manifiesto.json", *hashes}:
            raise ValueError("El manifiesto no corresponde al contenido del respaldo.")
        for nombre, esperado in hashes.items():
            if (nombre != base and not nombre.startswith("privados/")) or not isinstance(esperado, str) or not re.fullmatch(r"[0-9a-f]{64}", esperado):
                raise ValueError("El manifiesto contiene archivos o hashes no admitidos.")
            with tar.extractfile(nombre) as archivo:
                if hashlib.file_digest(archivo, "sha256").hexdigest() != esperado:
                    raise ValueError("El respaldo no supera la verificación SHA-256.")
        with tar.extractfile(base) as archivo:
            cabecera = b"SQLite format 3\x00" if base == "base.sqlite3" else b"PGDMP"
            if archivo.read(len(cabecera)) != cabecera:
                raise ValueError("La base del respaldo no corresponde al formato declarado.")
        if extraer is not None:
            for miembro in miembros:
                destino = _dentro(Path(extraer)/miembro.name, extraer)
                destino.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(miembro) as origen, destino.open("wb") as archivo:
                    shutil.copyfileobj(origen, archivo)
    return manifiesto


def restaurar(paquete, config, privados, *, confirmar=False):
    if not confirmar:
        raise ValueError("La restauración sustituye datos: requiere confirmar=True y aplicación detenida.")
    motor = _motor(config)
    with tempfile.TemporaryDirectory(prefix="restaurar-suministros-") as temporal:
        temporal = Path(temporal)
        manifiesto = verificar(paquete, temporal)
        if manifiesto["motor"] != motor:
            raise ValueError("El respaldo y la base de destino usan motores distintos.")
        base = temporal / manifiesto["base"]
        if motor == "sqlite3":
            from django.db.backends.sqlite3._functions import register
            with closing(sqlite3.connect(base.resolve().as_uri()+"?mode=ro", uri=True)) as origen:
                register(origen)
                if origen.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("La base SQLite del respaldo no supera la comprobación de integridad.")
                with closing(sqlite3.connect(config["NAME"])) as destino:
                    register(destino)
                    origen.backup(destino)
        else:
            _postgres("pg_restore", config, ["--clean", "--if-exists", "--no-owner", "--no-acl", "--exit-on-error", "--single-transaction", str(base)])
        privados = Path(privados).resolve()
        privados.mkdir(parents=True, exist_ok=True, mode=0o750)
        for nombre in manifiesto["sha256"]:
            if nombre.startswith("privados/"):
                destino = _dentro(privados / nombre.removeprefix("privados/"), privados)
                destino.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
                shutil.copyfile(temporal/nombre, destino)
    return manifiesto


def main():
    from dotenv import load_dotenv
    load_dotenv(os.environ.get("DJANGO_ENV_FILE", Path(__file__).resolve().parent.parent / ".env"), override=False)
    parser = argparse.ArgumentParser(description="Respaldos de Suministros sin secretos en argumentos.")
    parser.add_argument("--destino", default=os.environ.get("SUMINISTROS_BACKUP_DIR") or "/var/backups/suministros")
    parser.add_argument("--diarios", type=int, default=os.environ.get("SUMINISTROS_RESPALDOS_DIARIOS") or 7)
    parser.add_argument("--semanales", type=int, default=os.environ.get("SUMINISTROS_RESPALDOS_SEMANALES") or 4)
    parser.add_argument("--verificar")
    parser.add_argument("--restaurar")
    parser.add_argument("--confirmar-sustitucion", action="store_true")
    argumentos = parser.parse_args()
    if argumentos.verificar:
        verificar(argumentos.verificar)
        print("Respaldo verificado: estructura y SHA-256 correctos.")
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from django.conf import settings
    if argumentos.restaurar:
        restaurar(argumentos.restaurar, settings.DATABASES["default"], settings.MEDIA_ROOT, confirmar=argumentos.confirmar_sustitucion)
        print("Restauración terminada. Verifique migraciones, ingreso y PDF antes de habilitar el servicio.")
    else:
        print(crear(settings.DATABASES["default"], settings.MEDIA_ROOT, argumentos.destino, diarios=argumentos.diarios, semanales=argumentos.semanales))


if __name__ == "__main__":
    main()

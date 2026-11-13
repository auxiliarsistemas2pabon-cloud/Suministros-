from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import skipUnless
import uuid
import json
import hashlib
import tarfile
from io import BytesIO
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from deploy.respaldo import crear, restaurar, verificar


class RespaldoSQLiteTests(SimpleTestCase):
    def test_cabecera_y_sha_de_la_base_se_validan_antes_de_escribir_destino(self):
        with TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            destino = raiz/"destino.sqlite3"
            with closing(sqlite3.connect(destino)) as db, db:
                db.execute("CREATE TABLE ejemplo (texto TEXT)")
                db.execute("INSERT INTO ejemplo VALUES ('Dato conservado')")
            archivo_base = b"esto no es una base SQLite"
            digest = hashlib.sha256(archivo_base).hexdigest()
            for motor, nombre_base, hash_guardado in (("sqlite3", "base.sqlite3", digest), ("sqlite3", "base.sqlite3", "0"*64),
                    ("postgresql", "base.sqlite3", digest), ("sqlite3", "base.sqlite3", "hash-no-valido")):
                with self.subTest(motor=motor, hash=hash_guardado):
                    manifiesto = {"version": 1, "motor": motor, "base": nombre_base, "sha256": {nombre_base: hash_guardado}}
                    paquete = raiz/"formato-invalido.tar.gz"
                    with tarfile.open(paquete, "w:gz") as tar:
                        for nombre, datos in (("manifiesto.json", json.dumps(manifiesto).encode("utf-8")), (nombre_base, archivo_base)):
                            miembro = tarfile.TarInfo(nombre)
                            miembro.size = len(datos)
                            tar.addfile(miembro, BytesIO(datos))
                    with self.assertRaises(ValueError):
                        restaurar(paquete, {"ENGINE": "django.db.backends.sqlite3", "NAME": str(destino)}, raiz/"privados", confirmar=True)
                    with closing(sqlite3.connect(destino)) as db:
                        self.assertEqual(db.execute("SELECT texto FROM ejemplo").fetchone()[0], "Dato conservado")

    def test_respaldo_incompleto_se_rechaza_antes_de_sustituir_la_base(self):
        with TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            destino = raiz / "destino.sqlite3"
            with closing(sqlite3.connect(destino)) as db, db:
                db.execute("CREATE TABLE ejemplo (texto TEXT)")
                db.execute("INSERT INTO ejemplo VALUES ('Dato original')")
            paquete = raiz / "incompleto.tar.gz"
            manifiesto = {"version": 1, "motor": "sqlite3", "base": "base.sqlite3", "sha256": {}}
            datos = json.dumps(manifiesto).encode("utf-8")
            with tarfile.open(paquete, "w:gz") as tar:
                miembro = tarfile.TarInfo("manifiesto.json")
                miembro.size = len(datos)
                tar.addfile(miembro, BytesIO(datos))
            with self.assertRaises(ValueError):
                restaurar(paquete, {"ENGINE": "django.db.backends.sqlite3", "NAME": str(destino)}, raiz/"privados", confirmar=True)
            with closing(sqlite3.connect(destino)) as db:
                self.assertEqual(db.execute("SELECT texto FROM ejemplo").fetchone()[0], "Dato original")

    def test_respaldo_y_restauracion_con_archivos_y_rotacion(self):
        with TemporaryDirectory() as carpeta:
            raiz = Path(carpeta)
            base = raiz / "origen.sqlite3"
            config = {"ENGINE": "django.db.backends.sqlite3", "NAME": str(base)}
            privados = raiz / "privados"
            privados.mkdir()
            (privados / "soporte.pdf").write_bytes(b"%PDF-1.4 ficticio")
            with closing(sqlite3.connect(base)) as db, db:
                db.execute("CREATE TABLE ejemplo (id INTEGER PRIMARY KEY, texto TEXT)")
                db.execute("INSERT INTO ejemplo VALUES (1, 'Dato ficticio de restauración')")
            for dia in range(16):
                paquete = crear(config, privados, raiz/"respaldos", diarios=7, semanales=2, ahora=datetime(2026, 6, 1, tzinfo=timezone.utc)+timedelta(days=dia))
            self.assertEqual(len(list((raiz/"respaldos").glob("diario-*.tar.gz"))), 7)
            self.assertEqual(len(list((raiz/"respaldos").glob("semanal-*.tar.gz"))), 2)
            verificar(paquete)
            destino = {**config, "NAME": str(raiz/"restaurada.sqlite3")}
            with self.assertRaises(ValueError):
                restaurar(paquete, destino, raiz/"privados_restaurados")
            restaurar(paquete, destino, raiz/"privados_restaurados", confirmar=True)
            with closing(sqlite3.connect(destino["NAME"])) as db:
                self.assertEqual(db.execute("SELECT texto FROM ejemplo").fetchone()[0], "Dato ficticio de restauración")
            self.assertEqual((raiz/"privados_restaurados"/"soporte.pdf").read_bytes(), b"%PDF-1.4 ficticio")


@skipUnless(connection.vendor == "postgresql", "La restauración PostgreSQL requiere la instancia aislada.")
class RespaldoPostgreSQLTests(TransactionTestCase):
    def test_pg_dump_pg_restore_en_dos_bases_ficticias_aisladas(self):
        import psycopg
        from psycopg import sql
        config = connection.settings_dict.copy()
        argumentos = dict(dbname=config["NAME"], user=config["USER"], password=config["PASSWORD"], host=config["HOST"], port=config["PORT"])
        prefijo = "prueba_respaldo_"+uuid.uuid4().hex[:10]
        origen, destino = prefijo+"_origen", prefijo+"_destino"
        creadas = []
        with psycopg.connect(**argumentos, autocommit=True) as control:
            try:
                for nombre in (origen, destino):
                    assert nombre.startswith("prueba_respaldo_") and nombre != config["NAME"]
                    control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre)))
                    creadas.append(nombre)
                with psycopg.connect(**{**argumentos, "dbname": origen}, autocommit=True) as db:
                    db.execute("CREATE TABLE ejemplo (id integer primary key, texto text)")
                    db.execute("INSERT INTO ejemplo VALUES (1, 'Restauración ficticia verificada')")
                with TemporaryDirectory() as carpeta:
                    raiz = Path(carpeta)
                    privados = raiz/"privados"
                    privados.mkdir()
                    (privados/"soporte.pdf").write_bytes(b"%PDF-1.4 ficticio")
                    paquete = crear({**config, "NAME": origen}, privados, raiz/"respaldos")
                    restaurar(paquete, {**config, "NAME": destino}, raiz/"restaurados", confirmar=True)
                    with psycopg.connect(**{**argumentos, "dbname": destino}) as db:
                        self.assertEqual(db.execute("SELECT texto FROM ejemplo").fetchone()[0], "Restauración ficticia verificada")
                    self.assertEqual((raiz/"restaurados"/"soporte.pdf").read_bytes(), b"%PDF-1.4 ficticio")
            finally:
                for nombre in reversed(creadas):
                    assert nombre.startswith("prueba_respaldo_") and nombre != config["NAME"]
                    control.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(nombre)))

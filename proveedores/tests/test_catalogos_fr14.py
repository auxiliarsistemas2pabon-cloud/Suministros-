"""Catálogo FR14: reglas, carga atómica e idempotente y trazabilidad."""

from datetime import timedelta
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario
from proveedores import servicios
from proveedores.carga_fr14 import COLUMNAS, leer_csv
from proveedores.models import CategoriaProveedor, Peso, Requisito, TipoDocumento
from proveedores.tests.utilidades import MOTIVO, crear_documento_con_enlace, crear_proveedor, tipo_documento

CABECERA = ",".join(COLUMNAS) + "\n"
FILA = "calidad,1,Requisito ficticio,Categoría ficticia,2\n"


class CatalogosFR14Tests(TestCase):
    def setUp(self):
        self.admin = crear_usuario(Rol.ADMINISTRADOR)
        self.categoria = CategoriaProveedor.objects.create(nombre="Categoría de prueba")
        self.requisito = Requisito.objects.create(numero=40, grupo="calidad", texto="Texto ficticio")

    def guardar(self, instancia, **opciones):
        return servicios.guardar_catalogo(instancia, actor=opciones.pop("actor", self.admin), motivo=opciones.pop("motivo", MOTIVO))

    def cargar(self, texto=FILA, **opciones):
        return servicios.cargar_fr14(BytesIO((CABECERA + texto).encode("utf-8-sig")), actor=self.admin,
                                    motivo=MOTIVO, **opciones)

    def test_peso_uno_o_dos_y_par_unico_en_modelo_y_base(self):
        for valor in (0, 3, -1):
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.guardar(Peso(requisito=self.requisito, categoria=self.categoria, valor=valor))
            with self.assertRaises(IntegrityError), transaction.atomic():
                Peso.objects.create(requisito=self.requisito, categoria=self.categoria, valor=valor)
        self.guardar(Peso(requisito=self.requisito, categoria=self.categoria, valor=1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Peso.objects.create(requisito=self.requisito, categoria=self.categoria, valor=2)

    def test_requisito_valida_grupo_numero_y_texto(self):
        for cambios in ({"numero": 0}, {"grupo": "otro"}, {"texto": "  "}):
            datos = {"numero": 50, "grupo": "ambiental", "texto": "Ejemplo", **cambios}
            with self.subTest(cambios=cambios), self.assertRaises(ValidationError):
                self.guardar(Requisito(**datos))
        for cambios in ({"numero": 0}, {"grupo": "otro"}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Requisito.objects.create(numero=cambios.get("numero", 50), grupo=cambios.get("grupo", "calidad"), texto="X")

    def test_cambios_y_desactivacion_preservan_relaciones_y_bitacora(self):
        peso = self.guardar(Peso(requisito=self.requisito, categoria=self.categoria, valor=1))
        self.categoria.descripcion = "Descripción actualizada"
        self.guardar(self.categoria)
        servicios.cambiar_estado_catalogo(self.categoria, False, actor=self.admin, motivo=MOTIVO)
        self.assertTrue(Peso.objects.filter(pk=peso.pk).exists())
        self.assertTrue(Requisito.objects.filter(pk=self.requisito.pk).exists())
        registro = RegistroBitacora.objects.get(accion="categoria_proveedor.desactivado")
        self.assertTrue(registro.valor_anterior["activo"])
        self.assertFalse(registro.valor_nuevo["activo"])
        self.assertEqual(registro.actor, self.admin)

    def test_motivo_y_actor_activo_obligatorios_en_servicios(self):
        with self.assertRaises(ValidationError):
            self.guardar(self.categoria, motivo=" ")
        for rol in (Rol.COORDINADOR, Rol.PROVEEDOR):
            actor = crear_usuario(rol)
            with self.assertRaises(PermissionDenied):
                self.guardar(self.categoria, actor=actor)
            with self.assertRaises(PermissionDenied):
                servicios.cambiar_estado_catalogo(self.categoria, False, actor=actor, motivo=MOTIVO)
            with self.assertRaises(PermissionDenied):
                servicios.cargar_fr14(BytesIO((CABECERA + FILA).encode()), actor=actor, motivo=MOTIVO)
        self.admin.activo = False
        with self.assertRaises(PermissionDenied):
            self.guardar(self.categoria)

    def test_peso_nuevo_no_usa_catalogos_inactivos_ni_cambia_de_identidad(self):
        peso = self.guardar(Peso(requisito=self.requisito, categoria=self.categoria, valor=1))
        otra = CategoriaProveedor.objects.create(nombre="Otra categoría")
        peso.categoria = otra
        with self.assertRaises(ValidationError):
            self.guardar(peso)
        self.categoria.activo = False
        self.categoria.save()
        nuevo = Requisito.objects.create(numero=41, grupo="ambiental", texto="Otro texto")
        with self.assertRaises(ValidationError):
            self.guardar(Peso(requisito=nuevo, categoria=self.categoria, valor=1))

    def test_importacion_repetida_no_duplica_registros_ni_historial(self):
        primero = self.cargar()
        cuenta = RegistroBitacora.objects.count()
        segundo = self.cargar()
        self.assertEqual(primero, {"categorias_creadas": 1, "requisitos_creados": 1, "pesos_creados": 1, "actualizados": 0})
        self.assertTrue(all(v == 0 for v in segundo.values()))
        self.assertEqual(RegistroBitacora.objects.count(), cuenta)
        self.assertEqual(Peso.objects.count(), 1)

    def test_csv_actualiza_con_valores_anteriores_sin_reactivar(self):
        self.cargar()
        requisito = Requisito.objects.get(numero=1)
        servicios.cambiar_estado_catalogo(requisito, False, actor=self.admin, motivo=MOTIVO)
        resumen = self.cargar(FILA.replace("Requisito ficticio", "Nuevo texto").replace(",2\n", ",1\n"))
        self.assertEqual(resumen["actualizados"], 2)
        requisito.refresh_from_db()
        self.assertFalse(requisito.activo)
        registro = RegistroBitacora.objects.get(accion="requisito.modificado")
        self.assertEqual(registro.valor_anterior["texto"], "Requisito ficticio")
        self.assertEqual(registro.valor_nuevo["texto"], "Nuevo texto")

    def test_csv_agrupa_categorias_sin_distinguir_mayusculas(self):
        self.cargar(FILA + "ambiental,2,Segundo texto,categoría FICTICIA,1\n")
        self.assertEqual(CategoriaProveedor.objects.filter(nombre__iexact="Categoría ficticia").count(), 1)
        self.assertEqual(Peso.objects.count(), 2)

    def test_csv_invalido_no_deja_la_primera_fila_guardada(self):
        for fila in (
            "calidad,2,Mal peso,Otra,3\n", "otro,2,Texto,Otra,1\n", "calidad,0,Texto,Otra,1\n",
            "calidad,2,,Otra,1\n", "calidad,2,Texto,,1\n", "calidad,2,Texto,Otra\n",
            FILA, "ambiental,1,Texto distinto,Otra,1\n",
        ):
            with self.subTest(fila=fila), self.assertRaises(ValidationError):
                self.cargar(FILA + fila)
            self.assertFalse(Peso.objects.exists())
            self.assertFalse(Requisito.objects.filter(numero=1).exists())
            self.assertFalse(RegistroBitacora.objects.exists())

    def test_csv_fallo_de_guardado_revierte_todos_los_modelos(self):
        guardar_real = servicios.guardar_catalogo

        def guardar_y_fallar(instancia, **kwargs):
            if isinstance(instancia, Peso):
                raise ValidationError("Fallo simulado")
            return guardar_real(instancia, **kwargs)

        with patch.object(servicios, "guardar_catalogo", side_effect=guardar_y_fallar):
            with self.assertRaises(ValidationError):
                self.cargar()
        self.assertFalse(Requisito.objects.filter(numero=1).exists())
        self.assertFalse(Peso.objects.exists())
        self.assertFalse(CategoriaProveedor.objects.filter(nombre="Categoría ficticia").exists())
        self.assertFalse(RegistroBitacora.objects.exists())

    def test_csv_encoding_encabezados_citas_y_limites(self):
        for contenido in (b"\xff", b"\x00", b"texto,grupo\nx,y\n", CABECERA.encode(), (CABECERA + 'calidad,1,"texto sin cierre').encode()):
            with self.subTest(contenido=contenido), self.assertRaises(ValidationError):
                leer_csv(BytesIO(contenido))
        with patch("proveedores.carga_fr14.MAX_BYTES", 5), self.assertRaises(ValidationError):
            self.cargar()
        with patch("proveedores.carga_fr14.MAX_FILAS", 1), self.assertRaises(ValidationError):
            self.cargar(FILA + "ambiental,2,Otro,Otra,1\n")

    def test_csv_ejemplo_tiene_26_requisitos_ficticios_y_tres_grupos(self):
        ruta = Path(settings.BASE_DIR) / "docs" / "ejemplos" / "fr14_ejemplo.csv"
        with ruta.open("rb") as archivo:
            servicios.cargar_fr14(archivo, actor=self.admin, motivo=MOTIVO)
        requisitos = Requisito.objects.filter(numero__lte=26)
        self.assertEqual(requisitos.count(), 26)
        self.assertEqual(set(requisitos.values_list("grupo", flat=True)), set(Requisito.Grupo.values))
        self.assertEqual(Peso.objects.count(), 52)

    def test_comando_exige_actor_administrativo_y_motivo(self):
        with TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "ejemplo.csv"
            ruta.write_text(CABECERA + FILA, encoding="utf-8")
            salida = StringIO()
            call_command("cargar_fr14", str(ruta), actor=self.admin.correo, motivo=MOTIVO, stdout=salida)
            self.assertIn("Carga completada", salida.getvalue())
            for actor, motivo in (("nadie@ejemplo.test", MOTIVO), (self.admin.correo, " ")):
                with self.assertRaises(CommandError):
                    call_command("cargar_fr14", str(ruta), actor=actor, motivo=motivo)

    def test_alertas_por_tipo_y_parametro_general_coexisten(self):
        proveedor = crear_proveedor()
        tipo = tipo_documento("Alerta especial")
        tipo.usar_alerta_general, tipo.dias_alerta = False, 60
        self.guardar(tipo)
        documento = crear_documento_con_enlace(proveedor, self.admin, tipo=tipo, vence_en_dias=45)
        self.assertEqual([d.pk for d in servicios.alertas_vencimiento()], [documento.pk])
        self.assertEqual(servicios.alertas_vencimiento(dias=30), [])
        self.assertEqual(servicios.documentos_de(proveedor)[0].vigencia, "por_vencer")
        tipo.dias_alerta = 10
        self.guardar(tipo)
        self.assertEqual(servicios.alertas_vencimiento(), [])

    def test_no_se_exige_vencimiento_a_documentos_historicos_sin_fecha(self):
        proveedor = crear_proveedor()
        tipo = tipo_documento("Sin vencimiento", False)
        crear_documento_con_enlace(proveedor, self.admin, tipo=tipo)
        tipo.requiere_vencimiento = True
        with self.assertRaisesMessage(ValidationError, "Complete sus fechas"):
            self.guardar(tipo)

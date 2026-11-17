import json
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario


class GuardiaDemostracionTests(SimpleTestCase):
    def test_comando_no_carga_archivos_en_la_base_principal(self):
        with self.assertRaisesMessage(CommandError, "solo funciona"):
            call_command("preparar_ejemplo", "no_debe_abrir_este_archivo.xlsx", unidad_provisional=True)

    @override_settings(MODO_DEMOSTRACION=True)
    def test_bandera_sola_no_autoriza_escrituras_en_otra_base(self):
        from proyecciones.management.commands.preparar_ejemplo import comprobar_entorno

        with self.assertRaisesMessage(CommandError, "base separada"):
            comprobar_entorno()


@override_settings(ROOT_URLCONF="config.urls_demo", MODO_DEMOSTRACION=True)
class RecorridoDemostracionTests(TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="recorrido-demo-prueba-")
        self.addCleanup(self.temporal.cleanup)
        self.configuracion = override_settings(DIRECTORIO_DEMOSTRACION=Path(self.temporal.name))
        self.configuracion.enable()
        self.addCleanup(self.configuracion.disable)
        self.admin = crear_usuario(Rol.ADMINISTRADOR)
        self.archivo = Path(self.temporal.name) / "recorrido.json"
        self.archivo.write_text(json.dumps({"archivo_nombre": "Consolidado de prueba", "anio": 2026,
            "areas": [], "lineas_importables": 0, "lineas_pendientes": 1,
            "costo_proyectado_total": "70.00", "costo_cargado": "0", "costo_lineas_pendientes": "70.00",
            "accesos": [], "operacion": {}}), encoding="utf-8")

    def test_administracion_ve_presupuesto_cargado_y_pendiente(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get("/ejemplo/")
        self.assertContains(respuesta, "Consolidado de prueba")
        self.assertEqual(respuesta.context["lineas_pendientes"], 1)
        self.assertContains(respuesta, "Valor cargado en proyecciones")
        self.assertContains(respuesta, "Demostración local")

    def test_proveedor_no_ve_el_consolidado_de_las_areas(self):
        self.client.force_login(crear_usuario(Rol.PROVEEDOR))
        self.assertEqual(self.client.get("/ejemplo/").status_code, 403)

    @override_settings(MODO_DEMOSTRACION=False)
    def test_no_se_expone_el_recorrido_si_no_es_entorno_demo(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/ejemplo/").status_code, 404)

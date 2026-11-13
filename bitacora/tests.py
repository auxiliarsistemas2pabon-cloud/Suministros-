from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, InternalError, connection, transaction
from django.test import RequestFactory, TestCase

from bitacora.models import BitacoraInmutableError, RegistroBitacora
from bitacora.servicios import diferencias, guardar_con_bitacora, instantanea, registrar
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_area, crear_usuario


class SoloInsercionTests(TestCase):
    def setUp(self):
        self.registro = registrar("prueba.accion", motivo="Motivo de prueba")

    def test_no_se_puede_modificar_por_el_modelo(self):
        self.registro.motivo = "alterado"
        with self.assertRaises(BitacoraInmutableError):
            self.registro.save()

    def test_no_se_puede_borrar_por_el_modelo(self):
        with self.assertRaises(BitacoraInmutableError):
            self.registro.delete()

    def test_no_se_puede_modificar_ni_borrar_por_queryset(self):
        with self.assertRaises(BitacoraInmutableError):
            RegistroBitacora.objects.filter(pk=self.registro.pk).update(motivo="alterado")
        with self.assertRaises(BitacoraInmutableError):
            RegistroBitacora.objects.all().delete()

    def test_la_base_de_datos_rechaza_update_y_delete_directos(self):
        tabla = RegistroBitacora._meta.db_table
        for sql in (f"UPDATE {tabla} SET motivo = 'alterado'", f"DELETE FROM {tabla}"):
            with self.subTest(sql=sql), self.assertRaises((IntegrityError, InternalError)):
                with transaction.atomic(), connection.cursor() as cursor:
                    cursor.execute(sql)
        self.registro.refresh_from_db()
        self.assertEqual(self.registro.motivo, "Motivo de prueba")

    def test_se_pueden_insertar_mas_registros(self):
        registrar("prueba.otra")
        self.assertEqual(RegistroBitacora.objects.count(), 2)


class RegistrarTests(TestCase):
    def test_guarda_actor_objeto_valores_motivo_e_ip(self):
        actor = crear_usuario(Rol.ADMINISTRADOR)
        area = crear_area()
        request = RequestFactory().post("/", REMOTE_ADDR="10.1.2.3")
        registro = registrar(
            "area.prueba",
            actor=actor,
            objeto=area,
            anterior={"monto": Decimal("1500.25")},
            nuevo={"monto": Decimal("1999.99"), "fecha": date(2026, 11, 5)},
            motivo="  Ajuste ficticio  ",
            request=request,
        )
        registro.refresh_from_db()
        self.assertEqual(registro.actor, actor)
        self.assertEqual(registro.actor_texto, actor.correo)
        self.assertEqual(registro.objeto_id, str(area.pk))
        self.assertEqual(registro.objeto_texto, str(area))
        self.assertEqual(registro.tipo_objeto.model, "area")
        # Decimal se guarda como texto exacto, nunca como float.
        self.assertEqual(registro.valor_anterior, {"monto": "1500.25"})
        self.assertEqual(registro.valor_nuevo, {"monto": "1999.99", "fecha": "2026-11-05"})
        self.assertEqual(registro.motivo, "Ajuste ficticio")
        self.assertEqual(registro.ip, "10.1.2.3")
        self.assertIsNotNone(registro.fecha)

    def test_accion_del_sistema_sin_actor(self):
        registro = registrar("sistema.tarea")
        self.assertIsNone(registro.actor)
        self.assertEqual(registro.actor_texto, "")
        self.assertIn("sistema", str(registro))


class DiferenciasTests(TestCase):
    def test_instantanea_y_diferencias(self):
        area = crear_area()
        usuario = crear_usuario(Rol.COORDINADOR, area=area)
        foto = instantanea(usuario, ["nombre", "area", "activo"])
        self.assertEqual(foto["area"], {"id": area.pk, "texto": str(area)})
        cambiado = {**foto, "activo": False}
        self.assertEqual(diferencias(foto, cambiado), ({"activo": True}, {"activo": False}))
        self.assertEqual(diferencias(foto, foto), ({}, {}))

    def test_guardar_con_bitacora_sin_cambios_no_registra(self):
        area = crear_area()
        with transaction.atomic():
            resultado = guardar_con_bitacora(
                area,
                ["nombre", "activa"],
                accion_crear="area.creada",
                accion_modificar="area.modificada",
                actor=None,
                motivo="",
            )
        self.assertIsNone(resultado)
        self.assertFalse(RegistroBitacora.objects.exists())


class ConsultaBitacoraTests(TestCase):
    """/proyecciones/bitacora/: consulta filtrable, solo para administración."""

    def setUp(self):
        from django.urls import reverse

        self.url = reverse("bitacora:consulta")
        self.area = crear_area()
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin-consulta@ejemplo.test")
        self.otro_admin = crear_usuario(Rol.DESARROLLADOR, correo="dev-consulta@ejemplo.test")
        self.coordinador = crear_usuario(Rol.COORDINADOR, correo="coord-consulta@ejemplo.test", area=self.area)
        self.primero = registrar(
            "area.modificada",
            actor=self.administrador,
            objeto=self.area,
            anterior={"activa": True, "nombre": "Farmacia"},
            nuevo={"activa": False, "nombre": "Farmacia central"},
            motivo="Reorganización ficticia",
        )
        self.segundo = registrar(
            "cuenta.cambio_clave",
            actor=self.otro_admin,
            objeto=self.otro_admin,
            anterior={"debe_cambiar_clave": True},
            nuevo={"debe_cambiar_clave": False},
            motivo="Cambio de clave por el usuario",
        )

    def ids(self, respuesta):
        return {registro.pk for registro in respuesta.context["pagina"]}

    def test_sin_filtros_muestra_todo_con_valores_anterior_y_nuevo(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(self.url)
        self.assertEqual(self.ids(respuesta), {self.primero.pk, self.segundo.pk})
        self.assertContains(respuesta, "Reorganización ficticia")
        self.assertContains(respuesta, "Farmacia → Farmacia central")
        self.assertContains(respuesta, "Sí → No")

    def test_filtros(self):
        from django.contrib.contenttypes.models import ContentType
        from django.utils import timezone

        hoy = timezone.localdate()
        ayer = hoy - timedelta(days=1)
        tipo_area = ContentType.objects.get_for_model(self.area)
        casos = [
            ({"accion": "area.modificada"}, {self.primero.pk}),
            ({"actor": self.otro_admin.pk}, {self.segundo.pk}),
            ({"tipo_objeto": tipo_area.pk, "objeto_id": str(self.area.pk)}, {self.primero.pk}),
            ({"q": "reorganización"}, {self.primero.pk}),
            ({"desde": hoy.isoformat()}, {self.primero.pk, self.segundo.pk}),
            ({"hasta": ayer.isoformat()}, set()),
        ]
        self.client.force_login(self.administrador)
        for filtros, esperado in casos:
            with self.subTest(filtros=filtros):
                self.assertEqual(self.ids(self.client.get(self.url, filtros)), esperado)

    def test_rango_de_fechas_invertido_muestra_error(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(self.url, {"desde": "2031-02-01", "hasta": "2031-01-01"})
        self.assertContains(respuesta, "La fecha final debe ser igual o posterior a la inicial.")
        self.assertEqual(self.ids(respuesta), set())

    def test_solo_administracion_consulta(self):
        for usuario in (self.coordinador, crear_usuario(Rol.PROVEEDOR, correo="prov-consulta@ejemplo.test")):
            with self.subTest(rol=usuario.rol):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.otro_admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_consultar_no_modifica_la_bitacora(self):
        self.client.force_login(self.administrador)
        self.client.get(self.url)
        self.assertEqual(RegistroBitacora.objects.count(), 2)
        self.assertEqual(self.client.post(self.url, {}).status_code, 405)

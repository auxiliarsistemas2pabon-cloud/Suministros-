from django.test import TestCase

from areas.models import Area
from bitacora.models import RegistroBitacora
from cuentas.models import Rol, Usuario
from cuentas.tests.utilidades import CLAVE, crear_area, crear_usuario

MOTIVO = "Solicitud de la coordinación, radicado ficticio 001"


class AdminTests(TestCase):
    def setUp(self):
        self.area = crear_area()
        self.superusuario = Usuario.objects.create_superuser(
            correo="raiz@ejemplo.test", password=CLAVE, nombre="Soporte"
        )

    def test_solo_desarrollador_superusuario_entra_al_admin(self):
        sin_acceso = [crear_usuario(rol) for rol in Rol.values] + [
            # Staff pero no superusuario: tampoco entra (evita permisos sueltos).
            crear_usuario(Rol.DESARROLLADOR, correo="staff@ejemplo.test", is_staff=True),
            # Superusuario desactivado.
            Usuario.objects.create_superuser(
                correo="inactivo@ejemplo.test", password=CLAVE, nombre="Inactivo", activo=False
            ),
        ]
        urls = ("/admin/", "/admin/cuentas/usuario/", "/admin/areas/area/", "/admin/bitacora/registrobitacora/")
        for usuario in sin_acceso:
            with self.subTest(usuario=usuario.correo):
                self.client.force_login(usuario)
                for url in urls:
                    respuesta = self.client.get(url)
                    self.assertEqual(respuesta.status_code, 302)
                    self.assertIn("/admin/login/", respuesta["Location"])
        self.client.force_login(self.superusuario)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_superusuario_ve_listados_y_formularios(self):
        self.client.force_login(self.superusuario)
        for url in (
            "/admin/cuentas/usuario/",
            "/admin/cuentas/usuario/add/",
            f"/admin/cuentas/usuario/{self.superusuario.pk}/change/",
            f"/admin/cuentas/usuario/{self.superusuario.pk}/password/",
            "/admin/areas/area/",
            "/admin/areas/area/add/",
            f"/admin/areas/area/{self.area.pk}/change/",
            "/admin/bitacora/registrobitacora/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_no_se_puede_borrar_usuarios_ni_areas(self):
        self.client.force_login(self.superusuario)
        otro = crear_usuario(Rol.ADMINISTRADOR)
        for url in (f"/admin/cuentas/usuario/{otro.pk}/delete/", f"/admin/areas/area/{self.area.pk}/delete/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertTrue(Usuario.objects.filter(pk=otro.pk).exists())
        self.assertTrue(Area.objects.filter(pk=self.area.pk).exists())


class AdminUsuarioBitacoraTests(TestCase):
    def setUp(self):
        self.area = crear_area()
        self.superusuario = Usuario.objects.create_superuser(
            correo="raiz@ejemplo.test", password=CLAVE, nombre="Soporte"
        )
        self.client.force_login(self.superusuario)

    def alta(self, **cambios):
        datos = {
            "correo": "Nuevo.Coordinador@Ejemplo.test",
            "nombre": "Nuevo Coordinador",
            "rol": Rol.COORDINADOR,
            "area": self.area.pk,
            "debe_cambiar_clave": "on",
            "password1": CLAVE,
            "password2": CLAVE,
            "motivo": MOTIVO,
        }
        datos.update(cambios)
        return self.client.post("/admin/cuentas/usuario/add/", {k: v for k, v in datos.items() if v is not None})

    def test_alta_de_coordinador_queda_en_bitacora(self):
        respuesta = self.alta()
        self.assertEqual(respuesta.status_code, 302)
        nuevo = Usuario.objects.get(correo="nuevo.coordinador@ejemplo.test")
        self.assertTrue(nuevo.check_password(CLAVE))
        self.assertEqual(nuevo.area, self.area)
        self.assertTrue(nuevo.debe_cambiar_clave)
        registro = RegistroBitacora.objects.get(accion="usuario.creado")
        self.assertEqual(registro.actor, self.superusuario)
        self.assertEqual(registro.actor_texto, "raiz@ejemplo.test")
        self.assertEqual(registro.motivo, MOTIVO)
        self.assertIsNone(registro.valor_anterior)
        self.assertEqual(registro.valor_nuevo["rol"], Rol.COORDINADOR)
        self.assertEqual(registro.valor_nuevo["area"], {"id": self.area.pk, "texto": str(self.area)})
        self.assertEqual(registro.ip, "127.0.0.1")

    def test_el_formulario_de_alta_propone_cambio_obligatorio_de_clave(self):
        respuesta = self.client.get("/admin/cuentas/usuario/add/")
        self.assertTrue(respuesta.context["adminform"].form.fields["debe_cambiar_clave"].initial)

    def test_alta_sin_motivo_rechazada(self):
        respuesta = self.alta(motivo="  ")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Indique el motivo del cambio")
        self.assertFalse(Usuario.objects.filter(correo="nuevo.coordinador@ejemplo.test").exists())
        self.assertFalse(RegistroBitacora.objects.exists())

    def test_alta_de_coordinador_sin_area_muestra_error(self):
        respuesta = self.alta(area=None)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Un coordinador debe tener un área asignada.")
        self.assertFalse(Usuario.objects.filter(correo="nuevo.coordinador@ejemplo.test").exists())

    def test_edicion_guarda_valores_anterior_y_nuevo_y_motivo(self):
        coordinador = crear_usuario(Rol.COORDINADOR, area=self.area)
        otra_area = crear_area(nombre="Laboratorio", codigo="LAB")
        respuesta = self.client.post(
            f"/admin/cuentas/usuario/{coordinador.pk}/change/",
            {
                "correo": "Coordinador@Ejemplo.test",
                "nombre": coordinador.nombre,
                "rol": Rol.COORDINADOR,
                "area": otra_area.pk,
                # "activo" sin marcar: se desactiva.
                "motivo": MOTIVO,
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        coordinador.refresh_from_db()
        self.assertEqual(coordinador.correo, "coordinador@ejemplo.test")
        self.assertEqual(coordinador.area, otra_area)
        self.assertFalse(coordinador.activo)
        registro = RegistroBitacora.objects.get(accion="usuario.modificado")
        self.assertEqual(
            registro.valor_anterior,
            {"area": {"id": self.area.pk, "texto": str(self.area)}, "activo": True},
        )
        self.assertEqual(
            registro.valor_nuevo,
            {"area": {"id": otra_area.pk, "texto": str(otra_area)}, "activo": False},
        )
        self.assertEqual(registro.motivo, MOTIVO)

    def test_edicion_sin_motivo_rechazada(self):
        coordinador = crear_usuario(Rol.COORDINADOR, area=self.area)
        respuesta = self.client.post(
            f"/admin/cuentas/usuario/{coordinador.pk}/change/",
            {"correo": coordinador.correo, "nombre": "Otro Nombre", "rol": Rol.COORDINADOR, "area": self.area.pk},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Indique el motivo del cambio")
        coordinador.refresh_from_db()
        self.assertTrue(coordinador.activo)
        self.assertFalse(RegistroBitacora.objects.exists())

    def test_guardar_sin_cambios_no_exige_motivo_ni_registra(self):
        coordinador = crear_usuario(Rol.COORDINADOR, area=self.area)
        respuesta = self.client.post(
            f"/admin/cuentas/usuario/{coordinador.pk}/change/",
            {
                "correo": coordinador.correo,
                "nombre": coordinador.nombre,
                "rol": Rol.COORDINADOR,
                "area": self.area.pk,
                "activo": "on",
            },
        )
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(RegistroBitacora.objects.exists())

    def test_editar_a_proveedor_con_area_muestra_error(self):
        coordinador = crear_usuario(Rol.COORDINADOR, area=self.area)
        respuesta = self.client.post(
            f"/admin/cuentas/usuario/{coordinador.pk}/change/",
            {
                "correo": coordinador.correo,
                "nombre": "X",
                "rol": Rol.PROVEEDOR,
                "area": self.area.pk,
                "activo": "on",
                "motivo": MOTIVO,
            },
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Un proveedor no puede tener área.")
        coordinador.refresh_from_db()
        self.assertEqual(coordinador.rol, Rol.COORDINADOR)
        self.assertFalse(RegistroBitacora.objects.exists())

    def test_asignar_clave_obliga_a_cambiarla_y_queda_en_bitacora(self):
        usuario = crear_usuario(Rol.ADMINISTRADOR)
        nueva = "Otra-Clave-Ficticia-77"
        url = f"/admin/cuentas/usuario/{usuario.pk}/password/"
        datos = {"password1": nueva, "password2": nueva, "usable_password": "true"}

        sin_motivo = self.client.post(url, datos)
        self.assertEqual(sin_motivo.status_code, 200)
        self.assertContains(sin_motivo, "Indique el motivo del cambio")
        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password(CLAVE))

        respuesta = self.client.post(url, {**datos, "motivo": "Olvidó su clave"})
        self.assertEqual(respuesta.status_code, 302)
        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password(nueva))
        self.assertTrue(usuario.debe_cambiar_clave)
        registro = RegistroBitacora.objects.get(accion="cuenta.clave_asignada")
        self.assertEqual(registro.actor, self.superusuario)
        self.assertEqual(registro.motivo, "Olvidó su clave")
        self.assertEqual(registro.valor_nuevo, {"debe_cambiar_clave": True, "clave_habilitada": True})

    def test_deshabilitar_clave_queda_en_bitacora_sin_obligar_cambio(self):
        usuario = crear_usuario(Rol.ADMINISTRADOR)
        respuesta = self.client.post(
            f"/admin/cuentas/usuario/{usuario.pk}/password/",
            {"usable_password": "false", "unset-password": "1", "motivo": "Retiro de la clínica"},
        )
        self.assertEqual(respuesta.status_code, 302)
        usuario.refresh_from_db()
        self.assertFalse(usuario.has_usable_password())
        self.assertFalse(usuario.debe_cambiar_clave)
        registro = RegistroBitacora.objects.get(accion="cuenta.clave_deshabilitada")
        self.assertEqual(registro.motivo, "Retiro de la clínica")

    def test_si_la_bitacora_falla_la_clave_no_cambia(self):
        from unittest import mock

        usuario = crear_usuario(Rol.ADMINISTRADOR)
        nueva = "Otra-Clave-Ficticia-77"
        with mock.patch("cuentas.servicios.registrar", side_effect=RuntimeError("falla simulada")):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    f"/admin/cuentas/usuario/{usuario.pk}/password/",
                    {"password1": nueva, "password2": nueva, "usable_password": "true", "motivo": "x"},
                )
        usuario.refresh_from_db()
        self.assertTrue(usuario.check_password(CLAVE))


class AdminAreaBitacoraTests(TestCase):
    def setUp(self):
        self.superusuario = Usuario.objects.create_superuser(
            correo="raiz@ejemplo.test", password=CLAVE, nombre="Soporte"
        )
        self.client.force_login(self.superusuario)

    def test_alta_y_desactivacion_de_area_quedan_en_bitacora(self):
        respuesta = self.client.post(
            "/admin/areas/area/add/",
            {"nombre": "Urgencias", "codigo_area": "urg", "activa": "on", "motivo": "Nueva área"},
        )
        self.assertEqual(respuesta.status_code, 302)
        area = Area.objects.get(codigo_area="URG")
        creado = RegistroBitacora.objects.get(accion="area.creada")
        self.assertEqual(creado.valor_nuevo, {"nombre": "Urgencias", "codigo_area": "URG", "activa": True})

        respuesta = self.client.post(
            f"/admin/areas/area/{area.pk}/change/",
            {"nombre": "Urgencias", "codigo_area": "URG", "motivo": "Cierre temporal"},
        )
        self.assertEqual(respuesta.status_code, 302)
        area.refresh_from_db()
        self.assertFalse(area.activa)
        modificado = RegistroBitacora.objects.get(accion="area.modificada")
        self.assertEqual(modificado.valor_anterior, {"activa": True})
        self.assertEqual(modificado.valor_nuevo, {"activa": False})
        self.assertEqual(modificado.motivo, "Cierre temporal")

    def test_admin_tambien_bloquea_desactivar_area_con_coordinadores_activos(self):
        area = crear_area(nombre="Urgencias", codigo="URG")
        crear_usuario(Rol.COORDINADOR, area=area)
        respuesta = self.client.post(
            f"/admin/areas/area/{area.pk}/change/",
            {"nombre": "Urgencias", "codigo_area": "URG", "motivo": "Cierre"},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Reasígnelos a otra área o desactívelos primero")
        area.refresh_from_db()
        self.assertTrue(area.activa)

    def test_area_sin_motivo_rechazada(self):
        respuesta = self.client.post("/admin/areas/area/add/", {"nombre": "Urgencias", "codigo_area": "URG"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Indique el motivo del cambio")
        self.assertFalse(Area.objects.exists())

    def test_bitacora_en_admin_es_solo_lectura(self):
        registro = RegistroBitacora.objects.create(accion="prueba.lectura", motivo="x")
        self.assertEqual(self.client.get("/admin/bitacora/registrobitacora/add/").status_code, 403)
        self.assertEqual(
            self.client.get(f"/admin/bitacora/registrobitacora/{registro.pk}/delete/").status_code, 403
        )
        respuesta = self.client.post(
            f"/admin/bitacora/registrobitacora/{registro.pk}/change/", {"accion": "alterada"}
        )
        self.assertEqual(respuesta.status_code, 403)
        registro.refresh_from_db()
        self.assertEqual(registro.accion, "prueba.lectura")
